# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 00:11 真意] TimeAwareness — 给贾维斯真正对时间的理解.

Sir 原话:
  "并且给予贾维斯真正对时间的理解，这有助于他理解我的行为模式"

设计 (准则 6 三维耦合):
  - 数据强耦合: 学习 Sir 的 hour-of-day × day-of-week × activity pattern,
    持久化 memory_pool/sir_behavior_temporal_vocab.json
  - 行为弱耦合: 不 hard gate, 只 surface "pattern_at_hour + today's deviation"
    给 InnerThought / 主脑 prompt, LLM 自决
  - 决策集中主脑: 不在 .py 写死 pattern, LLM 周期反思 STM 提 pattern → vocab

数据流:
  STM (24h × 7day) → TemporalPatternReflector (hourly tick, LLM mine pattern)
    → memory_pool/sir_behavior_temporal_vocab.json
    → InnerThought daemon prompt 注 [TIME PATTERN] block
    → 主脑 prompt 注 [TIME CONTEXT] block (lite)

Sir CLI:
  scripts/time_awareness_dump.py — list/add/edit/remove pattern

vocab schema:
  {
    "patterns": {
      "<hour>_<day_of_week>": {  # e.g. "23_mon" = 周一 23:00
        "typical_activities": ["coding", "wind_down"],
        "typical_topics": ["jarvis_dev", "tomorrow's_meeting"],
        "frequency": 0.6,  # 此模式出现频率 (0-1)
        "last_observed": "2026-05-26",
        "sample_count": 12,
        "deviation_keywords": ["unusual", "异常"],  # Sir 真说过 "今天特别"
      }
    },
    "patterns_by_hour": {  # hour aggregate (across days)
      "23": {"typical_activities": [...], "frequency": 0.8}
    },
    "learned_routines": [  # 长期 routine 一段一段
      {"name": "evening_wind_down", "hours": [22, 23, 0],
       "signature": ["showered", "睡前", "wind down"], "confidence": 0.8}
    ],
    "last_reflector_run": "2026-05-27T00:00:00"
  }

准则:
  5 (言出必行): pattern 仅基于真 STM 观察, 不空头
  6 (vocab 持久化): JSON + CLI + reflector daemon, 0 hardcoded pattern
  8 (优雅): lazy load + 30s throttle + reflector hourly + safe fallback
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'sir_behavior_temporal_vocab.json',
)
_VOCAB_CACHE: dict = {'data': None, 'mtime': 0.0, 'checked_at': 0.0}
_VOCAB_CHECK_INTERVAL_S = 30.0

_DEFAULT_VOCAB = {
    'patterns': {},               # hour_dayofweek → pattern dict
    'patterns_by_hour': {},       # hour → aggregate pattern (across days)
    'learned_routines': [],       # list of long-term routines
    'last_reflector_run': '',
    'reflector_min_interval_s': 3600,  # 1h between reflections (token cap)
    'min_sample_count_to_surface': 3,  # need 3+ observations to count as pattern
}


_DAY_NAMES = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')


def _load_vocab() -> dict:
    """Lazy load + 30s throttle. Fail-safe → default."""
    now = time.time()
    if (_VOCAB_CACHE['data'] is not None and
            now - _VOCAB_CACHE['checked_at'] < _VOCAB_CHECK_INTERVAL_S):
        return _VOCAB_CACHE['data']
    _VOCAB_CACHE['checked_at'] = now
    try:
        if not os.path.exists(_VOCAB_PATH):
            _VOCAB_CACHE['data'] = dict(_DEFAULT_VOCAB)
            return _VOCAB_CACHE['data']
        mtime = os.path.getmtime(_VOCAB_PATH)
        if mtime == _VOCAB_CACHE['mtime'] and _VOCAB_CACHE['data']:
            return _VOCAB_CACHE['data']
        with open(_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Merge with default (preserve schema)
        config = dict(_DEFAULT_VOCAB)
        for k in _DEFAULT_VOCAB:
            if k in data:
                config[k] = data[k]
        _VOCAB_CACHE['data'] = config
        _VOCAB_CACHE['mtime'] = mtime
        return config
    except Exception:
        return dict(_DEFAULT_VOCAB)


def _save_vocab(data: dict) -> bool:
    """Persist vocab to JSON. Fail-safe → False."""
    try:
        os.makedirs(os.path.dirname(_VOCAB_PATH), exist_ok=True)
        # write to tmp then rename atomic
        tmp_path = _VOCAB_PATH + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, _VOCAB_PATH)
        _VOCAB_CACHE['data'] = data
        _VOCAB_CACHE['mtime'] = os.path.getmtime(_VOCAB_PATH)
        return True
    except Exception:
        return False


