# GravitationalWave — Docker Local Deployment

中科院国家天文台 × 中国科学院大学 引力波天文数据智能分析平台

## 一键启动

```powershell
powershell -File D:\AliCPT\start.ps1
```

## 手动启动

```bash
cd D:\AliCPT
docker compose up -d
```

## 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| gw-frontend | 6001 | React + Aladin/Firefly |
| gw-backend | 8093 | Spring Boot + ES |
| gw-elasticsearch | 9200 | ES 7.17.28 (180 obs / 12 errors / 48 details) |
| gw-mongodb | 30017 | MongoDB 6.0 (33 comments) |
| gw-pipeline | 8200 | Astropy FITS pipeline (180 files × 6 surveys) |
| gw-firefly | 8080 | IPAC Firefly Java server |
| gw-mcp-server | 8100 | Python MCP (6 tools) |

## 代理配置

每次梯子端口变化后：
```powershell
powershell -File D:\AliCPT\proxy-setup.ps1
```

## 镜像备份

构建成功后保存镜像（离线可用）：
```powershell
powershell -File D:\AliCPT\save-images.ps1
```

## MCP (Claude Desktop)

```json
{
  "mcpServers": {
    "gw-mcp": {
      "command": "python",
      "args": ["D:/AliCPT/gw-mcp-server/mcp_server.py"],
      "env": {"BACKEND_URL": "http://localhost:8093"}
    }
  }
}
```

## 停止

```bash
docker compose down        # 停止
docker compose down -v     # 停止 + 清除数据库
```
