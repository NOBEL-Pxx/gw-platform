"""v4.35: MongoDB Audit Log Persistence + Anomaly Alerting (Fix #6).

Provides:
  - Dual-write audit logging (MongoDB primary + JSONL file backup)
  - Anomaly detection thresholds with alert generation
  - Alert history with acknowledgement
  - Query API for admin dashboard

Alert thresholds (env-configurable):
  - rapid_requests: >50 requests/min from same IP → WARNING
  - injection_attempts: >5 blocked injections in 10min → CRITICAL
  - quota_exhaustion: >3 quota hits in 1 hour → WARNING
  - off_hours_access: Access between 02:00-05:00 UTC → INFO log
"""
import os, logging, hashlib, datetime, asyncio, json, re
from typing import Optional, Dict, List, Any

_log = logging.getLogger("gw-audit")

# ── MongoDB config ──────────────────────────────────────────────────────
_AUDIT_MONGO_URI = os.getenv("AUDIT_MONGO_URI", "mongodb://gw-mongodb:27017")
# R6.67.5: TTL retention (days). 0 = disable TTL. Default 90 days.
# CRITICAL #3 hotfix: defensive int parsing; falls back to defaults on bad env.
def _safe_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        return int(raw)
    except (ValueError, TypeError):
        _log.warning("Invalid %s=%r, falling back to %d", name, raw, default)
        return default

_AUDIT_TTL_DAYS = _safe_int_env("AUDIT_TTL_DAYS", 90)
_AUDIT_TTL_INDEX_NAME = "audit_ttl_ts"
_AUDIT_DB = os.getenv("AUDIT_DB_NAME", "gw_audit")
_AUDIT_COLLECTION = "compliance_logs"
_ALERTS_COLLECTION = "audit_alerts"
_AUDIT_HEALTH_RECHECK_SEC = _safe_int_env("AUDIT_HEALTH_RECHECK_SEC", 60)
# R6.66.3: explicit enable flag (default true). When false, file-only mode enforced.
_AUDIT_MONGO_ENABLED = os.getenv("AUDIT_MONGO_ENABLED", "true").lower() in ("true", "1", "yes")
_AUDIT_MONGO_URI = os.getenv("AUDIT_MONGO_URI", "mongodb://gw-mongodb:27017")

# ── Alert thresholds ────────────────────────────────────────────────────
_ALERT_THRESHOLDS = {
    "rapid_requests": _safe_int_env("AUDIT_ALERT_RAPID_REQUESTS", 50),
    "injection_attempts": _safe_int_env("AUDIT_ALERT_INJECTION_ATTEMPTS", 5),
    "quota_exhaustion": _safe_int_env("AUDIT_ALERT_QUOTA_EXHAUSTION", 3),
}
_ALERT_WINDOW_MIN = _safe_int_env("AUDIT_ALERT_WINDOW_MIN", 10)  # 10-min sliding window

# MongoDB client (lazy init with ping verification) -
# R6.66.3 state machine:
#   _mongo_client    - motor client or None
#   _mongo_available - last known good status (sticky until ping fails)
#   _last_ping_ts    - epoch seconds of last successful serverSelection ping
#   _last_ping_err   - most recent error string (for /health endpoint)
_mongo_client: Optional[Any] = None
_mongo_available: bool = False
_last_ping_ts: float = 0.0
_last_ping_err: Optional[str] = None
# R6.67.5: sticky flag so _ensure_indexes runs only once per process
_ttl_index_ready: bool = False


def is_enabled() -> bool:
    return _AUDIT_MONGO_ENABLED


def get_health() -> dict:
    return {
        "enabled": _AUDIT_MONGO_ENABLED,
        "available": _mongo_available,
        "uri": _AUDIT_MONGO_URI.split("@")[-1] if "@" in _AUDIT_MONGO_URI else _AUDIT_MONGO_URI,
        "database": _AUDIT_DB,
        "last_ping_ts": _last_ping_ts or None,
        "last_error": _last_ping_err,
        "mode": "mongo+file" if _mongo_available else "file-only",
        "ttl_days": _AUDIT_TTL_DAYS if _AUDIT_TTL_DAYS > 0 else None,
        "ttl_index_ready": _ttl_index_ready,
    }


async def _verify_mongo(client) -> bool:
    global _last_ping_ts, _last_ping_err
    try:
        await client.admin.command("ping")
        _last_ping_ts = datetime.datetime.utcnow().timestamp()
        _last_ping_err = None
        return True
    except Exception as e:
        _last_ping_err = f"{type(e).__name__}: {str(e)[:200]}"
        _log.debug("Mongo ping failed: %s", _last_ping_err)
        return False


