"""Local LLM Fallback — Ollama-powered offline inference (v4.34).

Three-tier fallback strategy:
  1. Ollama (local LLM) — if available, provides real LLM inference
  2. Keyword match — astronomy-domain keyword responses (existing)
  3. Static default — generic "AI unavailable" message

When DeepSeek API quota is exhausted or unreachable, this module provides
a local alternative that keeps the AI assistant functional without
sending user data to third-party servers.

Data sovereignty: All processing stays inside the gw-pipeline container.
"""

import os, logging
from typing import List, Dict, Optional
import httpx

_log = logging.getLogger("gw-local-llm")

# ── Config ────────────────────────────────────────────────────────────
OLLAMA_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT = float(os.getenv("LOCAL_LLM_TIMEOUT_SEC", "30.0"))

# ── Keyword response map (existing from server.py) ────────────────────
_OFFLINE_KEYWORDS: Dict[str, str] = {
    "dss2": "DSS2 (Digitized Sky Survey 2) is an optical all-sky survey providing deep imaging in B, R, and IR bands. The platform indexes DSS2 observations via the Spring Boot backend API at /api/app/gravitationalwave/geoSearch.",
    "nvss": "NVSS (NRAO VLA Sky Survey) is a 1.4 GHz radio continuum survey covering the sky north of -40° declination. Query it via the geoSearch endpoint with telescope=NVSS.",
    "first": "FIRST (Faint Images of the Radio Sky at Twenty-cm) is a radio survey covering ~10,000 deg². Use search_observations with telescope=FIRST.",
    "wise": "WISE (Wide-field Infrared Survey Explorer) provides all-sky infrared imaging. Available bands: W1 (3.4μm), W2 (4.6μm), W3 (12μm), W4 (22μm).",
    "ztf": "ZTF (Zwicky Transient Facility) is an optical time-domain survey scanning the northern sky every 2 days. Ideal for transient and variable source studies.",
    "legacy": "The DESI Legacy Imaging Surveys provide deep optical imaging in g, r, z bands covering ~14,000 deg². Data available at /geoSearch?telescope=LEGACY.",
    "alicpt": "AliCPT-1 (Ali CMB Polarization Telescope, Tibet) is a ground-based CMB experiment at 5,250m altitude. The platform stores anomaly-detection FITS files from AliCPT-1 observation runs.",
    "anomaly": "Anomaly detection is available through the DL models (CNN autoencoder) and rule-based classifier. Call detect_anomaly_dl to analyze a specific FITS file, or get_error_reports to browse existing anomaly reports.",
    "morphology": "Galaxy morphology classification uses the Zoobot ConvNeXt-Nano ONNX model. Call classify_galaxy_morphology with a FITS filename to classify it as spiral, elliptical, edge-on, merger, or irregular.",
    "wcs": "World Coordinate System (WCS) maps pixel positions to sky coordinates. Use run_wcs_query with a FITS filename to convert between pixel and RA/Dec coordinates.",
    "fits": "FITS (Flexible Image Transport System) is the standard astronomical data format. The platform stores ~2,000 FITS files. Use list_fits_files to browse available files, get_fits_header for metadata, and get_fits_stats for statistical analysis.",
    "how": "You can ask me to:\n  * Search observations by sky coordinates (search_observations)\n  * Browse anomaly reports (get_error_reports)\n  * Analyze FITS files (get_fits_header, get_fits_stats)\n  * Run DL classification (classify_galaxy_morphology, classify_source_type)\n  * Check system health (get_system_status)\n\nI am currently in offline mode — switch to Agent mode for tool-using capabilities.",
    "data": "The platform indexes gravitational wave follow-up observations from 7 surveys: DSS2, NVSS, FIRST, WISE, ZTF, LEGACY, and AliCPT-1. Use count_observations to check data availability, or search_observations to query by coordinates.",
}

