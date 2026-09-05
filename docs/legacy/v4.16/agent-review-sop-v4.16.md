# 多 Agent 对抗审查体系 — 标准化执行流程（v4.16）

## 1. 适用场景

触发以下任一条件时，启动多 Agent 审查：
- PR 涉及 ≥3 个文件修改
- 涉及认证/权限/安全相关代码
- 涉及数据库 schema 变更
- 生产环境部署前的最终检查

## 2. Agent 配置

### 2.1 标准 3-Agent 审查（默认）

| Agent | 角色 | 审查维度 | 权重 |
|-------|------|---------|------|
| **Agent A** | Code Quality | 正确性、TypeScript 类型、React 最佳实践、DRY | 40% |
| **Agent B** | Security & Performance | XSS/注入、性能、无障碍、边界条件 | 35% |
| **Agent C** | Arbiter (仲裁) | 对比 A/B 评分、决定是否需重审 | 25% |

### 2.2 扩展 4-Agent 审查（安全敏感）

在 3-Agent 基础上增加：
| **Agent D** | Auth & Data Safety | JWT、RBAC、审计、数据泄露 | 独立否决权 |

### 2.3 扩展 5-Agent 审查（架构变更）

在 4-Agent 基础上增加：
| **Agent E** | Architecture & Tech Debt | 循环依赖、版本兼容、可维护性 | 独立否决权 |

## 3. 评审打分细则（100 分制）

### Agent A：Code Quality（40 分）

| 维度 | 满分 | 判定标准 |
|------|------|---------|
| 无 bug / 逻辑错误 | 10 | 任何逻辑错误扣 ≥5 |
| 代码风格一致 | 5 | 与现有代码风格偏离扣 1-3 |
| TypeScript 类型正确 | 10 | `as any` 每次扣 2，缺少泛型扣 1 |
| React 最佳实践 | 5 | 缺少 key、直接修改 state 扣 2 |
| 无重复代码 | 5 | 可抽取为函数的重复块扣 2 |
| 错误处理完善 | 5 | 无 try/catch 扣 3 |

### Agent B：Security & Performance（35 分）

| 维度 | 满分 | 判定标准 |
|------|------|---------|
| 无 XSS 风险 | 8 | `dangerouslySetInnerHTML` 扣 5 |
| 无硬编码凭据 | 8 | 任何 API key/密码扣 8（直接不通过） |
| 性能无明显退化 | 7 | 不必要的 re-render 扣 3 |
| 无障碍 (WCAG AA) | 5 | 缺少 aria-label、无键盘导航扣 2 |
| 边界条件覆盖 | 7 | 空数组/null/undefined 未处理扣 3 |

### 综合再加权

| Agent C (仲裁) | 25 分 | 仅评估 A/B 的一致性 + 审查质量，不重复打分 |

## 4. 准入门槛

| 场景 | 最低要求 | 重审条件 |
|------|---------|---------|
| 常规 PR | Agent A ≥ 80 **且** Agent B ≥ 75 | 任一低于门槛 |
| 安全相关 | Agent A ≥ 85 **且** Agent B ≥ 85 **且** Agent D 通过 | Agent D 否决即不通过 |
| 架构变更 | 上述全部 + Agent E ≥ 80 | Agent E < 80 需重审 |
| **硬性不通过** | Agent A 或 B 评分 < 60 | 不进入仲裁，直接打回 |

## 5. 执行流程

```
┌──────────┐    ┌──────────┐
│ Agent A  │    │ Agent B  │    ← 并行执行（独立审查，互不知晓对方结果）
│ (Quality)│    │ (Sec/Perf)│
└────┬─────┘    └────┬─────┘
     │ 评分 A         │ 评分 B
     └──────┬─────────┘
            ↓
     ┌─────────────┐
     │  Agent C     │  ← 接收 A 和 B 的评分
     │  (Arbiter)   │
     └──────┬───────┘
            │
     ┌──────┴──────┐
     │ A≥门槛 且    │── Yes → ✅ PASS，合并代码
     │ B≥门槛？     │
     │              │── No  → 识别失败维度 → 修复 → 重新审查（最多 3 轮）
     └─────────────┘
```

## 6. 执行命令

```bash
# 使用 Claude Code Workflow 执行
# 准备 PR diff
git diff origin/main > /tmp/pr.diff

# 启动 3-Agent 审查
# (由 Workflow 工具自动并行调度 Agent A/B，再调度 Agent C)

# 查看结果
cat review-result.json
```

## 7. 结果记录模板

```json
{
  "review_id": "rev-20260724-001",
  "pr": "feat: auth hardening v4.16",
  "files_changed": 6,
  "agents": {
    "A": { "score": 92, "issues": 1, "verdict": "PASS" },
    "B": { "score": 88, "issues": 2, "verdict": "PASS" },
    "C": { "verdict": "PASS", "rounds": 1 }
  },
  "final": "PASS",
  "duration_seconds": 180
}
```