async def _ensure_indexes(client) -> bool:
    """R6.67.5: ensure TTL index on `timestamp` field exists.

    Idempotent — Mongo silently no-ops if index already exists with same spec.
    Returns True on success or skip, False on error.
    """
    global _last_ping_err
    if _AUDIT_TTL_DAYS <= 0:
        _log.debug("AUDIT_TTL_DAYS=%d — TTL disabled", _AUDIT_TTL_DAYS)
        return True
    try:
        db = client[_AUDIT_DB]
        coll = db[_AUDIT_COLLECTION]
        # expireAfterSeconds is per-index; createIndex with same name is no-op
        await coll.create_index(
            [("timestamp", 1)],
            expireAfterSeconds=_AUDIT_TTL_DAYS * 86400,
            name=_AUDIT_TTL_INDEX_NAME,
        )
        return True
    except Exception as e:
        # HIGH #4 hotfix: detect "IndexOptionsConflict" / "IndexKeySpecsConflict"
        # which means an existing index with same name but different options.
        # That's a pre-existing deployment with different TTL — treat as
        # success-with-warning rather than retry-on-every-write churn.
        err_msg = str(e)
        if "IndexOptionsConflict" in err_msg or "IndexKeySpecsConflict" in err_msg:
            _log.warning(
                "TTL index %s already exists with different options; "
                "leaving existing index in place. Override via Mongo shell if needed: "
                "db.%s.runCommand({collMod: '%s', index: {name: '%s', expireAfterSeconds: %d}})",
                _AUDIT_TTL_INDEX_NAME, _AUDIT_COLLECTION, _AUDIT_COLLECTION,
                _AUDIT_TTL_INDEX_NAME, _AUDIT_TTL_DAYS * 86400,
            )
            return True
        _last_ping_err = f"ttl_index: {type(e).__name__}: {err_msg[:200]}"
        _log.warning("Failed to ensure TTL index: %s", e)
        # Don't return False — caller already saw the warning, and we want
        # _ttl_index_ready=True so we don't retry on every audit write.
        # The error remains visible via /pipeline/admin/audit/health.
        return False


async def _get_mongo_async():
    global _mongo_client, _mongo_available
    if not _AUDIT_MONGO_ENABLED:
        _mongo_available = False
        return _mongo_client, False
    if _mongo_client is None:
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            _mongo_client = AsyncIOMotorClient(_AUDIT_MONGO_URI, serverSelectionTimeoutMS=3000)
        except ImportError:
            _log.warning("motor not installed - audit log uses file-only mode")
            _mongo_available = False
            return None, False
        except Exception as e:
            _log.warning("MongoDB client construct failed: %s", e)
            _mongo_client = None
            _mongo_available = False
            _last_ping_err = str(e)[:200]
            return None, False
    if await _verify_mongo(_mongo_client):
        if not _mongo_available:
            _log.info("Audit MongoDB reachable: %s/%s", _AUDIT_DB, _AUDIT_COLLECTION)
        _mongo_available = True
        # R6.67.5: ensure TTL index once after Mongo becomes available
        global _ttl_index_ready
        if not _ttl_index_ready:
            if await _ensure_indexes(_mongo_client):
                _ttl_index_ready = True
                _log.info("Audit TTL index ready: %d days", _AUDIT_TTL_DAYS)
        return _mongo_client, True
    _mongo_available = False
    return _mongo_client, False


def _get_mongo():
    """Lazy-init MongoDB client."""
    global _mongo_client, _mongo_available
    if _mongo_client is not None:
        return _mongo_client, _mongo_available
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        _mongo_client = AsyncIOMotorClient(_AUDIT_MONGO_URI, serverSelectionTimeoutMS=3000)
        _mongo_available = True
        _log.info("Audit MongoDB connected: %s/%s", _AUDIT_DB, _AUDIT_COLLECTION)
    except ImportError:
        _log.warning("motor not installed — audit log uses file-only mode")
        _mongo_available = False
    except Exception as e:
        _log.warning("MongoDB audit connection failed: %s — using file-only mode", e)
        _mongo_available = False
        _mongo_client = None
    return _mongo_client, _mongo_available


