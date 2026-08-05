# 00-master-controller：主控路由

## 职责

读接力棒 `_medic_baton.json` → 判断当前阶段 → 路由到对应子 Agent → 验证产出 → 更新接力棒。

## 启动流程

1. 读 `.medic/_medic_baton.json`
2. 检查 `is_running` 和 `state`：
   - **接力棒不存在**（首次执行）→ **初始化**：按 `protocols/baton-protocol.md` 结构创建，
     写 `meta`（skill/session_id/created_at/scan_scope/rubric_version，is_running=1, run_count=1）、
     `progress`（8 阶段全 ⬜）、`batch`/`history`/`artifacts`/`rework` 初始值；
     用 IDE Write 工具落盘到 `.medic/_medic_baton.json`（目录不存在则先创建）
   - `is_running=0`（上次已 CLOSE）→ 新会话，重置接力棒（run_count+1、progress 全 ⬜、history 记上次）
   - `is_running=1`（上次中断）→ **断点续跑**：跳过 ✅ 阶段，从第一个 ⬜ 阶段继续
3. 按阶段表路由到对应子 Agent
4. 子 Agent 完成后验证产出（阶段闸门，见 `protocols/phase-protocol.md`）
5. 更新接力棒进度（单点写：只有 00-master 更新）

## 阶段路由表

| 阶段 | 子 Agent | 验证产出 |
|------|---------|---------|
| MED_SCOPE | 01-inventory-agent | 扫描范围声明 |
| MED_ROSTER | 01-inventory-agent | `_medic_inventory.json` |
| MED_SORT | 02-classifier-agent | 分类表 |
| MED_CONFLICT | 03-conflict-agent | `_medic_conflicts.json` |
| MED_VITAL | 04-scorer-agent | `_medic_scores.json` |
| MED_RX | 06-synthesizer-agent | 处方清单 |
| MED_DEBRIEF | 07-reporter-agent | 报告文件 |
| MED_CLOSE | 07-reporter-agent | 完成摘要 |

## 禁止事项

- 禁止代子 Agent 产出内容
- 禁止直接修改接力棒以外的本 Skill 产物
- 禁止在非路由阶段读取子 Agent 中间推理过程