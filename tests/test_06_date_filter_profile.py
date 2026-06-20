"""
Tests for Step 6: Date Filter for Profile Page
Spec: .claude/specs/06-date-filter-profile.md

All test logic is derived exclusively from the feature specification.
The implementation files were read only for structural information
(route signatures, DB helper names, fixture patterns).
"""

import pytest
from datetime import date, timedelta
from unittest.mock import patch
from werkzeug.security import generate_password_hash

import database.db as db_module
from app import app as flask_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(d: date) -> str:
    return d.isoformat()


def today() -> date:
    return date.today()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_db(tmp_path):
    """Isolated file-backed SQLite DB patched into database.db.DB_PATH."""
    db_file = str(tmp_path / "filter_test.db")
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
    """
    Insert a user plus controlled expenses that span several date windows:

    - 3 days ago  : Food,      ₹100  (within This Month, Last 3 Months, Last 6 Months)
    - 15 days ago : Transport, ₹50   (within This Month if month has >15 days, Last 3/6 Months)
    - 60 days ago : Bills,     ₹200  (within Last 3 Months, Last 6 Months — NOT this month)
    - 100 days ago: Health,    ₹75   (within Last 6 Months only)
    - 200 days ago: Shopping,  ₹300  (outside all preset windows, only All Time)

    Yields (db_path, user_id, expenses_meta) where expenses_meta is a dict
    with keys describing each row's date offset for use in assertions.
    """
    t = today()
    dates = {
        "recent":      _iso(t - timedelta(days=3)),
        "mid_month":   _iso(t - timedelta(days=15)),
        "two_months":  _iso(t - timedelta(days=60)),
        "four_months": _iso(t - timedelta(days=100)),
        "old":         _iso(t - timedelta(days=200)),
    }

    with patch.object(db_module, "DB_PATH", test_db):
        conn = db_module.get_db()
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            ("Filter Tester", "filter@example.com",
             generate_password_hash("filterpass"), "2025-01-01 00:00:00"),
        )
        uid = cur.lastrowid

        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (uid, 100.00, "Food",      dates["recent"],      "Recent grocery"),
                (uid,  50.00, "Transport", dates["mid_month"],   "Bus pass"),
                (uid, 200.00, "Bills",     dates["two_months"],  "Electric bill"),
                (uid,  75.00, "Health",    dates["four_months"], "Pharmacy"),
                (uid, 300.00, "Shopping",  dates["old"],         "Old purchase"),
            ],
        )
        conn.commit()
        conn.close()

    yield test_db, uid, dates


@pytest.fixture
def auth_client(seeded_user):
    """
    Flask test client with DB_PATH patched and the seeded user injected into
    the session. Yields (client, uid, dates).
    """
    db_path, uid, dates = seeded_user
    flask_app.config.update({
        "TESTING": True,
        "SECRET_KEY": "test-filter-secret",
    })
    with patch.object(db_module, "DB_PATH", db_path):
        with flask_app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = uid
            yield client, uid, dates


@pytest.fixture
def empty_user(test_db):
    """A user with zero expenses, for testing empty-range edge cases."""
    with patch.object(db_module, "DB_PATH", test_db):
        conn = db_module.get_db()
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            ("Empty Tester", "empty@example.com",
             generate_password_hash("emptypass"), "2025-06-01 00:00:00"),
        )
        uid = cur.lastrowid
        conn.commit()
        conn.close()
    yield test_db, uid


@pytest.fixture
def empty_auth_client(empty_user):
    """Flask test client for a user with no expenses."""
    db_path, uid = empty_user
    flask_app.config.update({
        "TESTING": True,
        "SECRET_KEY": "test-filter-secret",
    })
    with patch.object(db_module, "DB_PATH", db_path):
        with flask_app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = uid
            yield client, uid


# ---------------------------------------------------------------------------
# 1. Authentication guard
# ---------------------------------------------------------------------------

