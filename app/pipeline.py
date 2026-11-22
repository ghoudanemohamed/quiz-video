"""Video -> transcript -> questions.

Download and transcription (yt-dlp + Whisper) only run where those packages are installed,
i.e. on the admin's PC. Online, the admin pastes the transcript instead.
Questions come from Gemini (free tier) when GEMINI_API_KEY is set, else from Claude.
Slow work runs in a background thread and reports progress through a job dict.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path

MODEL = os.environ.get("QUIZ_CLAUDE_MODEL", "claude-sonnet-5-5")
GEMINI_MODEL = os.environ.get("QUIZ_GEMINI_MODEL", "gemini-2.5-flash")
WHISPER_SIZE = os.environ.get("QUIZ_WHISPER", "small")


def transcription_available() -> bool:
    """True only where the local transcription stack is installed and not switched off."""
    if os.environ.get("QUIZ_TRANSCRIBE", "auto") == "0":
        return False
    return all(importlib.util.find_spec(m) for m in ("yt_dlp", "faster_whisper", "numpy"))


def ai_available() -> bool:
    """True when a key for Gemini or Claude is configured. Without one, questions are written by hand."""
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))


NEEDS_TRANSCRIPT ="Collez la transcription de la vidéo : la version en ligne ne peut pas télécharger les vidéos"

JOBS: dict[str, dict] = {}


def _set(job_id: str, **kw) -> None:
    JOBS[job_id].update(kw)


def transcribe_url(url: str) -> str:
    """Download the audio with yt-dlp and transcribe it locally with Whisper."""
    import numpy as np
    from faster_whisper import WhisperModel

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg est introuvable sur cet ordinateur")

    with tempfile.TemporaryDirectory(prefix="quiz_") as tmp:
        out = Path(tmp) / "audio.%(ext)s"
        cmd = [sys.executable, "-I", "-m", "yt_dlp", "-f", "bestaudio/best", "-x",
               "--audio-format", "wav", "-o", str(out), url]
        if shutil.which("deno"):
            cmd[4:4] = ["--js-runtimes", "deno"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        wav = Path(tmp) / "audio.wav"
        if res.returncode != 0 or not wav.exists():
            raise RuntimeError("Impossible de télécharger la vidéo. Collez la transcription à la main.")
        raw = subprocess.run(
            [ffmpeg, "-v", "quiet", "-i", str(wav), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
            capture_output=True,
        ).stdout
        audio = np.frombuffer(raw, dtype=np.float32)
        model = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio, language="fr")
        return " ".join(s.text.strip() for s in segments)


PROMPT = """Tu écris un questionnaire à choix multiples en français pour vérifier qu'une personne a bien compris une vidéo.

Règles :
- {n} questions, chacune avec 4 réponses dont une seule est correcte.
- Les questions portent uniquement sur ce que dit la transcription. N'ajoute aucun fait extérieur.
- Les mauvaises réponses sont plausibles mais clairement fausses d'après la vidéo.
- Place la bonne réponse à des positions variées.
- La transcription vient d'une reconnaissance vocale automatique : corrige mentalement les mots mal compris.
- "explanation" tient en une phrase et dit pourquoi la réponse est juste.

Réponds uniquement avec du JSON, sans texte autour, de la forme :
{{"title": "...", "questions": [{{"question": "...", "options": ["...", "...", "...", "..."], "correct": 0, "explanation": "..."}}]}}

Transcription :
{transcript}"""


def _ask_gemini(prompt: str) -> str:
    import httpx

    res = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
        },
        timeout=120,
    )
    if res.status_code == 429:
        raise RuntimeError("Limite gratuite de Gemini atteinte, réessayez dans quelques minutes")
    if res.status_code >= 400:
        raise RuntimeError(f"Gemini a refusé la demande (code {res.status_code}), vérifiez la clé GEMINI_API_KEY")
    data = res.json()
    try:
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError):
        raise RuntimeError("Gemini n'a pas renvoyé de questions, réessayez")


def _ask_claude(prompt: str) -> str:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("Le paquet anthropic n'est pas installé")
    msg = anthropic.Anthropic().messages.create(
        model=MODEL, max_tokens=4000, messages=[{"role": "user", "content": prompt}]
    )
    return "".join(b.text for b in msg.content if b.type == "text")


def generate_questions(transcript: str, n: int = 10) -> dict:
    prompt = PROMPT.format(n=n, transcript=transcript[:60000])
    if os.environ.get("GEMINI_API_KEY"):
        text = _ask_gemini(prompt)
    elif os.environ.get("ANTHROPIC_API_KEY"):
        text = _ask_claude(prompt)
    else:
        raise RuntimeError("Aucune clé d'IA : ajoutez GEMINI_API_KEY (gratuite) dans les réglages")
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise RuntimeError("La réponse de l'IA n'est pas exploitable, réessayez")
    return json.loads(text[start : end + 1])


def start_job(url: str, transcript: str, n: int, on_done) -> str:
    """Run the pipeline in the background. `on_done(title, transcript, questions)` stores the result."""
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {"state": "running", "step": "Préparation", "error": ""}

    def run():
        try:
            text = transcript
            if not text.strip():
                if not transcription_available():
                    raise RuntimeError(NEEDS_TRANSCRIPT)
                _set(job_id, step="Téléchargement et transcription de la vidéo")
                text = transcribe_url(url)
            _set(job_id, step="Écriture des questions")
            data = generate_questions(text, n)
            on_done(data.get("title", ""), text, data.get("questions", []))
            _set(job_id, state="done", step="Terminé")
        except Exception as exc:  # surfaced to the admin page
            _set(job_id, state="error", error=str(exc))

    threading.Thread(target=run, daemon=True).start()
    return job_id
