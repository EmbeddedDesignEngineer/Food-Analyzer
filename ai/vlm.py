"""High-level VLM call: identify ingredients from a meal photo."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai.providers.base import VLMProvider, ProviderError
from ai.providers.factory import get_vlm
from ai.schemas import INGREDIENTS_SCHEMA, Ingredient


_PROMPT = """You are a nutrition assistant analyzing a photo of a meal.

Identify each visible ingredient and estimate its weight in grams. Be specific
("white rice" not "rice", "grilled chicken breast" not just "chicken") and
realistic with portion sizes (a typical chicken breast is around 150-200 g).

If the photo does not contain a meal, set "meal_recognized" to false and
return an empty ingredients list.

For each ingredient: "confidence" reflects how sure you are about both the
identification and the portion estimate, on a 0..1 scale.
"""


class _VLMResponse(BaseModel):
    """Internal envelope used to validate the VLM's full payload at once."""

    model_config = ConfigDict(extra="forbid")

    meal_recognized: bool
    ingredients: list[Ingredient] = Field(default_factory=list)


def identify_ingredients(
    image_path: str,
    *,
    vlm: VLMProvider | None = None,
) -> list[Ingredient]:
    """Use a VLM to identify ingredients in a meal photo.

    Returns an empty list (without raising) when the model reports it does
    not recognize a meal in the image. This lets the SE layer handle the
    "unknown meal" case as a normal control-flow branch.

    Raises
    ------
    ProviderError
        If the model errors or returns an unparseable / schema-invalid response.
    """
    vlm = vlm or get_vlm()
    raw = vlm.describe(image_path, _PROMPT, json_schema=INGREDIENTS_SCHEMA)
    payload = _parse_json(raw)

    try:
        response = _VLMResponse.model_validate(payload)
    except ValidationError as e:
        raise ProviderError(f"VLM response failed schema validation: {e}") from e

    if not response.meal_recognized:
        return []
    return list(response.ingredients)


def _parse_json(raw: str) -> dict[str, Any]:
    s = raw.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        lines = lines[1:]
        s = "\n".join(lines).strip()
    try:
        obj = json.loads(s)
    except json.JSONDecodeError as e:
        raise ProviderError(f"Could not parse JSON from VLM: {e}\nRaw: {raw[:300]!r}")
    if not isinstance(obj, dict):
        raise ProviderError(f"Expected JSON object, got {type(obj).__name__}")
    return obj
