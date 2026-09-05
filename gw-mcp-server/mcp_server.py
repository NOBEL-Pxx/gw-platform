"""MCP server entry point — supports both stdio and SSE/HTTP transports.

v4.16: Added SSE transport for custom AI model integration.
       Previously only supported Claude Desktop via stdio.

==== Usage ====

1. Claude Desktop (stdio):
   python mcp_server.py --transport stdio

2. HTTP/SSE for custom AI models (e.g., self-hosted LLM agents):
   python mcp_server.py --transport sse --port 8101

   Then connect your AI agent to: http://localhost:8101/sse
   The /messages endpoint handles POST for tool execution.

3. Claude Desktop config for stdio:
   {"mcpServers": {"gw-mcp": {"command": "python",
     "args": ["D:/AliCPT/gw-mcp-server/mcp_server.py", "--transport", "stdio"],
     "env": {"BACKEND_URL": "http://gw-backend:8093"}}}}

4. Custom AI model integration (SSE/HTTP):
   Start the server with --transport sse, then use the SSE endpoint
   as a standard MCP streamable-http transport.

   Python client example:
     import asyncio
     from mcp.client.sse import sse_client
     async with sse_client("http://localhost:8101/sse") as (read, write):
         # Standard MCP protocol over SSE
         ...

   Curl example (list tools):
     curl http://localhost:8101/tools
     curl http://localhost:8101/degrade-status

   Or use FastMCP's built-in SSE support via the /mcp endpoint.
"""
import sys, os, argparse

sys.path.insert(0, os.path.dirname(__file__))
from tools import mcp


def run_stdio():
    """Standard Claude Desktop integration via stdio."""
    mcp.run(transport="stdio")


def run_sse(host: str = "0.0.0.0", port: int = 8101):
    """HTTP/SSE transport for custom AI model integration.

    FastMCP's SSE transport provides:
      - GET  /sse       — SSE event stream for MCP protocol
      - POST /messages  — JSON-RPC messages from the AI client
      - GET  /tools     — list available tools (our custom endpoint)

    Compatible with any MCP client that supports SSE transport
    (not just Claude Desktop — works with custom LLM agents).
    """
    print(f"GW MCP Server v4.16 — SSE transport")
    print(f"  Listening on http://{host}:{port}")
    print(f"  SSE endpoint:  http://{host}:{port}/sse")
    print(f"  Messages:      http://{host}:{port}/messages")
    print(f"  Tools list:    http://{host}:{port}/tools")
    print(f"  Health:        http://{host}:{port}/health")
    print("")
    # FastMCP built-in SSE support
    mcp.settings.host = host
    mcp.settings.port = port
    mcp.run(transport="sse")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GW MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio",
                        help="Transport protocol: stdio (Claude Desktop) or sse (custom AI models)")
    parser.add_argument("--host", default="0.0.0.0", help="Host for SSE transport (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8101, help="Port for SSE transport (default: 8101)")
    args = parser.parse_args()

    if args.transport == "sse":
        run_sse(host=args.host, port=args.port)
    else:
        run_stdio()
