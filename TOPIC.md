# Topic 2 — AI Food Analyzer

> **What you receive:** a working AI module (VLM ingredient ID + USDA nutrition adapter + totals calculator), sample meal images, an end-to-end demo, and smoke tests.
> **What you build:** the full software-engineering layer around it (storage, HTTP API, CLI, concurrency, retries, caching, logging, validation, tests, Docker, README, report).

---

## The problem

The user uploads a photo of a meal. The system identifies the ingredients with estimated portion sizes, retrieves nutritional data per ingredient, and returns total calories plus a macronutrient breakdown.

## What the AI does

1. **Ingredient identification** (`ai.identify_ingredients`) takes a meal photo, asks the chosen VLM to list each visible ingredient with an estimated weight in grams and a confidence score. Returns a `list[Ingredient]` (or empty list if no meal is recognized).
2. **Nutrition lookup** (`ai.NutritionProvider`, `ai.USDAProvider`) maps an ingredient name to a `NutritionFacts` (per 100g) by querying the USDA FoodData Central API. The `NutritionProvider` abstract base class lets students plug in alternative sources (Edamam, Nutritionix) without changing callers.
3. **Totals calculation** (`ai.compute_totals`) is a pure function: given a list of ingredients and a `dict[name -> NutritionFacts]`, it returns a single `Nutrition` row with kcal, protein, carbs, fat.

The VLM is provider-agnostic (Anthropic / OpenAI / Gemini), selected via env vars:

```bash
LLM_PROVIDER=anthropic         # or openai, gemini
LLM_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=...

NUTRITION_PROVIDER=usda
USDA_API_KEY=...               # free from api.data.gov
```

## What you build (the SE layer)

| Component | Required | Notes |
|---|---|---|
| `config.py` | yes | Read env, expose typed settings (`pydantic-settings` recommended). |
| Storage | yes | PostgreSQL (via `psycopg` or `asyncpg`) history log: timestamp, image path, ingredients, totals. |
| HTTP API | **yes** | `POST /analyze` accepting a multipart image upload, returning structured JSON. FastAPI or Flask. |
| CLI | yes | `python -m foodanalyzer analyze <path>` prints a totals table. |
| Concurrency | yes | When the VLM returns N ingredients, the N nutrition lookups run **in parallel** via `asyncio.gather` (or `concurrent.futures`). |
| Caching | yes | Nutrition lookups for the same ingredient string within a TTL (default 24h) must hit a local cache. |
| Retries | yes | Exponential backoff on every `ai.*` call and every USDA call. |
| Validation | yes | Reject non-JPEG/PNG, oversize files, missing fields. |
| Robustness | yes | Graceful "unknown meal" path when the VLM cannot identify the meal — return a structured response, not a crash. Handle USDA outages with a clear error path. |
| Logging | yes | `logging` module, env-driven level. |
| Tests | yes | ≥60% coverage, all offline. |
| Dockerfile | yes | Builds and runs end-to-end. |
| README | yes | Setup, env, run, test, curl examples. |

## How to run what we shipped

```bash
# (1) Install the AI-layer dependencies:
pip install numpy pydantic requests

# Optional, only needed if you actually call the providers:
pip install anthropic openai google-genai

# (2) Generate the sample meal images (one-time):
python data/_make_samples.py

# (3) Try the offline demo (no API keys required, no network):
python demo_ai.py --offline
python demo_ai.py --offline --image data/rice_chicken_broccoli.png
python demo_ai.py --offline --image data/no_meal_blue.png   # the "unknown meal" path

# (4) Run the smoke tests (offline, no network):
pytest tests/test_ai_smoke.py -v
```

Sample output of `python demo_ai.py --offline --image data/rice_chicken_broccoli.png`:

```
Analyzing: rice_chicken_broccoli.png  (mode=offline)

ingredient              g    kcal  protein  carbs  fat
------------------------------------------------------
white rice (cooked)     180  234   4.9      50.4   0.5
grilled chicken breast  150  248   46.5     0.0    5.4
broccoli                80   27    2.2      5.6    0.3
------------------------------------------------------
TOTAL                   410  509   53.6     56.0   6.3
```

## The contract (do not break)

- **Do not** edit any file under `ai/`. If you find a bug, file an issue with the instructor.
- **Do not** delete or weaken `tests/test_ai_smoke.py`. These tests are run during grading; they must pass on your final repo.
- **Do not** call provider SDKs or USDA directly from your business logic. Always go through `ai.identify_ingredients`, `ai.compute_totals`, and the `ai.NutritionProvider` interface.

## Recommended folder layout for your project

```
your-project/
├── ai/                        # COPIED FROM HERE, unchanged
├── src/
│   ├── config.py
│   ├── models.py              # YOUR pydantic models: AnalysisRecord, ...
│   ├── services/
│   │   ├── ai_service.py      # retries, caching, logging around ai.*
│   │   └── nutrition_cache.py # TTL-aware wrapper around NutritionProvider
│   ├── core/
│   │   └── analyzer.py        # business logic
│   ├── concurrency/
│   │   └── pipeline.py        # asyncio.gather for parallel nutrition lookups
│   ├── storage/
│   │   └── repository.py      # PostgreSQL history log
│   ├── cli.py
│   └── api.py                 # FastAPI / Flask
├── tests/                     # YOUR tests + the provided smoke tests
├── data/                      # COPIED FROM HERE
├── Dockerfile
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Sample data

`data/` contains 16 small synthetic PNGs whose filenames hint at the meal contents. They exist purely so the offline demo and smoke tests run end-to-end without API keys. **Replace with real meal photos for development.**

## Free-tier API options

| Provider | Free tier? | Notes |
|---|---|---|
| Anthropic Claude | Limited trial credit | Best for VLM quality on food photos. |
| OpenAI GPT-4o-mini | Pay-as-you-go (cheap) | Smallest cost per VLM call. |
| Google Gemini | Generous free tier | Both VLM and embeddings. |
| **USDA FoodData Central** | **Free, 1000 req/h/IP** | Sign up at https://fdc.nal.usda.gov/api-key-signup |

A single demo run on the 16 sample images is well under $0.05 on any of these.

## Tips for the SE layer

- **Cache aggressively.** Ingredient strings repeat across meals; the same query against USDA can hit your cache instead of the network. A simple in-memory dict with a TTL is enough; a PostgreSQL-backed cache is a nice upgrade.
- **Parallelise the nutrition lookups.** When the VLM returns 5 ingredients, you have 5 independent HTTP calls. `asyncio.gather` (with `aiohttp` or `httpx`) cuts wall-clock time roughly by 5×. Document the speedup in your report.
- **Bound parallelism with a semaphore.** The USDA free tier is 1000 req/h, but a burst of 50 simultaneous requests will still trigger throttling. Use `asyncio.Semaphore(10)`.
- **Treat the VLM's "meal_recognized = false" branch as a normal control flow case**, not an exception. The provided `identify_ingredients` already returns `[]` in that case.
