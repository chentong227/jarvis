# -*- coding: utf-8 -*-
"""[fix30 / Sir 2026-05-28 16:00 H.4] concern 两层耦合 strong-gate regression.

concern = Jarvis 视角 "I'm watching", Sir 真意 image 1 严格把关:
  强 ACT: source trusted (sir_added/sir_confirmed) /
          Sir 抱怨 vocab + watch token overlap
  强 REJ: watch trivial / why 缺

测试覆盖 (11 个):
  L1 vocab load enabled + disabled
  L2 强 ACT-(a) source=sir_added → activate (即使 watch trivial 也优先 trust)
  L3 强 ACT-(b) Sir 抱怨 vocab 命中 + watch overlap → activate
  L4 强 REJ-(a) watch 词数 < min → reject
  L5 强 REJ-(b) why 缺/太短 → reject
  L6 watch empty → reject
  L7 含 imperative-like watch, 无 STM 抱怨, 无 trusted source → None (LLM fallback)
  L8 中文 Sir 抱怨 vocab 命中 (焦虑/烦/累)
  L9 _evaluate_and_decide bypass LLM (强 ACT trusted)
  L10 _evaluate_and_decide bypass LLM (强 REJ trivial watch)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_vocab_file(tmpdir: str, **overrides) -> str:
    data = {
        'enabled': True,
        'sir_complaint_keywords': [
            'anxious', 'worried', 'stressed', 'frustrated', 'overwhelmed',
            'tired of', '焦虑', '担心', '烦', '累', '受不了',
        ],
        'trusted_sources': ['sir_added', 'sir_confirmed'],
        'min_watch_token_overlap': 0.3,
        'min_watch_words': 3,
        'min_why_words': 3,
        'stm_lookback_turns': 10,
        'log_decisions': False,
    }
    data.update(overrides)
    path = os.path.join(tmpdir, 'concern_vocab.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _make_daemon(vocab_path: str):
    from jarvis_auto_arbiter import AutoArbiterDaemon
    AutoArbiterDaemon.CONCERN_VOCAB_PATH = vocab_path
    AutoArbiterDaemon._CONCERN_VOCAB_CACHE = {
        'data': None, 'mtime': 0.0, 'checked_at': 0.0,
    }
    return AutoArbiterDaemon(key_router=None)


def _make_concern(what: str, why: str = '', source: str = 'discovered'):
    e = MagicMock()
    e.what_i_watch = what
    e.why_i_care = why
    e.source = source
    e.id = f"c_{int(time.time() * 1000) % 100000:05d}"
    e.created_at = time.time()
    e.state = 'review'
    e.severity = 0.5
    return e


# ==========================================================================
# L1: vocab load
# ==========================================================================
class TestL1VocabLoad(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix30_l1_')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_enabled(self):
        d = _make_daemon(_make_vocab_file(self.tmp))
        v = d._load_concern_vocab()
        self.assertTrue(v.get('enabled'))
        self.assertIn('anxious', v.get('sir_complaint_keywords'))

    def test_disabled_skips_gate(self):
        d = _make_daemon(_make_vocab_file(self.tmp, enabled=False))
        e = _make_concern('Sir interview anxiety', why='Sir mentioned stress')
        decision, _ = d._concern_strong_gate(e, {'stm': []})
        self.assertIsNone(decision)


# ==========================================================================
# L2: 强 ACT-(a) trusted source
# ==========================================================================
class TestL2StrongActTrustedSource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix30_l2_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sir_added_activates(self):
        e = _make_concern('Sir focus', why='requested', source='sir_added')
        decision, reason = self.d._concern_strong_gate(e, {'stm': []})
        self.assertEqual(decision, 'activate')
        self.assertIn('trusted_source:sir_added', reason)

    def test_sir_confirmed_activates(self):
        e = _make_concern('Sir health', why='past', source='sir_confirmed')
        decision, reason = self.d._concern_strong_gate(e, {'stm': []})
        self.assertEqual(decision, 'activate')
        self.assertIn('trusted_source:sir_confirmed', reason)


# ==========================================================================
# L3: 强 ACT-(b) Sir 抱怨 + watch overlap
# ==========================================================================
class TestL3StrongActComplaintOverlap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix30_l3_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_complaint_kw_plus_overlap_activates(self):
        # watch tokens: {sir, interview, anxiety, prep} 4 tokens
        # Sir text 含 'anxious' (complaint) + 2/4 overlap (interview, prep) = 0.5 >= 0.3
        e = _make_concern(
            'Sir interview anxiety prep',
            why='Sir mentioned interview stress recently',
            source='discovered',
        )
        ev = {'stm': [
            {'user': "i'm so anxious about the interview prep tomorrow",
             'jarvis': 'noted'},
        ]}
        decision, reason = self.d._concern_strong_gate(e, ev)
        self.assertEqual(decision, 'activate')
        self.assertIn('sir_complaint+watch_overlap', reason)


# ==========================================================================
# L4-L6: 强 REJ
# ==========================================================================
class TestL4StrongRejTrivialWatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix30_l4_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_short_watch_rejects(self):
        e = _make_concern('Sir mood', why='Sir said so today')  # 2 < 3
        decision, reason = self.d._concern_strong_gate(e, {'stm': []})
        self.assertEqual(decision, 'reject')
        self.assertIn('trivial_watch', reason)


class TestL5StrongRejMissingWhy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix30_l5_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_why_rejects(self):
        e = _make_concern('Sir interview preparation balance', why='')
        decision, reason = self.d._concern_strong_gate(e, {'stm': []})
        self.assertEqual(decision, 'reject')
        self.assertIn('missing_why', reason)

    def test_short_why_rejects(self):
        e = _make_concern(
            'Sir interview preparation balance', why='just because')  # 2 words
        decision, reason = self.d._concern_strong_gate(e, {'stm': []})
        self.assertEqual(decision, 'reject')
        self.assertIn('missing_why', reason)


class TestL6EmptyWatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix30_l6_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_watch_rejects(self):
        e = _make_concern('  ', why='whatever')
        decision, reason = self.d._concern_strong_gate(e, {'stm': []})
        self.assertEqual(decision, 'reject')
        self.assertEqual(reason, 'empty_watch')


# ==========================================================================
# L7: fall to LLM
# ==========================================================================
class TestL7FallthroughLLM(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix30_l7_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_none_no_strong(self):
        e = _make_concern(
            'Sir nightly screen time exposure',
            why='Sir prefers less blue light evenings',
            source='discovered',
        )
        ev = {'stm': [
            {'user': 'tomorrow let us discuss the new feature',
             'jarvis': 'noted'}
        ]}
        decision, reason = self.d._concern_strong_gate(e, ev)
        self.assertIsNone(decision)
        self.assertEqual(reason, 'no_strong_signal_fallback_to_llm')


# ==========================================================================
# L8: 中文 complaint
# ==========================================================================
class TestL8ChineseComplaint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix30_l8_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_chinese_complaint_activates(self):
        # 中文 watch: '面试 准备 焦虑' tokens {面试, 准备, 焦虑}
        # Sir 含 '焦虑' (complaint) + 2/3 overlap = 0.67 >= 0.3
        e = _make_concern(
            '面试 准备 焦虑',
            why='Sir 多次 提到 面试 压力',
            source='discovered',
        )
        ev = {'stm': [
            {'user': '面试 准备 好焦虑啊', 'jarvis': 'noted'}
        ]}
        decision, reason = self.d._concern_strong_gate(e, ev)
        self.assertEqual(decision, 'activate')
        self.assertIn('sir_complaint+watch_overlap', reason)


# ==========================================================================
# L9-L10: _evaluate_and_decide 真集成
# ==========================================================================
class TestL9L10EvaluateIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix30_l9_')
        from jarvis_auto_arbiter import AutoArbiterDaemon
        self._saved_persist = AutoArbiterDaemon.PERSIST_PATH
        AutoArbiterDaemon.PERSIST_PATH = os.path.join(self.tmp, 'log.jsonl')
        self._saved_calib = AutoArbiterDaemon.CALIBRATION_PATH
        AutoArbiterDaemon.CALIBRATION_PATH = os.path.join(self.tmp, 'cal.json')
        self.d = _make_daemon(_make_vocab_file(self.tmp))
        self.d.concerns_ledger = MagicMock()
        self.d.concerns_ledger.activate = MagicMock(return_value=True)
        self.d.concerns_ledger.reject = MagicMock(return_value=True)
        self.d.concerns_ledger.concerns = {}

    def tearDown(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        AutoArbiterDaemon.PERSIST_PATH = self._saved_persist
        AutoArbiterDaemon.CALIBRATION_PATH = self._saved_calib
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_strong_act_trusted_source_bypasses_llm(self):
        e = _make_concern(
            'Sir focus during interview prep',
            why='Sir explicitly asked',
            source='sir_added',
        )
        self.d.nerve = MagicMock()
        self.d.nerve.short_term_memory = []
        item = {'kind': 'concern', 'entity': e, 'preview': e.what_i_watch}
        with patch.object(self.d, '_llm_evaluate') as mock_llm:
            self.d._evaluate_and_decide(item)
        mock_llm.assert_not_called()
        self.d.concerns_ledger.activate.assert_called_once()
        self.assertEqual(self.d._decisions[0].decision, 'activate')

    def test_strong_rej_trivial_watch_bypasses_llm(self):
        e = _make_concern('Sir ok', why='note')  # 2 words trivial
        self.d.nerve = MagicMock()
        self.d.nerve.short_term_memory = []
        item = {'kind': 'concern', 'entity': e, 'preview': e.what_i_watch}
        with patch.object(self.d, '_llm_evaluate') as mock_llm:
            self.d._evaluate_and_decide(item)
        mock_llm.assert_not_called()
        self.d.concerns_ledger.reject.assert_called_once()
        self.assertEqual(self.d._decisions[0].decision, 'reject')


if __name__ == '__main__':
    unittest.main(verbosity=2)
