# -*- coding: utf-8 -*-
"""[P5-SirStatusTracker / 2026-05-21 15:25] Sir 声明状态跟踪 verify.

Sir 13:49 痛点: nudge 话术 "Soul Drive doc still active in Windsurf 90min"
— 但 Sir 12:06 说"睡觉了下午见". 系统不知道 → 改用 IDE 窗口 idle 推断.

Cover:
  A. detect_status_from_utterance — 8 类 (sleep/nap/lunch/dinner/out/afk_short/dnd/back)
  B. SirStatus dataclass + Store persist + load
  C. update_status 优先级 (sleep > out > nap > lunch > afk > active)
  D. 'back' transition → reset to active
  E. observe_sir_utterance publish SWM
  F. render_status_block_for_prompt
  G. chat_bypass hook static check
  H. central_nerve _assemble_prompt 加 block + ReturnSentinel nudge_ctx 加 declared_status
  I. Vocab loader + mtime cache
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# A. detect_status_from_utterance
# ============================================================

class TestA_DetectStatus(unittest.TestCase):
    def test_sleep_zh(self):
        from jarvis_sir_status_tracker import detect_status_from_utterance, STATUS_SLEEP
        s, kw = detect_status_from_utterance("睡觉了睡觉了，下午见")
        self.assertEqual(s, STATUS_SLEEP)
        self.assertIn(kw, ('睡觉了', '下午见'))

    def test_sleep_en(self):
        from jarvis_sir_status_tracker import detect_status_from_utterance, STATUS_SLEEP
        s, kw = detect_status_from_utterance("Good night, Jarvis")
        self.assertEqual(s, STATUS_SLEEP)

    def test_nap_zh(self):
        from jarvis_sir_status_tracker import detect_status_from_utterance, STATUS_NAP
        s, kw = detect_status_from_utterance("我睡个午觉")
        self.assertEqual(s, STATUS_NAP)

    def test_lunch_zh(self):
        from jarvis_sir_status_tracker import detect_status_from_utterance, STATUS_LUNCH
        s, kw = detect_status_from_utterance("吃饭去")
        self.assertEqual(s, STATUS_LUNCH)

    def test_out_zh(self):
        from jarvis_sir_status_tracker import detect_status_from_utterance, STATUS_OUT
        s, kw = detect_status_from_utterance("我出去一下")
        self.assertEqual(s, STATUS_OUT)

    def test_afk_short_zh(self):
        from jarvis_sir_status_tracker import detect_status_from_utterance, STATUS_AFK_SHORT
        s, kw = detect_status_from_utterance("一会回")
        self.assertEqual(s, STATUS_AFK_SHORT)

    def test_dnd_zh(self):
        from jarvis_sir_status_tracker import detect_status_from_utterance, STATUS_DND
        s, kw = detect_status_from_utterance("别打扰我了, 我在专注")
        self.assertEqual(s, STATUS_DND)

    def test_back_zh(self):
        from jarvis_sir_status_tracker import detect_status_from_utterance
        s, kw = detect_status_from_utterance("我回来了")
        self.assertEqual(s, 'back')

    def test_no_detect_chitchat(self):
        from jarvis_sir_status_tracker import detect_status_from_utterance
        s, kw = detect_status_from_utterance("Hello, Jarvis. How are you?")
        self.assertEqual(s, '')

    def test_priority_sleep_over_out(self):
        """睡觉 > 出门 优先级 (含 '下午见' 在 sleep 类)."""
        from jarvis_sir_status_tracker import detect_status_from_utterance, STATUS_SLEEP
        s, kw = detect_status_from_utterance("睡觉了 下午见")
        self.assertEqual(s, STATUS_SLEEP)


# ============================================================
# B. SirStatus dataclass + Store
# ============================================================

class TestB_StoreAPI(unittest.TestCase):
    def setUp(self):
        from jarvis_sir_status_tracker import (
            reset_default_store_for_tests, reset_vocab_cache_for_tests
        )
        self._tmpdir = tempfile.mkdtemp()
        self._path = os.path.join(self._tmpdir, 'sir_status.json')
        reset_default_store_for_tests(path=self._path)
        reset_vocab_cache_for_tests()

    def tearDown(self):
        from jarvis_sir_status_tracker import reset_default_store_for_tests
        reset_default_store_for_tests(path=None)
        try:
            if os.path.exists(self._path):
                os.remove(self._path)
            os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_initial_unknown(self):
        from jarvis_sir_status_tracker import get_default_store, STATUS_UNKNOWN
        store = get_default_store()
        cur = store.current()
        self.assertEqual(cur.status, STATUS_UNKNOWN)

    def test_update_status_persists(self):
        from jarvis_sir_status_tracker import get_default_store, STATUS_SLEEP
        store = get_default_store()
        changed = store.update_status(STATUS_SLEEP, '睡觉了', '睡觉了下午见', 'turn_a')
        self.assertTrue(changed)
        # reload
        from jarvis_sir_status_tracker import SirStatusStore
        store2 = SirStatusStore(path=self._path)
        cur2 = store2.current()
        self.assertEqual(cur2.status, STATUS_SLEEP)
        self.assertEqual(cur2.last_keyword, '睡觉了')

    def test_same_status_not_updated(self):
        from jarvis_sir_status_tracker import get_default_store, STATUS_SLEEP
        store = get_default_store()
        store.update_status(STATUS_SLEEP, '睡觉了', '', 'turn_a')
        changed2 = store.update_status(STATUS_SLEEP, '睡了', '', 'turn_b')
        self.assertFalse(changed2)


# ============================================================
# C. Priority logic
# ============================================================

class TestC_Priority(unittest.TestCase):
    def setUp(self):
        from jarvis_sir_status_tracker import (
            reset_default_store_for_tests, reset_vocab_cache_for_tests
        )
        self._tmpdir = tempfile.mkdtemp()
        self._path = os.path.join(self._tmpdir, 'sir_status.json')
        reset_default_store_for_tests(path=self._path)
        reset_vocab_cache_for_tests()

    def tearDown(self):
        from jarvis_sir_status_tracker import reset_default_store_for_tests
        reset_default_store_for_tests(path=None)
        try:
            os.remove(self._path); os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_low_priority_not_override_high(self):
        """sleep 已 active → afk_short 不能覆盖 (优先级低)."""
        from jarvis_sir_status_tracker import get_default_store, STATUS_SLEEP, STATUS_AFK_SHORT
        store = get_default_store()
        store.update_status(STATUS_SLEEP, '睡觉了', '', 't1')
        changed = store.update_status(STATUS_AFK_SHORT, '一会回', '', 't2')
        self.assertFalse(changed)
        self.assertEqual(store.current().status, STATUS_SLEEP)

    def test_high_priority_override_low(self):
        """afk_short → sleep (高优先级覆盖)."""
        from jarvis_sir_status_tracker import get_default_store, STATUS_SLEEP, STATUS_AFK_SHORT
        store = get_default_store()
        store.update_status(STATUS_AFK_SHORT, 'brb', '', 't1')
        changed = store.update_status(STATUS_SLEEP, '睡了', '', 't2')
        self.assertTrue(changed)
        self.assertEqual(store.current().status, STATUS_SLEEP)


# ============================================================
# D. 'back' transition
# ============================================================

class TestD_BackTransition(unittest.TestCase):
    def setUp(self):
        from jarvis_sir_status_tracker import (
            reset_default_store_for_tests, reset_vocab_cache_for_tests
        )
        self._tmpdir = tempfile.mkdtemp()
        self._path = os.path.join(self._tmpdir, 'sir_status.json')
        reset_default_store_for_tests(path=self._path)
        reset_vocab_cache_for_tests()

    def tearDown(self):
        from jarvis_sir_status_tracker import reset_default_store_for_tests
        reset_default_store_for_tests(path=None)
        try:
            os.remove(self._path); os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_back_resets_to_active(self):
        from jarvis_sir_status_tracker import get_default_store, STATUS_SLEEP, STATUS_ACTIVE
        store = get_default_store()
        store.update_status(STATUS_SLEEP, '睡觉了', '', 't1')
        self.assertEqual(store.current().status, STATUS_SLEEP)
        changed = store.update_status('back', '我回来了', '', 't2')
        self.assertTrue(changed)
        self.assertEqual(store.current().status, STATUS_ACTIVE)


# ============================================================
# E. observe_sir_utterance publishes SWM
# ============================================================

class TestE_ObserveUtterance(unittest.TestCase):
    def setUp(self):
        from jarvis_sir_status_tracker import (
            reset_default_store_for_tests, reset_vocab_cache_for_tests
        )
        self._tmpdir = tempfile.mkdtemp()
        self._path = os.path.join(self._tmpdir, 'sir_status.json')
        reset_default_store_for_tests(path=self._path)
        reset_vocab_cache_for_tests()

    def tearDown(self):
        from jarvis_sir_status_tracker import reset_default_store_for_tests
        reset_default_store_for_tests(path=None)
        try:
            os.remove(self._path); os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_observe_publishes_swm_when_status_changes(self):
        from jarvis_sir_status_tracker import observe_sir_utterance
        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus') as _g:
            _g.return_value = mock_bus
            result = observe_sir_utterance("睡觉了下午见", turn_id='turn_test')
        self.assertIsNotNone(result)
        # SWM publish 触发
        self.assertTrue(mock_bus.publish.called)
        kwargs = mock_bus.publish.call_args.kwargs
        self.assertEqual(kwargs['etype'], 'sir_declared_status')
        self.assertEqual(kwargs['source'], 'SirStatusTracker')

    def test_observe_no_detect_no_publish(self):
        from jarvis_sir_status_tracker import observe_sir_utterance
        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus') as _g:
            _g.return_value = mock_bus
            result = observe_sir_utterance("Hello Jarvis how are you", turn_id='t1')
        self.assertIsNone(result)
        mock_bus.publish.assert_not_called()


# ============================================================
# F. render_status_block_for_prompt
# ============================================================

class TestF_RenderBlock(unittest.TestCase):
    def setUp(self):
        from jarvis_sir_status_tracker import (
            reset_default_store_for_tests, reset_vocab_cache_for_tests
        )
        self._tmpdir = tempfile.mkdtemp()
        self._path = os.path.join(self._tmpdir, 'sir_status.json')
        reset_default_store_for_tests(path=self._path)
        reset_vocab_cache_for_tests()

    def tearDown(self):
        from jarvis_sir_status_tracker import reset_default_store_for_tests
        reset_default_store_for_tests(path=None)
        try:
            os.remove(self._path); os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_block_empty_when_unknown(self):
        from jarvis_sir_status_tracker import render_status_block_for_prompt
        self.assertEqual(render_status_block_for_prompt(), '')

    def test_block_shows_sleep_status(self):
        from jarvis_sir_status_tracker import (
            get_default_store, render_status_block_for_prompt, STATUS_SLEEP
        )
        store = get_default_store()
        store.update_status(STATUS_SLEEP, '睡觉了', '睡觉了下午见', 't1')
        block = render_status_block_for_prompt()
        self.assertIn("SIR'S DECLARED STATUS", block)
        self.assertIn('睡觉中', block)
        self.assertIn('rested', block)


# ============================================================
# G. static integration check
# ============================================================

class TestG_StaticIntegration(unittest.TestCase):
    def test_chat_bypass_calls_observe(self):
        import jarvis_chat_bypass
        with open(jarvis_chat_bypass.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('observe_sir_utterance_async', src)
        self.assertIn('jarvis_sir_status_tracker', src)

    def test_central_nerve_renders_block(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('render_status_block_for_prompt', src)
        self.assertIn("SIR'S DECLARED STATUS", src)

    def test_return_sentinel_reads_status(self):
        import jarvis_return_sentinel
        with open(jarvis_return_sentinel.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('sir_declared_status', src)
        self.assertIn('current_status', src)


if __name__ == '__main__':
    unittest.main()
