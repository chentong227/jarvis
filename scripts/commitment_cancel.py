# -*- coding: utf-8 -*-
"""
commitment_cancel.py — CommitmentWatcher 真正会出声的 commitment 查 + 取消 + 改时间

Sir 22:55 焦虑场景: 不想明早 9:00 被叫醒, 但不知道哪条会真叫.

PromiseLog (p_xxx) 只是观察账本, 不会真出声. 真出声的是这里的 SQLite
Commitments 表 (DB#N) — CommitmentWatcher tick 到时间就 nudge.

用法:
  python scripts/commitment_cancel.py                     # 列所有 pending
  python scripts/commitment_cancel.py --cancel 3          # 软删 DB#3
  python scripts/commitment_cancel.py --cancel 3,4        # 批量
  python scripts/commitment_cancel.py --retime 3 11:00    # 把 DB#3 deadline 改到今天 11:00
  python scripts/commitment_cancel.py --retime 3 2026-05-18,11:00  # 指定日期
  python scripts/commitment_cancel.py --wake-only 3       # 把 DB#3 改成 wake-trigger 模式
                                                              (push 时间到当天 23:00, source_text 加'醒了')
                                                              注意: 需要 wake-trigger 已并入 (β.2.8.6+)
"""
import argparse
import io
import os
import sqlite3
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, 'memory_pool', 'jarvis_memory.db')


def conn():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: DB not found at {DB_PATH}")
        sys.exit(1)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def fmt_age(ts):
    if ts <= 0:
        return '?'
    d = time.time() - ts
    if d < 60: return f"{int(d)}s ago"
    if d < 3600: return f"{int(d/60)}m ago"
    if d < 86400: return f"{int(d/3600)}h ago"
    return f"{int(d/86400)}d ago"


def fmt_eta(deadline_ts):
    d = deadline_ts - time.time()
    if d < 0:
        return f"OVERDUE by {fmt_age(deadline_ts)}"
    if d < 60: return f"in {int(d)}s"
    if d < 3600: return f"in {int(d/60)}m"
    if d < 86400: return f"in {int(d/3600)}h{int((d%3600)/60)}m"
    return f"in {int(d/86400)}d"


def list_pending():
    c = conn()
    cur = c.cursor()
    cur.execute(
        "SELECT id, description, deadline_ts, source_text, created_at, "
        "       grace_minutes, nudged, is_deleted "
        "FROM Commitments WHERE nudged=0 AND is_deleted=0 "
        "ORDER BY deadline_ts ASC"
    )
    rows = cur.fetchall()
    c.close()

    if not rows:
        print("(no pending commitments — Jarvis 不会主动出声叫你)")
        return

    print("=" * 78)
    print(f"📅 CommitmentWatcher 待 fire commitments ({len(rows)} 条)")
    print(f"   这些是会真出声的, 不是 PromiseLog 观察日志")
    print("=" * 78)
    for r in rows:
        deadline = time.strftime('%Y-%m-%d %H:%M', time.localtime(r['deadline_ts']))
        eta = fmt_eta(r['deadline_ts'])
        print(f"\n  DB#{r['id']:<3d}  ⏰ {deadline}  ({eta})")
        print(f"          desc:        {r['description'][:80]}")
        print(f"          source_text: {(r['source_text'] or '')[:80]}")
        print(f"          created:     {fmt_age(r['created_at'])}, "
              f"grace={r['grace_minutes']}min")
    print()
    print("-- 命令 --")
    print("   取消单条:  python scripts/commitment_cancel.py --cancel <id>")
    print("   批量取消:  python scripts/commitment_cancel.py --cancel 3,4,5")
    print("   改时间:    python scripts/commitment_cancel.py --retime <id> HH:MM")
    print("   wake-only: python scripts/commitment_cancel.py --wake-only <id>")
    print()


