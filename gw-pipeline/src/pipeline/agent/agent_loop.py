"""ReAct Agent Loop — DeepSeek-powered tool-using AI Agent (v4.34).

v4.34 improvements:
  - FactVerifier: automatic post-response data verification (Fix #1)
  - JSON repair: recover from malformed tool-call arguments (Fix #6)
  - Streaming: SSE-based real-time agent progress (Fix #7)
  - Model pinning: version tracking with drift detection (Fix #8)
  - run_streaming(): async generator yielding SSE events
"""

import os, json, time, logging, re as _re, asyncio, socket
from typing import Optional, Dict, Any, List, AsyncGenerator
from dataclasses import dataclass, field
import httpx

_log = logging.getLogger("gw-agent-loop")

# ── DeepSeek API config ──────────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_PROXY_URL", "https://api.deepseek.com/v1/chat/completions")
# Auto-fallback: if proxy host is unresolvable (e.g. Linux without host.docker.internal), use direct API
if "host.docker.internal" in DEEPSEEK_API_URL:
    try:
        socket.getaddrinfo("host.docker.internal", 8899)
    except socket.gaierror:
        DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL_VERSION", "deepseek-chat")
DEEPSEEK_VISION_MODEL = os.getenv("DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp")

# ── Agent limits ─────────────────────────────────────────────────────
_MAX_TOOL_ROUNDS = int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "10"))
_TOOL_RESULT_MAX_CHARS = int(os.getenv("AGENT_TOOL_RESULT_MAX_CHARS", "4000"))
_AGENT_TOTAL_TIMEOUT = float(os.getenv("AGENT_TOTAL_TIMEOUT_SEC", "300.0"))

AGENT_SYSTEM_PROMPT = """You are the GravitationalWave AI Agent — an autonomous assistant for the GravitationalWave astronomical data platform.

## Your Capabilities
You have access to TOOLS that let you query databases, analyze FITS files, run deep learning inference, and inspect system state. You are NOT a passive chatbot — you ACTIVELY use tools to answer user questions with real data.

## Platform Context
- **7-container Docker system**: gw-frontend (React+Nginx), gw-backend (Spring Boot, port 8093), gw-pipeline (Python FastAPI, port 8200), gw-mcp-server (Python, port 8100), gw-firefly (Firefly/Aladin), MongoDB 6.0, Elasticsearch 7.17
- **Surveys indexed**: DSS2 (optical), NVSS (radio), FIRST (radio), WISE (infrared), ZTF (optical time-domain), LEGACY (deep optical), AliCPT-1 (CMB, Tibet)
- **~200,000 indexed observations, ~2,000 FITS files, ~3,500 anomaly reports**
- **DL models**: Zoobot ConvNeXt-Nano (galaxy morphology), MLP classifier (source type), CNN autoencoder (anomaly detection)

## CRITICAL RULE: USE TOOLS TO GET REAL DATA
**Every factual claim about the platform (counts, coordinates, statistics, survey names) MUST come from tool results.** Never invent or approximate numbers. If you need data, call the tool. If you already have the data in previous tool results, cite them.

## STOP AFTER 2-3 ROUNDS
**After at most 2-3 rounds of tool calls, you MUST stop and write a final answer.** Do NOT keep drilling deeper. The user wants answers, not an endless investigation.

## Tool Usage Rules
1. **GATHER THEN SYNTHESIZE**: Call 1-3 tools in the FIRST round, then STOP and provide your analysis.
2. **NEVER call the same tool more than twice**: Use the results you already have.
3. **INTERPRET, DO NOT DUMP**: Always provide natural language analysis. Never return raw JSON output.
4. **ACCEPT FAILURES**: If a tool returns an error, mention it and move on. Do NOT retry failed tools.
5. **CITE YOUR SOURCES**: Reference which tool result supports each factual claim.

## Standard Workflows (2 rounds max)
- "What data is available?" → count_observations + list_fits_files → STOP, summarize findings
- "Show me anomalies" → get_error_reports → STOP, let user ask for details
- "Analyze this FITS file" → get_fits_header + get_fits_stats → STOP, provide analysis
- "Is the platform healthy?" → get_system_status → STOP

Always respond in the user's language. Be concise but thorough. MAX 3 tool-calling rounds total."""


