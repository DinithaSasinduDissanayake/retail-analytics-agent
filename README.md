# AI-Native Retail Analytics Agent & In-Process OLAP Engine

A full-stack, in-process retail analytics warehouse and guided conversational agent powered by **DuckDB**, **FastAPI (SSE)**, **PydanticAI**, **React + assistant-ui**, and **NetworkX (Louvain Community Detection)**.

> **Public Demo Scope:** This public repository is the sanitized agent & DuckDB OLAP demo harness (using a deterministic synthetic seeder) derived from an 8-year, 263,000+-docket (487,000+ line items) private retail POS DuckDB warehouse consolidation.
>
> See [docs/architecture.md](docs/architecture.md) for the design rationale and security model.

## Architecture

- **Streaming Tool-Calling Agent (`backend/src/agent/orchestrator.py`):** Streams `PydanticAI` `run_stream` progress and text deltas over SSE using schema-grounded SQL/Python tools, bounded by explicit request (50), tool-call (100), and wall-clock (300s) usage limits.
- **In-Process Dual-DB OLAP (`backend/src/db/`):**
  - `warehouse.db` opened strictly with `read_only=True` at the DuckDB driver level (physically immutable by agent SQL).
  - `auxiliary.db` (read-write) for structured analysis logs and auxiliary metadata.
  - Full-reload `.mdb` → DuckDB ETL pipeline (`etl.py`) with schema-drift hashing.
- **FastAPI + SSE Backend (`backend/src/api/server.py`):** Streams live agent progress, data tables, and interactive user questions over Server-Sent Events (`/api/agent/run`, `/api/agent/respond`, `/api/dashboard/query`, `/api/sync`, `/api/health`).
- **Dual-View React Frontend (`frontend/`):** React 19 + Vite + TypeScript + Tailwind v4 + shadcn/ui + `@assistant-ui/react`:
  - **Chat Tab:** Conversational analytics with streaming progress, tool-call inspection, and inline markdown tables.
  - **Dashboard Tab:** Zero-LLM, offline-capable direct DuckDB SQL runner and data sync controls.
- **Market Basket Graph Mining (`backend/src/analytics/graph_mining.py`):** NetworkX Louvain modularity clustering to surface co-purchase trade communities for shelf-zoning.

## Quickstart

### 1. Backend Setup & Synthetic Demo Database
No real business data is stored in this repository. Generate a deterministic synthetic retail warehouse first:

```bash
# Install backend dependencies
cd backend
uv sync --extra dev   # or: pip install -e ".[dev]"
cd ..

# Seed synthetic demo data (Stock, Departments, Docket, DocketLine)
uv run --project backend python scripts/seed_demo.py --output data/demo_warehouse.db
export WAREHOUSE_DB_PATH="$(pwd)/data/demo_warehouse.db"

# Configure your OpenAI-compatible LLM provider
export LLM_API_KEY="your-api-key"
export LLM_MODEL="gpt-4o-mini"
export LLM_BASE_URL="https://api.openai.com/v1"

# Start the FastAPI server
cd backend
uvicorn src.api.server:app --reload --port 8000
```

### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

### 3. Tests & Graph Mining

```bash
# Backend unit & integration tests
cd backend && pytest

# Co-purchase Louvain community detection
WAREHOUSE_DB_PATH="$(pwd)/data/demo_warehouse.db" PYTHONPATH=backend uv run --project backend python -m src.analytics.graph_mining
```
