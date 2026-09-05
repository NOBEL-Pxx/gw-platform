"""HTTP client for Spring Boot backend API, with real-data fallback and degradation tracking.

v4.16: Added tiered degradation alerting — every response includes `_gw_source`
so AI callers can distinguish live data from fallback/mock/error.
"""
import os, json, time, logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
import httpx

logger = logging.getLogger("gw-mcp-client")

BACKEND_URL = os.getenv("BACKEND_URL", "http://gw-backend:8093")
PIPELINE_URL = os.getenv("PIPELINE_URL", "http://gw-pipeline:8200")
BASE_PATH = "/api/app/gravitationalwave"
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"
FALLBACK_JSON_ENABLED = os.getenv("FALLBACK_JSON_ENABLED", "true").lower() == "true"

# ── Real data loader ───────────────────────────────────────────────────────
try:
    from real_data_loader import get_observations, get_errors, get_details, get_comments as _get_comments
    _REAL_DATA = True
except ImportError:
    _REAL_DATA = False

# ── Degradation state (singleton, shared across requests) ──────────────────
@dataclass
class DegradeState:
    """Track backend health and degradation history for alerting."""
    consecutive_failures: int = 0
    last_success_ts: float = 0.0
    last_failure_ts: float = 0.0
    last_failure_error: str = ""
    total_requests: int = 0
    live_count: int = 0
    fallback_count: int = 0
    mock_count: int = 0
    error_count: int = 0
    # Per-endpoint failure tracking
    endpoint_failures: Dict[str, int] = field(default_factory=dict)

    def record_success(self):
        self.consecutive_failures = 0
        self.last_success_ts = time.time()
        self.total_requests += 1
        self.live_count += 1

    def record_fallback(self, endpoint: str, error: str):
        self.consecutive_failures += 1
        self.last_failure_ts = time.time()
        self.last_failure_error = error[:200]
        self.total_requests += 1
        self.fallback_count += 1
        self.endpoint_failures[endpoint] = self.endpoint_failures.get(endpoint, 0) + 1

    def record_mock(self):
        self.total_requests += 1
        self.mock_count += 1

    def record_error(self, endpoint: str, error: str):
        self.consecutive_failures += 1
        self.last_failure_ts = time.time()
        self.last_failure_error = error[:200]
        self.total_requests += 1
        self.error_count += 1
        self.endpoint_failures[endpoint] = self.endpoint_failures.get(endpoint, 0) + 1

    @property
    def is_degraded(self) -> bool:
        return self.consecutive_failures >= 3

    @property
    def alert_level(self) -> str:
        if self.consecutive_failures == 0:
            return "healthy"
        if self.consecutive_failures < 3:
            return "warning"
        if self.consecutive_failures < 10:
            return "degraded"
        return "critical"

    def status_dict(self) -> dict:
        return {
            "alert_level": self.alert_level,
            "consecutive_failures": self.consecutive_failures,
            "last_success_ts": self.last_success_ts,
            "last_failure_ts": self.last_failure_ts,
            "last_failure_error": self.last_failure_error,
            "total_requests": self.total_requests,
            "live_count": self.live_count,
            "fallback_count": self.fallback_count,
            "mock_count": self.mock_count,
            "error_count": self.error_count,
            "endpoint_failures": dict(self.endpoint_failures),
            "mock_mode": MOCK_MODE,
            "fallback_json_enabled": FALLBACK_JSON_ENABLED,
            "real_data_available": _REAL_DATA,
        }


_state = DegradeState()


def _page(data_list: List[Dict], page: int, page_size: int) -> Dict[str, Any]:
    total = len(data_list)
    ps = page_size if page_size > 0 else total
    start = (page - 1) * ps
    end = min(start + ps, total)
    paged = data_list[start:end] if start < total else []
    return {
        "error": {"code": "0", "msg": "ok"},
        "data": {
            "list": paged,
            "total_info": {"page": page, "page_size": ps, "total_count": total}
        }
    }


def _inject_source(result: dict, source: str, degrade_reason: str = None) -> dict:
    """Inject degradation metadata into every response.

    Key: _gw_source — allows AI callers to distinguish data quality:
      - "live": from the live Spring Boot backend
      - "fallback_json": backend unreachable, using local JSON export (STALE — see _data_export_date)
      - "mock": MOCK_MODE enabled, using synthetic data
      - "error": all layers failed
      - "pipeline-live": from gw-pipeline ONNX inference (v4.24)
      - "pipeline-error": pipeline inference failed (v4.24)
    """
    meta = {"_gw_source": source}
    if degrade_reason:
        meta["_gw_degrade_reason"] = degrade_reason
    if _state.alert_level != "healthy":
        meta["_gw_alert"] = _state.alert_level
    # v4.24: Include data export dates for fallback/mock sources
    if source in ("fallback_json", "mock") and _REAL_DATA:
        try:
            from real_data_loader import get_data_export_dates
            dates = get_data_export_dates()
            if dates:
                meta["_data_export_date"] = max(dates.values())  # newest export
        except Exception:
            pass
    # Merge into response — preserve existing keys
    result = dict(result)
    result.update(meta)
    return result


