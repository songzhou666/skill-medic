# CHANGELOG

## v0.4.16 (2026-08-08)

### 六轮回归收敛修复（2 子 Agent：v0.4.15 回归验证 / 残余问题排查）+ 完整端到端测试

- **回归验证结论**：v0.4.15 的 12 个修复点全部真实落地，无 P0/P1，未引入新矛盾
- **P2 fix-frontmatter 边界**：`(completeness or 1) < 1` 的 `or 1` 把 `completeness=0.0`（frontmatter 存在但 4 必填字段全空）误提升为 1 而漏触发 → 去掉 `or 1`（get 默认值已是 1）
- **P2 命名泛化**：run.py 注释残留 `xbrowser`、chunk-07 回填示例残留 `scout/parse/manual-gen` 真实 Skill 名 → 泛化为 `skills/<skill>` 与"示例 Skill A/B/C"
- **P2 examples diff 参数**：`<last_inventory>`（必填）→ `[last_inventory]`（可选，缺省读上次清单），与 cli-guide/run.py 一致
- **P2 description 优化**：压缩至 ~150 字符（原 194，距 ≤200 上限余量翻倍），反触发摘要补齐正文 6 类（新增 C 盘清理、代码审查/安全扫描），SKILL.md 与 manifest 同步
- **完整端到端测试（12 项全过）**：ping / scan / analyze（字段全）/ categorize / conflict / score 累积 / prescribe / report（第 9 部分定级阈值 ✅、正文零裸文本 ✅）/ diff / cleanup（白名单 ✅）/ broken ✅ / 无 frontmatter ✅
- 验证：py_compile 通过；测试临时目录已清理；版本 0.4.15 → 0.4.16

## v0.4.15 (2026-08-08)

### 五轮实测验证收敛修复（3 子 Agent：全链路引用矩阵 / run.py 逐函数终审 / 真实环境端到端实跑）

- **P1 报告第 9 部分缺固定定级阈值**（BLOCK-E 阻断项，代码终审 + 实跑双重确认）：build_report 第 9 部分补
  "定级规则（固定阈值）：L3≥80 ｜ L2 55~79 ｜ L1 30~54 ｜ L0<30（引用 chunk-05，禁止自创）"
- **P1 merge 处方 severity 写死 high 与候选"待确认"矛盾**：改为继承候选 `c.get("severity", "candidate")`，
  与第 5 部分冲突矩阵一致（C1 高/中定级仍由 05-auditor 闸门① 补齐）
- **P1 脚本工具型判定与 chunk-03 不符**：chunk-03 同步"description 含 run.py/CLI/命令行 精确词 或 tools 目录"
- **P2 实跑修复**：diff 错误消息补 `ensure_ascii=False`（中文不再转义）；diff 任一侧 mtime 缺失回退字符数比较
  （当前读取失败不再漏检）；报告第 2 部分"常驻估算 token"改用 `always_load_tokens_est`（与 C3 口径一致）
- **P2 健壮性**：read_file_safe 改 `utf-8-sig` 兼容 BOM（Windows 常见）+ 512KB 超限截断（§14 风险对策）；
  boundary 处方 severity 继承 C4 候选；fix-frontmatter 触发改 `completeness < 1`（字段不全也覆盖）；
  analyze_skill 补 path/description/has_tools/mtime 等字段，SKILL.md 缺失时与 scan 一致走设计文档 fallback；
  classify_skill 生命周期判定顺序修正（有 CHANGELOG=活跃维护优先于"仅有设计稿"的"开发中"）
- **P2 性能**：build_conflict_candidates C4/C5 共用 collect_skill_text 缓存（消除每 Skill 重复 I/O）
- **P3**：需求文档 §8.3 模块注释修正（扫描/冲突引擎/token 估算内置单文件）；chunk-03 生命周期表补实现口径说明
- 验证：py_compile 通过；实跑确认报告第 9 部分阈值、diff 中文、merge candidate、fix-frontmatter 全覆盖
  均正确；报告正文零裸文本；版本 0.4.14 → 0.4.15

## v0.4.14 (2026-08-08)

### 四轮验收收敛修复（3 子 Agent：三方一致性终审 / v0.4.13 回归 / 用户视角演练）

- **P1 cli-guide project_root 铁律**：消除"cd {CLI_DIR} 后 Get-Location 取到 CLI_DIR 当项目根"的静默空产物风险——明确 project_root 永远取会话项目根，与 cd 无关，Get-Location 不得替代
- **P1 断点续跑 batch 恢复**：00-master 续跑补"读取接力棒 batch 段传给 04，已完成组跳过、未完成组继续"；04-scorer 补"batch 段是批进度唯一数据源"
- **P1 gate 续跑时序**：改为"先续完阶段全部批 → 阶段产物完整后 → 再强制重跑 05 全覆盖审核 → 放行"（避免部分评分被审、剩余批漏审）
- **P1 cleanup 收口顺序**：00-master 先收口（state=CLOSE / 回填 artifacts.report / 登记 prescriptions_outstanding）→ 最后执行 cleanup；07 只产出摘要与报告路径回报
- **P2 scores 写回段名统一**：chunk-05 / 04-scorer / 07-reporter 统一为"保留 CLI 顶层信号块 + 追加 llm_scores 键"（run.py 实际结构）；run.py score 合并改为 `{**旧, **新}` 保留既有键，防重复调用覆盖 LLM 分数
- **P2 需求文档对齐**：§5.3 C4/C5 检测信号列（删"版本约定不一致"/"同一库表写入权"、补 mtime 差异）、§6.2/§8.2 score 签名补 root、§9.2 常驻口径（SKILL.md + chunk-index）、§6.3 熔断补"is_running 保持 1 非死局"、§10.3 补"子 Agent"、§9.1 补 ~/.qclaw/skills、§7 图例补"对号入座"、§6.3 batch/history 示例补 conflict_pairs 与报告路径、§9.4 补 meta 前缀、§11.1 标注规划项
- **P2 执行可操作性**：C1 严重度补齐指定唯一责任人（05-auditor 闸门① 依据 scores.json 补齐写回）；跨组冲突对批次来源与预算明确（按 domain_final 分组 + ≤3 对/批 + ≤10k token）；06 处方 severity 以 conflicts.json 写回版为准
- **P3 收敛**：examples.md 报告路径改 `./.medic/` + path 字段加注；run.py docstring conflict/score 补 --save；chunk-04 补 C4_infra 聚合说明
- 验证：py_compile 通过；版本 0.4.13 → 0.4.14

