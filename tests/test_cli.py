from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from src.config import get_settings
from src.models import AnalysisRecord, AnalysisStatus, IngredientResult, Nutrition
from src.storage.repository import AnalysisRepository

logger = logging.getLogger(__name__)


def _print_table(ingredients: list[IngredientResult], totals: Nutrition) -> None:
    headers = ["ingredient", "g", "kcal", "protein", "carbs", "fat"]
    rows: list[list[str]] = []
    for ing in ingredients:
        if ing.nutrition is None:
            rows.append([ing.name, f"{ing.estimated_grams:.0f}", "?", "?", "?", "?"])
        else:
            n = ing.nutrition
            rows.append([
                ing.name,
                f"{ing.estimated_grams:.0f}",
                f"{n.kcal:.0f}",
                f"{n.protein:.1f}",
                f"{n.carbs:.1f}",
                f"{n.fat:.1f}",
            ])
    total_row = [
        "TOTAL",
        f"{sum(i.estimated_grams for i in ingredients):.0f}",
        f"{totals.kcal:.0f}",
        f"{totals.protein:.1f}",
        f"{totals.carbs:.1f}",
        f"{totals.fat:.1f}",
    ]

    all_rows = rows + [total_row]
    widths = [max(len(headers[i]), *(len(r[i]) for r in all_rows)) for i in range(len(headers))]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    sep = "-" * len(line)

    print(line)
    print(sep)
    for r in rows:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))
    print(sep)
    print("  ".join(c.ljust(widths[i]) for i, c in enumerate(total_row)))


async def _run_analyze(args: argparse.Namespace) -> int:
    from src.core.analyzer import analyze_meal

    if not os.path.isfile(args.image_path):
        print(f"error: file not found: {args.image_path}", file=sys.stderr)
        return 2

    try:
        record: AnalysisRecord = await analyze_meal(args.image_path, offline=args.offline)
    except Exception as exc:
        logger.exception("analysis failed")
        print(f"error: analysis failed: {exc}", file=sys.stderr)
        return 1

    if record.status == AnalysisStatus.UNKNOWN_MEAL or not record.ingredients:
        print("No meal recognized in this image.")
        for w in record.warnings:
            print(f"  - {w}")
        return 0

    print(f"Analyzing: {os.path.basename(args.image_path)}  (status={record.status.value})\n")
    _print_table(record.ingredients, record.totals)

    if record.warnings:
        print("\nWarnings:")
        for w in record.warnings:
            print(f"  - {w}")

    if args.no_save:
        return 0

    settings = get_settings()
    try:
        repo = await AnalysisRepository.create(settings.database_url)
    except Exception as exc:
        logger.exception("could not connect to database")
        print(f"\nwarning: could not connect to database, skipping save: {exc}", file=sys.stderr)
        return 0

    try:
        analysis_id = await repo.save_analysis(record)
        print(f"\nSaved as analysis #{analysis_id}")
    except Exception as exc:
        logger.exception("failed to save analysis to history")
        print(f"\nwarning: could not save to history: {exc}", file=sys.stderr)
    finally:
        await repo.close()

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="foodanalyzer", description="AI Food Analyzer CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Analyze a meal image and print a totals table")
    analyze.add_argument("image_path", help="Path to a JPEG/PNG meal image")
    analyze.add_argument("--offline", action="store_true", help="Use offline/mock mode (no network calls)")
    analyze.add_argument("--no-save", action="store_true", help="Do not save the result to the database")
    analyze.set_defaults(func=_run_analyze)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=get_settings().log_level)
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())