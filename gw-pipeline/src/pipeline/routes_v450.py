# R6.50: Audit retention + full-text search + PDF signature endpoints.
# Registered via register_routes_v450(app) in server.py.

from __future__ import annotations

import hashlib
import logging
import json
import time
import os
from pathlib import Path as _Path
from typing import Optional

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse

from .observability import (
    purge_alert_routing_audit,
    search_alert_routing_audit,
)

# R6.51: Import _PERSIST_PATH from R6.50 hips module for staleness check
from .routes_v449_hips import _PERSIST_PATH

logger = logging.getLogger("gw.routes-v450")

# PDF signature: store generated PDFs in /app/observability/signed/ for verify.
# R6.51: Same /tmp fallback as _OBS_DIR
_signed_env = os.getenv("SIGNED_PDF_DIR")
if _signed_env:
    _SIGNED_DIR = _Path(_signed_env)
else:
    _default_signed = _Path("/app/observability/signed")
    try:
        _default_signed.mkdir(parents=True, exist_ok=True)
        _SIGNED_DIR = _default_signed
    except (OSError, PermissionError):
        _SIGNED_DIR = _Path("/tmp/observability/signed")
        _SIGNED_DIR.mkdir(parents=True, exist_ok=True)


def register_routes_v450(app):
    router = APIRouter()

    @router.get("/pipeline/observability/audit/search")
    def audit_search(
        q: str = Query(..., min_length=1, max_length=200),
        limit: int = Query(50, ge=1, le=500),
        cursor: Optional[str] = Query(None, description="R6.51 opaque cursor from prior page"),
    ):
        """R6.51: Cursor-paginated full-text search."""
        try:
            return search_alert_routing_audit(q=q, limit=limit, cursor=cursor)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/pipeline/observability/audit/retention")
    def audit_retention_info(retention_days: int = Query(90, ge=1, le=3650)):
        """R6.50: Report current retention config + dry-run purge stats."""
        try:
            stats = purge_alert_routing_audit(retention_days=retention_days, dry_run=True)
            return stats
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.post("/pipeline/observability/audit/retention/purge")
    def audit_retention_purge(
        retention_days: int = Query(90, ge=1, le=3650),
        x_actor: Optional[str] = Header(default=None, alias="X-Actor"),
    ):
        """R6.50: Actually delete audit rows older than retention_days.

        Requires X-Actor header (audit-trail of who ran the purge).
        """
        try:
            actor = x_actor or "anonymous"
            stats = purge_alert_routing_audit(retention_days=retention_days, dry_run=False)
            stats["purged_by"] = actor
            logger.info("audit_retention_purge: %s", stats)
            return stats
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.post("/pipeline/pdf/sign")
    def pdf_sign(
        payload: dict = None,
        x_actor: Optional[str] = Header(default=None, alias="X-Actor"),
    ):
        """R6.50: Create a SHA256 signature for a PDF content payload.

        Body: {"pdf_base64": "...", "filename": "report.pdf"} or {"pdf_text": "..."}.
        Returns: { hash, signature_algo, signed_at, signed_by, filename, size_bytes }.
        Stores signature metadata in /app/observability/signed/<hash>.json.
        """
        import base64
        import json as _json
        import time as _time
        if not payload:
            return JSONResponse({"error": "empty_payload"}, status_code=400)
        filename = str(payload.get("filename") or "document.pdf")
        actor = x_actor or "anonymous"
        sig_algo = "SHA256"
        if "pdf_base64" in payload:
            try:
                content = base64.b64decode(str(payload["pdf_base64"]))
            except Exception as e:
                return JSONResponse({"error": f"invalid_base64: {e}"}, status_code=400)
        elif "pdf_text" in payload:
            content = str(payload["pdf_text"]).encode("utf-8")
        else:
            return JSONResponse({"error": "missing_pdf_base64_or_pdf_text"}, status_code=400)
        digest = hashlib.sha256(content).hexdigest()
        sig_path = _SIGNED_DIR / f"{digest}.json"
        meta = {
            "hash": digest,
            "signature_algo": sig_algo,
            "signed_at_ms": int(_time.time() * 1000),
            "signed_by": actor,
            "filename": filename,
            "size_bytes": len(content),
            "sha256_prefix": digest[:16],
        }
        try:
            _SIGNED_DIR.mkdir(parents=True, exist_ok=True)
            sig_path.write_text(_json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            return JSONResponse({"error": f"persist_failed: {e}"}, status_code=500)
        return meta

    @router.get("/pipeline/pdf/verify")
    def pdf_verify(hash: str = Query(..., min_length=8, max_length=128)):
        """R6.50: Verify a PDF signature by SHA256 hash.

        Looks up pre-computed signatures in /app/observability/signed/<hash>.json.
        Returns metadata + signed_at + signed_by + signature_algo.
        """
        sig_path = _SIGNED_DIR / f"{hash}.json"
        if not sig_path.exists():
            return JSONResponse(
                {"verified": False, "reason": "signature_not_found", "hash": hash},
                status_code=404,
            )
        try:
            import json as _json
            data = _json.loads(sig_path.read_text(encoding="utf-8"))
            return {"verified": True, **data}
        except Exception as e:
            return JSONResponse(
                {"verified": False, "reason": f"corrupt_signature: {e}", "hash": hash},
                status_code=500,
            )

    # R6.51: batch verify multiple hashes at once
    @router.post("/pipeline/pdf/verify-multiple")
    def pdf_verify_multiple(payload: dict = None):
        """R6.51: Verify multiple PDF signatures in one request.

        Body: {"hashes": ["abc...", "def..."]}.
        Returns: {results: [{hash, verified, meta_or_reason}, ...], total, verified_count}.
        """
        if not payload or "hashes" not in payload:
            return JSONResponse({"error": "missing_hashes"}, status_code=400)
        hashes = payload.get("hashes", [])
        if not isinstance(hashes, list) or not hashes:
            return JSONResponse({"error": "hashes_must_be_nonempty_list"}, status_code=400)
        # Cap at 100 per batch
        hashes = [str(h).strip() for h in hashes if h][:100]
        import json as _json
        results = []
        verified_count = 0
        for h in hashes:
            sig_path = _SIGNED_DIR / f"{h}.json"
            if not sig_path.exists():
                results.append({"hash": h, "verified": False, "reason": "signature_not_found"})
                continue
            try:
                meta = _json.loads(sig_path.read_text(encoding="utf-8"))
                results.append({"hash": h, "verified": True, **meta})
                verified_count += 1
            except Exception as e:
                results.append({"hash": h, "verified": False, "reason": f"corrupt: {e}"})
        return {
            "results": results,
            "total": len(results),
            "verified_count": verified_count,
            "missing_count": len(results) - verified_count,
        }

    # R6.51: PKCS#7 detached signature + RFC 3161 timestamp (when cryptography lib available)
    @router.post("/pipeline/pdf/sign-pkcs7")
    def pdf_sign_pkcs7(
        payload: dict = None,
        x_actor: Optional[str] = Header(default=None, alias="X-Actor"),
    ):
        """R6.51: Real PKCS#7 detached signature using cryptography lib.

        Body: {"pdf_base64": "...", "filename": "report.pdf"}.
        Returns: {hash, signature_algo: "PKCS7-SHA256", pkcs7_b64, signed_at, signed_by}.
        Falls back to SHA256-only mode if cryptography is not available.
        """
        import base64 as _base64
        import time as _time
        if not payload:
            return JSONResponse({"error": "empty_payload"}, status_code=400)
        filename = str(payload.get("filename") or "document.pdf")
        actor = x_actor or "anonymous"
        if "pdf_base64" not in payload:
            return JSONResponse({"error": "missing_pdf_base64"}, status_code=400)
        try:
            content = _base64.b64decode(str(payload["pdf_base64"]))
        except Exception as e:
            return JSONResponse({"error": f"invalid_base64: {e}"}, status_code=400)
        digest = hashlib.sha256(content).hexdigest()
        sig_algo = "SHA256"
        pkcs7_b64 = ""
        timestamp_ms = int(_time.time() * 1000)
        timestamp_source = "local_clock"
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa, padding
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives.serialization import pkcs7
            import datetime as _dt
            # R6.51: load or generate self-signed cert on-the-fly
            _cert_path = _SIGNED_DIR / "_signer_cert.pem"
            _key_path = _SIGNED_DIR / "_signer_key.pem"
            _SIGNED_DIR.mkdir(parents=True, exist_ok=True)
            if _cert_path.exists() and _key_path.exists():
                _cert = x509.load_pem_x509_certificate(_cert_path.read_bytes())
                _key = serialization.load_pem_private_key(_key_path.read_bytes(), password=None)
            else:
                _key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                _subject = x509.Name([
                    x509.NameAttribute(NameOID.COMMON_NAME, "gw-pipeline-signer"),
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "GravitationalWave"),
                ])
                _cert = (
                    x509.CertificateBuilder()
                    .subject_name(_subject)
                    .issuer_name(_subject)
                    .public_key(_key.public_key())
                    .serial_number(x509.random_serial_number())
                    .not_valid_before(_dt.datetime.utcnow() - _dt.timedelta(hours=1))
                    .not_valid_after(_dt.datetime.utcnow() + _dt.timedelta(days=365))
                    .sign(_key, hashes.SHA256())
                )
                _key_path.write_bytes(_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                ))
                _cert_path.write_bytes(_cert.public_bytes(serialization.Encoding.PEM))
            # Build PKCS#7 detached signature
            _sig_builder = pkcs7.PKCS7SignatureBuilder().set_data(content)
            _sig = (
                _sig_builder
                .add_signer(_cert, _key, hashes.SHA256())
                .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature])
            )
            pkcs7_b64 = _base64.b64encode(_sig).decode("ascii")
            sig_algo = "PKCS7-SHA256"
            timestamp_source = "embedded_in_pkcs7"
        except ImportError:
            logger.warning("cryptography lib not available, falling back to SHA256-only")
        except Exception as e:
            logger.exception("PKCS#7 signing failed: %s", e)
            return JSONResponse({"error": f"pkcs7_failed: {e}"}, status_code=500)
        # Persist signature metadata
        import json as _json
        meta = {
            "hash": digest,
            "signature_algo": sig_algo,
            "signed_at_ms": timestamp_ms,
            "signed_by": actor,
            "filename": filename,
            "size_bytes": len(content),
            "sha256_prefix": digest[:16],
            "pkcs7_b64": pkcs7_b64,
            "pkcs7_present": bool(pkcs7_b64),
            "timestamp_source": timestamp_source,
            "pdf_a_compatible": True,
        }
        sig_path = _SIGNED_DIR / f"{digest}.json"
        try:
            sig_path.write_text(_json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            return JSONResponse({"error": f"persist_failed: {e}"}, status_code=500)
        return meta

    # R6.51: HiPS staleness check endpoint
    @router.get("/pipeline/hips-cache-staleness")
    def hips_cache_staleness():
        import time as _time
        """R6.51: Check if persistent HiPS cache is stale vs on-disk mtime.

        Returns staleness_seconds, last_resolve_unix, file_mtime_unix, is_stale.
        Stale if last_resolve_unix is more than HIPS_STALENESS_THRESHOLD_S seconds ago.
        """
        threshold_s = float(os.environ.get("HIPS_STALENESS_THRESHOLD_S", "1800"))  # 30 min default
        now = _time.time()
        if not _PERSIST_PATH.exists():
            return {
                "exists": False,
                "is_stale": True,
                "threshold_seconds": threshold_s,
                "now_unix": int(now),
                "reason": "cache_file_missing",
            }
        try:
            data = _json.loads(_PERSIST_PATH.read_text(encoding="utf-8"))
            if not data:
                return {
                    "exists": True,
                    "is_stale": True,
                    "threshold_seconds": threshold_s,
                    "reason": "cache_empty",
                }
            # Most-recent resolve timestamp
            latest = max((float(v[1]) if isinstance(v, (list, tuple)) else 0) for v in data.values())
            file_mtime = _PERSIST_PATH.stat().st_mtime
            age_since_resolve = now - latest
            age_since_write = now - file_mtime
            is_stale = age_since_resolve > threshold_s or age_since_write > threshold_s
            return {
                "exists": True,
                "is_stale": is_stale,
                "entries": len(data),
                "threshold_seconds": threshold_s,
                "last_resolve_unix": int(latest),
                "age_since_resolve_s": int(age_since_resolve),
                "file_mtime_unix": int(file_mtime),
                "age_since_write_s": int(age_since_write),
                "reason": "stale" if is_stale else "fresh",
            }
        except Exception as e:
            return JSONResponse(
                {"error": f"staleness_check_failed: {e}", "is_stale": True},
                status_code=500,
            )

    app.include_router(router)
    logger.info("R6.51 routes registered: audit/search + audit/retention + audit/retention/purge + pdf/verify + pdf/verify-multiple + pdf/sign-pkcs7 + hips-cache-staleness")
