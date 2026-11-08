"""When will an item go bad? Plain code, no AI.

Priority, most trustworthy first:
  1. a date printed on the package (read by the vision model),
  2. the vision model's estimate from how the item actually looks,
  3. a typical fridge shelf life for that kind of food (table below).
Anything other than (1) is stored as an *estimate* and labeled that way in
the app — this is food safety, so a guess never masquerades as a printed date.
"""
from __future__ import annotations

from datetime import date, timedelta

from intelligence import clock

MAX_REASONABLE_DAYS = 365

# Typical refrigerated shelf life after purchase/opening, in days (USDA
# FoodKeeper-style ballparks). Matched as keywords against the item name;
# more specific entries first so "cream cheese" doesn't match "cheese".
FRIDGE_DAYS_BY_KEYWORD: list[tuple[str, int]] = [
    # Names that contain a shorter keyword below but keep differently.
    ("eggplant", 7), ("pineapple", 5), ("grapefruit", 21), ("hamburger", 2), ("pepperoni", 21),
    ("buttermilk", 14), ("peanut butter", 90),
    ("cream cheese", 14), ("cottage cheese", 7), ("sour cream", 14), ("heavy cream", 10),
    ("almond milk", 7), ("oat milk", 7),
    ("chicken", 2), ("turkey", 2), ("ground beef", 2), ("ground", 2), ("fish", 2), ("salmon", 2),
    ("shrimp", 2), ("steak", 4), ("pork", 4), ("bacon", 7), ("ham", 5), ("sausage", 3), ("deli", 4),
    ("leftover", 4), ("soup", 4), ("cooked", 4),
    ("milk", 7), ("yogurt", 14), ("butter", 60), ("egg", 28), ("cheese", 21), ("tofu", 5), ("hummus", 7),
    ("juice", 7), ("salsa", 7),
    ("spinach", 5), ("lettuce", 5), ("salad", 4), ("arugula", 4), ("kale", 6), ("cilantro", 6),
    ("parsley", 7), ("basil", 4), ("herb", 5), ("mushroom", 5), ("berr", 4), ("strawberr", 4),
    ("grape", 10), ("broccoli", 5), ("cauliflower", 7), ("pepper", 7), ("cucumber", 7), ("zucchini", 5),
    ("tomato", 5), ("avocado", 4), ("banana", 5), ("carrot", 21), ("celery", 14), ("apple", 30),
    ("lemon", 21), ("lime", 21), ("orange", 21), ("cabbage", 21),
]

FRIDGE_DAYS_BY_CATEGORY: dict[str, int] = {
    "meat": 2, "seafood": 2, "leftovers": 4, "produce": 5, "leafy greens": 5, "vegetables": 5,
    "fruit": 7, "dairy": 10, "drink": 7, "beverages": 7,
}


def estimate_shelf_life_days(name: str | None, category: str | None = None) -> int | None:
    """Typical fridge life for this kind of food, or None if we don't know."""
    lowered = (name or "").lower()
    for keyword, days in FRIDGE_DAYS_BY_KEYWORD:
        if keyword in lowered:
            return days
    if category:
        return FRIDGE_DAYS_BY_CATEGORY.get(category.strip().lower())
    return None


# Freezer quality guidance in months (USDA FoodKeeper ballparks); first keyword match wins.
FREEZER_MONTHS_BY_KEYWORD: list[tuple[str, int]] = [
    ("leftover", 3), ("cooked", 3), ("ground", 4), ("hamburger", 4), ("sausage", 2), ("bacon", 1),
    ("chicken", 9), ("turkey", 9), ("duck", 9), ("beef", 9), ("steak", 9), ("pork", 9), ("lamb", 9),
    ("bread", 3), ("bagel", 3), ("tortilla", 3), ("cheese", 6),
]
FREEZER_MONTHS_BY_CATEGORY: dict[str, int] = {"leftovers": 3, "meat": 9}
DEFAULT_FREEZER_MONTHS = 3
DAYS_PER_MONTH = 30


def freezer_days(name: str | None, category: str | None = None) -> int:
    """How long it keeps well in the freezer, from today."""
    lowered = (name or "").lower()
    months = next((m for keyword, m in FREEZER_MONTHS_BY_KEYWORD if keyword in lowered), None)
    if months is None:
        months = FREEZER_MONTHS_BY_CATEGORY.get((category or "").strip().lower(), DEFAULT_FREEZER_MONTHS)
    return months * DAYS_PER_MONTH


def _valid_days(days: object) -> int | None:
    """The model's estimate, if it's a sane whole number of days."""
    if isinstance(days, bool) or not isinstance(days, (int, float)):
        return None
    days = int(days)
    return days if 0 <= days <= MAX_REASONABLE_DAYS else None


def _valid_date(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def resolve_expiration(
    *,
    printed_date: object = None,
    estimated_days: object = None,
    name: str | None = None,
    category: str | None = None,
    today: date | None = None,
) -> tuple[str | None, bool]:
    """Returns (expiration date as YYYY-MM-DD or None, is_estimate)."""
    printed = _valid_date(printed_date)
    if printed:
        return printed, False
    days = _valid_days(estimated_days)
    if days is None:
        days = estimate_shelf_life_days(name, category)
    if days is None:
        return None, False
    today = today or clock.local_today()
    return (today + timedelta(days=days)).isoformat(), True


def days_until(expiration_date: str, today: date | None = None) -> int:
    today = today or clock.local_today()
    return (date.fromisoformat(expiration_date) - today).days


def describe_expiry(expiration_date: str, estimated: bool, today: date | None = None) -> str:
    """'expired', 'expires today', 'expires tomorrow', 'expires in 4 days' — '(est.)' when estimated."""
    d = days_until(expiration_date, today)
    if d < 0:
        text = "expired"
    elif d == 0:
        text = "expires today"
    elif d == 1:
        text = "expires tomorrow"
    else:
        text = f"expires in {d} days"
    return f"{text} (est.)" if estimated else text
