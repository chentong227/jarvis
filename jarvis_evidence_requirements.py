# -*- coding: utf-8 -*-
"""
[P0+20-β.4.3.2 / 2026-05-18] INTEGRITY_STACK L2 — Evidence Requirements

把每个 ClaimType (6 类 + Unknown) 应当接受的 evidence_kinds 列表持久化到 json,
让 L4 trace_to_evidence 表驱动 verify 而不再 hardcode past_action 分支.

设计准则 (Sir 准则 6 / 6.5):
  - vocab 持久化 memory_pool/evidence_requirements.json
  - CLI scripts/evidence_req_dump.py
  - L7 LLM-propose: WeeklyReflector 看 audit unverify 率反推 evidence path 缺漏
  - py-side seed fallback (vocab 缺/损时仍 work)
  - mtime cache

evidence_kinds 枚举 (与 json _meta.evidence_kinds_canonical 同步):
  - tool_results_success         tool_results 含 ✅ marker (Past-action 治本)
  - tool_results_any             tool_results 任一含 claim text 子串
  - stm_match                    STM entry 含命中
  - ltm_match                    ltm_context 含命中
  - system_clock_within_2min     time claim 与 SYSTEM CLOCK diff <= 2 min (β.4.2 治本)
  - promise_log_recorded         本轮 jarvis_reply 含 <PROMISE> tag (Future evidence)
  - uncertainty_marker_nearby    claim 附近含 hedge (β.2.8.7 已有)
  - none                         永远 pass (Unknown 不 audit)

防恶性耦合 BUG (β.4.2-hotfix 教训):
  - Unknown 类 evidence_kinds = []: claim 走 L4 trace 时 → 空 list → 视为 verified
    (理由: L1 没分到任何类的 claim 不应进 audit 死循环路径)
  - 任何异常 (vocab 损坏 / IO 错误 / claim_type 不存在) → seed fallback 不 raise
  - 新参数全部 Optional, 老调用方零修改

API:
  get_requirements(claim_type, vocab_path=None) -> List[str]
  get_evidence_requirements_vocab(path=None) -> dict
"""

from __future__ import annotations

import json
import os
import threading
from typing import Dict, List, Optional

try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(msg: str) -> None:
        print(msg)


_VOCAB_PATH = os.path.join('memory_pool', 'evidence_requirements.json')

_CACHE_LOCK = threading.Lock()
_VOCAB_CACHE: Dict[str, object] = {
    'path': '',
    'mtime': 0.0,
    'data': None,
}

EVIDENCE_KINDS_CANONICAL = (
    'tool_results_success',
    'tool_results_success_domain_scoped',
    'tool_results_any',
    'stm_match',
    'ltm_match',
    'system_clock_within_2min',
    'promise_log_recorded',
    'uncertainty_marker_nearby',
    'none',
)


# ============================================================
# Seed vocab (py-side fallback)
# ============================================================

_SEED_VOCAB: Dict[str, object] = {
    '_meta': {'schema_version': 1, 'source': 'seed_py_fallback'},
    'patterns': [
        {
            'id': 'past_default',
            'claim_type': 'Past',
            'accepted_evidence_kinds': [
                'tool_results_success_domain_scoped', 'uncertainty_marker_nearby',
            ],
            'state': 'active',
        },
        {
            'id': 'future_default',
            'claim_type': 'Future',
            'accepted_evidence_kinds': [
                'promise_log_recorded', 'uncertainty_marker_nearby',
            ],
            'state': 'active',
        },
        {
            'id': 'state_default',
            'claim_type': 'State',
            'accepted_evidence_kinds': [
                'system_clock_within_2min', 'tool_results_any',
                'stm_match', 'ltm_match', 'uncertainty_marker_nearby',
            ],
            'state': 'active',
        },
        {
            'id': 'recall_default',
            'claim_type': 'Recall',
            'accepted_evidence_kinds': [
                'stm_match', 'ltm_match', 'uncertainty_marker_nearby',
            ],
            'state': 'active',
        },
        {
            'id': 'social_default',
            'claim_type': 'Social',
            'accepted_evidence_kinds': [
                'ltm_match', 'stm_match', 'uncertainty_marker_nearby',
            ],
            'state': 'active',
        },
        {
            'id': 'tool_default',
            'claim_type': 'Tool',
            'accepted_evidence_kinds': [
                'tool_results_any', 'uncertainty_marker_nearby',
            ],
            'state': 'active',
        },
        {
            'id': 'unknown_failsafe',
            'claim_type': 'Unknown',
            'accepted_evidence_kinds': [],
            'state': 'active',
        },
    ],
}


