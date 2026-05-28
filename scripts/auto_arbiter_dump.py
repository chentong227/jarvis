#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auto_arbiter_dump — Sir 看贾维斯自决历史 + 手动 revert.

[AA / Sir 2026-05-25 22:58 自决]

用法:
  python scripts/auto_arbiter_dump.py                    # 默认 list 最近 24h
  python scripts/auto_arbiter_dump.py --hours 72         # 最近 3d
  python scripts/auto_arbiter_dump.py --kind inside_joke # 只看内梗
  python scripts/auto_arbiter_dump.py --reverted-only    # 只看 Sir 撤销的
  python scripts/auto_arbiter_dump.py --stats            # daemon 统计
  python scripts/auto_arbiter_dump.py --calibration      # 看当前 confidence 阈值
  python scripts/auto_arbiter_dump.py --revert <id> --reason "原因"  # 撤销一条
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
from typing import List


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PERSIST_PATH = os.path.join(ROOT, 'memory_pool', 'auto_arbiter_log.jsonl')
CAL_PATH = os.path.join(ROOT, 'memory_pool', 'auto_arbiter_calibration.json')


KIND_LABELS = {
    'inside_joke': ('🃏', '内梗'),
    'thread':      ('🧵', '历史线'),
    'concern':     ('🎯', '关怀'),
    'directive':   ('📜', '指令'),
}
DECISION_LABELS = {
    'activate':     ('✅', '通过'),
    'reject':       ('❌', '拒绝'),
    'defer_to_sir': ('🙋', '建议 Sir'),
    'noop':         ('➖', '不动'),
}


