import csv
import io
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
import app.routers.upload as upload_router
import app.services.inventory_service as inventory_service
from app.main import app
from app.services.upload_service import REQUIRED_COLUMNS
from app.models import InventoryDailyMetric, RawInventory, UploadAnalysisSummary


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

    def test_existing_inventory_table_gets_edit_columns(self):
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE raw_inventory (item_id INTEGER PRIMARY KEY, user_id INTEGER)"))
            connection.execute(text("INSERT INTO raw_inventory (item_id, user_id) VALUES (1, 9)"))
        with patch.object(database, "engine", self.engine):
            database.ensure_raw_inventory_edit_columns()
            database.ensure_raw_inventory_edit_columns()
        columns = {column["name"] for column in inspect(self.engine).get_columns("raw_inventory")}
        self.assertIn("version", columns)
        self.assertIn("edited_at", columns)
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT version, edited_at FROM raw_inventory WHERE item_id = 1")).one()
            self.assertEqual(row.version, 1)
            self.assertIsNone(row.edited_at)

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

    def test_grid_batch_edit_recomputes_rows_and_rejects_conflicts_atomically(self):
        with (
            patch.object(database, "engine", self.engine),
            patch.object(database, "SessionLocal", self.session_factory),
            patch.object(upload_router, "get_upload_diagnosis_summary", return_value="test summary"),
            TestClient(app) as client,
        ):
            signup = client.post("/api/auth/signup", json={
                "username": "Grid User", "email": "grid@example.test", "password": "test-password",
            })
            self.assertEqual(signup.status_code, 200, signup.text)
            upload = self._upload(client, "one.csv", [
                ["Alpha", 4, 100, "2026-01-01", 150, 1],
                ["Beta", 5, 200, "2026-01-01", 250, 2],
            ])
            self.assertEqual(upload.status_code, 200, upload.text)
            original = {item["product_name"]: item for item in client.get("/api/inventory").json()["items"]}

            def edit(item, **changes):
                return {
                    "item_id": item["item_id"], "version": item["version"],
                    "product_name": item["product_name"], "stock_qty": item["stock_qty"],
                    "purchase_price": item["purchase_price"], "received_date": item["received_date"],
                    "selling_price": item["selling_price"], "sales_qty": item["sales_qty"],
                    **changes,
                }

            changes = [
                edit(original["Alpha"], product_name="Alpha renamed", stock_qty=10, selling_price=300),
                edit(original["Beta"], stock_qty=9, sales_qty=6),
            ]
            saved = client.patch("/api/inventory/batch", json={"items": changes})
            self.assertEqual(saved.status_code, 200, saved.text)
            updated = {item["item_id"]: item for item in client.get("/api/inventory").json()["items"]}
            alpha = updated[original["Alpha"]["item_id"]]
            beta = updated[original["Beta"]["item_id"]]
            self.assertEqual(alpha["product_name"], "Alpha renamed")
            self.assertEqual(alpha["inventory_value"], 1000)
            self.assertEqual(alpha["version"], original["Alpha"]["version"] + 1)
            self.assertIsNotNone(alpha["edited_at"])
            self.assertEqual(beta["sales_qty"], 6)
            self.assertEqual(beta["inventory_value"], 1800)
            self.assertEqual(len(client.get("/api/inventory", params={"upload_id": upload.json()["history_id"]}).json()["items"]), 2)
            self.assertTrue(client.get("/api/history").json()[0]["edited"])
            with self.session_factory() as db:
                self.assertEqual(db.query(InventoryDailyMetric).filter_by(item_id=alpha["item_id"]).count(), 31)
                self.assertEqual(db.query(InventoryDailyMetric).filter_by(item_id=alpha["item_id"]).first().daily_selling_price > 250, True)
                self.assertEqual(db.query(UploadAnalysisSummary).first().status, "stale")
                self.assertEqual(db.get(RawInventory, alpha["item_id"]).upload_file_id, upload.json()["history_id"])

            stale = client.patch("/api/inventory/batch", json={"items": [changes[0], edit(beta, stock_qty=99)]})
            self.assertEqual(stale.status_code, 409, stale.text)
            self.assertEqual(client.get("/api/inventory").json()["items"][0]["stock_qty"] in (10, 9), True)
            self.assertEqual(client.patch("/api/inventory/batch", json={"items": [edit(alpha, product_name="Beta")]}).status_code, 409)
            invalid = client.patch("/api/inventory/batch", json={"items": [edit(alpha, stock_qty=-1)]})
            self.assertEqual(invalid.status_code, 422)
            self.assertEqual(invalid.json()["detail"][0]["loc"], ["body", "items", 0, "stock_qty"])
            unchanged = {item["item_id"]: item for item in client.get("/api/inventory").json()["items"]}
            self.assertEqual(unchanged[alpha["item_id"]]["stock_qty"], 10)
            self.assertEqual(unchanged[beta["item_id"]]["stock_qty"], 9)

            with patch.object(inventory_service, "replace_daily_inventory_metrics", side_effect=[None, RuntimeError("metric failure")]):
                with self.assertRaisesRegex(RuntimeError, "metric failure"):
                    client.patch("/api/inventory/batch", json={"items": [
                        edit(alpha, stock_qty=20), edit(beta, stock_qty=30),
                    ]})
            rolled_back = {item["item_id"]: item for item in client.get("/api/inventory").json()["items"]}
            self.assertEqual(rolled_back[alpha["item_id"]]["stock_qty"], 10)
            self.assertEqual(rolled_back[beta["item_id"]]["stock_qty"], 9)
            self.assertEqual(rolled_back[alpha["item_id"]]["version"], alpha["version"])
            self.assertEqual(rolled_back[beta["item_id"]]["version"], beta["version"])

            client.post("/api/auth/logout")
            signup_other = client.post("/api/auth/signup", json={
                "username": "Other Grid User", "email": "other-grid@example.test", "password": "test-password",
            })
            self.assertEqual(signup_other.status_code, 200, signup_other.text)
            foreign = client.patch("/api/inventory/batch", json={"items": [edit(alpha, stock_qty=999)]})
            self.assertEqual(foreign.status_code, 404, foreign.text)

            client.post("/api/auth/logout")
            login = client.post("/api/auth/login", json={
                "email": "grid@example.test", "password": "test-password",
            })
            self.assertEqual(login.status_code, 200, login.text)
            reupload = self._upload(client, "updated.csv", [["Alpha renamed", 12, 100, "2026-01-01", 300, 2]])
            self.assertEqual(reupload.status_code, 200, reupload.text)
            refreshed = next(row for row in client.get("/api/inventory").json()["items"] if row["item_id"] == alpha["item_id"])
            self.assertEqual(refreshed["version"], alpha["version"] + 1)
            self.assertIsNone(refreshed["edited_at"])
            self.assertEqual(client.patch("/api/inventory/batch", json={"items": [edit(alpha, stock_qty=11)]}).status_code, 409)

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