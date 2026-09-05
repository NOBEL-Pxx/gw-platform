"""v4.38: Tests for config_manager.py (Fix #3)."""
import pytest
import sys, os

# Ensure pipeline is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import patch, MagicMock, AsyncMock
from pipeline.config_manager import ConfigManager, get_config_manager, _DEFAULTS


class TestConfigManager:
    """Unit tests for ConfigManager (no MongoDB required)."""

    def test_defaults_structure(self):
        """All three default namespaces should exist."""
        assert "ai" in _DEFAULTS
        assert "thresholds" in _DEFAULTS
        assert "bands" in _DEFAULTS
        assert "temperature" in _DEFAULTS["ai"]
        assert "spike_sigma" in _DEFAULTS["thresholds"]
        assert "surveys" in _DEFAULTS["bands"]

    def test_ai_defaults_reasonable(self):
        """AI defaults should be within valid ranges."""
        ai = _DEFAULTS["ai"]
        assert 0.0 <= ai["temperature"] <= 2.0
        assert ai["max_tokens"] >= 100
        assert ai["max_tool_rounds"] >= 1
        assert ai["total_timeout_sec"] >= 10

    def test_threshold_defaults_positive(self):
        """All thresholds should be positive."""
        t = _DEFAULTS["thresholds"]
        assert t["spike_sigma"] > 0
        assert t["dip_sigma"] > 0
        assert t["pattern_break_sigma"] > 0
        assert t["window_size"] > 0

    def test_bands_has_surveys(self):
        """Band config should include known surveys."""
        surveys = _DEFAULTS["bands"]["surveys"]
        assert "AliCPT" in surveys
        assert "DSS2" in surveys
        assert "NVSS" in surveys
        # All surveys should have priority, wavelength, color, bands
        for name, cfg in surveys.items():
            assert "priority" in cfg, f"{name} missing priority"
            assert "wavelength" in cfg, f"{name} missing wavelength"
            assert "bands" in cfg, f"{name} missing bands"

    @pytest.mark.asyncio
    async def test_get_config_falls_back_to_defaults(self):
        """Without MongoDB, get_config returns defaults."""
        mgr = ConfigManager()
        mgr._mongo_available = False
        mgr._client = None
        cfg = await mgr.get_config("ai")
        assert cfg["temperature"] == 0.3
        assert cfg["max_tokens"] == 1500

    @pytest.mark.asyncio
    async def test_reset_returns_defaults(self):
        """reset_to_default returns clean defaults."""
        mgr = ConfigManager()
        mgr._mongo_available = False
        cfg = await mgr.reset_to_default("ai")
        assert cfg["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_list_namespaces_without_mongo(self):
        """list_namespaces returns defaults-only when no MongoDB."""
        mgr = ConfigManager()
        mgr._mongo_available = False
        ns = await mgr.list_namespaces()
        assert len(ns) == 3
        for item in ns:
            assert item["source"] == "default"

    @pytest.mark.asyncio
    async def test_update_config_raises_without_mongo(self):
        """Cannot update when MongoDB is unavailable."""
        mgr = ConfigManager()
        mgr._mongo_available = False
        with pytest.raises(RuntimeError, match="MongoDB not available"):
            await mgr.update_config("ai", {"temperature": 0.8})

    def test_singleton(self):
        """get_config_manager returns same instance."""
        a = get_config_manager()
        b = get_config_manager()
        assert a is b