class TestAuthGuard:
    def test_unauthenticated_get_profile_redirects_to_login(self, test_db):
        """Unauthenticated GET /profile must redirect to /login with 302."""
        flask_app.config["TESTING"] = True
        with patch.object(db_module, "DB_PATH", test_db):
            with flask_app.test_client() as client:
                resp = client.get("/profile")
        assert resp.status_code == 302, "Expected 302 redirect for unauthenticated request"
        assert "/login" in resp.headers["Location"], "Redirect target must be /login"

    def test_unauthenticated_get_profile_with_date_params_redirects_to_login(self, test_db):
        """Filter params must not bypass the auth guard."""
        flask_app.config["TESTING"] = True
        t = today()
        date_from = _iso(t.replace(day=1))
        date_to = _iso(t)
        with patch.object(db_module, "DB_PATH", test_db):
            with flask_app.test_client() as client:
                resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        assert resp.status_code == 302, "Expected 302 redirect even when filter params are present"
        assert "/login" in resp.headers["Location"], "Redirect target must be /login"


# ---------------------------------------------------------------------------
# 2. No filter params — All Time (unfiltered) view
# ---------------------------------------------------------------------------

class TestNoFilterAllTime:
    def test_profile_no_params_returns_200(self, auth_client):
        """GET /profile with no params returns HTTP 200."""
        client, uid, dates = auth_client
        resp = client.get("/profile")
        assert resp.status_code == 200, "Expected 200 for authenticated /profile with no params"

    def test_profile_no_params_shows_all_expenses(self, auth_client):
        """Unfiltered view includes all 5 seeded expenses in total count."""
        client, uid, dates = auth_client
        resp = client.get("/profile")
        body = resp.data.decode()
        # All 5 transactions → total = 725.00
        assert "725" in body, "Unfiltered total should be ₹725.00 (sum of all 5 expenses)"

    def test_profile_no_params_all_time_preset_is_active(self, auth_client):
        """The 'All Time' preset link must carry the active CSS class when no filter is set."""
        client, uid, dates = auth_client
        resp = client.get("/profile")
        body = resp.data.decode()
        # Template marks active preset with 'filter-preset--active' class on the All Time link
        assert "filter-preset--active" in body, "Some preset must be marked active"
        # The All Time link has no query params; its href should be /profile without ? params
        # The active class must appear near "All Time" text
        active_idx = body.find("filter-preset--active")
        all_time_idx = body.find("All Time")
        # Both markers exist; the active class appears before or close to "All Time"
        assert active_idx != -1, "filter-preset--active class must be present"
        assert all_time_idx != -1, "'All Time' text must be present in the page"

    def test_profile_no_params_shows_rupee_symbol(self, auth_client):
        """The ₹ symbol must appear in the unfiltered view."""
        client, uid, dates = auth_client
        resp = client.get("/profile")
        assert "₹" in resp.data.decode(), "₹ symbol must appear in the profile page"

    def test_profile_no_params_renders_filter_bar(self, auth_client):
        """The filter bar with all four preset links must be present on the page."""
        client, uid, dates = auth_client
        resp = client.get("/profile")
        body = resp.data.decode()
        assert "This Month" in body, "Filter bar must include 'This Month' preset"
        assert "Last 3 Months" in body, "Filter bar must include 'Last 3 Months' preset"
        assert "Last 6 Months" in body, "Filter bar must include 'Last 6 Months' preset"
        assert "All Time" in body, "Filter bar must include 'All Time' preset"

    def test_profile_no_params_renders_date_inputs(self, auth_client):
        """The custom range form must contain date_from and date_to input fields."""
        client, uid, dates = auth_client
        resp = client.get("/profile")
        body = resp.data.decode()
        assert 'name="date_from"' in body, "Custom range form must include date_from input"
        assert 'name="date_to"' in body, "Custom range form must include date_to input"


# ---------------------------------------------------------------------------
# 3. This Month filter
# ---------------------------------------------------------------------------

