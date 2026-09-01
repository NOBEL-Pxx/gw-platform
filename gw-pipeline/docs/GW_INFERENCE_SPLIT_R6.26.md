# R6.26 — gw-inference Service Split Plan

## Context

Currently `gw-pipeline` is a single FastAPI process handling:
  - LLM proxy (DeepSeek API)
  - DL inference (ONNX, 3 models ~150 MB each)
  - FITS processing (source detection, photometry, WCS)
  - Thumbnail generation
  - Anomaly classification
  - User-facing routes (observation search, anomaly dashboard)

**Memory ceiling**: container `memory: 1G` (docker-compose.yml line 269).
With ONNX models pre-loaded (warmup_models()), only ~200 MB is left for
FITS decode + thumbnail cache + spike handling. Heavy concurrent traffic
triggers:
  - DL request rejection when free memory < 200 MB
  - Thumbnail cache thrash when 5000-entry LRU exceeds memory
  - ProcessPoolExecutor (Python GIL) limits CPU-bound parallelism

**Hardcoded concurrency limits**:
  - `_DL_MAX_CONCURRENT = 3` (line 367) -- blocks under load
  - `_HEAVY_WORKERS = min(CPU, 16)` -- fixed, doesn't adapt
  - `THUMBNAIL_CACHE_SIZE = 5000` -- doesn't scale with memory

**Goal**: Extract DL inference into a standalone `gw-inference` service that:
  1. Scales horizontally (2-10 replicas behind a load balancer)
  2. Owns its memory budget (containers sized for ONNX, not the full pipeline)
  3. Exposes a clean HTTP API (`POST /infer`) -- gw-pipeline becomes a client
  4. Replaces `asyncio.Semaphore(3)` with service-level rate limiting

## Architecture

### Before (single container)

```
                    ┌─ gw-pipeline (1 GB) ─────────────────────────┐
                    │                                               │
   gw-frontend ──► │ FastAPI  ──► DL inference (ONNX, 3 models)    │
                    │           ──► FITS decode                     │
                    │           ──► Source detection (CPU-bound)   │
                    │           ──► Thumbnail cache (5000 entries)  │
                    │           ──► LLM proxy (DeepSeek)            │
                    │           ──► Anomaly classification          │
                    └───────────────────────────────────────────────┘
```

### After (R6.26)

```
                    ┌─ gw-pipeline (1 GB) ─────────────────────────┐
                    │                                               │
   gw-frontend ──► │ FastAPI  ──► FITS decode                     │
                    │           ──► Source detection (CPU-bound)   │
                    │           ──► Thumbnail cache (dynamic)      │
                    │           ──► LLM proxy (DeepSeek)            │
                    │           ──► Anomaly classification          │
                    │           ──► /infer ──HTTP──► gw-inference  │
                    │                          (x N replicas)      │
                    └──────────────────────┬────────────────────────┘
                                           │
                                           ▼
                    ┌─ gw-inference (1 GB each, 2-10 replicas) ─────┐
                    │                                               │
                    │ FastAPI  ──► ONNX Runtime (3 models, warm)    │
                    │           ──► Lightweight feature extractors  │
                    │           ──► Async I/O (no event loop block) │
                    │                                               │
                    │ POST /infer {model, input_data, request_id}   │
                    │  ──► returns {predictions, scores, timing}    │
                    └───────────────────────────────────────────────┘
```

## gw-inference service contract

### POST /infer

Request:
```json
{
  "model": "morphology_classifier" | "anomaly_detector" | "psf_estimator",
  "input": {
    "type": "fits_url" | "numpy_array",
    "data": "http://gw-backend:8093/fits/abc123.fits" | "<base64 npz>",
    "shape": [256, 256]
  },
  "request_id": "uuid-v4",
  "timeout_sec": 30
}
```

Response:
```json
{
  "model": "morphology_classifier",
  "predictions": [{"label": "spiral_galaxy", "score": 0.92}, ...],
  "timing_ms": 47,
  "model_version": "1.2.3",
  "request_id": "uuid-v4"
}
```

