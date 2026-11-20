"""Integration tests — ETL + API end-to-end."""
import json
import os
import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from src.api.server import app
from src.db.etl import run_etl

HAS_LIVE_LLM = bool(os.getenv("LLM_API_KEY")) and os.getenv("LLM_API_KEY") != "mock-key-for-testing"


# === ETL Integration ===

def test_etl_full_reload(mdb_path, db_path):
    """Full ETL reload produces expected tables."""
    summary = run_etl(mdb_path, db_path)
    assert summary["Stock"] > 0
    assert summary["Docket"] > 0
    assert summary["DocketLine"] > 0
    assert summary["Departments"] > 0


def test_etl_idempotent(mdb_path, db_path):
    """Running ETL twice produces same counts."""
    first = run_etl(mdb_path, db_path)
    second = run_etl(mdb_path, db_path)
    assert second["Stock"] == first["Stock"]


def test_etl_schema_hash(mdb_path, db_path):
    """ETL computes a consistent schema hash."""
    from src.db import get_warehouse
    run_etl(mdb_path, db_path)
    conn = get_warehouse(db_path)
    hashes = conn.execute(
        "SELECT value FROM _etl_meta WHERE key = 'schema_hash'"
    ).fetchall()
    assert len(hashes) == 1
    assert len(hashes[0][0]) == 16


# === API Integration ===

@pytest.fixture
def client():
    """FastAPI test client."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_health(client):
    """Health endpoint returns stock count."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["products"] > 0


@pytest.mark.asyncio
async def test_dashboard_query(client):
    """Direct SQL query works."""
    resp = await client.post("/api/dashboard/query", json={"sql": "SELECT COUNT(*) as cnt FROM Departments"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["columns"] == ["cnt"]
    assert data["rows"][0]["cnt"] > 0


@pytest.mark.asyncio
async def test_dashboard_query_error(client):
    """Bad SQL returns error."""
    resp = await client.post("/api/dashboard/query", json={"sql": "SELECT * FROM nonexistent"})
    assert resp.status_code == 400


@pytest.mark.slow
@pytest.mark.skipif(not HAS_LIVE_LLM, reason="Requires live LLM_API_KEY")
@pytest.mark.asyncio
async def test_agent_run_simple(client):
    """Simple fact query via agent returns SSE events."""
    resp = await client.post(
        "/api/agent/run",
        json={"message": "How many products do we have?"},
    )
    assert resp.status_code == 200
    
    events = []
    async for line in resp.aiter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    
    types = [e["type"] for e in events]
    assert "progress" in types
    assert "done" in types
    # Answer should reference the product count
    done_event = next(e for e in events if e["type"] == "done")
    assert "6" in done_event.get("answer", "")  # some number


@pytest.mark.slow
@pytest.mark.skipif(not HAS_LIVE_LLM, reason="Requires live LLM_API_KEY")
@pytest.mark.asyncio
async def test_agent_run_complex(client):
    """Complex query via real AI agent completes."""
    resp = await client.post(
        "/api/agent/run",
        json={"message": "How many departments do we have and list their names?"},
    )
    
    events = []
    async for line in resp.aiter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    
    types = [e["type"] for e in events]
    assert "progress" in types
    assert "done" in types
    
    done = next(e for e in events if e["type"] == "done")
    assert len(done.get("answer", "")) > 0


@pytest.mark.asyncio
async def test_sync(client):
    """Sync endpoint works when a source .mdb file is present."""
    mdb_path = Path(os.getenv("POS_MDB_PATH", str(Path(__file__).resolve().parents[3] / "data" / "pos_export.mdb")))
    if not mdb_path.exists():
        pytest.skip(f"Source .mdb not present at {mdb_path}")
    resp = await client.post("/api/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["summary"]["Stock"] > 0
