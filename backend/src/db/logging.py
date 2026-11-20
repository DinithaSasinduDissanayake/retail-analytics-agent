"""Agent run logging — writes run events to auxiliary.db."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import structlog

logger = structlog.get_logger()

_HERE = Path(__file__).resolve().parent
AUX_DB = str(_HERE.parent.parent.parent / "data" / "auxiliary.db")


def _ensure_table(conn: duckdb.DuckDBPyConnection) -> None:
    """Create the agent_logs table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_logs (
            id INTEGER,
            session_id VARCHAR,
            user_query VARCHAR,
            event_types VARCHAR,
            event_count INTEGER,
            answer_length INTEGER,
            had_error BOOLEAN,
            had_data BOOLEAN,
            had_question BOOLEAN,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _next_id(conn: duckdb.DuckDBPyConnection) -> int:
    """Get next sequential ID for agent_logs."""
    result = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM agent_logs").fetchone()
    return result[0]


def log_agent_run(
    session_id: str,
    user_query: str,
    events: list[dict[str, Any]],
) -> None:
    """Log an agent run to auxiliary.db.

    Args:
        session_id: Unique session identifier.
        user_query: The user's original query.
        events: List of SSE events yielded during the run.
    """
    event_types = [e.get("type", "") for e in events]
    done_evt = next((e for e in events if e.get("type") == "done"), None)

    conn = duckdb.connect(AUX_DB)
    try:
        _ensure_table(conn)
        next_id = _next_id(conn)

        conn.execute("""
            INSERT INTO agent_logs (
                id, session_id, user_query, event_types, event_count,
                answer_length, had_error, had_data, had_question
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            next_id,
            session_id,
            user_query[:500],
            json.dumps(event_types),
            len(events),
            len(done_evt.get("answer", "")) if done_evt else 0,
            any(e.get("type") == "error" for e in events),
            any(e.get("type") == "data_found" for e in events),
            any(e.get("type") == "question" for e in events),
        ])
        conn.commit()
    except Exception as e:
        logger.warning("failed to write agent log", error=str(e))
    finally:
        try:
            conn.close()
        except Exception:
            pass
