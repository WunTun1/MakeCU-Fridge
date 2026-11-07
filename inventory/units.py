"""How people count a product: grams, pieces, or millilitres.

Stock is always stored in grams; a product's unit and grams_per_unit only
change how amounts are entered and shown ("12 eggs", "1 L").
"""
from __future__ import annotations

import re

UNITS = ("g", "count", "ml")

COUNT_WORDS = ("egg", "lemon", "lime", "apple", "avocado", "onion", "pepper", "tomato")
ML_WORDS = ("milk", "juice", "oil", "cream", "broth", "soda")
# "Sour cream" and "peppercorn" don't pour or get counted.
NOT_A_UNIT_WORDS = ("sour cream", "cream cheese", "ice cream", "peppercorn", "eggplant", "pepper flake")

GRAMS_PER_PIECE = {"egg": 50.0, "lemon": 100.0, "apple": 180.0, "onion": 150.0}
DEFAULT_PIECE_G = 100.0
ML_G = 1.0


def _words(name: str) -> str:
    return " " + re.sub(r"[^a-z ]", " ", name.lower()) + " "


def _has_word(text: str, stem: str) -> bool:
    """'eggs' and 'egg' match 'egg'; 'eggplant' doesn't."""
    return re.search(rf"\b{stem}(e?s)?\b", text) is not None


def guess_unit(name: str | None) -> str:
    text = _words(name or "")
    if any(w in text for w in NOT_A_UNIT_WORDS):
        return "g"
    if any(_has_word(text, w) for w in COUNT_WORDS):
        return "count"
    if any(_has_word(text, w) for w in ML_WORDS):
        return "ml"
    return "g"


def default_grams_per_unit(name: str | None, unit: str) -> float:
    if unit == "ml":
        return ML_G
    if unit == "count":
        text = _words(name or "")
        return next((g for w, g in GRAMS_PER_PIECE.items() if _has_word(text, w)), DEFAULT_PIECE_G)
    return 1.0


def to_grams(quantity: float, unit: str, grams_per_unit: float) -> float:
    return quantity if unit == "g" else quantity * grams_per_unit


def _count_noun(name: str | None, n: int) -> str:
    words = re.findall(r"[a-z]+", (name or "").lower())
    word = words[-1] if words else "piece"
    if word.endswith("ies"):
        word = word[:-3] + "y"
    elif word.endswith("oes"):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if n == 1:
        return word
    if word in ("tomato", "potato", "mango"):
        return word + "es"
    return word[:-1] + "ies" if re.search(r"[^aeiou]y$", word) else word + "s"


def format_amount(grams: float, unit: str = "g", grams_per_unit: float = 1.0, name: str | None = None) -> str:
    """Same wording as the app (mobile/src/lib/amount.ts): '6 eggs', 'about 1 egg', '1 L', '150 g'."""
    if unit == "count":
        exact = grams / (grams_per_unit or 1)
        n = round(exact)
        if n < 1:
            return f"less than 1 {_count_noun(name, 1)}"
        about = "about " if abs(exact - n) > 0.15 else ""
        return f"{about}{n} {_count_noun(name, n)}"
    amount = grams / (grams_per_unit or 1) if unit == "ml" else grams
    small, big = ("ml", "L") if unit == "ml" else ("g", "kg")
    if amount >= 1000:
        return f"{round(amount / 1000, 1):g} {big}"
    rounded = round(amount / 10) * 10 if unit == "ml" and amount >= 100 else round(amount)
    return f"{rounded} {small}"
