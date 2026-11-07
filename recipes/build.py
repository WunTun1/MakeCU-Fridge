"""Build the local recipe library (data/recipes.db).

  python -m recipes.build                 # full Food.com library (~230k recipes; downloads ~900 MB once)
  python -m recipes.build --sample-only   # just the bundled starter set (instant, no download)
  python -m recipes.build --write-sample  # maintainers: refresh the bundled starter set from the full build

Sources (Food.com recipes mirrored on Hugging Face):
  RAW_recipes.csv     name, minutes, tags (incl. cuisine), steps, ingredient names, calories
  parsed_recipes.csv  same recipes with nutrition in grams per serving, servings, ingredient
                      quantities, photos — but its "steps" column is broken, so it only
                      *enriches* RAW_recipes, matched by recipe name.
Build on the computer and copy data/recipes.db to the Pi rather than building there.
"""
from __future__ import annotations

import argparse
import ast
import csv
import gzip
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

from recipes.ingredients import canonical
from recipes.store import CUISINES, DEFAULT_PATH, RecipeStore

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
SOURCES = {
    "RAW_recipes.csv": "https://huggingface.co/datasets/Cassiedu66/ai-blessed_raw_recipes/resolve/main/RAW_recipes.csv",
    "parsed_recipes.csv": "https://huggingface.co/datasets/Karo8870/food.com-parsed-dataset/resolve/main/parsed_recipes.csv",
}
SAMPLE_PATH = Path(__file__).resolve().parent / "sample_recipes.jsonl.gz"
SAMPLE_SIZE = 3000
SAMPLE_CUISINE_QUOTA = 160
MAX_MINUTES = 24 * 60
GENERIC_DESCRIPTION = re.compile(r"^make and share this .* recipe from food\.com\.?$", re.I)

csv.field_size_limit(2**31 - 1)


