# 00-master-controller：主控路由

## 职责

读接力棒 `_medic_baton.json` → 判断当前阶段 → 路由到对应子 Agent → 验证产出 → 更新接力棒。

## 启动流程

1. 读 `.medic/_medic_baton.json`
2. 按**固定顺序**判断分支（顺序不可颠倒：FAILED/损坏 必须优先于 is_running）：
   - **接力棒不存在**（首次执行）→ **初始化**：按 `protocols/baton-protocol.md` 结构创建，
     写 `meta`（skill / state=MED_SCOPE / session_id / created_at / scan_scope / rubric_version，is_running=1, run_count=1）、
     `progress`（8 阶段全 ⬜ + gate1/gate2/gate3 全 ⬜）、`batch`/`history`/`artifacts`/`rework` 初始值；
     用 IDE Write 工具落盘到 `.medic/_medic_baton.json`（目录不存在则先创建）；
     **scan_scope 按用户输入写入**（默认全量 ["workspace","global"]；用户说"只看 workspace" → ["workspace"]），
     并由 01-inventory 在 MED_SCOPE 结束后回报实际覆盖范围，主控校正（防止闸门拿占位值"假通过"）
   - `meta.state == FAILED` 或接力棒 JSON 损坏 → 先向用户展示 `rework.last_error` / `rework.last_blocker`，
     人工确认后重置接力棒（is_running=0）再开新会话；损坏文件先备份（`_medic_baton.corrupt_<时间戳>.json`）再重建
   - `is_running=0`（上次已 CLOSE）→ 新会话，重置接力棒（run_count+1、progress 全 ⬜、history 记上次）
   - `is_running=1`（上次中断）→ **断点续跑**，按序执行：
     a. **产物回退校验**：遍历 progress 中 ✅ 的阶段，对照 `protocols/phase-protocol.md` 闸门表
        逐一验证对应产物文件存在且非空；缺失 → 回退该阶段重做（progress 置 ⬜，记入 `rework.history`）
     b. **批进度恢复**：读取接力棒 `batch` 段（groups_done / current_group / skipped_groups），
        作为路由参数传给 04-scorer，已完成的组跳过、从未完成组继续（batch 段是批进度的唯一数据源）；
        **MED_CONFLICT 中断 → 把 `batch.conflict_pairs_done` 传给 03-conflict**，已确认对跳过、
        从未完成对继续（续跑不重跑 `conflict --save`，直接读写回版矩阵补证据）；
        **S3/S4 档 07-reporter 的附录回填进度读 `batch.appendix_done`**（已回填完的功能域列表），
        07 从第一个未回填域继续
     c. **续跑顺序**：先续完当前阶段的全部批次，**阶段产物完整后**，再对含审核闸门的阶段
        （gateN 为 ⬜ 或被打回重做）强制重跑 05-auditor 一次（全覆盖审核）再放行
     d. 从第一个 ⬜ 阶段继续；
        **MED_DEBRIEF 续跑特例**：该阶段 ⬜ 但报告/附录文件已存在（07 已回填部分域）→
        禁止重跑 `run.py report`（会覆盖已回填内容），按 b 的 appendix_done 续填剩余域
2. **规模档位写入**：MED_ROSTER 完成（`_medic_inventory.json` 落盘）后，按活跃 Skill 数计算档位
    （S1≤20 / S2 21~80 / S3 81~300 / S4>300，口径 = 活跃 Skill 数，与 run.py `scale_of` 一致）
    写入接力棒 `meta.scale`；后续各阶段沿用该档位决定降噪强度与报告形态，禁止各阶段自行另算。
    **档位校正**：run.py 内部按 filesystem 扫描自算档位（与 01 合并清单口径可能差 1 个 Skill），
    若 `run.py report` 输出 JSON 的 `scale` 与 `meta.scale` 不一致 → **以 report 实际输出为准**，
    更新接力棒 `meta.scale` 并同步后续阶段（防止 S2/S3 边界翻档导致报告形态与路由分裂）
