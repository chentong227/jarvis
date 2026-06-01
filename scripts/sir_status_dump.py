#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[P5-SirStatusTracker / 2026-05-21 15:30] Sir Status CLI

Sir 准则 6 — vocab + state 持久化 + CLI manage.

用法:
  python scripts/sir_status_dump.py --current      # 看当前 status
  python scripts/sir_status_dump.py --history       # 看最近 transitions
  python scripts/sir_status_dump.py --reset         # 重置回 unknown
  python scripts/sir_status_dump.py --set sleep --kw '睡觉了' (Sir 手动 force)
  python scripts/sir_status_dump.py --vocab-list   # 看 vocab
  python scripts/sir_status_dump.py --vocab-add sleep --en 'gonna crash'
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def cmd_current(_args) -> None:
    from jarvis_sir_status_tracker import current_status
    c = current_status()
    if c['status'] in ('unknown', 'active'):
        print(f"\n=== Sir Current Status ===\n  status: {c['status']}  (Sir 没 declare 特殊状态)")
        return
    age_min = int(c['age_s'] / 60)
    expected_min = int(c['expected_return_s'] / 60)
    print(f"\n=== Sir Current Status ===")
    print(f"  status      : {c['status']}")
    print(f"  since       : {c['since_iso']} ({age_min}min ago)")
    print(f"  expected    : ~{expected_min}min back")
    print(f"  overdue     : {c['is_overdue']}")
    print(f"  last_keyword: {c['last_keyword']}")
    print(f"  utterance   : \"{c['last_utterance_excerpt']}\"")
    print(f"  turn_id     : {c['last_turn_id']}")


def cmd_history(_args) -> None:
    from jarvis_sir_status_tracker import get_default_store
    store = get_default_store()
    cur = store.current()
    if not cur.history:
        print('(no history)')
        return
    print(f"\n=== Sir Status History ({len(cur.history)} transitions) ===\n")
    for h in cur.history[-20:]:
        ts = h.get('at_ts', 0)
        iso = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts)) if ts else '?'
        dur = int(h.get('duration_s', 0))
        dur_str = f'{dur//60}m {dur%60}s' if dur else '?'
        print(f"  {iso}: {h.get('from'):10s} → {h.get('to'):10s} (after {dur_str}, {h.get('reason','')[:60]})")


def cmd_reset(_args) -> None:
    from jarvis_sir_status_tracker import get_default_store, STATUS_ACTIVE
    store = get_default_store()
    store.update_status('back', 'sir_cli_reset', 'Sir 手动 reset', 'cli')
    print(f"✅ status reset to {STATUS_ACTIVE}")


def cmd_set(args) -> None:
    from jarvis_sir_status_tracker import get_default_store
    store = get_default_store()
    new_status = (args.set_status or '').strip()
    if not new_status:
        print('--set requires status name')
        return
    kw = (args.kw or 'sir_cli_force').strip()
    ok = store.update_status(new_status, kw, f'force from CLI: {kw}', 'cli')
    if ok:
        print(f'✅ status forced to {new_status}')
    else:
        print(f'⏭ status unchanged (already {new_status} or low priority)')


def cmd_vocab_list(_args) -> None:
    vocab_path = os.path.join(ROOT, 'memory_pool', 'sir_status_vocab.json')
    if not os.path.exists(vocab_path):
        print(f'(no vocab: {vocab_path})')
        return
    with open(vocab_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    patterns = data.get('patterns') or {}
    print(f"\n=== Sir Status Vocab ({len(patterns)} statuses) ===\n")
    for k, entry in patterns.items():
        en_n = len(entry.get('en') or [])
        zh_n = len(entry.get('zh') or [])
        label = entry.get('label', '?')
        print(f"  {k:12s} {label} (en={en_n}, zh={zh_n})")
        if _args.verbose:
            print(f"    en: {', '.join(entry.get('en') or [])}")
            print(f"    zh: {', '.join(entry.get('zh') or [])}")


def cmd_vocab_add(args) -> None:
    vocab_path = os.path.join(ROOT, 'memory_pool', 'sir_status_vocab.json')
    if not os.path.exists(vocab_path):
        print(f'(no vocab: {vocab_path})')
        return
    with open(vocab_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    patterns = data.setdefault('patterns', {})
    status_key = (args.vocab_add or '').strip()
    if status_key not in patterns:
        print(f'❌ no such status: {status_key}')
        return
    entry = patterns[status_key]
    if args.en:
        en_list = entry.setdefault('en', [])
        if args.en in en_list:
            print(f'⏭ already in en: {args.en}')
            return
        en_list.append(args.en)
        print(f'✅ added en: {args.en}')
    if args.zh:
        zh_list = entry.setdefault('zh', [])
        if args.zh in zh_list:
            print(f'⏭ already in zh: {args.zh}')
            return
        zh_list.append(args.zh)
        print(f'✅ added zh: {args.zh}')
    data.setdefault('_meta', {})['updated_at'] = time.time()
    data['_meta']['updated_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())
    tmp = vocab_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, vocab_path)


def main() -> int:
    p = argparse.ArgumentParser(description='Sir Status Tracker CLI')
    p.add_argument('--current', action='store_true', help='show current status')
    p.add_argument('--history', action='store_true', help='show history transitions')
    p.add_argument('--reset', action='store_true', help='force reset to active')
    p.add_argument('--set', dest='set_status', type=str, default='',
                    metavar='STATUS', help='force set status (sleep/nap/lunch/...)')
    p.add_argument('--kw', type=str, default='', help='keyword (with --set)')
    p.add_argument('--vocab-list', action='store_true', help='list status vocab')
    p.add_argument('--vocab-add', type=str, default='', metavar='STATUS_KEY',
                    help='add keyword to status (use with --en or --zh)')
    p.add_argument('--en', type=str, default='', help='english keyword')
    p.add_argument('--zh', type=str, default='', help='chinese keyword')
    p.add_argument('--verbose', '-v', action='store_true')
    args = p.parse_args()

    if args.current:
        cmd_current(args)
    elif args.history:
        cmd_history(args)
    elif args.reset:
        cmd_reset(args)
    elif args.set_status:
        cmd_set(args)
    elif args.vocab_list:
        cmd_vocab_list(args)
    elif args.vocab_add:
        cmd_vocab_add(args)
    else:
        p.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
