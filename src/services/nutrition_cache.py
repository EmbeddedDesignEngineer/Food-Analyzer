"""In-process TTL storage for nutrition lookup results."""

from __future__ import annotations

from collections.abc import Callable
import logging
import math
from numbers import Real
import time

from ai import NutritionFacts


logger = logging.getLogger(__name__)


def _normalize(ingredient_name: str) -> str:
    if not isinstance(ingredient_name, str):
        raise TypeError("ingredient_name must be a string")
    key = ingredient_name.strip().casefold()
    if not key:
        raise ValueError("ingredient_name must be non-empty")
    return key


class NutritionCache:
    """Store process-local results without performing provider lookups.

    Concurrent orchestration and request coalescing belong to the caller;
    cache access must be serialized externally when used across threads.
    Expiration is lazy and cache hits do not extend the TTL.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 86400,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, Real):
            raise ValueError("ttl_seconds must be a positive finite real number")
        try:
            finite = math.isfinite(ttl_seconds)
        except OverflowError as exc:
            raise ValueError("ttl_seconds is too large for a duration") from exc
        if not finite or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be a positive finite real number")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: dict[str, tuple[NutritionFacts, float]] = {}

    def get(self, ingredient_name: str) -> NutritionFacts | None:
        """Return the stored object, or None for a missing or expired entry."""
        key = _normalize(ingredient_name)
        entry = self._entries.get(key)
        if entry is None:
            logger.debug("Nutrition cache MISS")
            return None
        facts, stored_at = entry
        if self._clock() - stored_at >= self._ttl_seconds:
            del self._entries[key]
            logger.debug("Nutrition cache EXPIRED")
            return None
        logger.debug("Nutrition cache HIT")
        return facts

    def set(self, ingredient_name: str, facts: NutritionFacts) -> None:
        """Store the exact model with a fresh timestamp, replacing any old entry."""
        key = _normalize(ingredient_name)
        if not isinstance(facts, NutritionFacts):
            raise TypeError("facts must be a NutritionFacts instance")
        stored_at = self._clock()
        self._entries[key] = (facts, stored_at)
        logger.debug("Nutrition cache SET")