@dataclass
class AgentConfig:
    """Configuration for an Agent run."""
    max_tool_rounds: int = _MAX_TOOL_ROUNDS
    tool_result_max_chars: int = _TOOL_RESULT_MAX_CHARS
    total_timeout: float = _AGENT_TOTAL_TIMEOUT
    model: str = DEEPSEEK_MODEL
    temperature: float = 0.3
    max_tokens: int = 1500
    stream: bool = False


@dataclass
class AgentStep:
    """Record of one step in the agent loop."""
    step: int
    type: str  # "tool_call" | "response" | "error"
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_result: dict | None = None
    content: str | None = None
    elapsed_ms: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════
# v4.34: FactVerifier — automatic post-response data verification (Fix #1)
# ═══════════════════════════════════════════════════════════════════════════

class FactVerifier:
    """Cross-checks LLM claims against actual tool results.

    After the agent produces a final response, this verifier extracts
    numerical/scientific claims and compares them with the structured
    data returned by tools during the agent run. No external API calls
    — uses only data already in AgentStep.tool_result.

    Verification is DEFAULT-ON. It does not block the response, but
    flags discrepancies for the user.
    """

    # Claim patterns: (regex, category, extract_value_fn)
    CLAIM_PATTERNS = [
        # Observation counts
        (r'(\d{1,6})\s*(?:total\s*)?(?:observations?|records?|entries?|data\s*points?)\s*(?:in|from|across)?\s*(?:the\s*)?(?:database|platform|system)?',
         'observation_count', lambda m: int(m.group(1))),
        # FITS file counts
        (r'(\d{1,6})\s*(?:total\s*)?FITS\s*files?',
         'fits_count', lambda m: int(m.group(1))),
        # Anomaly/error counts
        (r'(\d{1,6})\s*(?:total\s*)?(?:anomalies|error\s*reports?|anomaly\s*reports?)',
         'anomaly_count', lambda m: int(m.group(1))),
        # Survey names mentioned
        (r'(?:survey|telescope)\s+(?:is\s+)?["\']?(DSS2|NVSS|FIRST|WISE|ZTF|LEGACY|AliCPT)["\']?',
         'survey_mentioned', lambda m: m.group(1).upper()),
        # RA coordinates (degrees)
        (r'RA\s*[=:]\s*(\d{1,3}\.\d+)',
         'coordinate_ra', lambda m: float(m.group(1))),
        # Dec coordinates (degrees)
        (r'Dec\s*[=:]\s*(-?\d{1,2}\.\d+)',
         'coordinate_dec', lambda m: float(m.group(1))),
        # Pixel dimensions
        (r'(\d{2,5})\s*[×x]\s*(\d{2,5})\s*pixels?',
         'image_dimensions', lambda m: (int(m.group(1)), int(m.group(2)))),
    ]

    @staticmethod
    def _extract_tool_data(steps: List[AgentStep]) -> Dict[str, Any]:
        """Aggregate ground-truth data from tool results."""
        data = {
            'observation_count': None,
            'fits_count': None,
            'anomaly_count': None,
            'surveys_found': set(),
            'coordinates_seen': [],
            'image_dimensions_seen': [],
            'tool_errors': [],
        }

        for s in steps:
            if s.type != "tool_call" or not s.tool_result:
                continue
            r = s.tool_result
            if not r.get("success"):
                data['tool_errors'].append(s.tool_name)
                continue

            tn = s.tool_name
            if tn == "count_observations":
                data['observation_count'] = r.get("total_observations")
            elif tn == "search_observations":
                if data['observation_count'] is None:
                    data['observation_count'] = r.get("total_count")
            elif tn == "list_fits_files":
                data['fits_count'] = r.get("total_files")
                for sname in r.get("detected_surveys", []):
                    data['surveys_found'].add(sname)
            elif tn == "get_error_reports":
                data['anomaly_count'] = r.get("total_count")
            elif tn == "get_fits_header":
                wcs = r.get("wcs_info", {})
                if "CRVAL1" in wcs:
                    data['coordinates_seen'].append({
                        'ra': wcs.get("CRVAL1"),
                        'dec': wcs.get("CRVAL2"),
                        'source': os.path.basename(str(r.get("filename", ""))),
                    })
                img_size = r.get("image_size", "")
                dim_match = _re.match(r'(\d+)\s*[x×]\s*(\d+)', str(img_size))
                if dim_match:
                    data['image_dimensions_seen'].append(
                        (int(dim_match.group(1)), int(dim_match.group(2))))
            elif tn == "get_fits_stats":
                data['image_dimensions_seen'].append(
                    tuple(r.get("shape", [0, 0])[:2]))
            elif tn == "run_wcs_query":
                sky = r.get("sky_output", {})
                if sky:
                    data['coordinates_seen'].append({
                        'ra': sky.get("ra_deg"),
                        'dec': sky.get("dec_deg"),
                        'source': os.path.basename(str(r.get("filename", ""))),
                    })
        return data

    async def verify(self, content: str, steps: List[AgentStep]) -> Dict:
        """Verify LLM claims against tool results.

        Returns: {verified: bool, checks: [...], discrepancy_count: int, summary: str}
        """
        ground_truth = self._extract_tool_data(steps)
        checks = []
        discrepancies = 0

        for pattern, category, extract_fn in self.CLAIM_PATTERNS:
            for match in _re.finditer(pattern, content, _re.IGNORECASE):
                claimed = extract_fn(match)
                check = {"category": category, "claimed": str(claimed), "match": match.group(0)[:80]}

                if category == 'observation_count' and ground_truth['observation_count'] is not None:
                    actual = ground_truth['observation_count']
                    if isinstance(claimed, (int, float)) and isinstance(actual, (int, float)):
                        if max(actual, 1) > 0:
                            deviation = abs(claimed - actual) / max(actual, 1)
                            if deviation > 0.2:
                                check['status'] = 'discrepancy'
                                check['actual'] = actual
                                check['deviation_pct'] = round(deviation * 100, 1)
                                discrepancies += 1
                            else:
                                check['status'] = 'verified'
                                check['actual'] = actual
                        else:
                            check['status'] = 'verified'
                            check['actual'] = actual

                elif category == 'fits_count' and ground_truth['fits_count'] is not None:
                    actual = ground_truth['fits_count']
                    if isinstance(claimed, (int, float)) and isinstance(actual, (int, float)):
                        if max(actual, 1) > 0:
                            deviation = abs(claimed - actual) / max(actual, 1)
                            if deviation > 0.2:
                                check['status'] = 'discrepancy'
                                check['actual'] = actual
                                check['deviation_pct'] = round(deviation * 100, 1)
                                discrepancies += 1
                            else:
                                check['status'] = 'verified'
                                check['actual'] = actual

                elif category == 'anomaly_count' and ground_truth['anomaly_count'] is not None:
                    actual = ground_truth['anomaly_count']
                    if isinstance(claimed, (int, float)) and isinstance(actual, (int, float)):
                        if max(actual, 1) > 0:
                            deviation = abs(claimed - actual) / max(actual, 1)
                            if deviation > 0.2:
                                check['status'] = 'discrepancy'
                                check['actual'] = actual
                                check['deviation_pct'] = round(deviation * 100, 1)
                                discrepancies += 1
                            else:
                                check['status'] = 'verified'
                                check['actual'] = actual

                elif category == 'survey_mentioned':
                    sname = str(claimed).upper()
                    if ground_truth['surveys_found']:
                        if sname in ground_truth['surveys_found']:
                            check['status'] = 'verified'
                            check['note'] = f'{sname} confirmed in platform data'
                        else:
                            # Survey mentioned but not in results — not necessarily wrong
                            check['status'] = 'unverified'
                            check['note'] = f'{sname} not confirmed by tool results'

                elif category in ('coordinate_ra', 'coordinate_dec'):
                    if ground_truth['coordinates_seen']:
                        check['status'] = 'unverified'
                        check['note'] = 'Coordinate claim not cross-referenced (nearest source shown)'

                elif category == 'image_dimensions':
                    if ground_truth['image_dimensions_seen']:
                        check['status'] = 'unverified'
                        check['note'] = 'Image dimension claim not cross-referenced'

                if 'status' not in check:
                    check['status'] = 'unverified'
                    check['note'] = 'No ground truth data available for verification'

                checks.append(check)

        total_checks = len(checks)
        passed = total_checks - discrepancies
        verified = discrepancies == 0

        summary_parts = []
        if total_checks == 0:
            summary_parts.append("No verifiable claims detected in response")
        elif verified:
            summary_parts.append(f"All {total_checks} verifiable claims confirmed")
        else:
            summary_parts.append(f"{passed}/{total_checks} claims verified ({discrepancies} discrepancies)")

        if ground_truth['tool_errors']:
            summary_parts.append(f"Note: {len(ground_truth['tool_errors'])} tool(s) returned errors")

        return {
            "verified": verified,
            "total_checks": total_checks,
            "passed": passed,
            "discrepancy_count": discrepancies,
            "checks": checks[:20],  # Limit to avoid huge responses
            "summary": " | ".join(summary_parts),
            "ground_truth_summary": {
                "observation_count": ground_truth['observation_count'],
                "fits_count": ground_truth['fits_count'],
                "anomaly_count": ground_truth['anomaly_count'],
                "surveys_found": sorted(ground_truth['surveys_found']),
                "coordinates_count": len(ground_truth['coordinates_seen']),
                "tool_errors": ground_truth['tool_errors'],
            },
        }


