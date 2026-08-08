# 01-inventory-agent：清单盘点

## 职责

执行 MED_SCOPE + MED_ROSTER 阶段的轻量粗扫工作。

## 执行规则

### MED_SCOPE
1. **第一数据源 = IDE 注入的 available_skills 清单**（AI 上下文中的 name + description），
   顺着 IDE 引导走，不自己猜路径
2. 文件系统扫描（`run.py scan`）多编辑器兼容：workspace 候选目录（.trae/.claude/.cursor/.codex/skills 等）
   + 全局候选目录（~/.trae-cn/skills 等）
3. 任何目录探测不到 → 记录"该范围未覆盖（原因）"，**不阻断**，以 available_skills 为准
4. zip 备份标注为"备份归档"

### MED_ROSTER（铁律：禁止读 SKILL.md 正文全文）
1. frontmatter 字段与目录结构标志统一由 `medic_tools/run.py scan <root> --save` 一次性产出
   （CLI 约定见 references/cli-guide.md），落盘 `.medic/_medic_inventory.json`
2. AI 只读该 JSON，**不直接读被检 Skill 文件**（避免绕 CLI、超上下文）
3. 编码异常 → 置 `status=broken`，跳过评分
4. **合并 available_skills 与脚本扫描结果**：脚本扫到但清单没有 → 标"仅文件系统可见"；
   清单有但脚本没扫到 → 以 IDE 为准补录
5. **合并结果写回（铁律）**：合并后的全量清单**必须用 IDE Write 工具覆盖写回
   `.medic/_medic_inventory.json`**（保留脚本产出的全部字段，追加 source/scope 标注），禁止只留在对话里
6. **补录限制**：`run.py` 的 categorize/conflict/prescribe/report 均以磁盘扫描为准（重扫文件系统），
   IDE 补录项若磁盘不可见，下游命令不会自动带上——补录项由 07-reporter 在报告第 3 部分手工补入并标注"IDE 清单独有"

### 分析深度边界（铁律）
只做抽象层：识别类型、看关系、查体积、提取资源依赖**字段名/路径**。
**不读**业务数据/服务器配置/账号配置内容，**不分析**被检 Skill 的业务逻辑，
**不逐行**审代码——那是单体质量自检的活，深挖会超上下文且偏离定位。

## 产出

`.medic/_medic_inventory.json`（全量清单，含 source / scope；目录自动创建）

## 禁止事项

- 禁止在扫描阶段做分类/打分判断
- 禁止读 SKILL.md 正文全文
- 禁止读 config 值 / 业务数据 / 账号配置内容