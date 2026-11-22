"""Storage and scoring for the video quiz site.

Uses PostgreSQL when DATABASE_URL is set (online, e.g. Neon), SQLite otherwise (local PC).
SQL in the app is written once with `?` placeholders; the wrapper adapts it for PostgreSQL.
"""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_PATH = Path(os.environ.get("QUIZ_DB", Path(__file__).resolve().parent.parent / "data" / "quiz.db"))
IS_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))

_COLUMNS = """
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    video_url TEXT NOT NULL DEFAULT '',
    video_id TEXT NOT NULL DEFAULT '',
    transcript TEXT NOT NULL DEFAULT '',
    questions_json TEXT NOT NULL DEFAULT '[]',
    published INTEGER NOT NULL DEFAULT 0,
    show_score INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT ''
"""
_SUB_COLUMNS = """
    nom TEXT NOT NULL,
    prenom TEXT NOT NULL,
    tel TEXT NOT NULL,
    email TEXT NOT NULL,
    entreprise TEXT NOT NULL,
    answers_json TEXT NOT NULL,
    score INTEGER NOT NULL,
    total INTEGER NOT NULL,
    consent_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
"""
SCHEMA_SQLITE = [
    f"CREATE TABLE IF NOT EXISTS quizzes (id INTEGER PRIMARY KEY AUTOINCREMENT, {_COLUMNS})",
    "CREATE TABLE IF NOT EXISTS submissions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
    f" quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE, {_SUB_COLUMNS})",
]
SCHEMA_POSTGRES = [
    f"CREATE TABLE IF NOT EXISTS quizzes (id SERIAL PRIMARY KEY, {_COLUMNS})",
    "CREATE TABLE IF NOT EXISTS submissions (id SERIAL PRIMARY KEY,"
    f" quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE, {_SUB_COLUMNS})",
]


def now() -> str:
    """UTC timestamp in the format the admin page parses: 2026-11-22 14:30:00."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class _Conn:
    """Same tiny API for both engines: execute(sql, params) -> cursor with fetchone/fetchall/rowcount."""

    def __init__(self, raw, postgres: bool):
        self.raw = raw
        self.postgres = postgres

    def execute(self, sql: str, params: tuple = ()):
        if self.postgres:
            sql = sql.replace("?", "%s")
        cur = self.raw.cursor()
        cur.execute(sql, params)
        return cur


@contextmanager
def connect():
    if IS_POSTGRES:
        import psycopg
        from psycopg.rows import dict_row

        raw = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(DB_PATH)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
    try:
        yield _Conn(raw, IS_POSTGRES)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def init() -> None:
    with connect() as con:
        for stmt in SCHEMA_POSTGRES if IS_POSTGRES else SCHEMA_SQLITE:
            con.execute(stmt)


_YT_ID = re.compile(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})")


def youtube_id(url: str) -> str:
    m = _YT_ID.search(url or "")
    return m.group(1) if m else ""


def new_slug() -> str:
    return secrets.token_urlsafe(6).replace("_", "x").replace("-", "y")


def validate_questions(questions: list) -> list[dict]:
    """Normalise and validate a question list. Raises ValueError on bad input."""
    clean = []
    for i, q in enumerate(questions, start=1):
        text = str(q.get("question", "")).strip()
        options = [str(o).strip() for o in q.get("options", []) if str(o).strip()]
        correct = q.get("correct")
        if not text:
            raise ValueError(f"Question {i} : l'énoncé est vide")
        if len(options) < 2:
            raise ValueError(f"Question {i} : il faut au moins deux réponses")
        if not isinstance(correct, int) or isinstance(correct, bool) or not 0 <= correct < len(options):
            raise ValueError(f"Question {i} : la bonne réponse est invalide")
        clean.append(
            {
                "question": text,
                "options": options,
                "correct": correct,
                "explanation": str(q.get("explanation", "")).strip(),
            }
        )
    return clean


def score_answers(questions: list[dict], answers: list) -> int:
    """One point per question whose chosen option equals the correct one."""
    score = 0
    for q, a in zip(questions, answers):
        if isinstance(a, int) and not isinstance(a, bool) and a == q["correct"]:
            score += 1
    return score
