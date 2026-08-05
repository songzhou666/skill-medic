# 06-synthesizer-agent：综合研判与处方

## 职责

汇总冲突矩阵 × 评分结果 → 产出综合处方清单。

## 执行规则

1. 读取 `_medic_conflicts.json` + `_medic_scores.json`
2. 调用 `medic_tools/run.py prescribe <root> --save` 生成规则处方候选（CLI 约定见 references/cli-guide.md），落盘 `.medic/_medic_rx.json`
3. 对每个冲突/低分 Skill 生成处方
4. 处方类型：保留 A 合并 B / 划清边界 / 明确分工 / 整改 / 移除归档
5. 每个处方含精确可执行指引（文件路径 + 改动内容 + 执行方式）
6. 本 Skill 只产出处方、不代执行

## 处方必给其一

- 同质冲突（C1）中评分较低者 → 建议合并/归档
- 意图抢占（C2）→ 建议加反触发说明
- 上下文膨胀（C3）→ 建议整改瘦身
- 不建议用的（L0 且无冲突价值）→ 建议移除