### GET /health

Standard health probe (used by Docker HEALTHCHECK + load balancer).

### GET /status

Returns loaded models, current concurrency, average latency, error rate.

## Migration phases

### Phase 1 (R6.26) — Code preparation
- [x] Create `memory_budget.py` (startup budget calculation)
- [x] Create `process_pool.py` (ProcessPoolExecutor for CPU-bound FITS)
- [x] Create `user_quota.py` (per-user daily quota, MongoDB)
- [ ] Wire `memory_budget.get_max_concurrent_inferences()` into server.py
- [ ] Replace hardcoded `THUMBNAIL_CACHE_SIZE = 5000` with `get_thumbnail_cache_size()`
- [ ] Replace FITS ThreadPoolExecutor call sites with `run_in_fits_pool()`

### Phase 2 (R6.27) — gw-inference skeleton
- [ ] Create `gw-inference/` directory (separate package)
- [ ] FastAPI app with `/infer`, `/health`, `/status` routes
- [ ] Docker image `gw-inference:latest` (multi-stage build)
- [ ] docker-compose.yml entry (initially 1 replica)
- [ ] gw-net network attachment

### Phase 3 (R6.28) — Client refactor
- [ ] gw-pipeline: replace `asyncio.Semaphore(3) + ONNX in-process` with `httpx.AsyncClient.post(/infer)`
- [ ] Add circuit breaker + retry (tenacity)
- [ ] Load balancer config (round-robin across replicas)

### Phase 4 (R6.29) — Horizontal scaling
- [ ] docker-compose.yml: `gw-inference` scaled to 2 replicas
- [ ] Kubernetes manifests (HPA on CPU > 70%)
- [ ] Prometheus metrics (inference latency histogram)

### Phase 5 (R6.30) — Production rollout
- [ ] Production deploy with traffic shadowing (5% → 25% → 100%)
- [ ] Deprecate in-process DL (keep as fallback for offline mode)
- [ ] Per-model autoscaling

## Memory budget allocation (after split)

### gw-pipeline (1 GB)
- Python + FastAPI: 150 MB
- ONNX models: **0 MB** (moved to gw-inference)
- FITS decode buffers: 120 MB
- Thumbnail cache (dynamic): 400 MB (~6500 thumbs at 60 KB)
- Free pool: 80 MB
- Process pool workers (x3): ~150 MB peak (FITS work)
- LLM proxy cache: 100 MB

### gw-inference (1 GB per replica, 2-10 replicas)
- Python + FastAPI: 150 MB
- ONNX models (3, warm): 450 MB
- Inference request buffers: 200 MB
- Free pool: 200 MB

Total cluster memory: 2-10 GB (vs. 1 GB today) — but each replica is
independently scalable. Under sustained load, scale to 10 replicas = 10 GB
distributed. Under idle, scale to 2 = 2 GB.

## Backward compatibility

R6.26 introduces no breaking changes:
- All new modules are additive
- `memory_budget.py` falls back to env vars / hardcoded defaults if cgroup
  detection fails
- `process_pool.py` is opt-in (no FITS callsite uses it in R6.26)
- `user_quota.py` is opt-in (LlmController.java unchanged)

## Verification

1. `python -m memory_budget` standalone: prints budget report for current container
2. `python -m process_pool` standalone: spawns 4 CPU-bound tasks, prints timings
3. `python -m user_quota` integration test: simulates 3 users, verifies counters
4. After Phase 1 wiring: gw-pipeline /status endpoint shows budget-aware values

## Risks & rollback

| Risk | Mitigation |
|------|------------|
| cgroup detection returns wrong limit | Env override `GW_MEMORY_LIMIT_MB` always wins |
| ProcessPoolExecutor spawn overhead on Windows | Use `mp_context="spawn"` (default); measure cold-start |
| UserQuota MongoDB unavailable | Fail-open (allow request, log error) |
| gw-inference network unreachable (R6.27+) | Circuit breaker + fallback to in-process ONNX |
