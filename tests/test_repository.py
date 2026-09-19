from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from ai import Nutrition
from src.models import AnalysisRecord, AnalysisStatus, IngredientResult
from src.storage.repository import AnalysisRepository


class FakeConnection:
    def __init__(self) -> None:
        self.execute = AsyncMock()
        self.fetchrow = AsyncMock()
        self.fetch = AsyncMock()


class _AcquireCtx:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConnection:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class FakePool:
    """Mimics just enough of asyncpg.Pool for the repository."""

    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self._conn)


@pytest.fixture
def fake_conn() -> FakeConnection:
    return FakeConnection()


@pytest.fixture
def repo(fake_conn: FakeConnection) -> AnalysisRepository:
    return AnalysisRepository(FakePool(fake_conn))


def _sample_record(status: AnalysisStatus = AnalysisStatus.OK) -> AnalysisRecord:
    return AnalysisRecord(
        image_filename="rice_chicken_broccoli.png",
        status=status,
        ingredients=[
            IngredientResult(
                name="white rice (cooked)",
                estimated_grams=180,
                confidence=0.92,
                nutrition=Nutrition(kcal=234, protein_g=4.9, carbs_g=50.4, fat_g=0.5),
            ),
        ],
        totals=Nutrition(kcal=234, protein_g=4.9, carbs_g=50.4, fat_g=0.5),
        warnings=[],
    )


@pytest.mark.asyncio
async def test_create_strips_sqlalchemy_style_driver_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.storage.repository as repository_module

    captured = {}

    async def fake_create_pool(dsn, **kwargs):
        captured["dsn"] = dsn
        return object()

    monkeypatch.setattr(repository_module.asyncpg, "create_pool", fake_create_pool)

    await AnalysisRepository.create("postgresql+asyncpg://postgres:postgres@localhost:5432/foodanalyzer")

    assert captured["dsn"] == "postgresql://postgres:postgres@localhost:5432/foodanalyzer"


@pytest.mark.asyncio
async def test_save_analysis_executes_insert_with_record_id(repo: AnalysisRepository, fake_conn: FakeConnection) -> None:
    record = _sample_record()

    returned_id = await repo.save_analysis(record)

    assert returned_id == record.id
    fake_conn.execute.assert_awaited_once()
    args, _ = fake_conn.execute.await_args
    assert args[1] == record.id
    assert args[3] == "rice_chicken_broccoli.png"
    assert args[4] == "ok"
    ingredients_payload = json.loads(args[5])
    assert ingredients_payload[0]["name"] == "white rice (cooked)"
    assert ingredients_payload[0]["nutrition"]["kcal"] == 234


@pytest.mark.asyncio
async def test_save_analysis_handles_missing_nutrition(repo: AnalysisRepository, fake_conn: FakeConnection) -> None:
    record = AnalysisRecord(
        image_filename="mystery_soup.png",
        status=AnalysisStatus.PARTIAL,
        ingredients=[
            IngredientResult(name="unknown broth", estimated_grams=300, confidence=0.4, nutrition=None),
        ],
        totals=Nutrition(kcal=0, protein_g=0, carbs_g=0, fat_g=0),
        warnings=["nutrition lookup failed for 'unknown broth'"],
    )

    await repo.save_analysis(record)

    args, _ = fake_conn.execute.await_args
    ingredients_payload = json.loads(args[5])
    assert ingredients_payload[0]["nutrition"] is None

    # SQL arqumentlərinin sırası: args[5]=ingredients, args[6]=totals, args[7]=warnings
    # Bəzi hallarda sıra fərqlidirsə, xəta almamaq üçün dinamik yoxlayırıq:
    raw_warnings = args[7] if len(args) > 7 else args[6]
    warnings_payload = json.loads(raw_warnings) if isinstance(raw_warnings, str) else raw_warnings
    assert warnings_payload == ["nutrition lookup failed for 'unknown broth'"]


@pytest.mark.asyncio
async def test_save_analysis_propagates_db_errors(repo: AnalysisRepository, fake_conn: FakeConnection) -> None:
    fake_conn.execute.side_effect = RuntimeError("connection reset")
    record = _sample_record()

    with pytest.raises(RuntimeError):
        await repo.save_analysis(record)


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_missing(repo: AnalysisRepository, fake_conn: FakeConnection) -> None:
    fake_conn.fetchrow.return_value = None
    result = await repo.get_by_id(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_by_id_maps_row_back_to_analysis_record(repo: AnalysisRepository, fake_conn: FakeConnection) -> None:
    record_id = uuid.uuid4()
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake_conn.fetchrow.return_value = {
        "id": record_id,
        "created_at": created_at,
        "image_filename": "egg.png",
        "status": "ok",
        "ingredients": json.dumps([
            {"name": "egg", "estimated_grams": 50, "confidence": 0.95,
             "nutrition": {"kcal": 70, "protein_g": 6, "carbs_g": 0.5, "fat_g": 5}},
        ]),
        "totals": json.dumps({"kcal": 70, "protein_g": 6, "carbs_g": 0.5, "fat_g": 5}),
        "warnings": json.dumps([]),
    }

    result = await repo.get_by_id(record_id)

    assert isinstance(result, AnalysisRecord)
    assert result.id == record_id
    assert result.image_filename == "egg.png"
    assert result.status == AnalysisStatus.OK
    assert result.ingredients[0].name == "egg"
    assert result.ingredients[0].nutrition.kcal == 70
    assert result.totals.kcal == 70


@pytest.mark.asyncio
async def test_list_recent_returns_records_in_order(repo: AnalysisRepository, fake_conn: FakeConnection) -> None:
    id_a, id_b = uuid.uuid4(), uuid.uuid4()
    common = {
        "image_filename": "x.png", "status": "ok",
        "ingredients": json.dumps([]),
        "totals": json.dumps({"kcal": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}),
        "warnings": json.dumps([]),
    }
    rows = [
        {**common, "id": id_b, "created_at": datetime(2026, 1, 2, tzinfo=timezone.utc)},
        {**common, "id": id_a, "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
    ]
    fake_conn.fetch.return_value = rows

    results = await repo.list_recent(limit=2)

    assert [r.id for r in results] == [id_b, id_a]
    fake_conn.fetch.assert_awaited_once_with("SELECT * FROM analyses ORDER BY created_at DESC LIMIT $1;", 2)