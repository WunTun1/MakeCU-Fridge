"""Fuzzy search over products with plain-language answers. Section 10."""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process

from inventory.database import Database
from intelligence.consumption import days_left, grams_on_hand
from intelligence.expiry import days_until

MATCH_SCORE_THRESHOLD = 60


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


def _plain_language(product_name: str, on_hand_g: float, dl: float | None) -> str:
    if on_hand_g <= 0:
        return f"You're out of {product_name}."
    amount = f"{on_hand_g / 1000:.1f} kg" if on_hand_g >= 1000 else f"{on_hand_g:.0f} g"
    if dl is None:
        return f"You have about {amount} of {product_name}."
    return f"You have about {amount} of {product_name}, roughly {dl:.0f} days left."


def search(db: Database, query: str, limit: int = 5) -> list[SearchResult]:
    with db.cursor() as cur:
        cur.execute("SELECT id, name, category, unit, grams_per_unit FROM products")
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
        dates = [i["expiration_date"] for i in db.active_items()
                 if i["product_id"] == product["id"] and i["expiration_date"] and i["location"] != "freezer"]
        results.append(SearchResult(
            product_id=product["id"],
            product_name=product["name"],
            on_hand_g=on_hand,
            days_left=dl,
            answer=_plain_language(product["name"], on_hand, dl),
            unit=product["unit"],
            grams_per_unit=product["grams_per_unit"],
            expires_in_days=days_until(min(dates)) if dates else None,
        ))
    return results