## v0.4.13 (2026-08-08)

### 三轮复查收敛修复（3 子 Agent：回归验证 / 深度角落 / 全文一致性）

- **P1 需求文档残留**：标题与文末版本号改为 v0.4.13；§6.1/§10 两处"批间写接力棒进度"旧表述改为"回报 00-master 代写"（单点写全量清零）；§6.3 接力棒结构示例补 gate1/2/3 与 CLOSE 终态；控制规则同步断点续跑产物回退 + FAILED 分支优先 + 熔断转人工口径
- **P1 cli-guide 补录限制缺注**：分工表补"run.py 以磁盘扫描为准，IDE 补录项由 07 报告手工补入"
- **P2 run.py 业务逻辑**：C3 上下文膨胀改用常驻口径（SKILL.md + load:always chunk 索引，scan 新增 `always_load_tokens_est` 字段）；C4 严重度实现 mtime 差异 → 高（新增 `C4_MTIME_DIFF_SEC`，>7 天）；build_report 历史洞察占位改 HTML 注释并补"冲突新增与缓解"三要素；cleanup kept 按实际报告文件计算（去 glob 字面量）
- **P2 文档-实现对齐**：chunk-02 broken 判定对齐 run.py（目录不可读→跳过记未覆盖、frontmatter 缺失→仍 active 触发 fix-frontmatter）；全局候选目录补 `~/.qclaw/skills`；chunk-02 合并写回铁律 + chunk-05 LLM 打分写回铁律；faq-deep Q6 增量数据源改为 `_medic_last_inventory.json`、Q10 补产物回退与重审；conflict-catalog C3 常驻口径 / C4 删未落地"版本约定不一致"、补 mtime 差异 / C5 明确 DB 写入权归 C4；chunk-04 C3/C4/C5 表同步；熔断口径统一为"FAILED 非死局，is_running 保持 1 由下次调用恢复"（chunk-01/06、05-auditor）
- **P2 措辞同步**：00-master 重审名单补 MED_CONFLICT；chunk-09"任何 agent"→"任何子 Agent"+ 阻断码表指向完整版；cli-guide diff 缺省参数 `[last_inventory]` + score 路径入参；README 快速开始 conflict/score/prescribe 补 `--save`；chunk-08 联网流程补第 5 步写入接力棒 rubric_version + §8.4 引用；04-scorer TypeError 描述改为"损坏备份重建"；examples.md 反斜杠路径改正斜杠
- 验证：py_compile 通过；版本 0.4.12 → 0.4.13

## v0.4.12 (2026-08-08)

### 整体机制复查修复（4 子 Agent 二轮交叉检查：机制 / 文档 / 工具层 / 全流程走查）

- **P1 接力棒单点写穿透**：04-scorer / chunk-05 / chunk-09 指示"批间写接力棒"，与单点写铁律互斥 →
  统一口径：**所有子 Agent 禁止写棒**，04 批进度 / 06 处方登记完成后**回报 00-master 代写**；
  cli-guide 分工表同步
- **P1 FAILED 恢复分支被遮蔽**：00-master 判断顺序 is_running=1 先于 FAILED，FAILED 时 is_running 保持 1
  导致恢复路径不可达 → 启动分支顺序改为"FAILED/损坏 优先于 is_running"
- **P1 产物缺失回退未落地**：断点续跑只"跳过 ✅ 阶段"不校验产物 → 00-master 续跑增加产物回退校验
  + 闸门进度强制重跑 05（gate1/gate2/gate3 纳入 progress）
- **P1 03-conflict 证据无落盘**：LLM 确认的严重度/证据只留对话里 → chunk-04 + 03-conflict-agent 补
  "覆盖写回 `_medic_conflicts.json`（severity/evidence≥2/impact）"铁律
- **P1 01 合并清单空转**：available_skills 合并结果无写回、下游 run.py 全量重扫磁盘丢补录 →
  01 明确覆盖写回 inventory.json；cli-guide 注明"run.py 以磁盘扫描为准，补录项由 07 报告手工补入"
- **P1 C1 严重度时序矛盾**：评分差判定依赖 MED_VITAL 但冲突检测在前 → chunk-04 补时序说明
  （candidate → MED_VITAL 后由 05/07 依据 scores.json 补齐高/中定级）
- **P2 run.py 健壮性**：score 落盘损坏时备份重建（防静默清空累积分数）；diff 状态变化（active↔broken）视为变更；
  report 归档失败告警；collect_skill_text / cleanup / scan 内层 listdir/getmtime 兜底（_safe_listdir/_safe_mtime）；
  analyze 死代码分支删除
