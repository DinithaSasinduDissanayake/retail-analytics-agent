"""Test configuration for unit tests."""
import os
import sys
from pathlib import Path

# This file lives at backend/tests/unit/conftest.py
# Project root = 4 levels up
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Add backend/ to path so "from src.agent..." imports work
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

# Export for tests to use in absolute path resolution
import pytest

@pytest.fixture
def db_path() -> Path:
    """Absolute path to warehouse.db."""
    return PROJECT_ROOT / "data" / "warehouse.db"
