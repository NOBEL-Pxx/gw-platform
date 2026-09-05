"""
v4.37: AI Metrics — Prometheus-format metrics for LLM/Agent observability.

Tracks:
  - LLM call count, token usage, latency histograms
  - Tool call count and latency
  - Active SSE stream connections
  - Error counts by type
  - Rate limit status
  - Anomaly detection throughput

Exposes GET /pipeline/metrics in Prometheus text format.
Integrates with agent_loop.py and server.py.

Usage:
    from .ai_metrics import get_metrics
    metrics = get_metrics()
    metrics.record_llm_call(tokens=1500, latency_ms=2340)
    metrics.record_tool_call(tool_name="count_observations", latency_ms=450)
"""
import time, threading, os
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# ── Configuration ──────────────────────────────────────────────────────────
METRICS_HISTOGRAM_BUCKETS = [100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000]  # ms
TOKEN_BUCKETS = [100, 500, 1000, 2000, 4000, 8000, 16000, 32000]


class AIMetrics:
    """Thread-safe metrics collector for AI/LLM operations.

    All metrics are in-memory (no external DB dependency). Designed for
    Prometheus scraping at ~15s intervals.
    """

    def __init__(self):
        self._lock = threading.Lock()

        # ── Counters (monotonically increasing) ──
        self._llm_calls_total: int = 0
        self._llm_tokens_total: int = 0
        self._tool_calls_total: int = 0
        self._stream_connections_total: int = 0
        self._anomalies_processed_total: int = 0
        self._errors_total: Dict[str, int] = defaultdict(int)
        self._injection_blocks_total: int = 0
        self._quota_exhaustions_total: int = 0

        # ── Gauges (current value) ──
        self._active_streams: int = 0
        self._rate_limit_remaining: int = -1  # -1 = unknown
        self._rate_limit_total: int = -1
        self._tool_cache_size: int = 0
        self._tool_cache_hit_rate: float = 0.0

        # ── Histograms (cumulative) ──
        self._llm_latency_buckets: Dict[int, int] = defaultdict(int)  # bucket_upper_ms → count
        self._tool_latency_buckets: Dict[int, int] = defaultdict(int)
        self._token_buckets: Dict[int, int] = defaultdict(int)

        # ── Startup info ──
        self._start_time = time.time()

    # ── Record Methods ──────────────────────────────────────────────────────

    def record_llm_call(self, tokens: int = 0, latency_ms: float = 0,
                        model: str = "", success: bool = True) -> None:
        """Record a completed LLM API call."""
        with self._lock:
            self._llm_calls_total += 1
            self._llm_tokens_total += tokens

            if latency_ms > 0:
                for bucket in sorted(METRICS_HISTOGRAM_BUCKETS):
                    if latency_ms <= bucket:
                        self._llm_latency_buckets[bucket] += 1
                        break

            if tokens > 0:
                for bucket in sorted(TOKEN_BUCKETS):
                    if tokens <= bucket:
                        self._token_buckets[bucket] += 1
                        break

            if not success:
                self._errors_total["llm_call_failed"] += 1

    def record_tool_call(self, tool_name: str = "", latency_ms: float = 0,
                         success: bool = True) -> None:
        """Record a completed tool execution."""
        with self._lock:
            self._tool_calls_total += 1

            if latency_ms > 0:
                for bucket in sorted(METRICS_HISTOGRAM_BUCKETS):
                    if latency_ms <= bucket:
                        self._tool_latency_buckets[bucket] += 1
                        break

            if not success:
                self._errors_total[f"tool_error:{tool_name}"] += 1

    def record_stream_start(self) -> None:
        """Record a new SSE stream connection."""
        with self._lock:
            self._stream_connections_total += 1
            self._active_streams += 1

    def record_stream_end(self) -> None:
        """Record an SSE stream disconnection."""
        with self._lock:
            self._active_streams = max(0, self._active_streams - 1)

    def record_error(self, error_type: str) -> None:
        """Record an error occurrence."""
        with self._lock:
            self._errors_total[error_type] += 1

    def record_injection_block(self) -> None:
        """Record a blocked prompt injection attempt."""
        with self._lock:
            self._injection_blocks_total += 1

    def record_quota_exhaustion(self) -> None:
        """Record a quota exhaustion event."""
        with self._lock:
            self._quota_exhaustions_total += 1

    def record_anomaly_processed(self, count: int = 1) -> None:
        """Record anomaly detection throughput."""
        with self._lock:
            self._anomalies_processed_total += count

    def set_rate_limit(self, remaining: int, total: int) -> None:
        """Update rate limit gauge."""
        with self._lock:
            self._rate_limit_remaining = remaining
            self._rate_limit_total = total

    def set_cache_stats(self, size: int, hit_rate: float) -> None:
        """Update tool cache stats."""
        with self._lock:
            self._tool_cache_size = size
            self._tool_cache_hit_rate = hit_rate

    # ── Prometheus Format Output ────────────────────────────────────────────

    def render_prometheus(self) -> str:
        """Render all metrics in Prometheus text format."""
        with self._lock:
            lines = []

            # Helpers
            def _add(name: str, typ: str, help_text: str, value, labels: dict = None):
                lines.append(f"# HELP {name} {help_text}")
                lines.append(f"# TYPE {name} {typ}")
                if labels:
                    label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
                    lines.append(f"{name}{{{label_str}}} {value}")
                else:
                    lines.append(f"{name} {value}")

            def _add_counter(name, help_text, value, labels=None):
                _add(name, "counter", help_text, value, labels)

            def _add_gauge(name, help_text, value, labels=None):
                _add(name, "gauge", help_text, value, labels)

            def _add_histogram(name, help_text, buckets_dict, sum_val, count_val):
                lines.append(f"# HELP {name} {help_text}")
                lines.append(f"# TYPE {name} histogram")
                cumulative = 0
                for bucket in sorted(METRICS_HISTOGRAM_BUCKETS):
                    cumulative += buckets_dict.get(bucket, 0)
                    lines.append(f'{name}_bucket{{le="{bucket}"}} {cumulative}')
                lines.append(f'{name}_bucket{{le="+Inf"}} {count_val}')
                lines.append(f"{name}_sum {sum_val}")
                lines.append(f"{name}_count {count_val}")

            # ── Counters ──
            _add_counter("gw_llm_calls_total", "Total LLM API calls", self._llm_calls_total)
            _add_counter("gw_llm_tokens_total", "Total tokens consumed", self._llm_tokens_total)
            _add_counter("gw_tool_calls_total", "Total tool executions", self._tool_calls_total)
            _add_counter("gw_stream_connections_total", "Total SSE stream connections",
                         self._stream_connections_total)
            _add_counter("gw_anomalies_processed_total", "Total anomalies processed",
                         self._anomalies_processed_total)
            _add_counter("gw_injection_blocks_total", "Total prompt injection blocks",
                         self._injection_blocks_total)
            _add_counter("gw_quota_exhaustions_total", "Total quota exhaustion events",
                         self._quota_exhaustions_total)

            # Error counters
            for error_type, count in sorted(self._errors_total.items()):
                _add_counter("gw_errors_total", f"Errors of type {error_type}", count,
                             {"error_type": error_type})

            # ── Gauges ──
            _add_gauge("gw_active_streams", "Currently active SSE streams",
                       self._active_streams)
            _add_gauge("gw_rate_limit_remaining", "Remaining rate limit quota",
                       self._rate_limit_remaining)
            _add_gauge("gw_rate_limit_total", "Total rate limit quota",
                       self._rate_limit_total)
            _add_gauge("gw_tool_cache_size", "Tool cache entries",
                       self._tool_cache_size)
            _add_gauge("gw_tool_cache_hit_rate", "Tool cache hit rate (0-1)",
                       f"{self._tool_cache_hit_rate:.3f}")
            _add_gauge("gw_uptime_seconds", "Process uptime in seconds",
                       f"{time.time() - self._start_time:.0f}")

            # ── Histograms ──
            _add_histogram("gw_llm_latency_ms", "LLM call latency in ms",
                           self._llm_latency_buckets, 0, self._llm_calls_total)
            _add_histogram("gw_tool_latency_ms", "Tool call latency in ms",
                           self._tool_latency_buckets, 0, self._tool_calls_total)

            return "\n".join(lines) + "\n"


# ── Module-level singleton ─────────────────────────────────────────────────
_metrics: Optional[AIMetrics] = None


def get_metrics() -> AIMetrics:
    """Get or create the global AIMetrics singleton."""
    global _metrics
    if _metrics is None:
        _metrics = AIMetrics()
    return _metrics
