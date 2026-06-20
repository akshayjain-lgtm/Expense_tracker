"""
Tests for Step 9: Delete Expense
Spec: .claude/specs/08-delete-expense.md

All test logic is derived exclusively from the feature specification.
Implementation files (app.py, database/db.py, database/queries.py) were
read only for structural information (route paths, function signatures,
DB schema, fixture patterns used elsewhere in tests/) -- never for
expected behavior.
"""

import pytest
from unittest.mock import patch
from werkzeug.security import generate_password_hash

import database.db as db_module
from database.queries import delete_expense, insert_expense
from app import app as flask_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_db(tmp_path):
    """Isolated file-backed SQLite DB patched into database.db.DB_PATH."""
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
    """Insert two users (owner + other); yields (db_path, owner_id, other_id)."""
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
    """Insert one expense owned by `owner_id`; yields (db_path, owner_id, other_id, expense_id)."""
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
    """Flask test client logged in as the owner, with DB_PATH patched."""
    db_path, owner_id, other_id, expense_id = seeded_expense
    flask_app.config.update({
        "TESTING": True,
        "SECRET_KEY": "test-08-delete-expense-secret",
    })
    with patch.object(db_module, "DB_PATH", db_path):
        with flask_app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = owner_id
            yield client, owner_id, other_id, expense_id


def _expense_rows(db_path, user_id):
    """Return all expense rows belonging to user_id."""
    with patch.object(db_module, "DB_PATH", db_path):
        conn = db_module.get_db()
        rows = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchall()
        conn.close()
        return rows