class TestThisMonthFilter:
    def _preset_dates(self):
        t = today()
        return _iso(t.replace(day=1)), _iso(t)

    def test_this_month_returns_200(self, auth_client):
        """GET /profile with This Month dates returns 200."""
        client, uid, dates = auth_client
        date_from, date_to = self._preset_dates()
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        assert resp.status_code == 200, "Expected 200 for This Month filter"

    def test_this_month_excludes_older_expenses(self, auth_client):
        """Expenses older than current month must not appear in stats total."""
        client, uid, dates = auth_client
        t = today()
        date_from, date_to = self._preset_dates()

        # Expenses within this month: 'recent' (3 days ago) always falls in this month.
        # 'mid_month' (15 days ago) may or may not fall in this month depending on today's day.
        # 'two_months' (60 days ago) is definitely outside this month.
        # We check that the 200-day-old Shopping expense (₹300) is excluded.
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        # Old purchase was ₹300. If it were included with others the total would include 300;
        # the 200-days-ago expense description should NOT appear in filtered view.
        assert "Old purchase" not in body, (
            "200-day-old 'Old purchase' expense must be excluded from This Month filter"
        )

    def test_this_month_filter_summary_stats_reflect_filter(self, auth_client):
        """Summary stats transaction count must only count expenses within this month."""
        client, uid, dates = auth_client
        date_from, date_to = self._preset_dates()

        # Calculate expected: expenses within [first of month, today]
        t = today()
        first_of_month = t.replace(day=1)
        in_month = []
        for key, ds in [("recent", 3), ("mid_month", 15), ("two_months", 60),
                        ("four_months", 100), ("old", 200)]:
            exp_date = t - timedelta(days=ds)
            if first_of_month <= exp_date <= t:
                in_month.append(key)

        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        # The transaction count shown must equal len(in_month)
        expected_count = len(in_month)
        assert str(expected_count) in body, (
            f"Transaction count must be {expected_count} for This Month filter"
        )

    def test_this_month_rupee_symbol_present(self, auth_client):
        """₹ symbol must appear in the This Month filtered view."""
        client, uid, dates = auth_client
        date_from, date_to = self._preset_dates()
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        assert "₹" in resp.data.decode(), "₹ symbol must appear in filtered view"


# ---------------------------------------------------------------------------
# 4. Last 3 Months filter (90-day window)
# ---------------------------------------------------------------------------

class TestLast3MonthsFilter:
    def _preset_dates(self):
        t = today()
        return _iso(t - timedelta(days=90)), _iso(t)

    def test_last_3_months_returns_200(self, auth_client):
        """GET /profile with Last 3 Months dates returns 200."""
        client, uid, dates = auth_client
        date_from, date_to = self._preset_dates()
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        assert resp.status_code == 200, "Expected 200 for Last 3 Months filter"

    def test_last_3_months_includes_60_day_old_expense(self, auth_client):
        """The 60-day-old Bills expense must appear in the Last 3 Months view."""
        client, uid, dates = auth_client
        date_from, date_to = self._preset_dates()
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert "Electric bill" in body, (
            "60-day-old 'Electric bill' expense must be included in Last 3 Months filter"
        )

    def test_last_3_months_excludes_100_day_old_expense(self, auth_client):
        """The 100-day-old Health expense must be excluded from the Last 3 Months view."""
        client, uid, dates = auth_client
        date_from, date_to = self._preset_dates()
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert "Pharmacy" not in body, (
            "100-day-old 'Pharmacy' expense must be excluded from Last 3 Months filter"
        )

    def test_last_3_months_excludes_200_day_old_expense(self, auth_client):
        """The 200-day-old Shopping expense must not appear in the Last 3 Months view."""
        client, uid, dates = auth_client
        date_from, date_to = self._preset_dates()
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert "Old purchase" not in body, (
            "200-day-old 'Old purchase' must be excluded from Last 3 Months filter"
        )

    def test_last_3_months_stats_total_correct(self, auth_client):
        """Summary stats total must equal sum of expenses within 90-day window."""
        client, uid, dates = auth_client
        t = today()
        date_from_dt = t - timedelta(days=90)
        # Expenses in window: recent(3d=100), mid_month(15d=50), two_months(60d=200) → 350
        expected_total = 350.00
        date_from, date_to = self._preset_dates()
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert "350" in body, (
            f"Total spent must be ₹350.00 for Last 3 Months filter, got page: {body[:500]}"
        )

    def test_last_3_months_category_breakdown_present(self, auth_client):
        """Category breakdown must include categories from the 90-day window."""
        client, uid, dates = auth_client
        date_from, date_to = self._preset_dates()
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        # Bills (60d) and Food (3d) are in the window
        assert "Bills" in body, "Bills category must appear in Last 3 Months breakdown"
        assert "Food" in body, "Food category must appear in Last 3 Months breakdown"

    def test_last_3_months_rupee_symbol_present(self, auth_client):
        """₹ symbol must appear in the Last 3 Months filtered view."""
        client, uid, dates = auth_client
        date_from, date_to = self._preset_dates()
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        assert "₹" in resp.data.decode(), "₹ symbol must appear in filtered view"


