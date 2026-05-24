"""[Reshape M1.2] tests for SWM critical event 持久化 + 重启 restore."""
import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from jarvis_utils import ConversationEventBus


class TestSWMPersist(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.persist_path = os.path.join(self.tmpdir, 'swm_history.jsonl')
        # patch class-level path
        self._orig_path = ConversationEventBus.SWM_PERSIST_PATH
        ConversationEventBus.SWM_PERSIST_PATH = self.persist_path
        # ensure dir exists
        os.makedirs(self.tmpdir, exist_ok=True)

    def tearDown(self):
        ConversationEventBus.SWM_PERSIST_PATH = self._orig_path
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_high_salience_event_persisted(self):
        bus = ConversationEventBus()
        # publish high-salience event (>= 0.85)
        bus.publish(etype='intent_resolved',
                    description='Sir confirmed: drink 8 cups',
                    salience=0.90,
                    source='test')
        # file should exist with 1 line
        self.assertTrue(os.path.exists(self.persist_path))
        with open(self.persist_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec['type'], 'intent_resolved')
        self.assertEqual(rec['salience'], 0.90)
        self.assertIn('description', rec)
        self.assertIn('timestamp', rec)

    def test_low_salience_not_persisted(self):
        bus = ConversationEventBus()
        bus.publish(etype='emotion_shift',
                    description='emotion=neutral',
                    salience=0.4,
                    source='test')
        self.assertFalse(os.path.exists(self.persist_path))

    def test_threshold_boundary(self):
        bus = ConversationEventBus()
        # 0.85 = threshold itself → persist
        bus.publish(etype='tool_called',
                    description='exactly at threshold',
                    salience=0.85,
                    source='test')
        self.assertTrue(os.path.exists(self.persist_path))
        # 0.84 = below → not persist (clear file)
        os.remove(self.persist_path)
        bus2 = ConversationEventBus()
        bus2.publish(etype='other',
                     description='below threshold',
                     salience=0.84,
                     source='test')
        self.assertFalse(os.path.exists(self.persist_path))

    def test_restore_on_init(self):
        # First bus: write 3 high-salience events
        bus1 = ConversationEventBus()
        bus1.publish('a', 'event 1', salience=0.90, source='t')
        bus1.publish('b', 'event 2', salience=0.91, source='t')
        bus1.publish('c', 'event 3', salience=0.92, source='t')

        # Second bus: should restore from disk
        bus2 = ConversationEventBus()
        events = bus2.recent_events()
        # 3 restored events should be visible (within TTL)
        self.assertGreaterEqual(len(events), 3)
        descs = [e['description'] for e in events]
        self.assertIn('event 1', descs)
        self.assertIn('event 2', descs)
        self.assertIn('event 3', descs)
        # verify restored marker
        for e in events:
            if e['description'] in ('event 1', 'event 2', 'event 3'):
                self.assertTrue(e.get('_restored_from_disk'))

    def test_restore_skips_expired_ttl(self):
        # Manually write a stale record (timestamp 2 hours ago, ttl 60s)
        os.makedirs(self.tmpdir, exist_ok=True)
        stale_rec = {
            'type': 'old_event',
            'description': 'too old, should skip',
            'timestamp': time.time() - 7200,  # 2h ago
            'ttl': 60.0,                        # 60s TTL → expired
            'source': 'test',
            'metadata': {},
            'salience': 0.95,
            'evidence_id': 'evt_old',
            'evidence_chain': [],
        }
        with open(self.persist_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps(stale_rec) + '\n')
        bus = ConversationEventBus()
        events = bus.recent_events()
        descs = [e['description'] for e in events]
        self.assertNotIn('too old, should skip', descs)

    def test_persist_disabled_via_env(self):
        os.environ['JARVIS_SWM_PERSIST'] = '0'
        try:
            bus = ConversationEventBus()
            bus.publish(etype='test', description='should not persist',
                        salience=0.95, source='test')
            self.assertFalse(os.path.exists(self.persist_path))
        finally:
            os.environ.pop('JARVIS_SWM_PERSIST', None)


if __name__ == '__main__':
    unittest.main()
