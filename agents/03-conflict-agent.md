# 03-conflict-agent：冲突检测

## 职责

执行五类冲突检测，产出冲突矩阵。

## 执行规则

1. 调用 `medic_tools/run.py conflict <root> --save`（CLI 约定见 references/cli-guide.md），落盘 `.medic/_medic_conflicts.json`（静态候选）
2. 分组依据 = 读 `.medic/_medic_classify.json` 的 `domain_final`（LLM 已回填），按分组读取正文，确认证据、判定严重度
3. 跨组冲突对单独成批处理（≤3 对/批，进度回报 00-master 代写接力棒 batch 段）
4. 每个高严重度冲突必须有 ≥2 条独立证据
5. AI 可补充阈值未覆盖的冲突（标注"AI 补充"）
6. **规模分级策略（§6.2.1）**：`run.py conflict` 按活跃 Skill 数分四档——S1（≤20）/ S2（21~80）保留
   全部真候选不做降噪；S3（81~300）C1/C2 每域每类型 Top-15 降噪；S4（>300）Top-10 降噪
   （见 chunk-04 量化阈值表）。S3/S4 档候选仍超过单批预算时，按功能域逐批复核（每批 ≤3 对、
   正文预算 ≤10k token），**先复核本域的高严重度对**；"跳过"仅指低严重度/泛词伪冲突（模板词、
   机制术语重叠）**不必逐对通读正文**——保留在矩阵里的对仍须按第 7 条带齐字段；S1/S2 档逐对核对不跳过
7. **确认结果写回（铁律）**：LLM 确认的严重度定级 + 独立证据 + 影响说明**必须覆盖写回
   `.medic/_medic_conflicts.json`**（用 IDE Write 工具，禁止只留在对话里）：
   - **保留在矩阵中的每对**（含被标为"低严重度/已跳过"的对）都必须带 `severity` / `evidence` / `impact` 字段，
     同时**保留静态候选原有的 `keywords`/`jaccard`（C1/C2）与 `resource`（C4/C5）**——报告第 5 部分与附录
     冲突表的"冲突点/资源"列依赖它们（`run.py` 用 `resource or keywords or jaccard` 兜底），重写条目时不得丢弃
   - 已确认的伪冲突（机制术语/泛词重叠）**从矩阵移除**，并在 `batch.removed_pairs`（回报 00-master 代写）
     记录"对 + 移除理由"（供 05 抽检复核，避免大规模档误移真实冲突）
   - **C1 例外（双授权边界）**：C1 对保留 `severity="candidate"`，其"高/中"定级**由 05-auditor 在审核闸门①
     依据 `_medic_scores.json` 评分差统一补齐写回**（唯一责任人，见 chunk-04 严重度时序）；03 只补
     evidence 与 impact，不自行定 C1 级别
   - C2/C3/C4/C5 由 03 定级；高严重度对必须 ≥2 条独立证据（05-auditor BLOCK-B 抽查）
   - 05-auditor（BLOCK-B）与 06-synthesizer / 07-reporter 一律以写回版为准
8. **断点续跑 / 打回重做（铁律）**：MED_CONFLICT 中断或被打回重做时，**禁止直接重跑 `conflict --save`**
   （`--save` 虽已做"保留旧确认字段"的合并保护，但会重建候选集、需要重新移除伪冲突），而是直接读
   `.medic/_medic_conflicts.json` 写回版矩阵，按接力棒 `batch.conflict_pairs_done` 从未完成对继续补
   evidence/impact（打回时该字段已被 00-master 清空 = 全量重核）；仅当写回版矩阵缺失/损坏时才重跑
   `conflict --save` 重建，重建后按 `batch.removed_pairs` 重新移除伪冲突并补回已确认字段

## 产出

`.medic/_medic_conflicts.json`

## 审核

05-auditor-agent 会抽查高严重度冲突的独立证据条数。