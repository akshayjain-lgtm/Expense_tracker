# Spec: Registration

## Overview
Enable users to create a Spendly account by implementing the `POST /register` handler. The GET route and template already exist; this step wires up form submission — validating input, checking for duplicate emails, hashing the password, inserting the new user into the database, and redirecting to the login page on success. Error messages are surfaced in-template via the existing `{% if error %}` block.

## Depends on
- Step 01 — Database Setup (`users` table and `get_db()` must exist)

## Routes
- `POST /register` — process registration form, validate input, insert user — public

## Database changes
No database changes. Uses the existing `users` table:
- `name` TEXT NOT NULL
- `email` TEXT UNIQUE NOT NULL
- `password_hash` TEXT NOT NULL
- `created_at` TEXT DEFAULT datetime('now')

## Templates
- **Modify:** `templates/register.html` — add a "Confirm password" `<input type="password">` field (name `confirm_password`) below the password field

## Files to change
- `app.py` — update `/register` to accept both `GET` and `POST`; add form processing logic including password-match validation
- `templates/register.html` — add confirm password field

## Files to create
None.

## New dependencies
No new dependencies. `werkzeug.security.generate_password_hash` is already installed.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never string-format SQL
- Hash passwords with `werkzeug.security.generate_password_hash`
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Validate on the server side: name required, email required, password minimum 8 characters, password matches confirm password
- Catch `sqlite3.IntegrityError` to detect duplicate email — do not query for existence first
- On success, use `redirect(url_for('login'))` — do not set a session (that is Step 3)
- On error, re-render the registration template with the `error` variable set

## Definition of done
- [ ] `GET /register` still loads the form without errors
- [ ] Submitting the form with valid data inserts a row into `users` in `spendly.db`
- [ ] Password is stored as a hash, never plaintext (verify with `sqlite3 spendly.db "SELECT password_hash FROM users LIMIT 1"`)
- [ ] Successful registration redirects to `/login`
- [ ] Submitting with a duplicate email re-renders the form with the message "An account with that email already exists"
- [ ] Submitting with a password shorter than 8 characters re-renders the form with the message "Password must be at least 8 characters"
- [ ] Submitting with an empty name re-renders the form with the message "Name is required"
- [ ] Submitting with an invalid/empty email re-renders the form with an appropriate error
- [ ] Submitting with mismatched passwords re-renders the form with the message "Passwords do not match"
- [ ] No plain SQL string formatting anywhere in the new code
