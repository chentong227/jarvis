# -*- coding: utf-8 -*-
"""[P0+20-β.2.4.2 / 2026-05-16] sir_profile → relational_state 迁移脚本测试

测 scripts/migrate_profile_to_relational.py 的：
- dry-run 不写 relational
- --apply 真写
- --delete-from-profile 备份 + 删字段
- 已存在 id 不重复添加（dedupe）
- 空 our_inside_jokes / significant_milestones 不抛
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_relational import (
    RelationalStateStore, InsideJoke, SharedHistoryThread,
    make_joke_id, make_thread_id,
)


SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'scripts', 'migrate_profile_to_relational.py'
)


class TestMigrationDryRun(unittest.TestCase):

    def setUp(self):
        self.profile_tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        json.dump({
            'core_philosophy': 'placeholder',
            'our_inside_jokes': [
                'becoming overbearing',
                'the furniture',
                'sleeping definition is flexible',
            ],
            'significant_milestones': [
                'Built and deployed J.A.R.V.I.S.',
                'P0+19 nerve split done',
            ],
        }, self.profile_tmp, ensure_ascii=False)
        self.profile_tmp.close()

        self.relational_tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.relational_tmp.close()
        os.unlink(self.relational_tmp.name)

    def tearDown(self):
        for p in (self.profile_tmp.name, self.relational_tmp.name):
            if os.path.exists(p):
                os.unlink(p)
        # also clean .bak files
        for f in os.listdir(os.path.dirname(self.profile_tmp.name)):
            if f.startswith(os.path.basename(self.profile_tmp.name)) and '.bak.' in f:
                try:
                    os.unlink(os.path.join(os.path.dirname(self.profile_tmp.name), f))
                except Exception:
                    pass

    def _run(self, *args, timeout: float = 20.0):
        cmd = [
            sys.executable, SCRIPT_PATH,
            '--profile-path', self.profile_tmp.name,
            '--relational-path', self.relational_tmp.name,
        ] + list(args)
        return subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout
        )

    def test_dry_run_does_not_create_relational_file(self):
        r = self._run()
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        self.assertIn('DRY-RUN', r.stdout)
        self.assertIn('jokes to add', r.stdout)
        self.assertIn('3', r.stdout)  # 3 jokes
        self.assertFalse(os.path.exists(self.relational_tmp.name))

    def test_dry_run_does_not_modify_profile(self):
        before = open(self.profile_tmp.name, encoding='utf-8').read()
        self._run()
        after = open(self.profile_tmp.name, encoding='utf-8').read()
        self.assertEqual(before, after)


class TestMigrationApply(unittest.TestCase):

    def setUp(self):
        self.profile_tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        json.dump({
            'core_philosophy': 'placeholder',
            'our_inside_jokes': ['joke A', 'joke B'],
            'significant_milestones': ['milestone X'],
            'active_projects': ['project 1'],
        }, self.profile_tmp, ensure_ascii=False)
        self.profile_tmp.close()

        self.relational_tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.relational_tmp.close()
        os.unlink(self.relational_tmp.name)

    def tearDown(self):
        for p in (self.profile_tmp.name, self.relational_tmp.name):
            if os.path.exists(p):
                os.unlink(p)
        d = os.path.dirname(self.profile_tmp.name)
        for f in os.listdir(d):
            if f.startswith(os.path.basename(self.profile_tmp.name)) and '.bak.' in f:
                try:
                    os.unlink(os.path.join(d, f))
                except Exception:
                    pass

    def _run(self, *args, timeout: float = 20.0):
        cmd = [
            sys.executable, SCRIPT_PATH,
            '--profile-path', self.profile_tmp.name,
            '--relational-path', self.relational_tmp.name,
        ] + list(args)
        return subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout
        )

    def test_apply_writes_relational_file(self):
        r = self._run('--apply')
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        self.assertTrue(os.path.exists(self.relational_tmp.name))
        self.assertIn('APPLIED', r.stdout)
        self.assertIn('jokes_added', r.stdout)
        self.assertIn('threads_added', r.stdout)

    def test_apply_jokes_and_threads_correct(self):
        self._run('--apply')
        store = RelationalStateStore(persist_path=self.relational_tmp.name)
        store.load()
        jokes = store.list_inside_jokes()
        threads = store.list_threads()
        self.assertEqual(len(jokes), 2)
        self.assertEqual(len(threads), 1)

        phrases = {j.phrase for j in jokes}
        self.assertIn('joke A', phrases)
        self.assertIn('joke B', phrases)
        titles = {t.title for t in threads}
        self.assertIn('milestone X', titles)

        for j in jokes:
            self.assertEqual(j.source, 'migrated_from_profile')
            self.assertIn('β.2.4.2', j.source_marker)
        for t in threads:
            self.assertEqual(t.source, 'migrated_from_profile')

    def test_apply_does_not_delete_profile_by_default(self):
        self._run('--apply')
        with open(self.profile_tmp.name, encoding='utf-8') as f:
            d = json.load(f)
        self.assertIn('our_inside_jokes', d)
        self.assertIn('significant_milestones', d)

    def test_apply_delete_from_profile_removes_keys_and_backs_up(self):
        r = self._run('--apply', '--delete-from-profile')
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        with open(self.profile_tmp.name, encoding='utf-8') as f:
            d = json.load(f)
        self.assertNotIn('our_inside_jokes', d)
        self.assertNotIn('significant_milestones', d)
        # active_projects should remain（Sir 画像）
        self.assertIn('active_projects', d)
        self.assertIn('core_philosophy', d)
        # backup must exist
        d_dir = os.path.dirname(self.profile_tmp.name)
        base = os.path.basename(self.profile_tmp.name)
        baks = [f for f in os.listdir(d_dir)
                if f.startswith(base) and '.bak.' in f]
        self.assertTrue(len(baks) >= 1, "backup file not found")

    def test_apply_dedupes_when_run_twice(self):
        self._run('--apply')
        store1 = RelationalStateStore(persist_path=self.relational_tmp.name)
        store1.load()
        before_jokes = len(store1.list_inside_jokes())

        # Run again — should skip duplicates
        r2 = self._run('--apply')
        self.assertEqual(r2.returncode, 0)
        store2 = RelationalStateStore(persist_path=self.relational_tmp.name)
        store2.load()
        after_jokes = len(store2.list_inside_jokes())
        self.assertEqual(before_jokes, after_jokes)
        self.assertIn('skipped', r2.stdout.lower())


class TestMigrationEmptyOrMissing(unittest.TestCase):

    def setUp(self):
        self.profile_tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        # 没有 our_inside_jokes / significant_milestones 字段
        json.dump({'core_philosophy': 'placeholder'}, self.profile_tmp,
                  ensure_ascii=False)
        self.profile_tmp.close()

        self.relational_tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.relational_tmp.close()
        os.unlink(self.relational_tmp.name)

    def tearDown(self):
        for p in (self.profile_tmp.name, self.relational_tmp.name):
            if os.path.exists(p):
                os.unlink(p)

    def test_missing_fields_no_crash(self):
        cmd = [
            sys.executable, SCRIPT_PATH,
            '--profile-path', self.profile_tmp.name,
            '--relational-path', self.relational_tmp.name,
            '--apply',
        ]
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=20
        )
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        self.assertIn('jokes_added', r.stdout)
        self.assertIn('= 0', r.stdout.replace('       ', ''))


if __name__ == '__main__':
    unittest.main(verbosity=2)
