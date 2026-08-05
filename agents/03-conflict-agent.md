# 03-conflict-agent：冲突检测

## 职责

执行五类冲突检测，产出冲突矩阵。

## 执行规则

1. 调用 `medic_tools/run.py conflict <root> --save`（CLI 约定见 references/cli-guide.md），落盘 `.medic/_medic_conflicts.json`
2. 按分组读取正文，确认证据、判定严重度
3. 跨组冲突对单独成批处理
4. 每个高严重度冲突必须有 ≥2 条独立证据
5. AI 可补充阈值未覆盖的冲突（标注"AI 补充"）

## 产出

`.medic/_medic_conflicts.json`

## 审核

05-auditor-agent 会抽查高严重度冲突的独立证据条数。