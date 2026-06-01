#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[β.5.35-A / 2026-05-20] screen_tease_vocab_dump.py — screen_tease keyword vocab CLI

Sir 2026-05-20 10:46 实测反馈: SmartNudge screen_tease 一周静音 →
根因: error_kw / fun_kw / slack_kw 硬编码在 jarvis_smart_nudge.py:361-372,
跟不上 Sir 真实屏幕场景 (Cascade / Cursor / IDE 项目名 / 文档 / 教程都不在 vocab).

准则 6 治本: vocab 持久化到 memory_pool/screen_tease_vocab.json, 此 CLI 管理.
配套 design doc: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md

用法:
  python scripts/screen_tease_vocab_dump.py                  # list 所有 (含 review)
  python scripts/screen_tease_vocab_dump.py --active-only    # 只看 active
  python scripts/screen_tease_vocab_dump.py --review-list    # 只看待 Sir 审

  python scripts/screen_tease_vocab_dump.py --add <id> --keywords "a,b,c" \\
         --directive-hint "Sir 在 X" [--ttl-seconds N]
  python scripts/screen_tease_vocab_dump.py --add-keyword <category_id> <keyword>
  python scripts/screen_tease_vocab_dump.py --remove-keyword <category_id> <keyword>

  python scripts/screen_tease_vocab_dump.py --activate <id>  # review → active
  python scripts/screen_tease_vocab_dump.py --reject <id>    # review → rejected_history
  python scripts/screen_tease_vocab_dump.py --deactivate <id> # active → archived
  python scripts/screen_tease_vocab_dump.py --delete <id>    # 真删 (慎用)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'screen_tease_vocab.json')

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
            'categories': [],
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


def _find(data: dict, cat_id: str) -> tuple:
    """返回 (kind, idx, item). kind in {'category', 'review', None}."""
    for i, c in enumerate(data.get('categories', [])):
        if c.get('id') == cat_id:
            return 'category', i, c
    for i, c in enumerate(data.get('review_queue', [])):
        if c.get('id') == cat_id:
            return 'review', i, c
    return None, -1, None


def cmd_list(filter_state: str = '') -> int:
    data = _load()
    categories = data.get('categories', [])
    review_queue = data.get('review_queue', [])

    if filter_state == 'review':
        items = [(c, 'review') for c in review_queue]
    elif filter_state == 'active':
        items = [(c, 'category') for c in categories if c.get('state', 'active') == 'active']
    else:
        items = [(c, 'category') for c in categories] + [(c, 'review') for c in review_queue]

    if not items:
        print(f"(no {filter_state or 'any'} categories)")
        return 0

    print(f"screen_tease_vocab.json - {len(items)} categories {filter_state or '(all)'}")
    print("=" * 78)
    for c, src in items:
        state = c.get('state', 'active')
        emoji = {'active': '[OK]', 'review': '[REV]',
                 'archived': '[ARC]'}.get(state, '[?]')
        print(f"\n{emoji} [{state:8s}] {c.get('id', '?')}  (src={src})")
        kws = c.get('keywords', [])
        print(f"    keywords ({len(kws)}): {', '.join(kws[:10])}" +
              (f" ... +{len(kws)-10}" if len(kws) > 10 else ''))
        if c.get('directive_hint'):
            print(f"    hint: {c['directive_hint']}")
        if c.get('ttl_seconds'):
            print(f"    ttl: {c['ttl_seconds']} sec")
        if c.get('source'):
            print(f"    source: {c['source']}")
    print()
    return 0


