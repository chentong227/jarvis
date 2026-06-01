#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[P0+20-β.3.4-vocab7 / 2026-05-18] concern_keywords_dump.py — ConcernsReflector kw 加权 vocab CLI

Sir 准则 6.5: vocab 必须 (1) 持久化 (2) CLI 可改 (3) L7 LLM-propose.
特殊: entry 含 concern_id + List[{kw, severity_delta}], 不是简单 keyword.

用法:
  python scripts/concern_keywords_dump.py
  python scripts/concern_keywords_dump.py --active-only
  python scripts/concern_keywords_dump.py --concern sir_sleep_streak  # 只看某 concern
  python scripts/concern_keywords_dump.py --add --id custom_X \\
        --concern-id new_concern --kws-weighted "睡懒觉:0.10,赖床:0.08" \\
        --state review --note "Sir 加的赖床 vocab"
  python scripts/concern_keywords_dump.py --activate <id>
  python scripts/concern_keywords_dump.py --reject <id>
  python scripts/concern_keywords_dump.py --delete <id>

severity_delta 建议范围: 0.03-0.10 (单 keyword), 单轮 cap 0.15.
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
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'concern_keywords_vocab.json')

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


def _parse_kws_weighted(s: str) -> list:
    """'kw1:0.05,kw2:0.10' → [{'kw': 'kw1', 'severity_delta': 0.05}, ...]"""
    out = []
    for chunk in s.split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ':' not in chunk:
            raise ValueError(f"格式应为 'kw:delta', 看到 '{chunk}'")
        kw, delta_s = chunk.rsplit(':', 1)
        kw = kw.strip()
        try:
            delta = float(delta_s.strip())
        except ValueError:
            raise ValueError(f"delta '{delta_s}' 非合法 float")
        if not kw:
            raise ValueError(f"keyword 为空: '{chunk}'")
        out.append({'kw': kw, 'severity_delta': delta})
    return out


def cmd_list(filter_state: str = '', filter_concern: str = '') -> int:
    data = _load()
    patterns = data.get('patterns', [])
    if filter_state:
        patterns = [p for p in patterns if p.get('state') == filter_state]
    if filter_concern:
        patterns = [p for p in patterns if p.get('concern_id') == filter_concern]
    if not patterns:
        print(f"(无 {filter_state or '任何'} pattern" +
              (f", concern={filter_concern}" if filter_concern else '') + ")")
        return 0
    print(f"📚 concern_keywords_vocab.json — {len(patterns)} 条 "
          f"{filter_state or '(all)'}"
          + (f" / concern={filter_concern}" if filter_concern else ''))
    print("=" * 78)
    by_concern: dict = {}
    for p in patterns:
        by_concern.setdefault(p.get('concern_id', '?'), []).append(p)
    for cid in sorted(by_concern.keys()):
        print(f"\n🎯 concern_id = {cid}")
        for p in by_concern[cid]:
            state_emoji = {'active': '✅', 'review': '⏳',
                            'archived': '🗄️'}.get(p.get('state', '?'), '?')
            print(f"  {state_emoji} [{p.get('state', '?'):8s}] {p.get('id', '?')}")
            kws = p.get('keywords_weighted', [])
            head = kws[:8]
            kws_str = ', '.join(f"{k['kw']}:{k['severity_delta']}" for k in head)
            print(f"      {kws_str}" + (f" ... +{len(kws)-8}" if len(kws) > 8 else ''))
            if p.get('note'):
                print(f"      note: {p['note']}")
    print()
    return 0


def cmd_add(args) -> int:
    if not args.id or not args.concern_id or not args.kws_weighted:
        print("❌ --add 必须传 --id + --concern-id + --kws-weighted")
        return 1
    try:
        kws = _parse_kws_weighted(args.kws_weighted)
    except ValueError as e:
        print(f"❌ --kws-weighted 解析失败: {e}")
        return 1
    if not kws:
        print("❌ --kws-weighted 解析后为空")
        return 1
    data = _load()
    patterns = data.setdefault('patterns', [])
    if any(p.get('id') == args.id for p in patterns):
        print(f"❌ id '{args.id}' 已存在")
        return 1
    new_p = {
        'id': args.id,
        'concern_id': args.concern_id,
        'category': args.category or 'custom',
        'keywords_weighted': kws,
        'state': args.state or 'review',
        'source': 'sir_added',
        'created_at': time.time(),
        'note': args.note or '',
    }
    patterns.append(new_p)
    _save(data)
    print(f"✅ 加入 pattern '{args.id}' state={new_p['state']} concern={args.concern_id}")
    print(f"   {len(kws)} keyword(s): {[k['kw'] for k in kws]}")
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
    ap.add_argument('--concern', help='仅看某 concern_id')
    ap.add_argument('--add', action='store_true')
    ap.add_argument('--id', help='pattern entry id (唯一)')
    ap.add_argument('--concern-id', dest='concern_id',
                    help='对应 concern_id (e.g. sir_sleep_streak)')
    ap.add_argument('--kws-weighted', dest='kws_weighted',
                    help='kw:delta 列表, 逗号分隔 (e.g. "睡懒觉:0.10,赖床:0.08")')
    ap.add_argument('--category', help='分类标签')
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
    filter_state = ''
    if args.review_list: filter_state = 'review'
    elif args.active_only: filter_state = 'active'
    elif args.archived: filter_state = 'archived'
    return cmd_list(filter_state, args.concern or '')


if __name__ == '__main__':
    sys.exit(main())