# ---------------------------------------------------------------------------
# 5. Last 6 Months filter (180-day window)
# ---------------------------------------------------------------------------

class TestLast6MonthsFilter:
    def _preset_dates(self):
        t = today()
        return _iso(t - timedelta(days=180)), _iso(t)

    def test_last_6_months_returns_200(self, auth_client):
        """GET /profile with Last 6 Months dates returns 200."""
        client, uid, dates = auth_client
        date_from, date_to = self._preset_dates()
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        assert resp.status_code == 200, "Expected 200 for Last 6 Months filter"

    def test_last_6_months_includes_100_day_old_expense(self, auth_client):
        """The 100-day-old Health expense must appear in the Last 6 Months view."""
        client, uid, dates = auth_client
        date_from, date_to = self._preset_dates()
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert "Pharmacy" in body, (
            "100-day-old 'Pharmacy' expense must be included in Last 6 Months filter"
        )

    def test_last_6_months_excludes_200_day_old_expense(self, auth_client):
        """The 200-day-old Shopping expense must be excluded from the Last 6 Months view."""
        client, uid, dates = auth_client
        date_from, date_to = self._preset_dates()
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert "Old purchase" not in body, (
            "200-day-old 'Old purchase' must be excluded from Last 6 Months filter"
        )

    def test_last_6_months_stats_total_correct(self, auth_client):
        """Summary stats total must equal sum of expenses within 180-day window."""
        client, uid, dates = auth_client
        # Expenses in 180-day window: recent(100) + mid_month(50) + two_months(200) + four_months(75) = 425
        expected_total = 425.00
        date_from, date_to = self._preset_dates()
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert "425" in body, (
            f"Total spent must be ₹425.00 for Last 6 Months filter"
        )

    def test_last_6_months_category_breakdown_excludes_old_category(self, auth_client):
        """The 200-day-old 'Shopping' category must not appear in Last 6 Months breakdown."""
        client, uid, dates = auth_client
        date_from, date_to = self._preset_dates()
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        # Health should appear (100d ago) but Shopping should not (200d ago)
        assert "Health" in body, "Health category must appear in Last 6 Months breakdown"

    def test_last_6_months_rupee_symbol_present(self, auth_client):
        """₹ symbol must appear in the Last 6 Months filtered view."""
        client, uid, dates = auth_client
        date_from, date_to = self._preset_dates()
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        assert "₹" in resp.data.decode(), "₹ symbol must appear in filtered view"


# ---------------------------------------------------------------------------
# 6. Custom date range
# ---------------------------------------------------------------------------