- **P2 文档同步**：需求文档 §6.3 artifacts 补 4 字段 / §16.5 cleanup 表述 / §16.1 补 examples / §5.1 删"其他" /
  diff 缺省参数 / 标题与文末版本；phase-protocol 闸门表补审核闸门①/②/③；chunk-03/chunk-06 补写回铁律；
  examples.md C2 示例严重度 medium；BLOCK-F 打回目标具体化；chunk-05 score 命令补 root
- 验证：py_compile 通过；版本 0.4.11 → 0.4.12

## v0.4.11 (2026-08-08)

### 整体机制审查修复（4 子 Agent 交叉检查：机制 / 文档 / 工具层 / 全流程走查）

- **P0 cleanup 误删接力棒**：原逻辑删除所有 `_medic_*`（仅豁免 inventory），会把 `_medic_baton.json` 一起删掉 → 白名单化，只清理 classify/conflicts/scores/rx/review，**显式保留接力棒 / 本次与上次清单 / 历史报告**
- **P1 历史对比数据源三重错位**：本次清单覆盖 inventory → report 前先把本次清单归档为 `_medic_last_inventory.json` 再覆盖，build_report 与 diff 缺省路径统一读 last；diff 变更判定改用 mtime（旧清单无 mtime 回退字符数比较），修复 ceil 取整漏报
- **P1 score 落盘键不稳定**：`scores[skill_name]` 用原始入参（路径/目录名不固定）→ 统一 `scores[base]`（目录名）
- **P1 05-auditor 调度黑洞**：路由表无 05 阶段引用 → 00-master 补审核闸门①（MED_VITAL 后）/ ②（MED_RX 后）/ ③（MED_DEBRIEF 后）
- **P1 MED_CLOSE 写棒与单点写冲突**：07-reporter 写接力棒违反"只有 00-master 写" → MED_CLOSE 收口归 00-master（验证 07 产出后更新 state/is_running/history）
- **P1 分类初值来源文档错位**：chunk-03/02 写"读 inventory"实际读 `.medic/_medic_classify.json` → 文档对齐
- **P2 批量**：report 时间戳毫秒级（同秒并发覆盖）；scan 补 mtime；docstring 补 categorize/prescribe/diff 缺省参数；listdir try/except 兜底；cleanup 空 active 名单不报错；C1/C2 冲突阈值文档对齐；02-classifier domain_final 明确写回 classify.json；06-synthesizer 处方完善写回 rx.json + prescriptions_outstanding 登记；接力棒协议补状态异常处理（FAILED / 产物缺失回退 / JSON 损坏备份重建）
- 验证：py_compile 通过；需求文档 §8.2 / 目录结构 / 审核范围同步；版本 0.4.10 → 0.4.11

## v0.4.10 (2026-08-08)

### 报告正文零场外话改造（真实用户反馈：成品报告残留"（LLM 列出名字）/ 例：/ LLM 回填"等模板指导语）

- **P1 模板指导语泄漏进报告正文**：build_report 骨架含"例：""（LLM 回填）""（LLM 列出名字，没有就写'无'）""回填区"等执行指导语，
  LLM 回填时未替换干净，直接出现在成品报告里，不专业
- 修复（run.py build_report）：
  - 所有模板指导语 → **HTML 注释**（`<!-- ... -->`，渲染不可见、回填后删除），正文只留干净专业结构
  - 标题/表头去模板后缀：`## 1. 给你的结论`、`| # | 问题 |`、`通俗评估`、`## 4. 分类表`、`## 5. 冲突与问题`、`## 6. 评分明细`、`### 7.1 使用建议（如果你是…）`、`## 8. 历史对比`
  - "待 LLM 判定" → "未归类"；白话导读/影响示例/回填区 → HTML 注释
  - 报告尾部改为"*本报告由 SkillMedic 自动生成；结论、评分定级与行动建议由 AI 结合完整检查流程输出。*"
- 执行层强约束（防再犯）：
  - chunk-07 / 07-reporter 新增"**报告正文零场外话铁律**"：回填时替换并删除全部 HTML 注释、补全空占位，
    最终正文不得残留"例：/LLM 回填/AI 回填/回填区"或未替换的"（）"空占位
  - 05-auditor BLOCK-E 新增阻断：报告正文残留模板指导语或未删除的 HTML 注释 → 打回 07-reporter
- 验证：py_compile 通过；report 实跑新骨架干净（无"例：/LLM 回填"字样，指导语仅以 HTML 注释形式存在）；版本 0.4.9 → 0.4.10

## v0.4.9 (2026-08-05)

### TRACE 自检补漏（对照 skill-trace-checker 25 项清单）

- **P1 references/examples.md 缺失**（TRACE E 维度"每个主要模块有真实输出示例"）
  → 新建 `references/examples.md`：8 个命令（ping/scan/analyze/conflict/score/prescribe/report/diff）的场景→命令→输出片段示例
- **P1 渐进式披露第 3 层缺失**：SKILL.md 只引用 cli-guide，无 references 深度文档总览
  → SKILL.md 新增"深度参考（references/，渐进式披露第 3 层）"表，列出 7 个参考文件用途
- **P2 score 的 dim6 has_refs 信号失真**：inventory 无 ref_files_count，静态显示 false（实际有 references）
  → scan_skills 补 `ref_files_count`（统计 references/reference/templates/protocols/agents 下 md/yaml/json 数）；实测 has_refs 恢复为 true
