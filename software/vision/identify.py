"""
vision/identify.py
Sends the frames from one capture to GPT and asks: what food is it, was it
put IN the fridge or taken OUT, and when will it go bad?

Run by itself on a capture folder:
    python vision/identify.py captures/20261107_114719
capture.py also calls identify_capture() automatically after each recording.
"""
import base64
import io
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, APIError
from PIL import Image

load_dotenv()
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
MAX_SIDE = 768                       # smaller images = cheaper, still plenty for GPT
EVENTS_FILE = Path("captures/events.jsonl")

PROMPT = """You are the vision system for a smart fridge.
Today's date is TODAY.
You will see frames from a short video of a hand moving through the fridge opening.
Frames from each camera are in time order (frame 1 = earliest).
The "overhead" camera looks down from above; the "side" camera looks from the side.
Some frames may show only a hand, or be blurry. Use the clearest frames.

Decide:
- "action": "in" if the hand arrives holding food and leaves empty (food put into the fridge),
  "out" if the hand arrives empty and leaves holding food (food taken out),
  "unclear" if you can't tell.
- What the food item is, and how long it will last in a refrigerator starting today.

Return ONLY a JSON object with exactly these keys:
{
  "action": "in | out | unclear",
  "item": "specific name, e.g. 'banana' or 'whole milk', or 'unknown'",
  "possible_items": ["up to 3 guesses, most likely first"],
  "category": "produce | dairy | meat | leftovers | drink | packaged | other",
  "printed_expiry_date": "YYYY-MM-DD if legible on the packaging, else null",
  "condition": "short description of how fresh it looks",
  "spoilage_signs": ["visible signs like browning or mold; empty list if none"],
  "days_until_expired": integer days from today until it should be thrown out, or null if unknown,
  "confidence": "low | medium | high",
  "reasoning": "one or two sentences"
}
Use "high" confidence only if the item is clearly identifiable in at least one sharp frame."""


def encode_image(path):
    img = Image.open(path).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def build_content(folder, today):
    """Prompt text followed by every picked frame, each labeled with its camera and order."""
    content = [{"type": "text", "text": PROMPT.replace("TODAY", today.isoformat())}]
    for cam in ("overhead", "side"):
        frames = sorted(folder.glob(f"{cam}_*.jpg"))   # skips the all_* debug frames
        for i, path in enumerate(frames, start=1):
            content.append({"type": "text", "text": f"{cam} camera, frame {i} of {len(frames)}:"})
            content.append({"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{encode_image(path)}"}})
    return content


def identify_capture(folder):
    folder = Path(folder)
    today = date.today()
    content = build_content(folder, today)
    if len(content) == 1:
        print("    No frames to send.")
        return None

    print(f"    Asking {MODEL}...")
    try:
        response = OpenAI().chat.completions.create(
            model=MODEL,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": content}],
        )
        result = json.loads(response.choices[0].message.content)
    except (APIError, json.JSONDecodeError) as e:
        print("    GPT error:", e)
        return None

    # Date math in Python, not GPT
    days = result.get("days_until_expired")
    result["estimated_expiry_date"] = (
        (today + timedelta(days=int(days))).isoformat() if days is not None else None)
    result["time"] = datetime.now().isoformat(timespec="seconds")
    result["capture_folder"] = str(folder)

    # Print a short summary
    action = {"in": "PUT IN", "out": "TOOK OUT"}.get(result.get("action"), "UNCLEAR")
    print(f"\n>>> {action}: {result.get('item')}  ({result.get('confidence')} confidence)")
    if result.get("estimated_expiry_date"):
        print(f"    Expires around {result['estimated_expiry_date']} ({days} days)")
    else:
        print(f"    Not sure. Guesses: {result.get('possible_items')}")
    print(f"    Why: {result.get('reasoning')}\n")

    # Keep a running log of every event, one JSON object per line
    EVENTS_FILE.parent.mkdir(exist_ok=True)
    with open(EVENTS_FILE, "a") as f:
        f.write(json.dumps(result) + "\n")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python vision/identify.py captures/<folder_name>")
        sys.exit(1)
    identify_capture(sys.argv[1])