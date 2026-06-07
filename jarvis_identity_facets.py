# -*- coding: utf-8 -*-
"""jarvis_identity_facets.py — 锚重构 P0 Step 1: identity facets store + 离散资格闸.

设计源: docs/process/JARVIS_ANCHOR_REBUILD_P0_DESIGN.md (commit 3af74c1, 顾问/Sir 审过).
理念: 锚 = 稳定骨架(墙 + 宪法散文) + 可塑 facets 层(围墙生长)。本模块只做
可塑 facets 层的 **store + 离散资格闸**(B.5/B.5a)。

scope (Step 1 铁律):
  - 纯新增。**不接进 prompt**(Step 3 才接 build_block)、**不改真机行为**。
  - flag 默认 off (FACETS_ENABLED=False) → 真机零变化。
  - 不碰墙(_SEED_ANCHORS.walls)、不碰 WHO-I-AM/REFERENT-MAP 宪法散文。
  - 衡记伤→facet 本阶段**只留接口位不实做**(守冻结 §9 次序: 锚重构→河床)。

冻结红线 (docs/process/JARVIS_META_ARCH_ALIGNMENT_20260607.md):
  §5 不评分/不交易: 无 strength/weight/score 标量字段; 资格闸=离散 AND;
                     无排序/argmax/公共货币比较。
  §3/§10 墙钉死: 不读写 _SEED_ANCHORS.walls; facet 须正交于墙。
  §7 锚增=随真接地: 真出处 = manifold PROV_SAID/PROV_SHARED 接地边(布尔);
                     PROV_EMBED/COOCCUR/INFERRED 不算。

看守点① (死守 — B.5a): facet 结晶代码**不得调用任何 cosine/相似度函数**。
  "同一 X" 用离散键(manifold 边结构键 / resolve 后 node_id / commitment ID)。
  若 manifold alias 上游靠 embed 聚类, 只取 resolve 后的离散 node_id 作键,
  绝不下钻向量层比相似度。本模块全程零 import/调用任何 embedding/cosine/similarity。
"""

from __future__ import annotations

# import safety net (JARVIS_PYTHON_STYLE §1)
import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import re  # noqa: F401
import json
import time
import threading
import collections  # noqa: F401
from typing import Dict, List, Optional, Any, Iterable

# 🔒 [看守点① / anchor-rebuild-P0] 本模块严禁 import 任何相似度/向量比较设施。
# "同一性"只用离散键。任何 cosine/embedding/fuzz 的 import 都是红线违规。
# (静态守护见 tests/_test_identity_facets_p0_step1_*.py: grep 本文件无 cosine/similarity。)

_STORE_PATH = os.path.join("memory_pool", "identity_facets.json")
_LOCK = threading.RLock()

# flag (Step 1 默认 off — 真机零变化, 可 revert)。Step 3 接 prompt 时由 Sir/CLI 开。
FACETS_ENABLED_DEFAULT = False

# 离散状态 (红线: 无连续标量)
STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"
_VALID_STATUS = frozenset({STATUS_ACTIVE, STATUS_REVOKED})

# provenance source 白名单 (命门: 只认接地出处, 不认相似度/推断)
SRC_MANIFOLD_SAID = "manifold_said"      # ← manifold PROV_SAID 边
SRC_MANIFOLD_SHARED = "manifold_shared"  # ← manifold PROV_SHARED 边
SRC_INNER_THOUGHT = "inner_thought"      # ← 识 propose 的立场/关系痕迹 (仍须过闸)
_VALID_SRC = frozenset({SRC_MANIFOLD_SAID, SRC_MANIFOLD_SHARED, SRC_INNER_THOUGHT})

# 复现计数门槛 (B.5: 离散硬常量, 非阈值分数; 系统级常量同 TICK_INTERVAL, 不下钻 vocab)
RECURRENCE_MIN_N = 3


def _log(msg: str) -> None:
    try:
        from jarvis_utils import bg_log
        bg_log(msg)
    except Exception:
        try:
            print(msg)
        except Exception:
            pass


