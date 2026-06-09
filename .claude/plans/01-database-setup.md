# Plan: Implement `database/db.py` (Step 1 — Database Setup)

## Context

`database/db.py` is currently a stub (just a comment block). The spec at
`.claude/specs/01-database-setup.md` calls for a working SQLite data layer —
`get_db()`, `init_db()`, `seed_db()` — plus wiring it into `app.py` startup.
This is the foundation every later feature (auth, profile, expense CRUD)
depends on. No new routes, no new files, no new dependencies — just filling
in the stub and one small addition to `app.py`.

Findings from exploration that shape this plan:
- `templates/register.html` posts `name`, `email`, `password` — matches the
  `users` table columns (`name`, `email`, `password_hash`) the spec defines.
- No `tests/` directory and no existing `.db` file — this is a clean slate.
- `.gitignore` only has `/tmp/`, so the generated DB file would be tracked by
  git unless ignored.
- The spec offers a choice of DB filename (`spendly.db` or
  `expense_tracker.db`); the app is branded "Spendly" and the demo user's
  email is `demo@spendly.com`, so **`spendly.db`** is the natural choice.

---

## Implementation

### 1. `database/db.py` — replace stub with real implementation

```python
import os
import sqlite3
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "spendly.db"
)

CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```

- **`get_db()`**: opens `spendly.db` in the project root (path computed from
  `__file__` so it's independent of CWD), sets `row_factory = sqlite3.Row`,
  enables `PRAGMA foreign_keys = ON`, returns the connection.

- **`init_db()`**: opens a connection via `get_db()`, runs two
  `CREATE TABLE IF NOT EXISTS` statements matching the spec schema exactly:
  - `users(id PK AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')))`
  - `expenses(id PK AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id), amount REAL NOT NULL, category TEXT NOT NULL, date TEXT NOT NULL, description TEXT, created_at TEXT DEFAULT (datetime('now')))`
  - Commits and closes. Safe to call repeatedly.

- **`seed_db()`**:
  - Opens a connection, runs `SELECT COUNT(*) FROM users` — if non-zero,
    closes and returns immediately (idempotent, no duplicates).
  - Otherwise inserts the demo user (`Demo User`, `demo@spendly.com`,
    `generate_password_hash("demo123")`) and captures `cursor.lastrowid`.
  - Inserts 8 sample expenses via `executemany` with parameterized SQL,
    one per category (`Food` gets a second entry to reach 8), `description`
    filled in, `date` values generated dynamically as `date.today()` minus
    small offsets (e.g. 0, 2, 4, 7, 10, 13, 16, 19 days) — always in the
    past, spread across the current month.
  - Commits and closes.

All SQL uses `?` placeholders — no string formatting.

---

### 2. `app.py` — wire up DB init on startup

Add import and app-context startup block right after `app = Flask(__name__)`:

```python
from database.db import get_db, init_db, seed_db

app = Flask(__name__)

with app.app_context():
    init_db()
    seed_db()
```

---

### 3. `.gitignore` — ignore the generated DB file

Add `spendly.db` so the SQLite file isn't accidentally committed (currently
only `/tmp/` is ignored).

---

## Files Touched

| File | Change |
|------|--------|
| `database/db.py` | Full implementation (replaces stub) |
| `app.py` | Add import + `init_db()`/`seed_db()` startup calls |
| `.gitignore` | Add `spendly.db` |

---

## Verification

1. `source venv/bin/activate && python app.py` — app starts cleanly,
   `spendly.db` appears in project root.
2. `sqlite3 spendly.db ".tables"` → both tables present.
3. `SELECT * FROM users; SELECT * FROM expenses;` → demo user with hashed
   password, 8 expenses across all 7 categories.
4. Restart app → row counts unchanged (idempotent seed).
5. Python shell: insert duplicate email → `sqlite3.IntegrityError` (UNIQUE);
   insert expense with bad `user_id` → `sqlite3.IntegrityError` (FK enforced).
</content>
