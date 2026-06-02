# -*- coding: utf-8 -*-
"""[body-diff-PG / Sir 2026-06-02] 接地谓词门 (Grounded Predicate Gate) — 固着↔健忘旋钮.

真理源: .kiro/specs/body-differentiation/ (R1/R11/R16, design §5.1, Property 1/2/3)。
引导: docs/AGENT_KICKOFF_BODY_DIFFERENTIATION.md (不变量① + PG 并行轨)。

== 它解决什么 (已 LIVE 的回归) ==
本 session 给 concern 加了 severity 时间半衰 (commit eec9648) + habituation (be4cad5)
= 体只有"健忘"侧, 没有"未解决时长"反向力 → **严重但拖久的真问题被过早遗忘**风险此刻
真实存在。但裸时间标量 (未解时长→继续倾斜) 会把反刍 (也"未解+拖久") 喂回来。

== 不变量① 的解 (否决裸标量) ==
时间从来只是"这事在世界里还真的开着"的代理变量。本门切掉代理、直接咬本体:
  **默认衰减 (decay) UNLESS 一个机器可核的世界事实谓词证明此事 still-open。**
反刍 = 没有新外部输入却自激的环 → 无 still-open 谓词 → 默认衰减 (不复活)。
真问题 (账单还 fail / deadline 还在未来 / 体检还没做 / 承诺还开着) → 谓词 still-open
→ 抗衰减保持 → 顶住, 直到世界事实了结 (账单付了/体检做了), 倾斜自然松开。

== 两条焊死的护栏 ==
(a) 默认衰减: 无谓词 / 谓词 not-open / 不可判 → 一律走默认衰减 (安全侧)。
(b) 机器可核优先: still-open 只认可机器核验的 backstop (commitment_watcher / date_compare
    / external_state / claim_tracer)。**绝不靠 LLM 判"还开着"** — 否则反刍借幻觉的
    "还开着"从后门复活 (Property 3)。

== 副产物 ==
让体的情绪可信: 顶住一件事是因为那事真没完 (有外部活证据), 既不是固执 (固着) 也不是
健忘。

== 准则 ==
1 (TTFT): 纯机器判定, 无 LLM, 后台 decay 路径调, 不碰主脑热路径。
5 (接地): 每次 still-open 带 evidence_ref (谓词名 + 取值来源)。
6 (vocab): 谓词注册表 memory_pool/grounded_predicates_vocab.json + CLI scripts/grounded_predicates_dump.py。
8 (优雅): 布尔门, 非标量最优 (红线A: 不引入 argmax/utility)。A 层 (想哪块), 不碰 C 层 (守哪堵墙)。
"""
from __future__ import annotations

import os  # noqa: F401
import sys  # noqa: F401
import json
import time
import threading
from typing import Any, Dict, List, Optional, Tuple


def _log(msg: str) -> None:
    try:
        from jarvis_utils import bg_log
        bg_log(msg)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 谓词注册表 — 准则 6 持久化 (seed 默认 + json override, mtime cache)
# ---------------------------------------------------------------------------
# 每个谓词: {id, applies_to_kind, match, backstop, enabled}
#   - applies_to_kind: 'concern' (现仅 concern; 未来可扩 thread/...)
#   - match: 限定哪些节点适用 (concern_id_pattern 正则 / has_field 字段存在)
#   - backstop: 机器求值器名 (见 _BACKSTOPS) — 决定 still-open 怎么机器核验
#   - enabled: 关掉某谓词
# 顺序求值, 任一 backstop 判 still-open 即 still-open (OR 语义)。
_SEED_PREDICATES: Dict[str, Any] = {
    "version": 1,
    "_doc": (
        "接地谓词门: 默认衰减 UNLESS 机器可核谓词证明 still-open。绝不靠 LLM。"
        "公理 docs/AGENT_KICKOFF_BODY_DIFFERENTIATION.md 不变量①。"
    ),
    "enabled": True,
    "predicates": [
        {
            "id": "deadline_future",
            "applies_to_kind": "concern",
            "match": {"has_field": "deadline_ts"},
            "backstop": "date_compare",
            "enabled": True,
            "_note": "concern.deadline_ts > now → 此事 deadline 还在未来 = 仍开着",
        },
        {
            "id": "commitment_open",
            "applies_to_kind": "concern",
            "match": {"concern_id_pattern": ".*"},
            "backstop": "commitment_watcher",
            "enabled": True,
            "_note": "有 active 未履约承诺 concern_link 指向此 concern = 仍开着",
        },
        {
            "id": "external_state_open",
            "applies_to_kind": "concern",
            "match": {"has_field": "external_state"},
            "backstop": "external_state",
            "enabled": True,
            "_note": "concern.external_state == 'open' (账单 fail flag 等) = 仍开着",
        },
    ],
}

