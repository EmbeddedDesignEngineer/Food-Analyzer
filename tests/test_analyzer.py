import pytest

from ai import Ingredient, NutritionFacts
from src.core.analyzer import Analyzer
from src.models import AnalysisStatus
from src.services.nutrition_cache import NutritionCache


class FakeAIService:
    """Stands in for AIService — no VLM, no network."""

    def __init__(self, ingredients):
        self._ingredients = ingredients

    def identify_ingredients(self, image_path):
        return self._ingredients


class FakeProvider:
    def __init__(self, known: dict[str, NutritionFacts], fail_for: set[str] = frozenset()):
        self._known = known
        self._fail_for = fail_for

    def lookup(self, name):
        if name in self._fail_for:
            raise ValueError(f"lookup failed for {name!r}")
        return self._known[name]


def _facts(name):
    return NutritionFacts(
        name=name,
        kcal_per_100g=100,
        protein_g_per_100g=10,
        carbs_g_per_100g=20,
        fat_g_per_100g=5,
    )


@pytest.mark.asyncio
async def test_analyze_returns_ok_when_all_lookups_succeed():
    ingredients = [
        Ingredient(name="toyuq", estimated_grams=100, confidence=0.9),
        Ingredient(name="düyü", estimated_grams=150, confidence=0.9),
    ]
    ai_service = FakeAIService(ingredients)
    provider = FakeProvider({"toyuq": _facts("toyuq"), "düyü": _facts("düyü")})
    cache = NutritionCache(ttl_seconds=86400)

    record = await Analyzer(ai_service, provider, cache).analyze("fake.png")

    assert record.status == AnalysisStatus.OK
    assert len(record.ingredients) == 2
    assert record.warnings == []
    assert record.totals.kcal > 0


@pytest.mark.asyncio
async def test_analyze_returns_unknown_meal_when_no_ingredients():
    ai_service = FakeAIService([])
    provider = FakeProvider({})
    cache = NutritionCache(ttl_seconds=86400)

    record = await Analyzer(ai_service, provider, cache).analyze("fake.png")

    assert record.status == AnalysisStatus.UNKNOWN_MEAL
    assert record.ingredients == []
    assert record.warnings == ["no meal recognized in image"]


@pytest.mark.asyncio
async def test_analyze_returns_partial_when_some_lookups_fail():
    ingredients = [
        Ingredient(name="toyuq", estimated_grams=100, confidence=0.9),
        Ingredient(name="xiyar", estimated_grams=50, confidence=0.9),
    ]
    ai_service = FakeAIService(ingredients)
    provider = FakeProvider({"toyuq": _facts("toyuq")}, fail_for={"xiyar"})
    cache = NutritionCache(ttl_seconds=86400)

    record = await Analyzer(ai_service, provider, cache).analyze("fake.png")

    assert record.status == AnalysisStatus.PARTIAL
    assert len(record.ingredients) == 2
    xiyar_result = next(i for i in record.ingredients if i.name == "xiyar")
    assert xiyar_result.nutrition is None
    assert any("xiyar" in w for w in record.warnings)