#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[P5-fix35-C / 2026-05-23 11:11] CyclicTask CLI — Sir 管理循环任务.

通用 cyclic_task organ 持久化 protocol 的 CLI 工具. Sir 看/取消/查 status.
跟 promise_dump / concerns_dump / mutation_dump 同款风格.

用法:
  python scripts/cyclic_task_dump.py                       # 列 active (default)
  python scripts/cyclic_task_dump.py --list-all            # 含 cancelled/completed
  python scripts/cyclic_task_dump.py --cancel <task_id>    # 取消
  python scripts/cyclic_task_dump.py --status <task_id>    # detail
  python scripts/cyclic_task_dump.py --json                # 机读
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
    from jarvis_cyclic_task import get_default_store, CyclicTaskStore
except Exception as e:
    print(f"[error] import jarvis_cyclic_task: {e}", file=sys.stderr)
    sys.exit(1)

# Hippocampus needed for cancel to actually remove future reminders
try:
    from jarvis_hippocampus import Hippocampus
    _HIPPOCAMPUS = Hippocampus(
        db_path=os.path.join(ROOT, 'memory_pool', 'jarvis_memory.db'))
except Exception:
    _HIPPOCAMPUS = None


def _list(active_only: bool, as_json: bool) -> int:
    store = get_default_store(hippocampus=_HIPPOCAMPUS)
    tasks = store.list_active() if active_only else store.list_all()
    if as_json:
        print(json.dumps(
            [t.to_dict() for t in tasks], ensure_ascii=False, indent=2))
        return 0
    if not tasks:
        print("📭 无 cyclic_task" + (" (active)" if active_only else ""))
        return 0
    print("=" * 78)
    print(f"  Cyclic Tasks ({len(tasks)} {'active' if active_only else 'all'})")
    print("=" * 78)
    for t in tasks:
        emoji = {'active': '🟢', 'cancelled': '🔴',
                  'completed': '✅'}.get(t.state, '⚪')
        print(f"\n{emoji} {t.task_id}  ({t.kind})  state={t.state}")
        print(f"  Description: {t.description[:80]}")
        print(f"  Cycle:       every {t.cycle_minutes} min")
        print(f"  Window:      {t.start_iso} → {t.end_iso}")
        print(f"  Fires:       {len(t.fire_ids)} scheduled "
                f"(reminder IDs: {t.fire_ids[:5]}{'...' if len(t.fire_ids) > 5 else ''})")
        print(f"  Intent:      {t.intent_template[:80]}")
        if t.state == 'cancelled':
            cancelled_iso = (time.strftime('%Y-%m-%d %H:%M',
                                              time.localtime(t.cancelled_at))
                              if t.cancelled_at else '?')
            print(f"  Cancelled:   {cancelled_iso}  reason={t.cancelled_reason[:60]}")
    print()
    return 0


def _cancel(task_id: str, reason: str) -> int:
    store = get_default_store(hippocampus=_HIPPOCAMPUS)
    r = store.cancel(task_id, reason=reason or 'CLI cancel')
    if not r.get('ok'):
        print(f"[error] {r.get('error')}", file=sys.stderr)
        return 1
    print(f"✅ Cancelled '{task_id}' — removed {r['n_removed']} pending reminders.")
    return 0


def _status(task_id: str, as_json: bool) -> int:
    store = get_default_store(hippocampus=_HIPPOCAMPUS)
    t = store.get(task_id)
    if not t:
        print(f"[error] task_id '{task_id}' not found", file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps(t.to_dict(), ensure_ascii=False, indent=2))
        return 0
    print("=" * 78)
    print(f"  cyclic_task: {t.task_id}")
    print("=" * 78)
    print(f"  Kind:        {t.kind}")
    print(f"  State:       {t.state}")
    print(f"  Description: {t.description}")
    print(f"  Cycle:       every {t.cycle_minutes} minutes")
    print(f"  Start:       {t.start_iso}")
    print(f"  End:         {t.end_iso}")
    print(f"  Intent:      {t.intent_template}")
    print(f"  Created at:  {time.strftime('%Y-%m-%d %H:%M', time.localtime(t.created_ts))}")
    print(f"  Created by:  {t.created_by}")
    print(f"  Fires:       {len(t.fire_ids)} scheduled")
    print(f"  Fire IDs:    {t.fire_ids}")
    if t.cancelled_at:
        print(f"  Cancelled:   {time.strftime('%Y-%m-%d %H:%M', time.localtime(t.cancelled_at))}")
        print(f"  Reason:      {t.cancelled_reason}")
    print()
    return 0


def main():
    p = argparse.ArgumentParser(description='CyclicTask CLI')
    p.add_argument('--list-all', action='store_true',
                     help='list all tasks (default: active only)')
    p.add_argument('--cancel', metavar='TASK_ID',
                     help='cancel an active cyclic_task by id')
    p.add_argument('--reason', default='',
                     help='reason for cancel (audit trail)')
    p.add_argument('--status', metavar='TASK_ID',
                     help='show detail of one task')
    p.add_argument('--json', action='store_true', help='JSON output')
    args = p.parse_args()

    if args.cancel:
        return _cancel(args.cancel, args.reason)
    if args.status:
        return _status(args.status, args.json)
    return _list(active_only=not args.list_all, as_json=args.json)


if __name__ == '__main__':
    sys.exit(main())
