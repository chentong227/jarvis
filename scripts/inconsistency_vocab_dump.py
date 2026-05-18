#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[P0+20-β.3.4-vocab4 / 2026-05-18] inconsistency_vocab_dump.py — InconsistencyWatcher vocab CLI

Sir 准则 6.5: vocab 必须 (1) 持久化 (2) CLI 可改 (3) L7 LLM-propose.
范式照搬 tool_intent_dump (β.3.0-vocab1).

3 类 vocab (category 必须是 sleep_commitment / break_commitment / wrapper_exclusion):
  - sleep_commitment: Sir 自承诺 sleep 动词 (命中 → 可能是 sleep promise)
  - break_commitment: Sir 自承诺 break 动词 (命中 → 可能是 break promise)
  - wrapper_exclusion: Jarvis 代理人称包装句 (命中 → 排除, 不是 Sir 自承诺)

用法:
  python scripts/inconsistency_vocab_dump.py
  python scripts/inconsistency_vocab_dump.py --active-only
  python scripts/inconsistency_vocab_dump.py --add --id sleep_zh_extra \\
        --keywords "我要去躺,我要去眯一下" --category sleep_commitment
  python scripts/inconsistency_vocab_dump.py --activate <id>
  python scripts/inconsistency_vocab_dump.py --reject <id>
  python scripts/inconsistency_vocab_dump.py --delete <id>
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'inconsistency_vocab.json')

VALID_CATEGORIES = ('sleep_commitment', 'break_commitment', 'wrapper_exclusion')

if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                        errors='replace')
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
    print(f"📚 inconsistency_vocab.json — {len(patterns)} 条 {filter_state or '(all)'}")
    print("=" * 78)
    # group by category
    by_cat: dict = {}
    for p in patterns:
        by_cat.setdefault(p.get('category', '?'), []).append(p)
    for cat in sorted(by_cat.keys()):
        print(f"\n📁 category = {cat}")
        for p in by_cat[cat]:
            state_emoji = {'active': '✅', 'review': '⏳',
                            'archived': '🗄️'}.get(p.get('state', '?'), '?')
            print(f"  {state_emoji} [{p.get('state', '?'):8s}] {p.get('id', '?')}")
            kws = p.get('keywords', [])
            head = kws[:10]
            print(f"      keywords: {', '.join(head)}" +
                  (f" ... +{len(kws)-10}" if len(kws) > 10 else ''))
            if p.get('note'):
                print(f"      note: {p['note']}")
    print()
    return 0


def cmd_add(args) -> int:
    if not args.id or not args.keywords or not args.category:
        print("❌ --add 必须传 --id + --keywords + --category")
        return 1
    if args.category not in VALID_CATEGORIES:
        print(f"❌ --category 必须是 {VALID_CATEGORIES} 之一")
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
        'category': args.category,
        'keywords': keywords,
        'state': args.state or 'review',
        'source': 'sir_added',
        'created_at': time.time(),
        'note': args.note or '',
    }
    patterns.append(new_p)
    _save(data)
    print(f"✅ 加入 pattern '{args.id}' state={new_p['state']} category={args.category}")
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
    ap.add_argument('--category', choices=list(VALID_CATEGORIES))
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
