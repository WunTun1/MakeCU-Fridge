"""The one place Gemini clients are created (item naming + nutrition chat)."""
from __future__ import annotations

import os

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None
    types = None

DEFAULT_MODEL = "gemini-2.5-flash"


def model_name() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)


def make_client():
    """A Gemini client, or None when no API key is configured (callers fall back).

    Pinned to the v1beta API: the SDK defaults to v1, which rejects both system
    instructions and function calling — the two things this app relies on."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or genai is None:
        return None
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(api_version="v1beta"))
