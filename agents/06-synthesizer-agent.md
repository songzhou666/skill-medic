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
   **必须覆盖写回 `.medic/_medic_rx.json`**（用 IDE Write 工具），禁止只留在对话里。
   **rx.json 完善版字段结构（07 读取呈现 7.2 的依据）**：在 run.py 候选字段（type/severity/targets/conflict/rule/llm_todo）
   基础上，完善时补 `llm_actions` 数组：`[{target, path, action, method}]`（target=Skill 名、path=文件路径、
   action=改动内容、method=手改文件|运行命令），每个 target 一条；07-reporter 按此回填 7.2 与附录"精确操作"列
8. **S4 档聚合处方（>300 活跃，run.py 已批量聚合）**：聚合后的处方 `targets` 含多个 Skill
   （如"补维护文档"批量、add-antitrigger 按 Skill 合并）。完善时必须**对 targets 中每个 Skill 分别给出
   7.2 精确操作（文件路径 + 改动内容 + 执行方式）**，禁止只针对第一个目标给出——聚合只压缩条目数，
   不压缩覆盖范围；每份附录按域展示各自域的聚合处方子集
9. **未完成处方登记**：处方中标注"需创建者/维护者后续落地"的项（prescriptions_outstanding），
   在 `_medic_rx.json` 对应条目上补 **`"outstanding": true`** 字段（LLM 写回版字段，随 rx.json 落盘），
   并把**带 outstanding 标记的条目清单回报给 00-master**，由主控在 MED_CLOSE 收口时登记进接力棒
   `history.prescriptions_outstanding`（单点写；子 Agent 禁止直接改接力棒）；
   断点续跑时优先核查这些处方是否已落地
10. **断点续跑 / 打回重做**：MED_RX 中断或被打回重做时，**禁止直接重跑 `prescribe --save`**（会重建候选集、
   抹掉 06 已完善的 llm_actions/outstanding——run.py 虽有保留旧字段的合并保护，但候选行集重建仍可能失配），
   而是直接读 `.medic/_medic_rx.json` 写回版，在现有条目上继续完善/修改；仅当写回版缺失/损坏时才重跑
   `prescribe --save` 重建

## 处方必给其一

- 同质冲突（C1）中评分较低者 → 建议合并/归档
- 意图抢占（C2）→ 建议加反触发说明
- 上下文膨胀（C3）→ 建议整改瘦身
- 不建议用的（L0 且无冲突价值）→ 建议移除