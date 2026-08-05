# 阶段闸门协议

## 8 阶段顺序

```
MED_SCOPE → MED_ROSTER → MED_SORT → MED_CONFLICT → MED_VITAL → MED_RX → MED_DEBRIEF → MED_CLOSE
```

## 闸门规则

| 阶段 | 进入条件 | 产出验证 |
|------|---------|---------|
| MED_SCOPE | 初始化或断点续跑 | **扫描范围声明**已写入接力棒 `meta.scan_scope`（workspace/global/自定义） |
| MED_ROSTER | MED_SCOPE ✅ | 有扫描范围声明；`_medic_inventory.json` 存在且非空 |
| MED_SORT | MED_ROSTER ✅ | `_medic_inventory.json` 存在；分类表产出（`_medic_classify.json` 或 LLM 回填 domain_final） |
| MED_CONFLICT | MED_SORT ✅ | `_medic_conflicts.json` 存在 |
| MED_VITAL | MED_CONFLICT ✅ | `_medic_scores.json` 存在（至少一个 Skill 已评分） |
| MED_RX | MED_VITAL ✅ | `_medic_rx.json` 存在（处方候选非空） |
| MED_DEBRIEF | MED_RX ✅ | 处方清单存在；报告文件已落盘 `.medic/skill_audit_report_*.md` |
| MED_CLOSE | MED_DEBRIEF ✅ | 报告文件已落盘；接力棒更新为 CLOSE |

## 跳步禁止

- 禁止跳过任何阶段
- 禁止在 MED_ROSTER 阶段读正文全文
- 禁止在 MED_SCOPE 阶段做分类/打分