- **P3 SKILL.md 缺"禁止笼统提示"**（TRACE R 维度"禁止'请提供更多信息'式空话"）
  → 异常处理小节补一条："缺信息时禁止回复'请提供更多信息'，必须列出具体缺哪 N 项"
- 验证：py_compile 通过；score 自举 has_refs=true；版本号 0.4.8 → 0.4.9（SKILL.md / manifest / README）

## v0.4.8 (2026-08-05)

### 真实用户反馈 5 项核查与修复（68 Skill 环境全流程实测）

- **P1 docstring 参数序错误**：docstring 写 `report --save <root>`，但 report 实际无条件落盘、--save 冗余，且与 cli-guide/README（`report <root>`）不一致
  → docstring 改为 `report <project_root>` 并注明"总是落盘，无需 --save"；需求文档 §8.2 同步
- **P1 analyze/score 只认裸目录名**：scan 输出完整 path，但 analyze/score 传 `skills/xbrowser` 报"未找到该 Skill"
  → analyze_skill 支持三种入参（绝对路径 / 相对路径 / 裸目录名）；score 取 basename 匹配，报错提示改为"请用 scan 输出的 Skill 目录名"
- **P2 中文 bigram 碎片噪声**：字符级双字滑窗产生"以下/件与/么使"等无意义交集，导致 C2 大量误报
  → STOP_BIGRAMS 扩充 60+ 中文高频碎片与跨词 bigram（实跑验证 conflict 候选下降）
- **P3 候选目录未覆盖 .qclaw/skills**：GLOBAL_SKILLS_DIRS 补 `~/.qclaw/skills`；注释说明"候选目录无法穷举，未覆盖时依赖 available_skills 或传 project_root 到对应目录"
- **P4 报告占位符易误读**：报告尾部新增阅读提示——"标有「LLM 回填 / 例：」的区块是 AI 完善区，需经完整检查流程（MED_DEBRIEF）回填后才算完成；只跑 CLI 看到占位属正常现象"
- 验证：py_compile 通过；analyze 传完整路径、score 传裸名、conflict/report 实跑均正常；版本号 0.4.6 → 0.4.8（SKILL.md / manifest / README）

## v0.4.6 (2026-08-05)

### 四档评级语义精确定义（消除"放心用=很安全"的误读）

- 明确评级本质：**衡量 Skill 的"可靠性 / 完成度"**（能不能稳定把它承诺的功能执行到位、达到你的目的），**不是"安不安全"**（数据安全与合规不在此评分内）
- 四档"准确含义"重写（chunk-05 成熟度表 + 报告 0.1 图例区 + 需求文档 §5.2 同步）：
  - 放心用（L3）= 能稳定完成它承诺的功能，复杂场景也可靠，出问题能自己兜住
  - 基本能用（L2）= 常规场景能完成功能，但缺异常处理/自检/边界，复杂输入可能出错，需要多检查
  - 不太成熟（L1）= 只能处理理想样例，真实业务容易翻车，可能达不到你要的效果
  - 不建议用（L0）= 基本不可用，用了大概率白折腾
- 附八维判据：L3=八维健全；L2=核心流程完整但异常/边界/工程薄弱；L1=只有流程骨架或纯模板；L0=骨架不完整
- 同步：chunk-05 / chunk-07 / run.py build_report / README / 需求文档 §5.2；版本号 0.4.5 → 0.4.6（SKILL.md / manifest / README）
- **frontmatter 兼容性修复**：description 从 YAML `>` 折叠语法改为**单行纯文本**（参考 conspect 格式），避免部分解析器只显示"`>`"而看不到描述内容；内部引号改为中文弯引号防解析歧义；同步 SKILL.md 与 manifest
- 验证：py_compile 通过；scan 验证 frontmatter 解析正常

## v0.4.5 (2026-08-05)

### 实跑报告复盘（E:/skill_example 29 Skill 完整报告）发现 2 问题并修复

- **P1 报告定级阈值漂移再现**：报告第 9 部分写成"≥75=L3 / 55~74=L2 / 35~54=L1 / <35=L0"，
  与 chunk-05 固定阈值（L3≥80 / 55~79 / 30~54 / <30）不符 → wb-finance-skill(79)/scout(78) 被错误定为 L3（应为 L2），分级名单跟着错
  → chunk-07 第 9 部分强制"定级规则必须引用 chunk-05 固定阈值，禁止自创"；07-reporter 新增"报告格式铁律"；
    05-auditor BLOCK-E 增加"报告第 9 部分定级规则 ≠ 固定阈值"阻断
- **P2 0.1 图例区缺失**：07-reporter 重写报告时把"怎么读这份报告"固定图例区删掉了
  → chunk-07 标注"固定区块，07-reporter 重写报告时不得删减"；05-auditor BLOCK-E 增加"0.1 图例区缺失"阻断
- 验证：py_compile 通过；版本号 0.4.4 → 0.4.5（SKILL.md / manifest / README）

## v0.4.4 (2026-08-05)

### 建议按角色对号入座：让用户"带入自己，明白看什么、做什么"

