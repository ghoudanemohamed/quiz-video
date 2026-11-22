"""Video -> transcript -> questions.

Runs on the admin's machine. Download and transcription are slow, so they run
in a background thread and report progress through a job dict.
"""
from __future__ import annotations

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
WHISPER_SIZE = os.environ.get("QUIZ_WHISPER", "small")

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


def generate_questions(transcript: str, n: int = 10) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("Clé ANTHROPIC_API_KEY absente : ajoutez-la dans le fichier .env")
    import anthropic

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": PROMPT.format(n=n, transcript=transcript[:60000])}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
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
