"""USDA FoodData Central (general foods) + Open Food Facts (packaged/barcoded
products). Section 11. Each product is looked up once and cached in the
`products` table by inventory.database — these functions are only hit on a
cache miss.
"""
from __future__ import annotations

import os

import requests

USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
OFF_BARCODE_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
REQUEST_TIMEOUT_S = 6


def _usda_nutrient(food: dict, name: str) -> float | None:
    for n in food.get("foodNutrients", []):
        if n.get("nutrientName") == name:
            return n.get("value")
    return None


def lookup_nutrition_usda(food_name: str) -> dict | None:
    """Per-100g macro/micro nutrition for a general (non-packaged) food."""
    api_key = os.getenv("USDA_FDC_API_KEY")
    if not api_key:
        return None
    try:
        resp = requests.get(
            USDA_SEARCH_URL,
            params={"api_key": api_key, "query": food_name, "pageSize": 1, "dataType": "Foundation,SR Legacy"},
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        results = resp.json().get("foods", [])
    except requests.RequestException:
        return None
    if not results:
        return None

    food = results[0]
    return {
        "calories": _usda_nutrient(food, "Energy"),
        "protein_g": _usda_nutrient(food, "Protein"),
        "carbs_g": _usda_nutrient(food, "Carbohydrate, by difference"),
        "fat_g": _usda_nutrient(food, "Total lipid (fat)"),
        "fiber_g": _usda_nutrient(food, "Fiber, total dietary"),
        "sugar_g": _usda_nutrient(food, "Sugars, total including NLEA"),
        "sodium_mg": _usda_nutrient(food, "Sodium, Na"),
    }


def lookup_barcode_off(barcode: str) -> dict | None:
    """Name, package size, and per-100g nutrition for a scanned barcode."""
    try:
        resp = requests.get(OFF_BARCODE_URL.format(barcode=barcode), timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return None
    if data.get("status") != 1:
        return None

    product = data["product"]
    nutriments = product.get("nutriments", {})
    return {
        "name": product.get("product_name") or product.get("generic_name") or "Unknown product",
        "category": (product.get("categories") or "").split(",")[0].strip() or None,
        "package_size_g": _parse_quantity_g(product.get("quantity")),
        "nutrition": {
            "calories": nutriments.get("energy-kcal_100g"),
            "protein_g": nutriments.get("proteins_100g"),
            "carbs_g": nutriments.get("carbohydrates_100g"),
            "fat_g": nutriments.get("fat_100g"),
            "fiber_g": nutriments.get("fiber_100g"),
            "sugar_g": nutriments.get("sugars_100g"),
            "sodium_mg": (nutriments.get("sodium_100g") or 0) * 1000 if nutriments.get("sodium_100g") else None,
        },
    }


def _parse_quantity_g(quantity: str | None) -> float | None:
    if not quantity:
        return None
    q = quantity.lower().replace(" ", "")
    try:
        if "kg" in q:
            return float(q.replace("kg", "")) * 1000
        if "g" in q:
            return float(q.replace("g", ""))
    except ValueError:
        return None
    return None


def nutrition_for_grams(product_row, grams: float) -> dict:
    """Scale a product's per-100g nutrition to an actual portion."""
    factor = grams / 100.0
    fields = ["calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg"]
    return {
        field: (product_row[f"{field}_per_100g"] * factor) if product_row[f"{field}_per_100g"] is not None else None
        for field in fields
    }