def cancel(ids):
    c = conn()
    cur = c.cursor()
    cancelled = []
    for db_id in ids:
        cur.execute(
            "UPDATE Commitments SET is_deleted=1 WHERE id=?", (db_id,)
        )
        if cur.rowcount > 0:
            cancelled.append(db_id)
    c.commit()
    c.close()
    print(f"✅ 软删 {len(cancelled)} 条: {cancelled}")
    print("注: in-memory list 由 daemon 在 12h 内自然清理. "
          "重启 Jarvis 立刻生效, 不重启也不会再 fire (DB 记 is_deleted=1).")


def retime(db_id, hh_mm, date_str=None):
    # 解析新时间
    try:
        h, m = map(int, hh_mm.split(':'))
    except Exception:
        print(f"ERROR: HH:MM format invalid: '{hh_mm}'")
        return
    if date_str:
        try:
            y, mo, d = map(int, date_str.split('-'))
            ts = time.mktime((y, mo, d, h, m, 0, 0, 0, -1))
        except Exception:
            print(f"ERROR: date format invalid: '{date_str}', need YYYY-MM-DD")
            return
    else:
        now = time.localtime()
        ts = time.mktime((now.tm_year, now.tm_mon, now.tm_mday,
                           h, m, 0, 0, 0, now.tm_isdst))
        if ts < time.time() - 60:
            ts += 86400  # 明天

    c = conn()
    cur = c.cursor()
    cur.execute(
        "UPDATE Commitments SET deadline_ts=? WHERE id=?", (ts, db_id)
    )
    if cur.rowcount > 0:
        c.commit()
        new_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))
        print(f"✅ DB#{db_id} deadline → {new_str}")
        print("注: 重启 Jarvis 立刻生效, 不重启 in-memory 缓存仍按旧时间. "
              "建议改完重启或等 12h.")
    else:
        print(f"❌ DB#{db_id} not found")
    c.close()


def wake_only(db_id):
    """把 commitment 改成 wake-trigger 友好模式:
       - deadline_ts 推到当天 22:00 (避免误闹钟)
       - source_text 注入 '醒了之后' (让 commitment_watcher β.2.8.6 wake-keyword 命中)
    """
    c = conn()
    cur = c.cursor()
    cur.execute("SELECT source_text FROM Commitments WHERE id=?", (db_id,))
    row = cur.fetchone()
    if row is None:
        print(f"❌ DB#{db_id} not found")
        c.close()
        return
    new_src = (row['source_text'] or '') + ' [醒了之后再提醒]'
    # 推到当天 22:00 防误闹
    now = time.localtime()
    ts = time.mktime((now.tm_year, now.tm_mon, now.tm_mday + 1,
                       22, 0, 0, 0, 0, now.tm_isdst))
    cur.execute(
        "UPDATE Commitments SET deadline_ts=?, source_text=? WHERE id=?",
        (ts, new_src[:500], db_id)
    )
    c.commit()
    c.close()
    print(f"✅ DB#{db_id} 改 wake-only 模式: "
          f"deadline → {time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))}, "
          f"source_text 注入'醒了'关键词 (需 β.2.8.6 wake-trigger 逻辑生效)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cancel', type=str, help='取消 db_id (单个或逗号分隔)')
    ap.add_argument('--retime', nargs='+', help='--retime <id> <HH:MM> [YYYY-MM-DD]')
    ap.add_argument('--wake-only', type=int, help='改为 wake-trigger 模式 (deadline 推到 22:00)')
    args = ap.parse_args()

    if args.cancel:
        ids = [int(x.strip()) for x in args.cancel.split(',') if x.strip()]
        cancel(ids)
    elif args.retime:
        if len(args.retime) < 2:
            print("usage: --retime <id> <HH:MM> [YYYY-MM-DD]")
            return
        db_id = int(args.retime[0])
        hh_mm = args.retime[1]
        date_str = args.retime[2] if len(args.retime) >= 3 else None
        retime(db_id, hh_mm, date_str)
    elif args.wake_only:
        wake_only(args.wake_only)
    else:
        list_pending()


if __name__ == '__main__':
    main()
