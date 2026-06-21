"""
Tests for Step 8: Edit Expense
Spec: .claude/specs/08-edit-expense.md
"""

import pytest
from unittest.mock import patch
from werkzeug.security import generate_password_hash

import database.db as db_module
from database.queries import get_expense_by_id, insert_expense, update_expense
from app import app as flask_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "edit_expense_test.db")
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
def two_users(test_db):
    with patch.object(db_module, "DB_PATH", test_db):
        conn = db_module.get_db()
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (
                "Owner",
                "owner@example.com",
                generate_password_hash("password123"),
                "2026-01-15 10:00:00",
            ),
        )
        owner_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (
                "Other",
                "other@example.com",
                generate_password_hash("password123"),
                "2026-01-15 10:00:00",
            ),
        )
        other_id = cur.lastrowid
        conn.commit()
        conn.close()
    return test_db, owner_id, other_id


@pytest.fixture
def seeded_expense(two_users):
    db_path, owner_id, other_id = two_users
    with patch.object(db_module, "DB_PATH", db_path):
        insert_expense(owner_id, 50.0, "Food", "2026-03-20", "Lunch")
        conn = db_module.get_db()
        expense_id = conn.execute(
            "SELECT id FROM expenses WHERE user_id = ?", (owner_id,)
        ).fetchone()["id"]
        conn.close()
    return db_path, owner_id, other_id, expense_id


@pytest.fixture
def auth_client(seeded_expense):
    db_path, owner_id, other_id, expense_id = seeded_expense
    flask_app.config.update({"TESTING": True, "SECRET_KEY": "test-edit-expense-secret"})
    with patch.object(db_module, "DB_PATH", db_path):
        with flask_app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = owner_id
            yield client, owner_id, other_id, expense_id


def _expense_row(db_path, expense_id):
    with patch.object(db_module, "DB_PATH", db_path):
        conn = db_module.get_db()
        row = conn.execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        return row


# ---------------------------------------------------------------------------
# Unit tests: update_expense
# ---------------------------------------------------------------------------


class TestUpdateExpense:
    def test_updates_row_for_owner(self, seeded_expense):
        db_path, owner_id, other_id, expense_id = seeded_expense
        with patch.object(db_module, "DB_PATH", db_path):
            update_expense(expense_id, owner_id, 99.0, "Bills", "2026-04-01", "Updated")
        row = _expense_row(db_path, expense_id)
        assert row["amount"] == 99.0
        assert row["category"] == "Bills"
        assert row["date"] == "2026-04-01"
        assert row["description"] == "Updated"

    def test_no_op_for_wrong_user(self, seeded_expense):
        db_path, owner_id, other_id, expense_id = seeded_expense
        with patch.object(db_module, "DB_PATH", db_path):
            update_expense(expense_id, other_id, 99.0, "Bills", "2026-04-01", "Updated")
        row = _expense_row(db_path, expense_id)
        assert row["amount"] == 50.0
        assert row["category"] == "Food"


# ---------------------------------------------------------------------------
# Route tests: GET /expenses/<id>/edit
# ---------------------------------------------------------------------------


class TestGetEditExpense:
    def test_unauthenticated_redirects_to_login(self, seeded_expense):
        db_path, owner_id, other_id, expense_id = seeded_expense
        flask_app.config["TESTING"] = True
        with patch.object(db_module, "DB_PATH", db_path):
            with flask_app.test_client() as client:
                resp = client.get(f"/expenses/{expense_id}/edit")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_own_expense_returns_prefilled_form(self, auth_client):
        client, owner_id, other_id, expense_id = auth_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "50.0" in body or "50.00" in body
        assert "Lunch" in body
        assert "<select" in body
        assert "selected" in body

    def test_other_users_expense_returns_404(self, seeded_expense):
        db_path, owner_id, other_id, expense_id = seeded_expense
        flask_app.config.update(
            {"TESTING": True, "SECRET_KEY": "test-edit-expense-secret"}
        )
        with patch.object(db_module, "DB_PATH", db_path):
            with flask_app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["user_id"] = other_id
                resp = client.get(f"/expenses/{expense_id}/edit")
        assert resp.status_code == 404

    def test_non_existent_id_returns_404(self, auth_client):
        client, owner_id, other_id, expense_id = auth_client
        resp = client.get(f"/expenses/{expense_id + 999}/edit")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Route tests: POST /expenses/<id>/edit
