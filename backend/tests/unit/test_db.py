"""Unit tests for database modules — connections, schema, logging."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest


class TestWarehouseConnection:
    """Test read-only warehouse connection."""

    def test_get_warehouse_returns_readonly(self, tmp_path):
        """get_warehouse opens a read-only connection."""
        from src.db import get_warehouse

        # Create a test database
        db = tmp_path / "test.db"
        conn = duckdb.connect(str(db))
        conn.execute("CREATE TABLE test (x INTEGER)")
        conn.execute("INSERT INTO test VALUES (1)")
        conn.close()

        # Open read-only
        ro = get_warehouse(db)
        result = ro.execute("SELECT * FROM test").fetchall()
        assert result == [(1,)]
        ro.close()

    def test_get_warehouse_readonly_enforced(self, tmp_path):
        """Writing to a read-only warehouse fails."""
        from src.db import get_warehouse

        db = tmp_path / "test.db"
        conn = duckdb.connect(str(db))
        conn.execute("CREATE TABLE test (x INTEGER)")
        conn.close()

        ro = get_warehouse(db)
        with pytest.raises((duckdb.InvalidInputException, duckdb.CatalogException)):
            ro.execute("INSERT INTO test VALUES (2)")
        ro.close()

    def test_get_warehouse_nonexistent_raises(self):
        """Opening a nonexistent DB in read-only mode raises an error."""
        from src.db import get_warehouse

        with pytest.raises((IOError, duckdb.IOException)):
            get_warehouse(Path("/nonexistent/test.db"))


class TestSchemaDescription:
    """Test schema description generation."""

    def test_load_schema_returns_markdown(self, tmp_path):
        """load_schema_description returns non-empty markdown."""
        from src.db.schema import load_schema_description

        # Create a minimal DuckDB
        db = tmp_path / "test.db"
        conn = duckdb.connect(str(db))
        conn.execute("CREATE TABLE products (id INTEGER, name VARCHAR, price DECIMAL(10,2))")
        conn.execute("CREATE TABLE sales (sale_id INTEGER, product_id INTEGER, qty INTEGER)")
        conn.close()

        schema = load_schema_description(db)
        assert isinstance(schema, str)
        assert "Database Schema" in schema
        assert "products" in schema
        assert "sales" in schema
        assert "business rules" in schema.lower()
        assert "READ ONLY" in schema

    def test_load_schema_includes_rules(self, tmp_path):
        """Schema markdown includes business rules."""
        from src.db.schema import load_schema_description

        db = tmp_path / "test.db"
        conn = duckdb.connect(str(db))
        conn.execute("CREATE TABLE empty (x INTEGER)")
        conn.close()

        schema = load_schema_description(db)
        assert "business rules" in schema.lower()
        assert "READ ONLY" in schema

    def test_load_schema_empty_db(self, tmp_path):
        """Empty database returns minimal schema."""
        from src.db.schema import load_schema_description

        db = tmp_path / "empty.db"
        conn = duckdb.connect(str(db))
        conn.close()

        schema = load_schema_description(db)
        assert "Database Schema" in schema
        assert "READ ONLY" in schema


class TestLogging:
    """Test agent run logging to auxiliary.db."""

    def test_log_agent_run_basic(self, tmp_path):
        """log_agent_run writes a row to auxiliary.db."""
        from src.db.logging import log_agent_run

        # Override AUX_DB for testing
        import src.db.logging as logging_mod
        original_aux = logging_mod.AUX_DB
        logging_mod.AUX_DB = str(tmp_path / "aux.db")

        try:
            log_agent_run(
                session_id="test-sess-1",
                user_query="how many products?",
                events=[
                    {"type": "progress", "message": "starting"},
                    {"type": "done", "answer": "42"},
                ],
            )

            conn = duckdb.connect(str(tmp_path / "aux.db"))
            rows = conn.execute("SELECT * FROM agent_logs").fetchall()
            conn.close()

            assert len(rows) == 1
            session_id, query = rows[0][1], rows[0][2]
            assert session_id == "test-sess-1"
            assert "products" in query
        finally:
            logging_mod.AUX_DB = original_aux

    def test_log_agent_run_empty_events(self, tmp_path):
        """Empty event list doesn't crash."""
        from src.db.logging import log_agent_run

        import src.db.logging as logging_mod
        original_aux = logging_mod.AUX_DB
        logging_mod.AUX_DB = str(tmp_path / "aux_empty.db")

        try:
            log_agent_run(session_id="sess-2", user_query="test", events=[])
            conn = duckdb.connect(str(tmp_path / "aux_empty.db"))
            rows = conn.execute("SELECT * FROM agent_logs").fetchall()
            conn.close()
            assert len(rows) == 1
            assert rows[0][4] == 0  # event_count = 0
        finally:
            logging_mod.AUX_DB = original_aux

    def test_log_agent_run_error_event(self, tmp_path):
        """Error events are marked in the log."""
        from src.db.logging import log_agent_run

        import src.db.logging as logging_mod
        original_aux = logging_mod.AUX_DB
        logging_mod.AUX_DB = str(tmp_path / "aux_err.db")

        try:
            log_agent_run(
                session_id="sess-3",
                user_query="crash test",
                events=[{"type": "error", "message": "API down"}],
            )

            conn = duckdb.connect(str(tmp_path / "aux_err.db"))
            row = conn.execute("SELECT had_error FROM agent_logs").fetchone()
            conn.close()
            assert row[0] is True
        finally:
            logging_mod.AUX_DB = original_aux

    def test_log_agent_run_data_event(self, tmp_path):
        """data_found events are marked in the log."""
        from src.db.logging import log_agent_run

        import src.db.logging as logging_mod
        original_aux = logging_mod.AUX_DB
        logging_mod.AUX_DB = str(tmp_path / "aux_data.db")

        try:
            log_agent_run(
                session_id="sess-4",
                user_query="data test",
                events=[{"type": "data_found", "data": "results..."}, {"type": "done", "answer": "done"}],
            )

            conn = duckdb.connect(str(tmp_path / "aux_data.db"))
            row = conn.execute("SELECT had_data, had_question FROM agent_logs").fetchone()
            conn.close()
            assert row[0] is True  # had_data
            assert row[1] is False  # had_question
        finally:
            logging_mod.AUX_DB = original_aux

    def test_log_agent_run_long_query_truncated(self, tmp_path):
        """Long queries are truncated to 500 chars."""
        from src.db.logging import log_agent_run

        import src.db.logging as logging_mod
        original_aux = logging_mod.AUX_DB
        logging_mod.AUX_DB = str(tmp_path / "aux_long.db")

        try:
            long_query = "what " * 200  # 1000 chars
            log_agent_run(
                session_id="sess-5",
                user_query=long_query,
                events=[{"type": "done", "answer": "ok"}],
            )

            conn = duckdb.connect(str(tmp_path / "aux_long.db"))
            stored = conn.execute("SELECT user_query FROM agent_logs").fetchone()[0]
            conn.close()
            assert len(stored) <= 500
        finally:
            logging_mod.AUX_DB = original_aux

    def test_log_agent_run_idempotent(self, tmp_path):
        """Multiple log calls create multiple rows."""
        from src.db.logging import log_agent_run

        import src.db.logging as logging_mod
        original_aux = logging_mod.AUX_DB
        logging_mod.AUX_DB = str(tmp_path / "aux_multi.db")

        try:
            for i in range(3):
                log_agent_run(
                    session_id=f"sess-{i}",
                    user_query=f"query {i}",
                    events=[{"type": "done", "answer": str(i)}],
                )

            conn = duckdb.connect(str(tmp_path / "aux_multi.db"))
            rows = conn.execute("SELECT COUNT(*) FROM agent_logs").fetchone()
            conn.close()
            assert rows[0] == 3
        finally:
            logging_mod.AUX_DB = original_aux