_OFFLINE_DEFAULT = (
    "I am currently operating in offline mode (DeepSeek API quota exhausted or unreachable). "
    "I can answer basic astronomy questions using local knowledge. "
    "For detailed data queries, please wait for quota reset at UTC midnight, "
    "or contact the platform administrator to increase the quota limit.\n\n"
    "Try asking about: DSS2, NVSS, FIRST, WISE, ZTF, LEGACY, AliCPT, anomaly detection, "
    "galaxy morphology, WCS coordinates, or FITS file analysis."
)

_LOCAL_SYSTEM_PROMPT = """You are a gravitational wave astronomy assistant. You answer questions about:
- Astronomical surveys: DSS2, NVSS, FIRST, WISE, ZTF, LEGACY, AliCPT-1
- FITS file analysis and WCS coordinates
- Galaxy morphology classification and anomaly detection
- Gravitational wave data platform operations

Keep responses concise (under 300 words). Be factual — if you don't know, say so."""


class LocalLLMFallback:
    """Three-tier offline LLM fallback.

    Usage:
        fallback = LocalLLMFallback()
        await fallback.initialize()  # Check Ollama availability
        reply = await fallback.chat([{"role": "user", "content": "What is DSS2?"}])
    """

    def __init__(self):
        self.ollama_url = OLLAMA_URL
        self.ollama_model = OLLAMA_MODEL
        self.ollama_available = False
        self.ollama_checked = False

    async def initialize(self):
        """Check if Ollama is reachable and has the configured model."""
        if self.ollama_checked:
            return
        self.ollama_checked = True

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self.ollama_url}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    model_names = [m.get("name", "") for m in models]
                    if self.ollama_model in model_names or any(
                        m.startswith(self.ollama_model.split(":")[0]) for m in model_names
                    ):
                        self.ollama_available = True
                        _log.info("Ollama available: model=%s at %s", self.ollama_model, self.ollama_url)
                    else:
                        _log.warning("Ollama reachable but model '%s' not found. Available: %s",
                                   self.ollama_model, model_names[:5])
        except Exception as e:
            _log.info("Ollama not available at %s: %s — will use keyword fallback", self.ollama_url, e)

    async def chat(self, messages: List[Dict]) -> str:
        """Generate response using best available method."""
        await self.initialize()

        last_message = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_message = m.get("content", "")
                break

        if not last_message:
            return _OFFLINE_DEFAULT

        if self.ollama_available:
            try:
                return await self._ollama_chat(messages)
            except Exception as e:
                _log.warning("Ollama chat failed: %s — falling back to keywords", e)

        keyword_reply = self._keyword_match(last_message)
        if keyword_reply:
            return keyword_reply

        return _OFFLINE_DEFAULT

    async def _ollama_chat(self, messages: List[Dict]) -> str:
        """Query Ollama API."""
        ollama_messages = [{"role": "system", "content": _LOCAL_SYSTEM_PROMPT}]
        for m in messages[-6:]:
            role = m.get("role", "user")
            if role in ("user", "assistant"):
                ollama_messages.append({"role": role, "content": m.get("content", "")})

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=OLLAMA_TIMEOUT, write=10.0, pool=5.0),
        ) as client:
            resp = await client.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": self.ollama_model,
                    "messages": ollama_messages,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 512},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", _OFFLINE_DEFAULT)

    def _keyword_match(self, user_message: str) -> Optional[str]:
        """Match user message against astronomy keywords."""
        msg_lower = user_message.lower()
        matched = []
        for keyword, response in _OFFLINE_KEYWORDS.items():
            if keyword in msg_lower:
                matched.append(response)
        if matched:
            return "\n\n".join(matched)
        return None

    @property
    def status(self) -> Dict:
        """Return fallback status for /pipeline/llm/status."""
        return {
            "ollama_available": self.ollama_available,
            "ollama_url": self.ollama_url,
            "ollama_model": self.ollama_model,
            "keyword_entries": len(_OFFLINE_KEYWORDS),
            "tier": "ollama" if self.ollama_available else "keyword",
        }


_fallback: Optional[LocalLLMFallback] = None

def get_local_llm() -> LocalLLMFallback:
    """Get or create the singleton LocalLLMFallback."""
    global _fallback
    if _fallback is None:
        _fallback = LocalLLMFallback()
    return _fallback
