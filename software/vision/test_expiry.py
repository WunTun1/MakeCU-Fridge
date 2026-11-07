"""
vision/test_expiry.py
Send two photos of a food item (overhead + side) to OpenAI and get back
what it is, its condition, and an estimated expiration date.

Usage (from the fridge_bot folder):
    python vision/test_expiry.py test_images/overhead.jpg test_images/side.jpg
"""
import base64
import io
import json
import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv
from openai import OpenAI, APIError
from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener  # lets Pillow open iPhone .HEIC photos
    register_heif_opener()
except ImportError:
    pass

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")   # cheap model for testing
MAX_SIDE = 1024                                     # shrink images to save tokens
PRICE_IN, PRICE_OUT = 0.20, 1.20                    # Luna, USD per 1M tokens

PROMPT = """You are the vision system for a smart fridge.
Today's date is TODAY.
Image 1 is an OVERHEAD view and image 2 is a SIDE view of the same food item.
Assume the item is being stored in a refrigerator starting today.

Return ONLY a JSON object with exactly these keys:
{
  "item": "specific name, e.g. 'banana' or 'whole milk'",
  "category": "produce | dairy | meat | leftovers | drink | packaged | other",
  "packaged": true or false,
  "printed_expiry_date": "YYYY-MM-DD if a date is legible on the packaging, else null",
  "condition": "short description of how fresh it looks",
  "spoilage_signs": ["list any visible signs like browning, mold, wilting; empty list if none"],
  "days_until_expired": integer number of days from today until it should be thrown out (0 if already spoiled),
  "confidence": "low | medium | high",
  "reasoning": "one or two sentences explaining the estimate"
}
If a printed date is legible, base the estimate on it, but shorten it if the item looks worse than the date suggests."""


def encode_image(path: str) -> str:
    """Open an image, fix rotation, shrink it, and return base64 JPEG."""
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python vision/test_expiry.py <overhead_image> <side_image>")
        sys.exit(1)

    load_dotenv()  # reads OPENAI_API_KEY from the .env file
    if not os.getenv("OPENAI_API_KEY"):
        print("No OPENAI_API_KEY found. Put it in a .env file in the fridge_bot folder.")
        sys.exit(1)

    overhead_path, side_path = sys.argv[1], sys.argv[2]
    today = date.today()
    prompt = PROMPT.replace("TODAY", today.isoformat())

    print(f"Sending images to {MODEL}...")
    client = OpenAI()
    try:
        response = client.chat.completions.create(
            model=MODEL,
            response_format={"type": "json_object"},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{encode_image(overhead_path)}"}},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{encode_image(side_path)}"}},
                ],
            }],
        )
    except APIError as e:
        print("OpenAI API error:", e)
        sys.exit(1)

    result = json.loads(response.choices[0].message.content)

    # Do the date math in Python instead of trusting the model with calendars
    days = int(result.get("days_until_expired", 0))
    expires = today + timedelta(days=days)
    result["estimated_expiry_date"] = expires.isoformat()

    print("\n=== RESULT ===")
    print(f"Item:        {result.get('item')}")
    print(f"Condition:   {result.get('condition')}")
    if result.get("spoilage_signs"):
        print(f"Spoilage:    {', '.join(result['spoilage_signs'])}")
    if result.get("printed_expiry_date"):
        print(f"Printed date:{result['printed_expiry_date']:>11}")
    print(f"Expires:     {expires.strftime('%a %b %d, %Y')}  ({days} days)")
    print(f"Confidence:  {result.get('confidence')}")
    print(f"Why:         {result.get('reasoning')}")

    usage = response.usage
    cost = usage.prompt_tokens / 1e6 * PRICE_IN + usage.completion_tokens / 1e6 * PRICE_OUT
    print(f"\nTokens: {usage.prompt_tokens} in / {usage.completion_tokens} out  (~${cost:.4f})")

    print("\nRaw JSON:")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()