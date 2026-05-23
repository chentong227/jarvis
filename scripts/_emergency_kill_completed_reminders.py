#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[P5-fix35-emergency / 2026-05-23 10:54] Sir 真测 BUG#11 + BUG#12 触发死循环.

主脑教正"我已完成 X" → memory_correction 把"已完成 X"当 new_val 改 hippocampus →
hippocampus 上游补 REMINDER 占位 (因含时间锚 "今天早上10点") → 注册 TaskMemories
is_future_task=1 trigger_time=过去 → ChronosSentinel 每 30s 扫到 → fire reminder →
主脑被唤醒 → emit modify_record 又含时间锚 → 再注册 reminder → 死循环.

3 条 "Completed:" / "已完成" 类 reminder 在 fire loop (ID 11/12/13).
本脚本: SQL kill all 含 Completed/已完成 前缀的 future reminder.
"""
import sqlite3
import sys
import time
import os

DB_PATH = os.path.join('memory_pool', 'jarvis_memory.db')


def main():
    if not os.path.exists(DB_PATH):
        print(f"[error] DB not found: {DB_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()

    # List active reminders
    cursor.execute(
        "SELECT id, user_intent, trigger_time FROM TaskMemories "
        "WHERE is_future_task = 1 AND is_deleted = 0"
    )
    rows = cursor.fetchall()
    print(f"Active future reminders (is_future_task=1, is_deleted=0): {len(rows)}")
    for r in rows:
        iso = time.strftime('%Y-%m-%d %H:%M',
                              time.localtime(r[2])) if r[2] else 'n/a'
        intent_disp = (r[1] or '')[:80]
        print(f"  ID={r[0]}  trigger={iso}  intent={intent_disp}")

    # Kill all completed-prefixed
    cursor.execute(
        "UPDATE TaskMemories SET is_future_task = 0 "
        "WHERE is_future_task = 1 AND is_deleted = 0 "
        "AND (user_intent LIKE 'Completed:%' "
        "  OR user_intent LIKE 'Completed %' "
        "  OR user_intent LIKE '已完成%' "
        "  OR user_intent LIKE '已经完成%' "
        "  OR user_intent LIKE '%已完成:%' "
        ")"
    )
    n_killed = cursor.rowcount
    conn.commit()
    print(f"")
    print(f">>> Killed {n_killed} completed-prefixed future reminders.")
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
