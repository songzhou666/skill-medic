# Chunk 02：扫描与清单盘点

> 加载条件：`phase == MED_SCOPE || phase == MED_ROSTER`

## 分析深度边界（铁律，本 Skill 的定位红线）

**SkillMedic 只做"外检"，不做"解剖"。** 只检查一个 Skill *是什么、和谁重复、占多大、该和谁合并*，绝不深挖它内部怎么运作：

| 做 ✅（抽象层） | 不做 ❌（越界，会超上下文） |
|----------------|---------------------------|
| 识别类型：功能域 / 交互模型 / 生命周期 | 不读业务数据、服务器配置、账号配置的具体内容 |
| 看关系：同质 / 意图抢占 / 上下文膨胀 / 依赖 / 资源竞争 | 不分析业务逻辑对不对（那是单体质量自检的活） |
| 查体积：SKILL.md + 常驻引用 token 估算 | 不逐行审代码、不读 config 值（仅记录被引用的资源**字段名/路径**） |
| 出处方：合并 / 整改 / 移除 建议（关系视角） | 不找"skill 本身怎么运作"的毛病 |

> 一句话：**我们看"它是什么、它和谁抢、它多重、它该和谁并"，不看"它内部怎么转"。**
> 被检 Skill 内部哪怕有一千个 bug，也不是本 Skill 的职责——那是用户用单体质量自检工具逐个修的。

## MED_SCOPE 范围扫描

**第一数据源 = IDE 注入的 available_skills 清单**（AI 上下文里就有：name + description）。
IDE 已经把当前所有 Skill 引导给 AI 了，顺着它走，而不是自己瞎猜路径。

文件系统扫描（`run.py scan`）只用于**补充静态指标**（路径 / token / 结构标志），多编辑器兼容：

1. workspace 候选目录（全部存在的都收集，按序优先）：`.trae/skills` → `.claude/skills` → `.cursor/skills` → `.codex/skills` → `skills`
2. 全局候选目录（§9.1，探测不到**不阻断**）：`~/.trae-cn/skills`、`~/.claude/skills`、`~/.cursor/skills`、`~/.trae/skills`
3. 用户显式指定的附加目录
4. **同名 Skill 去重**：workspace 优先，标注 `source` 与 `scope`（workspace / global）
5. **同源裁决**：同名不同路径的 Skill，默认按 §9.1 去重只保留一个（workspace 优先）；
   重复安装位置由工具记入该条目 `dup_sources`，报告"重复安装"区展示（例：同一 Skill 在
   `.trae/skills` 与 `.claude/skills` 各装了一份 → 建议只保留一份）；
   若 AI 判断内容差异大、需分别计数（如版本不同），**必须**在清单/报告标注
   "同源裁决：双版本分别计数 + 理由"（05-auditor 校验），禁止无说明地重复计数

> **CLI 约定**：调用方式、{CLI_DIR} 定位、失败处理见 `references/cli-guide.md`。
> 扫描结果必须 `--save` 落盘：`python run.py scan <project_root> --save` → `.medic/_medic_inventory.json`。

> **铁律**：任何目录探测不到 → 记录"该范围未覆盖（原因）"，**不阻断**审计，以 available_skills 清单为准继续。

## MED_ROSTER 清单盘点（轻量粗扫）

**铁律：粗扫阶段禁止读 SKILL.md 正文全文**，只读以下内容：

1. frontmatter（name / description / version / tags）
2. 目录树（文件清单、目录结构标志：agents / chunks / tools / protocols / CHANGELOG / README）
3. 静态指标（由 `medic_tools/run.py` 计算）：
   - SKILL.md 字符数、估算 token 数（公式：`ceil(cjk / 1.7 + ascii / 4)`）
   - frontmatter 完整度
4. **资源依赖声明**（仅字段名/路径，不读值）：环境变量名、config 文件名、DB 表名/库名、baton 路径、MCP 工具名——由 `run.py conflict` 从实现声明文件**通用提取**，不深读业务逻辑

### 异常 Skill 处理

- SKILL.md 缺失 / frontmatter 解析失败 / 目录不可读 / 编码无法识别 → `status=broken`
- 异常 Skill 不阻断全流程，跳过 MED_VITAL 评分，在报告中标注"未评分（异常）"
- 编码读取顺序：UTF-8 → GBK → 仍失败判定异常

### 输出

全量清单 JSON（`.medic/_medic_inventory.json`），每条含：
```json
{
  "name": "example-skill",
  "path": "/path/to/project/.trae/skills/example-skill",
  "source": ".trae\\skills",
  "scope": "workspace",
  "description": "...",
  "version": "1.0.0",
  "chars": 2500,
  "tokens_est": 1500,
  "has_frontmatter": true,
  "has_changelog": true,
  "has_readme": true,
  "has_agents": true,
  "has_chunks": true,
  "has_tools": true,
  "has_protocols": true,
  "status": "active"
}
```

> **LLM 层合并**：01-inventory-agent 必须把 available_skills 清单（IDE 注入）与脚本扫描结果合并——
> 脚本扫到的但 IDE 清单没有的，标"仅文件系统可见"；IDE 清单有的但脚本没扫到的，以 IDE 为准并补录。