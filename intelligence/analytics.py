"""The data analysis behind Home's "Best to cook now" and Grocery's "Your eating".

Both run on Tiger Data when it's connected (intelligence/tiger.py: SQL over the fridge's
event history) and fall back to the same math on the local database when it isn't, so
the app never breaks. Every answer says which it used ("source": "tiger" | "local").
"""
from __future__ import annotations

import logging
import math
from datetime import timedelta

from intelligence import clock, tiger
from intelligence.consumption import daily_usage, usage_rate_g_per_day
from intelligence.fridge_view import day_word, inventory_entries
from inventory.database import Database
from inventory.units import format_amount

log = logging.getLogger("refridge.analytics")

WINDOW_DAYS = tiger.WINDOW_DAYS
SUPPLY_DAYS = 7          # a restock buys about a week of what you use
PRESSURE_DAYS = 7        # only food going bad within a week counts as "cook it first"


# ----------------------------------------------------------------- restock
def _local_rates(db: Database) -> list[dict]:
    """The Tiger query's numbers, from the local database."""
    today = clock.local_today()
    by_product: dict[int, dict] = {}
    for e in inventory_entries(db):
        if e["location"] == "freezer" or e["leftovers"]:
            continue
        row = by_product.setdefault(e["product_id"], {
            "product_id": e["product_id"], "name": e["name"], "grams": 0.0, "unit": e["unit"],
            "grams_per_unit": e["grams_per_unit"], "package_g": e["package_size_g"]})
        row["grams"] += e["grams"]
    out = []
    for row in by_product.values():
        rate = usage_rate_g_per_day(db, row["product_id"], lookback_days=WINDOW_DAYS)
        if rate <= 0:
            continue
        used = daily_usage(db, row["product_id"], days=WINDOW_DAYS)
        series = [used.get((today - timedelta(days=d)).isoformat(), 0.0) for d in range(WINDOW_DAYS, -1, -1)]
        out.append({**row, "rate": rate, "last7": sum(series[-7:]), "prev7": sum(series[:-7]), "series": series})
    return sorted(out, key=lambda r: r["grams"] / r["rate"])


def _buy(rate: float, unit: str, grams_per_unit: float, package_g: float | None) -> float:
    """About a week of it, rounded up to whole packages (or whole eggs, or 50 g)."""
    want = rate * SUPPLY_DAYS
    if package_g:
        return math.ceil(want / package_g) * package_g
    if unit == "count" and grams_per_unit:
        return math.ceil(want / grams_per_unit) * grams_per_unit
    return max(math.ceil(want / 50) * 50, 50)


def restock(db: Database) -> dict:
    """How fast you go through each food, and when to buy how much: soonest to run out first."""
    source = "local"
    rows = None
    if tiger.enabled():
        try:
            rows = tiger.restock()
            source = "tiger"
        except Exception as e:
            log.warning("Tiger Data restock query failed (%s); using the local database", e)
    if rows is None:
        rows = _local_rates(db)

    today = clock.local_today()
    items = []
    for r in rows:
        rate = float(r["rate"])
        runs_out = r["grams"] / rate if rate > 0 else None
        buy_in = max(math.floor(runs_out) - 1, 0) if runs_out is not None else None   # a day before it runs out
        buy_g = _buy(rate, r["unit"] or "g", r["grams_per_unit"] or 1.0, r["package_g"])
        prev7, last7 = float(r["prev7"] or 0), float(r["last7"] or 0)
        items.append({
            "product_id": r["product_id"],
            "name": r["name"],
            "on_hand_g": round(r["grams"], 1),
            "unit": r["unit"] or "g",
            "grams_per_unit": r["grams_per_unit"] or 1.0,
            "rate_g_per_day": round(rate, 1),
            "runs_out_in_days": round(runs_out, 1) if runs_out is not None else None,
            "restock_in_days": buy_in,
            "restock_on": (today + timedelta(days=buy_in)).isoformat() if buy_in is not None else None,
            "restock_g": round(buy_g, 1),
            "trend_pct": round((last7 - prev7) / prev7 * 100) if prev7 > 0 else None,
            "series": [round(float(v), 1) for v in r["series"]],
        })
    return {"source": source, "window_days": WINDOW_DAYS, "items": items}


