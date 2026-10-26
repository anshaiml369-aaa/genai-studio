"""
studio.py - The Video Studio (Kling-style).

Long work (making videos) runs as a background JOB:
  1. the browser starts a job      -> gets a job id
  2. the browser asks every second -> gets progress + current stage
  3. when done                     -> gets the final video URL
"""

import json
import re
import threading
import uuid

from openai import OpenAI

import config
import media
import speech

jobs: dict[str, dict] = {}          # job id -> {status, progress, stage, result, error}
jobs_lock = threading.Lock()


# ------------------------------------------------------------------
# Text helpers (Gemini is free -> try it first, OpenAI as backup)
# ------------------------------------------------------------------
def ask_llm(prompt: str, want_json: bool = False) -> str:
    if config.GEMINI_API_KEY:
        try:
            from google import genai

            client = genai.Client(api_key=config.GEMINI_API_KEY)
            extra = {"response_mime_type": "application/json"} if want_json else None
            return client.models.generate_content(model=config.GEMINI_TEXT_MODEL, contents=prompt,
                                                  config=extra).text
        except Exception as error:
            print(f"[studio] Gemini text failed, using OpenAI: {str(error)[:120]}")
    response = OpenAI(api_key=config.OPENAI_API_KEY).chat.completions.create(
        model=config.CHAT_MODEL, messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"} if want_json else None)
    return response.choices[0].message.content


def enhance_prompt(idea: str) -> str:
    return ask_llm(
        "Rewrite this idea into ONE rich, cinematic prompt for an AI video model. Describe subject, "
        "action, setting, lighting, mood, camera movement and style in 2-4 sentences. No real people "
        f"or copyrighted characters. Return only the prompt.\n\nIdea: \"{idea}\"").strip().strip('"')


def write_story(idea: str, scenes: int, seconds: int) -> dict:
    text = ask_llm(
        f"You are a film director. Plan a short video for this idea: \"{idea}\".\n"
        f"Exactly {scenes} scenes of about {seconds} seconds each. For every scene give:\n"
        "- visual: a detailed cinematic description for an AI video model (no on-screen text, "
        "no real people, no copyrighted characters)\n"
        f"- narration: one sentence a narrator says (speakable in {seconds} seconds)\n"
        'Return JSON: {"title": "...", "scenes": [{"visual": "...", "narration": "..."}]}',
        want_json=True)
    data = json.loads(re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M))
    data["scenes"] = data["scenes"][:scenes]
    return data


# ------------------------------------------------------------------
# Jobs
# ------------------------------------------------------------------
def _update(job_id: str, **fields) -> None:
    with jobs_lock:
        jobs[job_id].update(fields)


def start_job(params: dict) -> str:
    job_id = uuid.uuid4().hex[:10]
    jobs[job_id] = {"status": "running", "progress": 0, "stage": "Starting", "result": None,
                    "error": None, "notice": None}
    threading.Thread(target=_run_job, args=(job_id, params), daemon=True).start()
    return job_id


def _run_job(job_id: str, p: dict) -> None:
    """p = {mode, prompt, scenes, engine, ratio, seconds, voice, narration, image_bytes}"""
    try:
        # 1) Plan the scenes
        if p["mode"] == "story":
            _update(job_id, stage="Writing the story", progress=3)
            story = p.get("story") or write_story(p["prompt"], p["scenes"], p["seconds"])
            title, scenes = story["title"], story["scenes"]
        else:
            title = p["prompt"][:50]
            scenes = [{"visual": p["prompt"], "narration": p.get("narration", "")}]

        # 2) Make one clip per scene (each scene gets an equal share of the progress bar)
        clips, engines, share = [], set(), 80 / len(scenes)
        for i, scene in enumerate(scenes):
            base = 5 + i * share
            _update(job_id, stage=f"Generating scene {i + 1} of {len(scenes)}", progress=int(base))
            result = media.make_video(
                scene["visual"], p.get("image_bytes") if i == 0 else None, p["engine"], p["ratio"],
                p["seconds"], on_progress=lambda pct, b=base: _update(job_id, progress=int(b + share * pct / 100)))
            clips.append(result["path"])
            engines.add(result["engine"])
            if result["notice"]:
                _update(job_id, notice=result["notice"])

        # 3) Voiceover (optional) for each scene
        voices = []
        if p.get("voice"):
            _update(job_id, stage="Recording the narrator", progress=86)
            for scene in scenes:
                if scene.get("narration"):
                    audio = config.TMP_DIR / f"{uuid.uuid4().hex[:8]}.mp3"
                    audio.write_bytes(speech.speak(scene["narration"], p["voice"], "Cinematic, warm narrator voice."))
                    voices.append(audio)
                else:
                    voices.append(None)

        # 4) Join everything into one final MP4
        _update(job_id, stage="Editing the final cut", progress=92)
        final = _assemble(clips, voices) if (len(clips) > 1 or any(voices)) else clips[0]
        _update(job_id, status="done", progress=100, stage="Done",
                result={"url": config.to_url(final), "title": title, "engine": " + ".join(sorted(engines)),
                        "scenes": scenes})
    except Exception as error:
        print(f"[studio] job {job_id} failed: {error}")
        _update(job_id, status="error", error=str(error)[:300])


def _assemble(clips, voices):
    from moviepy import AudioFileClip, VideoFileClip, concatenate_videoclips

    opened, parts = [], []
    for i, clip_path in enumerate(clips):
        clip = VideoFileClip(str(clip_path))
        opened.append(clip)
        voice = voices[i] if i < len(voices) else None
        if voice:
            audio = AudioFileClip(str(voice))
            opened.append(audio)
            clip = clip.with_audio(audio.subclipped(0, min(audio.duration, clip.duration)))
        parts.append(clip)
    final = concatenate_videoclips(parts, method="compose")
    out = media._new_file(config.VIDEOS_DIR, "mp4")
    final.write_videofile(str(out), fps=25, codec="libx264", audio_codec="aac", preset="veryfast",
                          threads=4, logger=None)
    for item in [final, *opened]:
        item.close()
    for path in clips + [v for v in voices if v]:                 # remove the in-between files
        if path != out:
            path.unlink(missing_ok=True)
    return out
