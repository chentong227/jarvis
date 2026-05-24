"""[Reshape M8.B] tests for jarvis_sir_state unified state read facade."""
import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestSirStateReader(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import jarvis_sir_state as ss
        self._orig_unified = ss.UNIFIED_PATH
        self._orig_legacy = dict(ss.LEGACY_PATHS)
        self._orig_mem_dir = ss.MEM_DIR
        ss.MEM_DIR = self.tmpdir
        ss.UNIFIED_PATH = os.path.join(self.tmpdir, 'sir_state.json')
        ss.LEGACY_PATHS = {
            'sir_status': os.path.join(self.tmpdir, 'sir_status.json'),
            'stand_down': os.path.join(self.tmpdir, 'stand_down_state.json'),
            'sir_acked': os.path.join(self.tmpdir, 'sir_acked_state.json'),
        }

    def tearDown(self):
        import jarvis_sir_state as ss
        ss.UNIFIED_PATH = self._orig_unified
        ss.LEGACY_PATHS = self._orig_legacy
        ss.MEM_DIR = self._orig_mem_dir
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, kind: str, data: dict):
        from jarvis_sir_state import LEGACY_PATHS
        with open(LEGACY_PATHS[kind], 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)

    def test_get_physical_state_default_unknown(self):
        from jarvis_sir_state import get_physical_state
        s = get_physical_state()
        self.assertEqual(s['status'], 'unknown')

    def test_get_physical_state_active(self):
        self._write('sir_status', {
            'current': {'status': 'active', 'since_ts': 1779589645.0},
        })
        from jarvis_sir_state import get_physical_state
        s = get_physical_state()
        self.assertEqual(s['status'], 'active')
        self.assertTrue(s['active'])
        self.assertFalse(s['sleeping'])

    def test_get_physical_state_sleeping(self):
        self._write('sir_status', {
            'current': {'status': 'sleeping', 'since_ts': 0},
        })
        from jarvis_sir_state import get_physical_state
        s = get_physical_state()
        self.assertEqual(s['status'], 'sleeping')
        self.assertTrue(s['sleeping'])

    def test_get_stand_down_default_inactive(self):
        from jarvis_sir_state import get_stand_down_state
        sd = get_stand_down_state()
        self.assertFalse(sd['active'])

    def test_get_stand_down_active(self):
        self._write('stand_down', {
            'active': True,
            'since_ts': 1.0, 'until_ts': 1800.0,
            'reason': 'manual',
        })
        from jarvis_sir_state import get_stand_down_state
        sd = get_stand_down_state()
        self.assertTrue(sd['active'])
        self.assertEqual(sd['reason'], 'manual')

    def test_get_acked_state(self):
        self._write('sir_acked', {
            'item_acks': {'item_x': 1700000000.0, 'item_y': 1700001000.0},
        })
        from jarvis_sir_state import get_acked_state
        a = get_acked_state()
        self.assertEqual(len(a['item_acks']), 2)

    def test_read_unified_empty(self):
        from jarvis_sir_state import read_unified
        u = read_unified()
        self.assertIn('_meta', u)
        self.assertEqual(u['physical']['status'], 'unknown')
        self.assertFalse(u['stand_down']['active'])

    def test_read_unified_full(self):
        self._write('sir_status', {'current': {'status': 'active', 'since_ts': 1.0}})
        self._write('stand_down', {'active': False})
        self._write('sir_acked', {'item_acks': {'a': 1.0}})
        from jarvis_sir_state import read_unified
        u = read_unified()
        self.assertEqual(u['physical']['status'], 'active')
        self.assertFalse(u['stand_down']['active'])
        self.assertEqual(len(u['acked']['item_acks']), 1)

    def test_write_unified_snapshot(self):
        self._write('sir_status', {'current': {'status': 'active'}})
        from jarvis_sir_state import write_unified_snapshot, UNIFIED_PATH
        ok = write_unified_snapshot()
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(UNIFIED_PATH))
        with open(UNIFIED_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('physical', data)
        self.assertEqual(data['physical']['status'], 'active')

    def test_render_state_block(self):
        self._write('sir_status', {'current': {'status': 'active', 'since_ts': 1.0}})
        self._write('stand_down', {
            'active': True, 'since_ts': time.time(),
            'until_ts': time.time() + 1800,
            'reason': 'meeting',
        })
        from jarvis_sir_state import render_state_block
        block = render_state_block()
        self.assertIn('[SIR STATE', block)
        self.assertIn('active', block)
        self.assertIn('stand_down: ACTIVE', block)
        self.assertIn('meeting', block)


if __name__ == '__main__':
    unittest.main()
