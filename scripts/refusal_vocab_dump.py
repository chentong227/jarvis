# -*- coding: utf-8 -*-
"""[P0+20-β.5.22-F / 2026-05-19] Refusal Vocab CLI - Sir 管理 refusal_vocab.json.

提供 list / show / add / count 命令, Sir 不用改源码.
分类: generic / strong / dismissal_soft / sleep_soft.

用法:
  python scripts/refusal_vocab_dump.py list
  python scripts/refusal_vocab_dump.py show generic
  python scripts/refusal_vocab_dump.py show sleep_soft
  python scripts/refusal_vocab_dump.py add sleep_soft "晚点睡"
  python scripts/refusal_vocab_dump.py count
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


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(ROOT, 'memory_pool', 'refusal_vocab.json')

CATEGORIES = ('generic', 'strong', 'dismissal_soft', 'sleep_soft')


def _load(path: str) -> dict:
    if not os.path.exists(path):
        print(f"⚠️  {path} 不存在")
        sys.exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(path: str, data: dict) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cmd_list(args, data: dict) -> None:
    """列出所有分类 + 数量"""
    print(f"📋 Refusal Vocab @ {args.path}")
    print(f"   schema_version: {data.get('schema_version', '?')}")
    print(f"   note: {data.get('note', '')[:80]}")
    print()
    for cat in CATEGORIES:
        items = data.get(cat) or []
        print(f"   [{cat:18}] {len(items):3} items")
    print()
    print("Use `show <category>` to see content.")


def cmd_show(args, data: dict) -> None:
    """显示某分类的内容"""
    cat = args.category
    if cat not in CATEGORIES:
        print(f"❌ 未知分类 '{cat}'. 可选: {', '.join(CATEGORIES)}")
        sys.exit(1)
    items = data.get(cat) or []
    print(f"📋 [{cat}] ({len(items)} items):")
    for i, item in enumerate(items, 1):
        print(f"   {i:3}. {item}")


def cmd_add(args, data: dict) -> None:
    """添加新 keyword 到某分类"""
    cat = args.category
    keyword = args.keyword
    if cat not in CATEGORIES:
        print(f"❌ 未知分类 '{cat}'. 可选: {', '.join(CATEGORIES)}")
        sys.exit(1)
    items = data.get(cat) or []
    if keyword in items:
        print(f"⚠️  '{keyword}' 已存在 [{cat}], skip")
        return
    items.append(keyword)
    data[cat] = items
    _save(args.path, data)
    print(f"✅ 加入 '{keyword}' → [{cat}] ({len(items)} items)")


def cmd_count(args, data: dict) -> None:
    """统计总量"""
    total = 0
    for cat in CATEGORIES:
        n = len(data.get(cat) or [])
        total += n
        print(f"   {cat:18}: {n}")
    print(f"   ----")
    print(f"   total           : {total}")


def main():
    parser = argparse.ArgumentParser(
        description='Refusal Vocab CLI (β.5.22-F)')
    parser.add_argument('--path', default=DEFAULT_PATH,
                          help=f'json path (default: {DEFAULT_PATH})')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_list = sub.add_parser('list', help='列出所有分类 + 数量')
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser('show', help='显示某分类的全部内容')
    p_show.add_argument('category', choices=CATEGORIES)
    p_show.set_defaults(func=cmd_show)

    p_add = sub.add_parser('add', help='添加 keyword')
    p_add.add_argument('category', choices=CATEGORIES)
    p_add.add_argument('keyword')
    p_add.set_defaults(func=cmd_add)

    p_count = sub.add_parser('count', help='统计每分类 + 总量')
    p_count.set_defaults(func=cmd_count)

    args = parser.parse_args()
    data = _load(args.path)
    args.func(args, data)


if __name__ == '__main__':
    main()
