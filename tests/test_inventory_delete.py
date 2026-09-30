import csv
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
import app.routers.upload as upload_router
from app.main import app
from app.models import AnalysisResult, InventoryDailyMetric, RawInventory
from app.services.upload_service import REQUIRED_COLUMNS


class InventoryDeleteTests(unittest.TestCase):
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

    def _upload_csv(self, client):
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(REQUIRED_COLUMNS)
        writer.writerow(["Delete Test Item", 3, 100, "2026-01-01", 150, 1])
        return client.post(
            "/api/upload",
            files={"file": ("delete-test.csv", buffer.getvalue().encode("utf-8-sig"), "text/csv")},
        )

    def test_delete_permanently_removes_inventory_and_analysis(self):
        with (
            patch.object(database, "engine", self.engine),
            patch.object(database, "SessionLocal", self.session_factory),
            patch.object(upload_router, "get_upload_diagnosis_summary", return_value="test summary"),
            TestClient(app) as client,
        ):
            signup = client.post("/api/auth/signup", json={
                "username": "Owner",
                "email": "delete-owner@example.test",
                "password": "test-password",
            })
            self.assertEqual(signup.status_code, 200, signup.text)
            upload = self._upload_csv(client)
            self.assertEqual(upload.status_code, 200, upload.text)
            item_id = client.get("/api/inventory").json()["items"][0]["item_id"]

            client.post("/api/auth/logout")
            other_signup = client.post("/api/auth/signup", json={
                "username": "Other",
                "email": "delete-other@example.test",
                "password": "test-password",
            })
            self.assertEqual(other_signup.status_code, 200, other_signup.text)
            self.assertEqual(client.delete(f"/api/inventory/{item_id}").status_code, 404)

            client.post("/api/auth/logout")
            owner_login = client.post("/api/auth/login", json={
                "email": "delete-owner@example.test",
                "password": "test-password",
            })
            self.assertEqual(owner_login.status_code, 200, owner_login.text)
            delete_response = client.delete(f"/api/inventory/{item_id}")
            self.assertEqual(delete_response.status_code, 200, delete_response.text)
            self.assertEqual(client.get("/api/inventory").json()["items"], [])
            self.assertEqual(client.get("/api/export").json()["summary"]["ai_summary_status"], "stale")

            with self.session_factory() as db:
                self.assertIsNone(db.get(RawInventory, item_id))
                self.assertEqual(db.query(AnalysisResult).filter_by(item_id=item_id).count(), 0)
                self.assertEqual(db.query(InventoryDailyMetric).filter_by(item_id=item_id).count(), 0)

            api_paths = client.get("/openapi.json").json()["paths"]
            self.assertNotIn("/api/inventory/trash", api_paths)
            self.assertNotIn("/api/inventory/{item_id}/restore", api_paths)
            self.assertNotIn("/api/inventory/{item_id}/permanent", api_paths)
            self.assertNotIn("/api/inventory/trash/empty", api_paths)

    def test_inventory_page_has_no_trash_controls_or_calls(self):
        page_path = Path(__file__).resolve().parents[1] / "static" / "inventory.html"
        source = page_path.read_text(encoding="utf-8")
        for removed_reference in (
            "trashModal",
            "trashCount",
            "loadTrashData",
            "openTrashModal",
            "restoreItem",
            "emptyTrashAll",
            "/api/inventory/trash",
        ):
            with self.subTest(reference=removed_reference):
                self.assertNotIn(removed_reference, source)
        self.assertIn("deleteInventoryItem", source)
        self.assertIn("되돌릴 수 없습니다", source)


if __name__ == "__main__":
    unittest.main()