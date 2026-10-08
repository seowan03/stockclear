import csv
import io
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
import app.routers.upload as upload_router
from app.main import app
from app.services.upload_service import REQUIRED_COLUMNS


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

    def _csv_file(self):
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(REQUIRED_COLUMNS)
        writer.writerow(["Retry Item", 10, 100, "2026-09-01", 150, 4])
        return buffer.getvalue().encode("utf-8-sig")

    def test_failed_summary_can_be_retried_only_by_its_owner(self):
        with (
            patch.object(database, "engine", self.engine),
            patch.object(database, "SessionLocal", self.session_factory),
            patch.object(
                upload_router,
                "get_upload_diagnosis_summary",
                side_effect=[RuntimeError("temporary AI failure"), "재생성된 종합진단"],
            ),
            TestClient(app) as client,
        ):
            signup = client.post("/api/auth/signup", json={
                "username": "Summary Retry User",
                "email": "summary-retry@example.test",
                "password": "test-password",
            })
            self.assertEqual(signup.status_code, 200, signup.text)

            upload = client.post(
                "/api/upload",
                files={"file": ("retry.csv", self._csv_file(), "text/csv")},
            )
            self.assertEqual(upload.status_code, 200, upload.text)
            self.assertEqual(upload.json()["ai_summary_status"], "failed")
            upload_id = upload.json()["history_id"]

            export = client.get("/api/export").json()
            self.assertEqual(export["summary"]["ai_summary_status"], "failed")
            self.assertEqual(export["summary"]["summary_upload_id"], upload_id)

            retry = client.post(f"/api/upload/{upload_id}/summary/retry")
            self.assertEqual(retry.status_code, 200, retry.text)
            self.assertEqual(retry.json()["status"], "complete")
            regenerated = client.get("/api/export").json()["summary"]
            self.assertEqual(regenerated["ai_summary_status"], "complete")
            self.assertEqual(regenerated["ai_summary"], "재생성된 종합진단")

            duplicate_retry = client.post(f"/api/upload/{upload_id}/summary/retry")
            self.assertEqual(duplicate_retry.status_code, 409, duplicate_retry.text)

            client.post("/api/auth/logout")
            other_signup = client.post("/api/auth/signup", json={
                "username": "Other Summary User",
                "email": "other-summary@example.test",
                "password": "test-password",
            })
            self.assertEqual(other_signup.status_code, 200, other_signup.text)
            foreign_retry = client.post(f"/api/upload/{upload_id}/summary/retry")
            self.assertEqual(foreign_retry.status_code, 404, foreign_retry.text)


if __name__ == "__main__":
    unittest.main()
