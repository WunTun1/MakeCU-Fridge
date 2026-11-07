"""Fuzzy search over products with plain-language answers. Section 10."""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process

from inventory.database import Database
from intelligence.consumption import days_left, grams_on_hand

MATCH_SCORE_THRESHOLD = 60


@dataclass
class SearchResult:
    product_id: int
    product_name: str
    on_hand_g: float
    days_left: float | None
    answer: str


def _plain_language(product_name: str, on_hand_g: float, dl: float | None) -> str:
    if on_hand_g <= 0:
        return f"You're out of {product_name}."
    amount = f"{on_hand_g / 1000:.1f} kg" if on_hand_g >= 1000 else f"{on_hand_g:.0f} g"
    if dl is None:
        return f"You have about {amount} of {product_name}."
    return f"You have about {amount} of {product_name}, roughly {dl:.0f} days left."


def search(db: Database, query: str, limit: int = 5) -> list[SearchResult]:
    with db.cursor() as cur:
        cur.execute("SELECT id, name, category FROM products")
        products = cur.fetchall()

    if not products:
        return []

    names = [p["name"] for p in products]
    matches = process.extract(query, names, scorer=fuzz.WRatio, limit=limit)

    results: list[SearchResult] = []
    for name, score, idx in matches:
        if score < MATCH_SCORE_THRESHOLD:
            continue
        product = products[idx]
        on_hand = grams_on_hand(db, product["id"])
        dl = days_left(db, product["id"])
        results.append(SearchResult(
            product_id=product["id"],
            product_name=product["name"],
            on_hand_g=on_hand,
            days_left=dl,
            answer=_plain_language(product["name"], on_hand, dl),
        ))
    return results