def cmd_add(args) -> int:
    if not args.add or not args.keywords:
        print("[ERR] --add <id> + --keywords 'a,b,c' required")
        return 1
    data = _load()
    cat_id = args.add
    kind, _, existing = _find(data, cat_id)
    if existing is not None:
        print(f"[ERR] id '{cat_id}' already exists in {kind} (use --remove-keyword/--activate/--delete first)")
        return 1
    kws = [k.strip() for k in args.keywords.split(',') if k.strip()]
    item = {
        'id': cat_id,
        'state': 'active',
        'keywords': kws,
        'directive_hint': args.directive_hint or f"Sir 屏幕在 {cat_id}",
        'ttl_seconds': args.ttl_seconds,
        'source': args.source or f'manual add @ {time.strftime("%Y-%m-%dT%H:%M:%S")}',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    data.setdefault('categories', []).append(item)
    _save(data)
    print(f"[OK] added category '{cat_id}' with {len(kws)} keywords (active)")
    return 0


def cmd_add_keyword(cat_id: str, keyword: str) -> int:
    data = _load()
    kind, _, item = _find(data, cat_id)
    if item is None:
        print(f"[ERR] category '{cat_id}' not found")
        return 1
    kws = item.setdefault('keywords', [])
    if keyword in kws:
        print(f"[OK] keyword '{keyword}' already in '{cat_id}' (no-op)")
        return 0
    kws.append(keyword)
    _save(data)
    print(f"[OK] added keyword '{keyword}' to '{cat_id}' ({len(kws)} total)")
    return 0


def cmd_remove_keyword(cat_id: str, keyword: str) -> int:
    data = _load()
    kind, _, item = _find(data, cat_id)
    if item is None:
        print(f"[ERR] category '{cat_id}' not found")
        return 1
    kws = item.get('keywords', [])
    if keyword not in kws:
        print(f"[ERR] keyword '{keyword}' not in '{cat_id}'")
        return 1
    kws.remove(keyword)
    _save(data)
    print(f"[OK] removed keyword '{keyword}' from '{cat_id}' ({len(kws)} left)")
    return 0


def cmd_activate(cat_id: str) -> int:
    data = _load()
    kind, idx, item = _find(data, cat_id)
    if item is None:
        print(f"[ERR] '{cat_id}' not found")
        return 1
    if kind == 'review':
        item['state'] = 'active'
        item['activated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        data['review_queue'].pop(idx)
        data.setdefault('categories', []).append(item)
        _save(data)
        print(f"[OK] '{cat_id}' moved from review_queue to active categories")
    else:
        item['state'] = 'active'
        _save(data)
        print(f"[OK] '{cat_id}' state -> active")
    return 0


def cmd_reject(cat_id: str) -> int:
    data = _load()
    kind, idx, item = _find(data, cat_id)
    if item is None:
        print(f"[ERR] '{cat_id}' not found")
        return 1
    if kind != 'review':
        print(f"[ERR] '{cat_id}' not in review_queue (use --deactivate to archive an active one)")
        return 1
    item['state'] = 'rejected'
    item['rejected_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    data['review_queue'].pop(idx)
    data.setdefault('rejected_history', []).append(item)
    _save(data)
    print(f"[OK] '{cat_id}' moved from review_queue to rejected_history")
    return 0


def cmd_deactivate(cat_id: str) -> int:
    data = _load()
    kind, _, item = _find(data, cat_id)
    if item is None:
        print(f"[ERR] '{cat_id}' not found")
        return 1
    if kind != 'category':
        print(f"[ERR] '{cat_id}' not active (in {kind})")
        return 1
    item['state'] = 'archived'
    item['archived_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    _save(data)
    print(f"[OK] '{cat_id}' state -> archived (will not trigger nudge)")
    return 0


def cmd_delete(cat_id: str) -> int:
    data = _load()
    kind, idx, item = _find(data, cat_id)
    if item is None:
        print(f"[ERR] '{cat_id}' not found")
        return 1
    if kind == 'category':
        data['categories'].pop(idx)
    elif kind == 'review':
        data['review_queue'].pop(idx)
    _save(data)
    print(f"[OK] '{cat_id}' DELETED from {kind} (was: state={item.get('state')})")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog='screen_tease_vocab_dump',
        description='screen_tease keyword vocab CLI (β.5.35-A)',
    )
    p.add_argument('--active-only', action='store_true')
    p.add_argument('--review-list', action='store_true')

    p.add_argument('--add', metavar='ID', help='add new category id')
    p.add_argument('--keywords', metavar='CSV', help='comma-separated keywords for --add')
    p.add_argument('--directive-hint', metavar='STR', help='hint for main brain when matched')
    p.add_argument('--ttl-seconds', type=int, default=None)
    p.add_argument('--source', metavar='STR')

    p.add_argument('--add-keyword', nargs=2, metavar=('CAT_ID', 'KW'))
    p.add_argument('--remove-keyword', nargs=2, metavar=('CAT_ID', 'KW'))

    p.add_argument('--activate', metavar='ID')
    p.add_argument('--reject', metavar='ID')
    p.add_argument('--deactivate', metavar='ID')
    p.add_argument('--delete', metavar='ID')

    args = p.parse_args(argv)

    if args.add:
        return cmd_add(args)
    if args.add_keyword:
        return cmd_add_keyword(args.add_keyword[0], args.add_keyword[1])
    if args.remove_keyword:
        return cmd_remove_keyword(args.remove_keyword[0], args.remove_keyword[1])
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
