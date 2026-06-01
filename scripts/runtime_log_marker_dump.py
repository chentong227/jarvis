# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 18:54 真意 anchor FIX C] Runtime Log Marker Vocab CLI.

Sir 真意 (准则 6 vocab 持久化 + CLI 可改):
  "反思要看真日志, 终端省略了很多输出". marker 决定哪些 log line 进反思
  evidence. Sir 自己 add/remove marker, daemon 自动 reload (mtime check).

用法:
  python scripts/runtime_log_marker_dump.py list
  python scripts/runtime_log_marker_dump.py show
  python scripts/runtime_log_marker_dump.py add "[Hippocampus]"
  python scripts/runtime_log_marker_dump.py add "spawn_promise" --kind action_event_prefix
  python scripts/runtime_log_marker_dump.py remove "[Tone]"
  python scripts/runtime_log_marker_dump.py history          # 最近 30 ops
  python scripts/runtime_log_marker_dump.py review           # L7 propose 等 Sir 拍板

📌 [Sir 2026-05-26] L7 reflector (jarvis_log_marker_reflector) TODO,
   本期 Sir 手动 add/remove. 未来 LLM 自动 propose 新 marker.
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

import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_runtime_log_markers import (  # noqa: E402
    DEFAULT_VOCAB_PATH,
    add_marker,
    list_all,
    remove_marker,
)


def _print_section(title: str, items, max_show: int = 30) -> None:
    print(f"\n[{title}] ({len(items)} entries)")
    if not items:
        print("   (empty)")
        return
    for i, it in enumerate(items[:max_show], 1):
        print(f"   {i:3}. {it}")
    if len(items) > max_show:
        print(f"   ... +{len(items) - max_show} more")


def cmd_list(args):
    data = list_all(args.path)
    if not data:
        print(f"⚠️  {args.path} not found or empty")
        sys.exit(1)
    meta = data.get('_meta') or {}
    print(f"📋 Runtime Log Marker Vocab @ {args.path}")
    print(f"   schema_version: {meta.get('schema_version', '?')}")
    print(f"   purpose: {meta.get('purpose', '?')}")
    _print_section('action_event_prefixes',
                     data.get('action_event_prefixes') or [])
    _print_section('log_line_markers',
                     data.get('log_line_markers') or [])
    hist = data.get('history') or []
    rev = data.get('review_queue') or []
    print(f"\n[History] {len(hist)} ops (use 'history' cmd to see latest 30)")
    print(f"[Review Queue] {len(rev)} pending L7 proposals")


def cmd_show(args):
    """Show 是 list 的 alias (跟其他 dump CLI 风格统一)."""
    cmd_list(args)


def cmd_add(args):
    ok = add_marker(args.marker, kind=args.kind, path=args.path,
                       source='sir_cli')
    if ok:
        print(f"✅ added [{args.kind}] '{args.marker}'")
    else:
        data = list_all(args.path)
        key = ('log_line_markers' if args.kind == 'log_line'
                else 'action_event_prefixes')
        lst = data.get(key) or []
        if args.marker in lst:
            print(f"⚠️  '{args.marker}' already in [{args.kind}], no-op")
        else:
            print(f"❌ add failed (invalid marker or IO error)")
            sys.exit(1)


def cmd_remove(args):
    ok = remove_marker(args.marker, kind=args.kind, path=args.path,
                          source='sir_cli')
    if ok:
        print(f"✅ removed [{args.kind}] '{args.marker}'")
    else:
        data = list_all(args.path)
        key = ('log_line_markers' if args.kind == 'log_line'
                else 'action_event_prefixes')
        lst = data.get(key) or []
        if args.marker not in lst:
            print(f"⚠️  '{args.marker}' not in [{args.kind}], no-op")
        else:
            print(f"❌ remove failed (IO error)")
            sys.exit(1)


def cmd_history(args):
    data = list_all(args.path)
    hist = data.get('history') or []
    if not hist:
        print("(no history entries)")
        return
    print(f"📋 History ({len(hist)} ops, latest 30):")
    for e in hist[-30:]:
        print(f"   [{e.get('when', '?')}] {e.get('op', '?'):6} "
                f"[{e.get('kind', '?'):20}] "
                f"'{e.get('marker', '?')}' "
                f"({e.get('source', '?')})")


def cmd_review(args):
    """L7 propose 等 Sir 拍板 (本期 placeholder, L7 reflector 未实装)."""
    data = list_all(args.path)
    rev = data.get('review_queue') or []
    if not rev:
        print("(no L7 proposals waiting — reflector not yet implemented)")
        return
    print(f"📋 L7 Proposals ({len(rev)} pending):")
    for i, p in enumerate(rev, 1):
        print(f"\n   [{i}] proposed {p.get('when', '?')}")
        print(f"       kind: {p.get('kind')}")
        print(f"       marker: {p.get('marker')}")
        print(f"       rationale: {p.get('rationale', '')[:200]}")


def main():
    parser = argparse.ArgumentParser(
        description='InnerThought daemon Runtime Log Marker Vocab CLI '
                    '(Sir 2026-05-26 FIX C)')
    parser.add_argument('--path', default=DEFAULT_VOCAB_PATH)
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_list = sub.add_parser('list', help='列出全 vocab')
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser('show', help='同 list')
    p_show.set_defaults(func=cmd_show)

    p_add = sub.add_parser('add', help='加 marker (--kind log_line/action_event_prefix)')
    p_add.add_argument('marker')
    p_add.add_argument('--kind', default='log_line',
                        choices=['log_line', 'action_event_prefix'])
    p_add.set_defaults(func=cmd_add)

    p_rm = sub.add_parser('remove', help='删 marker')
    p_rm.add_argument('marker')
    p_rm.add_argument('--kind', default='log_line',
                       choices=['log_line', 'action_event_prefix'])
    p_rm.set_defaults(func=cmd_remove)

    p_hist = sub.add_parser('history', help='历史 ops (最近 30)')
    p_hist.set_defaults(func=cmd_history)

    p_rev = sub.add_parser('review', help='L7 propose 待 Sir 拍板 (TODO)')
    p_rev.set_defaults(func=cmd_review)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
