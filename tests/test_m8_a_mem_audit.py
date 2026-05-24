"""[Reshape M8.A] tests for jarvis_mem_audit unified writer + reader."""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestMemAuditWriter(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # patch MEM_DIR + UNIFIED_PATH + LEGACY_PATHS
        self._patches = []
        import jarvis_mem_audit as ma
        self._orig_unified = ma.UNIFIED_PATH
        self._orig_legacy = dict(ma.LEGACY_PATHS)
        self._orig_mem_dir = ma.MEM_DIR
        ma.MEM_DIR = self.tmpdir
        ma.UNIFIED_PATH = os.path.join(self.tmpdir, 'mem_audit.jsonl')
        ma.LEGACY_PATHS = {
            'mutation': os.path.join(self.tmpdir, 'mutation_receipts.jsonl'),
            'correction': os.path.join(self.tmpdir, 'profile_corrections.jsonl'),
            'claim_revision': os.path.join(self.tmpdir, 'claim_revisions.json'),
            'claim_stat': os.path.join(self.tmpdir, 'claim_stats.json'),
            'integrity_unverified': os.path.join(self.tmpdir, 'integrity_audit.jsonl'),
        }

    def tearDown(self):
        import jarvis_mem_audit as ma
        ma.UNIFIED_PATH = self._orig_unified
        ma.LEGACY_PATHS = self._orig_legacy
        ma.MEM_DIR = self._orig_mem_dir
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_audit_creates_unified(self):
        from jarvis_mem_audit import write_audit, UNIFIED_PATH
        rec = {'mutation_id': 'm1', 'field_path': 'preferences.x'}
        ok = write_audit(rec, kind='mutation', source='test')
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(UNIFIED_PATH))
        with open(UNIFIED_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 1)
        loaded = json.loads(lines[0])
        self.assertEqual(loaded['kind'], 'mutation')
        self.assertEqual(loaded['mutation_id'], 'm1')
        self.assertEqual(loaded['source'], 'test')
        self.assertIn('ts', loaded)
        self.assertIn('iso', loaded)

    def test_write_audit_dual_write_legacy_jsonl(self):
        from jarvis_mem_audit import write_audit, LEGACY_PATHS
        rec = {'field': 'x', 'old': 'a', 'new': 'b'}
        write_audit(rec, kind='correction', source='test_dual', dual_write=True)
        legacy = LEGACY_PATHS['correction']
        self.assertTrue(os.path.exists(legacy))

    def test_write_audit_dual_write_disabled(self):
        from jarvis_mem_audit import write_audit, LEGACY_PATHS
        rec = {'field': 'x'}
        write_audit(rec, kind='correction', source='test', dual_write=False)
        legacy = LEGACY_PATHS['correction']
        self.assertFalse(os.path.exists(legacy))

    def test_normalize_record_adds_ts_iso(self):
        from jarvis_mem_audit import _normalize_record
        rec = _normalize_record({'foo': 'bar'}, kind='system_event', source='x')
        self.assertEqual(rec['kind'], 'system_event')
        self.assertEqual(rec['source'], 'x')
        self.assertIn('ts', rec)
        self.assertIn('iso', rec)

    def test_write_multiple_records(self):
        from jarvis_mem_audit import write_audit, UNIFIED_PATH
        for i in range(5):
            write_audit({'mut_id': f'm{i}'}, kind='mutation', source='loop')
        with open(UNIFIED_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 5)


class TestMemAuditReader(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import jarvis_mem_audit as ma
        self._orig_unified = ma.UNIFIED_PATH
        self._orig_legacy = dict(ma.LEGACY_PATHS)
        self._orig_mem_dir = ma.MEM_DIR
        ma.MEM_DIR = self.tmpdir
        ma.UNIFIED_PATH = os.path.join(self.tmpdir, 'mem_audit.jsonl')
        ma.LEGACY_PATHS = {
            'mutation': os.path.join(self.tmpdir, 'mutation_receipts.jsonl'),
            'correction': os.path.join(self.tmpdir, 'profile_corrections.jsonl'),
            'claim_revision': os.path.join(self.tmpdir, 'claim_revisions.json'),
            'claim_stat': os.path.join(self.tmpdir, 'claim_stats.json'),
            'integrity_unverified': os.path.join(self.tmpdir, 'integrity_audit.jsonl'),
        }

    def tearDown(self):
        import jarvis_mem_audit as ma
        ma.UNIFIED_PATH = self._orig_unified
        ma.LEGACY_PATHS = self._orig_legacy
        ma.MEM_DIR = self._orig_mem_dir
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_unified_empty(self):
        from jarvis_mem_audit import read_unified
        records = read_unified()
        self.assertEqual(records, [])

    def test_read_unified_after_write(self):
        from jarvis_mem_audit import write_audit, read_unified
        write_audit({'a': 1}, kind='mutation', source='s1')
        time.sleep(0.01)
        write_audit({'b': 2}, kind='correction', source='s2')
        records = read_unified()
        self.assertEqual(len(records), 2)
        # 倒序: 最新在前
        self.assertEqual(records[0]['kind'], 'correction')
        self.assertEqual(records[1]['kind'], 'mutation')

    def test_read_unified_kind_filter(self):
        from jarvis_mem_audit import write_audit, read_unified
        write_audit({'a': 1}, kind='mutation', source='s1')
        write_audit({'b': 2}, kind='correction', source='s2')
        records = read_unified(kinds={'mutation'})
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['kind'], 'mutation')

    def test_read_unified_limit(self):
        from jarvis_mem_audit import write_audit, read_unified
        for i in range(10):
            write_audit({'i': i}, kind='mutation', source='loop')
        records = read_unified(limit=3)
        self.assertEqual(len(records), 3)

    def test_get_audit_stats(self):
        from jarvis_mem_audit import write_audit, get_audit_stats
        write_audit({'a': 1}, kind='mutation', source='x')
        stats = get_audit_stats()
        self.assertTrue(stats['unified_exists'])
        self.assertEqual(stats['unified_lines'], 1)
        self.assertIn('legacy', stats)


if __name__ == '__main__':
    unittest.main()