def load_decisions(hours: float = 24.0) -> List[dict]:
    if not os.path.exists(PERSIST_PATH):
        return []
    cutoff = time.time() - hours * 3600.0
    latest_by_id = {}
    with open(PERSIST_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if d.get('ts', 0) < cutoff:
                    continue
                latest_by_id[d.get('id')] = d
            except (json.JSONDecodeError, ValueError):
                continue
    return list(latest_by_id.values())


def fmt_age(ts: float) -> str:
    age_s = time.time() - ts
    if age_s < 60:
        return f"{int(age_s)}s ago"
    if age_s < 3600:
        return f"{int(age_s / 60)}min ago"
    if age_s < 86400:
        return f"{age_s / 3600:.1f}h ago"
    return f"{age_s / 86400:.1f}d ago"


def print_decision(d: dict) -> None:
    k_icon, k_label = KIND_LABELS.get(d.get('kind', '?'),
                                        ('?', d.get('kind', '?')))
    dec = d.get('decision', '?')
    dec_icon, dec_label = DECISION_LABELS.get(dec, ('?', dec))
    conf = d.get('confidence', 0.0)
    thr = d.get('threshold_at_decision', 0.0)
    reverted = d.get('sir_reverted')

    head = f"  {k_icon} [{k_label}] {dec_icon} {dec_label}"
    if reverted:
        head += " (↩ Sir 撤销)"
    head += f" | conf {conf:.2f}/thr {thr:.2f} | {fmt_age(d.get('ts', 0))}"
    print(head)
    if d.get('item_preview'):
        print(f"     \"{d['item_preview']}\"")
    if d.get('reason'):
        print(f"     🤖 {d['reason'][:150]}")
    if d.get('execution_msg'):
        print(f"     → {d['execution_msg']}")
    if reverted and d.get('sir_revert_reason'):
        print(f"     ↩ Sir: {d['sir_revert_reason']}")
    print(f"     id={d.get('id', '?')}")
    print()


def show_stats() -> None:
    all_d = load_decisions(hours=24 * 7)
    if not all_d:
        print("(还没决策 — 重启 Jarvis 后等 60s 第一波 tick)")
        return
    h24 = [d for d in all_d if d.get('ts', 0) > time.time() - 86400]
    by_kind = {}
    for d in h24:
        k = d.get('kind', '?')
        if k not in by_kind:
            by_kind[k] = {'total': 0, 'activate': 0, 'reject': 0,
                           'defer_to_sir': 0, 'noop': 0, 'reverted': 0}
        by_kind[k]['total'] += 1
        by_kind[k][d.get('decision', '?')] = \
            by_kind[k].get(d.get('decision', '?'), 0) + 1
        if d.get('sir_reverted'):
            by_kind[k]['reverted'] += 1

    real_dec = sum(1 for d in h24 if d.get('decision') in ('activate', 'reject'))
    reverted = sum(1 for d in h24 if d.get('sir_reverted'))
    revert_rate = reverted / max(1, real_dec)

    print("=" * 60)
    print("🤖 AutoArbiter 统计")
    print("=" * 60)
    print(f"  total persisted (7d):    {len(all_d)}")
    print(f"  last 24h decisions:       {len(h24)}")
    print(f"  真拍板 (通过+拒):         {real_dec}")
    print(f"  Sir 撤销:                 {reverted} ({revert_rate:.0%})")
    print()
    print("  per-kind 分布 (last 24h):")
    for k, st in sorted(by_kind.items()):
        k_icon, k_label = KIND_LABELS.get(k, ('?', k))
        rr = st['reverted'] / max(1, st['activate'] + st['reject'])
        print(f"    {k_icon} {k_label:6s}  total={st['total']:3d}  "
              f"✅ {st['activate']:2d}  ❌ {st['reject']:2d}  "
              f"🙋 {st['defer_to_sir']:2d}  ➖ {st['noop']:2d}  "
              f"↩ {st['reverted']:2d} ({rr:.0%})")
    print()


def show_calibration() -> None:
    if not os.path.exists(CAL_PATH):
        print("(没 calibration 文件 — daemon 没跑过 daily reflection 03:xx)")
        return
    with open(CAL_PATH, 'r', encoding='utf-8') as f:
        cal = json.load(f)
    print("=" * 60)
    print("📊 当前 Confidence 阈值 (per-category)")
    print("=" * 60)
    thr = cal.get('thresholds', {})
    for k in sorted(thr.keys()):
        k_icon, k_label = KIND_LABELS.get(k, ('?', k))
        print(f"  {k_icon} {k_label:6s}  {thr[k]:.2f}")
    print()
    hist = cal.get('revert_history_24h', {})
    if hist:
        print("  Last 24h revert history (used for calibration):")
        for k, h in hist.items():
            k_icon, k_label = KIND_LABELS.get(k, ('?', k))
            rate = h.get('reverted', 0) / max(1, h.get('total', 1))
            print(f"    {k_icon} {k_label:6s}  "
                  f"total={h.get('total', 0):3d}  reverted={h.get('reverted', 0):2d}  "
                  f"({rate:.0%})")
    last_cal = cal.get('last_calibrated_iso', '')
    if last_cal:
        print(f"\n  last_calibrated: {last_cal}")
    else:
        print(f"\n  (还没 daily reflection 跑过, 03:xx fire)")
    print()


def do_revert(decision_id: str, reason: str) -> int:
    """直接调 daemon API (需主进程跑 + dashboard 装入)."""
    try:
        from jarvis_auto_arbiter import get_default_daemon
    except Exception as e:
        print(f"[ERROR] 不能 import: {e}")
        return 1
    daemon = get_default_daemon()
    if daemon is None:
        print("[ERROR] daemon 未启动 (主进程没跑 / 或 init fail)")
        print("       Sir 改用 dashboard 撤销 (http://127.0.0.1:8765/auto_arbiter)")
        return 1
    ok, msg = daemon.sir_revert(decision_id, reason)
    print(f"[{'OK' if ok else 'FAIL'}] {msg}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--hours', type=float, default=24.0,
                      help='只看最近 N 小时 (default 24)')
    ap.add_argument('--limit', type=int, default=50,
                      help='最多 N 条 (default 50)')
    ap.add_argument('--kind', type=str, default=None,
                      help='只看某 kind (inside_joke/thread/concern/directive)')
    ap.add_argument('--decision', type=str, default=None,
                      help='只看某 decision (activate/reject/defer_to_sir/noop)')
    ap.add_argument('--reverted-only', action='store_true',
                      help='只看 Sir 撤销的')
    ap.add_argument('--stats', action='store_true', help='显示统计')
    ap.add_argument('--calibration', action='store_true',
                      help='显示当前 confidence 阈值')
    ap.add_argument('--revert', type=str, default=None,
                      metavar='ID', help='撤销某条 decision (需 --reason)')
    ap.add_argument('--reason', type=str, default='',
                      help='撤销原因 (帮 daemon 下次更准)')
    args = ap.parse_args()

    if args.revert:
        if not args.reason:
            print("[ERROR] --revert 需要 --reason '原因'")
            return 1
        return do_revert(args.revert, args.reason)

    if args.calibration:
        show_calibration()
        return 0
    if args.stats:
        show_stats()
        return 0

    decisions = load_decisions(hours=args.hours)
    if not decisions:
        print(f"(最近 {args.hours}h 没决策 — check {PERSIST_PATH})")
        return 0

    # filter
    if args.kind:
        decisions = [d for d in decisions if d.get('kind') == args.kind]
    if args.decision:
        decisions = [d for d in decisions
                       if d.get('decision') == args.decision]
    if args.reverted_only:
        decisions = [d for d in decisions if d.get('sir_reverted')]

    decisions.sort(key=lambda d: -d.get('ts', 0))
    decisions = decisions[:args.limit]

    print(f"🤖 AutoArbiter Decisions (last {args.hours}h, {len(decisions)} shown)")
    print("=" * 60)
    print()
    for d in decisions:
        print_decision(d)
    return 0


if __name__ == '__main__':
    sys.exit(main())
