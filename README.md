# AI Food Analyzer

Upload a photo of a meal and get back its ingredients, estimated portion sizes, total calories, and a protein, carbs and fat breakdown.

A vision-language model identifies the ingredients and estimates how many grams of each are on the plate. We run it with OpenAI's `gpt-4o-mini`; Anthropic and Gemini are supported too. USDA FoodData Central supplies nutrition facts per 100 g, which are scaled to each portion and summed. Food Analyzer runs as a web app, a REST API and a command-line tool, and it keeps a history of analyses in PostgreSQL.

This is the final project for **Topic 2: AI Food Analyzer** ([TOPIC.md](TOPIC.md)). The AI module in `ai/`, the sample images and the smoke tests came with the brief and are unchanged. This repository builds the software-engineering layer around them: storage, HTTP API, CLI, concurrency, retries, caching, validation, logging, tests, Docker and a web UI.

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Quick start with Docker](#quick-start-with-docker)
- [Local development](#local-development)
- [Configuration](#configuration)
- [Usage](#usage): [web UI](#web-ui), [HTTP API](#http-api), [CLI](#cli)
- [Database](#database)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Requirements checklist](#requirements-checklist)
- [Design notes](#design-notes)
- [Known limitations](#known-limitations)
- [Credits](#credits)

## Features

- **Three ways in:** a web UI at `/`, a REST API with Swagger docs at `/docs`, and a CLI (`python -m foodanalyzer analyze <image>`).
- **Parallel nutrition lookups:** one `asyncio.gather` task per ingredient, with at most 10 USDA calls running at once.
- **Caching:** nutrition facts are cached in memory for 24 hours, so repeated ingredients skip the network.
- **Retries:** the VLM call is retried with exponential backoff after rate limits, 5xx errors, timeouts and connection errors.
- **Validation:** only real JPEG or PNG files up to 5 MB are accepted. The content type, size, format, file extension and a full decode are all checked.
- **Graceful failure:** a photo without food returns `unknown_meal`, failed lookups return a `partial` result, and the API keeps working without a database.
- **History:** every analysis made through the API is stored in PostgreSQL and listed by `GET /analyses`.
- **Offline mode:** `--offline` runs the whole pipeline with fake providers, with no API keys and no network.
- **Tested and containerized:** 245 offline tests with 65% coverage of `src/`, and a Docker Compose stack with the app and PostgreSQL 16.

## How it works

```mermaid
flowchart TB
    client["Web UI, curl or CLI"] --> entry["FastAPI app or CLI"]
    entry --> analyzer["Analyzer"]
    analyzer -->|"1. identify ingredients"| vlm["VLM<br/>OpenAI, Anthropic or Gemini"]
    analyzer -->|"2. look up in parallel"| cache["TTL cache"]
    cache -->|"miss"| usda["USDA FoodData Central"]
    analyzer -->|"3. scale and sum"| totals["Totals and status"]
    entry -->|"4. save"| db[("PostgreSQL")]
```

1. **Validate.** The API checks the upload's content type and size. Then `validate_image` uses Pillow to confirm the file really is a JPEG or PNG, that its extension matches, and that it decodes.
2. **Identify.** `AIService` calls `ai.identify_ingredients` in a worker thread and retries transient errors with exponential backoff. If the photo shows no meal, it returns an empty list.
3. **Look up.** `fetch_all_nutrition` starts one task per ingredient. Each task checks the cache first and, on a miss, calls USDA in a thread pool.
4. **Compute.** Each ingredient's per-100 g facts are scaled to its weight, `ai.compute_totals` sums them, and the result is marked `ok`, `partial` or `unknown_meal`.
5. **Save and respond.** The `AnalysisRecord` is saved to PostgreSQL and returned as JSON. A failed save is logged and doesn't fail the request.

**[FLOW_DIAGRAM.md](FLOW_DIAGRAM.md)** has detailed diagrams of every flow: startup, the request sequence, retries, caching, the CLI, the web UI, the data model and deployment.

## Quick start with Docker

**You need** Docker with Compose v2, an OpenAI API key (or an Anthropic or Gemini key, see [Configuration](#configuration)), and a free [USDA FoodData Central key](https://fdc.nal.usda.gov/api-key-signup).

1. Clone the repository and create your `.env`:

   ```bash
   git clone https://github.com/EmbeddedDesignEngineer/Food-Analyzer.git
   cd Food-Analyzer
   cp .env.example .env        # PowerShell: Copy-Item .env.example .env
   ```

2. Edit these lines in `.env`:

   ```dotenv
   LLM_PROVIDER=openai
   LLM_MODEL=gpt-4o-mini
   OPENAI_API_KEY=sk-...
   USDA_API_KEY=your-usda-key
   ```

   > **Important:** the Docker image installs only the `openai` SDK. `.env.example` starts with `LLM_PROVIDER=anthropic`, so either switch to `openai` as shown or add `anthropic` or `google-genai` to `requirements.txt` and rebuild.

3. Build and start the stack:

   ```bash
   docker compose up -d --build
   ```

4. Open **http://localhost:8000** for the web UI, or **http://localhost:8000/docs** for Swagger. Check that everything is connected:

   ```bash
   curl http://localhost:8000/health
   # {"status":"ok","analyzer":"ready","database":"postgresql"}
   ```

| Service | Address |
|---|---|
| Web UI and API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| PostgreSQL | `localhost:5433`, user `postgres`, password `postgres`, database `foodanalyzer` |

```bash
docker compose logs -f app     # follow the app logs
docker compose down            # stop the stack and keep the data
docker compose down -v         # stop the stack and delete the data (the schema is recreated on the next start)
```

## Local development

You need Python 3.12 or newer. The Docker image uses 3.12, and the tests also pass on 3.14.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env               # then fill in the keys as shown above
```

**Database (optional).** The easiest option is to start only the Compose database, which creates the schema for you:

```bash
docker compose up -d db
```

Then point `.env` at it. From the host, it listens on port 5433:

```dotenv
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/foodanalyzer
```

To use your own PostgreSQL server instead, create a `foodanalyzer` database, run `psql -d foodanalyzer -f src/storage/schema.sql`, and set `DATABASE_URL` to match.

**Run the API:**

```bash
uvicorn src.api:app --reload       # http://localhost:8000
```

Without a database the API still analyzes photos. It just doesn't save them, `GET /analyses` returns 503, and `/health` reports `degraded`.

**Try it offline.** No API keys or network are needed. The fake providers read the ingredients from the sample file names, so use the images in `data/`:

```bash
python -m foodanalyzer analyze data/rice_chicken_broccoli.png --offline --no-save
python demo_ai.py --offline --image data/rice_chicken_broccoli.png
```

## Configuration

Settings come from environment variables or `.env`. `src/config.py` loads `.env` with python-dotenv. Variables that are already set in the environment take precedence.

**AI providers**, read by `ai/`:

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | VLM provider: `openai`, `anthropic` or `gemini`. We use `openai`. |
| `LLM_MODEL` | Provider's default | Model id. The defaults are `gpt-4o-mini`, `claude-sonnet-4-6` and `gemini-2.0-flash`. |
| `OPENAI_API_KEY` | | OpenAI key. For the other providers, set `ANTHROPIC_API_KEY` or `GOOGLE_API_KEY` instead. `LLM_API_KEY` works as a fallback for any of them. |
| `OPENAI_BASE_URL` | OpenAI's API | Optional OpenAI-compatible endpoint, read by the `openai` SDK. |
| `NUTRITION_PROVIDER` | `usda` | Only `usda` is included. |
| `USDA_API_KEY` | | Free key from [fdc.nal.usda.gov](https://fdc.nal.usda.gov/api-key-signup). |

**Application**, read by `src/config.py`:

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Log level for the API and CLI. |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/foodanalyzer` | PostgreSQL connection string. The `+asyncpg` part is optional and is removed before connecting. |
| `MAX_IMAGE_SIZE_MB` | `5` | Upload size limit. |
| `NUTRITION_CACHE_TTL_SECONDS` | `86400` | How long cached nutrition facts stay valid. |
| `MAX_RETRIES` | `3` | Total attempts for the VLM call. |
| `RETRY_BACKOFF_SECONDS` | `0.5` | Delay before the first retry. It doubles on each retry, up to 8 s. |

The last four settings apply to the API only. The CLI uses fixed values: a 5 MB limit, a 24-hour cache, and 3 attempts with a 1 s first delay.

**Docker Compose**, read from your shell or `.env`:

| Variable | Default | Description |
|---|---|---|
| `HTTP_PORT` | `8000` | Host port for the app. |
| `POSTGRES_HOST_PORT` | `5433` | Host port for PostgreSQL. It isn't 5432, to avoid clashing with a local PostgreSQL install. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `postgres`, `postgres`, `foodanalyzer` | Database credentials. |

Inside Compose, `DATABASE_URL` is overridden to point at the `db` container.

## Usage

### Web UI

Open http://localhost:8000.

- **Status pills** at the top show whether the analyzer and the history database are available.
- **Add a photo** by browsing for it, dragging it anywhere onto the page, or pasting it. JPEG and PNG photos up to 4 MB and 2048 px are sent unchanged. Other formats and larger photos are converted to JPEG in the browser first.
- **Results** show total calories, protein, carbs and fat with each macro's share of the calories, a macro split bar, a table of ingredients with the model's confidence, any warnings, and the raw JSON.
- **Recent analyses** lists the last 20. Click one to view it again.

The page is served with a strict Content-Security-Policy. Text from the model and from file names is always inserted as plain text, never as HTML.

### HTTP API

| Method | Path | Description |
|---|---|---|
| `POST` | `/analyze` | Analyze a meal photo sent as a multipart form with a `file` field (JPEG or PNG). Returns an `AnalysisRecord`. |
| `GET` | `/analyses?limit=20` | Saved analyses, newest first. `limit` is 1 to 100 and defaults to 20. |
| `GET` | `/health` | `ok` when both the analyzer and the database are available, `degraded` otherwise. |
| `GET` | `/docs` | Swagger UI. |
| `GET` | `/` | Web UI. |

**curl examples.** In Windows PowerShell, type `curl.exe` instead of `curl`, because `curl` is an alias for `Invoke-WebRequest` there.

```bash
# Health check
curl http://localhost:8000/health

# Analyze a photo
curl -F "file=@data/rice_chicken_broccoli.png;type=image/png" http://localhost:8000/analyze
curl -F "file=@path/to/meal.jpg;type=image/jpeg" http://localhost:8000/analyze

# Include the status code in the output
curl -i -F "file=@data/rice_chicken_broccoli.png;type=image/png" http://localhost:8000/analyze

# Recent history
curl "http://localhost:8000/analyses?limit=5"

# Error paths
curl -F "file=@data/no_meal_blue.png;type=image/png" http://localhost:8000/analyze   # 200, unknown_meal
curl -i -F "file=@TOPIC.md;type=text/plain" http://localhost:8000/analyze            # 400, not an image type
curl -i -F "file=@TOPIC.md;type=image/png" http://localhost:8000/analyze             # 400, claims PNG but isn't
curl -i -X POST http://localhost:8000/analyze                                        # 422, no file
```

[COMMANDS.md](COMMANDS.md) has more ready-to-paste commands.

**Example response.** This one was produced with the offline fakes. With a real VLM, the names, weights and confidence scores come from the model.

```json
{
  "id": "9cbd100a-1149-4f84-b862-8884e506578b",
  "created_at": "2026-09-19T17:31:30.801656Z",
  "image_filename": "rice_chicken_broccoli.png",
  "status": "ok",
  "ingredients": [
    {
      "name": "white rice (cooked)", "estimated_grams": 180.0, "confidence": 0.85,
      "nutrition": {"kcal": 234.0, "protein_g": 4.86, "carbs_g": 50.4, "fat_g": 0.54}
    },
    {
      "name": "grilled chicken breast", "estimated_grams": 150.0, "confidence": 0.85,
      "nutrition": {"kcal": 247.5, "protein_g": 46.5, "carbs_g": 0.0, "fat_g": 5.4}
    },
    {
      "name": "broccoli", "estimated_grams": 80.0, "confidence": 0.85,
      "nutrition": {"kcal": 27.200000000000003, "protein_g": 2.2399999999999998, "carbs_g": 5.6000000000000005, "fat_g": 0.32000000000000006}
    }
  ],
  "totals": {"kcal": 508.7, "protein_g": 53.6, "carbs_g": 56.0, "fat_g": 6.260000000000001},
  "warnings": []
}
```

| Field | Description |
|---|---|
| `id`, `created_at` | UUID and UTC timestamp of the analysis. |
| `image_filename` | Name of the uploaded file. |
| `status` | `ok`, `partial` (some nutrition lookups failed) or `unknown_meal`. |
| `ingredients[]` | `name`, `estimated_grams`, `confidence` (0 to 1), and `nutrition` for that portion, which is `null` if its lookup failed. |
| `totals` | `kcal`, `protein_g`, `carbs_g` and `fat_g`, summed over the ingredients that have nutrition data. |
| `warnings` | Readable descriptions of anything that went wrong: one per failed lookup, or the identification error. |

Numbers are returned unrounded. The CLI and web UI round them for display.

**Errors and edge cases:**

| Situation | Status | Response |
|---|---|---|
| No food in the photo | 200 | `"status": "unknown_meal"` with the warning `no meal recognized in image` |
| The VLM failed, even after retries, or its key or SDK is missing | 200 | `"status": "unknown_meal"` with the warning `ingredient identification failed: ...` |
| Some nutrition lookups failed, for example during a USDA outage | 200 | `"status": "partial"`. Those ingredients have `"nutrition": null` and one warning each. |
| Content type isn't JPEG or PNG | 400 | `{"error": "invalid_image", "detail": "Unsupported content type 'text/plain'; use JPEG or PNG"}` |
| Not a real image, extension doesn't match, or corrupt | 400 | `{"error": "invalid_image", "detail": "Image TOPIC.md cannot be verified or decoded: ..."}` |
| Empty file, or over the size limit | 400 | `Uploaded file is empty`, or `Image exceeds the 5.0 MB limit` |
| No `file` field | 422 | FastAPI's validation error |
| Analyzer not configured, for example `USDA_API_KEY` is missing | 503 | `{"error": "service_unavailable", "detail": "Analyzer is not configured; check the server's API keys"}` |
| `GET /analyses` without a database | 503 | `History is unavailable: the server has no database connection` |

> **Note:** the VLM client is created on each request, not at startup. A missing or invalid LLM key therefore doesn't show in `/health`. It shows up as an `unknown_meal` result with an `ingredient identification failed` warning, and the web UI shows an "Ingredients couldn't be identified" banner for it.

### CLI

```text
python -m foodanalyzer analyze <image_path> [--offline] [--no-save]
```

| Option | Effect |
|---|---|
| `--offline` | Use the fake VLM and nutrition data from `demo_ai.py`. No keys or network are needed, but it only recognizes the sample images in `data/`. |
| `--no-save` | Don't save the result to PostgreSQL. |

```text
$ python -m foodanalyzer analyze data/rice_chicken_broccoli.png --offline --no-save
Analyzing: rice_chicken_broccoli.png  (status=ok)

ingredient              g    kcal  protein  carbs  fat
------------------------------------------------------
white rice (cooked)     180  234   4.9      50.4   0.5
grilled chicken breast  150  248   46.5     0.0    5.4
broccoli                80   27    2.2      5.6    0.3
------------------------------------------------------
TOTAL                   410  509   53.6     56.0   6.3

$ python -m foodanalyzer analyze data/no_meal_blue.png --offline --no-save
No meal recognized in this image.
  - no meal recognized in image
```

- Log messages go to stderr, at the level set by `LOG_LEVEL`.
- An ingredient whose nutrition lookup failed shows `?` in each nutrition column, and the warnings are listed under the table.
- Without `--no-save`, a recognized meal is saved to `DATABASE_URL` and the CLI prints `Saved as analysis #<uuid>`. If the database can't be reached, it prints a warning and the result is still shown. When you use the Compose database from the host, remember it's on port 5433.

## Database

There is one table, created by `src/storage/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS analyses (
    id              UUID PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL,
    image_filename  TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('ok', 'partial', 'unknown_meal')),
    ingredients     JSONB NOT NULL,
    totals          JSONB NOT NULL,
    warnings        JSONB NOT NULL DEFAULT '[]'
);
-- Plus indexes on created_at DESC and on status.
```

Compose runs this file automatically, but only when the `pgdata` volume is first created. To open a SQL shell:

```bash
docker compose exec db psql -U postgres -d foodanalyzer
```

```sql
-- One line per analysis, newest first
SELECT created_at, image_filename, status,
       round((totals->>'kcal')::numeric) AS kcal,
       jsonb_array_length(ingredients)   AS n_ingredients
FROM analyses
ORDER BY created_at DESC;
```

[COMMANDS.md](COMMANDS.md) has more queries: one row per ingredient, the most common ingredients, failed lookups, averages and clean-up.

## Testing

```bash
pytest                                        # 244 passed, 1 skipped on Windows
pip install pytest-cov                        # coverage plugin, not in requirements.txt
pytest --cov=src --cov-report=term-missing    # 65% coverage of src/
```

All 245 tests run offline, using fake VLMs, fake nutrition providers and a fake connection pool, so no API keys, network or database are needed. `pytest.ini` sets `pythonpath = .` and `asyncio_mode = auto`. On Windows, one test is skipped because it needs `os.mkfifo`.

| Test file | What it covers |
|---|---|
| `test_ai_smoke.py` (from the brief) | The AI layer's contract: VLM response parsing, schema validation, scaling and totals. |
| `test_ai_service.py` | Which errors are retried, the backoff cap, configuration errors, validating once per call, and logs that contain no secrets. |
| `test_image_validation.py` | Formats, extensions, the size limit, truncated and corrupt files, and filesystem errors. |
| `test_nutrition_cache.py` | Key normalization, TTL boundaries, expiry, input validation and safe logging. |
| `test_pipeline.py` | Parallel lookups, collecting failures, and cache use. |
| `test_analyzer.py` | The `ok`, `partial` and `unknown_meal` outcomes. |
| `test_repository.py` | Connection string handling, insert payloads, mapping rows back to records, and database errors. |
| `test_api.py` | Serving the web UI and static files with the right headers, and `/analyses` limits and 503 responses. |

**Concurrency benchmark.** `python -m src.concurrency.pipeline` compares sequential and parallel lookups. It uses 7 ingredients and a fake provider that takes 2 s per call and fails for one of them:

| Mode | Time |
|---|---|
| Sequential (`fetch_sequential`) | 14.0 s |
| Parallel (`fetch_all_nutrition`) | 4.0 s |

The parallel run takes 4 s rather than 2 s because the failing lookup is retried once. The script's output labels are in Azerbaijani: *Ardıcıl vaxt* is the sequential time and *Paralel vaxt* the parallel time.

## Project structure

```text
Food-Analyzer/
├── ai/                          # AI module from the brief (unchanged)
│   ├── vlm.py                   #   identify_ingredients: prompt → VLM → validated ingredients
│   ├── nutrition.py             #   NutritionProvider interface and USDAProvider
│   ├── calculator.py            #   compute_totals
│   ├── schemas.py               #   Ingredient, NutritionFacts, Nutrition
│   └── providers/               #   OpenAI, Anthropic and Gemini adapters, get_vlm factory
├── src/
│   ├── api.py                   # FastAPI app: /analyze, /analyses, /health and the web UI
│   ├── cli.py                   # CLI with the analyze command
│   ├── config.py                # Settings from the environment and .env
│   ├── models.py                # AnalysisRecord, IngredientResult, AnalysisStatus
│   ├── core/analyzer.py         # Orchestration: identify → look up → total → status
│   ├── services/
│   │   ├── ai_service.py        # Validation and retries around ai.identify_ingredients
│   │   ├── image_validation.py  # JPEG/PNG, size and integrity checks
│   │   └── nutrition_cache.py   # In-memory TTL cache
│   ├── concurrency/pipeline.py  # Parallel nutrition lookups
│   ├── storage/
│   │   ├── repository.py        # PostgreSQL repository (asyncpg)
│   │   └── schema.sql           # The analyses table
│   └── web/                     # Web UI: index.html and static/ (app.js, styles.css, favicon.svg)
├── foodanalyzer/                # Makes `python -m foodanalyzer` run src/cli.py
├── tests/                       # pytest suite, fully offline
├── data/                        # 16 synthetic sample images, a real photo in real/, _make_samples.py
├── demo_ai.py                   # Demo from the brief; its offline fakes power --offline
├── Dockerfile                   # python:3.12-slim, non-root user, uvicorn
├── docker-compose.yml           # App and PostgreSQL 16
├── requirements.txt             # All dependencies, including test tools
├── requirements-ai.txt          # Dependencies of ai/ only (from the brief)
├── pytest.ini
├── .env.example                 # Configuration template
├── COMMANDS.md                  # Ready-to-paste curl, CLI and SQL commands
├── FLOW_DIAGRAM.md              # Architecture and flow diagrams
└── TOPIC.md                     # Project brief
```

## Requirements checklist

How each requirement in [TOPIC.md](TOPIC.md) is met:

| Requirement | Where and how |
|---|---|
| `config.py` | `src/config.py`: typed `Settings` with pydantic-settings, cached by `get_settings()`, with `.env` support. |
| Storage | `src/storage/repository.py` and `schema.sql`: an asyncpg pool. Each analysis stores its timestamp, image name, status, ingredients, totals and warnings. |
| HTTP API | `src/api.py`: FastAPI `POST /analyze` takes a multipart image and returns an `AnalysisRecord` as JSON. There are also `/analyses`, `/health` and the web UI. |
| CLI | `python -m foodanalyzer analyze <path>` prints the totals table (`src/cli.py`). |
| Concurrency | `src/concurrency/pipeline.py`: `asyncio.gather` with one task per ingredient, limited by `Semaphore(10)`. |
| Caching | `src/services/nutrition_cache.py`: a TTL cache, 24 hours by default, checked before every lookup. |
| Retries | `src/services/ai_service.py`: exponential backoff with tenacity on the VLM call. Nutrition lookups are retried once (see [Known limitations](#known-limitations)). |
| Validation | `src/api.py` checks the content type, empty files and the size. `src/services/image_validation.py` checks the format, extension and decoding. FastAPI rejects a missing `file` field. |
| Robustness | `src/core/analyzer.py` returns `unknown_meal` and `partial` results instead of failing. The API answers 503 when the analyzer or database is unavailable. |
| Logging | The `logging` module in the API, CLI, services and repository, at the level set by `LOG_LEVEL`. |
| Tests | 245 offline tests with 65% coverage of `src/`. |
| Dockerfile | `Dockerfile` and `docker-compose.yml`, with the app and PostgreSQL. |
| README | This file, plus [FLOW_DIAGRAM.md](FLOW_DIAGRAM.md) and [COMMANDS.md](COMMANDS.md). |

## Design notes

- **Layers.** The entry points (`api.py`, `cli.py`) call the `Analyzer`, which calls the services and the pipeline, which call `ai/`. As the brief requires, business logic reaches the AI layer only through `ai.identify_ingredients`, `ai.compute_totals` and the `NutritionProvider` interface.
- **Non-blocking.** The provider SDKs and the USDA client are synchronous, so they run in the default thread pool through `run_in_executor`. The event loop keeps serving other requests during a slow VLM call.
- **Selective retries.** `AIService` follows the exception's cause chain to find an HTTP status or a timeout or connection error. Only 429, 5xx, timeouts and connection errors are retried. Invalid JSON, schema errors, other 4xx errors and configuration errors fail immediately. Retry logs record the attempt, delay, error category and status, never the model's output or the error text.
- **Shared rate limit.** The semaphore is module-level, so the limit of 10 concurrent USDA calls covers every request in the process. That protects the USDA free tier of 1,000 requests per hour.
- **Cache behavior.** Keys are normalized with `strip().casefold()`. Entries expire after the TTL, measured with a monotonic clock, and reading an entry doesn't extend it. The API keeps one cache for its whole lifetime.
- **Upload safety.** Only the file's base name is kept, which prevents path traversal. The handler reads at most the size limit plus one byte, stages the upload in a temporary directory that is deleted afterwards, and removes the temporary path from error messages.
- **Best-effort history.** A failed save is logged, and the user still gets their result. Without a database, only the history features are disabled. Database error details never reach the client.
- **Container.** The image runs as a non-root user. `.env` is excluded by `.dockerignore`, and secrets are passed in at runtime through `env_file`.

## Known limitations

- USDA lookups are retried once, immediately. Only the VLM call uses exponential backoff.
- `Settings` defines `NUTRITION_CONCURRENCY_LIMIT`, but `pipeline.py` uses a fixed `Semaphore(10)` instead.
- The CLI ignores `MAX_IMAGE_SIZE_MB`, `NUTRITION_CACHE_TTL_SECONDS` and the retry settings, and it starts each run with an empty cache.
- The cache lives in process memory. It's lost on restart and isn't shared between processes.
- If two requests look up the same uncached ingredient at the same moment, both call USDA.
- The USDA search uses the top match for each ingredient name, which may not be the best match.
- Portion sizes and nutrition values are estimates, so treat the results as approximate.

## Credits

- The `ai/` module, `demo_ai.py`, the sample images in `data/`, `tests/test_ai_smoke.py` and `tests/conftest.py` came with the project brief and are unchanged.
- Nutrition data comes from [USDA FoodData Central](https://fdc.nal.usda.gov/).
