"""
medic_tools - SkillMedic 工具层 CLI

用法:
    python run.py scan <project_root> [--save] [--scope workspace|global] [--extra-dir <path>...]  # 列出所有 Skill 目录（--save 落盘 _medic_inventory.json；--scope 限定范围；--extra-dir 追加自定义目录）
    python run.py analyze <project_root> <skill>      # 静态指标分析（skill 支持路径或目录名）
    python run.py categorize <project_root> [--save]  # 三维分类静态初值
    python run.py conflict <project_root> [--save]   # 静态冲突候选
    python run.py score <project_root> <skill> [--save]  # 静态指标输出（skill 支持路径或目录名）
    python run.py prescribe <project_root> [--save]   # 规则处方候选
    python run.py diff <project_root> [last_inventory]  # 增量差异对比（缺省用 _medic_last_inventory.json）
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
import shutil
import sys
import math
import re
from collections import defaultdict
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
C2_CROSS_MIN_OVERLAP = 8     # 意图抢占：跨功能域对需更高交集（不同域抢占信号要更强）
C2_CROSS_MIN_JACCARD = 0.15  # 意图抢占：跨功能域对需满足的 Jaccard 下限
C1_TOP_K_PER_DOMAIN = 15     # C1/C2 共用：每功能域每类型最多保留 Top-K 组（C1 按 Jaccard、C2 按交集数降序，防候选爆炸）
C3_TOKEN_THRESHOLD = 8000    # 上下文膨胀：常驻 token 阈值（且无 chunk 分层）
C3_HIGH_TOKEN = 30000        # 上下文膨胀：高严重度阈值
C4_INFRA_MIN_OWNERS = 4      # 依赖冲突：基础设施型共享（≥N Skill 引用则聚合单列，避免矩阵爆炸）
C4_MTIME_DIFF_SEC = 86400 * 7  # 依赖冲突：双方实现 mtime 差异 >7 天 → 高严重度（一方改动未同步）

# 摘要模式与附录（§6.2.1 规模分级策略）：活跃 Skill 数超过 S2 上限（80）时进入摘要模式，
# 完整清单/分类/冲突/评分/处方按功能域拆多份附录，避免单份报告撑爆上下文（百级 Skill 场景）
REPORT_TOP_CONFLICTS = 20      # 摘要模式（S3/S4）下主报告保留的冲突条数（按严重度高→低取前 N）
REPORT_TOP_RX = 30             # 摘要模式（S3/S4）下主报告保留的处方条数（按严重度高→低取前 N）

# 规模档位（§6.2.1 分级策略：少则精、多则省——不同数量级用不同分析深度，不笼统套一套方案）
SCALE_S1_MAX = 20              # S1 精细：活跃 ≤20 → 全量冲突候选、完整报告、逐冲突核对
SCALE_S2_MAX = 80              # S2 标准：21~80 → 全量冲突候选、完整报告、分批精析（摘要模式的阈值边界）
SCALE_S3_MAX = 300             # S3 摘要：81~300 → 每域 Top-K=15、摘要报告 + 每域附录
SCALE_S4_TOP_K = 10            # S4 极限：>300 → 每域 Top-K 收紧到 10、摘要 + 附录 + 处方聚合

# token 估算公式（§9.2，固定）
TOKEN_CJK_DIV = 1.7
TOKEN_ASCII_DIV = 4


def _safe_listdir(path: str) -> list[str]:
    """目录列举兜底：权限异常/竞态删除时不中断全量扫描，返回空列表"""
    try:
        return os.listdir(path)
    except OSError:
        return []


def _safe_mtime(path: str):
    """文件修改时间兜底：读取失败返回 None（diff 会回退字符数比较）"""
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


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


def scale_of(active_count: int) -> str:
    """
    按活跃 Skill 数返回规模档位（§6.2.1 分级策略：少则精、多则省）：
    - S1 精细（≤20）：全量冲突候选、完整报告、逐冲突核对
    - S2 标准（21~80）：全量冲突候选、完整报告、分批精析
    - S3 摘要（81~300）：每域 Top-K=15、摘要报告 + 每域附录
    - S4 极限（>300）：每域 Top-K=10、摘要报告 + 附录 + 处方聚合
    """
    if active_count <= SCALE_S1_MAX:
        return "S1"
    if active_count <= SCALE_S2_MAX:
        return "S2"
    if active_count <= SCALE_S3_MAX:
        return "S3"
    return "S4"


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


# 单个 SKILL.md 最大读取字节（§14 风险对策：单 Skill 文本量设上限，超限截断并提示）
MAX_SKILL_MD_BYTES = 512 * 1024


def read_file_safe(filepath: str) -> tuple[str | None, str | None]:
    """
    安全读取文件，尝试 UTF-8（含 BOM）→ GBK；超大文件截断。
    返回 (content, error_message)
    """
    content = None
    for encoding in ['utf-8-sig', 'gbk']:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                raw = f.read(MAX_SKILL_MD_BYTES + 1)
                if len(raw) > MAX_SKILL_MD_BYTES:
                    content = raw[:MAX_SKILL_MD_BYTES] + "\n<!-- 内容超限，已截断 -->"
                else:
                    content = raw
                return content, None
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


def scan_skills(project_root: str, extra_dirs: list[str] | None = None) -> list[dict]:
    """
    扫描所有存在的 Skill 目录（多编辑器兼容，见 find_skills_dirs）。
    返回清单列表（不含正文全文）；同名 Skill 去重，workspace 优先，
    重复安装位置记入已收录条目的 dup_sources（供报告"重复安装"识别）。
    extra_dirs: 用户显式指定的自定义 Skill 目录（scope 标记为 custom，追加到扫描列表）。
    """
    dirs = find_skills_dirs(project_root)
    if extra_dirs:
        dirs = dirs + [(os.path.abspath(d), "custom") for d in extra_dirs]
    if not dirs:
        print(f"Warning: 未探测到任何 Skill 目录（已尝试 {SKILLS_DIR_CANDIDATES} 与全局候选）——"
              f"可能目录在别处，请以 IDE 注入的 available_skills 清单为准")
        return []

    def register(name: str, entry: dict, item_path: str, skills_dir: str, scope: str) -> str:
        """同名 Skill 注册（active 优先）：
        - 无同名：新增为主条目
        - 已有同名且新条目为 active 而旧条目为 broken：active 提升为主条目，旧 broken 位置降级记入 dup_sources
          （避免 broken 版本先收录导致可用版本被误判为"重复安装"）
        - 其余：记入已收录条目的 dup_sources（重复安装识别）
        返回 "added" / "replaced" / "dup"
        """
        for i, s in enumerate(inventory):
            if s.get("name") != name:
                continue
            if entry.get("status") == "active" and s.get("status") == "broken":
                entry.setdefault("dup_sources", []).append({
                    "path": s.get("path"),
                    "source": s.get("source"),
                    "scope": s.get("scope"),
                })
                inventory[i] = entry
                return "replaced"
            s.setdefault("dup_sources", []).append({
                "path": item_path,
                "source": rel_or_abs(skills_dir, project_root),
                "scope": scope,
            })
            return "dup"
        inventory.append(entry)
        return "added"

    inventory = []
    for skills_dir, scope in dirs:
        try:
            entries = sorted(os.listdir(skills_dir))
        except (PermissionError, OSError) as e:
            print(f"Warning: 无法读取目录 {skills_dir}：{e}（已跳过）")
            continue
        for item in entries:
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
                register(item, {
                    "name": item,
                    "path": item_path,
                    "source": rel_or_abs(skills_dir, project_root),
                    "scope": scope,
                    "description": fallback_desc,
                    "desc_source": "design_doc" if fallback_desc else None,
                    "status": "broken",
                    "broken_reason": "SKILL.md 缺失"
                }, item_path, skills_dir, scope)
                continue

            # 读取 SKILL.md（仅 frontmatter + 统计）
            content, error = read_file_safe(skill_md)
            if error:
                register(item, {
                    "name": item,
                    "path": item_path,
                    "source": rel_or_abs(skills_dir, project_root),
                    "scope": scope,
                    "status": "broken",
                    "broken_reason": error
                }, item_path, skills_dir, scope)
                continue

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
                    for entry in _safe_listdir(item_path)
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
            # 常驻加载量 = SKILL.md + load:always 的 chunk 索引（C3 上下文膨胀判定口径）
            always_load_tokens = tokens_est
            _ci_path = os.path.join(item_path, "SKILL.chunks", "chunk-index.yaml")
            if os.path.isfile(_ci_path):
                _ci_content, _ = read_file_safe(_ci_path)
                if _ci_content:
                    always_load_tokens = token_estimate(content + "\n" + _ci_content)

            register(item, {
                "name": item,
                "path": item_path,
                "source": rel_or_abs(skills_dir, project_root),
                "scope": scope,
                "description": fm.get("description", ""),
                "version": fm.get("version", ""),
                "tags": fm.get("tags", ""),
                "chars": len(content),
                "tokens_est": tokens_est,
                "always_load_tokens_est": always_load_tokens,
                "ref_files_count": ref_files_count,
                "mtime": _safe_mtime(skill_md),
                "has_frontmatter": fm["has_frontmatter"],
                "frontmatter_completeness": fm["frontmatter_completeness"],
                **dir_structure,
                "status": "active"
            }, item_path, skills_dir, scope)

    return inventory


def analyze_skill(project_root: str, skill_name: str) -> dict:
    """
    对单个 Skill 做静态指标分析。
    返回指标字典。
    """
    # 定位该 Skill：支持三种入参——绝对路径 / 相对路径 / 裸目录名（与 scan 输出的 path 兼容）
    skill_dir = None
    if os.path.isdir(skill_name):
        # 绝对路径（如 scan 输出的完整 path）或已存在的相对路径（含 skills/<skill> 形态）
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
        # 与 scan_skills 一致：SKILL.md 缺失时尝试从设计文档/README 提取 fallback 描述（参与 C1/C2 比对）
        fallback_desc = ""
        for doc_name in ["设计需求文档.md", "_design.md", "README.md"]:
            doc_path = os.path.join(skill_dir, doc_name)
            if os.path.isfile(doc_path):
                fb, _ = read_file_safe(doc_path)
                if fb:
                    fallback_desc = fb[:1200]
                    break
        return {"name": skill_name, "status": "broken", "broken_reason": "SKILL.md 缺失",
                "description": fallback_desc, "path": skill_dir,
                "desc_source": "design_doc" if fallback_desc else None}

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

    has_tools = any(has_dir(os.path.join(skill_dir, e)) for e in _safe_listdir(skill_dir) if is_tools_dir(e))
    return {
        "name": skill_name,
        "path": skill_dir,
        "status": "active",
        "chars": len(content),
        "tokens_est": token_estimate(content),
        "always_load_tokens_est": token_estimate(always_load),
        "mtime": _safe_mtime(skill_md),
        "description": fm.get("description", ""),
        "version": fm.get("version", ""),
        "tags": fm.get("tags", ""),
        "frontmatter": fm,
        "has_frontmatter": fm["has_frontmatter"],
        "frontmatter_completeness": fm["frontmatter_completeness"],
        "has_tools": has_tools,
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


def _aggregate_rx_for_large_scale(rx: list[dict]) -> list[dict]:
    """
    S4 极限模式处方聚合（>300 个 Skill 时启用）：批量同类处方合并，控制处方条目数量。
    - fix-frontmatter / maintain / fix-or-archive / slim：同类型合并为一条（targets 列出全部）
    - add-antitrigger：按 Skill 维度合并——同一 Skill 与 N 个对手抢占时聚合为一条
      （完整冲突细节保留在附录冲突表，rule 注明数量，不丢失可追溯性）
    - merge / boundary / schedule：保持逐对（涉及双方精确对象，聚合会失真）
    """
    batch_types = {"fix-frontmatter", "maintain", "fix-or-archive", "slim"}
    by_type: dict[str, list[dict]] = {}
    anti_by_skill: dict[str, list[dict]] = {}
    rest: list[dict] = []
    for r in rx:
        t = r["type"]
        if t in batch_types:
            by_type.setdefault(t, []).append(r)
        elif t == "add-antitrigger":
            for s in r.get("targets", []):
                anti_by_skill.setdefault(s, []).append(r)
        else:
            rest.append(r)
    sev_order = {"high": 0, "medium": 1, "low": 2, "candidate": 3}
    out: list[dict] = []
    for t, rs in by_type.items():
        targets = sorted({x for r in rs for x in r.get("targets", [])})
        sev = min((r.get("severity", "low") for r in rs), key=lambda s: sev_order.get(s, 9))
        # fix-or-archive 的 rule 内含各 Skill 不同的 broken_reason，聚合时逐 Skill 保留原因
        detail = "明细见附录清单表"
        if t == "fix-or-archive":
            parts = []
            for r in rs:
                reason = "未知"
                if "（" in r["rule"] and "）" in r["rule"]:
                    reason = r["rule"].split("（", 1)[1].rsplit("）", 1)[0]
                for target in r.get("targets", []):
                    parts.append(f"{target}（{reason}）")
            detail = "；".join(parts)
        out.append({
            "type": t, "severity": sev, "targets": targets, "conflict": rs[0].get("conflict"),
            "rule": rs[0]["rule"] + "（批量聚合，共 %d 个 Skill，%s）" % (len(targets), detail),
            "llm_todo": "对 targets 中每个 Skill 分别给出精确操作（文件路径 + 改动内容 + 执行方式）；聚合只压缩条目数、不压缩覆盖范围",
        })
    for s in sorted(anti_by_skill.keys(), key=str.lower):
        rs = anti_by_skill[s]
        sev = min((r.get("severity", "medium") for r in rs), key=lambda x: sev_order.get(x, 9))
        out.append({
            "type": "add-antitrigger", "severity": sev, "targets": [s], "conflict": "C2",
            "rule": "意图抢占：该 Skill 与 %d 个其他 Skill 存在抢占（冲突对见附录冲突表），补'何时不要调用'反触发说明" % len(rs),
            "llm_todo": "给出该 Skill description 的反触发改写建议（精确措辞）",
        })
    return rest + out


def build_prescriptions(project_root: str, inventory: list[dict], conflicts: dict) -> list[dict]:
    """
    基于冲突矩阵 + 静态维护信号生成**规则处方候选**（MED_RX 阶段 06-synthesizer 使用）。
    规则层只给候选与方向；精确执行指引（文件路径+改动内容+执行方式）与优先级由 LLM 完善。
    S4 极限模式（>300 个 Skill）返回前自动聚合批量同类处方。
    """
    rx = []
    active_names = {s["name"] for s in inventory if s.get("status") == "active"}

    # C1 同质冲突：保留评分高者合并评分低者（谁高谁低需 LLM 按八维评分定夺）
    # severity 继承候选初值（candidate=待确认），避免与第 5 部分冲突矩阵自相矛盾；
    # C1 高/中定级由 05-auditor 在闸门① 依据 scores.json 补齐，06 以 conflicts.json 写回版为准
    for c in conflicts.get("C1", []):
        rx.append({
            "type": "merge", "severity": c.get("severity", "candidate"),
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
            "type": "boundary", "severity": c.get("severity", "medium"),
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
        if not s.get("has_frontmatter") or s.get("frontmatter_completeness", 1) < 1:
            rx.append({
                "type": "fix-frontmatter", "severity": "medium",
                "targets": [name], "conflict": None,
                "rule": "frontmatter 缺失或字段不全：补全 name/description/version/tags，description 需含'何时调用+何时不要调用'",
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

    # S4 极限模式（>300 个 Skill）：批量同类处方聚合，控制处方条目数量
    if scale_of(len(active_names)) == "S4":
        rx = _aggregate_rx_for_large_scale(rx)

    return rx


def _domain_of_skill_map(classify: list[dict]) -> dict:
    """name -> 功能域映射（domain_final 优先，回退 domain_hint）。
    与 conflict 的 load_domain_map 口径一致，保证附录挂域/冲突挂域使用同一套域映射。"""
    m = {}
    for c in classify:
        if isinstance(c, dict) and c.get("name"):
            m[c["name"]] = c.get("domain_final") or c.get("domain_hint") or "未归类"
    return m


def _safe_filename(name: str) -> str:
    """文件名安全化：去掉 Windows/通用非法字符（冲突/斜杠/通配符/控制符），防路径穿越与落盘失败"""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().strip('.')
    return cleaned or "未归类"


def build_appendix_files(project_root: str, inventory: list[dict], classify: list[dict],
                         conflicts: dict, rx: list[dict], domain_map: dict) -> list[str]:
    """
    S3 摘要 / S4 极限档：把完整明细按功能域拆成多份附录（清单/分类/冲突/评分/处方），返回附录文件绝对路径列表。
    每功能域一份 `skill_audit_appendix_<域>.md`；涉及跨域冲突的组只挂到 skill_a 所属域。
    主报告（摘要模式）通过这些附录的路径引用细节，保证百级 Skill 下仍可逐域深挖。
    """
    active = [s for s in inventory if s.get("status") == "active"]
    domain_of = domain_map or _domain_of_skill_map(classify)
    # 每个 Skill 归属一个域（分类缺失归"未归类"），按域聚合清单
    by_domain = defaultdict(list)
    for s in active:
        by_domain[domain_of.get(s["name"], "未归类")].append(s)

    scope_plain = {"workspace": "项目内", "global": "全局"}
    status_plain = {"active": "正常", "broken": "损坏"}
    severity_plain = {"candidate": "待确认", "low": "低", "medium": "中", "high": "高"}
    conflict_type_plain = {
        "C1": "功能重复（C1）", "C2": "抢着响应（C2）", "C3": "占资源（C3）",
        "C4": "共享依赖（C4）", "C5": "抢工具（C5）",
    }
    rx_type_plain = {
        "merge": "合并重复", "add-antitrigger": "补'何时不要调用'", "boundary": "划清边界",
        "schedule": "明确分工顺序", "slim": "瘦身", "maintain": "补维护文档",
        "fix-frontmatter": "修复 Skill 说明信息", "fix-or-archive": "修复或归档",
    }
    rx_sev_plain = {"high": "高", "medium": "中", "low": "低", "candidate": "待确认"}
    c_map = {c["name"]: c for c in classify}
    pair_rows = (conflicts.get("C1", []) + conflicts.get("C2", []) +
                 conflicts.get("C4", []) + conflicts.get("C5", []))
    # 冲突挂域：按双方各自域各挂一次（跨域对在双方域附录都可见，保证 skill_b 侧可追溯）；
    # 同域对只挂一次（set 去重，避免同一域内重复）
    conflicts_by_domain = defaultdict(list)
    for c in pair_rows:
        da = domain_of.get(c.get("skill_a"), "未归类")
        db = domain_of.get(c.get("skill_b"), "未归类")
        for dom in sorted({da, db}):
            conflicts_by_domain[dom].append(c)
    # 处方挂域：聚合条目（跨多域）在**每个命中域**都挂载（rule 已注明是批量聚合，不重复计数）；
    # 未命中任何域的（含 broken 的 fix-or-archive）归"未归类"
    rx_by_domain = defaultdict(list)
    for r in rx:
        hit_doms = sorted({domain_of.get(t, "未归类") for t in r.get("targets", [])})
        for dom in (hit_doms or ["未归类"]):
            rx_by_domain[dom].append(r)

    # 附录域集合 = 有 Skill 的域 ∪ 有处方/冲突的域（确保 broken 处方等不因无清单域而整体丢失）
    all_doms = set(by_domain.keys()) | set(rx_by_domain.keys()) | set(conflicts_by_domain.keys())

    appendix_paths = []
    for dom in sorted(all_doms, key=str.lower):
        skills = by_domain.get(dom, [])
        A = []
        A.append(f"# Skill 检查报告附录：{dom}\n")
        A.append(f"- 功能域：{dom}（共 {len(skills)} 个 Skill）")
        A.append("- 本附录为摘要/极限档（活跃 Skill > %d）下主报告的完整明细，供按域深挖；主报告只保留摘要与 Top 冲突。\n" % SCALE_S2_MAX)

        # 清单表
        A.append("## 清单表\n")
        A.append("| Skill | 状态 | 所在位置 | 估算 Token | 版本 | 结构(多角色/分块/工具/协议) |")
        A.append("|-------|------|---------|-----------|------|---------------------------|")
        for s in sorted(skills, key=lambda x: x["name"]):
            struct = "".join("✓" if s.get(k) else "·" for k in ["has_agents", "has_chunks", "has_tools", "has_protocols"])
            A.append(f"| {s['name']} | {status_plain.get(s.get('status'), s.get('status'))} | "
                     f"{scope_plain.get(s.get('scope'), s.get('scope'))} | {s.get('tokens_est', 'N/A')} | "
                     f"{s.get('version') or '-'} | {struct} |")
        A.append("")

        # 分类表
        A.append("## 分类表\n")
        A.append("| Skill | 用途分组 | 交互方式 | 维护状态 |")
        A.append("|-------|-----------|---------|---------|")
        for s in sorted(skills, key=lambda x: x["name"]):
            c = c_map.get(s["name"], {})
            A.append(f"| {s['name']} | {c.get('domain_final') or c.get('domain_hint') or '未归类'} | {c.get('interaction') or '-'} | {c.get('lifecycle') or '-'} |")
        A.append("")

        # 冲突（挂到本域的组）
        dom_conflicts = conflicts_by_domain.get(dom, [])
        A.append("## 冲突与问题\n")
        if dom_conflicts:
            A.append("| A × B | 冲突类型 | 冲突点/资源 | 初判严重度 | 影响你什么 |")
            A.append("|-------|---------|------------|-----------|-----------|")
            for c in dom_conflicts:
                a, b = c.get("skill_a", c.get("skill", "")), c.get("skill_b", "")
                res = c.get("resource") or c.get("keywords") or c.get("jaccard") or ""
                if isinstance(res, list):
                    res = ",".join(str(x) for x in res[:5])
                t = conflict_type_plain.get(c.get("type"), c.get("type"))
                sev = severity_plain.get(c.get("severity"), c.get("severity", "待确认"))
                A.append(f"| {a} × {b} | {t} | {res} | {sev} | |")
        else:
            A.append("- 无冲突候选")
        for c in conflicts.get("C3", []):
            if domain_of.get(c.get("skill"), "未归类") == dom:
                A.append(f"- 占资源（C3）：{c['skill']}（常驻 token {c['tokens_est']}，无分块）→ 每次对话加载较多说明，可能拖慢响应")
        A.append("")

        # 评分明细
        A.append("## 评分明细\n")
        A.append("> 数字 = 该维度机器统计的证据数（越多说明写得越充分，专业参考用）；"
                 "'通俗评估'列由 AI 复核后回填。'内容价值'维度由 AI 语义评判，不在表中。\n")
        A.append("| Skill | 触发说明 | 流程步骤 | 异常处理 | 产出检查 | 边界约束 | 工程配套 | 维护痕迹 | 通俗评估 |")
        A.append("|-------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|-----------------|")
        for s in sorted(skills, key=lambda x: x["name"]):
            sig = static_score_signals(s)
            A.append(f"| {s['name']} | {len(sig['dim1_trigger'])} | {len(sig['dim2_flow'])} | "
                     f"{len(sig['dim3_exception'])} | {len(sig['dim4_output'])} | "
                     f"{len(sig['dim5_boundary']['hits'])} | "
                     f"{sum(1 for v in sig['dim7_engineering'].values() if v)}/4 | "
                     f"{sum(1 for v in sig['dim8_maintain'].values() if v)}/3 | |")
        A.append("")

        # 处方（挂到本域的）
        dom_rx = rx_by_domain.get(dom, [])
        A.append("## 改造建议（处方候选）\n")
        if dom_rx:
            rx_sorted = sorted(dom_rx, key=lambda r: {"high": 0, "medium": 1, "low": 2}.get(r.get("severity"), 3))
            A.append("| 优先级 | 建议方向 | 对象 | 依据 | 精确操作 |")
            A.append("|:---:|----------|------|------|----------|")
            for r in rx_sorted:
                t = rx_type_plain.get(r['type'], r['type'])
                sev = rx_sev_plain.get(r.get("severity"), r.get("severity") or "-")
                A.append(f"| {sev} | {t} | {', '.join(r['targets'])} | {r['rule']} | |")
            A.append("\n> '精确操作'列由 07-reporter 逐域回填：聚合处方须对 targets 中**每个 Skill**分别给出"
                     "文件路径 + 改动内容 + 执行方式（S4 聚合只压缩条目数、不压缩覆盖范围）。")
        else:
            A.append("- 无改造建议候选")
        A.append("\n---\n")
        A.append("*本附录由 SkillMedic 自动生成，属主报告的完整明细分卷。*")

        appendix_dir = medic_dir(project_root)
        ap_path = os.path.join(appendix_dir, f"skill_audit_appendix_{_safe_filename(dom)}.md")
        with open(ap_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(A))
        appendix_paths.append(ap_path)

    return appendix_paths


def build_report(project_root: str, inventory: list[dict], classify: list[dict],
                 conflicts: dict, rx: list[dict]) -> tuple[str, list[str]]:
    """
    装配 Skill 检查报告（静态可得的全部部分：元信息/总览/清单/分类/冲突/评分信号/处方/历史/标准）。
    一句话总结、评分、冲突影响、行动建议等 LLM 产物以"回填区"占位，由 07-reporter 在 MED_DEBRIEF 完善。
    报告面向普通用户：专业术语只作括号备注，主表达用日常语言。
    分级策略（§6.2.1 scale_of）：S1 精细 / S2 标准 → 完整报告（全量明细）；
    S3 摘要 / S4 极限 → 主报告只保留摘要 + Top 冲突/处方，完整明细按功能域拆附录，
    返回 (主报告内容, 附录文件路径列表)。
    """
    now = datetime.now()
    L = []
    active = [s for s in inventory if s.get("status") == "active"]
    broken = [s for s in inventory if s.get("status") == "broken"]
    scale = scale_of(len(active))
    large_mode = scale in ("S3", "S4")
    # 附录文件（S3/S4 摘要档生成；S1/S2 小报告返回空列表）
    appendix_files: list[str] = []

    # 0 元信息
    L.append("# Skill 检查报告\n")
    L.append(f"- **生成时间**：{now.strftime('%Y-%m-%d %H:%M:%S')}")
    L.append(f"- **扫描范围**：项目内（workspace）候选 {SKILLS_DIR_CANDIDATES}；全局候选 {GLOBAL_SKILLS_DIRS}（探测不到不阻断）")
    L.append("- **评分标准版本**：8-axis-v0.1（内置基线，可联网更新）")
    L.append(f"- **异常 Skill（损坏/不可读）**：{len(broken)} 个（未评分）")
    scale_plain = {
        "S1": "精细模式（≤20 个：全量候选、完整报告、逐冲突核对）",
        "S2": "标准模式（21~80 个：全量候选、完整报告、分批精析）",
        "S3": "摘要模式（81~300 个：候选按域 Top-15 降噪、主报告摘要 + 每域附录）",
        "S4": "极限模式（>300 个：候选按域 Top-10 降噪、处方聚合、主报告摘要 + 每域附录）",
    }
    # scale_plain 自带括号说明，直接拼接避免双重括号（如 "S1（精细模式（≤20 个…））"）
    L.append(f"- **规模档位**：{scale} {scale_plain[scale]}")
    if large_mode:
        L.append(f"- **报告模式**：摘要模式（活跃 Skill {len(active)} 个，超过 {SCALE_S2_MAX} 阈值）——"
                 "主报告只保留摘要与 Top 冲突/处方，完整清单/分类/冲突/评分/处方按功能域拆分见第 3 部分末尾的附录文件列表")
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

    # 1 给你的结论（人话版汇报层；AI 回填）
    # 铁律：AI 回填后必须删除全部 HTML 注释与占位，报告正文不得残留任何模板指导语（例：/LLM 回填/AI 回填/回填区）
    L.append("## 1. 给你的结论\n")
    L.append("<!-- AI 回填：用一两句大白话总结——装了几个 Skill / 几个放心用 / 几个要注意 / 几个不建议用；发现了什么大问题。"
             "汇报层必须从第 5 部分冲突矩阵、第 6 部分评分表推导，禁止另写一套分布。回填后删除本注释。 -->\n")
    L.append("### 1.1 健康度总评\n")
    L.append("<!-- AI 回填：① 总评一句话（如\"你装了 11 个 Skill，整体不错：3 个放心用、7 个基本能用、1 个不太成熟\"）；"
             "② 分级名单逐个点名，与第 6 部分评分表逐项一致，没有的档写\"无\"。回填后删除本注释。 -->")
    L.append("- 健康度分布：放心用（L3）｜基本能用（L2）｜不太成熟（L1）｜不建议用（L0）")
    L.append("- 分级名单：")
    L.append("  - 放心用（L3）：")
    L.append("  - 基本能用（L2）：")
    L.append("  - 不太成熟（L1）：")
    L.append("  - 不建议用（L0）：")
    names = sorted((s["name"] for s in active), key=str.lower)
    names_str = ("、".join(names[:15]) + ("…等共" + str(len(active)) + " 个" if len(names) > 15 else "")) if names else "无"
    L.append(f"- 本次检查范围：{len(active)} 个 Skill（{names_str}）\n")
    L.append("### 1.2 最需要注意的问题（TOP 榜，3~5 条）\n")
    L.append("<!-- AI 回填：列 3~5 条最要紧的问题，每条 = 问题一句话 / 影响你什么（日常语言）/ 建议怎么办（使用层面）。回填后删除本注释。 -->")
    L.append("| # | 问题 | 影响你什么 | 建议怎么办 |")
    L.append("|---|------|-----------|-----------|\n")
    L.append("### 1.3 你现在最该做的 2~3 件事（如果你是使用者）\n")
    L.append("<!-- AI 回填：从 7.1 使用建议挑 2~3 条最优先的（不用改文件就能照做的）。回填后删除本注释。 -->")
    L.append("- 1) \n- 2) \n- 3) \n")

    # 2 总览
    L.append("## 2. 总览\n")
    # 常驻口径（SKILL.md + load:always chunk 索引）与 C3 判定一致；旧清单无该字段回退单体 tokens_est
    tokens = [s.get("always_load_tokens_est") or s.get("tokens_est", 0) or 0 for s in active]
    avg_tok = sum(tokens) / len(tokens) if tokens else 0
    domain_count = {}
    for c in classify:
        d = c.get("domain_final") or c.get("domain_hint") or "未归类"
        domain_count[d] = domain_count.get(d, 0) + 1
    L.append(f"- Skill 总数：{len(inventory)}（活跃 {len(active)} / 异常 {len(broken)}）")
    L.append(f"- 常驻估算 token：平均 {avg_tok:.0f} / 最大 {max(tokens) if tokens else 0}")
    L.append("- 功能域分布（静态提示）：" + "；".join(f"{k}×{v}" for k, v in sorted(domain_count.items(), key=lambda x: -x[1])))
    L.append("<!-- AI 回填：健康度分布条，与第 1.1 节和第 6 部分一致。回填后删除本注释。 -->")
    L.append("- 健康度分布：放心用（L3）｜基本能用（L2）｜不太成熟（L1）｜不建议用（L0）\n")

    # 3 清单表
    L.append("## 3. 清单表\n")
    domain_of = _domain_of_skill_map(classify)
    if large_mode:
        # S3/S4 摘要档：只输出按功能域聚合的摘要 + 附录指引，完整清单见附录
        by_domain = defaultdict(list)
        for s in active:
            by_domain[domain_of.get(s["name"], "未归类")].append(s)
        L.append(f"- 共 {len(active)} 个活跃 Skill，按功能域聚合（完整清单/分类/评分/处方见下方附录）：")
        for dom in sorted(by_domain.keys(), key=str.lower):
            ap_rel = os.path.join(MEDIC_DIR, f"skill_audit_appendix_{_safe_filename(dom)}.md")
            L.append(f"  - {dom}：{len(by_domain[dom])} 个 → `{ap_rel}`")
        L.append("")
        # 生成附录文件（S3/S4 摘要档：主报告与附录同批落盘）
        appendix_files.extend(build_appendix_files(
            project_root, inventory, classify, conflicts, rx, domain_of))
        L.append("**附录文件列表（完整明细，按功能域拆分）**：")
        for ap in appendix_files:
            L.append(f"- `{rel_or_abs(ap, project_root)}`")
        L.append("")
    else:
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
    L.append("## 4. 分类表\n")
    if large_mode:
        L.append(f"> 摘要模式（S3/S4 档）：完整分类明细（用途分组/交互方式/维护状态）见各功能域附录，"
                 f"主报告仅保留功能域分布——{len(active)} 个活跃 Skill 按域统计见第 2 部分总览。\n")
    else:
        L.append("| Skill | 用途分组 | 交互方式 | 维护状态 |")
        L.append("|-------|-----------|---------|---------|")
        c_map = {c["name"]: c for c in classify}
        for s in sorted(inventory, key=lambda x: x["name"]):
            c = c_map.get(s["name"], {})
            L.append(f"| {s['name']} | {c.get('domain_final') or c.get('domain_hint') or '未归类'} | {c.get('interaction') or '-'} | {c.get('lifecycle') or '-'} |")
        L.append("")

    # 5 冲突与问题（专业明细：静态候选；影响由 AI 复核）
    L.append("## 5. 冲突与问题\n")
    L.append("<!-- AI 回填：白话导读——用一句话说清\"N 组真冲突，最需要注意的是 X×Y（原因一句话）\"；模板词伪冲突不计入。回填后删除本注释。 -->\n")
    conflict_type_plain = {
        "C1": "功能重复（C1）", "C2": "抢着响应（C2）", "C3": "占资源（C3）",
        "C4": "共享依赖（C4）", "C5": "抢工具（C5）",
    }
    severity_plain = {"candidate": "待确认", "low": "低", "medium": "中", "high": "高"}
    conflict_rows = (conflicts.get("C1", []) + conflicts.get("C2", []) +
                     conflicts.get("C4", []) + conflicts.get("C5", []))
    if large_mode and conflict_rows:
        # S3/S4 摘要档：主报告只保留严重度最高（高→中→低）的前 N 组，完整冲突矩阵见附录
        sev_order = {"high": 0, "medium": 1, "low": 2, "candidate": 3}
        top_rows = sorted(conflict_rows, key=lambda c: sev_order.get(c.get("severity"), 4))[:REPORT_TOP_CONFLICTS]
        L.append(f"共 {len(conflict_rows)} 组冲突候选，以下为主报告保留的严重度最高的 {len(top_rows)} 组（完整清单见各功能域附录）：\n")
        L.append("| A × B | 冲突类型 | 冲突点/资源 | 初判严重度 | 影响你什么 |")
        L.append("|-------|---------|------------|-----------|-----------|")
        for c in top_rows:
            a, b = c.get("skill_a", c.get("skill", "")), c.get("skill_b", "")
            res = c.get("resource") or c.get("keywords") or c.get("jaccard") or ""
            if isinstance(res, list):
                res = ",".join(str(x) for x in res[:5])
            t = conflict_type_plain.get(c.get("type"), c.get("type"))
            sev = severity_plain.get(c.get("severity"), c.get("severity", "待确认"))
            L.append(f"| {a} × {b} | {t} | {res} | {sev} | |")
        L.append("\n> 说明：'冲突点/资源'含机器比对信息（专业参考），'影响你什么'列由 AI 复核后用日常语言补充；"
                 "完整冲突候选请查阅对应功能域附录。\n")
        L.append("<!-- AI 回填参考示例（供复核时对照，不写入报告）：抢着响应 → \"当你说'帮我扫描页面'时，2 个 Skill 都会响应，AI 可能随机选一个 → 结果不稳定\"；"
                 "功能重复 → \"两个 Skill 做同一件事，你不知道用哪个，建议只留一个\"；"
                 "同一 Skill 出现在两个 IDE 目录 → \"是分别安装过，建议只保留一份\"。 -->\n")
    elif conflict_rows:
        L.append("| A × B | 冲突类型 | 冲突点/资源 | 初判严重度 | 影响你什么 |")
        L.append("|-------|---------|------------|-----------|-----------|")
        for c in conflict_rows:
            a, b = c.get("skill_a", c.get("skill", "")), c.get("skill_b", "")
            res = c.get("resource") or c.get("keywords") or c.get("jaccard") or ""
            if isinstance(res, list):
                res = ",".join(str(x) for x in res[:5])
            t = conflict_type_plain.get(c.get("type"), c.get("type"))
            sev = severity_plain.get(c.get("severity"), c.get("severity", "待确认"))
            L.append(f"| {a} × {b} | {t} | {res} | {sev} | |")
        L.append("\n> 说明：'冲突点/资源'含机器比对信息（专业参考），'影响你什么'列由 AI 复核后用日常语言补充。\n")
        L.append("<!-- AI 回填参考示例（供复核时对照，不写入报告）：抢着响应 → \"当你说'帮我扫描页面'时，2 个 Skill 都会响应，AI 可能随机选一个 → 结果不稳定\"；"
                 "功能重复 → \"两个 Skill 做同一件事，你不知道用哪个，建议只留一个\"；"
                 "同一 Skill 出现在两个 IDE 目录 → \"是分别安装过，建议只保留一份\"。 -->\n")
    else:
        L.append("- 无冲突候选")
    # C3 占资源：摘要档（S3/S4）主报告只保留最严重的 Top-N（完整清单在附录）；小规模全量
    c3_rows = conflicts.get("C3", [])
    if large_mode and len(c3_rows) > REPORT_TOP_CONFLICTS:
        c3_rows = sorted(c3_rows, key=lambda c: -c.get("tokens_est", 0))[:REPORT_TOP_CONFLICTS]
        L.append(f"占资源（C3）：共 {len(conflicts.get('C3', []))} 个 Skill 超常驻阈值，主报告只列最严重的 {len(c3_rows)} 个（完整清单见各功能域附录）：")
    for c in c3_rows:
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

    # 6 评分明细（静态信号摘要；打分与通俗评估由 AI 复核）
    L.append("## 6. 评分明细\n")
    if large_mode:
        L.append(f"> 摘要模式（S3/S4 档）：完整评分明细（每 Skill 八维证据数）见各功能域附录；"
                 f"主报告仅保留健康度分布条（由 AI 回填，必须与附录评分一致）。\n")
    else:
        L.append("> 数字 = 该维度机器统计的证据数（越多说明这个 Skill 该维度写得越充分，专业参考用）；"
                 "想快速知道结果，看最后一列\"通俗评估\"即可。\"内容价值\"维度由 AI 语义评判，不在表中。\n")
        L.append("| Skill | 触发说明 | 流程步骤 | 异常处理 | 产出检查 | 边界约束 | 工程配套 | 维护痕迹 | 通俗评估 |")
        L.append("|-------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|-----------------|")
        for s in sorted(active, key=lambda x: x["name"]):
            sig = static_score_signals(s)
            L.append(f"| {s['name']} | {len(sig['dim1_trigger'])} | {len(sig['dim2_flow'])} | "
                     f"{len(sig['dim3_exception'])} | {len(sig['dim4_output'])} | "
                     f"{len(sig['dim5_boundary']['hits'])} | "
                     f"{sum(1 for v in sig['dim7_engineering'].values() if v)}/4 | "
                     f"{sum(1 for v in sig['dim8_maintain'].values() if v)}/3 | |")
        L.append("")
    L.append("<!-- AI 回填：对照八维细则给出每维分数/证据/扣分定位与定级，定级用通俗格式如\"放心用（L3）\"（映射：L3 放心用 / L2 基本能用 / L1 不太成熟 / L0 不建议用）。回填后删除本注释。 -->\n")

    # 7 行动建议（分两层：7.1 使用建议=使用者直接照做；7.2 改造建议=创建者改 Skill 文件，可选）
    L.append("## 7. 行动建议\n")
    L.append("### 7.1 使用建议（如果你是 Skill 的使用者，看这里）\n")
    L.append("> 不需要改任何文件，照着做就行。覆盖三类：**注意什么 / 有什么风险 / 什么需求别指望它**。\n")
    L.append("<!-- AI 回填：按优先级列使用建议（如\"XX 别用于正式数据（有风险）\"；\"要生成手册时用 A 而不是 B，避免两个 Skill 抢着响应\"）。回填后删除本注释。 -->\n")
    L.append("### 7.2 改造建议 —— 如果你是 Skill 的**创建者 / 维护者**，看这里\n")
    L.append("> 以下建议需要改动 Skill 文件（合并/删文档/补说明/瘦身）。**使用者可以完全跳过本节**："
             "某个 Skill 影响使用，按 7.1 使用建议规避即可；你是作者想根治，再动手改。\n")
    rx_type_plain = {
        "merge": "合并重复", "add-antitrigger": "补'何时不要调用'", "boundary": "划清边界",
        "schedule": "明确分工顺序", "slim": "瘦身", "maintain": "补维护文档",
        "fix-frontmatter": "修复 Skill 说明信息", "fix-or-archive": "修复或归档",
    }
    rx_sev_plain = {"high": "高", "medium": "中", "low": "低", "candidate": "待确认"}
    if rx:
        # 按严重度排序（高→中→低），同一级别内保持原顺序
        rx_sorted = sorted(rx, key=lambda r: {"high": 0, "medium": 1, "low": 2}.get(r.get("severity"), 3))
        if large_mode:
            top_rx = rx_sorted[:REPORT_TOP_RX]
            L.append(f"共 {len(rx_sorted)} 条处方候选，以下为主报告保留的优先级最高的 {len(top_rx)} 条（完整处方见各功能域附录）：\n")
            rx_sorted = top_rx
        L.append("| 优先级 | 建议方向 | 对象 | 依据 |")
        L.append("|:---:|----------|------|------|")
        for r in rx_sorted:
            t = rx_type_plain.get(r['type'], r['type'])
            sev = rx_sev_plain.get(r.get("severity"), r.get("severity") or "-")
            L.append(f"| {sev} | {t} | {', '.join(r['targets'])} | {r['rule']} |")
        L.append("<!-- AI 回填：在 7.2 表格基础上输出\"现在建议你做什么\"（先处理\"高\"优先级），并为每条补精确操作（文件路径 + 改动内容 + 执行方式）；\"是否执行\"由用户/作者决定。回填后删除本注释。 -->\n")
    else:
        L.append("- 无改造建议候选")
    L.append("")

    # 8 历史对比
    L.append("## 8. 历史对比\n")
    last_inv = os.path.join(medic_dir(project_root), "_medic_last_inventory.json")
    if os.path.isfile(last_inv):
        try:
            with open(last_inv, 'r', encoding='utf-8') as f:
                last = json.load(f)
            cur = {s["name"] for s in inventory}
            prev = {s["name"] for s in last if isinstance(s, dict)}
            L.append(f"- 新增 Skill：{sorted(cur - prev) if cur - prev else '无'}")
            L.append(f"- 消失 Skill：{sorted(prev - cur) if prev - cur else '无'}")
            L.append("<!-- 历史洞察：上次的问题解决了吗？覆盖三要素——① 成熟度变化（升级/降级/新增/修复）② 冲突新增与缓解（上期冲突是否仍在/新增哪些）③ 上期处方执行核对（prescriptions_outstanding 落地情况）。回填后删除本注释，无对应内容写'无'。 -->")
        except Exception as e:
            L.append(f"- 读取上次清单失败：{e}")
    else:
        L.append("- 首次审计（无上次清单）")
    L.append("")

    # 9 标准对照
    L.append("## 9. 标准对照表\n")
    L.append("- 当前 rubric：8-axis-v0.1（内置基线，2026-08-04）")
    L.append("- 定级规则（固定阈值，引用 chunk-05，禁止自创）：L3≥80 ｜ L2 55~79 ｜ L1 30~54 ｜ L0<30")
    L.append("- 联网更新：未触发（用户未要求 / 版本未过期 / 非首次执行）。触发条件见 chunk-08")

    L.append("\n---\n")
    L.append("*本报告由 SkillMedic 自动生成；结论、评分定级与行动建议由 AI 结合完整检查流程输出。*")
    return "\n".join(L), appendix_files


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
    收集 Skill 的"实现声明"文本（工具层 py + SKILL.md + agents/protocols + references/mcp-reference.md），
    用于静态资源引用比对。工具层 py 排在最前并优先保留——它是 C4/C5 核心信号源（CDP/Playwright/COS/端口），
    若被 SKILL.md 长正文挤到截断区会导致大 Skill 的资源冲突静默漏报。
    注意：不读 references 其他文件与 SKILL.chunks——那些是知识/示例材料，
    其中的"CDP/Playwright"等词是说明文字，会被误判为资源声明（如本 Skill 的 conflict-catalog）。
    """
    tool_texts: list[str] = []
    body_texts: list[str] = []

    # 工具层 py 文件（只读前 300 行，避免把整个实现读入）——优先保留，放最前
    # 识别任意 <skill>_tools / tools 目录（is_tools_dir 泛化，不依赖具体 Skill 名）
    # 注意：跳过 medic_tools 自身——检测器代码天然包含所有关键字（playwright/CDP/aitest），
    # 读入会造成自引用误报（如本 Skill 的 run.py）
    if os.path.isdir(skill_dir):
        for entry in sorted(_safe_listdir(skill_dir)):
            if not is_tools_dir(entry) or entry == "medic_tools":
                continue
            tp = os.path.join(skill_dir, entry)
            if not os.path.isdir(tp):
                continue
            try:
                tool_files = os.listdir(tp)
            except OSError as e:
                print(f"Warning: 无法读取工具目录 {tp}：{e}（跳过该工具目录的 C4/C5 比对）")
                continue
            for f in tool_files:
                if f.endswith(".py") and f != "__init__.py":
                    fp = os.path.join(tp, f)
                    try:
                        with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                            tool_texts.append("\n".join(fh.readlines()[:300]))
                    except Exception as e:
                        print(f"Warning: 读取 {fp} 失败（跳过该工具文件）: {e}")

    skill_md = os.path.join(skill_dir, "SKILL.md")
    if os.path.isfile(skill_md):
        content, _ = read_file_safe(skill_md)
        if content:
            body_texts.append(content)

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
                            body_texts.append(content)

    # 仅 mcp-reference.md 属于资源声明，纳入比对
    mcp_ref = os.path.join(skill_dir, "references", "mcp-reference.md")
    if os.path.isfile(mcp_ref):
        content, _ = read_file_safe(mcp_ref)
        if content:
            body_texts.append(content)

    # 截断优先级：工具层在前（C4/C5 核心信号源），正文在后——超限时优先截正文
    tool_part = "\n".join(tool_texts)
    body_part = "\n".join(body_texts)
    if len(tool_part) >= max_chars:
        return tool_part[:max_chars]
    return tool_part + "\n" + body_part[: max_chars - len(tool_part)]


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
        for entry in _safe_listdir(skill_dir)
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

    # 生命周期状态（chunk-03 五类；active 有 SKILL.md 才进入 classify）：
    # 有 CHANGELOG = 活跃维护（版本迭代痕迹，优先于"仅有设计稿"的"开发中"）；
    # 仅设计稿 = 开发中；两者皆无 = 维护停滞；
    # "备份归档"（仅 zip）在 scan 层即跳过、"已发布"（全局同步）由 01 合并时从 available_skills 标注，静态 classify 不产出
    if skill.get("has_changelog"):
        lifecycle = "活跃维护"
    elif os.path.isfile(os.path.join(skill_dir, "_design.md")) or \
            os.path.isfile(os.path.join(skill_dir, "设计需求文档.md")):
        lifecycle = "开发中"
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


