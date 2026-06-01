#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[P0+20-β.4.3.1 / 2026-05-18] claim_classify_dump.py — L1 Claim Classifier vocab CLI

Sir 准则 6.5: vocab 必须 (1) 持久化 (2) CLI 可改 (3) L7 LLM-propose.

schema:
  patterns[] = {id, claim_type, kinds_hard_map[], keywords[], state, source, ...}
  claim_type ∈ {Past, Future, State, Recall, Social, Tool}
  state ∈ {active, review, archived}

用法:
  python scripts/claim_classify_dump.py
  python scripts/claim_classify_dump.py --active-only
  python scripts/claim_classify_dump.py --review-list
  python scripts/claim_classify_dump.py --type Past
  python scripts/claim_classify_dump.py --add --id custom_X \\
        --claim-type Future --keywords "I gonna,I shall" \\
        --kinds-hard-map "" --state review --note "Sir 加的口语 Future"
  python scripts/claim_classify_dump.py --activate <id>
  python scripts/claim_classify_dump.py --reject <id>
  python scripts/claim_classify_dump.py --delete <id>
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
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'claim_classify_vocab.json')

CLAIM_TYPES_CANONICAL = ('Past', 'Future', 'State', 'Recall', 'Social', 'Tool')

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


def _split_csv(s: str) -> list:
    if not s:
        return []
    return [x.strip() for x in s.split(',') if x.strip()]


def cmd_list(filter_state: str = '', filter_type: str = '') -> int:
    data = _load()
    patterns = data.get('patterns', [])
    if filter_state:
        patterns = [p for p in patterns if p.get('state') == filter_state]
    if filter_type:
        patterns = [p for p in patterns if p.get('claim_type') == filter_type]
    if not patterns:
        print(f"(无 {filter_state or '任何'} pattern" +
              (f", type={filter_type}" if filter_type else '') + ")")
        return 0
    print(f"📚 claim_classify_vocab.json — {len(patterns)} 条 "
          f"{filter_state or '(all)'}"
          + (f" / type={filter_type}" if filter_type else ''))
    print("=" * 78)
    by_type: dict = {}
    for p in patterns:
        by_type.setdefault(p.get('claim_type', '?'), []).append(p)
    for ct in sorted(by_type.keys()):
        print(f"\n🏷️  claim_type = {ct}")
        for p in by_type[ct]:
            state_emoji = {'active': '✅', 'review': '⏳',
                            'archived': '🗄️'}.get(p.get('state', '?'), '?')
            kws = p.get('keywords', []) or []
            hm = p.get('kinds_hard_map', []) or []
            print(f"  {state_emoji} [{p.get('state', '?'):8s}] {p.get('id', '?')}"
                  f"   ({len(hm)} kind hard-map, {len(kws)} keyword)")
            if hm:
                print(f"      kind: {hm}")
            head = kws[:8]
            if head:
                print(f"      kw: {head}" + (f" ... +{len(kws)-8}" if len(kws) > 8 else ''))
            if p.get('note'):
                print(f"      note: {p['note']}")
    print()
    return 0


def cmd_add(args) -> int:
    if not args.id or not args.claim_type:
        print("❌ --add 必须传 --id + --claim-type")
        return 1
    if args.claim_type not in CLAIM_TYPES_CANONICAL:
        print(f"❌ --claim-type 必须是 {CLAIM_TYPES_CANONICAL}, 你传 '{args.claim_type}'")
        return 1
    kws = _split_csv(args.keywords or '')
    hm = _split_csv(args.kinds_hard_map or '')
    if not kws and not hm:
        print("❌ --keywords 或 --kinds-hard-map 至少给一个")
        return 1
    data = _load()
    patterns = data.setdefault('patterns', [])
    if any(p.get('id') == args.id for p in patterns):
        print(f"❌ id '{args.id}' 已存在")
        return 1
    new_p = {
        'id': args.id,
        'claim_type': args.claim_type,
        'kinds_hard_map': hm,
        'keywords': kws,
        'state': args.state or 'review',
        'source': 'sir_added',
        'created_at': time.time(),
        'note': args.note or '',
    }
    patterns.append(new_p)
    _save(data)
    print(f"✅ 加入 pattern '{args.id}' state={new_p['state']} "
          f"type={args.claim_type}")
    print(f"   kind: {hm}  ({len(hm)})")
    print(f"   kw:   {kws[:5]}  ({len(kws)} total)")
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
    ap.add_argument('--type', dest='claim_type_filter',
                    help='仅看某 claim_type (Past/Future/...)')
    ap.add_argument('--add', action='store_true')
    ap.add_argument('--id', help='pattern entry id (唯一)')
    ap.add_argument('--claim-type', dest='claim_type',
                    help='claim_type (Past/Future/State/Recall/Social/Tool)')
    ap.add_argument('--kinds-hard-map', dest='kinds_hard_map',
                    help='extract_claims kind 硬映射, 逗号分隔 (e.g. "past_action")')
    ap.add_argument('--keywords', help='keyword 列表, 逗号分隔')
    ap.add_argument('--state', choices=['active', 'review', 'archived'])
    ap.add_argument('--note')
    ap.add_argument('--activate', metavar='ID')
    ap.add_argument('--reject', metavar='ID')
    ap.add_argument('--delete', metavar='ID')
    args = ap.parse_args()
    if args.activate:
        return cmd_state_change(args.activate, 'active')
    if args.reject:
        return cmd_state_change(args.reject, 'archived')
    if args.delete:
        return cmd_delete(args.delete)
    if args.add:
        return cmd_add(args)
    filter_state = ''
    if args.review_list:
        filter_state = 'review'
    elif args.active_only:
        filter_state = 'active'
    elif args.archived:
        filter_state = 'archived'
    return cmd_list(filter_state, args.claim_type_filter or '')


if __name__ == '__main__':
    sys.exit(main())
