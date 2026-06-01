#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[P0+20-β.3.4-vocab3 / 2026-05-18] memory_correction_dump.py — memory_update_honesty vocab CLI

Sir 准则 6.5: vocab 必须 (1) 持久化 json (2) CLI 可改 (3) L7 LLM-propose.
范式照搬 tool_intent_dump (β.3.0-vocab1) — 详 commit 63611f3.

用法:
  python scripts/memory_correction_dump.py                # list 所有
  python scripts/memory_correction_dump.py --active-only
  python scripts/memory_correction_dump.py --review-list
  python scripts/memory_correction_dump.py --archived

  python scripts/memory_correction_dump.py --add --id X --keywords "其实,你听错了" --category correction
  python scripts/memory_correction_dump.py --activate <id>
  python scripts/memory_correction_dump.py --reject <id>
  python scripts/memory_correction_dump.py --delete <id>
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'memory_correction_vocab.json')

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def _load() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return {'_meta': {'schema_version': 1,
                          'created_at': time.strftime('%Y-%m-%dT%H:%M:%S')},
                'patterns': []}
    try:
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ 读 vocab 失败: {e}")
        sys.exit(1)


def _save(data: dict) -> None:
    data.setdefault('_meta', {})['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    os.makedirs(os.path.dirname(VOCAB_PATH), exist_ok=True)
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, VOCAB_PATH)


def cmd_list(filter_state: str = '') -> int:
    data = _load()
    patterns = data.get('patterns', [])
    if filter_state:
        patterns = [p for p in patterns if p.get('state') == filter_state]
    if not patterns:
        print(f"(无 {filter_state or '任何'} pattern)")
        return 0
    print(f"📚 memory_correction_vocab.json — {len(patterns)} 条 {filter_state or '(all)'}")
    print("=" * 78)
    for p in patterns:
        state_emoji = {'active': '✅', 'review': '⏳',
                        'archived': '🗄️'}.get(p.get('state', '?'), '?')
        cat = p.get('category', '?')
        print(f"\n{state_emoji} [{p.get('state', '?'):8s}] {p.get('id', '?')}  "
              f"(category={cat})")
        kws = p.get('keywords', [])
        head = kws[:12]
        print(f"    keywords: {', '.join(head)}" +
              (f" ... +{len(kws)-12}" if len(kws) > 12 else ''))
        if p.get('source'):
            print(f"    source: {p['source']}")
        if p.get('note'):
            print(f"    note: {p['note']}")
    print()
    return 0


def cmd_add(args) -> int:
    if not args.id or not args.keywords:
        print("❌ --add 必须传 --id + --keywords")
        return 1
    data = _load()
    patterns = data.setdefault('patterns', [])
    if any(p.get('id') == args.id for p in patterns):
        print(f"❌ id '{args.id}' 已存在")
        return 1
    keywords = [k.strip() for k in args.keywords.split(',') if k.strip()]
    if not keywords:
        print("❌ --keywords 解析后为空")
        return 1
    new_p = {
        'id': args.id,
        'category': args.category or 'correction',
        'keywords': keywords,
        'state': args.state or 'review',
        'source': 'sir_added',
        'created_at': time.time(),
        'note': args.note or '',
    }
    patterns.append(new_p)
    _save(data)
    print(f"✅ 加入 pattern '{args.id}' state={new_p['state']} category={new_p['category']}")
    print(f"   keywords ({len(keywords)}): {keywords}")
    return 0


def cmd_state_change(pid: str, new_state: str) -> int:
    data = _load()
    for p in data.get('patterns', []):
        if p.get('id') == pid:
            old = p.get('state', '?')
            p['state'] = new_state
            _save(data)
            print(f"✅ pattern '{pid}': {old} → {new_state}")
            return 0
    print(f"❌ pattern id '{pid}' 不存在")
    return 1


def cmd_delete(pid: str) -> int:
    data = _load()
    before = len(data.get('patterns', []))
    data['patterns'] = [p for p in data.get('patterns', []) if p.get('id') != pid]
    if len(data['patterns']) == before:
        print(f"❌ pattern id '{pid}' 不存在")
        return 1
    _save(data)
    print(f"🗑️  真删 pattern '{pid}'")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--active-only', action='store_true')
    ap.add_argument('--review-list', action='store_true')
    ap.add_argument('--archived', action='store_true')
    ap.add_argument('--add', action='store_true')
    ap.add_argument('--id')
    ap.add_argument('--keywords')
    ap.add_argument('--category')
    ap.add_argument('--state', choices=['active', 'review', 'archived'])
    ap.add_argument('--note')
    ap.add_argument('--activate', metavar='ID')
    ap.add_argument('--reject', metavar='ID')
    ap.add_argument('--delete', metavar='ID')
    args = ap.parse_args()
    if args.activate: return cmd_state_change(args.activate, 'active')
    if args.reject: return cmd_state_change(args.reject, 'archived')
    if args.delete: return cmd_delete(args.delete)
    if args.add: return cmd_add(args)
    if args.review_list: return cmd_list('review')
    if args.active_only: return cmd_list('active')
    if args.archived: return cmd_list('archived')
    return cmd_list('')


if __name__ == '__main__':
    sys.exit(main())
