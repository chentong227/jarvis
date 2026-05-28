# -*- coding: utf-8 -*-
"""[fix28 / Sir 2026-05-28 15:40 H.3] protocol 两层耦合 strong-gate regression.

protocol = STRICT rule, Sir 真意 image 1 "严格把关":
  - 强 ACT: STM Sir 复述 rule (token overlap)
  - 强 REJ: rule trivial (词数 < min / 字数 > max) / 缺 imperative verb

测试覆盖 (10 个):
  L1 vocab load enabled + disabled
  L2 强 ACT-(a) Sir substring 复述 rule → activate
  L3 强 ACT-(b) Sir token overlap 复述 rule → activate
  L4 强 REJ-(a) rule 词数 < min → reject
  L5 强 REJ-(b) rule 字数 > max → reject
  L6 强 REJ-(c) rule 缺 imperative verb → reject
  L7 imperative verb 含 → 过 REJ-(c), 无强信号 → None
  L8 中文 imperative verb 命中 (必须/禁止/不要)
  L9 _evaluate_and_decide bypass LLM (strong ACT)
  L10 _evaluate_and_decide bypass LLM (strong REJ)
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
        'imperative_verbs': [
            'never', 'always', 'must', 'don\'t', "don't", 'should', 'use',
            'avoid', 'stop', 'keep', '禁止', '必须', '不要',
        ],
        'min_rule_token_overlap': 0.5,
        'min_rule_words': 4,
        'max_rule_chars': 200,
        'stm_lookback_turns': 10,
        'log_decisions': False,
    }
    data.update(overrides)
    path = os.path.join(tmpdir, 'protocol_vocab.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _make_daemon(vocab_path: str):
    from jarvis_auto_arbiter import AutoArbiterDaemon
    AutoArbiterDaemon.PROTOCOL_VOCAB_PATH = vocab_path
    AutoArbiterDaemon._PROTOCOL_VOCAB_CACHE = {
        'data': None, 'mtime': 0.0, 'checked_at': 0.0,
    }
    return AutoArbiterDaemon(key_router=None)


def _make_entity(rule: str):
    e = MagicMock()
    e.rule = rule
    e.id = f"p_{int(time.time() * 1000) % 100000:05d}"
    e.created_at = time.time()
    e.source = 'test'
    e.state = 'review'
    return e


# ==========================================================================
# L1: vocab load
# ==========================================================================
class TestL1VocabLoad(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix28_l1_')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_enabled(self):
        d = _make_daemon(_make_vocab_file(self.tmp))
        v = d._load_protocol_vocab()
        self.assertTrue(v.get('enabled'))
        self.assertIn('never', v.get('imperative_verbs'))

    def test_disabled_skips_gate(self):
        d = _make_daemon(_make_vocab_file(self.tmp, enabled=False))
        e = _make_entity('never reply with You are absolutely right')
        decision, _ = d._protocol_strong_gate(e, {'stm': []})
        self.assertIsNone(decision)


# ==========================================================================
# L2-L3: 强 ACT
# ==========================================================================
class TestL2StrongActSubstring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix28_l2_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_substring_activates(self):
        rule = "never start with you are absolutely right"
        e = _make_entity(rule)
        ev = {'stm': [
            {'user': f'rule: {rule}, ok?', 'jarvis': 'noted'}
        ]}
        decision, reason = self.d._protocol_strong_gate(e, ev)
        self.assertEqual(decision, 'activate')
        self.assertIn('sir_quoted_rule_substring', reason)


class TestL3StrongActTokenOverlap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix28_l3_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_token_overlap_activates(self):
        # rule tokens {never, start, with, absolutely, right} 5 tokens
        # Sir 3/5 (start, absolutely, right) = 0.6 >= 0.5
        e = _make_entity('never start with absolutely right')
        ev = {'stm': [
            {'user': 'dont start your reply with absolutely right phrasing',
             'jarvis': 'noted'}
        ]}
        decision, reason = self.d._protocol_strong_gate(e, ev)
        self.assertEqual(decision, 'activate')
        self.assertIn('sir_quoted_rule_token_overlap', reason)


# ==========================================================================
# L4-L6: 强 REJ
# ==========================================================================
class TestL4StrongRejTrivialWords(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix28_l4_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_short_rule_rejects(self):
        e = _make_entity('be nice')  # 2 words < min 4
        decision, reason = self.d._protocol_strong_gate(e, {'stm': []})
        self.assertEqual(decision, 'reject')
        self.assertIn('trivial_rule', reason)


class TestL5StrongRejTooLong(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix28_l5_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_long_rule_rejects(self):
        e = _make_entity('never ' + ('reply ' * 50))  # > 200 chars
        decision, reason = self.d._protocol_strong_gate(e, {'stm': []})
        self.assertEqual(decision, 'reject')
        self.assertIn('trivial_rule', reason)


class TestL6StrongRejNoImperativeVerb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix28_l6_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_imperative_rejects(self):
        # 4 words 过 REJ-a, 字数 OK 过 REJ-b, 但无 imperative verb
        e = _make_entity('the reply is good')  # no never/must/use/...
        decision, reason = self.d._protocol_strong_gate(e, {'stm': []})
        self.assertEqual(decision, 'reject')
        self.assertEqual(reason, 'missing_imperative_verb')


# ==========================================================================
# L7: 含 imperative + 无 STM 复述 → None (LLM fallback)
# ==========================================================================
class TestL7HasImperativeNoQuote(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix28_l7_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_none_no_strong(self):
        e = _make_entity('always use bullet points in long answers')
        ev = {'stm': [
            {'user': 'unrelated discussion', 'jarvis': 'unrelated'}
        ]}
        decision, reason = self.d._protocol_strong_gate(e, ev)
        self.assertIsNone(decision)
        self.assertEqual(reason, 'no_strong_signal_fallback_to_llm')


# ==========================================================================
# L8: 中文 imperative verb
# ==========================================================================
class TestL8ChineseImperative(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix28_l8_')
        self.d = _make_daemon(_make_vocab_file(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_chinese_imperative_passes_rej_c(self):
        e = _make_entity('必须使用 Sir 称谓 不要 you')
        decision, reason = self.d._protocol_strong_gate(e, {'stm': []})
        # 5 words 过 REJ-a, 字数 OK 过 REJ-b, 有"必须"/"不要" 过 REJ-c, 无 STM 复述 → None
        self.assertIsNone(decision)
        self.assertEqual(reason, 'no_strong_signal_fallback_to_llm')


# ==========================================================================
# L9-L10: _evaluate_and_decide 真集成
# ==========================================================================
class TestL9L10EvaluateIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix28_l9_')
        from jarvis_auto_arbiter import AutoArbiterDaemon
        self._saved_persist = AutoArbiterDaemon.PERSIST_PATH
        AutoArbiterDaemon.PERSIST_PATH = os.path.join(self.tmp, 'log.jsonl')
        self._saved_calib = AutoArbiterDaemon.CALIBRATION_PATH
        AutoArbiterDaemon.CALIBRATION_PATH = os.path.join(self.tmp, 'cal.json')
        self.d = _make_daemon(_make_vocab_file(self.tmp))
        self.d.relational = MagicMock()
        self.d.relational.activate_from_review = MagicMock(return_value='protocol')
        self.d.relational.reject_from_review = MagicMock(return_value='protocol')
        self.d.relational.style_protocols = {}

    def tearDown(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        AutoArbiterDaemon.PERSIST_PATH = self._saved_persist
        AutoArbiterDaemon.CALIBRATION_PATH = self._saved_calib
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_strong_act_bypasses_llm(self):
        rule = "never start reply with absolutely right"
        e = _make_entity(rule)
        self.d.nerve = MagicMock()
        self.d.nerve.short_term_memory = [
            {'user': f'add a rule: {rule}', 'jarvis': 'noted'}
        ]
        item = {'kind': 'protocol', 'entity': e, 'preview': e.rule}
        with patch.object(self.d, '_llm_evaluate') as mock_llm:
            self.d._evaluate_and_decide(item)
        mock_llm.assert_not_called()
        self.d.relational.activate_from_review.assert_called_once()
        self.assertEqual(self.d._decisions[0].decision, 'activate')

    def test_strong_rej_bypasses_llm(self):
        e = _make_entity('hi ok')  # 2 < 4 trivial
        self.d.nerve = MagicMock()
        self.d.nerve.short_term_memory = []
        item = {'kind': 'protocol', 'entity': e, 'preview': e.rule}
        with patch.object(self.d, '_llm_evaluate') as mock_llm:
            self.d._evaluate_and_decide(item)
        mock_llm.assert_not_called()
        self.d.relational.reject_from_review.assert_called_once()
        self.assertEqual(self.d._decisions[0].decision, 'reject')


if __name__ == '__main__':
    unittest.main(verbosity=2)
