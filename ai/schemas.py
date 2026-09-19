"""Pydantic schemas for Topic 2 — AI Food Analyzer.

The Pydantic models below are the structured types the AI module emits and
the SE layer consumes. The companion JSON schema is the contract we pass to
the VLM so it returns structured data we can validate.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


INGREDIENTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ingredients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "estimated_grams": {"type": "number", "minimum": 0},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["name", "estimated_grams", "confidence"],
                "additionalProperties": False,
            },
        },
        "meal_recognized": {"type": "boolean"},
    },
    "required": ["ingredients", "meal_recognized"],
    "additionalProperties": False,
}


class Ingredient(BaseModel):
    """One ingredient identified in a meal photo.

    Frozen so that the SE layer cannot mutate the AI output downstream.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    estimated_grams: float = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("name")
    @classmethod
    def _name_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must be non-empty")
        return v


class NutritionFacts(BaseModel):
    """Per-100g nutrition profile for an ingredient.

    All values are per 100g of the ingredient as found in the database.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    kcal_per_100g: float
    protein_g_per_100g: float
    carbs_g_per_100g: float
    fat_g_per_100g: float
    source: str = "USDA"

    def for_grams(self, grams: float) -> "Nutrition":
        scale = grams / 100.0
        return Nutrition(
            kcal=self.kcal_per_100g * scale,
            protein_g=self.protein_g_per_100g * scale,
            carbs_g=self.carbs_g_per_100g * scale,
            fat_g=self.fat_g_per_100g * scale,
        )


class Nutrition(BaseModel):
    """A computed nutrition row (totals or per-ingredient).

    Mutable on purpose: the SE layer often accumulates totals across
    ingredients with ``+=``.
    """

    model_config = ConfigDict(extra="forbid")

    kcal: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0

    def __add__(self, other: "Nutrition") -> "Nutrition":
        return Nutrition(
            kcal=self.kcal + other.kcal,
            protein_g=self.protein_g + other.protein_g,
            carbs_g=self.carbs_g + other.carbs_g,
            fat_g=self.fat_g + other.fat_g,
        )

    def to_dict(self) -> dict[str, float]:
        return self.model_dump()
