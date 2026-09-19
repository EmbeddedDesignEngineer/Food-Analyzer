from __future__ import annotations

import asyncio
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse

from ai import get_nutrition_provider
from ai.providers.base import ProviderError
from src.config import get_settings
from src.core.analyzer import Analyzer
from src.models import AnalysisRecord
from src.services.ai_service import AIService
from src.services.image_validation import (
    ImageTooLargeError,
    ImageValidationError,
    InvalidImageError,
    UnsupportedImageFormatError,
)
from src.services.nutrition_cache import NutritionCache
from src.storage.repository import AnalysisRepository

logger = logging.getLogger(__name__)

_DB_CONNECT_TIMEOUT_SECONDS = 10
_SUFFIX_BY_CONTENT_TYPE = {"image/jpeg": ".jpg", "image/png": ".png"}


class ServiceUnavailableError(Exception):
    """The analyzer could not be built at startup (e.g. missing API keys)."""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    # History is optional: analysis keeps working without a database.
    repo: AnalysisRepository | None = None
    try:
        repo = await asyncio.wait_for(
            AnalysisRepository.create(settings.database_url),
            timeout=_DB_CONNECT_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.exception("could not connect to database; analyses will not be saved")

    analyzer: Analyzer | None = None
    try:
        analyzer = Analyzer(
            AIService(
                max_size_bytes=int(settings.max_image_size_mb * 1024 * 1024),
                max_attempts=settings.max_retries,
                initial_wait_seconds=settings.retry_backoff_seconds,
            ),
            get_nutrition_provider(),
            NutritionCache(ttl_seconds=settings.nutrition_cache_ttl_seconds),
        )
    except ProviderError:
        logger.exception("nutrition provider could not be initialized; /analyze is disabled")

    app.state.repository = repo
    app.state.analyzer = analyzer
    try:
        yield
    finally:
        if repo is not None:
            await repo.close()


app = FastAPI(title="AI Food Analyzer", lifespan=lifespan)


@app.exception_handler(ImageValidationError)
async def _validation_error(request: Request, exc: ImageValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "invalid_image", "detail": str(exc)})


@app.exception_handler(ServiceUnavailableError)
async def _service_unavailable(request: Request, exc: ServiceUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"error": "service_unavailable", "detail": str(exc)})


def _upload_filename(file: UploadFile, settings) -> str:
    """Return a safe basename whose suffix matches the declared content type."""
    if file.content_type not in settings.allowed_content_types:
        raise UnsupportedImageFormatError(
            f"Unsupported content type {file.content_type!r}; use JPEG or PNG"
        )
    name = Path(file.filename or "").name or "upload"
    if not Path(name).suffix:
        name += _SUFFIX_BY_CONTENT_TYPE.get(file.content_type, "")
    return name


@app.post("/analyze", response_model=AnalysisRecord)
async def analyze(file: UploadFile = File(...)) -> AnalysisRecord:
    analyzer: Analyzer | None = app.state.analyzer
    if analyzer is None:
        raise ServiceUnavailableError("Analyzer is not configured; check the server's API keys")

    settings = get_settings()
    filename = _upload_filename(file, settings)

    max_bytes = int(settings.max_image_size_mb * 1024 * 1024)
    data = await file.read(max_bytes + 1)
    if not data:
        raise InvalidImageError("Uploaded file is empty")
    if len(data) > max_bytes:
        raise ImageTooLargeError(f"Image exceeds the {settings.max_image_size_mb} MB limit")

    # AIService validates and identifies from a path, so stage the upload on disk.
    # The original filename is kept so filename-keyed offline VLMs still work.
    with tempfile.TemporaryDirectory(prefix="foodanalyzer-") as tmp_dir:
        tmp_path = Path(tmp_dir) / filename
        tmp_path.write_bytes(data)
        try:
            record = await analyzer.analyze(str(tmp_path))
        except ImageValidationError as exc:
            # Don't leak the server's temp path to the client.
            detail = str(exc)
            for form in (str(tmp_path), repr(str(tmp_path))[1:-1]):
                detail = detail.replace(form, filename)
            raise type(exc)(detail) from exc

    record = record.model_copy(update={"image_filename": filename})

    repo: AnalysisRepository | None = app.state.repository
    if repo is not None:
        try:
            await repo.save_analysis(record)
        except Exception:
            logger.exception("failed to save analysis %s to history", record.id)

    return record


@app.get("/health")
async def health() -> dict:
    persistent = app.state.repository is not None
    ready = app.state.analyzer is not None
    return {
        "status": "ok" if persistent and ready else "degraded",
        "analyzer": "ready" if ready else "unavailable",
        "database": "postgresql" if persistent else "unavailable",
    }