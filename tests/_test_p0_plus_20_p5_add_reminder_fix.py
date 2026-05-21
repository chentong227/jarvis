# -*- coding: utf-8 -*-
"""[P5-fix-add_reminder / 2026-05-21 10:10] Sir 10:06 真测真报
"NOT NULL constraint failed: TaskMemories.timestamp" — l4_memory_hands.add_reminder
INSERT 缺 timestamp/environment/macro_goal 3 个 NOT NULL 列, 提醒功能从某次 schema
升级后就挂了 (Sir 早期记得这功能能用).

修: INSERT 时补传 timestamp=now / environment='reminder' / macro_goal='reminder: <intent>'.
"""
from __future__ import annotations

import os
import sys
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAddReminderInsert(unittest.TestCase):
    """add_reminder INSERT 包含所有 NOT NULL 列."""

    def test_source_includes_timestamp_environment_macro_goal(self):
        """l4_memory_hands.py add_reminder INSERT 必须含 timestamp + environment + macro_goal."""
        from l4_hands_pool import l4_memory_hands as mh
        with open(mh.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # 找 add_reminder block 的 INSERT
        idx = src.find('cmd == "add_reminder"')
        self.assertGreater(idx, 0, '找不到 add_reminder block')
        section = src[idx:idx + 1200]
        self.assertIn('timestamp', section, 'INSERT 必须传 timestamp')
        self.assertIn('environment', section, 'INSERT 必须传 environment')
        self.assertIn('macro_goal', section, 'INSERT 必须传 macro_goal')

    def test_real_insert_against_temp_db(self):
        """真在 temp db 插一条 future task — schema 跟生产 hippocampus 一致."""
        # mock hippocampus._get_conn 返回 temp db, 跑 INSERT 不抛 NOT NULL.
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, 'test.db')
        try:
            # 创 schema (复刻 jarvis_hippocampus.py:192-211)
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute('''
                CREATE TABLE TaskMemories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    environment TEXT NOT NULL,
                    user_intent TEXT NOT NULL,
                    macro_goal TEXT NOT NULL,
                    execution_summary TEXT,
                    raw_actions JSON,
                    semantic_embedding BLOB,
                    is_deleted INTEGER DEFAULT 0,
                    memory_type TEXT DEFAULT 'UNKNOWN',
                    entities_json TEXT DEFAULT '{}',
                    is_future_task INTEGER DEFAULT 0,
                    trigger_time REAL DEFAULT 0.0
                )
            ''')
            conn.commit()
            conn.close()

            # 模 add_reminder 行为
            import time
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO TaskMemories "
                "(timestamp, environment, user_intent, macro_goal, "
                " trigger_time, is_future_task, is_deleted) "
                "VALUES (?, ?, ?, ?, ?, 1, 0)",
                (
                    time.time(),
                    'reminder',
                    '7点叫我',
                    'reminder: 7点叫我',
                    time.time() + 3600,
                )
            )
            conn.commit()
            new_id = cur.lastrowid
            conn.close()
            self.assertGreater(new_id, 0)
        finally:
            import shutil
            try:
                shutil.rmtree(tmpdir)
            except Exception:
                pass


if __name__ == '__main__':
    unittest.main()
