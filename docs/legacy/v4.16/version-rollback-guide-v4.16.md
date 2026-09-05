# 版本回滚工具使用手册（v4.16）

适用工具：[version-snapshot.py](D:\AliCPT\version-snapshot.py)

## 1. 参数说明

```bash
python version-snapshot.py save                  # 创建新快照
python version-snapshot.py list                  # 列出所有快照
python version-snapshot.py restore <timestamp>    # 恢复到指定时间戳
python version-snapshot.py clean --keep 10       # 保留最近 10 个，删除旧快照
python version-snapshot.py diff <ts1> <ts2>      # 比较两个快照的差异
```

| 参数 | 说明 | 示例 |
|------|------|------|
| `save` | 创建时间戳快照，包含 TRACKED_FILES 列表中的所有文件 | `save` |
| `list` | 列出所有快照（时间戳 + 文件数量 + 大小） | `list` |
| `restore <ts>` | 恢复到指定快照。**会覆盖当前文件！** 自动创建恢复前备份 | `restore 20260724_120000` |
| `clean --keep N` | 保留最近 N 个快照，删除其余。默认 N=10 | `clean --keep 5` |
| `diff <ts1> <ts2>` | 逐文件比较两个快照，输出差异摘要 | `diff 20260723 20260724` |

## 2. 快照存储

- **位置**：`D:\AliCPT\version-snapshots\`
- **结构**：
  ```
  version-snapshots/
  ├── manifest.json              ← 所有快照的索引
  ├── 20260724_120000/           ← 快照目录（时间戳命名）
  │   ├── gw-frontend/src/...    ← 文件副本（保留原始目录结构）
  │   └── snapshot_meta.yaml     ← 快照元数据
  └── restore-backups/           ← 恢复前自动备份（安全网）
  ```
- **单快照大小**：~200KB（仅跟踪源文件，不含 node_modules/docker-data）
- **容量规划**：100 个快照 ≈ 20MB

## 3. 恢复失败容错

```
restore 执行流程:
  1. 验证快照存在且完整（检查 manifest + 文件数量）
     ↓ 失败 → "Snapshot corrupted or incomplete" + 退出
  2. 创建恢复前备份 → version-snapshots/restore-backups/<ts>/
     ↓ 失败 → "Cannot create safety backup, aborting" + 退出
  3. 逐文件恢复
     ↓ 单文件失败 → 跳过该文件，继续恢复其余文件
     ↓           → 最终报告 "Restored 45/48 files (3 skipped)"
  4. 更新 manifest 状态 → "last_restore": "<ts>"
```

**安全网**：恢复前自动备份当前文件到 `restore-backups/`。如果恢复导致问题，可手动从 `restore-backups/` 复制回原位置。

## 4. 快照清理策略

```bash
# 手动清理（推荐定期执行）
python version-snapshot.py clean --keep 10

# 自动清理逻辑：
#   1. 保留最近 N 个快照（按时间戳排序）
#   2. 跳过标记为 "pinned" 的快照（手动保护）
#   3. 删除快照目录 + manifest 条目
#   4. 清理 orphan restore-backups（超过 30 天的恢复备份）
```

| 场景 | 建议保留数量 |
|------|------------|
| 活跃开发期 | 20-30 个（每天 1-2 个快照） |
| 稳定维护期 | 5-10 个 |
| 发布前 | 手动 `save` + pin（不自动清理） |

## 5. 快照保护（Pin）

```bash
# 保护重要快照不被 clean 删除
python version-snapshot.py pin 20260724_120000 "v4.16 release candidate"

# 取消保护
python version-snapshot.py unpin 20260724_120000
```
