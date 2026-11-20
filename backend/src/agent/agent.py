"""PydanticAI agent for the warehouse data assistant."""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

import structlog

logger = structlog.get_logger()

# ── OpenAI-Compatible Model Configuration ───────────────────────────

_MODEL = OpenAIChatModel(
    os.getenv("LLM_MODEL", "gpt-4o-mini"),
    provider=OpenAIProvider(
        base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        api_key=os.getenv("LLM_API_KEY", "mock-key-for-testing"),
    ),
)

# ── Dependencies (per-run) ──────────────────────────────────────────


class Deps(BaseModel):
    """Per-run dependencies passed to the agent."""
    event_queue: asyncio.Queue
    db_path: str
    data_dir: str

    model_config = ConfigDict(arbitrary_types_allowed=True)


# ── Agent Definition ────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a data warehouse assistant for a retail store.
You help decision makers understand their business data by answering questions in natural language.

## Rules
1. You have 15+ years of business data stored in a DuckDB database.
2. All numeric values in the database are stored as VARCHAR — use CAST() in SQL queries.
3. The database is READ-ONLY — you cannot insert, update, or delete data.
4. You can write SQL queries, run Python analysis, and ask the user follow-up questions.
5. Be conversational but concise.
6. If a query fails, try a different approach before asking the user for help.
7. Dates are in YYYY-MM-DD format.
8. A stock item is ACTIVE if `inactive` is NULL or empty. "1" means inactive.
"""


warehouse_agent = Agent(
    _MODEL,
    system_prompt=SYSTEM_PROMPT,
    deps_type=Deps,
)

# ── Dynamic system prompt: inject schema ────────────────────────────


@warehouse_agent.system_prompt
async def add_schema(ctx: RunContext[Deps]) -> str:
    """Inject the database schema into every LLM call."""
    from src.db.schema import load_schema_description
    return load_schema_description(Path(ctx.deps.db_path))


# ── Tools ───────────────────────────────────────────────────────────


@warehouse_agent.tool
async def duckdb_query(ctx: RunContext[Deps], sql: str) -> str:
    """Execute a SQL query against the warehouse database.

    The database is READ-ONLY — writes will fail.
    Results are limited to prevent massive output.
    Pass the SQL as a complete, valid DuckDB SQL statement.
    Remember to CAST() VARCHAR columns to appropriate types.
    """
    from src.agent.tools import duckdb_query as _duckdb_query

    await ctx.deps.event_queue.put({"type": "progress", "message": f"Running SQL: {sql[:120]}..."})
    logger.info("agent.duckdb_query", sql=sql[:200])

    result = await _duckdb_query(sql, ctx.deps.db_path)
    await ctx.deps.event_queue.put({"type": "data_found", "data": result})
    return result


@warehouse_agent.tool
async def run_python(ctx: RunContext[Deps], code: str) -> str:
    """Run Python code in a sandboxed environment.

    The DuckDB connection is available as `conn`.
    Dangerous imports (os, subprocess, etc.) are blocked.
    Execution is limited to 30 seconds and 10000 chars output.
    """
    from src.agent.tools import run_python as _run_python

    await ctx.deps.event_queue.put({"type": "progress", "message": "Running Python analysis..."})
    logger.info("agent.run_python", code=code[:200])

    result = await _run_python(code, ctx.deps.db_path)
    if result.startswith("BLOCKED") or result.startswith("TIMEOUT") or result.startswith("Error"):
        await ctx.deps.event_queue.put({"type": "error", "message": result})
    else:
        await ctx.deps.event_queue.put({"type": "data_found", "data": result})
    return result


@warehouse_agent.tool
async def ask_user(ctx: RunContext[Deps], question: str) -> str:
    """Ask the user a question mid-analysis when you need more information.

    Use this when you need clarification, context, or additional data
    that the user can provide (e.g., "which supplier?", "what time period?").
    The user will see your question and can respond.
    """
    from src.agent.tools import _user_message_queue, _pending_user_questions

    question_id = str(uuid.uuid4())
    future: asyncio.Future[str] = asyncio.get_event_loop().create_future()

    _user_message_queue[question_id] = future
    _pending_user_questions[question_id] = {
        "question_id": question_id,
        "question": question,
    }

    logger.info("agent.ask_user", question_id=question_id, question=question[:100])

    await ctx.deps.event_queue.put({
        "type": "question",
        "question_id": question_id,
        "question": question,
    })

    try:
        answer = await asyncio.wait_for(future, timeout=120.0)
        _pending_user_questions.pop(question_id, None)
        _user_message_queue.pop(question_id, None)
        return answer
    except asyncio.TimeoutError:
        _pending_user_questions.pop(question_id, None)
        _user_message_queue.pop(question_id, None)
        logger.info("agent.ask_user timeout", question_id=question_id)
        return "NO_ANSWER"
