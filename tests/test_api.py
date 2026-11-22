import base64
import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp()
os.environ["QUIZ_DB"] = os.path.join(_tmp, "test.db")
os.environ["ADMIN_PASSWORD"] = "secret-pass"
os.environ["DATABASE_URL"] = ""  # tests always run on a throwaway SQLite file

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402

AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:secret-pass").decode()}
QUESTIONS = [
    {"question": "Délai d'inscription ?", "options": ["2 jours", "10 jours ouvrés", "1 mois"], "correct": 1, "explanation": "Dix jours ouvrés"},
    {"question": "Qui inscrit ?", "options": ["Le candidat", "L'école"], "correct": 1, "explanation": ""},
]
PERSON = {"nom": "Durand", "prenom": "Léa", "tel": "0601020304", "email": "lea@example.com", "entreprise": "Acme", "consent": True}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def make_quiz(client, show_score=True, published=True):
    qid = client.post("/api/admin/quizzes", json={"generate": False, "video_url": "https://youtu.be/_Ybx69RTTOQ"}, headers=AUTH).json()["id"]
    r = client.put(f"/api/admin/quizzes/{qid}", headers=AUTH, json={
        "title": "PPL", "video_url": "https://youtu.be/_Ybx69RTTOQ",
        "questions": QUESTIONS, "published": published, "show_score": show_score})
    assert r.status_code == 200, r.text
    return qid, r.json()["slug"]


def test_youtube_id():
    assert db.youtube_id("https://www.youtube.com/watch?v=_Ybx69RTTOQ") == "_Ybx69RTTOQ"
    assert db.youtube_id("https://youtu.be/_Ybx69RTTOQ?si=x") == "_Ybx69RTTOQ"
    assert db.youtube_id("https://example.com/video") == ""


def test_score_answers():
    qs = db.validate_questions(QUESTIONS)
    assert db.score_answers(qs, [1, 1]) == 2
    assert db.score_answers(qs, [0, 1]) == 1
    assert db.score_answers(qs, [None, True]) == 0  # skipped and bool never count


def test_validate_rejects_bad_correct():
    with pytest.raises(ValueError):
        db.validate_questions([{"question": "x", "options": ["a", "b"], "correct": 5}])


def test_admin_requires_password(client):
    assert client.get("/api/admin/quizzes").status_code == 401
    bad = {"Authorization": "Basic " + base64.b64encode(b"admin:nope").decode()}
    assert client.get("/api/admin/quizzes", headers=bad).status_code == 401
    assert client.get("/admin").status_code == 401


def test_public_quiz_hides_answers(client):
    _, slug = make_quiz(client)
    data = client.get(f"/api/q/{slug}").json()
    assert data["video_id"] == "_Ybx69RTTOQ"
    assert "correct" not in str(data) and "explanation" not in str(data)


def test_unpublished_quiz_is_404(client):
    _, slug = make_quiz(client, published=False)
    assert client.get(f"/api/q/{slug}").status_code == 404
    assert client.post(f"/api/q/{slug}/submit", json={"participant": PERSON, "answers": [1, 1]}).status_code == 404


def test_submit_scores_server_side(client):
    _, slug = make_quiz(client)
    r = client.post(f"/api/q/{slug}/submit", json={"participant": PERSON, "answers": [1, 0]})
    assert r.status_code == 200
    body = r.json()
    assert (body["score"], body["total"]) == (1, 2)
    assert body["review"][0]["correct"] == 1


def test_score_hidden_when_disabled(client):
    _, slug = make_quiz(client, show_score=False)
    body = client.post(f"/api/q/{slug}/submit", json={"participant": PERSON, "answers": [1, 1]}).json()
    assert body == {"done": True}


def test_submit_validation(client):
    _, slug = make_quiz(client)
    url = f"/api/q/{slug}/submit"
    assert client.post(url, json={"participant": {**PERSON, "consent": False}, "answers": [1, 1]}).status_code == 422
    assert client.post(url, json={"participant": {**PERSON, "email": "pas-un-mail"}, "answers": [1, 1]}).status_code == 422
    assert client.post(url, json={"participant": PERSON, "answers": [1]}).status_code == 422
    assert client.post(url, json={"participant": PERSON, "answers": [9, 1]}).status_code == 422
    assert client.post(url, json={"participant": {**PERSON, "nom": ""}, "answers": [1, 1]}).status_code == 422


