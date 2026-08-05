# Chunk 01：总览与状态机

> 加载策略：always — 本 chunk 随 Skill 激活常驻加载。

## 本 Skill 一句话

**SkillMedic** 帮你把装的一堆 Skill 查清楚：先列出都有谁（清单），再按用途分组（分类），然后揪出"谁和谁重复、谁会抢着响应同一个请求"（冲突），最后评估每个 Skill 靠不靠谱（成熟度），给出"留谁、并谁、改谁、删谁"的建议（处方）。

## 8 阶段状态机

```
MED_SCOPE → MED_ROSTER → MED_SORT → MED_CONFLICT → MED_VITAL → MED_RX → MED_DEBRIEF → MED_CLOSE
```

### 阶段闸门规则

- 进入下一阶段前必须验证上一阶段产出存在且非空
- 无 `inventory_json` 禁止进入 MED_SORT
- 无 `conflict_matrix` 禁止进入 MED_VITAL
- 接力棒由 00-master-controller 统一更新，子 Agent 禁止直接修改

### 断点续跑

中断后再次调用，读接力棒跳过已完成阶段，从第一个 ⬜ 阶段继续。

### 熔断

- 子 Agent 超时（120s）→ 自动重试 1 次 → 仍失败则记录 last_error，`state=FAILED`
- 同一阻断累计重试 ≥3 次 → `state=FAILED`

## 命名空间

全部阶段/节点/产物统一使用 `MED_` / `_medic_` 前缀，不与任何现有 Skill 撞名。

## 约束分层

| 层 | 约束强度 | 典型内容 |
|----|---------|---------|
| 工程骨架层 | 强约束（规则化、数值化） | 状态机、接力棒、批处理、熔断、脱敏、编码 |
| 智能分析层 | 软约束（给目标、不锁表述） | 分类语义、冲突判定、评分证据、处方内容 |