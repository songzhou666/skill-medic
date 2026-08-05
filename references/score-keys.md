# 评分证据定位指南 — score-keys

> 供 04-scorer-agent 在 MED_VITAL 阶段给每维打分时使用：
> 每条评分必须有**可回溯证据**（文件路径 + 行号/章节 + 原文摘录），禁止无依据打分。

## 证据格式（要素固定，表述自由）

每条证据形如：
`<文件> L<行号> <章节>：<原文摘录> → <它支撑哪一维的什么判断>`

示例：
- `SKILL.md L11-31 触发契约：description 含"何时调用+何时不要调用" → 维度1 触发契约，反触发纪律成立`
- `SKILL.chunks/chunk-05-score.md §评分流程：有逐条自检 → 维度4 产出控制，checklist 闭环成立`

## 各维度的证据来源（默认检索范围）

| 维度 | 优先证据位置 |
|------|-------------|
| 1 触发契约 | SKILL.md frontmatter description + 触发契约章节 |
| 2 流程机制 | SKILL.md 状态机/阶段表 + protocols/phase-protocol.md |
| 3 异常与熔断 | SKILL.md 熔断/异常段 + protocols/baton-protocol.md |
| 4 产出控制 | SKILL.md 自检/验收段 + agents/05-auditor-agent.md 阻断码 |
| 5 边界与上下文 | SKILL.chunks/chunk-index.yaml + 常驻 token 估算 |
| 6 内容价值密度 | references/（方法论/反模式/FAQ）+ SKILL.chunks 正文 |
| 7 工程配套 | medic_tools/、1-manifest/、README、protocols/ 存在性 |
| 8 维护健康度 | CHANGELOG.md 版本轨迹 + README 与实现一致性 |

## 扣分定位要求（对应 BLOCK-C 审核）

- 任何维度给分 ≤4/满分时，**必须**给出扣分定位（文件 + 章节/行号 + 缺失或不足的具体内容）
- 无扣分定位的 ≤4 分 → 被 05-auditor 打回（BLOCK-C）

## 信号 ≠ 证据

`run.py score` 输出的关键词命中只是**候选信号**；证据必须是"从文件里实际读到、能支撑该维判断"的内容。
信号为空可作为扣分线索，但也要指明具体缺什么（如"无自检相关章节"）。