def test_results_and_csv_injection(client):
    qid, slug = make_quiz(client)
    client.post(f"/api/q/{slug}/submit", json={"participant": {**PERSON, "entreprise": "=HYPERLINK(\"x\")"}, "answers": [1, 1]})
    rows = client.get(f"/api/admin/quizzes/{qid}/submissions", headers=AUTH).json()
    assert rows[0]["score"] == 2 and rows[0]["prenom"] == "Léa"
    csv_text = client.get(f"/api/admin/quizzes/{qid}/export.csv", headers=AUTH).text
    assert "Léa" in csv_text and "'=HYPERLINK" in csv_text


def test_publish_needs_questions(client):
    qid = client.post("/api/admin/quizzes", json={"generate": False}, headers=AUTH).json()["id"]
    r = client.put(f"/api/admin/quizzes/{qid}", headers=AUTH, json={"questions": [], "published": True})
    assert r.status_code == 422


def test_delete_submission_and_quiz(client):
    qid, slug = make_quiz(client)
    client.post(f"/api/q/{slug}/submit", json={"participant": PERSON, "answers": [1, 1]})
    sub = client.get(f"/api/admin/quizzes/{qid}/submissions", headers=AUTH).json()[0]["id"]
    assert client.delete(f"/api/admin/submissions/{sub}", headers=AUTH).status_code == 200
    assert client.get(f"/api/admin/quizzes/{qid}/submissions", headers=AUTH).json() == []
    assert client.delete(f"/api/admin/quizzes/{qid}", headers=AUTH).status_code == 200
    assert client.get(f"/api/q/{slug}").status_code == 404


# ---------------------------------------------------------------- online mode (Render) and Gemini
from app import pipeline  # noqa: E402


def test_online_requires_transcript(client, monkeypatch):
    monkeypatch.setenv("QUIZ_TRANSCRIBE", "0")
    assert client.get("/api/admin/config", headers=AUTH).json()["transcribe"] is False
    before = len(client.get("/api/admin/quizzes", headers=AUTH).json())
    r = client.post("/api/admin/quizzes", headers=AUTH, json={"video_url": "https://youtu.be/_Ybx69RTTOQ"})
    assert r.status_code == 400 and "transcription" in r.json()["detail"]
    # the refused request must not leave an empty draft behind
    assert len(client.get("/api/admin/quizzes", headers=AUTH).json()) == before


def test_healthz_needs_no_password(client):
    assert client.get("/healthz").json() == {"ok": True}


class _FakeResponse:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload

    def json(self):
        return self._payload


def test_gemini_generation(monkeypatch):
    import httpx

    sent = {}
    quiz = '{"title": "PPL", "questions": [{"question": "Q ?", "options": ["a", "b"], "correct": 1, "explanation": ""}]}'

    def fake_post(url, headers, json, timeout):
        sent.update(url=url, key=headers["x-goog-api-key"], prompt=json["contents"][0]["parts"][0]["text"])
        return _FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": quiz}]}}]})

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "post", fake_post)
    data = pipeline.generate_questions("Le texte de la vidéo", n=3)
    assert data["title"] == "PPL" and data["questions"][0]["correct"] == 1
    assert sent["key"] == "test-key" and "Le texte de la vidéo" in sent["prompt"]
    assert sent["url"].startswith("https://generativelanguage.googleapis.com/")


def test_gemini_quota_message(monkeypatch):
    import httpx

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(429, {}))
    with pytest.raises(RuntimeError, match="Limite gratuite"):
        pipeline.generate_questions("texte", n=3)


def test_no_ai_key_message(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        pipeline.generate_questions("texte", n=3)


def test_manual_mode_without_ai_key(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.get("/api/admin/config", headers=AUTH).json()["ai"] is False
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert client.get("/api/admin/config", headers=AUTH).json()["ai"] is True
