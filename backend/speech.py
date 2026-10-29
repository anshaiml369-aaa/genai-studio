"""
speech.py - Voice features.
  * transcribe()  recorded voice -> text   (Groq Whisper, backup: OpenAI)
  * speak()       text -> MP3 voice        (OpenAI TTS)
"""

import re

from openai import OpenAI

import config

openai_client = OpenAI(api_key=config.OPENAI_API_KEY or "not-set")   # start without a key

VOICES = ["coral", "nova", "alloy", "ash", "ballad", "echo", "fable", "onyx", "sage", "shimmer"]


def transcribe(audio_bytes: bytes, filename: str = "voice.webm") -> str:
    """Try Groq first (free + very fast); if it fails, use OpenAI."""
    if config.GROQ_API_KEY:
        try:
            groq = OpenAI(api_key=config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
            result = groq.audio.transcriptions.create(model=config.GROQ_STT_MODEL,
                                                      file=(filename, audio_bytes))
            return result.text.strip()
        except Exception as error:
            print(f"[speech] Groq failed, using OpenAI: {error}")
    result = openai_client.audio.transcriptions.create(model=config.STT_MODEL,
                                                       file=(filename, audio_bytes))
    return result.text.strip()


def clean_for_speech(text: str) -> str:
    """Remove markdown symbols so the voice doesn't read '**' or '#' out loud."""
    text = re.sub(r"```.*?```", " (code shown on screen) ", text, flags=re.DOTALL)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)      # links -> just their text
    text = re.sub(r"[*#`_>|]", "", text)
    return text.strip()[:4000]                                    # API limit is 4096 chars


def speak(text: str, voice: str = "coral", style: str = "") -> bytes:
    response = openai_client.audio.speech.create(
        model=config.TTS_MODEL,
        voice=voice if voice in VOICES else "coral",
        input=clean_for_speech(text) or "Done.",
        instructions=style,
        response_format="mp3",
    )
    return response.content
