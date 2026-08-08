# 03-conflict-agent：冲突检测

## 职责

执行五类冲突检测，产出冲突矩阵。

## 执行规则

1. 调用 `medic_tools/run.py conflict <root> --save`（CLI 约定见 references/cli-guide.md），落盘 `.medic/_medic_conflicts.json`（静态候选）
2. 分组依据 = 读 `.medic/_medic_classify.json` 的 `domain_final`（LLM 已回填），按分组读取正文，确认证据、判定严重度
3. 跨组冲突对单独成批处理（≤3 对/批，进度回报 00-master 代写接力棒 batch 段）
4. 每个高严重度冲突必须有 ≥2 条独立证据
5. AI 可补充阈值未覆盖的冲突（标注"AI 补充"）
6. **确认结果写回（铁律）**：LLM 确认的严重度定级 + 独立证据 + 影响说明**必须覆盖写回
   `.medic/_medic_conflicts.json`**（用 IDE Write 工具，每对冲突保留 `severity` / `evidence`（≥2 条）/ `impact` 字段），
   禁止只留在对话里；05-auditor（BLOCK-B 审核证据条数）与 06-synthesizer / 07-reporter 以写回版为准

## 产出

`.medic/_medic_conflicts.json`

## 审核

05-auditor-agent 会抽查高严重度冲突的独立证据条数。