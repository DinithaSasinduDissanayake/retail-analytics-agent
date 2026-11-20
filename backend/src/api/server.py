"""FastAPI application with SSE streaming endpoint."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from src.agent.orchestrator import run_analysis
from src.agent.tools import submit_user_answer, get_pending_questions
from src.db.etl import run_etl

import structlog

logger = structlog.get_logger()


# === Request/Response Models ===

class AgentRunRequest(BaseModel):
    message: str


class AgentRespondRequest(BaseModel):
    answer: str
    question_id: str | None = None


class QueryRequest(BaseModel):
    sql: str


class SyncResponse(BaseModel):
    status: str
    summary: dict | None = None


# === Session Store ===
# Each entry: { "history": str | None }  (JSON-encoded ModelMessage list)

_sessions: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — init and cleanup."""
    logger.info("Starting warehouse agent API")
    yield
    logger.info("Shutting down warehouse agent API")


app = FastAPI(title="Warehouse Agent", lifespan=lifespan)


# === SSE Agent Run ===

@app.post("/api/agent/run")
async def agent_run(request: Request):
    """Start an analysis. Streams SSE events.

    Accepts an optional ``session_id`` in the request body. If provided
    and known, previous conversation history is included so the agent
    can continue the conversation. If omitted, a new session is created.
    The final ``done`` event includes ``messages_json`` with the full
    updated history.
    """
    body = await request.json()
    user_query = body.get("message", "")
    session_id = body.get("session_id") or str(uuid.uuid4())

    # Retrieve stored history for this session
    session = _sessions.get(session_id, {})
    history_json: str | None = session.get("history")

    async def event_generator() -> AsyncGenerator[str, None]:
        messages_json: str | None = None
        try:
            async for event in run_analysis(
                session_id,
                user_query,
                message_history_json=history_json,
            ):
                if await request.is_disconnected():
                    break
                # Capture updated history from final done event
                if event.get("type") == "done":
                    messages_json = event.pop("messages_json", None)
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            logger.exception("agent run error", error=str(e))
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            # Persist updated history
            if messages_json:
                _sessions[session_id] = {"history": messages_json}

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-Id": session_id,
        },
    )


@app.post("/api/agent/respond")
async def agent_respond(body: AgentRespondRequest):
    """Submit a user answer to a pending question."""
    question_id = body.question_id
    if not question_id:
        pending = get_pending_questions()
        if pending:
            question_id = pending[0]["question_id"]

    if question_id:
        found = submit_user_answer(question_id, body.answer)
        if found:
            return JSONResponse({"status": "ok", "question_id": question_id})
        return JSONResponse(
            {"status": "not_found", "detail": "Question not found or already answered"},
            status_code=404,
        )

    return JSONResponse(
        {"status": "error", "detail": "No pending questions"},
        status_code=400,
    )


@app.get("/api/agent/questions")
async def get_questions():
    """Get all currently pending user questions."""
    return JSONResponse(get_pending_questions())


# === Dashboard (direct SQL) ===

@app.post("/api/dashboard/query")
async def dashboard_query(body: QueryRequest):
    """Execute a direct SQL query against the warehouse. Deterministic, no agent."""
    from src.db import get_warehouse
    conn = None
    try:
        _here = Path(__file__).resolve().parent.parent.parent.parent
        db_path = Path(os.getenv("WAREHOUSE_DB_PATH", str(_here / "data" / "warehouse.db")))
        conn = get_warehouse(db_path)
        result = conn.execute(body.sql)
        columns = [desc[0] for desc in result.description]
        rows = [dict(zip(columns, row)) for row in result.fetchmany(1000)]
        return JSONResponse({"columns": columns, "rows": rows, "count": len(rows)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    finally:
        if conn is not None:
            conn.close()


# === Data Sync ===

@app.post("/api/sync", response_model=SyncResponse)
async def sync_data():
    """Re-run ETL to refresh data from the .mdb file."""
    try:
        _here = Path(__file__).resolve().parent.parent.parent.parent
        mdb_path = Path(os.getenv("POS_MDB_PATH", str(_here / "data" / "pos_export.mdb")))
        db_path = Path(os.getenv("WAREHOUSE_DB_PATH", str(_here / "data" / "warehouse.db")))
        summary = run_etl(mdb_path, db_path)
        return SyncResponse(status="ok", summary=summary)
    except Exception as e:
        logger.exception("sync error")
        return SyncResponse(status="error", summary={"error": str(e)})


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    try:
        from src.db import get_warehouse
        _here = Path(__file__).resolve().parent.parent.parent.parent
        db_path = Path(os.getenv("WAREHOUSE_DB_PATH", str(_here / "data" / "warehouse.db")))
        conn = get_warehouse(db_path)
        count = conn.execute("SELECT COUNT(*) FROM Stock").fetchone()[0]
        conn.close()
        return {"status": "ok", "products": count}
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)


# === Development Index Page ===

@app.get("/", response_class=HTMLResponse)
async def index():
    """Simple dev landing page."""
    return HTMLResponse("""
    <html>
    <head><title>Warehouse Agent</title></head>
    <body style="font-family: sans-serif; max-width: 800px; margin: 40px auto;">
        <h1>Warehouse Agent API</h1>
        <p>Available endpoints:</p>
        <ul>
            <li><code>POST /api/agent/run</code> — Start analysis (SSE stream)</li>
            <li><code>POST /api/agent/respond</code> — Answer agent question</li>
            <li><code>GET /api/agent/questions</code> — Pending questions</li>
            <li><code>POST /api/dashboard/query</code> — Direct SQL query</li>
            <li><code>POST /api/sync</code> — Re-run ETL</li>
            <li><code>GET /api/health</code> — Health check</li>
        </ul>
        <hr>
        <h2>Quick Test</h2>
        <form id="test-form">
            <input type="text" id="query" size="60" placeholder="Ask a question..." value="Show top 10 products by revenue">
            <button type="submit">Send</button>
        </form>
        <pre id="output" style="background: #f5f5f5; padding: 10px; min-height: 100px;"></pre>
        <script>
            document.getElementById('test-form').onsubmit = async (e) => {
                e.preventDefault();
                const query = document.getElementById('query').value;
                const output = document.getElementById('output');
                output.textContent = 'Connecting...';

                const response = await fetch('/api/agent/run', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: query}),
                });

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                output.textContent = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    const text = decoder.decode(value);
                    for (const line of text.split('\\n')) {
                        if (line.startsWith('data: ')) {
                            try {
                                const event = JSON.parse(line.slice(6));
                                output.textContent += JSON.stringify(event, null, 2) + '\\n\\n';
                            } catch {}
                        }
                    }
                }
            };
        </script>
    </body>
    </html>
    """)


def main():
    """Run the dev server."""
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
