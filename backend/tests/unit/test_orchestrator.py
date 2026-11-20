"""Unit tests for the orchestrator — event flow, timeouts, cleanup."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


class TestOrchestratorInfrastructure:
    """Test the orchestrator's event flow infrastructure.
    
    These tests verify the orchestrator mechanics (event queue, cleanup, error
    handling) without making actual LLM calls.
    """

    @pytest.mark.asyncio
    async def test_event_queue_flow(self):
        """Events flow through queue in order."""
        from src.agent.orchestrator import run_analysis

        async def mock_run(user_query, *args, **kwargs):
            deps = kwargs["deps"]
            await deps.event_queue.put({"type": "progress", "message": "step 1"})
            await deps.event_queue.put({"type": "data_found", "data": "result_1"})
            await deps.event_queue.put({"type": "done", "answer": "done!"})
            mock = AsyncMock()
            mock.output = "done!"
            return mock

        with patch("src.agent.orchestrator.warehouse_agent.run", mock_run):
            events = []
            async for event in run_analysis("test-session", "test query"):
                events.append(event)
                if event.get("type") in ("done", "error"):
                    break

            types = [e["type"] for e in events]
            assert types == ["progress", "progress", "data_found", "done"]
            assert events[-1]["answer"] == "done!"

    @pytest.mark.asyncio
    async def test_error_event_propagated(self):
        """Agent errors are yielded as error events."""
        from src.agent.orchestrator import run_analysis

        async def mock_run(*args, **kwargs):
            raise RuntimeError("LLM unavailable")

        with patch("src.agent.orchestrator.warehouse_agent.run", mock_run):
            events = []
            async for event in run_analysis("test-session", "test query"):
                events.append(event)
                if event.get("type") in ("done", "error"):
                    break

            assert events[-1]["type"] == "error"
            assert "LLM unavailable" in events[-1]["message"]

    @pytest.mark.asyncio
    async def test_generator_cleanup_on_early_exit(self):
        """Generator doesn't hang when consumer exits early."""
        from src.agent.orchestrator import run_analysis

        async def hanging_run(*args, **kwargs):
            deps = kwargs["deps"]
            await deps.event_queue.put({"type": "progress", "message": "working..."})
            await asyncio.Event().wait()

        with patch("src.agent.orchestrator.warehouse_agent.run", hanging_run):
            gen = run_analysis("test-session", "test query")
            # Read just the first progress event, then close
            async for event in gen:
                break

            # Generator should close cleanly
            await gen.aclose()

    @pytest.mark.asyncio
    async def test_multiple_data_events(self):
        """Multiple data_found events are yielded correctly."""
        from src.agent.orchestrator import run_analysis

        async def mock_run(user_query, *args, **kwargs):
            deps = kwargs["deps"]
            await deps.event_queue.put({"type": "data_found", "data": "q1_result"})
            await deps.event_queue.put({"type": "data_found", "data": "q2_result"})
            await deps.event_queue.put({"type": "done", "answer": "synthesis"})
            mock = AsyncMock()
            mock.output = "synthesis"
            return mock

        with patch("src.agent.orchestrator.warehouse_agent.run", mock_run):
            events = []
            async for event in run_analysis("test-session", "multi step"):
                events.append(event)
                if event.get("type") in ("done", "error"):
                    break

            data_events = [e for e in events if e["type"] == "data_found"]
            assert len(data_events) == 2
            assert data_events[0]["data"] == "q1_result"
            assert data_events[1]["data"] == "q2_result"

    @pytest.mark.asyncio
    async def test_deps_passed_correctly(self):
        """Deps are constructed with correct paths and queue."""
        from src.agent.orchestrator import run_analysis, DB_PATH, DATA_DIR

        captured_deps = None

        async def mock_run(user_query, *args, **kwargs):
            nonlocal captured_deps
            captured_deps = kwargs["deps"]
            mock = AsyncMock()
            mock.output = "ok"
            return mock

        with patch("src.agent.orchestrator.warehouse_agent.run", mock_run):
            async for event in run_analysis("test-session", "test"):
                if event.get("type") in ("done", "error"):
                    break

        assert captured_deps is not None
        assert captured_deps.db_path == DB_PATH
        assert captured_deps.data_dir == DATA_DIR
        assert captured_deps.event_queue is not None

    @pytest.mark.asyncio
    async def test_timeout_limit(self):
        """Orchestrator enforces time limit."""
        from src.agent.orchestrator import run_analysis

        async def slow_run(*args, **kwargs):
            await asyncio.sleep(10)
            mock = AsyncMock()
            mock.output = "too late"
            return mock

        with patch("src.agent.orchestrator.warehouse_agent.run", slow_run), \
             patch("src.agent.orchestrator.MAX_TIME_SEC", 1):
            events = []
            async for event in run_analysis("test-session", "slow query"):
                events.append(event)
                if event.get("type") in ("done", "error"):
                    break

        assert events[-1]["type"] == "error"
        msg = events[-1]["message"].lower()
        assert "limit" in msg or "timed out" in msg or "time" in msg
