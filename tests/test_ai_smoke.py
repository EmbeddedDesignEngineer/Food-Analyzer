"""Smoke tests for the provided Topic 2 AI module.

These exercise the AI module's public interface end-to-end using fake providers
that do NOT touch the network. Students MUST NOT delete or weaken these tests;
they are part of the grading contract.

Add your own tests in tests/test_*.py — these stay as-is.
"""

from __future__ import annotations

import json

import pytest

from ai import (
    Ingredient,
    NutritionFacts,
    Nutrition,
    identify_ingredients,
    compute_totals,
)
from ai.providers.base import ProviderError
from ai.vlm import _parse_json
from ai.schemas import INGREDIENTS_SCHEMA


# --- identify_ingredients --------------------------------------------------


def test_identify_ingredients_returns_list_of_ingredients(fake_vlm, sample_image):
    result = identify_ingredients(sample_image, vlm=fake_vlm)
    assert isinstance(result, list)
    assert len(result) == 3
    assert all(isinstance(i, Ingredient) for i in result)


def test_identify_ingredients_returns_empty_when_meal_not_recognized(fake_vlm, sample_image):
    fake_vlm.payload = {"meal_recognized": False, "ingredients": []}
    result = identify_ingredients(sample_image, vlm=fake_vlm)
    assert result == []


def test_identify_ingredients_passes_image_path(fake_vlm, sample_image):
    identify_ingredients(sample_image, vlm=fake_vlm)
    assert len(fake_vlm.calls) == 1
    assert fake_vlm.calls[0][0] == sample_image


def test_identify_ingredients_rejects_negative_grams(fake_vlm, sample_image):
    fake_vlm.payload = {
        "meal_recognized": True,
        "ingredients": [{"name": "rice", "estimated_grams": -10, "confidence": 0.9}],
    }
    with pytest.raises(ProviderError):
        identify_ingredients(sample_image, vlm=fake_vlm)


def test_identify_ingredients_rejects_invalid_confidence(fake_vlm, sample_image):
    fake_vlm.payload = {
        "meal_recognized": True,
        "ingredients": [{"name": "rice", "estimated_grams": 100, "confidence": 1.7}],
    }
    with pytest.raises(ProviderError):
        identify_ingredients(sample_image, vlm=fake_vlm)


def test_identify_ingredients_rejects_empty_name(fake_vlm, sample_image):
    fake_vlm.payload = {
        "meal_recognized": True,
        "ingredients": [{"name": "  ", "estimated_grams": 100, "confidence": 0.5}],
    }
    with pytest.raises(ProviderError):
        identify_ingredients(sample_image, vlm=fake_vlm)


def test_identify_ingredients_rejects_missing_meal_recognized(fake_vlm, sample_image):
    fake_vlm.payload = {"ingredients": []}
    with pytest.raises(ProviderError):
        identify_ingredients(sample_image, vlm=fake_vlm)


def test_identify_ingredients_rejects_missing_field(fake_vlm, sample_image):
    fake_vlm.payload = {
        "meal_recognized": True,
        "ingredients": [{"name": "rice", "confidence": 0.9}],  # no estimated_grams
    }
    with pytest.raises(ProviderError):
        identify_ingredients(sample_image, vlm=fake_vlm)


# --- JSON parsing forgiveness ---------------------------------------------


def test_parse_json_strips_markdown_fences():
    raw = '```json\n{"meal_recognized": true, "ingredients": []}\n```'
    assert _parse_json(raw) == {"meal_recognized": True, "ingredients": []}


def test_parse_json_strips_bare_fences():
    raw = '```\n{"a": 1}\n```'
    assert _parse_json(raw) == {"a": 1}


def test_parse_json_rejects_non_object():
    with pytest.raises(ProviderError):
        _parse_json("[1, 2, 3]")


def test_parse_json_rejects_garbage():
    with pytest.raises(ProviderError):
        _parse_json("not json at all")


# --- Ingredient model ----------------------------------------------------


def test_ingredient_rejects_negative_grams():
    with pytest.raises(ValueError):
        Ingredient(name="rice", estimated_grams=-1, confidence=0.5)


def test_ingredient_rejects_out_of_range_confidence():
    with pytest.raises(ValueError):
        Ingredient(name="rice", estimated_grams=100, confidence=1.5)


def test_ingredient_rejects_empty_name():
    with pytest.raises(ValueError):
        Ingredient(name="   ", estimated_grams=100, confidence=0.5)


def test_ingredient_is_frozen():
    ing = Ingredient(name="rice", estimated_grams=100, confidence=0.5)
    with pytest.raises(Exception):  # FrozenInstanceError
        ing.estimated_grams = 200  # type: ignore


# --- NutritionFacts.for_grams ---------------------------------------------


