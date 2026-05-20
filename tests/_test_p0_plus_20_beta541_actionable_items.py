# -*- coding: utf-8 -*-
"""β.5.41-B — ActionableItems backend abstraction tests."""

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestBeta541ABackendStructure(unittest.TestCase):
    def test_imports(self):
        import jarvis_actionable_items as ai
        for sym in ('ActionableItem', 'get_all_sir_actionable_items',
                     'get_category_counts', 'find_item_by_id',
                     'mark_sir_acked', 'get_recent_corrections',
                     '_log_correction'):
            self.assertTrue(hasattr(ai, sym), f'必须有 {sym}')

    def test_actionable_item_schema(self):
        from jarvis_actionable_items import ActionableItem
        it = ActionableItem(id='test', category='cat')
        d = it.to_dict()
        # 必有字段
        for k in ('id', 'category', 'subcategory', 'state', 'preview', 'fields',
                  'impact_if_modified', 'impact_if_deleted', 'source_file',
                  'source_path', 'created_at', 'last_used_at', 'use_count',
                  'auto_proposed', 'proposed_by', 'sir_acked'):
            self.assertIn(k, d, f'schema 必须含 {k}')


class TestBeta541AGetAllItems(unittest.TestCase):
    def test_get_all_returns_list(self):
        from jarvis_actionable_items import get_all_sir_actionable_items
        items = get_all_sir_actionable_items()
        self.assertIsInstance(items, list)

    def test_items_have_required_fields(self):
        from jarvis_actionable_items import get_all_sir_actionable_items
        items = get_all_sir_actionable_items()
        for it in items:
            self.assertTrue(it.id, 'id 非空')
            self.assertTrue(it.category, 'category 非空')
            self.assertTrue(it.preview, 'preview 非空')
            self.assertTrue(it.source_file, 'source_file 非空')
            self.assertIsInstance(it.fields, dict)
            self.assertIsInstance(it.auto_proposed, bool)
            self.assertIsInstance(it.sir_acked, bool)

    def test_filter_by_category(self):
        from jarvis_actionable_items import get_all_sir_actionable_items
        items = get_all_sir_actionable_items(filter_category='inside_joke')
        for it in items:
            self.assertEqual(it.category, 'inside_joke')

    def test_filter_by_state(self):
        from jarvis_actionable_items import get_all_sir_actionable_items
        items = get_all_sir_actionable_items(filter_state='review')
        for it in items:
            self.assertEqual(it.state, 'review')


class TestBeta541AGetCategoryCounts(unittest.TestCase):
    def test_counts_returns_dict(self):
        from jarvis_actionable_items import get_category_counts
        counts = get_category_counts()
        self.assertIsInstance(counts, dict)
        for cat, st in counts.items():
            self.assertIsInstance(cat, str)
            self.assertIsInstance(st, dict)
            for state, n in st.items():
                self.assertGreaterEqual(n, 0)


class TestBeta541ACategoriesCoverage(unittest.TestCase):
    """21 类 sub-extractors 都必须能跑 (不一定有数据)."""

    def test_all_extractors_callable(self):
        import jarvis_actionable_items as ai
        for ext in ai._ALL_EXTRACTORS:
            self.assertTrue(callable(ext))

    def test_each_extractor_returns_list(self):
        import jarvis_actionable_items as ai
        for ext in ai._ALL_EXTRACTORS:
            result = ext({})  # empty ack state
            self.assertIsInstance(result, list, f'{ext.__name__} 必须返 list')


class TestBeta541AAckTracking(unittest.TestCase):
    def setUp(self):
        # 用临时路径避免污染
        import tempfile
        import jarvis_actionable_items as ai
        self.tmp = tempfile.mkdtemp()
        self._orig_mem = ai.MEM
        ai.MEM = self.tmp

    def tearDown(self):
        import jarvis_actionable_items as ai
        ai.MEM = self._orig_mem

    def test_mark_and_check_ack(self):
        from jarvis_actionable_items import mark_sir_acked, _is_acked, _load_ack_state
        self.assertFalse(_is_acked('test_item_1'))
        self.assertTrue(mark_sir_acked('test_item_1'))
        self.assertTrue(_is_acked('test_item_1'))


class TestBeta541ACorrectionsLog(unittest.TestCase):
    def setUp(self):
        import tempfile
        import jarvis_actionable_items as ai
        self.tmp = tempfile.mkdtemp()
        self._orig_mem = ai.MEM
        ai.MEM = self.tmp

    def tearDown(self):
        import jarvis_actionable_items as ai
        ai.MEM = self._orig_mem

    def test_log_and_read(self):
        from jarvis_actionable_items import (
            ActionableItem, _log_correction, get_recent_corrections
        )
        item = ActionableItem(
            id='joke_test', category='inside_joke',
            source_file='memory_pool/relational_state.json',
            source_path='inside_jokes.joke_test',
        )
        _log_correction('modify', item, old={'phrase': 'old'}, new={'phrase': 'new'})
        _log_correction('delete', item, reason='不需要')
        entries = get_recent_corrections(hours=24)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['action'], 'modify')
        self.assertEqual(entries[1]['action'], 'delete')


if __name__ == '__main__':
    unittest.main()
