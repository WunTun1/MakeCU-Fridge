"""Tiger Data (TimescaleDB on Tiger Cloud): the fridge's history as time series, and the
analytics that run on it.

The fridge keeps working on its local SQLite database; this mirrors it to Tiger Cloud
(TIGER_DATABASE_URL in .env) every SYNC_EVERY_S seconds:

    fridge_events      hypertable: every add / use / removal / return, with grams
    fridge_conditions  hypertable: every temperature, pressure, humidity, light reading
    fridge_inventory   what's on hand right now (amount, unit, days until it goes bad)
    daily_food_use     continuous aggregate: grams of each food used per day (real time)

and answers two questions in SQL there:

    restock()   how fast you go through each food (recency-weighted daily use over two
                weeks, gap-filled so quiet days count), the week-over-week trend, when it
                runs out, and when to buy how much
    pressure()  which foods you'll likely throw away — what you have, minus what you'd
                use before it goes bad — weighted by how soon: what to cook first

Rows are tagged with a household (TIGER_HOUSEHOLD, else the local database's name), so a
demo database and the real fridge never mix. Without TIGER_DATABASE_URL, or when Tiger
can't be reached, callers compute the same numbers locally (see api/server.py).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from intelligence import clock
from inventory.database import Database

log = logging.getLogger("refridge.tiger")

SYNC_EVERY_S = 30
WINDOW_DAYS = 14          # how far back the daily-use analysis looks
HALF_LIFE_DAYS = 7.0      # recent days count more (same half-life as intelligence/consumption.py)
RECONCILE_DAYS = 30       # local undos in this window are mirrored as deletions
USAGE_TYPES = ["consume", "remove", "return"]   # return cancels a removal (grams_delta > 0)

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS fridge_events (
        time         timestamptz NOT NULL,
        household    text        NOT NULL,
        event_id     bigint      NOT NULL,
        event_type   text        NOT NULL,
        product_id   integer,
        product_name text,
        grams_delta  double precision NOT NULL DEFAULT 0,
        shelf        integer,
        UNIQUE (household, event_id, time)
    )""",
    "SELECT create_hypertable('fridge_events', by_range('time'), if_not_exists => TRUE)",
    """CREATE TABLE IF NOT EXISTS fridge_conditions (
        time          timestamptz NOT NULL,
        household     text        NOT NULL,
        temperature_c double precision,
        pressure_hpa  double precision,
        humidity_pct  double precision,
        light_raw     double precision,
        UNIQUE (household, time)
    )""",
    "SELECT create_hypertable('fridge_conditions', by_range('time'), if_not_exists => TRUE)",
    """CREATE TABLE IF NOT EXISTS fridge_inventory (
        household       text    NOT NULL,
        product_id      integer NOT NULL,
        location        text    NOT NULL,
        name            text    NOT NULL,
        grams           double precision NOT NULL,
        unit            text,
        grams_per_unit  double precision,
        package_g       double precision,
        expires_in_days double precision,
        updated_at      timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (household, product_id, location)
    )""",
    # Grams of each food used per day, kept up to date by TimescaleDB (and real-time for today).
    f"""CREATE MATERIALIZED VIEW IF NOT EXISTS daily_food_use
        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
        SELECT time_bucket('1 day', time, '{clock.DEFAULT_TZ}') AS day, household, product_id,
               sum(-grams_delta) AS grams_used
        FROM fridge_events
        WHERE event_type IN ('consume', 'remove', 'return')
        GROUP BY day, household, product_id
        WITH NO DATA""",
    """SELECT add_continuous_aggregate_policy('daily_food_use',
        start_offset => INTERVAL '60 days', end_offset => INTERVAL '1 hour',
        schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE)""",
]

status: dict = {"enabled": False, "connected": False, "last_sync": None, "error": None, "events": 0}

_lock = threading.RLock()
_conn = None
_schema_ready = False


def url() -> str:
    return os.getenv("TIGER_DATABASE_URL", "").strip()


def enabled() -> bool:
    return bool(url())


def household() -> str:
    return os.getenv("TIGER_HOUSEHOLD", "").strip() or Path(os.getenv("DATABASE_PATH", "refridge.db")).stem


def _tz() -> str:
    return os.getenv("REFRIDGE_TZ", "").strip() or clock.DEFAULT_TZ


def _connection():
    global _conn
    import psycopg

    if _conn is None or _conn.closed:
        _conn = psycopg.connect(url(), autocommit=True, connect_timeout=10)
    return _conn


