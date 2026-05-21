# -*- coding: utf-8 -*-
"""[Gap 5 / β.5.46-fix10] Reject Learner CLI Dump — Sir 拍板 propose.

Usage:
    python scripts/reject_learner_dump.py --list                # 看待 review propose
    python scripts/reject_learner_dump.py --run-now             # 立刻跑一次 cycle
    python scripts/reject_learner_dump.py --accept <id>         # 接受 propose
    python scripts/reject_learner_dump.py --reject <id> --note "reason"
    python scripts/reject_learner_dump.py --stats               # 看 daemon stats
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS)
sys.path.insert(0, _ROOT)

from jarvis_reject_learner import (
    list_review_queue,
    update_review_status,
    get_default_learner,
    RejectLearner,
)


def cmd_list():
    queue = list_review_queue()
    if not queue:
        print('[OK] No pending propose in review queue.')
        return
    print(f'[!] {len(queue)} pending propose(s):')
    print('=' * 80)
    for entry in queue:
        prop = entry.get('propose', {})
        print(f"ID:         {entry['id']}")
        print(f"  ts:         {entry.get('iso', '?')}")
        print(f"  rejects:    {entry.get('reject_count', '?')}")
        print(f"  type:       {prop.get('propose_type', '?')}")
        print(f"  target:     {prop.get('target', '')[:60]}")
        print(f"  rationale:  {prop.get('rationale', '')[:80]}")
        print(f"  delta:      {prop.get('delta', '')[:120]}")
        print(f"  confidence: {prop.get('confidence', 0):.2f}")
        # sample rejects
        excerpts = entry.get('reject_excerpts', [])
        if excerpts:
            print('  sample rejects:')
            for r in excerpts[:3]:
                print(f"    - [{r.get('verdict')}] {r.get('excerpt', '')[:60]}")
        print('-' * 80)
    print()
    print('Sir actions:')
    print('  python scripts/reject_learner_dump.py --accept <id>')
    print('  python scripts/reject_learner_dump.py --reject <id> --note "<reason>"')


def cmd_run_now():
    print('[Running] Reject Learner cycle...')
    try:
        from jarvis_key_router import get_default_router
        kr = get_default_router()
    except Exception as e:
        print(f'[ERR] no key_router: {e}')
        return
    learner = RejectLearner(key_router=kr)
    result = learner.run_cycle(force=True)
    if result is None:
        print('[OK] No propose generated this cycle (skip / no_action / cooldown).')
    else:
        print(f'[!] Propose generated: {result["id"]}')
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_accept(propose_id: str, note: str = ''):
    if update_review_status(propose_id, 'accepted', sir_note=note):
        print(f'[OK] {propose_id} marked accepted.')
        print('Note: applying propose to live registry needs manual edit '
              '(future: scripts/apply_reject_propose.py).')
    else:
        print(f'[ERR] {propose_id} not found in review queue.')


def cmd_reject(propose_id: str, note: str = ''):
    if update_review_status(propose_id, 'rejected', sir_note=note):
        print(f'[OK] {propose_id} marked rejected.')
    else:
        print(f'[ERR] {propose_id} not found.')


def cmd_stats():
    learner = get_default_learner()
    if learner is None:
        print('[!] No running learner registered (start jarvis_nerve first).')
        return
    print('Reject Learner runtime stats:')
    for k, v in learner.stats().items():
        print(f'  {k:30s} = {v}')


def main():
    parser = argparse.ArgumentParser(description='Reject Learner CLI')
    parser.add_argument('--list', action='store_true', help='list pending proposes')
    parser.add_argument('--run-now', action='store_true', help='run cycle now (real LLM)')
    parser.add_argument('--accept', type=str, help='accept propose id')
    parser.add_argument('--reject', type=str, help='reject propose id')
    parser.add_argument('--note', type=str, default='', help='sir note for accept/reject')
    parser.add_argument('--stats', action='store_true', help='runtime stats')
    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.run_now:
        cmd_run_now()
    elif args.accept:
        cmd_accept(args.accept, args.note)
    elif args.reject:
        cmd_reject(args.reject, args.note)
    elif args.stats:
        cmd_stats()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