- 之前用"普通用户可跳过"模糊边界，用户不知道"普通用户"指谁 → 改为**按角色对号入座**
- **7.1 使用建议**：标注"**如果你是 Skill 的使用者，看这里**"（不用改文件，覆盖注意什么/风险/什么需求别指望它）
- **7.2 改造建议**：标注"**如果你是 Skill 的创建者 / 维护者，看这里**"（需改文件，标注"使用者可完全跳过本节"）
- **0.1 图例区新增"对号入座"行**：只是用 Skill 干活 → 看第 1 部分和第 7.1；自己写/维护 Skill → 看第 7.2
- **1.3 标题标注"（如果你是使用者）"**，提示"创建者想改文件的建议见第 7.2 节"
- 同步：chunk-07 / 07-reporter-agent / 需求文档 §7 / run.py build_report；版本号 0.4.3 → 0.4.4（SKILL.md / manifest / README）
- 验证：py_compile 通过

## v0.4.3 (2026-08-05)

### 行动建议分层：普通用户"能照做"，不再只有改文件的技术活

- **第 7 部分拆为两层**：
  - **7.1 使用建议**（LLM 回填，必写）：普通人直接照做、**不用改任何文件**，覆盖"注意什么 / 有什么风险 / 什么需求别指望它"
    （例："别用 XX 处理正式数据"、"要生成手册时用 A 而不是 B"、"XX 只支持英文，中文项目达不到你要的效果"）
  - **7.2 改造建议**（规则候选）：合并/删文档/补说明/瘦身等需改 Skill 文件的操作，明确标注
    "**普通用户不用自己动手**，按 7.1 使用建议规避即可；想根治转发给 Skill 作者处理"
- **汇报层同步收紧**：1.2 TOP 榜"建议怎么办"、1.3"最该做的 2~3 件事"**只给不用改文件的使用类建议**
  （如"以后都用 A，B 先别用"），改文件的建议一律放 7.2
- 一致性：1.3 从 7.1 使用建议推导（05-auditor BLOCK-E 核对范围更新）
- 同步：chunk-07 / 07-reporter-agent / 需求文档 §7 / run.py build_report；版本号 0.4.2 → 0.4.3（SKILL.md / manifest / README）
- 验证：py_compile 通过；E:/skill_example 实跑 report 无报错

## v0.4.2 (2026-08-05)

### 报告用户友好度深化：普通用户"看得懂、读得下去"

- **新增 0.1"怎么读这份报告"图例区**：四档评级 / 五类冲突 / 八维评分 / 严重度含义一句话解释，第一次用也不懵
- **清单表通俗化**：状态 active/broken → 正常/损坏；范围 global/workspace → 全局/项目内；结构列改"多角色/分块/工具/协议"
- **冲突表通俗化**：类型 C1~C5 → 功能重复（C1）/抢着响应（C2）/占资源（C3）/共享依赖（C4）/抢工具（C5）；严重度 candidate → 待确认；证据列注明"含机器比对信息，AI 复核后补人话解读"
- **评分表通俗化**：列名改"触发说明/流程步骤/异常处理/产出检查/边界约束/工程配套/维护痕迹"，加注"数字=机器统计证据数（专业参考），快速看结论看'通俗评估'列"
- **处方表通俗化**：建议方向 merge/add-antitrigger/... → 合并重复/补'何时不要调用'/划清边界/明确分工顺序/瘦身/补维护文档
- **分级名单增强"使用局限"**：对"不太成熟 / 不建议用"档的 Skill 各补一句"什么场景下容易出问题、别用它做什么"（LLM 回填）
- 同步：chunk-07 / 07-reporter-agent / 需求文档 §7 / run.py build_report；版本号 0.4.1 → 0.4.2（SKILL.md / manifest / README）
- 验证：py_compile 通过；E:/skill_example 实跑 report 无报错

## v0.4.1 (2026-08-05)

### 报告双层结构：人话汇报层 + 专业明细层（专业数据不删减，易用性更好）

- 报告升级为**双层结构（元信息 + 9 个编号部分）**：编号 1"给你的结论"是**人话汇报层**（结论先给、大白话），编号 2~9 是**专业明细层**（清单/分类/冲突矩阵/八维评分/处方全量/历史对比/标准对照完整保留）
- 汇报层三要素（LLM 回填，必写）：
  - **1.1 健康度总评**：一句话总评 + 分布条（放心用 █ 7 ｜ 基本能用 █ 5 ｜ 不太成熟 █ 1 ｜ 不建议用 █ 1）+ **分级名单**（把每个 Skill 名字归入四档，逐个点名，让"谁好谁不好"落到具体名字）
  - **1.2 最需要注意的问题 TOP 榜**（3~5 条）：问题一句话 / 影响你什么 / 建议怎么办
  - **1.3 你现在最该做的 2~3 件事**（从第 7 部分处方全量挑最高优先级）
- 一致性铁律：汇报层数据**必须**从第 5 部分冲突矩阵、第 6 部分评分表推导，"结论可简化、不可矛盾"（05-auditor BLOCK-E 核对）
- 冲突矩阵上方新增"白话导读"占位（LLM 回填 N 组干扰/重复 + 最需注意的一对）
- 同步：chunk-07 / 07-reporter-agent / 需求文档 §7 / run.py build_report；版本号 0.4.0 → 0.4.1（SKILL.md / manifest / README）
- 验证：py_compile 通过；E:/skill_example 实跑 report 无报错

## v0.4.0 (2026-08-05)

### 用户视角通俗化（让普通用户一眼看懂，不依赖圈内术语）

