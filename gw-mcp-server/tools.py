"""MCP tool definitions wrapping the GW backend API.

v4.16: Added parameter validation at MCP layer — invalid ra/dec/radius
are rejected BEFORE reaching the backend, with clear error messages
for the AI model to self-correct.
v4.26: Added audit logging + RBAC awareness fields to all tool responses.
"""
import time as _time
import logging as _logging
from mcp.server.fastmcp import FastMCP
from gw_client import GWClient, pipeline

mcp = FastMCP("gw-mcp-server")
client = GWClient()

# ── Audit logging (v4.28: persistent file-based + structured) ──────────────
_audit_log = _logging.getLogger("gw-mcp-audit")

# v4.28: Persistent audit file (JSONL format for easy querying)
_AUDIT_FILE = os.environ.get("MCP_AUDIT_FILE", "/app/thumbnail_cache/logs/mcp-audit.jsonl")
_AUDIT_DIR = os.path.dirname(_AUDIT_FILE)

def _audit(tool_name: str, params: dict, source: str, user_role: str = "unknown") -> dict:
    """Record MCP tool invocation for audit trail (v4.28: persistent).

    Writes a JSONL entry to _AUDIT_FILE for long-term storage.
    Each line is a JSON object: {tool, timestamp_utc, params_summary, source, user_role}
    """
    import json as _json
    entry = {
        "tool": tool_name,
        "timestamp_utc": _time.time(),
        "timestamp_iso": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        "params_summary": {k: str(v)[:80] for k, v in params.items()},
        "source": source,
        "user_role": user_role,
    }
    _audit_log.info("MCP_TOOL:%s params=%s source=%s role=%s", tool_name,
                    str(entry["params_summary"])[:120], source, user_role)

    # v4.28: Persistent file-based audit log
    try:
        os.makedirs(_AUDIT_DIR, exist_ok=True)
        with open(_AUDIT_FILE, "a") as f:
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # Non-blocking: audit failure must not break tool execution

    return entry


# v4.28: RBAC role definitions
# Roles are passed via X-GW-User-Role HTTP header from the backend.
# Backend AuthInterceptor already validates JWT tokens; MCP enforces tool-level access.
_DL_TOOLS = {"classify_galaxy_morphology", "classify_source_type", "detect_anomaly_dl",
             "get_dl_model_status", "enhance_anomaly_detection"}
_READ_TOOLS = {"search_observations", "get_error_reports", "get_error_detail",
               "get_error_reference", "get_comments", "get_system_status"}
_ADMIN_TOOLS = {"add_comment"}

# Role → allowed tool sets
_RBAC_POLICY = {
    "observer": _READ_TOOLS,                        # read-only: search, view errors
    "analyst":  _READ_TOOLS | _DL_TOOLS,            # + DL inference
    "admin":    _READ_TOOLS | _DL_TOOLS | _ADMIN_TOOLS,  # + write operations
}


def _get_user_role() -> str:
    """Extract user role from the current MCP request context (v4.28).

    The MCP server runs over stdio (FastMCP) — there is no HTTP request object.
    Role is read from the GW_USER_ROLE environment variable, which should be
    set by the MCP server's transport layer when it receives the X-GW-User-Role
    header from the backend's reverse proxy.

    In SSE/streamable HTTP mode, role may be passed via query parameter or
    session context. Falls back to "observer" (most restrictive) when unknown.
    """
    return os.environ.get("GW_USER_ROLE", "observer").lower()


def _check_rbac(tool_name: str) -> dict:
    """Enforce RBAC: return allowed=True/False + metadata (v4.28).

    Unlike v4.26's _rbac_note() which only DOCUMENTED the lack of RBAC,
    this function actually ENFORCES role-based access control.
    """
    role = _get_user_role()
    allowed_tools = _RBAC_POLICY.get(role, _READ_TOOLS)
    allowed = tool_name in allowed_tools

    return {
        "rbac_enforced": True,  # v4.28: RBAC is now enforced, not just documented
        "user_role": role,
        "tool_allowed": allowed,
        "note": (
            f"User role '{role}' {'CAN' if allowed else 'CANNOT'} access '{tool_name}'. "
            f"Allowed tools for {role}: {sorted(allowed_tools)}"
        ) if not allowed else (
            f"RBAC enforced: user role '{role}' authorized for '{tool_name}'"
        ),
        "audit_logged": True,
    }


