"""Pure totals calculation: combine ingredients + nutrition facts."""

from __future__ import annotations

from ai.schemas import Ingredient, NutritionFacts, Nutrition


def compute_totals(
    ingredients: list[Ingredient],
    facts_by_name: dict[str, NutritionFacts],
) -> Nutrition:
    """Sum nutrition across ingredients.

    Parameters
    ----------
    ingredients : list[Ingredient]
        From the VLM.
    facts_by_name : dict[str, NutritionFacts]
        From the nutrition provider, keyed by `ingredient.name` (the same
        string the VLM produced — case-sensitive). Ingredients without an
        entry are skipped silently; the SE layer is responsible for
        handling/reporting missing lookups.

    Returns
    -------
    Nutrition
        The totals row.
    """
    total = Nutrition()
    for ing in ingredients:
        facts = facts_by_name.get(ing.name)
        if facts is None:
            continue
        total = total + facts.for_grams(ing.estimated_grams)
    return total