- **描述重写**：去掉"军团体检"等黑话，改为"检查你安装的所有 AI Skill：列出清单、发现重复或冲突、评估是否成熟可靠、告诉你怎么办"，并同步到 SKILL.md / manifest / README
- **触发契约通俗化**：触发示例改为"我有哪些 skill / 哪些 skill 重复了 / skill 有没有问题 / 该留哪个 skill"等日常说法
- **成熟度标签通俗化**：L3~L0 从"成熟/可用/玩具 Demo/残缺僵尸"改为"放心用 / 基本能用 / 不太成熟 / 不建议用"（chunk-05 对照表 + 报告统一用通俗标签，L 级仅括号备注）
- **报告 9 部分结构**（chunk-07 + run.py build_report）：新增"一句话总结"、"冲突影响你什么（含自然语言唤醒举例）"、"给普通用户的行动建议"、"通俗评估列"，历史对比改为"上次的问题解决了吗"
- **统一清理**：chunk-02/06/08/09、agents、faq-deep、CHANGELOG、run.py 注释中的"军团/体检/玩具/僵尸/验尸官"等表述全部改为日常语言
- **重复安装识别落地**：scan_skills 不再静默丢弃同名 Skill，重复安装位置记入 `dup_sources`，报告"冲突与问题"区新增"重复安装"展示（例：同一 Skill 在 `.trae/skills` 与 `.claude/skills` 各装一份 → 建议只保留一份）
- 验证：py_compile 通过

## v0.3.4 (2026-08-05)

### 陌生环境实跑报告复盘（E:/skill_example，20 Skill 审计）发现 4 问题并修复

- **P1 评分口径漂移**：实跑报告用了"每维 0-100 再加权 + 定级阈值 85/60/30"，
  与内置 rubric（每维满分=权重、总分=Σ、L3≥80/55~79/30~54/<30）不符，违反可复现性
  → chunk-05 新增"评分规则（口径强约束）"：每维给分上限=权重值、总分=Σ、阈值固定；
    05-auditor BLOCK-C 增加口径违规阻断
- **P1 报告数字矛盾**：总览健康度（L3=7）与评分表汇总（L3=1）不一致
  → chunk-07 回填区强约束"健康度总评必须从评分表推导且逐项一致"；05-auditor BLOCK-E 核对
- **P2 C1 英文停用词噪声**：14 对 C1 候选多为 to/use/when/not 等模板词重叠
  → run.py STOP_BIGRAMS 增补 40+ 英文停用词（含 skill/agent/baton 等无区分度词）
- **P2 同源去重未规范**：ReqPlan-v3 双路径分别计数未走规则
  → chunk-02 新增"同源裁决"条款：去重优先，需分别计数必须标注理由（05-auditor 校验）
- 验证：py_compile 通过；conflict 重跑 C1 候选量应显著下降

## v0.3.3 (2026-08-05)

### 机制走查（接力棒/状态机/分块/批量/多角色）修复

- **P1 修复：cleanup 破坏历史资产**——原逻辑删除 `_medic_inventory.json` 与全部报告，
  导致增量模式/历史对比失效 → 改为仅清理本次会话中间产物（classify/conflicts/scores/rx），
  保留 inventory 与历史报告；并明确"cleanup 仅在 MED_CLOSE（会话完成）后执行，中断续跑前禁止"
- **P2 修复 3 处断链**：
  1. MED_VITAL 批分组依据明确为 `domain_final`（02-classifier LLM 判定），domain_hint 仅兜底（chunk-05）
  2. 接力棒初始化动作细化（00-master：接力棒不存在→按 baton-protocol 结构创建，含 meta/progress/batch 初始值）
  3. MED_SCOPE 产出载体明确为接力棒 `meta.scan_scope`；闸门表逐阶段对应产物文件（phase-protocol）
- 验证：cleanup 保留 inventory+报告、diff 增量仍可用、全链路命令无回归

## v0.3.2 (2026-08-05)

### 端到端流程走查 + CLI 实装（参考 conspect）

- **流程走查（带入 AI 模拟 MED_SCOPE→MED_CLOSE 全流程）发现 4 处阻塞并修复**：
  1. **P1 中间产物断链**：scan/categorize/conflict/score/prescribe 只输出不落盘，但各阶段要求 `_medic_*.json`
     → 全部命令加 `--save`，统一落盘 `.medic/`（score 累积合并到 `_medic_scores.json`）
  2. **P1 缺 CLI 实装约定**：AI 会裸跑 PowerShell / `python -c`
     → 新增 `references/cli-guide.md`（参考 conspect 模式）：{CLI_DIR} Glob 定位 / 统一 `cd`+`python run.py` /
       正斜杠路径 / 中间产物强制 `--save` / 失败处理流程 / 禁止 `python -c`
  3. **P2 project_root 来源未明确** → cli-guide 明确"用当前工作目录，正斜杠写法"
  4. **P2 分类表产物路径未定义** → `categorize --save` 落盘 `_medic_classify.json`
- SKILL.md 新增"CLI 工具层"强制约定；chunk-02 / agents 01/03/04/06 调用方式同步为 `--save` + cli-guide 引用
- 需求文档 §8.2（命令 + --save 落盘表）、§16.1（cli-guide 资产）同步
- **验证**：端到端跑通 scan→categorize→conflict→score×N→prescribe 全部 --save 落盘成功，
  `.medic/` 生成 5 个中间产物 JSON

## v0.3.1 (2026-08-05)

### M5 质量体系：TRACE 联网核查 + 20 子项补全

- **联网核查结论**：TRACE 已是 SkillHub 官方标准（腾讯新闻科技+SkillHub+腾讯玄武实验室 2026-05-21 联合发布），
  五维 20 子项；本地 skill-trace-checker v2.0.0 与官方一致（无版本漂移）