class GWClient:
    def __init__(self, base_url: str = None):
        self.base_url = (base_url or BACKEND_URL).rstrip("/")
        self.client = httpx.AsyncClient(timeout=10.0)
        self._use_mock = MOCK_MODE

    async def close(self):
        await self.client.aclose()

    async def _check_live(self) -> bool:
        """Quick liveness check against backend. Cached for 10 seconds."""
        try:
            r = await self.client.get(f"{self.base_url}{BASE_PATH}/error", params={"page": 1, "page_size": 1}, timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    async def _get(self, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{BASE_PATH}{path}"
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, data: Dict) -> Dict[str, Any]:
        url = f"{self.base_url}{BASE_PATH}{path}"
        resp = await self.client.post(url, json=data)
        resp.raise_for_status()
        return resp.json()

    # ═══════════════════════════════════════════════════════════════════════
    #  Tool methods — tiered degradation: live → fallback JSON → mock/error
    # ═══════════════════════════════════════════════════════════════════════

    async def search_observations(self, ra=None, dec=None, radius=1.0,
        telescope=None, uuid=None, page=1, page_size=10):
        endpoint = "search_observations"

        # Tier 1: Mock mode (explicitly requested)
        if self._use_mock:
            _state.record_mock()
            result = _page(get_observations() if _REAL_DATA else [], page, page_size)
            return _inject_source(result, "mock", "MOCK_MODE=true — no live backend calls")

        # Tier 2: Try live backend
        params = {"page": page, "page_size": page_size, "radius": radius}
        if ra is not None: params["ra"] = ra
        if dec is not None: params["dec"] = dec
        if telescope: params["telescope"] = telescope
        if uuid: params["uuid"] = uuid
        try:
            result = await self._get("/geoSearch", params)
            _state.record_success()
            return _inject_source(result, "live")
        except Exception as e:
            error_str = str(e)[:200]
            logger.warning(f"[{endpoint}] Backend failed: {error_str}")

            # Tier 3: Fallback to local JSON export
            if FALLBACK_JSON_ENABLED and _REAL_DATA:
                _state.record_fallback(endpoint, error_str)
                result = _page(get_observations(), page, page_size)
                return _inject_source(result, "fallback_json",
                    f"Backend unreachable ({error_str[:80]}). Using local JSON export. "
                    f"Data may be stale. Consecutive failures: {_state.consecutive_failures}")

            # Tier 4: All layers failed
            _state.record_error(endpoint, error_str)
            return _inject_source(
                {"error": {"code": "500", "msg": f"All data sources failed: {error_str}"}, "data": {}},
                "error", f"No fallback available — {error_str}")

    async def get_error_reports(self, page=1, page_size=10):
        endpoint = "get_error_reports"

        if self._use_mock:
            _state.record_mock()
            result = _page(get_errors() if _REAL_DATA else [], page, page_size)
            return _inject_source(result, "mock")

        try:
            result = await self._get("/error", {"page": page, "page_size": page_size})
            _state.record_success()
            return _inject_source(result, "live")
        except Exception as e:
            error_str = str(e)[:200]
            if FALLBACK_JSON_ENABLED and _REAL_DATA:
                _state.record_fallback(endpoint, error_str)
                result = _page(get_errors(), page, page_size)
                return _inject_source(result, "fallback_json",
                    f"Backend unreachable: {error_str[:80]}")
            _state.record_error(endpoint, error_str)
            return _inject_source(
                {"error": {"code": "500", "msg": f"All data sources failed: {error_str}"}, "data": {}},
                "error", str(e)[:200])

    async def get_error_detail(self, error_id, page=1, page_size=10):
        endpoint = "get_error_detail"

        if self._use_mock:
            _state.record_mock()
            result = _page(get_details() if _REAL_DATA else [], page, page_size)
            return _inject_source(result, "mock")

        try:
            result = await self._get(f"/error/{error_id}", {"page": page, "page_size": page_size})
            _state.record_success()
            return _inject_source(result, "live")
        except Exception as e:
            error_str = str(e)[:200]
            if FALLBACK_JSON_ENABLED and _REAL_DATA:
                _state.record_fallback(endpoint, error_str)
                result = _page(get_details(), page, page_size)
                items = result.get("data", {}).get("list", [])
                if items and "logContent" in items[0]:
                    result["data"]["logContent"] = items[0]["logContent"]
                return _inject_source(result, "fallback_json",
                    f"Backend unreachable: {error_str[:80]}")
            _state.record_error(endpoint, error_str)
            return _inject_source(
                {"error": {"code": "500", "msg": f"All data sources failed: {error_str}"}, "data": {}},
                "error", str(e)[:200])

    async def get_error_reference(self, error_id, uuid):
        endpoint = "get_error_reference"

        if self._use_mock:
            _state.record_mock()
            obs = get_observations() if _REAL_DATA else []
            result = {"error": {"code": "0", "msg": "ok"}, "data": obs[0] if obs else {}}
            return _inject_source(result, "mock")

        try:
            result = await self._get(f"/error/{error_id}/{uuid}")
            _state.record_success()
            return _inject_source(result, "live")
        except Exception as e:
            error_str = str(e)[:200]
            if FALLBACK_JSON_ENABLED and _REAL_DATA:
                _state.record_fallback(endpoint, error_str)
                obs = get_observations()
                result = {"error": {"code": "0", "msg": "ok"}, "data": obs[0] if obs else {}}
                return _inject_source(result, "fallback_json",
                    f"Backend unreachable: {error_str[:80]}")
            _state.record_error(endpoint, error_str)
            return _inject_source(
                {"error": {"code": "500", "msg": f"All data sources failed: {error_str}"}, "data": {}},
                "error", str(e)[:200])

    async def get_comments(self, grawave_id, page=1, size=10):
        endpoint = "get_comments"

        if self._use_mock:
            _state.record_mock()
            comments = [c for c in (_get_comments() if _REAL_DATA else []) if c.get("grawaveId") == grawave_id]
            result = _page(comments, page, size)
            return _inject_source(result, "mock")

        try:
            result = await self._get(f"/comments/{grawave_id}", {"page": page, "size": size})
            _state.record_success()
            return _inject_source(result, "live")
        except Exception as e:
            error_str = str(e)[:200]
            if FALLBACK_JSON_ENABLED and _REAL_DATA:
                _state.record_fallback(endpoint, error_str)
                comments = [c for c in _get_comments() if c.get("grawaveId") == grawave_id]
                result = _page(comments, page, size)
                return _inject_source(result, "fallback_json",
                    f"Backend unreachable: {error_str[:80]}")
            _state.record_error(endpoint, error_str)
            return _inject_source(
                {"error": {"code": "500", "msg": f"All data sources failed: {error_str}"}, "data": {}},
                "error", str(e)[:200])

    async def add_comment(self, grawave_id, content, user_id, category="analysis"):
        endpoint = "add_comment"
        try:
            result = await self._post("/comments", {
                "grawaveId": grawave_id, "content": content,
                "userId": user_id, "category": category
            })
            _state.record_success()
            return _inject_source(result, "live")
        except Exception as e:
            error_str = str(e)[:200]
            _state.record_error(endpoint, error_str)
            return _inject_source(
                {"error": {"code": "500", "msg": f"Backend error: {error_str}"}, "data": {}},
                "error", str(e)[:200])

    # ── Degradation status API ──────────────────────────────────────────
    def degrade_status(self) -> dict:
        return _state.status_dict()

    async def health_check(self) -> dict:
        """Deep health: liveness + degradation state + alert level."""
        live = await self._check_live()
        status = _state.status_dict()
        status["backend_reachable"] = live
        return status


# ── Pipeline client for DL inference tools (v4.24) ──────────────────
class PipelineClient:
    """HTTP client for gw-pipeline DL inference endpoints.

    Separate from GWClient because the pipeline is a different service
    (Python FastAPI, not Spring Boot) with different API conventions.
    No tiered degradation — pipeline is local ONNX inference, so
    failures are reported directly to the AI caller.
    """
    def __init__(self, base_url: str = None):
        self.base_url = (base_url or PIPELINE_URL).rstrip("/")
        self._client = None

    async def _get_client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)  # DL inference can be slow
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def classify_galaxy_morphology(self, filename: str) -> dict:
        """POST /pipeline/dl/morphology — 5-class galaxy morphology."""
        client = await self._get_client()
        resp = await client.post(f"{self.base_url}/pipeline/dl/morphology",
                                 json={"filename": filename})
        resp.raise_for_status()
        data = resp.json()
        data["_gw_source"] = "pipeline-live"
        return data

    async def classify_source_type(self, filename: str) -> dict:
        """POST /pipeline/dl/source-type — star/galaxy/quasar classification."""
        client = await self._get_client()
        resp = await client.post(f"{self.base_url}/pipeline/dl/source-type",
                                 json={"filename": filename})
        resp.raise_for_status()
        data = resp.json()
        data["_gw_source"] = "pipeline-live"
        return data

    async def detect_anomaly(self, filename: str) -> dict:
        """POST /pipeline/dl/anomaly/detect — CNN autoencoder anomaly detection."""
        client = await self._get_client()
        resp = await client.post(f"{self.base_url}/pipeline/dl/anomaly/detect",
                                 json={"filename": filename})
        resp.raise_for_status()
        data = resp.json()
        data["_gw_source"] = "pipeline-live"
        return data

    async def get_model_status(self) -> dict:
        """GET /pipeline/dl/status — all DL model statuses."""
        client = await self._get_client()
        resp = await client.get(f"{self.base_url}/pipeline/dl/status")
        resp.raise_for_status()
        data = resp.json()
        data["_gw_source"] = "pipeline-live"
        return data


# Singleton
client = GWClient()
pipeline = PipelineClient()
degrade_state = _state
