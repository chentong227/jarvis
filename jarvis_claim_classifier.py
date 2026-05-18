# -*- coding: utf-8 -*-
"""
[P0+20-β.4.3.1 / 2026-05-18] INTEGRITY_STACK L1 — Claim Classifier

把 ClaimTracer (β.2.8.7) 抽出的细粒度 kind (time/past_action/count/percent/quote/multiplier)
映射到粗粒度 ClaimType (Past/Future/State/Recall/Social/Tool), 供 L2 EvidenceRequirements
表查 → L4 trace_to_evidence 走表驱动 verify, 不再 hardcode past_action regex.

设计准则 (Sir 准则 6 / 6.5):
  - vocab 持久化 memory_pool/claim_classify_vocab.json
  - CLI scripts/claim_classify_dump.py (list/add/activate/reject/delete)
  - L7 LLM-propose 入口预留 (reflector future)
  - py-side seed fallback (vocab 缺/损时仍 work)
  - mtime cache (vocab 改不需要重启 Jarvis)

防恶性耦合 BUG 设计 (β.4.2-hotfix 教训内化):
  - 任何异常 (vocab 损坏 / IO 错误 / keyword 类型错) → 走 seed fallback, 不 raise
  - text 空/None → 'Unknown' (调用方决定 fail-safe 行为)
  - 多 type 命中: patterns list 顺序即优先级 (Past > Future > State > Recall > Social > Tool 是 seed 默认)
  - performance ≤ 5ms (短 reply <500 chars + 7 type × ~30 keyword 简单 substring 扫)

API:
  classify(text, kind=None, vocab_path=None) -> str
    返 'Past' | 'Future' | 'State' | 'Recall' | 'Social' | 'Tool' | 'Unknown'

  get_classify_vocab(path=None) -> dict
    带 mtime cache. 缺/损返 _SEED_VOCAB.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Dict, List, Optional

try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(msg: str) -> None:
        print(msg)


_VOCAB_PATH = os.path.join('memory_pool', 'claim_classify_vocab.json')

_CACHE_LOCK = threading.Lock()
_VOCAB_CACHE: Dict[str, object] = {
    'path': '',
    'mtime': 0.0,
    'data': None,
}

CLAIM_TYPE_UNKNOWN = 'Unknown'
CLAIM_TYPES_CANONICAL = ('Past', 'Future', 'State', 'Recall', 'Social', 'Tool')


# ============================================================
# Seed vocab (py-side fallback when json missing/corrupt)
# ------------------------------------------------------------
# 与 memory_pool/claim_classify_vocab.json patterns 内容保持一致.
# vocab json 是 source of truth; seed 仅在 IO 失败时兜底.
# ============================================================

_SEED_VOCAB: Dict[str, object] = {
    '_meta': {'schema_version': 1, 'source': 'seed_py_fallback'},
    'patterns': [
        {
            'id': 'past_default',
            'claim_type': 'Past',
            'kinds_hard_map': ['past_action'],
            'keywords': [
                'already', "i've", 'i have', 'i opened', 'i launched',
                'i started', 'i closed', 'i muted', 'i sent', 'i set',
                'i updated', 'i saved', 'i deleted', 'i cancelled',
                '已经', '已', '完成了', '做完了', '刚才完成',
                '刚搞定', '处理完了',
            ],
            'state': 'active',
        },
        {
            'id': 'future_default',
            'claim_type': 'Future',
            'kinds_hard_map': [],
            'keywords': [
                'i will', "i'll", 'i plan', "i'm going to", 'let me',
                "i'll try", "i'll see", 'i can take', 'i can do',
                "i'll set", "i'll look", "i'll check", "i'll get back",
                'let me know',
                '我会', '我准备', '我打算', '我之后', '稍后我',
                '我去做', '我看看', '我尝试', '我帮你', '我帮您',
                '等我',
            ],
            'state': 'active',
        },
        {
            'id': 'recall_default',
            'claim_type': 'Recall',
            'kinds_hard_map': ['quote'],
            'keywords': [
                'you said', 'you told me', 'you mentioned', 'you noted',
                'as you said', 'as you mentioned', 'you recall',
                '您说', '您说过', '您告诉我', '您提到', '您表示',
                '我记得您', '正如您说', '您之前说',
            ],
            'state': 'active',
        },
        {
            'id': 'social_default',
            'claim_type': 'Social',
            'kinds_hard_map': [],
            'keywords': [
                'you like', 'you prefer', 'you enjoy', 'you tend to',
                'you usually', 'you always', 'you never', 'you typically',
                'sir likes', 'sir prefers',
                '您喜欢', '您偏爱', '您习惯', '您通常', '您总是',
                '您从不', '您往往',
            ],
            'state': 'active',
        },
        {
            # Tool 必须在 State_quant 之前 (β.4.3.4 教训: "正在" 过广吐后 State 抢)
            'id': 'tool_default',
            'claim_type': 'Tool',
            'kinds_hard_map': [],
            'keywords': [
                'opening', 'launching', 'calling', 'executing', 'running',
                'fetching', 'querying', 'pulling up', 'checking',
                '正在打开', '正在调用', '正在执行', '正在运行',
                '正在查', '在打开', '在调用', '在查',
                '帮您打开', '帮您查',
            ],
            'state': 'active',
        },
        {
            'id': 'state_time_default',
            'claim_type': 'State',
            'kinds_hard_map': ['time'],
            'keywords': [],
            'state': 'active',
        },
        {
            'id': 'state_quant_default',
            'claim_type': 'State',
            'kinds_hard_map': ['percent', 'multiplier', 'count'],
            'keywords': [
                'is currently', 'currently', 'right now',
                '处于', '当前状态', '目前状态',
                '状态是', '数据显示', 'stats show',
            ],
            'state': 'active',
        },
    ],
}


# ============================================================
# Vocab loader (mtime cache)
# ============================================================

def get_classify_vocab(path: Optional[str] = None) -> dict:
    """读 vocab json. 带 mtime cache. 缺/损返 _SEED_VOCAB 不 raise.

    并发安全: _CACHE_LOCK 包 read-modify-write of _VOCAB_CACHE.
    """
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
                bg_log(f"⚠️ [ClaimClassifier] vocab load failed ({type(e).__name__}: "
                       f"{str(e)[:60]}), fallback to seed")
            except Exception:
                pass
            return _SEED_VOCAB


def _active_patterns(vocab: dict) -> List[dict]:
    """筛 state=active patterns. 防 archived/review 干扰 classify."""
    patterns = vocab.get('patterns', []) if isinstance(vocab, dict) else []
    out: List[dict] = []
    for p in patterns:
        if not isinstance(p, dict):
            continue
        if p.get('state', 'active') == 'active':
            out.append(p)
    return out


# ============================================================
# Classifier
# ============================================================

def classify(text: str, kind: Optional[str] = None,
              vocab_path: Optional[str] = None) -> str:
    """分类 claim → ClaimType 6 类 (或 'Unknown').

    Args:
      text: claim text (extract_claims 抽出来的字串, 含上下文如 "已打开 dashboard")
      kind: extract_claims 给的细粒度 kind ('past_action'/'time'/...) — 可空
      vocab_path: testcase 注入用. 不传走全局 _VOCAB_PATH.

    Returns:
      'Past' | 'Future' | 'State' | 'Recall' | 'Social' | 'Tool' | 'Unknown'

    算法 (顺序即优先级):
      1. kind 非空且命中某 pattern 的 kinds_hard_map → 返该 pattern.claim_type
      2. 否则按 patterns list 顺序扫 keywords, lower(text) 含任一 → 返该 claim_type
      3. 都没命中 → 'Unknown'
    """
    if text is None and not kind:
        return CLAIM_TYPE_UNKNOWN
    try:
        vocab = get_classify_vocab(vocab_path)
        patterns = _active_patterns(vocab)
    except Exception:
        # 严守 fail-safe: 任何异常返 Unknown, 主路径不卡
        return CLAIM_TYPE_UNKNOWN

    text_l = (text or '').lower()

    # 阶段 1: kind hard_map (优先级最高)
    if kind:
        for p in patterns:
            hm = p.get('kinds_hard_map', []) or []
            if isinstance(hm, list) and kind in hm:
                ct = p.get('claim_type', CLAIM_TYPE_UNKNOWN)
                return ct if ct in CLAIM_TYPES_CANONICAL else CLAIM_TYPE_UNKNOWN

    # 阶段 2: keywords substring 扫
    if text_l:
        for p in patterns:
            kws = p.get('keywords', []) or []
            if not isinstance(kws, list):
                continue
            for kw in kws:
                if not kw or not isinstance(kw, str):
                    continue
                if kw.lower() in text_l:
                    ct = p.get('claim_type', CLAIM_TYPE_UNKNOWN)
                    return ct if ct in CLAIM_TYPES_CANONICAL else CLAIM_TYPE_UNKNOWN

    return CLAIM_TYPE_UNKNOWN


# ============================================================
# Diagnostics
# ============================================================

def get_loaded_stats(vocab_path: Optional[str] = None) -> dict:
    """返 loader 状态 (供 dashboard / debug 显示)."""
    vocab = get_classify_vocab(vocab_path)
    patterns = vocab.get('patterns', []) if isinstance(vocab, dict) else []
    by_type: Dict[str, int] = {}
    for p in patterns:
        if not isinstance(p, dict):
            continue
        if p.get('state', 'active') != 'active':
            continue
        ct = p.get('claim_type', '?')
        kws = p.get('keywords', []) or []
        hm = p.get('kinds_hard_map', []) or []
        by_type[ct] = by_type.get(ct, 0) + len(kws) + len(hm)
    return {
        'source': 'json' if vocab is not _SEED_VOCAB else 'seed',
        'total_patterns': len(patterns),
        'active_patterns': len([p for p in patterns
                                  if isinstance(p, dict)
                                  and p.get('state', 'active') == 'active']),
        'by_type_terms': by_type,
    }
