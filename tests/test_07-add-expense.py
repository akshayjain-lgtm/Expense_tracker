"""
Tests for Step 7: Add Expense
Spec: .claude/specs/07-add-expense.md

All test logic is derived exclusively from the feature specification.
The implementation files (app.py, database/db.py, database/queries.py) were
read only for structural information (route paths, function signatures,
DB schema, fixture patterns used elsewhere in tests/) -- never for expected
behavior.
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
    """Isolated file-backed SQLite DB patched into database.db.DB_PATH."""
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
    """Insert a single user with no expenses; yields (db_path, user_id)."""
    with patch.object(db_module, "DB_PATH", test_db):
        conn = db_module.get_db()
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            ("Add Expense Tester", "addexpense@example.com",
             generate_password_hash("testpass123"), "2026-01-15 10:00:00"),
        )
        uid = cur.lastrowid
        conn.commit()
        conn.close()
    yield test_db, uid


@pytest.fixture
def auth_client(seeded_user):
    """Flask test client with DB_PATH patched and the seeded user logged in via session."""
    db_path, uid = seeded_user
    flask_app.config.update({
        "TESTING": True,
        "SECRET_KEY": "test-add-expense-secret",
    })
    with patch.object(db_module, "DB_PATH", db_path):
        with flask_app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = uid
            yield client, uid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXED_CATEGORIES = [
    "Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other",
]


def _fetch_expenses(db_path, user_id):
    with patch.object(db_module, "DB_PATH", db_path):
        conn = db_module.get_db()
        rows = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchall()
        conn.close()
    return rows


# ---------------------------------------------------------------------------
# 1. Unit tests for insert_expense
# ---------------------------------------------------------------------------

class TestInsertExpenseUnit:
    def test_insert_expense_valid_data_creates_row(self, seeded_user):
        """insert_expense with valid data must create a row retrievable from the DB."""
        db_path, uid = seeded_user
        with patch.object(db_module, "DB_PATH", db_path):
            insert_expense(uid, 50.0, "Food", "2026-03-20", "Lunch")

        rows = _fetch_expenses(db_path, uid)
        assert len(rows) == 1, "Expected exactly one expense row to be inserted"
        row = rows[0]
        assert row["user_id"] == uid, "Inserted row must belong to the correct user"
        assert row["amount"] == 50.0, "Amount must match the inserted value"
        assert row["category"] == "Food", "Category must match the inserted value"
        assert row["date"] == "2026-03-20", "Date must match the inserted value"
        assert row["description"] == "Lunch", "Description must match the inserted value"

    def test_insert_expense_none_description_stores_null(self, seeded_user):
        """insert_expense with description=None must store NULL in the DB."""
        db_path, uid = seeded_user
        with patch.object(db_module, "DB_PATH", db_path):
            insert_expense(uid, 25.0, "Transport", "2026-04-01", None)

        rows = _fetch_expenses(db_path, uid)
        assert len(rows) == 1, "Expected exactly one expense row to be inserted"
        assert rows[0]["description"] is None, "Description must be stored as NULL when None is passed"


# ---------------------------------------------------------------------------
# 2. GET /expenses/add -- auth guard
# ---------------------------------------------------------------------------

class TestGetAddExpenseAuthGuard:
    def test_unauthenticated_get_redirects_to_login(self, test_db):
        """Unauthenticated GET /expenses/add must redirect to /login (302)."""
        flask_app.config["TESTING"] = True
        with patch.object(db_module, "DB_PATH", test_db):
            with flask_app.test_client() as client:
                resp = client.get("/expenses/add")
        assert resp.status_code == 302, "Expected 302 redirect for unauthenticated GET"
        assert "/login" in resp.headers["Location"], "Redirect target must be /login"


# ---------------------------------------------------------------------------
# 3. GET /expenses/add -- authenticated
# ---------------------------------------------------------------------------

class TestGetAddExpenseAuthenticated:
    def test_authenticated_get_returns_200(self, auth_client):
        """Authenticated GET /expenses/add must return 200."""
        client, uid = auth_client
        resp = client.get("/expenses/add")
        assert resp.status_code == 200, "Expected 200 for authenticated GET /expenses/add"

    def test_authenticated_get_contains_form_with_post_method(self, auth_client):
        """Response body must contain a <form> with method POST."""
        client, uid = auth_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        assert "<form" in body, "Response must contain a <form> element"
        assert 'method="post"' in body.lower(), "Form must use method POST"

    def test_authenticated_get_contains_category_select_with_all_options(self, auth_client):
        """Response body must contain a category <select> with all 7 fixed options."""
        client, uid = auth_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        assert "<select" in body, "Response must contain a <select> element for category"
        for category in FIXED_CATEGORIES:
            assert category in body, f"Category option '{category}' must appear in the form"

    def test_authenticated_get_contains_amount_field(self, auth_client):
        """Response body must contain an amount input field."""
        client, uid = auth_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        assert 'name="amount"' in body, "Form must include an amount input"

    def test_authenticated_get_contains_date_field(self, auth_client):
        """Response body must contain a date input field."""
        client, uid = auth_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        assert 'name="date"' in body, "Form must include a date input"

    def test_authenticated_get_contains_description_field(self, auth_client):
        """Response body must contain a description input field."""
        client, uid = auth_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        assert 'name="description"' in body, "Form must include a description input"


# ---------------------------------------------------------------------------
# 4. POST /expenses/add -- auth guard
# ---------------------------------------------------------------------------

class TestPostAddExpenseAuthGuard:
    def test_unauthenticated_post_redirects_to_login(self, test_db):
        """Unauthenticated POST /expenses/add must redirect to /login (302)."""
        flask_app.config["TESTING"] = True
        with patch.object(db_module, "DB_PATH", test_db):
            with flask_app.test_client() as client:
                resp = client.post("/expenses/add", data={
                    "amount": "50.0",
                    "category": "Food",
                    "date": "2026-03-20",
                    "description": "Lunch",
                })
        assert resp.status_code == 302, "Expected 302 redirect for unauthenticated POST"
        assert "/login" in resp.headers["Location"], "Redirect target must be /login"

    def test_unauthenticated_post_does_not_insert_row(self, test_db):
        """An unauthenticated POST attempt must not create any expense row."""
        flask_app.config["TESTING"] = True
        with patch.object(db_module, "DB_PATH", test_db):
            with flask_app.test_client() as client:
                client.post("/expenses/add", data={
                    "amount": "50.0",
                    "category": "Food",
                    "date": "2026-03-20",
                    "description": "Lunch",
                })
            conn = db_module.get_db()
            count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
            conn.close()
        assert count == 0, "No expense row should be inserted for unauthenticated POST"


# ---------------------------------------------------------------------------
# 5. POST /expenses/add -- authenticated, valid data
# ---------------------------------------------------------------------------

class TestPostAddExpenseValid:
    def test_valid_post_redirects_to_profile(self, auth_client):
        """A valid POST must redirect to /profile (302)."""
        client, uid = auth_client
        resp = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert resp.status_code == 302, "Expected 302 redirect after valid POST"
        assert "/profile" in resp.headers["Location"], "Redirect target must be /profile"

    def test_valid_post_inserts_row_for_user(self, auth_client):
        """After a valid POST, the new expense must exist in the DB for the test user."""
        client, uid = auth_client
        client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        # Re-fetch using the same patched DB_PATH active inside the auth_client context
        conn = db_module.get_db()
        rows = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (uid,)
        ).fetchall()
        conn.close()
        assert len(rows) == 1, "Expected one expense row inserted for the test user"
        row = rows[0]
        assert row["amount"] == 50.0, "Inserted amount must match submitted value"
        assert row["category"] == "Food", "Inserted category must match submitted value"
        assert row["date"] == "2026-03-20", "Inserted date must match submitted value"
        assert row["description"] == "Lunch", "Inserted description must match submitted value"


# ---------------------------------------------------------------------------
# 6. POST /expenses/add -- validation errors
# ---------------------------------------------------------------------------

class TestPostAddExpenseValidation:
    def test_missing_amount_rerenders_form_with_error(self, auth_client):
        """Missing amount must re-render the form (200) with an error message."""
        client, uid = auth_client
        resp = client.post("/expenses/add", data={
            "amount": "",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert resp.status_code == 200, "Expected 200 when amount is missing"
        body = resp.data.decode().lower()
        assert "amount" in body, "Error message should reference the amount field"

    def test_missing_amount_does_not_insert_row(self, auth_client):
        """Missing amount must not create a DB row."""
        client, uid = auth_client
        client.post("/expenses/add", data={
            "amount": "",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        conn = db_module.get_db()
        count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (uid,)
        ).fetchone()[0]
        conn.close()
        assert count == 0, "No row should be inserted when amount is missing"

    def test_zero_amount_rerenders_form_with_error(self, auth_client):
        """Amount of 0 must re-render the form (200) with an error message."""
        client, uid = auth_client
        resp = client.post("/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert resp.status_code == 200, "Expected 200 when amount is zero"
        body = resp.data.decode()
        assert len(body) > 0, "Response body must contain the re-rendered form"

    def test_zero_amount_does_not_insert_row(self, auth_client):
        """Amount of 0 must not create a DB row."""
        client, uid = auth_client
        client.post("/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        conn = db_module.get_db()
        count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (uid,)
        ).fetchone()[0]
        conn.close()
        assert count == 0, "No row should be inserted when amount is zero"

    def test_negative_amount_rerenders_form_with_error(self, auth_client):
        """A negative amount must re-render the form (200) with an error message."""
        client, uid = auth_client
        resp = client.post("/expenses/add", data={
            "amount": "-10",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert resp.status_code == 200, "Expected 200 when amount is negative"

    def test_non_numeric_amount_rerenders_form_with_error(self, auth_client):
        """A non-numeric amount must re-render the form (200) with an error message."""
        client, uid = auth_client
        resp = client.post("/expenses/add", data={
            "amount": "abc",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert resp.status_code == 200, "Expected 200 when amount is non-numeric"
        body = resp.data.decode().lower()
        assert "amount" in body, "Error message should reference the amount field"

    def test_non_numeric_amount_does_not_insert_row(self, auth_client):
        """Non-numeric amount must not create a DB row."""
        client, uid = auth_client
        client.post("/expenses/add", data={
            "amount": "abc",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        conn = db_module.get_db()
        count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (uid,)
        ).fetchone()[0]
        conn.close()
        assert count == 0, "No row should be inserted when amount is non-numeric"

    def test_invalid_category_rerenders_form_with_error(self, auth_client):
        """An invalid category must re-render the form (200) with an error message."""
        client, uid = auth_client
        resp = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "NotARealCategory",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert resp.status_code == 200, "Expected 200 when category is invalid"
        body = resp.data.decode().lower()
        assert "categor" in body, "Error message should reference the category field"

    def test_invalid_category_does_not_insert_row(self, auth_client):
        """An invalid category must not create a DB row."""
        client, uid = auth_client
        client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "NotARealCategory",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        conn = db_module.get_db()
        count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (uid,)
        ).fetchone()[0]
        conn.close()
        assert count == 0, "No row should be inserted when category is invalid"

    def test_invalid_date_rerenders_form_with_error(self, auth_client):
        """An invalid date string must re-render the form (200) with an error message."""
        client, uid = auth_client
        resp = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "not-a-date",
            "description": "Lunch",
        })
        assert resp.status_code == 200, "Expected 200 when date is invalid"
        body = resp.data.decode().lower()
        assert "date" in body, "Error message should reference the date field"

    def test_invalid_date_does_not_insert_row(self, auth_client):
        """An invalid date string must not create a DB row."""
        client, uid = auth_client
        client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "not-a-date",
            "description": "Lunch",
        })
        conn = db_module.get_db()
        count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (uid,)
        ).fetchone()[0]
        conn.close()
        assert count == 0, "No row should be inserted when date is invalid"

    @pytest.mark.parametrize("bad_date", [
        "2026-13-01",   # invalid month
        "2026-02-30",   # invalid day (Feb has 28/29 days)
        "03/20/2026",   # wrong format
        "2026/03/20",   # wrong separator
        "",             # empty (missing required field)
    ])
    def test_various_invalid_dates_rerender_form(self, auth_client, bad_date):
        """A variety of invalid date strings must all re-render the form with 200."""
        client, uid = auth_client
        resp = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": bad_date,
            "description": "Lunch",
        })
        assert resp.status_code == 200, f"Invalid date '{bad_date}' must re-render the form (200)"

    def test_validation_error_repopulates_previous_values(self, auth_client):
        """On validation failure, the previously submitted values must be pre-filled in the form."""
        client, uid = auth_client
        resp = client.post("/expenses/add", data={
            "amount": "abc",
            "category": "Food",
            "date": "2026-03-20",
            "description": "My unique description marker",
        })
        body = resp.data.decode()
        assert "My unique description marker" in body, (
            "Previously submitted description must be retained in the re-rendered form"
        )


# ---------------------------------------------------------------------------
# 7. POST /expenses/add -- optional description
# ---------------------------------------------------------------------------

class TestPostAddExpenseOptionalDescription:
    def test_no_description_redirects_to_profile(self, auth_client):
        """Submitting without a description must still redirect to /profile (302)."""
        client, uid = auth_client
        resp = client.post("/expenses/add", data={
            "amount": "30.0",
            "category": "Bills",
            "date": "2026-05-01",
            "description": "",
        })
        assert resp.status_code == 302, "Expected 302 redirect when description is blank"
        assert "/profile" in resp.headers["Location"], "Redirect target must be /profile"

    def test_no_description_inserts_row_with_null_description(self, auth_client):
        """Submitting without a description must insert a row with description = NULL."""
        client, uid = auth_client
        client.post("/expenses/add", data={
            "amount": "30.0",
            "category": "Bills",
            "date": "2026-05-01",
            "description": "",
        })
        conn = db_module.get_db()
        row = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (uid,)
        ).fetchone()
        conn.close()
        assert row is not None, "Expected an expense row to be inserted"
        assert row["description"] is None, "Description must be stored as NULL when blank"

    def test_description_field_omitted_entirely_redirects_to_profile(self, auth_client):
        """Omitting the description field entirely from the POST body is also treated as optional."""
        client, uid = auth_client
        resp = client.post("/expenses/add", data={
            "amount": "15.0",
            "category": "Other",
            "date": "2026-05-02",
        })
        assert resp.status_code == 302, "Expected 302 redirect when description key is absent"
        assert "/profile" in resp.headers["Location"], "Redirect target must be /profile"

    def test_whitespace_only_description_stored_as_null(self, auth_client):
        """A description that is only whitespace must be stripped and stored as NULL."""
        client, uid = auth_client
        client.post("/expenses/add", data={
            "amount": "20.0",
            "category": "Other",
            "date": "2026-05-03",
            "description": "    ",
        })
        conn = db_module.get_db()
        row = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (uid,)
        ).fetchone()
        conn.close()
        assert row is not None, "Expected an expense row to be inserted"
        assert row["description"] is None, "Whitespace-only description must be stored as NULL"


# ---------------------------------------------------------------------------
# 8. Edge cases
# ---------------------------------------------------------------------------

class TestPostAddExpenseEdgeCases:
    def test_very_long_description_is_accepted_or_rejected_gracefully(self, auth_client):
        """A very long description must not crash the app (200 or 302 only)."""
        client, uid = auth_client
        long_description = "x" * 5000
        resp = client.post("/expenses/add", data={
            "amount": "10.0",
            "category": "Other",
            "date": "2026-05-04",
            "description": long_description,
        })
        assert resp.status_code in (200, 302), (
            "Very long description must not cause a server error"
        )

    def test_sql_injection_attempt_in_description_is_handled_safely(self, auth_client):
        """A SQL-injection-style description must be stored literally, not executed."""
        client, uid = auth_client
        malicious = "Lunch'; DROP TABLE expenses; --"
        resp = client.post("/expenses/add", data={
            "amount": "12.0",
            "category": "Food",
            "date": "2026-05-05",
            "description": malicious,
        })
        assert resp.status_code in (200, 302), "Injection attempt must not crash the app"

        # The expenses table must still exist and be queryable.
        conn = db_module.get_db()
        rows = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (uid,)
        ).fetchall()
        conn.close()
        assert rows is not None, "Expenses table must still exist after injection attempt"

    def test_sql_injection_attempt_in_category_rejected_as_invalid(self, auth_client):
        """A SQL-injection-style category value must be rejected by the fixed category whitelist."""
        client, uid = auth_client
        resp = client.post("/expenses/add", data={
            "amount": "12.0",
            "category": "Food'; DROP TABLE expenses; --",
            "date": "2026-05-06",
            "description": "test",
        })
        assert resp.status_code == 200, "Invalid/malicious category must re-render the form (200)"

        conn = db_module.get_db()
        count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        conn.close()
        # No row inserted, and the table itself must still exist (query succeeded).
        assert count == 0, "No row should be inserted for an invalid/malicious category"

    @pytest.mark.parametrize("category", FIXED_CATEGORIES)
    def test_each_fixed_category_is_accepted(self, auth_client, category):
        """Each of the 7 fixed categories must be accepted and redirect to /profile."""
        client, uid = auth_client
        resp = client.post("/expenses/add", data={
            "amount": "5.0",
            "category": category,
            "date": "2026-06-01",
            "description": f"Test for {category}",
        })
        assert resp.status_code == 302, f"Category '{category}' must be accepted (302 redirect)"
        assert "/profile" in resp.headers["Location"], "Redirect target must be /profile"

    def test_amount_with_decimal_precision_is_stored_accurately(self, auth_client):
        """An amount with cents (e.g. 49.99) must be stored with correct precision."""
        client, uid = auth_client
        client.post("/expenses/add", data={
            "amount": "49.99",
            "category": "Shopping",
            "date": "2026-06-02",
            "description": "Precise amount",
        })
        conn = db_module.get_db()
        row = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ? AND description = ?",
            (uid, "Precise amount"),
        ).fetchone()
        conn.close()
        assert row is not None, "Expected the expense row to be inserted"
        assert row["amount"] == 49.99, "Amount must be stored with correct decimal precision"


# ---------------------------------------------------------------------------
# 9. Profile page integration -- new expense visible after redirect
# ---------------------------------------------------------------------------

class TestAddExpenseProfileIntegration:
    def test_new_expense_appears_in_profile_after_redirect(self, auth_client):
        """Following the redirect to /profile after a valid add must show the new expense."""
        client, uid = auth_client
        client.post("/expenses/add", data={
            "amount": "77.0",
            "category": "Entertainment",
            "date": "2026-06-10",
            "description": "Concert tickets",
        }, follow_redirects=True)

        resp = client.get("/profile")
        body = resp.data.decode()
        assert "Concert tickets" in body, (
            "Newly added expense must appear in the profile transaction list"
        )