def _expense_exists(db_path, expense_id):
    """Return True if an expense row with this id still exists, regardless of owner."""
    with patch.object(db_module, "DB_PATH", db_path):
        conn = db_module.get_db()
        row = conn.execute(
            "SELECT id FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        return row is not None


# ---------------------------------------------------------------------------
# 1. Unit tests for delete_expense (database/queries.py)
# ---------------------------------------------------------------------------

class TestDeleteExpenseUnit:
    def test_valid_id_and_correct_owner_removes_row(self, seeded_expense):
        """delete_expense with a valid id and the correct owner must remove the row."""
        db_path, owner_id, other_id, expense_id = seeded_expense
        with patch.object(db_module, "DB_PATH", db_path):
            delete_expense(expense_id, owner_id)
        assert len(_expense_rows(db_path, owner_id)) == 0, (
            "Expense row must be removed from the DB after delete_expense with correct owner"
        )

    def test_valid_id_wrong_owner_leaves_row_intact(self, seeded_expense):
        """delete_expense with a valid id but the wrong user_id must not delete the row."""
        db_path, owner_id, other_id, expense_id = seeded_expense
        with patch.object(db_module, "DB_PATH", db_path):
            delete_expense(expense_id, other_id)
        assert len(_expense_rows(db_path, owner_id)) == 1, (
            "Row must remain in the DB when delete_expense is called with the wrong user_id"
        )
        assert _expense_exists(db_path, expense_id), (
            "Expense must still exist by id when owner mismatch occurs"
        )

    def test_non_existent_id_raises_no_error_and_db_unchanged(self, seeded_expense):
        """delete_expense with a non-existent expense_id must not raise and must not change the DB."""
        db_path, owner_id, other_id, expense_id = seeded_expense
        with patch.object(db_module, "DB_PATH", db_path):
            delete_expense(expense_id + 999, owner_id)  # must not raise
        assert len(_expense_rows(db_path, owner_id)) == 1, (
            "DB must be unchanged when delete_expense targets a non-existent id"
        )


# ---------------------------------------------------------------------------
# 2. Route tests: POST /expenses/<id>/delete -- auth guard
# ---------------------------------------------------------------------------

class TestDeleteExpenseAuthGuard:
    def test_unauthenticated_post_redirects_to_login(self, seeded_expense):
        """Unauthenticated POST must redirect to /login (302)."""
        db_path, owner_id, other_id, expense_id = seeded_expense
        flask_app.config["TESTING"] = True
        with patch.object(db_module, "DB_PATH", db_path):
            with flask_app.test_client() as client:
                resp = client.post(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 302, "Expected 302 redirect for unauthenticated POST"
        assert "/login" in resp.headers["Location"], "Redirect target must be /login"

    def test_unauthenticated_post_does_not_delete_row(self, seeded_expense):
        """Unauthenticated POST must not delete the expense row."""
        db_path, owner_id, other_id, expense_id = seeded_expense
        flask_app.config["TESTING"] = True
        with patch.object(db_module, "DB_PATH", db_path):
            with flask_app.test_client() as client:
                client.post(f"/expenses/{expense_id}/delete")
        assert len(_expense_rows(db_path, owner_id)) == 1, (
            "Expense row must remain intact when the requester is unauthenticated"
        )


# ---------------------------------------------------------------------------
# 3. Route tests: POST /expenses/<id>/delete -- authenticated, own expense
# ---------------------------------------------------------------------------

class TestDeleteOwnExpense:
    def test_deleting_own_expense_redirects_to_profile(self, auth_client):
        """Deleting one's own expense must redirect (302) to /profile."""
        client, owner_id, other_id, expense_id = auth_client
        resp = client.post(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 302, "Expected 302 redirect after successful delete"
        assert resp.headers["Location"].endswith("/profile"), (
            "Redirect target must be /profile"
        )

    def test_deleting_own_expense_removes_row_from_db(self, auth_client, seeded_expense):
        """After deleting one's own expense, the row must no longer exist in the DB."""
        client, owner_id, other_id, expense_id = auth_client
        db_path, _, _, _ = seeded_expense
        client.post(f"/expenses/{expense_id}/delete")
        assert len(_expense_rows(db_path, owner_id)) == 0, (
            "Expense row must be removed from the DB after a successful delete"
        )
        assert not _expense_exists(db_path, expense_id), (
            "Expense must no longer exist by id after deletion"
        )

    def test_deleting_own_expense_does_not_render_template(self, auth_client):
        """A successful delete must redirect, not render a template body directly."""
        client, owner_id, other_id, expense_id = auth_client
        resp = client.post(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 302, (
            "Spec requires a redirect (not a rendered template) on success"
        )

    def test_deleted_expense_no_longer_appears_in_profile(self, auth_client):
        """Following the redirect, the deleted expense must not appear in the profile list."""
        client, owner_id, other_id, expense_id = auth_client
        resp = client.post(
            f"/expenses/{expense_id}/delete", follow_redirects=True
        )
        body = resp.data.decode()
        assert "Lunch" not in body, (
            "Deleted expense's description must not appear in the profile transaction list"
        )


# ---------------------------------------------------------------------------
# 4. Route tests: POST /expenses/<id>/delete -- other user's expense
# ---------------------------------------------------------------------------

class TestDeleteOtherUsersExpense:
    def test_deleting_other_users_expense_returns_404(self, seeded_expense):
        """Authenticated request to delete another user's expense must return 404."""
        db_path, owner_id, other_id, expense_id = seeded_expense
        flask_app.config.update({
            "TESTING": True,
            "SECRET_KEY": "test-08-delete-expense-secret",
        })
        with patch.object(db_module, "DB_PATH", db_path):
            with flask_app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["user_id"] = other_id
                resp = client.post(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 404, (
            "Deleting another user's expense must return 404 (ownership guard)"
        )

    def test_deleting_other_users_expense_leaves_row_intact(self, seeded_expense):
        """Attempting to delete another user's expense must not remove the row."""
        db_path, owner_id, other_id, expense_id = seeded_expense
        flask_app.config.update({
            "TESTING": True,
            "SECRET_KEY": "test-08-delete-expense-secret",
        })
        with patch.object(db_module, "DB_PATH", db_path):
            with flask_app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["user_id"] = other_id
                client.post(f"/expenses/{expense_id}/delete")
        assert len(_expense_rows(db_path, owner_id)) == 1, (
            "Owner's expense row must remain intact after a non-owner delete attempt"
        )
        assert _expense_exists(db_path, expense_id), (
            "Expense must still exist by id after a non-owner delete attempt"
        )


# ---------------------------------------------------------------------------
# 5. Route tests: POST /expenses/<id>/delete -- non-existent id
# ---------------------------------------------------------------------------

class TestDeleteNonExistentExpense:
    def test_non_existent_id_returns_404(self, auth_client):
        """Authenticated POST to a non-existent expense id must return 404."""
        client, owner_id, other_id, expense_id = auth_client
        resp = client.post(f"/expenses/{expense_id + 999}/delete")
        assert resp.status_code == 404, (
            "Deleting a non-existent expense id must return 404"
        )

    def test_non_existent_id_does_not_alter_existing_rows(self, auth_client, seeded_expense):
        """Attempting to delete a non-existent id must not affect existing rows."""
        client, owner_id, other_id, expense_id = auth_client
        db_path, _, _, _ = seeded_expense
        client.post(f"/expenses/{expense_id + 999}/delete")
        assert len(_expense_rows(db_path, owner_id)) == 1, (
            "Existing expense rows must remain unaffected by a delete attempt on a bogus id"
        )


# ---------------------------------------------------------------------------
# 6. Route tests: HTTP method restrictions
# ---------------------------------------------------------------------------

class TestDeleteExpenseMethodRestrictions:
    def test_get_request_returns_405(self, auth_client):
        """A bare GET to the delete URL must return 405 Method Not Allowed."""
        client, owner_id, other_id, expense_id = auth_client
        resp = client.get(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 405, (
            "GET /expenses/<id>/delete must return 405 since only POST is allowed"
        )

    def test_get_request_does_not_delete_row(self, auth_client, seeded_expense):
        """A GET request must never delete the expense, regardless of the 405 response."""
        client, owner_id, other_id, expense_id = auth_client
        db_path, _, _, _ = seeded_expense
        client.get(f"/expenses/{expense_id}/delete")
        assert len(_expense_rows(db_path, owner_id)) == 1, (
            "Expense row must remain intact after a disallowed GET request"
        )

    def test_get_request_unauthenticated_still_returns_405_or_redirect(self, seeded_expense):
        """An unauthenticated GET to the delete URL must not be treated as a successful delete.

        Per spec, only POST is accepted on this route; a GET should be rejected by Flask's
        routing layer (405) regardless of auth state, since method dispatch happens before
        the auth guard runs.
        """
        db_path, owner_id, other_id, expense_id = seeded_expense
        flask_app.config["TESTING"] = True
        with patch.object(db_module, "DB_PATH", db_path):
            with flask_app.test_client() as client:
                resp = client.get(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 405, (
            "GET must return 405 regardless of authentication state"
        )
        assert len(_expense_rows(db_path, owner_id)) == 1, (
            "Expense row must remain intact after a disallowed GET request"
        )
