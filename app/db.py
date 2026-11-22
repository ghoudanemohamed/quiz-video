"""SQLite storage and scoring for the video quiz site."""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("QUIZ_DB", Path(__file__).resolve().parent.parent / "data" / "quiz.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS quizzes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    video_url TEXT NOT NULL DEFAULT '',
    video_id TEXT NOT NULL DEFAULT '',
    transcript TEXT NOT NULL DEFAULT '',
    questions_json TEXT NOT NULL DEFAULT '[]',
    published INTEGER NOT NULL DEFAULT 0,
    show_score INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    nom TEXT NOT NULL,
    prenom TEXT NOT NULL,
    tel TEXT NOT NULL,
    email TEXT NOT NULL,
    entreprise TEXT NOT NULL,
    answers_json TEXT NOT NULL,
    score INTEGER NOT NULL,
    total INTEGER NOT NULL,
    consent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with connect() as con:
        con.executescript(SCHEMA)


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
