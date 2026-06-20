import sqlite3
from datetime import date, datetime, timedelta

from flask import Flask, flash, render_template, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import get_db, get_user_by_email, init_db, seed_db
from database.queries import (get_category_breakdown, get_recent_transactions,
                               get_summary_stats, get_user_by_id)

app = Flask(__name__)
app.secret_key = "spendly-dev-secret"

with app.app_context():
    init_db()
    seed_db()


def parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date() if s else None
    except ValueError:
        return None


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

    uid = session["user_id"]

    date_from = parse_date(request.args.get("date_from", "").strip())
    date_to   = parse_date(request.args.get("date_to",   "").strip())

    if date_from and date_to and date_from > date_to:
        flash("Start date must be before end date.", "error")
        date_from = date_to = None
    elif (date_from and not date_to) or (not date_from and date_to):
        flash("Please provide both a start date and an end date.", "error")
        date_from = date_to = None

    df_str = date_from.isoformat() if date_from else None
    dt_str = date_to.isoformat()   if date_to   else None

    today = date.today()
    presets = {
        "this_month": {
            "date_from": today.replace(day=1).isoformat(),
            "date_to":   today.isoformat(),
        },
        "last_3": {
            "date_from": (today - timedelta(days=90)).isoformat(),
            "date_to":   today.isoformat(),
        },
        "last_6": {
            "date_from": (today - timedelta(days=180)).isoformat(),
            "date_to":   today.isoformat(),
        },
    }

    if not df_str and not dt_str:
        active_preset = "all_time"
    elif df_str == presets["this_month"]["date_from"] and dt_str == presets["this_month"]["date_to"]:
        active_preset = "this_month"
    elif df_str == presets["last_3"]["date_from"] and dt_str == presets["last_3"]["date_to"]:
        active_preset = "last_3"
    elif df_str == presets["last_6"]["date_from"] and dt_str == presets["last_6"]["date_to"]:
        active_preset = "last_6"
    else:
        active_preset = None

    user       = get_user_by_id(uid)
    stats      = get_summary_stats(uid, date_from=df_str, date_to=dt_str)
    expenses   = get_recent_transactions(uid, date_from=df_str, date_to=dt_str)
    categories = get_category_breakdown(uid, date_from=df_str, date_to=dt_str)

    return render_template(
        "profile.html",
        user=user, stats=stats, expenses=expenses, categories=categories,
        date_from=df_str, date_to=dt_str, presets=presets, active_preset=active_preset,
    )


@app.route("/analytics")
def analytics():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    launch_date = (datetime.utcnow() + timedelta(days=45)).isoformat()
    return render_template("analytics.html", launch_date=launch_date)


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
