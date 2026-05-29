# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('JARVIS_MIRROR', '1')

from jarvis_relationship_reflector import (  # noqa: E402
    RelationshipReflector,
    propose_relationship_signal,
)
from jarvis_relationship_state import RelationshipStateStore  # noqa: E402


class TestRelationshipReflector(unittest.TestCase):

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='_relationship_reflector.json')
        os.close(fd)
        try:
            os.unlink(self.path)
        except Exception:
            pass
        self.store = RelationshipStateStore(self.path)

    def tearDown(self):
        try:
            os.unlink(self.path)
        except Exception:
            pass

    def test_propose_relationship_signal_review_only(self):
        ok, pid = propose_relationship_signal(
            'trust', 0.8, 'Sir praised follow-through', 'turn_r_001',
            store=self.store,
        )
        self.assertTrue(ok, pid)
        self.assertEqual(self.store.state.trust, 0.5)
        self.assertEqual(len(self.store.list_review()), 1)
        self.assertEqual(self.store.list_review()[0].evidence_turn_id, 'turn_r_001')

    def test_reflect_once_forced_json_proposes_review(self):
        reflector = RelationshipReflector(self.store)
        stm = [
            {'source': 'user_voice', 'text': '这次你跟得很好', 'turn_id': 'turn_r_002'},
            {'source': 'jarvis_voice', 'text': 'Understood, Sir.'},
        ]
        result = reflector.reflect_once(
            stm,
            force_llm_text=(
                '{"proposal":{"dimension":"rhythm","value":0.74,'
                '"reason":"Sir indicated timing matched well"}}'
            ),
        )
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['proposed'], result)
        self.assertEqual(self.store.state.rhythm, 0.5)
        proposal = self.store.list_review()[0]
        self.assertEqual(proposal.dimension, 'rhythm')
        self.assertEqual(proposal.proposed_value, 0.74)
        self.assertEqual(proposal.evidence_turn_id, 'turn_r_002')

    def test_reflect_once_null_proposal_noop(self):
        reflector = RelationshipReflector(self.store)
        result = reflector.reflect_once(
            [{'source': 'user_voice', 'text': '普通一句话'}],
            force_llm_text='{"proposal": null}',
        )
        self.assertTrue(result['ok'])
        self.assertFalse(result['proposed'])
        self.assertEqual(self.store.list_review(), [])

    def test_build_prompt_contains_state_and_dimensions(self):
        reflector = RelationshipReflector(self.store)
        prompt = reflector.build_prompt([
            {'source': 'user_voice', 'text': '你刚刚处理得不错'},
        ])
        self.assertIn('RELATIONSHIP STATE:', prompt)
        self.assertIn('temperature', prompt)
        self.assertIn('你刚刚处理得不错', prompt)


if __name__ == '__main__':
    unittest.main(verbosity=2)