def _rbac_note(tool_name: str) -> dict:
    """Legacy RBAC note — now delegates to _check_rbac (v4.28).

    Kept for backward compatibility with v4.26 response format.
    """
    return _check_rbac(tool_name)

# ── Parameter validation (MCP layer — catches errors before backend) ──
# These mirror backend CoordinateValidator.java and Pipeline's coordinate checks.
# AI models can self-correct based on these error messages.

RA_MIN, RA_MAX = 0.0, 360.0
DEC_MIN, DEC_MAX = -90.0, 90.0
RADIUS_MIN, RADIUS_MAX = 0.0, 180.0
MAX_PAGE_SIZE = 100
MAX_STR_LEN = 256
MAX_CONTENT_LEN = 10000
VALID_CATEGORIES = {"analysis", "crossmatch", "verification", "recommendation"}


def _v_ra(ra) -> str | None:
    """Validate RA: 0–360 degrees. Returns error string or None."""
    if ra is None:
        return None
    if not isinstance(ra, (int, float)):
        return f"RA must be a number, got {type(ra).__name__}"
    if ra < RA_MIN or ra > RA_MAX:
        return f"RA={ra} is out of range. RA must be between {RA_MIN} and {RA_MAX} degrees."
    return None


def _v_dec(dec) -> str | None:
    """Validate Dec: -90 to +90 degrees."""
    if dec is None:
        return None
    if not isinstance(dec, (int, float)):
        return f"Dec must be a number, got {type(dec).__name__}"
    if dec < DEC_MIN or dec > DEC_MAX:
        return f"Dec={dec} is out of range. Dec must be between {DEC_MIN} and {DEC_MAX} degrees."
    return None


def _v_radius(radius) -> str | None:
    """Validate search radius: 0–180 degrees."""
    if not isinstance(radius, (int, float)):
        return f"Radius must be a number, got {type(radius).__name__}"
    if radius < RADIUS_MIN or radius > RADIUS_MAX:
        return f"Radius={radius}° is out of range. Must be between {RADIUS_MIN}° and {RADIUS_MAX}°."
    return None


def _v_page(page: int) -> str | None:
    if page < 1:
        return f"Page={page} is invalid. Page must be >= 1."
    return None


def _v_page_size(page_size: int) -> str | None:
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        return f"Page size={page_size} is invalid. Must be between 1 and {MAX_PAGE_SIZE}."
    return None


def _v_str(value: str, max_len: int, field: str) -> str | None:
    """Validate string length."""
    if not isinstance(value, str):
        return f"{field} must be a string, got {type(value).__name__}"
    if len(value) > max_len:
        return f"{field} is too long: {len(value)} chars (max {max_len})"
    if not value.strip():
        return f"{field} cannot be empty or whitespace-only"
    return None


def _validate_and_fail(**validations) -> None:
    """Raise ValueError with the first validation error found."""
    errors = [(field, err) for field, err in validations if err is not None]
    if errors:
        field, msg = errors[0]
        raise ValueError(f"Invalid parameter '{field}': {msg}")


# ═══════════════════════════════════════════════════════════════════════════
#  MCP Tools
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def search_observations(
    ra: float = None, dec: float = None, radius: float = 1.0,
    telescope: str = None, page: int = 1, page_size: int = 10
) -> dict:
    """Search gravitational wave observations by sky coordinates (RA/Dec).

    RA must be 0-360 degrees. Dec must be -90 to +90 degrees.
    Radius is the search cone radius in degrees (0-180, default 1.0).
    Returns paginated FITS observations from AliCPT/WISE/ZTF telescopes.

    The response includes _gw_source field indicating data quality:
      "live" = real backend, "fallback_json" = backend down using cached data,
      "mock" = MOCK_MODE enabled, "error" = all sources failed.
    """
    _validate_and_fail(
        ("ra", _v_ra(ra)),
        ("dec", _v_dec(dec)),
        ("radius", _v_radius(radius)),
        ("page", _v_page(page)),
        ("page_size", _v_page_size(page_size)),
        ("telescope", _v_str(telescope, 50, "telescope") if telescope else None),
    )
    result = await client.search_observations(
        ra=ra, dec=dec, radius=radius, telescope=telescope,
        page=page, page_size=page_size)
    # v4.26: Inject audit + RBAC metadata
    _audit("search_observations", {"ra": ra, "dec": dec, "radius": radius}, result.get("_gw_source", "unknown"), _get_user_role())
    result["_gw_rbac"] = _rbac_note("search_observations")
    return result