def test_for_grams_scales_linearly():
    facts = NutritionFacts(
        name="rice", kcal_per_100g=130, protein_g_per_100g=2.7,
        carbs_g_per_100g=28, fat_g_per_100g=0.3,
    )
    half = facts.for_grams(50)
    assert abs(half.kcal - 65.0) < 1e-6
    assert abs(half.protein_g - 1.35) < 1e-6
    assert abs(half.carbs_g - 14.0) < 1e-6
    assert abs(half.fat_g - 0.15) < 1e-6


def test_for_grams_at_zero_is_zero():
    facts = NutritionFacts(
        name="rice", kcal_per_100g=130, protein_g_per_100g=2.7,
        carbs_g_per_100g=28, fat_g_per_100g=0.3,
    )
    n = facts.for_grams(0)
    assert n.kcal == 0.0 and n.protein_g == 0.0


def test_for_grams_at_100_matches_per_100g_values():
    facts = NutritionFacts(
        name="rice", kcal_per_100g=130, protein_g_per_100g=2.7,
        carbs_g_per_100g=28, fat_g_per_100g=0.3,
    )
    n = facts.for_grams(100)
    assert n.kcal == 130 and n.protein_g == 2.7


# --- Nutrition addition ---------------------------------------------------


def test_nutrition_addition_is_componentwise():
    a = Nutrition(kcal=100, protein_g=10, carbs_g=20, fat_g=5)
    b = Nutrition(kcal=50, protein_g=5, carbs_g=10, fat_g=2)
    c = a + b
    assert c.kcal == 150
    assert c.protein_g == 15
    assert c.carbs_g == 30
    assert c.fat_g == 7


def test_nutrition_default_is_zero():
    n = Nutrition()
    assert n.kcal == 0.0 and n.protein_g == 0.0


# --- compute_totals -------------------------------------------------------


def test_compute_totals_empty():
    n = compute_totals([], {})
    assert n.kcal == 0 and n.protein_g == 0


def test_compute_totals_single_ingredient(fake_nutrition):
    ings = [Ingredient(name="white rice (cooked)", estimated_grams=200, confidence=0.9)]
    facts = {"white rice (cooked)": fake_nutrition.lookup("white rice (cooked)")}
    n = compute_totals(ings, facts)
    # 200g of 130 kcal/100g = 260 kcal
    assert abs(n.kcal - 260.0) < 1e-6
    assert abs(n.carbs_g - 56.0) < 1e-6


def test_compute_totals_multiple_ingredients(fake_nutrition):
    ings = [
        Ingredient(name="white rice (cooked)", estimated_grams=200, confidence=0.9),
        Ingredient(name="grilled chicken breast", estimated_grams=150, confidence=0.85),
        Ingredient(name="broccoli", estimated_grams=80, confidence=0.8),
    ]
    facts = {n: fake_nutrition.lookup(n) for n in
             ["white rice (cooked)", "grilled chicken breast", "broccoli"]}
    n = compute_totals(ings, facts)
    # 260 (rice) + 247.5 (chicken) + 27.2 (broccoli) = 534.7 kcal
    assert abs(n.kcal - (260 + 247.5 + 27.2)) < 1e-6


def test_compute_totals_skips_missing_facts(fake_nutrition):
    """Ingredients without a facts entry contribute 0 to totals; the SE
    layer is responsible for surfacing the gap."""
    ings = [
        Ingredient(name="white rice (cooked)", estimated_grams=200, confidence=0.9),
        Ingredient(name="some unknown ingredient", estimated_grams=50, confidence=0.5),
    ]
    facts = {"white rice (cooked)": fake_nutrition.lookup("white rice (cooked)")}
    n = compute_totals(ings, facts)
    assert abs(n.kcal - 260.0) < 1e-6  # only the rice counted


# --- FakeNutrition sanity check (so students see how the contract works) --


def test_fake_nutrition_returns_facts(fake_nutrition):
    facts = fake_nutrition.lookup("broccoli")
    assert isinstance(facts, NutritionFacts)
    assert facts.kcal_per_100g == 34


def test_fake_nutrition_unknown_raises(fake_nutrition):
    with pytest.raises(ProviderError):
        fake_nutrition.lookup("dragonfruit smoothie")


# --- schema sanity --------------------------------------------------------


def test_schema_has_required_top_level_fields():
    assert set(INGREDIENTS_SCHEMA["required"]) == {"ingredients", "meal_recognized"}


def test_ingredient_rejects_extra_fields():
    """Pydantic ConfigDict(extra='forbid') enforces the schema contract."""
    with pytest.raises(Exception):  # pydantic.ValidationError
        Ingredient(
            name="rice", estimated_grams=100, confidence=0.5,
            totally_unknown_field=42,  # type: ignore[call-arg]
        )
