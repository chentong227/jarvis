#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[β.5.35-C / 2026-05-20] struggle_vocab_dump.py — Sir 抱怨 vocab CLI

Sir 2026-05-20 10:46 实测反馈: Conductor offer_help 误触 (基于屏幕 error 报错 ProactiveShield
触发, 而非 Sir 自己说困难). β.5.35-C 重设触发源: **Sir 嘴里说的话** 才是 offer_help 真信号
(屏幕 error 改 screen_tease 风格调皮观察).

准则 6 治本: 抱怨 vocab 持久化到 memory_pool/sir_struggle_vocab.json, 此 CLI 管理.
配套 design doc: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md

用法:
  python scripts/struggle_vocab_dump.py                  # list 所有 (含 review)
  python scripts/struggle_vocab_dump.py --active-only    # 只看 active
  python scripts/struggle_vocab_dump.py --review-list    # 只看待 Sir 审

  python scripts/struggle_vocab_dump.py --add <id> --patterns "a,b,c" --severity high
  python scripts/struggle_vocab_dump.py --add-pattern <phrase_id> <pattern>
  python scripts/struggle_vocab_dump.py --remove-pattern <phrase_id> <pattern>

  python scripts/struggle_vocab_dump.py --activate <id>  # review → active
  python scripts/struggle_vocab_dump.py --reject <id>    # review → rejected_history
  python scripts/struggle_vocab_dump.py --deactivate <id> # active → archived
  python scripts/struggle_vocab_dump.py --delete <id>    # 真删 (慎用)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'sir_struggle_vocab.json')

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def _load() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return {
            '_meta': {
                'schema_version': 1,
                'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            },
            'phrases': [],
            'review_queue': [],
            'rejected_history': [],
        }
    try:
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERR] read vocab failed: {e}")
        sys.exit(1)


def _save(data: dict) -> None:
    data.setdefault('_meta', {})['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    os.makedirs(os.path.dirname(VOCAB_PATH), exist_ok=True)
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, VOCAB_PATH)


def _find(data: dict, phrase_id: str) -> tuple:
    for i, c in enumerate(data.get('phrases', [])):
        if c.get('id') == phrase_id:
            return 'phrase', i, c
    for i, c in enumerate(data.get('review_queue', [])):
        if c.get('id') == phrase_id:
            return 'review', i, c
    return None, -1, None


def cmd_list(filter_state: str = '') -> int:
    data = _load()
    phrases = data.get('phrases', [])
    review_queue = data.get('review_queue', [])

    if filter_state == 'review':
        items = [(c, 'review') for c in review_queue]
    elif filter_state == 'active':
        items = [(c, 'phrase') for c in phrases if c.get('state', 'active') == 'active']
    else:
        items = [(c, 'phrase') for c in phrases] + [(c, 'review') for c in review_queue]

    if not items:
        print(f"(no {filter_state or 'any'} phrases)")
        return 0

    print(f"sir_struggle_vocab.json - {len(items)} phrases {filter_state or '(all)'}")
    print("=" * 78)
    for c, src in items:
        state = c.get('state', 'active')
        emoji = {'active': '[OK]', 'review': '[REV]',
                 'archived': '[ARC]'}.get(state, '[?]')
        sev = c.get('severity', '?')
        print(f"\n{emoji} [{state:8s}] [{sev:6s}] {c.get('id', '?')}  (src={src})")
        pats = c.get('patterns', [])
        print(f"    patterns ({len(pats)}): {', '.join(pats[:8])}" +
              (f" ... +{len(pats)-8}" if len(pats) > 8 else ''))
        if c.get('source'):
            print(f"    source: {c['source']}")
    print()
    return 0