# ------------------------------------------------------------- best recipe
def _local_pressure(db: Database) -> list[dict]:
    out = []
    for e in inventory_entries(db):
        d = e["expires_in_days"]
        if e["location"] == "freezer" or d is None or d > PRESSURE_DAYS:
            continue
        # What you'll likely throw away; with no usage history, all of it.
        at_risk = e["likely_wasted_g"] if e["days_left"] is not None else e["grams"]
        if at_risk and at_risk > 0:
            out.append({"product_id": e["product_id"], "name": e["name"], "grams": e["grams"],
                        "expires_in_days": d, "at_risk_g": at_risk, "score": at_risk / (1 + max(d, 0))})
    return sorted(out, key=lambda f: f["score"], reverse=True)[:6]


def at_risk_foods(db: Database) -> tuple[list[dict], str]:
    if tiger.enabled():
        try:
            return tiger.pressure(), "tiger"
        except Exception as e:
            log.warning("Tiger Data pressure query failed (%s); using the local database", e)
    return _local_pressure(db), "local"


def _same_food(product: str, ingredient: str) -> bool:
    from recipes.ingredients import canonical

    a, b = canonical(product) or product.lower(), canonical(ingredient) or ingredient.lower()
    if a == b:
        return True
    ta, tb = set(a.split()), set(b.split())
    return bool(ta and tb) and (ta <= tb or tb <= ta)


def best_recipe(db: Database, engine, high_protein: bool = False) -> dict:
    """The recipe that saves the most food you'd otherwise throw away, soonest first, among those you
    can mostly make. "why" says which foods, how much, and by when, in words."""
    from recipes.engine import card

    foods, source = at_risk_foods(db)
    if not foods:
        return {"source": source, "recipe": None, "why": [], "foods": []}
    query = " ".join(f["name"] for f in foods[:3])
    matches = engine.suggest(query=query, limit=20, high_protein=high_protein)
    if not matches:
        matches = engine.suggest(limit=20, high_protein=high_protein)

    def saves(m) -> list[dict]:
        names = list(m.have) + [s.use for s in m.swaps]
        return [f for f in foods if any(_same_food(f["name"], n) for n in names)]

    def score(m) -> float:
        needed = max(len(m.have) + len(m.swaps) + len(m.short) + len(m.missing), 1)
        coverage = (len(m.have) + len(m.swaps)) / needed
        return sum(f["score"] for f in saves(m)) * (0.5 + coverage)

    best = max(matches, key=score)
    units = {e["product_id"]: e for e in inventory_entries(db)}
    why = []
    for f in sorted(saves(best), key=lambda f: f["score"], reverse=True):
        e = units.get(f["product_id"])
        amount = format_amount(f["at_risk_g"], e["unit"], e["grams_per_unit"], f["name"]) if e else f"{f['at_risk_g']:.0f} g"
        why.append(f"Uses your {f['name'].lower()}: {amount} would go bad {day_word(int(f['expires_in_days']))}")
    return {"source": source, "recipe": card(best), "why": why, "foods": foods}


# -------------------------------------------------------------- stock score
STOCK_DAYS = 30           # the history chart, and the window your "usual" comes from
BALANCED = 0.25           # |score| up to this is balanced (green)
WASTE_WEIGHT = 0.5        # how hard food you can't finish in time pushes toward "overstocked"


