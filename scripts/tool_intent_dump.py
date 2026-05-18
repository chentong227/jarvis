#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[P0+20-β.3.0-vocab1 / 2026-05-18] tool_intent_dump.py — tool_overture 触发 vocab 管理 CLI

Sir 准则 6.5: 一切层级架构 vocab 必须 (1) 持久化 json (2) CLI 可改 (3) L7 LLM-propose.
准则 6 治本: 旧 `_TOOL_INTENT_PATTERNS = (...)` 写死 in py → 迁
`memory_pool/tool_intent_vocab.json` + 此 CLI 管理.

用法:
  python scripts/tool_intent_dump.py                # list 所有 (含 review)
  python scripts/tool_intent_dump.py --active-only  # 只看 active
  python scripts/tool_intent_dump.py --review-list  # 只看待 Sir 审
  python scripts/tool_intent_dump.py --archived     # 只看已归档

  python scripts/tool_intent_dump.py --add ...      # 加新 pattern (见 --add 参数组)
  python scripts/tool_intent_dump.py --activate <id> # review → active
  python scripts/tool_intent_dump.py --reject <id>   # review/active → archived (软删)
  python scripts/tool_intent_dump.py --delete <id>   # 真删 (慎用)

  # --add 参数组示例:
  #   --add --id media_ctrl_zh --keywords "下一首,上一首,快进,倒退" \\
  #         --category device_control --note "媒体控制扩展"
  #   --add --id browser_ops_en --keywords "navigate,refresh,reload" \\
  #         --category actions --state active

注意: 命中规则是 substring (any(kw in user_input for kw in keywords)).
      短 keyword 容易误命中, Sir --add 时倾向 review 状态先, 实测 OK 再 --activate.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'tool_intent_vocab.json')

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
    print(f"📚 tool_intent_vocab.json — {len(patterns)} 条 {filter_state or '(all)'}")
    print("=" * 78)
    for p in patterns:
        state_emoji = {'active': '✅', 'review': '⏳',
                        'archived': '🗄️'}.get(p.get('state', '?'), '?')
        cat = p.get('category', '?')
        print(f"\n{state_emoji} [{p.get('state', '?'):8s}] {p.get('id', '?')}  "
              f"(category={cat})")
        kws = p.get('keywords', [])
        # 显示前 12 个关键词
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
        print(f"❌ id '{args.id}' 已存在 (用 --delete <id> 先删, 或 --activate/--reject 改 state)")
        return 1
    keywords = [k.strip() for k in args.keywords.split(',') if k.strip()]
    if not keywords:
        print("❌ --keywords 解析后为空 (期望逗号分隔字符串, 如 '打开,关闭')")
        return 1
    new_p = {
        'id': args.id,
        'category': args.category or 'misc',
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
    ap.add_argument('--active-only', action='store_true', help='仅看 active')
    ap.add_argument('--review-list', action='store_true', help='仅看 review')
    ap.add_argument('--archived', action='store_true', help='仅看 archived')

    ap.add_argument('--add', action='store_true', help='加新 pattern')
    ap.add_argument('--id', help='pattern id (唯一)')
    ap.add_argument('--keywords', help='触发关键词 (逗号分隔)')
    ap.add_argument('--category',
                    help='分类标签 (e.g. device_control / file_ops / search_query / actions / misc)')
    ap.add_argument('--state', choices=['active', 'review', 'archived'],
                    help='初始 state (默认 review, Sir 审后 --activate)')
    ap.add_argument('--note', help='备注')

    ap.add_argument('--activate', metavar='ID', help='review → active')
    ap.add_argument('--reject', metavar='ID', help='review/active → archived')
    ap.add_argument('--delete', metavar='ID', help='真删 (慎用)')

    args = ap.parse_args()

    if args.activate:
        return cmd_state_change(args.activate, 'active')
    if args.reject:
        return cmd_state_change(args.reject, 'archived')
    if args.delete:
        return cmd_delete(args.delete)
    if args.add:
        return cmd_add(args)

    if args.review_list:
        return cmd_list('review')
    if args.active_only:
        return cmd_list('active')
    if args.archived:
        return cmd_list('archived')
    return cmd_list('')


if __name__ == '__main__':
    sys.exit(main())