# ============================================================
# Loader (mtime cache)
# ============================================================

def get_evidence_requirements_vocab(path: Optional[str] = None) -> dict:
    """读 vocab json. 带 mtime cache. 缺/损返 _SEED_VOCAB 不 raise."""
    p = path or _VOCAB_PATH
    if not os.path.exists(p):
        return _SEED_VOCAB
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return _SEED_VOCAB
    with _CACHE_LOCK:
        if (_VOCAB_CACHE['path'] == p
                and float(_VOCAB_CACHE['mtime']) == mt
                and _VOCAB_CACHE['data'] is not None):
            return _VOCAB_CACHE['data']  # type: ignore[return-value]
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict) or 'patterns' not in data:
                raise ValueError('vocab missing patterns key')
            _VOCAB_CACHE['path'] = p
            _VOCAB_CACHE['mtime'] = mt
            _VOCAB_CACHE['data'] = data
            return data
        except (OSError, ValueError, TypeError) as e:
            try:
                bg_log(f"⚠️ [EvidenceReq] vocab load failed "
                       f"({type(e).__name__}: {str(e)[:60]}), fallback to seed")
            except Exception:
                pass
            return _SEED_VOCAB


def _active_patterns(vocab: dict) -> List[dict]:
    """筛 state=active patterns."""
    patterns = vocab.get('patterns', []) if isinstance(vocab, dict) else []
    out: List[dict] = []
    for p in patterns:
        if not isinstance(p, dict):
            continue
        if p.get('state', 'active') == 'active':
            out.append(p)
    return out


# ============================================================
# Public API
# ============================================================

def get_requirements(claim_type: str,
                       vocab_path: Optional[str] = None) -> List[str]:
    """返该 claim_type 的 accepted_evidence_kinds 列表 (union 同 claim_type 多 pattern).

    Args:
      claim_type: 'Past' | 'Future' | 'State' | 'Recall' | 'Social' | 'Tool' | 'Unknown'
      vocab_path: testcase 注入用. 不传走全局 _VOCAB_PATH.

    Returns:
      List[str] of evidence_kind. 找不到该 claim_type 也返 [] (fail-safe, 不 raise).
      Unknown 类型显式返 [] (设计约定: L4 trace 视为 verified 不 audit).
    """
    if not claim_type:
        return []
    try:
        vocab = get_evidence_requirements_vocab(vocab_path)
        patterns = _active_patterns(vocab)
    except Exception:
        return []

    # union 同 claim_type 多 pattern
    seen: List[str] = []
    for p in patterns:
        if p.get('claim_type') != claim_type:
            continue
        kinds = p.get('accepted_evidence_kinds', []) or []
        if not isinstance(kinds, list):
            continue
        for k in kinds:
            if isinstance(k, str) and k in EVIDENCE_KINDS_CANONICAL and k not in seen:
                seen.append(k)
    return seen


def get_loaded_stats(vocab_path: Optional[str] = None) -> dict:
    """诊断 stats. dashboard / debug 用."""
    vocab = get_evidence_requirements_vocab(vocab_path)
    patterns = vocab.get('patterns', []) if isinstance(vocab, dict) else []
    by_type: Dict[str, int] = {}
    for p in patterns:
        if not isinstance(p, dict):
            continue
        if p.get('state', 'active') != 'active':
            continue
        ct = p.get('claim_type', '?')
        kinds = p.get('accepted_evidence_kinds', []) or []
        by_type[ct] = by_type.get(ct, 0) + len(kinds)
    return {
        'source': 'json' if vocab is not _SEED_VOCAB else 'seed',
        'total_patterns': len(patterns),
        'active_patterns': len([p for p in patterns
                                  if isinstance(p, dict)
                                  and p.get('state', 'active') == 'active']),
        'by_type_evidence_count': by_type,
    }
