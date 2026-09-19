"""
AI module for Topic 2 — AI Food Analyzer.

Public surface
--------------
identify_ingredients(image_path, *, vlm=None) -> list[Ingredient]
    Use a VLM to identify ingredients with estimated portion sizes.

class NutritionProvider (abstract)
class USDAProvider     (concrete)
    Look up nutrition facts per 100g for an ingredient.

compute_totals(ingredients, facts_by_name) -> Nutrition
    Pure function: combine ingredients + facts into a totals row.

Schemas: Ingredient, NutritionFacts, Nutrition.
"""

from ai.schemas import Ingredient, NutritionFacts, Nutrition
from ai.vlm import identify_ingredients
from ai.nutrition import NutritionProvider, USDAProvider, get_nutrition_provider
from ai.calculator import compute_totals

__all__ = [
    "Ingredient",
    "NutritionFacts",
    "Nutrition",
    "identify_ingredients",
    "NutritionProvider",
    "USDAProvider",
    "get_nutrition_provider",
    "compute_totals",
]