async def write_audit_entry(entry: dict) -> bool:
    """Write audit entry: MongoDB (primary) AND file (backup).

    Returns True if written to MongoDB, False if file-only.

    R6.66.3:
      - Uses async ping-verified client (_get_mongo_async) instead of trusting
        a bare AsyncIOMotorClient ctor (motor's connect is lazy).
      - AUDIT_MONGO_ENABLED env flag can fully opt out (skips client creation).
      - Captures real ping/write errors into _last_ping_err for /health endpoint.
    """
    # Ensure required fields
    entry.setdefault("timestamp", datetime.datetime.utcnow())
    entry.setdefault("session_id", "unknown")
    entry.setdefault("action", "unknown")
    entry.setdefault("compliance_level", os.getenv("COMPLIANCE_LEVEL", "moderate"))

    # File backup (always; survives Mongo outage)
    try:
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "compliance_audit.log")
        with open(log_path, "a", encoding="utf-8") as f:
            entry_copy = entry.copy()
            ts = entry_copy["timestamp"]
            if hasattr(ts, "isoformat"):
                entry_copy["timestamp"] = ts.isoformat() + "Z"
            else:
                entry_copy["timestamp"] = str(ts)
            f.write(json.dumps(entry_copy, default=str) + "\n")
    except Exception as e:
        _log.debug("File audit write failed: %s", e)

    # MongoDB primary (R6.66.3: ping-verified async)
    if not _AUDIT_MONGO_ENABLED:
        return False
    client, available = await _get_mongo_async()
    if not available or client is None:
        return False

    try:
        db = client[_AUDIT_DB]
        await db[_AUDIT_COLLECTION].insert_one(entry)
        return True
    except Exception as e:
        global _last_ping_err, _mongo_available
        _last_ping_err = f"write: {type(e).__name__}: {str(e)[:200]}"
        _log.debug("MongoDB audit write failed: %s", e)
        _mongo_available = False  # force re-ping next time
        return False
async def check_alerts(entry: dict) -> List[dict]:
    """Check audit entry against alert thresholds. Returns list of triggered alerts."""
    client, available = _get_mongo()
    if not available or client is None:
        return []

    alerts = []
    now = datetime.datetime.utcnow()
    window_start = now - datetime.timedelta(minutes=_ALERT_WINDOW_MIN)

    try:
        db = client[_AUDIT_DB]
        coll = db[_AUDIT_COLLECTION]

        # 1. Rapid requests check
        if entry.get("ip_hash"):
            rapid_count = await coll.count_documents({
                "ip_hash": entry["ip_hash"],
                "timestamp": {"$gte": window_start},
            })
            if rapid_count >= _ALERT_THRESHOLDS["rapid_requests"]:
                alerts.append({
                    "level": "WARNING",
                    "type": "rapid_requests",
                    "detail": f"IP {entry['ip_hash']}: {rapid_count} requests in {_ALERT_WINDOW_MIN}min",
                    "timestamp": now,
                })

        # 2. Injection attempts check
        if entry.get("action") == "injection_blocked":
            inj_count = await coll.count_documents({
                "action": "injection_blocked",
                "timestamp": {"$gte": window_start},
            })
            if inj_count >= _ALERT_THRESHOLDS["injection_attempts"]:
                alerts.append({
                    "level": "CRITICAL",
                    "type": "injection_attack",
                    "detail": f"{inj_count} blocked injection attempts in {_ALERT_WINDOW_MIN}min",
                    "timestamp": now,
                })

        # 3. Quota exhaustion check
        if entry.get("action") in ("quota_exceeded", "agent_chat"):
            quota_hits = await coll.count_documents({
                "action": "quota_exceeded",
                "timestamp": {"$gte": now - datetime.timedelta(hours=1)},
            })
            if quota_hits >= _ALERT_THRESHOLDS["quota_exhaustion"]:
                alerts.append({
                    "level": "WARNING",
                    "type": "quota_exhaustion",
                    "detail": f"{quota_hits} quota exhaustion events in 1 hour",
                    "timestamp": now,
                })

        # 4. Off-hours access (log only, not alert)
        hour = now.hour
        if 2 <= hour < 5:
            _log.info("Off-hours audit: %s from %s at UTC %d:00",
                     entry.get("action"), entry.get("ip_hash", "?"), hour)

        # Persist alerts
        for alert in alerts:
            alert["acknowledged"] = False
            await db[_ALERTS_COLLECTION].insert_one(alert)
            _log.warning("AUDIT ALERT [%s]: %s - %s",
                        alert["level"], alert["type"], alert["detail"])

    except Exception as e:
        _log.debug("Alert check failed: %s", e)

    return alerts


