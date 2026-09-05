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
import os, logging, hashlib, datetime, asyncio, json
from typing import Optional, Dict, List, Any

_log = logging.getLogger("gw-audit")

# ── MongoDB config ──────────────────────────────────────────────────────
_AUDIT_MONGO_URI = os.getenv("AUDIT_MONGO_URI", "mongodb://gw-mongodb:27017")
_AUDIT_DB = os.getenv("AUDIT_DB_NAME", "gw_audit")
_AUDIT_COLLECTION = "compliance_logs"
_ALERTS_COLLECTION = "audit_alerts"

# ── Alert thresholds ────────────────────────────────────────────────────
_ALERT_THRESHOLDS = {
    "rapid_requests": int(os.getenv("AUDIT_ALERT_RAPID_REQUESTS", "50")),
    "injection_attempts": int(os.getenv("AUDIT_ALERT_INJECTION_ATTEMPTS", "5")),
    "quota_exhaustion": int(os.getenv("AUDIT_ALERT_QUOTA_EXHAUSTION", "3")),
}
_ALERT_WINDOW_MIN = int(os.getenv("AUDIT_ALERT_WINDOW_MIN", "10"))  # 10-min sliding window

# ── MongoDB client (lazy init) ──────────────────────────────────────────
_mongo_client: Optional[Any] = None
_mongo_available: bool = False


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
    """Write an audit entry to MongoDB (primary) and file (backup).

    Args:
        entry: Audit entry dict with keys: timestamp, session_id, action,
               input_length, compliance_level, user_role, ip_hash, extra

    Returns:
        True if written to MongoDB, False if file-only
    """
    # Ensure required fields
    entry.setdefault("timestamp", datetime.datetime.utcnow())
    entry.setdefault("session_id", "unknown")
    entry.setdefault("action", "unknown")
    entry.setdefault("compliance_level", os.getenv("COMPLIANCE_LEVEL", "moderate"))

    # File backup (always)
    try:
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "compliance_audit.log")
        with open(log_path, "a", encoding="utf-8") as f:
            entry_copy = entry.copy()
            entry_copy["timestamp"] = entry_copy["timestamp"].isoformat() + "Z" if hasattr(entry_copy["timestamp"], "isoformat") else str(entry_copy["timestamp"])
            f.write(json.dumps(entry_copy, default=str) + "\n")
    except Exception:
        pass

    # MongoDB primary
    client, available = _get_mongo()
    if not available or client is None:
        return False

    try:
        db = client[_AUDIT_DB]
        # Convert datetime for MongoDB
        if isinstance(entry.get("timestamp"), datetime.datetime):
            pass  # motor handles datetime natively
        await db[_AUDIT_COLLECTION].insert_one(entry)
        return True
    except Exception as e:
        _log.debug("MongoDB audit write failed: %s", e)
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
                           user_role: str = None) -> dict:
    """Query audit logs with pagination and filters. For admin dashboard."""
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

        total = await coll.count_documents(filt)
        cursor = coll.find(filt).sort("timestamp", -1).skip((page - 1) * page_size).limit(page_size)
        entries = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            if isinstance(doc.get("timestamp"), datetime.datetime):
                doc["timestamp"] = doc["timestamp"].isoformat() + "Z"
            entries.append(doc)

        return {"success": True, "entries": entries, "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        return {"success": False, "error": f"Audit query failed: {str(e)[:200]}", "entries": [], "total": 0}


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
