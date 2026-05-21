#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[P5-fixCB-revise / 2026-05-21 11:45] Claim Revision Log CLI

Sir 准则 6 vocab persistence + CLI manage. Sir 用此工具:
  - list pending revisions (你之前 over-claim 现在等机会 surface 的)
  - mark revision as surfaced (主脑已主动 admit, 不再 pending)
  - reject revision (Sir 觉得这条不需要 admit, 是 false positive)
  - archive stale (老 pending 没 surface 自动归档)
  - stats (总 / pending / surfaced / archived)

用法:
  python scripts/claim_revision_dump.py --list
  python scripts/claim_revision_dump.py --list --include-archived
  python scripts/claim_revision_dump.py --pending          # 只看 pending
  python scripts/claim_revision_dump.py --stats
  python scripts/claim_revision_dump.py --surface <id>      # 标 X 已 surface
  python scripts/claim_revision_dump.py --reject <id>       # Sir 拒此 revision
  python scripts/claim_revision_dump.py --archive-stale --days 7
"""
from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from jarvis_claim_revision_log import (  # noqa: E402
    get_default_store,
    get_stats,
    STATUS_PENDING,
    STATUS_SURFACED,
    STATUS_ARCHIVED,
    STATUS_REJECTED,
)


def _human_age(captured_at: float) -> str:
    if not captured_at:
        return '?'
    delta = time.time() - captured_at
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


def _print_revision(rev) -> None:
    age = _human_age(rev.captured_at)
    status_icon = {
        STATUS_PENDING: '⏳',
        STATUS_SURFACED: '✅',
        STATUS_ARCHIVED: '📦',
        STATUS_REJECTED: '❌',
    }.get(rev.status, '❓')
    print(f"{status_icon} [{rev.id[:8]}] {rev.status:9s} captured {age}")
    print(f"  capability_keyword : {rev.capability_keyword}")
    if rev.original_claim_excerpt:
        print(f"  original_claim     : \"{rev.original_claim_excerpt[:120]}\"")
    if rev.admitted_lacking_reason:
        print(f"  admitted_reason    : {rev.admitted_lacking_reason[:120]}")
    if rev.related_keywords:
        print(f"  related_keywords   : {rev.related_keywords}")
    print(f"  source             : {rev.source}, captured_turn = {rev.captured_turn_id[:16]}")
    if rev.status == STATUS_SURFACED and rev.surfaced_turn_id:
        print(f"  surfaced_at        : {time.strftime('%H:%M:%S', time.localtime(rev.surfaced_at or 0))}, turn = {rev.surfaced_turn_id[:16]}")
    print('')


def cmd_list(args) -> None:
    store = get_default_store()
    items = store.all_items(include_archived=bool(args.include_archived))
    if args.pending:
        items = [r for r in items if r.status == STATUS_PENDING]
    if not items:
        print('(no claim revisions)')
        return
    print(f'\n=== ClaimRevisionLog ({len(items)} entries) ===\n')
    for rev in items:
        _print_revision(rev)


def cmd_stats(args) -> None:
    s = get_stats()
    if not s:
        print('(stats unavailable)')
        return
    print(f"\n=== ClaimRevisionLog Stats ===")
    print(f"  total           : {s.get('total', 0)}")
    print(f"  pending         : {s.get('pending', 0)}")
    print(f"  surfaced        : {s.get('surfaced', 0)}")
    print(f"  archived        : {s.get('archived', 0)}")
    print(f"  rejected by Sir : {s.get('rejected_by_sir', 0)}")
    if s.get('oldest_pending_iso'):
        print(f"  oldest pending  : {s['oldest_pending_iso']}")
    print('')


def cmd_surface(args) -> None:
    store = get_default_store()
    ok = store.mark_surfaced(args.surface, turn_id='cli_manual')
    if ok:
        print(f"✅ revision {args.surface[:8]} marked as SURFACED")
    else:
        print(f"❌ revision {args.surface} not found")


def cmd_reject(args) -> None:
    store = get_default_store()
    ok = store.reject(args.reject)
    if ok:
        print(f"❌ revision {args.reject[:8]} marked as REJECTED (Sir 拒绝, 不再算 pending)")
    else:
        print(f"❌ revision {args.reject} not found")


def cmd_archive_stale(args) -> None:
    store = get_default_store()
    n = store.archive_stale(days=float(args.days or 7.0))
    print(f"📦 archived {n} stale revision(s) (older than {args.days or 7.0} days)")


def main() -> int:
    parser = argparse.ArgumentParser(description='Jarvis Claim Revision Log CLI')
    parser.add_argument('--list', action='store_true', help='List all revisions')
    parser.add_argument('--pending', action='store_true', help='List only pending')
    parser.add_argument('--include-archived', action='store_true', help='Include archived')
    parser.add_argument('--stats', action='store_true', help='Show stats')
    parser.add_argument('--surface', type=str, default='', metavar='REVISION_ID',
                        help='Mark revision as surfaced')
    parser.add_argument('--reject', type=str, default='', metavar='REVISION_ID',
                        help='Sir reject revision (not pending anymore)')
    parser.add_argument('--archive-stale', action='store_true',
                        help='Archive stale pending')
    parser.add_argument('--days', type=float, default=7.0,
                        help='Archive cutoff days (default 7)')
    args = parser.parse_args()

    if args.list or args.pending:
        cmd_list(args)
    elif args.stats:
        cmd_stats(args)
    elif args.surface:
        cmd_surface(args)
    elif args.reject:
        cmd_reject(args)
    elif args.archive_stale:
        cmd_archive_stale(args)
    else:
        parser.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
