# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('JARVIS_MIRROR', '1')

import jarvis_inner_thought_daemon as itd  # noqa: E402
from jarvis_inner_thought_daemon import InnerThoughtDaemon  # noqa: E402
from jarvis_relationship_reflector import RelationshipReflector  # noqa: E402
from scripts import relationship_reflector_dump  # noqa: E402


class TestRelationshipReflectorInnerHook(unittest.TestCase):

    def test_config_default_disabled(self):
        cfg = itd._load_relationship_reflector_config()
        self.assertFalse(cfg.get('enabled'))
        self.assertFalse(cfg.get('use_llm'))
        self.assertGreaterEqual(int(cfg.get('min_interval_s', 0)), 3600)

    def test_inner_hook_disabled_noop(self):
        daemon = InnerThoughtDaemon(key_router=None)
        daemon._maybe_run_relationship_reflector({
            'stm': [
                {'user': '你这次节奏不错', 'jarvis': 'Understood, Sir.'},
                {'user': '继续保持', 'jarvis': 'Yes, Sir.'},
            ]
        })
        self.assertEqual(daemon._last_relationship_reflector_ts, 0.0)

    def test_reflector_formats_inner_thought_stm_shape(self):
        text = RelationshipReflector._format_stm([
            {'user': '你刚才跟得很好', 'jarvis': 'Understood, Sir.'},
        ])
        self.assertIn('[Sir] 你刚才跟得很好', text)
        self.assertIn('[Jarvis] Understood, Sir.', text)

    def test_cli_path_enable_set_reset_smoke(self):
        fd, path = tempfile.mkstemp(suffix='_relationship_reflector_config.json')
        os.close(fd)
        try:
            os.unlink(path)
            relationship_reflector_dump.main([
                '--path', path, '--enable', '--llm-on',
                '--set', 'min_interval_s=60',
            ])
            cfg = relationship_reflector_dump._load(path)
            self.assertTrue(cfg['enabled'])
            self.assertTrue(cfg['use_llm'])
            self.assertEqual(cfg['min_interval_s'], 60)

            relationship_reflector_dump.main(['--path', path, '--reset'])
            cfg = relationship_reflector_dump._load(path)
            self.assertFalse(cfg['enabled'])
            self.assertFalse(cfg['use_llm'])
            self.assertEqual(cfg['min_interval_s'], 21600)
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass


if __name__ == '__main__':
    unittest.main(verbosity=2)