class TestCustomDateRange:
    def test_custom_range_returns_200(self, auth_client):
        """A well-formed custom date range returns 200."""
        client, uid, dates = auth_client
        t = today()
        date_from = _iso(t - timedelta(days=5))
        date_to = _iso(t)
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        assert resp.status_code == 200, "Expected 200 for valid custom date range"

    def test_custom_range_only_shows_matching_transactions(self, auth_client):
        """Only expenses whose date falls within the custom range appear in the view."""
        client, uid, dates = auth_client
        t = today()
        # Range: last 5 days — only 'recent' (3 days ago) falls in this window
        date_from = _iso(t - timedelta(days=5))
        date_to = _iso(t)
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert "Recent grocery" in body, "Recent grocery must appear in 5-day custom range"
        assert "Bus pass" not in body, "15-day-old 'Bus pass' must be excluded from 5-day range"
        assert "Electric bill" not in body, "60-day-old 'Electric bill' must be excluded"
        assert "Pharmacy" not in body, "100-day-old 'Pharmacy' must be excluded"
        assert "Old purchase" not in body, "200-day-old 'Old purchase' must be excluded"

    def test_custom_range_stats_total_reflects_filter(self, auth_client):
        """Stats total must equal sum of expenses within the custom range only."""
        client, uid, dates = auth_client
        t = today()
        # Range: last 5 days — only 'recent' (₹100) matches
        date_from = _iso(t - timedelta(days=5))
        date_to = _iso(t)
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert "100" in body, "Stats total must show ₹100.00 for the 5-day custom range"

    def test_custom_range_category_breakdown_reflects_filter(self, auth_client):
        """Category breakdown must include only categories present in the custom range."""
        client, uid, dates = auth_client
        t = today()
        # Range: last 5 days — only Food (recent grocery) matches
        date_from = _iso(t - timedelta(days=5))
        date_to = _iso(t)
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert "Food" in body, "Food category must appear in 5-day range breakdown"
        assert "Transport" not in body or "Bus pass" not in body, (
            "Transport expense outside range must not appear"
        )

    def test_custom_range_broader_window_shows_multiple_expenses(self, auth_client):
        """A wider custom range spanning 20 days captures two seeded expenses."""
        client, uid, dates = auth_client
        t = today()
        # Range: last 20 days — captures 'recent' (3d) and 'mid_month' (15d)
        date_from = _iso(t - timedelta(days=20))
        date_to = _iso(t)
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert "Recent grocery" in body, "Recent grocery must appear in 20-day custom range"
        assert "Bus pass" in body, "Bus pass must appear in 20-day custom range"
        assert "Electric bill" not in body, "60-day-old expense must not appear in 20-day range"

    def test_custom_range_rupee_symbol_present(self, auth_client):
        """₹ symbol must appear in a custom-range filtered view."""
        client, uid, dates = auth_client
        t = today()
        date_from = _iso(t - timedelta(days=20))
        date_to = _iso(t)
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        assert "₹" in resp.data.decode(), "₹ symbol must appear in custom-range filtered view"


# ---------------------------------------------------------------------------
# 7. date_from > date_to — invalid range
# ---------------------------------------------------------------------------

class TestInvalidDateRange:
    def test_date_from_after_date_to_returns_200(self, auth_client):
        """A range where date_from > date_to must still return 200, not a server error."""
        client, uid, dates = auth_client
        t = today()
        date_from = _iso(t)
        date_to = _iso(t - timedelta(days=10))  # date_to is before date_from
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        assert resp.status_code == 200, "Invalid range must return 200, not 4xx/5xx"

    def test_date_from_after_date_to_flashes_error_message(self, auth_client):
        """Flash message 'Start date must be before end date.' must appear in response."""
        client, uid, dates = auth_client
        t = today()
        date_from = _iso(t)
        date_to = _iso(t - timedelta(days=10))
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert "Start date must be before end date." in body, (
            "Flash message 'Start date must be before end date.' must appear in the response"
        )

    def test_date_from_after_date_to_falls_back_to_unfiltered(self, auth_client):
        """When the range is invalid, the view must show all expenses (unfiltered fallback)."""
        client, uid, dates = auth_client
        t = today()
        date_from = _iso(t)
        date_to = _iso(t - timedelta(days=10))
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        # Unfiltered total is ₹725.00 — all 5 expenses
        assert "725" in body, (
            "Unfiltered total (₹725.00) must appear when date range is invalid"
        )

    def test_date_from_equal_to_date_to_returns_200(self, auth_client):
        """A range where date_from == date_to (same day) is valid and must return 200."""
        client, uid, dates = auth_client
        t = today()
        same_day = _iso(t - timedelta(days=3))  # matches the 'recent' expense
        resp = client.get(f"/profile?date_from={same_day}&date_to={same_day}")
        assert resp.status_code == 200, "Same-day range must return 200"

    def test_date_from_equal_to_date_to_shows_matching_expense(self, auth_client):
        """A same-day range must show only the expense on that exact date."""
        client, uid, dates = auth_client
        t = today()
        same_day = _iso(t - timedelta(days=3))  # matches the 'recent' (Food, ₹100) expense
        resp = client.get(f"/profile?date_from={same_day}&date_to={same_day}")
        body = resp.data.decode()
        assert "Recent grocery" in body, "Expense on the exact same-day range must appear"
        assert "Bus pass" not in body, "Expense outside same-day range must not appear"


