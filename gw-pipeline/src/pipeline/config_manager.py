"""
v4.38: Configuration Manager (Fix #3)

MongoDB-backed config store with environment-variable defaults fallback.
Provides runtime-read/write AI platform configuration — no redeploy needed
for prompt changes, threshold tuning, or band configuration.

Namespaces:
  - ai           System prompt, temperature, max_tokens, model, etc.
  - thresholds   Anomaly classifier sigma values
  - bands        Survey band definitions (wavelength, color, priority)

Usage:
    from .config_manager import get_config_manager
    mgr = get_config_manager()
    ai_cfg = await mgr.get_config("ai")
"""

from __future__ import annotations
import os, logging, copy
from typing import Any, Dict, Optional

logger = logging.getLogger("gw.config-manager")

# ── Defaults (fallback when MongoDB is unavailable) ────────────────────

_DEFAULT_AI_CONFIG: Dict[str, Any] = {
    "system_prompt": (
        "You are the GravitationalWave AI Agent — an autonomous assistant "
        "for the GravitationalWave astronomical data platform.\n\n"
        "## Your Capabilities\n"
        "You have access to TOOLS that let you query databases, analyze FITS files, "
        "run deep learning inference, and inspect system state.\n\n"
        "## CRITICAL RULE: USE TOOLS TO GET REAL DATA\n"
        "Every factual claim MUST come from tool results. Never invent numbers.\n\n"
        "## STOP AFTER 2-3 ROUNDS\n"
        "After at most 2-3 rounds of tool calls, you MUST stop and write a final answer."
    ),
    "temperature": 0.3,
    "max_tokens": 1500,
    "model": os.getenv("DEEPSEEK_MODEL_VERSION", "deepseek-chat"),
    "max_tool_rounds": 10,
    "tool_result_max_chars": 4000,
    "total_timeout_sec": 300.0,
}

_DEFAULT_THRESHOLDS: Dict[str, Any] = {
    "spike_sigma": 5.0,
    "dip_sigma": 5.0,
    "pattern_break_sigma": 4.0,
    "window_size": 64,
    "dl_anomaly_z_threshold": 3.0,
    "dl_suspicious_z_threshold": 2.0,
    "fact_verifier_deviation_pct": 0.20,
}

_DEFAULT_BANDS: Dict[str, Any] = {
    "surveys": {
        "AliCPT": {"priority": 0, "wavelength": "mm-wave", "color": "#00F0FF", "bands": ["150 GHz"]},
        "Planck": {"priority": 1, "wavelength": "mm-wave", "color": "#FFB800", "bands": ["030 GHz", "044 GHz", "070 GHz", "100 GHz", "143 GHz", "217 GHz", "353 GHz", "545 GHz", "857 GHz"]},
        "DSS2": {"priority": 2, "wavelength": "optical", "color": "#00E676", "bands": ["Blue", "Green", "Red"]},
        "2MASS": {"priority": 3, "wavelength": "near-IR", "color": "#FA8C16", "bands": ["J", "H", "K"]},
        "allWISE": {"priority": 4, "wavelength": "mid-IR", "color": "#FF006E", "bands": ["W1", "W2", "W4"]},
        "LEGACY": {"priority": 5, "wavelength": "optical", "color": "#00E676", "bands": ["g", "r", "i", "z"]},
        "NVSS": {"priority": 6, "wavelength": "radio", "color": "#7C3AED", "bands": ["1.4 GHz"]},
        "FIRST": {"priority": 7, "wavelength": "radio", "color": "#7C3AED", "bands": ["1.4 GHz"]},
        "ZTF": {"priority": 8, "wavelength": "optical", "color": "#FF4F00", "bands": ["g", "r", "i"]},
    }
}

_DEFAULTS = {
    "ai": _DEFAULT_AI_CONFIG,
    "thresholds": _DEFAULT_THRESHOLDS,
    "bands": _DEFAULT_BANDS,
}

