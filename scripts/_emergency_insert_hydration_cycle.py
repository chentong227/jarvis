#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[P5-fix35-A / 2026-05-23 11:08] Sir 真测 hydration BUG 兜底.

Sir 11:05 让主脑设 90 min hydration cycle 14:30→22:00 → 主脑只 emit 1 个
add_reminder (14:30), 后续 5 个 (16:00/17:30/19:00/20:30/22:00) 没 emit,
嘴上说 'continue 90-minute cycle'. ClaimTracer 抓到 unverified 但没拦.

本脚本兜底插 5 个 reminder, Sir 今天能用. 后续 P5-fix35-C cyclic_task organ
通用化, 主脑下次说"循环 X"能 emit 一个 cyclic_task 自动展开 → 不需要 SQL 补.
"""
import sqlite3
import time
import os
from datetime import datetime

DB_PATH = os.path.join('memory_pool', 'jarvis_memory.db')


def main():
    if not os.path.exists(DB_PATH):
        print(f"[error] DB not found: {DB_PATH}")
        return 1

    # 5 个 reminder: 16:00 / 17:30 / 19:00 / 20:30 / 22:00 today
    today = datetime.now().date()
    schedule = [
        (16, 0),
        (17, 30),
        (19, 0),
        (20, 30),
        (22, 0),
    ]

    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cur = conn.cursor()

    # check if any of these already exist (avoid double-insert)
    inserted = []
    skipped = []
    for hh, mm in schedule:
        dt = datetime(today.year, today.month, today.day, hh, mm)
        trigger_ts = dt.timestamp()
        intent = f"💧 Hydration reminder ({hh:02d}:{mm:02d}) — 喝 ~300ml 水"

        # dup check: same trigger_time (±60s) + 'Hydration' in intent
        cur.execute(
            "SELECT id FROM TaskMemories WHERE is_future_task=1 AND is_deleted=0 "
            "AND ABS(trigger_time - ?) < 60 AND user_intent LIKE '%Hydration%'",
            (trigger_ts,)
        )
        if cur.fetchone():
            skipped.append(f"{hh:02d}:{mm:02d}")
            continue

        cur.execute('''
            INSERT INTO TaskMemories
            (timestamp, environment, user_intent, macro_goal, execution_summary,
             raw_actions, semantic_embedding, memory_type, entities_json,
             is_future_task, trigger_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            time.time(),
            'CHAT',
            intent,
            'hydration_cycle_2026-05-23',
            '90 min cycle reminder (P5-fix35-A SQL bootstrap)',
            '[]',
            None,
            'REMINDER',
            '{}',
            1,
            trigger_ts,
        ))
        inserted.append((cur.lastrowid, f"{hh:02d}:{mm:02d}"))

    conn.commit()

    print("=" * 60)
    print(f"Hydration Cycle Bootstrap (P5-fix35-A)")
    print("=" * 60)
    print(f"Already in DB / skipped: {skipped}")
    print(f"Inserted ({len(inserted)}):")
    for rid, t in inserted:
        print(f"  ID={rid}  trigger={t}")
    print()

    # Verify final state
    cur.execute(
        "SELECT id, user_intent, trigger_time FROM TaskMemories "
        "WHERE is_future_task=1 AND is_deleted=0 "
        "AND (user_intent LIKE '%Hydration%' OR user_intent LIKE '%hydration%') "
        "ORDER BY trigger_time"
    )
    print("Active hydration future reminders now:")
    for r in cur.fetchall():
        iso = time.strftime('%Y-%m-%d %H:%M', time.localtime(r[2]))
        print(f"  ID={r[0]}  {iso}  {r[1][:60]}")

    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