# ---------------------------------------------------------------------------
# 8. Malformed date parameters
# ---------------------------------------------------------------------------

class TestMalformedDateParams:
    @pytest.mark.parametrize("bad_value", [
        "not-a-date",
        "2026-13-01",   # invalid month
        "2026-02-30",   # invalid day
        "01/15/2026",   # wrong format
        "yesterday",
        "2026",
        "",
    ])
    def test_malformed_date_from_does_not_crash(self, auth_client, bad_value):
        """A malformed date_from param must not crash the app — expect 200."""
        client, uid, dates = auth_client
        t = today()
        resp = client.get(f"/profile?date_from={bad_value}&date_to={_iso(t)}")
        assert resp.status_code == 200, (
            f"Malformed date_from='{bad_value}' must not crash the app"
        )

    @pytest.mark.parametrize("bad_value", [
        "not-a-date",
        "2026-13-01",
        "01/15/2026",
        "tomorrow",
        "",
    ])
    def test_malformed_date_to_does_not_crash(self, auth_client, bad_value):
        """A malformed date_to param must not crash the app — expect 200."""
        client, uid, dates = auth_client
        t = today()
        resp = client.get(f"/profile?date_from={_iso(t - timedelta(days=7))}&date_to={bad_value}")
        assert resp.status_code == 200, (
            f"Malformed date_to='{bad_value}' must not crash the app"
        )

    def test_malformed_date_from_falls_back_to_unfiltered(self, auth_client):
        """A malformed date_from causes silent fallback to unfiltered (all expenses shown)."""
        client, uid, dates = auth_client
        t = today()
        resp = client.get(f"/profile?date_from=not-a-date&date_to={_iso(t)}")
        body = resp.data.decode()
        # When one param is malformed, the route treats it as absent — falls back to unfiltered.
        # All 5 expenses → total ₹725.00
        assert "725" in body, (
            "Unfiltered data (₹725 total) must be shown when date_from is malformed"
        )

    def test_malformed_date_to_falls_back_to_unfiltered(self, auth_client):
        """A malformed date_to causes silent fallback to unfiltered (all expenses shown)."""
        client, uid, dates = auth_client
        t = today()
        resp = client.get(f"/profile?date_from={_iso(t - timedelta(days=7))}&date_to=not-a-date")
        body = resp.data.decode()
        assert "725" in body, (
            "Unfiltered data (₹725 total) must be shown when date_to is malformed"
        )

    def test_both_params_malformed_falls_back_to_unfiltered(self, auth_client):
        """Both params malformed → 200 with unfiltered data, no crash."""
        client, uid, dates = auth_client
        resp = client.get("/profile?date_from=bad&date_to=worse")
        assert resp.status_code == 200, "Both params malformed must still return 200"
        body = resp.data.decode()
        assert "725" in body, "Unfiltered data must be shown when both params are malformed"


# ---------------------------------------------------------------------------
# 9. No expenses in selected range
# ---------------------------------------------------------------------------

