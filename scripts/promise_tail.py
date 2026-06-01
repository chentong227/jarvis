# -*- coding: utf-8 -*-
"""
promise_tail.py — Jarvis 承诺账本查询工具

Sir 22:25: "贾维斯说话能不能和行为一致这个事情让我很困扰. 任何一个他表态
的事情都要有对应的日志."

显示最近 N 条 Jarvis 自承诺及其执行状态:
- pending: 已说但还在等行为兑现
- fulfilled: 已被某 tool / nudge / state 变更兑现 (有 evidence)
- overdue: 有 deadline 但过期未兑现
- untracked: 24h 无 evidence (我说了但无法验证)
- cancelled: 被显式取消

用法:
  python scripts/promise_tail.py              # 最近 20 条
  python scripts/promise_tail.py -n 50        # 最近 50 条
  python scripts/promise_tail.py --pending    # 只看 pending
  python scripts/promise_tail.py --stats      # 只显示统计
  python scripts/promise_tail.py --sweep      # 跑一次 sweep_untracked
"""

import argparse
import io
import os
import sys
import time

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from jarvis_promise_log import get_default_log, STATE_PENDING  # noqa: E402


STATE_ICON = {
    'pending': '⏳',
    'fulfilled': '✅',
    'overdue': '⏰',
    'untracked': '❓',
    'cancelled': '🚫',
}


def fmt_age(ts: float) -> str:
    if ts <= 0:
        return '?'
    delta = time.time() - ts
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta/60)}m ago"
    if delta < 86400:
        return f"{int(delta/3600)}h ago"
    return f"{int(delta/86400)}d ago"


def render_one(p) -> str:
    icon = STATE_ICON.get(p.state, '·')
    age = fmt_age(p.registered_at)
    kind_tag = f"[{p.kind}]"
    deadline = f" by {p.deadline_str}" if p.deadline_str else ""
    ev_count = len(p.evidence)
    ev_tag = f" [{ev_count} evidence]" if ev_count > 0 else ""
    return (
        f"{icon} {p.id} {kind_tag} {age}\n"
        f"   '{p.description[:90]}'{deadline}{ev_tag}\n"
        f"   from reply: '{p.jarvis_reply[:90]}'"
    )


def render_evidence(p) -> str:
    if not p.evidence:
        return "  (no evidence yet)"
    lines = []
    for ev in p.evidence:
        ts_str = ev.get('when_iso', '?')[-8:]
        lines.append(f"  [{ts_str}] {ev.get('kind', '?')}: {ev.get('what', '')[:100]}")
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-n', '--limit', type=int, default=20)
    ap.add_argument('--pending', action='store_true', help='只看 pending')
    ap.add_argument('--stats', action='store_true', help='只显示统计')
    ap.add_argument('--sweep', action='store_true', help='跑 sweep_untracked')
    ap.add_argument('--detail', action='store_true', help='展开 evidence 详情')
    args = ap.parse_args()

    log = get_default_log()

    if args.sweep:
        n = log.sweep_untracked()
        print(f"sweep_untracked: {n} promises moved to UNTRACKED")
        return

    stats = log.stats()
    print("=" * 64)
    print(f"Jarvis 承诺账本 — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 64)
    print(f"总数: {stats['total']}")
    print("状态分布:")
    for st, n in stats['states'].items():
        if n > 0:
            print(f"  {STATE_ICON.get(st, '·')} {st:12s}  {n}")
    print(f"类型: hard={stats['kinds'].get('hard', 0)}  soft={stats['kinds'].get('soft', 0)}")
    print()

    if args.stats:
        return

    if args.pending:
        items = log.list_pending()
        items.sort(key=lambda p: -p.registered_at)
        items = items[:args.limit]
        print(f"-- Pending ({len(items)}) --")
    else:
        items = log.list_recent(limit=args.limit)
        print(f"-- 最近 {len(items)} 条 --")

    if not items:
        print("(none)")
        return

    for p in items:
        print(render_one(p))
        if args.detail:
            print(render_evidence(p))
        print()


if __name__ == '__main__':
    main()