def _local_stock_history(db: Database, days: int) -> list[dict]:
    """tiger.stock_history(), from the local database: each food's level rebuilt from its events."""
    import statistics

    today = clock.local_today()
    day_list = [today - timedelta(days=d) for d in range(days - 1, -1, -1)]
    rows = []
    with db.cursor() as cur:
        product_ids = [r[0] for r in cur.execute("SELECT DISTINCT product_id FROM events WHERE product_id IS NOT NULL")]
    for pid in product_ids:
        rate = usage_rate_g_per_day(db, pid, lookback_days=WINDOW_DAYS)
        if rate <= 0:
            continue
        events = db.events_for_product(pid)
        if not events:
            continue
        first = clock.local_date(events[0]["occurred_at"])  # before that it's unknown, not empty
        level, i, per_day = 0.0, 0, []
        known = [d for d in day_list if d >= first]
        for day in known:
            while i < len(events) and clock.local_date(events[i]["occurred_at"]) <= day:
                level += events[i]["grams_delta"]
                i += 1
            per_day.append(max(level, 0.0) / rate)
        if not per_day:
            continue
        usual = statistics.median(per_day)
        for day, supply in zip(known, per_day):
            score = max(min(math.log2((supply + 0.25) / (usual + 0.25)), 2), -2) / 2
            rows.append({"day": day.isoformat(), "product_id": pid, "rate": rate,
                         "days_of_supply": supply, "usual_days": usual, "score": score})
    return rows


def stock_score(db: Database, days: int = STOCK_DAYS) -> dict:
    """One number for how stocked you are against your own normal: -100 understocked, 0 balanced,
    +100 overstocked. Today's also leans toward overstocked by the food you likely can't finish
    before it goes bad. With the history (for the chart) and the foods pulling it each way."""
    source, rows = "local", None
    if tiger.enabled():
        try:
            rows, source = tiger.stock_history(days), "tiger"
        except Exception as e:
            log.warning("Tiger Data stock query failed (%s); using the local database", e)
    if rows is None:
        rows = _local_stock_history(db, days)

    by_day: dict[str, list[dict]] = {}
    for r in rows:
        by_day.setdefault(r["day"], []).append(r)
    history = [{"day": d, "score": round(100 * sum(x["rate"] * x["score"] for x in rs) / sum(x["rate"] for x in rs))}
               for d, rs in sorted(by_day.items()) if sum(x["rate"] for x in rs) > 0]

    entries = [e for e in inventory_entries(db) if e["location"] != "freezer"]
    names = {e["product_id"]: e["name"] for e in entries}
    on_hand = sum(e["grams"] for e in entries)
    foods, _ = at_risk_foods(db)
    waste_share = min(sum(f["at_risk_g"] for f in foods) / on_hand, 1.0) if on_hand > 0 else 0.0

    today_rows = by_day.get(max(by_day), []) if by_day else []
    base = history[-1]["score"] / 100 if history else 0.0
    score = round(100 * max(min(base + WASTE_WEIGHT * waste_share, 1), -1))
    band = "under" if score <= -100 * BALANCED else "over" if score >= 100 * BALANCED else "balanced"
    if history:
        history[-1]["score"] = score  # today's point is today's dial

    def food(r: dict) -> dict:
        return {"product_id": r["product_id"], "name": names.get(r["product_id"]) or _product_name(db, r["product_id"]),
                "days_of_supply": round(r["days_of_supply"], 1), "usual_days": round(r["usual_days"], 1)}

    low = [food(r) for r in sorted(today_rows, key=lambda r: r["score"]) if r["score"] <= -0.5 or r["days_of_supply"] < 1]
    high = [food(r) for r in sorted(today_rows, key=lambda r: -r["score"]) if r["score"] >= 0.5]
    return {
        "source": source,
        "score": score,
        "band": band,
        "waste_share": round(waste_share, 2),
        "history": history,
        "low": low[:5],
        "high": high[:5],
        "at_risk": [{"name": f["name"], "at_risk_g": round(f["at_risk_g"]), "expires_in_days": f["expires_in_days"]}
                    for f in foods[:5]],
    }


def _product_name(db: Database, product_id: int) -> str:
    p = db.get_product(product_id)
    return p["name"] if p else "?"
