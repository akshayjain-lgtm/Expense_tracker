"""
Tests for Step 7: Add Expense
Spec: .claude/specs/07-add-expense.md
"""

import pytest
from unittest.mock import patch
from werkzeug.security import generate_password_hash

import database.db as db_module
from database.queries import insert_expense
from app import app as flask_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "add_expense_test.db")
    with patch.object(db_module, "DB_PATH", db_file):
        conn = db_module.get_db()
        conn.execute("""
            CREATE TABLE users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                email         TEXT    UNIQUE NOT NULL,
                password_hash TEXT    NOT NULL,
                created_at    TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE expenses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                amount      REAL    NOT NULL,
                category    TEXT    NOT NULL,
                date        TEXT    NOT NULL,
                description TEXT,
                created_at  TEXT    DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.commit()
        conn.close()
        yield db_file


@pytest.fixture
def seeded_user(test_db):
    with patch.object(db_module, "DB_PATH", test_db):
        conn = db_module.get_db()
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            ("Test User", "test@example.com",
             generate_password_hash("password123"), "2026-01-15 10:00:00"),
        )
        uid = cur.lastrowid
        conn.commit()
        conn.close()
    return test_db, uid


@pytest.fixture
def auth_client(seeded_user):
    db_path, uid = seeded_user
    flask_app.config.update({"TESTING": True, "SECRET_KEY": "test-add-expense-secret"})
    with patch.object(db_module, "DB_PATH", db_path):
        with flask_app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = uid
            yield client, uid


def _expense_rows(db_path, uid):
    with patch.object(db_module, "DB_PATH", db_path):
        conn = db_module.get_db()
        rows = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (uid,)
        ).fetchall()
        conn.close()
        return rows


# ---------------------------------------------------------------------------
# Unit tests: insert_expense
# ---------------------------------------------------------------------------

class TestInsertExpense:
    def test_insert_expense_creates_row(self, seeded_user):
        db_path, uid = seeded_user
        with patch.object(db_module, "DB_PATH", db_path):
            insert_expense(uid, 50.0, "Food", "2026-03-20", "Lunch")
        rows = _expense_rows(db_path, uid)
        assert len(rows) == 1
        assert rows[0]["amount"] == 50.0
        assert rows[0]["category"] == "Food"
        assert rows[0]["date"] == "2026-03-20"
        assert rows[0]["description"] == "Lunch"

    def test_insert_expense_with_none_description_stores_null(self, seeded_user):
        db_path, uid = seeded_user
        with patch.object(db_module, "DB_PATH", db_path):
            insert_expense(uid, 20.0, "Other", "2026-03-21", None)
        rows = _expense_rows(db_path, uid)
        assert len(rows) == 1
        assert rows[0]["description"] is None


# ---------------------------------------------------------------------------
# Route tests: GET /expenses/add
# ---------------------------------------------------------------------------

class TestGetAddExpense:
    def test_unauthenticated_redirects_to_login(self, test_db):
        flask_app.config["TESTING"] = True
        with patch.object(db_module, "DB_PATH", test_db):
            with flask_app.test_client() as client:
                resp = client.get("/expenses/add")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_authenticated_returns_200(self, auth_client):
        client, uid = auth_client
        resp = client.get("/expenses/add")
        assert resp.status_code == 200

    def test_authenticated_shows_all_categories(self, auth_client):
        client, uid = auth_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        for category in ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]:
            assert category in body

    def test_authenticated_shows_post_form(self, auth_client):
        client, uid = auth_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        assert "<form" in body
        assert 'method="POST"' in body


# ---------------------------------------------------------------------------
# Route tests: POST /expenses/add
# ---------------------------------------------------------------------------

class TestPostAddExpense:
    def test_unauthenticated_redirects_to_login(self, test_db):
        flask_app.config["TESTING"] = True
        with patch.object(db_module, "DB_PATH", test_db):
            with flask_app.test_client() as client:
                resp = client.post("/expenses/add", data={
                    "amount": "10", "category": "Food", "date": "2026-03-20", "description": "x"
                })
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_valid_data_redirects_to_profile_and_inserts_row(self, auth_client, seeded_user):
        client, uid = auth_client
        db_path, _ = seeded_user
        resp = client.post("/expenses/add", data={
            "amount": "50.0", "category": "Food", "date": "2026-03-20", "description": "Lunch"
        })
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/profile")
        rows = _expense_rows(db_path, uid)
        assert len(rows) == 1
        assert rows[0]["amount"] == 50.0

    def test_missing_amount_rerenders_with_error(self, auth_client, seeded_user):
        client, uid = auth_client
        db_path, _ = seeded_user
        resp = client.post("/expenses/add", data={
            "amount": "", "category": "Food", "date": "2026-03-20", "description": ""
        })
        assert resp.status_code == 200
        assert len(_expense_rows(db_path, uid)) == 0

    def test_zero_amount_rerenders_with_error(self, auth_client, seeded_user):
        client, uid = auth_client
        db_path, _ = seeded_user
        resp = client.post("/expenses/add", data={
            "amount": "0", "category": "Food", "date": "2026-03-20", "description": ""
        })
        assert resp.status_code == 200
        assert len(_expense_rows(db_path, uid)) == 0

    def test_non_numeric_amount_rerenders_with_error(self, auth_client, seeded_user):
        client, uid = auth_client
        db_path, _ = seeded_user
        resp = client.post("/expenses/add", data={
            "amount": "abc", "category": "Food", "date": "2026-03-20", "description": ""
        })
        assert resp.status_code == 200
        assert len(_expense_rows(db_path, uid)) == 0

    def test_invalid_category_rerenders_with_error(self, auth_client, seeded_user):
        client, uid = auth_client
        db_path, _ = seeded_user
        resp = client.post("/expenses/add", data={
            "amount": "10", "category": "NotACategory", "date": "2026-03-20", "description": ""
        })
        assert resp.status_code == 200
        assert len(_expense_rows(db_path, uid)) == 0

    def test_invalid_date_rerenders_with_error(self, auth_client, seeded_user):
        client, uid = auth_client
        db_path, _ = seeded_user
        resp = client.post("/expenses/add", data={
            "amount": "10", "category": "Food", "date": "not-a-date", "description": ""
        })
        assert resp.status_code == 200
        assert len(_expense_rows(db_path, uid)) == 0

    def test_no_description_inserts_with_null_description(self, auth_client, seeded_user):
        client, uid = auth_client
        db_path, _ = seeded_user
        resp = client.post("/expenses/add", data={
            "amount": "10", "category": "Food", "date": "2026-03-20", "description": ""
        })
        assert resp.status_code == 302
        rows = _expense_rows(db_path, uid)
        assert len(rows) == 1
        assert rows[0]["description"] is None
