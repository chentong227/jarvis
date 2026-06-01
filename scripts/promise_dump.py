# -*- coding: utf-8 -*-
"""[P5-fix27-E / 2026-05-22] Promise CLI — Sir 命令行 mark fulfilled/cancel/list.

跟 scripts/concerns_dump.py 风格对齐 (准则 6.5: CLI 可改).

Usage:
    # 看 pending 全部
    python scripts/promise_dump.py --list pending
    # 看最近 20 (任何 state)
    python scripts/promise_dump.py --list recent --limit 20
    # 看 stats
    python scripts/promise_dump.py --stats
    # 按 id 完成
    python scripts/promise_dump.py --fulfill p_cdc96ad5 --reason "Sir 体检完了"
    # 按 keyword 完成 (模糊找 pending)
    python scripts/promise_dump.py --fulfill --keyword 体检 --reason "Sir 体检完了"
    # 按 keyword 撤销
    python scripts/promise_dump.py --cancel --keyword 面试 --reason "Sir 改主意了"
    # 看一条详情
    python scripts/promise_dump.py --show p_cdc96ad5
"""
import argparse
import json
import os
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time


def _setup_path():
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    if repo not in sys.path:
        sys.path.insert(0, repo)


_setup_path()


def _fmt_ts(ts: float) -> str:
    if not ts or ts <= 0:
        return '-'
    return time.strftime('%m-%d %H:%M', time.localtime(ts))


def _fmt_state(state: str) -> str:
    return {
        'pending': '⏳ pending',
        'fulfilled': '✅ fulfilled',
        'overdue': '⏰ overdue',
        'untracked': '❓ untracked',
        'cancelled': '🚫 cancelled',
    }.get(state, state)


def _find_by_keyword(log, keyword: str, state: str = 'pending'):
    """模糊匹配 — 查 description + jarvis_reply.

    Returns: list of (pid, promise) ordered by registered_at desc.
    """
    kw = (keyword or '').lower().strip()
    if not kw:
        return []
    hits = []
    for pid, p in log.promises.items():
        if state and p.state != state:
            continue
        blob = ((p.description or '') + ' ' + (p.jarvis_reply or '')).lower()
        if kw in blob:
            hits.append((pid, p))
    hits.sort(key=lambda x: -x[1].registered_at)
    return hits


def cmd_list(log, state: str, limit: int):
    """List promises by state ('pending'/'fulfilled'/'recent'/'all')."""
    rows = []
    if state == 'recent':
        rows = sorted(log.promises.values(),
                        key=lambda p: -p.registered_at)[:limit]
    elif state == 'all':
        rows = sorted(log.promises.values(), key=lambda p: -p.registered_at)
    else:
        rows = [p for p in log.promises.values() if p.state == state]
        rows.sort(key=lambda p: -p.registered_at)

    if not rows:
        print(f'(no promises with state={state!r})')
        return
    print(f'{"id":<14} {"state":<14} {"author":<8} {"reg":<14} {"desc":<60}')
    print('-' * 110)
    for p in rows[:limit]:
        desc = (p.description or '')[:58]
        print(f'{p.id:<14} {_fmt_state(p.state):<14} '
                f'{(p.author or "?"):<8} {_fmt_ts(p.registered_at):<14} '
                f'{desc}')
    if len(rows) > limit:
        print(f'... 还有 {len(rows) - limit} 条 (--limit N 看更多)')


def cmd_show(log, pid: str):
    p = log.promises.get(pid)
    if p is None:
        print(f'❌ promise_id={pid!r} 未找到')
        sys.exit(1)
    print(f'\n=== Promise {p.id} ===')
    print(f'  state       : {_fmt_state(p.state)}')
    print(f'  kind        : {p.kind}')
    print(f'  author      : {p.author}')
    print(f'  description : {p.description}')
    print(f'  deadline    : {p.deadline_str or "-"}')
    print(f'  lang        : {p.lang}')
    print(f'  registered  : {_fmt_ts(p.registered_at)} ({p.registered_at:.0f})')
    if p.fulfilled_at > 0:
        print(f'  fulfilled   : {_fmt_ts(p.fulfilled_at)}')
    print(f'  turn_id     : {p.turn_id or "-"}')
    if p.jarvis_reply:
        print(f'  jarvis_reply: {p.jarvis_reply[:200]}')
    if p.evidence:
        print(f'  evidence (n={len(p.evidence)}):')
        for ev in p.evidence[-5:]:
            ts = ev.get('when', 0)
            kind = ev.get('kind', '')
            what = (ev.get('what', '') or '')[:80]
            print(f'    [{_fmt_ts(ts)}] {kind}: {what}')


