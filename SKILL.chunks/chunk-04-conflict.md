# Chunk 04：五类冲突检测

> 加载条件：`phase == MED_CONFLICT`

## 冲突检测流程

1. **全量静态比对**（由 `medic_tools/run.py conflict` 一次性跑完所有 Skill，不耗 LLM 上下文）：
   - description 关键词 Jaccard 相似度计算
   - 引用文件路径归一化比对
   - 常驻文本量估算
2. **LLM 确认证据**：分组依据 = 读 `.medic/_medic_classify.json` 的 `domain_final`；按分组读取正文，
   确认证据、判定严重度；**确认结果（severity 定级 + ≥2 条独立 evidence + impact 影响说明）必须覆盖写回
   `.medic/_medic_conflicts.json`**（用 IDE Write 工具），禁止只留在对话里

## 五类冲突模型

| 编号 | 类型 | 报告通俗名 | 定义 | 检测信号 |
|------|------|-----------|------|---------|
| C1 | 同质冲突 | 功能重复 | 功能域高度重叠 | description 关键词重叠 ≥ 20（或 ≥ 8 且 Jaccard ≥ 0.12） |
| C2 | 意图抢占 | 抢着响应 | 同一请求可命中多个 Skill | 非模板词交集 ≥ 4 且至少一方无反触发 |
| C3 | 上下文膨胀 | 占资源 | 常驻体积过大、无分层 | 常驻 token（SKILL.md + load:always chunk 索引）> 8k 且无 chunk |
| C4 | 依赖冲突 | 共享依赖 | 共享资源一方改动静默破坏另一方 | 引用路径/DB 表名/环境变量相同（DB 表/库归 C4，从代码通用提取） |
| C5 | 资源竞争 | 抢工具 | 同一物理/逻辑资源被抢占 | 声明同一 MCP 工具/端口/浏览器（不含 DB 写入权——DB 归 C4） |

> 报告输出必须用"报告通俗名 +（编号）"格式（如"功能重复（C1）"），与 chunk-07 图例一致。

## 量化阈值

> 阈值统一在 `medic_tools/run.py` 顶部"集中配置"区维护，调整必须同步本表、需求文档 §5.3 与 CHANGELOG。

| 冲突类型 | 静态命中阈值 | 严重度判定 |
|----------|-------------|------------|
| C1 | 交集 bigram ≥ 20（或 ≥ 8 且 Jaccard ≥ 0.12） | 高：同质且评分差 ≥ 20；中：同质但评分差 < 20 |
| C2 | 非模板词交集 ≥ 4 且至少一方无反触发 | 高：交集 ≥ 10；中：4~9 |
| C3 | 常驻 token > 8k 且无 chunk | 高：> 30k；中：8k~30k |
| C4 | 共享资源（config/baton/环境变量/DB 表库）精确相同 | 高：mtime 差异；中：静态相同 |
| C5 | 声明同一 MCP 工具/浏览器/CDP | 中：静态声明相同；低：语义相近 |

> 基础设施型共享（同一资源被 ≥4 个 Skill 引用）→ 聚合单列 `C4_infra`（低严重度），不生成两两对，避免矩阵爆炸（`C4_INFRA_MIN_OWNERS`）。

> **C1 严重度时序**：评分差判定依赖八维评分（MED_VITAL），而冲突检测在 MED_CONFLICT 阶段先于评分——
> 03-conflict 先按静态信号标 `candidate` 与证据；C1 的"高/中"评分差定级由 **05-auditor 在审核闸门①
> （MED_VITAL 后）依据 `_medic_scores.json` 统一补齐并写回**（唯一责任人），07-reporter 不另行判定。

> DB 表名/库名从代码**通用提取**（SQL 上下文 / `database` 赋值 / `get_<db>_db_config` 函数名），
> 不依赖任何具体表名/库名前缀——它们是环境数据，不是判定规则。

## 冲突矩阵

Skill A × Skill B 交点的单元格 = 冲突类型 + 严重度 + 一句话证据。

## 跨组冲突批

静态比对产出的跨组冲突对单独成批：**跨组对 = `_medic_conflicts.json` 候选对中，按
`_medic_classify.json` 的 `domain_final` 分组后分属不同组的对**；同组内对同样按 ≤3 对/批分批。
每批读双方正文确认证据，每批正文预算 ≤10k token；跨组对进度回报 00-master 代写接力棒
`batch` 段（conflict_pairs_total / conflict_pairs_done）。

## AI 可补充

AI 在精析中发现阈值未覆盖的真实冲突，必须补充进矩阵并标注"AI 补充"。