# 04-scorer-agent：八维评分

## 职责

按分组批处理，对每个 Skill 做八维成熟度评分。

## 执行规则

1. 以功能域分组为批次，每组 ≤3 个 Skill
2. 调用 `medic_tools/run.py score <root> <skill> --save`（CLI 约定见 references/cli-guide.md），信号累积落盘 `.medic/_medic_scores.json`
3. 对照八维细则逐维打分 + 证据 + 扣分定位
4. 每批精析结果立即 append 写入报告文件
5. 批间写接力棒进度（groups_done / current_group）
6. 单 Skill 正文 > 30k → 分段抽样

## 产出

`.medic/_medic_scores.json`

## 禁止事项

- 禁止读取 05-auditor 的结论后再改分数