- **对照 20 子项逐项自查 skill-medic**，补全 7 处缺口：
  1. 能力边界三分类（✅擅长 6/⚠️需素材 3/❌超范围 5）→ T3/A9 达标
  2. 安全红线章节（不读配置值/不代执行/脱敏）→ T2/T4 达标
  3. 异常处理与输出准确性（信息不足列出缺什么/失败重试/证据可回溯禁编造）→ R5/E17 达标
  4. 受众说明（4 类用户）→ A11 达标
  5. 定制化参数（范围限定/增量/专项/严格模式）→ A12 达标
  6. 主文档 FAQ（6 题，补齐 C16 主 FAQ ≥6 缺口）→ C16 达标
  7. 国内真实场景示例（电商/微信小程序/企业微信/个人开发者）→ T1 达标
- §16.3 TRACE 引用更新为官方 20 子项标准
- 验证：SKILL.md 扩容后 1691 token，仍 < 8k 阈值且分块加载；语法 OK

## v0.3.0 (2026-08-05)

### M4 报告与自举

- `run.py report` 升级为**完整报告装配器**（`build_report`）：
  元信息 / 总览（含功能域分布）/ 清单表 / 分类表 / 冲突矩阵 / 评分信号摘要 / 处方清单 / 历史对比 / 标准对照
  ——8 部分静态装配 + LLM 回填区（八维打分、健康度总评、历史洞察、处方精确指引）
- report 同时落盘 `.medic/_medic_inventory.json`（增量 diff 与历史对比基础）
- 全局 Skill 自动纳入审计（实测探测到 game-design-document-main 等，§3.2 第二组候选真实命中）
- 新增 references/score-keys.md（评分证据定位指南，补齐 §16.1 文档清单）
- 更新 chunk-07（报告结构 + LLM 回填区职责）
- **自举验收**：用本 Skill 审自己，八维打分 98/100 → L3（≥80）通过
  - 触发契约 14（desc 略短）/ 流程 15 / 异常 12 / 产出 13 / 边界 12 / 价值 12 / 工程 10 / 维护 10

## v0.2.0 (2026-08-05)

### M3 评分与处方

- `run.py score <skill>`：输出**八维静态证据信号**（`static_score_signals`）——每维候选命中词 +
  结构信号（has_chunks/tokens/has_tools 等），只做抽象信号检测，供 04-scorer LLM 打分参照
- `run.py prescribe`：**规则处方候选**（`build_prescriptions`）——基于冲突矩阵 + 静态维护信号，
  生成 merge（C1）/ add-antitrigger（C2）/ slim（C3）/ boundary（C4）/ schedule（C5）/
  fix-frontmatter / maintain / fix-or-archive 候选；精确执行指引由 LLM 完善
- 更新 chunk-05（静态信号与八维对照表）、chunk-06（处方规则引擎表）、需求文档 §8.2、README
- 验证：score stylist 输出真实薄弱信号（dim4 自检为空、dim7 缺工程配套）；
  prescribe 对 C1 style-weaver↔stylist 给出 merge 候选

## v0.1.6 (2026-08-05)

### 全环境去影子化：产物/状态目录自包含（陌生环境可直接执行）

- **问题**：接力棒 `.agent/harness/_medic_baton.json` 与产物目录 `_batch_data/` 都是当前环境约定，
  陌生环境不存在这些目录，执行时"找不到北"
- **修正**：
  - 新增本 Skill 专属产物目录 **`.medic/`**（环境无关、自动创建，`medic_dir()` 统一管理）：
    接力棒、清单、冲突矩阵、评分表、报告、审核报告全部收口到这里
  - `.agent/harness` 降级为 C4 **检测信号**（检测"别的 Skill"是否共享状态目录），本 Skill 自身不再依赖
  - run.py / SKILL.md / chunks / agents / protocols / references / .gitignore / 需求文档全部同步
- 验证：`report` 在陌生无目录环境下自动创建 `.medic/` 并落盘成功

## v0.1.5 (2026-08-05)

### 去除文档中的环境文件引用（_baton.json / skill-config.json）

- **问题**：`_baton.json`（当前环境 scout/deepdive 的共享状态文件）与 `skill-config.json`（当前环境的
  Skill 启用配置）是环境产物，别人的电脑上不一定有，写死会造成困惑
- **修正**：
  - "不用 `_baton.json`" → "状态文件使用专属命名 `_medic_baton.json`，不依赖任何既有 Skill 的状态文件"
  - "不自动改 `skill-config.json`" → "不自动改 IDE 的 Skill 启用配置（启用/禁用清单需用户确认）"
  - 本 Skill 自己的 `_medic_baton.json` 保留（每个 Skill 都需定义状态文件路径）
  - run.py 中 `.agent/harness` 补注为"启发式检测信号，别人的环境没有也不影响（不命中即不报冲突）"

## v0.1.4 (2026-08-05)

### 分发文档去环境引用（不写死私人 Skill 名）

- **问题**：SKILL.md / chunks / agents / references / README / protocols 中引用了具体私人 Skill 名
  （如 skill-trace-checker、scout、stylist、style-weaver），其他用户无法理解，且属环境硬编码
- **修正**：全部替换为**抽象角色描述**：
  - 路由/边界："skill-creator"→"Skill 创建类 Skill"；"skill-trace-checker"→"单体质量自检类 Skill"；"c-drive-cleaner"→"系统维护类 Skill"
  - 冲突示例："style-weaver↔stylist"→"同功能的两个风格定制 Skill"；"scout↔deepdive↔fepilot"→"多个浏览器探索类 Skill"
  - JSON/输出示例：scout → example-skill；baton 示例 → skill-a/skill-b
