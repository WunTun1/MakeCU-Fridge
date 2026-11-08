"""AI naming for brand-new items only — everything else in this app is
plain code. Section 7.

Called when a changed region can't be matched to any known item. Quantity
always comes from the scale, never from the model. The model reports a
printed expiry date only if it can read one, and separately estimates days
until the item goes bad from how it looks; intelligence/expiry.py decides
which to trust and labels estimates as such.

Uses Google Gemini (multimodal: text + image in one call).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import cv2
import numpy as np

from gemini import make_client, model_name, types

log = logging.getLogger("refridge.vision.classifier")

LOW_CONFIDENCE_THRESHOLD = 0.6

SYSTEM_PROMPT = (
    "You identify grocery items from a fridge camera for an inventory system. "
    "Look at the cropped item photo (and the full shelf photo for context). "
    "Respond with ONLY compact JSON: "
    '{"item_name": str, "category": "produce|dairy|meat|seafood|leftovers|drink|packaged|other", '
    '"visible_expiration_date": "YYYY-MM-DD" or null, "days_until_expired": int or null, '
    '"confidence": 0-1}. '
    "visible_expiration_date: only if you can actually read a printed date on the packaging — never guess one. "
    "days_until_expired: your estimate of how many days from today this will stay good in a refrigerator, "
    "judged from what kind of food it is and how fresh it looks (browning, wilting, mold mean fewer days); "
    "null if you can't tell. If you aren't confident what the item is, say so with a low confidence score "
    "rather than guessing a specific brand."
)


def _encode_jpeg(frame: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        raise RuntimeError("Failed to encode frame as JPEG")
    return bytes(buf)


def identify_item(
    crop: np.ndarray,
    shelf_context: np.ndarray | None,
    measured_grams: float,
) -> dict:
    """Returns {"item_name", "category", "visible_expiration_date",
    "days_until_expired", "confidence", "needs_confirmation"}. Falls back to an
    "Unknown Item" placeholder (flagged for user confirmation) if no API key is
    configured or the call fails."""
    client = make_client()
    if client is None:
        return _unknown_item_fallback()

    today = datetime.now(timezone.utc).date().isoformat()
    parts = [
        f"Today is {today}. "
        + (f"Measured weight: {measured_grams:.0f} g. " if measured_grams > 0 else "Weight: not measured. ")
        + "Cropped item photo:",
        types.Part.from_bytes(data=_encode_jpeg(crop), mime_type="image/jpeg"),
    ]
    if shelf_context is not None:
        parts.append("Full shelf photo for context:")
        parts.append(types.Part.from_bytes(data=_encode_jpeg(shelf_context), mime_type="image/jpeg"))

    try:
        response = client.models.generate_content(
            model=model_name(),
            contents=parts,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
            ),
        )
        result = json.loads(response.text)
        if not isinstance(result, dict):
            raise ValueError(f"expected a JSON object, got {type(result).__name__}")
        result["confidence"] = float(result.get("confidence", 0.5))
    except Exception:
        # Still fall back so the fridge keeps working, but never silently —
        # a bad key or model name would otherwise look like "AI can't recognize anything".
        log.exception("Gemini item identification failed; asking the user instead")
        return _unknown_item_fallback()

    result["needs_confirmation"] = result["confidence"] < LOW_CONFIDENCE_THRESHOLD
    return result


WHICH_PROMPT = (
    "Something was just taken out of a fridge. The first photo is a crop of where it sat, from "
    "before it was taken; the second is the whole shelf before. Which of the listed items is it? "
    'Respond with ONLY compact JSON: {"index": int or null, "confidence": 0-1}. index is the '
    "item's number in the list; null if none of them fits."
)


def which_item(crop: np.ndarray, shelf_context: np.ndarray | None, names: list[str]) -> int | None:
    """Which of `names` the crop shows (an index into it), or None if Gemini is off, unsure, or
    sees none of them."""
    client = make_client()
    if client is None or not names:
        return None
    listing = "\n".join(f"{i}: {n}" for i, n in enumerate(names))
    parts = [f"Items on the shelf:\n{listing}\nCrop of where it was:",
             types.Part.from_bytes(data=_encode_jpeg(crop), mime_type="image/jpeg")]
    if shelf_context is not None:
        parts += ["Whole shelf, before:", types.Part.from_bytes(data=_encode_jpeg(shelf_context), mime_type="image/jpeg")]
    try:
        response = client.models.generate_content(
            model=model_name(), contents=parts,
            config=types.GenerateContentConfig(system_instruction=WHICH_PROMPT, response_mime_type="application/json"),
        )
        result = json.loads(response.text)
        index, confidence = result.get("index"), float(result.get("confidence", 0))
    except Exception:
        log.exception("Gemini couldn't say which item was taken out; asking the user instead")
        return None
    if isinstance(index, int) and 0 <= index < len(names) and confidence >= LOW_CONFIDENCE_THRESHOLD:
        return index
    return None


def _unknown_item_fallback() -> dict:
    return {
        "item_name": "Unknown Item",
        "category": None,
        "visible_expiration_date": None,
        "days_until_expired": None,
        "confidence": 0.0,
        "needs_confirmation": True,
    }
