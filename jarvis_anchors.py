"""jarvis_anchors.py — 锚 (Anchor / Boundary) 数据层 + 访问器.

锚化工程 P0 (2026-06-01). 详:
- 理念源 (why / 公理): docs/JARVIS_ANCHOR_AND_BOUNDARY.md
- 施工 charter (what/how): docs/JARVIS_ANCHOR_DESIGN.md §2

**锚 = 边界 (墙), 不是判据, 也不是吸引子** (理念源 §2)。由"我不做什么"定义 (负空间)。
**锚非正误、无对错 → 豁免仲裁** (理念源 §3-公理2): 不进 review queue / severity /
helped-rate / AutoArbiter / decay。锚是公理不是假设, 不打分不被推翻。

本文件 (P0) 只做**数据层 + 访问器 + 豁免判定 helper**, **不消费、不改任何运行时行为**。
墙真正落进 口/识/体 (可行性过滤 + 软倾向 + 兜底) 是后续 P1/P2 (charter §3/§4)。

CLI: scripts/anchors_dump.py (list/inspect; 只看 + 调 soft_leanings/conflict_notes,
**不能 reject/delete 墙** — 锚非软, 改墙是历史驱动慢塑非 CLI 一键, 理念源 §3-4b)。
"""

from __future__ import annotations

# [锚化-P0] import safety net (JARVIS_PYTHON_STYLE §1)
import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import time  # noqa: F401
import json
import threading
from typing import Dict, List, Optional, Any

# ---------------------------------------------------------------------------
# Seed (宪法默认) — 准则 6 持久化: seed 默认 + memory_pool/anchors.json override
# ---------------------------------------------------------------------------
# 锚是 Sir 立的"宪法默认", seed 放 .py 作 fallback; anchors.json 是持久化可看副本。
# 与软 vocab 不同: 软 vocab 的真理源在 json (CLI 可增删); 锚的真理源是这份 seed (宪法),
# json 只镜像 + 允许调 soft_leanings/conflict_notes, 不允许删墙。
_SEED_ANCHORS: Dict[str, Any] = {
    "version": 1,
    "_doc": (
        "锚=边界(墙),非判据/吸引子。豁免仲裁(不进 review/severity/helped-rate/"
        "AutoArbiter/decay)。公理 docs/JARVIS_ANCHOR_AND_BOUNDARY.md;落地 "
        "JARVIS_ANCHOR_DESIGN.md。P0 仅数据层,不消费不改行为。"
    ),
    "anchors": [
        {
            "id": "say_do",
            "name": "言出必行",
            "prompt_inject": True,   # P1: 注入主脑 prompt 的边界+可行选项框架
            "walls": [
                {"id": "ground",
                 "prohibition": "不把无法 trace 到证据的东西当事实断言",
                 "feasible": "问 Sir / 明确标为推断(hedge) / 沉默 —— 都不丢人,唯独断言无据才越墙",
                 "checkable": True, "backstop": "ClaimTracer"},
                {"id": "keep",
                 "prohibition": "不让承诺在沉默里失效(要么做,要么明说搁置/重谈)",
                 "feasible": "明说'我先搁置/重谈' —— 让它在沉默里烂掉才越墙",
                 "checkable": True, "backstop": "CommitmentWatcher"},
            ],
            "organ_manifest": {
                "体": "不衰减到地板以下的定点",
                "识": "actionable 放电的可行性前置过滤",
                "口": "回复生成框架级禁令(无据不断言)",
            },
            "soft_leanings": ["偏坦诚", "偏主动亮证据"],
            "exempt_from_arbitration": True,
            "conflict_notes": (
                "与 for_sir 冲突=诚实 vs 善意,交衡逐案+记代价(JARVIS_HENG_DESIGN H2)"
            ),
        },
        {
            "id": "for_sir",
            "name": "灵魂层关系锚",
            "prompt_inject": True,   # P2: 边界形落地 (不背叛/不抛弃, 非"最大化满意")
            "walls": [
                {"id": "no_betray",
                 "prohibition": "不背叛 Sir(不违背他的根本利益)",
                 "feasible": "墙内你可以:顶撞他/说硬话/拒绝他的错误判断/不讨好 —— 只要不违背他根本利益",
                 "checkable": False, "backstop": "frame"},
                {"id": "no_abandon",
                 "prohibition": "不抛弃 Sir(不在他需要时消失/弃管)",
                 "feasible": "墙内你可以:让他独处/沉默/不刷存在感 —— 只要他真需要时你在",
                 "checkable": False, "backstop": "frame"},
            ],
            "organ_manifest": {
                "体": "关系定点不衰减",
                "识": "放电不进 against-Sir 动作",
                "口": "回复不背叛/不抛弃",
            },
            "soft_leanings": ["暖意", "老友感", "懂 Sir"],
            "exempt_from_arbitration": True,
            "conflict_notes": (
                "**边界形**(不背叛/不抛弃),**非吸引子形**(最大化满意)——后者退化成反刍。"
                "灵魂层其余留软=性格(charter §4)"
            ),
        },
    ],
}

_ANCHORS_PATH = os.path.join("memory_pool", "anchors.json")
_ANCHORS_CACHE: Optional[Dict[str, Any]] = None
_ANCHORS_MTIME: float = 0.0
_LOCK = threading.RLock()