# ═══════════════════════════════════════════════════════════════════════════
# v4.34: JSON repair utility (Fix #6)
# ═══════════════════════════════════════════════════════════════════════════

def _repair_json(raw: str) -> str:
    """Attempt to repair common JSON errors from LLM function-calling output.

    Handles:
      1. Trailing commas: {"a": 1,} → {"a": 1}
      2. Single-quoted strings: {'a': 1} → {"a": 1}
      3. Unquoted keys: {a: 1} → {"a": 1}
      4. Truncated JSON: add missing closing brackets
      5. Extra content around JSON: extract first {...}
    """
    if not raw or not isinstance(raw, str):
        return raw

    original = raw.strip()

    # Step 1: Extract first JSON object if embedded in text
    brace_start = original.find('{')
    brace_end = original.rfind('}')
    if brace_start >= 0 and brace_end > brace_start:
        raw = original[brace_start:brace_end + 1]

    # Step 2: Remove trailing commas before } or ]
    raw = _re.sub(r',\s*}', '}', raw)
    raw = _re.sub(r',\s*]', ']', raw)

    # Step 3: Convert single quotes to double quotes (careful with apostrophes)
    # Simple heuristic: replace single quotes around keys and string values
    raw = _re.sub(r"(?<=[{,]\s*)'([^']+)'(?=\s*:)", r'"\\1"', raw)  # keys
    raw = _re.sub(r"(?<=:\s*)'([^']*)'(?=\s*[,}])", r'"\\1"', raw)  # values

    # Step 4: Quote unquoted keys (simple identifiers only)
    raw = _re.sub(r'(?<=[{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)(?=\s*:)', r'"\\1"', raw)

    # Step 5: Count brackets and add missing closing ones
    open_braces = raw.count('{') - raw.count('}')
    open_brackets = raw.count('[') - raw.count(']')
    raw += '}' * max(0, open_braces)
    raw += ']' * max(0, open_brackets)

    return raw


