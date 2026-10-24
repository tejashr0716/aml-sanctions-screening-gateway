# Setup & Operations Guide: AML Sanctions Screening Gateway

## Prerequisites
- Python 3.12+ (tested on Python 3.14)
- Internet connectivity to fetch United Nations Consolidated Sanctions (`https://scsanctions.un.org`)

## Installation
```bash
git clone https://github.com/tejashr0716/aml-sanctions-screening-gateway.git
cd aml-sanctions-screening-gateway

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Configuration (.env)
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Settings available:
- `SANCTIONS_FEED_URL`: Live UN XML endpoint (`https://scsanctions.un.org/resources/xml/en/consolidated.xml`)
- `FUZZY_MATCH_THRESHOLD`: Default threshold for Tier 3 matching (`0.85`)
- `DATABASE_URL`: SQLite connection URI (`sqlite+aiosqlite:///data/sanctions.db`)
- `DB_PATH`: Local database path (`data/sanctions.db`)

## Running the API Gateway
```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

## Running Automated Tests
```bash
pytest -v --junitxml=artifacts/test-results.xml
```

## Running the Benchmark Harness
```bash
python benchmarks/benchmark_screening.py
```
Outputs empirical performance data to `artifacts/benchmark-results.json`.