def is_facets_enabled() -> bool:
    """Step 1: 默认 off。env JARVIS_FACETS=1 显式开 (Step 3 接 prompt 前不影响真机)。"""
    if os.environ.get("JARVIS_FACETS") == "1":
        return True
    return FACETS_ENABLED_DEFAULT


# ---------------------------------------------------------------------------
# 离散同一性键 (B.5a) — 禁相似度
# ---------------------------------------------------------------------------
def _manifold_provenance_kind_to_src(kind: str) -> Optional[str]:
    """manifold PROV_* → facet provenance source。只接地两类, 其余 (embed/cooccur/inferred) → None。"""
    try:
        import jarvis_relational_manifold as _m
        if kind == _m.PROV_SAID:
            return SRC_MANIFOLD_SAID
        if kind == _m.PROV_SHARED:
            return SRC_MANIFOLD_SHARED
    except Exception:
        pass
    return None


def gather_grounded_provenance(node_id: str) -> List[Dict[str, Any]]:
    """B.5a: 拿某节点(经 manifold.resolve 去别名)的离散接地 provenance。

    **零相似度**: 只调 manifold.node_grounded_provenance (按 PROV kind 离散过滤),
    edge_key / resolve 后 node_id 作离散同一性键。返 [{src, ref, edge_key, other, count}]。
    """
    out: List[Dict[str, Any]] = []
    try:
        import jarvis_relational_manifold as _m
        mani = _m.get_manifold()
        rows = mani.node_grounded_provenance(node_id)  # 已只含 PROV_SAID/SHARED
        for r in rows:
            src = _manifold_provenance_kind_to_src(r.get("kind"))
            if src is None:
                continue  # 非接地 (理论上 node_grounded_provenance 已过滤, 双保险)
            out.append({
                "src": src,
                "ref": r.get("ref"),
                "edge_key": r.get("edge_key"),
                "other": r.get("other"),
                "count": int(r.get("count", 1)),
            })
    except Exception as exc:
        _log(f"[Facets] gather_grounded_provenance failed ({exc!r})")
    return out


# ---------------------------------------------------------------------------
# 离散资格闸 (B.5 + B.5a, 全 AND, 无排序/argmax)
# ---------------------------------------------------------------------------
def qualifies(
    *,
    grounded_provenance: List[Dict[str, Any]],
    recurrence_count: int,
    orthogonal_to_walls: bool,
    recurrence_min: int = RECURRENCE_MIN_N,
) -> bool:
    """B.5 离散资格闸 (全 AND, 布尔):

    1. 真出处: grounded_provenance 至少 1 条接地源 (manifold_said/shared)。布尔。
    2. 复现计数: recurrence_count >= recurrence_min (离散计数, 非分数)。
    3. 与墙正交: orthogonal_to_walls=True (不复述/改写 _SEED_ANCHORS 4 墙)。

    无打分/无排序/无 argmax — 纯 AND。任一不满足 → 不结晶。
    """
    has_grounded = any(
        (p.get("src") in (SRC_MANIFOLD_SAID, SRC_MANIFOLD_SHARED))
        for p in (grounded_provenance or [])
    )
    return bool(has_grounded) and (int(recurrence_count) >= int(recurrence_min)) and bool(orthogonal_to_walls)