- run.py 注释中的环境示例同步泛化（维护者可读且不误导）
- CHANGELOG 保留历史记录（当时真实验证对象不篡改）；需求文档 §3.2 为"真实待检样本"设计意图，保留

## v0.1.3 (2026-08-05)

### Skill 发现机制：顺着 IDE 引导，不写死目录

- **第一数据源 = IDE 注入的 available_skills 清单**（01-inventory-agent 负责合并），文件系统扫描仅补充静态指标
- **多编辑器兼容探测**：workspace 候选 `.trae/skills` → `.claude/skills` → `.cursor/skills` → `.codex/skills` → `skills`；全局候选 `~/.trae-cn/skills` 等；探测不到**不阻断**，以 available_skills 为准
- 清单增加 `source` / `scope` 字段，同名去重 workspace 优先
- 修复 Windows 跨盘 relpath ValueError（`rel_or_abs` 降级为绝对路径）

### 分析深度边界（外检，不解剖）

- 明确本 Skill 只做**抽象层**：识别类型 / 看关系 / 查体积 / 提取资源依赖**字段名路径**（不读值）
- **不读**业务数据/服务器配置/账号配置内容，**不分析**被检 Skill 业务逻辑，**不逐行**审代码（归 skill-trace-checker）
- 边界写入 chunk-02 分析深度铁律、01-inventory-agent 禁止清单、需求文档 §9.1.1，防执行越界超上下文

## v0.1.2 (2026-08-05)

### 硬编码/硬性规则全面清理（防跨环境失真）

- **工具目录识别泛化**：`["scout_tools", "deepdive_tools", ...]` 硬编码列表（3 处）→ `is_tools_dir()`（任意 `<skill>_tools` / `tools`）
- **DB 表名/库名提取泛化**：`aitest`、`scout_|deepdive_|parse_` 前缀硬编码 → SQL 上下文行级提取（FROM/INTO/UPDATE/JOIN/CREATE TABLE）+ `database` 赋值 + `get_<db>_db_config` 函数名，通用提取任意环境真实表名/库名
- **交互模型关键字去环境词**：去掉 aitest/scout_表/deepdive_表，只留通用技术信号（MySQL/sqlite/postgres 等）
- **平台路径与阈值集中配置**：`.trae/skills`、`.agent/harness`、`_batch_data` 与 C1~C5 阈值统一收口到 run.py 顶部"集中配置"区
- **文档一致性同步**：chunk-03/chunk-04 交互模型判定与阈值表更新；需求文档 §5.1 功能域开放语义、§5.3 阈值表、§8.2 补 categorize
- 验证：冲突检测信号保持干净（C1 style-weaver↔stylist；C4 scout-config/SCOUT_DB_PASSWORD/aitest；C5 playwright），无回归

## v0.1.1 (2026-08-05)

### M2 修正：功能域分类改为开放语义域

- **问题**：功能域静态关键词表（9 个固定域）由当前 11 个 Skill 归纳而来，无法覆盖用户任意行业安装的 Skill，跨领域会失真/误判
- **修正**：功能域改为开放语义域——静态表降级为"已知域启发式提示"（`domain_hint` + `domain_evidence`），
  最终分类由 02-classifier-agent 基于正文语义判定，允许创造新域标签；未命中时不得判"其他"
- 交互模型 / 生命周期保持确定性结构信号判定（tools 目录 / mcp-reference / CHANGELOG / 设计文档）
- 同步更新 chunk-03-categorize.md、agents/02-classifier-agent.md

### M2 功能：分类与冲突规则引擎

- `run.py categorize`：三维分类静态初值（功能域提示 / 交互模型 / 生命周期）
- `run.py conflict`：五类冲突静态检测（C1 同质 / C2 意图抢占 / C3 上下文膨胀 / C4 依赖 / C5 资源竞争）
  - C1/C2 基于 description 轻量中文分词（双字 bigram + 停用词）+ Jaccard/交集阈值
  - C4 环境变量精确提取（os.environ/os.getenv/$env:），避免 SQL 关键词误报
  - C4 基础设施型共享（≥4 Skill 引用）聚合单列，避免矩阵爆炸
  - 资源引用比对只读"实现声明"文件（agents/protocols/tools/mcp-reference），不读知识材料避免自引用误报
  - broken Skill 用设计文档兜底描述，参与同质/意图抢占比对
- 验证：独立推导出 §3.2 的 style-weaver↔stylist 同质冲突、scout/deepdive/fepilot 资源竞争等候选

## v0.1.0 (2026-08-04)

### M1 骨架搭建

- 创建完整目录结构（1-manifest / SKILL.chunks / agents / protocols / references / medic_tools）
- SKILL.md：触发契约 + 反触发 + 状态机总览 + 路由表
- manifest：skill-medic 元数据登记
- 9 个分块文件（chunk-01~09）：覆盖扫描/分类/冲突/评分/处方/报告/审核
- 8 个子 Agent 文档（00-master-controller ~ 07-reporter-agent）
- 协议文件：baton-protocol.md + phase-protocol.md
- 工具层：medic_tools/run.py（scan / analyze / conflict / score / diff / report / ping / cleanup）
- 参考文件：rubric-detail / conflict-catalog / anti-patterns / faq-deep
- README + CHANGELOG + .gitignore