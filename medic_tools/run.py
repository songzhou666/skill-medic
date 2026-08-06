"""
medic_tools - SkillMedic 工具层 CLI

用法:
    python run.py scan <project_root>                 # 列出所有 Skill 目录
    python run.py analyze <project_root> <skill>      # 静态指标分析（skill 支持路径或目录名）
    python run.py conflict <project_root>             # 静态冲突候选
    python run.py score <project_root> <skill>        # 静态指标输出（skill 支持路径或目录名）
    python run.py diff <project_root> <last_inventory># 增量差异对比
    python run.py report <project_root>               # 生成报告（总是落盘 .medic/，无需 --save）
    python run.py ping <project_root>                 # 工具自检
    python run.py cleanup <project_root>              # 清理临时文件

说明:
    - 命令统一格式为 <action> <project_root> [params] [--save]，参数在前、选项在后
    - report 无条件落盘报告与清单，--save 可省略
    - 仅跑 CLI 得到的是"静态骨架"，第 1/5/6/7 部分的结论/评分/建议由 AI
      在完整检查流程（MED_DEBRIEF）中回填后才算完成
"""

import argparse
import json
import os
import sys
import math
import re
from datetime import datetime


# ================= 集中配置（工程骨架强约束） =================
# 调整任何数值/路径，必须同步需求文档 §5.3 / §9.2 / §6.3 与 CHANGELOG，禁止悄悄改。

# Skill 存放位置探测（顺着 IDE/平台引导，不写死单一目录）：
# - workspace 候选目录：多编辑器兼容（Trae/Claude/Cursor/Codex/通用约定），全部存在的都收集，按序优先
# - 全局目录：§9.1 探测，探测不到不阻断
# - 铁律：IDE 运行时注入的 available_skills 清单是**第一数据源**（01-inventory-agent 负责合并），
#   文件系统扫描仅用于补充路径/静态指标，禁止因为"目录探测不到"就判定没有 Skill
SKILLS_DIR_CANDIDATES = [
    os.path.join(".trae", "skills"),    # Trae IDE
    os.path.join(".claude", "skills"),  # Claude Code
    os.path.join(".cursor", "skills"),  # Cursor
    os.path.join(".codex", "skills"),   # OpenAI Codex
    "skills",                            # 通用约定
]
GLOBAL_SKILLS_DIRS = [                                  # 全局 Skill 候选目录（§9.1，探测不到不阻断）
    os.path.join(os.path.expanduser("~"), ".trae-cn", "skills"),
    os.path.join(os.path.expanduser("~"), ".claude", "skills"),
    os.path.join(os.path.expanduser("~"), ".cursor", "skills"),
    os.path.join(os.path.expanduser("~"), ".trae", "skills"),
    os.path.join(os.path.expanduser("~"), ".qclaw", "skills"),
]
# 说明：候选目录无法穷举所有 IDE（.qclaw 等为常见补充）。
# 未覆盖的目录：① 依赖 IDE 注入的 available_skills 清单（第一数据源）；
# ② 或把 project_root 直接指向该目录（命中通用 'skills' 候选）。
# 本 Skill 专属产物目录（环境无关、自动创建）：
# 清单/冲突/评分/报告/接力棒统一放这里，命名空间 _medic_*，不依赖任何既有 Skill 的目录约定
MEDIC_DIR = ".medic"

# C4 检测信号：其他 Skill 可能共享的状态/中间产物目录（启发式；本 Skill 自身不使用该目录，
# 别人的环境即使没有也不影响——不命中即不报冲突）
HARNESS_DIR_REL = os.path.join(".agent", "harness")

# 冲突静态检测阈值（§5.3；bigram 分词粒度下的经验值，LLM 可修正初值但须留理由）
C1_MIN_OVERLAP = 20          # 同质冲突：绝对交集数（一方描述长稀释 jaccard 时的兜底）
C1_MIN_JACCARD = 0.12        # 同质冲突：Jaccard 下限
C1_OVERLAP_JACCARD = 8       # 同质冲突：需同时满足 overlap 与 jaccard 的下限
C2_MIN_OVERLAP = 4           # 意图抢占：非模板词交集下限
C2_HIGH_OVERLAP = 10         # 意图抢占：高严重度交集数
C3_TOKEN_THRESHOLD = 8000    # 上下文膨胀：常驻 token 阈值（且无 chunk 分层）
C3_HIGH_TOKEN = 30000        # 上下文膨胀：高严重度阈值
C4_INFRA_MIN_OWNERS = 4      # 依赖冲突：基础设施型共享（≥N Skill 引用则聚合单列，避免矩阵爆炸）

# token 估算公式（§9.2，固定）
TOKEN_CJK_DIV = 1.7
TOKEN_ASCII_DIV = 4


def is_tools_dir(name: str) -> bool:
    """工具目录识别：任意 <skill>_tools 或 tools，不依赖具体 Skill 名（避免环境硬编码）"""
    return name == "tools" or name.endswith("_tools")


def find_skills_dirs(project_root: str) -> list[tuple[str, str]]:
    """
    探测所有存在的 Skill 目录（多编辑器兼容，顺着平台引导），返回 [(绝对路径, scope)]。
    - workspace 候选目录按 SKILLS_DIR_CANDIDATES 顺序，存在的全部收集（可混用多个编辑器）
    - 全局目录按 GLOBAL_SKILLS_DIRS 探测，找不到不阻断
    - 注意：探测不到不代表没有 Skill——available_skills 清单（IDE 注入）由 LLM 层合并
    """
    found = []
    for rel in SKILLS_DIR_CANDIDATES:
        p = os.path.join(project_root, rel)
        if os.path.isdir(p):
            found.append((p, "workspace"))
    for gp in GLOBAL_SKILLS_DIRS:
        if os.path.isdir(gp):
            found.append((gp, "global"))
    return found


def rel_or_abs(path: str, start: str) -> str:
    """跨盘安全的相对路径：Windows 跨盘（C: vs e:）relpath 会抛 ValueError，降级为绝对路径"""
    try:
        return os.path.relpath(path, start)
    except ValueError:
        return path