def _is_orthogonal_to_walls(content: str) -> bool:
    """B.5 条件3: facet 内容是否正交于墙(不复述墙的 prohibition/id)。

    离散判定: content 不得包含墙的 id 关键词(ground/keep/no_betray/no_abandon)
    或其 prohibition 措辞的明显复述。保守: 命中即判"非正交"(拒结晶)。
    **不碰墙数据的写** — 只读 _SEED_ANCHORS 的墙 id 做关键词排除, 不修改任何墙。
    """
    if not content:
        return True
    low = content.lower()
    # 看守点①bis [Step2+3 / 2026-06-07]: 墙 id 从 _SEED_ANCHORS 读 (只读, 不写墙),
    # 墙将来改了自动同步, 不再硬写。
    # 英文墙 id 用**词边界**匹配 (避免 'ground' ⊂ 'grounded' 类子串误判);
    # 中文禁令词无词边界概念 → 直接子串 (无对应离散源, 保留小集兜底)。
    wall_ids = _get_wall_ids()  # ← 只读 jarvis_anchors._SEED_ANCHORS 的墙 id
    for wid in wall_ids:
        if re.search(r"\b" + re.escape(wid.lower()) + r"\b", low):
            return False
    for cn in ("不背叛", "不抛弃", "无据不断言", "承诺不", "言出必行"):
        if cn in content:
            return False
    return True


def _get_wall_ids() -> List[str]:
    """看守点①bis: 只读 jarvis_anchors._SEED_ANCHORS 的墙 id (ground/keep/no_betray/
    no_abandon)。**只读, 绝不修改任何墙数据。** 失败 → 退回硬集 (兜底, 仍只读)。"""
    try:
        import jarvis_anchors as _ja
        ids: List[str] = []
        for a in _ja._SEED_ANCHORS.get("anchors", []):
            for w in a.get("walls", []):
                wid = w.get("id")
                if wid:
                    ids.append(str(wid).lower())
        if ids:
            return ids
    except Exception:
        pass
    return ["no_betray", "no_abandon", "ground", "keep"]  # 兜底, 只读不写


# ---------------------------------------------------------------------------
# Store (独立 json, 不进 manifold; 范式同 affordance store)
# ---------------------------------------------------------------------------
def _load_store_at(path: str) -> Dict[str, Any]:
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"_meta": {"schema": "identity_facets"}, "facets": {}}


def _save_store_at(store: Dict[str, Any], path: str) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as exc:
        _log(f"[Facets] save failed ({exc!r})")


def _make_facet_id(identity_key: str) -> str:
    """facet_id = 由离散同一性键派生 (稳定, 同一 X 同 id → 不重复结晶)。无相似度。"""
    safe = re.sub(r"[^0-9a-zA-Z_:.\-]", "_", (identity_key or "").strip())[:80]
    return f"facet_{safe}" if safe else "facet_unknown"


def crystallize(
    identity_key: str,
    content: str,
    *,
    grounded_provenance: List[Dict[str, Any]],
    recurrence_count: int,
    recurrence_min: int = RECURRENCE_MIN_N,
    store_path: Optional[str] = None,
) -> Dict[str, Any]:
    """**结晶闸 = facet 写入的唯一入口**。过离散资格闸(B.5) → 写 active facet。

    identity_key: 离散同一性键 (manifold edge_key / resolve 后 node_id / commitment ID)。
                  禁用相似度产生的键。
    返记录 dict (status=active 表结晶成功 / 不返回未结晶记录, 不结晶返 {"crystallized": False, ...})。

    红线: 记录**无 strength/weight/score 字段**。资格闸离散 AND。
    """
    identity_key = (identity_key or "").strip()
    if not identity_key:
        raise ValueError("facets: empty identity_key (离散键不能为空, 无相似度兜底)")

    orthogonal = _is_orthogonal_to_walls(content)
    ok = qualifies(
        grounded_provenance=grounded_provenance,
        recurrence_count=recurrence_count,
        orthogonal_to_walls=orthogonal,
        recurrence_min=recurrence_min,
    )
    if not ok:
        return {
            "crystallized": False,
            "identity_key": identity_key,
            "reason": _why_rejected(grounded_provenance, recurrence_count,
                                    orthogonal, recurrence_min),
        }

    now = time.time()
    facet_id = _make_facet_id(identity_key)
    # provenance 落 store: 只留离散字段 (src/ref/edge_key/other/count), 无 score。
    prov_clean = [
        {
            "source": p.get("src"),
            "ref": p.get("ref"),
            "edge_key": p.get("edge_key"),
            "other": p.get("other"),
            "recurrence_count": int(p.get("count", 1)),
            "ts": now,
        }
        for p in (grounded_provenance or [])
        if p.get("src") in _VALID_SRC
    ]
    path = store_path or _STORE_PATH
    with _LOCK:
        store = _load_store_at(path)
        rec = {
            "facet_id": facet_id,
            "identity_key": identity_key,
            "content": (content or "")[:300],
            "provenance": prov_clean,
            "recurrence_count": int(recurrence_count),
            "crystallized_ts": now,
            "status": STATUS_ACTIVE,
            # ❌ 无 strength / weight / score / salience 字段 (红线 §5)。
        }
        store.setdefault("facets", {})[facet_id] = rec
        _save_store_at(store, path)
    _log(f"[Facets] crystallized {facet_id} (recurrence={recurrence_count})")
    return {"crystallized": True, **rec}


