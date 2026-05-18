#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[P0+20-β.3.4-vocab6 / 2026-05-18] feedback_vocab_dump.py — FeedbackTracker regex vocab CLI

Sir 准则 6.5: vocab 必须 (1) 持久化 (2) CLI 可改 (3) L7 LLM-propose.
特殊: 每条 entry 是 (regex, signal_type) 而非 keyword list. 顺序保留 (first match wins).

5 个 signal_type (Sir 加新 entry 必须指明):
  - correction: Sir 在纠正 (你搞错了 / actually)
  - confusion: Sir 困惑 (啥 / what?)
  - positive: Sir 满意 (谢谢 / perfect)
  - follow_up: Sir 要继续 (然后 / go on)
  - dismiss: Sir 让算了 (算了 / never mind)

用法:
  python scripts/feedback_vocab_dump.py
  python scripts/feedback_vocab_dump.py --active-only
  python scripts/feedback_vocab_dump.py --add --id positive_emoji \\
        --regex "(?:👍|👏|🎯)" --signal-type positive --category positive
  python scripts/feedback_vocab_dump.py --activate <id>
  python scripts/feedback_vocab_dump.py --reject <id>
  python scripts/feedback_vocab_dump.py --delete <id>

提示: regex 中文不要 \\b (中文无单词边界). 英文加 \\b 防 'not' 命中 'another'.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'feedback_vocab.json')

VALID_SIGNAL_TYPES = ('correction', 'confusion', 'positive',
                       'follow_up', 'dismiss')

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
    print(f"📚 feedback_vocab.json — {len(patterns)} 条 {filter_state or '(all)'}")
    print("=" * 78)
    for p in patterns:
        state_emoji = {'active': '✅', 'review': '⏳',
                        'archived': '🗄️'}.get(p.get('state', '?'), '?')
        st = p.get('signal_type', '?')
        cat = p.get('category', '?')
        print(f"\n{state_emoji} [{p.get('state', '?'):8s}] {p.get('id', '?')}  "
              f"(signal={st} / cat={cat})")
        rx = p.get('regex', '')
        if len(rx) > 100:
            print(f"    regex: {rx[:97]}...")
        else:
            print(f"    regex: {rx}")
        if p.get('note'):
            print(f"    note: {p['note']}")
    print()
    return 0


def cmd_add(args) -> int:
    if not args.id or not args.regex or not args.signal_type:
        print("❌ --add 必须传 --id + --regex + --signal-type")
        return 1
    if args.signal_type not in VALID_SIGNAL_TYPES:
        print(f"❌ --signal-type 必须是 {VALID_SIGNAL_TYPES}")
        return 1
    # validate regex compiles
    try:
        re.compile(args.regex)
    except re.error as e:
        print(f"❌ regex 编译失败: {e}")
        return 1
    data = _load()
    patterns = data.setdefault('patterns', [])
    if any(p.get('id') == args.id for p in patterns):
        print(f"❌ id '{args.id}' 已存在")
        return 1
    new_p = {
        'id': args.id,
        'category': args.category or args.signal_type,
        'signal_type': args.signal_type,
        'regex': args.regex,
        'state': args.state or 'review',
        'source': 'sir_added',
        'created_at': time.time(),
        'note': args.note or '',
    }
    patterns.append(new_p)
    _save(data)
    print(f"✅ 加入 pattern '{args.id}' state={new_p['state']} signal_type={args.signal_type}")
    print(f"   regex: {args.regex[:80]}{'...' if len(args.regex) > 80 else ''}")
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
    ap.add_argument('--regex', help='Python regex (raw 字符串)')
    ap.add_argument('--signal-type', dest='signal_type',
                    choices=list(VALID_SIGNAL_TYPES))
    ap.add_argument('--category', help='分类标签 (默认 = signal_type)')
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
