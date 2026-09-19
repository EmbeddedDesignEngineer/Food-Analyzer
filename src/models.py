import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from ai import Nutrition


class AnalysisStatus(str, Enum):
    OK = "ok"                      # every ingredient's nutrition was found
    PARTIAL = "partial"            # meal recognized, some nutrition lookups failed
    UNKNOWN_MEAL = "unknown_meal"  # VLM did not recognize a meal


class IngredientResult(BaseModel):
    name: str
    estimated_grams: float
    confidence: float
    nutrition: Nutrition | None = None  # None if this ingredient's lookup failed


class AnalysisRecord(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    image_filename: str
    status: AnalysisStatus
    ingredients: list[IngredientResult] = Field(default_factory=list)
    totals: Nutrition = Field(default_factory=Nutrition)
    warnings: list[str] = Field(default_factory=list)
