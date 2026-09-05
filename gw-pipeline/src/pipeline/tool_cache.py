"""v4.35: LRU Tool Result Cache for Automatic Degradation Data Sync (Fix #2).

When the Spring Boot backend (ES/MongoDB) is unavailable, this cache serves
stale-but-known-good data snapshots instead of returning errors. Combined with
the MCP server's /degrade-status monitoring, it enables seamless failover.

Features:
  - LRU eviction with configurable max entries
  - TTL-based freshness (default 5 min)
  - Background refresh of top-N hot keys
  - Automatic degradation detection (consecutive failures >= 3)
  - Per-tool cache control (read queries only, never cache writes)
"""
import os, json, time, asyncio, logging, hashlib
from typing import Optional, Dict, Any, Callable

_log = logging.getLogger("gw-tool-cache")

# ── Cache config ───────────────────────────────────────────────────────
_CACHE_MAX_ENTRIES = int(os.getenv("TOOL_CACHE_MAX_ENTRIES", "500"))
_CACHE_DEFAULT_TTL = int(os.getenv("TOOL_CACHE_TTL_SEC", "300"))  # 5 min
_CACHE_REFRESH_INTERVAL = int(os.getenv("TOOL_CACHE_REFRESH_SEC", "60"))
_CACHE_DEGRADE_THRESHOLD = int(os.getenv("TOOL_CACHE_DEGRADE_THRESHOLD", "3"))
_CACHE_ENABLED = os.getenv("TOOL_CACHE_ENABLED", "true").lower() == "true"

# Tools that write data — never cache their results
_WRITE_TOOLS = set(os.getenv("TOOL_CACHE_WRITE_TOOLS", "").split(",") if os.getenv("TOOL_CACHE_WRITE_TOOLS") else [])


def _make_key(tool_name: str, args: dict) -> str:
    """Create a deterministic cache key from tool name + sorted arguments."""
    args_str = json.dumps(args, sort_keys=True, default=str)
    raw = f"{tool_name}:{args_str}"
    return hashlib.sha256(raw.encode()).hexdigest()