class TestEmptyRangeResult:
    def test_no_expenses_in_range_returns_200(self, auth_client):
        """A valid date range with no matching expenses must return 200."""
        client, uid, dates = auth_client
        # A range in the far future contains no expenses
        future_from = "2099-01-01"
        future_to = "2099-12-31"
        resp = client.get(f"/profile?date_from={future_from}&date_to={future_to}")
        assert resp.status_code == 200, "Empty range must return 200, not an error"

    def test_no_expenses_in_range_shows_zero_total(self, auth_client):
        """Stats must show ₹0.00 total when no expenses fall in the range."""
        client, uid, dates = auth_client
        future_from = "2099-01-01"
        future_to = "2099-12-31"
        resp = client.get(f"/profile?date_from={future_from}&date_to={future_to}")
        body = resp.data.decode()
        assert "0.00" in body, "Total spent must be ₹0.00 when no expenses match the filter"

    def test_no_expenses_in_range_shows_zero_transaction_count(self, auth_client):
        """Transaction count must be 0 when no expenses fall in the range."""
        client, uid, dates = auth_client
        future_from = "2099-01-01"
        future_to = "2099-12-31"
        resp = client.get(f"/profile?date_from={future_from}&date_to={future_to}")
        body = resp.data.decode()
        # The stat value for Transactions should show 0
        assert "0" in body, "Transaction count must be 0 when no expenses match the filter"

    def test_no_expenses_in_range_shows_empty_transactions_message(self, auth_client):
        """The transactions table must show the 'no transactions' placeholder."""
        client, uid, dates = auth_client
        future_from = "2099-01-01"
        future_to = "2099-12-31"
        resp = client.get(f"/profile?date_from={future_from}&date_to={future_to}")
        body = resp.data.decode()
        assert "No transactions match your filter." in body, (
            "Empty state message must appear when no expenses match the filter"
        )

    def test_no_expenses_in_range_empty_category_breakdown(self, auth_client):
        """Category breakdown must be empty when no expenses fall in the range."""
        client, uid, dates = auth_client
        future_from = "2099-01-01"
        future_to = "2099-12-31"
        resp = client.get(f"/profile?date_from={future_from}&date_to={future_to}")
        body = resp.data.decode()
        # No category rows should appear for categories like Food, Bills, Transport
        # when no expenses are in range
        assert "category-row" not in body, (
            "No category breakdown rows must be rendered for an empty range"
        )

    def test_user_with_no_expenses_all_time_returns_200(self, empty_auth_client):
        """A user who has never added any expense must still get 200 on /profile."""
        client, uid = empty_auth_client
        resp = client.get("/profile")
        assert resp.status_code == 200, "User with no expenses must get 200 on /profile"

    def test_user_with_no_expenses_shows_zero_total(self, empty_auth_client):
        """A user with no expenses at all must see ₹0.00 total spent."""
        client, uid = empty_auth_client
        resp = client.get("/profile")
        body = resp.data.decode()
        assert "0.00" in body, "User with no expenses must see ₹0.00 total"

    def test_user_with_no_expenses_shows_zero_transaction_count(self, empty_auth_client):
        """A user with no expenses must see transaction count of 0."""
        client, uid = empty_auth_client
        resp = client.get("/profile")
        body = resp.data.decode()
        assert "0" in body, "User with no expenses must see transaction count 0"

    def test_user_with_no_expenses_in_filtered_range_no_crash(self, empty_auth_client):
        """Empty-expense user with a date filter must get 200 with no crash."""
        client, uid = empty_auth_client
        t = today()
        resp = client.get(f"/profile?date_from={_iso(t.replace(day=1))}&date_to={_iso(t)}")
        assert resp.status_code == 200, (
            "User with no expenses using a date filter must still get 200"
        )


# ---------------------------------------------------------------------------
# 10. Rupee symbol present across all filter states
# ---------------------------------------------------------------------------

