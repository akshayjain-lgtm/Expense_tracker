import sqlite3

from flask import Flask, render_template, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import get_db, get_user_by_email, init_db, seed_db

app = Flask(__name__)
app.secret_key = "spendly-dev-secret"

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name             = request.form.get("name", "").strip()
    email            = request.form.get("email", "").strip()
    password         = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not name:
        return render_template("register.html", error="Name is required")
    if not email:
        return render_template("register.html", error="Email is required")
    if len(password) < 8:
        return render_template("register.html", error="Password must be at least 8 characters")
    if password != confirm_password:
        return render_template("register.html", error="Passwords do not match")

    try:
        db = get_db()
        db.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(password)),
        )
        db.commit()
        db.close()
    except sqlite3.IntegrityError:
        return render_template("register.html", error="An account with that email already exists")

    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    user = get_user_by_email(email)
    if not user or not check_password_hash(user["password_hash"], password):
        return render_template("login.html", error="Invalid email or password.")

    session["user_id"] = user["id"]
    return redirect(url_for("profile"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user = {
        "name": "Demo User",
        "email": "demo@spendly.com",
        "member_since": "January 2025",
    }
    stats = {
        "total_spent": 12450.75,
        "transaction_count": 8,
        "top_category": "Food",
    }
    expenses = [
        {"date": "2025-06-10", "description": "Grocery shopping",    "category": "Food",          "amount": 1200.00},
        {"date": "2025-06-08", "description": "Uber to office",       "category": "Transport",     "amount": 340.00},
        {"date": "2025-06-05", "description": "Electricity bill",     "category": "Bills",         "amount": 2100.00},
        {"date": "2025-06-03", "description": "Pharmacy",             "category": "Health",        "amount": 580.00},
        {"date": "2025-05-30", "description": "Netflix subscription", "category": "Entertainment", "amount": 649.00},
        {"date": "2025-05-28", "description": "Supermarket run",      "category": "Food",          "amount": 2000.00},
        {"date": "2025-05-25", "description": "New shoes",            "category": "Shopping",      "amount": 3500.00},
        {"date": "2025-05-20", "description": "Miscellaneous",        "category": "Other",         "amount": 2081.75},
    ]
    categories = [
        {"name": "Shopping",      "total": 3500.00, "pct": 28},
        {"name": "Food",          "total": 3200.00, "pct": 26},
        {"name": "Bills",         "total": 2100.00, "pct": 17},
        {"name": "Other",         "total": 2081.75, "pct": 17},
        {"name": "Health",        "total":  580.00, "pct":  5},
        {"name": "Entertainment", "total":  649.00, "pct":  5},
        {"name": "Transport",     "total":  340.00, "pct":  3},
    ]
    return render_template("profile.html", user=user, stats=stats,
                           expenses=expenses, categories=categories)


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
