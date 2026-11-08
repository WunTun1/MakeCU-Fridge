"""Fuzzy search over products with plain-language answers. Section 10."""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process
from rapidfuzz.utils import default_process

from inventory.database import Database
from intelligence.consumption import days_left, grams_on_hand
from intelligence.fridge_view import fridge_entry
from recipes.ingredients import sentence_words

MATCH_SCORE_THRESHOLD = 60
TYPO_SCORE = 80  # "spinch" still finds Spinach; short words must match exactly
TYPO_MIN_LENGTH = 5


@dataclass
class SearchResult:
    product_id: int
    product_name: str
    on_hand_g: float
    days_left: float | None
    answer: str
    unit: str = "g"
    grams_per_unit: float = 1.0
    expires_in_days: int | None = None   # soonest, freezer left out
    likely_wasted_g: float | None = None


def _plain_language(product_name: str, on_hand_g: float, dl: float | None) -> str:
    if on_hand_g <= 0:
        return f"You're out of {product_name}."
    amount = f"{on_hand_g / 1000:.1f} kg" if on_hand_g >= 1000 else f"{on_hand_g:.0f} g"
    if dl is None:
        return f"You have about {amount} of {product_name}."
    return f"You have about {amount} of {product_name}, roughly {dl:.0f} days left."


def _word_matches(word: str, name_stems: list[str]) -> bool:
    return any(word == n or (len(word) >= TYPO_MIN_LENGTH and fuzz.ratio(word, n) >= TYPO_SCORE) for n in name_stems)


def matches_every_word(query: str, name: str) -> bool:
    """'egg' finds Eggs, 'tomato' Tomatoes; 'soy sauce' needs both words, so it never finds Rice."""
    stems = sentence_words(name).split()
    words = sentence_words(query).split()
    return bool(words) and all(_word_matches(w, stems) for w in words)


def search(db: Database, query: str, limit: int = 5) -> list[SearchResult]:
    with db.cursor() as cur:
        cur.execute("SELECT id, name, category, unit, grams_per_unit FROM products")
        products = [p for p in cur.fetchall() if matches_every_word(query, p["name"])]

    if not products:
        return []

    names = [p["name"] for p in products]
    matches = process.extract(query, names, scorer=fuzz.WRatio, processor=default_process, limit=limit)

    results: list[SearchResult] = []
    for name, score, idx in matches:
        if score < MATCH_SCORE_THRESHOLD:
            continue
        product = products[idx]
        on_hand = grams_on_hand(db, product["id"])
        dl = days_left(db, product["id"])
        entry = fridge_entry(db, product["id"])
        outside_freezer = entry if entry and entry["location"] != "freezer" else None
        results.append(SearchResult(
            product_id=product["id"],
            product_name=product["name"],
            on_hand_g=on_hand,
            days_left=dl,
            answer=_plain_language(product["name"], on_hand, dl),
            unit=product["unit"],
            grams_per_unit=product["grams_per_unit"],
            expires_in_days=outside_freezer and outside_freezer["expires_in_days"],
            likely_wasted_g=outside_freezer and outside_freezer["likely_wasted_g"],
        ))
    return results
