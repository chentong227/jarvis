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
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_watch_task import (
    DEFAULT_CONFIG_PATH,
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


# ============================================================
# 🆕 [fix50 / 2026-05-28] vague-phrases subcommand
# 准则 6 持久化 + CLI 可改 — Sir 加新 phrase 不需改 .py
# ============================================================


def _load_config_for_edit() -> dict:
    """读 watch_task_config.json. 不存在 → raise (避免误写空文件)."""
    if not os.path.exists(DEFAULT_CONFIG_PATH):
        raise SystemExit(
            f"❌ config file 不存在: {DEFAULT_CONFIG_PATH}. "
            f"先恢复 git 版本."
        )
    with open(DEFAULT_CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_config(data: dict) -> None:
    """atomic write watch_task_config.json."""
    tmp = DEFAULT_CONFIG_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, DEFAULT_CONFIG_PATH)


def cmd_vague_phrases(*, add_zh: str = '', add_en: str = '',
                        remove: str = '', list_only: bool = False) -> int:
    """list/add/remove vague_trigger_phrases_zh|en in watch_task_config.json."""
    cfg = _load_config_for_edit()
    zh_list = list(cfg.get('vague_trigger_phrases_zh') or [])
    en_list = list(cfg.get('vague_trigger_phrases_en') or [])
    changed = False
    if add_zh:
        if add_zh not in zh_list:
            zh_list.append(add_zh)
            cfg['vague_trigger_phrases_zh'] = zh_list
            changed = True
            print(f"✅ added vague_trigger_phrases_zh: '{add_zh}'")
        else:
            print(f"⚠️ already in zh list: '{add_zh}'")
    if add_en:
        if add_en.lower() not in [p.lower() for p in en_list]:
            en_list.append(add_en)
            cfg['vague_trigger_phrases_en'] = en_list
            changed = True
            print(f"✅ added vague_trigger_phrases_en: '{add_en}'")
        else:
            print(f"⚠️ already in en list: '{add_en}'")
    if remove:
        removed_from = []
        if remove in zh_list:
            zh_list.remove(remove)
            cfg['vague_trigger_phrases_zh'] = zh_list
            removed_from.append('zh')
            changed = True
        # case-insensitive remove for en
        en_lower_to_orig = {p.lower(): p for p in en_list}
        if remove.lower() in en_lower_to_orig:
            orig = en_lower_to_orig[remove.lower()]
            en_list.remove(orig)
            cfg['vague_trigger_phrases_en'] = en_list
            removed_from.append('en')
            changed = True
        if removed_from:
            print(f"✅ removed '{remove}' from {removed_from}")
        else:
            print(f"⚠️ '{remove}' not found in either list")

    if changed:
        _save_config(cfg)

    # 总是列出当前 vocab
    print()
    print(f"=== current vague_trigger_phrases ({DEFAULT_CONFIG_PATH}) ===")
    print(f"zh ({len(zh_list)}):")
    for p in zh_list:
        print(f"  - {p}")
    print(f"en ({len(en_list)}):")
    for p in en_list:
        print(f"  - {p}")

    # 顺手显 vague_clarify + vision_refresh_advice config
    print()
    print("=== vague_clarify config ===")
    print(json.dumps(cfg.get('vague_clarify') or {}, ensure_ascii=False, indent=2))
    print()
    print("=== vision_refresh_advice config ===")
    print(
        json.dumps(cfg.get('vision_refresh_advice') or {},
                    ensure_ascii=False, indent=2)
    )
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

    # 🆕 [fix50] vague-phrases subcommand
    pv = sub.add_parser(
        'vague-phrases',
        help='list/add/remove vague_trigger_phrases_zh|en in watch_task_config.json'
    )
    pv.add_argument('--add-zh', type=str, default='',
                     help='add 1 zh phrase (e.g. "盯一下")')
    pv.add_argument('--add-en', type=str, default='',
                     help='add 1 en phrase (e.g. "keep an eye on")')
    pv.add_argument('--remove', type=str, default='',
                     help='remove phrase from either list (case-insensitive en)')

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
    if args.cmd == 'vague-phrases':
        return cmd_vague_phrases(
            add_zh=args.add_zh, add_en=args.add_en, remove=args.remove,
        )
    p.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
