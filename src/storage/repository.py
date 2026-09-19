from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

import asyncpg

from src.models import AnalysisRecord

logger = logging.getLogger(__name__)


def _normalize_dsn(dsn: str) -> str:
    """asyncpg connects with a plain postgresql:// DSN; it doesn't understand
    SQLAlchemy-style '+driver' suffixes like postgresql+asyncpg://."""
    return dsn.replace("+asyncpg", "")


class AnalysisRepository:
    """Async PostgreSQL repository for analysis history."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def create(cls, dsn: str, *, min_size: int = 1, max_size: int = 10) -> "AnalysisRepository":
        """Open a connection pool and return a repository wrapping it.

        dsn example: postgresql://user:pass@host:5432/foodanalyzer
        """
        pool = await asyncpg.create_pool(dsn=_normalize_dsn(dsn), min_size=min_size, max_size=max_size)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def save_analysis(self, record: AnalysisRecord) -> uuid.UUID:
        """Insert an AnalysisRecord into the database."""
        data = record.model_dump(mode="json")
        query = """
            INSERT INTO analyses (id, created_at, image_filename, status, ingredients, totals, warnings)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb);
        """
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    query,
                    record.id,
                    record.created_at,
                    record.image_filename,
                    record.status.value,
                    json.dumps(data["ingredients"]),
                    json.dumps(data["totals"]),
                    json.dumps(data["warnings"]),
                )
        except Exception:
            logger.exception("Failed to save analysis id=%s image=%s", record.id, record.image_filename)
            raise

        logger.info("Saved analysis id=%s image=%s status=%s", record.id, record.image_filename, record.status)
        return record.id

    async def get_by_id(self, analysis_id: uuid.UUID) -> Optional[AnalysisRecord]:
        query = "SELECT * FROM analyses WHERE id = $1;"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, analysis_id)
        if row is None:
            return None
        return self._row_to_record(row)

    async def list_recent(self, limit: int = 20) -> list[AnalysisRecord]:
        query = "SELECT * FROM analyses ORDER BY created_at DESC LIMIT $1;"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, limit)
        return [self._row_to_record(r) for r in rows]

    @staticmethod
    def _row_to_record(row: Any) -> AnalysisRecord:
        def _maybe_load(value: Any) -> Any:
            return json.loads(value) if isinstance(value, str) else value

        return AnalysisRecord(
            id=row["id"],
            created_at=row["created_at"],
            image_filename=row["image_filename"],
            status=row["status"],
            ingredients=_maybe_load(row["ingredients"]),
            totals=_maybe_load(row["totals"]),
            warnings=_maybe_load(row["warnings"]),
        )