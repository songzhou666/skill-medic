# 命令输出示例（references/examples.md）

> 以下示例来自真实环境（`project_root` 下含多个 Skill）的 CLI 输出，供快速对照：看到类似的输出即说明工具层工作正常。
> 格式：**场景 → 命令 → 输出片段**。输出会因环境 Skill 不同而不同，重点是**结构**一致。

---

## 1. ping —— 工具自检

**场景**：执行前确认环境可读、Python 可用。

**命令**：`python run.py ping <project_root>`

**输出片段**：
```json
{
  "project_root_exists": true,
  "skills_dirs_found": 1,
  "python_version": "3.13.x",
  "all_ok": true
}
```

---

## 2. scan —— 全量清单

**场景**：盘点所有 Skill，产出清单 JSON（含同名去重与重复安装记录）。

**命令**：`python run.py scan <project_root> --save`

**输出片段**（每项关键字段；`path` 为平台原生绝对路径，Windows 下为反斜杠，**命令行入参请用正斜杠**）：
```json
{
  "name": "conspect",
  "path": "C:\\Users\\...\\skills\\conspect",
  "scope": "global",
  "description": "全自动多源数据智能分析与商务报表渲染工具。…",
  "tokens_est": 6341,
  "ref_files_count": 3,
  "has_agents": true,
  "has_chunks": true,
  "has_tools": true,
  "has_protocols": true,
  "status": "active"
}
```

---

## 3. analyze —— 单 Skill 静态指标

**场景**：查单个 Skill 的静态指标（支持 绝对路径 / 相对路径 / 目录名 三种入参）。

**命令**：`python run.py analyze <project_root> <skill>`

**输出片段**：
```json
{
  "name": "conspect",
  "status": "active",
  "chars": 17341,
  "tokens_est": 6341,
  "always_load_tokens_est": 6534,
  "has_changelog": true,
  "has_readme": true,
  "has_agents": true,
  "has_chunks": true,
  "has_tools": true,
  "has_protocols": true
}
```

---

## 4. conflict —— 五类冲突候选

**场景**：静态冲突检测，产出 C1~C5 候选（供 03-conflict-agent 复核证据、判定严重度）。

**命令**：`python run.py conflict <project_root> --save`

**输出片段**：
```json
{
  "C1": [
    {
      "skill_a": "tencent-docs",
      "skill_b": "tencent-saas-docs",
      "type": "C1",
      "jaccard": 0.848,
      "overlap_count": 84,
      "keywords": ["文档", "在线", "新建"],
      "severity": "candidate"
    }
  ],
  "C2": [
    {
      "skill_a": "agent-browser",
      "skill_b": "xbrowser",
      "type": "C2",
      "overlap_count": 6,
      "keywords": ["浏览器", "自动化"],
      "severity": "medium"
    }
  ]
}
```

---

## 5. score —— 单 Skill 八维静态信号

**场景**：输出一个 Skill 的八维静态证据信号（供 04-scorer-agent 打分时定位证据）。

**命令**：`python run.py score <project_root> <skill> --save`

**输出片段**：
```json
{
  "name": "skill-medic",
  "status": "active",
  "desc_len": 196,
  "desc_has_antitrigger": true,
  "dim1_trigger": ["何时调用", "应触发", "不要调用"],
  "dim2_flow": ["阶段", "当"],
  "dim3_exception": ["信息不足", "失败", "重试", "熔断"],
  "dim4_output": ["自检", "中间产物"],
  "dim5_boundary": {"hits": ["分层", "chunk"], "has_chunks": true},
  "dim6_value_weak": {"has_refs": true, "tokens_est": 1757},
  "dim7_engineering": {"has_tools": true, "has_readme": true},
  "dim8_maintain": {"has_changelog": true}
}
```

---

## 6. prescribe —— 规则处方候选

**场景**：基于冲突矩阵 + 静态维护信号生成规则处方候选（供 06-synthesizer 完善）。

**命令**：`python run.py prescribe <project_root> --save`

**输出片段**：
```json
[
  {
    "type": "add-antitrigger",
    "severity": "medium",
    "targets": ["agent-browser", "xbrowser"],
    "conflict": "C2",
    "rule": "意图抢占：为双方 description 补充'何时不要调用'反触发说明，降低误触发",
    "llm_todo": "给出各 Skill description 的改写建议（精确措辞）"
  }
]
```

---

## 7. report —— 报告落盘

**场景**：装配报告静态骨架并落盘（总是落盘，无需 `--save`；结论区由 AI 在 MED_DEBRIEF 回填）。

**命令**：`python run.py report <project_root>`

**输出片段**：
```json
{
  "report_path": "./.medic/skill_audit_report_20260806_134509.md",
  "inventory_path": "./.medic/_medic_inventory.json",
  "skills_count": 11,
  "conflict_candidates": 39,
  "prescriptions": 45
}
```

---

## 8. diff —— 增量差异

**场景**：与上次清单对比，输出新增/变更/删除的 Skill。

**命令**：`python run.py diff <project_root> [last_inventory]`（缺省用 `.medic/_medic_last_inventory.json`）

**输出片段**：
```json
{
  "added": ["xbrowser", "kdocs"],
  "removed": ["old-skill"],
  "changed": ["conspect"]
}
```

---

> 各命令的失败处理、定位方式与禁止项见 `references/cli-guide.md`。