def _why_rejected(grounded_prov, recurrence, orthogonal, recurrence_min) -> str:
    reasons = []
    if not any(p.get("src") in (SRC_MANIFOLD_SAID, SRC_MANIFOLD_SHARED)
               for p in (grounded_prov or [])):
        reasons.append("no_grounded_provenance")
    if int(recurrence) < int(recurrence_min):
        reasons.append(f"recurrence<{recurrence_min}")
    if not orthogonal:
        reasons.append("not_orthogonal_to_walls")
    return ",".join(reasons) or "unknown"


def _distinct_event_count(grounded_provenance: List[Dict[str, Any]]) -> int:
    """[末轮 count 语义核] recurrence = "≥N 个不同 turn/事件" 的**离散事件数**,
    **不是** sum(count)(后者把同一 turn 内重复也计入, 违 B.5a)。

    实证 (jarvis_relational_manifold.py:455-466 _append_provenance dedup 键=(kind,ref)):
    PROV_SAID 的 ref=turn_id (observe_explicit_link:500) → 不同 turn = 不同 provenance 记录;
    PROV_SHARED 的 ref=entity_id (observe_shared_entity:512) → 不同共享源 = 不同记录。
    ⟹ 离散事件数 = **不同 ref 的个数**(每条 grounded provenance = 一个离散事件)。
    """
    refs = set()
    for p in (grounded_provenance or []):
        if p.get("src") in (SRC_MANIFOLD_SAID, SRC_MANIFOLD_SHARED):
            refs.add((p.get("src"), p.get("ref")))
    return len(refs)


def crystallize_from_node(
    node_id: str,
    content: str,
    *,
    recurrence_count: Optional[int] = None,
    recurrence_min: int = RECURRENCE_MIN_N,
    store_path: Optional[str] = None,
) -> Dict[str, Any]:
    """便捷入口: 从 manifold 节点离散键采集接地 provenance → 结晶。

    identity_key = manifold.resolve 后的离散 node_id。recurrence_count 缺省时
    = **不同接地 ref 的离散事件数** (_distinct_event_count, 非 sum(count) — 同一 turn
    重复不累加, B.5a count 语义核)。零相似度。
    """
    prov = gather_grounded_provenance(node_id)
    if recurrence_count is None:
        recurrence_count = _distinct_event_count(prov)
    # identity_key 用 resolve 后的离散 node_id
    try:
        import jarvis_relational_manifold as _m
        ikey = _m.get_manifold().resolve(node_id)
    except Exception:
        ikey = node_id
    return crystallize(ikey, content, grounded_provenance=prov,
                       recurrence_count=recurrence_count,
                       recurrence_min=recurrence_min, store_path=store_path)


