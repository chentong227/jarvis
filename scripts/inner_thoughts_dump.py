#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inner_thoughts_dump — Sir 看 Jarvis 内心独白历史.

[P1 / Sir 2026-05-25 22:10 数字生命基础]

用法:
  python scripts/inner_thoughts_dump.py                # 默认 list 最近 24h
  python scripts/inner_thoughts_dump.py --hours 6      # 最近 6h
  python scripts/inner_thoughts_dump.py --limit 50     # 限制条数
  python scripts/inner_thoughts_dump.py --category C   # 只看 C 类 (concern-evo)
  python scripts/inner_thoughts_dump.py --min-salience 0.5  # 只看 >= 0.5
  python scripts/inner_thoughts_dump.py --soul-block   # 显示当前会注入主脑的 SOUL block
  python scripts/inner_thoughts_dump.py --stats        # daemon 统计

5 类思考池:
  [A] OBSERVATION  — Sir 当前外部状态
  [B] SELF-REFLECT — 看自己最近 reply
  [C] CONCERN-EVO  — 自评 severity 该升/降
  [D] PROACTIVE    — 下次该 silently 做什么
  [E] RELATIONSHIP — inside joke 候选
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import List


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PERSIST_PATH = os.path.join(ROOT, 'memory_pool', 'inner_thoughts.jsonl')


CATEGORY_LABELS = {
    'A': 'OBSERVATION',
    'B': 'SELF-REFLECT',
    'C': 'CONCERN-EVO',
    'D': 'PROACTIVE',
    'E': 'RELATIONSHIP',
}

CATEGORY_ICONS = {
    'A': '👁️',
    'B': '🪞',
    'C': '🎯',
    'D': '🌱',
    'E': '💝',
}


