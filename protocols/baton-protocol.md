# 接力棒协议 — _medic_baton.json

## 文件位置

`.medic/_medic_baton.json`（本 Skill 专属目录，自动创建；专属命名，不依赖任何既有 Skill 的状态文件）

## 结构

```json
{
  "meta": {
    "skill": "skill-medic",
    "state": "MED_SCOPE|MED_ROSTER|MED_SORT|MED_CONFLICT|MED_VITAL|MED_RX|MED_DEBRIEF|MED_CLOSE|FAILED",
    "session_id": "audit_20260804_143000",
    "created_at": "2026-08-04T14:30:00+08:00",
    "updated_at": "2026-08-04T14:35:00+08:00",
    "is_running": 1,
    "run_count": 1,
    "scan_scope": ["workspace", "global", "custom"],
    "rubric_version": "8-axis-v0.1"
  },
  "progress": {
    "MED_SCOPE": "✅",
    "MED_ROSTER": "✅",
    "MED_SORT": "✅",
    "MED_CONFLICT": "⬜",
    "MED_VITAL": "⬜",
    "MED_RX": "⬜",
    "MED_DEBRIEF": "⬜",
    "MED_CLOSE": "⬜"
  },
  "batch": {
    "groups_total": 5,
    "groups_done": 2,
    "current_group": 3,
    "current_batch_skills": ["skill-a", "skill-b"],
    "skipped_groups": []
  },
  "history": {
    "last_audit_at": null,
    "last_report": null,
    "last_inventory": null,
    "prescriptions_outstanding": []
  },
  "artifacts": {
    "inventory_json": ".medic/_medic_inventory.json",
    "conflict_matrix": ".medic/_medic_conflicts.json",
    "score_table": ".medic/_medic_scores.json",
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

1. **单点写**：只有 00-master-controller 更新接力棒，子 Agent 禁止直接改
2. **阶段闸门**：进入下一阶段前验证上一阶段产出存在且非空
3. **断点续跑**：中断后再次调用，跳过已完成阶段，从第一个 ⬜ 阶段继续
4. **熔断**：子 Agent 超时 120s → 自动重试 1 次 → 仍失败记录 last_error，`state=FAILED`
5. **完成清理**：MED_CLOSE 阶段更新 state、is_running=0