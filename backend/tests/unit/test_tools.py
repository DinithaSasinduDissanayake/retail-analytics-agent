"""Tests for tools: duckdb_query, ask_user, run_python."""
import pytest
from src.agent.tools import (
    duckdb_query,
    ask_user,
    run_python,
    submit_user_answer,
    get_pending_questions,
)


@pytest.mark.asyncio
async def test_duckdb_query_simple(db_path):
    """Can query the warehouse and get results."""
    result = await duckdb_query("SELECT COUNT(*) as cnt FROM Stock", str(db_path))
    assert "Error:" not in result
    assert "cnt" in result


@pytest.mark.asyncio
async def test_duckdb_query_departments(db_path):
    result = await duckdb_query("SELECT COUNT(*) as cnt FROM Departments", str(db_path))
    assert "Error:" not in result
    lines = [line.strip() for line in result.splitlines() if line.strip()]
    assert int(lines[-1]) > 0


@pytest.mark.asyncio
async def test_duckdb_query_bad_sql(db_path):
    result = await duckdb_query("SELECT * FROM nonexistent_table", str(db_path))
    assert "Error:" in result


@pytest.mark.asyncio
async def test_duckdb_query_read_only_enforced(db_path):
    """Write attempts must fail at the database level."""
    result = await duckdb_query("CREATE TABLE test_write (x INTEGER)", str(db_path))
    assert "Error:" in result


@pytest.mark.asyncio
async def test_run_python_simple(db_path):
    code = "print(2 + 2)"
    result = await run_python(code, str(db_path))
    assert "4" in result
    assert "BLOCKED" not in result


@pytest.mark.asyncio
async def test_run_python_with_conn(db_path):
    """Run Python can access the DuckDB connection."""
    code = "result = conn.execute('SELECT COUNT(*) FROM Stock').fetchone()\nprint(result[0])"
    result = await run_python(code, str(db_path))
    assert int(result.strip()) > 0


@pytest.mark.asyncio
async def test_run_python_blocked_import_os(db_path):
    code = "import os\nprint('should not work')"
    result = await run_python(code, str(db_path))
    assert "BLOCKED" in result


@pytest.mark.asyncio
async def test_run_python_blocked_import_subprocess(db_path):
    code = "from subprocess import run"
    result = await run_python(code, str(db_path))
    assert "BLOCKED" in result


@pytest.mark.asyncio
async def test_run_python_blocked_import_requests(db_path):
    code = "import requests"
    result = await run_python(code, str(db_path))
    assert "BLOCKED" in result


@pytest.mark.asyncio
async def test_run_python_error(db_path):
    code = "print(1/0)"
    result = await run_python(code, str(db_path))
    assert "Error" in result
    assert "ZeroDivisionError" in result


@pytest.mark.asyncio
async def test_ask_user_and_answer():
    """Ask a question, submit answer, verify it arrives."""
    # Clear pending first
    pending = get_pending_questions()
    
    # Start asking (runs in background)
    import asyncio
    async def ask_and_wait():
        return await ask_user("What color is the sky?", timeout=5.0)
    
    task = asyncio.create_task(ask_and_wait())
    await asyncio.sleep(0.1)  # Let the tool register
    
    # Check question was queued
    assert len(get_pending_questions()) >= 1
    q = get_pending_questions()[-1]
    assert "sky" in q["question"]
    
    # Answer it
    result = submit_user_answer(q["question_id"], "blue")
    assert result is True
    
    answer = await task
    assert answer == "blue"


@pytest.mark.asyncio
async def test_ask_user_timeout():
    """Unanswered question should timeout and return NO_ANSWER."""
    result = await ask_user("Quick test?", timeout=0.1)
    assert result == "NO_ANSWER"