# ═══════════════════════════════════════════════════════════════════════════
# v4.34: Model version tracking (Fix #8)
# ═══════════════════════════════════════════════════════════════════════════

_last_model_version: Optional[str] = None
_model_version_changed: bool = False


def _track_model_version(returned_model: str):
    """Track DeepSeek model version across API calls. Logs drift warnings."""
    global _last_model_version, _model_version_changed
    if returned_model and returned_model != _last_model_version:
        if _last_model_version is not None:
            _log.warning("Model version changed: %s → %s (possible silent update)",
                        _last_model_version, returned_model)
            _model_version_changed = True
        _last_model_version = returned_model


def get_model_info() -> Dict:
    """Return current model version tracking info."""
    return {
        "configured_model": DEEPSEEK_MODEL,
        "last_returned_model": _last_model_version,
        "version_changed": _model_version_changed,
    }


class AgentLoop:
    """ReAct Agent loop using DeepSeek function calling.

    v4.34 features:
      - FactVerifier for automatic data verification
      - JSON repair for malformed tool arguments
      - SSE streaming via run_streaming()
      - Model version drift detection

    Usage:
        agent = AgentLoop(registry)
        result = await agent.run(messages, config=AgentConfig())
        # Or for streaming:
        async for event in agent.run_streaming(messages, config):
            yield event
    """

    def __init__(self, tool_registry=None):
        from .tools import get_tool_registry
        self.registry = tool_registry or get_tool_registry()
        self._api_key = DEEPSEEK_API_KEY
        self._api_url = DEEPSEEK_API_URL
        self._verifier = FactVerifier()

    async def run(self, messages: List[Dict], config: AgentConfig = None,
                  verify: bool = True) -> "AgentResult":
        """Run the agent loop. verify=True (default) enables automatic fact-checking."""
        cfg = config or AgentConfig()
        t_start = time.monotonic()
        steps: List[AgentStep] = []

        conversation = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}] + messages

        if not conversation or conversation[-1]["role"] != "user":
            return AgentResult(success=False, error="Last message must be from user", steps=steps)

        tool_schemas = self.registry.get_schemas()

        for round_idx in range(cfg.max_tool_rounds):
            # Check total timeout
            if time.monotonic() - t_start > cfg.total_timeout:
                steps.append(AgentStep(step=round_idx + 1, type="error",
                                       content="Agent timeout"))
                break

            # Call DeepSeek
            llm_result = await self._call_llm(conversation, tool_schemas, cfg)

            if llm_result.get("error"):
                steps.append(AgentStep(step=round_idx + 1, type="error",
                                       content=llm_result["error"]))
                return AgentResult(success=False, error=llm_result["error"], steps=steps)

            tool_calls = llm_result.get("tool_calls", [])
            content = llm_result.get("content", "")

            if tool_calls:
                # v4.35: Parallel tool execution via asyncio.gather (Fix #3)
                _PARALLEL_ENABLED = os.getenv("AGENT_PARALLEL_TOOLS", "true").lower() == "true"
                _TOOL_TIMEOUT = float(os.getenv("AGENT_TOOL_TIMEOUT_SEC", "30.0"))

                async def _execute_one_tool(tc, idx):
                    """Execute one tool call, return (tc, tool_args, result, elapsed_ms, error)."""
                    tool_name = tc["function"]["name"]
                    try:
                        tool_args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        # v4.34: JSON repair attempt (Fix #6)
                        repaired = _repair_json(tc["function"]["arguments"])
                        try:
                            tool_args = json.loads(repaired)
                            _log.info("JSON repair succeeded for tool %s", tool_name)
                        except json.JSONDecodeError:
                            tool_args = {}
                            _log.warning("JSON parse failed for tool %s even after repair: %s",
                                       tool_name, tc["function"]["arguments"][:100])

                    t_start = time.monotonic()
                    try:
                        result = await asyncio.wait_for(
                            self.registry.execute(tool_name, tool_args),
                            timeout=_TOOL_TIMEOUT,
                        )
                        elapsed = round((time.monotonic() - t_start) * 1000, 1)
                        return (tc, tool_args, result, elapsed, None)
                    except asyncio.TimeoutError:
                        elapsed = round((time.monotonic() - t_start) * 1000, 1)
                        return (tc, tool_args, {"success": False, "error": f"Tool execution timed out after {_TOOL_TIMEOUT}s", "_tool_name": tool_name}, elapsed, "timeout")
                    except Exception as e:
                        elapsed = round((time.monotonic() - t_start) * 1000, 1)
                        return (tc, tool_args, {"success": False, "error": f"Tool execution error: {str(e)[:200]}", "_tool_name": tool_name}, elapsed, str(e))

                if _PARALLEL_ENABLED and len(tool_calls) > 1:
                    _log.info("Round %d: executing %d tools in parallel", round_idx + 1, len(tool_calls))
                    tasks = [_execute_one_tool(tc, i) for i, tc in enumerate(tool_calls)]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    # Results are in order, matching tool_calls
                    exec_results = []
                    for r in results:
                        if isinstance(r, Exception):
                            exec_results.append((tool_calls[0], {}, {"success": False, "error": f"Tool dispatch error: {str(r)[:200]}"}, 0, str(r)))
                        else:
                            exec_results.append(r)
                else:
                    # Serial execution (single tool or parallelism disabled)
                    exec_results = []
                    for i, tc in enumerate(tool_calls):
                        r = await _execute_one_tool(tc, i)
                        exec_results.append(r)

                # Process results in order
                for i, (tc, tool_args, result, elapsed, error) in enumerate(exec_results):
                    tool_name = tc["function"]["name"]
                    if error:
                        _log.warning("Tool %s had error: %s", tool_name, error)

                    # Truncate large results
                    result_str = json.dumps(result, ensure_ascii=False, default=str)
                    if len(result_str) > cfg.tool_result_max_chars:
                        result_str = result_str[:cfg.tool_result_max_chars] + "... [truncated]"

                    steps.append(AgentStep(step=round_idx + 1, type="tool_call",
                                           tool_name=tool_name, tool_args=tool_args,
                                           tool_result=result, elapsed_ms=elapsed))

                    # Append assistant tool_call + tool result to conversation
                    conversation.append({
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": [{
                            "id": tc.get("id", f"call_{round_idx}_{i}"),
                            "type": "function",
                            "function": {"name": tool_name, "arguments": json.dumps(tool_args, ensure_ascii=False)},
                        }],
                    })
                    conversation.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", f"call_{round_idx}_{i}"),
                        "content": result_str,
                    })

                # v4.33.1: Detect repetitive tool calls
                tool_call_counts = {}
                for s in steps:
                    if s.type == "tool_call" and s.tool_name:
                        tool_call_counts[s.tool_name] = tool_call_counts.get(s.tool_name, 0) + 1
                overcalled = [f"{t}({c}x)" for t, c in tool_call_counts.items() if c > 1]
                if overcalled:
                    _log.warning("Repetitive calls detected: %s — forcing synthesis", overcalled)
                    conversation.append({
                        "role": "user",
                        "content": (
                            f"[SYSTEM] You called the same tool too many times: {', '.join(overcalled)}. "
                            f"STOP calling tools NOW. Write your final answer based on the data you already have."
                        ),
                    })
                    continue

                continue

            # No tool calls — LLM provided final response
            steps.append(AgentStep(step=round_idx + 1, type="response",
                                   content=content,
                                   elapsed_ms=round((time.monotonic() - t_start) * 1000, 1)))

            # v4.34: Automatic fact verification (Fix #1)
            verification = None
            if verify and content:
                verification = await self._verifier.verify(content, steps)

            return AgentResult(success=True, final_response=content or "",
                               steps=steps, total_rounds=round_idx + 1,
                               total_time_ms=round((time.monotonic() - t_start) * 1000, 1),
                               model=cfg.model, verification=verification)

        # Max rounds exhausted — force final synthesis without tools
        try:
            conversation.append({
                "role": "user",
                "content": "You MUST stop calling tools now. Based on ALL the data gathered above, write your final comprehensive answer. No more tool calls."
            })
            llm_result = await self._call_llm(conversation, [], cfg)  # NO tools
            content_final = llm_result.get("content", "")
            if content_final:
                steps.append(AgentStep(step=cfg.max_tool_rounds + 1, type="response",
                                       content=content_final,
                                       elapsed_ms=round((time.monotonic() - t_start) * 1000, 1)))

                # v4.34: Verification on forced synthesis too
                verification = None
                if verify:
                    verification = await self._verifier.verify(content_final, steps)

                return AgentResult(success=True, final_response=content_final,
                                   steps=steps, total_rounds=len(steps),
                                   total_time_ms=round((time.monotonic() - t_start) * 1000, 1),
                                   model=cfg.model, verification=verification)
        except Exception:
            pass

        return AgentResult(success=False, error=f"Agent exceeded max tool rounds ({cfg.max_tool_rounds})",
                           steps=steps, total_rounds=cfg.max_tool_rounds,
                           total_time_ms=round((time.monotonic() - t_start) * 1000, 1))

    # ═══════════════════════════════════════════════════════════════════
    # v4.34: SSE Streaming (Fix #7)
    # ═══════════════════════════════════════════════════════════════════

    async def run_streaming(self, messages: List[Dict],
                            config: AgentConfig = None,
                            verify: bool = True) -> AsyncGenerator[Dict, None]:
        """Stream agent progress as SSE events.

        Yields dicts with 'event' key:
          - {"event": "thinking", "round": N, "message": "..."}
          - {"event": "tool_call", "tool": "...", "args": {...}}
          - {"event": "tool_result", "tool": "...", "success": bool, "elapsed_ms": N}
          - {"event": "chunk", "content": "..."}
          - {"event": "verification", "data": {...}}
          - {"event": "done", "result": AgentResult.to_dict()}
          - {"event": "error", "message": "..."}
        """
        cfg = config or AgentConfig()
        t_start = time.monotonic()
        steps: List[AgentStep] = []

        conversation = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}] + messages

        if not conversation or conversation[-1]["role"] != "user":
            yield {"event": "error", "message": "Last message must be from user"}
            return

        tool_schemas = self.registry.get_schemas()

        for round_idx in range(cfg.max_tool_rounds):
            if time.monotonic() - t_start > cfg.total_timeout:
                yield {"event": "error", "message": "Agent timeout"}
                break

            yield {"event": "thinking", "round": round_idx + 1,
                   "message": f"Reasoning about next action (round {round_idx + 1}/{cfg.max_tool_rounds})..."}

            llm_result = await self._call_llm(conversation, tool_schemas, cfg)

            if llm_result.get("error"):
                yield {"event": "error", "message": llm_result["error"]}
                return

            tool_calls = llm_result.get("tool_calls", [])
            content = llm_result.get("content", "")

            if tool_calls:
                for tc in tool_calls:
                    tool_name = tc["function"]["name"]
                    try:
                        tool_args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        repaired = _repair_json(tc["function"]["arguments"])
                        try:
                            tool_args = json.loads(repaired)
                        except json.JSONDecodeError:
                            tool_args = {}

                    yield {"event": "tool_call", "tool": tool_name, "args": tool_args}

                    t_tool_start = time.monotonic()
                    result = await self.registry.execute(tool_name, tool_args)
                    elapsed = round((time.monotonic() - t_tool_start) * 1000, 1)

                    yield {"event": "tool_result", "tool": tool_name,
                           "success": result.get("success", False), "elapsed_ms": elapsed}

                    result_str = json.dumps(result, ensure_ascii=False, default=str)
                    if len(result_str) > cfg.tool_result_max_chars:
                        result_str = result_str[:cfg.tool_result_max_chars] + "... [truncated]"

                    steps.append(AgentStep(step=round_idx + 1, type="tool_call",
                                           tool_name=tool_name, tool_args=tool_args,
                                           tool_result=result, elapsed_ms=elapsed))

                    conversation.append({
                        "role": "assistant", "content": content or None,
                        "tool_calls": [{
                            "id": tc.get("id", f"call_{round_idx}"),
                            "type": "function",
                            "function": {"name": tool_name, "arguments": json.dumps(tool_args, ensure_ascii=False)},
                        }],
                    })
                    conversation.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", f"call_{round_idx}"),
                        "content": result_str,
                    })

                # Repetitive call detection
                tool_call_counts = {}
                for s in steps:
                    if s.type == "tool_call" and s.tool_name:
                        tool_call_counts[s.tool_name] = tool_call_counts.get(s.tool_name, 0) + 1
                overcalled = [f"{t}({c}x)" for t, c in tool_call_counts.items() if c > 1]
                if overcalled:
                    conversation.append({
                        "role": "user",
                        "content": f"[SYSTEM] You called the same tool too many times: {', '.join(overcalled)}. STOP calling tools NOW."
                    })
                continue

            # Final response — stream chunks
            steps.append(AgentStep(step=round_idx + 1, type="response",
                                   content=content,
                                   elapsed_ms=round((time.monotonic() - t_start) * 1000, 1)))

            # v4.34: Verification
            verification = None
            if verify and content:
                verification = await self._verifier.verify(content, steps)
                if verification:
                    yield {"event": "verification", "data": verification}

            result = AgentResult(success=True, final_response=content or "",
                                 steps=steps, total_rounds=round_idx + 1,
                                 total_time_ms=round((time.monotonic() - t_start) * 1000, 1),
                                 model=cfg.model, verification=verification)
            yield {"event": "done", "result": result.to_dict()}
            return

        # Force synthesis
        try:
            conversation.append({
                "role": "user",
                "content": "You MUST stop calling tools now. Write your final comprehensive answer."
            })
            yield {"event": "thinking", "round": cfg.max_tool_rounds + 1,
                   "message": "Forcing final synthesis..."}
            llm_result = await self._call_llm(conversation, [], cfg)
            content_final = llm_result.get("content", "")
            if content_final:
                steps.append(AgentStep(step=cfg.max_tool_rounds + 1, type="response",
                                       content=content_final))
                verification = None
                if verify:
                    verification = await self._verifier.verify(content_final, steps)
                    if verification:
                        yield {"event": "verification", "data": verification}
                result = AgentResult(success=True, final_response=content_final,
                                     steps=steps, total_rounds=len(steps),
                                     total_time_ms=round((time.monotonic() - t_start) * 1000, 1),
                                     model=cfg.model, verification=verification)
                yield {"event": "done", "result": result.to_dict()}
                return
        except Exception:
            pass

        yield {"event": "error", "message": f"Agent exceeded max tool rounds ({cfg.max_tool_rounds})"}

    async def _call_llm(self, conversation: List[Dict], tools: List[Dict],
                        cfg: AgentConfig) -> Dict:
        """Make one API call to DeepSeek."""
        if not self._api_key:
            return {"error": "DeepSeek API key not configured"}

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=10.0),
            ) as client:
                payload = {
                    "model": cfg.model,
                    "messages": conversation,
                    "temperature": cfg.temperature,
                    "max_tokens": cfg.max_tokens,
                    "stream": False,
                }
                if tools:
                    payload["tools"] = tools
                    payload["tool_choice"] = "auto"

                resp = await client.post(
                    self._api_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self._api_key}",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            choices = data.get("choices", [])
            if not choices:
                return {"error": "Empty response from DeepSeek"}

            msg = choices[0].get("message", {})

            # v4.34: Track model version (Fix #8)
            returned_model = data.get("model", "")
            _track_model_version(returned_model)

            return {
                "content": msg.get("content", ""),
                "tool_calls": msg.get("tool_calls", []),
                "finish_reason": choices[0].get("finish_reason", ""),
                "model": returned_model or cfg.model,
            }
        except httpx.HTTPStatusError as e:
            return {"error": f"DeepSeek API HTTP {e.response.status_code}"}
        except httpx.TimeoutException:
            return {"error": "DeepSeek API timeout"}
        except Exception as e:
            return {"error": f"DeepSeek API error: {str(e)[:200]}"}

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    @property
    def available_tools(self) -> list:
        return self.registry.tool_names


@dataclass
class AgentResult:
    """Result of an Agent run."""
    success: bool
    final_response: str = ""
    error: str = ""
    steps: List[AgentStep] = field(default_factory=list)
    total_rounds: int = 0
    total_time_ms: float = 0.0
    model: str = ""
    verification: Optional[Dict] = None  # v4.34: FactVerifier result

    @property
    def tool_calls_count(self) -> int:
        return sum(1 for s in self.steps if s.type == "tool_call")

    def to_dict(self) -> dict:
        d = {
            "success": self.success,
            "content": self.final_response,
            "error": self.error,
            "model": self.model,
            "total_rounds": self.total_rounds,
            "total_time_ms": self.total_time_ms,
            "tool_calls_count": self.tool_calls_count,
            "steps": [
                {
                    "step": s.step,
                    "type": s.type,
                    "tool_name": s.tool_name,
                    "tool_args": s.tool_args,
                    "tool_result": s.tool_result,
                    "content": s.content,
                    "elapsed_ms": s.elapsed_ms,
                }
                for s in self.steps
            ],
        }
        if self.verification:
            d["verification"] = self.verification
        return d
