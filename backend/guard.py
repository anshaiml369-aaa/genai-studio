"""
guard.py - Protection for the public demo. Switched on only with PUBLIC_DEMO=1 (the Hugging Face Space);
running locally, nothing here changes how the app behaves.

- per-visitor hourly limits on every paid route (visitor = a random cookie, plus the client IP)
- daily caps on images and videos for the whole Space; real Kling video has its own small cap, after which
  videos fall back to the free Motion Preview and say so
- each visitor's gallery shows (and can delete) only what that visitor made: uploads can be personal photos
- files older than CLEANUP_HOURS are deleted, so the Space's disk never fills up
- request bodies over MAX_UPLOAD_MB are refused
"""

import contextvars
import os
import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

import config

PUBLIC = os.getenv("PUBLIC_DEMO") == "1"
COOKIE = "kalpana_visitor"


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


PER_HOUR = {"chat": _int("CHATS_PER_HOUR", 30), "voice": _int("VOICE_PER_HOUR", 40), "write": _int("WRITES_PER_HOUR", 15),
            "image": _int("IMAGES_PER_HOUR", 6), "video": _int("VIDEOS_PER_HOUR", 3)}
PER_DAY = {"chat": _int("CHATS_PER_DAY", 400), "image": _int("IMAGES_PER_DAY", 60), "video": _int("VIDEOS_PER_DAY", 20),
           "kling": _int("KLING_VIDEOS_PER_DAY", 3)}
MAX_UPLOAD = _int("MAX_UPLOAD_MB", 12) * 1024 * 1024
CLEANUP_HOURS = _int("CLEANUP_HOURS", 6)

ROUTES = {"/api/chat": "chat", "/api/speak": "voice", "/api/transcribe": "voice", "/api/enhance": "write",
          "/api/story": "write", "/api/image": "image", "/api/videos": "video"}

visitor = contextvars.ContextVar("visitor", default="")
_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)          # "kind:who" -> request times in the last hour
_day = {"date": "", "count": defaultdict(int)}
owners: dict[str, str] = {}                           # file stem -> visitor id
job_owners: dict[str, str] = {}                       # studio job id -> visitor id


class LimitReached(Exception):
    pass


def _within_hour(key: str, limit: int) -> bool:
    now = time.time()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def spend_day(kind: str) -> bool:
    """Count one use of a daily-capped resource; False when today's cap is used up."""
    today = time.strftime("%Y-%m-%d")
    with _lock:
        if _day["date"] != today:
            _day["date"], _day["count"] = today, defaultdict(int)
        if _day["count"][kind] >= PER_DAY[kind]:
            return False
        _day["count"][kind] += 1
        return True


def _stem(url: str) -> str:
    return url.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def remember(url: str, who: str | None = None) -> None:
    who = who if who is not None else visitor.get()
    if who:
        owners[_stem(url)] = who


def mine(stem: str, who: str) -> bool:
    if stem in owners:
        return owners[stem] == who
    return False


def install(app, media, studio, brain) -> None:
    """Wire the guard into the app. A no-op unless PUBLIC_DEMO=1."""
    if not PUBLIC:
        return

    @app.middleware("http")
    async def limits(request: Request, call_next):
        who = request.cookies.get(COOKIE) or uuid.uuid4().hex
        visitor.set(who)
        if int(request.headers.get("content-length") or 0) > MAX_UPLOAD:
            return JSONResponse({"detail": f"Upload too large for the public demo (max {MAX_UPLOAD // 1048576} MB)."}, 413)
        kind = ROUTES.get(request.url.path) if request.method == "POST" else None
        if kind:
            ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                  or (request.client.host if request.client else "?"))
            if not (_within_hour(f"{kind}:{who}", PER_HOUR[kind]) and _within_hour(f"{kind}:{ip}", PER_HOUR[kind] * 2)):
                return JSONResponse({"detail": f"Public demo limit reached for {kind} ({PER_HOUR[kind]} per hour). "
                                               "Please try again later."}, 429)
            if kind == "chat" and not spend_day("chat"):
                return JSONResponse({"detail": "The public demo has reached today's chat limit. Please come back tomorrow."}, 429)
        response = await call_next(request)
        if COOKIE not in request.cookies:
            response.set_cookie(COOKIE, who, max_age=7 * 86400, httponly=True, samesite="lax", secure=True)
        return response

    # daily caps live on the media functions themselves, so the chat's tool calls and the studio both count
    make_image, make_video = media.make_image, media.make_video

    def guarded_image(*args, **kwargs):
        if not spend_day("image"):
            raise media.MediaError("The public demo has made today's images. Please come back tomorrow.")
        path, engine = make_image(*args, **kwargs)
        remember(config.to_url(path))
        return path, engine

    def guarded_video(prompt, image_bytes=None, engine="auto", *args, **kwargs):
        if not spend_day("video"):
            raise media.MediaError("The public demo has made today's videos. Please come back tomorrow.")
        note = None
        if config.KLING_API_KEY and engine in ("auto", "kling"):
            if not spend_day("kling"):
                engine, note = "motion", "Today's real AI-video quota is used up - made a Motion Preview instead."
        result = make_video(prompt, image_bytes, engine, *args, **kwargs)
        if note and not result.get("notice"):
            result["notice"] = note
        return result

    media.make_image, media.make_video = guarded_image, guarded_video

    # studio jobs run in their own thread: remember who started each one
    start_job = studio.start_job

    def guarded_start(params):
        job_id = start_job(params)
        job_owners[job_id] = visitor.get()
        return job_id

    studio.start_job = guarded_start

    # chat replies can create media through tool calls: claim every media URL the stream sends
    chat_events = brain.chat_events

    def guarded_chat(history, personality):
        who = visitor.get()            # read now, in the request; the stream itself runs later in a worker thread

        def stream():
            for item in chat_events(history, personality):
                if isinstance(item, str) and '"url": "/media/' in item:
                    remember(item.split('"url": "', 1)[1].split('"', 1)[0], who)
                yield item
        return stream()

    brain.chat_events = guarded_chat
    threading.Thread(target=_cleanup_loop, daemon=True).start()


def claim_finished_jobs(who: str) -> None:
    for job_id, owner in list(job_owners.items()):
        job = studio_jobs().get(job_id) or {}
        if owner and job.get("status") == "done" and job.get("result"):
            remember(job["result"]["url"], owner)


def studio_jobs() -> dict:
    import studio
    return studio.jobs


def _cleanup_loop() -> None:
    while True:
        cutoff = time.time() - CLEANUP_HOURS * 3600
        for folder in (config.IMAGES_DIR, config.VIDEOS_DIR, config.AUDIO_DIR, config.TMP_DIR, config.STORAGE / "uploads"):
            if folder.is_dir():
                for path in folder.iterdir():
                    try:
                        if path.is_file() and path.stat().st_mtime < cutoff:
                            path.unlink()
                            owners.pop(path.stem, None)
                    except OSError:
                        pass
        time.sleep(1800)
