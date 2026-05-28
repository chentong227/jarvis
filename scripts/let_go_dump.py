#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[Sir 2026-05-29 governor Phase 2 F4] Let-go topics CLI 工具.

Sir 真痛 anchor: "重复思考严重, 放下元能力一直没立".

准则 6 三维耦合:
  数据: memory_pool/let_go_topics.json
  决策: LLM 自决 <LET_GO>thread_id</LET_GO> 输出 (思考脑 prompt 教)
  CLI: 本工具让 Sir 不改源码 + 不 git commit 就能 inspect / 强解锁 / extend

Subcommands:
  list        列出 active let_go topics (含 TTL remaining + reason + source)
  add         手动加 let_go thread_id (source=sir_manual)
  extend      extend 已有 let_go topic TTL
  revoke      强解锁某 thread_id (Sir 元否决 LLM 决定, 准则 7)
  clear       清空所有 let_go (危险, 需 --yes)
  config      显示 topic_repeat vocab config + path
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Windows GBK utf-8 fix (复用 _cli_utils)
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
try:
    import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout
except Exception:
    pass

if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _fmt_ttl(sec: int) -> str:
    if sec <= 0:
        return "expired"
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m{sec % 60}s"
    return f"{sec // 3600}h{(sec % 3600) // 60}m"


def cmd_list(_args) -> int:
    """List active let_go topics."""
    from jarvis_inner_thought_daemon import (
        _load_let_go_topics, _LET_GO_TOPICS_PATH,
    )
    active = _load_let_go_topics()
    print(f"[storage path] {_LET_GO_TOPICS_PATH}")
    print(f"[file exists]  {os.path.exists(_LET_GO_TOPICS_PATH)}")
    print(f"[active count] {len(active)}")
    if not active:
        print("(no active let_go topics)")
        return 0
    now = time.time()
    print()
    for i, e in enumerate(active, 1):
        ttl_s = int(float(e.get('ttl_ts', 0)) - now)
        print(f"  [{i}] thread_id = {e.get('thread_id', '?')}")
        print(f"      source     = {e.get('source', '?')}")
        print(f"      TTL left   = {_fmt_ttl(ttl_s)}")
        print(f"      created    = {e.get('created_at_iso', '?')}")
        print(f"      reason     = {e.get('reason', '(none)')[:100]}")
        if e.get('last_extended_at_iso'):
            print(f"      last_ext   = {e['last_extended_at_iso']}")
        ext_count = len(e.get('extend_history', []) or [])
        if ext_count:
            print(f"      extends    = {ext_count} time(s)")
        print()
    return 0


def cmd_add(args) -> int:
    """Manually add a let_go (source=sir_manual)."""
    from jarvis_inner_thought_daemon import _add_let_go_topic
    ok = _add_let_go_topic(
        thread_id=args.thread_id,
        ttl_min=args.ttl_min,
        source='sir_manual',
        thought_id='',
        reason=args.reason or 'Sir manual let-go via CLI',
    )
    if ok:
        print(f"✅ added/extended let_go for thread_id={args.thread_id} "
              f"(TTL {args.ttl_min}min, source=sir_manual)")
        return 0
    else:
        print(f"❌ failed to add let_go for thread_id={args.thread_id}",
              file=sys.stderr)
        return 1


def cmd_extend(args) -> int:
    """Extend TTL of existing let_go (alias of add — _add 自动 extend if exists)."""
    return cmd_add(args)


def cmd_revoke(args) -> int:
    """Force-remove a let_go topic (Sir 元否决 LLM, 准则 7)."""
    from jarvis_inner_thought_daemon import _remove_let_go_topic
    ok = _remove_let_go_topic(args.thread_id)
    if ok:
        print(f"✅ revoked let_go for thread_id={args.thread_id} "
              f"(Sir 元否决, 思考脑下轮重新看到该 thread)")
        return 0
    else:
        print(f"⚠️  thread_id={args.thread_id} 不在 active let_go list",
              file=sys.stderr)
        return 1


def cmd_clear(args) -> int:
    """Clear all let_go topics (危险, 需 --yes)."""
    if not args.yes:
        print("⚠️  needs --yes to confirm clearing all let_go topics",
              file=sys.stderr)
        return 1
    from jarvis_inner_thought_daemon import (
        _load_let_go_topics, _save_let_go_topics,
    )
    active = _load_let_go_topics()
    count = len(active)
    ok = _save_let_go_topics([])
    if ok:
        print(f"✅ cleared {count} let_go topic(s)")
        return 0
    else:
        print("❌ failed to clear", file=sys.stderr)
        return 1


def cmd_config(_args) -> int:
    """Show topic_repeat vocab + path."""
    from jarvis_inner_thought_daemon import _get_topic_repeat_config
    from jarvis_inner_voice_track import _AGING_CONFIG_PATH, _load_aging_config
    max_occ, win_min, default_ttl = _get_topic_repeat_config()
    cfg = _load_aging_config()
    tr = cfg.get('topic_repeat', {})
    print(f"[vocab path]   {_AGING_CONFIG_PATH}")
    print(f"[file exists]  {os.path.exists(_AGING_CONFIG_PATH)}")
    print()
    print(f"[active config] (after sanity cap)")
    print(f"  max_occurrences_in_window = {max_occ}")
    print(f"  window_min                = {win_min}")
    print(f"  default_let_go_ttl_min    = {default_ttl}")
    print()
    print(f"[raw vocab 'topic_repeat']")
    print(json.dumps(tr, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog='let_go_dump',
        description=(
            "Sir CLI: 思考脑 '放下' 元能力管理 (governor Phase 2 F4). "
            "Inspect / Sir 元否决 LLM let_go 决定."
        ),
    )
    sub = parser.add_subparsers(dest='cmd', required=True)

    sub.add_parser('list', help='列出 active let_go topics')

    p_add = sub.add_parser('add', help='手动加 let_go (sir_manual)')
    p_add.add_argument('thread_id', help='thread_id (full or short prefix)')
    p_add.add_argument('--ttl-min', dest='ttl_min', type=int, default=30,
                       help='TTL minutes (default 30)')
    p_add.add_argument('--reason', help='可选 reason (≤200 char)')

    p_ext = sub.add_parser('extend', help='extend existing let_go TTL')
    p_ext.add_argument('thread_id')
    p_ext.add_argument('--ttl-min', dest='ttl_min', type=int, default=30)
    p_ext.add_argument('--reason', help='可选 reason')

    p_rev = sub.add_parser('revoke', help='强解锁 let_go (Sir 元否决)')
    p_rev.add_argument('thread_id')

    p_clr = sub.add_parser('clear', help='清空所有 let_go (危险)')
    p_clr.add_argument('--yes', action='store_true', help='confirm')

    sub.add_parser('config', help='show topic_repeat vocab config + path')

    args = parser.parse_args()
    if args.cmd == 'list':
        return cmd_list(args)
    if args.cmd == 'add':
        return cmd_add(args)
    if args.cmd == 'extend':
        return cmd_extend(args)
    if args.cmd == 'revoke':
        return cmd_revoke(args)
    if args.cmd == 'clear':
        return cmd_clear(args)
    if args.cmd == 'config':
        return cmd_config(args)
    parser.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main())