def _key(name: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", name.lower()))


def _float(value: str | None) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # drop NaN


def _json_list(value: str | None) -> list:
    if not value or value in ("character(0)", "NA"):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _py_list(value: str | None) -> list:
    try:
        parsed = ast.literal_eval(value) if value else []
    except (ValueError, SyntaxError):
        return []
    return parsed if isinstance(parsed, list) else []


def download_sources() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for filename, url in SOURCES.items():
        target = RAW_DIR / filename
        if target.exists() and target.stat().st_size > 0:
            continue
        print(f"Downloading {filename} (one time)...", flush=True)
        tmp = target.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(target)


def _raw_rows():
    with open(RAW_DIR / "RAW_recipes.csv", encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def _enrichment(wanted: set[str]) -> dict[str, dict]:
    """name key -> the extra fields parsed_recipes has for that recipe."""
    out: dict[str, dict] = {}
    with open(RAW_DIR / "parsed_recipes.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            k = _key(row.get("name") or "")
            if k not in wanted or k in out:
                continue
            images = [u for u in _json_list(row.get("images")) if isinstance(u, str) and u.startswith("http")]
            ingredients = [i for i in _json_list(row.get("ingredients")) if isinstance(i, dict) and i.get("name")]
            description = (row.get("description") or "").strip()
            out[k] = {
                "name": (row.get("name") or "").strip(),
                "servings": _float(row.get("servings")),
                "calories": _float(row.get("calories")),
                "protein_g": _float(row.get("protein")),
                "fat_g": _float(row.get("total_fat")),
                "carbs_g": _float(row.get("carbohydrates")),
                "fiber_g": _float(row.get("fiber")),
                "sugar_g": _float(row.get("sugar")),
                "sodium_mg": _float(row.get("sodium")),
                "image_url": images[0] if images else None,
                "description": None if GENERIC_DESCRIPTION.match(description) else description or None,
                "ingredients": ingredients,
            }
    return out


def clean_step(text: str) -> str:
    """The source text is pre-tokenized: 'ricotta , 1 / 4 cup ( optional )' -> 'ricotta, 1/4 cup (optional)'."""
    text = re.sub(r"\s+([,.;:!?)%])", r"\1", text.strip())
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"(\d)\s*/\s*(\d)", r"\1/\2", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text[:1].upper() + text[1:]


def _recipe(raw: dict, extra: dict | None, recipe_id: int) -> dict | None:
    steps = [clean_step(s) for s in _py_list(raw.get("steps")) if isinstance(s, str) and s.strip()]
    raw_ingredients = [s.strip() for s in _py_list(raw.get("ingredients")) if isinstance(s, str) and s.strip()]
    if not steps or len(raw_ingredients) < 2:
        return None
    tags = [t for t in _py_list(raw.get("tags")) if isinstance(t, str)]
    minutes = int(_float(raw.get("minutes")) or 0)
    extra = extra or {}

    detailed = extra.get("ingredients") or []
    if detailed and abs(len(detailed) - len(raw_ingredients)) <= 2:
        ingredients = [
            {"name": i["name"].strip(), "canon": canonical(i["name"]),
             "quantity": (i.get("quantity") or None), "unit": (i.get("unit") or None)}
            for i in detailed
        ]
    else:
        ingredients = [{"name": n, "canon": canonical(n), "quantity": None, "unit": None} for n in raw_ingredients]

    name = extra.get("name") or " ".join(raw["name"].split()).title()
    return {
        "id": recipe_id,
        "name": name,
        "cuisine": next((c for c in CUISINES if c in tags), None),
        "minutes": minutes if 0 < minutes <= MAX_MINUTES else None,
        "servings": extra.get("servings"),
        "calories": extra.get("calories") if extra.get("calories") is not None else _float(raw.get("calories")),
        "protein_g": extra.get("protein_g"),
        "fat_g": extra.get("fat_g"),
        "carbs_g": extra.get("carbs_g"),
        "fiber_g": extra.get("fiber_g"),
        "sugar_g": extra.get("sugar_g"),
        "sodium_mg": extra.get("sodium_mg"),
        "image_url": extra.get("image_url"),
        "description": extra.get("description"),
        "tags": tags,
        "ingredients": ingredients,
        "steps": steps,
    }


def build_full(out_path: Path) -> int:
    download_sources()
    started = time.time()
    print("Indexing recipe names...", flush=True)
    wanted = {_key(r["name"]) for r in _raw_rows()}
    print(f"  {len(wanted):,} recipes. Matching nutrition, quantities and photos...", flush=True)
    extras = _enrichment(wanted)
    print(f"  enriched {len(extras):,}. Writing library...", flush=True)

    tmp = out_path.with_suffix(".building")
    if tmp.exists():
        tmp.unlink()
    store = RecipeStore(tmp)
    written = 0
    for raw in _raw_rows():
        recipe = _recipe(raw, extras.get(_key(raw["name"])), written + 1)
        if recipe is None:
            continue
        store.add(recipe)
        written += 1
        if written % 20000 == 0:
            store.commit()
            print(f"  {written:,} written", flush=True)
    store.commit()
    store.close()
    tmp.replace(out_path)
    print(f"Done: {written:,} recipes in {out_path} ({time.time() - started:.0f}s)")
    return written


def write_sample(store: RecipeStore, path: Path = SAMPLE_PATH, size: int = SAMPLE_SIZE) -> int:
    """Pick a varied, good-looking starter set: has a photo and protein data, reasonable
    length, spread across cuisines, then filled with main dishes."""
    rng = random.Random(7)
    conn = store._conn
    base = """SELECT id FROM recipes WHERE image_url IS NOT NULL AND protein_g IS NOT NULL
              AND minutes IS NOT NULL AND minutes <= 90"""
    chosen: list[int] = []
    for cuisine in CUISINES[:-3]:  # skip the broad "asian"/"european"/"american" buckets here
        ids = [r[0] for r in conn.execute(base + " AND cuisine = ?", (cuisine,))]
        rng.shuffle(ids)
        chosen.extend(ids[:SAMPLE_CUISINE_QUOTA])
    mains = [r[0] for r in conn.execute(base + " AND tags LIKE '%\"main-dish\"%'") if r[0] not in set(chosen)]
    rng.shuffle(mains)
    chosen.extend(mains[: max(0, size - len(chosen))])
    chosen = chosen[:size]

    with gzip.open(path, "wt", encoding="utf-8") as f:
        for new_id, recipe in enumerate(store.get_many(chosen), start=1):
            row = {
                "id": new_id, "name": recipe.name, "cuisine": recipe.cuisine, "minutes": recipe.minutes,
                "servings": recipe.servings, **recipe.nutrition, "image_url": recipe.image_url,
                "description": recipe.description, "tags": recipe.tags, "ingredients": recipe.ingredients,
                "steps": recipe.steps,
            }
            f.write(json.dumps(row) + "\n")
    print(f"Wrote {len(chosen):,} recipes to {path} ({path.stat().st_size / 1e6:.1f} MB)")
    return len(chosen)


def load_sample_into(store: RecipeStore) -> int:
    if not SAMPLE_PATH.exists():
        return 0
    count = 0
    with gzip.open(SAMPLE_PATH, "rt", encoding="utf-8") as f:
        for line in f:
            store.add(json.loads(line))
            count += 1
    store.commit()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--sample-only", action="store_true", help="load just the bundled starter set")
    mode.add_argument("--write-sample", action="store_true", help="regenerate the bundled starter set from the full library")
    parser.add_argument("--out", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()

    if args.write_sample:
        store = RecipeStore(args.out)
        if store.count() < SAMPLE_SIZE:
            sys.exit("Build the full library first: python -m recipes.build")
        write_sample(store)
        return

    if args.sample_only:
        if args.out.exists():
            args.out.unlink()
        n = load_sample_into(RecipeStore(args.out))
        print(f"Loaded {n:,} starter recipes into {args.out}")
        return

    build_full(args.out)


if __name__ == "__main__":
    main()