def query(sql: str, params: dict | tuple | None = None) -> list[tuple]:
    """Run SQL on Tiger; rows for a SELECT, [] otherwise. Reconnects once if the link dropped."""
    import psycopg

    with _lock:
        for attempt in (1, 2):
            try:
                cur = _connection().execute(sql, params)
                return cur.fetchall() if cur.description else []
            except psycopg.OperationalError:
                global _conn
                _conn = None
                if attempt == 2:
                    raise
    return []


def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    for statement in SCHEMA:
        query(statement)
    _schema_ready = True


# ------------------------------------------------------------------- sync
def _ts(iso: str) -> datetime:
    t = datetime.fromisoformat(iso)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def sync(db: Database) -> dict:
    """Mirror new events and readings, local undos, and the current inventory to Tiger."""
    from intelligence.fridge_view import inventory_entries

    ensure_schema()
    h = household()
    with _lock, db.cursor() as cur:
        last_id = query("SELECT coalesce(max(event_id), 0) FROM fridge_events WHERE household = %s", (h,))[0][0]
        names = {r["id"]: r["name"] for r in cur.execute("SELECT id, name FROM products").fetchall()}
        events = cur.execute(
            "SELECT * FROM events WHERE id > ? AND event_type != 'needs_review' ORDER BY id", (last_id,)
        ).fetchall()
        last_time = query("SELECT max(time) FROM fridge_conditions WHERE household = %s", (h,))[0][0]
        since = last_time.isoformat() if last_time else "0000"
        readings = cur.execute(
            "SELECT * FROM fridge_conditions WHERE occurred_at > ? ORDER BY occurred_at", (since,)
        ).fetchall()
        window = (clock.utc_now().timestamp() - RECONCILE_DAYS * 86400)
        recent_local = {r["id"] for r in cur.execute(
            "SELECT id FROM events WHERE occurred_at >= ?",
            (datetime.fromtimestamp(window, timezone.utc).isoformat(),),
        ).fetchall()}

    with _lock:
        conn = _connection()
        with conn.cursor() as c:
            if events:
                c.executemany(
                    """INSERT INTO fridge_events (time, household, event_id, event_type, product_id, product_name,
                                                  grams_delta, shelf)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    [(_ts(e["occurred_at"]), h, e["id"], e["event_type"], e["product_id"],
                      names.get(e["product_id"]), e["grams_delta"], e["shelf"]) for e in events],
                )
            if readings:
                c.executemany(
                    """INSERT INTO fridge_conditions (time, household, temperature_c, pressure_hpa, humidity_pct, light_raw)
                       VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    [(_ts(r["occurred_at"]), h, r["temperature_c"], r["pressure_hpa"], r["humidity_pct"],
                      r["light_raw"]) for r in readings],
                )
            # An undo deletes the local event: drop it here too, so the history matches.
            mirrored = [r[0] for r in c.execute(
                "SELECT event_id FROM fridge_events WHERE household = %s AND time >= to_timestamp(%s)",
                (h, window)).fetchall()]
            gone = [i for i in mirrored if i not in recent_local]
            if gone:
                c.execute("DELETE FROM fridge_events WHERE household = %s AND event_id = ANY(%s)", (h, gone))
            # What's on hand now: replaced whole, it's small.
            c.execute("DELETE FROM fridge_inventory WHERE household = %s", (h,))
            entries = inventory_entries(db)
            if entries:
                c.executemany(
                    """INSERT INTO fridge_inventory (household, product_id, location, name, grams, unit, grams_per_unit,
                                                     package_g, expires_in_days)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    [(h, e["product_id"], e["location"], e["name"], e["grams"], e["unit"], e["grams_per_unit"],
                      e["package_size_g"], e["expires_in_days"]) for e in entries],
                )
    status.update(connected=True, last_sync=clock.utc_now().isoformat(), error=None,
                  events=status["events"] + len(events))
    return {"events": len(events), "readings": len(readings), "removed": len(gone), "inventory": len(entries)}


def start_background_sync(db: Database) -> None:
    """Keep Tiger in step with the local database, every SYNC_EVERY_S seconds."""
    status["enabled"] = enabled()
    if not enabled():
        log.info("Tiger Data off (no TIGER_DATABASE_URL): analytics run on the local database")
        return

    def loop() -> None:
        while True:
            try:
                result = sync(db)
                if result["events"] or result["removed"]:
                    log.info("Tiger Data sync: %s", result)
            except Exception as e:  # network, credentials, ...: the app keeps working locally
                status.update(connected=False, error=str(e)[:200])
                log.warning("Tiger Data sync failed (%s); using the local database meanwhile", e)
            time.sleep(SYNC_EVERY_S)

    threading.Thread(target=loop, name="tiger-sync", daemon=True).start()


# --------------------------------------------------------------- analytics
# Each food's daily use over the window, every day present (time_bucket_gapfill), and a
# recency-weighted average of it: the "how fast do I go through this" number.
_RATES = """
    WITH days AS (
        SELECT time_bucket_gapfill('1 day', time, %(tz)s, now() - %(window)s * INTERVAL '1 day', now()) AS day,
               product_id,
               sum(-grams_delta) AS used
        FROM fridge_events
        WHERE household = %(h)s AND event_type = ANY(%(types)s)
          AND time > now() - %(window)s * INTERVAL '1 day' AND time <= now()
        GROUP BY day, product_id
    ), weighted AS (
        SELECT product_id,
               coalesce(used, 0) AS used,
               day,
               exp(-ln(2) / %(half_life)s * extract(epoch FROM (now() - day)) / 86400) AS w
        FROM days
    )
    SELECT product_id,
           sum(used * w) / nullif(sum(w), 0)                          AS rate_g_per_day,
           sum(used) FILTER (WHERE day > now() - INTERVAL '7 days')    AS last7,
           sum(used) FILTER (WHERE day <= now() - INTERVAL '7 days')   AS prev7,
           array_agg(round(used::numeric, 1) ORDER BY day)             AS series
    FROM weighted
    GROUP BY product_id
"""


def _params(**extra) -> dict:
    return {"h": household(), "tz": _tz(), "window": WINDOW_DAYS, "half_life": HALF_LIFE_DAYS,
            "types": USAGE_TYPES, **extra}


def restock() -> list[dict]:
    """Per food you use: on hand, daily rate, 7-day vs prior 7-day use, last WINDOW_DAYS days of use."""
    rows = query(f"""
        WITH rates AS ({_RATES}),
        stock AS (
            SELECT product_id, min(name) AS name, sum(grams) AS grams, min(unit) AS unit,
                   min(grams_per_unit) AS grams_per_unit, min(package_g) AS package_g
            FROM fridge_inventory WHERE household = %(h)s AND location <> 'freezer'
            GROUP BY product_id
        )
        SELECT s.product_id, s.name, s.grams, s.unit, s.grams_per_unit, s.package_g,
               r.rate_g_per_day, r.last7, r.prev7, r.series
        FROM stock s JOIN rates r USING (product_id)
        WHERE r.rate_g_per_day > 0
        ORDER BY s.grams / r.rate_g_per_day
    """, _params())
    keys = ("product_id", "name", "grams", "unit", "grams_per_unit", "package_g", "rate", "last7", "prev7", "series")
    return [{k: (float(v) if isinstance(v, (int, float)) and k not in ("product_id",) else v)
             for k, v in zip(keys, r)} for r in rows]


def pressure(limit: int = 6) -> list[dict]:
    """Foods you'll likely throw away, most pressing first: grams at risk (what's left after your usual
    use until it goes bad; all of it with no history) divided by days left plus one."""
    rows = query(f"""
        WITH rates AS ({_RATES}),
        stock AS (
            SELECT product_id, min(name) AS name, sum(grams) AS grams, min(expires_in_days) AS days
            FROM fridge_inventory
            WHERE household = %(h)s AND location <> 'freezer' AND expires_in_days IS NOT NULL
            GROUP BY product_id
        )
        SELECT s.product_id, s.name, s.grams, s.days,
               greatest(s.grams - coalesce(r.rate_g_per_day, 0) * greatest(s.days, 0), 0) AS at_risk_g
        FROM stock s LEFT JOIN rates r USING (product_id)
        WHERE s.days <= 7
        ORDER BY greatest(s.grams - coalesce(r.rate_g_per_day, 0) * greatest(s.days, 0), 0)
                 / (1 + greatest(s.days, 0)) DESC
        LIMIT %(limit)s
    """, _params(limit=limit))
    return [{"product_id": r[0], "name": r[1], "grams": float(r[2]), "expires_in_days": float(r[3]),
             "at_risk_g": float(r[4]), "score": float(r[4]) / (1 + max(float(r[3]), 0))}
            for r in rows if r[4] and r[4] > 0]
