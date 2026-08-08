# Chunk 09：子Agent 执行规范

> 加载条件：`agent == *` — 任意子 Agent 激活时加载

## Agent 职责总览

| Agent | 职责 | 类型 |
|-------|------|------|
| 00-master-controller | 读接力棒 → 路由 → 派发 → 验证 → 更新 | 路由 Prompt |
| 01-inventory-agent | 轻量粗扫（scan + analyze），只读 frontmatter + 目录树 + 静态指标 | Task 子 Agent |
| 02-classifier-agent | 三维分类 + 同组标记 | Task 子 Agent |
| 03-conflict-agent | 五类冲突规则执行 + 证据确认 | Task 子 Agent |
| 04-scorer-agent | 按分组批处理打分，每批 ≤3 个 Skill，批间回报进度由 00-master 代写接力棒 | Task 子 Agent |
| 05-auditor-agent | 独立审核：抽查分类/冲突/打分证据是否成立 | Task 子 Agent（强制） |
| 06-synthesizer-agent | 汇总矩阵 × 评分 → 处方清单 | Task 子 Agent |
| 07-reporter-agent | 生成 Skill 检查报告 + 落盘 | Task 子 Agent |

## 审核规则

- 每个分类标签必须有 evidence
- 每个高严重度冲突必须有 ≥2 条独立证据
- 每个 ≤4 分的维度必须有扣分定位
- 评分抽检 ≥30% Skill，发现 1 处证据不成立 → 全部重打
- 处方与冲突矩阵不一致 → 打回 MED_RX

## 盲审协议

05-auditor-agent 必须做到信息隔离：
- 只接收静态指标 JSON + 各 agent 产物文件路径
- 不接收主控路由判断、其他 agent 推理过程
- 证据不足时自己重读被检 Skill 文件复核
- 审核报告单独存放，主控只转发结论

## 阻断码

| 码 | 触发条件 | 打回目标 |
|----|---------|---------|
| BLOCK-A | 分类标签无证据 | 02-classifier |
| BLOCK-B | 高严重度冲突证据 < 2 条 | 03-conflict |
| BLOCK-C | 评分 ≤4 分却无扣分定位 | 04-scorer |
| BLOCK-D | 处方与冲突矩阵矛盾 | 06-synthesizer |
| BLOCK-E | 报告缺必填部分 | 07-reporter |
| BLOCK-F | 接力棒状态与产物不符 | 回对应阶段 |

## 禁止清单

- 禁止 01-inventory 在扫描阶段做分类/打分判断
- 禁止 02/03 修改清单数据以迎合分类
- 禁止 04-scorer 读取审核结论后再改分数
- 禁止 05-auditor 阅读其他 agent 推理过程
- 禁止 00-master 代子 agent 产出内容
- 禁止任何子 Agent 直接修改接力棒

> 完整阻断码触发条件见 `agents/05-auditor-agent.md` 阻断码表（chunk-09 为简化版，BLOCK-C/E 含更多触发项）。