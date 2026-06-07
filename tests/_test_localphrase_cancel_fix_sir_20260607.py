# -*- coding: utf-8 -*-
"""[localphrase-cancel-fix / 2026-06-07] bug#1 "One moment, Sir." 罐头音误触发修复.

真机 (jarvis_20260607_224539.log turn 2dde): TTFT=4.9s/stream 5.4s 已说完, 但 10s
墙钟 timer 漏被首token取消, 活过 full pipeline 16.9s 后台窗口, 在 turn_complete 后
fire "One moment, Sir." = 纯噪音.

修法 (推荐: 修触发不整删): 加 _turn_streaming_done 守卫, _maybe_say_local fire 前查;
turn 收尾 (stream_chat finally) set True + 强制 cancel timer. 保留真慢响应 (>10s, 流式
还没结束) 垫场.

覆盖:
  T1 turn 已结束守卫: _turn_streaming_done=True 时 timer fire → 不播 (核心修复)
  T2 真慢响应仍垫场: turn 未结束 + 未收首token → timer fire → 仍播 (DEEP_QUERY one_moment)
  T3 首token取消仍生效 (原行为不破): 收首token → timer 不播
  T4 守卫 + 首token 双保险: 两者任一为真都不播
  T5 源码静态守护: finally 块 set _turn_streaming_done + cancel timer; init 有该 flag
"""
from __future__ import annotations

import os
import sys
import re
import time
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _MockVocal:
    def __init__(self):
        self.play_calls = []
        self.render_calls = []

    def render_only(self, text):
        self.render_calls.append(text)
        return b'PCM:' + text.encode('utf-8')

    def play_only(self, pcm):
        self.play_calls.append(pcm)


class _MockSubtitleQueue:
    def put(self, item):
        pass


class _MockBypass:
    def __init__(self):
        from jarvis_nerve import ChatBypass
        self.vocal = _MockVocal()
        self.subtitle_queue = _MockSubtitleQueue()
        self._first_token_received = False
        self._turn_streaming_done = False        # 🆕 新守卫
        self._backchannel_timer = None
        self._local_utterance_timer = None
        self._local_utterance_in_progress = False
        self.is_interrupted = False
        self.jarvis = None
        self._LOCAL_PHRASE_POOL_SPEC = ChatBypass._LOCAL_PHRASE_POOL_SPEC
        self._LOCAL_PHRASE_TIER_ROUTE = ChatBypass._LOCAL_PHRASE_TIER_ROUTE
        self._LOCAL_PHRASE_THRESHOLD = ChatBypass._LOCAL_PHRASE_THRESHOLD
        self._LOCAL_PHRASE_POOL_ENABLED = ChatBypass._LOCAL_PHRASE_POOL_ENABLED
        self._LOCAL_UTTERANCE_ENABLED = ChatBypass._LOCAL_UTTERANCE_ENABLED
        self._local_phrase_pool = {}
        self._local_phrase_pool_lock = threading.Lock()
        self._local_phrase_pool_ready = False
        self._warmup_local_phrase_pool = lambda: ChatBypass._warmup_local_phrase_pool(self)
        self._get_local_phrase_for_tier = (
            lambda tier: ChatBypass._get_local_phrase_for_tier(self, tier))
        self._start_backchannel_timer = (
            lambda *a, **kw: ChatBypass._start_backchannel_timer(self, *a, **kw))
        self._mark_first_token = lambda: ChatBypass._mark_first_token(self)


class TestTurnEndedGuard(unittest.TestCase):
    def setUp(self):
        self.b = _MockBypass()
        self.b._warmup_local_phrase_pool()

    def test_t1_streaming_done_suppresses_phrase(self):
        """核心修复: turn 已结束 → 即便 timer fire 也不播 (bug#1 根因)."""
        self.b._start_backchannel_timer(threshold_sec=2.0,
                                        local_utterance_threshold=0.3,
                                        prompt_tier='DEEP_QUERY')
        # 模拟 turn 收尾: streaming done (timer 漏取消的场景)
        self.b._turn_streaming_done = True
        time.sleep(0.5)  # timer 0.3s 到点 fire
        self.assertEqual(len(self.b.vocal.play_calls), 0,
                         "turn 已结束守卫应阻止罐头音 (bug#1 修复)")

    def test_t2_genuine_slow_still_plays(self):
        """真慢响应: turn 未结束 + 未收首token → 仍垫场 (保留价值)."""
        self.b._start_backchannel_timer(threshold_sec=2.0,
                                        local_utterance_threshold=0.3,
                                        prompt_tier='DEEP_QUERY')
        # turn 仍在进行 (未 set _turn_streaming_done), 未收首token
        time.sleep(0.5)
        self.assertEqual(len(self.b.vocal.play_calls), 1,
                         "真慢响应应仍播 one_moment 垫场")
        self.assertIn(b'One moment', self.b.vocal.play_calls[0])

    def test_t3_first_token_cancels(self):
        """原行为不破: 收首token → timer 取消, 不播."""
        self.b._start_backchannel_timer(threshold_sec=2.0,
                                        local_utterance_threshold=0.3,
                                        prompt_tier='DEEP_QUERY')
        self.b._mark_first_token()
        time.sleep(0.5)
        self.assertEqual(len(self.b.vocal.play_calls), 0)

    def test_t4_both_guards_suppress(self):
        self.b._start_backchannel_timer(threshold_sec=2.0,
                                        local_utterance_threshold=0.3,
                                        prompt_tier='DEEP_QUERY')
        self.b._first_token_received = True
        self.b._turn_streaming_done = True
        time.sleep(0.5)
        self.assertEqual(len(self.b.vocal.play_calls), 0)


class TestSourceStaticGuard(unittest.TestCase):
    def test_t5_wiring_in_source(self):
        src = open(os.path.join(ROOT, 'jarvis_chat_bypass.py'),
                   encoding='utf-8').read()
        # init + timer-start 重置 + maybe_say guard 都引用 _turn_streaming_done
        self.assertGreaterEqual(src.count('_turn_streaming_done'), 3)
        # finally 块 set True + cancel timer (取 finally 之后一段验证)
        idx = src.rfind('set_conversation_active(False)')
        self.assertGreater(idx, 0)
        tail = src[idx:idx + 600]
        self.assertIn('_turn_streaming_done = True', tail)
        self.assertIn('_local_utterance_timer.cancel()', tail)


if __name__ == '__main__':
    unittest.main()
