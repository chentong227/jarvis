# -*- coding: utf-8 -*-
"""[Sir 真测 BUG-3 / 2026-05-24 16:15] CommitmentRetireOverdue CLI

Sir 痛点: "过期的 commit 就不要存在 commit 了, 存在长期的记忆那边, 记住贾维斯
在什么时候提醒过我什么, 我是什么时候让贾维斯做过什么这种, 我需要和他的记忆,
不需要他一直拿过期的 commit 骚扰我".

治法 (准则 6 数据强耦合):
  - SQLite Commitments mark is_deleted=1 → CommitmentWatcher 不再 fire nudge
  - PromiseLog mark state=fulfilled (kind=commitment) → 历史 evidence 保留
  - 不调 hippocampus.seal_memory 写 TaskMemory (避免 24 次 embed quota 浪费,
    PromiseLog 已经是 source of truth, 主脑读 PromiseLog 看历史)

usage:
  python scripts/commitment_retire_overdue.py --hours 24      # retire deadline 24h+ 前
  python scripts/commitment_retire_overdue.py --dry-run       # 预览不写
  python scripts/commitment_retire_overdue.py --all-overdue   # retire 所有 deadline 已过
"""
from __future__ import annotations
import os
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import json
import time
import sqlite3
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=int, default=24,
                      help='retire deadline 多少小时前的 (default 24)')
    ap.add_argument('--all-overdue', action='store_true',
                      help='retire 所有 deadline 已过 (不限小时数, 等价 --hours 0)')
    ap.add_argument('--dry-run', action='store_true',
                      help='只 preview, 不写')
    args = ap.parse_args()

    if args.all_overdue:
        cutoff_seconds = 0
    else:
        cutoff_seconds = args.hours * 3600

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sqlite_path = os.path.join(here, 'memory_pool', 'jarvis_memory.db')
    promise_log_path = os.path.join(here, 'memory_pool', 'jarvis_promise_log.json')

    if not os.path.exists(sqlite_path):
        print(f'❌ SQLite 不存在: {sqlite_path}', file=sys.stderr)
        return 1
    if not os.path.exists(promise_log_path):
        print(f'❌ PromiseLog 不存在: {promise_log_path}', file=sys.stderr)
        return 1

    now = time.time()
    cutoff_ts = now - cutoff_seconds

    # 1) 查 SQLite overdue active commitments
    conn = sqlite3.connect(sqlite_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, description, deadline_ts FROM Commitments "
        "WHERE is_deleted=0 AND deadline_ts < ?",
        (cutoff_ts,),
    )
    sqlite_rows = cur.fetchall()

    print(f'\n=== Commitment Retire (cutoff={time.strftime("%Y-%m-%d %H:%M", time.localtime(cutoff_ts))}) ===\n')
    print(f'SQLite Commitments overdue: {len(sqlite_rows)} 条\n')
    for r in sqlite_rows:
        iso = time.strftime('%Y-%m-%d %H:%M', time.localtime(r[2]))
        print(f'  id={r[0]} deadline={iso} desc={r[1][:60]!r}')

    # 2) 查 PromiseLog 对应的 pending commitment
    with open(promise_log_path, 'r', encoding='utf-8') as f:
        promise_log = json.load(f)
    plog_pending = []
    for pid, p in promise_log.items():
        if not isinstance(p, dict):
            continue
        if p.get('state') != 'pending':
            continue
        if p.get('kind') != 'commitment':
            continue
        # parse deadline_str
        ds = str(p.get('deadline_str', '')).strip()
        try:
            dl_ts = time.mktime(time.strptime(ds, '%Y-%m-%d %H:%M:%S'))
        except Exception:
            try:
                dl_ts = time.mktime(time.strptime(ds, '%Y-%m-%d %H:%M'))
            except Exception:
                continue
        if dl_ts < cutoff_ts:
            plog_pending.append((pid, p, dl_ts))

    print(f'\nPromiseLog pending commitments overdue: {len(plog_pending)} 条')

    if not sqlite_rows and not plog_pending:
        print('\n✅ 无过期承诺, 无需 retire')
        conn.close()
        return 0

    if args.dry_run:
        print('\n[DRY-RUN] 未写, 加 --dry-run=False 才执行')
        conn.close()
        return 0

    # 3) 执行 retire
    iso_now = time.strftime('%Y-%m-%dT%H:%M:%S')
    retire_reason = (
        f"Sir 真测 BUG-3 / 2026-05-24: 过期承诺自动 retire. "
        f"SQLite mark is_deleted=1, 不再 nudge. PromiseLog state=fulfilled, "
        f"历史 evidence 保留 (主脑通过 PromiseLog 读历史)."
    )

    # 3a) SQLite mark is_deleted=1
    n_sqlite = 0
    for r in sqlite_rows:
        try:
            cur.execute(
                "UPDATE Commitments SET is_deleted=1 WHERE id=?",
                (r[0],),
            )
            n_sqlite += 1
        except Exception as e:
            print(f'⚠️ SQLite mark id={r[0]} 失败: {e}', file=sys.stderr)
    conn.commit()
    conn.close()

    # 3b) PromiseLog mark state=fulfilled + evidence
    n_plog = 0
    for pid, p, dl_ts in plog_pending:
        try:
            promise_log[pid]['state'] = 'fulfilled'
            promise_log[pid]['fulfilled_at'] = now
            ev = promise_log[pid].setdefault('evidence', [])
            ev.append({
                'when': now,
                'when_iso': iso_now,
                'kind': 'auto_retire_overdue',
                'what': retire_reason,
            })
            n_plog += 1
        except Exception as e:
            print(f'⚠️ PromiseLog mark {pid} 失败: {e}', file=sys.stderr)

    with open(promise_log_path, 'w', encoding='utf-8') as f:
        json.dump(promise_log, f, indent=2, ensure_ascii=False)

    print(f'\n✅ 完成:')
    print(f'  SQLite mark is_deleted: {n_sqlite} 条')
    print(f'  PromiseLog mark fulfilled: {n_plog} 条')
    print(f'\n下次 Jarvis 启动 → CommitmentWatcher 不再读这些 → 不再 nudge.')
    print(f'主脑可通过 PromiseLog evidence 仍能 reference 历史 (kind=auto_retire_overdue).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
