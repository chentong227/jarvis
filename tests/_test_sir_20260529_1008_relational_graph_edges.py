# -*- coding: utf-8 -*-
"""[#4b / Sir 2026-05-29] Relational graph edge tests."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_relational import (  # noqa: E402
    InsideJoke,
    RelationalEdge,
    RelationalStateStore,
    SharedHistoryThread,
)


class TestRelationalGraphEdges(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode='w', delete=False,
                                               suffix='.json')
        self.tmp.close()
        self.review_path = self.tmp.name + '.review.json'
        self.store = RelationalStateStore(
            persist_path=self.tmp.name,
            review_path=self.review_path,
        )

    def tearDown(self):
        for p in (self.tmp.name, self.review_path):
            try:
                os.unlink(p)
            except Exception:
                pass

    def test_add_list_query_archive_edge(self):
        e = RelationalEdge(
            id='edge_1',
            from_kind='inside_joke', from_id='j1',
            to_kind='thread', to_id='t1',
            relation_type='born_from', weight=1.5,
        )
        self.assertTrue(self.store.add_edge(e))
        self.assertFalse(self.store.add_edge(e))
        self.assertEqual(self.store.get_edge('edge_1').weight, 1.0)
        self.assertEqual(len(self.store.list_edges_for('inside_joke', 'j1')), 1)
        self.assertEqual(len(self.store.list_edges_for('thread', 't1')), 1)

        self.assertTrue(self.store.archive_edge('edge_1'))
        self.assertEqual(self.store.list_edges(), [])
        self.assertEqual(len(self.store.list_edges(include_archived=True)), 1)

    def test_persist_load_edges_round_trip(self):
        self.store.add_edge(RelationalEdge(
            id='edge_rt',
            from_kind='protocol', from_id='p1',
            to_kind='inside_joke', to_id='j1',
            relation_type='reinforces', weight=0.8,
            evidence_turn_id='turn_edge_001', note='Protocol reinforces the joke.',
        ))
        self.assertTrue(self.store.persist())

        loaded = RelationalStateStore(
            persist_path=self.tmp.name,
            review_path=self.review_path,
        )
        stats = loaded.load()
        self.assertEqual(stats, {'jokes': 0, 'protocols': 0, 'ub': 0, 'threads': 0})
        self.assertEqual(len(loaded.relational_edges), 1)
        edge = loaded.get_edge('edge_rt')
        self.assertIsNotNone(edge)
        self.assertEqual(edge.relation_type, 'reinforces')
        self.assertEqual(edge.evidence_turn_id, 'turn_edge_001')
        self.assertEqual(edge.note, 'Protocol reinforces the joke.')

    def test_prompt_does_not_render_edges_by_default(self):
        self.store.add_inside_joke(InsideJoke(id='j1', phrase='地基打牢'))
        self.store.add_thread(SharedHistoryThread(id='t1', title='Closure work'))
        self.store.add_edge(RelationalEdge(
            id='edge_hidden',
            from_kind='inside_joke', from_id='j1',
            to_kind='thread', to_id='t1',
            relation_type='symbolizes', weight=0.9,
        ))
        block = self.store.to_prompt_block(
            top_jokes=0, top_unfinished=0, top_threads=0,
            top_pending_review=0,
        )
        self.assertEqual(block, '')

    def test_prompt_renders_edges_when_enabled_and_truncates(self):
        self.store.add_edge(RelationalEdge(
            id='edge_visible',
            from_kind='inside_joke', from_id='j1',
            to_kind='thread', to_id='t1',
            relation_type='symbolizes', weight=0.9,
            note='This edge connects a phrase to the closure thread.',
        ))
        block = self.store.to_prompt_block(
            top_jokes=0, top_unfinished=0, top_threads=0,
            top_pending_review=0, top_edges=1, max_chars=180,
        )
        self.assertIn('[RELATIONAL LINKS', block)
        self.assertIn('inside_joke:j1 --symbolizes/0.90--> thread:t1', block)
        self.assertLessEqual(len(block), 180)

    def test_dump_human_includes_edges_count(self):
        self.store.add_edge(RelationalEdge(
            id='edge_dump',
            from_kind='protocol', from_id='p1',
            to_kind='thread', to_id='t1',
            relation_type='belongs_to', weight=0.6,
        ))
        dump = self.store.dump_human()
        self.assertIn('edges=1', dump)
        self.assertIn('[RELATIONAL EDGES]', dump)
        self.assertIn('edge_dump', dump)


if __name__ == '__main__':
    unittest.main(verbosity=2)
