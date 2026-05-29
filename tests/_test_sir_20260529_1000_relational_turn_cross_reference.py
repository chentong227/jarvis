# -*- coding: utf-8 -*-
"""[#4a / Sir 2026-05-29] Relational turn cross-reference tests."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_lineage import LineageTracer  # noqa: E402
from jarvis_relational import RelationalStateStore  # noqa: E402


class TestLineageFindDecisionsByTurn(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp_dir, 'lineage.jsonl')
        self.tracer = LineageTracer(jsonl_path=self.path,
                                    auto_start_flush=False)

    def tearDown(self):
        try:
            self.tracer.stop(timeout=0.2)
        except Exception:
            pass
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
            os.rmdir(self.tmp_dir)
        except Exception:
            pass

    def test_find_decisions_by_turn_returns_matching_decisions_only(self):
        self.tracer.record_decision(
            decision_id='bd_turn_a_1', turn_id='turn_a', reply_text='A1')
        self.tracer.record_decision(
            decision_id='bd_turn_b_1', turn_id='turn_b', reply_text='B1')
        self.tracer.record_decision(
            decision_id='bd_turn_a_2', turn_id='turn_a', reply_text='A2')

        found = self.tracer.find_decisions_by_turn('turn_a')
        self.assertEqual([d['decision_id'] for d in found],
                         ['bd_turn_a_1', 'bd_turn_a_2'])
        self.assertTrue(all(d['turn_id'] == 'turn_a' for d in found))

    def test_find_decisions_by_turn_empty_id_noop(self):
        self.assertEqual(self.tracer.find_decisions_by_turn(''), [])


class TestRelationalResolveTurn(unittest.TestCase):

    def test_resolve_turn_wraps_lineage_decisions(self):
        store = RelationalStateStore(
            persist_path=tempfile.mktemp(suffix='_rs.json'),
            review_path=tempfile.mktemp(suffix='_review.json'),
        )
        fake_tracer = MagicMock()
        fake_tracer.find_decisions_by_turn.return_value = [
            {'decision_id': 'bd_1', 'turn_id': 'turn_x', 'reply_text': 'Sir.'}
        ]
        with patch('jarvis_lineage.get_default_tracer',
                   return_value=fake_tracer):
            resolved = store.resolve_turn('turn_x')

        self.assertFalse(resolved['not_found'])
        self.assertEqual(resolved['turn_id'], 'turn_x')
        self.assertEqual(resolved['decisions'][0]['decision_id'], 'bd_1')
        fake_tracer.find_decisions_by_turn.assert_called_once_with(
            'turn_x', max_records=10)

    def test_resolve_turn_empty_id_returns_not_found(self):
        store = RelationalStateStore(
            persist_path=tempfile.mktemp(suffix='_rs.json'),
            review_path=tempfile.mktemp(suffix='_review.json'),
        )
        resolved = store.resolve_turn('')
        self.assertTrue(resolved['not_found'])
        self.assertEqual(resolved['decisions'], [])


class TestInnerThoughtProposalWritesTurnId(unittest.TestCase):

    def _make_daemon_with_rs(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        rs = RelationalStateStore(
            persist_path=tempfile.mktemp(suffix='_rs.json'),
            review_path=tempfile.mktemp(suffix='_review.json'),
        )
        with patch.object(InnerThoughtDaemon, '_append_cold_start_record',
                          return_value=None):
            daemon = InnerThoughtDaemon(
                key_router=MagicMock(),
                relational_state=rs,
            )
        return daemon, rs

    def _thought(self, category='B', salience=0.85):
        from jarvis_inner_thought_daemon import InnerThought
        return InnerThought(
            id='thought_test_001',
            ts=time.time(),
            ts_iso='2026-05-29T10:00:00',
            category=category,
            thought='I should preserve where this relational item was born.',
            salience=salience,
            actionable='none',
            evidence_link='relational item was born',
        )

    def test_suggest_inside_joke_sets_birth_turn_id(self):
        from jarvis_utils import TraceContext
        daemon, rs = self._make_daemon_with_rs()
        thought = self._thought(category='E')
        with TraceContext.captured_turn('turn_rel_joke_001'):
            ok, result = daemon._do_suggest_inside_joke(
                thought, 'suggest_inside_joke:turn anchor joke')
        self.assertTrue(ok, result)
        self.assertEqual(len(rs.inside_jokes), 1)
        joke = next(iter(rs.inside_jokes.values()))
        self.assertEqual(joke.birth_turn_id, 'turn_rel_joke_001')

    def test_propose_protocol_sets_learned_from_turn_id(self):
        from jarvis_utils import TraceContext
        daemon, rs = self._make_daemon_with_rs()
        thought = self._thought(category='B')
        with TraceContext.captured_turn('turn_rel_proto_001'):
            ok, result = daemon._do_propose_protocol(
                thought,
                'propose_protocol:Always preserve relational birth turn anchors',
            )
        self.assertTrue(ok, result)
        self.assertEqual(len(rs.unspoken_protocols), 1)
        proto = next(iter(rs.unspoken_protocols.values()))
        self.assertEqual(proto.learned_from_turn_id, 'turn_rel_proto_001')


if __name__ == '__main__':
    unittest.main(verbosity=2)