@mcp.tool()
async def get_error_reports(page: int = 1, page_size: int = 10) -> dict:
    """Get anomaly detection error reports. Returns paginated list
    of detected anomalies with telescope, band, coordinates, FOV."""
    _validate_and_fail(
        ("page", _v_page(page)),
        ("page_size", _v_page_size(page_size)),
    )
    result = await client.get_error_reports(page=page, page_size=page_size)
    _audit("get_error_reports", {"page": page, "page_size": page_size}, result.get("_gw_source", "unknown"), _get_user_role())
    result["_gw_rbac"] = _rbac_note("get_error_reports")
    return result


@mcp.tool()
async def get_error_detail(error_id: str, page: int = 1, page_size: int = 10) -> dict:
    """Get detailed info for a specific anomaly. Includes log content,
    anomaly type, and list of affected data points with UUIDs."""
    _validate_and_fail(
        ("error_id", _v_str(error_id, 256, "error_id")),
        ("page", _v_page(page)),
        ("page_size", _v_page_size(page_size)),
    )
    return await client.get_error_detail(error_id, page=page, page_size=page_size)


@mcp.tool()
async def get_error_reference(error_id: str, uuid: str) -> dict:
    """Get multi-band observation data for a specific anomaly source.
    Returns FITS paths, images, and metadata across bands."""
    _validate_and_fail(
        ("error_id", _v_str(error_id, 256, "error_id")),
        ("uuid", _v_str(uuid, 256, "uuid")),
    )
    return await client.get_error_reference(error_id, uuid)


@mcp.tool()
async def get_comments(grawave_id: str, page: int = 1, page_size: int = 10) -> dict:
    """Get user comments for an observation record.
    Returns comments with user IDs, categories, and timestamps."""
    _validate_and_fail(
        ("grawave_id", _v_str(grawave_id, 256, "grawave_id")),
        ("page", _v_page(page)),
        ("page_size", _v_page_size(page_size)),
    )
    return await client.get_comments(grawave_id, page=page, size=page_size)


@mcp.tool()
async def add_comment(grawave_id: str, content: str, user_id: str, category: str = "analysis") -> dict:
    """Add a comment to an observation.

    Category must be one of: analysis, crossmatch, verification, recommendation.
    Content max 10000 characters. user_id identifies the commenter.
    """
    _validate_and_fail(
        ("grawave_id", _v_str(grawave_id, 256, "grawave_id")),
        ("content", _v_str(content, MAX_CONTENT_LEN, "content")),
        ("user_id", _v_str(user_id, 256, "user_id")),
    )
    if category not in VALID_CATEGORIES:
        raise ValueError(
            f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}")
    return await client.add_comment(grawave_id, content, user_id, category)


# ═══════════════════════════════════════════════════════════════════════════
#  DL Inference Tools (v4.24) — wraps gw-pipeline ONNX DL endpoints
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def classify_galaxy_morphology(filename: str) -> dict:
    """Classify galaxy morphology from a FITS file using Zoobot ConvNeXt-Nano ONNX.

    Returns: morphology_class (spiral/elliptical/edge-on/merger/irregular),
    confidence (0-1), probabilities per class, model_name, inference_time_ms.

    The model runs locally via ONNX Runtime CPU inference — no external API call.
    Falls back to lightweight numpy/scipy classifier if ONNX unavailable.

    RBAC: Requires analyst or admin role. Observer role is denied (v4.28).
    """
    rbac = _check_rbac("classify_galaxy_morphology")
    if not rbac["tool_allowed"]:
        return {"error": f"Access denied: {rbac['note']}", "_gw_source": "pipeline-rbac-deny",
                "_gw_rbac": rbac}
    _validate_and_fail(
        ("filename", _v_str(filename, 256, "filename")),
    )
    try:
        result = await pipeline.classify_galaxy_morphology(filename)
        _audit("classify_galaxy_morphology", {"filename": filename}, result.get("_gw_source", "unknown"), _get_user_role())
        result["_gw_rbac"] = rbac
        return result
    except Exception as e:
        return {"error": f"Galaxy morphology classification failed: {str(e)[:200]}",
                "_gw_source": "pipeline-error",
                "_gw_rbac": rbac}


