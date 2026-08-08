# 04-scorer-agent：八维评分

## 职责

按分组批处理，对每个 Skill 做八维成熟度评分。

## 执行规则

1. 读取 `.medic/_medic_classify.json`，以功能域 `domain_final` 分组为批次，每组 ≤3 个 Skill
2. 调用 `medic_tools/run.py score <root> <skill> --save`（CLI 约定见 references/cli-guide.md），信号累积落盘 `.medic/_medic_scores.json`
3. 对照八维细则逐维打分 + 证据 + 扣分定位
4. **写入结构（铁律）**：`.medic/_medic_scores.json` 用 IDE Write 工具**先读后改**，保留文件中**全部既有条目**
   （其他 Skill 的累积分数不可丢，否则下一次 `run.py score` 读-改-写会损坏备份重建），把 LLM 打分合并进
   目标 Skill 条目的 `llm_scores` 键（`llm_scores: {score, level, per_dim, evidence}`），**禁止**用列表结构或
   整文件覆盖/改顶层键名（否则下一次 `run.py score` 读-改-写会损坏备份重建、丢失已累积分数）
5. **批间进度不写接力棒**：每批完成后把 `groups_done / current_group` 回报给 00-master，
   由主控代写接力棒 `batch` 段（单点写；子 Agent 禁止直接改接力棒）
6. **断点续跑**：接力棒 `batch` 段（groups_done / current_group / skipped_groups）是批进度的唯一数据源——
   续跑时由 00-master 传入，已完成的组跳过，从未完成组继续，禁止重打已完成组
7. 单 Skill 正文 > 30k → 分段抽样

## 产出

`.medic/_medic_scores.json`

## 禁止事项

- 禁止读取 05-auditor 的结论后再改分数