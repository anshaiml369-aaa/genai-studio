"""
media.py - Creates images and videos.

Images:  Gemini  ->  OpenAI (backup)
Videos:  "kling"   = Kling AI (paid credits, very realistic)
         "motion"  = Motion Preview: an AI image + cinematic camera move (ffmpeg), almost free
         "auto"    = Kling first, Motion Preview if Kling fails
"""

import base64
import hashlib
import io
import json
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

from openai import OpenAI
from PIL import Image, ImageOps

import config


class MediaError(Exception):
    """Raised when an image or video cannot be created."""


def _new_file(folder: Path, extension: str) -> Path:
    return folder / f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.{extension}"


# ==================================================================
# IMAGES
# ==================================================================
_gemini_blocked_until = 0.0      # skip Gemini for a while after a "no quota" error


def _image_gemini(prompt: str, ratio: str) -> bytes:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=config.GEMINI_IMAGE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"], image_config=types.ImageConfig(aspect_ratio=ratio)),
    )
    for part in response.candidates[0].content.parts:
        if part.inline_data:
            return part.inline_data.data
    raise MediaError("Gemini returned no image (the prompt may have been blocked).")


def _image_openai(prompt: str, ratio: str) -> bytes:
    size = {"16:9": "1536x1024", "9:16": "1024x1536"}.get(ratio, "1024x1024")
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    response = client.images.generate(model=config.OPENAI_IMAGE_MODEL, prompt=prompt,
                                      size=size, quality="low")
    return base64.b64decode(response.data[0].b64_json)


def make_image(prompt: str, ratio: str = "16:9") -> tuple[Path, str]:
    """Returns (saved image file, engine name)."""
    global _gemini_blocked_until
    errors = []
    if config.GEMINI_API_KEY and time.time() > _gemini_blocked_until:
        try:
            data = _image_gemini(prompt, ratio)
            path = _new_file(config.IMAGES_DIR, "png")
            path.write_bytes(data)
            return path, "Gemini"
        except Exception as error:
            if "RESOURCE_EXHAUSTED" in str(error):
                _gemini_blocked_until = time.time() + 3600
                print("[media] Gemini image quota is 0 - using OpenAI for the next hour")
            else:
                print(f"[media] Gemini image failed: {str(error)[:150]}")
            errors.append("Gemini")
    if config.OPENAI_API_KEY:
        try:
            data = _image_openai(prompt, ratio)
            path = _new_file(config.IMAGES_DIR, "png")
            path.write_bytes(data)
            return path, "OpenAI"
        except Exception as error:
            raise MediaError(f"Could not create the image: {str(error)[:200]}") from error
    raise MediaError("No image engine available - add an OpenAI or Gemini key.")


# ==================================================================
# VIDEOS
# ==================================================================
def _fit_image(image_bytes: bytes, width: int, height: int) -> Image.Image:
    """Crop the picture to the video shape (like 'cover' in CSS)."""
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
    return ImageOps.fit(image, (width, height), Image.Resampling.LANCZOS)


