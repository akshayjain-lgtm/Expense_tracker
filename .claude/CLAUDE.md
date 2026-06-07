# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
source venv/bin/activate
python app.py          # starts on http://localhost:5001
```

If port 5001 is already in use:
```bash
lsof -ti :5001 | xargs kill -9
```

## Running tests

```bash
source venv/bin/activate
pytest                        # all tests
pytest tests/test_foo.py      # single file
pytest -k "test_name"         # single test
```

## Architecture

This is a Flask + SQLite expense tracker built as a step-by-step teaching project (CampusX). Many routes in `app.py` are stubs — they return placeholder strings until students implement them in later steps.

**Request flow:** Browser → `app.py` (route) → `database/db.py` (data) → Jinja2 template → response

- **`app.py`** — all routes in one file; no blueprints. Implemented: `/`, `/login`, `/register`, `/terms`, `/privacy`. Stubbed: `/logout`, `/profile`, `/expenses/add`, `/expenses/<id>/edit`, `/expenses/<id>/delete`.
- **`database/db.py`** — not yet written. Will expose `get_db()` (SQLite connection with `row_factory` and foreign keys), `init_db()` (CREATE TABLE IF NOT EXISTS), and `seed_db()` (sample data).
- **`templates/`** — all templates extend `base.html`. Base provides the sticky navbar, footer with Terms/Privacy links, and `{% block scripts %}` for per-page JS.
- **`static/css/style.css`** — single stylesheet; no CSS framework. Uses custom properties defined in `:root` (`--ink`, `--accent`, `--paper`, `--font-display`, etc.). Font pairing: DM Serif Display (headings/accent) + DM Sans (body).
- **`static/js/main.js`** — stub file; per-page JS goes in `{% block scripts %}` in individual templates using vanilla JS only (no framework).

## Key conventions

- No JS framework — all interactivity is vanilla JS, written as IIFEs inside `{% block scripts %}`.
- YouTube embeds use `youtube-nocookie.com` and a `data-src`/`src` swap pattern to stop video on modal close.
- The `tmp/` directory is gitignored and used for scratch files / design references.
