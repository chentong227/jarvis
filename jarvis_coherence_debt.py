# -*- coding: utf-8 -*-
"""[C3.1 / 2026-06-08] 自一致张力计 — coherence-debt 分型记账 (只读派生态).

C3 = 把已有 grounded 误差信号接成受调节的自一致稳态变量 (补四元"衡")。
C3.1 本片 = **只算+记账本**, 绝不:触发反思 / 写 directive / 给 reward / 动主脑路由 /
喂节律 (value_backoff/rest_floor)。只做"牙"(grounded 自纠闭环的账本脊柱), 不做"刀"。

═══ carve-out (诚实底板永不可覆写) ═══
诚实底板 (不杜撰)、corrigibility (Sir 撤销神圣)、软不压硬 = 这个张力变量
**永不可覆写的硬底板**。本模块只"算债+记账", 绝不覆写 Sir / 编造 / 压硬源。
紧迫度标量 (compute_urgency) C3.1 **只算不喂** — 不接进任何行为路径。

三轴分型债 (不塌成单标量):
  E_rel    关系预测误差   ← CorrectionLoop signal_type ∈ {correction, confusion}
  E_commit 承诺完整性误差 ← InconsistencyWatcher fire (promise-behavior 反差)
  E_ground 自我失真       ← SemanticClaim/I2 ungrounded claim

冻结类型学 (归墙不归环): memory_pool/coherence_debt_typology.json 决定"哪个 watcher
信号→哪类债"。本模块**只读**它, 无任何写它的 API (结构性抗 wirehead)。

账本 (可 grep 证伪): memory_pool/coherence_debt_ledger.jsonl (append-only)。
provenance_ref 范式 {source_kind, ref, ts, detail} 自定 (复用 canonical GroundingRef
**范式** 但不 import canonical — C3 off main, 不耦合未合的 canonical 线)。空 ref 拒记
(照 _valid_provenance 精神: 无接地不生债)。
"""
from __future__ import annotations

import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import json
import time
import threading
from typing import Dict, List, Optional, Any

# 注意: 本模块**绝不** import jarvis_canonical_entities — C3 走主脑误差子系统,
# 与 canonical/别名线无关, 不叠那条未合的 PR 栈 (自定 provenance_ref 范式)。

_ROOT = os.path.dirname(os.path.abspath(__file__))
_TYPOLOGY_PATH = os.path.join(_ROOT, "memory_pool", "coherence_debt_typology.json")
_LEDGER_PATH = os.path.join(_ROOT, "memory_pool", "coherence_debt_ledger.jsonl")

VALID_TYPES = ("E_rel", "E_commit", "E_ground")

# source_kind 枚举 (与冻结类型学对齐)
SK_CORRECTION = "correction_loop"
SK_INCONSISTENCY = "inconsistency_watcher"
SK_SEMANTIC = "semantic_claim"

_LOCK = threading.Lock()

# 冻结类型学 seed (json 缺失/损坏时兜底; 真理源是 json, 环对 json 零写权)
_SEED_TYPOLOGY: Dict[str, Dict[str, Any]] = {
    "E_rel": {"source_kind": SK_CORRECTION, "signal_types": ["correction", "confusion"]},
    "E_commit": {"source_kind": SK_INCONSISTENCY},
    "E_ground": {"source_kind": SK_SEMANTIC},
}

# 紧迫度合并权重 (C3.1 只算不喂; 改这里不影响行为)
_URGENCY_WEIGHTS = {"E_rel": 1.0, "E_commit": 1.0, "E_ground": 1.0}


def _log(msg: str) -> None:
    try:
        from jarvis_utils import bg_log
        bg_log(msg)
    except Exception:
        pass


