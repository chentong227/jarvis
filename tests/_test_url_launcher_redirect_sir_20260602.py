# -*- coding: utf-8 -*-
"""[真痛2 / Sir 2026-06-02] url_launcher 自家面板/主页 URL 确定性重定向回归.

Sir 真机痛点 (trace jarvis_20260602_074921):
  说"打开主页" → 主脑绕过 ui_control directive, 直接 emit
  url_launcher_hands.open_url(http://127.0.0.1:8765) → 开错端口 (8765=面板, 主页=8766)
  且 server 没起时是死链。

治本 (commit e03f12c): 在 _execute_fast_call 顶部 (覆盖 FAST_CALL + TOOL_CALL
via IntentRouter.fast_call_executor) 做确定性拦截 — URL 命中 jarvis 自家端口 →
改走对应 ui_control 命令。不靠模型遵循 directive (镜像证明弱模型不可靠)。

为什么不用镜像测: 镜像弱模型 emit 的是 malformed <TOOL_CALL> (schema 错), 根本
没触发执行路径 (tool_results=[]), 复现不了真机 bug。确定性拦截器只能用单元级
直调 _execute_fast_call 来证明 — 它跟主脑用什么模型无关。

覆盖:
  T1  open_url(8766)  → 重定向 homepage_open
  T2  open_url(8765)  → 重定向 dashboard_open
  T3  organ='url_launcher' (无 _hands 后缀) 同样拦
  T4  command='open' (别名) 同样拦
  T5  params 用 'target' 而非 'url' 也拦
  T6  非 jarvis 自家 URL (google.com) → 不重定向 (落 generic 路径)
  T7  localhost:8766 写法 (非 127.0.0.1) 也拦
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
    """warmup daemon 会调 render_only; 返 None → pool 空, 无副作用."""
    def render_only(self, *a, **k):
        return None

    def play_only(self, *a, **k):
        return None


class _StubHandRegistry(dict):
    """空 registry — 非 jarvis URL 落到这里返 'not mounted', 不真开浏览器."""
    pass


class _StubJarvis:
    def __init__(self):
        self.hand_registry = _StubHandRegistry()
        self.event_bus = None
        self.gemini_key = None


def _make_bypass():
    # 构造时 mirror 关 (避免 monkeypatch stream_chat), 调用时再开
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop('JARVIS_MIRROR', None)
        b = cb.ChatBypass(
            key_router=object(),
            vocal_cord=_StubVocal(),
            state_callback=lambda *a, **k: None,
        )
    b.jarvis = _StubJarvis()
    return b


class TestUrlLauncherRedirect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = _make_bypass()

    def _call(self, organ, command, params):
        # 调用时强制 mirror mode → homepage_open/dashboard_open 返 mirror-skip 串
        # (不真起 subprocess / 不开浏览器), 串里带 command 名供断言.
        with patch.dict(os.environ, {'JARVIS_MIRROR': '1'}):
            return self.b._execute_fast_call(organ, command, params)

    def test_t1_8766_redirects_to_homepage(self):
        r = self._call("url_launcher_hands", "open_url",
                       {"url": "http://127.0.0.1:8766"})
        self.assertIn("homepage_open", r, f"8766 应重定向 homepage_open, got: {r!r}")
        self.assertNotIn("dashboard_open", r)

    def test_t2_8765_redirects_to_dashboard(self):
        r = self._call("url_launcher_hands", "open_url",
                       {"url": "http://127.0.0.1:8765"})
        self.assertIn("dashboard_open", r, f"8765 应重定向 dashboard_open, got: {r!r}")

    def test_t3_organ_without_hands_suffix(self):
        r = self._call("url_launcher", "open_url",
                       {"url": "http://127.0.0.1:8766"})
        self.assertIn("homepage_open", r)

    def test_t4_command_open_alias(self):
        r = self._call("url_launcher_hands", "open",
                       {"url": "http://127.0.0.1:8765"})
        self.assertIn("dashboard_open", r)

    def test_t5_target_param_instead_of_url(self):
        r = self._call("url_launcher_hands", "open_url",
                       {"target": "http://127.0.0.1:8766"})
        self.assertIn("homepage_open", r)

    def test_t6_non_jarvis_url_not_redirected(self):
        r = self._call("url_launcher_hands", "open_url",
                       {"url": "https://www.google.com"})
        # 不该命中重定向 → 落 generic 路径, 空 registry 返 not mounted
        self.assertNotIn("homepage_open", r)
        self.assertNotIn("dashboard_open", r)
        self.assertIn("not mounted", r)

    def test_t7_localhost_form(self):
        r = self._call("url_launcher_hands", "open_url",
                       {"url": "http://localhost:8766/"})
        self.assertIn("homepage_open", r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
