# -*- coding: utf-8 -*-
"""[Reshape M4.4 / 2026-05-24] Migration script unit test (mock SQLite + PromiseLog)

覆盖:
  - fetch_active_commitments 只取 nudged=0 AND is_deleted=0
  - plan_migration 正确算 to_migrate / already_migrated
  - is_already_migrated 同 desc + same author 内 60s 视为已迁
  - apply_migration: 真写 PromiseLog + 标 SQLite nudged=1 + backup
  - rollback restore backup OK
"""
import os
import sys
import json
import sqlite3
import shutil
import tempfile
import unittest
import time
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))


def _make_sqlite_with_commitments(db_path, rows):
    """rows: list of dict (description, deadline_ts, grace_minutes,
    source_text, created_at, nudged, is_deleted)."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE Commitments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            deadline_ts REAL NOT NULL,
            grace_minutes INTEGER DEFAULT 10,
            source_text TEXT,
            created_at REAL,
            nudged INTEGER DEFAULT 0,
            is_deleted INTEGER DEFAULT 0
        )
    ''')
    for r in rows:
        cur.execute(
            'INSERT INTO Commitments '
            '(description, deadline_ts, grace_minutes, source_text, created_at, nudged, is_deleted) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (r['description'], r['deadline_ts'], r.get('grace_minutes', 10),
             r.get('source_text', ''), r['created_at'],
             r.get('nudged', 0), r.get('is_deleted', 0))
        )
    conn.commit()
    conn.close()


class TestMigrationScript(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='m4_4_test_')
        self.db_path = os.path.join(self.tmpdir, 'jarvis_memory.db')
        self.plog_path = os.path.join(self.tmpdir, 'jarvis_promise_log.json')
        self.backup_base = os.path.join(self.tmpdir, '_legacy', 'data_migration_backup')

        # mock DB: 3 rows = 1 active + 1 nudged + 1 deleted
        _now = time.time()
        _make_sqlite_with_commitments(self.db_path, [
            {'description': 'active commitment 1', 'deadline_ts': _now + 3600,
             'created_at': _now - 100, 'nudged': 0, 'is_deleted': 0},
            {'description': 'already nudged', 'deadline_ts': _now + 7200,
             'created_at': _now - 200, 'nudged': 1, 'is_deleted': 0},
            {'description': 'deleted one', 'deadline_ts': _now + 1800,
             'created_at': _now - 50, 'nudged': 0, 'is_deleted': 1},
        ])

        # 空 PromiseLog
        with open(self.plog_path, 'w', encoding='utf-8') as f:
            json.dump({}, f)

        # patch module-level paths
        import migrate_commitments_to_promise_log as m
        self.m = m
        self._orig_db = m.DB_PATH
        self._orig_plog = m.PLOG_PATH
        self._orig_bkup = m.BACKUP_BASE
        m.DB_PATH = self.db_path
        m.PLOG_PATH = self.plog_path
        m.BACKUP_BASE = self.backup_base

        # reset PromiseLog singleton to isolated path
        from jarvis_promise_log import reset_default_log_for_test
        reset_default_log_for_test(persist_path=self.plog_path)

    def tearDown(self):
        # restore module paths
        self.m.DB_PATH = self._orig_db
        self.m.PLOG_PATH = self._orig_plog
        self.m.BACKUP_BASE = self._orig_bkup
        from jarvis_promise_log import reset_default_log_for_test
        reset_default_log_for_test()
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_fetch_active_commitments_filters_correctly(self):
        rows = self.m.fetch_active_commitments()
        self.assertEqual(len(rows), 1,
                          'fetch 应只返 nudged=0 AND is_deleted=0')
        self.assertEqual(rows[0]['description'], 'active commitment 1')

    def test_plan_migration_empty_plog(self):
        plan = self.m.plan_migration()
        self.assertEqual(plan['plog_size_before'], 0)
        self.assertEqual(plan['commitments_active'], 1)
        self.assertEqual(len(plan['to_migrate']), 1)
        self.assertEqual(len(plan['already_migrated']), 0)

    def test_apply_migration_writes_promise_log(self):
        plan = self.m.plan_migration()
        ok = self.m.apply_migration(plan)
        self.assertTrue(ok)

        # PromiseLog 真有 1 条新 promise
        with open(self.plog_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        p = list(data.values())[0]
        self.assertEqual(p['kind'], 'commitment')
        self.assertEqual(p['author'], 'sir')
        self.assertEqual(p['who_promised'], 'sir')
        self.assertIn('active commitment 1', p['description'])
        # registered_at 用原 created_at
        self.assertEqual(p['registered_at'],
                          plan['to_migrate'][0]['created_at'])
        # 含 migration evidence
        self.assertTrue(any(e.get('kind') == 'migration' for e in p['evidence']))

    def test_apply_migration_marks_sqlite_nudged(self):
        plan = self.m.plan_migration()
        self.m.apply_migration(plan)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute('SELECT nudged FROM Commitments WHERE description=?',
                     ('active commitment 1',))
        self.assertEqual(cur.fetchone()[0], 1,
                          'apply 后原 row 应标 nudged=1')
        conn.close()

    def test_apply_migration_backup_created(self):
        plan = self.m.plan_migration()
        self.m.apply_migration(plan)
        # backup dir 应该存在
        self.assertTrue(os.path.isdir(self.backup_base))
        backups = os.listdir(self.backup_base)
        self.assertEqual(len(backups), 1, 'backup 应创 1 个 timestamp 目录')
        backup_dir = os.path.join(self.backup_base, backups[0])
        self.assertTrue(os.path.exists(os.path.join(backup_dir,
                                                       'jarvis_memory.db')))
        self.assertTrue(os.path.exists(os.path.join(backup_dir,
                                                       'jarvis_promise_log.json')))

    def test_apply_then_dry_run_shows_already_migrated(self):
        """apply 后再 dry-run 应识别已 migrated (不重复)."""
        plan1 = self.m.plan_migration()
        self.m.apply_migration(plan1)
        # 第二次 dry-run
        plan2 = self.m.plan_migration()
        self.assertEqual(len(plan2['to_migrate']), 0,
                          'apply 后 to_migrate 应为 0 (dedup)')
        # 但 SQLite 那 1 条已 nudged=1, fetch_active_commitments 返 0
        # (因为 nudged=1), 所以 already_migrated 也是 0
        self.assertEqual(plan2['commitments_active'], 0)

    def test_rollback_restores_files(self):
        plan = self.m.plan_migration()
        self.m.apply_migration(plan)
        backups = os.listdir(self.backup_base)
        timestamp = backups[0]
        # 改一下 PromiseLog
        with open(self.plog_path, 'w', encoding='utf-8') as f:
            json.dump({'tampered': 'x'}, f)
        # rollback
        ok = self.m.rollback(timestamp)
        self.assertTrue(ok)
        # PromiseLog 应回到 backup 时状态 (空 {})
        with open(self.plog_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data, {}, 'rollback 后 PromiseLog 应回 backup snapshot')


class TestDedup(unittest.TestCase):
    """is_already_migrated 防重复 migrate."""

    def test_same_desc_same_author_within_60s_is_dup(self):
        from migrate_commitments_to_promise_log import is_already_migrated
        c = {'description': 'foo', 'created_at': 1000.0}
        plog_data = {
            'p1': {'description': 'foo', 'author': 'sir',
                    'registered_at': 1030.0},  # 30s diff
        }
        self.assertTrue(is_already_migrated(plog_data, c))

    def test_same_desc_different_author_not_dup(self):
        from migrate_commitments_to_promise_log import is_already_migrated
        c = {'description': 'foo', 'created_at': 1000.0}
        plog_data = {
            'p1': {'description': 'foo', 'author': 'jarvis',
                    'registered_at': 1010.0},
        }
        self.assertFalse(is_already_migrated(plog_data, c))

    def test_same_desc_far_away_not_dup(self):
        from migrate_commitments_to_promise_log import is_already_migrated
        c = {'description': 'foo', 'created_at': 1000.0}
        plog_data = {
            'p1': {'description': 'foo', 'author': 'sir',
                    'registered_at': 5000.0},  # 4000s diff
        }
        self.assertFalse(is_already_migrated(plog_data, c))

    def test_different_desc_not_dup(self):
        from migrate_commitments_to_promise_log import is_already_migrated
        c = {'description': 'foo', 'created_at': 1000.0}
        plog_data = {
            'p1': {'description': 'bar', 'author': 'sir',
                    'registered_at': 1000.0},
        }
        self.assertFalse(is_already_migrated(plog_data, c))


if __name__ == '__main__':
    unittest.main()