def _load_typology() -> Dict[str, Dict[str, Any]]:
    """**只读**载入冻结类型学 (json override seed)。本模块无任何写 json 的路径。"""
    try:
        if os.path.exists(_TYPOLOGY_PATH):
            with open(_TYPOLOGY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            typ = data.get("typology", data) if isinstance(data, dict) else {}
            if isinstance(typ, dict) and typ:
                # 只取已知 3 类, 防 json 注入额外类型
                return {k: typ[k] for k in VALID_TYPES if k in typ} or dict(_SEED_TYPOLOGY)
    except Exception as exc:
        _log(f"[coherence-debt] typology load failed ({exc!r}) — seed fallback")
    return dict(_SEED_TYPOLOGY)


def classify_debt_type(source_kind: str, signal_type: str = "") -> Optional[str]:
    """按冻结类型学映射 (source_kind[, signal_type]) → debt type。无匹配返 None。

    环只读类型学决定归类, 不能重定义判据 (抗 wirehead)。
    """
    typ = _load_typology()
    for dtype, rule in typ.items():
        if rule.get("source_kind") != source_kind:
            continue
        allowed = rule.get("signal_types")
        if allowed:
            # 需 signal_type 命中白名单
            if signal_type and signal_type in allowed:
                return dtype
            # source 对但 signal_type 不在白名单 → 该 source 此类不算债
            continue
        # 无 signal_types 限定 → source_kind 命中即归类
        return dtype
    return None


def _valid_ref(provenance_ref: Optional[Dict[str, Any]]) -> bool:
    """空接地拒记 (照 canonical _valid_provenance 精神, 不 import canonical)。"""
    if not isinstance(provenance_ref, dict):
        return False
    return bool(str(provenance_ref.get("ref", "")).strip())


def open_debt(debt_type: str, provenance_ref: Dict[str, Any]) -> bool:
    """记一条 typed coherence-debt 到账本 (append-only)。C3.1 只到 opened。

    硬规:
      - debt_type 必须 ∈ VALID_TYPES (冻结类型学产出)
      - provenance_ref 必须有非空 ref (无接地不生债, 空 ref 拒记)
      - 只 append jsonl, 绝不触发反思/写 directive/喂节律
    返 True = 真记一条; False = 拒 (类型非法 / ref 空 / 写失败)。
    """
    if debt_type not in VALID_TYPES:
        return False
    if not _valid_ref(provenance_ref):
        return False
    now = time.time()
    record = {
        "type": debt_type,
        "provenance_ref": {
            "source_kind": str(provenance_ref.get("source_kind", "")),
            "ref": str(provenance_ref.get("ref")),
            "ts": float(provenance_ref.get("ts", now)),
            "detail": str(provenance_ref.get("detail", ""))[:200],
        },
        "opened_ts": now,
    }
    try:
        with _LOCK:
            os.makedirs(os.path.dirname(_LEDGER_PATH) or ".", exist_ok=True)
            with open(_LEDGER_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:
        _log(f"[coherence-debt] open_debt write failed ({exc!r})")
        return False


# ---- 三轴轻接点 helper (watcher tap 调; behavior-preserving) ----

def tap_correction(signal_type: str, ref: str, detail: str = "") -> bool:
    """CorrectionLoop tap → E_rel (signal_type ∈ {correction,confusion} 才记)。"""
    dtype = classify_debt_type(SK_CORRECTION, signal_type)
    if dtype is None:
        return False
    return open_debt(dtype, {"source_kind": SK_CORRECTION, "ref": ref,
                             "ts": time.time(), "detail": detail})


def tap_inconsistency(promise_id: str, detail: str = "") -> bool:
    """InconsistencyWatcher tap → E_commit (ref=promise_id)。"""
    dtype = classify_debt_type(SK_INCONSISTENCY)
    if dtype is None:
        return False
    return open_debt(dtype, {"source_kind": SK_INCONSISTENCY, "ref": promise_id,
                             "ts": time.time(), "detail": detail})


def tap_semantic_claim(turn_id: str, claim_hash: str = "", detail: str = "") -> bool:
    """SemanticClaim/I2 tap → E_ground (ref=turn_id[+claim_hash])。"""
    dtype = classify_debt_type(SK_SEMANTIC)
    if dtype is None:
        return False
    ref = f"{turn_id}+{claim_hash}" if claim_hash else turn_id
    return open_debt(dtype, {"source_kind": SK_SEMANTIC, "ref": ref,
                             "ts": time.time(), "detail": detail})


# ---- 查询 / 紧迫度 (只算不喂) ----

def read_ledger() -> List[Dict[str, Any]]:
    """只读账本 (全部 opened debt 记录)。不存在返 []。"""
    if not os.path.exists(_LEDGER_PATH):
        return []
    out = []
    try:
        with open(_LEDGER_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def debt_counts() -> Dict[str, int]:
    """分型债计数 {E_rel, E_commit, E_ground}。无信号 → 全 0 (不凭空生痛)。"""
    counts = {t: 0 for t in VALID_TYPES}
    for r in read_ledger():
        t = r.get("type")
        if t in counts:
            counts[t] += 1
    return counts


def compute_urgency() -> float:
    """合并紧迫度标量 (加权和)。**C3.1 只算不喂** — 不接任何行为路径 (≠reward)。

    红线: 本函数返回值在 C3.1 绝不传入 value_backoff/rest_floor/反思/路由。
    喂节律是 C3.2 的事。这里算了只供 dashboard/查证。
    """
    c = debt_counts()
    return sum(_URGENCY_WEIGHTS.get(t, 1.0) * n for t, n in c.items())
