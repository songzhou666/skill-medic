# SkillMedic — Skill 健康检查与冲突检测

## 定位

检查你安装的全部 AI Skill（技能）：列出清单、发现内容重复或互相冲突的 Skill、评估每个 Skill 是否成熟可靠，并告诉你怎么处理。

**你把 Skill 装了一堆，它帮你查清楚哪几个好用、哪几个重复、哪几个会打架、该留谁。**

## 功能

- **全量清单**：扫描 workspace + 全局 Skill，产出统一清单
- **三维分类**：功能域 / 交互模型 / 生命周期状态
- **五类冲突检测**：同质（C1）/ 意图抢占（C2）/ 上下文膨胀（C3）/ 依赖（C4）/ 资源竞争（C5）
- **八维成熟度评分**：0-100 分，L0~L3 定级（放心用 / 基本能用 / 不太成熟 / 不建议用；**评级 = 可靠性/完成度，不是安全性**）
- **综合处方**：保留 / 合并 / 整改 / 移除 建议
- **检查报告**：结构化 Markdown 报告，含"对日常使用的影响"与"现在建议你做什么"

## 快速开始

```bash
# 工具自检
python .trae/skills/skill-medic/medic_tools/run.py ping <project_root>

# 扫描所有 Skill（--save 落盘中间产物到 .medic/）
python .trae/skills/skill-medic/medic_tools/run.py scan <project_root> --save

# 分析单个 Skill（<skill_name> 换成实际 Skill 名）
python .trae/skills/skill-medic/medic_tools/run.py analyze <project_root> <skill_name>

# 静态冲突候选（--save 落盘中间产物到 .medic/）
python .trae/skills/skill-medic/medic_tools/run.py conflict <project_root> --save

# 八维评分静态证据信号（供 LLM 打分；--save 累积落盘）
python .trae/skills/skill-medic/medic_tools/run.py score <project_root> <skill_name> --save

# 规则处方候选（--save 落盘中间产物到 .medic/）
python .trae/skills/skill-medic/medic_tools/run.py prescribe <project_root> --save

# 生成报告
python .trae/skills/skill-medic/medic_tools/run.py report <project_root>
```

## 版本

v0.4.18 — 四档规模分级策略（S1 精细≤20 / S2 标准21~80 / S3 摘要81~300 / S4 极限>300：候选降噪、摘要报告+每域附录、处方聚合按档自动启用，少则精多则省）；v0.4.17 候选降噪与摘要模式

## 依赖

- Python 3.10+
- 标准库（无需第三方依赖）