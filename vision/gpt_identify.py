"""Name a cropped fridge item with OpenAI's GPT — a testing stand-in for the
backend's Gemini classifier (vision/classifier.py), used by vision/snap.py.

Asks for the same fields the classifier returns. Never asks for a weight:
quantity comes from the scale, not the model. Reads OPENAI_API_KEY from .env;
OPENAI_MODEL picks the model.
"""
from __future__ import annotations

import base64
import json
import os
import unicodedata
from datetime import date, timedelta

import cv2
import numpy as np
from dotenv import load_dotenv

load_dotenv()

# Benchmarked 2026-11-07 on real fridge photos (bagged onions, shallot, orange; 8 tries each):
# gpt-5.6-terra at low effort was as accurate as any (7/8, never confidently wrong) and fastest (~1.5 s
# typical); gpt-5.6-sol and gpt-5.5 were slower and sometimes confidently wrong; gpt-5.6-luna was weakest.
DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_EFFORT = "low"
MAX_SIDE = 768                  # the close-up: smaller is cheaper and still plenty for naming food
CONTEXT_SIDE = 512              # the whole-shelf before/after photos only give context
# OPENAI_MODEL / OPENAI_REASONING_EFFORT (none|minimal|low|medium|high; lower = faster) override the defaults.

PROMPT = """You identify a grocery item from a fridge camera for an inventory system.
Today's date is {today}. One item was just put on the shelf. You'll see:
- a close-up crop around where the camera saw a change,
- the whole shelf AFTER, with that spot outlined in a green box,
- (if present) the whole shelf BEFORE the item was added.
The box is only a hint: clear plastic bags barely show up for the camera, so the box may cover
just part of the item, or part of its bag. Compare BEFORE and AFTER to find what was added,
look through any bag at what's inside, and name that one new item (e.g. a bagged onion is
"Yellow Onion"). Ignore everything that was already on the shelf.
Respond with ONLY a JSON object with exactly these keys:
{{
  "item_name": "the plain grocery name a recipe would use, e.g. 'Orange', 'Whole Milk', 'Beef Steak', 'Chicken Thighs', 'Jalapeno Pepper' (the full name, not just 'Jalapeno'; plain letters, no accents; no words like 'raw', 'fresh', 'packaged'); 'Unknown Item' if you can't tell",
  "category": "produce | dairy | meat | seafood | leftovers | drink | packaged | other",
  "visible_expiration_date": "YYYY-MM-DD only if a printed date is legible, else null; never guess one",
  "days_until_expired": integer days it should stay good in a refrigerator from today, judged from what it is and how fresh it looks, or null,
  "confidence": number from 0 to 1,
  "reasoning": "one short sentence"
}}"""


def _data_url(image: np.ndarray, max_side: int = MAX_SIDE) -> str:
    h, w = image.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("Couldn't encode the image as JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def model_name() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_MODEL)


def with_box(full: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """The whole photo with the item outlined, so GPT knows which thing to name."""
    out = full.copy()
    x, y, w, h = box
    cv2.rectangle(out, (x, y), (x + w, y + h), (0, 220, 0), max(3, full.shape[1] // 300))
    return out


def identify(
    crop: np.ndarray,
    full: np.ndarray | None = None,
    box: tuple[int, int, int, int] | None = None,
    before: np.ndarray | None = None,
) -> dict:
    """GPT's read of the new item: the crop for detail, the whole AFTER photo with the change
    boxed, and the BEFORE photo so it can tell what was added even when the box is partial.
    Raises if no key is set or the call fails."""
    from openai import OpenAI

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY isn't set — add it to .env in the fridge_bot folder")
    today = date.today()
    labeled = [("Close-up crop:", crop, MAX_SIDE)]
    if full is not None and box is not None:
        labeled.append(("Whole shelf AFTER (change outlined in green):", with_box(full, box), CONTEXT_SIDE))
    if before is not None:
        labeled.append(("Whole shelf BEFORE:", before, CONTEXT_SIDE))
    effort = os.getenv("OPENAI_REASONING_EFFORT", DEFAULT_EFFORT if model_name() == DEFAULT_MODEL else "")
    response = OpenAI().chat.completions.create(
        model=model_name(),
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": PROMPT.format(today=today.isoformat())},
            *(part for label, img, side in labeled for part in (
                {"type": "text", "text": label},
                {"type": "image_url", "image_url": {"url": _data_url(img, side)}},
            )),
        ]}],
        **({"reasoning_effort": effort} if effort else {}),
    )
    info = json.loads(response.choices[0].message.content)
    # Plain ASCII names: the recipe matcher splits "Jalapeño" into "jalape o", which matches nothing.
    if isinstance(info.get("item_name"), str):
        info["item_name"] = unicodedata.normalize("NFKD", info["item_name"]).encode("ascii", "ignore").decode().strip()
    # Date math in Python, not GPT: a printed date wins, else today + the estimate.
    days = info.get("days_until_expired")
    info["expiration_date"] = info.get("visible_expiration_date") or (
        (today + timedelta(days=int(days))).isoformat() if isinstance(days, (int, float)) else None
    )
    return info


if __name__ == "__main__":
    import sys

    image = cv2.imread(sys.argv[1]) if len(sys.argv) > 1 else None
    if image is None:
        sys.exit("Usage: python -m vision.gpt_identify path/to/photo.jpg")
    print(f"Asking {model_name()}...")
    print(json.dumps(identify(image), indent=2))
