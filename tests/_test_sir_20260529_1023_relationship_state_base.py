# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('JARVIS_MIRROR', '1')

from jarvis_relationship_state import RelationshipStateStore  # noqa: E402


class TestRelationshipStateBase(unittest.TestCase):

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='_relationship_state.json')
        os.close(fd)
        try:
            os.unlink(self.path)
        except Exception:
            pass

    def tearDown(self):
        try:
            os.unlink(self.path)
        except Exception:
            pass

    def test_default_prompt_line_one_line_and_budgeted(self):
        store = RelationshipStateStore(self.path)
        line = store.to_prompt_line(max_chars=80)
        self.assertIn('RELATIONSHIP STATE:', line)
        self.assertNotIn('\n', line)
        self.assertLessEqual(len(line), 80)

    def test_set_dimension_clamps_persists_and_loads(self):
        store = RelationshipStateStore(self.path)
        ok, msg = store.set_dimension('trust', 1.8, note='manual correction')
        self.assertTrue(ok, msg)
        self.assertEqual(store.state.trust, 1.0)
        self.assertTrue(os.path.exists(self.path))

        loaded = RelationshipStateStore(self.path)
        loaded.load()
        self.assertEqual(loaded.state.trust, 1.0)
        self.assertEqual(loaded.state.note, 'manual correction')

    def test_unknown_dimension_rejected(self):
        store = RelationshipStateStore(self.path)
        ok, msg = store.set_dimension('moodiness', 0.5)
        self.assertFalse(ok)
        self.assertIn('unknown dimension', msg)

    def test_central_nerve_layer2_injects_relationship_line(self):
        from jarvis_central_nerve import CentralNerve
        nerve = object.__new__(CentralNerve)
        nerve.relational_state = None
        with patch('jarvis_relationship_state.get_default_store',
                   return_value=RelationshipStateStore(self.path)):
            block = nerve._build_layer_2_relational_block()
        self.assertIn('RELATIONSHIP STATE:', block)

    def test_cli_list_and_set_with_temp_path(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = os.path.join(root, 'scripts', 'relationship_state_dump.py')
        env = os.environ.copy()
        env['PYTHONUTF8'] = '1'
        env['JARVIS_MIRROR'] = '1'
        r1 = subprocess.run(
            [sys.executable, script, '--path', self.path, 'set', 'rhythm', '0.72', '--note', 'cli test'],
            cwd=root, env=env, text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(r1.returncode, 0, r1.stderr + r1.stdout)
        r2 = subprocess.run(
            [sys.executable, script, '--path', self.path, 'list'],
            cwd=root, env=env, text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(r2.returncode, 0, r2.stderr + r2.stdout)
        self.assertIn('rhythm=0.72', r2.stdout)
        with open(self.path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['state']['source'], 'sir_cli')


if __name__ == '__main__':
    unittest.main(verbosity=2)