def load_domain_map(project_root: str) -> dict:
    """读取 `.medic/_medic_classify.json` 的 domain_final（LLM 已回填）/domain_hint 构建 name->domain 映射。
    文件不存在或损坏返回空 dict（conflict 退化为全同域比对）。"""
    p = os.path.join(medic_dir(project_root), "_medic_classify.json")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, list):
        return {}
    m = {}
    for e in data:
        if isinstance(e, dict) and e.get("name"):
            m[e["name"]] = e.get("domain_final") or e.get("domain_hint") or "未归类"
    return m


def load_classify_merged(project_root: str, inventory: list[dict]) -> list[dict]:
    """
    读取 `.medic/_medic_classify.json` 的 LLM 回填版分类（domain_final/interaction/lifecycle），
    与本次 scan 的 inventory 合并：磁盘回填条目优先（按 name），未回填的 active Skill 现场重算静态初值。
    返回与 report 第 4 部分 / 附录分类表 / 附录挂域同源的分类列表——
    与 conflict 的 load_domain_map 共用同一套 domain_final 口径，避免"附录挂域用静态初值、
    冲突判定用回填值"的分裂（§6.2.1）。文件不存在或损坏时全部现场重算（退化为静态初值）。
    """
    disk = {}
    p = os.path.join(medic_dir(project_root), "_medic_classify.json")
    if os.path.isfile(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                for e in data:
                    if isinstance(e, dict) and e.get("name"):
                        disk[e["name"]] = e
        except Exception:
            disk = {}
    out = []
    for s in inventory:
        if s.get("status") != "active":
            continue
        cached = disk.get(s["name"])
        if cached and (cached.get("domain_final") or cached.get("interaction") or cached.get("lifecycle")):
            # 磁盘回填版存在且含有效回填字段：直接用（保留静态初值字段作为 fallback 来源）
            out.append(cached)
        else:
            out.append(classify_skill(s, project_root))
    return out


def load_conflicts_merged(project_root: str, inventory: list[dict]) -> dict:
    """
    读取 `.medic/_medic_conflicts.json` 的 03 写回版冲突矩阵（severity/evidence/impact 已确认、
    伪冲突已移除）；文件不存在/损坏/结构无效时现场重算静态候选（load_domain_map 退化为全同域）。
    prescribe 与 report 用此函数，保证处方目标集以写回版矩阵为准（剔除 removed_pairs、含 AI 补充对）。
    """
    p = os.path.join(medic_dir(project_root), "_medic_conflicts.json")
    if os.path.isfile(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and any(k in data for k in ("C1", "C2", "C3", "C4", "C5")):
                return data
        except Exception:
            pass
    return build_conflict_candidates(project_root, inventory, load_domain_map(project_root))


def load_rx_merged(project_root: str, inventory: list[dict], conflicts: dict) -> list[dict]:
    """
    读取 `.medic/_medic_rx.json` 的 06 写回版处方（llm_actions 已完善、severity/targets 已调整、
    含 06 依据评分补的整改/移除类处方）；文件不存在/损坏/结构无效时退化为规则候选
    build_prescriptions（仅静态规则，无 06 语义完善）。
    report 用此函数保证主报告 7.2 表与附录处方行以 06 写回版为准（与 07 回填 llm_actions 同源），
    避免"报告重算候选 vs 07 读写回版"的行集/字段失配。
    """
    p = os.path.join(medic_dir(project_root), "_medic_rx.json")
    if os.path.isfile(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return build_prescriptions(project_root, inventory, conflicts)


def _conflict_key(c_type: str, item: dict):
    """冲突条目稳定键（用于合并写回版时对位）：C1/C2 按双方集合，C3 按 Skill，C4/C5 按双方+资源。"""
    if c_type in ("C1", "C2"):
        return (c_type, frozenset([item.get("skill_a"), item.get("skill_b")]))
    if c_type == "C3":
        return (c_type, item.get("skill"))
    return (c_type, item.get("skill_a"), item.get("skill_b"), item.get("resource"))


def merge_classify_with_disk(new_results: list[dict], disk_data) -> list[dict]:
    """categorize --save 合并：把旧文件（02 已回填）的 domain_final/interaction/lifecycle/evidence 保留到新条目。
    静态初值每次重算，但 LLM 确认字段不因重跑 --save 丢失（02/05 追溯与 report 第 4 部分依赖）。"""
    if not isinstance(disk_data, list):
        return new_results
    old = {}
    for e in disk_data:
        if isinstance(e, dict) and e.get("name"):
            old[e["name"]] = e
    for item in new_results:
        prev = old.get(item.get("name"))
        if not prev:
            continue
        for field in ("domain_final", "interaction", "lifecycle", "domain_evidence", "evidence"):
            if prev.get(field) and not item.get(field):
                item[field] = prev[field]
    return new_results


def merge_conflicts_with_disk(new_candidates: dict, disk_data) -> dict:
    """conflict --save 合并：把旧文件（03/05 已确认）的 severity/evidence/impact 保留到新候选。
    静态候选每次重算，但 LLM 确认字段不因重跑 --save 丢失（打回重做后 03 只补证据不重复定级）。
    - severity：**"旧值已确认则覆盖"**——旧文件里非 candidate 的 severity（03 对 C2~C5 的定级、05 对 C1 补齐的
      高/中）视为已确认，覆盖新候选的静态初值（candidate 视为未确认占位，不覆盖）；
      C1 旧值若仍为 candidate（未定级）则不覆盖，保持新候选 candidate
    - evidence/impact：新值空缺时回填旧值（静态候选不生成这两字段）
    注意：removed_pairs（伪冲突移除）在接力棒中记录，重跑 --save 后需按该清单重新移除（见 03-agent 规则）。"""
    if not isinstance(disk_data, dict):
        return new_candidates
    old_by_key = {}
    for t, items in disk_data.items():
        if t not in ("C1", "C2", "C3", "C4", "C5"):
            continue
        for it in items:
            if isinstance(it, dict):
                old_by_key[_conflict_key(t, it)] = it
    for t, items in new_candidates.items():
        if t not in ("C1", "C2", "C3", "C4", "C5"):
            continue
        for it in items:
            prev = old_by_key.get(_conflict_key(t, it))
            if not prev:
                continue
            # severity：旧值非 candidate（已确认）优先；candidate 视为未确认不覆盖
            prev_sev = prev.get("severity")
            if prev_sev and prev_sev != "candidate":
                it["severity"] = prev_sev
            # evidence/impact：静态候选不生成，新值空缺时回填旧确认值
            for field in ("evidence", "impact"):
                if prev.get(field) and not it.get(field):
                    it[field] = prev[field]
    return new_candidates


def merge_rx_with_disk(new_rx: list[dict], disk_data) -> list[dict]:
    """prescribe --save 合并：把旧文件（06 已完善）的 llm_actions/llm_todo/priority 保留到新候选。
    06 打回重做后不丢失已写回的精确操作。"""
    if not isinstance(disk_data, list):
        return new_rx
    old_by_key = {}
    for it in disk_data:
        if isinstance(it, dict):
            old_by_key[(it.get("type"), frozenset(it.get("targets", [])))] = it
    for item in new_rx:
        prev = old_by_key.get((item.get("type"), frozenset(item.get("targets", []))))
        if not prev:
            continue
        for field in ("llm_actions", "llm_todo", "priority"):
            if prev.get(field) and not item.get(field):
                item[field] = prev[field]
    return new_rx


def build_conflict_candidates(project_root: str, inventory: list[dict], domain_map: dict | None = None) -> dict:
    """
    五类冲突静态检测（C1~C5），全部确定性计算，不耗 LLM 上下文。
    C1/C2 基于 description 关键词（同域比对 + 跨域高阈值 + 每域 Top-K，防百级 Skill 候选爆炸）；
    C3 基于常驻 token；C4/C5 基于共享资源引用比对。
    domain_map: name -> domain_final（来自 classify.json，LLM 已回填；缺省全部视为同域）。
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

    # 功能域映射（来自 MED_SORT 的 classify.json domain_final，LLM 已回填）；
    # 无映射时全部视为同域（兼容 MED_SORT 前直接跑 conflict 的场景）
    domain_of = domain_map or {}

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
            same_domain = (domain_of.get(a, "未归类") == domain_of.get(b, "未归类"))
            # C1 同质冲突：仅同功能域才可能功能同质（跨域不判）；
            # overlap 绝对显著（一方描述长稀释 jaccard 时兜底）或 overlap 可观且 jaccard 达标
            if same_domain and (len(intersection) >= C1_MIN_OVERLAP or
                                (len(intersection) >= C1_OVERLAP_JACCARD and jaccard >= C1_MIN_JACCARD)):
                candidates["C1"].append({
                    "skill_a": a, "skill_b": b, "type": "C1",
                    "jaccard": round(jaccard, 3),
                    "overlap_count": len(intersection),
                    "keywords": sorted(intersection)[:10],
                    "severity": "candidate"
                })
            else:
                # C2 意图抢占：域内交集 ≥4；跨域需更高交集 + Jaccard 下限（不同域抢占信号要更强）
                c2_hit = (len(intersection) >= C2_MIN_OVERLAP if same_domain
                          else (len(intersection) >= C2_CROSS_MIN_OVERLAP and jaccard >= C2_CROSS_MIN_JACCARD))
                no_anti = (not anti_trigger_map.get(a, False)) or (not anti_trigger_map.get(b, False))
                if c2_hit and no_anti:
                    severity = "high" if len(intersection) >= C2_HIGH_OVERLAP else "medium"
                    candidates["C2"].append({
                        "skill_a": a, "skill_b": b, "type": "C2",
                        "overlap_count": len(intersection),
                        "keywords": sorted(intersection)[:10],
                        "severity": severity
                    })

    # --- Top-K 降噪（仅 S3 摘要 / S4 极限启用；S1 精细 / S2 标准保留全部真候选，避免小规模漏报）---
    # 档位规则见 scale_of()：S3 每域每类型 Top-15，S4 收紧到 Top-10。
    # 口径统一用"活跃 Skill 数"（与 prescribe/report 一致，避免 300 边界附近档位错位）
    scale = scale_of(len(active))
    if scale in ("S3", "S4"):
        top_k = C1_TOP_K_PER_DOMAIN if scale == "S3" else SCALE_S4_TOP_K

        def _domain_of_entry(e):
            return domain_of.get(e["skill_a"], "未归类")

        _c1 = defaultdict(list)
        for e in candidates["C1"]:
            _c1[_domain_of_entry(e)].append(e)
        candidates["C1"] = []
        for _dom, _lst in _c1.items():
            _lst.sort(key=lambda e: e["jaccard"], reverse=True)
            candidates["C1"].extend(_lst[:top_k])

        _c2 = defaultdict(list)
        for e in candidates["C2"]:
            _c2[_domain_of_entry(e)].append(e)
        candidates["C2"] = []
        for _dom, _lst in _c2.items():
            _lst.sort(key=lambda e: e["overlap_count"], reverse=True)
            candidates["C2"].extend(_lst[:top_k])

    # --- C3: 上下文膨胀（常驻加载量超阈值且无 chunk 分层）---
    # 常驻口径 = SKILL.md + load:always 的 chunk 索引（always_load_tokens_est），无该字段回退单体 tokens_est
    for skill in active:
        tokens = skill.get("always_load_tokens_est") or skill.get("tokens_est", 0) or 0
        if tokens > C3_TOKEN_THRESHOLD and not skill.get("has_chunks"):
            candidates["C3"].append({
                "skill": skill["name"], "type": "C3",
                "tokens_est": tokens, "has_chunks": False,
                "severity": "high" if tokens > C3_HIGH_TOKEN else "medium"
            })

    # --- C4: 共享引用路径 / DB / 环境变量 / baton（资源名 -> 引用它的 Skill 集合）---
    # 全文收集缓存：C4/C5 共用，避免每个 Skill 重复读取实现文本
    text_cache = {}
    resource_owners = {}
    for skill in active:
        text = text_cache.setdefault(skill["name"], collect_skill_text(skill.get("path") or ""))
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

    # skill 名 -> mtime（C4 严重度"mtime 差异 → 高"判定用）
    _skill_mtime = {s.get("name"): s.get("mtime") for s in active}

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
                # 共享资源且双方实现 mtime 差异明显 → 高严重度（一方改动未同步，可能静默破坏另一方）
                _mt_a = _skill_mtime.get(owners[i])
                _mt_b = _skill_mtime.get(owners[j])
                _high = (_mt_a is not None and _mt_b is not None
                         and abs(_mt_a - _mt_b) > C4_MTIME_DIFF_SEC)
                candidates["C4"].append({
                    "skill_a": owners[i], "skill_b": owners[j], "type": "C4",
                    "resource": resource,
                    "severity": "high" if _high else "medium"
                })
    candidates["C4_infra"] = infra_shared

    # --- C5: 资源竞争（同一 MCP 工具 / 同一浏览器会话 / 同一端口）---
    # 工具名/协议名是通用技术信号（playwright/COS/CDP），非环境数据，保留精确匹配
    tool_owners = {}
    for skill in active:
        text = text_cache.setdefault(skill["name"], collect_skill_text(skill.get("path") or ""))
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
    parser.add_argument("--scope", choices=["workspace", "global"], default=None,
                        help="限定扫描范围（仅 scan 使用；缺省全部）")
    parser.add_argument("--extra-dir", action="append", default=None,
                        help="追加用户自定义 Skill 目录（仅 scan 使用，可多次传入，scope 标记为 custom）")

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
        """扫描所有 Skill（--save 落盘 _medic_inventory.json；--scope 限定 workspace/global；--extra-dir 追加自定义目录）"""
        inventory = scan_skills(project_root, args.extra_dir)
        if args.scope:
            inventory = [s for s in inventory if s.get("scope") == args.scope]
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
            # 合并写回：保留旧文件（02 已回填）的 domain_final/interaction/lifecycle，
            # 防止打回重做重跑 --save 时抹掉已确认字段
            disk_data = None
            _p = os.path.join(medic_dir(project_root), "_medic_classify.json")
            if os.path.isfile(_p):
                try:
                    with open(_p, 'r', encoding='utf-8') as f:
                        disk_data = json.load(f)
                except Exception:
                    disk_data = None
            results = merge_classify_with_disk(results, disk_data)
            p = save_medic_json(project_root, "_medic_classify.json", results)
            print(json.dumps({"saved": p, "skills_count": len(results)}, ensure_ascii=False))
        else:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if args.action == "conflict":
        """五类冲突静态候选（C1~C5；--save 落盘 _medic_conflicts.json）"""
        inventory = scan_skills(project_root)
        candidates = build_conflict_candidates(project_root, inventory, load_domain_map(project_root))
        if args.save:
            # 合并写回：保留旧文件（03/05 已确认）的 severity/evidence/impact，
            # 防止打回重做重跑 --save 时抹掉已确认字段（removed_pairs 由 03 按接力棒重新移除）
            disk_data = None
            _p = os.path.join(medic_dir(project_root), "_medic_conflicts.json")
            if os.path.isfile(_p):
                try:
                    with open(_p, 'r', encoding='utf-8') as f:
                        disk_data = json.load(f)
                except Exception:
                    disk_data = None
            candidates = merge_conflicts_with_disk(candidates, disk_data)
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
        # 兼容路径入参：传 skills/<skill> 或完整 path 时取 basename 匹配（与 scan 输出对齐）
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
                        loaded = json.load(f)
                    # 只接受 dict 结构（{skill: signals}）；list/其他结构视为损坏
                    if isinstance(loaded, dict):
                        scores = loaded
                    else:
                        raise ValueError("scores 文件结构非法（应为 dict）")
                except Exception:
                    # 损坏备份后重建，避免静默清空已累积的其他 Skill 分数
                    _bak = path + ".corrupt_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                    try:
                        os.replace(path, _bak)
                    except OSError:
                        pass
                    print(f"Warning: {path} 读取失败，已备份为 {_bak} 并重建")
                    scores = {}
            scores[base] = {**scores.get(base, {}), **signals}  # 保留既有键（含 LLM 追加的 llm_scores），不整条覆盖
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(scores, f, ensure_ascii=False, indent=2)
            print(json.dumps({"saved": path, "skills": list(scores.keys())}, ensure_ascii=False))
        else:
            print(json.dumps(signals, ensure_ascii=False, indent=2))
        return

    if args.action == "prescribe":
        """规则处方候选（MED_RX；--save 落盘 _medic_rx.json）——冲突矩阵优先读 03 写回版"""
        inventory = scan_skills(project_root)
        conflicts = load_conflicts_merged(project_root, inventory)
        rx = build_prescriptions(project_root, inventory, conflicts)
        if args.save:
            # 合并写回：保留旧文件（06 已完善）的 llm_actions/llm_todo/priority，
            # 防止打回重做重跑 --save 时抹掉已写回的精确操作
            disk_data = None
            _p = os.path.join(medic_dir(project_root), "_medic_rx.json")
            if os.path.isfile(_p):
                try:
                    with open(_p, 'r', encoding='utf-8') as f:
                        disk_data = json.load(f)
                except Exception:
                    disk_data = None
            rx = merge_rx_with_disk(rx, disk_data)
            p = save_medic_json(project_root, "_medic_rx.json", rx)
            print(json.dumps({"saved": p, "prescriptions": len(rx)}, ensure_ascii=False))
        else:
            print(json.dumps(rx, ensure_ascii=False, indent=2))
        return

    if args.action == "diff":
        """增量差异对比：对比上次清单（缺省用 .medic/_medic_last_inventory.json）"""
        if args.params:
            last_inventory_path = args.params[0]
        else:
            last_inventory_path = os.path.join(medic_dir(project_root), "_medic_last_inventory.json")
        current = scan_skills(project_root)
        try:
            with open(last_inventory_path, 'r', encoding='utf-8') as f:
                last = json.load(f)
        except FileNotFoundError:
            print(json.dumps({"error": f"未找到上次清单：{last_inventory_path}（首次审计或清单被清理）"}, ensure_ascii=False))
            return
        except Exception as e:
            print(json.dumps({"error": f"读取上次清单失败: {e}"}, ensure_ascii=False))
            return

        last_names = {s["name"] for s in last if isinstance(s, dict)}
        current_names = {s["name"] for s in current if isinstance(s, dict)}

        diff = {
            "added": list(current_names - last_names),
            "removed": list(last_names - current_names),
            "changed": [],
        }
        # 变更检测：比较 SKILL.md 修改时间（mtime）；旧清单无 mtime 字段时回退比较字符数
        for s in current:
            if s.get("name") in last_names:
                last_skill = next((x for x in last if x.get("name") == s["name"]), None)
                if not last_skill:
                    continue
                cur_mtime = s.get("mtime")
                last_mtime = last_skill.get("mtime")
                # 状态变化（active↔broken）或 mtime 变化均视为变更；
                # 任一侧 mtime 缺失（当前读取失败或旧清单无该字段）→ 回退比较字符数
                changed = (s.get("status") != last_skill.get("status"))
                if not changed and cur_mtime is not None and last_mtime is not None:
                    changed = (cur_mtime != last_mtime)
                if not changed and (last_mtime is None or cur_mtime is None):
                    changed = s.get("chars") != last_skill.get("chars")
                if changed:
                    diff["changed"].append(s["name"])
        print(json.dumps(diff, ensure_ascii=False, indent=2))
        return

    if args.action == "report":
        """装配并落盘 Skill 检查报告（静态部分），同时落盘本次清单供增量/历史对比"""
        # 归档"上次"清单：把现有 _medic_inventory.json 复制为 _medic_last_inventory.json
        # （历史对比与增量 diff 的单一数据源；本次清单随后覆盖 _medic_inventory.json）
        _inv_now = os.path.join(medic_dir(project_root), "_medic_inventory.json")
        _inv_last = os.path.join(medic_dir(project_root), "_medic_last_inventory.json")
        if os.path.isfile(_inv_now):
            try:
                shutil.copyfile(_inv_now, _inv_last)
            except OSError as e:
                print(f"Warning: 归档上次清单失败（历史对比可能缺失或陈旧）: {e}")
        inventory = scan_skills(project_root)
        # 分类统一读磁盘回填版（domain_final/interaction/lifecycle，LLM 已回填），
        # 与 conflict 的 load_domain_map 同源，避免"附录挂域用静态初值、冲突判定用回填值"的分裂
        classify = load_classify_merged(project_root, inventory)
        # 冲突矩阵优先读 03 写回版（severity/evidence/impact 已确认、伪冲突已移除）；无则现场重算
        conflicts = load_conflicts_merged(project_root, inventory)
        # 处方优先读 06 写回版（llm_actions 已完善、含 06 补的整改/移除类处方）；无则退化为规则候选
        rx = load_rx_merged(project_root, inventory, conflicts)
        content, appendix_files = build_report(project_root, inventory, classify, conflicts, rx)

        report_dir = medic_dir(project_root)
        ts_file = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # 毫秒级，避免同秒覆盖
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
            "scale": scale_of(len([s for s in inventory if s.get("status") == "active"])),
            "conflict_candidates": conflict_count,
            "prescriptions": len(rx),
            "appendix_files": appendix_files,
        }, ensure_ascii=False))
        return

    if args.action == "cleanup":
        """清理本次会话的临时中间产物（保留清单与历史报告——它们是增量模式与历史对比的基础）"""
        report_dir = medic_dir(project_root)
        # 白名单化：只清理确定的临时中间产物；显式保留接力棒（断点续跑/历史机制基础）
        # 与 _medic_inventory.json / _medic_last_inventory.json / 历史报告（增量对比基础）
        temp_medic_files = {"_medic_classify.json", "_medic_conflicts.json",
                            "_medic_scores.json", "_medic_rx.json", "_medic_review.json"}
        cleaned = []
        for f in os.listdir(report_dir):
            if f in temp_medic_files:
                fpath = os.path.join(report_dir, f)
                try:
                    os.remove(fpath)
                    cleaned.append(f)
                except OSError as e:
                    print(f"Warning: 清理 {f} 失败: {e}")
        kept = sorted(set(os.listdir(report_dir)) | {"_medic_baton.json", "_medic_inventory.json",
                      "_medic_last_inventory.json"} |
                      {f for f in os.listdir(report_dir)
                       if f.startswith("skill_audit_report_") or f.startswith("skill_audit_appendix_")})
        print(json.dumps({"cleaned": cleaned, "count": len(cleaned), "kept": kept}, ensure_ascii=False))
        return


if __name__ == "__main__":
    main()