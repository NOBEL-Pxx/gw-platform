"""R6.73 #2: IP whitelist middleware for gw-pipeline.

Defense-in-depth on top of RBAC: reject requests from outside the Docker
network so a compromised peer container cannot reach pipeline endpoints
directly (only via gw-backend -> PipelineProxyController).

Allow list (any of):
  - Docker bridge subnets (172.16.0.0/12 covers gw-net default gateway ranges)
  - Loopback (127.0.0.1, ::1)
  - gw-backend container hostname (Docker DNS resolves to bridge IP)
  - Optional admin escape via GW_ADMIN_IPS env (CIDR list, comma-separated)

Config via env:
  GW_IP_WHITELIST_ENABLED=true|false        (default: true)
  GW_IP_WHITELIST_ADMIN_IPS=10.0.0.5,...    (optional admin escape hatch)
  GW_IP_WHITELEST_BRIDGE_CIDRS=172.16.0.0/12,172.17.0.0/16,...   (override bridge ranges)

Health/metrics endpoints are exempted so Docker healthchecks + Prometheus
scraping still work regardless of caller IP.

Why this matters (R6.72留待 #2):
  Current: gw-pipeline listens on :8200 inside gw-net. Any container on
           gw-net (frontend nginx, mongodb sidecar, etc.) can curl it
           directly, bypassing PipelineProxyController's auth header
           propagation.
  After: gw-pipeline rejects non-whitelisted IPs at the middleware layer,
         so direct curls from unexpected sources return 403.
"""
from __future__ import annotations

import ipaddress
import logging
import os
from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

_log = logging.getLogger("gw-ip-whitelist")

_ENABLED = os.getenv("GW_IP_WHITELIST_ENABLED", "true").lower() in ("1", "true", "yes")

# Default Docker bridge subnets. Docker creates 172.17.0.0/16 by default,
# but custom networks can land anywhere in 172.16.0.0/12.
_DEFAULT_BRIDGE_CIDRS = (
    "172.16.0.0/12",   # 172.16.0.0 - 172.31.255.255 (covers 172.17/172.18/...)
    "10.0.0.0/8",      # compose default for some user-defined networks
)

_BRIDGE_OVERRIDE = os.getenv("GW_IP_WHITELIST_BRIDGE_CIDRS", "")
_BRIDGE_CIDRS: tuple = tuple(
    c.strip() for c in (_BRIDGE_OVERRIDE or ",".join(_DEFAULT_BRIDGE_CIDRS)).split(",") if c.strip()
)

_ADMIN_IPS_ENV = os.getenv("GW_IP_WHITELIST_ADMIN_IPS", "")
_ADMIN_IPS: tuple = tuple(
    ipaddress.ip_network(c.strip(), strict=False)
    for c in _ADMIN_IPS_ENV.split(",")
    if c.strip()
)

# Paths exempt from IP check (so healthchecks / metrics / docs still work).
_EXEMPT_PATHS = frozenset({
    "/health",
    "/pipeline/health",
    "/pipeline/metrics",
    "/pipeline/agent/status",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/pipeline/docs",
    "/pipeline/redoc",
    "/pipeline/openapi.json",
})
_EXEMPT_PREFIXES = ("/pipeline/cache/warmup",)


def _parse_cidrs(raw: Iterable[str]):
    """Parse CIDR strings, silently dropping malformed entries."""
    out = []
    for c in raw:
        try:
            out.append(ipaddress.ip_network(c, strict=False))
        except ValueError:
            _log.warning("IP whitelist: skipping invalid CIDR %r", c)
    return tuple(out)


_BRIDGE_NETS = _parse_cidrs(_BRIDGE_CIDRS)


def _is_allowed(client_ip: str) -> bool:
    """Return True if client_ip is in any allow-listed subnet / match."""
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        _log.warning("IP whitelist: cannot parse client_ip=%r, rejecting", client_ip)
        return False

    # Loopback (always allowed for ops escape)
    if ip.is_loopback:
        return True

    # Admin escape CIDRs
    for net in _ADMIN_IPS:
        if ip in net:
            return True

    # Docker bridge subnets
    for net in _BRIDGE_NETS:
        if ip in net:
            return True

    return False


class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """Reject requests whose client IP is not in the allow list."""

    async def dispatch(self, request: Request, call_next):
        if not _ENABLED:
            return await call_next(request)

        # Exempt health/metrics/docs paths so Docker healthchecks + Prometheus
        # scraping still work regardless of caller IP.
        path = request.url.path
        if path in _EXEMPT_PATHS or any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        # X-Forwarded-For first (when behind nginx); fall back to socket address.
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # Use first IP (original client). nginx sets this; PipelineProxyController
            # also forwards it. We trust gw-frontend here; if it lies, that's a
            # bigger problem than IP whitelist would solve.
            client_ip = xff.split(",")[0].strip()
        else:
            client = request.client
            client_ip = client.host if client else "0.0.0.0"

        if not _is_allowed(client_ip):
            _log.warning(
                "IP whitelist: BLOCKED %s %s from %s (xff=%s)",
                request.method, path, client_ip,
                xff or "(none)",
            )
            return JSONResponse(
                status_code=403,
                content={
                    "error": "forbidden",
                    "reason": "client_ip_not_whitelisted",
                    "client_ip": client_ip,
                    "hint": "gw-pipeline only accepts Docker-internal callers. "
                            "Access via gw-backend PipelineProxyController.",
                },
            )

        return await call_next(request)


__all__ = ["IPWhitelistMiddleware", "_is_allowed", "_BRIDGE_CIDRS", "_ADMIN_IPS"]
