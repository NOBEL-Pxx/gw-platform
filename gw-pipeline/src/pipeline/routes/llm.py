"""
LLM routes (R6.24+) -- LLM proxy / agent loop / tool dispatch.

Endpoints planned for this module:
    POST /llm/chat                  -- proxy to DeepSeek with streaming
    POST /llm/agent                 -- multi-step agent loop entry
    GET  /llm/tools                 -- list available agent tools
    POST /llm/tools/{name}/invoke   -- direct tool invocation (debugging)

Helpers exported:
    llm_helpers.build_system_prompt()
    llm_helpers.stream_response_to_sse()
    llm_helpers.sanitize_tool_args()

Why split llm separately from dl:
- LLM calls are I/O bound (network), DL is CPU/GPU bound
- Different retry policies: LLM uses exponential backoff with circuit breaker,
  DL uses simple request queue
- Different audit categories: LLM interactions logged with token counts,
  DL with model version + confidence
"""
from __future__ import annotations

from typing import Any


class _LlmHelpers:
    """Namespace for LLM-related pure functions."""

    def build_system_prompt(self, context: dict[str, Any]) -> str:
        from pipeline.server import build_system_prompt
        return build_system_prompt(context)

    def stream_response_to_sse(self, chunks: list[str]):
        from pipeline.server import stream_response_to_sse
        return stream_response_to_sse(chunks)

    def sanitize_tool_args(self, args: dict[str, Any]) -> dict[str, Any]:
        from pipeline.server import sanitize_tool_args
        return sanitize_tool_args(args)


llm_helpers = _LlmHelpers()


try:
    from fastapi import APIRouter
    router = APIRouter()
    # R6.24.3: @router.post("/chat") etc.
except ImportError:
    router = None


__all__ = ["llm_helpers", "router"]
