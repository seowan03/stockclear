import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
import app.routers.upload as upload_router
from app.main import app
from app.database import Base
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
            RawInventory(item_id=1, user_id=7, product_name="Widget A", stock_qty=4, is_deleted=False),
            RawInventory(item_id=2, user_id=7, product_name="Widget B", stock_qty=8, is_deleted=False),
            RawInventory(item_id=3, user_id=7, product_name="Widget C", stock_qty=2, is_deleted=False),
            RawInventory(item_id=4, user_id=7, product_name="Deleted", stock_qty=99, is_deleted=True),
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


class UploadSummaryRetryApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_factory = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
        )

    def tearDown(self):
        self.engine.dispose()

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


if __name__ == "__main__":
    unittest.main()