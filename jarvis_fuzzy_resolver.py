# -*- coding: utf-8 -*-
"""[P0+18-b.8 / 2026-05-15] Fuzzy Entity Resolver — ASR 实体名容错

设计目标
--------
修复 Sir 13:08 实测 BUG #7：
    "查 nonexistent_xyz_app 进程" → ASR 转 "XYZAPP" → 主脑装作查了进程

承诺必行系列的另一面：
- a.16 修的是"不能提议做不到的事"
- b.8 修的是"找不到时不要装作找到了"

工作流
-----
1. hand 收到指定 name 的查询（如 find_process('XYZAPP')）
2. 真匹配失败 → 走 fuzzy fallback
3. 拉所有候选（process_iter 所有进程名）
4. 用 difflib.SequenceMatcher + 形态归一比对
5. 返回 top_k 候选 + 相似度
6. 主脑看到 `fuzzy_candidates` → 反向问 Sir 确认（不要装跑）

依赖
----
仅 stdlib (re, difflib)。get_running_process_names() 可选 psutil。
线程安全：纯函数 + 无全局状态。
"""

from __future__ import annotations

import re
import difflib
from typing import Optional


# ============================================================
# 形态归一化
# ============================================================

# 常见 ASR 转写垃圾后缀 — 比较前剥掉
_NOISE_SUFFIXES = (
    '.exe', '.lnk', '.app', '.bat', '.cmd', '.com',
    ' application', ' app', ' service', ' helper',
)

# 形态归一：lowercase + 去后缀 + 多空格/下划线/横杠/点 折成单下划线
def _normalize(s: str) -> str:
    """把字符串折成可比较的"骨架"形态。"""
    if not s:
        return ''
    s = s.strip().lower()
    # 反复剥后缀（chrome.exe.lnk → chrome）
    changed = True
    while changed:
        changed = False
        for suf in _NOISE_SUFFIXES:
            if s.endswith(suf):
                s = s[:-len(suf)].rstrip()
                changed = True
    # 分隔符归一为单下划线
    s = re.sub(r'[\s_\-\.]+', '_', s)
    s = s.strip('_')
    return s


# ============================================================
# 公开 API
# ============================================================

def fuzzy_resolve_entity(query: str, candidates: list, *,
                         top_k: int = 5,
                         min_similarity: float = 0.55) -> list:
    """模糊匹配 entity name。

    参数：
        query              原始查询字符串（如 ASR 转写出来的 "XYZAPP"）
        candidates         候选名字列表（如所有进程名 / 窗口标题 / 设备名）
        top_k              返回前 k 个匹配（默认 5）
        min_similarity     最小相似度阈值（默认 0.55，0.0 - 1.0）

    返回：
        list[tuple[str, float]]  [(original_candidate_name, score), ...] 按 score 降序去重

    示例：
        >>> fuzzy_resolve_entity('XYZAPP', ['xyz_app.exe', 'chrome.exe', 'xyz_application'])
        [('xyz_app.exe', 0.75), ('xyz_application', 0.75)]

    设计取舍：
    - 用 difflib.SequenceMatcher (Python stdlib, 无第三方依赖)
    - 加权规则：query 是 candidate 子串（或反之）→ 提到 0.75 起步
      理由：ASR 倾向把短词扩展成"长形"（"xyz" → "xyz application"），
      或反过来把长词截短。子串关系是高置信信号。
    - 形态归一比较：去 .exe / 多空格折成单下划线 → "XYZ APP" ≈ "xyz_app.exe"
    - top_k 后去重（同 candidate 名字只保留第一个），保序
    """
    if not query or not candidates:
        return []
    q_norm = _normalize(query)
    if not q_norm:
        return []

    scored = []
    for cand in candidates:
        if not isinstance(cand, str) or not cand:
            continue
        c_norm = _normalize(cand)
        if not c_norm:
            continue
        # 基础相似度
        base = difflib.SequenceMatcher(None, q_norm, c_norm).ratio()
        # 子串提权：q ⊆ c 或 c ⊆ q → 至少 0.75
        if q_norm in c_norm or c_norm in q_norm:
            score = max(base, 0.75)
        else:
            score = base
        # 完全相等再加 boost（防止其它 candidate 同分上来）
        if q_norm == c_norm:
            score = max(score, 0.99)
        if score >= min_similarity:
            scored.append((cand, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    # 去重：相同 candidate（lower）只留第一个
    seen = set()
    deduped = []
    for cand, score in scored:
        key = cand.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append((cand, round(score, 3)))
        if len(deduped) >= top_k:
            break
    return deduped


def get_running_process_names() -> list:
    """便利函数：拉所有正在跑的进程名（去重保序）。失败返回 []。

    用于 process_hands 的 fuzzy fallback。psutil 不可用时返回空，
    调用方应自行兜底（不做 fuzzy 回退）。
    """
    try:
        import psutil
    except Exception:
        return []
    names = []
    seen = set()
    try:
        for p in psutil.process_iter(['name']):
            try:
                n = (p.info.get('name') or '').strip()
                if n and n.lower() not in seen:
                    seen.add(n.lower())
                    names.append(n)
            except Exception:
                continue
    except Exception:
        pass
    return names


def format_fuzzy_candidates_for_msg(candidates: list, *,
                                    query: str = '',
                                    max_lines: int = 5) -> str:
    """把 fuzzy 候选渲染成 hand return msg 用的人类可读文本。

    格式：
        🔍 [Fuzzy Candidates] 没找到 '<query>'，候选:
          ~ xyz_app.exe (87%)
          ~ xyz_application.exe (76%)
          ~ x_y_z_helper.exe (62%)
    """
    if not candidates:
        return ''
    header = f"🔍 [Fuzzy Candidates] 没找到 '{query}'，候选:" if query else "🔍 [Fuzzy Candidates] 候选:"
    lines = [header]
    for cand, score in candidates[:max_lines]:
        try:
            pct = int(round(float(score) * 100))
        except Exception:
            pct = 0
        lines.append(f"  ~ {cand} ({pct}%)")
    return "\n".join(lines)


# ============================================================
# [P0+18-b.8 / 2026-05-15] FUZZY_CANDIDATES_POLICY — prompt 软约束
# ============================================================

FUZZY_CANDIDATES_POLICY = """[FUZZY CANDIDATES POLICY — 找不到时不装跑]:
If a tool result contains `fuzzy_candidates` (look for "🔍 [Fuzzy Candidates]" in the
tool output or `data.fuzzy_candidates` in structured data), it means Sir's exact spelling
was not matched, but similar candidates exist. You MUST:

1. NEVER pretend you found it or already ran the action. That violates 承诺必行.
2. Quote the top 1-2 candidates back to Sir in Sir's language and ask:
   "Sir, I couldn't find '<query>' exactly. Did you mean: <top1> or <top2>?"
3. Wait for Sir's confirmation (or correction), then re-issue the tool call with
   the confirmed name as <FAST_CALL>.
4. If candidates are all very low score (< 60%) or feel unrelated, say honestly:
   "I don't see anything matching '<query>' running, Sir. Want me to widen the search?"
   Do NOT pick a low-confidence candidate silently.

This is the post-action mirror of [TOOL HONESTY]: that block stops you from offering
capabilities you don't have; this block stops you from claiming results you didn't get.
"""
