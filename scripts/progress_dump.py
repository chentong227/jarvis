#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[P5-fix35-D / 2026-05-23 11:30] Progress CLI.

Sir 管 progress tracks (饮水/跑步/写作/...). 跟 cyclic_task_dump / promise_dump 同款.

用法:
  python scripts/progress_dump.py                         # active default
  python scripts/progress_dump.py --list-all              # 含 completed/cancelled
  python scripts/progress_dump.py --status <track_id>     # detail + history
  python scripts/progress_dump.py --update <track_id> --amount 500 --note "manual"
  python scripts/progress_dump.py --cancel <track_id>     # cancel
  python scripts/progress_dump.py --json                  # 机读
"""
from __future__ import annotations

import argparse
import json
import os
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from jarvis_progress_tracker import (
        ProgressTrackerStore, get_default_store
    )
except Exception as e:
    print(f"[error] import jarvis_progress_tracker: {e}", file=sys.stderr)
    sys.exit(1)


def _state_emoji(state: str) -> str:
    return {'active': '🟢', 'completed': '🎯',
              'cancelled': '🔴'}.get(state, '⚪')


def _list(active_only: bool, as_json: bool) -> int:
    store = get_default_store()
    tracks = store.list_active() if active_only else store.list_all()
    if as_json:
        print(json.dumps([t.to_dict() for t in tracks],
                            ensure_ascii=False, indent=2))
        return 0
    if not tracks:
        print("📭 无 progress track" + (" (active)" if active_only else ""))
        return 0
    print("=" * 78)
    print(f"  Progress Tracks ({len(tracks)} {'active' if active_only else 'all'})")
    print("=" * 78)
    for t in tracks:
        print(f"\n{_state_emoji(t.state)} {t.track_id}  "
                f"({t.kind}, state={t.state})")
        print(f"  Label:    {t.label or '(no label)'}")
        print(f"  Brief:    {t.render_brief()}")
        print(f"  Deadline: {t.deadline_iso or '(none)'}")
        if t.linked_cyclic_task:
            print(f"  Linked:   cyclic_task '{t.linked_cyclic_task}'")
        print(f"  History:  {len(t.history)} updates")
        if t.cancelled_reason:
            print(f"  Reason:   {t.cancelled_reason[:80]}")
    print()
    return 0


def _status(track_id: str, as_json: bool) -> int:
    store = get_default_store()
    r = store.status(track_id)
    if not r.get('ok'):
        print(f"[error] {r.get('error')}", file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    print("=" * 78)
    print(f"  progress.status: {track_id}")
    print("=" * 78)
    for k, v in r.items():
        if k == 'last_n_entries':
            print(f"  Last 3 history entries:")
            for h in v:
                ts_iso = time.strftime('%Y-%m-%d %H:%M',
                                          time.localtime(h.get('ts', 0)))
                print(f"    {ts_iso}  amount={h.get('amount')} "
                        f"note={h.get('note', '')[:40]}")
        elif k == 'ok':
            continue
        else:
            print(f"  {k}: {v}")
    print()
    return 0


def _update(track_id: str, amount: float, note: str) -> int:
    store = get_default_store()
    r = store.update(track_id=track_id, amount=amount,
                       note=note or 'CLI manual', source='sir_cli')
    if not r.get('ok'):
        print(f"[error] {r.get('error')}", file=sys.stderr)
        return 1
    print(f"✅ updated: {r['brief']}")
    if r.get('became_complete'):
        print(f"  🎯 已达成! "
                f"(linked cycle '{r.get('cancelled_linked_cycle', '')}' 已 cancel)")
    return 0


def _cancel(track_id: str, reason: str) -> int:
    store = get_default_store()
    r = store.cancel(track_id, reason=reason or 'CLI cancel')
    if not r.get('ok'):
        print(f"[error] {r.get('error')}", file=sys.stderr)
        return 1
    print(f"✅ cancelled '{track_id}'")
    return 0


def main():
    p = argparse.ArgumentParser(description='Progress Tracker CLI')
    p.add_argument('--list-all', action='store_true',
                     help='list all (default: active only)')
    p.add_argument('--status', metavar='TRACK_ID',
                     help='show detail of one track')
    p.add_argument('--update', metavar='TRACK_ID',
                     help='manually update progress (Sir CLI 加进度)')
    p.add_argument('--amount', type=float, default=0.0,
                     help='amount for --update')
    p.add_argument('--note', default='',
                     help='note for --update / --cancel')
    p.add_argument('--cancel', metavar='TRACK_ID',
                     help='cancel a track')
    p.add_argument('--json', action='store_true', help='JSON output')
    args = p.parse_args()

    if args.update:
        return _update(args.update, args.amount, args.note)
    if args.status:
        return _status(args.status, args.json)
    if args.cancel:
        return _cancel(args.cancel, args.note)
    return _list(active_only=not args.list_all, as_json=args.json)


if __name__ == '__main__':
    sys.exit(main())
