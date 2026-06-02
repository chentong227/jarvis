# -*- coding: utf-8 -*-
"""[B2 / Sir 2026-06-02 真机二次] 主页/面板端口意图消歧回归.

真机 BUG (jarvis_20260602_194104): Sir "打开主页" → 主脑想开主页却 emit
url_launcher.open_url(8765) (8765=面板端口, 记错), 拦截器按端口 8765→dashboard
→ 又开成面板。

治本: 拦截器先用**本轮 Sir 原话**意图 (dashboard_intent_vocab) 消歧:
  Sir 说"主页"→ 强制 homepage_open (无视主脑 emit 的端口);
  说"面板"→ dashboard_open; 没说→ fallback 端口号。

覆盖 (用 JARVIS_MIRROR=1 让 ui_control 返 mock-skip 串, 不真开窗):
  T1  Sir 说"打开主页" + 主脑 emit 8765(错端口) → 仍 homepage_open
  T2  Sir 说"打开面板" + 主脑 emit 8765 → dashboard_open
  T3  Sir 说"主页" + 主脑 emit 8766(对) → homepage_open
  T4  Sir 没说主页/面板 + emit 8766 → fallback homepage_open
  T5  Sir 没说主页/面板 + emit 8765 → fallback dashboard_open
  T6  _resolve_homepage_dashboard_intent: homepage 关键词 → 'homepage'
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_chat_bypass as cb


class _StubVocal:
    def render_only(self, *a, **k): return None
    def play_only(self, *a, **k): return None


class _StubJarvis:
    def __init__(self):
        self.hand_registry = {}
        self.event_bus = None
        self.gemini_key = None


def _make_bypass():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop('JARVIS_MIRROR', None)
        b = cb.ChatBypass(key_router=object(),
                          vocal_cord=_StubVocal(),
                          state_callback=lambda *a, **k: None)
    b.jarvis = _StubJarvis()
    return b


class TestB2PortIntent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = _make_bypass()

    def _call(self, user_text, url):
        self.b._current_turn_user_text = user_text
        with patch.dict(os.environ, {'JARVIS_MIRROR': '1'}):
            return self.b._execute_fast_call(
                "url_launcher_hands", "open_url", {"url": url})

    def test_t1_homepage_intent_wrong_port_8765(self):
        r = self._call("打开主页", "http://127.0.0.1:8765")
        self.assertIn("homepage_open", r,
                      f"B2: Sir说主页+错端口8765 应仍 homepage_open, got {r!r}")

    def test_t2_dashboard_intent_port_8765(self):
        r = self._call("打开面板", "http://127.0.0.1:8765")
        self.assertIn("dashboard_open", r)

    def test_t3_homepage_intent_right_port_8766(self):
        r = self._call("打开主页", "http://127.0.0.1:8766")
        self.assertIn("homepage_open", r)

    def test_t4_no_intent_fallback_8766(self):
        r = self._call("帮我打开那个", "http://127.0.0.1:8766")
        self.assertIn("homepage_open", r, "B2: 无意图 8766 fallback homepage")

    def test_t5_no_intent_fallback_8765(self):
        r = self._call("帮我打开那个", "http://127.0.0.1:8765")
        self.assertIn("dashboard_open", r, "B2: 无意图 8765 fallback dashboard")

    def test_t6_resolve_intent_helper(self):
        self.b._current_turn_user_text = "打开主页看看"
        self.assertEqual(self.b._resolve_homepage_dashboard_intent(), "homepage")
        self.b._current_turn_user_text = "打开面板"
        self.assertEqual(self.b._resolve_homepage_dashboard_intent(), "dashboard")
        self.b._current_turn_user_text = "今天天气不错"
        self.assertEqual(self.b._resolve_homepage_dashboard_intent(), "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