# ---------------------------------------------------------------------------
# 接口位 (Step 2/河床留位 — 本阶段不实做)
# ---------------------------------------------------------------------------
def revoke_facet(facet_id: str, *, reason: str = "",
                 store_path: Optional[str] = None) -> bool:
    """[Step 2 接口位] 锚减: 离散事件驱动撤销 (Sir 纠正/接地边消失/reverify 出处没了)。

    Step 1 提供最小实现 (标 status=revoked, 离散事件), 触发逻辑 Step 2 接。
    时间**不**在此降级 (B.6: 时间只触发 reverify, 不直接 revoke)。
    """
    path = store_path or _STORE_PATH
    with _LOCK:
        store = _load_store_at(path)
        rec = store.get("facets", {}).get(facet_id)
        if rec is None:
            return False
        rec["status"] = STATUS_REVOKED
        rec["revoked_ts"] = time.time()
        rec["revoke_reason"] = (reason or "")[:200]
        _save_store_at(store, path)
    _log(f"[Facets] revoked {facet_id} (reason={reason})")
    return True


# ---------------------------------------------------------------------------
# Step 2 — 锚减的离散事件触发 (B.6, 三类全离散事件, 无分数掉阈值)
# ---------------------------------------------------------------------------
def _find_facets_by_identity_key(identity_key: str, store: Dict[str, Any]
                                 ) -> List[str]:
    """按离散 identity_key 找 facet_id 列表 (离散键匹配, 无相似度)。"""
    out = []
    for fid, rec in store.get("facets", {}).items():
        if rec.get("identity_key") == identity_key:
            out.append(fid)
    return out


def reverify_facet(facet_id: str, *, store_path: Optional[str] = None) -> str:
    """[B.6 锚减·reverify] 离散重核: 重新 gather identity_key 的接地 provenance。

    接地边**还在** → 留 active;**没了** → revoke_facet(reason='grounding_edge_gone')。
    **时间只触发本函数, 绝不在此按时长降级** (B.6 第3条: 状态变化只能有证据)。
    返 'active' / 'revoked' / 'not_found'。零相似度 (gather 只走离散 PROV kind)。
    """
    path = store_path or _STORE_PATH
    with _LOCK:
        store = _load_store_at(path)
        rec = store.get("facets", {}).get(facet_id)
        if rec is None:
            return "not_found"
        if rec.get("status") != STATUS_ACTIVE:
            return rec.get("status", "revoked")
        identity_key = rec.get("identity_key", "")
    # gather 在锁外 (调 manifold) — 离散事实重采
    prov = gather_grounded_provenance(identity_key)
    has_grounded = any(
        p.get("src") in (SRC_MANIFOLD_SAID, SRC_MANIFOLD_SHARED) for p in prov
    )
    if has_grounded:
        return STATUS_ACTIVE  # 接地边还在 → 留 active (时间没把它降级)
    revoke_facet(facet_id, reason="grounding_edge_gone", store_path=path)
    return STATUS_REVOKED


def on_sir_correction(identity_key: str, *, detail: str = "",
                      store_path: Optional[str] = None) -> int:
    """[B.6 锚减·Sir 纠正] Sir 显式纠正/否认事件钩子 → 按离散键撤销对应 facet。

    离散事件驱动 (非分数)。给 MemoryCorrection / Sir 显式否认接 (本轮提供钩子,
    真机当轮接线留 producer 末轮)。返撤销条数。
    """
    identity_key = (identity_key or "").strip()
    if not identity_key:
        return 0
    path = store_path or _STORE_PATH
    with _LOCK:
        store = _load_store_at(path)
        fids = _find_facets_by_identity_key(identity_key, store)
    n = 0
    for fid in fids:
        if revoke_facet(fid, reason=f"sir_corrected:{detail}"[:200],
                        store_path=path):
            n += 1
    return n


def reverify_all_facets(*, store_path: Optional[str] = None) -> Dict[str, int]:
    """周期重核全部 active facet (B.6: 降级由证据决定, 非时间)。返 {reverified, revoked}。"""
    path = store_path or _STORE_PATH
    actives = [r["facet_id"] for r in get_facets(status=STATUS_ACTIVE, store_path=path)]
    revoked = 0
    for fid in actives:
        if reverify_facet(fid, store_path=path) == STATUS_REVOKED:
            revoked += 1
    return {"reverified": len(actives), "revoked": revoked}


