"""GW AI Agent — DeepSeek-powered agent with tool-use capabilities (v4.34).

v4.34: FactVerifier (automatic data verification), JSON repair, SSE streaming,
model version tracking, enhanced safety measures.

Architecture:
  User message -> Agent Loop (ReAct) -> DeepSeek API (with tools)
    -> [think] -> tool_call -> execute tool -> result -> DeepSeek
    -> [think] -> final_response -> FactVerifier -> User

Tools are executed server-side within the gw-pipeline container.
Database access is through the Spring Boot backend API (not direct DB).
"""

from .agent_loop import AgentLoop, AgentConfig, FactVerifier, get_model_info
from .agent_loop import _MAX_TOOL_ROUNDS, _TOOL_RESULT_MAX_CHARS, _AGENT_TOTAL_TIMEOUT
from .tools import ToolRegistry, get_tool_registry

__all__ = ["AgentLoop", "AgentConfig", "FactVerifier", "ToolRegistry",
           "get_tool_registry", "get_model_info",
           "_MAX_TOOL_ROUNDS", "_TOOL_RESULT_MAX_CHARS", "_AGENT_TOTAL_TIMEOUT"]

# v4.35: Tool cache (Fix #2)
from ..tool_cache import get_tool_cache, ToolCache  # noqa: F401
