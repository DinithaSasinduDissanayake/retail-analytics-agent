"""Unit tests for the orchestrator — event flow, timeouts, cleanup."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest


def _make_stream_cm(answer: str = "done!", on_enter=None):
    """Build an async context manager mimicking `warehouse_agent.run_stream`."""

    class _MockResult:
        async def stream_text(self, delta: bool = True):
            if answer:
                yield answer

        def all_messages_json(self) -> bytes:
            return b"[]"

    @asynccontextmanager
    async def _mock_run_stream(user_query, *args, **kwargs):
        if on_enter is not None:
            await on_enter(kwargs.get("deps"))
        yield _MockResult()

    return _mock_run_stream


class TestOrchestratorInfrastructure:
    """Test the orchestrator's event flow infrastructure."""

    @pytest.mark.asyncio
    async def test_event_queue_flow(self):
        """Events flow through queue in order."""
        from src.agent.orchestrator import run_analysis

        async def on_enter(deps):
            await deps.event_queue.put({"type": "progress", "message": "step 1"})
            await deps.event_queue.put({"type": "data_found", "data": "result_1"})

        with patch("src.agent.orchestrator.warehouse_agent.run_stream", _make_stream_cm("done!", on_enter)):
            events = []
            async for event in run_analysis("test-session", "test query"):
                events.append(event)
                if event.get("type") in ("done", "error"):
                    break

            types = [e["type"] for e in events]
            assert types == ["progress", "progress", "data_found", "text_delta", "done"]
            assert events[-1]["answer"] == "done!"

    @pytest.mark.asyncio
    async def test_error_event_propagated(self):
        """Agent errors are yielded as error events."""
        from src.agent.orchestrator import run_analysis

        @asynccontextmanager
        async def mock_run_stream(*args, **kwargs):
            raise RuntimeError("LLM unavailable")
            yield  # pragma: no cover

        with patch("src.agent.orchestrator.warehouse_agent.run_stream", mock_run_stream):
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

        @asynccontextmanager
        async def hanging_stream(*args, **kwargs):
            deps = kwargs["deps"]
            await deps.event_queue.put({"type": "progress", "message": "working..."})
            await asyncio.Event().wait()
            yield  # pragma: no cover

        with patch("src.agent.orchestrator.warehouse_agent.run_stream", hanging_stream):
            gen = run_analysis("test-session", "test query")
            async for _event in gen:
                break
            await gen.aclose()

    @pytest.mark.asyncio
    async def test_multiple_data_events(self):
        """Multiple data_found events are yielded correctly."""
        from src.agent.orchestrator import run_analysis

        async def on_enter(deps):
            await deps.event_queue.put({"type": "data_found", "data": "q1_result"})
            await deps.event_queue.put({"type": "data_found", "data": "q2_result"})

        with patch("src.agent.orchestrator.warehouse_agent.run_stream", _make_stream_cm("synthesis", on_enter)):
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

        async def on_enter(deps):
            nonlocal captured_deps
            captured_deps = deps

        with patch("src.agent.orchestrator.warehouse_agent.run_stream", _make_stream_cm("ok", on_enter)):
            async for event in run_analysis("test-session", "test"):
                if event.get("type") in ("done", "error"):
                    break

        assert captured_deps is not None
        assert captured_deps.db_path == DB_PATH
        assert captured_deps.data_dir == DATA_DIR
        assert isinstance(captured_deps.event_queue, asyncio.Queue)

    @pytest.mark.asyncio
    async def test_timeout_limit(self):
        """Timeout triggers error event."""
        from src.agent.orchestrator import run_analysis

        @asynccontextmanager
        async def slow_stream(*args, **kwargs):
            await asyncio.sleep(10)
            yield  # pragma: no cover

        with (
            patch("src.agent.orchestrator.warehouse_agent.run_stream", slow_stream),
            patch("src.agent.orchestrator.MAX_TIME_SEC", 0.05),
        ):
            events = []
            async for event in run_analysis("test-session", "slow query"):
                events.append(event)
                if event.get("type") in ("done", "error"):
                    break

            assert events[-1]["type"] == "error"
            assert "limit" in events[-1]["message"].lower()
