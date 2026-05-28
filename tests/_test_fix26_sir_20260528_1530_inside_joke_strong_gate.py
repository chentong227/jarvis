# -*- coding: utf-8 -*-
"""[fix26 / Sir 2026-05-28 15:30 真痛 image 1] inside_joke 两层耦合 strong-gate regression.

Sir 真痛 (image 1):
  "真笑点得我大致复述 / 笑了 (现在能听语音) / 或者我确认对笑才算 inside_joke.
   把拍板的提案标全部列出来, 不用列给我你自己分析, 然后严格把关一下, 保证提案的质量."

Sir 反 LLM 自嗨, 要 Python deterministic strong-gate 决强信号 case, LLM 仅做 edge.

修法 (准则 6 + 准则 8 两层耦合):
  1. memory_pool/auto_arbiter_inside_joke_vocab.json 持久化 (confirm / dismiss /
     stock_butler / 阈值)
  2. AutoArbiterDaemon._inside_joke_strong_gate() 强 ACT / 强 REJ deterministic
     (Sir 复述 / laughter / confirm / dismiss / stock / trivial 6 信号)
  3. _evaluate_and_decide 加 inside_joke pre-check, 命中 → bypass LLM
  4. _collect_evidence 扩 STM + 加 ambient_laughter_events

测试覆盖 (10 个):
  L1 vocab load OK + enabled
  L2 强 ACT-(a) Sir substring 复述 → activate
  L3 强 ACT-(a') Sir char overlap 复述 → activate
  L4 强 ACT-(b) ambient laughter event → activate
  L5 强 ACT-(c) Sir 文字 confirm vocab → activate
  L6 强 REJ-(a) Sir dismiss vocab → reject
  L7 强 REJ-(c) stock butler clichés → reject
  L8 强 REJ-(d) trivial 短 phrase → reject
  L9 无强信号 → None (走 LLM fallback)
  L10 _evaluate_and_decide 真集成 inside_joke pre-check (bypass LLM 真生效)
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


# ==========================================================================
# Helpers
# ==========================================================================
def _make_vocab_file(tmpdir: str, **overrides) -> str:
    """构造测试 vocab json 并返回 path. overrides 覆盖默认值."""
    data = {
        'enabled': True,
        'confirm_keywords': ['好笑', '哈哈', '对', 'lol', 'haha', 'good one'],
        'dismiss_keywords': ['不好笑', 'not funny', '别闹', 'cringe'],
        'stock_butler_keywords': ['indeed sir', 'as you wish', '明白了'],
        'sir_quote_token_overlap': 0.6,
        'laughter_window_s': 300,
        'confirm_turns_after': 2,
        'min_phrase_words': 3,
        'max_phrase_chars': 80,
        'stm_lookback_turns': 10,
        'log_decisions': False,  # 测试静音
    }
    data.update(overrides)
    path = os.path.join(tmpdir, 'inside_joke_vocab.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _make_daemon(vocab_path: str):
    """建 daemon + patch vocab path + clear cache."""
    from jarvis_auto_arbiter import AutoArbiterDaemon
    AutoArbiterDaemon.INSIDE_JOKE_VOCAB_PATH = vocab_path
    # 清 class-level cache (per-test 隔离)
    AutoArbiterDaemon._INSIDE_JOKE_VOCAB_CACHE = {
        'data': None, 'mtime': 0.0, 'checked_at': 0.0,
    }
    daemon = AutoArbiterDaemon(key_router=None)
    return daemon


def _make_entity(phrase: str, created_at: float = None):
    """假 InsideJoke entity (只用 phrase + created_at)."""
    e = MagicMock()
    e.phrase = phrase
    e.id = f"j_{int(time.time() * 1000) % 100000:05d}"
    e.created_at = created_at or time.time()
    e.birth_context = ''
    e.tone = ''
    e.source = 'test'
    e.state = 'review'
    return e


# ==========================================================================
# L1: vocab load + enabled
# ==========================================================================
class TestL1VocabLoad(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix26_l1_')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_vocab_load_enabled(self):
        path = _make_vocab_file(self.tmp)
        d = _make_daemon(path)
        vocab = d._load_inside_joke_vocab()
        self.assertTrue(vocab.get('enabled'))
        self.assertIn('好笑', vocab.get('confirm_keywords'))
        self.assertIn('not funny', vocab.get('dismiss_keywords'))

    def test_vocab_disabled_skips_gate(self):
        path = _make_vocab_file(self.tmp, enabled=False)
        d = _make_daemon(path)
        e = _make_entity('Sir specific funny phrase here')
        ev = {'stm': []}
        decision, reason = d._inside_joke_strong_gate(e, ev)
        self.assertIsNone(decision)
        self.assertEqual(reason, 'vocab_disabled')


# ==========================================================================
# L2-L5: 强 ACT 4 信号
# ==========================================================================
class TestL2StrongActSubstring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix26_l2_')
        self.path = _make_vocab_file(self.tmp)
        self.d = _make_daemon(self.path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sir_substring_quoted_activates(self):
        e = _make_entity('becoming subtly overbearing')
        ev = {'stm': [
            {'user': 'haha you are really becoming subtly overbearing today',
             'jarvis': 'noted sir'}
        ]}
        decision, reason = self.d._inside_joke_strong_gate(e, ev)
        self.assertEqual(decision, 'activate')
        self.assertIn('sir_quoted_substring', reason)


class TestL3StrongActTokenOverlap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix26_l3_')
        # 加大 confirm_turns_after 让 ACT-c 不走 (test 隔离)
        self.path = _make_vocab_file(self.tmp, confirm_turns_after=0)
        self.d = _make_daemon(self.path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sir_token_overlap_activates(self):
        # phrase tokens: {vocal, cord, logic} 3 tokens
        # Sir 原话 contain 2/3 (vocal, logic) = 0.67 >= 0.6 (vocab default) ✓
        # Sir 不必完全说原 phrase, 只是关键 2/3 token 命中即真复述
        e = _make_entity('vocal cord logic')
        ev = {'stm': [
            {'user': 'that vocal trick about logic was something',
             'jarvis': 'noted'}
        ]}
        decision, reason = self.d._inside_joke_strong_gate(e, ev)
        self.assertEqual(decision, 'activate')
        self.assertIn('sir_quoted_token_overlap', reason)


class TestL4StrongActLaughter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix26_l4_')
        self.path = _make_vocab_file(self.tmp)
        self.d = _make_daemon(self.path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ambient_laughter_activates(self):
        e = _make_entity('Sir favorite punchline here')
        ev = {
            'stm': [],
            'ambient_laughter_events': [
                {'ts': time.time(), 'offset_s': 12, 'desc': 'laughter'}
            ],
        }
        decision, reason = self.d._inside_joke_strong_gate(e, ev)
        self.assertEqual(decision, 'activate')
        self.assertIn('sir_laughed', reason)


class TestL5StrongActConfirm(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix26_l5_')
        self.path = _make_vocab_file(self.tmp)
        self.d = _make_daemon(self.path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sir_text_confirm_activates(self):
        e = _make_entity('xyzabc unique phrase nomatch')
        ev = {'stm': [
            {'user': 'whatever sir says here',
             'jarvis': 'some reply'},
            {'user': '哈哈 真好笑',  # confirm hit
             'jarvis': 'thank you sir'},
        ]}
        decision, reason = self.d._inside_joke_strong_gate(e, ev)
        self.assertEqual(decision, 'activate')
        self.assertIn('sir_text_confirm', reason)


# ==========================================================================
# L6-L8: 强 REJ 3 信号
# ==========================================================================
class TestL6StrongRejDismiss(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix26_l6_')
        self.path = _make_vocab_file(self.tmp)
        self.d = _make_daemon(self.path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sir_dismiss_rejects(self):
        e = _make_entity('some attempted phrase that flopped')
        ev = {'stm': [
            {'user': 'that was not funny at all',
             'jarvis': 'noted'}
        ]}
        decision, reason = self.d._inside_joke_strong_gate(e, ev)
        self.assertEqual(decision, 'reject')
        self.assertIn('sir_dismiss', reason)


class TestL7StrongRejStockButler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix26_l7_')
        self.path = _make_vocab_file(self.tmp)
        self.d = _make_daemon(self.path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stock_butler_rejects(self):
        e = _make_entity('Indeed sir, very well noted')
        ev = {'stm': []}
        decision, reason = self.d._inside_joke_strong_gate(e, ev)
        self.assertEqual(decision, 'reject')
        self.assertIn('stock_butler', reason)


class TestL8StrongRejTrivial(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix26_l8_')
        self.path = _make_vocab_file(self.tmp)
        self.d = _make_daemon(self.path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_short_phrase_rejects(self):
        e = _make_entity('too short')  # 2 words < min 3
        ev = {'stm': []}
        decision, reason = self.d._inside_joke_strong_gate(e, ev)
        self.assertEqual(decision, 'reject')
        self.assertIn('trivial', reason)

    def test_long_phrase_rejects(self):
        e = _make_entity('a' * 100)  # > max 80 chars
        ev = {'stm': []}
        decision, reason = self.d._inside_joke_strong_gate(e, ev)
        self.assertEqual(decision, 'reject')
        self.assertIn('trivial', reason)


# ==========================================================================
# L9: 无强信号 fallback to LLM
# ==========================================================================
class TestL9NoStrongSignalFallsBackToLLM(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix26_l9_')
        self.path = _make_vocab_file(self.tmp)
        self.d = _make_daemon(self.path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_signal_returns_none(self):
        # phrase 长度合格 + 没 stock + STM 没 dismiss/confirm/quote, 也没 laughter
        e = _make_entity('something neutral nothing matching here')
        ev = {
            'stm': [
                {'user': 'unrelated topic discussion',
                 'jarvis': 'unrelated reply'}
            ],
            'ambient_laughter_events': [],
        }
        decision, reason = self.d._inside_joke_strong_gate(e, ev)
        self.assertIsNone(decision)
        self.assertEqual(reason, 'no_strong_signal_fallback_to_llm')


# ==========================================================================
# L10: _evaluate_and_decide 真集成 (bypass LLM 真生效)
# ==========================================================================
class TestL10EvaluateBypassesLLMOnStrongSignal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fix26_l10_')
        self.path = _make_vocab_file(self.tmp)
        # PERSIST_PATH 也 patch 到 tmp 防写真 prod jsonl
        from jarvis_auto_arbiter import AutoArbiterDaemon
        self._saved_persist = AutoArbiterDaemon.PERSIST_PATH
        AutoArbiterDaemon.PERSIST_PATH = os.path.join(self.tmp, 'log.jsonl')
        self._saved_calib = AutoArbiterDaemon.CALIBRATION_PATH
        AutoArbiterDaemon.CALIBRATION_PATH = os.path.join(self.tmp, 'cal.json')
        self.d = _make_daemon(self.path)
        # mock relational + execute path
        self.d.relational = MagicMock()
        self.d.relational.activate_from_review = MagicMock(return_value='joke')
        self.d.relational.reject_from_review = MagicMock(return_value='joke')
        self.d.relational.inside_jokes = {}  # 空 active list

    def tearDown(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        AutoArbiterDaemon.PERSIST_PATH = self._saved_persist
        AutoArbiterDaemon.CALIBRATION_PATH = self._saved_calib
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_strong_act_bypasses_llm_eval(self):
        e = _make_entity('uniquely funny callback phrase')
        # 准备 STM 含 substring 复述
        self.d.nerve = MagicMock()
        self.d.nerve.short_term_memory = [
            {'user': 'haha uniquely funny callback phrase indeed',
             'jarvis': 'noted'}
        ]
        item = {'kind': 'inside_joke', 'entity': e,
                'preview': 'uniquely funny callback phrase'}
        # 关键: spy _llm_evaluate 应该 NOT 被调
        with patch.object(self.d, '_llm_evaluate') as mock_llm:
            self.d._evaluate_and_decide(item)
        mock_llm.assert_not_called()
        # activate 真调
        self.d.relational.activate_from_review.assert_called_once()
        # decision 写 deterministic
        self.assertEqual(len(self.d._decisions), 1)
        decision = self.d._decisions[0]
        self.assertEqual(decision.decision, 'activate')
        self.assertEqual(decision.confidence, 1.0)
        self.assertIn('pre_decide_strong', decision.reason)

    def test_strong_rej_bypasses_llm_eval(self):
        e = _make_entity('Indeed sir, as you wish always')  # stock_butler hit
        self.d.nerve = MagicMock()
        self.d.nerve.short_term_memory = []
        item = {'kind': 'inside_joke', 'entity': e,
                'preview': e.phrase}
        with patch.object(self.d, '_llm_evaluate') as mock_llm:
            self.d._evaluate_and_decide(item)
        mock_llm.assert_not_called()
        self.d.relational.reject_from_review.assert_called_once()
        self.assertEqual(self.d._decisions[0].decision, 'reject')

    def test_no_strong_signal_falls_back_to_llm(self):
        e = _make_entity('neutral something xyz random here')
        self.d.nerve = MagicMock()
        self.d.nerve.short_term_memory = [
            {'user': 'unrelated nothing matching',
             'jarvis': 'unrelated'}
        ]
        item = {'kind': 'inside_joke', 'entity': e,
                'preview': e.phrase}
        with patch.object(self.d, '_llm_evaluate',
                            return_value=('reject', 0.5, 'llm says no')) as mock_llm:
            self.d._evaluate_and_decide(item)
        mock_llm.assert_called_once()
        self.assertEqual(self.d._decisions[0].decision, 'defer_to_sir')


if __name__ == '__main__':
    unittest.main(verbosity=2)
