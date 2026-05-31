# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 21:45 真测 BUG-H 治本] Mutation Evidence Guard.

Sir 真测 (21:07 jarvis_2026.log Turn ?? "d home" → "Stay safe" 幻觉):
  事实链:
    1. Sir 说 "d home, 钢铁侠电影里那句话" (想说 "I am home")
    2. Jarvis 凭空答 "Stay safe"
    3. Jarvis 自动调 worker.memory_correction →
       MemoryGateway.update_sir_field('profile.idiosyncrasies',
       "Sir frequently references the 'Stay safe' quote from Avenger")
    4. sir_profile.json 真被污染 (mut_be4efe2dfe)
  违反准则 5 (INTEGRITY) + 准则 6 (any specific factual claim → trace evidence).

治本 (准则 8 优雅): 集中 guard 在 MemoryGateway 入口 (一处), 不在每个 caller
散落:
  - 对每个 new_value, 检 Sir 最近 N turn STM 中是否真有相关 evidence
  - 不达 → block + audit log + publish SWM 'mutation_evidence_blocked'
  - 达 → 正常 mutation + publish 'mutation_evidence_pass'

vocab (准则 6 持久化): memory_pool/mutation_evidence_vocab.json
  阈值, bypass list, block_mode 全可 Sir CLI 改, 不在 .py 写死.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, List, Tuple


_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'mutation_evidence_vocab.json',
)
_VOCAB_CACHE: dict = {'data': None, 'mtime': 0.0, 'checked_at': 0.0}
_VOCAB_CHECK_INTERVAL_S = 30.0

_DEFAULT_VOCAB = {
    'min_jaccard_with_stm': 0.15,
    'min_substring_chars': 6,
    'stm_window_turns': 6,
    'block_mode': 'block',           # 'block' 真拦 / 'audit' 只 warn
    'bypass_field_prefixes': (
        'preferences.user_correction',
        'biographic.last_modified',
    ),
    'bypass_sources': (
        'sir_cli',
        'fast_call_sir_explicit',
        'system_init',
        'skepticism_loop',
    ),
    'exempt_layers': (),
    # 🆕 [Sir 2026-05-26 23:55 BUG-α 评估] cross-language case 占位 (default OFF).
    # default OFF — 准则 5 反幻觉优先, "returned_from_shower" block 是对的 (主脑无端
    # mutate sir_status, guard 救了 profile). 真治本在 console UX 层 (BUG-β workorder).
    # Sir 真想全语言 relax → CLI 改 true (但 BUG-H "Stay safe" 类型会复发, 自决).
    'cross_lang_audit_only': False,
}


def _ratio_cjk(text: str) -> float:
    """text 中 CJK char (中日韩) 占比. 0.0 = 纯 ASCII, 1.0 = 纯 CJK."""
    if not text:
        return 0.0
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff')
    return cjk / max(1, len(text))


def _is_cross_language_mismatch(new_value: str, stm_text: str) -> bool:
    """STM 主体中文 (CJK > 0.5) + new_value 主体英文 (CJK < 0.1) → cross-lang.

    或反之 (STM 主英, new_value 主中). lexical guard 在 cross-lang 永远 fail,
    audit-only relax 此 case (Sir 真痛: 我说中文, Jarvis 想英文 mutation).
    """
    stm_cjk = _ratio_cjk(stm_text)
    nv_cjk = _ratio_cjk(new_value)
    if stm_cjk > 0.5 and nv_cjk < 0.1:
        return True
    if stm_cjk < 0.1 and nv_cjk > 0.5:
        return True
    return False


