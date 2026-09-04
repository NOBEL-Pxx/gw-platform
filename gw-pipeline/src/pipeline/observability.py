"""
R6.44: Observability persistence layer.

Stores font-load errors and A/B test metrics from frontend in a local
SQLite + JSON file backend. Provides aggregate queries for the dashboard
endpoints (R6.44 todo 1 + todo 3).

Why SQLite + JSON (and not Sentry SDK):
- Lab deployment with no external DSN / account
- Need full data ownership (compliance)
- Local file system already mounted via Docker volume
- Sentry SDK has privacy / egress concerns unsuitable for a research platform

Schema:
    font_errors(id, family, weight, src, url, user_agent, timestamp)
    ab_metrics(id, group_name, load_time_ms, fcp, cls, page, user_id, timestamp)

Storage location:
    /app/observability/observability.db      (SQLite)
    /app/observability/font_errors.jsonl     (append-only, for debugging)
    /app/observability/ab_metrics.jsonl      (append-only, for debugging)

Aggregation rules:
    - Keep all raw samples for replay / forensic
    - Dashboard queries compute aggregates on demand (median/p95)
    - Auto-flag ab_analysis_ready.json when 100+ samples reached
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time as _time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gw.observability")

# R6.51: cursor-based pagination helpers
import base64 as _base64


def _encode_cursor(ts_ms: int, row_id: int) -> str:
    """Encode (ts, id) tuple to opaque cursor string."""
    raw = f"{int(ts_ms)}:{int(row_id)}".encode("utf-8")
    return _base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple:
    """Decode cursor to (ts_ms, id). Returns None on malformed input."""
    try:
        pad = "=" * (-len(cursor) % 4)
        raw = _base64.urlsafe_b64decode(cursor + pad).decode("utf-8")
        ts_str, id_str = raw.split(":", 1)
        return (int(ts_str), int(id_str))
    except Exception:
        return None

# ── Storage paths (Docker volume) ─────────────────────────────────
# R6.51: Try user-supplied OBSERVABILITY_DIR first; fall back to /tmp/observability if /app is read-only
_obs_env = os.getenv("OBSERVABILITY_DIR")
if _obs_env:
    _OBS_DIR = Path(_obs_env)
else:
    _default = Path("/app/observability")
    try:
        _default.mkdir(parents=True, exist_ok=True)
        _OBS_DIR = _default
    except (OSError, PermissionError):
        _OBS_DIR = Path("/tmp/observability")
        _OBS_DIR.mkdir(parents=True, exist_ok=True)
_DB_PATH = _OBS_DIR / "observability.db"
_JSONL_FONT = _OBS_DIR / "font_errors.jsonl"
_JSONL_AB = _OBS_DIR / "ab_metrics.jsonl"
_ANALYSIS_FLAG = _OBS_DIR / "ab_analysis_ready.json"
_LOCK = threading.Lock()

# R6.46: Alert engine constants
# A font (family, weight) with more than FONT_ERROR_RATE_THRESHOLD errors
# within FONT_ERROR_RATE_WINDOW_MS (default 10/min) fires a high_error_rate alert.
_FONT_ERROR_RATE_THRESHOLD = int(os.getenv('FONT_ERROR_RATE_THRESHOLD', '10'))
_FONT_ERROR_RATE_WINDOW_MS = int(os.getenv('FONT_ERROR_RATE_WINDOW_MS', '60000'))
# Cooldown: same alert key won't refire within this window (5 min default).
_FONT_ERROR_ALERT_COOLDOWN_MS = int(os.getenv('FONT_ERROR_ALERT_COOLDOWN_MS', '300000'))
# PagerDuty Events API v2 (optional). Set PAGERDUTY_ROUTING_KEY to enable.
_PAGERDUTY_WEBHOOK_URL = os.getenv('PAGERDUTY_WEBHOOK_URL', '').strip()
_PAGERDUTY_ROUTING_KEY = os.getenv('PAGERDUTY_ROUTING_KEY', '').strip()

# R6.47: Multi-tenant alert routing - JSON-encoded env mapping family -> PD routing key.
# Example: PAGERDUTY_ROUTING_TABLE = '{"Inter":"rkey_inter_xxx","JetBrains Mono":"rkey_jbm_yyy"}'
# If a family is not in the table, _PAGERDUTY_ROUTING_KEY is used as fallback.
_PAGERDUTY_ROUTING_TABLE = {}
_routing_table_raw = os.getenv('PAGERDUTY_ROUTING_TABLE', '').strip()
if _routing_table_raw:
    try:
        import json as _json_rt
        _PAGERDUTY_ROUTING_TABLE = _json_rt.loads(_routing_table_raw)
    except Exception as _rt_err:
        logger.warning('PAGERDUTY_ROUTING_TABLE parse failed (non-fatal): %s', _rt_err)

# R6.46: AB history bucketing defaults
_DEFAULT_HISTORY_BUCKET_MS = 3600000       # 1h
_DEFAULT_HISTORY_WINDOW_MS = 7 * 86400000   # 7d
_MAX_HISTORY_BUCKETS = 720                  # safety cap (30d at 1h)


def _ensure_dir() -> None:
    """Create observability dir + initialize SQLite tables."""
    _OBS_DIR.mkdir(parents=True, exist_ok=True)
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS font_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family TEXT NOT NULL,
                weight TEXT NOT NULL,
                src TEXT,
                url TEXT,
                user_agent TEXT,
                timestamp INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_font_ts ON font_errors(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_font_family ON font_errors(family, weight);

            CREATE TABLE IF NOT EXISTS ab_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL,
                load_time_ms REAL,
                fcp REAL,
                cls REAL,
                page TEXT,
                user_id TEXT,
                timestamp INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ab_group ON ab_metrics(group_name, timestamp DESC);

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                alert_key TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT,
                fired_at INTEGER NOT NULL,
                dismissed_at INTEGER,
                pagerduty_dedup_key TEXT,
                last_value REAL,
                occurrences INTEGER DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_fired ON alerts(fired_at DESC);
            CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(type, dismissed_at);

            CREATE TABLE IF NOT EXISTS alert_routing (
                family TEXT PRIMARY KEY,
                pagerduty_routing_key TEXT NOT NULL,
                team_email TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_alert_routing_team ON alert_routing(team_email);

            -- R6.49: audit log for routing changes
            CREATE TABLE IF NOT EXISTS alert_routing_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('upsert','delete')),
                actor TEXT NOT NULL,
                before_json TEXT,
                after_json TEXT,
                ts INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_routing_audit_ts ON alert_routing_audit(ts DESC);
            CREATE INDEX IF NOT EXISTS idx_routing_audit_family ON alert_routing_audit(family, ts DESC);
        """)
        conn.commit()


