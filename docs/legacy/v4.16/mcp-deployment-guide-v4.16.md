# MCP Server 部署对接完整指南（v4.16）

## 1. 部署前提条件

| 条件 | 最低要求 | 推荐 |
|------|---------|------|
| Python | 3.11+ | 3.12 |
| 依赖 | `mcp`, `fastapi`, `httpx`, `uvicorn` | `pip install -r requirements.txt` |
| 后端可达 | `gw-backend:8093` 或 `localhost:8093` | Docker 网络内 `http://gw-backend:8093` |
| 端口 | 8100 (HTTP REST) / 8101 (SSE MCP) | 确保端口未占用 |
| Claude Desktop | 最新版 | 需配置 `claude_desktop_config.json` |

## 2. 两种传输模式

### 模式 A：stdio（Claude Desktop 专用）

```json
// %APPDATA%\Claude\claude_desktop_config.json (Windows)
// ~/Library/Application Support/Claude/claude_desktop_config.json (macOS)
{
  "mcpServers": {
    "gw-mcp": {
      "command": "python",
      "args": [
        "D:/AliCPT/gw-mcp-server/mcp_server.py",
        "--transport", "stdio"
      ],
      "env": {
        "BACKEND_URL": "http://gw-backend:8093",
        "MOCK_MODE": "false",
        "FALLBACK_JSON_ENABLED": "true"
      }
    }
  }
}
```

### 模式 B：SSE（自研 AI 大模型 / 任意 MCP 客户端）

```bash
# 启动 SSE 服务器
python mcp_server.py --transport sse --host 0.0.0.0 --port 8101

# 客户端连接
# SSE:  http://localhost:8101/sse
# POST: http://localhost:8101/messages
```

## 3. stdio 端口冲突处理

stdio 模式**不使用网络端口**（通过标准输入/输出通信），不存在端口冲突。

**常见问题**：

| 问题 | 原因 | 解决 |
|------|------|------|
| Claude Desktop 显示 "Failed to start" | Python 路径错误 | 使用完整路径 `which python` |
| MCP 工具列表为空 | `BACKEND_URL` 不可达 | 检查 `curl $BACKEND_URL/api/app/gravitationalwave/error` |
| Windows 中文路径乱码 | 编码问题 | 使用英文路径或 `chcp 65001` |
| 多个 MCP 服务器冲突 | 同一端口被占用 | stdio 模式无此问题；SSE 模式换端口 `--port 8102` |

## 4. 降级策略

```
MOCK_MODE=true            → 直接返回模拟数据（零后端依赖）
FALLBACK_JSON_ENABLED=true → 后端不可达时使用本地 JSON 导出数据
（默认）                   → 优先实时后端，失败自动降级

每个响应包含 _gw_source 字段标识数据来源：
  "live"          → 实时后端
  "fallback_json" → 降级到本地 JSON
  "mock"          → 模拟模式
  "error"         → 全部失败
```

## 5. 自研 AI 大模型对接示例

```python
# 使用 SSE 客户端连接
import asyncio
from mcp.client.sse import sse_client

async def main():
    async with sse_client("http://localhost:8101/sse") as (read, write):
        # 标准 MCP 协议: initialize → list_tools → call_tool
        ...

asyncio.run(main())
```

或直接调用 REST API（非 MCP 协议，但兼容任何 HTTP 客户端）：
```bash
curl "http://localhost:8100/api/app/gravitationalwave/geoSearch?ra=159.6&dec=44.8&radius=1"
# 响应含 _gw_source: "live"
```
