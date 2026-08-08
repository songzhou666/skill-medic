# 接力棒协议 — _medic_baton.json

## 文件位置

`.medic/_medic_baton.json`（本 Skill 专属目录，自动创建；专属命名，不依赖任何既有 Skill 的状态文件）

## 结构

```json
{
  "meta": {
    "skill": "skill-medic",
    "state": "MED_SCOPE|MED_ROSTER|MED_SORT|MED_CONFLICT|MED_VITAL|MED_RX|MED_DEBRIEF|MED_CLOSE|FAILED|CLOSE",
    "session_id": "audit_20260804_143000",
    "created_at": "2026-08-04T14:30:00+08:00",
    "updated_at": "2026-08-04T14:35:00+08:00",
    "is_running": 1,
    "run_count": 1,
    "scan_scope": ["workspace", "global", "custom"],
    "rubric_version": "8-axis-v0.1",
    "scale": "S1|S2|S3|S4"
  },
  "progress": {
    "MED_SCOPE": "✅",
    "MED_ROSTER": "✅",
    "MED_SORT": "✅",
    "MED_CONFLICT": "⬜",
    "MED_VITAL": "⬜",
    "MED_RX": "⬜",
    "MED_DEBRIEF": "⬜",
    "MED_CLOSE": "⬜",
    "gate1": "⬜",
    "gate2": "⬜",
    "gate3": "⬜"
  },
  "batch": {
    "groups_total": 5,
    "groups_done": 2,
    "current_group": 3,
    "current_batch_skills": ["skill-a", "skill-b"],
    "conflict_pairs_total": 4,
    "conflict_pairs_done": 2,
    "skipped_groups": [],
    "appendix_done": [],
    "removed_pairs": []
  },
  "history": {
    "last_audit_at": null,
    "last_report": null,
    "last_inventory": null,
    "prescriptions_outstanding": []
  },
  "artifacts": {
    "inventory_json": ".medic/_medic_inventory.json",
    "last_inventory_json": ".medic/_medic_last_inventory.json",
    "classify_json": ".medic/_medic_classify.json",
    "conflict_matrix": ".medic/_medic_conflicts.json",
    "score_table": ".medic/_medic_scores.json",
    "rx_json": ".medic/_medic_rx.json",
    "review_json": ".medic/_medic_review.json",
    "report": ".medic/skill_audit_report_<时间戳>.md"
  },
  "rework": {
    "retry_count": 0,
    "last_blocker": null,
    "history": []
  }
}
```

## 控制规则

1. **单点写**：只有 00-master-controller 更新接力棒，**所有子 Agent 禁止直接改**（含 `batch` 段的批进度——
   04-scorer 等完成后**回报给 00-master**，由主控代写；不设任何子 Agent 写棒豁免）
2. **阶段闸门**：进入下一阶段前验证上一阶段产出存在且非空（对照 `phase-protocol.md` 闸门表）
3. **规模档位**：MED_ROSTER 后由 00-master 按活跃 Skill 数写入 `meta.scale`（S1~S4，口径 = 活跃 Skill 数，
   与 run.py `scale_of` 一致），各阶段沿用该档位决定降噪/报告形态，禁止各阶段自行另算；
   `meta.scan_scope` 初始化时按用户输入写入（默认全量），01-inventory 在 MED_SCOPE 结束后回报实际覆盖范围，
   由 00-master 校正（防止闸门拿占位值"假通过"）
4. **断点续跑**：中断后再次调用，先做产物回退校验（✅ 阶段产物缺失 → 回退重做并记 rework.history），
   再对含审核闸门的阶段（`gateN` 为 ⬜ 或被打回重做）强制重跑 05-auditor 一次，然后从第一个 ⬜ 阶段继续；
   **S3/S4 档 07-reporter 逐域回填中断后，按 `batch.appendix_done` 从未完成域继续**（该字段由 07 每完成一域回报 00-master 代写）；
   **MED_DEBRIEF 续跑禁止重跑 `run.py report`**（会覆盖已回填内容，00-master 启动流程已约束）；
5. **打回重做进度重置**：00-master 打回某阶段重做时，同步重置该阶段的进度字段——打回 MED_DEBRIEF 清空
   `batch.appendix_done`（附录问题必须全量重填，防止按进度跳过已回填域导致问题原样保留）；
   打回 MED_VITAL 清空 `groups_done`/`current_group`（04 全量重打，不受旧进度限制）；
   打回 MED_CONFLICT 清空 `batch.conflict_pairs_done`（03 全量重核写回版矩阵，防止"已完成对"被跳过
   导致伪冲突原样保留）
6. **熔断**：子 Agent 超时（120s，由平台运行超时机制接管，AI 侧以"单批执行超过上下文预算/步骤异常增多"为等价信号）→ 自动重试 1 次 → 仍失败记录 last_error，`state=FAILED`（is_running 保持 1，
   由下次调用按"状态异常处理"恢复）；同一阶段/闸门累计重试 ≥3 次 → 禁止自动重试，转人工
7. **完成收口**：MED_CLOSE 由 00-master 在验证 07-reporter 产出（完成摘要）后，
   把 `prescriptions_outstanding`（未完成处方，06-synthesizer 产出 rx.json 时回报）登记进 `history`，
   更新 `state=CLOSE, is_running=0` 并记录 history（保持单点写）；
   **收口完成后由 00-master 最后执行 `run.py cleanup`**（cleanup 归属 00-master，07-reporter 不执行；
   "收口先于清理"，避免 cleanup 后收口前中断触发产物回退误判）

> **state 取值说明**：`MED_SCOPE…MED_CLOSE` 为阶段名（运行中），`CLOSE` 为终态值（全会话完成），
> `FAILED` 为异常终态；初始化时 `meta.state` 默认 `MED_SCOPE`。

## 状态异常处理

- **state=FAILED**：下次调用 00-master 先展示 `rework.last_error` / `rework.last_blocker`，人工确认后
  重置接力棒（is_running=0）再开新会话；同一阶段累计重试 ≥3 次仍 FAILED → 禁止自动重试，转人工
- **进度 ✅ 但产物缺失**（闸门验证失败）：回退该阶段重新执行，并记入 `rework.history`
- **接力棒 JSON 损坏 / 解析失败**：备份损坏文件（`_medic_baton.corrupt_<时间戳>.json`）后按初始化结构重建