"""
media.py - Creates images and videos.

Images:  Gemini  ->  OpenAI (backup)
Videos:  "runway"  = real AI motion (paid credits)
         "motion"  = Motion Preview: an AI image + cinematic camera move (ffmpeg), almost free
         "auto"    = Runway first, Motion Preview if Runway fails
"""

import base64
import hashlib
import io
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


def _video_runway(prompt, image_bytes, ratio, seconds, on_progress) -> Path:
    if not config.RUNWAY_API_KEY:
        raise MediaError("No Runway key in .env")
    from runwayml import RunwayML

    width, height = config.RATIOS.get(ratio, (1280, 720))
    runway_ratio = f"{width}:{height}" if ratio != "1:1" else "960:960"
    client = RunwayML(api_key=config.RUNWAY_API_KEY)
    try:
        if image_bytes:
            buffer = io.BytesIO()
            _fit_image(image_bytes, width, height).save(buffer, format="JPEG", quality=90)
            data_uri = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
            task = client.image_to_video.create(model=config.RUNWAY_IMAGE_MODEL, prompt_image=data_uri,
                                                prompt_text=prompt[:1000], ratio=runway_ratio,
                                                duration=seconds)
        else:
            task = client.text_to_video.create(model=config.RUNWAY_TEXT_MODEL, prompt_text=prompt[:1000],
                                               ratio=runway_ratio, duration=seconds)
    except Exception as error:
        if "enough credits" in str(error):
            raise MediaError("Runway has no credits (add them at dev.runwayml.com → Billing)") from error
        raise MediaError(f"Runway error: {str(error)[:200]}") from error

    # The video takes 1-3 minutes: ask Runway for the status every 5 seconds
    task = client.tasks.retrieve(task.id)
    while task.status in ("PENDING", "THROTTLED", "RUNNING"):
        on_progress(int((getattr(task, "progress", None) or 0) * 100))
        time.sleep(5)
        task = client.tasks.retrieve(task.id)
    if task.status != "SUCCEEDED":
        raise MediaError(f"Runway could not make this video: {getattr(task, 'failure', task.status)}")

    path = _new_file(config.VIDEOS_DIR, "mp4")
    urllib.request.urlretrieve(task.output[0], path)
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


def make_video(prompt: str, image_bytes: bytes | None = None, engine: str = "auto",
               ratio: str = "16:9", seconds: int = 5, on_progress=lambda pct: None) -> dict:
    """
    Returns {"path": Path, "engine": "Runway" / "Motion Preview", "notice": str or None}.
    """
    if engine in ("auto", "runway") and config.RUNWAY_API_KEY:
        try:
            path = _video_runway(prompt, image_bytes, ratio, seconds, on_progress)
            return {"path": path, "engine": "Runway", "notice": None}
        except MediaError as error:
            if engine == "runway":
                raise
            notice = f"{error} - made a free Motion Preview instead."
            print(f"[media] {notice}")
    else:
        notice = None if engine == "motion" else "No Runway key - made a Motion Preview instead."
    try:
        path = _video_motion(prompt, image_bytes, ratio, seconds, on_progress)
    except subprocess.CalledProcessError as error:
        raise MediaError(f"ffmpeg failed: {error.stderr.decode()[:200]}") from error
    return {"path": path, "engine": "Motion Preview", "notice": notice}