def cmd_add(args) -> int:
    if not args.add or not args.patterns:
        print("[ERR] --add <id> + --patterns 'a,b,c' required")
        return 1
    data = _load()
    pid = args.add
    kind, _, existing = _find(data, pid)
    if existing is not None:
        print(f"[ERR] id '{pid}' already exists in {kind} (use --remove-pattern/--activate/--delete first)")
        return 1
    pats = [p.strip() for p in args.patterns.split(',') if p.strip()]
    sev = (args.severity or 'medium').lower()
    if sev not in ('low', 'medium', 'high'):
        print(f"[ERR] --severity must be low/medium/high, got {sev}")
        return 1
    item = {
        'id': pid,
        'state': 'active',
        'patterns': pats,
        'severity': sev,
        'source': args.source or f'manual add @ {time.strftime("%Y-%m-%dT%H:%M:%S")}',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    data.setdefault('phrases', []).append(item)
    _save(data)
    print(f"[OK] added phrase '{pid}' with {len(pats)} patterns (severity={sev}, active)")
    return 0


def cmd_add_pattern(phrase_id: str, pattern: str) -> int:
    data = _load()
    kind, _, item = _find(data, phrase_id)
    if item is None:
        print(f"[ERR] phrase '{phrase_id}' not found")
        return 1
    pats = item.setdefault('patterns', [])
    if pattern in pats:
        print(f"[OK] pattern '{pattern}' already in '{phrase_id}' (no-op)")
        return 0
    pats.append(pattern)
    _save(data)
    print(f"[OK] added pattern '{pattern}' to '{phrase_id}' ({len(pats)} total)")
    return 0


def cmd_remove_pattern(phrase_id: str, pattern: str) -> int:
    data = _load()
    kind, _, item = _find(data, phrase_id)
    if item is None:
        print(f"[ERR] phrase '{phrase_id}' not found")
        return 1
    pats = item.get('patterns', [])
    if pattern not in pats:
        print(f"[ERR] pattern '{pattern}' not in '{phrase_id}'")
        return 1
    pats.remove(pattern)
    _save(data)
    print(f"[OK] removed pattern '{pattern}' from '{phrase_id}' ({len(pats)} left)")
    return 0


def cmd_activate(phrase_id: str) -> int:
    data = _load()
    kind, idx, item = _find(data, phrase_id)
    if item is None:
        print(f"[ERR] '{phrase_id}' not found")
        return 1
    if kind == 'review':
        item['state'] = 'active'
        item['activated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        data['review_queue'].pop(idx)
        data.setdefault('phrases', []).append(item)
        _save(data)
        print(f"[OK] '{phrase_id}' moved from review_queue to active phrases")
    else:
        item['state'] = 'active'
        _save(data)
        print(f"[OK] '{phrase_id}' state -> active")
    return 0


def cmd_reject(phrase_id: str) -> int:
    data = _load()
    kind, idx, item = _find(data, phrase_id)
    if item is None:
        print(f"[ERR] '{phrase_id}' not found")
        return 1
    if kind != 'review':
        print(f"[ERR] '{phrase_id}' not in review_queue (use --deactivate to archive an active one)")
        return 1
    item['state'] = 'rejected'
    item['rejected_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    data['review_queue'].pop(idx)
    data.setdefault('rejected_history', []).append(item)
    _save(data)
    print(f"[OK] '{phrase_id}' moved from review_queue to rejected_history")
    return 0


def cmd_deactivate(phrase_id: str) -> int:
    data = _load()
    kind, _, item = _find(data, phrase_id)
    if item is None:
        print(f"[ERR] '{phrase_id}' not found")
        return 1
    if kind != 'phrase':
        print(f"[ERR] '{phrase_id}' not active (in {kind})")
        return 1
    item['state'] = 'archived'
    item['archived_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    _save(data)
    print(f"[OK] '{phrase_id}' state -> archived (will not trigger detector)")
    return 0


def cmd_delete(phrase_id: str) -> int:
    data = _load()
    kind, idx, item = _find(data, phrase_id)
    if item is None:
        print(f"[ERR] '{phrase_id}' not found")
        return 1
    if kind == 'phrase':
        data['phrases'].pop(idx)
    elif kind == 'review':
        data['review_queue'].pop(idx)
    _save(data)
    print(f"[OK] '{phrase_id}' DELETED from {kind} (was: state={item.get('state')})")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog='struggle_vocab_dump',
        description='Sir struggle/抱怨 vocab CLI (β.5.35-C)',
    )
    p.add_argument('--active-only', action='store_true')
    p.add_argument('--review-list', action='store_true')

    p.add_argument('--add', metavar='ID', help='add new phrase id')
    p.add_argument('--patterns', metavar='CSV', help='comma-separated patterns for --add')
    p.add_argument('--severity', metavar='LEVEL', help='low/medium/high (default medium)')
    p.add_argument('--source', metavar='STR')

    p.add_argument('--add-pattern', nargs=2, metavar=('PHRASE_ID', 'PATTERN'))
    p.add_argument('--remove-pattern', nargs=2, metavar=('PHRASE_ID', 'PATTERN'))

    p.add_argument('--activate', metavar='ID')
    p.add_argument('--reject', metavar='ID')
    p.add_argument('--deactivate', metavar='ID')
    p.add_argument('--delete', metavar='ID')

    args = p.parse_args(argv)

    if args.add:
        return cmd_add(args)
    if args.add_pattern:
        return cmd_add_pattern(args.add_pattern[0], args.add_pattern[1])
    if args.remove_pattern:
        return cmd_remove_pattern(args.remove_pattern[0], args.remove_pattern[1])
    if args.activate:
        return cmd_activate(args.activate)
    if args.reject:
        return cmd_reject(args.reject)
    if args.deactivate:
        return cmd_deactivate(args.deactivate)
    if args.delete:
        return cmd_delete(args.delete)

    if args.active_only:
        return cmd_list('active')
    if args.review_list:
        return cmd_list('review')
    return cmd_list()


if __name__ == '__main__':
    sys.exit(main())
