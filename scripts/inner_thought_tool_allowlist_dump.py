# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 19:48 Phase 3] InnerThought call_tool allowlist CLI.

Sir 真意 (准则 6 vocab 持久化 + 准则 7 元否决):
  thought call_tool actionable 高风险 — 错调 tool 让 Sir 反感.
  allowlist 持久化 JSON, Sir CLI add/remove 即时生效.

用法:
  python scripts/inner_thought_tool_allowlist_dump.py list
  python scripts/inner_thought_tool_allowlist_dump.py add commitment_register
  python scripts/inner_thought_tool_allowlist_dump.py remove milestone_register
  python scripts/inner_thought_tool_allowlist_dump.py history
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(
    ROOT, 'memory_pool', 'inner_thought_tool_allowlist.json'
)


def _load(path: str) -> dict:
    if not os.path.exists(path):
        print(f"⚠️  {path} not found")
        sys.exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(path: str, data: dict) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cmd_list(args):
    data = _load(args.path)
    meta = data.get('_meta') or {}
    print(f"📋 InnerThought call_tool allowlist @ {args.path}")
    print(f"   schema_version: {meta.get('schema_version', '?')}")
    print(f"   purpose: {meta.get('purpose', '?')[:120]}")
    print(f"\n[Allowed tools] ({len(data.get('allowlist', []))})")
    for t in data.get('allowlist', []):
        print(f"   ✅ {t}")
    print(f"\n[Explicitly forbidden]")
    for t in meta.get('explicitly_forbidden', []):
        print(f"   ❌ {t}")
    hist = data.get('history') or []
    print(f"\n[History] {len(hist)} ops "
            f"(use 'history' cmd to see latest 30)")


def cmd_add(args):
    data = _load(args.path)
    allow = data.get('allowlist') or []
    tool = args.tool.strip()
    if not tool:
        print("❌ tool name empty")
        sys.exit(1)
    if tool in allow:
        print(f"⚠️  '{tool}' already in allowlist")
        return
    allow.append(tool)
    data['allowlist'] = allow
    hist = data.get('history') or []
    hist.append({
        'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'op': 'add',
        'tool': tool,
        'source': 'sir_cli',
    })
    data['history'] = hist
    _save(args.path, data)
    print(f"✅ added '{tool}' to allowlist")


def cmd_remove(args):
    data = _load(args.path)
    allow = data.get('allowlist') or []
    tool = args.tool.strip()
    if tool not in allow:
        print(f"⚠️  '{tool}' not in allowlist")
        return
    allow.remove(tool)
    data['allowlist'] = allow
    hist = data.get('history') or []
    hist.append({
        'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'op': 'remove',
        'tool': tool,
        'source': 'sir_cli',
    })
    data['history'] = hist
    _save(args.path, data)
    print(f"✅ removed '{tool}' from allowlist")


def cmd_history(args):
    data = _load(args.path)
    hist = data.get('history') or []
    if not hist:
        print("(no history entries)")
        return
    print(f"📋 History ({len(hist)} ops, latest 30):")
    for e in hist[-30:]:
        print(f"   [{e.get('when', '?')}] {e.get('op', '?'):6} "
                f"'{e.get('tool', '?')}' ({e.get('source', '?')})")


def main():
    parser = argparse.ArgumentParser(
        description='InnerThought call_tool allowlist CLI (Sir 19:48 Phase 3)'
    )
    parser.add_argument('--path', default=DEFAULT_PATH)
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_list = sub.add_parser('list', help='列 allowlist + forbidden')
    p_list.set_defaults(func=cmd_list)

    p_add = sub.add_parser('add', help='加 tool 到 allowlist')
    p_add.add_argument('tool')
    p_add.set_defaults(func=cmd_add)

    p_rm = sub.add_parser('remove', help='删 tool')
    p_rm.add_argument('tool')
    p_rm.set_defaults(func=cmd_remove)

    p_hist = sub.add_parser('history', help='历史 ops (最近 30)')
    p_hist.set_defaults(func=cmd_history)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
