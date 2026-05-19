# -*- coding: utf-8 -*-
"""[P0+20-β.5.26 / 2026-05-20] Wake Filler Vocab CLI.

管理 memory_pool/wake_filler_vocab.json - 'hey jarvis' 类快唤醒时剥的语气词.

用法:
  python scripts/wake_filler_dump.py list
  python scripts/wake_filler_dump.py add "\\byes\\b"
  python scripts/wake_filler_dump.py count
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(ROOT, 'memory_pool', 'wake_filler_vocab.json')


def _load(path):
    if not os.path.exists(path):
        print(f"⚠️  {path} 不存在")
        sys.exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cmd_list(args, data):
    words = data.get('filler_words', [])
    print(f"📋 Wake Filler Vocab @ {args.path}")
    print(f"   schema_version: {data.get('schema_version', '?')}")
    print(f"   {len(words)} 条 filler:")
    for i, w in enumerate(words, 1):
        print(f"   {i:3}. {w}")


def cmd_add(args, data):
    words = data.get('filler_words', [])
    if args.word in words:
        print(f"⚠️  '{args.word}' 已存在")
        return
    words.append(args.word)
    data['filler_words'] = words
    _save(args.path, data)
    print(f"✅ 加入 '{args.word}' ({len(words)} 条)")


def cmd_count(args, data):
    words = data.get('filler_words', [])
    print(f"   filler_words: {len(words)}")


def main():
    parser = argparse.ArgumentParser(description='Wake Filler Vocab CLI (β.5.26)')
    parser.add_argument('--path', default=DEFAULT_PATH)
    sub = parser.add_subparsers(dest='cmd', required=True)
    p_list = sub.add_parser('list', help='列所有 filler')
    p_list.set_defaults(func=cmd_list)
    p_add = sub.add_parser('add', help='添加 filler 词 (regex pattern)')
    p_add.add_argument('word')
    p_add.set_defaults(func=cmd_add)
    p_count = sub.add_parser('count', help='统计')
    p_count.set_defaults(func=cmd_count)
    args = parser.parse_args()
    data = _load(args.path)
    args.func(args, data)


if __name__ == '__main__':
    main()
