import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cookie_token TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    scenario_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('train', 'test')),
    state_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'completed')),
    risk_score INTEGER,
    reasoning_score INTEGER,
    outcome TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    turn_number INTEGER NOT NULL,
    speaker TEXT NOT NULL CHECK (speaker IN ('scenario', 'user')),
    content TEXT NOT NULL,
    technique_used TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    turn_number INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    score_delta INTEGER NOT NULL,
    category TEXT NOT NULL,
    explanation TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS skill_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    category TEXT NOT NULL,
    proficiency INTEGER NOT NULL DEFAULT 50,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, category)
);

CREATE TABLE IF NOT EXISTS achievements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    achievement_key TEXT NOT NULL,
    earned_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, achievement_key)
);

-- Stores only the DERIVED analysis (indicators/risk/confidence), never the
-- raw uploaded artifact (image bytes / pasted text) — see spec section 8:
-- "never store uploaded artifacts permanently."
CREATE TABLE IF NOT EXISTS artifact_analyses (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    artifact_type TEXT NOT NULL CHECK (artifact_type IN ('text', 'screenshot', 'url')),
    analysis_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS generated_scenarios (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    source_analysis_id TEXT NOT NULL REFERENCES artifact_analyses(id),
    scenario_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DB_PATH"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    app.config["DB_PATH"].parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(app.config["DB_PATH"]) as conn:
        conn.executescript(SCHEMA)


def fetch_session_messages(db, session_id, limit=20):
    """Chronological message history for a session, most recent `limit` kept
    — bounds how much conversation gets sent to Claude per call."""
    rows = db.execute(
        "SELECT speaker, content FROM messages WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    return rows[-limit:]


def save_artifact_analysis(db, analysis_id, user_id, artifact_type, analysis_json):
    db.execute(
        "INSERT INTO artifact_analyses (id, user_id, artifact_type, analysis_json) VALUES (?, ?, ?, ?)",
        (analysis_id, user_id, artifact_type, analysis_json),
    )
    db.commit()


def fetch_artifact_analysis(db, analysis_id, user_id):
    row = db.execute(
        "SELECT * FROM artifact_analyses WHERE id = ? AND user_id = ?",
        (analysis_id, user_id),
    ).fetchone()
    return row


def save_generated_scenario(db, scenario_id, user_id, source_analysis_id, scenario_json):
    db.execute(
        "INSERT INTO generated_scenarios (id, user_id, source_analysis_id, scenario_json) VALUES (?, ?, ?, ?)",
        (scenario_id, user_id, source_analysis_id, scenario_json),
    )
    db.commit()


def fetch_generated_scenario(db, scenario_id, user_id):
    row = db.execute(
        "SELECT * FROM generated_scenarios WHERE id = ? AND user_id = ?",
        (scenario_id, user_id),
    ).fetchone()
    return row


def init_app(app):
    init_db(app)
    app.teardown_appcontext(close_db)
