"""
v4.37: Unified Audit Extensions (Fix #3)

Additional functions appended to audit_mongo.py for:
  - unified_search(): Cross-source (llm/mcp/backend) query
  - log_mcp_event(): MCP tool call audit logging
  - log_backend_event(): Spring Boot backend operation audit
  - detect_anomalies(): Behavioral anomaly detection
  - write_shipped_event(): Log shipper event ingestion

These are appended to audit_mongo.py by deploy_v437.py.
"""
import datetime
from typing import Optional, Dict, List


async def unified_search(source: str = "all", user: str = None,
                         action: str = None, page: int = 1,
                         page_size: int = 50, q: str = None,
                         offset: int = None) -> dict:
    """Cross-source unified audit log search.

    Sources: llm (compliance_logs), mcp (mcp_audit), backend (backend_audit)

    R6.52 #1 additions:
      - q: full-text case-insensitive substring search across all string fields.
            For each matching entry, returns match_field (which field matched)
            and highlight (the value with **...** around the matched substring).
      - offset: skip N entries (alternative to page-based pagination, useful
               for incremental / infinite-scroll UIs).
    """
    from .audit_mongo import _get_mongo, _AUDIT_DB
    client, available = _get_mongo()
    if not available or client is None:
        return {"success": False, "error": "Audit database not available", "entries": [], "total": 0}

    try:
        db = client[_AUDIT_DB]
        collections = []
        if source in ("llm", "all"):
            collections.append("compliance_logs")
        if source in ("mcp", "all"):
            collections.append("mcp_audit")
        if source in ("backend", "all"):
            collections.append("backend_audit")

        # Build filter
        filt = {}
        if user:
            filt["$or"] = [
                {"session_id": user},
                {"user_id": user},
            ]
        if action:
            filt["action"] = {"$regex": action, "$options": "i"}

        # R6.52 #1: q = full-text across all string fields. Mongo side uses
        # $regex (case-insensitive) on each string field via $or.
        q_lower = (q or "").strip().lower()
        if q_lower:
            # Escape regex meta chars to prevent injection / ReDoS
            import re as _re_q
            q_pat = _re_q.escape(q_lower)
            string_fields = [
                "session_id", "user_id", "action", "endpoint", "method",
                "tool_name", "user_role", "source", "message",
                "arguments_summary", "result_summary",
            ]
            filt["$and"] = filt.get("$and", []) + [
                {"$or": [{f: {"$regex": q_pat, "$options": "i"}} for f in string_fields]}
            ]

        # Pagination: offset takes precedence if provided, else page-based.
        skip_n = offset if offset is not None else (page - 1) * page_size

        # Query each collection and merge
        all_entries = []
        for coll_name in collections:
            coll = db[coll_name]
            cursor = coll.find(filt).sort("timestamp", -1).skip(skip_n).limit(page_size)
            async for doc in cursor:
                doc["_id"] = str(doc["_id"])
                doc["_source"] = coll_name
                if isinstance(doc.get("timestamp"), datetime.datetime):
                    doc["timestamp"] = doc["timestamp"].isoformat() + "Z"

                # R6.52 #1: compute match_field + highlight for q matches
                if q_lower:
                    mf, hv = _first_string_match(doc, q_lower)
                    doc["match_field"] = mf
                    doc["highlight"] = hv
                else:
                    doc["match_field"] = None
                    doc["highlight"] = None

                all_entries.append(doc)

        # Sort merged results by timestamp descending
        all_entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        total = len(all_entries)

        return {
            "success": True,
            "source_filter": source,
            "entries": all_entries[:page_size],
            "total": total,
            "page": page if offset is None else (offset // page_size) + 1,
            "page_size": page_size,
            "offset": skip_n,
            "q": q or "",
        }
    except Exception as e:
        return {"success": False, "error": f"Unified search failed: {str(e)[:200]}", "entries": [], "total": 0}


def _first_string_match(doc: dict, q_lower: str) -> tuple:
    """Return (match_field, highlight) for the first field whose stringified
    value contains q_lower (case-insensitive). highlight wraps the match in **...**.

    Skips internal fields (_id, _source, match_field, highlight).
    """
    skip = {"_id", "_source", "match_field", "highlight", "timestamp"}
    for k, v in doc.items():
        if k in skip:
            continue
        if v is None:
            continue
        s = str(v)
        idx = s.lower().find(q_lower)
        if idx >= 0:
            end = idx + len(q_lower)
            highlight = s[:idx] + "**" + s[idx:end] + "**" + s[end:]
            # Truncate to 200 chars max to keep response payload sane.
            # Build the marked substring from the raw window first, THEN wrap
            # with "..." prefix/suffix so local_idx arithmetic stays consistent.
            if len(highlight) > 200:
                start = max(0, idx - 60)
                end_w = start + 200
                window = s[start:end_w]                   # raw 200 chars
                local_idx = idx - start                    # 0-based within window
                local_end = local_idx + len(q_lower)
                marked = (
                    window[:local_idx] + "**" +
                    window[local_idx:local_end] + "**" +
                    window[local_end:]
                )
                prefix = "" if start == 0 else "..."
                suffix = "" if end_w >= len(s) else "..."
                highlight = prefix + marked + suffix
            return k, highlight
    return None, None


async def log_mcp_event(tool_name: str, arguments: dict, result_summary: str,
                        session_id: str = "unknown", user_role: str = "unknown",
                        duration_ms: float = 0, success: bool = True) -> bool:
    """Log an MCP tool call to the mcp_audit collection."""
    from .audit_mongo import _get_mongo, _AUDIT_DB
    client, available = _get_mongo()
    if not available:
        return False

    try:
        entry = {
            "timestamp": datetime.datetime.utcnow(),
            "source": "mcp",
            "tool_name": tool_name,
            "arguments_summary": str(arguments)[:500],
            "result_summary": result_summary[:500],
            "session_id": session_id,
            "user_role": user_role,
            "duration_ms": duration_ms,
            "success": success,
        }
        db = client[_AUDIT_DB]
        await db["mcp_audit"].insert_one(entry)
        return True
    except Exception:
        return False


async def log_backend_event(endpoint: str, method: str, status_code: int,
                            user_id: str = "unknown", duration_ms: float = 0) -> bool:
    """Log a Spring Boot backend API event to the backend_audit collection."""
    from .audit_mongo import _get_mongo, _AUDIT_DB
    client, available = _get_mongo()
    if not available:
        return False

    try:
        entry = {
            "timestamp": datetime.datetime.utcnow(),
            "source": "backend",
            "endpoint": endpoint,
            "method": method,
            "status_code": status_code,
            "user_id": user_id,
            "duration_ms": duration_ms,
        }
        db = client[_AUDIT_DB]
        await db["backend_audit"].insert_one(entry)
        return True
    except Exception:
        return False


async def detect_anomalies() -> dict:
    """Detect behavioral anomalies across all audit collections."""
    from .audit_mongo import _get_mongo, _AUDIT_DB, _ALERT_WINDOW_MIN
    client, available = _get_mongo()
    if not available or client is None:
        return {"anomalies": [], "count": 0}

    now = datetime.datetime.utcnow()
    window_start = now - datetime.timedelta(minutes=_ALERT_WINDOW_MIN)
    anomalies = []

    try:
        db = client[_AUDIT_DB]

        # 1. High-frequency access pattern
        for coll_name in ["compliance_logs", "mcp_audit", "backend_audit"]:
            coll = db[coll_name]
            total = await coll.count_documents({"timestamp": {"$gte": window_start}})
            if total > 200:
                anomalies.append({
                    "type": "high_frequency",
                    "source": coll_name,
                    "detail": f"{total} events in {_ALERT_WINDOW_MIN}min (threshold: 200)",
                    "severity": "warning",
                })

        # 2. Error rate spike
        error_count = await db["compliance_logs"].count_documents({
            "timestamp": {"$gte": window_start},
            "action": {"$regex": "error|failed|blocked", "$options": "i"},
        })
        total_llm = await db["compliance_logs"].count_documents({"timestamp": {"$gte": window_start}})
        if total_llm > 10:
            error_rate = error_count / total_llm
            if error_rate > 0.3:
                anomalies.append({
                    "type": "error_rate_spike",
                    "detail": f"Error rate {error_rate:.1%} ({error_count}/{total_llm}) in {_ALERT_WINDOW_MIN}min",
                    "severity": "critical",
                })

        # 3. New user agent or IP pattern
        recent_ips = await db["compliance_logs"].distinct(
            "ip_hash", {"timestamp": {"$gte": window_start}}
        )
        if len(recent_ips) > 20:
            anomalies.append({
                "type": "distributed_access",
                "detail": f"{len(recent_ips)} distinct IPs in {_ALERT_WINDOW_MIN}min",
                "severity": "warning",
            })

        return {"anomalies": anomalies, "count": len(anomalies), "window_min": _ALERT_WINDOW_MIN}
    except Exception as e:
        return {"anomalies": [], "count": 0, "error": str(e)[:200]}


async def write_shipped_event(event: dict) -> bool:
    """Ingest a shipped log event from log-shipper.sh.

    The event dict should contain: source, timestamp, message
    Stored in the 'shipped_logs' collection for unified search.
    """
    from .audit_mongo import _get_mongo, _AUDIT_DB
    client, available = _get_mongo()
    if not available:
        return False

    try:
        entry = {
            "timestamp": datetime.datetime.utcnow(),
            "source": event.get("source", "unknown"),
            "message": event.get("message", "")[:2000],
        }
        db = client[_AUDIT_DB]
        await db["shipped_logs"].insert_one(entry)
        return True
    except Exception:
        return False
