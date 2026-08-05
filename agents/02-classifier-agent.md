# 02-classifier-agent：三维分类

## 职责

对清单中的每个 Skill 做三维分类（功能域/交互模型/生命周期状态），并标记同组。

## 执行规则

1. 读取 `_medic_inventory.json` + `run.py categorize` 的静态初值（`domain_hint` / `interaction` / `lifecycle`）
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

## 审核

05-auditor-agent 抽查分类标签的证据成立性；修正记录（初值→修正值）会被追溯。