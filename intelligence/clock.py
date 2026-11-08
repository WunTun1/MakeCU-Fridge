"""The household's one clock. Every day count ("tomorrow", "in 2 days", alert windows, trip
dates, today's meals) is reckoned in the household's time zone, never the UTC date.

REFRIDGE_TZ names the zone (e.g. America/New_York); unset, it's this machine's local zone.
Stored timestamps stay UTC.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def local_tz() -> tzinfo:
    name = os.getenv("REFRIDGE_TZ", "").strip()
    if name:
        return ZoneInfo(name)
    return utc_now().astimezone().tzinfo or timezone.utc


def local_now() -> datetime:
    return utc_now().astimezone(local_tz())


def local_today() -> date:
    return local_now().date()


def local_date(timestamp: str) -> date:
    """The household's calendar day of a stored (UTC) timestamp."""
    moment = datetime.fromisoformat(timestamp)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(local_tz()).date()


def start_of_local_day() -> datetime:
    """Midnight today in the household's zone, as a UTC moment (for comparing stored timestamps)."""
    now = local_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def date_in(days: int) -> date:
    return local_today() + timedelta(days=days)
