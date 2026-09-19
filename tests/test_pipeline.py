import pytest
from src.concurrency.pipeline import fetch_all_nutrition
from src.services.nutrition_cache import NutritionCache
from ai import NutritionFacts


class FakeIngredient:
    def __init__(self, name):
        self.name = name


class FakeProvider:
    def __init__(self):
        self.call_count = 0

    def lookup(self, name):
        self.call_count += 1
        if name == "bad":
            raise ValueError("API error")
        return NutritionFacts(
            name=name,
            kcal_per_100g=100,
            protein_g_per_100g=10,
            carbs_g_per_100g=20,
            fat_g_per_100g=5,
        )


@pytest.mark.asyncio
async def test_fetch_all_nutrition_success():
    ingredients = [FakeIngredient("toyuq"), FakeIngredient("düyü")]
    provider = FakeProvider()
    cache = NutritionCache(ttl_seconds=86400)

    facts_by_name, failed = await fetch_all_nutrition(ingredients, provider, cache)

    assert len(facts_by_name) == 2
    assert "toyuq" in facts_by_name
    assert "düyü" in facts_by_name
    assert len(failed) == 0


@pytest.mark.asyncio
async def test_fetch_all_nutrition_handles_failure():
    ingredients = [FakeIngredient("toyuq"), FakeIngredient("bad")]
    provider = FakeProvider()
    cache = NutritionCache(ttl_seconds=86400)

    facts_by_name, failed = await fetch_all_nutrition(ingredients, provider, cache)

    assert "toyuq" in facts_by_name
    assert "bad" not in facts_by_name
    assert len(failed) == 1


@pytest.mark.asyncio
async def test_cache_avoids_duplicate_calls():
    ingredients = [FakeIngredient("toyuq"), FakeIngredient("toyuq")]
    provider = FakeProvider()
    cache = NutritionCache(ttl_seconds=86400)

    await fetch_all_nutrition(ingredients, provider, cache)

    assert provider.call_count <= 2