import math
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
from app.analysis import calculate_safety_stock
from app.main import app
from app.models import AnalysisResult, InventoryDailyMetric, RawInventory, User
from app.security import get_current_user


class SafetyStockTests(unittest.TestCase):
    def test_default_lead_times(self):
        self.assertEqual(calculate_safety_stock(10, 4), 42)

    def test_manual_lead_times(self):
        self.assertEqual(calculate_safety_stock(10, 4, 7, 3), 58)

    def test_rounds_up(self):
        self.assertEqual(calculate_safety_stock(2.5, 1.2), 11)

    def test_decimal_boundary(self):
        self.assertEqual(calculate_safety_stock(0.2, 0.1, 7, 4), 1)

    def test_no_sales(self):
        self.assertEqual(calculate_safety_stock(0, 0), 0)

    def test_zero_buffer(self):
        self.assertEqual(calculate_safety_stock(4, 4, 2, 2), 0)

    def test_invalid_values(self):
        for values in [(-1, 0), (math.nan, 0), (math.inf, 0), (1, 0, -1, 0)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                calculate_safety_stock(*values)

    def test_inconsistent_averages(self):
        for values in [(2, 3), (10, 4, 2, 5)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                calculate_safety_stock(*values)

    def test_daily_sales_auto_inputs_window_zero_days_and_ownership(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        sessions = sessionmaker(bind=engine)
        overrides = dict(app.dependency_overrides)
        try:
            with patch.object(database, "engine", engine), patch.object(database, "SessionLocal", sessions), TestClient(app) as client:
                with sessions() as db:
                    db.add_all([User(user_id=1), User(user_id=2)])
                    db.add_all([RawInventory(item_id=1, user_id=1), RawInventory(item_id=2, user_id=2), RawInventory(item_id=3, user_id=1)])
                    db.add_all([AnalysisResult(item_id=1), AnalysisResult(item_id=2), AnalysisResult(item_id=3, sales_velocity=1.5)])
                    for offset in range(-1, 31):
                        db.add(InventoryDailyMetric(
                            item_id=1, business_date=date.today() - timedelta(days=offset),
                            daily_sales_qty=999 if offset == -1 else 99 if offset == 30 else (10 if offset % 2 else 0),
                            daily_selling_price=100, price_variation_rate=0,
                        ))
                    db.commit()
                self.assertEqual(client.get("/api/inventory/1/safety-stock").status_code, 401)
                app.dependency_overrides[get_current_user] = lambda: User(user_id=1)
                response = client.get("/api/inventory/1/safety-stock")
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertEqual(result["recorded_days"], 30)
                self.assertEqual(result["inputs"]["max_daily_sales"], 10)
                self.assertEqual(result["inputs"]["average_daily_sales"], 5)
                self.assertEqual(result["source"], "stored_daily_demo")
                calculated = client.post("/api/inventory/1/safety-stock", json=result["inputs"])
                self.assertEqual(calculated.json()["recommended_qty"], 40)
                self.assertEqual(client.get("/api/inventory/2/safety-stock").status_code, 404)
                empty = client.get("/api/inventory/3/safety-stock").json()
                self.assertEqual(empty["recorded_days"], 0)
                self.assertIsNone(empty["inputs"]["max_daily_sales"])
                self.assertEqual(empty["inputs"]["average_daily_sales"], 1.5)
                self.assertEqual(empty["source"], "estimate")
                with sessions() as db:
                    db.query(InventoryDailyMetric).filter(InventoryDailyMetric.business_date != date.today()).delete()
                    db.commit()
                partial = client.get("/api/inventory/1/safety-stock").json()
                self.assertEqual(partial["recorded_days"], 1)
                self.assertEqual(partial["inputs"]["average_daily_sales"], 0)
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(overrides)
            engine.dispose()

    def test_api_defaults_manual_validation_and_ownership(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        sessions = sessionmaker(bind=engine)
        overrides = dict(app.dependency_overrides)
        try:
            with patch.object(database, "engine", engine), patch.object(database, "SessionLocal", sessions), TestClient(app) as client:
                with sessions() as db:
                    db.add_all([User(user_id=1), User(user_id=2)])
                    db.add_all([RawInventory(item_id=1, user_id=1), RawInventory(item_id=2, user_id=2)])
                    db.add_all([AnalysisResult(item_id=1), AnalysisResult(item_id=2)])
                    db.commit()
                payload = {"max_daily_sales": 10, "average_daily_sales": 4}
                self.assertEqual(client.post("/api/inventory/1/safety-stock", json=payload).status_code, 401)
                app.dependency_overrides[get_current_user] = lambda: User(user_id=1)
                response = client.post("/api/inventory/1/safety-stock", json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["recommended_qty"], 42)
                payload.update(max_lead_time_days=7, average_lead_time_days=3)
                self.assertEqual(client.post("/api/inventory/1/safety-stock", json=payload).json()["recommended_qty"], 58)
                self.assertEqual(client.post("/api/inventory/2/safety-stock", json=payload).status_code, 404)
                for invalid in [dict(payload, average_lead_time_days=8), dict(payload, max_daily_sales=-1), dict(payload, average_daily_sales=11)]:
                    self.assertEqual(client.post("/api/inventory/1/safety-stock", json=invalid).status_code, 422)
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(overrides)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()