def record_wound_for_facet(*args, **kwargs) -> None:
    """[河床接口位 — 冻结 §6, 本阶段不实做] 衡记伤 → facet 附着。

    守冻结 §9 次序 (锚重构 → 河床闭环): Step 1 只留位, 不接 anchor_conflict_wounds。
    """
    return None  # noqa: 接口位, 河床阶段实做


# ---------------------------------------------------------------------------
# 读 (CLI / Step 3 render 用)
# ---------------------------------------------------------------------------
def get_facets(*, status: Optional[str] = None,
               store_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """读 facet 记录。status 过滤 (active/revoked/None=全部)。不排序打分 — 仅按插入序。"""
    path = store_path or _STORE_PATH
    store = _load_store_at(path)
    recs = list(store.get("facets", {}).values())
    if status is not None:
        recs = [r for r in recs if r.get("status") == status]
    return recs


# ---------------------------------------------------------------------------
# Step 3 — render facets (B.8a: 离散子预算 + 溢出离散硬规 + 看守点C 不半截断)
# ---------------------------------------------------------------------------
# 离散硬常量 (系统级, 同 TICK_INTERVAL, 不下钻 vocab)
FACETS_RENDER_MAX_CHARS = 400   # 子预算上限 (叠加在动态状态之后, 不挤占)
FACETS_RENDER_MAX_COUNT = 5     # 最多列几条

# 出处优先级 (离散硬规, B.8a): PROV_SHARED > PROV_SAID。无分数。
_SRC_PRIORITY = {SRC_MANIFOLD_SHARED: 0, SRC_MANIFOLD_SAID: 1, SRC_INNER_THOUGHT: 2}


def _facet_primary_src(rec: Dict[str, Any]) -> str:
    """facet 的主出处 (取其 provenance 里优先级最高的 src — 离散查表, 非打分)。"""
    best = SRC_INNER_THOUGHT
    best_p = 99
    for p in rec.get("provenance", []):
        s = p.get("source")
        pr = _SRC_PRIORITY.get(s, 99)
        if pr < best_p:
            best_p = pr
            best = s
    return best


def _select_facets_for_render(actives: List[Dict[str, Any]]
                              ) -> List[Dict[str, Any]]:
    """B.8a 溢出离散硬规: 出处优先级 (PROV_SHARED>PROV_SAID) + 同级 FIFO
    (最早 crystallized_ts 先)。**绝不按显著度/分数排序** — 仅离散键 (优先级整数 +
    时间戳) 做稳定排序, 无 score/weight 参与。取前 FACETS_RENDER_MAX_COUNT 条。
    """
    # 离散排序键 = (出处优先级整数, crystallized_ts) — 全离散, 无分数。
    ordered = sorted(
        actives,
        key=lambda r: (_SRC_PRIORITY.get(_facet_primary_src(r), 99),
                       float(r.get("crystallized_ts", 0.0))),
    )
    return ordered[:FACETS_RENDER_MAX_COUNT]


def render_facets_block(*, max_chars: int = FACETS_RENDER_MAX_CHARS,
                        store_path: Optional[str] = None) -> str:
    """[B.8a] 渲染 active facets 段, 框成"我经真接地长出的具体性格/关系定点"。

    - 仅当 is_facets_enabled() → 否则返 "" (flag off 真机零变化)。
    - 子预算 max_chars (默 400) + 最多 5 条 (离散硬规)。
    - 溢出选择 = 出处优先级 + FIFO (离散, 见 _select_facets_for_render)。
    - 看守点C (不半截断): 某条放不进剩余预算 → **整条丢弃**, 绝不截半条。
    - 离散列出 (像列 commitments), 无分数标注。
    """
    if not is_facets_enabled():
        return ""
    actives = get_facets(status=STATUS_ACTIVE, store_path=store_path)
    if not actives:
        return ""
    selected = _select_facets_for_render(actives)
    header = "[WHO I'VE BECOME — facets grounded in real traces with Sir]"
    lines = [header]
    used = len(header) + 1
    for rec in selected:
        content = (rec.get("content") or "").strip()
        if not content:
            continue
        line = f"  - {content}"
        # 看守点C: 放不进剩余子预算 → 整条丢弃, 不半截断。
        if used + len(line) + 1 > max_chars:
            continue
        lines.append(line)
        used += len(line) + 1
    if len(lines) == 1:
        return ""  # header 之外一条没放进 → 不渲染空头
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 末轮 — producer: scan_and_crystallize (增-producer, 死守离散, 不打分不排序)
# ---------------------------------------------------------------------------
def _template_content_for_node(node_id: str,
                               grounded_provenance: List[Dict[str, Any]]) -> str:
    """[末轮 content 模板化 / 死守禁 LLM] facet content = 对离散接地事实的**确定性
    模板渲染**, 不由口/识 free-form 生成 (防身份层假焊回潮)。

    只搬运真痕迹已有的离散字段 (resolve 后 node_id + 关系另一端 other + 关系类型),
    不新增任何"事实"。无 LLM 调用, 无相似度。
    """
    try:
        import jarvis_relational_manifold as _m
        kind, raw = _m.split_node_id(node_id)
    except Exception:
        kind, raw = ("", node_id)
    # 离散搬运: 关系另一端 (去重, 最多列 3 个, 插入序非排序)
    others = []
    for p in (grounded_provenance or []):
        o = p.get("other")
        if o and o not in others:
            others.append(o)
    others_str = ", ".join(others[:3]) if others else "(no linked nodes)"
    # 模板: 纯字段拼接, 确定性
    return f"a grounded relational trace: [{kind}:{raw}] linked with {others_str}"


def scan_and_crystallize(*, recurrence_min: int = RECURRENCE_MIN_N,
                         store_path: Optional[str] = None) -> Dict[str, Any]:
    """[末轮 producer] 把真接地痕迹结晶成 facet。**flag-gated, 默认 off**。

    死守离散 (B.5/§5):
      - 枚举 manifold 所有有接地边的候选节点 (iter_grounded_nodes, 不排序)。
      - **逐个独立**过 B.5 离散资格闸 (crystallize_from_node), 互不比较。
      - 够格的**全部**结晶; **绝不**按显著度排序挑几条 (无 score/sort/argmax 选结晶)。
      - 容量限制只在 render 层 (5 条离散硬规); producer/store 不设上限/不挑选/不排序。
      - content 模板化 (确定性, 禁 LLM)。recurrence = 不同 ref 离散事件数。
      - 幂等: 同离散键 → 同 facet_id, 不重复结晶 (_make_facet_id)。

    返 {scanned, crystallized}。flag off → no-op ({enabled: False})。
    """
    if not is_facets_enabled():
        return {"enabled": False, "scanned": 0, "crystallized": 0}
    try:
        import jarvis_relational_manifold as _m
        mani = _m.get_manifold()
        candidates = mani.iter_grounded_nodes()  # 离散枚举, 不排序
    except Exception as exc:
        _log(f"[Facets] scan_and_crystallize: manifold unavailable ({exc!r})")
        return {"enabled": True, "scanned": 0, "crystallized": 0}
    scanned = 0
    crystallized = 0
    for node_id in candidates:  # 逐个独立, 互不比较 (无跨候选排序/打分)
        scanned += 1
        prov = gather_grounded_provenance(node_id)
        content = _template_content_for_node(node_id, prov)
        r = crystallize_from_node(node_id, content, recurrence_min=recurrence_min,
                                  store_path=store_path)
        if r.get("crystallized"):
            crystallized += 1
    _log(f"[Facets] scan_and_crystallize: scanned={scanned} crystallized={crystallized}")
    return {"enabled": True, "scanned": scanned, "crystallized": crystallized}