# ==========================================================================
# Pattern lookup — daemon / 主脑 prompt 注入用
# ==========================================================================
def _now_hour_day() -> Tuple[int, str]:
    """Current local hour + day-of-week short name."""
    lt = time.localtime()
    return lt.tm_hour, _DAY_NAMES[lt.tm_wday]


def get_pattern_at_now() -> dict:
    """返当前 hour + day 对应的 pattern.

    Returns dict with keys:
      hour, day, hour_day_key, typical_activities, typical_topics,
      frequency, sample_count, fallback_used (bool)
    """
    hour, day = _now_hour_day()
    key = f"{hour}_{day}"
    vocab = _load_vocab()
    pat = vocab.get('patterns', {}).get(key)
    fallback = False
    if not pat:
        # fallback: 用 hour aggregate (across days)
        pat = vocab.get('patterns_by_hour', {}).get(str(hour))
        fallback = True
    if not pat:
        return {
            'hour': hour, 'day': day, 'hour_day_key': key,
            'typical_activities': [], 'typical_topics': [],
            'frequency': 0.0, 'sample_count': 0,
            'fallback_used': True, 'has_data': False,
        }
    min_samples = int(vocab.get('min_sample_count_to_surface', 3))
    sample_count = int(pat.get('sample_count', 0))
    return {
        'hour': hour, 'day': day, 'hour_day_key': key,
        'typical_activities': list(pat.get('typical_activities', [])),
        'typical_topics': list(pat.get('typical_topics', [])),
        'frequency': float(pat.get('frequency', 0.0)),
        'sample_count': sample_count,
        'last_observed': pat.get('last_observed', ''),
        'fallback_used': fallback,
        'has_data': sample_count >= min_samples,
    }


def get_learned_routines() -> List[dict]:
    """所有学过的 routine."""
    vocab = _load_vocab()
    return list(vocab.get('learned_routines', []))


def get_routines_active_now() -> List[dict]:
    """当前 hour 落在某 routine 时段内的 routines."""
    hour, _ = _now_hour_day()
    return [r for r in get_learned_routines()
            if hour in r.get('hours', [])]


def detect_deviation_today(stm: List[dict]) -> Optional[str]:
    """detect 今天 Sir 行为是否偏离当前 hour 的 typical pattern.

    Returns 简短 deviation 描述 (None = 无 deviation 或数据不足).
    """
    pat = get_pattern_at_now()
    if not pat.get('has_data'):
        return None
    typical_acts = set(pat.get('typical_activities', []))
    if not typical_acts:
        return None
    # 检 STM 今 hour 内有 Sir text, 含 typical_activities keyword?
    now = time.time()
    cur_hour = pat['hour']
    matched = False
    for t in (stm or [])[-20:]:
        if not isinstance(t, dict):
            continue
        # only count this hour
        ts = t.get('ts', 0) or t.get('time', 0) or 0
        if isinstance(ts, str):
            continue  # skip if not numeric
        if ts and now - ts > 3600:
            continue
        text = (t.get('user', '') or '').lower()
        if not text:
            continue
        for act in typical_acts:
            if act.lower() in text:
                matched = True
                break
        if matched:
            break
    if not matched and typical_acts:
        return (f"typical at {cur_hour}:00 = "
                f"{','.join(list(typical_acts)[:3])} — "
                f"today no signal of those in STM")
    return None