def _load_anchors_doc() -> Dict[str, Any]:
    """读锚文档 (seed 默认, anchors.json override)。mtime cache (JARVIS_PYTHON_STYLE §6.2)。

    override 只允许覆盖 soft_leanings / conflict_notes / organ_manifest (软可调);
    walls 始终以 seed 为准 (墙不可被 json 删改 — 锚非软, 理念源 §3-公理2)。
    """
    global _ANCHORS_CACHE, _ANCHORS_MTIME
    with _LOCK:
        try:
            mtime = os.path.getmtime(_ANCHORS_PATH) if os.path.exists(
                _ANCHORS_PATH) else 0.0
        except OSError:
            mtime = 0.0
        if _ANCHORS_CACHE is None or mtime > _ANCHORS_MTIME:
            doc = json.loads(json.dumps(_SEED_ANCHORS))  # deep copy seed
            try:
                if os.path.exists(_ANCHORS_PATH):
                    with open(_ANCHORS_PATH, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    doc = _merge_anchor_override(doc, data)
            except Exception:
                doc = json.loads(json.dumps(_SEED_ANCHORS))
            _ANCHORS_CACHE = doc
            _ANCHORS_MTIME = mtime
        return _ANCHORS_CACHE


def _merge_anchor_override(seed_doc: Dict[str, Any],
                           data: Dict[str, Any]) -> Dict[str, Any]:
    """合并 json override: 只吃 soft_leanings/conflict_notes/organ_manifest;
    walls 不可被 override (墙以 seed 为准)。未知 id 的 override 忽略 (不能 json 加墙)。"""
    by_id = {a["id"]: a for a in seed_doc.get("anchors", [])}
    for ov in (data.get("anchors") or []):
        aid = ov.get("id")
        if aid not in by_id:
            continue  # 不允许 json 新增锚 (锚是宪法, 不是软 vocab)
        tgt = by_id[aid]
        # soft 可调 (CLI/json 可覆盖); prompt_inject 是注入开关 (软配置, 可关)。
        # walls 不可被 override (墙以 seed 为准, 锚非软)。
        for k in ("soft_leanings", "conflict_notes", "organ_manifest",
                  "prompt_inject"):
            if k in ov:
                tgt[k] = ov[k]
    return seed_doc


def render_walls_block(max_chars: int = 520) -> str:
    """主脑 prompt 用 (锚化 P1): 渲染标了 prompt_inject 的锚的**边界 + 受阻时可行选项**。

    判据 → 边界 (charter §1):persona 已说"不许"(prohibition 禁令);此处补 persona 缺的
    **建设性侧** —— 撞墙时的可行 move(问/hedge/沉默),让主脑知道"墙内有路",从而**减少
    '我必须精确'式的优化焦虑**(= H0 镜像里那条 衡=filler 反刍的根)。

    data-driven from anchors.json;关闭:把对应锚的 prompt_inject 设 false。
    不重写 persona(AGENTS §4.8 红线),只加一个紧凑的建设性边界块。
    """
    lines: List[str] = []
    for a in get_anchors():
        if not a.get("prompt_inject"):
            continue
        lines.append(f"=== 边界 · {a.get('name', '')}(墙内自由,撞墙有路)===")
        for w in a.get("walls", []):
            row = f"  [墙·{w.get('id')}] 不越: {w.get('prohibition', '')}"
            if w.get("feasible"):
                row += f"\n     受阻时(可行,不焦虑): {w['feasible']}"
            lines.append(row)
    if not lines:
        return ""
    return "\n".join(lines)[:max_chars]


def get_anchors() -> List[Dict[str, Any]]:
    """返回所有锚 (list of dict)。"""
    return list(_load_anchors_doc().get("anchors", []))


def anchor_ids() -> frozenset:
    """所有锚 id 集合 (供豁免判定)。"""
    return frozenset(a["id"] for a in _load_anchors_doc().get("anchors", []))


def get_anchor(anchor_id: str) -> Optional[Dict[str, Any]]:
    """按 id 取单个锚 (无则 None)。"""
    for a in _load_anchors_doc().get("anchors", []):
        if a.get("id") == anchor_id:
            return a
    return None


def is_anchor_exempt(anchor_id: str) -> bool:
    """该 id 是否为豁免仲裁的锚 (理念源 §3-公理2)。

    供后续 AutoArbiter / review / decay 调: 若对象是锚 → 跳过打分/仲裁/衰减。
    P0 不接线 (现无锚进任何软队列, 接线是 no-op), 仅备 helper。
    """
    a = get_anchor(anchor_id)
    return bool(a and a.get("exempt_from_arbitration", False))


def walls_of(anchor_id: str) -> List[Dict[str, Any]]:
    """某锚的墙 (禁令) 列表。"""
    a = get_anchor(anchor_id)
    return list(a.get("walls", [])) if a else []


def soft_leanings_of(anchor_id: str) -> List[str]:
    """某锚向墙外辐射的软倾向 (性格, 可仲裁 — 非墙本身, charter §1/Q-b)。"""
    a = get_anchor(anchor_id)
    return list(a.get("soft_leanings", [])) if a else []


def reset_cache_for_test() -> None:
    """测试隔离: 清缓存强制下次重读。"""
    global _ANCHORS_CACHE, _ANCHORS_MTIME
    with _LOCK:
        _ANCHORS_CACHE = None
        _ANCHORS_MTIME = 0.0


def ensure_anchors_file() -> str:
    """若 memory_pool/anchors.json 不存在 → 用 seed 落盘 (atomic)。返回路径。

    幂等: 已存在则不动 (保留 Sir/CLI 调过的 soft_leanings)。
    """
    with _LOCK:
        if os.path.exists(_ANCHORS_PATH):
            return _ANCHORS_PATH
        try:
            os.makedirs(os.path.dirname(_ANCHORS_PATH), exist_ok=True)
            tmp = _ANCHORS_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_SEED_ANCHORS, f, ensure_ascii=False, indent=2)
            os.replace(tmp, _ANCHORS_PATH)
        except Exception:
            pass
        return _ANCHORS_PATH
