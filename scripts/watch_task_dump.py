# -*- coding: utf-8 -*-
"""[β.5.46-fix13 Fix-3] WatchTask CLI — list / show / cancel / expire

Sir 准则 6.5: 配置持久化, CLI 可改 (不需要改源码 + git commit).

Usage:
    cd d:/Jarvis
    python scripts/watch_task_dump.py list              # 列 active tasks
    python scripts/watch_task_dump.py list --all        # 列所有 (含 fired/cancelled/expired)
    python scripts/watch_task_dump.py show <task_id>    # 看单条详情
    python scripts/watch_task_dump.py cancel <task_id>  # 取消 active task
    python scripts/watch_task_dump.py expire <task_id>  # 强制 expire
    python scripts/watch_task_dump.py stats             # 统计

接 jarvis_watch_task.py 的 _load_tasks / cancel_task / expire_task.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_watch_task import (
    _load_tasks,
    cancel_task,
    expire_task,
    list_active_tasks,
)


def _fmt_dur(sec: float) -> str:
    if sec < 60:
        return f"{int(sec)}s"
    if sec < 3600:
        return f"{int(sec / 60)}min"
    return f"{sec / 3600:.1f}h"


def cmd_list(show_all: bool) -> int:
    tasks = _load_tasks() if show_all else list_active_tasks()
    if not tasks:
        print('(no tasks)')
        return 0
    print(f"{'ID':<14}{'STATE':<12}{'AGE':<8}{'EXPIRES':<12}{'WATCH':<60}")
    print('-' * 110)
    now = time.time()
    for t in tasks:
        age = _fmt_dur(now - t.created_at)
        if t.state == 'active' and t.expires_at > 0:
            exp = _fmt_dur(t.expires_at - now)
        else:
            exp = '-'
        watch = t.what_to_watch[:55]
        print(f"{t.id:<14}{t.state:<12}{age:<8}{exp:<12}{watch:<60}")
    return 0


def cmd_show(task_id: str) -> int:
    tasks = _load_tasks()
    for t in tasks:
        if t.id == task_id:
            print(f"=== WatchTask {t.id} ===")
            print(f"  state          : {t.state}")
            print(f"  created_at     : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t.created_at))}")
            if t.expires_at > 0:
                print(f"  expires_at     : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t.expires_at))}")
            if t.fired_at > 0:
                print(f"  fired_at       : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t.fired_at))}")
                print(f"  fired_evidence : {t.fired_evidence}")
            print(f"  turn_id        : {t.turn_id}")
            print()
            print(f"  what_to_watch  : {t.what_to_watch}")
            print(f"  trigger        : {t.trigger_evidence}")
            print(f"  notify_msg_en  : {t.notify_msg_en}")
            print(f"  notify_msg_zh  : {t.notify_msg_zh}")
            print()
            print(f"  judge_count    : {t.judge_count}")
            if t.last_judge_at > 0:
                age = _fmt_dur(time.time() - t.last_judge_at)
                print(f"  last_judge_at  : {age} ago")
                print(f"  last_judge_summary : {t.last_judge_summary}")
            print()
            print(f"  poll_via_screen_vision : {t.poll_via_screen_vision}")
            print()
            print(f"  sir_request    : {t.sir_request}")
            print(f"  jarvis_ack     : {t.jarvis_ack}")
            return 0
    print(f"task_id not found: {task_id}", file=sys.stderr)
    return 2


def cmd_cancel(task_id: str) -> int:
    ok = cancel_task(task_id)
    if ok:
        print(f"cancelled: {task_id}")
        return 0
    print(f"failed (not active or not found): {task_id}", file=sys.stderr)
    return 2


def cmd_expire(task_id: str) -> int:
    ok = expire_task(task_id)
    if ok:
        print(f"expired: {task_id}")
        return 0
    print(f"failed (not active or not found): {task_id}", file=sys.stderr)
    return 2


def cmd_stats() -> int:
    tasks = _load_tasks()
    counts = {'active': 0, 'fired': 0, 'cancelled': 0, 'expired': 0}
    judge_total = 0
    for t in tasks:
        counts[t.state] = counts.get(t.state, 0) + 1
        judge_total += t.judge_count
    print(f"Total tasks : {len(tasks)}")
    for s, c in counts.items():
        print(f"  {s:<10} : {c}")
    print(f"Judge calls : {judge_total}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description='WatchTask CLI dump')
    sub = p.add_subparsers(dest='cmd')

    pl = sub.add_parser('list')
    pl.add_argument('--all', action='store_true',
                     help='show all tasks (default: only active)')

    ps = sub.add_parser('show')
    ps.add_argument('task_id')

    pc = sub.add_parser('cancel')
    pc.add_argument('task_id')

    pe = sub.add_parser('expire')
    pe.add_argument('task_id')

    sub.add_parser('stats')

    args = p.parse_args()
    if args.cmd == 'list':
        return cmd_list(show_all=args.all)
    if args.cmd == 'show':
        return cmd_show(args.task_id)
    if args.cmd == 'cancel':
        return cmd_cancel(args.task_id)
    if args.cmd == 'expire':
        return cmd_expire(args.task_id)
    if args.cmd == 'stats':
        return cmd_stats()
    p.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