# ==========================================================================
# Reflector — hourly tick, LLM mine pattern from STM
# ==========================================================================
def maybe_run_reflector(stm: List[dict], force: bool = False) -> bool:
    """If due (>= 1h since last), run LLM pattern mining + update vocab.

    Returns True if reflector ran, False if throttled.
    """
    vocab = _load_vocab()
    last_run_str = vocab.get('last_reflector_run', '')
    min_interval = float(vocab.get('reflector_min_interval_s', 3600))
    now = time.time()
    if not force and last_run_str:
        try:
            last_t = time.mktime(time.strptime(last_run_str[:19],
                                                  '%Y-%m-%dT%H:%M:%S'))
            if now - last_t < min_interval:
                return False
        except Exception:
            pass
    # actually mine
    new_vocab = _mine_patterns_from_stm(stm, vocab)
    new_vocab['last_reflector_run'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    _save_vocab(new_vocab)
    return True


def _mine_patterns_from_stm(stm: List[dict], existing_vocab: dict) -> dict:
    """从 STM 提取 hour × day pattern (准则 6: LLM 提, python 整理).

    简化版 (无 LLM): 用 keyword frequency 提 typical_activity. 后续 v2 加 LLM.
    """
    if not stm:
        return existing_vocab
    new_vocab = dict(existing_vocab)
    new_vocab['patterns'] = dict(existing_vocab.get('patterns', {}))
    new_vocab['patterns_by_hour'] = dict(existing_vocab.get('patterns_by_hour', {}))

    # 简化 pattern mine: 聚合 STM 按 hour, 提 user_text 前 2 个 word 作 activity
    # (v1 简版, v2 加 LLM call refine)
    from collections import defaultdict, Counter
    hour_acts: Dict[int, Counter] = defaultdict(Counter)
    hour_day_acts: Dict[str, Counter] = defaultdict(Counter)
    for t in (stm or []):
        if not isinstance(t, dict):
            continue
        ts = t.get('ts', 0) or 0
        if not isinstance(ts, (int, float)) or ts <= 0:
            continue
        lt = time.localtime(ts)
        hour = lt.tm_hour
        day = _DAY_NAMES[lt.tm_wday]
        text = (t.get('user', '') or '').strip()
        if not text or len(text) < 2:
            continue
        # 提 activity = 前 30ch 摘要 (后续 LLM mine refine)
        snippet = text[:40].strip()
        if snippet:
            hour_acts[hour][snippet] += 1
            hour_day_acts[f"{hour}_{day}"][snippet] += 1
    # 写回 vocab
    for hour, ctr in hour_acts.items():
        top = ctr.most_common(5)
        if not top:
            continue
        total = sum(ctr.values())
        sample_count = total
        new_vocab['patterns_by_hour'][str(hour)] = {
            'typical_activities': [a for a, _ in top],
            'typical_topics': [],  # v2 加 LLM 提
            'frequency': min(1.0, top[0][1] / max(1, total)),
            'sample_count': sample_count,
            'last_observed': time.strftime('%Y-%m-%d'),
        }
    for key, ctr in hour_day_acts.items():
        top = ctr.most_common(3)
        if not top or sum(ctr.values()) < 2:
            continue
        total = sum(ctr.values())
        new_vocab['patterns'][key] = {
            'typical_activities': [a for a, _ in top],
            'typical_topics': [],
            'frequency': min(1.0, top[0][1] / max(1, total)),
            'sample_count': total,
            'last_observed': time.strftime('%Y-%m-%d'),
        }
    return new_vocab


# ==========================================================================
# Format for prompt injection
# ==========================================================================
def format_for_thought_prompt() -> str:
    """格式化为 InnerThought daemon prompt block.

    输出形如:
      [TIME CONTEXT (Sir's typical at this hour, learned from STM)]
        - Now: 23:00 Mon
        - Typical activities at this hour: coding, wind_down, jarvis_dev
        - Today deviation: no signal of typical activities yet
        - Active long routine: evening_wind_down (22-00, sig: showered/睡前)
    """
    pat = get_pattern_at_now()
    if not pat.get('has_data'):
        # 数据不足, 不注入 (准则 8: 避免 prompt 噪音)
        return ''
    lines = ["[TIME CONTEXT (Sir's typical at this hour, learned from STM)]"]
    lines.append(f"  - Now: {pat['hour']}:00 {pat['day']}")
    if pat['typical_activities']:
        acts = ', '.join(pat['typical_activities'][:5])
        lines.append(f"  - Typical at this hour: {acts}")
    if pat.get('frequency', 0) > 0:
        lines.append(
            f"  - Pattern confidence: {pat['frequency']:.0%} "
            f"({pat['sample_count']} samples)"
        )
    if pat.get('fallback_used'):
        lines.append(f"  - (Using hour aggregate, no day-specific data for {pat['day']})")
    # 加 routines
    routines = get_routines_active_now()
    if routines:
        for r in routines[:2]:
            lines.append(
                f"  - Active routine: {r.get('name', '?')} "
                f"(sig: {','.join(r.get('signature', [])[:3])})"
            )
    return '\n'.join(lines) + '\n'


def format_for_main_brain_lite() -> str:
    """主脑 prompt 注入精简版 (省 token).

    输出形如:
      [TIME] 23:00 Mon — Sir typical: coding, wind_down
    """
    pat = get_pattern_at_now()
    if not pat.get('has_data'):
        return ''
    acts = ', '.join(pat.get('typical_activities', [])[:3])
    return f"[TIME] {pat['hour']}:00 {pat['day']} — Sir typical: {acts}"