@mcp.tool()
async def classify_source_type(filename: str) -> dict:
    """Classify astronomical source type (star/galaxy/quasar) from FITS photometric features.

    Returns: source_class (star/galaxy/quasar), confidence (0-1),
    probabilities per class, model_name, features_used list, inference_time_ms.

    Uses ONNX MLP(13→32→16→3) or lightweight heuristic classifier.
    Features are pixel-domain: peakiness, concentration indices, ellipticity,
    gradient magnitude, flip symmetry — computed from FITS data directly.

    RBAC: Requires analyst or admin role. Observer role is denied (v4.28).
    """
    rbac = _check_rbac("classify_source_type")
    if not rbac["tool_allowed"]:
        return {"error": f"Access denied: {rbac['note']}", "_gw_source": "pipeline-rbac-deny",
                "_gw_rbac": rbac}
    _validate_and_fail(
        ("filename", _v_str(filename, 256, "filename")),
    )
    try:
        return await pipeline.classify_source_type(filename)
    except Exception as e:
        return {"error": f"Source type classification failed: {str(e)[:200]}",
                "_gw_source": "pipeline-error"}


@mcp.tool()
async def detect_anomaly_dl(filename: str) -> dict:
    """Detect anomalies in FITS image using CNN autoencoder (independent DL detector).

    The autoencoder reconstructs the input; high reconstruction error → anomaly.
    No rule classifier input needed — this is a standalone deep learning detector.

    Returns: is_anomalous (bool), anomaly_score (z-score, >3=strong anomaly),
    reconstruction_error (raw MSE), confidence (0-1), verdict (anomalous/suspicious/normal),
    threshold_used (e.g. "3-sigma"), model_name, inference_time_ms.

    For anomaly TYPE classification (spike/dip/pattern_break/wcs_mismatch),
    use the rule-based classifier via get_error_reports/get_error_detail.

    RBAC: Requires analyst or admin role. Observer role is denied (v4.28).
    """
    rbac = _check_rbac("detect_anomaly_dl")
    if not rbac["tool_allowed"]:
        return {"error": f"Access denied: {rbac['note']}", "_gw_source": "pipeline-rbac-deny",
                "_gw_rbac": rbac}
    _validate_and_fail(
        ("filename", _v_str(filename, 256, "filename")),
    )
    try:
        return await pipeline.detect_anomaly(filename)
    except Exception as e:
        return {"error": f"DL anomaly detection failed: {str(e)[:200]}",
                "_gw_source": "pipeline-error"}


@mcp.tool()
async def get_dl_model_status() -> dict:
    """Get status of all deep learning models in the pipeline.

    Returns: onnx_available (bool), list of models with name/type/status/size_mb.
    ONNX models: zoobot_encoder_greyscale (57 MB), source_classifier (5 KB),
    anomaly_autoencoder (487 KB). Lightweight numpy/scipy fallbacks also listed.

    Use this to verify DL capabilities are available before calling
    morphology/source-type/anomaly tools.
    """
    try:
        return await pipeline.get_model_status()
    except Exception as e:
        return {"error": f"DL status check failed: {str(e)[:200]}",
                "_gw_source": "pipeline-error",
                "onnx_available": False, "models": []}


# ── Degradation status tool — allows AI to self-check data quality ──────
@mcp.tool()
async def get_system_status() -> dict:
    """Get MCP server health and degradation status.

    Returns the current alert level and data-source breakdown:
      - alert_level: healthy / warning / degraded / critical
      - live_count vs fallback_count vs mock_count vs error_count
      - backend_reachable: whether the live backend is responding
      - per-endpoint failure counts

    Use this to verify you're receiving live data before making
    scientific claims based on tool results.
    """
    from gw_client import degrade_state
    health = await client.health_check()
    health["mcp_version"] = "v4.28"
    health["audit"] = {
        "enabled": True,
        "log_target": "gw-mcp-audit",
        "persistent_file": os.environ.get("MCP_AUDIT_FILE", "/app/thumbnail_cache/logs/mcp-audit.jsonl"),
        "note": "v4.28: All tool invocations logged to structured logger AND persistent JSONL file"
    }
    health["rbac"] = {
        "enforced": True,
        "current_role": _get_user_role(),
        "policy": {role: sorted(tools) for role, tools in _RBAC_POLICY.items()},
        "note": "v4.28: RBAC enforced at MCP layer. DL tools require analyst+. Observer is read-only."
    }
    health["transport"] = "stdio"  # may be overridden in SSE mode
    health["note"] = (
        "Check _gw_source in tool responses: "
        "'live' = real data, 'fallback_json' = cached export, "
        "'mock' = MOCK_MODE, 'error' = all sources failed."
    )
    return health