def record_font_error(
    family: str,
    weight: str,
    src: str = "",
    url: str = "",
    user_agent: str = "",
    timestamp: Optional[int] = None,
) -> Dict[str, Any]:
    """Persist a font-load error from frontend useFontMonitor."""
    _ensure_dir()
    ts = timestamp or int(_time.time() * 1000)
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO font_errors (family, weight, src, url, user_agent, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (family, weight, src, url, user_agent, ts),
        )
        conn.commit()
    # Append JSONL
    try:
        with _JSONL_FONT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "family": family, "weight": weight, "src": src,
                "url": url, "user_agent": user_agent, "timestamp": ts,
            }) + "\n")
    except Exception as e:
        logger.warning("font_errors.jsonl append failed: %s", e)

    # R6.46: lightweight alert check (rate-limited internally via cooldown)
    try:
        check_font_error_alerts()
    except Exception as e:
        logger.warning("check_font_error_alerts failed (non-fatal): %s", e)

    return {"recorded": True, "timestamp": ts}


def record_ab_metric(
    group_name: str,
    load_time_ms: Optional[float],
    fcp: Optional[float] = None,
    cls: Optional[float] = None,
    page: str = "",
    user_id: str = "",
    timestamp: Optional[int] = None,
) -> Dict[str, Any]:
    """Persist an A/B test sample from frontend useFontABTest."""
    _ensure_dir()
    ts = timestamp or int(_time.time() * 1000)
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO ab_metrics (group_name, load_time_ms, fcp, cls, page, user_id, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (group_name, load_time_ms, fcp, cls, page, user_id, ts),
        )
        cur = conn.execute("SELECT COUNT(*) FROM ab_metrics")
        total = cur.fetchone()[0]
        conn.commit()

    try:
        with _JSONL_AB.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "group": group_name, "load_time_ms": load_time_ms,
                "fcp": fcp, "cls": cls, "page": page,
                "user_id": user_id, "timestamp": ts,
            }) + "\n")
    except Exception as e:
        logger.warning("ab_metrics.jsonl append failed: %s", e)

    # Auto-flag analysis ready at 100+ samples (and every 50 thereafter)
    if total >= 100 and total % 50 == 0:
        try:
            _ANALYSIS_FLAG.write_text(json.dumps({
                "ready": True,
                "total_samples": total,
                "flagged_at": int(_time.time()),
            }), encoding="utf-8")
            logger.info("AB analysis ready: total_samples=%d", total)
        except Exception:
            pass

    return {"recorded": True, "timestamp": ts, "total_samples": total}


