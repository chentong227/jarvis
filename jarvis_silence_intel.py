# -*- coding: utf-8 -*-
"""[β.5.43-E / 2026-05-20 19:13] Silence Intelligence — thinking pause detection

Sir 17:10 真理 (6 缺口 E): Sir 说话过程中 'uh / 嗯 / let me think' 等 thinking pause,
Jarvis 主脑应感知 Sir 在思考, 不急着答复内容. 

设计 (publish-only, Sir 准则 6 + β.5.0 三维耦合):
- vocab 持久化: memory_pool/thinking_pause_vocab.json (en/zh fillers + patterns)
- mtime cache + 自动 recompile
- is_thinking_pause(cmd) -> (bool, evidence): 短 utterance + 含 filler → True
- chat_bypass / worker fire 前调, 命中 → publish 'sir_thinking_pause' SWM
- directive 'thinking_pause_aware_judge' 让主脑反应: 'mhm' / 短回应 / 不打断
- 不阻塞 emit (避免 race), 主脑自己决定要不要 acknowledge

doc 推断: β.5.43-E (Sir 17:10 6 缺口 E silence intelligence)
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Optional, Tuple, Dict, List

_VOCAB_PATH = os.path.join('memory_pool', 'thinking_pause_vocab.json')

_SEED_EN_FILLERS = ('uh', 'um', 'umm', 'hmm', 'well', 'let me think',
                     'let me see', 'hold on', 'wait')
_SEED_ZH_FILLERS = ('嗯', '呃', '让我想想', '让我看看', '等等', '稍等',
                     '等一下', '我想想', '我看看')
_SEED_PATTERNS = (r'^.{1,8}\.\.\.$', r'^.{1,6}…$')

_VOCAB_CACHE: Dict = {}
_VOCAB_MTIME: float = 0.0
_LOCK = threading.Lock()
_COMPILED_EN_RE: Optional[re.Pattern] = None
_COMPILED_ZH_RE: Optional[re.Pattern] = None
_COMPILED_PATTERNS: List[re.Pattern] = []
_THRESHOLDS: Dict = {
    'short_utterance_max_chars': 12,
    'thinking_pause_confidence_min': 0.6,
}


def _load_vocab() -> Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[str, ...], Dict]:
    """从 vocab json 加载 fillers. fail → 返 SEED fallback."""
    global _VOCAB_CACHE, _VOCAB_MTIME, _THRESHOLDS
    fallback = (_SEED_EN_FILLERS, _SEED_ZH_FILLERS, _SEED_PATTERNS, dict(_THRESHOLDS))
    try:
        if not os.path.exists(_VOCAB_PATH):
            return fallback
        mtime = os.path.getmtime(_VOCAB_PATH)
        cached_mtime = _VOCAB_CACHE.get('_mtime', 0.0)
        if mtime == cached_mtime and _VOCAB_CACHE:
            return (
                _VOCAB_CACHE.get('en', _SEED_EN_FILLERS),
                _VOCAB_CACHE.get('zh', _SEED_ZH_FILLERS),
                _VOCAB_CACHE.get('patterns', _SEED_PATTERNS),
                _VOCAB_CACHE.get('thresholds', dict(_THRESHOLDS)),
            )
        with _LOCK:
            with open(_VOCAB_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            groups = data.get('groups', {})
            en = tuple(groups.get('en_thinking_fillers', {}).get(
                'verbs', _SEED_EN_FILLERS))
            zh = tuple(groups.get('zh_thinking_fillers', {}).get(
                'verbs', _SEED_ZH_FILLERS))
            patterns = tuple(groups.get('patterns', {}).get(
                'patterns', _SEED_PATTERNS))
            thresholds = data.get('thresholds', dict(_THRESHOLDS))
            _VOCAB_CACHE = {
                '_mtime': mtime,
                'en': en, 'zh': zh, 'patterns': patterns,
                'thresholds': thresholds,
            }
            _VOCAB_MTIME = mtime
            _THRESHOLDS = thresholds
            return (en, zh, patterns, thresholds)
    except Exception:
        return fallback


def _get_compiled() -> Tuple[re.Pattern, re.Pattern, List[re.Pattern], Dict]:
    """vocab-driven regex 编译 cache."""
    global _COMPILED_EN_RE, _COMPILED_ZH_RE, _COMPILED_PATTERNS
    en, zh, patterns, thresholds = _load_vocab()
    cur_mtime = _VOCAB_CACHE.get('_mtime', 0.0)
    cached_mtime = getattr(_get_compiled, '_compiled_mtime', None)
    if (_COMPILED_EN_RE is not None and cached_mtime == cur_mtime):
        return _COMPILED_EN_RE, _COMPILED_ZH_RE, _COMPILED_PATTERNS, thresholds
    with _LOCK:
        en_alt = '|'.join(re.escape(v) for v in en if v)
        zh_alt = '|'.join(re.escape(v) for v in zh if v)
        _COMPILED_EN_RE = re.compile(
            r'\b(?:' + en_alt + r')\b' if en_alt else r'(?!.*)',
            re.IGNORECASE,
        )
        _COMPILED_ZH_RE = re.compile(zh_alt if zh_alt else r'(?!.*)')
        _COMPILED_PATTERNS = [re.compile(p) for p in patterns if p]
        _get_compiled._compiled_mtime = cur_mtime
    return _COMPILED_EN_RE, _COMPILED_ZH_RE, _COMPILED_PATTERNS, thresholds


def is_thinking_pause(cmd: str) -> Tuple[bool, Dict]:
    """检测 cmd 是否像 thinking pause.
    
    Args:
      cmd: Sir 说的话 (ASR result)
    
    Returns:
      (is_pause, evidence_dict). evidence 含:
        - confidence: 0.0-1.0
        - matched_fillers: 命中的 filler list
        - matched_patterns: 命中的 pattern list
        - utterance_short: True if utterance <= threshold
        - lang: 'en' / 'zh' / 'mixed'
    """
    evidence = {
        'confidence': 0.0,
        'matched_fillers': [],
        'matched_patterns': [],
        'utterance_short': False,
        'lang': 'unknown',
    }
    if not cmd or not isinstance(cmd, str):
        return False, evidence
    cmd_strip = cmd.strip()
    if not cmd_strip:
        return False, evidence

    en_re, zh_re, patterns, thresholds = _get_compiled()
    short_max = thresholds.get('short_utterance_max_chars', 12)
    conf_min = thresholds.get('thinking_pause_confidence_min', 0.6)

    # 长度判断 (短 utterance 更可能是 thinking pause)
    utterance_short = len(cmd_strip) <= short_max
    evidence['utterance_short'] = utterance_short

    # 语言判断
    has_zh = bool(re.search(r'[\u4e00-\u9fa5]', cmd_strip))
    has_en = bool(re.search(r'[a-zA-Z]', cmd_strip))
    if has_zh and has_en:
        evidence['lang'] = 'mixed'
    elif has_zh:
        evidence['lang'] = 'zh'
    elif has_en:
        evidence['lang'] = 'en'

    # filler match
    en_matches = en_re.findall(cmd_strip)
    zh_matches = zh_re.findall(cmd_strip)
    evidence['matched_fillers'] = en_matches + zh_matches

    # pattern match
    for p in patterns:
        if p.search(cmd_strip):
            evidence['matched_patterns'].append(p.pattern)

    # confidence 计算 — 简单加权
    conf = 0.0
    if evidence['matched_fillers']:
        conf += 0.5
        if utterance_short:
            conf += 0.3  # 短 + filler 强信号
    if evidence['matched_patterns']:
        conf += 0.4
    # 极短 (1-3 字) 且 filler 占满 → 高置信
    if utterance_short and len(cmd_strip) <= 4 and evidence['matched_fillers']:
        conf = max(conf, 0.85)
    conf = min(1.0, conf)
    evidence['confidence'] = conf

    is_pause = conf >= conf_min
    return is_pause, evidence


def publish_thinking_pause_event(cmd: str, evidence: Dict, turn_id: str = '') -> None:
    """publish 'sir_thinking_pause' SWM event (publish-only, 主脑决定怎么反应)."""
    try:
        from jarvis_utils import get_event_bus
        bus = get_event_bus()
        if bus is None:
            return
        bus.publish(
            etype='sir_thinking_pause',
            description=f'Sir 在思考: "{cmd[:60]}" (conf={evidence.get("confidence", 0):.2f})',
            source='SilenceIntel',
            salience=0.55,  # 中等 — 主脑可顺嘴 acknowledge, 不强迫
            metadata={
                'turn_id': turn_id,
                'cmd': str(cmd)[:200],
                'evidence': evidence,
            },
        )
    except Exception:
        pass
