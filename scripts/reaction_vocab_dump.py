# -*- coding: utf-8 -*-
"""[Sir 2026-05-29 Option A] Reaction Vocab CLI (准则 6 持久化 + CLI 可改).

reaction 分类 vocab — 驱动 V6 元学习闭环 (classify_fast) + #1 behavioral_reject
LLM 预筛闸. Sir add/remove 词, daemon 自动 reload (mtime check, 30s throttle).

用法:
  python scripts/reaction_vocab_dump.py list
  python scripts/reaction_vocab_dump.py show
  python scripts/reaction_vocab_dump.py add "不太行"
  python scripts/reaction_vocab_dump.py add "你错了" --kind strong_correction
  python scripts/reaction_vocab_dump.py remove "醒醒"
  python scripts/reaction_vocab_dump.py history          # 最近 30 ops
  python scripts/reaction_vocab_dump.py review           # L7 propose 等 Sir 拍板

📌 L7 reflector (reaction vocab 自动 propose) TODO. 本期 Sir 手动 add/remove.
"""
from __future__ import annotations

import argparse
import os
import sys
# force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(
    _cu_os.path.dirname(_cu_os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
try:
    import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_reaction_classifier import (  # noqa: E402
    DEFAULT_VOCAB_PATH,
    _VALID_KINDS,
    add_term,
    list_all,
    remove_term,
)


def _print_section(title: str, items, max_show: int = 40) -> None:
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
    print(f"📋 Reaction Vocab @ {args.path}")
    print(f"   schema_version: {meta.get('schema_version', '?')}")
    print(f"   purpose: {meta.get('purpose', '?')[:100]}")
    print(f"   ignored_after_min: {data.get('ignored_after_min', '?')}")
    for kind in _VALID_KINDS:
        _print_section(kind, data.get(kind) or [])
    hist = data.get('history') or []
    rev = data.get('review_queue') or []
    print(f"\n[History] {len(hist)} ops (use 'history' cmd to see latest 30)")
    print(f"[Review Queue] {len(rev)} pending L7 proposals")


def cmd_show(args):
    cmd_list(args)


def cmd_add(args):
    ok = add_term(args.term, kind=args.kind, path=args.path, source='sir_cli')
    if ok:
        print(f"✅ added [{args.kind}] '{args.term}'")
    else:
        data = list_all(args.path)
        lst = data.get(args.kind) or []
        if args.term in lst:
            print(f"⚠️  '{args.term}' already in [{args.kind}], no-op")
        else:
            print("❌ add failed (invalid term/kind or IO error)")
            sys.exit(1)


def cmd_remove(args):
    ok = remove_term(args.term, kind=args.kind, path=args.path,
                     source='sir_cli')
    if ok:
        print(f"✅ removed [{args.kind}] '{args.term}'")
    else:
        data = list_all(args.path)
        lst = data.get(args.kind) or []
        if args.term not in lst:
            print(f"⚠️  '{args.term}' not in [{args.kind}], no-op")
        else:
            print("❌ remove failed (IO error)")
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
              f"[{e.get('kind', '?'):20}] '{e.get('term', '?')}' "
              f"({e.get('source', '?')})")


def cmd_review(args):
    data = list_all(args.path)
    rev = data.get('review_queue') or []
    if not rev:
        print("(no L7 proposals waiting — reflector not yet implemented)")
        return
    print(f"📋 L7 Proposals ({len(rev)} pending):")
    for i, p in enumerate(rev, 1):
        print(f"\n   [{i}] proposed {p.get('when', '?')}")
        print(f"       kind: {p.get('kind')}")
        print(f"       term: {p.get('term')}")
        print(f"       rationale: {p.get('rationale', '')[:200]}")


def main():
    parser = argparse.ArgumentParser(
        description='Reaction Vocab CLI (Sir 2026-05-29 Option A / #2)')
    parser.add_argument('--path', default=DEFAULT_VOCAB_PATH)
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_list = sub.add_parser('list', help='列出全 vocab')
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser('show', help='同 list')
    p_show.set_defaults(func=cmd_show)

    p_add = sub.add_parser('add', help='加词 (--kind negative_candidates/strong_correction/soft)')
    p_add.add_argument('term')
    p_add.add_argument('--kind', default='negative_candidates',
                       choices=list(_VALID_KINDS))
    p_add.set_defaults(func=cmd_add)

    p_rm = sub.add_parser('remove', help='删词')
    p_rm.add_argument('term')
    p_rm.add_argument('--kind', default='negative_candidates',
                      choices=list(_VALID_KINDS))
    p_rm.set_defaults(func=cmd_remove)

    p_hist = sub.add_parser('history', help='历史 ops (最近 30)')
    p_hist.set_defaults(func=cmd_history)

    p_rev = sub.add_parser('review', help='L7 propose 待 Sir 拍板 (TODO)')
    p_rev.set_defaults(func=cmd_review)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
