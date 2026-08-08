# Chunk 06：综合研判与处方

> 加载条件：`phase == MED_RX`

## 规则处方候选（prescribe 命令）

`medic_tools/run.py prescribe <root> --save` 基于**冲突矩阵 + 静态维护信号**生成规则处方候选（不依赖 LLM 评分）：

| 候选类型 | 触发 | 方向 |
|----------|------|------|
| merge | C1 同质 | 保留评分高者，合并/归档低者 |
| add-antitrigger | C2 意图抢占 | 双方补"何时不要调用"反触发 |
| slim | C3 上下文膨胀 | 拆分 chunk / 裁剪常识 |
| boundary | C4 依赖冲突 | 明确共享资源读写职责 |
| schedule | C5 资源竞争 | 明确分工顺序/串行约束 |
| fix-frontmatter / maintain | 静态维护信号 | 补 frontmatter / CHANGELOG / README |
| fix-or-archive | broken Skill | 修复或归档 |

> 规则层只给候选与方向；**精确执行指引（文件路径 + 改动内容 + 执行方式）与优先级由 LLM 完善**。
> **写回铁律**：LLM 完善后的处方（含 7.2 改造建议分流）必须**覆盖写回 `.medic/_medic_rx.json`**
> （用 IDE Write 工具），禁止只留在对话里；05-auditor 与 07-reporter 以写回版为准。
> **severity 数据源**：处方引用的冲突严重度/判定一律以 `_medic_conflicts.json` 写回版为准
> （03 确认 + 05 补齐），禁止沿用 prescribe 静态候选的 `candidate` 初值。
>
> **S4 聚合处方（>300 活跃，prescribe 自动聚合）**：聚合后 `targets` 含多个 Skill，完善时必须
> **对 targets 中每个 Skill 分别给出精确操作**，禁止只针对第一个目标；聚合只压缩条目数、不压缩覆盖范围。
> 聚合规则枚举见 chunk-04 规模分级策略：maintain/fix-frontmatter/fix-or-archive/slim 同型合并、
> add-antitrigger 按 Skill 聚合、merge/boundary/schedule 保持逐对。

## 处方生成规则（LLM 层）

| 处方 | 适用场景 | 示例 |
|------|----------|------|
| 保留 A，合并 B | 功能重复，B 能力被 A 覆盖 | 同功能的两个风格定制 Skill，能力重叠 → 合并 |
| 保留 A、B，划清边界 | 功能相关但有差异 | 用户手册生成 vs 开发文档捕获 → 各自补充反触发说明 |
| 保留 A、B，明确分工顺序 | 分层协作但有抢占风险 | 浏览器探索类 Skill 之间定好"谁先谁后、谁的数据是谁的输入" |
| 整改（瘦身/加边界/加反触发） | 单 Skill 膨胀或误触发 | 对 C3 命中者建议拆分 chunk |
| 移除/归档 | 已废弃、被完全取代 | 无维护且无使用场景 → 归档为 zip |

## 处方执行交接

1. 每个处方必须含精确可执行指引：具体文件路径 + 改动内容 + 执行方式
2. 本 Skill **只产出处方、不代执行**
3. 处方清单进入回访队列：下次审计逐一核对执行情况；
   **需后续落地的未完成处方（prescriptions_outstanding）在 rx 条目上补 `outstanding: true` 字段并回报 00-master**，
   由主控在 MED_CLOSE 收口时登记进接力棒 `history.prescriptions_outstanding`

## 审核与打回

- 处方与冲突矩阵不一致 → 打回 MED_RX 重出
- 05-auditor-agent 审核处方合理性
- 重试 ≥3 次 → `state=FAILED`（is_running 保持 1，由下次调用按状态异常处理恢复，非死局）