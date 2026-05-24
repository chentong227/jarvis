# -*- coding: utf-8 -*-
"""[Reshape 准则 6 / 2026-05-24] PhraseLock CLI — Sir 管反话术锁 review queue.

跟 reject_learner_dump / promise_dump / concerns_dump 同款风格 (准则 6.5).

用法:
  python scripts/phrase_lock_dump.py                 # 列 pending lock
  python scripts/phrase_lock_dump.py --all           # 含 accepted/rejected
  python scripts/phrase_lock_dump.py --accept <id>   # 接受 (Sir 同意是话术锁, 后续 directive 反向教)
  python scripts/phrase_lock_dump.py --reject <id>   # 拒绝 (phrase 是必要的)
  python scripts/phrase_lock_dump.py --run-now       # 强制立刻跑 cycle (不等 daemon)
  python scripts/phrase_lock_dump.py --json          # 机读
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _print_locks(locks: list, title: str):
    if not locks:
        print(f"📭 {title}: (空)")
        return
    print("=" * 78)
    print(f"  {title} ({len(locks)} 条)")
    print("=" * 78)
    for l in locks:
        status = l.get('status', '?')
        emoji = {'pending': '⏳', 'accepted': '✅', 'rejected': '❌'}.get(status, '?')
        print(f"\n  {emoji} {l.get('id', '?')}  [{status}]")
        print(f"    phrase  : {l.get('phrase', '')!r}")
        print(f"    lang    : {l.get('lang', '?')}")
        print(f"    count   : {l.get('count', 0)}")
        print(f"    diversity: {l.get('diversity', 0)} (turns)")
        print(f"    first   : {l.get('first_seen_iso', '')}")
        print(f"    last    : {l.get('last_seen_iso', '')}")
        if l.get('sample_turns'):
            print(f"    sample  : {l['sample_turns'][:3]}")


def main() -> int:
    p = argparse.ArgumentParser(description='PhraseLock CLI')
    p.add_argument('--all', action='store_true', help='含 accepted / rejected')
    p.add_argument('--accept', metavar='ID', help='接受 lock (是话术锁)')
    p.add_argument('--reject', metavar='ID', help='拒绝 lock (phrase 是必要的)')
    p.add_argument('--run-now', action='store_true', help='强制立刻跑 cycle')
    p.add_argument('--json', action='store_true', help='机读输出')
    args = p.parse_args()

    import jarvis_phrase_lock_detector as pld
    queue = pld._load_review()

    if args.run_now:
        det = pld.get_default_detector()
        new_locks = det.run_cycle()
        print(f"✅ ran cycle: {len(new_locks)} new lock(s) added")
        queue = pld._load_review()

    if args.accept:
        for entry in queue:
            if entry.get('id') == args.accept:
                entry['status'] = 'accepted'
                print(f"✅ accepted: {args.accept}")
                pld._save_review(queue)
                return 0
        print(f"❌ id not found: {args.accept}")
        return 1

    if args.reject:
        for entry in queue:
            if entry.get('id') == args.reject:
                entry['status'] = 'rejected'
                print(f"❌ rejected: {args.reject}")
                pld._save_review(queue)
                return 0
        print(f"❌ id not found: {args.reject}")
        return 1

    # 列 pending (default) or all
    if args.all:
        locks = queue
        title = 'All locks'
    else:
        locks = [l for l in queue if l.get('status') == 'pending']
        title = 'Pending locks (--all 含 accepted/rejected)'

    if args.json:
        print(json.dumps(locks, ensure_ascii=False, indent=2))
        return 0

    _print_locks(locks, title)
    return 0


if __name__ == '__main__':
    sys.exit(main())
