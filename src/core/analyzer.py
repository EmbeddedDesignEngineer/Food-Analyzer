from __future__ import annotations

import asyncio

from ai import Ingredient, NutritionFacts, compute_totals, get_nutrition_provider
from ai.providers.base import ProviderError

from src.concurrency.pipeline import fetch_all_nutrition
from src.models import AnalysisRecord, AnalysisStatus, IngredientResult, Nutrition
from src.services.ai_service import AIService
from src.services.nutrition_cache import NutritionCache


def _scale_to_grams(facts: NutritionFacts, grams: float) -> Nutrition:
    factor = grams / 100.0
    return Nutrition(
        kcal=facts.kcal_per_100g * factor,
        protein_g=facts.protein_g_per_100g * factor,
        carbs_g=facts.carbs_g_per_100g * factor,
        fat_g=facts.fat_g_per_100g * factor,
    )


class Analyzer:
    def __init__(self, ai_service: AIService, nutrition_provider, cache: NutritionCache):
        self.ai_service = ai_service
        self.nutrition_provider = nutrition_provider
        self.cache = cache

    async def analyze(self, image_path: str, *, offline: bool = False) -> AnalysisRecord:
        loop = asyncio.get_running_loop()

        try:
            ingredients: list[Ingredient] = await loop.run_in_executor(
                None, self.ai_service.identify_ingredients, image_path
            )
        except ProviderError as exc:
            return AnalysisRecord(
                image_filename=image_path,
                status=AnalysisStatus.UNKNOWN_MEAL,
                ingredients=[],
                totals=Nutrition(),
                warnings=[f"ingredient identification failed: {exc}"],
            )

        if not ingredients:
            return AnalysisRecord(
                image_filename=image_path,
                status=AnalysisStatus.UNKNOWN_MEAL,
                ingredients=[],
                totals=Nutrition(),
                warnings=["no meal recognized in image"],
            )

        facts_by_name, failed = await fetch_all_nutrition(
            ingredients, self.nutrition_provider, self.cache
        )

        ingredient_results = [
            IngredientResult(
                name=ing.name,
                estimated_grams=ing.estimated_grams,
                confidence=ing.confidence,
                nutrition=(
                    _scale_to_grams(facts_by_name[ing.name], ing.estimated_grams)
                    if ing.name in facts_by_name else None
                ),
            )
            for ing in ingredients
        ]

        totals = compute_totals(ingredients, facts_by_name)
        status = AnalysisStatus.PARTIAL if failed else AnalysisStatus.OK


        missing_names = [ing.name for ing in ingredients if ing.name not in facts_by_name]
        warnings = [f"nutrition lookup failed for {name!r}" for name in missing_names]

        return AnalysisRecord(
            image_filename=image_path,
            status=status,
            ingredients=ingredient_results,
            totals=totals,
            warnings=warnings,
        )


async def analyze_meal(image_path: str, *, offline: bool = False) -> AnalysisRecord:


    if offline:
        from demo_ai import _OfflineVLM, _OfflineNutrition
        vlm = _OfflineVLM()
        nutrition_provider = _OfflineNutrition()
    else:
        vlm = None
        nutrition_provider = get_nutrition_provider()

    ai_service = AIService(max_size_bytes=5 * 1024 * 1024, vlm=vlm)
    cache = NutritionCache(ttl_seconds=86400)
    return await Analyzer(ai_service, nutrition_provider, cache).analyze(image_path, offline=offline)


if __name__ == "__main__":
    async def _manual_test():
        record = await analyze_meal("data/rice_chicken_broccoli.png", offline=True)
        print("status:", record.status)
        print("ingredients:", record.ingredients)
        print("totals:", record.totals)
        print("warnings:", record.warnings)

    asyncio.run(_manual_test())