_CONFIG_DB = os.getenv("GW_CONFIG_DB", "gw_config")
_COLLECTION_NAME = "platform_config"


class ConfigManager:
    """Read/write platform configuration with MongoDB persistence.

    On startup, loads from MongoDB. Falls back to hardcoded defaults if
    MongoDB is unreachable.  All writes are immediately persisted.
    """

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._mongo_available = False
        self._client = None

    async def _ensure_mongo(self):
        """Lazy-connect to MongoDB. Called on first access."""
        if self._client is not None:
            return
        try:
            import motor.motor_asyncio
            mongo_url = os.getenv("GW_MONGO_URL", "mongodb://mongodb:27017")
            self._client = motor.motor_asyncio.AsyncIOMotorClient(
                mongo_url, serverSelectionTimeoutMS=3000
            )
            # Test connection
            await self._client.admin.command("ping")
            self._mongo_available = True
            logger.info("ConfigManager: MongoDB connected")
        except Exception as e:
            logger.warning("ConfigManager: MongoDB unavailable (%s), using defaults", e)
            self._mongo_available = False
            self._client = None

    async def get_config(self, namespace: str) -> Dict[str, Any]:
        """Get config for a namespace. Merges DB overrides onto defaults."""
        await self._ensure_mongo()

        defaults = copy.deepcopy(_DEFAULTS.get(namespace, {}))
        if not self._mongo_available or self._client is None:
            return defaults

        try:
            db = self._client[_CONFIG_DB]
            doc = await db[_COLLECTION_NAME].find_one({"_id": namespace})
            if doc:
                # Merge stored values over defaults
                stored = {k: v for k, v in doc.items() if not k.startswith("_")}
                defaults.update(stored)
        except Exception as e:
            logger.error("ConfigManager: get_config(%s) failed: %s", namespace, e)

        return defaults

    async def update_config(self, namespace: str, values: Dict[str, Any]) -> Dict[str, Any]:
        """Update config values for a namespace. Returns the merged result."""
        await self._ensure_mongo()
        if not self._mongo_available or self._client is None:
            raise RuntimeError("MongoDB not available — cannot persist config")

        try:
            db = self._client[_CONFIG_DB]
            # Use upsert to create if not exists
            update_doc = {"_id": namespace}
            update_doc.update(values)
            await db[_COLLECTION_NAME].replace_one(
                {"_id": namespace}, update_doc, upsert=True
            )
            logger.info("ConfigManager: Updated %s config (%d keys)", namespace, len(values))
            return await self.get_config(namespace)
        except Exception as e:
            logger.error("ConfigManager: update_config(%s) failed: %s", namespace, e)
            raise

    async def reset_to_default(self, namespace: str) -> Dict[str, Any]:
        """Reset a namespace to hardcoded defaults."""
        await self._ensure_mongo()
        if self._mongo_available and self._client is not None:
            try:
                db = self._client[_CONFIG_DB]
                await db[_COLLECTION_NAME].delete_one({"_id": namespace})
            except Exception as e:
                logger.error("ConfigManager: reset(%s) failed: %s", namespace, e)
        return copy.deepcopy(_DEFAULTS.get(namespace, {}))

    async def list_namespaces(self) -> list:
        """List all available config namespaces with their source."""
        await self._ensure_mongo()
        result = []
        stored_ns = set()
        if self._mongo_available and self._client is not None:
            try:
                db = self._client[_CONFIG_DB]
                async for doc in db[_COLLECTION_NAME].find({}):
                    ns = doc["_id"]
                    stored_ns.add(ns)
                    result.append({"namespace": ns, "source": "mongodb", "keys": len(doc) - 1})
            except Exception:
                pass
        for ns in _DEFAULTS:
            if ns not in stored_ns:
                result.append({"namespace": ns, "source": "default", "keys": len(_DEFAULTS[ns])})
        return result


# ── Singleton ───────────────────────────────────────────────────────────

_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Return the singleton ConfigManager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