def query_font_errors(
    family: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Return recent font errors (newest first)."""
    _ensure_dir()
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if family:
            rows = conn.execute(
                "SELECT * FROM font_errors WHERE family = ? ORDER BY timestamp DESC LIMIT ?",
                (family, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM font_errors ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def query_font_error_stats() -> Dict[str, Any]:
    """Aggregate font errors by family + weight."""
    _ensure_dir()
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT family, weight, COUNT(*) as count, MAX(timestamp) as last_seen "
            "FROM font_errors GROUP BY family, weight ORDER BY count DESC",
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM font_errors").fetchone()[0]
    return {
        "total": total,
        "by_family_weight": [dict(r) for r in rows],
    }


def _percentile(values: List[float], p: float) -> float:
    """Compute p-th percentile (0-100). Empty list returns 0."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(len(s) * p / 100)))
    return s[idx]


def query_ab_dashboard() -> Dict[str, Any]:
    """R6.44 todo 3: backend A/B test dashboard."""
    _ensure_dir()
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT group_name, load_time_ms, fcp, cls FROM ab_metrics",
        ).fetchall()

    by_group: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        g = r["group_name"]
        for k in ("load_time_ms", "fcp", "cls"):
            v = r[k]
            if v is not None:
                by_group[g][k].append(float(v))

    summary: Dict[str, Any] = {}
    for g, metrics in by_group.items():
        summary[g] = {
            "count": len(metrics["load_time_ms"]),
            "load_time_ms": {
                "avg": round(sum(metrics["load_time_ms"]) / len(metrics["load_time_ms"]), 2)
                if metrics["load_time_ms"] else 0,
                "median": _percentile(metrics["load_time_ms"], 50),
                "p95": _percentile(metrics["load_time_ms"], 95),
            },
            "fcp_ms": {
                "avg": round(sum(metrics["fcp"]) / len(metrics["fcp"]), 2)
                if metrics["fcp"] else 0,
                "p95": _percentile(metrics["fcp"], 95),
            },
            "cls": {
                "avg": round(sum(metrics["cls"]) / len(metrics["cls"]), 4)
                if metrics["cls"] else 0,
                "p95": _percentile(metrics["cls"], 95),
            },
        }

    total = sum(s["count"] for s in summary.values())
    winner: Optional[str] = None
    delta_ms: float = 0.0
    if "woff2" in summary and "system" in summary:
        a = summary["woff2"]["load_time_ms"]["median"]
        b = summary["system"]["load_time_ms"]["median"]
        if a > 0 and b > 0 and min(summary["woff2"]["count"], summary["system"]["count"]) >= 30:
            if a < b * 0.95:
                winner = "woff2"
                delta_ms = round(b - a, 2)
            elif b < a * 0.95:
                winner = "system"
                delta_ms = round(a - b, 2)

    analysis_ready = False
    if _ANALYSIS_FLAG.exists():
        try:
            analysis_ready = json.loads(_ANALYSIS_FLAG.read_text(encoding="utf-8")).get("ready", False)
        except Exception:
            pass

    return {
        "total_samples": total,
        "analysis_ready": analysis_ready,
        "groups": summary,
        "winner": winner,
        "winner_delta_ms": delta_ms,
        "queried_at": int(_time.time()),
    }




