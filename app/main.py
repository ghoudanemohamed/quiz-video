"""Video quiz site: an admin turns a video into a quiz, participants answer it."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


_load_env()

from . import db, pipeline  # noqa: E402  (after .env so settings are visible)

STATIC = Path(__file__).resolve().parent / "static"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(9)
if not os.environ.get("ADMIN_PASSWORD"):
    print(f"[quiz] ADMIN_PASSWORD absent du .env, mot de passe temporaire : {ADMIN_PASSWORD}")

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    yield


app = FastAPI(title="Quiz vidéo", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
basic = HTTPBasic()


def admin(creds: HTTPBasicCredentials = Depends(basic)) -> None:
    ok = secrets.compare_digest(creds.username.encode(), b"admin") & secrets.compare_digest(
        creds.password.encode(), ADMIN_PASSWORD.encode()
    )
    if not ok:
        raise HTTPException(401, "Accès refusé", headers={"WWW-Authenticate": "Basic"})


# ---------------------------------------------------------------- pages
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/admin")


@app.get("/admin", include_in_schema=False)
def admin_page(_: None = Depends(admin)):
    return FileResponse(STATIC / "admin.html")


@app.get("/q/{slug}", include_in_schema=False)
def quiz_page(slug: str):
    return FileResponse(STATIC / "quiz.html")


# ---------------------------------------------------------------- helpers
def _quiz_or_404(con, quiz_id: int):
    row = con.execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Questionnaire introuvable")
    return row


def _admin_quiz(row) -> dict:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "title": row["title"],
        "video_url": row["video_url"],
        "video_id": row["video_id"],
        "transcript": row["transcript"],
        "questions": json.loads(row["questions_json"]),
        "published": bool(row["published"]),
        "show_score": bool(row["show_score"]),
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------- admin API
class CreateQuiz(BaseModel):
    video_url: str = Field("", max_length=500)
    transcript: str = Field("", max_length=200000)
    count: int = Field(10, ge=3, le=20)
    generate: bool = True


@app.get("/api/admin/quizzes")
def list_quizzes(_: None = Depends(admin)):
    with db.connect() as con:
        rows = con.execute(
            """SELECT q.*, (SELECT COUNT(*) FROM submissions s WHERE s.quiz_id = q.id) AS n
               FROM quizzes q ORDER BY q.id DESC"""
        ).fetchall()
    return [
        {
            "id": r["id"], "slug": r["slug"], "title": r["title"] or "Sans titre",
            "published": bool(r["published"]), "responses": r["n"],
            "questions": len(json.loads(r["questions_json"])), "created_at": r["created_at"],
        }
        for r in rows
    ]


@app.post("/api/admin/quizzes")
def create_quiz(body: CreateQuiz, _: None = Depends(admin)):
    slug = db.new_slug()
    with db.connect() as con:
        cur = con.execute(
            "INSERT INTO quizzes (slug, video_url, video_id, transcript) VALUES (?, ?, ?, ?)",
            (slug, body.video_url.strip(), db.youtube_id(body.video_url), body.transcript),
        )
        quiz_id = cur.lastrowid
    if not body.generate:
        return {"id": quiz_id, "job": None}
    if not body.video_url.strip() and not body.transcript.strip():
        raise HTTPException(400, "Collez un lien de vidéo ou une transcription")

    def on_done(title: str, transcript: str, questions: list) -> None:
        clean = db.validate_questions(questions)
        with db.connect() as con:
            con.execute(
                "UPDATE quizzes SET title = CASE WHEN title = '' THEN ? ELSE title END,"
                " transcript = ?, questions_json = ? WHERE id = ?",
                (title, transcript, json.dumps(clean, ensure_ascii=False), quiz_id),
            )

    job = pipeline.start_job(body.video_url.strip(), body.transcript, body.count, on_done)
    return {"id": quiz_id, "job": job}


@app.get("/api/admin/jobs/{job_id}")
def job_status(job_id: str, _: None = Depends(admin)):
    job = pipeline.JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Tâche introuvable")
    return job


@app.get("/api/admin/quizzes/{quiz_id}")
def get_quiz(quiz_id: int, _: None = Depends(admin)):
    with db.connect() as con:
        return _admin_quiz(_quiz_or_404(con, quiz_id))


class UpdateQuiz(BaseModel):
    title: str = Field("", max_length=200)
    video_url: str = Field("", max_length=500)
    questions: list[dict]
    published: bool = False
    show_score: bool = True


@app.put("/api/admin/quizzes/{quiz_id}")
def update_quiz(quiz_id: int, body: UpdateQuiz, _: None = Depends(admin)):
    try:
        clean = db.validate_questions(body.questions)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if body.published and not clean:
        raise HTTPException(422, "Ajoutez au moins une question avant de publier")
    with db.connect() as con:
        _quiz_or_404(con, quiz_id)
        con.execute(
            "UPDATE quizzes SET title = ?, video_url = ?, video_id = ?, questions_json = ?,"
            " published = ?, show_score = ? WHERE id = ?",
            (body.title.strip(), body.video_url.strip(), db.youtube_id(body.video_url),
             json.dumps(clean, ensure_ascii=False), int(body.published), int(body.show_score), quiz_id),
        )
        return _admin_quiz(_quiz_or_404(con, quiz_id))


@app.delete("/api/admin/quizzes/{quiz_id}")
def delete_quiz(quiz_id: int, _: None = Depends(admin)):
    with db.connect() as con:
        _quiz_or_404(con, quiz_id)
        con.execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,))
    return {"ok": True}


def _submission_rows(con, quiz_id: int):
    return con.execute(
        "SELECT * FROM submissions WHERE quiz_id = ? ORDER BY id DESC", (quiz_id,)
    ).fetchall()


@app.get("/api/admin/quizzes/{quiz_id}/submissions")
def list_submissions(quiz_id: int, _: None = Depends(admin)):
    with db.connect() as con:
        _quiz_or_404(con, quiz_id)
        rows = _submission_rows(con, quiz_id)
    return [
        {"id": r["id"], "nom": r["nom"], "prenom": r["prenom"], "tel": r["tel"],
         "email": r["email"], "entreprise": r["entreprise"], "score": r["score"],
         "total": r["total"], "created_at": r["created_at"]}
        for r in rows
    ]


def _csv_cell(value) -> str:
    s = str(value)
    # Stop spreadsheet formula injection from participant-typed text.
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@app.get("/api/admin/quizzes/{quiz_id}/export.csv")
def export_csv(quiz_id: int, _: None = Depends(admin)):
    with db.connect() as con:
        _quiz_or_404(con, quiz_id)
        rows = _submission_rows(con, quiz_id)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Date", "Nom", "Prénom", "Téléphone", "E-mail", "Entreprise", "Score", "Total"])
    for r in rows:
        w.writerow([r["created_at"], *(_csv_cell(r[k]) for k in ("nom", "prenom", "tel", "email", "entreprise")),
                    r["score"], r["total"]])
    data = "﻿" + buf.getvalue()  # BOM so Excel reads accents correctly
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="resultats-{quiz_id}.csv"'})


@app.delete("/api/admin/submissions/{sub_id}")
def delete_submission(sub_id: int, _: None = Depends(admin)):
    with db.connect() as con:
        cur = con.execute("DELETE FROM submissions WHERE id = ?", (sub_id,))
        if not cur.rowcount:
            raise HTTPException(404, "Réponse introuvable")
    return {"ok": True}


# ---------------------------------------------------------------- public API
def _public_quiz(slug: str):
    with db.connect() as con:
        row = con.execute("SELECT * FROM quizzes WHERE slug = ? AND published = 1", (slug,)).fetchone()
    if not row:
        raise HTTPException(404, "Ce questionnaire n'existe pas ou n'est plus ouvert")
    return row


@app.get("/api/q/{slug}")
def public_quiz(slug: str):
    row = _public_quiz(slug)
    questions = json.loads(row["questions_json"])
    return {
        "title": row["title"],
        "video_id": row["video_id"],
        "video_url": row["video_url"],
        "questions": [{"question": q["question"], "options": q["options"]} for q in questions],
    }


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Participant(BaseModel):
    nom: str = Field(..., min_length=1, max_length=100)
    prenom: str = Field(..., min_length=1, max_length=100)
    tel: str = Field(..., min_length=6, max_length=30)
    email: str = Field(..., max_length=200)
    entreprise: str = Field(..., min_length=1, max_length=150)
    consent: bool


class Submission(BaseModel):
    participant: Participant
    answers: list[int | None]


@app.post("/api/q/{slug}/submit")
def submit(slug: str, body: Submission):
    row = _public_quiz(slug)
    p = body.participant
    if not p.consent:
        raise HTTPException(422, "Le consentement est nécessaire pour envoyer vos réponses")
    if not _EMAIL.match(p.email.strip()):
        raise HTTPException(422, "Adresse e-mail invalide")
    questions = json.loads(row["questions_json"])
    if len(body.answers) != len(questions):
        raise HTTPException(422, "Nombre de réponses incorrect")
    for q, a in zip(questions, body.answers):
        if a is not None and not 0 <= a < len(q["options"]):
            raise HTTPException(422, "Réponse invalide")
    score = db.score_answers(questions, body.answers)
    with db.connect() as con:
        con.execute(
            "INSERT INTO submissions (quiz_id, nom, prenom, tel, email, entreprise, answers_json, score, total)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["id"], p.nom.strip(), p.prenom.strip(), p.tel.strip(), p.email.strip(),
             p.entreprise.strip(), json.dumps(body.answers), score, len(questions)),
        )
    result: dict = {"done": True}
    if row["show_score"]:
        result.update(
            score=score,
            total=len(questions),
            review=[
                {"correct": q["correct"], "chosen": a, "explanation": q.get("explanation", "")}
                for q, a in zip(questions, body.answers)
            ],
        )
    return result
