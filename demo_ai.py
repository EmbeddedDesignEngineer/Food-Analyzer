"""Demo harness for the Topic 2 AI module.

Two modes:

  python demo_ai.py                     # uses real providers from env (API keys required)
  python demo_ai.py --offline           # uses fake providers (no network)
  python demo_ai.py --offline --image data/sample_meal_2.png   # any sample

The offline mode is what we use during grading to confirm the pipeline shape
works without burning API credits.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ai import (
    Ingredient,
    NutritionFacts,
    Nutrition,
    identify_ingredients,
    compute_totals,
    NutritionProvider,
)
from ai.providers.base import VLMProvider, ProviderError


# --- offline fakes --------------------------------------------------------

class _OfflineVLM(VLMProvider):
    """Pulls a plausible ingredient list from the filename.

    The filename hints (e.g. 'rice_chicken_broccoli.png') drive the output.
    Real grading uses real VLMs; this exists so the pipeline runs end-to-end
    without API keys.
    """

    KNOWN = {
        "rice":     ("white rice (cooked)",       180.0),
        "chicken":  ("grilled chicken breast",    150.0),
        "broccoli": ("broccoli",                   80.0),
        "salmon":   ("salmon, baked",             140.0),
        "potato":   ("baked potato",              200.0),
        "egg":      ("boiled egg",                 50.0),
        "salad":    ("mixed green salad",         100.0),
        "pasta":    ("pasta, cooked",             220.0),
        "tomato":   ("tomato, raw",                70.0),
        "cheese":   ("cheddar cheese",             30.0),
        "avocado":  ("avocado",                   100.0),
        "bread":    ("white bread",                60.0),
    }

    def describe(self, image_path: str, prompt: str, *, json_schema=None) -> str:
        stem = Path(image_path).stem.lower()
        ingredients = []
        for keyword, (name, grams) in self.KNOWN.items():
            if keyword in stem:
                ingredients.append({
                    "name": name,
                    "estimated_grams": grams,
                    "confidence": 0.85,
                })
        if not ingredients:
            return json.dumps({"meal_recognized": False, "ingredients": []})
        return json.dumps({"meal_recognized": True, "ingredients": ingredients})


def _nf(name: str, kcal: float, protein: float, carbs: float, fat: float) -> NutritionFacts:
    """Compact constructor for the offline nutrition DB below."""
    return NutritionFacts(
        name=name,
        kcal_per_100g=kcal,
        protein_g_per_100g=protein,
        carbs_g_per_100g=carbs,
        fat_g_per_100g=fat,
        source="offline",
    )


class _OfflineNutrition(NutritionProvider):
    """Hard-coded per-100g facts for the ingredients the OfflineVLM can produce."""

    DB = {
        # name (as the offline VLM produces): NutritionFacts(per-100g values)
        "white rice (cooked)":    _nf("Rice, white, cooked",      130, 2.7, 28,  0.3),
        "grilled chicken breast": _nf("Chicken breast, grilled",  165, 31,  0,   3.6),
        "broccoli":               _nf("Broccoli, raw",            34,  2.8, 7,   0.4),
        "salmon, baked":          _nf("Salmon, baked",            206, 22,  0,   13),
        "baked potato":           _nf("Potato, baked",            93,  2.5, 21,  0.1),
        "boiled egg":             _nf("Egg, boiled",              155, 13,  1.1, 11),
        "mixed green salad":      _nf("Lettuce, mixed greens",    15,  1.4, 2.9, 0.2),
        "pasta, cooked":          _nf("Pasta, cooked",            158, 5.8, 31,  0.9),
        "tomato, raw":            _nf("Tomato, raw",              18,  0.9, 3.9, 0.2),
        "cheddar cheese":         _nf("Cheese, cheddar",          403, 25,  1.3, 33),
        "avocado":                _nf("Avocado, raw",             160, 2,   9,   15),
        "white bread":            _nf("Bread, white",             265, 9,   49,  3.2),
    }

    def lookup(self, ingredient_name: str) -> NutritionFacts:
        if ingredient_name not in self.DB:
            raise ProviderError(f"unknown ingredient: {ingredient_name!r}")
        return self.DB[ingredient_name]


# --- table rendering ------------------------------------------------------

def _render_table(rows: list[tuple[str, float, Nutrition]], totals: Nutrition) -> str:
    """Format ingredient rows + totals as an aligned text table."""
    headers = ("ingredient", "g", "kcal", "protein", "carbs", "fat")
    body = []
    for name, grams, n in rows:
        body.append((
            name,
            f"{grams:.0f}",
            f"{n.kcal:.0f}",
            f"{n.protein_g:.1f}",
            f"{n.carbs_g:.1f}",
            f"{n.fat_g:.1f}",
        ))
    body.append((
        "TOTAL",
        f"{sum(g for _, g, _ in rows):.0f}",
        f"{totals.kcal:.0f}",
        f"{totals.protein_g:.1f}",
        f"{totals.carbs_g:.1f}",
        f"{totals.fat_g:.1f}",
    ))
    widths = [
        max(len(headers[i]), max(len(r[i]) for r in body))
        for i in range(len(headers))
    ]
    def fmt(row, sep="  "):
        return sep.join(c.ljust(widths[i]) for i, c in enumerate(row))
    out = [fmt(headers)]
    out.append("-" * (sum(widths) + 2 * (len(widths) - 1)))
    for r in body[:-1]:
        out.append(fmt(r))
    out.append("-" * (sum(widths) + 2 * (len(widths) - 1)))
    out.append(fmt(body[-1]))
    return "\n".join(out)


# --- main demo ------------------------------------------------------------

def run_demo(offline: bool, image_path: str | None) -> None:
    here = Path(__file__).parent

    if image_path is None:
        # default: pick the first .png in data/
        candidates = sorted((here / "data").glob("*.png"))
        if not candidates:
            print(f"!! No sample images in {here / 'data'}/. "
                  f"Run `python data/_make_samples.py` first.", file=sys.stderr)
            sys.exit(2)
        img = candidates[0]
    else:
        img = Path(image_path)
        if not img.is_file():
            print(f"!! Image not found: {img}", file=sys.stderr)
            sys.exit(2)

    vlm = _OfflineVLM() if offline else None
    nutrition = _OfflineNutrition() if offline else None

    print(f"Analyzing: {img.name}  (mode={'offline' if offline else 'online'})\n")

    # Step 1: identify ingredients
    try:
        ingredients = identify_ingredients(str(img), vlm=vlm)
    except ProviderError as e:
        print(f"VLM failed: {e}", file=sys.stderr)
        sys.exit(1)

    if not ingredients:
        print("Meal not recognized in image.")
        return

    # Step 2: look up nutrition for each ingredient
    if nutrition is None:
        from ai import get_nutrition_provider
        try:
            nutrition = get_nutrition_provider()
        except ProviderError as e:
            print(f"Nutrition provider unavailable: {e}", file=sys.stderr)
            sys.exit(1)

    facts_by_name: dict[str, NutritionFacts] = {}
    rows: list[tuple[str, float, Nutrition]] = []
    for ing in ingredients:
        try:
            facts = nutrition.lookup(ing.name)
        except ProviderError as e:
            print(f"  ! Skipping {ing.name!r}: {e}", file=sys.stderr)
            continue
        facts_by_name[ing.name] = facts
        per_ing = facts.for_grams(ing.estimated_grams)
        rows.append((ing.name, ing.estimated_grams, per_ing))

    # Step 3: totals
    totals = compute_totals(ingredients, facts_by_name)

    print(_render_table(rows, totals))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--offline", action="store_true",
                   help="Use fake providers (no API keys, no network).")
    p.add_argument("--image", type=str, default=None,
                   help="Path to a meal image. Default: first .png in data/.")
    args = p.parse_args()
    run_demo(offline=args.offline, image_path=args.image)


if __name__ == "__main__":
    main()