# ---------------------------------------------------------------------------


class TestPostEditExpense:
    def test_unauthenticated_redirects_to_login(self, seeded_expense):
        db_path, owner_id, other_id, expense_id = seeded_expense
        flask_app.config["TESTING"] = True
        with patch.object(db_module, "DB_PATH", db_path):
            with flask_app.test_client() as client:
                resp = client.post(
                    f"/expenses/{expense_id}/edit",
                    data={
                        "amount": "75.0",
                        "category": "Bills",
                        "date": "2026-04-01",
                        "description": "Updated",
                    },
                )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_valid_data_updates_and_redirects_to_profile(
        self, auth_client, seeded_expense
    ):
        client, owner_id, other_id, expense_id = auth_client
        db_path, _, _, _ = seeded_expense
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "75.0",
                "category": "Bills",
                "date": "2026-04-01",
                "description": "Updated",
            },
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/profile")
        row = _expense_row(db_path, expense_id)
        assert row["amount"] == 75.0
        assert row["category"] == "Bills"
        assert row["date"] == "2026-04-01"
        assert row["description"] == "Updated"

    def test_other_users_expense_returns_404(self, seeded_expense):
        db_path, owner_id, other_id, expense_id = seeded_expense
        flask_app.config.update(
            {"TESTING": True, "SECRET_KEY": "test-edit-expense-secret"}
        )
        with patch.object(db_module, "DB_PATH", db_path):
            with flask_app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["user_id"] = other_id
                resp = client.post(
                    f"/expenses/{expense_id}/edit",
                    data={
                        "amount": "75.0",
                        "category": "Bills",
                        "date": "2026-04-01",
                        "description": "Updated",
                    },
                )
        assert resp.status_code == 404
        row = _expense_row(db_path, expense_id)
        assert row["amount"] == 50.0

    def test_missing_amount_rerenders_with_error(self, auth_client):
        client, owner_id, other_id, expense_id = auth_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "",
                "category": "Food",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        assert resp.status_code == 200
        assert "valid amount" in resp.get_data(as_text=True)

    def test_zero_amount_rerenders_with_error(self, auth_client):
        client, owner_id, other_id, expense_id = auth_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "0",
                "category": "Food",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        assert resp.status_code == 200
        assert "valid amount" in resp.get_data(as_text=True)

    def test_non_numeric_amount_rerenders_with_error(self, auth_client):
        client, owner_id, other_id, expense_id = auth_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "abc",
                "category": "Food",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        assert resp.status_code == 200
        assert "valid amount" in resp.get_data(as_text=True)

    def test_invalid_category_rerenders_with_error(self, auth_client):
        client, owner_id, other_id, expense_id = auth_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "50.0",
                "category": "NotACategory",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        assert resp.status_code == 200
        assert "valid category" in resp.get_data(as_text=True)

    def test_invalid_date_rerenders_with_error(self, auth_client):
        client, owner_id, other_id, expense_id = auth_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "50.0",
                "category": "Food",
                "date": "not-a-date",
                "description": "Lunch",
            },
        )
        assert resp.status_code == 200
        assert "valid date" in resp.get_data(as_text=True)

    def test_no_description_saves_as_null(self, auth_client, seeded_expense):
        client, owner_id, other_id, expense_id = auth_client
        db_path, _, _, _ = seeded_expense
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "50.0",
                "category": "Food",
                "date": "2026-03-20",
                "description": "",
            },
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/profile")
        row = _expense_row(db_path, expense_id)
        assert row["description"] is None
