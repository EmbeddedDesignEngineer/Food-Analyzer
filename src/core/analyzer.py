"""Business-logic entry point for the analysis pipeline.

Wires together: AIService (ingredient identification) -> pipeline.py
(parallel, cached nutrition lookups) -> compute_totals -> AnalysisRecord.

cli.py imports analyze_meal from here and nothing else.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ai import compute_totals, get_nutrition_provider
from ai.providers.base import ProviderError

from src.concurrency.pipeline import fetch_all_nutrition
from src.models import AnalysisRecord, AnalysisStatus, IngredientResult
from src.services.ai_service import AIService
from src.services.nutrition_cache import NutritionCache

# TODO(config): max_size_bytes and ttl_seconds should come from D's config,

_MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024
_cache = NutritionCache(ttl_seconds=86400)


async def analyze_meal(image_path: str, *, offline: bool = False) -> AnalysisRecord:

    loop = asyncio.get_running_loop()
    image_filename = Path(image_path).name

    if offline:
        from demo_ai import _OfflineVLM, _OfflineNutrition
        vlm = _OfflineVLM()
        provider = _OfflineNutrition()
    else:
        vlm = None
        provider = get_nutrition_provider()

    ai_service = AIService(max_size_bytes=_MAX_IMAGE_SIZE_BYTES, vlm=vlm)


    try:
        ingredients = await loop.run_in_executor(
            None, ai_service.identify_ingredients, image_path
        )
    except ProviderError as exc:

        return AnalysisRecord(
            image_filename=image_filename,
            status=AnalysisStatus.UNKNOWN_MEAL,
            warnings=[f"Ingredient identification failed: {exc}"],
        )

    if not ingredients:
        # Empty list is a valid, normal result: VLM didn't recognize a meal.
        return AnalysisRecord(
            image_filename=image_filename,
            status=AnalysisStatus.UNKNOWN_MEAL,
        )

    facts_by_name, failed = await fetch_all_nutrition(ingredients, provider, _cache)

    ingredient_results: list[IngredientResult] = []
    warnings: list[str] = []
    for ing in ingredients:
        facts = facts_by_name.get(ing.name)
        ingredient_results.append(
            IngredientResult(
                name=ing.name,
                estimated_grams=ing.estimated_grams,
                confidence=ing.confidence,
                nutrition=facts.for_grams(ing.estimated_grams) if facts is not None else None,
            )
        )
        if facts is None:
            warnings.append(f"Nutrition lookup failed for {ing.name!r}")

    totals = compute_totals(ingredients, facts_by_name)

    status = AnalysisStatus.OK if not failed else AnalysisStatus.PARTIAL

    return AnalysisRecord(
        image_filename=image_filename,
        status=status,
        ingredients=ingredient_results,
        totals=totals,
        warnings=warnings,
    )


if __name__ == "__main__":
    async def _manual_test():
        record = await analyze_meal("data/rice_chicken_broccoli.png", offline=True)
        print("status:", record.status)
        print("ingredients:", record.ingredients)
        print("totals:", record.totals)
        print("warnings:", record.warnings)

    asyncio.run(_manual_test())
