# gw-pipeline

FastAPI service for gravitational wave astronomy data processing.
Part of the AliCPT platform (R6.0+).

## Quick Start

### Dev mode (permissive CORS, debug logs, /docs open)
```bash
pip install -r requirements.txt
python -m src.pipeline.server --profile dev --port 8200
```
- Open http://localhost:8200/docs for Swagger UI
- CORS allows all origins
- No Bearer token required
- DEBUG-level logs to stdout

### Prod mode (strict CORS, INFO logs, /docs closed, auth required)
```bash
PIPELINE_PROFILE=prod python -m src.pipeline.server --profile prod --port 8200
```
- CORS restricted to configured origins via `PIPELINE_CORS_ALLOW_ORIGINS`
- INFO-level logs only
- `/docs` and `/openapi.json` disabled
- Bearer token middleware enforced

### Env-var override
Either flag can be replaced by env var:
```bash
PIPELINE_PROFILE=prod python -m src.pipeline.server
```

## Configuration

### R6.52 #3: HiPS cache TTL by survey (override defaults via env)

| Env var | Default | Survey | Rationale |
|---------|---------|--------|-----------|
| `HIPS_TTL_DSS2_S`     | `604800`   (7 days) | DSS2     | DSS2 photographic plates rarely update; cache aggressively |
| `HIPS_TTL_2MASS_S`    | `2592000`  (30 days)| 2MASS    | 2MASS catalog is static since 2003 |
| `HIPS_TTL_GAIA_S`     | `86400`    (1 day)  | Gaia     | Gaia DR updates daily |
| `HIPS_TTL_DEFAULT_S`  | `1800`     (30 min) | fallback | Default for other surveys (CDS, PanSTARRS, etc.) |

Verify current TTLs via:
```bash
curl http://localhost:8200/pipeline/hips-cache-staleness?survey=DSS2
# {"survey": "DSS2", "threshold_seconds": 604800, ...}
```

To override (e.g., force 1-hour DSS2 cache during heavy re-ingest):
```bash
HIPS_TTL_DSS2_S=3600 python -m src.pipeline.server
```

### R6.53 #4: Profile env vars

| Env var | Default | Description |
|---------|---------|-------------|
| `PIPELINE_PROFILE`         | `dev`  | Active profile (also settable via `--profile` CLI flag) |
| `PIPELINE_DEV_MODE`        | `1`/`0`| Auto-set by profile; can override manually |
| `PIPELINE_CORS_ALLOW_ORIGINS` | `*` (dev) / empty (prod) | Comma-separated origins or `*` |
| `PIPELINE_LOG_LEVEL`       | `DEBUG` (dev) / `INFO` (prod) | Python logging level |
| `PIPELINE_DOCS_OPEN`       | `1` (dev) / `0` (prod) | Expose `/docs` and `/openapi.json` |
| `PIPELINE_AUTH_REQUIRED`   | `0` (dev) / `1` (prod) | Require Bearer token |

### R6.52 #7: Dependency pinning (R6.52+)
```
cryptography>=41.0.0   # PKCS#7 detached signature
PyMuPDF>=1.24.0        # PDF watermark EXIF
```
Baked into image via `sync-to-zjlab.py v4.39` SHA256 diff detection (auto-rebuild).

## Endpoints (high-level)

| Path | Method | Purpose |
|------|--------|---------|
| `/pipeline/hips-cache-staleness?survey=DSS2`  | GET    | Report current TTL threshold |
| `/pipeline/pdf/sign-pkcs7`                    | POST   | Sign PDF with PKCS#7 + embed XMP (PDF/A-2b compliant) |
| `/pipeline/pdf/verify-multiple`               | POST   | Parallel batch verify via ThreadPoolExecutor(N=8) |
| `/pipeline/pdf/watermark-exif`                | POST   | Embed watermark as PngInfo tEXt + XMP (PNG) or PyMuPDF (PDF) |
| `/pipeline/observability/audit/search`        | GET    | Full-text audit search with match_field + match_offset (R6.52 #1) |
| `/pipeline/observability/audit/retention/purge` | POST | Purge old audit entries (R6.50) |
| `/pipeline/observability/alert-routing`       | GET/POST | Alert routing CRUD |
| `/pipeline/sentry-compare-releases`           | POST   | Internal: Sentry compare (called by gw-frontend/scripts/sentry-compare-releases.sh) |

## Deployment

- Local: `docker compose up gw-pipeline`
- zjlab: `python D:/AliCPT/scripts/sync-to-zjlab.py pipeline`
  (auto-detects requirements.txt change → rebuild)

## Tests

```bash
pytest tests/ -v
```

## Versioning

- Current: v4.62 (R6.53)
- See `docs/changelog/` for per-iteration details
