import sqlite3
import pytest
from unittest.mock import patch

import database.db as db_module
from database.queries import (
    get_category_breakdown,
    get_recent_transactions,
    get_summary_stats,
    get_user_by_id,
)
from app import app as flask_app
from werkzeug.security import generate_password_hash


@pytest.fixture
def test_db(tmp_path):
    """In-memory SQLite DB patched into database.db.DB_PATH."""
    db_file = str(tmp_path / "test.db")
    with patch.object(db_module, "DB_PATH", db_file):
        conn = db_module.get_db()
        conn.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL,
                description TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.commit()
        conn.close()
        yield db_file


@pytest.fixture
def seeded_user(test_db):
    """Insert a user + 3 expenses; yield (db_path, user_id)."""
    with patch.object(db_module, "DB_PATH", test_db):
        conn = db_module.get_db()
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            ("Test User", "test@example.com", generate_password_hash("password"), "2026-01-15 10:00:00"),
        )
        uid = cur.lastrowid
        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
            [
                (uid, 100.00, "Bills",     "2026-06-10", "Electric"),
                (uid,  50.00, "Food",      "2026-06-08", "Grocery"),
                (uid,  20.00, "Transport", "2026-06-05", "Bus"),
            ],
        )
        conn.commit()
        conn.close()
    return test_db, uid


# ── get_user_by_id ────────────────────────────────────────────────────────────

def test_get_user_by_id_valid(seeded_user):
    db_path, uid = seeded_user
    with patch.object(db_module, "DB_PATH", db_path):
        user = get_user_by_id(uid)
    assert user["name"] == "Test User"
    assert user["email"] == "test@example.com"
    assert user["member_since"] == "January 2026"


def test_get_user_by_id_nonexistent(test_db):
    with patch.object(db_module, "DB_PATH", test_db):
        assert get_user_by_id(9999) is None


# ── get_summary_stats ─────────────────────────────────────────────────────────

def test_get_summary_stats_with_expenses(seeded_user):
    db_path, uid = seeded_user
    with patch.object(db_module, "DB_PATH", db_path):
        stats = get_summary_stats(uid)
    assert stats["total_spent"] == pytest.approx(170.00)
    assert stats["transaction_count"] == 3
    assert stats["top_category"] == "Bills"


def test_get_summary_stats_no_expenses(test_db):
    with patch.object(db_module, "DB_PATH", test_db):
        conn = db_module.get_db()
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Empty User", "empty@example.com", generate_password_hash("pw")),
        )
        uid = cur.lastrowid
        conn.commit()
        conn.close()
        stats = get_summary_stats(uid)
    assert stats == {"total_spent": 0, "transaction_count": 0, "top_category": "—"}


# ── get_recent_transactions ───────────────────────────────────────────────────

def test_get_recent_transactions_ordered_newest_first(seeded_user):
    db_path, uid = seeded_user
    with patch.object(db_module, "DB_PATH", db_path):
        txns = get_recent_transactions(uid)
    assert len(txns) == 3
    dates = [t["date"] for t in txns]
    assert dates == sorted(dates, reverse=True)
    assert all(k in txns[0] for k in ("date", "description", "category", "amount"))


def test_get_recent_transactions_no_expenses(test_db):
    with patch.object(db_module, "DB_PATH", test_db):
        conn = db_module.get_db()
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Empty", "e2@example.com", generate_password_hash("pw")),
        )
        uid = cur.lastrowid
        conn.commit()
        conn.close()
        assert get_recent_transactions(uid) == []


# ── get_category_breakdown ────────────────────────────────────────────────────

def test_get_category_breakdown_pct_sums_to_100(seeded_user):
    db_path, uid = seeded_user
    with patch.object(db_module, "DB_PATH", db_path):
        cats = get_category_breakdown(uid)
    assert len(cats) == 3
    assert sum(c["pct"] for c in cats) == 100
    # ordered by total desc
    totals = [c["total"] for c in cats]
    assert totals == sorted(totals, reverse=True)
    assert all(k in cats[0] for k in ("name", "total", "pct"))


def test_get_category_breakdown_no_expenses(test_db):
    with patch.object(db_module, "DB_PATH", test_db):
        conn = db_module.get_db()
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Empty", "e3@example.com", generate_password_hash("pw")),
        )
        uid = cur.lastrowid
        conn.commit()
        conn.close()
        assert get_category_breakdown(uid) == []


# ── Route tests ───────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret"
    with flask_app.test_client() as c:
        yield c


def test_profile_unauthenticated_redirects(client):
    resp = client.get("/profile")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_profile_authenticated_seed_user(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1  # seed user inserted by init_db/seed_db on app startup
    resp = client.get("/profile")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Demo User" in body
    assert "demo@spendly.com" in body
    assert "₹" in body
