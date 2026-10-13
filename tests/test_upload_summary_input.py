import csv
import io
import json
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
import app.routers.upload as upload_router
from app.main import app
from app.database import Base
from app.llm import LLMFailure, get_upload_diagnosis_summary
from app.models import AnalysisResult, RawInventory, UploadAnalysisSummary, UploadHistory
from app.services.inventory_service import make_user_summary_input


class UploadSummaryInputTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_summary_uses_active_account_items_and_exposes_quality_context(self):
        timestamp = datetime(2026, 10, 7, 12, 30)
        self.db.add_all([
            RawInventory(item_id=1, user_id=7, upload_batch_id="batch-1", product_name="Widget A", stock_qty=4, purchase_price=100, market_price=150, inbound_date=date(2026, 1, 1), is_deleted=False),
            RawInventory(item_id=2, user_id=7, upload_batch_id="batch-1", product_name="Widget B", stock_qty=8, purchase_price=100, market_price=150, inbound_date=date(2026, 1, 1), is_deleted=False),
            RawInventory(item_id=3, user_id=7, upload_batch_id="batch-1", product_name="Widget C", stock_qty=2, purchase_price=100, market_price=150, inbound_date=date(2026, 1, 1), is_deleted=False),
            RawInventory(item_id=4, user_id=7, upload_batch_id="batch-1", product_name="Deleted", stock_qty=99, purchase_price=100, market_price=150, inbound_date=date(2026, 1, 1), is_deleted=True),
            AnalysisResult(
                item_id=1, risk_grade="악성", final_score=88.8, aging_days=91,
                days_to_sell=120, inventory_amount=400, fluctuation_rate=12.5,
                updated_at=timestamp,
            ),
            AnalysisResult(
                item_id=2, risk_grade="정상", final_score=10, inventory_amount=800,
                updated_at=timestamp,
            ),
        ])
        self.db.commit()

        summary = make_user_summary_input(self.db, 7)

        self.assertEqual(summary["scope"], "account_active_inventory")
        self.assertEqual(summary["overview"]["total_count"], 3)
        self.assertEqual(summary["overview"]["inventory_value_cost_basis"], 1200)
        self.assertEqual(summary["overview"]["risk_grade_counts"]["미분류"], 1)
        self.assertEqual(summary["overview"]["risk_grade_share_percent"]["악성"], 33.3)
        self.assertEqual(summary["overview"]["unclassified_count"], 1)
        self.assertEqual(summary["data_as_of"], timestamp.isoformat())
        self.assertEqual(summary["priority_items"][0]["product_name"], "Widget A")
        self.assertEqual(summary["priority_items"][0]["item_id"], 1)
        self.assertEqual(summary["priority_items"][0]["stock_qty"], 4)
        self.assertTrue(summary["data_quality"]["daily_sales_is_demo"])
        self.assertFalse(summary["data_quality"]["actual_order_history_available"])
        self.assertFalse(summary["data_quality"]["actual_lead_time_available"])
        self.assertEqual(summary["total_count"], 3)

    def test_empty_inventory_has_null_grade_shares(self):
        summary = make_user_summary_input(self.db, 7)

        self.assertEqual(summary["overview"]["total_count"], 0)
        self.assertTrue(all(
            share is None
            for share in summary["overview"]["risk_grade_share_percent"].values()
        ))
        self.assertEqual(summary["priority_items"], [])


