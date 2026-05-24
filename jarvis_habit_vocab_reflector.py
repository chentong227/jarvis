# -*- coding: utf-8 -*-
"""[Reshape 准则 6.5 / 2026-05-24] Habit vocab L7 reflector.

# Purpose

补齐 habit_progress_vocab 三件套 (持久化 JSON + CLI + L7 reflector).

周期扫 STM 找含数字 + 测量单位 + 动词模式的 Sir 句子, LLM 判是否是新 habit
progress 表达 (e.g. "我跑了 5 公里" / "今天背了 30 个单词"). LLM 若觉得新 →
propose 加进 vocab review queue, Sir 看 scripts/habit_progress_vocab_dump.py
拍板.

# 不调 LLM 时也能跑

无 LLM 时, 基于纯启发 (数字+单位+动词) propose, 但不直接 accept — 仍写 review,
Sir 拍板.

# Schema (memory_pool/habit_progress_vocab_review.json)

[
  {
    "id": "habv_<hash>",
    "ts": <unix>,
    "iso": "...",
    "phrase": "跑了",
    "lang": "zh",
    "evidence_count": 3,
    "sample_sentences": ["我跑了 5 公里", ...],
    "concern_id_guess": "sir_exercise_habit",  # LLM propose
    "status": "pending"  # pending / accepted / rejected
  }
]

# Sir 流程

1. 看 `python scripts/habit_progress_vocab_dump.py`
2. accept → `--add-zh 跑了` (CLI 真加进 vocab)
3. reject → `--reject habv_xxx` (本 reflector 记忆不重复 propose)

# Cycle

- 每 12h
- 启动延 10min
- env JARVIS_HABIT_VOCAB_REFLECTOR=0 关
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional


_THIS = os.path.dirname(os.path.abspath(__file__))
_VOCAB_PATH = os.path.join(_THIS, 'memory_pool', 'habit_progress_vocab.json')
_REVIEW_PATH = os.path.join(_THIS, 'memory_pool', 'habit_progress_vocab_review.json')
_STM_PATH = os.path.join(_THIS, 'memory_pool', 'stm_recent.jsonl')


# 启发模式: 数字 + 量词/单位 + 动词
# ZH: 我 V 了 N 量
# EN: I Ved N unit
_ZH_PATTERN = re.compile(
    r'(?:我|今天|刚)\s*([\u4e00-\u9fff]{1,4})\s*了\s*\d+\s*'
    r'([\u4e00-\u9fff]{1,3})'
)
_EN_PATTERN = re.compile(
    r"(?:i|i've)\s+(\w+ed)\s+(\d+)\s+(\w+)",
    re.IGNORECASE,
)


def _is_enabled() -> bool:
    val = os.environ.get('JARVIS_HABIT_VOCAB_REFLECTOR', '').strip()
    if val in ('0', 'false', 'False', 'no', 'off'):
        return False
    return True


def _load_vocab() -> Dict[str, Any]:
    if not os.path.exists(_VOCAB_PATH):
        return {}
    try:
        with open(_VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _load_review() -> List[Dict[str, Any]]:
    if not os.path.exists(_REVIEW_PATH):
        return []
    try:
        with open(_REVIEW_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _save_review(queue: List[Dict[str, Any]]) -> bool:
    try:
        os.makedirs(os.path.dirname(_REVIEW_PATH), exist_ok=True)
        tmp = _REVIEW_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _REVIEW_PATH)
        return True
    except Exception:
        return False


def _read_stm_user_lines(lookback_hours: float = 168.0) -> List[Dict[str, Any]]:
    """读 STM jsonl 取 Sir 自己发的句子 ('user' field)."""
    if not os.path.exists(_STM_PATH):
        return []
    out = []
    cutoff = time.time() - lookback_hours * 3600
    try:
        with open(_STM_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                user = (rec.get('user') or '').strip()
                if not user or len(user) < 5:
                    continue
                ts = rec.get('ts')
                if ts is None:
                    out.append(rec)
                else:
                    try:
                        if float(ts) >= cutoff:
                            out.append(rec)
                    except Exception:
                        out.append(rec)
    except Exception:
        pass
    return out


def _extract_candidates(user_lines: List[Dict[str, Any]],
                          existing_zh: set,
                          existing_en: set) -> List[Dict[str, Any]]:
    """启发 extract 含 (数字+单位+动词) pattern 的句子, 提候选 phrase."""
    candidates: Dict[str, Dict[str, Any]] = {}
    for rec in user_lines:
        sentence = (rec.get('user') or '').strip()
        if not sentence:
            continue
        turn_id = rec.get('turn_id') or 'unknown'
        # ZH: 我 V 了 N 单位
        for m in _ZH_PATTERN.finditer(sentence):
            verb = m.group(1)            # e.g. '跑'
            unit = m.group(2)            # e.g. '公里'
            phrase = f'{verb}了'           # vocab token
            if phrase in existing_zh:
                continue
            if phrase not in candidates:
                candidates[phrase] = {
                    'phrase': phrase,
                    'lang': 'zh',
                    'unit': unit,
                    'evidence_count': 0,
                    'sample_sentences': [],
                    'turns': [],
                }
            candidates[phrase]['evidence_count'] += 1
            if len(candidates[phrase]['sample_sentences']) < 3:
                candidates[phrase]['sample_sentences'].append(sentence[:80])
            candidates[phrase]['turns'].append(turn_id)
        # EN: I Ved N unit
        for m in _EN_PATTERN.finditer(sentence):
            verb = m.group(1).lower()
            unit = m.group(3).lower()
            phrase = verb                 # e.g. 'biked'
            if phrase in existing_en:
                continue
            if phrase not in candidates:
                candidates[phrase] = {
                    'phrase': phrase,
                    'lang': 'en',
                    'unit': unit,
                    'evidence_count': 0,
                    'sample_sentences': [],
                    'turns': [],
                }
            candidates[phrase]['evidence_count'] += 1
            if len(candidates[phrase]['sample_sentences']) < 3:
                candidates[phrase]['sample_sentences'].append(sentence[:80])
            candidates[phrase]['turns'].append(turn_id)
    # filter min 2 occurrences (avoid one-off 句)
    return [c for c in candidates.values() if c['evidence_count'] >= 2]


class HabitVocabReflector:
    """L7 reflector 周期扫 STM propose 新 habit vocab."""

    def __init__(self):
        self._stop = threading.Event()
        self._daemon: Optional[threading.Thread] = None
        self._stats = {
            'cycles_run': 0,
            'proposals_total': 0,
            'last_cycle_iso': '',
            'last_n_candidates': 0,
        }

    def run_cycle(self) -> List[Dict[str, Any]]:
        self._stats['cycles_run'] += 1
        self._stats['last_cycle_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        if not _is_enabled():
            return []
        vocab = _load_vocab()
        existing_zh = set(vocab.get('zh_keywords') or [])
        existing_en = set(vocab.get('en_keywords') or [])
        user_lines = _read_stm_user_lines(lookback_hours=168.0)
        if not user_lines:
            return []
        candidates = _extract_candidates(user_lines, existing_zh, existing_en)
        self._stats['last_n_candidates'] = len(candidates)
        if not candidates:
            return []
        # merge into review queue
        existing_review = _load_review()
        existing_by_id: Dict[str, Dict[str, Any]] = {
            e.get('id', ''): e for e in existing_review
        }
        now = time.time()
        new_or_updated = []
        for cand in candidates:
            phrase = cand['phrase']
            h = hashlib.md5(phrase.encode('utf-8', 'ignore')).hexdigest()[:8]
            cid = f'habv_{h}'
            if cid in existing_by_id:
                ex = existing_by_id[cid]
                # update count if pending
                if ex.get('status') == 'pending':
                    ex['evidence_count'] = cand['evidence_count']
                    ex['sample_sentences'] = cand['sample_sentences']
                continue
            entry = {
                'id': cid,
                'ts': now,
                'iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'phrase': phrase,
                'lang': cand['lang'],
                'unit': cand['unit'],
                'evidence_count': cand['evidence_count'],
                'sample_sentences': cand['sample_sentences'],
                'concern_id_guess': self._guess_concern_id(phrase, cand['unit']),
                'status': 'pending',
            }
            existing_by_id[cid] = entry
            new_or_updated.append(entry)
        merged = list(existing_by_id.values())
        merged.sort(key=lambda r: float(r.get('ts', 0)), reverse=True)
        merged = merged[:100]
        _save_review(merged)
        self._stats['proposals_total'] += len(new_or_updated)
        if new_or_updated:
            try:
                from jarvis_utils import get_event_bus, bg_log
                bus = get_event_bus()
                if bus is not None:
                    bus.publish(
                        etype='habit_vocab_proposed',
                        description=(
                            f"HabitVocabReflector: {len(new_or_updated)} new candidate(s). "
                            f"top: '{new_or_updated[0]['phrase']}' "
                            f"(×{new_or_updated[0]['evidence_count']})"
                        ),
                        source='HabitVocabReflector',
                        salience=0.6,
                        metadata={
                            'n_new': len(new_or_updated),
                            'top_phrase': new_or_updated[0]['phrase'],
                        },
                    )
                bg_log(
                    f"🌱 [HabitVocabReflector] {len(new_or_updated)} new candidate(s) "
                    f"— see scripts/habit_progress_vocab_dump.py"
                )
            except Exception:
                pass
        return new_or_updated

    def _guess_concern_id(self, phrase: str, unit: str) -> str:
        """启发: phrase + unit → concern_id guess (Sir 可改)."""
        keymap = {
            ('喝', '杯'): 'sir_hydration_habit',
            ('喝', '毫升'): 'sir_hydration_habit',
            ('drank', 'cups'): 'sir_hydration_habit',
            ('drank', 'ml'): 'sir_hydration_habit',
            ('番茄', '个'): 'sir_pomodoro_compliance',
            ('pomodoro', 's'): 'sir_pomodoro_compliance',
            ('睡', '小时'): 'sir_sleep_streak',
            ('slept', 'hours'): 'sir_sleep_streak',
        }
        for (verb_kw, unit_kw), cid in keymap.items():
            if verb_kw in phrase and unit_kw in unit:
                return cid
        return ''  # Sir 自己填

    def start_daemon(self) -> None:
        if self._daemon is not None and self._daemon.is_alive():
            return
        if not _is_enabled():
            return
        def _loop():
            time.sleep(600.0)  # 10min startup delay
            interval_s = 12 * 3600.0  # 12h
            while not self._stop.is_set():
                try:
                    self.run_cycle()
                except Exception:
                    pass
                self._stop.wait(max(60.0, interval_s))
        self._daemon = threading.Thread(target=_loop, daemon=True,
                                          name='HabitVocabReflector')
        self._daemon.start()

    def stop(self):
        self._stop.set()

    def stats(self) -> Dict[str, Any]:
        return dict(self._stats)


_DEFAULT: Optional[HabitVocabReflector] = None
_LOCK = threading.Lock()


def get_default_reflector() -> HabitVocabReflector:
    global _DEFAULT
    with _LOCK:
        if _DEFAULT is None:
            _DEFAULT = HabitVocabReflector()
        return _DEFAULT


def reset_for_test() -> None:
    global _DEFAULT
    with _LOCK:
        if _DEFAULT is not None:
            _DEFAULT.stop()
        _DEFAULT = None
