"""v4.35: RBAC Middleware for Fine-Grained Permissions (Fix #1).

Provides FastAPI middleware that:
  - Verifies JWT tokens against the Spring Boot backend
  - Maps user roles (observer/analyst/admin) to endpoint permissions
  - Enforces per-role quota limits
  - Supports public/unauthenticated endpoints via whitelist

Role permissions:
  - observer:  read-only (search, view files, agent chat with 50/day)
  - analyst:   read + DL inference + pipeline execution (200/day)
  - admin:     all endpoints + audit logs + user management (unlimited)

Config via env:
  GW_ROLE_QUOTAS={"observer":50,"analyst":200,"admin":-1}
  GW_AUTH_VERIFY_URL=http://gw-backend:8093/api/auth/verify
"""
import os, logging
from typing import Optional, Dict, Set
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import httpx

_log = logging.getLogger("gw-rbac")

# ── Config ─────────────────────────────────────────────────────────────
_AUTH_VERIFY_URL = os.getenv("GW_AUTH_VERIFY_URL", "http://gw-backend:8093/api/auth/verify")
_AUTH_TIMEOUT = float(os.getenv("GW_AUTH_TIMEOUT_SEC", "5.0"))

# Role → quota mapping (-1 = unlimited)
import json as _json
_DEFAULT_QUOTAS = {"observer": 50, "analyst": 200, "admin": -1, "user": 50}
_ROLE_QUOTAS = _json.loads(os.getenv("GW_ROLE_QUOTAS", _json.dumps(_DEFAULT_QUOTAS)))

# Role → allowed actions
_ROLE_ACTIONS: Dict[str, Set[str]] = {
    "observer": {"agent_chat", "agent_stream", "read", "llm_status", "llm_usage"},
    "analyst":  {"agent_chat", "agent_stream", "read", "dl_inference", "pipeline_run"},
    "admin":    {"*"},
    "user":     {"agent_chat", "agent_stream", "read", "llm_status", "llm_usage"},  # v4.38: backend returns role=user, map to observer-level
}

# Endpoint → required action mapping
_ENDPOINT_ACTIONS = {
    "/pipeline/agent/chat": "agent_chat",
    "/pipeline/agent/chat/stream": "agent_stream",
    "/pipeline/dl/morphology": "dl_inference",
    "/pipeline/dl/source-type": "dl_inference",
    "/pipeline/dl/anomaly/detect": "dl_inference",
    "/pipeline/dl/anomaly/enhance": "dl_inference",
    "/pipeline/sources": "pipeline_run",
    "/pipeline/photometry": "pipeline_run",
    "/pipeline/wcs": "read",
    "/pipeline/admin/audit/logs": "admin",
    "/pipeline/admin/audit/stats": "admin",
    "/pipeline/admin/audit/alerts": "admin",
    "/pipeline/admin/quota/users": "admin",
}

# Paths that do NOT require authentication
_PUBLIC_PATHS = {
    "/", "/health", "/docs", "/openapi.json", "/redoc",
    "/pipeline/health", "/pipeline/agent/status",
    "/pipeline/metrics",  # v4.37: Prometheus scraping (public)
    "/pipeline/dl/status", "/pipeline/files",
    "/pipeline/jobs",  # job creation may be public
}

# Path prefixes that are public
_PUBLIC_PREFIXES = ("/pipeline/jobs/", "/pipeline/thumbnail", "/pipeline/merge-rgb", "/pipeline/hips-thumb", "/pipeline/hips-stats", "/pipeline/hips-float", "/pipeline/hips-tile-resolve", "/pipeline/hips-cache-invalidate", "/pipeline/hips-cache-stats", "/pipeline/hips-cache-staleness", "/pipeline/pdf/verify-multiple", "/pipeline/pdf/sign-pkcs7", "/pipeline/docs", "/pipeline/redoc", "/pipeline/openapi.json", "/pipeline/observability/")  # R6.44: telemetry data is non-sensitive (font errors + A/B metrics)


async def _verify_token(token: str) -> Optional[dict]:
    """Verify a JWT token with the Spring Boot backend. Returns user info or None."""
    if not token or token == "undefined" or token == "null":
        return None
    try:
        async with httpx.AsyncClient(timeout=_AUTH_TIMEOUT) as client:
            resp = await client.get(
                _AUTH_VERIFY_URL,
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                # Support both wrapped and unwrapped responses
                user = data.get("data", data)
                if user.get("userId"):
                    return {
                        "userId": user["userId"],
                        "username": user.get("username", "unknown"),
                        "role": user.get("role", "observer"),
                    }
    except Exception as e:
        _log.debug("Token verification failed: %s", e)
    return None


def _get_required_action(path: str) -> Optional[str]:
    """Map an endpoint path to the required RBAC action."""
    # Exact match
    if path in _ENDPOINT_ACTIONS:
        return _ENDPOINT_ACTIONS[path]
    # Prefix match for admin endpoints
    if path.startswith("/pipeline/admin/"):
        return "admin"
    # Default: low-risk paths need "read", others are public
    if any(path.startswith(p) for p in ["/pipeline/", "/api/"]):
        return "read"
    return None


def _check_permission(role: str, action: str) -> bool:
    """Check if role is allowed to perform action."""
    allowed = _ROLE_ACTIONS.get(role, set())
    if "*" in allowed:
        return True
    return action in allowed


class RBACMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware enforcing role-based access control.

    Flow:
      1. Check if path is public → allow
      2. Extract Bearer token from Authorization header
      3. Verify token with Spring Boot backend
      4. Map endpoint path → required action
      5. Check if user's role allows the action
      6. Attach user info to request.state for downstream handlers
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip public paths
        if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        # Determine required action
        required_action = _get_required_action(path)
        if required_action is None:
            # No specific action required — allow through (e.g., static files)
            return await call_next(request)

        # Extract and verify token
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""

        user_info = await _verify_token(token)
        if user_info is None:
            _log.warning("RBAC: Unauthenticated access to %s", path)
            return JSONResponse(
                {"error": "Authentication required. Please log in to access this resource.", "success": False},
                status_code=401,
            )

        # Check permission
        role = user_info.get("role", "observer")
        if not _check_permission(role, required_action):
            _log.warning("RBAC: %s (role=%s) denied access to %s (action=%s)",
                        user_info.get("username"), role, path, required_action)
            return JSONResponse(
                {"error": f"Permission denied. Role '{role}' cannot perform '{required_action}'.",
                 "success": False, "required_role": required_action},
                status_code=403,
            )

        # Attach user to request state
        request.state.user = user_info
        request.state.user_role = role

        _log.debug("RBAC: %s (role=%s) → %s", user_info.get("username"), role, path)
        return await call_next(request)


def get_role_quota(role: str) -> int:
    """Get the daily LLM quota for a given role. -1 = unlimited."""
    return _ROLE_QUOTAS.get(role, _ROLE_QUOTAS.get("observer", 50))
