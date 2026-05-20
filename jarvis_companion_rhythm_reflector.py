# -*- coding: utf-8 -*-
"""[β.5.40-E1 / 2026-05-20] CompanionRhythmReflector — L7 daemon nudge timing learn

Sir 方向 E.1 (~3h):
  - 每日 03:30 跑, 扫近 7 天 STM
  - 提取所有 Jarvis 主动 nudge (含 [Smart Nudge] / [ProactiveCare/LIVE] 标记 / source='proactive_care')
  - 算每条 nudge 的 hour bucket + outcome (engaged/rejected/silent)
  - 更新 memory_pool/nudge_window_vocab.json:
    - weekday_hourly_receptive[hour] = engaged_rate (0-1)
    - weekend_hourly_receptive[hour] = engaged_rate
    - 每 hour ≥ 3 samples 才有 score (Sir 精准要求)

Outcome 判定 (60s window after nudge ts):
  - 含 user_voice STM (≥ 5 字) + 不含 refusal vocab → 'engaged' (+1)
  - 含 user_voice STM 含 refusal vocab → 'rejected' (-1)
  - 60s 内无 user_voice → 'silent' (0)
  
Vocab usage:
  - ProactiveCare 看 vocab, current_hour 的 score < 0.3 → severity *= 0.3 软 dampen
  - 同时 publish 'nudge_window_advice' SWM signal → 主脑看 evidence 调 tone

test: tests/_test_p0_plus_20_beta540_companion_rhythm.py
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


COMPANION_RHYTHM_REFLECTOR_CONFIG = {
    'tick_seconds': 60.0,
    'min_interval_s': 86400,            # 24h 1 跑
    'min_stm_for_run': 100,             # < 100 STM entries 不跑
    'lookback_s': 7 * 24 * 3600,        # 看近 7 天
    'min_samples_per_hour': 3,          # Sir 精准: 每 hour ≥ 3 sample 才计 score
    'outcome_window_s': 60.0,           # nudge 后 60s 内 user reply
    'preferred_run_hour_local': 3,      # 03:00 idle
    'history_max': 200,
    'min_engaged_text_len': 5,          # Sir reply ≥ 5 字才算 engaged
}


# Refusal vocab — Sir 拒绝/不耐烦词 (低置信也算 rejected)
_REFUSAL_KEYWORDS_ZH = [
    '不用', '别', '不要', '走开', '一边', '别催', '别问', '烦', '闭嘴',
    '安静', '少废话', '哦', '嗯',  # 哦/嗯 单字看 len 是不是 only this
]
_REFUSAL_KEYWORDS_EN = [
    'shut up', 'go away', 'leave me alone', 'not now', 'stop', 'enough',
    'no thanks', 'no thank you',
]


def _detect_refusal(text: str) -> bool:
    """Sir reply 是否含拒绝/不耐烦 (conservative — 不含则 engaged)."""
    if not text:
        return False
    t = text.lower().strip()
    if len(t) <= 2 and t in {'哦', '嗯', 'ok', 'okay'}:
        return True  # 单字应付 = mild dismiss
    for kw in _REFUSAL_KEYWORDS_ZH:
        if kw in t:
            return True
    for kw in _REFUSAL_KEYWORDS_EN:
        if kw in t:
            return True
    return False


def _is_nudge_entry(entry: Dict) -> bool:
    """STM entry 是否为 Jarvis 主动 nudge."""
    if not isinstance(entry, dict):
        return False
    source = (entry.get('source', '') or '').lower()
    if 'proactive' in source or 'nudge' in source or source == 'jarvis_self':
        # 进一步看 user 字段为空 (主动而非回应)
        user = entry.get('user', '')
        if not user or user == '' or '[Smart Nudge]' in (entry.get('jarvis', '') or '') \
                or '[ProactiveCare' in (entry.get('jarvis', '') or ''):
            return True
    # 老 STM: 有 [Smart Nudge] 或 [ProactiveCare/LIVE] marker 在 jarvis text
    jarvis = entry.get('jarvis', '') or entry.get('text', '') or ''
    if '[Smart Nudge]' in jarvis or '[ProactiveCare/LIVE]' in jarvis:
        return True
    return False


def _is_user_voice(entry: Dict) -> bool:
    if not isinstance(entry, dict):
        return False
    source = (entry.get('source', '') or '').lower()
    if 'user_voice' in source:
        return True
    user = entry.get('user', '') or entry.get('text', '') or ''
    return bool(user) and source != 'jarvis_self'


def _entry_ts(entry: Dict) -> float:
    return float(entry.get('ts', 0) or entry.get('timestamp', 0) or 0)


def _classify_nudge_outcome(nudge_entry: Dict, stm: List[Dict], window_s: float = 60.0,
                            min_text_len: int = 5) -> str:
    """从 nudge entry 找后续 outcome ('engaged' / 'rejected' / 'silent')."""
    nudge_ts = _entry_ts(nudge_entry)
    if nudge_ts <= 0:
        return 'silent'
    found_reply = False
    for entry in stm:
        ets = _entry_ts(entry)
        if ets <= nudge_ts:
            continue
        if ets > nudge_ts + window_s:
            break
        if _is_user_voice(entry):
            text = entry.get('user', '') or entry.get('text', '') or ''
            if not text.strip():
                continue
            found_reply = True
            if _detect_refusal(text):
                return 'rejected'
            if len(text.strip()) >= min_text_len:
                return 'engaged'
    return 'silent' if not found_reply else 'engaged'


def _build_hour_buckets(samples: List[Dict]) -> Tuple[Dict, Dict, Dict]:
    """从 sample list 算每 hour 的 engaged_rate.
    
    samples: [{'hour': int, 'is_weekday': bool, 'outcome': 'engaged|rejected|silent'}]
    
    Returns:
        (weekday_score_dict, weekend_score_dict, samples_count_dict)
        score = (engaged_count - rejected_count * 0.5) / total, clamp [0, 1]
    """
    bucket = {True: {}, False: {}}  # is_weekday → hour → {engaged, rejected, silent, total}
    for s in samples:
        is_wd = s.get('is_weekday', True)
        hour = int(s.get('hour', 0))
        out = s.get('outcome', 'silent')
        h_dict = bucket[is_wd].setdefault(hour, {'engaged': 0, 'rejected': 0, 'silent': 0, 'total': 0})
        h_dict[out] = h_dict.get(out, 0) + 1
        h_dict['total'] += 1
    
    def _calc(d):
        result = {str(h): None for h in range(24)}
        for h, st in d.items():
            total = st.get('total', 0)
            if total < COMPANION_RHYTHM_REFLECTOR_CONFIG['min_samples_per_hour']:
                continue
            engaged = st.get('engaged', 0)
            rejected = st.get('rejected', 0)
            silent = st.get('silent', 0)
            # silent 视作中性 (0), rejected 视作 -0.5, engaged 视作 +1
            score = (engaged - 0.5 * rejected) / total
            score = max(0.0, min(1.0, score))
            result[str(h)] = round(score, 3)
        return result
    
    samples_count = {
        'weekday': {str(h): bucket[True].get(h, {}).get('total', 0) for h in range(24)},
        'weekend': {str(h): bucket[False].get(h, {}).get('total', 0) for h in range(24)},
    }
    return _calc(bucket[True]), _calc(bucket[False]), samples_count


class CompanionRhythmReflector(threading.Thread):
    """L7 daemon: 每日 03:30 算 nudge-receptive hour, 写 nudge_window_vocab.json."""

    def __init__(
        self,
        stm_provider=None,
        vocab_path: Optional[str] = None,
        config: Optional[Dict] = None,
    ):
        super().__init__(daemon=True, name='CompanionRhythmReflector')
        self.stm_provider = stm_provider
        self.config = dict(COMPANION_RHYTHM_REFLECTOR_CONFIG)
        if config:
            self.config.update(config)
        self.vocab_path = vocab_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'memory_pool', 'nudge_window_vocab.json',
        )
        self._stop = threading.Event()
        self._last_run_ts = 0.0
        self._stats = {
            'runs_total': 0,
            'last_run_ts': 0.0,
            'last_sample_count': 0,
            'last_hours_with_score': 0,
            'last_error': '',
        }

    def stop(self):
        self._stop.set()

    def force_run_now(self) -> Dict:
        try:
            return self._reflect_once(force=True)
        except Exception as e:
            return {'error': str(e)[:200], 'ok': False}

    def _load_vocab(self) -> Dict:
        try:
            with open(self.vocab_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_vocab(self, vocab: Dict) -> bool:
        try:
            tmp = self.vocab_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(vocab, f, ensure_ascii=False, indent=2)
                f.write('\n')
            os.replace(tmp, self.vocab_path)
            return True
        except Exception:
            return False

    def _should_run_by_hour(self, force: bool = False) -> bool:
        if force:
            return True
        try:
            hour = time.localtime().tm_hour
            return 3 <= hour < 6
        except Exception:
            return True

    def _extract_samples(self, stm: List[Dict]) -> List[Dict]:
        """从 STM 提取 nudge samples."""
        if not stm:
            return []
        now = time.time()
        cutoff = now - self.config['lookback_s']
        samples = []
        for i, entry in enumerate(stm):
            ets = _entry_ts(entry)
            if ets < cutoff:
                continue
            if not _is_nudge_entry(entry):
                continue
            outcome = _classify_nudge_outcome(
                entry, stm,
                window_s=self.config['outcome_window_s'],
                min_text_len=self.config['min_engaged_text_len'],
            )
            try:
                tm_local = time.localtime(ets)
                hour = tm_local.tm_hour
                is_weekday = tm_local.tm_wday < 5
                samples.append({
                    'ts': ets,
                    'iso': time.strftime('%Y-%m-%dT%H:%M:%S', tm_local),
                    'hour': hour,
                    'is_weekday': is_weekday,
                    'outcome': outcome,
                })
            except Exception:
                continue
        return samples

    def _reflect_once(self, force: bool = False) -> Dict:
        result = {
            'ok': False,
            'reason': '',
            'samples_n': 0,
            'hours_with_score': 0,
        }

        if not force:
            now = time.time()
            since = now - self._last_run_ts
            if since < self.config['min_interval_s']:
                result['reason'] = f'too soon: {since:.0f}s'
                return result
            if not self._should_run_by_hour(force=False):
                result['reason'] = 'outside preferred hour'
                return result

        if self.stm_provider is None:
            result['reason'] = 'no stm_provider'
            self._stats['last_error'] = result['reason']
            return result

        try:
            stm = self.stm_provider() or []
        except Exception as e:
            result['reason'] = f'stm fetch err: {str(e)[:100]}'
            self._stats['last_error'] = result['reason']
            return result

        if not force and len(stm) < self.config['min_stm_for_run']:
            result['reason'] = f'not enough STM: {len(stm)}'
            return result

        samples = self._extract_samples(stm)
        result['samples_n'] = len(samples)
        if not samples:
            self._last_run_ts = time.time()
            self._stats['runs_total'] += 1
            self._stats['last_run_ts'] = self._last_run_ts
            result['reason'] = 'no nudge samples in lookback window'
            result['ok'] = True
            return result

        # Compute scores
        weekday_score, weekend_score, samples_count = _build_hour_buckets(samples)
        hours_with_score = sum(
            1 for v in list(weekday_score.values()) + list(weekend_score.values())
            if v is not None
        )
        result['hours_with_score'] = hours_with_score

        # Update vocab
        vocab = self._load_vocab()
        if not vocab:
            vocab = {}
        vocab['weekday_hourly_receptive'] = weekday_score
        vocab['weekend_hourly_receptive'] = weekend_score
        vocab['samples_count'] = samples_count
        vocab['last_computed_ts'] = time.time()
        vocab['source'] = f'L7 CompanionRhythmReflector ({len(samples)} samples / 7d)'
        
        # Rolling history (keep last N)
        hist_max = vocab.get('_meta', {}).get('history_max', self.config['history_max'])
        old_history = vocab.get('history', [])
        if not isinstance(old_history, list):
            old_history = []
        merged = old_history + samples
        # dedup by ts
        seen_ts = set()
        deduped = []
        for s in merged:
            ts = s.get('ts', 0)
            if ts in seen_ts:
                continue
            seen_ts.add(ts)
            deduped.append(s)
        # truncate
        if len(deduped) > hist_max:
            deduped = sorted(deduped, key=lambda x: x.get('ts', 0))[-hist_max:]
        vocab['history'] = deduped

        if self._save_vocab(vocab):
            result['ok'] = True
            result['reason'] = f'computed {hours_with_score} hours from {len(samples)} samples'
        else:
            result['reason'] = 'save vocab failed'
            self._stats['last_error'] = result['reason']

        self._last_run_ts = time.time()
        self._stats['runs_total'] += 1
        self._stats['last_run_ts'] = self._last_run_ts
        self._stats['last_sample_count'] = len(samples)
        self._stats['last_hours_with_score'] = hours_with_score

        try:
            from jarvis_utils import bg_log
            bg_log(f"📈 [CompanionRhythmReflector] {result['reason']}")
        except Exception:
            pass
        return result

    def get_stats(self) -> Dict:
        return dict(self._stats)

    def run(self):
        try:
            from jarvis_utils import bg_log
            bg_log('[CompanionRhythmReflector] L7 daemon ready (β.5.40-E1)')
        except Exception:
            pass
        self._stop.wait(60.0)
        while not self._stop.is_set():
            try:
                self._reflect_once(force=False)
            except Exception as e:
                self._stats['last_error'] = f'reflect_once threw: {str(e)[:80]}'
            self._stop.wait(self.config['tick_seconds'])


def get_current_hour_receptive_score(vocab_path: Optional[str] = None,
                                      now_local=None) -> Optional[float]:
    """Public API for ProactiveCare. 当前 hour 的 receptive score (None 若未填充)."""
    if vocab_path is None:
        vocab_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'memory_pool', 'nudge_window_vocab.json',
        )
    try:
        with open(vocab_path, 'r', encoding='utf-8') as f:
            vocab = json.load(f)
    except Exception:
        return None
    if now_local is None:
        now_local = time.localtime()
    is_weekday = now_local.tm_wday < 5
    hour = now_local.tm_hour
    key = 'weekday_hourly_receptive' if is_weekday else 'weekend_hourly_receptive'
    table = vocab.get(key, {})
    return table.get(str(hour))