def query_ab_history(bucket_ms: int = _DEFAULT_HISTORY_BUCKET_MS,
                     window_ms: int = _DEFAULT_HISTORY_WINDOW_MS) -> Dict[str, Any]:
    """Return time-bucketed AB metrics for charting winner drift.

    Args:
        bucket_ms: bucket size in ms (default 1h, range 1min..1day).
        window_ms: lookback window in ms (default 7d, range 1h..30d).

    Returns dict with key "buckets": list of {bucket_ts, woff2_count, woff2_load_median_ms,
    woff2_load_avg_ms, woff2_fcp_avg_ms, woff2_cls_avg, system_count, system_load_median_ms,
    system_load_avg_ms, system_fcp_avg_ms, system_cls_avg, winner, delta_ms}.
    """
    _ensure_dir()
    bucket_ms = max(60_000, min(bucket_ms, 86_400_000))
    window_ms = max(bucket_ms, min(window_ms, 30 * 86_400_000))
    now_ms = int(_time.time() * 1000)
    since_ms = now_ms - window_ms

    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT group_name, load_time_ms, fcp, cls, timestamp "
            "FROM ab_metrics WHERE timestamp >= ? AND timestamp < ?",
            (since_ms, now_ms),
        ).fetchall()

    per_group: Dict[str, Dict[int, Dict[str, List[float]]]] = {
        "woff2": defaultdict(lambda: defaultdict(list)),
        "system": defaultdict(lambda: defaultdict(list)),
    }
    for r in rows:
        g = r["group_name"]
        if g not in per_group:
            continue
        b = (int(r["timestamp"]) // bucket_ms) * bucket_ms
        if r["load_time_ms"] is not None:
            per_group[g][b]["load"].append(float(r["load_time_ms"]))
        if r["fcp"] is not None:
            per_group[g][b]["fcp"].append(float(r["fcp"]))
        if r["cls"] is not None:
            per_group[g][b]["cls"].append(float(r["cls"]))

    all_buckets = sorted(set(per_group["woff2"].keys()) | set(per_group["system"].keys()))

    def _median(values: List[float]) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        return s[max(0, min(len(s) - 1, len(s) // 2))]

    def _avg(values: List[float]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    buckets_out = []
    for b in all_buckets:
        w = per_group["woff2"].get(b, {})
        s = per_group["system"].get(b, {})
        w_med = _median(w.get("load", []))
        s_med = _median(s.get("load", []))
        winner = None
        delta_ms = 0.0
        if w_med > 0 and s_med > 0 and len(w.get("load", [])) >= 5 and len(s.get("load", [])) >= 5:
            if w_med < s_med * 0.95:
                winner = "woff2"
                delta_ms = round(s_med - w_med, 2)
            elif s_med < w_med * 0.95:
                winner = "system"
                delta_ms = round(w_med - s_med, 2)
            else:
                winner = "tie"
                delta_ms = round(abs(s_med - w_med), 2)
        buckets_out.append({
            "bucket_ts": b,
            "woff2_count": len(w.get("load", [])),
            "woff2_load_median_ms": w_med,
            "woff2_load_avg_ms": _avg(w.get("load", [])),
            "woff2_fcp_avg_ms": _avg(w.get("fcp", [])),
            "woff2_cls_avg": _avg(w.get("cls", [])),
            "system_count": len(s.get("load", [])),
            "system_load_median_ms": s_med,
            "system_load_avg_ms": _avg(s.get("load", [])),
            "system_fcp_avg_ms": _avg(s.get("fcp", [])),
            "system_cls_avg": _avg(s.get("cls", [])),
            "winner": winner,
            "delta_ms": delta_ms,
        })

    return {
        "bucket_ms": bucket_ms,
        "window_ms": window_ms,
        "buckets": buckets_out[-_MAX_HISTORY_BUCKETS:],
        "queried_at": now_ms,
    }


def _post_pagerduty(payload: Dict[str, Any]) -> bool:
    """Best-effort PagerDuty Events API v2 post. Returns True on 202.
    Routing key is read from payload['routing_key'] (R6.47 multi-tenant).
    Webhook URL still comes from env (single endpoint)."""
    if not _PAGERDUTY_WEBHOOK_URL:
        return False
    if not payload.get('routing_key'):
        return False
    try:
        import httpx
        with httpx.Client(timeout=5.0) as c:
            r = c.post(_PAGERDUTY_WEBHOOK_URL, json=payload)
            return r.status_code == 202
    except Exception as e:
        logger.warning('PagerDuty post failed (non-fatal): %s', e)
        return False


def check_font_error_alerts() -> List[Dict[str, Any]]:
    """Fire high_error_rate alerts when font error count exceeds threshold in window."""
    _ensure_dir()
    now_ms = int(_time.time() * 1000)
    since_ms = now_ms - _FONT_ERROR_RATE_WINDOW_MS

    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        recent = conn.execute(
            "SELECT family, weight, COUNT(*) as cnt, MAX(timestamp) as last_seen "
            "FROM font_errors WHERE timestamp >= ? GROUP BY family, weight HAVING cnt >= ?",
            (since_ms, _FONT_ERROR_RATE_THRESHOLD),
        ).fetchall()
        if not recent:
            return []

        cooldown_cutoff = now_ms - _FONT_ERROR_ALERT_COOLDOWN_MS
        fired = []
        for r in recent:
            alert_key = "high_error_rate::" + str(r["family"]) + "::" + str(r["weight"])
            existing = conn.execute(
                "SELECT id, fired_at FROM alerts WHERE alert_key = ? AND dismissed_at IS NULL "
                "ORDER BY fired_at DESC LIMIT 1",
                (alert_key,),
            ).fetchone()
            if existing and existing["fired_at"] >= cooldown_cutoff:
                continue
            message = (
                "Font " + str(r["family"]) + " weight " + str(r["weight"]) +
                " has " + str(r["cnt"]) + " load errors in the last " +
                str(_FONT_ERROR_RATE_WINDOW_MS // 1000) + "s (threshold " +
                str(_FONT_ERROR_RATE_THRESHOLD) + "). Last seen at " + str(r["last_seen"]) + "."
            )
            cur = conn.execute(
                "INSERT INTO alerts (type, alert_key, severity, message, fired_at, "
                "pagerduty_dedup_key, last_value, occurrences) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "high_error_rate",
                    alert_key,
                    "warning",
                    message,
                    now_ms,
                    alert_key + "::" + str(now_ms // _FONT_ERROR_ALERT_COOLDOWN_MS),
                    float(r["cnt"]),
                    r["cnt"],
                ),
            )
            conn.commit()
            fired.append({
                "id": cur.lastrowid,
                "type": "high_error_rate",
                "alert_key": alert_key,
                "severity": "warning",
                "message": message,
                "fired_at": now_ms,
                "count": r["cnt"],
                "family": r["family"],
                "weight": r["weight"],
            })

    # R6.47: per-family PagerDuty routing key lookup (multi-tenant).
    # Priority: PAGERDUTY_ROUTING_TABLE[family] -> alert_routing DB row -> _PAGERDUTY_ROUTING_KEY fallback.
    def _resolve_routing_key(family_val):
        if family_val in _PAGERDUTY_ROUTING_TABLE:
            return _PAGERDUTY_ROUTING_TABLE[family_val]
        try:
            with _LOCK, sqlite3.connect(_DB_PATH) as conn2:
                row = conn2.execute(
                    "SELECT pagerduty_routing_key FROM alert_routing WHERE family = ?",
                    (family_val,),
                ).fetchone()
                if row and row[0]:
                    return str(row[0])
        except Exception as _rk_err:
            logger.warning('alert_routing lookup failed (non-fatal): %s', _rk_err)
        return _PAGERDUTY_ROUTING_KEY

    for alert in fired:
        routing_key = _resolve_routing_key(str(alert['family']))
        if not routing_key:
            continue
        payload = {
            'routing_key': routing_key,
            'event_action': 'trigger',
            'dedup_key': alert['alert_key'] + '::' + routing_key,
            'payload': {
                'summary': alert['message'][:1024],
                'source': 'gw-frontend',
                'severity': alert['severity'],
                'timestamp': _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime(alert['fired_at'] / 1000)),
                'custom_details': {
                    'family': alert['family'],
                    'weight': alert['weight'],
                    'error_count': alert['count'],
                    'window_seconds': _FONT_ERROR_RATE_WINDOW_MS // 1000,
                    'threshold': _FONT_ERROR_RATE_THRESHOLD,
                    'routed_to_family_key': bool(routing_key != _PAGERDUTY_ROUTING_KEY),
                },
            },
        }
        if _post_pagerduty(payload):
            logger.info('PagerDuty alert fired: %s -> rkey=%s', alert['alert_key'], routing_key[:8] + '...' if len(routing_key) > 8 else routing_key)
    return fired


def get_alert_routing() -> List[Dict[str, Any]]:
    """List all family -> PagerDuty routing mappings (DB-backed only)."""
    _ensure_dir()
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT family, pagerduty_routing_key, team_email, created_at, updated_at "
            "FROM alert_routing ORDER BY family ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_alert_routing(family: str, pagerduty_routing_key: str, team_email: str = '', actor: str = 'anonymous') -> Dict[str, Any]:
    """Insert or update routing for a family. R6.49: records audit entry."""
    _ensure_dir()
    now_ms = int(_time.time() * 1000)
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        # Capture before snapshot for audit
        before_row = conn.execute(
            "SELECT family, pagerduty_routing_key, team_email, created_at, updated_at "
            "FROM alert_routing WHERE family = ?", (family,)
        ).fetchone()
        before_dict = dict(before_row) if before_row else None

        conn.execute(
            "INSERT INTO alert_routing (family, pagerduty_routing_key, team_email, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(family) DO UPDATE SET "
            "  pagerduty_routing_key = excluded.pagerduty_routing_key, "
            "  team_email = excluded.team_email, "
            "  updated_at = excluded.updated_at",
            (family, pagerduty_routing_key, team_email, now_ms, now_ms),
        )
        after_dict = {'family': family, 'pagerduty_routing_key': pagerduty_routing_key, 'team_email': team_email, 'updated_at': now_ms}
        # R6.49: audit log entry
        try:
            import json as _json
            conn.execute(
                "INSERT INTO alert_routing_audit (family, action, actor, before_json, after_json, ts) "
                "VALUES (?, 'upsert', ?, ?, ?, ?)",
                (family, actor, _json.dumps(before_dict) if before_dict else None, _json.dumps(after_dict), now_ms),
            )
        except Exception as _ae:
            logger.warning('audit write failed (non-fatal): %s', _ae)
        conn.commit()
    return after_dict
    """Insert or update routing for a family."""
    _ensure_dir()
    now_ms = int(_time.time() * 1000)
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO alert_routing (family, pagerduty_routing_key, team_email, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(family) DO UPDATE SET "
            "  pagerduty_routing_key = excluded.pagerduty_routing_key, "
            "  team_email = excluded.team_email, "
            "  updated_at = excluded.updated_at",
            (family, pagerduty_routing_key, team_email, now_ms, now_ms),
        )
        conn.commit()
    return {'family': family, 'pagerduty_routing_key': pagerduty_routing_key, 'team_email': team_email, 'updated_at': now_ms}


def delete_alert_routing(family: str, actor: str = 'anonymous') -> Dict[str, Any]:
    """Remove routing entry; alerts will fall back to default routing key.
    R6.49: records audit entry."""
    _ensure_dir()
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        # Capture before snapshot for audit
        before_row = conn.execute(
            "SELECT family, pagerduty_routing_key, team_email, created_at, updated_at "
            "FROM alert_routing WHERE family = ?", (family,)
        ).fetchone()
        before_dict = dict(before_row) if before_row else None

        cur = conn.execute('DELETE FROM alert_routing WHERE family = ?', (family,))
        deleted = cur.rowcount > 0

        if deleted:
            try:
                import json as _json
                conn.execute(
                    "INSERT INTO alert_routing_audit (family, action, actor, before_json, after_json, ts) "
                    "VALUES (?, 'delete', ?, ?, NULL, ?)",
                    (family, actor, _json.dumps(before_dict), int(_time.time() * 1000)),
                )
            except Exception as _ae:
                logger.warning('audit write failed (non-fatal): %s', _ae)
        conn.commit()
        return {'deleted': deleted, 'family': family}
    """Remove routing entry; alerts will fall back to default routing key."""
    _ensure_dir()
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        cur = conn.execute('DELETE FROM alert_routing WHERE family = ?', (family,))
        conn.commit()
        return {'deleted': cur.rowcount > 0, 'family': family}


def query_alerts(active_only: bool = True, limit: int = 50) -> List[Dict[str, Any]]:
    """Return active or all alerts."""
    _ensure_dir()
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if active_only:
            rows = conn.execute(
                "SELECT id, type, alert_key, severity, message, fired_at, "
                "dismissed_at, last_value, occurrences FROM alerts "
                "WHERE dismissed_at IS NULL ORDER BY fired_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, type, alert_key, severity, message, fired_at, "
                "dismissed_at, last_value, occurrences FROM alerts "
                "ORDER BY fired_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def dismiss_alert(alert_id: int) -> Dict[str, Any]:
    """Manually dismiss an active alert."""
    _ensure_dir()
    now_ms = int(_time.time() * 1000)
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        cur = conn.execute(
            "UPDATE alerts SET dismissed_at = ? WHERE id = ? AND dismissed_at IS NULL",
            (now_ms, alert_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return {"dismissed": False, "reason": "not_found_or_already_dismissed"}
    return {"dismissed": True, "alert_id": alert_id, "dismissed_at": now_ms}




def query_alert_routing_audit(family: Optional[str] = None, limit: int = 100, since_ms: Optional[int] = None, cursor: Optional[str] = None) -> Dict[str, Any]:
    """R6.51: cursor-paginated audit log query.

    Returns dict with: audit (list), count, has_more, next_cursor.
    Cursor is opaque base64(ts:id) — pass it back to get the next page.

    Filters:
      family: filter by font family
      limit: page size (default 100, capped at 500)
      since_ms: only entries with ts >= since_ms
      cursor: pagination cursor from previous response
    """
    _ensure_dir()
    capped_limit = min(max(1, limit), 500)
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        sql = "SELECT id, family, action, actor, before_json, after_json, ts FROM alert_routing_audit"
        clauses: List[str] = []
        params: List[Any] = []
        if family:
            clauses.append("family = ?")
            params.append(family)
        if since_ms is not None:
            clauses.append("ts >= ?")
            params.append(int(since_ms))
        if cursor:
            decoded = _decode_cursor(cursor)
            if decoded:
                cur_ts, cur_id = decoded
                # R6.51 cursor: rows strictly older than (cur_ts, cur_id) in (ts DESC, id DESC) order
                clauses.append("(ts < ? OR (ts = ? AND id < ?))")
                params.extend([cur_ts, cur_ts, cur_id])
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        # Fetch limit+1 to detect has_more
        params.append(capped_limit + 1)
        rows = conn.execute(sql, params).fetchall()
    import json as _json
    has_more = len(rows) > capped_limit
    if has_more:
        rows = rows[:capped_limit]
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for k in ('before_json', 'after_json'):
            if d.get(k):
                try:
                    d[k] = _json.loads(d[k])
                except Exception:
                    pass
        out.append(d)
    next_cursor = None
    if has_more and out:
        last = out[-1]
        next_cursor = _encode_cursor(last["ts"], last["id"])
    return {"audit": out, "count": len(out), "has_more": has_more, "next_cursor": next_cursor}


# R6.50: Retention purge for alert_routing_audit table.
# Deletes entries older than retention_days. Safe to call from cron or admin endpoint.
def purge_alert_routing_audit(retention_days: int = 90, dry_run: bool = False) -> Dict[str, Any]:
    """Delete alert_routing_audit rows older than retention_days.

    Args:
        retention_days: rows with ts < (now - retention_days * 86400 * 1000) are deleted.
        dry_run: if True, just report counts without deleting.

    Returns:
        dict with keys: deleted_count, kept_count, cutoff_ms, retention_days, dry_run
    """
    if retention_days < 1:
        return {"error": "retention_days must be >= 1", "deleted_count": 0}
    _ensure_dir()
    cutoff_ms = int(_time.time() * 1000) - int(retention_days) * 86400 * 1000
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        total = conn.execute("SELECT COUNT(*) FROM alert_routing_audit").fetchone()[0]
        if dry_run:
            to_delete = conn.execute(
                "SELECT COUNT(*) FROM alert_routing_audit WHERE ts < ?", (cutoff_ms,)
            ).fetchone()[0]
            return {
                "deleted_count": 0,
                "kept_count": total,
                "to_delete_count": to_delete,
                "cutoff_ms": cutoff_ms,
                "retention_days": retention_days,
                "dry_run": True,
            }
        cur = conn.execute("DELETE FROM alert_routing_audit WHERE ts < ?", (cutoff_ms,))
        deleted = cur.rowcount
        conn.commit()
        kept = conn.execute("SELECT COUNT(*) FROM alert_routing_audit").fetchone()[0]
    logger.info("purge_alert_routing_audit: deleted %d rows, kept %d (retention=%dd)", deleted, kept, retention_days)
    return {
        "deleted_count": deleted,
        "kept_count": kept,
        "cutoff_ms": cutoff_ms,
        "retention_days": retention_days,
        "dry_run": False,
    }


# R6.50: Full-text search across before/after JSON + actor + family + action.
# Uses LIKE for portability (no FTS5 required). Returns entries where any of
# (family, action, actor, before_json, after_json) match %q%.
def search_alert_routing_audit(q: str, limit: int = 100, cursor: Optional[str] = None) -> Dict[str, Any]:
    """R6.51: cursor-paginated full-text search.

    Returns dict with: audit, count, has_more, next_cursor, query.
    """
    if not q or not q.strip():
        return {"audit": [], "count": 0, "has_more": False, "next_cursor": None, "query": q or ""}
    """Search audit log for substring matches.

    Args:
        q: non-empty search string (case-insensitive via LIKE).
        limit: max rows (default 100, capped at 500).

    Returns:
        list of audit entries (most recent first), same shape as query_alert_routing_audit().
    """
    if not q or not q.strip():
        return []
    capped_limit = min(max(1, limit), 500)
    _ensure_dir()
    needle = "%" + q.replace("%", "\%").replace("_", "\_") + "%"
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        sql = (
            "SELECT id, family, action, actor, before_json, after_json, ts FROM alert_routing_audit "
            "WHERE family LIKE ? ESCAPE '\\' "
            "   OR action LIKE ? ESCAPE '\\' "
            "   OR actor LIKE ? ESCAPE '\\' "
            "   OR before_json LIKE ? ESCAPE '\\' "
            "   OR after_json LIKE ? ESCAPE '\\' "
            "ORDER BY ts DESC, id DESC LIMIT ?"
        )
        # R6.52 #1: Initialize params for the 5 LIKE placeholders (was missing,
        # causing NameError when search was invoked with non-empty q).
        params: List[Any] = [needle, needle, needle, needle, needle]
        # R6.51: cursor pagination — append (ts, id) filter + limit+1
        if cursor:
            decoded = _decode_cursor(cursor)
            if decoded:
                cur_ts, cur_id = decoded
                # Wrap with AND since WHERE has 5 OR clauses; inject at end of existing WHERE
                sql = sql.replace(
                    "ORDER BY ts DESC, id DESC LIMIT ?",
                    "AND (ts < ? OR (ts = ? AND id < ?)) ORDER BY ts DESC, id DESC LIMIT ?",
                )
                params.extend([cur_ts, cur_ts, cur_id])
        params.append(capped_limit + 1)
        rows = conn.execute(sql, params).fetchall()
    import json as _json
    has_more = len(rows) > capped_limit
    if has_more:
        rows = rows[:capped_limit]
    out: List[Dict[str, Any]] = []
    # R6.52 #1: case-insensitive highlight (match_field + match_offset)
    q_lower = q.lower()
    for r in rows:
        d = dict(r)
        match_field = None
        match_offset = -1
        for field in ('family', 'action', 'actor', 'before_json', 'after_json'):
            val = d.get(field)
            if val is None:
                continue
            if field in ('before_json', 'after_json') and isinstance(val, (dict, list)):
                val = _json.dumps(val, ensure_ascii=False)
            if not isinstance(val, str):
                continue
            idx = val.lower().find(q_lower)
            if idx >= 0:
                match_field = field
                match_offset = idx
                break
        for k in ('before_json', 'after_json'):
            if d.get(k):
                try:
                    d[k] = _json.loads(d[k])
                except Exception:
                    pass
        d['match_field'] = match_field
        d['match_offset'] = match_offset
        out.append(d)
    next_cursor = None
    if has_more and out:
        last = out[-1]
        next_cursor = _encode_cursor(last["ts"], last["id"])
    return {"audit": out, "count": len(out), "has_more": has_more, "next_cursor": next_cursor, "query": q}


def get_observability_health() -> Dict[str, Any]:
    """Sanity check: report DB size + record counts."""
    _ensure_dir()
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        font_count = conn.execute("SELECT COUNT(*) FROM font_errors").fetchone()[0]
        ab_count = conn.execute("SELECT COUNT(*) FROM ab_metrics").fetchone()[0]
    db_size = _DB_PATH.stat().st_size if _DB_PATH.exists() else 0
    with _LOCK, sqlite3.connect(_DB_PATH) as conn:
        routing_count = conn.execute('SELECT COUNT(*) FROM alert_routing').fetchone()[0]
        active_alerts = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE dismissed_at IS NULL"
        ).fetchone()[0]
        total_alerts = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        audit_count = conn.execute("SELECT COUNT(*) FROM alert_routing_audit").fetchone()[0]
    return {
        "db_path": str(_DB_PATH),
        "db_size_bytes": db_size,
        "font_errors_count": font_count,
        "ab_metrics_count": ab_count,
        "active_alerts_count": active_alerts,
        "total_alerts_count": total_alerts,
        "jsonl_font_exists": _JSONL_FONT.exists(),
        "jsonl_ab_exists": _JSONL_AB.exists(),
        "alert_threshold_per_window": _FONT_ERROR_RATE_THRESHOLD,
        "alert_window_seconds": _FONT_ERROR_RATE_WINDOW_MS // 1000,
        "pagerduty_enabled": bool(_PAGERDUTY_WEBHOOK_URL and _PAGERDUTY_ROUTING_KEY),
        "routing_table_count": routing_count,
        "routing_table_env_size": len(_PAGERDUTY_ROUTING_TABLE),
        "routing_audit_count": audit_count,
        "audit_retention_days": int(os.getenv("AUDIT_RETENTION_DAYS", "90")),
        "routing_audit_count": audit_count,
    }
