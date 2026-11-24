"""Orchestrator — runs the PydanticAI agent and yields SSE events."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, AsyncGenerator

from pydantic import TypeAdapter
from pydantic_ai import UsageLimits
from pydantic_ai.messages import ModelMessage

import structlog

_HERE = Path(__file__).resolve().parent
DB_PATH = str(_HERE.parent.parent.parent / "data" / "warehouse.db")
DATA_DIR = str(_HERE.parent.parent.parent / "data")

from src.agent.agent import warehouse_agent, Deps
from src.db.logging import log_agent_run

logger = structlog.get_logger()

# ── Budget Limits ───────────────────────────────────────────────────
MAX_REQUESTS = 50         # Max LLM requests per run
MAX_TOOL_CALLS = 100      # Max total tool calls per run
MAX_TIME_SEC = 300        # Max wall-clock time per run (5 min)

_USAGE_LIMITS = UsageLimits(
    request_limit=MAX_REQUESTS,
    tool_calls_limit=MAX_TOOL_CALLS,
)

# Type adapter for message history serialization
_message_ta = TypeAdapter(list[ModelMessage])


# ── Run Analysis ────────────────────────────────────────────────────


async def run_analysis(
    session_id: str,
    user_query: str,
    *,
    message_history_json: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run the PydanticAI agent on a user query. Yields SSE events.

    If *message_history_json* is provided (JSON‑encoded list of
    ``ModelMessage`` from a previous run), it is passed as
    ``message_history`` to the agent so the conversation continues.

    The final ``done`` event includes a ``messages_json`` key carrying
    the full updated message history for the caller to store.
    """
    event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    db_path = os.getenv("WAREHOUSE_DB_PATH", DB_PATH)
    deps = Deps(event_queue=event_queue, db_path=db_path, data_dir=DATA_DIR)

    # Rehydrate message history
    message_history: list[ModelMessage] | None = None
    if message_history_json:
        try:
            message_history = _message_ta.validate_json(message_history_json)
        except Exception as e:
            logger.warning("failed to rehydrate message history", error=str(e))

    yield {"type": "progress", "message": "Starting analysis..."}

    async def run_agent() -> None:
        """Run agent in background with streaming. Pushes terminal events to queue."""
        try:
            async def _stream() -> None:
                async with warehouse_agent.run_stream(
                    user_query,
                    deps=deps,
                    usage_limits=_USAGE_LIMITS,
                    message_history=message_history,
                ) as result:
                    full_text = ""
                    async for delta in result.stream_text(delta=True):
                        full_text += delta
                        await event_queue.put({"type": "text_delta", "delta": delta})

                    messages_json = result.all_messages_json().decode()
                    await event_queue.put({
                        "type": "done",
                        "answer": full_text or "(no response)",
                        "messages_json": messages_json,
                    })

            await asyncio.wait_for(_stream(), timeout=MAX_TIME_SEC)
        except asyncio.TimeoutError:
            await event_queue.put({
                "type": "error",
                "message": f"Analysis exceeded {MAX_TIME_SEC}s limit. Try a simpler question.",
            })
        except Exception as e:
            logger.exception("agent run failed")
            await event_queue.put({"type": "error", "message": f"Agent error: {e}"})

    task = asyncio.create_task(run_agent())

    collected_events: list[dict[str, Any]] = []

    try:
        while True:
            event = await event_queue.get()
            collected_events.append(event)
            yield event
            if event.get("type") in ("done", "error"):
                break
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Log the run (best-effort)
        try:
            log_agent_run(
                session_id=session_id,
                user_query=user_query,
                events=collected_events,
            )
        except Exception as e:
            logger.warning("failed to log agent run", error=str(e))
