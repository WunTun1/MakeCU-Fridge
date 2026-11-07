"""AI naming for brand-new items only — everything else in this app is
plain code. Section 7.

Called when a changed region can't be matched to any known item. Quantity
always comes from the scale, never from the model; the model also isn't
trusted to invent an expiration date it can't actually read.

Uses Google Gemini (multimodal: text + image in one call).
"""
from __future__ import annotations

import json
import os

import cv2
import numpy as np

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None
    types = None

DEFAULT_MODEL = "gemini-2.5-flash"
LOW_CONFIDENCE_THRESHOLD = 0.6

SYSTEM_PROMPT = (
    "You identify grocery items from a fridge camera for an inventory system. "
    "Look at the cropped item photo (and the full shelf photo for context). "
    "Respond with ONLY compact JSON: "
    '{"item_name": str, "category": str, "visible_expiration_date": "YYYY-MM-DD" or null, "confidence": 0-1}. '
    "Only set visible_expiration_date if you can actually read a printed date on the packaging — "
    "never guess one. If you aren't confident what the item is, say so with a low confidence score "
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
    """Returns {"item_name", "category", "visible_expiration_date", "confidence",
    "needs_confirmation"}. Falls back to an "Unknown Item" placeholder (flagged
    for user confirmation) if no API key is configured or the call fails."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or genai is None:
        return _unknown_item_fallback()

    parts = [
        f"Measured weight: {measured_grams:.0f} g. Cropped item photo:",
        types.Part.from_bytes(data=_encode_jpeg(crop), mime_type="image/jpeg"),
    ]
    if shelf_context is not None:
        parts.append("Full shelf photo for context:")
        parts.append(types.Part.from_bytes(data=_encode_jpeg(shelf_context), mime_type="image/jpeg"))

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
            contents=parts,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
            ),
        )
        result = json.loads(response.text)
    except Exception:
        return _unknown_item_fallback()

    result.setdefault("confidence", 0.5)
    result["needs_confirmation"] = result["confidence"] < LOW_CONFIDENCE_THRESHOLD
    return result


def _unknown_item_fallback() -> dict:
    return {
        "item_name": "Unknown Item",
        "category": None,
        "visible_expiration_date": None,
        "confidence": 0.0,
        "needs_confirmation": True,
    }