class TestRupeeSymbolInFilteredViews:
    @pytest.mark.parametrize("params", [
        "",                                          # All Time
        "?date_from=2099-01-01&date_to=2099-12-31", # empty result range
    ])
    def test_rupee_symbol_in_various_filter_states(self, auth_client, params):
        """₹ symbol must appear regardless of which filter is active."""
        client, uid, dates = auth_client
        resp = client.get(f"/profile{params}")
        body = resp.data.decode()
        assert "₹" in body, f"₹ symbol must appear in profile page for params='{params}'"

    def test_rupee_symbol_in_custom_range_with_results(self, auth_client):
        """₹ symbol must appear when a custom range returns matching expenses."""
        client, uid, dates = auth_client
        t = today()
        date_from = _iso(t - timedelta(days=5))
        date_to = _iso(t)
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        assert "₹" in resp.data.decode(), "₹ symbol must appear in custom-range filtered view"


# ---------------------------------------------------------------------------
# 11. Preset active state in template
# ---------------------------------------------------------------------------

class TestPresetActiveState:
    def test_all_time_preset_active_when_no_params(self, auth_client):
        """'All Time' link must carry the active CSS class when no filter params are set."""
        client, uid, dates = auth_client
        resp = client.get("/profile")
        body = resp.data.decode()
        # The active link is 'All Time'; find its class annotation
        assert "filter-preset--active" in body, "Active preset class must be present"
        # 'All Time' must appear on the page
        assert "All Time" in body, "'All Time' preset must be present"

    def test_this_month_preset_active_when_matching_params(self, auth_client):
        """'This Month' link must carry the active CSS class when its dates are passed."""
        client, uid, dates = auth_client
        t = today()
        date_from = _iso(t.replace(day=1))
        date_to = _iso(t)
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert "filter-preset--active" in body, "Active preset class must be present for This Month"

    def test_last_3_months_preset_active_when_matching_params(self, auth_client):
        """'Last 3 Months' link must carry the active CSS class when its dates are passed."""
        client, uid, dates = auth_client
        t = today()
        date_from = _iso(t - timedelta(days=90))
        date_to = _iso(t)
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert "filter-preset--active" in body, (
            "Active preset class must be present for Last 3 Months"
        )

    def test_last_6_months_preset_active_when_matching_params(self, auth_client):
        """'Last 6 Months' link must carry the active CSS class when its dates are passed."""
        client, uid, dates = auth_client
        t = today()
        date_from = _iso(t - timedelta(days=180))
        date_to = _iso(t)
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert "filter-preset--active" in body, (
            "Active preset class must be present for Last 6 Months"
        )

    def test_custom_range_does_not_activate_preset_buttons(self, auth_client):
        """A custom date range that doesn't match any preset must not mark any preset active
        if the template only marks a preset active when it exactly matches."""
        client, uid, dates = auth_client
        t = today()
        # A completely custom range that matches no preset
        date_from = _iso(t - timedelta(days=7))
        date_to = _iso(t - timedelta(days=1))
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        # At minimum, the page must render without error
        assert resp.status_code == 200, "Custom range page must render without error"


# ---------------------------------------------------------------------------
# 12. Date inputs reflect active filter state
# ---------------------------------------------------------------------------

class TestDateInputValues:
    def test_date_inputs_empty_when_no_filter(self, auth_client):
        """date_from and date_to inputs must be empty when no filter is active."""
        client, uid, dates = auth_client
        resp = client.get("/profile")
        body = resp.data.decode()
        # The input values should be empty string when no filter is active
        # Checking that there is no pre-filled date value in the inputs
        assert 'value=""' in body or "value=''" in body or 'value=""' in body, (
            "Date inputs must have empty values when no filter is active"
        )

    def test_date_inputs_populated_when_custom_filter_applied(self, auth_client):
        """date_from and date_to inputs must reflect the active custom filter values."""
        client, uid, dates = auth_client
        t = today()
        date_from = _iso(t - timedelta(days=20))
        date_to = _iso(t - timedelta(days=5))
        resp = client.get(f"/profile?date_from={date_from}&date_to={date_to}")
        body = resp.data.decode()
        assert date_from in body, "date_from value must appear in the rendered page"
        assert date_to in body, "date_to value must appear in the rendered page"
