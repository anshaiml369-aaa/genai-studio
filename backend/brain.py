"""
brain.py - The chat assistant.

Streams the reply word by word and lets the AI decide (function calling) when
to create an image or a video. Everything is sent to the browser as small
JSON "events" (Server-Sent Events), e.g.
    {"type": "text",  "delta": "Hello"}
    {"type": "image", "url": "/media/images/..png", "engine": "OpenAI"}
    {"type": "video", "url": "/media/videos/..mp4", "engine": "Kling"}
"""

import base64
import json
import threading
import time

from openai import OpenAI

import config
import media

client = OpenAI(api_key=config.OPENAI_API_KEY)

# personality -> (system prompt, voice style)
PERSONALITIES = {
    "friendly": ("You are Kalpana, a friendly and helpful AI assistant.",
                 "Speak in a warm, friendly and cheerful tone."),
    "teacher": ("You are Kalpana, a patient teacher for engineering students. Explain step by step "
                "with simple examples and end with one quick question to check understanding.",
                "Speak slowly and clearly like a kind teacher."),
    "hinglish": ("You are Kalpana, a fun friend who replies in Hinglish (a natural mix of Hindi and "
                 "English written in Roman script).",
                 "Speak casually and energetically, like a friend from India."),
    "interviewer": ("You are Kalpana, a strict but helpful technical interviewer for software jobs. "
                    "Ask one question at a time, then give honest feedback.",
                    "Speak in a calm, professional tone."),
}

RULES = (
    " Use markdown (bold, lists, code blocks) when it helps. Keep answers short and clear "
    "unless the user asks for detail. When the user shares an image, describe what is relevant."
    " You can create pictures with generate_image and short videos with generate_video. "
    "Use them ONLY when the user asks to draw/create/generate/make an image or a video/animation. "
    "Write tool prompts in detailed, cinematic English. Before calling a tool, say one short sentence."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "generate_image",
        "description": "Create a new picture from a text description.",
        "parameters": {"type": "object", "required": ["prompt"], "properties": {
            "prompt": {"type": "string", "description": "Detailed description: subject, style, light, colors."}}},
    }},
    {"type": "function", "function": {
        "name": "generate_video",
        "description": "Create a short (5 second) video clip.",
        "parameters": {"type": "object", "required": ["prompt", "animate_last_image"], "properties": {
            "prompt": {"type": "string", "description": "Detailed description of scene, motion and camera."},
            "animate_last_image": {"type": "boolean",
                                   "description": "True if the user wants to animate the most recent image "
                                                  "in the conversation (uploaded or generated)."}}},
    }},
]


def event(data: dict) -> str:
    """Format one Server-Sent Event."""
    return f"data: {json.dumps(data)}\n\n"


def _to_api_messages(history: list[dict], personality: str) -> list[dict]:
    system = PERSONALITIES.get(personality, PERSONALITIES["friendly"])[0] + RULES
    messages = [{"role": "system", "content": system}]
    for msg in history[-20:]:                                  # last 20 messages = memory
        if msg["role"] == "user" and msg.get("images"):
            parts = [{"type": "text", "text": msg.get("text") or "What is in this image?"}]
            parts += [{"type": "image_url", "image_url": {"url": url}} for url in msg["images"]]
            messages.append({"role": "user", "content": parts})
        else:
            notes = "".join(f"\n[I created a {m['type']}: {m.get('prompt', '')}]" for m in msg.get("media", []))
            messages.append({"role": msg["role"], "content": (msg.get("text") or "") + notes})
    return messages


def _last_image(history: list[dict]) -> bytes | None:
    """Find the newest picture in the chat (an upload or one the AI made)."""
    for msg in reversed(history):
        images = [m["url"] for m in msg.get("media", []) if m["type"] == "image"] + msg.get("images", [])
        for url in reversed(images):
            if url.startswith("data:"):
                return base64.b64decode(url.split(",", 1)[1])
            path = (config.STORAGE / url.removeprefix("/media/")).resolve()
            if path.is_relative_to(config.STORAGE) and path.is_file():   # stay inside storage/
                return path.read_bytes()
    return None


def _run_with_heartbeat(work, label):
    """Run slow work in a thread and yield progress events every second (keeps the stream alive)."""
    box = {"progress": 0}

    def target():
        try:
            box["result"] = work(lambda pct: box.update(progress=pct))
        except Exception as error:
            box["error"] = error

    thread = threading.Thread(target=target)
    thread.start()
    while thread.is_alive():
        yield event({"type": "status", "text": label, "progress": box["progress"]})
        time.sleep(1)
    if "error" in box:
        raise box["error"]
    yield {"result": box.get("result")}      # the final item is a dict (events are strings)


def chat_events(history: list[dict], personality: str):
    """Generator of SSE events for one assistant reply."""
    try:
        stream = client.chat.completions.create(model=config.CHAT_MODEL, tools=TOOLS, stream=True,
                                                messages=_to_api_messages(history, personality))
        tool_calls = {}
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield event({"type": "text", "delta": delta.content})
            for call in delta.tool_calls or []:           # tool calls arrive in pieces -> join them
                piece = tool_calls.setdefault(call.index, {"name": "", "args": ""})
                piece["name"] += call.function.name or ""
                piece["args"] += call.function.arguments or ""

        for piece in tool_calls.values():
            args = json.loads(piece["args"] or "{}")
            prompt = args.get("prompt", "")
            try:
                if piece["name"] == "generate_image":
                    for item in _run_with_heartbeat(lambda p: media.make_image(prompt), "Painting your image"):
                        if isinstance(item, str):
                            yield item
                    path, engine = item["result"]
                    yield event({"type": "image", "url": config.to_url(path), "prompt": prompt, "engine": engine})

                elif piece["name"] == "generate_video":
                    source = _last_image(history) if args.get("animate_last_image") else None
                    label = "Animating your image" if source else "Directing your video"
                    for item in _run_with_heartbeat(
                            lambda p: media.make_video(prompt, source, "auto", on_progress=p), label):
                        if isinstance(item, str):
                            yield item
                    result = item["result"]
                    if result["notice"]:
                        yield event({"type": "notice", "text": result["notice"]})
                    yield event({"type": "video", "url": config.to_url(result["path"]),
                                 "prompt": prompt, "engine": result["engine"]})
            except Exception as error:
                yield event({"type": "error", "text": str(error)[:300]})
    except Exception as error:
        yield event({"type": "error", "text": f"Chat failed: {str(error)[:300]}"})
    yield event({"type": "done"})
