# -*- coding: utf-8 -*-
"""[P5-fix35 / 2026-05-23 11:18] BUG#6 vocab base + BUG#15 PreFlight topic tracker

BUG#6 — 3 vocab 文件去重:
  抽 _base_correction_vocab.json + _base_dismiss_vocab.json, 3 specific vocab
  自动 union base. Sir 加新公共词只需改 base 一处.

BUG#15 — PreFlight 重复 unsolicited callback:
  central_nerve 加 PreFlightTopicTracker block — 查近 5min preflight_verdict
  含 UNSOLICITED 类 issue → 提取 draft_excerpt 注入 prompt "别重复".
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ============================================================
# BUG#6 — base vocab union
# ============================================================

class TestBug6BaseVocab(unittest.TestCase):
    """_base_*_vocab.json 存在 + loader union 后 3 specific vocab 含 base 词."""

    def test_base_correction_file_exists(self):
        path = os.path.join(ROOT, 'memory_pool', '_base_correction_vocab.json')
        self.assertTrue(os.path.exists(path),
                          '_base_correction_vocab.json 必须存在 (准则 6 持久化)')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('patterns', data)
        self.assertGreater(len(data['patterns']), 20)

    def test_base_dismiss_file_exists(self):
        path = os.path.join(ROOT, 'memory_pool', '_base_dismiss_vocab.json')
        self.assertTrue(os.path.exists(path),
                          '_base_dismiss_vocab.json 必须存在 (准则 6 持久化)')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('patterns', data)
        self.assertGreater(len(data['patterns']), 10)

    def test_correction_dispatcher_unions_both_bases(self):
        """correction_dispatcher 是最广 vocab — 应含两个 base."""
        import jarvis_directives as jd
        jd._CORRECTION_DISPATCHER_CACHE = None
        jd._CORRECTION_DISPATCHER_MTIME = 0.0
        patterns = jd.get_correction_dispatcher_patterns()
        # base_correction 典型词
        self.assertIn('其实', patterns)
        self.assertIn('actually', patterns)
        # base_dismiss 典型词
        self.assertIn('不用再提', patterns)
        self.assertIn('stop bringing it up', patterns)
        # specific 词
        self.assertIn('改成', patterns)

    def test_memory_correction_unions_correction_base(self):
        """memory_correction vocab 应含 _base_correction 但 NOT _base_dismiss."""
        import jarvis_directives as jd
        jd._MEMORY_CORRECTION_CACHE = None
        jd._MEMORY_CORRECTION_MTIME = 0.0
        patterns = jd.get_memory_correction_patterns()
        # base_correction
        self.assertIn('其实', patterns)
        self.assertIn('actually', patterns)
        # specific
        self.assertIn('我没', patterns)
        # NOT in dismiss base
        self.assertNotIn('drop it', patterns)
        self.assertNotIn('let it go', patterns)

    def test_concern_dismiss_unions_dismiss_base(self):
        """concern_dismiss 应含 _base_dismiss 但 NOT _base_correction."""
        import jarvis_directives as jd
        jd._CONCERN_DISMISS_CACHE = None
        jd._CONCERN_DISMISS_MTIME = 0.0
        patterns = jd.get_concern_dismiss_patterns()
        # base_dismiss
        self.assertIn('不用再提', patterns)
        self.assertIn('stop bringing it up', patterns)
        # specific
        self.assertIn('别管了', patterns)
        # NOT in correction base
        self.assertNotIn('其实', patterns)
        self.assertNotIn('actually', patterns)

    def test_no_overlap_in_specific_vocabs(self):
        """specific vocab 文件应**不含** base 词 (Sir 加 base 词只需改 base)."""
        with open(os.path.join(ROOT, 'memory_pool',
                                  'correction_dispatcher_vocab.json'),
                  'r', encoding='utf-8') as f:
            corr = json.load(f).get('patterns', [])
        with open(os.path.join(ROOT, 'memory_pool',
                                  'concern_dismiss_vocab.json'),
                  'r', encoding='utf-8') as f:
            dism = json.load(f).get('patterns', [])
        with open(os.path.join(ROOT, 'memory_pool',
                                  '_base_correction_vocab.json'),
                  'r', encoding='utf-8') as f:
            base_corr = set(p.lower() for p in json.load(f).get('patterns', []))
        with open(os.path.join(ROOT, 'memory_pool',
                                  '_base_dismiss_vocab.json'),
                  'r', encoding='utf-8') as f:
            base_dism = set(p.lower() for p in json.load(f).get('patterns', []))
        corr_set = set(p.lower() for p in corr)
        dism_set = set(p.lower() for p in dism)
        # correction_dispatcher should not duplicate base
        corr_dup = corr_set & (base_corr | base_dism)
        self.assertEqual(
            len(corr_dup), 0,
            f"correction_dispatcher 不应含 base 词 (Sir 改 base 自动生效): "
            f"重复词={list(corr_dup)[:5]}")
        # concern_dismiss should not duplicate dismiss base
        dism_dup = dism_set & base_dism
        self.assertEqual(
            len(dism_dup), 0,
            f"concern_dismiss 不应含 base dismiss 词: 重复={list(dism_dup)[:5]}")


# ============================================================
# BUG#15 — PreFlight Topic Tracker block in central_nerve
# ============================================================

class TestBug15PreFlightTopicTracker(unittest.TestCase):
    """central_nerve 应有 PreFlightTopicTracker block 查 recent unsolicited issues."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'),
                   'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_topic_tracker_block_present(self):
        self.assertIn('PreFlightTopicTracker', self.src,
                       'central_nerve 应有 PreFlight Topic Tracker 注入逻辑')

    def test_queries_preflight_verdict_events(self):
        # 找 BUG#15 block 段
        idx = self.src.find('P5-fix35-BUG#15')
        self.assertGreater(idx, 0)
        snippet = self.src[idx:idx + 3000]
        self.assertIn("'preflight_verdict'", snippet)
        self.assertIn('recent_events', snippet)
        self.assertIn('UNSOLICITED', snippet)

    def test_extracts_draft_excerpt(self):
        idx = self.src.find('P5-fix35-BUG#15')
        snippet = self.src[idx:idx + 3000]
        self.assertIn('draft_excerpt', snippet)

    def test_injects_into_system_alert(self):
        idx = self.src.find('P5-fix35-BUG#15')
        snippet = self.src[idx:idx + 3000]
        # Should prepend block to system_alert_text
        self.assertIn('system_alert_text', snippet)
        self.assertIn('别重复', snippet)


if __name__ == '__main__':
    unittest.main()
