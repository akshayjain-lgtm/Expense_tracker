from datetime import datetime

from database.db import get_db

_DATE_CLAUSE = " AND date BETWEEN ? AND ?"


def get_user_by_id(user_id):
    db = get_db()
    row = db.execute(
        "SELECT name, email, created_at FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    db.close()
    if row is None:
        return None
    member_since = datetime.strptime(row["created_at"][:10], "%Y-%m-%d").strftime("%B %Y")
    return {"name": row["name"], "email": row["email"], "member_since": member_since}


def get_summary_stats(user_id, date_from=None, date_to=None):
    if date_from and date_to:
        params = (user_id, date_from, date_to)
        clause = _DATE_CLAUSE
    else:
        params = (user_id,)
        clause = ""
    db = get_db()
    row = db.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total_spent, COUNT(*) AS transaction_count "
        "FROM expenses WHERE user_id = ?" + clause,
        params,
    ).fetchone()
    top = db.execute(
        "SELECT category FROM expenses WHERE user_id = ?" + clause + " "
        "GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
        params,
    ).fetchone()
    db.close()
    return {
        "total_spent": row["total_spent"],
        "transaction_count": row["transaction_count"],
        "top_category": top["category"] if top else "—",
    }


def get_recent_transactions(user_id, limit=10, date_from=None, date_to=None):
    if date_from and date_to:
        params = (user_id, date_from, date_to, limit)
        clause = _DATE_CLAUSE
    else:
        params = (user_id, limit)
        clause = ""
    db = get_db()
    rows = db.execute(
        "SELECT date, description, category, amount "
        "FROM expenses WHERE user_id = ?" + clause + " ORDER BY date DESC LIMIT ?",
        params,
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_category_breakdown(user_id, date_from=None, date_to=None):
    if date_from and date_to:
        params = (user_id, date_from, date_to)
        clause = _DATE_CLAUSE
    else:
        params = (user_id,)
        clause = ""
    db = get_db()
    rows = db.execute(
        "SELECT category AS name, SUM(amount) AS total "
        "FROM expenses WHERE user_id = ?" + clause + " GROUP BY category ORDER BY total DESC",
        params,
    ).fetchall()
    db.close()
    if not rows:
        return []
    grand_total = sum(r["total"] for r in rows)
    result = [
        {"name": r["name"], "total": r["total"], "pct": int(r["total"] * 100 / grand_total)}
        for r in rows
    ]
    diff = 100 - sum(c["pct"] for c in result)
    result[0]["pct"] += diff
    return result