_PRED_PATH = os.path.join("memory_pool", "grounded_predicates_vocab.json")
_PRED_CACHE: Optional[Dict[str, Any]] = None
_PRED_MTIME: float = 0.0
_LOCK = threading.RLock()


def _load_predicates() -> Dict[str, Any]:
    """读谓词注册表 (seed 默认, json override)。mtime cache。失败 fallback seed。"""
    global _PRED_CACHE, _PRED_MTIME
    with _LOCK:
        try:
            mtime = os.path.getmtime(_PRED_PATH) if os.path.exists(_PRED_PATH) else 0.0
        except OSError:
            mtime = 0.0
        if _PRED_CACHE is None or mtime > _PRED_MTIME:
            doc = json.loads(json.dumps(_SEED_PREDICATES))  # deep copy seed
            try:
                if os.path.exists(_PRED_PATH):
                    with open(_PRED_PATH, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        # 顶层开关可覆盖; predicates 整列可覆盖 (Sir CLI 增删)
                        if "enabled" in data:
                            doc["enabled"] = data["enabled"]
                        if isinstance(data.get("predicates"), list):
                            doc["predicates"] = data["predicates"]
            except Exception:
                doc = json.loads(json.dumps(_SEED_PREDICATES))
            _PRED_CACHE = doc
            _PRED_MTIME = mtime
        return _PRED_CACHE


def reset_cache_for_test() -> None:
    global _PRED_CACHE, _PRED_MTIME
    with _LOCK:
        _PRED_CACHE = None
        _PRED_MTIME = 0.0


# ---------------------------------------------------------------------------
# Backstop 求值器 — 全部机器可核, 无 LLM (护栏 b / Property 3)
# 每个返 (still_open: bool, evidence_ref: str)。判不定 / 异常 → (False, '')。
# ---------------------------------------------------------------------------

def _backstop_date_compare(concern: Any, now: float) -> Tuple[bool, str]:
    """concern.deadline_ts > now → deadline 还在未来 = 仍开着 (纯日期比较)。"""
    ts = _get_field(concern, "deadline_ts", 0.0)
    try:
        ts = float(ts or 0.0)
    except (TypeError, ValueError):
        return (False, "")
    if ts > now:
        iso = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        return (True, f"date_compare:deadline_ts={iso}>now")
    return (False, "")


def _backstop_external_state(concern: Any, now: float) -> Tuple[bool, str]:
    """concern.external_state == 'open' (账单仍 fail 等外部状态字段)。"""
    st = _get_field(concern, "external_state", "")
    if isinstance(st, str) and st.strip().lower() == "open":
        return (True, "external_state:open")
    return (False, "")


def _backstop_commitment_watcher(concern: Any, now: float) -> Tuple[bool, str]:
    """有 active 未履约承诺 concern_link 指向此 concern = 仍开着 (扫 CommitmentWatcher)。"""
    cid = _get_field(concern, "id", "")
    if not cid:
        return (False, "")
    watcher = None
    try:
        import jarvis_central_nerve as _cn
        nerve = getattr(_cn, "_GLOBAL_NERVE", None)
        watcher = getattr(nerve, "commitment_watcher", None) if nerve else None
    except Exception:
        watcher = None
    if watcher is None:
        return (False, "")
    try:
        commitments = list(getattr(watcher, "commitments", []) or [])
    except Exception:
        return (False, "")
    for c in commitments:
        if not isinstance(c, dict):
            continue
        # 已履约 / 已 fulfilled → 不算开着
        if c.get("fulfilled") or c.get("nudged") and c.get("fulfillment_checked"):
            continue
        link = (c.get("concern_link") or "").strip()
        if link and link == cid:
            desc = (c.get("description") or "")[:40]
            return (True, f"commitment_watcher:open_commitment='{desc}'")
    return (False, "")


def _backstop_claim_tracer(concern: Any, now: float) -> Tuple[bool, str]:
    """有未核销 claim 关联此 concern (ClaimTracer)。保守: 模块不可用 → not-open。"""
    # ClaimTracer 接口随版本变, 保守只在明确可用时判; 否则默认 not-open (安全侧)。
    cid = _get_field(concern, "id", "")
    if not cid:
        return (False, "")
    try:
        from jarvis_claim_tracer import get_open_claims_for_concern  # type: ignore
    except Exception:
        return (False, "")
    try:
        claims = get_open_claims_for_concern(cid) or []
        if claims:
            return (True, f"claim_tracer:open_claims={len(claims)}")
    except Exception:
        pass
    return (False, "")


_BACKSTOPS = {
    "date_compare": _backstop_date_compare,
    "external_state": _backstop_external_state,
    "commitment_watcher": _backstop_commitment_watcher,
    "claim_tracer": _backstop_claim_tracer,
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _get_field(concern: Any, name: str, default: Any = None) -> Any:
    """concern 可能是 dataclass 实例或 dict — 统一取字段。"""
    if concern is None:
        return default
    if isinstance(concern, dict):
        return concern.get(name, default)
    return getattr(concern, name, default)


def _match(pred: Dict[str, Any], concern: Any) -> bool:
    """谓词 match 限定: applies_to_kind + concern_id_pattern / has_field。"""
    m = pred.get("match") or {}
    # has_field: concern 必须有该字段且非空
    hf = m.get("has_field")
    if hf:
        v = _get_field(concern, hf, None)
        if v in (None, "", 0, 0.0):
            return False
    # concern_id_pattern: 正则匹配 concern id
    pat = m.get("concern_id_pattern")
    if pat:
        import re
        cid = str(_get_field(concern, "id", "") or "")
        try:
            if not re.search(pat, cid):
                return False
        except re.error:
            return False
    return True


# ---------------------------------------------------------------------------
# 门 API
# ---------------------------------------------------------------------------

def is_still_open(concern: Any, *, now: Optional[float] = None) -> Tuple[bool, str]:
    """接地谓词门核心判定。返 (still_open, evidence_ref)。

    护栏 (a) 默认衰减: 门关 / 无适用谓词 / 全 backstop 判 not-open → (False, '')。
    护栏 (b) 机器可核: 只走 _BACKSTOPS 机器求值器, 无 LLM 分支。
    准则 5: still-open 必带 evidence_ref (谓词 id + backstop 取值来源)。

    OR 语义: 任一适用谓词的 backstop 判 still-open → still-open (此事确有一条活证据)。
    """
    now = time.time() if now is None else now
    try:
        doc = _load_predicates()
        if not doc.get("enabled", True):
            return (False, "")
        kind_of = "concern"  # 现仅 concern (未来可由调用方传 kind)
        for pred in doc.get("predicates", []):
            if not isinstance(pred, dict):
                continue
            if not pred.get("enabled", True):
                continue
            if pred.get("applies_to_kind", "concern") != kind_of:
                continue
            if not _match(pred, concern):
                continue
            bs = _BACKSTOPS.get(pred.get("backstop", ""))
            if bs is None:
                continue  # 未知 backstop → 跳 (不当 still-open, 安全侧)
            try:
                ok, ev = bs(concern, now)
            except Exception:
                ok, ev = (False, "")
            if ok:
                return (True, f"{pred.get('id', '?')}|{ev}")
        return (False, "")
    except Exception as exc:
        _log(f"[GroundedGate] is_still_open exception ({exc!r}) → 默认衰减")
        return (False, "")


def gate_stats() -> Dict[str, Any]:
    """CLI / dashboard 用 — 当前谓词注册表概览。"""
    doc = _load_predicates()
    preds = doc.get("predicates", [])
    return {
        "enabled": doc.get("enabled", True),
        "predicate_count": len(preds),
        "predicates": [
            {"id": p.get("id"), "backstop": p.get("backstop"),
             "enabled": p.get("enabled", True),
             "applies_to_kind": p.get("applies_to_kind", "concern")}
            for p in preds if isinstance(p, dict)
        ],
        "backstops_available": sorted(_BACKSTOPS.keys()),
    }
