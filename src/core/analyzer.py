import asyncio

from src.services.ai_service import AIService
from src.services.nutrition_cache import NutritionCache
from src.concurrency.pipeline import fetch_all_nutrition
from ai import compute_totals


class Analyzer:
    def __init__(self, ai_service: AIService, nutrition_provider, cache: NutritionCache):
        self.ai_service = ai_service
        self.nutrition_provider = nutrition_provider
        self.cache = cache

    async def analyze(self, image_path: str):
        loop = asyncio.get_running_loop()

        ingredients = await loop.run_in_executor(
            None, self.ai_service.identify_ingredients, image_path
        )

        if not ingredients:
            return {"ingredients": [], "totals": None, "failed": []}

        facts_by_name, failed = await fetch_all_nutrition(
            ingredients, self.nutrition_provider, self.cache
        )

        totals = compute_totals(ingredients, facts_by_name)

        return {
            "ingredients": ingredients,
            "facts_by_name": facts_by_name,
            "totals": totals,
            "failed": failed,
        }




if __name__ == "__main__":
    from ai import NutritionFacts, Ingredient

    class FakeProvider:
        def lookup(self, name):
            return NutritionFacts(
                name=name,
                kcal_per_100g=100,
                protein_g_per_100g=10,
                carbs_g_per_100g=20,
                fat_g_per_100g=5,
            )

    async def main():

        fake_ingredients = [
            Ingredient(name="çörək", estimated_grams=50, confidence=0.9),
            Ingredient(name="pendir", estimated_grams=30, confidence=0.9),
        ]

        provider = FakeProvider()
        cache = NutritionCache(ttl_seconds=86400)

        facts_by_name, failed = await fetch_all_nutrition(fake_ingredients, provider, cache)
        totals = compute_totals(fake_ingredients, facts_by_name)

        print("Cəmi:", totals)
        print("Uğursuz:", failed)

    asyncio.run(main())