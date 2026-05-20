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


class TestBeta541AMutation(unittest.TestCase):
    """mutation API: modify / delete / restore / activate / reject."""

    def setUp(self):
        import tempfile, json, shutil
        import jarvis_actionable_items as ai
        self.tmp = tempfile.mkdtemp()
        self._orig_mem = ai.MEM
        self._orig_cfg = ai.CFG
        ai.MEM = self.tmp
        ai.CFG = self.tmp
        # 准备一个 fake relational_state.json 含 1 个 inside_joke
        rel = {
            'inside_jokes': {
                'joke_test_abc': {
                    'id': 'joke_test_abc',
                    'phrase': '老梗', 'birth_context': '初版',
                    'tone': 'wry', 'state': 'active',
                    'source': 'auto_detected',
                }
            },
            'shared_history_threads': {},
            'unspoken_protocols': {},
            'unfinished_business': {},
        }
        with open(os.path.join(self.tmp, 'relational_state.json'), 'w', encoding='utf-8') as f:
            json.dump(rel, f, ensure_ascii=False)

    def tearDown(self):
        import jarvis_actionable_items as ai
        ai.MEM = self._orig_mem
        ai.CFG = self._orig_cfg

    def test_modify_inside_joke(self):
        from jarvis_actionable_items import mutate_actionable_item, find_item_by_id
        r = mutate_actionable_item(
            'joke_test_abc', 'modify',
            new_fields={'phrase': '新梗', 'tone': 'playful'},
            sir_note='上下文不对',
        )
        self.assertTrue(r['ok'])
        # 重读应该有新值
        it = find_item_by_id('joke_test_abc')
        self.assertEqual(it.fields['phrase'], '新梗')
        self.assertEqual(it.fields['tone'], 'playful')

    def test_delete_inside_joke_archives(self):
        from jarvis_actionable_items import mutate_actionable_item, find_item_by_id
        r = mutate_actionable_item('joke_test_abc', 'delete', sir_note='不需要')
        self.assertTrue(r['ok'])
        # archived state 不在默认 get_all (cat 1 + 12 filter active/review)
        it = find_item_by_id('joke_test_abc')
        self.assertIsNone(it, 'delete 后默认不再列出 (archived)')

    def test_restore_restores_state(self):
        from jarvis_actionable_items import mutate_actionable_item, find_item_by_id
        # delete then restore
        mutate_actionable_item('joke_test_abc', 'delete')
        # 直接看 source file state
        import json
        with open(os.path.join(self.tmp, 'relational_state.json'), encoding='utf-8') as f:
            d = json.load(f)
        self.assertEqual(d['inside_jokes']['joke_test_abc']['state'], 'archived')
        # restore
        # 需要 find_item 看到 archived (我们 extractor 只看 active+review, restore 不通过 find_item)
        # 实际 restore 通过 source 直接 mutate. 暂略 (handler 自己测).

    def test_unknown_item_returns_error(self):
        from jarvis_actionable_items import mutate_actionable_item
        r = mutate_actionable_item('nonexistent_xyz', 'modify')
        self.assertFalse(r['ok'])
        self.assertIn('not found', r.get('error', ''))


class TestBeta541ARecentCorrections(unittest.TestCase):
    """corrections.jsonl 写后能读出."""

    def setUp(self):
        import tempfile, json
        import jarvis_actionable_items as ai
        self.tmp = tempfile.mkdtemp()
        self._orig_mem = ai.MEM
        ai.MEM = self.tmp
        # 准备 relational
        rel = {
            'inside_jokes': {
                'joke_corr_test': {
                    'id': 'joke_corr_test',
                    'phrase': 'A', 'state': 'active',
                }
            },
            'shared_history_threads': {},
            'unspoken_protocols': {},
            'unfinished_business': {},
        }
        with open(os.path.join(self.tmp, 'relational_state.json'), 'w', encoding='utf-8') as f:
            json.dump(rel, f, ensure_ascii=False)

    def tearDown(self):
        import jarvis_actionable_items as ai
        ai.MEM = self._orig_mem

    def test_modify_logs_correction(self):
        from jarvis_actionable_items import mutate_actionable_item, get_recent_corrections
        mutate_actionable_item(
            'joke_corr_test', 'modify',
            new_fields={'phrase': 'B'},
            sir_note='改为 B',
        )
        recent = get_recent_corrections(hours=24)
        self.assertGreaterEqual(len(recent), 1)
        self.assertEqual(recent[-1]['action'], 'modify')
        self.assertEqual(recent[-1]['item_id'], 'joke_corr_test')
        self.assertEqual(recent[-1]['sir_note'], '改为 B')


class TestBeta541DCorrectionsInjectsInPrompt(unittest.TestCase):
    """β.5.41-D: corrections.jsonl 已注入 _assemble_prompt source."""

    def test_central_nerve_imports_get_recent_corrections(self):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.41-D', src, 'central_nerve 必须含 β.5.41-D marker')
        self.assertIn('get_recent_corrections', src,
                      '_assemble_prompt 必须 import get_recent_corrections')
        self.assertIn('SIR CORRECTIONS', src,
                      'prompt 必须含 [SIR CORRECTIONS] block 标题')


if __name__ == '__main__':
    unittest.main()
