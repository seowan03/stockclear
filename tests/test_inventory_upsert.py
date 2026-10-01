import csv
import io
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
import app.routers.upload as upload_router
from app.main import app
from app.services.upload_service import REQUIRED_COLUMNS


class InventoryUpsertApiTests(unittest.TestCase):
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

    def _csv_file(self, rows):
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(REQUIRED_COLUMNS)
        writer.writerows(rows)
        return buffer.getvalue().encode("utf-8-sig")

    def _upload(self, client, name, rows):
        return client.post(
            "/api/upload",
            files={"file": (name, self._csv_file(rows), "text/csv")},
        )

    def _xlsx_file(self, rows):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(REQUIRED_COLUMNS)
        for row in rows:
            sheet.append(row)
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def test_trimmed_product_name_upsert_updates_date_and_is_user_scoped(self):
        with (
            patch.object(database, "engine", self.engine),
            patch.object(database, "SessionLocal", self.session_factory),
            patch.object(upload_router, "get_upload_diagnosis_summary", return_value="test summary"),
            TestClient(app) as client,
        ):
            signup = client.post("/api/auth/signup", json={
                "username": "First User",
                "email": "first-upsert@example.test",
                "password": "test-password",
            })
            self.assertEqual(signup.status_code, 200, signup.text)

            first_rows = [["  Widget  ", 4, 100, "2026-01-01", 150, 0]]
            first_upload = self._upload(client, "first.csv", first_rows)
            self.assertEqual(first_upload.status_code, 200, first_upload.text)
            self.assertEqual(first_upload.json()["data_preview"][0]["product_name"], "Widget")

            first_item = client.get("/api/inventory").json()["items"][0]
            original_item_id = first_item["item_id"]
            original_score = first_item["final_score"]

            identical_upload = self._upload(client, "same-data.csv", first_rows)
            self.assertEqual(identical_upload.status_code, 409)

            updated_upload = self._upload(
                client,
                "updated.csv",
                [["Widget ", 12, 100, "2026-02-01", 150, 50]],
            )
            self.assertEqual(updated_upload.status_code, 200, updated_upload.text)

            updated_items = client.get("/api/inventory").json()["items"]
            self.assertEqual(len(updated_items), 1)
            updated_item = updated_items[0]
            self.assertEqual(updated_item["item_id"], original_item_id)
            self.assertEqual(updated_item["product_name"], "Widget")
            self.assertEqual(updated_item["received_date"], "2026-02-01")
            self.assertEqual(updated_item["stock_qty"], 12)
            self.assertEqual(updated_item["sales_qty"], 50)
            self.assertEqual(updated_item["inventory_value"], 1200)
            self.assertNotEqual(updated_item["final_score"], original_score)

            client.post("/api/auth/logout")
            second_signup = client.post("/api/auth/signup", json={
                "username": "Second User",
                "email": "second-upsert@example.test",
                "password": "test-password",
            })
            self.assertEqual(second_signup.status_code, 200, second_signup.text)
            other_user_upload = self._upload(
                client,
                "other-user.csv",
                [["Widget", 7, 100, "2026-01-01", 150, 10]],
            )
            self.assertEqual(other_user_upload.status_code, 200, other_user_upload.text)

            client.post("/api/auth/logout")
            first_login = client.post("/api/auth/login", json={
                "email": "first-upsert@example.test",
                "password": "test-password",
            })
            self.assertEqual(first_login.status_code, 200, first_login.text)
            first_user_items = client.get("/api/inventory").json()["items"]
            self.assertEqual(len(first_user_items), 1)
            self.assertEqual(first_user_items[0]["stock_qty"], 12)

    def test_future_inbound_date_is_rejected_for_csv_and_xlsx(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        with (
            patch.object(database, "engine", self.engine),
            patch.object(database, "SessionLocal", self.session_factory),
            patch.object(upload_router, "get_upload_diagnosis_summary", return_value="test summary"),
            TestClient(app) as client,
        ):
            signup = client.post("/api/auth/signup", json={
                "username": "Date Test",
                "email": "future-date@example.test",
                "password": "test-password",
            })
            self.assertEqual(signup.status_code, 200, signup.text)

            csv_response = self._upload(
                client,
                "future-date.csv",
                [["Future CSV", 1, 100, tomorrow, 150, 1]],
            )
            xlsx_response = client.post(
                "/api/upload",
                files={
                    "file": (
                        "future-date.xlsx",
                        self._xlsx_file([["Future XLSX", 1, 100, tomorrow, 150, 1]]),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

            for response in (csv_response, xlsx_response):
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn("[입고일]", response.json()["detail"])
                self.assertIn("미래", response.json()["detail"])

            self.assertEqual(client.get("/api/inventory").json()["items"], [])


if __name__ == "__main__":
    unittest.main()