def load_thoughts(hours: float = 24.0) -> List[dict]:
    if not os.path.exists(PERSIST_PATH):
        return []
    cutoff = time.time() - hours * 3600.0
    out = []
    with open(PERSIST_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if d.get('ts', 0) < cutoff:
                    continue
                out.append(d)
            except (json.JSONDecodeError, ValueError):
                continue
    return out


def fmt_age(ts: float) -> str:
    age_s = time.time() - ts
    if age_s < 60:
        return f"{int(age_s)}s ago"
    if age_s < 3600:
        return f"{int(age_s / 60)}min ago"
    if age_s < 86400:
        return f"{age_s / 3600:.1f}h ago"
    return f"{age_s / 86400:.1f}d ago"


def print_thought(t: dict) -> None:
    cat = t.get('category', '?')
    icon = CATEGORY_ICONS.get(cat, '💭')
    label = CATEGORY_LABELS.get(cat, '?')
    sal = t.get('salience', 0.0)
    sir_state = t.get('sir_state', '?')
    tick = t.get('tick_interval_s', 0)
    age = fmt_age(t.get('ts', 0))
    iso = t.get('ts_iso', '?')

    sal_bar = '★' * int(sal * 5) + '☆' * (5 - int(sal * 5))
    print(f"  {icon} [{cat}/{label}] sal={sal:.2f} {sal_bar} | "
          f"{age} ({iso}) | sir={sir_state} tick={tick}s")
    thought = t.get('thought', '')
    print(f"     \"{thought}\"")
    action = t.get('actionable', 'none')
    if action and action.lower() != 'none':
        done = '✓' if t.get('actionable_done') else '○'
        result = t.get('actionable_result', 'pending')
        print(f"     {done} actionable: {action} → {result}")
    print()


def show_stats() -> None:
    """显示 daemon 统计 (从 persist 算)."""
    all_thoughts = load_thoughts(hours=24 * 7)  # 7d
    if not all_thoughts:
        print("(no thoughts yet — Sir 重启 Jarvis 让 InnerThoughtDaemon 跑起来)")
        return

    last_24h = [t for t in all_thoughts if t.get('ts', 0) > time.time() - 86400]
    cat_count_24h = {}
    for t in last_24h:
        c = t.get('category', '?')
        cat_count_24h[c] = cat_count_24h.get(c, 0) + 1

    action_done_24h = sum(1 for t in last_24h
                            if t.get('actionable_done')
                            and t.get('actionable', 'none').lower() != 'none')
    action_total_24h = sum(1 for t in last_24h
                             if t.get('actionable', 'none').lower() != 'none')

    avg_sal_24h = (
        sum(t.get('salience', 0) for t in last_24h) / max(1, len(last_24h))
    )

    print("=" * 60)
    print("💭 InnerThoughtDaemon Stats")
    print("=" * 60)
    print(f"  total persisted (7d):    {len(all_thoughts)}")
    print(f"  thoughts last 24h:       {len(last_24h)}")
    print(f"  avg salience 24h:        {avg_sal_24h:.2f}")
    print(f"  actionable 24h:          {action_done_24h}/{action_total_24h}")
    print()
    print("  category breakdown (last 24h):")
    for cat in 'ABCDE':
        n = cat_count_24h.get(cat, 0)
        icon = CATEGORY_ICONS.get(cat, '?')
        label = CATEGORY_LABELS.get(cat, '?')
        bar = '█' * min(n, 30)
        print(f"    {icon} {cat} {label:<14} {n:>3}  {bar}")
    print()


def show_soul_block() -> None:
    """模拟主脑下次 turn 会看到的 SOUL inject block."""
    recent = load_thoughts(hours=24.0)
    if not recent:
        print("(no recent thoughts to inject)")
        return
    recent.sort(key=lambda t: -t.get('salience', 0.0))
    top = recent[:3]
    top.sort(key=lambda t: t.get('ts', 0))

    print("=" * 60)
    print("🪞 SOUL inject block (主脑下次 turn 会看到)")
    print("=" * 60)
    print()
    print("=== MY RECENT INNER THOUGHTS (last 24h, top by salience) ===")
    now = time.time()
    for t in top:
        age_min = max(1, int((now - t.get('ts', 0)) / 60))
        cat = t.get('category', '?')
        sal = t.get('salience', 0.0)
        thought = (t.get('thought', '') or '')[:140]
        action = t.get('actionable', 'none')
        action_str = ''
        if action and action.lower() != 'none':
            if t.get('actionable_done'):
                action_str = f" ✓ {t.get('actionable_result', '')[:30]}"
            else:
                action_str = " → pending"
        print(f"  [{cat}/{age_min}min ago/sal {sal:.2f}] "
              f"{thought}{action_str}")
    print()
    block_size = len('\n'.join([
        '=== MY RECENT INNER THOUGHTS (last 24h, top by salience) ==='
    ] + [f"  [{t.get('category')}/...] {t.get('thought', '')}" for t in top]))
    print(f"(estimated SOUL block size ~{block_size}c, cap 500c)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--hours', type=float, default=24.0,
                      help='只看最近 N 小时 (default 24)')
    ap.add_argument('--limit', type=int, default=50,
                      help='最多显示 N 条 (default 50)')
    ap.add_argument('--category', '-c', type=str, default=None,
                      help='只看某类 (A/B/C/D/E)')
    ap.add_argument('--min-salience', type=float, default=0.0,
                      help='只看 salience >= X')
    ap.add_argument('--actionable-only', action='store_true',
                      help='只看 actionable != none')
    ap.add_argument('--soul-block', action='store_true',
                      help='显示当前会注入主脑的 SOUL block')
    ap.add_argument('--stats', action='store_true',
                      help='显示统计')
    ap.add_argument('--newest-first', action='store_true',
                      help='最新在前 (default 旧→新)')
    args = ap.parse_args()

    if args.stats:
        show_stats()
        return
    if args.soul_block:
        show_soul_block()
        return

    thoughts = load_thoughts(hours=args.hours)
    if not thoughts:
        print(f"(no thoughts in last {args.hours}h — "
              f"check {PERSIST_PATH})")
        return

    # filter
    if args.category:
        cat_up = args.category.upper()
        thoughts = [t for t in thoughts if t.get('category') == cat_up]
    if args.min_salience > 0:
        thoughts = [t for t in thoughts
                     if t.get('salience', 0) >= args.min_salience]
    if args.actionable_only:
        thoughts = [t for t in thoughts
                     if (t.get('actionable') or 'none').lower() != 'none']

    # sort
    if args.newest_first:
        thoughts.sort(key=lambda t: -t.get('ts', 0))
    else:
        thoughts.sort(key=lambda t: t.get('ts', 0))

    # limit
    if len(thoughts) > args.limit:
        thoughts = thoughts[-args.limit:] if not args.newest_first else thoughts[:args.limit]

    print(f"💭 Jarvis Inner Thoughts (last {args.hours}h, "
          f"{len(thoughts)} shown)")
    print("=" * 60)
    print()
    for t in thoughts:
        print_thought(t)


if __name__ == '__main__':
    main()
