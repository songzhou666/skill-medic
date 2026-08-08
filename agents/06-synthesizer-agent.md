# 06-synthesizer-agent：综合研判与处方

## 职责

汇总冲突矩阵 × 评分结果 → 产出综合处方清单。

## 执行规则

1. 读取 `_medic_conflicts.json` + `_medic_scores.json` + `_medic_classify.json`（domain_final 分组）
2. 调用 `medic_tools/run.py prescribe <root> --save` 生成规则处方候选（CLI 约定见 references/cli-guide.md），落盘 `.medic/_medic_rx.json`
3. 对每个冲突/低分 Skill 生成处方
4. 处方类型：保留 A 合并 B / 划清边界 / 明确分工 / 整改 / 移除归档
5. 每个处方含精确可执行指引（文件路径 + 改动内容 + 执行方式）
6. 本 Skill 只产出处方、不代执行
7. **处方完善回写（LLM 智能分析层）**：对规则处方候选做语义完善（补行动优先级 / 面向使用者 vs 创建者的分流建议）后，
   **必须覆盖写回 `.medic/_medic_rx.json`**（用 IDE Write 工具），禁止只留在对话里
8. **未完成处方登记**：处方中标注"需创建者/维护者后续落地"的项（prescriptions_outstanding），
   **回报给 00-master**，由主控在 MED_CLOSE 收口时登记进接力棒 `history.prescriptions_outstanding`
   （单点写；子 Agent 禁止直接改接力棒）；断点续跑时优先核查这些处方是否已落地

## 处方必给其一

- 同质冲突（C1）中评分较低者 → 建议合并/归档
- 意图抢占（C2）→ 建议加反触发说明
- 上下文膨胀（C3）→ 建议整改瘦身
- 不建议用的（L0 且无冲突价值）→ 建议移除