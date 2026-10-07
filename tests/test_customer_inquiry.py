import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
from app.main import app
from app.models import CustomerInquiry


class CustomerInquiryTests(unittest.TestCase):
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

    def test_anonymous_inquiry_is_saved(self):
        with (
            patch.object(database, "engine", self.engine),
            patch.object(database, "SessionLocal", self.session_factory),
            TestClient(app) as client,
        ):
            response = client.post("/api/inquiries", json={
                "inquiry_type": "이용 안내",
                "subject": "파일 업로드 문의",
                "content": "지원하는 파일 형식을 알고 싶습니다.",
            })

            self.assertEqual(response.status_code, 200, response.text)
            with self.session_factory() as db:
                inquiry = db.get(CustomerInquiry, response.json()["inquiry_id"])
                self.assertIsNotNone(inquiry)
                self.assertIsNone(inquiry.user_id)
                self.assertEqual(inquiry.inquiry_type, "이용 안내")
                self.assertEqual(inquiry.subject, "파일 업로드 문의")

    def test_inquiry_requires_subject_and_content(self):
        with (
            patch.object(database, "engine", self.engine),
            patch.object(database, "SessionLocal", self.session_factory),
            TestClient(app) as client,
        ):
            response = client.post("/api/inquiries", json={
                "inquiry_type": "기타 문의",
                "subject": "   ",
                "content": "내용",
            })

            self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()