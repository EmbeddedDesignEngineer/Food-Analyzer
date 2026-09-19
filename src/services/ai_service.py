"""Synchronous ingredient identification with validation and bounded retries."""

from __future__ import annotations

import json
import logging
import math
from numbers import Real
from pathlib import Path
import time

from pydantic import ValidationError
from tenacity import (
    Retrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

import ai
from ai import Ingredient
from ai.providers.base import ProviderError, VLMProvider
from ai.providers.factory import get_vlm
from src.services.image_validation import validate_image


logger = logging.getLogger(__name__)


class AIConfigurationError(ProviderError):
    """The configured VLM could not be initialized."""


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _http_status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    for value in (
        getattr(exc, "status_code", None),
        getattr(response, "status_code", None),
        getattr(exc, "code", None),
    ):
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
            return value
    return None


def _failure_details(exc: BaseException) -> tuple[str, int | None]:
    """Classify preserved causes without inspecting potentially sensitive messages."""
    seen: set[int] = set()
    current: BaseException | None = exc
    category = "unclassified"
    status = None
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (json.JSONDecodeError, ValidationError)):
            return "invalid_response", None
        code = _http_status(current)
        if code is not None:
            if code != 429 and not 500 <= code <= 599:
                return "http_permanent", code
            category, status = "http_transient", code
        elif status is None:
            if isinstance(current, TimeoutError):
                category = "timeout"
            elif isinstance(current, ConnectionError):
                category = "connection"
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return category, status


def _is_retryable(exc: BaseException) -> bool:
    if not isinstance(exc, ProviderError) or isinstance(exc, AIConfigurationError):
        return False
    category, _ = _failure_details(exc)
    return category in {"http_transient", "timeout", "connection"}


class AIService:
    """Wrap ai.identify_ingredients without owning provider SDKs or concurrency.

    Unknown meals return an empty list. Input errors and unclassified provider
    errors are not retried. The supplied VLM interface exposes no request timeout.
    """

    def __init__(
        self,
        *,
        max_size_bytes: int,
        vlm: VLMProvider | None = None,
        max_attempts: int = 3,
        initial_wait_seconds: float = 1.0,
        max_wait_seconds: float = 8.0,
    ) -> None:
        for name, value in (
            ("max_size_bytes", max_size_bytes),
            ("max_attempts", max_attempts),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name, value in (
            ("initial_wait_seconds", initial_wait_seconds),
            ("max_wait_seconds", max_wait_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError(f"{name} must be a positive finite real number")
            try:
                finite = math.isfinite(value)
            except OverflowError as exc:
                raise ValueError(f"{name} is too large for a wait duration") from exc
            if not finite or value <= 0:
                raise ValueError(f"{name} must be a positive finite real number")
        if max_wait_seconds < initial_wait_seconds:
            raise ValueError("max_wait_seconds must be >= initial_wait_seconds")
        self._max_size_bytes = max_size_bytes
        self._vlm = vlm
        self._max_attempts = max_attempts
        self._initial_wait_seconds = initial_wait_seconds
        self._max_wait_seconds = max_wait_seconds

    def _log_retry(self, state: RetryCallState) -> None:
        assert state.outcome is not None and state.next_action is not None
        exc = state.outcome.exception()
        assert exc is not None
        category, status = _failure_details(exc)
        logger.warning(
            "Identification retry scheduled: attempt=%d/%d wait_seconds=%.3f category=%s status=%s",
            state.attempt_number, self._max_attempts, state.next_action.sleep, category, status,
        )

    def identify_ingredients(self, image_path: str | Path) -> list[Ingredient]:
        """Validate once, then identify with retries only for recognized transient failures."""
        started = time.perf_counter()
        logger.info("Identification started")
        path = validate_image(image_path, max_size_bytes=self._max_size_bytes)
        vlm = self._vlm
        if vlm is None:
            try:
                vlm = get_vlm()
            except ProviderError as exc:
                logger.warning(
                    "Identification setup failed: category=configuration duration_seconds=%.3f",
                    time.perf_counter() - started,
                )
                raise AIConfigurationError("Configured VLM could not be initialized") from exc

        logger.debug(
            "Identification settings: max_size_bytes=%d provider=%s",
            self._max_size_bytes, type(vlm).__name__,
        )
        retrying = Retrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(
                multiplier=self._initial_wait_seconds, max=self._max_wait_seconds,
            ),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
            before_sleep=self._log_retry,
            sleep=_sleep,
        )
        try:
            ingredients = retrying(ai.identify_ingredients, str(path), vlm=vlm)
        except ProviderError as exc:
            category, status = _failure_details(exc)
            logger.warning(
                "Identification failed: attempts=%d category=%s status=%s duration_seconds=%.3f",
                retrying.statistics["attempt_number"], category, status,
                time.perf_counter() - started,
            )
            raise
        logger.info(
            "Identification completed: ingredient_count=%d empty=%s duration_seconds=%.3f",
            len(ingredients), not ingredients, time.perf_counter() - started,
        )
        return ingredients
