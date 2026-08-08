# 阶段闸门协议

## 8 阶段顺序

```
MED_SCOPE → MED_ROSTER → MED_SORT → MED_CONFLICT → MED_VITAL → MED_RX → MED_DEBRIEF → MED_CLOSE
```

## 闸门规则

| 节点 | 进入条件 | 产出验证 |
|------|---------|---------|
| MED_SCOPE | 初始化或断点续跑 | **扫描范围声明**已写入接力棒 `meta.scan_scope`（workspace/global/自定义） |
| MED_ROSTER | MED_SCOPE ✅ | 有扫描范围声明；`_medic_inventory.json` 存在且非空 |
| MED_SORT | MED_ROSTER ✅ | `_medic_inventory.json` 存在；分类表产出（`_medic_classify.json`，LLM 回填 domain_final 后写回） |
| MED_CONFLICT | MED_SORT ✅ | `_medic_conflicts.json` 存在 |
| MED_VITAL | MED_CONFLICT ✅ | `_medic_scores.json` 存在（至少一个 Skill 已评分） |
| 审核闸门① | MED_VITAL ✅ | `_medic_review.json`（盲审分类/冲突/评分；BLOCK-A/B/C 打回 02/03/04） |
| MED_RX | 闸门① ✅ | `_medic_rx.json` 存在（处方候选非空） |
| 审核闸门② | MED_RX ✅ | `_medic_review.json`（盲审处方；BLOCK-D 打回 06） |
| MED_DEBRIEF | 闸门② ✅ | 报告文件已落盘 `.medic/skill_audit_report_*.md`（产出验证，非进入条件） |
| 审核闸门③ | MED_DEBRIEF ✅ | `_medic_review.json`（盲审报告成品；BLOCK-E 打回 07） |
| MED_CLOSE | 闸门③ ✅ | 报告文件已落盘；接力棒更新为 CLOSE |

> 审核闸门对应接力棒 `progress.gate1/gate2/gate3`，由 05-auditor 执行、00-master 标记；
> 打回重做后必须重新走对应闸门（断点续跑时对含闸门阶段强制重跑 05，见 00-master 启动流程）。

## 跳步禁止

- 禁止跳过任何阶段
- 禁止在 MED_ROSTER 阶段读正文全文
- 禁止在 MED_SCOPE 阶段做分类/打分