"""Test configuration — sets up path and working directory."""
import os
import sys
from pathlib import Path

# Resolve project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Add src to Python path
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Change to project root so data/warehouse.db resolves correctly
os.chdir(str(PROJECT_ROOT))
