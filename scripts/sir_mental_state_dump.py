# -*- coding: utf-8 -*-
"""[Gap 1 / P5-ToM / 2026-05-21 01:10] Sir Mental State CLI

Sir 看 Jarvis 对自己当下心智的 hypothesis. 校正 / 重置 / 审计.

Usage:
    python scripts/sir_mental_state_dump.py                     # show current
    python scripts/sir_mental_state_dump.py --history            # show revisions
    python scripts/sir_mental_state_dump.py --history task       # only task field history
    python scripts/sir_mental_state_dump.py --correct task "Sir is debugging X"
    python scripts/sir_mental_state_dump.py --reset              # clear hypothesis
    python scripts/sir_mental_state_dump.py --json               # machine-readable
    python scripts/sir_mental_state_dump.py --stats              # quick stats
"""
from __future__ import annotations

import argparse
import json
import os
import sys


if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        os.system('chcp 65001 > nul 2>&1')
    except Exception:
        pass


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


_VALID_FIELDS = (
    'current_task_hypothesis', 'task_confidence', 'emotional_state',
    'emotional_confidence', 'surface_need', 'deeper_need', 'unspoken_need',
    'relational_temp',
)


def _show_current(store):
    s = store.get_snapshot()
    if not s.has_meaningful_content():
        print('[SirMentalState] (empty — no hypothesis yet)')
        print('  Tip: ToMReflector populates this after first turn with key_router.')
        return
    print('=' * 72)
    print('SIR MENTAL STATE — Jarvis hypothesis (last update: {})'.format(
        s.last_updated_iso or '(never)'
    ))
    print('  proposed_by: {}'.format(s.proposed_by))
    print('  source_turn_id: {}'.format(s.source_turn_id or '(none)'))
    print('=' * 72)
    print('[TASK]      {}'.format(s.current_task_hypothesis or '(none)'))
    print('             confidence: {:.2f}'.format(s.task_confidence))
    if s.task_evidence:
        print('             evidence: {}'.format(', '.join(s.task_evidence[:5])))
    print()
    print('[EMOTION]   {} (conf {:.2f})'.format(s.emotional_state, s.emotional_confidence))
    print()
    _conf = s.need_layers_confidence or {}
    print('[NEEDS]')
    print("  surface ({:.2f}): {}".format(_conf.get('surface', 0), s.surface_need or '(none)'))
    print("  deeper  ({:.2f}): {}".format(_conf.get('deeper', 0), s.deeper_need or '(none)'))
    print("  unspoken({:.2f}): {}".format(_conf.get('unspoken', 0), s.unspoken_need or '(none)'))
    print()
    print('[RELATIONAL] temp = {}'.format(s.relational_temp))
    if s.relational_evidence:
        print('             evidence: {}'.format(', '.join(s.relational_evidence[:3])))
    print('=' * 72)
    print('Total revisions: {}'.format(len(s.revision_history)))
    print('Stale ({}min)?: {}'.format(int(_stale_minutes(s)), s.is_stale()))


def _stale_minutes(s) -> float:
    import time as _t
    if s.last_updated <= 0:
        return 9999
    return (_t.time() - s.last_updated) / 60.0


def _show_history(store, field_filter: str = ''):
    s = store.get_snapshot()
    history = s.revision_history
    if field_filter:
        history = [h for h in history if h.get('field') == field_filter]
    if not history:
        print('[SirMentalState] (no revisions{})'.format(
            f' for field "{field_filter}"' if field_filter else ''
        ))
        return
    print('Revision history ({} entries{}):'.format(
        len(history),
        f', filtered to "{field_filter}"' if field_filter else ''
    ))
    print('-' * 72)
    for h in history[-20:]:
        print('  [{}] {}: "{}" → "{}"'.format(
            h.get('iso', '?'),
            h.get('field', '?'),
            (h.get('old', '') or '')[:50],
            (h.get('new', '') or '')[:50],
        ))
        if h.get('why'):
            print('    why: {}'.format(h['why'][:100]))


def _correct(store, field: str, new_value: str):
    if field not in _VALID_FIELDS:
        print('[ERROR] invalid field. Valid: {}'.format(', '.join(_VALID_FIELDS)))
        sys.exit(2)
    # try float conversion for confidence fields
    typed = new_value
    if 'confidence' in field:
        try:
            typed = float(new_value)
        except Exception:
            print('[ERROR] confidence must be float 0-1')
            sys.exit(2)
    ok = store.correct_field(field, typed, decided_by='sir_cli')
    if ok:
        print('[OK] corrected {} = "{}"'.format(field, str(typed)[:80]))
    else:
        print('[FAIL] could not update {}'.format(field))


def _reset(store):
    print('Reset will clear ALL hypothesis. Type "yes" to confirm:')
    try:
        ans = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print('[abort]')
        sys.exit(130)
    if ans != 'yes':
        print('[abort]')
        return
    from jarvis_sir_mental_model import SirMentalState
    with store._lock:
        store.state = SirMentalState()
        store._persist()
    print('[OK] reset done')


def main():
    p = argparse.ArgumentParser(description='Sir Mental State CLI (Layer 6 ToM)')
    p.add_argument('--history', nargs='?', const='', metavar='FIELD',
                    help='show revision history (optionally filter by field)')
    p.add_argument('--correct', nargs=2, metavar=('FIELD', 'VALUE'),
                    help='manually correct a field (e.g. --correct task_confidence 0.8)')
    p.add_argument('--reset', action='store_true', help='clear all hypothesis (confirm required)')
    p.add_argument('--json', action='store_true', help='machine-readable JSON')
    p.add_argument('--stats', action='store_true', help='quick stats')
    args = p.parse_args()

    from jarvis_sir_mental_model import get_default_store
    store = get_default_store()

    if args.json:
        snapshot = store.get_snapshot()
        print(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2))
        return

    if args.stats:
        for k, v in store.stats().items():
            print(f'  {k:25s} = {v}')
        return

    if args.history is not None:
        _show_history(store, field_filter=args.history)
        return

    if args.correct:
        _correct(store, args.correct[0], args.correct[1])
        return

    if args.reset:
        _reset(store)
        return

    # default: show current
    _show_current(store)


if __name__ == '__main__':
    main()
