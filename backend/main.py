"""
main.py - The FastAPI web server (REST API + serves the website).

Run from the GENAI_STUDIO folder:
    .venv/bin/uvicorn main:app --app-dir backend --port 8000
"""

import json

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import brain
import config
import guard
import media
import speech
import studio

app = FastAPI(title="Kalpana · GenAI Studio API")
guard.install(app, media, studio, brain)   # public-demo limits; a no-op locally


# ---------------- Request bodies ----------------
class ChatRequest(BaseModel):
    history: list[dict]                 # [{role, text, images: [dataURL], media: [...]}]
    personality: str = "friendly"


class SpeakRequest(BaseModel):
    text: str
    voice: str = "coral"
    personality: str = "friendly"


class PromptRequest(BaseModel):
    prompt: str


class StoryRequest(BaseModel):
    idea: str
    scenes: int = 3
    seconds: int = 5


# ---------------- API ----------------
@app.get("/api/status")
def get_status():
    return config.status() | {"voices": speech.VOICES, "personalities": list(brain.PERSONALITIES),
                              "public_demo": guard.PUBLIC}


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Streams the reply as Server-Sent Events (text, image, video, status...)."""
    return StreamingResponse(brain.chat_events(req.history, req.personality),
                             media_type="text/event-stream")


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    data = await audio.read()
    if len(data) < 1000:
        raise HTTPException(400, "Recording is too short.")
    try:
        return {"text": speech.transcribe(data, audio.filename or "voice.webm")}
    except Exception as error:
        raise HTTPException(500, f"Speech-to-text failed: {error}")


@app.post("/api/speak")
def speak(req: SpeakRequest):
    style = brain.PERSONALITIES.get(req.personality, brain.PERSONALITIES["friendly"])[1]
    try:
        return Response(speech.speak(req.text, req.voice, style), media_type="audio/mpeg")
    except Exception as error:
        raise HTTPException(500, f"Text-to-speech failed: {error}")


@app.post("/api/enhance")
def enhance(req: PromptRequest):
    try:
        return {"prompt": studio.enhance_prompt(req.prompt)}
    except Exception as error:
        raise HTTPException(500, f"Enhance failed: {error}")


@app.post("/api/story")
def story(req: StoryRequest):
    try:
        return studio.write_story(req.idea, max(1, min(req.scenes, 4)), req.seconds)
    except Exception as error:
        raise HTTPException(500, f"Story writing failed: {error}")


@app.post("/api/image")
def image(req: PromptRequest):
    try:
        path, engine = media.make_image(req.prompt)
        return {"url": config.to_url(path), "engine": engine}
    except Exception as error:
        raise HTTPException(500, str(error))


@app.post("/api/videos")
async def create_video(
    mode: str = Form("text"),            # text | image | story
    prompt: str = Form(...),
    engine: str = Form("auto"),          # auto | kling | motion
    ratio: str = Form("16:9"),
    seconds: int = Form(5),
    scenes: int = Form(3),
    voice: str = Form(""),               # empty = no voiceover
    narration: str = Form(""),
    story: str = Form(""),               # optional edited story JSON
    image: UploadFile | None = File(None),
):
    if mode == "image" and not image:
        raise HTTPException(400, "Upload an image for Image → Video.")
    params = {
        "mode": mode, "prompt": prompt, "engine": engine,
        "ratio": ratio if ratio in config.RATIOS else "16:9",
        "seconds": seconds if seconds in config.DURATIONS else 5,
        "scenes": max(1, min(scenes, 4)), "voice": voice, "narration": narration,
        "story": json.loads(story) if story else None,
        "image_bytes": await image.read() if image else None,
    }
    return {"job_id": studio.start_job(params)}   # guard (public demo) records who started it


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    if job_id not in studio.jobs:
        raise HTTPException(404, "Job not found")
    return studio.jobs[job_id]


@app.get("/api/gallery")
def gallery(request: Request):
    who = guard.visitor.get()
    if guard.PUBLIC:
        guard.claim_finished_jobs(who)
    items = []
    for kind, folder in (("image", config.IMAGES_DIR), ("video", config.VIDEOS_DIR)):
        for path in folder.iterdir():
            if path.suffix in (".png", ".jpg", ".mp4") and (not guard.PUBLIC or guard.mine(path.stem, who)):
                items.append({"type": kind, "url": config.to_url(path), "name": path.stem,
                              "time": path.stat().st_mtime})
    return sorted(items, key=lambda item: item["time"], reverse=True)[:60]


@app.delete("/api/gallery/{kind}/{name}")
def delete_item(kind: str, name: str):
    folder = {"image": config.IMAGES_DIR, "video": config.VIDEOS_DIR}.get(kind)
    if not folder or "/" in name or ".." in name:
        raise HTTPException(400, "Bad request")
    if guard.PUBLIC and not guard.mine(name, guard.visitor.get()):
        raise HTTPException(403, "You can only delete your own creations.")
    for path in folder.glob(f"{name}.*"):
        path.unlink()
    return {"ok": True}


# ---------------- Website ----------------
app.mount("/media", StaticFiles(directory=config.STORAGE), name="media")
app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIR / "assets"), name="assets")


NO_CACHE = {"Cache-Control": "no-cache"}      # always load the newest HTML/CSS/JS


@app.get("/")
def home():
    return FileResponse(config.FRONTEND_DIR / "index.html", headers=NO_CACHE)


@app.get("/{filename}")
def frontend_file(filename: str):
    path = (config.FRONTEND_DIR / filename).resolve()
    if path.is_relative_to(config.FRONTEND_DIR) and path.is_file():
        return FileResponse(path, headers=NO_CACHE)
    return FileResponse(config.FRONTEND_DIR / "index.html", headers=NO_CACHE)
