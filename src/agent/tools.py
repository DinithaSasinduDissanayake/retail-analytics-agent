import asyncio, duckdb, sys, traceback
from pathlib import Path
from typing import Any
from src.db import get_warehouse

RESTRICTED_IMPORTS = {
    "os", "subprocess", "shutil", "pathlib", "ctypes",
    "socket", "requests", "urllib", "http", "multiprocessing",
    "threading", "pickle", "shelve", "dbm", "webbrowser",
}
RESTRICTED_BUILTINS = {"__import__", "eval", "compile", "open", "input"}

async def duckdb_query(sql: str, db_path: str = "data/warehouse.db") -> str:
    """Execute a SQL query against the read-only warehouse and return formatted tabular text."""
    MAX_ROWS = 1000
    try:
        conn = get_warehouse(Path(db_path))
        result = conn.execute(sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchmany(MAX_ROWS + 1)
        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]
        
        lines = [" | ".join(columns)]
        lines.append("-|-".join("-" * len(c) for c in columns))
        for row in rows:
            lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))
        
        if truncated:
            lines.append(f"... (limited to {MAX_ROWS} rows)")
        return "\n".join(lines)
    except Exception as e:
        return f"SQL Error: {type(e).__name__}: {e}"

async def run_sandboxed_python(code: str, db_path: str = "data/warehouse.db") -> str:
    """Run Python analysis code in a sandboxed namespace with read-only database access."""
    for kw in RESTRICTED_IMPORTS:
        if f"import {kw}" in code or f"from {kw}" in code:
            return f"BLOCKED: Import of '{kw}' is not permitted in sandbox."
    for b in RESTRICTED_BUILTINS:
        if b in code:
            return f"BLOCKED: '{b}' is restricted."
            
    conn = get_warehouse(Path(db_path))
    safe_globals = {"conn": conn, "duckdb": duckdb}
    safe_locals = {}
    
    try:
        exec(code, safe_globals, safe_locals)
        return str(safe_locals.get("result", "Execution succeeded with no explicit result variable."))
    except Exception as e:
        return f"Execution Error: {traceback.format_exc()}"