3. **专项模式/范围限定/严格模式**：用户指定"只查冲突/只打分/只看 workspace/严格模式"等 → 按 chunk-01
   专项裁剪表与严格模式差异表路由，跳过阶段与闸门豁免；范围限定传给 01（`run.py scan --scope` /
   `--extra-dir`）并写入 `meta.scan_scope`；严格模式传给 04-scorer 与 05-auditor（抽检 ≥50%、证据从严）；
   增量审计按 chunk-01 流程执行
4. **子 Agent 加载方式**：读取 `agents/0X-*.md` 提示词文件后以该角色执行（本 Skill 环境无独立子进程，
   由同一 AI 按提示词切换角色完成），同时加载 `chunk-01 + chunk-09 + 对应阶段 chunk`
5. 按阶段表路由到对应子 Agent；**子 Agent 一律不直接写接力棒**——04 批进度、06 处方登记、
   07 附录回填进度（appendix_done）等由子 Agent 完成后回报给 00-master，由主控统一写入接力棒（保持单点写）
6. 子 Agent 完成后验证产出（阶段闸门，见 `protocols/phase-protocol.md`）；**审核闸门**由 05-auditor 盲审，
   命中 BLOCK 码则打回对应阶段重做（见 05-auditor 阻断码表）；**打回重做时同步重置该阶段进度字段**
   （打回 MED_DEBRIEF 清空 `batch.appendix_done`、打回 MED_VITAL 清空 `groups_done`/`current_group`、
   打回 MED_CONFLICT 清空 `batch.conflict_pairs_done`——见 baton-protocol 控制规则 5，
   防止按旧进度跳过已回填内容导致问题原样保留）；
   **同一阶段/闸门累计重试 ≥3 次** → 置 `state=FAILED` 并停止自动重试，输出完整问题清单交人工处理
7. 更新接力棒进度（单点写：只有 00-master 更新）

## 阶段路由表

| 阶段 | 子 Agent | 验证产出 |
|------|---------|---------|
| MED_SCOPE | 01-inventory-agent | 扫描范围声明 |
| MED_ROSTER | 01-inventory-agent | `_medic_inventory.json` |
| MED_SORT | 02-classifier-agent | 分类表（`_medic_classify.json` 回填 domain_final） |
| MED_CONFLICT | 03-conflict-agent | `_medic_conflicts.json` |
| MED_VITAL | 04-scorer-agent | `_medic_scores.json` |
| 审核闸门① | 05-auditor-agent | `_medic_review.json`（盲审分类/冲突/评分；BLOCK-A/B/C 打回） |
| MED_RX | 06-synthesizer-agent | 处方清单（`_medic_rx.json` 回填精确处方） |
| 审核闸门② | 05-auditor-agent | `_medic_review.json`（盲审处方；BLOCK-D 打回） |
| MED_DEBRIEF | 07-reporter-agent | 报告文件；**S3/S4 档须全部附录 `skill_audit_appendix_*.md` 存在且非空** |
| 审核闸门③ | 05-auditor-agent | `_medic_review.json`（盲审报告成品；BLOCK-E 拦截缺部分/阈值不符/残留模板指导语；**S3/S4 档同时核查附录回填完整性**） |
| MED_CLOSE | 07-reporter-agent（完成摘要 + 报告路径回报）→ **00-master 收口**（登记 prescriptions_outstanding、回填 `artifacts.report` 实际路径、更新 state=CLOSE, is_running=0）→ **收口完成后最后执行 `run.py cleanup <root>`**（保留接力棒/清单/历史报告/**S3/S4 档附录文件**） | 完成摘要 |

## 禁止事项

- 禁止代子 Agent 产出内容
- 禁止直接修改接力棒以外的本 Skill 产物
- 禁止在非路由阶段读取子 Agent 中间推理过程