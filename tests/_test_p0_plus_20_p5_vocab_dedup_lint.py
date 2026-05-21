# -*- coding: utf-8 -*-
"""[Gap-Z4 / β.5.46-fix9 / 2026-05-22 00:05] Vocab Dedup Lint 测试."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestExtractKeywords(unittest.TestCase):

    def test_extract_from_simple_list(self):
        from scripts.vocab_dedup_lint import _extract_keywords_from_obj
        kws = set()
        _extract_keywords_from_obj({'words': ['hello', 'world']}, kws)
        self.assertIn('hello', kws)
        self.assertIn('world', kws)

    def test_skip_meta_fields(self):
        from scripts.vocab_dedup_lint import _extract_keywords_from_obj
        kws = set()
        _extract_keywords_from_obj({'_doc': 'meta', '_history': ['ignore'], 'real': ['kw']}, kws)
        self.assertIn('kw', kws)
        self.assertNotIn('meta', kws)
        self.assertNotIn('ignore', kws)

    def test_skip_too_short_or_long(self):
        from scripts.vocab_dedup_lint import _extract_keywords_from_obj
        kws = set()
        _extract_keywords_from_obj({'kws': ['x', 'a' * 250, 'normal']}, kws)
        self.assertIn('normal', kws)
        self.assertNotIn('x', kws)


class TestScan(unittest.TestCase):

    def test_scan_returns_dict(self):
        from scripts.vocab_dedup_lint import scan_vocab_files
        result = scan_vocab_files()
        self.assertIsInstance(result, dict)
        self.assertGreater(len(result), 0, '应找到至少 1 个 vocab')


class TestFindDuplicates(unittest.TestCase):

    def test_find_duplicates_basic(self):
        from scripts.vocab_dedup_lint import find_duplicates
        vocab_data = {
            'a.json': {'shared', 'unique_a'},
            'b.json': {'shared', 'unique_b'},
            'c.json': {'shared', 'unique_c'},
        }
        dups = find_duplicates(vocab_data, threshold=2)
        self.assertIn('shared', dups)
        self.assertEqual(len(dups['shared']), 3)

    def test_threshold_filters(self):
        from scripts.vocab_dedup_lint import find_duplicates
        vocab_data = {
            'a.json': {'in_two'},
            'b.json': {'in_two'},
            'c.json': {'in_three'},
            'd.json': {'in_three'},
            'e.json': {'in_three'},
        }
        # threshold=3 → 仅 in_three
        dups = find_duplicates(vocab_data, threshold=3)
        self.assertIn('in_three', dups)
        self.assertNotIn('in_two', dups)


if __name__ == '__main__':
    unittest.main()
