"""
R6.61.c: CSP violation reporter.

Frontend cspMonitor.ts batches securitypolicyviolation events and POSTs them
here. We log to a daily-rotated file so ops can detect CSP breakages
(wasm-unsafe-eval removal, XSS probes, supply-chain attempts) without
needing browser DevTools.

Why log only (not alert):
   - CSP violations are expected for some legacy inline scripts in dev mode.
   - Logging is enough for forensics; alerting on every violation would
     flood alerts during normal dev.
   - Ops can grep /app/logs/csp-violations.log for wasm-unsafe-eval
     blocked samples to catch real regressions.

Log format (JSONL one violation per line for easy jq):
   {ts, ua, url, blockedURI, effectiveDirective, disposition, sourceFile,
    lineNumber, sample}
"""
from __future__ import annotations

import json
import logging
import os
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter()

# Log file path env-overridable for tests
LOG_DIR = Path(os.getenv("CSP_LOG_DIR", "/app/logs"))
LOG_FILE = LOG_DIR / "csp-violations.log"

# R6.61.c: dedicated logger NOT the root logger (so we control format)
_csp_logger = None


def _get_logger():
    global _csp_logger
    if _csp_logger is not None:
        return _csp_logger
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("gw.csp.violations")
    logger.setLevel(logging.INFO)
    # Daily rotation, keep 7 days
    handler = TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    _csp_logger = logger
    return logger


class CspViolationIn(BaseModel):
    blockedURI: str = ""
    violatedDirective: str = ""
    effectiveDirective: str = ""
    originalPolicy: str = ""
    documentURI: str = ""
    referrer: str = ""
    sourceFile: str = ""
    lineNumber: int = 0
    columnNumber: int = 0
    sample: str = ""
    disposition: str = "enforce"


class CspReport(BaseModel):
    violations: list = Field(default_factory=list)
    userAgent: str = "unknown"
    url: str = "unknown"
    ts: int = Field(default_factory=lambda: int(time.time() * 1000))


@router.post("/security/csp-violation")
async def receive_csp_violation(report: CspReport, request: Request) -> dict:
    """Receive a batch of CSP violations from the frontend and log them."""
    logger = _get_logger()
    if not report.violations:
        return {"received": 0}
    received = 0
    for v in report.violations:
        entry = {
            "ts": report.ts or int(time.time() * 1000),
            "ua": report.userAgent,
            "url": report.url,
            "blockedURI": v.blockedURI,
            "effectiveDirective": v.effectiveDirective,
            "violatedDirective": v.violatedDirective,
            "disposition": v.disposition,
            "sourceFile": v.sourceFile,
            "lineNumber": v.lineNumber,
            "columnNumber": v.columnNumber,
            "sample": v.sample[:200] if v.sample else "",
            "originalPolicy": v.originalPolicy[:500] if v.originalPolicy else "",
            "client": request.client.host if request.client else "unknown",
        }
        logger.info(json.dumps(entry, ensure_ascii=False))
        received += 1
    return {"received": received}
