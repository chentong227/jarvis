# -*- coding: utf-8 -*-
"""[fix27 / Sir 2026-05-28 15:37 H.2] thread 两层耦合 strong-gate regression.

H.2 (随 H.1 inside_joke 同 pattern):
  - vocab memory_pool/auto_arbiter_thread_vocab.json 持久化
  - _thread_strong_gate(): 强 ACT / 强 REJ deterministic bypass LLM
    强 ACT: Sir 复述 title (token overlap) / Sir milestone vocab in STM
    强 REJ: title trivial (词数 < min / 字数 > max) / detail 太短
  - _evaluate_and_decide 加 thread pre-check (类 inside_joke)

测试覆盖 (9 个):
  L1 vocab load OK + enabled
  L2 强 ACT-(a) Sir substring 复述 title → activate
  L3 强 ACT-(a') Sir token overlap 复述 title → activate
  L4 强 ACT-(b) Sir milestone vocab in STM → activate
  L5 强 REJ-(a) title 词数 < min → reject
  L6 强 REJ-(b) detail 太短 → reject
  L7 强 REJ-(c) title 字数 > max → reject
  L8 无强信号 → None (走 LLM fallback)
  L9 _evaluate_and_decide 真集成 (bypass LLM 真生效)
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
        'milestone_keywords': ['shipped', 'launched', 'completed',
                                  '完成', '上线', '发布'],
        'min_title_token_overlap': 0.5,
        'min_title_words': 2,
        'max_title_chars': 80,
        'min_detail_chars': 10,
        'stm_lookback_turns': 10,
        'log_decisions': False,
    }
    data.update(overrides)
    path = os.path.join(tmpdir, 'thread_vocab.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _make_daemon(vocab_path: str):
    from jarvis_auto_arbiter import AutoArbiterDaemon
    AutoArbiterDaemon.THREAD_VOCAB_PATH = vocab_path
    AutoArbiterDaemon._THREAD_VOCAB_CACHE = {
        'data': None, 'mtime': 0.0, 'checked_at': 0.0,
    }
    return AutoArbiterDaemon(key_router=None)


def _make_entity(title: str, detail: str = 'a moderately long detail line'):
    e = MagicMock()
    e.title = title
    e.detail = detail
    e.id = f"t_{int(time.time() * 1000) % 100000:05d}"
    e.created_at = time.time()
    e.source = 'test'
    e.state = 'review'
    return e


# ==========================================================================
# L1: vocab load
# ==========================================================================
class TestL1VocabLoad(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix27_l1_')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_enabled(self):
        path = _make_vocab_file(self.tmp)
        d = _make_daemon(path)
        v = d._load_thread_vocab()
        self.assertTrue(v.get('enabled'))
        self.assertIn('shipped', v.get('milestone_keywords'))

    def test_disabled_skips_gate(self):
        path = _make_vocab_file(self.tmp, enabled=False)
        d = _make_daemon(path)
        e = _make_entity('Built and deployed J.A.R.V.I.S.')
        decision, reason = d._thread_strong_gate(e, {'stm': []})
        self.assertIsNone(decision)
        self.assertEqual(reason, 'vocab_disabled')


# ==========================================================================
# L2-L4: 强 ACT 3 信号
# ==========================================================================
class TestL2StrongActSubstring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix27_l2_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_substring_activates(self):
        e = _make_entity('built and deployed jarvis')
        ev = {'stm': [
            {'user': 'finally built and deployed jarvis last night',
             'jarvis': 'noted'}
        ]}
        decision, reason = self.d._thread_strong_gate(e, ev)
        self.assertEqual(decision, 'activate')
        self.assertIn('sir_quoted_title_substring', reason)


class TestL3StrongActTokenOverlap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix27_l3_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_token_overlap_activates(self):
        # title tokens: {built, deployed, jarvis} 3 tokens
        # Sir 2/3 (deployed, jarvis) = 0.67 >= 0.5
        e = _make_entity('built deployed jarvis')
        ev = {'stm': [
            {'user': 'i deployed the jarvis project yesterday',
             'jarvis': 'noted'}
        ]}
        decision, reason = self.d._thread_strong_gate(e, ev)
        self.assertEqual(decision, 'activate')
        self.assertIn('sir_quoted_title_token_overlap', reason)


class TestL4StrongActMilestoneVocab(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix27_l4_')
        # 加大 overlap 让 ACT-a 不走 (test 隔离)
        self.d = _make_daemon(
            _make_vocab_file(self.tmp, min_title_token_overlap=0.99)
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_milestone_vocab_activates(self):
        e = _make_entity('xyz unrelated title nonmatching')
        ev = {'stm': [
            {'user': 'we shipped the new feature today',
             'jarvis': 'noted'}
        ]}
        decision, reason = self.d._thread_strong_gate(e, ev)
        self.assertEqual(decision, 'activate')
        self.assertIn('sir_milestone_kw', reason)


# ==========================================================================
# L5-L7: 强 REJ 3 信号
# ==========================================================================
class TestL5StrongRejTrivialWords(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix27_l5_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_short_title_rejects(self):
        e = _make_entity('hi')  # 1 word < min 2
        decision, reason = self.d._thread_strong_gate(e, {'stm': []})
        self.assertEqual(decision, 'reject')
        self.assertIn('trivial_title', reason)


class TestL6StrongRejTrivialDetail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix27_l6_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_short_detail_rejects(self):
        e = _make_entity('proper title here', detail='ok')  # 2 < 10
        decision, reason = self.d._thread_strong_gate(e, {'stm': []})
        self.assertEqual(decision, 'reject')
        self.assertIn('no_detail', reason)


class TestL7StrongRejTitleTooLong(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix27_l7_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_long_title_rejects(self):
        e = _make_entity('a ' * 50)  # > 80 chars
        decision, reason = self.d._thread_strong_gate(e, {'stm': []})
        self.assertEqual(decision, 'reject')
        self.assertIn('trivial_title', reason)


# ==========================================================================
# L8: 无强信号 fallback to LLM
# ==========================================================================
class TestL8NoStrongSignal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix27_l8_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_signal_returns_none(self):
        e = _make_entity('something neutral xyz')
        ev = {'stm': [
            {'user': 'unrelated topic discussion',
             'jarvis': 'unrelated'}
        ]}
        decision, reason = self.d._thread_strong_gate(e, ev)
        self.assertIsNone(decision)
        self.assertEqual(reason, 'no_strong_signal_fallback_to_llm')


# ==========================================================================
# L9: _evaluate_and_decide 真集成
# ==========================================================================
class TestL9EvaluateBypassesLLMOnStrongSignal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix27_l9_')
        from jarvis_auto_arbiter import AutoArbiterDaemon
        self._saved_persist = AutoArbiterDaemon.PERSIST_PATH
        AutoArbiterDaemon.PERSIST_PATH = os.path.join(self.tmp, 'log.jsonl')
        self._saved_calib = AutoArbiterDaemon.CALIBRATION_PATH
        AutoArbiterDaemon.CALIBRATION_PATH = os.path.join(self.tmp, 'cal.json')
        self.d = _make_daemon(_make_vocab_file(self.tmp))
        self.d.relational = MagicMock()
        self.d.relational.activate_from_review = MagicMock(return_value='thread')
        self.d.relational.reject_from_review = MagicMock(return_value='thread')
        self.d.relational.shared_history_threads = {}

    def tearDown(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        AutoArbiterDaemon.PERSIST_PATH = self._saved_persist
        AutoArbiterDaemon.CALIBRATION_PATH = self._saved_calib
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_strong_act_bypasses_llm(self):
        e = _make_entity('built deployed jarvis')
        self.d.nerve = MagicMock()
        self.d.nerve.short_term_memory = [
            {'user': 'i built and deployed jarvis tonight',
             'jarvis': 'noted'}
        ]
        item = {'kind': 'thread', 'entity': e, 'preview': e.title}
        with patch.object(self.d, '_llm_evaluate') as mock_llm:
            self.d._evaluate_and_decide(item)
        mock_llm.assert_not_called()
        self.d.relational.activate_from_review.assert_called_once()
        self.assertEqual(self.d._decisions[0].decision, 'activate')

    def test_strong_rej_bypasses_llm(self):
        e = _make_entity('a', detail='also')  # both trivial
        self.d.nerve = MagicMock()
        self.d.nerve.short_term_memory = []
        item = {'kind': 'thread', 'entity': e, 'preview': e.title}
        with patch.object(self.d, '_llm_evaluate') as mock_llm:
            self.d._evaluate_and_decide(item)
        mock_llm.assert_not_called()
        self.d.relational.reject_from_review.assert_called_once()
        self.assertEqual(self.d._decisions[0].decision, 'reject')


if __name__ == '__main__':
    unittest.main(verbosity=2)
