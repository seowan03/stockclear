import hashlib
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
from app.main import app
from app.models import CustomerInquiry, User


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

    def test_legacy_tables_gain_admin_and_reply_columns_without_losing_rows(self):
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "CREATE TABLE users (user_id INTEGER PRIMARY KEY, username TEXT, email TEXT, password_hash TEXT)"
                ))
                connection.execute(text(
                    "INSERT INTO users (user_id, username, email, password_hash) "
                    "VALUES (1, 'Admin Candidate', 'admin@example.test', 'hash')"
                ))
                connection.execute(text(
                    "CREATE TABLE customer_inquiries ("
                    "inquiry_id INTEGER PRIMARY KEY, user_id INTEGER, inquiry_type TEXT NOT NULL, "
                    "subject TEXT NOT NULL, content TEXT NOT NULL, created_at DATETIME)"
                ))
                connection.execute(text(
                    "INSERT INTO customer_inquiries "
                    "(inquiry_id, inquiry_type, subject, content) "
                    "VALUES (4, '기타 문의', '기존 제목', '기존 내용')"
                ))

            with patch.object(database, "engine", engine):
                database.ensure_users_role_column()
                database.ensure_customer_inquiry_reply_columns()
                database.ensure_users_role_column()
                database.ensure_customer_inquiry_reply_columns()

            users_columns = {column["name"] for column in inspect(engine).get_columns("users")}
            inquiry_columns = {column["name"] for column in inspect(engine).get_columns("customer_inquiries")}
            self.assertIn("role", users_columns)
            self.assertTrue({
                "status", "admin_reply", "replied_at", "replied_by_user_id", "reply_token_hash",
            }.issubset(inquiry_columns))
            with engine.connect() as connection:
                user = connection.execute(text(
                    "SELECT email, role FROM users WHERE user_id = 1"
                )).one()
                inquiry = connection.execute(text(
                    "SELECT subject, content, status FROM customer_inquiries WHERE inquiry_id = 4"
                )).one()
            self.assertEqual(user.email, "admin@example.test")
            self.assertEqual(user.role, "user")
            self.assertEqual(inquiry.subject, "기존 제목")
            self.assertEqual(inquiry.content, "기존 내용")
            self.assertEqual(inquiry.status, "접수")
        finally:
            engine.dispose()

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
            reply_token = response.json()["reply_token"]
            self.assertTrue(reply_token)
            with self.session_factory() as db:
                inquiry = db.get(CustomerInquiry, response.json()["inquiry_id"])
                self.assertIsNotNone(inquiry)
                self.assertIsNone(inquiry.user_id)
                self.assertEqual(inquiry.inquiry_type, "이용 안내")
                self.assertEqual(inquiry.subject, "파일 업로드 문의")
                self.assertEqual(
                    inquiry.reply_token_hash,
                    hashlib.sha256(reply_token.encode("utf-8")).hexdigest(),
                )

            reply_status = client.get(
                f"/api/inquiries/{response.json()['inquiry_id']}/reply",
                params={"token": reply_token},
            )
            self.assertEqual(reply_status.status_code, 200, reply_status.text)
            self.assertEqual(reply_status.json()["status"], "접수")
            self.assertIsNone(reply_status.json()["reply"])

    def test_admin_can_reply_and_anonymous_customer_can_read_reply(self):
        with (
            patch.object(database, "engine", self.engine),
            patch.object(database, "SessionLocal", self.session_factory),
            TestClient(app) as client,
        ):
            created = client.post("/api/inquiries", json={
                "inquiry_type": "구매 안내",
                "subject": "재고 분석 문의",
                "content": "분석 결과에 대해 문의합니다.",
            })
            self.assertEqual(created.status_code, 200, created.text)
            inquiry_id = created.json()["inquiry_id"]
            reply_token = created.json()["reply_token"]

            signup = client.post("/api/auth/signup", json={
                "username": "Support Admin",
                "email": "support-admin@example.test",
                "password": "test-password",
            })
            self.assertEqual(signup.status_code, 200, signup.text)
            admin_user_id = signup.json()["user_id"]
            with self.session_factory() as db:
                admin = db.get(User, admin_user_id)
                admin.role = "admin"
                db.commit()

            listing = client.get("/api/admin/inquiries", params={"status": "접수"})
            self.assertEqual(listing.status_code, 200, listing.text)
            self.assertEqual(listing.json()["items"][0]["inquiry_id"], inquiry_id)

            reply = client.patch(
                f"/api/admin/inquiries/{inquiry_id}",
                json={"reply": "문의 내용 확인했습니다. 안내드립니다."},
            )
            self.assertEqual(reply.status_code, 200, reply.text)
            self.assertEqual(reply.json()["status"], "답변 완료")

            client.post("/api/auth/logout")
            customer_reply = client.get(
                f"/api/inquiries/{inquiry_id}/reply",
                params={"token": reply_token},
            )
            self.assertEqual(customer_reply.status_code, 200, customer_reply.text)
            self.assertEqual(customer_reply.json()["reply"], "문의 내용 확인했습니다. 안내드립니다.")

            invalid_token = client.get(
                f"/api/inquiries/{inquiry_id}/reply",
                params={"token": "invalid-token"},
            )
            self.assertEqual(invalid_token.status_code, 404)

            regular_signup = client.post("/api/auth/signup", json={
                "username": "Regular User",
                "email": "regular-user@example.test",
                "password": "test-password",
            })
            self.assertEqual(regular_signup.status_code, 200, regular_signup.text)
            denied = client.get("/api/admin/inquiries")
            self.assertEqual(denied.status_code, 403, denied.text)

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