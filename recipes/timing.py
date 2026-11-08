"""Hands-off time hidden in the steps: marinating, chilling, rising, resting, soaking.

Food.com's minutes are often only the active time, so "17 min" salmon can need a 4-hour marinade.
Read from the steps at load: "marinate at least four hours" -> 240, "refrigerate overnight" -> 480,
"chill 2-3 hours" -> 180 (a range counts as its larger end).
"""
from __future__ import annotations

import re

OVERNIGHT_MIN = 480
MIN_COUNTED = 15  # a 5-minute rest is part of cooking, not waiting

# keyword -> the word the card uses ("17 min + 4 h marinating")
# Adjectives ("marinated chicken", "chilled butter", "refrigerated dough", "the rest of the sauce")
# describe an ingredient, not a wait, so only these forms count.
VERBS = [
    (r"marinate|marinates|marinating|marinade", "marinating"),
    (r"chill|chills|chilling", "chilling"),
    (r"refrigerate|refrigerating|refrigerator|fridge", "chilling"),
    (r"rise|rises|rising|proof|proofing", "rising"),
    (r"(?<!the )rest|rests|resting", "resting"),
    (r"soak|soaks|soaking", "soaking"),
    (r"(?:let|allow|leave)\b[^.]{0,20}?\bset", "setting"),
]
KEYWORD = re.compile("|".join(rf"\b(?:{k})\b" for k, _ in VERBS), re.I)

WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "twenty-four": 24,
    "thirty": 30, "forty": 40, "forty-five": 45, "sixty": 60, "ninety": 90,
    "a couple of": 2, "a couple": 2, "a few": 3, "several": 4,
}
_WORDS = "|".join(sorted((re.escape(w) for w in WORD_NUMBERS), key=len, reverse=True))
NUM = rf"(?:\d+(?:\.\d+)?(?:\s+\d+/\d+)?|\d+/\d+|{_WORDS})"
DURATION = re.compile(
    rf"(?:\bhalf\s+an?\s+hour\b)|\b(?P<lo>{NUM})(?:\s*(?:-+|–|to|or)\s*(?P<hi>{NUM}))?\s*(?P<unit>hours?|hrs?|h|minutes?|mins?)\b",
    re.I,
)
OVERNIGHT = re.compile(r"\bovernight\b", re.I)


def _number(text: str) -> float:
    text = text.strip().lower()
    if text in WORD_NUMBERS:
        return WORD_NUMBERS[text]
    total = 0.0
    for part in text.split():
        num, _, den = part.partition("/")
        total += float(num) / float(den) if den else float(num)
    return total


def _minutes(match: re.Match) -> int:
    if not match.group("unit"):
        return 30  # "half an hour"
    value = max(_number(match.group("lo")), _number(match.group("hi") or "0"))
    return round(value * (60 if match.group("unit").lower().startswith("h") else 1))


def wait_in(sentence: str) -> tuple[int, str] | None:
    """(minutes, verb) for one sentence with a waiting word and a time: the first time after the
    word (or 'overnight'), else the nearest one before it."""
    key = KEYWORD.search(sentence)
    overnight = OVERNIGHT.search(sentence)
    if not key and not overnight:
        return None
    verb = next((v for k, v in VERBS if key and re.fullmatch(k, key.group(0), re.I)), "resting")
    start = key.end() if key else overnight.start()
    after = next(DURATION.finditer(sentence, start), None)
    if overnight and overnight.start() >= start and (after is None or overnight.start() < after.start()):
        return OVERNIGHT_MIN, verb
    if after:
        return _minutes(after), verb
    before = list(DURATION.finditer(sentence, 0, start))
    if key and before:
        return _minutes(before[-1]), verb
    return (OVERNIGHT_MIN, verb) if overnight else None


def inactive_time(steps: list[str]) -> tuple[int, str | None]:
    """Total waiting minutes across the steps, and the verb of the longest wait."""
    waits = [w for step in steps for s in re.split(r"(?<=[.!?;])\s+", step)
             if (w := wait_in(s)) and w[0] >= MIN_COUNTED]
    if not waits:
        return 0, None
    return sum(m for m, _ in waits), max(waits)[1]
