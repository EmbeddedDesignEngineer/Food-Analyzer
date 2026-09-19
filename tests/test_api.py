from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from ai import Nutrition
from src.api import app
from src.models import AnalysisRecord, AnalysisStatus, IngredientResult


class FakeRepository:
    def __init__(self, records: list[AnalysisRecord] | None = None, error: Exception | None = None) -> None:
        self.records = records or []
        self.error = error
        self.limits: list[int] = []

    async def list_recent(self, limit: int = 20) -> list[AnalysisRecord]:
        self.limits.append(limit)
        if self.error is not None:
            raise self.error
        return self.records[:limit]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Not entering the client as a context manager skips the lifespan, so no
    # database or API keys are needed; each test installs the state it wants.
    monkeypatch.setattr(app.state, "analyzer", None, raising=False)
    monkeypatch.setattr(app.state, "repository", None, raising=False)
    return TestClient(app)


def _record(image_filename: str) -> AnalysisRecord:
    nutrition = Nutrition(kcal=234, protein_g=4.9, carbs_g=50.4, fat_g=0.5)
    return AnalysisRecord(
        image_filename=image_filename,
        status=AnalysisStatus.OK,
        ingredients=[
            IngredientResult(name="white rice (cooked)", estimated_grams=180, confidence=0.9, nutrition=nutrition),
        ],
        totals=nutrition,
    )


def test_index_serves_the_web_ui(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Food Analyzer</title>" in response.text
    assert response.headers["cache-control"] == "no-cache"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_index_answers_head_requests(client: TestClient) -> None:
    response = client.head("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.content == b""


def test_every_asset_the_page_references_is_served(client: TestClient) -> None:
    html = client.get("/").text
    assets = re.findall(r'(?:href|src)="(static/[^"]+)"', html)

    assert {"static/app.js", "static/styles.css"} <= set(assets)
    for asset in assets:
        response = client.get(f"/{asset}")
        assert response.status_code == 200, asset
        assert response.headers["cache-control"] == "no-cache"


def test_web_ui_is_left_out_of_the_openapi_schema(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/" not in paths
    assert "/analyses" in paths


def test_list_analyses_returns_saved_records(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository([_record("newer.png"), _record("older.png")])
    monkeypatch.setattr(app.state, "repository", repo)

    response = client.get("/analyses", params={"limit": 5})

    assert response.status_code == 200
    body = response.json()
    assert [r["image_filename"] for r in body] == ["newer.png", "older.png"]
    assert body[0]["totals"]["kcal"] == 234
    assert body[0]["ingredients"][0]["nutrition"]["protein_g"] == 4.9
    assert repo.limits == [5]


def test_list_analyses_defaults_to_20(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    monkeypatch.setattr(app.state, "repository", repo)

    response = client.get("/analyses")

    assert response.status_code == 200
    assert response.json() == []
    assert repo.limits == [20]


@pytest.mark.parametrize("limit", [0, 101, "many"])
def test_list_analyses_rejects_invalid_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch, limit) -> None:
    repo = FakeRepository()
    monkeypatch.setattr(app.state, "repository", repo)

    response = client.get("/analyses", params={"limit": limit})

    assert response.status_code == 422
    assert repo.limits == []


def test_list_analyses_without_database_is_503(client: TestClient) -> None:
    response = client.get("/analyses")

    assert response.status_code == 503
    assert response.json()["error"] == "service_unavailable"


def test_list_analyses_hides_database_errors_behind_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.state, "repository", FakeRepository(error=RuntimeError("password=hunter2 rejected")))

    response = client.get("/analyses")

    assert response.status_code == 503
    assert response.json() == {"error": "service_unavailable", "detail": "Could not load analysis history"}
