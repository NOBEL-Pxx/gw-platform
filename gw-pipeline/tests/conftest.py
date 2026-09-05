"""Test fixtures for gw-pipeline."""
import pytest
from pathlib import Path

@pytest.fixture
def sample_fits_dir():
    return Path(__file__).parent / "data"