def _load_vocab() -> dict:
    """Lazy load + 30s throttle. Fail-safe → default."""
    now = time.time()
    if (_VOCAB_CACHE['data'] is not None and
            now - _VOCAB_CACHE['checked_at'] < _VOCAB_CHECK_INTERVAL_S):
        return _VOCAB_CACHE['data']
    _VOCAB_CACHE['checked_at'] = now
    try:
        if not os.path.exists(_VOCAB_PATH):
            _VOCAB_CACHE['data'] = _DEFAULT_VOCAB
            return _DEFAULT_VOCAB
        mtime = os.path.getmtime(_VOCAB_PATH)
        if mtime == _VOCAB_CACHE['mtime'] and _VOCAB_CACHE['data']:
            return _VOCAB_CACHE['data']
        with open(_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        config = dict(_DEFAULT_VOCAB)
        for k in _DEFAULT_VOCAB.keys():
            v = data.get(k)
            if v is None:
                continue
            if isinstance(_DEFAULT_VOCAB[k], tuple):
                config[k] = tuple(v)
            else:
                config[k] = v
        _VOCAB_CACHE['data'] = config
        _VOCAB_CACHE['mtime'] = mtime
        return config
    except Exception:
        return _DEFAULT_VOCAB


def _extract_stm_sir_text(nerve, window_turns: int = 6) -> str:
    """从 nerve.short_term_memory 取最近 N turn 拼 Sir 输入 text."""
    if nerve is None:
        return ''
    try:
        stm = getattr(nerve, 'short_term_memory', []) or []
        if not stm:
            return ''
        recent = stm[-window_turns:] if len(stm) > window_turns else stm
        parts = []
        for turn in recent:
            if isinstance(turn, dict):
                user_text = turn.get('user', '') or ''
                # 也含 Jarvis 自己说的, 因为有时 Sir 的修正是基于 Jarvis 提议
                # 但优先 Sir text (注: 治本核心是 Sir text)
                if user_text:
                    parts.append(user_text)
        return ' '.join(parts)
    except Exception:
        return ''


def _has_substring_evidence(new_value: str, stm_text: str,
                                min_chars: int) -> Tuple[bool, str]:
    """检 new_value 中 substring (>= min_chars) 是否在 stm_text 中出现.

    实用法: 取 new_value 中的 实词 phrase (>= min_chars 连续 word chars 含空格),
    任一在 stm_text (lowercased) 中出现 → True.
    """
    if not new_value or not stm_text:
        return False, ''
    text = str(new_value).lower()
    stm_lower = stm_text.lower()
    # 滑窗: 找 new_value 的 min_chars+ 连续 substring 是否在 stm
    for i in range(len(text) - min_chars + 1):
        candidate = text[i:i + min_chars]
        if candidate.strip() != candidate:
            continue
        if candidate in stm_lower:
            return True, candidate
    return False, ''


def _jaccard_with_stm(new_value: str, stm_text: str) -> float:
    """token-level jaccard between new_value 和 stm Sir text."""
    if not new_value or not stm_text:
        return 0.0
    new_tokens = set(re.findall(r'\w+', str(new_value).lower()))
    stm_tokens = set(re.findall(r'\w+', stm_text.lower()))
    if not new_tokens or not stm_tokens:
        return 0.0
    inter = len(new_tokens & stm_tokens)
    union = len(new_tokens | stm_tokens)
    return inter / union if union > 0 else 0.0


def check_mutation_evidence(
    new_value: Any,
    field_path: str = '',
    source: str = '',
    nerve=None,
    layer: str = '',
    current_text: str = '',
) -> Tuple[bool, str]:
    """Sir 治本入口 — 任何 mutation 前 check.

    Args:
      new_value: 即将写入的值
      field_path: e.g. 'profile.idiosyncrasies'
      source: caller (e.g. 'worker.memory_correction')
      nerve: CentralNerve ref (for STM)
      layer: target layer ('ProfileCard' / 'ConcernsLedger' / ...)

    Returns:
      (ok, reason): ok=True 通过, False 阻止. reason 简短说明 (audit log).
    """
    vocab = _load_vocab()

    # bypass: source 或 field 前缀 命中 → 直接通过 (Sir explicit input 等)
    for byp_src in vocab.get('bypass_sources', ()):
        if source.startswith(byp_src):
            return True, f'bypass:source={byp_src}'
    for byp_fld in vocab.get('bypass_field_prefixes', ()):
        if field_path.startswith(byp_fld):
            return True, f'bypass:field={byp_fld}'
    if layer in vocab.get('exempt_layers', ()):
        return True, f'bypass:layer={layer}'

    # 取 Sir STM text
    window = int(vocab.get('stm_window_turns', 6))
    stm_text = _extract_stm_sir_text(nerve, window_turns=window)
    # 🆕 [thinking-dehardcode fix#A / 2026-05-31 镜像挖出] 纳入"当前轮" Sir utterance.
    # =====================================================================
    # 根因 (镜像真测): _append_stm 在 turn 结束才把 user+jarvis 一起写 STM, 所以
    # mutation/guard 跑在 turn 中途时, Sir **当前刚说的话不在 STM** → guard 拿上一轮
    # STM 比对 → Sir 明确请求的合法写入 (e.g. "别老提醒我"→profile preference) 被
    # substring/jaccard=0 误拦 → 工具熔断 + 故障感回复. 治本: caller 传当前 utterance,
    # guard 把它并入证据 (检"Sir 真说过吗"的正确来源就是当前话). 不削弱反幻觉 — 编造
    # 的值 (e.g. "Stay safe" vs Sir 说 "d home") 仍不匹配. 准则 5/6 接地.
    # =====================================================================
    current_text_str = str(current_text or '').strip()
    if current_text_str:
        stm_text = (current_text_str + ' ' + stm_text).strip()
    if not stm_text:
        # STM 无 — 太早阶段或 nerve 没初始化, 不阻 (fail-open)
        return True, 'no_stm_available_fail_open'

    new_value_str = str(new_value or '').strip()
    if len(new_value_str) < 3:
        # 太短的 new_value 不算 fact (e.g. 数字 / 单字)
        return True, 'value_too_short_skip_check'

    # 检 evidence (substring OR jaccard 任一达标)
    min_chars = int(vocab.get('min_substring_chars', 6))
    has_substr, matched = _has_substring_evidence(
        new_value_str, stm_text, min_chars
    )
    jaccard = _jaccard_with_stm(new_value_str, stm_text)
    min_jac = float(vocab.get('min_jaccard_with_stm', 0.15))

    if has_substr:
        return True, f'evidence_ok:substring "{matched[:30]}"'
    if jaccard >= min_jac:
        return True, f'evidence_ok:jaccard={jaccard:.2f}>={min_jac}'

    # 无 evidence — block 或 audit
    # (cross_lang_audit_only relax 留在 vocab 里但 default 不启 — 准则 5 反幻觉
    # 优先, BUG-H "Stay safe" 凭空 mutation 需 block; BUG-α "returned_from_shower"
    # block 是对的 但 console error 显示问题在 console UX 层治, 不在 guard 放宽.)
    reason = (
        f'no_evidence_for_new_value: substring_match=False, '
        f'jaccard={jaccard:.2f}<{min_jac}; new_value head="{new_value_str[:60]}"; '
        f'stm_head="{stm_text[:80]}"'
    )
    return False, reason


def publish_guard_event(allowed: bool, reason: str, new_value: Any,
                            field_path: str, source: str) -> None:
    """publish SWM event for audit / monitor."""
    try:
        from jarvis_utils import get_event_bus
        bus = get_event_bus()
        if bus is None:
            return
        bus.publish(
            etype=('mutation_evidence_pass' if allowed
                     else 'mutation_evidence_blocked'),
            description=(
                f"{'OK' if allowed else 'BLOCKED'}: "
                f"{source} → {field_path[:40]}: {reason[:120]}"
            ),
            source='MutationEvidenceGuard',
            salience=0.5 if allowed else 0.85,
            metadata={
                'allowed': allowed,
                'reason': reason[:300],
                'field_path': field_path,
                'source_caller': source,
                'new_value_head': str(new_value)[:120],
            },
            ttl=86400.0,
        )
    except Exception:
        pass