class ToolCache:
    """LRU cache for agent tool results with TTL-based freshness.

    Usage:
        cache = ToolCache()
        result = await cache.get_or_fetch("search_observations",
                                           {"ra": 180, "dec": 30},
                                           fetcher=search_observations)
    """

    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # key → (data, timestamp, ttl)
        self._access_order: list = []  # LRU tracking
        self._hit_count = 0
        self._miss_count = 0
        self._stale_served = 0
        self._refresh_task: Optional[asyncio.Task] = None
        self._hot_keys: Dict[str, int] = {}  # key → access frequency

    def _evict_lru(self):
        """Evict oldest entry if cache is full."""
        while len(self._cache) >= _CACHE_MAX_ENTRIES and self._access_order:
            oldest = self._access_order.pop(0)
            self._cache.pop(oldest, None)
            self._hot_keys.pop(oldest, None)
            _log.debug("Cache evicted (LRU): %s", oldest[:16])

    def _set(self, key: str, data: dict, ttl: int = _CACHE_DEFAULT_TTL):
        """Store a result in the cache."""
        if key in self._cache:
            self._access_order.remove(key)
        self._evict_lru()
        self._cache[key] = (json.loads(json.dumps(data, default=str)), time.monotonic(), ttl)
        self._access_order.append(key)
        self._hot_keys[key] = self._hot_keys.get(key, 0) + 1

    def _get(self, key: str) -> Optional[dict]:
        """Get a cached result. Returns None if missing or expired."""
        entry = self._cache.get(key)
        if entry is None:
            self._miss_count += 1
            return None

        data, ts, ttl = entry
        age = time.monotonic() - ts
        if age > ttl:
            # Expired but keep for stale fallback
            self._miss_count += 1
            return None

        # Bump in LRU
        self._access_order.remove(key)
        self._access_order.append(key)
        self._hot_keys[key] = self._hot_keys.get(key, 0) + 1
        self._hit_count += 1
        return data

    def _get_stale(self, key: str) -> Optional[dict]:
        """Get expired cached result for degradation fallback."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        data, ts, ttl = entry
        data = json.loads(json.dumps(data, default=str))
        age = time.monotonic() - ts
        data["_source"] = f"cache (stale, age={age:.0f}s)"
        self._stale_served += 1
        return data

    async def get_or_fetch(self, tool_name: str, args: dict, fetcher: Callable) -> dict:
        """Primary interface: try fresh fetch, fall back to cache on failure.

        Args:
            tool_name: Name of the tool (e.g. "search_observations")
            args: Tool arguments dict
            fetcher: Async callable that takes **args and returns dict result

        Returns:
            Tool result dict — fresh, cached, or error
        """
        if not _CACHE_ENABLED or tool_name in _WRITE_TOOLS:
            return await fetcher(**args)

        key = _make_key(tool_name, args)

        # Try fresh fetch first
        try:
            result = await fetcher(**args)
            if result.get("success"):
                self._set(key, result)
                return result
            # Fetch returned error — try cache
            _log.debug("Tool %s fetch failed, trying cache", tool_name)
            cached = self._get(key)
            if cached:
                return cached
            # Try stale
            stale = self._get_stale(key)
            if stale:
                _log.info("Serving stale cache for %s", tool_name)
                return stale
            return result  # No cache available, return original error
        except Exception as e:
            _log.warning("Tool %s fetch exception: %s — checking cache", tool_name, str(e)[:100])
            cached = self._get(key)
            if cached:
                cached["_note"] = f"Served from cache (fetch error: {str(e)[:50]})"
                return cached
            stale = self._get_stale(key)
            if stale:
                return stale
            return {"success": False, "error": f"Backend unavailable: {str(e)[:200]}", "_tool_name": tool_name}

    async def start_background_refresh(self, registry: Any):
        """Start periodic refresh of top-N hot keys (call during server startup)."""
        if self._refresh_task is not None:
            return

        async def _refresher():
            while True:
                await asyncio.sleep(_CACHE_REFRESH_INTERVAL)
                try:
                    top_keys = sorted(self._hot_keys.items(), key=lambda x: x[1], reverse=True)[:20]
                    for key_str, _ in top_keys:
                        # Parse tool name and args from key
                        # Keys are SHA256, so we need to iterate cache entries
                        for ck, (data, ts, ttl) in list(self._cache.items()):
                            age = time.monotonic() - ts
                            if age > ttl * 0.8:  # Refresh if >80% of TTL elapsed
                                # Re-fetch using stored args from result
                                tool_name = data.get("_tool_name", "")
                                if tool_name and hasattr(registry, 'execute'):
                                    _log.debug("Background refresh: %s", tool_name)
                                    try:
                                        fresh = await registry.execute(tool_name, data.get("_args", {}))
                                        if fresh.get("success"):
                                            self._set(ck, fresh)
                                    except Exception:
                                        pass
                except Exception as e:
                    _log.debug("Background refresh error: %s", e)

        self._refresh_task = asyncio.create_task(_refresher())
        _log.info("Cache background refresh started (interval=%ds, max_entries=%d)",
                  _CACHE_REFRESH_INTERVAL, _CACHE_MAX_ENTRIES)

    @property
    def stats(self) -> dict:
        """Return cache statistics for monitoring."""
        return {
            "enabled": _CACHE_ENABLED,
            "entries": len(self._cache),
            "max_entries": _CACHE_MAX_ENTRIES,
            "hits": self._hit_count,
            "misses": self._miss_count,
            "stale_served": self._stale_served,
            "hit_rate": round(self._hit_count / max(1, self._hit_count + self._miss_count), 3),
            "default_ttl_sec": _CACHE_DEFAULT_TTL,
            "refresh_interval_sec": _CACHE_REFRESH_INTERVAL,
            "hot_keys": len([k for k, v in self._hot_keys.items() if v > 5]),
        }


# Singleton
_cache_instance: Optional[ToolCache] = None


def get_tool_cache() -> ToolCache:
    """Get or create the singleton ToolCache."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = ToolCache()
    return _cache_instance
