from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.cli import _print_table, build_parser, main
from src.models import AnalysisRecord, AnalysisStatus, IngredientResult, Nutrition


@pytest.fixture
def sample_nutrition() -> Nutrition:
    return Nutrition(kcal=250.0, protein_g=20.0, carbs_g=30.0, fat_g=5.0)


@pytest.fixture
def sample_ingredient(sample_nutrition: Nutrition) -> IngredientResult:
    return IngredientResult(
        name="chicken breast",
        estimated_grams=150.0,
        confidence=0.95,
        nutrition=sample_nutrition,
    )


@pytest.fixture
def sample_record(sample_ingredient: IngredientResult, sample_nutrition: Nutrition) -> AnalysisRecord:
    return AnalysisRecord(
        image_filename="test_meal.jpg",
        status=AnalysisStatus.OK,
        ingredients=[sample_ingredient],
        totals=sample_nutrition,
        warnings=[],
    )


def test_build_parser_arguments() -> None:
    parser = build_parser()
    args = parser.parse_args(["analyze", "meal.jpg", "--offline", "--no-save"])

    assert args.command == "analyze"
    assert args.image_path == "meal.jpg"
    assert args.offline is True
    assert args.no_save is True


def test_print_table_output(capsys: pytest.CaptureFixture[str], sample_ingredient: IngredientResult, sample_nutrition: Nutrition) -> None:
    _print_table([sample_ingredient], sample_nutrition)
    captured = capsys.readouterr()

    assert "ingredient" in captured.out
    assert "chicken breast" in captured.out
    assert "TOTAL" in captured.out


def test_run_analyze_file_not_found(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("os.path.isfile", return_value=False):
        exit_code = main(["analyze", "non_existent.jpg"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "error: file not found" in captured.err


def test_run_analyze_success_no_save(capsys: pytest.CaptureFixture[str], sample_record: AnalysisRecord) -> None:
    mock_analyze = AsyncMock(return_value=sample_record)
    with (
        patch("os.path.isfile", return_value=True),
        patch.dict("sys.modules", {"src.core.analyzer": MagicMock(analyze_meal=mock_analyze)}),
    ):
        exit_code = main(["analyze", "meal.jpg", "--no-save"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Analyzing: meal.jpg" in captured.out
    assert "chicken breast" in captured.out


def test_run_analyze_unknown_meal(capsys: pytest.CaptureFixture[str]) -> None:
    unknown_record = AnalysisRecord(
        image_filename="unknown.jpg",
        status=AnalysisStatus.UNKNOWN_MEAL,
        ingredients=[],
        totals=Nutrition(kcal=0, protein_g=0, carbs_g=0, fat_g=0),
        warnings=["Cannot identify food"],
    )

    mock_analyze = AsyncMock(return_value=unknown_record)
    with (
        patch("os.path.isfile", return_value=True),
        patch.dict("sys.modules", {"src.core.analyzer": MagicMock(analyze_meal=mock_analyze)}),
    ):
        exit_code = main(["analyze", "unknown.jpg"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No meal recognized in this image." in captured.out
    assert "- Cannot identify food" in captured.out


def test_run_analyze_db_save_success(capsys: pytest.CaptureFixture[str], sample_record: AnalysisRecord) -> None:
    mock_repo = AsyncMock()
    mock_repo.save_analysis.return_value = "12345"
    mock_analyze = AsyncMock(return_value=sample_record)

    with (
        patch("os.path.isfile", return_value=True),
        patch.dict("sys.modules", {"src.core.analyzer": MagicMock(analyze_meal=mock_analyze)}),
        patch("src.cli.AnalysisRepository.create", AsyncMock(return_value=mock_repo)),
    ):
        exit_code = main(["analyze", "meal.jpg"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Saved as analysis #12345" in captured.out
    mock_repo.close.assert_awaited_once()