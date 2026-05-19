# -*- coding: utf-8 -*-
"""[P0+20-β.5.23-A / 2026-05-19] ProactiveCare Cooldown Vocab CLI.

Sir 准则 6 + Sir 01:36 'B 不交手动' — 这个 CLI 主要给 Sir 查阅, 不是
让 Sir 手调阈值. 真值由 ConcernFeedbackReflector L7 LLM-propose 自动改.
Sir 想看就 list, 想强 override 才 set.

用法:
  python scripts/cooldown_vocab_dump.py list
  python scripts/cooldown_vocab_dump.py show GLOBAL_NUDGE_COOLDOWN_S
  python scripts/cooldown_vocab_dump.py set GLOBAL_NUDGE_COOLDOWN_S 450
  python scripts/cooldown_vocab_dump.py history
  python scripts/cooldown_vocab_dump.py review        # L7 propose 等 Sir 拍板
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(ROOT, 'memory_pool', 'proactive_care_cooldown_vocab.json')


def _load(path: str) -> dict:
    if not os.path.exists(path):
        print(f"⚠️  {path} not found")
        sys.exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(path: str, data: dict) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cmd_list(args, data):
    cur = data.get('current') or {}
    print(f"📋 ProactiveCare Cooldown Vocab @ {args.path}")
    print(f"   schema_version: {data.get('schema_version', '?')}")
    print(f"   markers: {data.get('markers', [])}")
    print()
    print("[Current 阈值]")
    for k, v in sorted(cur.items()):
        print(f"   {k:38} = {v}")
    print()
    h = data.get('history') or []
    print(f"[History] {len(h)} entries")
    r = data.get('review_queue') or []
    print(f"[Review Queue] {len(r)} pending L7 proposals")


def cmd_show(args, data):
    cur = data.get('current') or {}
    if args.key not in cur:
        print(f"❌ key '{args.key}' not in vocab")
        print(f"   Valid keys: {sorted(cur.keys())}")
        sys.exit(1)
    print(f"   {args.key} = {cur[args.key]}")
    ranges = (data.get('ranges') or {}).get(args.key)
    if ranges:
        print(f"   range: min={ranges.get('min')}, max={ranges.get('max')}, "
              f"step={ranges.get('step')}")


def cmd_set(args, data):
    """手动 override (Sir 紧急用)."""
    cur = data.get('current') or {}
    if args.key not in cur:
        print(f"❌ key '{args.key}' not in vocab")
        sys.exit(1)
    old_val = cur[args.key]
    try:
        new_val = float(args.value)
    except ValueError:
        print(f"❌ value must be float, got '{args.value}'")
        sys.exit(1)
    # range check
    ranges = (data.get('ranges') or {}).get(args.key) or {}
    mn = ranges.get('min')
    mx = ranges.get('max')
    if mn is not None and new_val < mn:
        print(f"⚠️  {new_val} < min {mn} for {args.key}, clamping")
        new_val = mn
    if mx is not None and new_val > mx:
        print(f"⚠️  {new_val} > max {mx} for {args.key}, clamping")
        new_val = mx
    cur[args.key] = new_val
    # 写 history
    hist = data.get('history') or []
    hist.append({
        'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'key': args.key,
        'old': old_val,
        'new': new_val,
        'source': 'sir_cli',
    })
    data['current'] = cur
    data['history'] = hist
    _save(args.path, data)
    print(f"✅ {args.key}: {old_val} → {new_val}")


def cmd_history(args, data):
    h = data.get('history') or []
    if not h:
        print("(no history entries)")
        return
    print(f"📋 History ({len(h)} entries):")
    for e in h[-30:]:
        print(f"   [{e.get('when', '?')}] {e.get('source', '?'):10} "
              f"{e.get('key', '?'):38} {e.get('old')} → {e.get('new')}")


def cmd_review(args, data):
    """L7 propose 等 Sir 拍板."""
    r = data.get('review_queue') or []
    if not r:
        print("(no L7 proposals waiting)")
        return
    print(f"📋 L7 Proposals ({len(r)} pending):")
    for i, p in enumerate(r, 1):
        print(f"\n   [{i}] proposed {p.get('when', '?')}")
        print(f"       key: {p.get('key')}")
        print(f"       current: {p.get('current')}")
        print(f"       proposed: {p.get('proposed')}")
        print(f"       rationale: {p.get('rationale', '')[:200]}")


def main():
    parser = argparse.ArgumentParser(
        description='ProactiveCare Cooldown Vocab CLI (β.5.23-A)')
    parser.add_argument('--path', default=DEFAULT_PATH)
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_list = sub.add_parser('list', help='列出所有 cooldown 阈值')
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser('show', help='看某 key')
    p_show.add_argument('key')
    p_show.set_defaults(func=cmd_show)

    p_set = sub.add_parser('set', help='手动 override (紧急用)')
    p_set.add_argument('key')
    p_set.add_argument('value')
    p_set.set_defaults(func=cmd_set)

    p_hist = sub.add_parser('history', help='history (最近 30)')
    p_hist.set_defaults(func=cmd_history)

    p_rev = sub.add_parser('review', help='L7 propose 等 Sir 拍板')
    p_rev.set_defaults(func=cmd_review)

    args = parser.parse_args()
    data = _load(args.path)
    args.func(args, data)


if __name__ == '__main__':
    main()