# ---------- Kling AI (paid) ----------
def _kling_call(method: str, path: str, payload: dict | None = None) -> dict:
    request = urllib.request.Request(
        config.KLING_API + path, method=method,
        data=json.dumps(payload).encode() if payload else None,
        headers={"Authorization": f"Bearer {config.KLING_API_KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            answer = json.load(response)
    except urllib.error.HTTPError as error:
        answer = json.loads(error.read() or b"{}") or {"message": f"HTTP {error.code}"}
    if answer.get("code", 0) != 0:
        message = answer.get("message", "unknown error")
        if "balance" in message.lower() or "resource pack" in message.lower():
            message = "no credits (buy a resource pack at app.klingai.com/global/dev)"
        raise MediaError(f"Kling: {message}")
    return answer["data"]


def _video_kling(prompt, image_bytes, ratio, seconds, on_progress) -> Path:
    if not config.KLING_API_KEY:
        raise MediaError("No KLING_API_KEY in .env")
    width, height = config.RATIOS.get(ratio, (1280, 720))
    payload = {"model_name": config.KLING_MODEL, "prompt": prompt[:2500], "duration": str(seconds),
               "mode": "std", "aspect_ratio": ratio}
    if image_bytes:
        buffer = io.BytesIO()
        _fit_image(image_bytes, width, height).save(buffer, format="JPEG", quality=90)
        payload["image"] = base64.b64encode(buffer.getvalue()).decode()
        kind = "image2video"
    else:
        kind = "text2video"
    task_id = _kling_call("POST", f"/v1/videos/{kind}", payload)["task_id"]

    # Kling takes 1-5 minutes: check every 5 seconds
    started = time.time()
    while True:
        task = _kling_call("GET", f"/v1/videos/{kind}/{task_id}")
        if task["task_status"] == "succeed":
            break
        if task["task_status"] == "failed":
            raise MediaError(f"Kling could not make this video: {task.get('task_status_msg', '')}")
        on_progress(min(95, int((time.time() - started) / 3)))
        time.sleep(5)
    path = _new_file(config.VIDEOS_DIR, "mp4")
    urllib.request.urlretrieve(task["task_result"]["videos"][0]["url"], path)
    return path


# Camera moves for Motion Preview: (zoom formula, x formula, y formula); n = number of frames
_CAMERA_MOVES = [
    ("1+0.15*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),            # slow push in
    ("1.15-0.15*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),         # slow pull out
    ("1.15", "(iw-iw/zoom)*on/{n}", "ih/2-(ih/zoom/2)"),                  # pan left -> right
    ("1.15", "(iw-iw/zoom)*(1-on/{n})", "(ih-ih/zoom)*on/{n}"),           # diagonal drift
]


def _video_motion(prompt, image_bytes, ratio, seconds, on_progress) -> Path:
    """Motion Preview: animate a still image with a smooth cinematic camera move."""
    width, height = config.RATIOS.get(ratio, (1280, 720))
    if not image_bytes:
        on_progress(10)
        image_path, _ = make_image(prompt, ratio)
        image_bytes = image_path.read_bytes()
    on_progress(50)

    # Upscale 2x first so the zoom looks smooth (no shaking)
    frame = config.TMP_DIR / f"frame_{uuid.uuid4().hex[:6]}.jpg"
    _fit_image(image_bytes, width * 2, height * 2).save(frame, quality=92)

    fps, frames = 25, 25 * seconds
    move = _CAMERA_MOVES[int(hashlib.md5(prompt.encode()).hexdigest(), 16) % len(_CAMERA_MOVES)]
    zoom, x, y = (part.format(n=frames) for part in move)
    path = _new_file(config.VIDEOS_DIR, "mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(frame),
         "-vf", f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},format=yuv420p",
         "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", str(path)],
        check=True, capture_output=True,
    )
    frame.unlink(missing_ok=True)
    on_progress(100)
    return path


ENGINES = {          # name shown in the app : function that makes the video
    "kling": ("Kling", _video_kling),
    "motion": ("Motion Preview", _video_motion),
}


def make_video(prompt: str, image_bytes: bytes | None = None, engine: str = "auto",
               ratio: str = "16:9", seconds: int = 5, on_progress=lambda pct: None) -> dict:
    """
    Returns {"path": Path, "engine": name, "notice": str or None}.
    "auto" tries each engine in order and uses the first one that works.
    """
    if engine == "auto":
        order = (["kling"] if config.KLING_API_KEY else []) + ["motion"]
    else:
        order = [engine if engine in ENGINES else "motion"]

    problems = []
    for key in order:
        name, function = ENGINES[key]
        try:
            path = function(prompt, image_bytes, ratio, seconds, on_progress)
        except subprocess.CalledProcessError as error:
            problems.append(f"ffmpeg failed: {error.stderr.decode()[:150]}")
            continue
        except Exception as error:
            problems.append(str(error)[:200])
            print(f"[media] {name} failed: {str(error)[:200]}")
            continue
        notice = f"{problems[-1]} - used {name} instead." if problems else None
        return {"path": path, "engine": name, "notice": notice}
    raise MediaError(problems[-1] if problems else "No video engine available.")
