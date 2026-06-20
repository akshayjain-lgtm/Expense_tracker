"""
Tests for Step 8: Delete Expense
Spec: .claude/specs/08-delete-expense.md
"""

import pytest
from unittest.mock import patch
from werkzeug.security import generate_password_hash

import database.db as db_module
from database.queries import delete_expense, get_expense_by_id, insert_expense
from app import app as flask_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "delete_expense_test.db")
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
            ("Owner", "owner@example.com",
             generate_password_hash("password123"), "2026-01-15 10:00:00"),
        )
        owner_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            ("Other", "other@example.com",
             generate_password_hash("password123"), "2026-01-15 10:00:00"),
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
    flask_app.config.update({"TESTING": True, "SECRET_KEY": "test-delete-expense-secret"})
    with patch.object(db_module, "DB_PATH", db_path):
        with flask_app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = owner_id
            yield client, owner_id, other_id, expense_id


def _expense_rows(db_path, uid):
    with patch.object(db_module, "DB_PATH", db_path):
        conn = db_module.get_db()
        rows = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (uid,)
        ).fetchall()
        conn.close()
        return rows


# ---------------------------------------------------------------------------
# Unit tests: get_expense_by_id / delete_expense
# ---------------------------------------------------------------------------

class TestGetExpenseById:
    def test_returns_row_for_owner(self, seeded_expense):
        db_path, owner_id, other_id, expense_id = seeded_expense
        with patch.object(db_module, "DB_PATH", db_path):
            row = get_expense_by_id(expense_id, owner_id)
        assert row is not None
        assert row["id"] == expense_id

    def test_returns_none_for_non_owner(self, seeded_expense):
        db_path, owner_id, other_id, expense_id = seeded_expense
        with patch.object(db_module, "DB_PATH", db_path):
            row = get_expense_by_id(expense_id, other_id)
        assert row is None

    def test_returns_none_for_non_existent_id(self, seeded_expense):
        db_path, owner_id, other_id, expense_id = seeded_expense
        with patch.object(db_module, "DB_PATH", db_path):
            row = get_expense_by_id(expense_id + 999, owner_id)
        assert row is None


class TestDeleteExpense:
    def test_deletes_row_for_owner(self, seeded_expense):
        db_path, owner_id, other_id, expense_id = seeded_expense
        with patch.object(db_module, "DB_PATH", db_path):
            delete_expense(expense_id, owner_id)
        assert len(_expense_rows(db_path, owner_id)) == 0

    def test_no_op_for_wrong_user(self, seeded_expense):
        db_path, owner_id, other_id, expense_id = seeded_expense
        with patch.object(db_module, "DB_PATH", db_path):
            delete_expense(expense_id, other_id)
        assert len(_expense_rows(db_path, owner_id)) == 1

    def test_no_op_for_non_existent_id(self, seeded_expense):
        db_path, owner_id, other_id, expense_id = seeded_expense
        with patch.object(db_module, "DB_PATH", db_path):
            delete_expense(expense_id + 999, owner_id)
        assert len(_expense_rows(db_path, owner_id)) == 1


# ---------------------------------------------------------------------------
# Route tests: POST /expenses/<id>/delete
# ---------------------------------------------------------------------------

class TestPostDeleteExpense:
    def test_unauthenticated_redirects_to_login(self, seeded_expense):
        db_path, owner_id, other_id, expense_id = seeded_expense
        flask_app.config["TESTING"] = True
        with patch.object(db_module, "DB_PATH", db_path):
            with flask_app.test_client() as client:
                resp = client.post(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
        assert len(_expense_rows(db_path, owner_id)) == 1

    def test_own_expense_deletes_and_redirects_to_profile(self, auth_client, seeded_expense):
        client, owner_id, other_id, expense_id = auth_client
        db_path, _, _, _ = seeded_expense
        resp = client.post(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/profile")
        assert len(_expense_rows(db_path, owner_id)) == 0

    def test_other_users_expense_returns_404(self, seeded_expense):
        db_path, owner_id, other_id, expense_id = seeded_expense
        flask_app.config.update({"TESTING": True, "SECRET_KEY": "test-delete-expense-secret"})
        with patch.object(db_module, "DB_PATH", db_path):
            with flask_app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["user_id"] = other_id
                resp = client.post(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 404
        assert len(_expense_rows(db_path, owner_id)) == 1

    def test_non_existent_id_returns_404(self, auth_client):
        client, owner_id, other_id, expense_id = auth_client
        resp = client.post(f"/expenses/{expense_id + 999}/delete")
        assert resp.status_code == 404

    def test_get_method_not_allowed(self, auth_client):
        client, owner_id, other_id, expense_id = auth_client
        resp = client.get(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 405

    def test_preserves_date_filter_on_redirect(self, auth_client):
        client, owner_id, other_id, expense_id = auth_client
        resp = client.post(f"/expenses/{expense_id}/delete", data={
            "date_from": "2026-01-01", "date_to": "2026-03-20"
        })
        assert resp.status_code == 302
        location = resp.headers["Location"]
        assert "date_from=2026-01-01" in location
        assert "date_to=2026-03-20" in location
