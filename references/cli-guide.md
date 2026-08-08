# CLI 工具层调用约定 — cli-guide

> 本 Skill 的所有静态分析（扫描/分类/冲突/评分信号/处方/报告）**必须**通过 CLI 工具层
> `medic_tools/run.py` 执行。AI 禁止绕过 CLI 自己写 Python 内联代码。

## 一、定位 CLI 目录（{CLI_DIR}）

```
1. 用 Glob 全局搜索（最可靠）：
   glob **/skill-medic/medic_tools/run.py

2. 多个结果时优先选择：
   - 不在 c:\Users\{user}\.trae-cn\ 路径下的（系统目录可能不是最新版）
   - 在项目所在盘符下的（如 e:\、d:\）

3. 定位后记下目录路径为 {CLI_DIR}，验证：ls {CLI_DIR}/run.py 确认存在
4. 后续所有调用统一：先 cd {CLI_DIR}，再 python run.py <action> ...
```

> **⚠️ project_root 铁律（与 cd 无关）**：`cd {CLI_DIR}` 只用于定位 run.py 脚本，**与 project_root 无关**。
> `project_root` 永远取 **AI 上下文中的会话项目根**（绝对路径显式传入，如 `e:/Mytest_skill`），
> 不随 cd 改变；**禁止用 `Get-Location` 的结果代替 project_root**（cd 后 Get-Location 得到的是 CLI_DIR，
> 会导致 scan/classify/report 以错误根目录产生空产物，`.medic/` 也会建错位置）。

## 二、统一调用方式

```powershell
cd {CLI_DIR}
python run.py <action> <project_root> [params] [--save]
```

**project_root 规则**：
- **永远取 AI 上下文中的会话项目根**（绝对路径显式传入），与 `cd {CLI_DIR}` 后的位置无关
- 不确定时，用 `Get-Location` 查看**会话启动目录**（非 cd 后的位置），再对照上下文确认项目根
- 路径用**正斜杠**（`e:/Mytest_skill`），避免反斜杠转义问题
- 路径含空格时用双引号包裹：`python run.py scan "e:/My Project"`

## 三、命令速查表

| action | 命令 | 产物（--save） | 阶段 |
|--------|------|---------------|------|
| ping | `python run.py ping <root>` | — | MED_SCOPE |
| scan | `python run.py scan <root> --save [--scope workspace\|global] [--extra-dir <path>...]` | `.medic/_medic_inventory.json`（--scope 限定扫描范围，用户限定"只看 workspace/global"时使用；--extra-dir 追加用户自定义 Skill 目录，可多次传入，scope 标记为 custom） | MED_ROSTER |
| analyze | `python run.py analyze <root> <skill>` | —（skill 支持 绝对路径 / 相对路径 / 目录名） | MED_ROSTER |
| categorize | `python run.py categorize <root> --save` | `.medic/_medic_classify.json` | MED_SORT |
| conflict | `python run.py conflict <root> --save` | `.medic/_medic_conflicts.json` | MED_CONFLICT |
| score | `python run.py score <root> <skill> --save` | `.medic/_medic_scores.json`（累积；skill 支持 绝对路径 / 相对路径 / 目录名） | MED_VITAL |
| prescribe | `python run.py prescribe <root> --save` | `.medic/_medic_rx.json` | MED_RX |
| report | `python run.py report <root>` | `.medic/skill_audit_report_*.md` + inventory | MED_DEBRIEF |
| diff | `python run.py diff <root> [last_inventory]` | —（缺省用 `.medic/_medic_last_inventory.json`） | 增量模式 |
| cleanup | `python run.py cleanup <root>` | 白名单清理临时中间产物（classify/conflicts/scores/rx/review；**保留 `_medic_baton.json` / `_medic_inventory.json` / `_medic_last_inventory.json`、历史报告与 S3/S4 档附录文件 `skill_audit_appendix_*.md`**——断点续跑 / 增量模式 / 历史对比的基础） | MED_CLOSE |

> **中间产物必须 --save 落盘**：每个阶段结束后，确认对应 `_medic_*.json` 已生成；
> 产物缺失即阻断，禁止跳过落盘直接进入下一阶段。

## 四、禁止事项（违规即流程违规）

- [禁止] 使用 `python -c "..."` / `python.exe -c "..."` 执行内联 Python（PowerShell 引号嵌套会 ParserError）
- [禁止] CLI 失败后放弃 CLI 自行写代码替代（按下方失败处理流程）
- [禁止] 在 PowerShell 中对路径/参数做手工转义拼接（用正斜杠 + 引号即可）
- [禁止] 用终端 `write` 命令写文件（那是 Write-Output 别名只打印不落盘；写 JSON 用 IDE Write 工具）

## 五、CLI 失败处理流程（强制）

```markdown
[P0 阻断] CLI 命令失败（ParserError/路径错误/FileNotFound）时，AI 不得自行写 Python 代码替代！

[正确] 失败处理流程：
1. 确认 {CLI_DIR} 路径是否正确（重新 Glob 搜索 run.py）
2. 确认是否先 cd 到了 {CLI_DIR}
3. 检查 project_root 是否用了正斜杠且引号包裹（如 "e:/My Project"）
4. 重试命令
5. 仍失败：将需要执行的 Python 逻辑写入 .py 脚本文件再执行（而非 -c 内联）

[错误] 失败后的错误做法：
- ❌ 放弃 CLI，直接用 python -c "import json; ..."
- ❌ 说"CLI 不能用，所以我用对话能力直接分析"
- ❌ 跳过 --save 改用对话转述代替中间产物
```

## 六、与 AI 的分工（边界）

| CLI 工具层 | AI（LLM） |
|-----------|----------|
| 静态计算：扫描/关键词/引用比对/token/信号提取 | 语义判断：功能域最终分类、冲突证据确认、八维打分、处方精确指引 |
| 确定性、可复现、全量一次跑完 | 分批精析、深度洞察、历史对比、报告回填 |
| 产物落盘（--save） | 接力棒维护（**00-master 用 Write 工具更新** `.medic/_medic_baton.json`，子 Agent 禁止直写） |

> 一句话：**CLI 管"数得出来的"，AI 管"要理解的"。**
> CLI 失败不归因于"AI 能力不足"，走失败处理流程即可。
>
> **补录限制**：`run.py` 各命令（categorize/conflict/prescribe/report）以**磁盘扫描**为准，不携带 01-inventory
> 合并的 IDE 补录项——IDE 清单独有但磁盘不可见的 Skill，由 07-reporter 在报告第 3 部分手工补入并标注"IDE 清单独有"。