def cmd_fulfill(log, pid: str, keyword: str, reason: str):
    if not pid and keyword:
        hits = _find_by_keyword(log, keyword, state='pending')
        if not hits:
            print(f'❌ keyword={keyword!r} 没找到 pending promise')
            sys.exit(1)
        if len(hits) > 1:
            print(f'⚠️ keyword={keyword!r} 找到 {len(hits)} 条 pending, 列前 5 个:')
            cmd_list_helper(hits[:5])
            print(f'\n请用 --fulfill <id> 精确指定.')
            sys.exit(1)
        pid = hits[0][0]
        print(f'(keyword={keyword!r} 唯一匹配 pid={pid})')

    if not pid:
        print('❌ 缺 --fulfill <id> 或 --keyword <kw>')
        sys.exit(1)

    ok = log.mark_fulfilled(
        pid, evidence_kind='cli',
        evidence_what=(reason or 'CLI manual fulfill')[:200])
    if ok:
        print(f'\n✅ {pid} 标记 fulfilled. ProactiveCare 不再提醒.')
    else:
        print(f'❌ {pid} 未找到或非 pending (可能已 fulfilled/cancelled).')
        sys.exit(1)


def cmd_cancel(log, pid: str, keyword: str, reason: str):
    if not pid and keyword:
        hits = _find_by_keyword(log, keyword, state='pending')
        if not hits:
            print(f'❌ keyword={keyword!r} 没找到 pending promise')
            sys.exit(1)
        if len(hits) > 1:
            print(f'⚠️ keyword={keyword!r} 找到 {len(hits)} 条 pending, 列前 5 个:')
            cmd_list_helper(hits[:5])
            print(f'\n请用 --cancel <id> 精确指定.')
            sys.exit(1)
        pid = hits[0][0]
        print(f'(keyword={keyword!r} 唯一匹配 pid={pid})')

    if not pid:
        print('❌ 缺 --cancel <id> 或 --keyword <kw>')
        sys.exit(1)

    ok = log.mark_cancelled(pid, reason=(reason or 'CLI manual cancel')[:200])
    if ok:
        print(f'\n🚫 {pid} 已撤销. ProactiveCare 不再提醒.')
    else:
        print(f'❌ {pid} 未找到或非 pending.')
        sys.exit(1)


def cmd_list_helper(hits):
    """Print short list of (pid, promise) tuples."""
    for pid, p in hits:
        desc = (p.description or '')[:60]
        print(f'  {pid} author={p.author} reg={_fmt_ts(p.registered_at)} '
                f'desc={desc!r}')


def cmd_stats(log):
    s = log.stats()
    print(f'\n=== Promise Log Stats ===')
    print(f'  total : {s["total"]}')
    print(f'  states:')
    for k, v in s['states'].items():
        if v > 0:
            print(f'    {k:<12} {v}')
    print(f'  kinds :')
    for k, v in s['kinds'].items():
        if v > 0:
            print(f'    {k:<12} {v}')


def main():
    ap = argparse.ArgumentParser(
        description='[P5-fix27] Promise log CLI (Sir 手动 mark fulfilled/cancel)')
    ap.add_argument('--list', choices=['pending', 'fulfilled', 'overdue',
                                              'untracked', 'cancelled', 'recent',
                                              'all'],
                       help='list by state')
    ap.add_argument('--show', metavar='PID', help='show one promise detail')
    ap.add_argument('--fulfill', nargs='?', const='', metavar='PID',
                       help='mark fulfilled (by id, 或配 --keyword 模糊找)')
    ap.add_argument('--cancel', nargs='?', const='', metavar='PID',
                       help='mark cancelled (by id, 或配 --keyword 模糊找)')
    ap.add_argument('--keyword', '-k', metavar='KW', default='',
                       help='模糊关键词 (配合 --fulfill/--cancel)')
    ap.add_argument('--reason', '-r', metavar='TEXT', default='',
                       help='reason/evidence (写进 evidence log)')
    ap.add_argument('--limit', '-n', type=int, default=20,
                       help='list 最大行数 (default 20)')
    ap.add_argument('--stats', action='store_true', help='show stats')
    args = ap.parse_args()

    from jarvis_promise_log import get_default_log
    log = get_default_log()

    if args.stats:
        cmd_stats(log)
        return
    if args.show:
        cmd_show(log, args.show)
        return
    if args.fulfill is not None:
        cmd_fulfill(log, args.fulfill, args.keyword, args.reason)
        return
    if args.cancel is not None:
        cmd_cancel(log, args.cancel, args.keyword, args.reason)
        return
    if args.list:
        cmd_list(log, args.list, args.limit)
        return

    # 默认: stats + pending list
    cmd_stats(log)
    print()
    cmd_list(log, 'pending', args.limit)


if __name__ == '__main__':
    main()
