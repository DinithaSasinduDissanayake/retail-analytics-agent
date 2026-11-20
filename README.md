# AI-Native Retail Analytics Agent & In-Process OLAP Engine

A full-stack, in-process retail analytics warehouse and guided conversational agent powered by **DuckDB**, **FastAPI (SSE)**, **PydanticAI**, **React + assistant-ui**, and **NetworkX (Louvain Community Detection)**.

> See [docs/architecture.md](docs/architecture.md) for the full design rationale, failure-mode analysis, and security model.

## Architecture

- **PEV Orchestrator (`backend/src/agent/orchestrator.py`):** Pure-code query classifier routes simple lookups to a fast single-SQL path and complex diagnostic/what-if queries through a **Plan → Execute → Verify → Route** loop with deterministic stop conditions, token/iteration budgets, and non-blocking `ask_user` queues.
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
python3 scripts/seed_demo.py --output data/demo_warehouse.db
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
WAREHOUSE_DB_PATH="data/demo_warehouse.db" PYTHONPATH=backend python3 -m src.analytics.graph_mining
```