def medic_dir(project_root: str) -> str:
    """返回本 Skill 专属产物目录（自动创建；环境无关，不依赖任何既有目录约定）"""
    d = os.path.join(project_root, MEDIC_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def save_medic_json(project_root: str, filename: str, data) -> str:
    """把中间产物落盘到 .medic/（自动创建目录），返回文件路径"""
    path = os.path.join(medic_dir(project_root), filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def get_project_root() -> str:
    """获取项目根目录（从命令行参数或环境变量）"""
    return os.environ.get("PROJECT_ROOT", os.getcwd())


def token_estimate(text: str) -> int:
    """
    估算 token 数。
    公式：ceil(cjk_chars / TOKEN_CJK_DIV + ascii_chars / TOKEN_ASCII_DIV)
    - cjk_chars: 中文字符数（Unicode 0x4E00-0x9FFF）
    - ascii_chars: 其余字符数
    """
    cjk_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    ascii_chars = len(text) - cjk_chars
    return math.ceil(cjk_chars / TOKEN_CJK_DIV + ascii_chars / TOKEN_ASCII_DIV)


def read_file_safe(filepath: str) -> tuple[str | None, str | None]:
    """
    安全读取文件，尝试 UTF-8 → GBK。
    返回 (content, error_message)
    """
    for encoding in ['utf-8', 'gbk']:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                return f.read(), None
        except UnicodeDecodeError:
            continue
        except FileNotFoundError:
            return None, f"文件不存在: {filepath}"
        except Exception as e:
            return None, f"读取失败: {e}"
    return None, f"编码无法识别（尝试 UTF-8/GBK 均失败）: {filepath}"


def parse_frontmatter(content: str) -> dict:
    """
    解析 frontmatter（YAML 风格的 --- 块），支持多行折叠值（> / |- / 缩进续行）。
    返回字段字典，含完整度标记。
    """
    result = {
        "name": None, "display_name": None, "version": None,
        "description": None, "tags": None, "language": None,
        "has_frontmatter": False, "frontmatter_completeness": 0
    }
    # 匹配 --- 包围的 frontmatter 块
    m = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not m:
        return result

    result["has_frontmatter"] = True
    fm_text = m.group(1)

    current_key = None
    current_lines = []
    for raw_line in fm_text.split('\n'):
        if raw_line.startswith(' ') or raw_line.startswith('\t'):
            # 缩进续行：属于上一个 key 的多行值
            if current_key is not None:
                current_lines.append(raw_line.strip())
            continue
        # 新 key 行
        if ':' in raw_line:
            # 先落盘上一个多行 key
            if current_key is not None and current_lines and current_key in result:
                result[current_key] = " ".join(current_lines)
            key, _, val = raw_line.partition(':')
            key = key.strip()
            val = val.strip()
            current_key = key if key in result else None
            current_lines = []
            if current_key is None:
                continue
            if val in (">", "|-", "|", ">-", "|-"):
                # 多行折叠：后续缩进行拼接到该 key
                continue
            result[key] = val.strip('"').strip("'")
    # 落盘最后一个多行 key
    if current_key is not None and current_lines and current_key in result:
        result[current_key] = " ".join(current_lines)

    # 计算完整度
    required = ["name", "description", "version", "tags"]
    filled = sum(1 for r in required if result.get(r))
    result["frontmatter_completeness"] = filled / len(required)
    return result


def scan_skills(project_root: str) -> list[dict]:
    """
    扫描所有存在的 Skill 目录（多编辑器兼容，见 find_skills_dirs）。
    返回清单列表（不含正文全文）；同名 Skill 去重，workspace 优先，
    重复安装位置记入已收录条目的 dup_sources（供报告"重复安装"识别）。
    """
    dirs = find_skills_dirs(project_root)
    if not dirs:
        print(f"Warning: 未探测到任何 Skill 目录（已尝试 {SKILLS_DIR_CANDIDATES} 与全局候选）——"
              f"可能目录在别处，请以 IDE 注入的 available_skills 清单为准")
        return []

    def record_duplicate(name: str, item_path: str, skills_dir: str, scope: str) -> None:
        """同名 Skill 在其他目录再出现时，把该安装位置记入已收录条目的 dup_sources（重复安装识别）"""
        for s in inventory:
            if s.get("name") == name:
                s.setdefault("dup_sources", []).append({
                    "path": item_path,
                    "source": rel_or_abs(skills_dir, project_root),
                    "scope": scope,
                })
                return

    inventory = []
    seen_names = set()
    for skills_dir, scope in dirs:
        for item in sorted(os.listdir(skills_dir)):
            item_path = os.path.join(skills_dir, item)
            skill_md = os.path.join(item_path, "SKILL.md")

            # 跳过 zip 备份
            if item.endswith(".zip") or not os.path.isdir(item_path):
                continue

            # 检查 SKILL.md 是否存在
            if not os.path.isfile(skill_md):
                # broken Skill 兜底：尝试从设计文档提取描述（参与 C1/C2 比对）
                fallback_desc = ""
                for doc_name in ["设计需求文档.md", "_design.md", "README.md"]:
                    doc_path = os.path.join(item_path, doc_name)
                    if os.path.isfile(doc_path):
                        content, _ = read_file_safe(doc_path)
                        if content:
                            fallback_desc = content[:1200]
                            break
                if item in seen_names:
                    record_duplicate(item, item_path, skills_dir, scope)
                    continue  # 同名已收录（workspace 优先）
                seen_names.add(item)
                inventory.append({
                    "name": item,
                    "path": item_path,
                    "source": rel_or_abs(skills_dir, project_root),
                    "scope": scope,
                    "description": fallback_desc,
                    "desc_source": "design_doc" if fallback_desc else None,
                    "status": "broken",
                    "broken_reason": "SKILL.md 缺失"
                })
                continue

            # 读取 SKILL.md（仅 frontmatter + 统计）
            content, error = read_file_safe(skill_md)
            if error:
                if item in seen_names:
                    record_duplicate(item, item_path, skills_dir, scope)
                    continue
                seen_names.add(item)
                inventory.append({
                    "name": item,
                    "path": item_path,
                    "source": rel_or_abs(skills_dir, project_root),
                    "scope": scope,
                    "status": "broken",
                    "broken_reason": error
                })
                continue

            # 同名去重：workspace 优先（候选目录顺序在前），重复安装位置记录到已收录条目
            if item in seen_names:
                record_duplicate(item, item_path, skills_dir, scope)
                continue
            seen_names.add(item)

            # 解析 frontmatter
            fm = parse_frontmatter(content)

            # 目录结构标志
            dir_structure = {
                "has_changelog": os.path.isfile(os.path.join(item_path, "CHANGELOG.md")),
                "has_readme": os.path.isfile(os.path.join(item_path, "README.md")),
                "has_agents": os.path.isdir(os.path.join(item_path, "agents")),
                "has_chunks": os.path.isdir(os.path.join(item_path, "SKILL.chunks")),
                "has_tools": any(
                    os.path.isdir(os.path.join(item_path, entry))
                    for entry in os.listdir(item_path)
                    if is_tools_dir(entry)
                ),
                "has_protocols": os.path.isdir(os.path.join(item_path, "protocols")),
                "has_manifest": os.path.isfile(os.path.join(item_path, "1-manifest", "skill-manifest.yaml")),
            }

            # references 等深度文档数量（dim6 内容价值弱信号：有深度参考 = 方法论沉淀）
            ref_files_count = 0
            for ref_dir in ["references", "reference", "templates", "protocols", "agents"]:
                ref_path = os.path.join(item_path, ref_dir)
                if os.path.isdir(ref_path):
                    for _root, _dirs, files in os.walk(ref_path):
                        ref_files_count += sum(1 for f in files if f.endswith((".md", ".yaml", ".json")))

            # 估算 token
            tokens_est = token_estimate(content)

            inventory.append({
                "name": item,
                "path": item_path,
                "source": rel_or_abs(skills_dir, project_root),
                "scope": scope,
                "description": fm.get("description", ""),
                "version": fm.get("version", ""),
                "tags": fm.get("tags", ""),
                "chars": len(content),
                "tokens_est": tokens_est,
                "ref_files_count": ref_files_count,
                "has_frontmatter": fm["has_frontmatter"],
                "frontmatter_completeness": fm["frontmatter_completeness"],
                **dir_structure,
                "status": "active"
            })

    return inventory


def analyze_skill(project_root: str, skill_name: str) -> dict:
    """
    对单个 Skill 做静态指标分析。
    返回指标字典。
    """
    # 定位该 Skill：支持三种入参——绝对路径 / 相对路径 / 裸目录名（与 scan 输出的 path 兼容）
    skill_dir = None
    if os.path.isdir(skill_name):
        # 绝对路径（如 scan 输出的完整 path）或已存在的相对路径
        skill_dir = skill_name
    elif os.sep in skill_name or "/" in skill_name:
        # 形如 skills/xbrowser 的相对路径：相对当前工作目录再试一次
        if os.path.isdir(skill_name):
            skill_dir = skill_name
    if skill_dir is None:
        # 裸目录名：在全部候选目录中查找
        base = os.path.basename(skill_name.rstrip("/\\"))
        for d, _ in find_skills_dirs(project_root):
            cand = os.path.join(d, base)
            if os.path.isdir(cand):
                skill_dir = cand
                break
    if not skill_dir:
        return {"name": skill_name, "error": "未找到该 Skill 目录（已探测传入路径与全部候选目录）", "status": "broken"}
    skill_md = os.path.join(skill_dir, "SKILL.md")

    if not os.path.isfile(skill_md):
        return {"name": skill_name, "error": "SKILL.md 不存在", "status": "broken"}

    content, error = read_file_safe(skill_md)
    if error:
        return {"name": skill_name, "error": error, "status": "broken"}

    fm = parse_frontmatter(content)

    # 统计结构标志
    def has_file(path):
        return os.path.isfile(path)

    def has_dir(path):
        return os.path.isdir(path)

    # 递归统计文件数和引用文件
    ref_files = []
    for ref_dir in ["references", "reference", "templates", "protocols", "agents"]:
        ref_path = os.path.join(skill_dir, ref_dir)
        if has_dir(ref_path):
            for root, dirs, files in os.walk(ref_path):
                for f in files:
                    if f.endswith((".md", ".yaml", ".json")):
                        ref_files.append(os.path.relpath(os.path.join(root, f), skill_dir))

    # 常驻加载量估算
    always_load = content  # SKILL.md 本身
    chunk_index = os.path.join(skill_dir, "SKILL.chunks", "chunk-index.yaml")
    if has_file(chunk_index):
        ci_content, _ = read_file_safe(chunk_index)
        if ci_content:
            always_load += "\n" + ci_content

    return {
        "name": skill_name,
        "status": "active",
        "chars": len(content),
        "tokens_est": token_estimate(content),
        "always_load_tokens_est": token_estimate(always_load),
        "frontmatter": fm,
        "has_changelog": has_file(os.path.join(skill_dir, "CHANGELOG.md")),
        "has_readme": has_file(os.path.join(skill_dir, "README.md")),
        "has_agents": has_dir(os.path.join(skill_dir, "agents")),
        "has_chunks": has_dir(os.path.join(skill_dir, "SKILL.chunks")),
        "has_protocols": has_dir(os.path.join(skill_dir, "protocols")),
        "has_manifest": has_file(os.path.join(skill_dir, "1-manifest", "skill-manifest.yaml")),
        "ref_files_count": len(ref_files),
        "ref_files": ref_files[:20],  # 最多列 20 个
    }


def static_score_signals(skill: dict) -> dict:
    """
    八维评分的静态证据信号（供 04-scorer-agent 的 LLM 打分参照，配合抽样正文）。
    只做抽象信号检测（关键词/结构命中），不读业务逻辑、不读配置值。
    命中词仅为"候选证据"，最终给分由 LLM 判断。
    """
    name = skill.get("name", "")
    skill_dir = skill.get("path") or ""
    desc = skill.get("description", "") or ""
    md = os.path.join(skill_dir, "SKILL.md")
    content = ""
    if os.path.isfile(md):
        content, _ = read_file_safe(md)
        content = content or ""
    text_l = (desc + "\n" + content).lower()

    def hits(words):
        return [w for w in words if w.lower() in text_l]

    return {
        "name": name,
        "status": skill.get("status"),
        "desc_len": len(desc),
        "desc_has_antitrigger": bool(re.search(r'不适用|不要调用|不要', desc)),
        # 维度 1 触发契约：描述中触发/反触发词
        "dim1_trigger": hits(["何时调用", "应触发", "适用场景", "不适用", "不要调用", "when to use", "when not"]),
        # 维度 2 流程机制：阶段/节点/分支词
        "dim2_flow": hits(["阶段", "phase", "step", "步骤", "节点", "禁止跳步", "分支", "如果", "当"]),
        # 维度 3 异常与熔断：缺信息/终止/重试词
        "dim3_exception": hits(["追问", "信息不足", "不足", "终止", "停止", "失败", "重试", "fallback", "熔断", "回退"]),
        # 维度 4 产出控制：自检/验收/中间产物词
        "dim4_output": hits(["checklist", "自检", "验收", "中间产物", "检查清单", "核对"]),
        # 维度 5 边界与上下文：上限/分层词 + 结构信号
        "dim5_boundary": {
            "hits": hits(["上限", "阈值", "超过", "拒绝", "超限", "分层", "分块", "chunk"]),
            "has_chunks": bool(skill.get("has_chunks")),
            "tokens_est": skill.get("tokens_est"),
        },
        # 维度 6 内容价值密度（弱信号，LLM 语义判定为主）
        "dim6_value_weak": {
            "has_refs": bool(skill.get("ref_files_count", 0) > 0),
            "chars": len(content),
            "tokens_est": skill.get("tokens_est"),
        },
        # 维度 7 工程配套
        "dim7_engineering": {
            "has_tools": bool(skill.get("has_tools")),
            "has_manifest": bool(skill.get("has_manifest")),
            "has_readme": bool(skill.get("has_readme")),
            "has_protocols": bool(skill.get("has_protocols")),
        },
        # 维度 8 维护健康度
        "dim8_maintain": {
            "has_changelog": bool(skill.get("has_changelog")),
            "version": skill.get("version"),
            "has_readme": bool(skill.get("has_readme")),
        },
    }


def build_prescriptions(project_root: str, inventory: list[dict], conflicts: dict) -> list[dict]:
    """
    基于冲突矩阵 + 静态维护信号生成**规则处方候选**（MED_RX 阶段 06-synthesizer 使用）。
    规则层只给候选与方向；精确执行指引（文件路径+改动内容+执行方式）与优先级由 LLM 完善。
    """
    rx = []
    active_names = {s["name"] for s in inventory if s.get("status") == "active"}

    # C1 同质冲突：保留评分高者合并评分低者（谁高谁低需 LLM 按八维评分定夺）
    for c in conflicts.get("C1", []):
        rx.append({
            "type": "merge", "severity": "high",
            "targets": [c["skill_a"], c["skill_b"]],
            "conflict": "C1",
            "rule": "同质冲突：保留八维评分较高者，合并/归档较低者",
            "llm_todo": "按八维评分定保留对象，给出合并具体动作（归档目录/删除重复文件）"
        })

    # C2 意图抢占：补反触发说明
    for c in conflicts.get("C2", []):
        rx.append({
            "type": "add-antitrigger", "severity": c.get("severity", "medium"),
            "targets": [c["skill_a"], c["skill_b"]],
            "conflict": "C2",
            "rule": "意图抢占：为双方 description 补充'何时不要调用'反触发说明，降低误触发",
            "llm_todo": "给出各 Skill description 的改写建议（精确措辞）"
        })

    # C3 上下文膨胀：瘦身/分块
    for c in conflicts.get("C3", []):
        rx.append({
            "type": "slim", "severity": c.get("severity", "medium"),
            "targets": [c["skill"]],
            "conflict": "C3",
            "rule": "上下文膨胀：常驻加载超限且无分块，拆分 chunk / 裁剪通用常识",
            "llm_todo": "给出拆分方案（哪些内容进 chunk、如何建索引）"
        })

    # C4 具体依赖冲突对（非基础设施）：划清职责或隔离
    for c in conflicts.get("C4", []):
        rx.append({
            "type": "boundary", "severity": "medium",
            "targets": [c["skill_a"], c["skill_b"]],
            "conflict": "C4",
            "resource": c.get("resource"),
            "rule": "依赖冲突：共享资源（%s）需明确读写职责，一方改动需同步另一方" % c.get("resource", ""),
            "llm_todo": "给出职责划分建议（谁读写该资源、变更通知机制）"
        })

    # C5 资源竞争：明确分工顺序或错峰
    for c in conflicts.get("C5", []):
        rx.append({
            "type": "schedule", "severity": "medium",
            "targets": [c["skill_a"], c["skill_b"]],
            "conflict": "C5",
            "resource": c.get("resource"),
            "rule": "资源竞争：同一资源（%s）需明确分工顺序或串行约束" % c.get("resource", ""),
            "llm_todo": "给出使用顺序/串行约束建议"
        })

    # 独立维护类处方（基于静态信号，对每个 active Skill）
    for s in inventory:
        if s.get("status") != "active":
            continue
        name = s["name"]
        if not s.get("has_frontmatter"):
            rx.append({
                "type": "fix-frontmatter", "severity": "medium",
                "targets": [name], "conflict": None,
                "rule": "frontmatter 缺失：补全 name/description/version/tags，description 需含'何时调用+何时不要调用'",
                "llm_todo": "给出补全后的 frontmatter 草案"
            })
        elif not (s.get("has_changelog") or s.get("has_readme")):
            rx.append({
                "type": "maintain", "severity": "low",
                "targets": [name], "conflict": None,
                "rule": "维护资产缺失：补充 CHANGELOG（版本记录）与 README（功能声明）",
                "llm_todo": "给出最小可行的 CHANGELOG/README 骨架"
            })
    # broken Skill：修复或归档
    for s in inventory:
        if s.get("status") == "broken":
            rx.append({
                "type": "fix-or-archive", "severity": "medium",
                "targets": [s["name"]], "conflict": None,
                "rule": "异常 Skill：SKILL.md 缺失或不可读，修复或归档（%s）" % s.get("broken_reason", ""),
                "llm_todo": "判断是否有保留价值（是否被引用/有设计文档），给出修复或归档动作"
            })

    return rx


def build_report(project_root: str, inventory: list[dict], classify: list[dict],
                 conflicts: dict, rx: list[dict]) -> str:
    """
    装配 Skill 检查报告（静态可得的全部部分：元信息/总览/清单/分类/冲突/评分信号/处方/历史/标准）。
    一句话总结、评分、冲突影响、行动建议等 LLM 产物以"回填区"占位，由 07-reporter 在 MED_DEBRIEF 完善。
    报告面向普通用户：专业术语只作括号备注，主表达用日常语言。
    """
    now = datetime.now()
    L = []
    active = [s for s in inventory if s.get("status") == "active"]
    broken = [s for s in inventory if s.get("status") == "broken"]

    # 0 元信息
    L.append("# Skill 检查报告\n")
    L.append(f"- **生成时间**：{now.strftime('%Y-%m-%d %H:%M:%S')}")
    L.append(f"- **扫描范围**：项目内（workspace）候选 {SKILLS_DIR_CANDIDATES}；全局候选 {GLOBAL_SKILLS_DIRS}（探测不到不阻断）")
    L.append("- **评分标准版本**：8-axis-v0.1（内置基线，可联网更新）")
    L.append(f"- **异常 Skill（损坏/不可读）**：{len(broken)} 个（未评分）")
    for b in broken:
        L.append(f"  - {b['name']}：{b.get('broken_reason', '未知')}")
    L.append("")

    # 0.1 怎么读这份报告（图例，普通用户先看这里）
    L.append("## 0.1 怎么读这份报告（第一次用先看这里）\n")
    L.append("- **结论在前**：第 1 部分是人话总结，第 2~9 部分是专业明细，看不懂细节不影响你拿到结论")
    L.append("- **四档评级（衡量 Skill 的\"可靠性/完成度\"，即能不能稳定达成它的功能目的；不是\"安不安全\"）**：")
    L.append("  放心用（L3）= 能稳定完成它承诺的功能，复杂场景也可靠，出问题能自己兜住；"
             "基本能用（L2）= 常规场景能完成功能，但缺异常处理，遇到复杂输入可能出错，需要你多检查；"
             "不太成熟（L1）= 只能处理理想样例，真实业务容易翻车，可能达不到你要的效果；"
             "不建议用（L0）= 基本不可用，用了大概率白折腾")
    L.append("- **冲突类型**：功能重复（C1）= 两个 Skill 做同一件事；抢着响应（C2）= 你一句话可能同时唤醒多个 Skill；"
             "占资源（C3）= 每次对话都要加载很多说明，可能拖慢 AI；共享依赖（C4）= 两个 Skill 共用同一个配置/文件；"
             "抢工具（C5）= 都要用同一个浏览器/工具")
    L.append("- **八维评分**：从 触发说明 / 流程步骤 / 异常处理 / 产出检查 / 边界约束 / 内容价值 / 工程配套 / 维护痕迹 "
             "8 个维度打分，总分 100。评分表里的数字 = 机器统计的说明充分度（专业参考），想快速知道结果看\"通俗评估\"列")
    L.append("- **严重度**：待确认 = 机器初判\"疑似\"，由 AI 复核后定级")
    L.append("- **对号入座**：你只是**用 Skill 干活** → 看第 1 部分和第 7.1 使用建议；你自己**写/维护 Skill** → 看第 7.2 改造建议\n")

    # 1 给你的结论（人话版汇报层；LLM 回填，必写）
    L.append("## 1. 给你的结论（人话版，LLM 回填）\n")
    L.append("> 这一节用大白话告诉你要紧的结果；专业数据与证据在第 2~9 部分完整保留，"
             "需要深究可往下看。汇报层**必须**从第 5 部分冲突矩阵、第 6 部分评分表推导，"
             "禁止另写一套分布（05-auditor BLOCK-E 核对）。\n")
    L.append("### 1.1 健康度总评\n")
    L.append("- 例：你装了 20 个 Skill，整体情况不错：7 个可以放心用，12 个基本能用但要注意，1 个不建议用。")
    L.append("- 分布条（LLM 绘制，与第 6 部分一致）："
             "放心用 ████████ 7 ｜ 基本能用 █████ 5 ｜ 不太成熟 █ 1 ｜ 不建议用 █ 1")
    L.append("- 分级名单（LLM 回填，**逐个点名**，谁好谁不好一眼看到底；必须与第 6 部分评分表逐项一致）：")
    L.append("  - 放心用（L3）：（LLM 列出名字，没有就写'无'）")
    L.append("  - 基本能用（L2）：（LLM 列出名字，没有就写'无'）")
    L.append("  - 不太成熟（L1）：（LLM 列出名字，没有就写'无'）")
    L.append("  - 不建议用（L0）：（LLM 列出名字，没有就写'无'）")
    names = sorted((s["name"] for s in active), key=str.lower)
    names_str = "、".join(names[:15]) + ("…等共" + str(len(active)) + " 个" if len(names) > 15 else "")
    L.append(f"- 本次检查范围：{len(active)} 个 Skill（{names_str}）\n")
    L.append("### 1.2 最需要注意的问题（TOP 榜，3~5 条）\n")
    L.append("| # | 问题（一句话） | 影响你什么 | 建议怎么办 |")
    L.append("|---|---------------|-----------|-----------|")
    L.append("| 1 | 例：有 2 个 Skill 功能重复 | 例：你不知道该用哪个，AI 也可能随机选一个 | 例：以后都用 A，B 先别用 |\n")
    L.append("### 1.3 你现在最该做的 2~3 件事（如果你是**使用者**）\n")
    L.append("- 例：1) 别用 XX 处理正式数据（有风险） 2) 要生成手册时用 A 而不是 B，避免结果不稳定 3) 3 个不太成熟的 Skill 先别用于重要任务\n")
    L.append("- 提示：如果你是 Skill 的**创建者 / 维护者**，想改文件根治问题的建议见第 7.2 节。\n")

    # 2 总览
    L.append("## 2. 总览\n")
    tokens = [s.get("tokens_est", 0) or 0 for s in active]
    avg_tok = sum(tokens) / len(tokens) if tokens else 0
    domain_count = {}
    for c in classify:
        d = c.get("domain_hint") or "待 LLM 判定"
        domain_count[d] = domain_count.get(d, 0) + 1
    L.append(f"- Skill 总数：{len(inventory)}（活跃 {len(active)} / 异常 {len(broken)}）")
    L.append(f"- 常驻估算 token：平均 {avg_tok:.0f} / 最大 {max(tokens) if tokens else 0}")
    L.append("- 功能域分布（静态提示）：" + "；".join(f"{k}×{v}" for k, v in sorted(domain_count.items(), key=lambda x: -x[1])))
    L.append("- 健康度分布条（LLM 回填，必须与第 1.1 节和第 6 部分一致）："
             "放心用 █ N ｜ 基本能用 █ M ｜ 不太成熟 █ K ｜ 不建议用 █ J\n")

    # 3 清单表
    L.append("## 3. 清单表\n")
    L.append("| Skill | 状态 | 所在位置 | 估算 Token | 版本 | 结构(多角色/分块/工具/协议) |")
    L.append("|-------|------|---------|-----------|------|---------------------------|")
    scope_plain = {"workspace": "项目内", "global": "全局"}
    status_plain = {"active": "正常", "broken": "损坏"}
    for s in sorted(inventory, key=lambda x: x["name"]):
        struct = "".join("✓" if s.get(k) else "·" for k in ["has_agents", "has_chunks", "has_tools", "has_protocols"])
        L.append(f"| {s['name']} | {status_plain.get(s.get('status'), s.get('status'))} | "
                 f"{scope_plain.get(s.get('scope'), s.get('scope'))} | {s.get('tokens_est', 'N/A')} | "
                 f"{s.get('version') or '-'} | {struct} |")
    L.append("")

    # 4 分类表
    L.append("## 4. 分类表（静态提示；最终分类由 LLM 语义判定后回填）\n")
    L.append("| Skill | 用途分组 | 交互方式 | 维护状态 |")
    L.append("|-------|-----------|---------|---------|")
    c_map = {c["name"]: c for c in classify}
    for s in sorted(inventory, key=lambda x: x["name"]):
        c = c_map.get(s["name"], {})
        L.append(f"| {s['name']} | {c.get('domain_hint') or '待判定'} | {c.get('interaction') or '-'} | {c.get('lifecycle') or '-'} |")
    L.append("")

    # 5 冲突与问题（专业明细：静态候选；影响由 LLM 回填）
    L.append("## 5. 冲突与问题（专业明细：静态候选；'影响你什么'由 LLM 用日常语言回填）\n")
    L.append("> 白话导读（LLM 回填）：你这里有 N 组 Skill 会互相干扰/重复，最需要注意的是 X×Y（原因一句话）。\n")
    conflict_type_plain = {
        "C1": "功能重复（C1）", "C2": "抢着响应（C2）", "C3": "占资源（C3）",
        "C4": "共享依赖（C4）", "C5": "抢工具（C5）",
    }
    severity_plain = {"candidate": "待确认", "low": "低", "medium": "中", "high": "高"}
    conflict_rows = (conflicts.get("C1", []) + conflicts.get("C2", []) +
                     conflicts.get("C4", []) + conflicts.get("C5", []))
    if conflict_rows:
        L.append("| A × B | 冲突类型 | 冲突点/资源 | 初判严重度 | 影响你什么（回填） |")
        L.append("|-------|---------|------------|-----------|-------------------|")
        for c in conflict_rows:
            a, b = c.get("skill_a", c.get("skill", "")), c.get("skill_b", "")
            res = c.get("resource") or c.get("keywords") or c.get("jaccard") or ""
            if isinstance(res, list):
                res = ",".join(str(x) for x in res[:5])
            t = conflict_type_plain.get(c.get("type"), c.get("type"))
            sev = severity_plain.get(c.get("severity"), c.get("severity", "待确认"))
            L.append(f"| {a} × {b} | {t} | {res} | {sev} | |")
        L.append("\n> 说明：'冲突点/资源'含机器比对信息（专业参考），AI 复核后会在'影响你什么'列补充人话解读。\n")
        L.append("\n> 影响示例（LLM 参考）：抢着响应 → \"当你说'帮我扫描页面'时，2 个 Skill 都会响应，AI 可能随机选一个 → 结果不稳定\"；"
                 "功能重复 → \"两个 Skill 做同一件事，你不知道用哪个，建议只留一个\";"
                 "同一 Skill 出现在两个 IDE 目录 → \"是分别安装过，建议只保留一份\"。\n")
    else:
        L.append("- 无冲突候选")
    for c in conflicts.get("C3", []):
        L.append(f"- 占资源（C3）：{c['skill']}（常驻 token {c['tokens_est']}，无分块）→ 每次对话加载较多说明，可能拖慢响应")
    if conflicts.get("C4_infra"):
        L.append("\n**基础设施共享**（多个 Skill 引用同一资源，聚合不拆对）：")
        for c in conflicts["C4_infra"]:
            L.append(f"- {c['resource']}：{', '.join(c['owners'])}")
    dups = [s for s in inventory if s.get("dup_sources")]
    if dups:
        L.append("\n**重复安装**（同一 Skill 出现在多个 IDE 目录，通常是分别安装过 → 建议只保留一份，避免更新不同步）：")
        for s in dups:
            others = "、".join(d["source"] for d in s["dup_sources"])
            L.append(f"- {s['name']}：{s.get('source', '-')}（已保留）+ {others}（重复）")
    L.append("")

    # 6 评分明细（静态信号摘要；打分与通俗评估由 LLM 回填）
    L.append("## 6. 评分明细（机器信号；AI 打分与通俗评估回填）\n")
    L.append("> 数字 = 该维度机器统计的证据数（越多说明这个 Skill 该维度写得越充分，专业参考用）；"
             "想快速知道结果，看最后一列\"通俗评估\"即可。\"内容价值\"维度由 AI 语义评判，不在表中。\n")
    L.append("| Skill | 触发说明 | 流程步骤 | 异常处理 | 产出检查 | 边界约束 | 工程配套 | 维护痕迹 | 通俗评估（回填） |")
    L.append("|-------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|-----------------|")
    for s in sorted(active, key=lambda x: x["name"]):
        sig = static_score_signals(s)
        L.append(f"| {s['name']} | {len(sig['dim1_trigger'])} | {len(sig['dim2_flow'])} | "
                 f"{len(sig['dim3_exception'])} | {len(sig['dim4_output'])} | "
                 f"{len(sig['dim5_boundary']['hits'])} | "
                 f"{sum(1 for v in sig['dim7_engineering'].values() if v)}/4 | "
                 f"{sum(1 for v in sig['dim8_maintain'].values() if v)}/3 | |")
    L.append("\n> 回填区：AI 对照八维细则给出每维分数/证据/扣分定位与定级，"
             "定级用通俗格式如\"放心用（L3）\"（映射：L3 放心用 / L2 基本能用 / L1 不太成熟 / L0 不建议用）\n")

    # 7 行动建议（分两层：7.1 使用建议=使用者直接照做；7.2 改造建议=创建者改 Skill 文件，可选）
    L.append("## 7. 行动建议\n")
    L.append("### 7.1 使用建议（LLM 回填）—— 如果你是 Skill 的**使用者**，看这里\n")
    L.append("> 不需要改任何文件，照着做就行。覆盖三类：**注意什么 / 有什么风险 / 什么需求别指望它**。\n")
    L.append("- （LLM 回填。例：1) \"reqplan-v3 别用于真实项目排期，它更适合演示\" "
             "2) \"要生成手册时用 A 而不是 B，避免两个 Skill 抢着响应导致结果不稳定\" "
             "3) \"游戏文档那个 Skill 只支持英文，中文项目达不到你要的效果\"）\n")
    L.append("### 7.2 改造建议 —— 如果你是 Skill 的**创建者 / 维护者**，看这里\n")
    L.append("> 以下建议需要改动 Skill 文件（合并/删文档/补说明/瘦身）。**使用者可以完全跳过本节**："
             "某个 Skill 影响使用，按 7.1 使用建议规避即可；你是作者想根治，再动手改。\n")
    rx_type_plain = {
        "merge": "合并重复", "add-antitrigger": "补'何时不要调用'", "boundary": "划清边界",
        "schedule": "明确分工顺序", "slim": "瘦身", "maintain": "补维护文档",
        "fix-frontmatter": "修复 Skill 说明信息", "fix-or-archive": "修复或归档",
    }
    rx_sev_plain = {"high": "高", "medium": "中", "low": "低"}
    if rx:
        # 按严重度排序（高→中→低），同一级别内保持原顺序
        rx_sorted = sorted(rx, key=lambda r: {"high": 0, "medium": 1, "low": 2}.get(r.get("severity"), 3))
        L.append("| 优先级 | 建议方向 | 对象 | 依据 |")
        L.append("|:---:|----------|------|------|")
        for r in rx_sorted:
            t = rx_type_plain.get(r['type'], r['type'])
            sev = rx_sev_plain.get(r.get("severity"), r.get("severity") or "-")
            L.append(f"| {sev} | {t} | {', '.join(r['targets'])} | {r['rule']} |")
        L.append("\n> 回填区：AI 按优先级输出\"现在建议你做什么\"（先处理\"高\"），并为每条补精确操作（文件路径 + 改动内容 + 执行方式）；\"是否执行\"由用户/作者决定。\n")
    else:
        L.append("- 无改造建议候选")
    L.append("")

    # 8 历史对比
    L.append("## 8. 历史对比（存在上次审计时输出）\n")
    last_inv = os.path.join(medic_dir(project_root), "_medic_inventory.json")
    if os.path.isfile(last_inv):
        try:
            with open(last_inv, 'r', encoding='utf-8') as f:
                last = json.load(f)
            cur = {s["name"] for s in inventory}
            prev = {s["name"] for s in last if isinstance(s, dict)}
            L.append(f"- 新增 Skill：{sorted(cur - prev) if cur - prev else '无'}")
            L.append(f"- 消失 Skill：{sorted(prev - cur) if prev - cur else '无'}")
            L.append("- 上次的问题解决了吗（成熟度变化 / 上期建议执行核对）：由 LLM 读取上次报告对比后补充")
        except Exception as e:
            L.append(f"- 读取上次清单失败：{e}")
    else:
        L.append("- 首次审计（无上次清单）")
    L.append("")

    # 9 标准对照
    L.append("## 9. 标准对照表\n")
    L.append("- 当前 rubric：8-axis-v0.1（内置基线，2026-08-04）")
    L.append("- 联网更新：未触发（用户未要求 / 版本未过期 / 非首次执行）。触发条件见 chunk-08")

    L.append("\n---\n")
    L.append("*报告由 SkillMedic 生成。标有「LLM 回填 / 例：」的区块是 AI 完善区：第 1 部分结论、第 5 部分冲突影响、"
             "第 6 部分评分定级、第 7.1 使用建议，需通过完整检查流程（MED_DEBRIEF）由 AI 回填后才算完成；"
             "若你只运行了 CLI，看到占位属正常现象。*")
    return "\n".join(L)


# ---- 三维分类静态初值（LLM 可修正，§4.3 软约束规则 2）----

# 功能域启发式提示表（仅对"已知域"提供初值提示，不穷举、不锁定分类）
# 注意：功能域是开放语义域，最终由 02-classifier-agent 基于 description + 正文语义判定，
# 可完全覆盖静态提示并创造新域标签（如"医疗文书""法律审查"）。本表命中与否都不代表最终分类。
FUNCTIONAL_DOMAIN_KEYWORDS = {
    "系统探索采集": ["探索", "采集", "页面", "扫描", "遍历", "骨架", "工单", "网页", "前端", "操作路径", "API扫描", "解析", "语料"],
    "数据分析报表": ["报表", "数据", "Excel", "看板", "统计", "图表", "可视化", "渲染", "多表合并"],
    "文档与手册": ["手册", "文档", "捕获", "编码", "注释", "操作手册"],
    "设计创意": ["游戏", "GDD", "策划", "机制", "玩法"],
    "风格定制": ["风格", "对话", "角色", "语气", "记忆文件", "模板"],
    "项目流程": ["项目", "流程", "需求", "开发", "测试", "管理", "规划", "重构", "修复", "里程碑"],
    "质量保障": ["缺陷", "检测", "安全", "调试", "性能", "风险报告", "Bug"],
    "Skill工程": ["Skill", "skill"],
    "系统维护": ["磁盘", "C盘", "清理", "空间", "缓存"],
}

# 交互模型精确关键字（命中优先序：浏览器 > 数据库 > 网络API > 脚本 > 纯提示词）
# 注意：只含通用技术信号（工具名/协议名），不含具体业务库名/表名——库名/表名是环境数据，由 C4 检测从代码通用提取
INTERACTION_KEYWORDS = {
    "浏览器驱动型": ["CDP", "Playwright", "browser_", "mcp_playwright", "Chrome CDP", "浏览器驱动", "浏览器端扫描", "浏览器扫描"],
    "数据库驱动型": ["MySQL", "数据库", "DB 连接", "读写 SQL", "sqlite", "postgres", "redis", "数据库驱动"],
    "网络API型": ["Gitea", "COS", "WebSearch", "工单同步", "网络请求", "REST", "Web API"],
    "脚本工具型": ["run.py", "_tools", "CLI", "命令行"],
}

def collect_skill_text(skill_dir: str, max_chars: int = 200_000) -> str:
    """
    收集 Skill 的"实现声明"文本（SKILL.md + agents/protocols + 工具层 py +
    references/mcp-reference.md），用于静态资源引用比对。
    注意：不读 references 其他文件与 SKILL.chunks——那些是知识/示例材料，
    其中的"CDP/Playwright"等词是说明文字，会被误判为资源声明（如本 Skill 的 conflict-catalog）。
    """
    chunks_text = []
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if os.path.isfile(skill_md):
        content, _ = read_file_safe(skill_md)
        if content:
            chunks_text.append(content)

    # agents / protocols 是执行声明文件
    for sub in ["agents", "protocols"]:
        sub_path = os.path.join(skill_dir, sub)
        if os.path.isdir(sub_path):
            for root, dirs, files in os.walk(sub_path):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in files:
                    if f.endswith(".md"):
                        fp = os.path.join(root, f)
                        content, _ = read_file_safe(fp)
                        if content:
                            chunks_text.append(content)

    # 仅 mcp-reference.md 属于资源声明，纳入比对
    mcp_ref = os.path.join(skill_dir, "references", "mcp-reference.md")
    if os.path.isfile(mcp_ref):
        content, _ = read_file_safe(mcp_ref)
        if content:
            chunks_text.append(content)

    # 工具层 py 文件（只读前 300 行，避免把整个实现读入）
    # 识别任意 <skill>_tools / tools 目录（is_tools_dir 泛化，不依赖具体 Skill 名）
    # 注意：跳过 medic_tools 自身——检测器代码天然包含所有关键字（playwright/CDP/aitest），
    # 读入会造成自引用误报（如本 Skill 的 run.py）
    if os.path.isdir(skill_dir):
        for entry in sorted(os.listdir(skill_dir)):
            if not is_tools_dir(entry) or entry == "medic_tools":
                continue
            tp = os.path.join(skill_dir, entry)
            if not os.path.isdir(tp):
                continue
            for f in os.listdir(tp):
                if f.endswith(".py") and f != "__init__.py":
                    fp = os.path.join(tp, f)
                    try:
                        with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                            chunks_text.append("\n".join(fh.readlines()[:300]))
                    except Exception:
                        pass

    text = "\n".join(chunks_text)
    return text[:max_chars]


# 环境变量精确提取模式（只匹配真实读取语法，避免 SQL 关键词/代码常量误报）
ENV_PATTERN = re.compile(
    r"os\.environ\[['\"]([A-Z_]+)['\"]\]"
    r"|os\.getenv\(['\"]([A-Z_]+)['\"]\)"
    r"|\$env:([A-Z_]+)"
    r"|env:([A-Z_]+)"
)


def extract_env_vars(text: str) -> set[str]:
    """从文本中提取真实环境变量名（os.environ / os.getenv / $env: / env: 语法）"""
    found = set()
    for groups in ENV_PATTERN.findall(text):
        for g in groups:
            if g:
                found.add(g)
    return found


# DB 表名提取（行级）：行含 SQL 关键字（SELECT/INSERT/UPDATE/DELETE/JOIN/CREATE TABLE）时，
# 提取 FROM/INTO/UPDATE/JOIN/TABLE 后的标识符；通用提取任意 Skill 的真实表名，不依赖表名前缀（环境数据）
SQL_KEYWORD = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE|JOIN|CREATE\s+TABLE)\b", re.IGNORECASE)
SQL_TARGET = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?(\w+)[`\"\]]?"
    r"|\b(?:FROM|INTO|UPDATE|JOIN)\s+[`\"\[]?(\w+)[`\"\]]?",
    re.IGNORECASE,
)
SQL_STOPWORDS = {
    "select", "insert", "update", "delete", "join", "table", "into", "from",
    "where", "set", "values", "if", "exists", "not", "null", "index", "key",
    "unique", "default", "as", "on", "left", "right", "inner", "outer", "cross",
    "count", "sum", "group", "order", "limit", "offset", "having", "distinct",
    "like", "and", "or", "in", "is", "by", "asc", "desc", "using", "case",
    "when", "then", "else", "end", "select", "database", "schema",
    # 时间函数与 SQL 内置，非表名
    "current_timestamp", "timestamp", "now", "curdate", "curtime", "date",
    "time", "utc", "utc_timestamp", "sysdate", "interval",
}

# DB 库名提取：直接赋值（database=… / "database": "…"）、db.get("name", …) 默认值、
# 以及 get_<db>_db_config 函数名（如某数据库类 Skill 的 get_xxx_db_config）
DB_NAME_PATTERN = re.compile(
    r"\b(?:database|db_name|dbname|DB_NAME|DATABASE)\s*[:=]\s*['\"](\w+)['\"]"
    r"|db\.get\(['\"]name['\"]\s*,\s*['\"](\w+)['\"]\)"
    r"|\bget_(\w+)_db_config\b",
    re.IGNORECASE,
)


def classify_skill(skill: dict, project_root: str) -> dict:
    """
    静态分类初值（§4.3 软约束：只给初值/提示，最终由 02-classifier-agent 语义判定）：
    - 功能域：开放语义域。静态关键词表仅提供"已知域"提示（domain_hint），
      未命中时 domain_hint=None，完全交由 LLM 基于正文语义判定，可创造新域标签。
    - 交互模型：确定性结构信号（tools 目录 / mcp-reference / description 精确词）→ 可信初值
    - 生命周期：确定性文件信号（CHANGELOG / _design.md / 设计需求文档）→ 可信初值
    """
    name = skill.get("name", "")
    desc = skill.get("description", "") or ""
    # 用清单中的 path（已在 scan_skills 阶段解析到具体目录，多编辑器兼容）
    skill_dir = skill.get("path") or os.path.join(project_root, "skills", name)

    # 功能域启发式提示：取命中关键词数最多的已知域；未命中则 None（不强制判"其他"）
    domain_hint = None
    domain_evidence = []
    if desc.strip():
        best_domain, best_score = None, 0
        for domain, kws in FUNCTIONAL_DOMAIN_KEYWORDS.items():
            hits = [kw for kw in kws if kw.lower() in desc.lower()]
            if len(hits) > best_score:
                best_domain, best_score = domain, len(hits)
                domain_evidence = hits[:5]
        domain_hint = best_domain if best_score > 0 else None

    # 交互模型文本源：description 为主（避免 SKILL.md 正文泛词如 API/数据库 误命中）
    probe_text = desc

    # 目录结构信号：有 references/mcp-reference.md → 浏览器/CDP 协作
    mcp_ref = os.path.join(skill_dir, "references", "mcp-reference.md")
    has_mcp_ref = os.path.isfile(mcp_ref)
    has_tools_dir = any(
        os.path.isdir(os.path.join(skill_dir, entry))
        for entry in os.listdir(skill_dir)
        if is_tools_dir(entry)
    )

    # 交互模型：mcp-reference 为最强浏览器信号；其次按精确关键字命中；再次 tools 目录 → 脚本工具型
    interaction = "纯提示词型"
    if has_mcp_ref:
        interaction = "浏览器驱动型"
    else:
        for model, kws in INTERACTION_KEYWORDS.items():
            if any(kw.lower() in probe_text.lower() for kw in kws):
                interaction = model
                break
    if interaction == "纯提示词型" and has_tools_dir:
        interaction = "脚本工具型"

    # 生命周期状态：开发中 > 活跃维护 > 维护停滞
    if os.path.isfile(os.path.join(skill_dir, "_design.md")) or \
            os.path.isfile(os.path.join(skill_dir, "设计需求文档.md")):
        lifecycle = "开发中"
    elif skill.get("has_changelog"):
        lifecycle = "活跃维护"
    else:
        lifecycle = "维护停滞"

    return {
        "name": name,
        # 功能域：静态提示 + 证据；domain_final 由 02-classifier-agent 语义判定后回填
        "domain_hint": domain_hint,
        "domain_evidence": domain_evidence,
        "domain_final": None,
        "interaction": interaction,
        "lifecycle": lifecycle,
    }


# 停用 bigram（模板词/高频泛词，交集不算触发面重叠）
STOP_BIGRAMS = {
    "不适", "适用", "场景", "不要", "调用", "单次", "简单", "问答", "编码",
    "任务", "进行", "相关", "主要", "包含", "通过", "支持", "一个", "我们",
    "可以", "需要", "以及", "或者", "对于", "这个", "当前", "其他", "使用",
    "系统", "所有", "并且", "一种", "两个", "方式", "方法", "内容", "信息",
    "基于", "实现", "完成", "产出", "结果", "过程",
    # 高频泛词（作为交集信号过于宽泛，易造成跨功能域误报）
    "分析", "文档", "流程", "用户", "状态", "完整", "核心", "报告", "问题",
    "自动", "定义", "结构", "修复", "创建", "方案", "描述", "现有", "逻辑",
    "路径", "概念", "审核", "检测", "骨架", "上下", "下文", "文膨", "膨胀",
    "久化", "持久", "构化", "渐进", "闭环", "机制", "检查", "评估", "接口",
    # 中文高频碎片与跨词 bigram（字符级双字滑窗产生的无意义片段，见 extract_keywords）
    # 实跑反馈：以下/下场/件与/么使 等碎片导致 C2 大量误报
    "以下", "下场", "件与", "么使", "时会", "以及", "并且", "还有", "然后",
    "所以", "因为", "如果", "但是", "什么", "怎么", "如何", "哪些", "这个",
    "一些", "没有", "不是", "就是", "而是", "位于", "包括", "提供", "生成",
    "输出", "输入", "处理", "管理", "控制", "操作", "基本", "重要", "本次",
    "全部", "其中", "部分", "某个", "各项", "各类", "种种", "部分", "各自",
    "互相", "相互", "之间", "方面", "层面", "情况", "时候", "之后", "之前",
    "以上", "以下", "根据", "按照", "经过", "利用", "借助", "围绕", "针对",
    "做到", "做好", "给到", "交给", "反馈", "指定", "明确", "完成", "流程",
    # 英文停用词（避免英文 description 的模板词交集噪声，如 to/use/when/not）
    "the", "and", "for", "with", "not", "use", "uses", "used", "when", "where",
    "what", "how", "to", "a", "an", "of", "in", "on", "at", "is", "are", "be",
    "can", "will", "should", "does", "do", "this", "that", "these", "those",
    "from", "by", "as", "or", "if", "then", "into", "your", "you", "user",
    "users", "skill", "skills", "agent", "agents", "baton", "harness", "produce",
    "produces", "output", "outputs", "input", "inputs", "file", "files", "create",
    "generates", "generate", "making", "make", "via", "using", "within",
}


def extract_keywords(text: str) -> set[str]:
    """
    轻量中文分词（标准库实现）：
    - 英文/数字词按原样提取（长度 ≥ 2）
    - 中文按双字 bigram 切分
    解决无空格中文整句被 \\w 贪婪匹配成一个词的问题（如无空格的长中文描述），
    同时保证同质/意图抢占比对有足够的词粒度。
    """
    kws = set()
    text_l = text.lower()
    for m in re.findall(r'[a-z0-9]+', text_l):
        if len(m) >= 2:
            kws.add(m)
    for m in re.findall(r'[\u4e00-\u9fff]+', text_l):
        if len(m) == 1:
            kws.add(m)
        else:
            for i in range(len(m) - 1):
                kws.add(m[i:i + 2])
    return kws - STOP_BIGRAMS


def build_conflict_candidates(project_root: str, inventory: list[dict]) -> dict:
    """
    五类冲突静态检测（C1~C5），全部确定性计算，不耗 LLM 上下文。
    C1/C2 基于 description 关键词；C3 基于常驻 token；C4/C5 基于共享资源引用比对。
    """
    candidates = {"C1": [], "C2": [], "C3": [], "C4": [], "C5": []}
    active = [s for s in inventory if s.get("status") == "active"]

    # --- C1/C2: description 关键词交集 + 反触发标记 ---
    # 参与比对的 Skill：active 全部 + broken 但含设计文档描述（如仅有设计文档的 Skill）
    compare_skills = [s for s in inventory
                      if s.get("status") == "active" or s.get("desc_source") == "design_doc"]
    skill_keywords = {}
    anti_trigger_map = {}
    for skill in compare_skills:
        desc = skill.get("description", "") or ""
        skill_keywords[skill["name"]] = extract_keywords(desc)
        anti_trigger_map[skill["name"]] = bool(re.search(r'不适用|不要调用|不要', desc))

    names = list(skill_keywords.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            kw_a, kw_b = skill_keywords[a], skill_keywords[b]
            if not kw_a or not kw_b:
                continue

            intersection = kw_a & kw_b
            union = kw_a | kw_b
            if not union:
                continue

            jaccard = len(intersection) / len(union)
            # C1 同质冲突：overlap 绝对显著（一方描述长稀释 jaccard 时兜底）
            # 或 overlap 可观且 jaccard 达标（阈值见集中配置）
            if len(intersection) >= C1_MIN_OVERLAP or \
                    (len(intersection) >= C1_OVERLAP_JACCARD and jaccard >= C1_MIN_JACCARD):
                candidates["C1"].append({
                    "skill_a": a, "skill_b": b, "type": "C1",
                    "jaccard": round(jaccard, 3),
                    "overlap_count": len(intersection),
                    "keywords": sorted(intersection)[:10],
                    "severity": "candidate"
                })
            elif len(intersection) >= C2_MIN_OVERLAP:
                # C2 意图抢占：非模板词交集达标且至少一方无反触发说明
                no_anti = (not anti_trigger_map.get(a, False)) or (not anti_trigger_map.get(b, False))
                if no_anti:
                    severity = "high" if len(intersection) >= C2_HIGH_OVERLAP else "medium"
                    candidates["C2"].append({
                        "skill_a": a, "skill_b": b, "type": "C2",
                        "overlap_count": len(intersection),
                        "keywords": sorted(intersection)[:10],
                        "severity": severity
                    })

    # --- C3: 上下文膨胀（常驻 token 超阈值且无 chunk 分层）---
    for skill in active:
        tokens = skill.get("tokens_est", 0) or 0
        if tokens > C3_TOKEN_THRESHOLD and not skill.get("has_chunks"):
            candidates["C3"].append({
                "skill": skill["name"], "type": "C3",
                "tokens_est": tokens, "has_chunks": False,
                "severity": "high" if tokens > C3_HIGH_TOKEN else "medium"
            })

    # --- C4: 共享引用路径 / DB / 环境变量 / baton（资源名 -> 引用它的 Skill 集合）---
    resource_owners = {}
    for skill in active:
        text = collect_skill_text(skill.get("path") or "")
        # baton 文件：行级排除否定语境（"不用/不与…冲突/改用"等）
        for line in text.split('\n'):
            if re.search(r'[\w/\\-]*_?baton[\w-]*\.json', line) and \
                    not re.search(r'不用|不碰|不与|不读|冲突|避免|禁用|改用|替代', line):
                for m in set(re.findall(r'[\w/\\-]*_?baton[\w-]*\.json', line)):
                    resource_owners.setdefault(f"baton:{m}", set()).add(skill["name"])
        for m in set(re.findall(r'[\w-]+-config\.(?:json|yaml)|config[\w-]*\.(?:json|yaml)', text)):
            resource_owners.setdefault(f"config:{m}", set()).add(skill["name"])
        for m in extract_env_vars(text):
            resource_owners.setdefault(f"env:{m}", set()).add(skill["name"])
        # DB 表名：行级 SQL 提取（行含 SQL 关键字时才提取，避免 python import 等误报）
        for line in text.split('\n'):
            if not SQL_KEYWORD.search(line):
                continue
            for groups in SQL_TARGET.findall(line):
                for g in groups:
                    if g and g.lower() not in SQL_STOPWORDS:
                        resource_owners.setdefault(f"db:{g}", set()).add(skill["name"])
        # DB 表名（文档弱信号）：下划线式表名后跟"表/table"字样（如"xxx_table 表"），
        # 覆盖 agents/protocols 文档中的表依赖描述（如某 Skill 声明读取另一 Skill 的表）
        for m in set(re.findall(r'\b(\w+_\w+)\s*(?:表|table)\b', text, re.IGNORECASE)):
            resource_owners.setdefault(f"db:{m}", set()).add(skill["name"])
        # DB 库名：database 赋值 / db.get 默认值 / get_<db>_db_config 函数名通用提取
        for groups in DB_NAME_PATTERN.findall(text):
            for g in groups:
                if g:
                    resource_owners.setdefault(f"db:{g}", set()).add(skill["name"])
        # 共享状态/中间产物目录（启发式信号：多个 Skill 引用同一目录说明存在状态共享；
        # 该目录是常见约定，别人的环境即使没有也不影响——不命中即不报冲突）
        if HARNESS_DIR_REL.replace("\\", "/") in text.replace("\\", "/"):
            resource_owners.setdefault(f"dir:{HARNESS_DIR_REL}", set()).add(skill["name"])

    infra_shared = []
    for resource, owners in resource_owners.items():
        owners = sorted(owners)
        if len(owners) < 2:
            continue
        if len(owners) >= C4_INFRA_MIN_OWNERS:
            # 基础设施型共享（≥N Skill 引用）：不生成两两对，报告单列，避免矩阵爆炸
            infra_shared.append({
                "resource": resource, "owners": owners, "type": "C4",
                "severity": "low",
                "note": f"基础设施型共享（≥{C4_INFRA_MIN_OWNERS} 个 Skill 引用），不生成两两冲突对"
            })
            continue
        for i in range(len(owners)):
            for j in range(i + 1, len(owners)):
                candidates["C4"].append({
                    "skill_a": owners[i], "skill_b": owners[j], "type": "C4",
                    "resource": resource, "severity": "medium"
                })
    candidates["C4_infra"] = infra_shared

    # --- C5: 资源竞争（同一 MCP 工具 / 同一浏览器会话 / 同一端口）---
    # 工具名/协议名是通用技术信号（playwright/COS/CDP），非环境数据，保留精确匹配
    tool_owners = {}
    for skill in active:
        text = collect_skill_text(skill.get("path") or "")
        if re.search(r'mcp_playwright|browser_(?:navigate|click|snapshot|type|evaluate)', text):
            tool_owners.setdefault("mcp:playwright", set()).add(skill["name"])
        if re.search(r'mcp_TencentCloudCOS|putObject|getObject', text):
            tool_owners.setdefault("mcp:tencent-cos", set()).add(skill["name"])
        if re.search(r'CDP 协议|Chrome DevTools Protocol|remote-debugging|\bCDP\b', text):
            tool_owners.setdefault("resource:chrome-cdp", set()).add(skill["name"])
        for m in set(re.findall(r'端口\s*[:：]?\s*(\d{4,5})', text)):
            tool_owners.setdefault(f"port:{m}", set()).add(skill["name"])

    for resource, owners in tool_owners.items():
        owners = sorted(owners)
        if len(owners) < 2:
            continue
        for i in range(len(owners)):
            for j in range(i + 1, len(owners)):
                candidates["C5"].append({
                    "skill_a": owners[i], "skill_b": owners[j], "type": "C5",
                    "resource": resource, "severity": "medium"
                })

    return candidates


def main():
    """CLI 入口"""
    parser = argparse.ArgumentParser(description="SkillMedic 工具层")
    parser.add_argument("action", choices=[
        "scan", "analyze", "categorize", "conflict", "score", "prescribe", "diff",
        "report", "ping", "cleanup"
    ], help="操作类型")
    parser.add_argument("project_root", nargs="?", default=None, help="项目根目录（默认当前工作目录）")
    parser.add_argument("params", nargs="*", help="附加参数")
    parser.add_argument("--save", action="store_true", help="将产物落盘到 .medic/（中间产物持久化）")

    args = parser.parse_args()
    project_root = args.project_root or get_project_root()

    if args.action == "ping":
        """工具自检：检查目录可读性、依赖可用性"""
        checks = {
            "project_root_exists": os.path.isdir(project_root),
            "skills_dirs_found": len(find_skills_dirs(project_root)),
            "skills_dir_candidates": SKILLS_DIR_CANDIDATES,
            "python_version": sys.version,
        }
        checks["all_ok"] = checks["project_root_exists"] and checks["skills_dirs_found"] > 0
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return

    if args.action == "scan":
        """扫描所有 Skill（--save 落盘 _medic_inventory.json）"""
        inventory = scan_skills(project_root)
        if args.save:
            p = save_medic_json(project_root, "_medic_inventory.json", inventory)
            print(json.dumps({"saved": p, "skills_count": len(inventory)}, ensure_ascii=False))
        else:
            print(json.dumps(inventory, ensure_ascii=False, indent=2))
        return

    if args.action == "analyze":
        """分析单个 Skill"""
        if not args.params:
            print("Error: 需要指定 Skill 名称")
            sys.exit(1)
        skill_name = args.params[0]
        result = analyze_skill(project_root, skill_name)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.action == "categorize":
        """三维分类静态初值（功能域/交互模型/生命周期；--save 落盘 _medic_classify.json）"""
        inventory = scan_skills(project_root)
        results = []
        for skill in inventory:
            if skill.get("status") == "broken":
                results.append({
                    "name": skill["name"], "status": "broken",
                    "broken_reason": skill.get("broken_reason")
                })
                continue
            results.append(classify_skill(skill, project_root))
        if args.save:
            p = save_medic_json(project_root, "_medic_classify.json", results)
            print(json.dumps({"saved": p, "skills_count": len(results)}, ensure_ascii=False))
        else:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if args.action == "conflict":
        """五类冲突静态候选（C1~C5；--save 落盘 _medic_conflicts.json）"""
        inventory = scan_skills(project_root)
        candidates = build_conflict_candidates(project_root, inventory)
        if args.save:
            p = save_medic_json(project_root, "_medic_conflicts.json", candidates)
            print(json.dumps({"saved": p, "conflict_candidates": sum(
                len(v) for k, v in candidates.items() if k != "C4_infra")}, ensure_ascii=False))
        else:
            print(json.dumps(candidates, ensure_ascii=False, indent=2))
        return

    if args.action == "score":
        """输出单个 Skill 的八维静态证据信号（--save 合并落盘 _medic_scores.json）"""
        if not args.params:
            print("Error: 需要指定 Skill 名称")
            sys.exit(1)
        skill_name = args.params[0]
        # 兼容路径入参：传 skills/xbrowser 或完整 path 时取 basename 匹配（与 scan 输出对齐）
        base = os.path.basename(skill_name.rstrip("/\\"))
        inventory = scan_skills(project_root)
        skill = next((s for s in inventory if s["name"] == base), None)
        if not skill:
            print(json.dumps({"name": skill_name,
                              "error": "未找到该 Skill（请用 scan 输出的 Skill 目录名）"}, ensure_ascii=False))
            return
        signals = static_score_signals(skill)
        if args.save:
            # 合并写入（同一批多次 score 累积到 _medic_scores.json）
            path = os.path.join(medic_dir(project_root), "_medic_scores.json")
            scores = {}
            if os.path.isfile(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        scores = json.load(f)
                except Exception:
                    scores = {}
            scores[skill_name] = signals
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(scores, f, ensure_ascii=False, indent=2)
            print(json.dumps({"saved": path, "skills": list(scores.keys())}, ensure_ascii=False))
        else:
            print(json.dumps(signals, ensure_ascii=False, indent=2))
        return

    if args.action == "prescribe":
        """规则处方候选（MED_RX；--save 落盘 _medic_rx.json）"""
        inventory = scan_skills(project_root)
        conflicts = build_conflict_candidates(project_root, inventory)
        rx = build_prescriptions(project_root, inventory, conflicts)
        if args.save:
            p = save_medic_json(project_root, "_medic_rx.json", rx)
            print(json.dumps({"saved": p, "prescriptions": len(rx)}, ensure_ascii=False))
        else:
            print(json.dumps(rx, ensure_ascii=False, indent=2))
        return

    if args.action == "diff":
        """增量差异对比：对比上次清单"""
        if not args.params:
            print("Error: 需要指定上次清单文件路径")
            sys.exit(1)
        last_inventory_path = args.params[0]
        current = scan_skills(project_root)
        try:
            with open(last_inventory_path, 'r', encoding='utf-8') as f:
                last = json.load(f)
        except Exception as e:
            print(json.dumps({"error": f"读取上次清单失败: {e}"}))
            return

        last_names = {s["name"] for s in last if isinstance(s, dict)}
        current_names = {s["name"] for s in current if isinstance(s, dict)}

        diff = {
            "added": list(current_names - last_names),
            "removed": list(last_names - current_names),
            "changed": [],
        }
        # 检查 mtime 变化
        for s in current:
            if s.get("name") in last_names:
                last_skill = next((x for x in last if x.get("name") == s["name"]), None)
                if last_skill and s.get("tokens_est") != last_skill.get("tokens_est"):
                    diff["changed"].append(s["name"])
        print(json.dumps(diff, ensure_ascii=False, indent=2))
        return

    if args.action == "report":
        """装配并落盘 Skill 检查报告（静态部分），同时落盘本次清单供增量/历史对比"""
        inventory = scan_skills(project_root)
        classify = [classify_skill(s, project_root)
                    for s in inventory if s.get("status") == "active"]
        conflicts = build_conflict_candidates(project_root, inventory)
        rx = build_prescriptions(project_root, inventory, conflicts)
        content = build_report(project_root, inventory, classify, conflicts, rx)

        report_dir = medic_dir(project_root)
        ts_file = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(report_dir, f"skill_audit_report_{ts_file}.md")
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(content)

        # 落盘本次清单（增量模式 diff 与历史对比的基础）
        inv_path = os.path.join(report_dir, "_medic_inventory.json")
        with open(inv_path, 'w', encoding='utf-8') as f:
            json.dump(inventory, f, ensure_ascii=False, indent=2)

        conflict_count = sum(len(v) for k, v in conflicts.items() if k != "C4_infra")
        print(json.dumps({
            "report_path": report_path,
            "inventory_path": inv_path,
            "skills_count": len(inventory),
            "conflict_candidates": conflict_count,
            "prescriptions": len(rx),
        }, ensure_ascii=False))
        return

    if args.action == "cleanup":
        """清理本次会话的临时中间产物（保留清单与历史报告——它们是增量模式与历史对比的基础）"""
        report_dir = medic_dir(project_root)
        cleaned = []
        for f in os.listdir(report_dir):
            # 只清理临时中间产物：classify/conflicts/scores/rx（_medic_ 前缀且非 inventory）
            if f.startswith("_medic_") and f != "_medic_inventory.json":
                fpath = os.path.join(report_dir, f)
                os.remove(fpath)
                cleaned.append(f)
        # _medic_inventory.json 与 skill_audit_report_* 是历史资产，MED_CLOSE 后保留供下次审计对比
        print(json.dumps({"cleaned": cleaned, "count": len(cleaned),
                          "kept": ["_medic_inventory.json", "skill_audit_report_*.md"]}, ensure_ascii=False))
        return


if __name__ == "__main__":
    main()