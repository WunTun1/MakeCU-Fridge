"""Food.com titles and steps as people typed them, tidied for the screen.

"Mr. Foods Banana Bread BEST BANANa BREAD EVER!!!!!!" -> "Mr. Foods Banana Bread";
"Alli's Crunchy Ranch Chicken #RSC" -> "Alli's Crunchy Ranch Chicken". The raw title stays
in the search index, so cleaning never changes what a search finds.
"""
from __future__ import annotations

import re

ACRONYM_MAX = 3  # "BBQ", "BLT" stay as they are; "BREAD" is shouting
STEP_FRAGMENT_WORDS = 4
WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*")
TIME_STEP = re.compile(r"^\s*(cooking|prep|preparation)\s+time\b", re.I)


def _is_shouting(token: str) -> bool:
    return token.isupper() and len(token) > ACRONYM_MAX


def _fix_case(token: str, shouting: bool) -> str:
    """'BANANa' -> 'Banana' always; 'BREAD' -> 'Bread' when the title shouts (two or more long
    all-caps words), so a lone acronym like 'OAMC' or 'BBQ' stays. 'bread', 'Bread', "McDonald's" stay."""
    letters = token.replace("'", "")
    if letters.islower() or (letters[0].isupper() and letters[1:].islower()):
        return token
    if re.fullmatch(r"[A-Z]{2,%d}s?" % ACRONYM_MAX, letters):  # "BLT's"
        return token
    if letters.isupper() and not (shouting and len(letters) > ACRONYM_MAX):
        return token
    if re.fullmatch(r"(Mc|Mac|O)[A-Z][a-z]+(s)?", letters):
        return token
    return token[:1].upper() + token[1:].lower()


TAIL_FILLER = {"ever", "recipe"}
CONNECTIVES = {"with", "w", "for", "and", "or", "of", "to", "in", "without", "from", "like"}


def _drop_repeated_tail(words: list[str]) -> list[str]:
    """A title that names its dish twice in a row keeps the first name: '... Banana Bread Best Banana
    Bread Ever' -> '... Banana Bread', 'We Hate Zucchini Bread Zucchini Bread' -> 'We Hate Zucchini
    Bread'. The repeat must be a two-word name or longer that ends the title (or is followed only by
    'Ever'), with no 'with', 'for', 'or' in between, so 'Peanut Butter Cake With Peanut Butter
    Frosting' and 'Avgolemono Soup Chicken Soup' are left alone."""
    plain = [re.sub(r"[^a-z]", "", w.lower()) for w in words]
    n = len(words)
    for i in range(1, n - 1):
        for j in range(i + 2, n):
            if plain[j - 1] != plain[i - 1] or plain[j] != plain[i] or j - 1 <= i or not plain[i - 1]                     or plain[i - 1] in CONNECTIVES:
                continue
            end_i, end_j = i, j
            while end_j + 1 < n and plain[end_i + 1] == plain[end_j + 1] and end_i + 1 < j - 1:
                end_i, end_j = end_i + 1, end_j + 1
            tail = plain[end_j + 1:]
            between = set(plain[end_i + 1: j - 1])
            if (not tail or set(tail) <= TAIL_FILLER) and not between & CONNECTIVES and len(plain[end_i]) >= 3:
                return words[: end_i + 1]
    return words


def clean_title(raw: str) -> str:
    title = re.sub(r"#\w+", " ", raw).replace("#", " ")
    title = re.sub(r"\(\s*variation[^)]*\)?", " ", title, flags=re.I)
    if title.count("(") > title.count(")"):  # "Spinach Pie (Makaronia Me" -> "Spinach Pie"
        title = title[: title.rfind("(")]
    title = re.sub(r"([!?])[!?]+", r"\1", title)
    shouting = sum(_is_shouting(t) for t in WORD.findall(title)) >= 2
    title = WORD.sub(lambda m: _fix_case(m.group(0), shouting), title)
    head, paren, aside = title.partition("(")  # asides in parentheses aren't counted as repeats
    title = " ".join(_drop_repeated_tail(head.split())) + (f" {paren}{aside}" if paren else "")
    title = re.sub(r"\s+", " ", title)
    title = re.sub(r"[\s!?:;,.\-–]+$", "", title).strip()
    return title or raw.strip()


# Blog talk, not instructions: first person, and asides about timing guesses and variations.
FIRST_PERSON = re.compile(r"(?<![\w'’])i(?:['’](?:m|ve|d))?(?![\w'’])|\b(?:my|me)\b", re.I)
CHATTER_START = re.compile(r"^\W*(these times|alternatively|a tasty variation)\b", re.I)
CHATTER_ANYWHERE = re.compile(r"\bcould be added\b", re.I)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _instruction(sentence: str) -> bool:
    return not (FIRST_PERSON.search(sentence) or CHATTER_START.search(sentence) or CHATTER_ANYWHERE.search(sentence))


def clean_steps(steps: list[str]) -> list[str]:
    """Keep the source's steps, minus headings scraped as steps ('Cooking time: 40 min', 'For the
    sauce:') and blog sentences ('I've messed it up...', 'These times are only a guide'). A step
    with nothing left is dropped."""
    out = []
    for step in steps:
        if TIME_STEP.match(step) or (len(step.split()) < STEP_FRAGMENT_WORDS and step.strip().endswith(":")):
            continue
        kept = " ".join(s for s in SENTENCE_END.split(step.strip()) if s and _instruction(s))
        if kept:
            out.append(kept)
    return out
