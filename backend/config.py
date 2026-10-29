"""
config.py - All settings in one place: API keys, model names, folders.
Keys are read from the .env file in the project folder.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent      # the GENAI_STUDIO folder
load_dotenv(BASE_DIR / ".env")

# ---------- API keys ----------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()   # brain, voice, images
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()       # fast speech-to-text (free)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()   # story writing, images
KLING_API_KEY = os.getenv("KLING_API_KEY", "").strip()     # realistic AI video

# ---------- Models (override in .env if needed) ----------
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-5.4-mini")
STT_MODEL = os.getenv("STT_MODEL", "gpt-4o-mini-transcribe")
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
TTS_MODEL = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")
GEMINI_TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1-mini")
KLING_MODEL = os.getenv("KLING_MODEL", "kling-v3")
KLING_API = "https://api-singapore.klingai.com"

# ---------- Folders (everything the app creates is saved here) ----------
STORAGE = BASE_DIR / "storage"
IMAGES_DIR = STORAGE / "images"
VIDEOS_DIR = STORAGE / "videos"
AUDIO_DIR = STORAGE / "audio"
TMP_DIR = STORAGE / "tmp"
for folder in (IMAGES_DIR, VIDEOS_DIR, AUDIO_DIR, TMP_DIR):
    folder.mkdir(parents=True, exist_ok=True)

FRONTEND_DIR = BASE_DIR / "frontend"

# ---------- Video options ----------
RATIOS = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (960, 960)}
DURATIONS = [5, 10]


def to_url(path: Path) -> str:
    """storage/videos/a.mp4  ->  /media/videos/a.mp4  (the URL the browser uses)"""
    return "/media/" + path.relative_to(STORAGE).as_posix()


def status() -> dict:
    """Which features are switched on (shown in the UI)."""
    return {
        "chat": bool(OPENAI_API_KEY),
        "voice_in": "Groq" if GROQ_API_KEY else ("OpenAI" if OPENAI_API_KEY else None),
        "voice_out": bool(OPENAI_API_KEY),
        "image": [name for name, key in (("Gemini", GEMINI_API_KEY), ("OpenAI", OPENAI_API_KEY)) if key],
        "video": (["Kling"] if KLING_API_KEY else []) + ["Motion Preview"],
        "models": {"chat": CHAT_MODEL, "kling": KLING_MODEL},
    }