class UploadSummaryValidationLogTests(unittest.TestCase):
    def test_summary_failure_messages_explain_user_action_without_codes(self):
        cases = {
            "user_concurrency_limit": "기다린 뒤 다시 시도",
            "global_concurrency_limit": "잠시 후 다시 시도",
            "timeout": "응답 시간이 초과",
            "evidence_validation_error": "근거를 확인하지 못했습니다",
        }
        for failure_code, expected_message in cases.items():
            with self.subTest(failure_code=failure_code):
                message = upload_router._summary_failure_message(failure_code)
                self.assertIn(expected_message, message)
                self.assertNotIn(failure_code, message)

    def test_analysis_schema_describes_qualitative_only_output(self):
        from app.llm import UploadDiagnosisSummary

        schema = UploadDiagnosisSummary.model_json_schema()
        overview_description = schema["$defs"]["UploadSummaryOverview"]["properties"]["analysis"]["description"]
        item_description = schema["$defs"]["UploadSummaryPriorityItem"]["properties"]["analysis"]["description"]

        self.assertIn("숫자", overview_description)
        self.assertIn("한글 수량·배수 표현", overview_description)
        self.assertIn("숫자", item_description)
        self.assertIn("한글 수량·배수 표현", item_description)

    def test_schema_failure_logs_field_and_type_without_response_text(self):
        payload = {
            "overview": {
                "analysis": 99,
                "evidence_refs": ["overview.total_count"],
            },
            "priority_items": [],
        }
        response = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
        )])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_kwargs: response,
        )))
        summary_data = {
            "overview": {"total_count": 3},
            "priority_items": [],
            "data_quality": {},
        }

        with (
            patch("app.llm._get_client", return_value=client),
            self.assertLogs("app.llm", level="WARNING") as captured_logs,
        ):
            with self.assertRaises(LLMFailure) as failure:
                get_upload_diagnosis_summary(summary_data)

        self.assertEqual(failure.exception.failure_code, "schema_validation_error")
        log_message = "\n".join(captured_logs.output)
        self.assertIn("overview.analysis:string_type", log_message)
        self.assertNotIn("99", log_message)

    def test_evidence_failure_logs_safe_validation_reason(self):
        payload = {
            "overview": {
                "analysis": "재고 현황을 확인할 필요가 있습니다.",
                "evidence_refs": ["overview.unavailable_metric"],
            },
            "priority_items": [],
        }
        response = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
        )])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_kwargs: response,
        )))
        summary_data = {
            "overview": {"total_count": 3},
            "priority_items": [],
            "data_quality": {},
        }

        with (
            patch("app.llm._get_client", return_value=client),
            self.assertLogs("app.llm", level="WARNING") as captured_logs,
        ):
            with self.assertRaises(LLMFailure) as failure:
                get_upload_diagnosis_summary(summary_data)

        self.assertEqual(failure.exception.failure_code, "evidence_validation_error")
        self.assertIn("AI 종합진단이 입력에 없는 근거를 참조했습니다.", "\n".join(captured_logs.output))
        self.assertNotIn("overview.unavailable_metric", "\n".join(captured_logs.output))

    def test_numeric_priority_analyses_fall_back_without_failing_summary(self):
        items = [
            {
                "item_id": item_id,
                "product_name": f"Stock Item {item_id}",
                "risk_grade": "악성",
                "risk_score": 80 + item_id,
            }
            for item_id in range(1, 6)
        ]
        payload = {
            "overview": {
                "analysis": "우선 확인 품목을 점검할 필요가 있습니다.",
                "evidence_refs": ["overview.total_count"],
            },
            "priority_items": [
                {
                    "item_id": item["item_id"],
                    "analysis": f"위험점수 {item['risk_score']}점으로 확인이 필요합니다.",
                    "evidence_refs": [f"item.{item['item_id']}.risk_score"],
                }
                for item in items
            ],
        }
        response = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
        )])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_kwargs: response,
        )))
        summary_data = {
            "overview": {"total_count": len(items)},
            "priority_items": items,
            "data_quality": {},
        }

        with (
            patch("app.llm._get_client", return_value=client),
            self.assertLogs("app.llm", level="WARNING") as captured_logs,
        ):
            summary = get_upload_diagnosis_summary(summary_data)

        self.assertIn("일부 AI 설명 문장은 기준 검증을 통과하지 않아 시스템 안내로 대체했습니다.", summary)
        self.assertEqual(summary.count("서버 계산 위험점수 기준으로 악성 등급으로 분류됐습니다."), 5)
        self.assertNotIn("서버 분석 기준으로 해당 품목의 재고 상태를 우선 확인하세요.", summary)
        self.assertNotIn("확인할 점:", summary)
        self.assertNotIn("위험점수 81점으로 확인이 필요합니다.", summary)
        self.assertIn("priority_items.0.analysis", "\n".join(captured_logs.output))

    def test_invalid_summary_narrative_is_retried_before_fallback(self):
        payloads = [
            {
                "overview": {
                    "analysis": "전체 재고 현황을 확인할 필요가 있습니다.",
                    "evidence_refs": ["overview.total_count"],
                },
                "priority_items": [{
                    "item_id": 1,
                    "analysis": "위험점수 80점으로 우선 확인이 필요합니다.",
                    "evidence_refs": ["item.1.risk_score"],
                }],
            },
            {
                "overview": {
                    "analysis": "전체 재고 현황을 우선 살펴볼 필요가 있습니다.",
                    "evidence_refs": ["overview.total_count"],
                },
                "priority_items": [{
                    "item_id": 1,
                    "analysis": "장기 재고 상태라 우선 관리가 필요합니다.",
                    "evidence_refs": ["item.1.risk_score"],
                }],
            },
        ]
        responses = [
            SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
            )])
            for payload in payloads
        ]
        calls = []

        def create_response(**kwargs):
            calls.append(kwargs)
            return responses[len(calls) - 1]

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=create_response,
        )))
        summary_data = {
            "overview": {"total_count": 1},
            "priority_items": [{
                "item_id": 1,
                "product_name": "Smart Watch",
                "risk_grade": "장기",
                "risk_score": 80,
            }],
            "data_quality": {},
        }

        with patch("app.llm._get_client", return_value=client):
            summary = get_upload_diagnosis_summary(summary_data)

        self.assertEqual(len(calls), 2)
        self.assertIn("장기 재고 상태라 우선 관리가 필요합니다.", summary)
        self.assertNotIn("시스템 안내로 대체했습니다.", summary)

    def test_unsupported_sales_trend_falls_back_without_failing_summary(self):
        payload = {
            "overview": {
                "analysis": "전체 재고 상태를 확인할 필요가 있습니다.",
                "evidence_refs": ["overview.total_count"],
            },
            "priority_items": [{
                "item_id": 1,
                "analysis": "판매량이 증가 추세를 보입니다.",
                "evidence_refs": ["item.1.risk_score"],
            }],
        }
        response = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
        )])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_kwargs: response,
        )))
        summary_data = {
            "overview": {"total_count": 1},
            "priority_items": [{
                "item_id": 1,
                "product_name": "Stock Item",
                "risk_grade": "장기",
                "risk_score": 61,
                "storage_days": 60,
                "days_to_sell": 60,
                "depreciation_rate": 40,
            }],
            "data_quality": {"actual_order_history_available": False},
        }

        with (
            patch("app.llm._get_client", return_value=client),
            self.assertLogs("app.llm", level="WARNING") as captured_logs,
        ):
            summary = get_upload_diagnosis_summary(summary_data)

        self.assertIn("일부 AI 설명 문장은 기준 검증을 통과하지 않아 시스템 안내로 대체했습니다.", summary)
        self.assertIn(
            "보관 기간·원가 대비 판매가 차이 지표가 위험점수에 반영되어 장기 등급으로 분류됐습니다.",
            summary,
        )
        self.assertNotIn("판매량이 증가 추세", summary)
        self.assertNotIn("서버 분석 기준으로 해당 품목의 재고 상태를 우선 확인하세요.", summary)
        self.assertIn("priority_items.0.analysis", "\n".join(captured_logs.output))

    def test_product_names_are_allowed_in_ai_narratives(self):
        items = [
            {"item_id": 1, "product_name": "Red Chair", "risk_grade": "악성", "risk_score": 82},
            {"item_id": 2, "product_name": "Blue Table", "risk_grade": "장기", "risk_score": 64},
        ]
        payload = {
            "overview": {
                "analysis": "Red Chair와 Blue Table의 재고 상태를 확인해야 합니다.",
                "evidence_refs": ["overview.total_count"],
            },
            "priority_items": [
                {
                    "item_id": item["item_id"],
                    "analysis": f"{item['product_name']}의 재고 상태를 확인할 필요가 있습니다.",
                    "evidence_refs": [f"item.{item['item_id']}.risk_score"],
                }
                for item in items
            ],
        }
        response = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
        )])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_kwargs: response,
        )))
        summary_data = {
            "overview": {"total_count": 2},
            "priority_items": items,
            "data_quality": {"actual_order_history_available": False},
        }

        with patch("app.llm._get_client", return_value=client):
            summary = get_upload_diagnosis_summary(summary_data)

        self.assertIn("Red Chair · 악성", summary)
        self.assertIn("Blue Table · 장기", summary)
        self.assertIn("Red Chair와 Blue Table의 재고 상태를 확인해야 합니다.", summary)
        self.assertIn("Red Chair의 재고 상태를 확인할 필요가 있습니다.", summary)
        self.assertIn("Blue Table의 재고 상태를 확인할 필요가 있습니다.", summary)


class UploadSummaryRetryApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
        )

    def tearDown(self):
        self.engine.dispose()

    def _csv_file(self):
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(["상품명", "재고량", "원가", "입고일", "판매가", "판매량"])
        writer.writerow(["Deadlock Retry Item", 10, 100, "2026-09-01", 150, 4])
        return buffer.getvalue().encode("utf-8-sig")

    def test_mysql_deadlock_retries_upload_transaction_once(self):
        original_save = upload_router.save_inventory_analysis
        call_count = 0

        def fail_once_then_save(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OperationalError("INSERT inventory_daily_metrics", {}, Exception(1213, "deadlock"))
            return original_save(*args, **kwargs)

        with (
            patch.object(database, "engine", self.engine),
            patch.object(database, "SessionLocal", self.session_factory),
            patch.object(upload_router, "save_inventory_analysis", side_effect=fail_once_then_save),
            patch.object(upload_router, "UPLOAD_DB_RETRY_DELAY_SECONDS", 0),
            patch.object(upload_router, "get_upload_diagnosis_summary", return_value="업로드 요약"),
            TestClient(app) as client,
        ):
            signup = client.post("/api/auth/signup", json={
                "username": "Deadlock Retry User",
                "email": "deadlock-retry@example.test",
                "password": "test-password",
            })
            self.assertEqual(signup.status_code, 200, signup.text)

            upload = client.post(
                "/api/upload",
                files={"file": ("deadlock.csv", self._csv_file(), "text/csv")},
            )

            self.assertEqual(upload.status_code, 200, upload.text)
            self.assertEqual(upload.json()["ai_summary_status"], "complete")
            self.assertEqual(call_count, 2)
            with self.session_factory() as db:
                self.assertEqual(db.query(UploadHistory).filter_by(user_id=signup.json()["user_id"]).count(), 1)
                self.assertEqual(db.query(RawInventory).filter_by(user_id=signup.json()["user_id"]).count(), 1)

    def test_failed_summary_can_be_retried_and_is_account_scoped(self):
        with (
            patch.object(database, "engine", self.engine),
            patch.object(database, "SessionLocal", self.session_factory),
            patch.object(upload_router, "get_upload_diagnosis_summary", return_value="재생성된 진단"),
            TestClient(app) as client,
        ):
            signup = client.post("/api/auth/signup", json={
                "username": "Retry User",
                "email": "retry-summary@example.test",
                "password": "test-password",
            })
            self.assertEqual(signup.status_code, 200, signup.text)

            with self.session_factory() as db:
                history = UploadHistory(
                    user_id=signup.json()["user_id"],
                    file_name="failed.csv",
                    size=100,
                    status="성공",
                    content_hash="retry-summary-hash",
                )
                db.add(history)
                db.flush()
                upload_id = history.id
                db.add(UploadAnalysisSummary(
                    upload_id=upload_id,
                    user_id=history.user_id,
                    status="failed",
                    summary_text=None,
                    summary_data=None,
                ))
                db.commit()

            response = client.post(f"/api/upload/{upload_id}/summary/retry")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "complete")
            with self.session_factory() as db:
                saved_summary = db.query(UploadAnalysisSummary).filter_by(upload_id=upload_id).one()
                self.assertEqual(saved_summary.status, "complete")
                self.assertEqual(saved_summary.summary_text, "재생성된 진단")

            repeated_retry = client.post(f"/api/upload/{upload_id}/summary/retry")
            self.assertEqual(repeated_retry.status_code, 409)
            report = client.get("/api/export")
            self.assertEqual(report.json()["summary"]["summary_upload_id"], upload_id)

            client.post("/api/auth/logout")
            other_signup = client.post("/api/auth/signup", json={
                "username": "Other Retry User",
                "email": "other-retry-summary@example.test",
                "password": "test-password",
            })
            self.assertEqual(other_signup.status_code, 200, other_signup.text)
            foreign_retry = client.post(f"/api/upload/{upload_id}/summary/retry")
            self.assertEqual(foreign_retry.status_code, 404)

    def test_existing_upload_without_summary_can_generate_one(self):
        with (
            patch.object(database, "engine", self.engine),
            patch.object(database, "SessionLocal", self.session_factory),
            patch.object(upload_router, "get_upload_diagnosis_summary", return_value="기존 업로드 요약"),
            TestClient(app) as client,
        ):
            signup = client.post("/api/auth/signup", json={
                "username": "Legacy Upload User",
                "email": "legacy-upload-summary@example.test",
                "password": "test-password",
            })
            self.assertEqual(signup.status_code, 200, signup.text)

            with self.session_factory() as db:
                history = UploadHistory(
                    user_id=signup.json()["user_id"],
                    file_name="existing.csv",
                    size=100,
                    status="성공",
                    content_hash="existing-upload-hash",
                )
                db.add(history)
                db.commit()
                upload_id = history.id

            report = client.get(f"/api/export?upload_id={upload_id}").json()
            self.assertEqual(report["summary"]["ai_summary_status"], "unavailable")
            self.assertEqual(report["summary"]["summary_upload_id"], upload_id)

            generated = client.post(f"/api/upload/{upload_id}/summary/retry")
            self.assertEqual(generated.status_code, 200, generated.text)
            self.assertEqual(generated.json()["status"], "complete")

            report = client.get(f"/api/export?upload_id={upload_id}").json()
            self.assertEqual(report["summary"]["ai_summary_status"], "complete")
            self.assertEqual(report["summary"]["ai_summary"], "기존 업로드 요약")


if __name__ == "__main__":
    unittest.main()