# -*- coding: utf-8 -*-
"""[Translator Phase 3 / 2026-05-24 21:10] L7 Reflector daemon.

设计 doc: docs/JARVIS_TRANSLATOR_ARCHITECTURE.md §7.6

职责:
- 周期扫 SWM 'translator_aliased' / 'translator_rejected' events
- 模式探测: 同 organ_name 重复 by_command alias N 次 → propose vocab alias
- 写 review queue 进 translator_alias_vocab.json status=review
- Sir CLI activate (`scripts/translator_alias_dump.py activate alias_XXX`)

Phase 3 简化版: 仅模式探测 (无 LLM). Phase 5+ 加 gemini-flash-lite propose.

跟 HabitVocabReflector 同型 (准则 6.5 三件套).
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'translator_alias_vocab.json')

# 模式探测阈值
_PROPOSE_THRESHOLD = 3   # 同 organ → 同 to-organ N 次 by_command 才 propose
_SCAN_WINDOW_S = 7200.0  # 2h 内的 events
_TICK_INTERVAL_S = 1800.0  # 30 min
_STARTUP_DELAY_S = 600.0   # 10min 启动延迟 (跟 HabitVocab 同, 让系统稳定)


def _load_vocab() -> Dict[str, Any]:
    if not os.path.exists(VOCAB_PATH):
        return {'schema_version': 1, 'aliases': []}
    try:
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'schema_version': 1, 'aliases': []}


def _save_vocab(data: Dict[str, Any]) -> None:
    data['last_modified'] = datetime.utcnow().isoformat() + 'Z'
    os.makedirs(os.path.dirname(VOCAB_PATH), exist_ok=True)
    with open(VOCAB_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _next_alias_id(data: Dict[str, Any]) -> str:
    aliases = data.get('aliases', []) or []
    max_n = 0
    for a in aliases:
        aid = a.get('id', '')
        if aid.startswith('alias_'):
            try:
                n = int(aid.split('_', 1)[1])
                if n > max_n:
                    max_n = n
            except ValueError:
                pass
    return f'alias_{max_n + 1:03d}'


class TranslatorReflector:
    """L7 reflector. 周期扫 SWM translator events, propose 新 alias."""

    def __init__(self, event_bus: Any = None):
        self.event_bus = event_bus
        self._stop = threading.Event()
        self._daemon: Optional[threading.Thread] = None
        self._stats = {
            'cycles_run': 0,
            'proposals_total': 0,
            'last_cycle_iso': '',
            'last_n_candidates': 0,
        }

    def run_cycle(self) -> List[Dict[str, Any]]:
        """1 轮: 扫 SWM events → 模式探测 → 写 review queue."""
        self._stats['cycles_run'] += 1
        self._stats['last_cycle_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        if self.event_bus is None:
            return []

        # 1. 扫 recent SWM events (translator_aliased / translator_rejected)
        try:
            events = self.event_bus.recent_events(
                within_seconds=_SCAN_WINDOW_S,
                types={'translator_aliased', 'translator_rejected'},
            ) if hasattr(self.event_bus, 'recent_events') else []
        except Exception:
            events = []

        if not events:
            return []

        # 2. 聚合模式: (from_organ, to_organ) → count
        pattern_counts: Dict[tuple, int] = {}
        pattern_kinds: Dict[tuple, str] = {}
        pattern_samples: Dict[tuple, List[str]] = {}
        for ev in events:
            meta = ev.get('metadata') or {}
            etype = ev.get('etype')
            if etype != 'translator_aliased':
                continue
            from_o = meta.get('from_organ')
            to_o = meta.get('to_organ')
            kind = meta.get('alias_kind')
            cmd = meta.get('command', '')
            # 仅 by_command alias 才值得 propose 持久化 (suffix_hands/exact 不需要)
            if kind != 'by_command' or not from_o or not to_o:
                continue
            key = (from_o, to_o)
            pattern_counts[key] = pattern_counts.get(key, 0) + 1
            pattern_kinds[key] = kind
            pattern_samples.setdefault(key, []).append(cmd)

        # 3. 阈值过滤 + 已存在不重复 propose
        # 🆕 [Phase 4.A / 2026-05-24 22:45] dedupe 扩展: review/active/rejected 都跳过.
        # 老 logic 只 dedupe active organ alias, 但:
        #   - status=review: 已在 review queue, 没必要重提
        #   - status=rejected: Sir 已明确 reject, 重提是骚扰 (Sir 准则 7 元否决)
        # 防 reflector 无限循环 propose Sir 不要的 alias.
        vocab = _load_vocab()
        existing = {(a.get('from'), a.get('to'))
                    for a in vocab.get('aliases', []) or []
                    if a.get('kind') == 'organ'
                    and a.get('status') in ('active', 'review', 'rejected')}

        new_proposals = []
        for (from_o, to_o), count in pattern_counts.items():
            if count < _PROPOSE_THRESHOLD:
                continue
            if (from_o, to_o) in existing:
                continue
            new_id = _next_alias_id(vocab)
            samples = pattern_samples.get((from_o, to_o), [])[:3]
            entry = {
                'id': new_id,
                'kind': 'organ',
                'from': from_o,
                'to': to_o,
                'status': 'review',
                'evidence': (
                    f"L7 reflector propose: {count} 次 by_command alias 在 {_SCAN_WINDOW_S/3600:.0f}h 内. "
                    f"samples: {', '.join(samples)}"
                ),
                'added_by': 'L7-TranslatorReflector',
                'added_at': datetime.utcnow().isoformat() + 'Z',
                'activated_by': None,
                'activated_at': None,
                'hit_count': count,
                'last_hit_at': None,
                'version': 1,
                'superseded_by': None,
            }
            vocab.setdefault('aliases', []).append(entry)
            new_proposals.append(entry)

        if new_proposals:
            _save_vocab(vocab)
            self._stats['proposals_total'] += len(new_proposals)

            # SWM publish 'translator_proposed' (Sir 看 review queue)
            try:
                if hasattr(self.event_bus, 'publish'):
                    top = new_proposals[0]
                    self.event_bus.publish(
                        etype='translator_proposed',
                        description=(
                            f"TranslatorReflector propose {len(new_proposals)} new alias(es). "
                            f"top: '{top['from']}' → '{top['to']}' ({top['hit_count']} hits)"
                        ),
                        source='TranslatorReflector',
                        salience=0.45,
                        metadata={
                            'n_new': len(new_proposals),
                            'top_id': top['id'],
                            'top_from': top['from'],
                            'top_to': top['to'],
                        },
                    )
            except Exception:
                pass

            # bg_log 让 Sir terminal 看到
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"📚 [TranslatorReflector] {len(new_proposals)} new alias(es) propose, "
                    f"Sir CLI: python scripts/translator_alias_dump.py list --status review"
                )
            except Exception:
                pass

        self._stats['last_n_candidates'] = len(new_proposals)
        return new_proposals

    def start_daemon(self) -> None:
        if self._daemon is not None and self._daemon.is_alive():
            return

        def _loop():
            time.sleep(_STARTUP_DELAY_S)
            while not self._stop.is_set():
                try:
                    self.run_cycle()
                except Exception:
                    pass
                self._stop.wait(_TICK_INTERVAL_S)

        self._daemon = threading.Thread(
            target=_loop, daemon=True, name='TranslatorReflector'
        )
        self._daemon.start()

    def stop(self) -> None:
        self._stop.set()

    def stats(self) -> Dict[str, Any]:
        return dict(self._stats)


_DEFAULT: Optional[TranslatorReflector] = None
_LOCK = threading.Lock()


def get_default_reflector() -> Optional[TranslatorReflector]:
    return _DEFAULT


def set_default_reflector(r: TranslatorReflector) -> None:
    global _DEFAULT
    with _LOCK:
        _DEFAULT = r


def reset_for_test() -> None:
    global _DEFAULT
    with _LOCK:
        if _DEFAULT is not None:
            _DEFAULT.stop()
        _DEFAULT = None
