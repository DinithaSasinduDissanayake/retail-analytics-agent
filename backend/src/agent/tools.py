"""Agent tools: duckdb_query, run_python, ask_user."""
from __future__ import annotations

import asyncio
import sys
import textwrap
import traceback
from pathlib import Path
from typing import Any

import duckdb
import structlog

from src.db import get_warehouse

logger = structlog.get_logger()

# === Message Queue (shared between tools and PEV loop) ===

_user_message_queue: dict[str, asyncio.Future[str]] = {}
_pending_user_questions: dict[str, dict[str, Any]] = {}


def submit_user_answer(question_id: str, answer: str) -> bool:
    """Submit an answer to a pending question. Returns True if found."""
    if question_id in _user_message_queue and not _user_message_queue[question_id].done():
        _user_message_queue[question_id].set_result(answer)
        return True
    return False


def get_pending_questions() -> list[dict[str, Any]]:
    """Get all currently pending questions for the frontend."""
    return list(_pending_user_questions.values())


async def ask_user(question: str, context: str = "", timeout: float = 120.0) -> str:
    """Ask the user a question mid-analysis. Non-blocking — returns immediately.
    
    The question is queued for the frontend. The answer arrives via submit_user_answer().
    If no answer within timeout, returns 'NO_ANSWER'.
    """
    import uuid
    question_id = str(uuid.uuid4())
    future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
    
    _user_message_queue[question_id] = future
    _pending_user_questions[question_id] = {
        "question_id": question_id,
        "question": question,
        "context": context,
        "timeout": timeout,
    }
    
    logger.info("ask_user", question_id=question_id, question=question[:100])
    
    try:
        answer = await asyncio.wait_for(future, timeout=timeout)
        _pending_user_questions.pop(question_id, None)
        return answer
    except asyncio.TimeoutError:
        _pending_user_questions.pop(question_id, None)
        _user_message_queue.pop(question_id, None)
        logger.info("ask_user timeout", question_id=question_id)
        return "NO_ANSWER"


async def duckdb_query(sql: str, db_path: str = "data/warehouse.db") -> str:
    """Execute a SQL query against the read-only warehouse and return results as text.
    
    The query is run against a READ-ONLY DuckDB connection. Any write attempt will fail.
    Results are limited to prevent massive output.
    """
    MAX_ROWS = 10000
    MAX_CHARS = 50000
    
    logger.info("duckdb_query", sql=sql[:200])
    
    try:
        conn = get_warehouse(Path(db_path))
        result = conn.execute(sql)
        
        # Get column names
        columns = [desc[0] for desc in result.description]
        
        # Fetch rows with limit
        rows = result.fetchmany(MAX_ROWS + 1)
        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]
        
        # Format as simple table
        lines = [" | ".join(columns)]
        lines.append("-|-".join("-" * len(c) for c in columns))
        for row in rows:
            lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))
        
        if truncated:
            lines.append(f"... and more (limited to {MAX_ROWS} rows)")
        
        output = "\n".join(lines)
        
        if len(output) > MAX_CHARS:
            output = output[:MAX_CHARS] + "\n... (truncated)"
        
        return output
    
    except Exception as e:
        error_msg = f"SQL Error: {type(e).__name__}: {e}"
        logger.error("duckdb_query error", error=error_msg, sql=sql[:200])
        return error_msg


# Block dangerous imports in run_python
RESTRICTED_IMPORTS = {
    "os", "subprocess", "shutil", "pathlib", "ctypes",
    "socket", "requests", "urllib", "http", "multiprocessing",
    "threading", "pickle", "shelve", "dbm", "webbrowser",
    "tkinter", "ssl", "email", "ftp", "telnetlib",
}

_RESTRICTED_BUILTINS = {
    "__import__", "eval", "compile", "open", "input",
}

# 'exec' is checked separately with word boundaries to avoid false positives on 'execute'


async def run_python(code: str, db_path: str = "data/warehouse.db") -> str:
    """Run Python code in a sandboxed environment.
    
    Blocks dangerous imports and limits execution time and output.
    The warehouse DuckDB connection is passed in as 'conn'.
    """
    MAX_TIME = 30
    MAX_OUTPUT = 10000
    
    logger.info("run_python", code=code[:200])
    
    # Check for blocked imports
    for keyword in RESTRICTED_IMPORTS:
        if f"import {keyword}" in code or f"from {keyword}" in code:
            return f"BLOCKED: Import of '{keyword}' is not allowed for safety reasons."
    
    for b in _RESTRICTED_BUILTINS:
        if b in code:
            return f"BLOCKED: Use of '{b}' is not allowed for safety reasons."
    
    # Check 'exec' with word boundaries to avoid false positives on 'execute'
    import re
    if re.search(r'\bexec\b', code):
        return "BLOCKED: Use of 'exec' is not allowed for safety reasons."
    
    conn = get_warehouse(Path(db_path))
    
    # Prepare safe globals
    safe_globals = {
        "__builtins__": {
            "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
            "enumerate": enumerate, "float": float, "format": format, "frozenset": frozenset,
            "hasattr": hasattr, "hash": hash, "hex": hex, "id": id, "int": int,
            "isinstance": isinstance, "issubclass": issubclass, "iter": iter,
            "len": len, "list": list, "map": map, "max": max, "min": min,
            "next": next, "object": object, "oct": oct, "ord": ord, "pow": pow,
            "print": print, "range": range, "repr": repr, "reversed": reversed,
            "round": round, "set": set, "slice": slice, "sorted": sorted,
            "str": str, "sum": sum, "tuple": tuple, "type": type,
            "zip": zip, "True": True, "False": False, "None": None,
        },
        "conn": conn,
    }
    
    # Capture stdout
    from io import StringIO
    stdout = StringIO()
    old_stdout = sys.stdout
    sys.stdout = stdout
    
    try:
        # Run with timeout via asyncio
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(exec, textwrap.dedent(code), safe_globals)
            try:
                future.result(timeout=MAX_TIME)
            except concurrent.futures.TimeoutError:
                return "TIMEOUT: Code execution exceeded 30 seconds and was terminated."
            except Exception as e:
                return f"Error: {type(e).__name__}: {e}\n{traceback.format_exc()[:2000]}"
    finally:
        sys.stdout = old_stdout
    
    output = stdout.getvalue()
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (truncated)"
    
    return output if output else "(no output)"