async def query_audit_logs(page: int = 1, page_size: int = 50,
                           action: str = None, level: str = None,
                           user_role: str = None,
                           q: str = None) -> dict:
    """Query audit logs with pagination and filters. For admin dashboard.

    R6.67.3: added `q` parameter for full-text substring search across
    all string fields. Matching entries get `match_field` (the field
    that contained the match) and `highlight` (the value with **...**
    wrapping the matched substring, Sentry-style).
    """
    client, available = _get_mongo()
    if not available or client is None:
        return {"success": False, "error": "Audit database not available", "entries": [], "total": 0}

    try:
        db = client[_AUDIT_DB]
        coll = db[_AUDIT_COLLECTION]

        # Build filter
        filt = {}
        if action:
            filt["action"] = action
        if level:
            filt["compliance_level"] = level
        if user_role:
            filt["user_role"] = user_role

        # R6.67.3: full-text search via $regex (case-insensitive). For each
        # returned entry, scan string fields for first match and emit
        # match_field + highlight with **...** wrapping.
        if q and q.strip():
            pattern = re.compile(re.escape(q.strip()), re.IGNORECASE)
            # Mongo $regex with multiple OR'd fields
            string_fields = [
                "action", "session_id", "compliance_level", "user_role",
                "ip_hash", "user", "request_path", "method", "tool_name",
                "prompt_excerpt", "blocked_reason",
            ]
            filt["$or"] = [{f: {"$regex": pattern}} for f in string_fields]

        total = await coll.count_documents(filt)
        cursor = coll.find(filt).sort("timestamp", -1).skip((page - 1) * page_size).limit(page_size)
        entries = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            if isinstance(doc.get("timestamp"), datetime.datetime):
                doc["timestamp"] = doc["timestamp"].isoformat() + "Z"

            # R6.67.3: highlight = first matching field with **...** markers
            if q and q.strip():
                hit = _find_match_field(doc, q.strip())
                if hit:
                    field_name, field_value, matched_text = hit
                    doc["match_field"] = field_name
                    # Wrap matched substring with **...** (Sentry-style)
                    doc["highlight"] = _wrap_highlight(field_value, matched_text)

            entries.append(doc)

        return {"success": True, "entries": entries, "total": total,
                "page": page, "page_size": page_size}
    except Exception as e:
        return {"success": False, "error": f"Audit query failed: {str(e)[:200]}", "entries": [], "total": 0}


def _find_match_field(doc: dict, q: str):
    """Find first string field in doc that contains q (case-insensitive).

    Returns (field_name, field_value, matched_text) or None.
    """
    pattern = re.compile(re.escape(q), re.IGNORECASE)
    for key, val in doc.items():
        if key.startswith("_") or val is None:
            continue
        if not isinstance(val, str):
            continue
        m = pattern.search(val)
        if m:
            return (key, val, m.group(0))
    return None


def _wrap_highlight(value: str, matched: str) -> str:
    """Wrap first occurrence of `matched` (case-insensitive) with **...**.

    Returns the original string if no match (defensive).
    """
    if not matched:
        return value
    pattern = re.compile(re.escape(matched), re.IGNORECASE)
    return pattern.sub(lambda m: f"**{m.group(0)}**", value, count=1)


async def get_audit_stats() -> dict:
    """Get audit statistics for the admin dashboard."""
    client, available = _get_mongo()
    if not available or client is None:
        return {"success": False, "error": "Audit database not available"}

    try:
        db = client[_AUDIT_DB]
        coll = db[_AUDIT_COLLECTION]
        alerts_coll = db[_ALERTS_COLLECTION]

        now = datetime.datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        today_count = await coll.count_documents({"timestamp": {"$gte": today_start}})
        blocked_count = await coll.count_documents({"action": "injection_blocked", "timestamp": {"$gte": today_start}})
        active_users = len(await coll.distinct("session_id", {"timestamp": {"$gte": today_start}}))
        pending_alerts = await alerts_coll.count_documents({"acknowledged": False})

        # Role breakdown
        role_pipeline = [
            {"$match": {"timestamp": {"$gte": today_start}}},
            {"$group": {"_id": "$user_role", "count": {"$sum": 1}}},
        ]
        role_counts = {}
        async for doc in coll.aggregate(role_pipeline):
            role_counts[doc["_id"]] = doc["count"]

        return {
            "success": True,
            "today_requests": today_count,
            "blocked_injections": blocked_count,
            "active_users": active_users,
            "pending_alerts": pending_alerts,
            "role_breakdown": role_counts,
        }
    except Exception as e:
        return {"success": False, "error": f"Stats query failed: {str(e)[:200]}"}


async def get_recent_alerts(limit: int = 20) -> list:
    """Get recent (unacknowledged first) alerts."""
    client, available = _get_mongo()
    if not available or client is None:
        return []

    try:
        db = client[_AUDIT_DB]
        alerts_coll = db[_ALERTS_COLLECTION]
        cursor = alerts_coll.find().sort([("acknowledged", 1), ("timestamp", -1)]).limit(limit)
        alerts = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            if isinstance(doc.get("timestamp"), datetime.datetime):
                doc["timestamp"] = doc["timestamp"].isoformat() + "Z"
            alerts.append(doc)
        return alerts
    except Exception:
        return []
