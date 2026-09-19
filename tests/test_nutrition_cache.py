"""Offline cache tests with deterministic elapsed time and real nutrition models."""

import logging

import pytest

from ai import NutritionFacts
from src.services.nutrition_cache import NutritionCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.error: Exception | None = None

    def __call__(self) -> float:
        if self.error is not None:
            raise self.error
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def facts():
    return NutritionFacts(
        name="Rice, cooked", kcal_per_100g=130, protein_g_per_100g=2.7,
        carbs_g_per_100g=28, fat_g_per_100g=0.3,
    )


@pytest.fixture
def cache(clock):
    return NutritionCache(ttl_seconds=10, clock=clock)


def test_missing_key(cache):
    assert cache.get("rice") is None


@pytest.mark.parametrize("key", ["rice", " Rice ", "RICE"])
def test_normalized_keys_return_exact_object(cache, facts, key):
    cache.set(key, facts)
    for equivalent in ("rice", " Rice ", "RICE"):
        assert cache.get(equivalent) is facts
    assert facts.name == "Rice, cooked"


def test_casefold_not_just_lowercase(cache, facts):
    cache.set("Straße", facts)
    assert cache.get("STRASSE") is facts


def test_internal_whitespace_remains_distinct(cache, facts):
    cache.set("white  rice", facts)
    assert cache.get("white rice") is None
    assert cache.get("white  rice") is facts


def test_replacement_resets_ttl(cache, clock, facts):
    replacement = facts.model_copy(update={"name": "Different rice"})
    cache.set("rice", facts)
    clock.now += 9
    cache.set(" RICE ", replacement)
    clock.now += 1
    assert cache.get("rice") is replacement
    clock.now += 9
    assert cache.get("rice") is None


@pytest.mark.parametrize("age,valid", [(9.999, True), (10, False), (11, False)])
def test_expiration_boundary(cache, clock, facts, age, valid):
    cache.set("rice", facts)
    clock.now += age
    assert cache.get("rice") is (facts if valid else None)


def test_expiration_removes_entry_and_next_access_is_miss(cache, clock, facts, caplog):
    cache.set("rice", facts)
    clock.now += 10
    with caplog.at_level(logging.DEBUG, logger="src.services.nutrition_cache"):
        assert cache.get("rice") is None
        assert cache.get("rice") is None
    assert [record.getMessage() for record in caplog.records] == [
        "Nutrition cache EXPIRED", "Nutrition cache MISS",
    ]
    assert not cache._entries  # Verify actual removal, not just repeated rejection.


@pytest.mark.parametrize("read_expired", [True, False])
def test_set_after_expiration(cache, clock, facts, read_expired):
    cache.set("rice", facts)
    clock.now += 20
    if read_expired:
        assert cache.get("rice") is None
    cache.set("rice", facts)
    clock.now += 9
    assert cache.get("rice") is facts
    clock.now += 1
    assert cache.get("rice") is None


def test_get_does_not_extend_ttl(cache, clock, facts):
    cache.set("rice", facts)
    for _ in range(9):
        clock.now += 1
        assert cache.get("rice") is facts
    clock.now += 1
    assert cache.get("rice") is None


def test_keys_expire_independently(cache, clock, facts):
    other = facts.model_copy(update={"name": "Broccoli"})
    cache.set("rice", facts)
    clock.now += 5
    cache.set("broccoli", other)
    clock.now += 5
    assert cache.get("rice") is None
    assert cache.get("broccoli") is other


def test_instances_do_not_share_entries(cache, clock, facts):
    cache.set("rice", facts)
    assert NutritionCache(clock=clock).get("rice") is None


def test_default_ttl(clock, facts):
    cache = NutritionCache(clock=clock)
    cache.set("rice", facts)
    clock.now += 86399
    assert cache.get("rice") is facts
    clock.now += 1
    assert cache.get("rice") is None


@pytest.mark.parametrize("ttl", [1, 0.5])
def test_positive_integer_and_float_ttl(clock, facts, ttl):
    cache = NutritionCache(ttl_seconds=ttl, clock=clock)
    cache.set("rice", facts)
    assert cache.get("rice") is facts
    clock.now += ttl
    assert cache.get("rice") is None


@pytest.mark.parametrize("ttl", [
    True, False, 0, -1, float("nan"), float("inf"), float("-inf"),
    "10", 1j, None, [], object(), 10 ** 1000,
])
def test_invalid_ttl(ttl):
    with pytest.raises(ValueError, match="ttl_seconds"):
        NutritionCache(ttl_seconds=ttl)


@pytest.mark.parametrize("name", ["", " ", "\t\n"])
@pytest.mark.parametrize("method", ["get", "set"])
def test_blank_names(cache, facts, name, method):
    with pytest.raises(ValueError, match="ingredient_name"):
        if method == "get":
            cache.get(name)
        else:
            cache.set(name, facts)


@pytest.mark.parametrize("name", [None, 1, True, [], b"rice"])
@pytest.mark.parametrize("method", ["get", "set"])
def test_nonstring_names(cache, facts, name, method):
    with pytest.raises(TypeError, match="ingredient_name"):
        if method == "get":
            cache.get(name)
        else:
            cache.set(name, facts)


@pytest.mark.parametrize("invalid_facts", [None, {}, "rice", 130])
def test_invalid_replacement_preserves_value_and_timestamp(cache, clock, facts, invalid_facts):
    cache.set("rice", facts)
    clock.now += 9
    with pytest.raises(TypeError, match="NutritionFacts"):
        cache.set(" RICE ", invalid_facts)
    assert cache.get("rice") is facts
    clock.now += 1
    assert cache.get("rice") is None


@pytest.mark.parametrize("clock", [None, 1, "clock"])
def test_noncallable_clock(clock):
    with pytest.raises(TypeError, match="clock"):
        NutritionCache(clock=clock)


@pytest.mark.parametrize("method", ["get", "set"])
def test_clock_failure_propagates_without_mutation(cache, clock, facts, method):
    cache.set("rice", facts)
    failure = RuntimeError("clock failed")
    clock.error = failure
    with pytest.raises(RuntimeError) as caught:
        if method == "get":
            cache.get("rice")
        else:
            cache.set("rice", facts.model_copy(update={"name": "replacement"}))
    assert caught.value is failure
    clock.error = None
    assert cache.get("rice") is facts
    clock.now += 10
    assert cache.get("rice") is None


def test_logging_only_safe_debug_events(cache, clock, caplog):
    name = "INGREDIENT_SENTINEL"
    facts = NutritionFacts(
        name="PAYLOAD_SENTINEL", source="SOURCE_SENTINEL",
        kcal_per_100g=130, protein_g_per_100g=2.7,
        carbs_g_per_100g=28, fat_g_per_100g=0.3,
    )
    with caplog.at_level(logging.DEBUG, logger="src.services.nutrition_cache"):
        cache.get(name)
        cache.set(name, facts)
        cache.get(name)
        clock.now += 10
        cache.get(name)
    assert [record.getMessage() for record in caplog.records] == [
        "Nutrition cache MISS", "Nutrition cache SET",
        "Nutrition cache HIT", "Nutrition cache EXPIRED",
    ]
    assert all(record.levelno == logging.DEBUG for record in caplog.records)
    for sentinel in (name, name.casefold(), facts.name, facts.source):
        assert sentinel not in caplog.text
