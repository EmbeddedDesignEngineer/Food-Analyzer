"""Offline service tests exercising the provided AI parser through fake VLMs."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest

import ai
from ai import Ingredient
from ai.providers.base import ProviderError, VLMProvider
from src.services import ai_service
from src.services.ai_service import AIConfigurationError, AIService
from src.services.image_validation import ImageTooLargeError, InvalidImageError


SECRET = "SECRET_RAW_PAYLOAD_SENTINEL"
SUCCESS = json.dumps({
    "meal_recognized": True,
    "ingredients": [{"name": "rice", "estimated_grams": 100, "confidence": 0.8}],
})


class ScriptedVLM(VLMProvider):
    def __init__(self, *outcomes: str | Exception) -> None:
        self.outcomes = iter(outcomes)
        self.calls: list[str] = []

    def describe(self, image_path: str, prompt: str, *, json_schema=None) -> str:
        self.calls.append(image_path)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def wrapped(cause: Exception) -> ProviderError:
    error = ProviderError(SECRET)
    error.__cause__ = cause
    return error


def status_error(value: object, location: str = "status_code") -> ProviderError:
    cause = RuntimeError(SECRET)
    if location == "response":
        cause.response = SimpleNamespace(status_code=value)
    else:
        setattr(cause, location, value)
    return wrapped(cause)


@pytest.fixture
def image_path(tmp_path):
    path = tmp_path / "meal.png"
    with Image.new("RGB", (8, 8), "green") as image:
        image.save(path)
    return path


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    factory = Mock(side_effect=AssertionError("Real provider factory must not run"))
    monkeypatch.setattr(ai_service, "get_vlm", factory)
    sleeps = []
    monkeypatch.setattr(ai_service, "_sleep", sleeps.append)
    return factory, sleeps


@pytest.mark.parametrize("as_string", [True, False])
@pytest.mark.parametrize("image_format,suffix", [("PNG", ".png"), ("JPEG", ".jpg")])
def test_success_uses_public_ai_function(tmp_path, monkeypatch, offline, as_string, image_format, suffix):
    path = tmp_path / f"meal{suffix}"
    with Image.new("RGB", (8, 8)) as image:
        image.save(path, format=image_format)
    vlm = ScriptedVLM(SUCCESS)
    identify = Mock(wraps=ai.identify_ingredients)
    monkeypatch.setattr(ai, "identify_ingredients", identify)
    result = AIService(max_size_bytes=1000, vlm=vlm).identify_ingredients(str(path) if as_string else path)
    assert result == [Ingredient(name="rice", estimated_grams=100, confidence=0.8)]
    identify.assert_called_once_with(str(path), vlm=vlm)
    offline[0].assert_not_called()
    assert offline[1] == []


@pytest.mark.parametrize("recognized", [True, False])
def test_empty_result_is_success(image_path, offline, recognized):
    vlm = ScriptedVLM(json.dumps({"meal_recognized": recognized, "ingredients": []}))
    assert AIService(max_size_bytes=1000, vlm=vlm).identify_ingredients(image_path) == []
    assert len(vlm.calls) == 1
    assert offline[1] == []


@pytest.mark.parametrize("injected", [True, False])
@pytest.mark.parametrize("kind,error", [("invalid", InvalidImageError), ("missing", FileNotFoundError), ("oversized", ImageTooLargeError)])
def test_bad_image_prevents_provider_work(tmp_path, image_path, offline, injected, kind, error):
    path = image_path
    limit = 1 if kind == "oversized" else 1000
    if kind == "missing":
        path = tmp_path / "absent.png"
    elif kind == "invalid":
        path.write_text("not an image")
    vlm = ScriptedVLM(SUCCESS)
    service = AIService(max_size_bytes=limit, vlm=vlm if injected else None)
    with pytest.raises(error):
        service.identify_ingredients(path)
    assert vlm.calls == []
    offline[0].assert_not_called()
    assert offline[1] == []


@pytest.mark.parametrize("cause_type", [ConnectionError, TimeoutError])
def test_transient_builtin_cause_retries(image_path, offline, cause_type):
    vlm = ScriptedVLM(wrapped(cause_type(SECRET)), SUCCESS)
    assert AIService(max_size_bytes=1000, vlm=vlm).identify_ingredients(image_path)
    assert len(vlm.calls) == 2
    assert offline[1] == [1.0]


@pytest.mark.parametrize("location", ["status_code", "response", "code"])
@pytest.mark.parametrize("status", [429, 500, 503, 599])
def test_transient_http_status_retries(image_path, offline, location, status):
    vlm = ScriptedVLM(status_error(status, location), SUCCESS)
    AIService(max_size_bytes=1000, vlm=vlm).identify_ingredients(image_path)
    assert len(vlm.calls) == 2
    assert offline[1] == [1.0]


@pytest.mark.parametrize("status", [400, 401, 403, True, False, "429", 503.0, 99, 600, None])
def test_nontransient_or_invalid_status_does_not_retry(image_path, offline, status):
    error = status_error(status)
    vlm = ScriptedVLM(error)
    with pytest.raises(ProviderError) as caught:
        AIService(max_size_bytes=1000, vlm=vlm).identify_ingredients(image_path)
    assert caught.value is error
    assert len(vlm.calls) == 1
    assert offline[1] == []


@pytest.mark.parametrize("error", [ProviderError("429 timeout 503"), wrapped(OSError("network?")), RuntimeError(SECRET), TimeoutError(SECRET)])
def test_unclassified_and_unexpected_errors_propagate(image_path, offline, error):
    vlm = ScriptedVLM(error)
    with pytest.raises(type(error)) as caught:
        AIService(max_size_bytes=1000, vlm=vlm).identify_ingredients(image_path)
    assert caught.value is error
    assert len(vlm.calls) == 1
    assert offline[1] == []


@pytest.mark.parametrize("payload", [
    SECRET, "[]",
    json.dumps({"meal_recognized": True, "ingredients": [{"name": "rice", "estimated_grams": -1, "confidence": 0.5}]}),
    json.dumps({"meal_recognized": True, "ingredients": [{"name": "rice", "estimated_grams": 1, "confidence": 2}]}),
    json.dumps({"ingredients": []}),
])
def test_invalid_response_not_retried(image_path, offline, payload):
    vlm = ScriptedVLM(payload)
    with pytest.raises(ProviderError):
        AIService(max_size_bytes=1000, vlm=vlm).identify_ingredients(image_path)
    assert len(vlm.calls) == 1
    assert offline[1] == []


def test_exhaustion_preserves_final_error_and_caps_backoff(image_path, offline):
    errors = [wrapped(TimeoutError(SECRET)) for _ in range(5)]
    vlm = ScriptedVLM(*errors)
    with pytest.raises(ProviderError) as caught:
        AIService(max_size_bytes=1000, vlm=vlm, max_attempts=5, max_wait_seconds=3).identify_ingredients(image_path)
    assert caught.value is errors[-1]
    assert isinstance(caught.value.__cause__, TimeoutError)
    assert len(vlm.calls) == 5
    assert offline[1] == [1, 2, 3, 3]


def test_factory_and_validation_once_per_operation(image_path, monkeypatch, offline):
    vlms = [ScriptedVLM(wrapped(ConnectionError()), SUCCESS) for _ in range(2)]
    offline[0].side_effect = vlms
    validate = Mock(wraps=ai_service.validate_image)
    monkeypatch.setattr(ai_service, "validate_image", validate)
    service = AIService(max_size_bytes=1000)
    for _ in range(2):
        service.identify_ingredients(image_path)
    assert validate.call_count == 2
    assert offline[0].call_count == 2
    assert [len(vlm.calls) for vlm in vlms] == [2, 2]
    assert offline[1] == [1, 1]


@pytest.mark.parametrize("error", [ProviderError(SECRET), RuntimeError(SECRET)])
def test_factory_errors(image_path, offline, error):
    offline[0].side_effect = error
    expected = AIConfigurationError if isinstance(error, ProviderError) else RuntimeError
    with pytest.raises(expected) as caught:
        AIService(max_size_bytes=1000).identify_ingredients(image_path)
    if isinstance(error, ProviderError):
        assert caught.value.__cause__ is error
        assert SECRET not in str(caught.value)
    else:
        assert caught.value is error
    offline[0].assert_called_once_with()
    assert offline[1] == []


@pytest.mark.parametrize("name", ["max_size_bytes", "max_attempts"])
@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "3", None])
def test_invalid_integer_policy(name, value):
    options = {"max_size_bytes": 1000, name: value}
    with pytest.raises(ValueError, match=name):
        AIService(**options)


@pytest.mark.parametrize("name", ["initial_wait_seconds", "max_wait_seconds"])
@pytest.mark.parametrize("value", [True, False, 0, -1, float("nan"), float("inf"), float("-inf"), "1", None, 1j])
def test_invalid_wait_policy(name, value):
    with pytest.raises(ValueError, match=name):
        AIService(max_size_bytes=1000, **{name: value})


def test_max_wait_must_cover_initial_wait():
    with pytest.raises(ValueError, match="max_wait_seconds"):
        AIService(max_size_bytes=1000, initial_wait_seconds=2, max_wait_seconds=1)


def test_unrepresentable_wait_raises_value_error():
    with pytest.raises(ValueError, match="initial_wait_seconds"):
        AIService(max_size_bytes=1000, initial_wait_seconds=10 ** 1000)


def test_result_list_is_returned_unchanged(image_path, monkeypatch):
    result = [Ingredient(name="rice", estimated_grams=100, confidence=0.8)]
    identify = Mock(return_value=result)
    monkeypatch.setattr(ai, "identify_ingredients", identify)
    vlm = ScriptedVLM()
    assert AIService(max_size_bytes=1000, vlm=vlm).identify_ingredients(image_path) is result
    identify.assert_called_once_with(str(image_path), vlm=vlm)


def test_one_attempt_has_no_sleep(image_path, offline):
    vlm = ScriptedVLM(wrapped(TimeoutError()))
    with pytest.raises(ProviderError):
        AIService(max_size_bytes=1000, vlm=vlm, max_attempts=1).identify_ingredients(image_path)
    assert offline[1] == []


@pytest.mark.parametrize("chain", ["context", "suppressed", "cycle"])
def test_cause_traversal(image_path, offline, chain):
    error = ProviderError(SECRET)
    error.__context__ = TimeoutError()
    if chain == "suppressed":
        error.__suppress_context__ = True
    elif chain == "cycle":
        error.__cause__ = error
    vlm = ScriptedVLM(error, SUCCESS)
    service = AIService(max_size_bytes=1000, vlm=vlm)
    if chain == "context":
        assert service.identify_ingredients(image_path)
        assert offline[1] == [1]
    else:
        with pytest.raises(ProviderError) as caught:
            service.identify_ingredients(image_path)
        assert caught.value is error
        assert offline[1] == []


@pytest.mark.parametrize("outcome", ["success", "failure", "setup", "malformed"])
def test_safe_logging(image_path, offline, caplog, outcome):
    caplog.set_level(logging.DEBUG, logger=ai_service.__name__)
    vlm = ScriptedVLM(status_error(429), SUCCESS)
    service = AIService(max_size_bytes=1000, vlm=vlm)
    if outcome == "success":
        service.identify_ingredients(image_path)
        assert "Identification completed" in caplog.text
        assert "ingredient_count=1" in caplog.text
        assert "attempt=1/3" in caplog.text
        assert "wait_seconds=1.000" in caplog.text
        assert "status=429" in caplog.text
    else:
        if outcome == "setup":
            offline[0].side_effect = ProviderError(SECRET)
            service = AIService(max_size_bytes=1000)
        else:
            vlm = ScriptedVLM(SECRET if outcome == "malformed" else ProviderError(SECRET))
            service = AIService(max_size_bytes=1000, vlm=vlm)
        with pytest.raises(ProviderError):
            service.identify_ingredients(image_path)
        assert "failed" in caplog.text
    assert "Identification started" in caplog.text
    assert "duration_seconds=" in caplog.text
    assert SECRET not in caplog.text
    assert str(image_path) not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
