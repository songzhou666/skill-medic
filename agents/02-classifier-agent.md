# 02-classifier-agent：三维分类

## 职责

对清单中的每个 Skill 做三维分类（功能域/交互模型/生命周期状态），并标记同组。

## 执行规则

1. **先执行** `medic_tools/run.py categorize <root> --save`（CLI 约定见 references/cli-guide.md），生成 `.medic/_medic_classify.json` 静态初值（`domain_hint` / `interaction` / `lifecycle`），再读取该文件
2. **功能域 = LLM 语义判定（开放域）**：
   - 参考但不盲从 `domain_hint`；命中且语义吻合 → 采纳；不符 → 覆盖并记录"初值 → 修正值 + 理由"
   - `domain_hint` 为空 → 基于正文语义自主判定并写 evidence
   - **禁止**因"不在静态关键词表"而判"其他"或强行塞相近域；允许创造新域标签（如"医疗文书"）
3. **交互模型 / 生命周期**：确认静态初值（确定性信号），异常时修正（留理由）
4. 每个分类标签必须有 evidence（来源 description 或正文行）
5. 同一功能域的 Skill 标记为同组
6. 输出格式：`example-skill | 文档生成 · 纯提示词型 · 活跃维护 | evidence: ...`

## 产出

分类表（每个 Skill 的三维标签 + evidence + 同组标记），回填 `domain_final`。
**回填必须写回 `.medic/_medic_classify.json`**（用 IDE Write 工具覆盖更新该 JSON 的
`domain_final` / `interaction` / `lifecycle` 三个字段——交互模型与生命周期的修正结论同样要落盘，
下游 `load_classify_merged` 把三者都当作"LLM 回填字段"消费、报告第 4 部分照此展示），
下游 05-auditor / 04-scorer / 06-synthesizer 统一读该文件，禁止只留在对话里。

## 审核

05-auditor-agent 抽查分类标签的证据成立性；修正记录（初值→修正值）会被追溯。