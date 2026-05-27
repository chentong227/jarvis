# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 12:25 真痛 anchor] 锁屏 screen grab failed 治本.

Sir 真测 (12:24:57):
  '睡觉了，拜拜' dismissal → stream_chat (主对话路径) →
  ImageGrab.grab() 抛 OSError 'screen grab failed' (锁屏不能截图) →
  外层 try 异常 → _try_local_fallback → Ollama 8s 空 → 罐头回复 →
  Sir 听不到自然 dismissal 回应.

根因: 3 个路径中 nudge (L6373-6418) 已 P5-fix33 治本 (inner try+text-only fallback),
但**主对话** (L3050) + **云端补答** (L2375) 没修.

修法: 同 nudge 路径模式, inner try/except 截图失败 → img_bytes=None →
已有 text-only chat_history 分支生效.

测试 (4 testcase):
  T1: stream_chat 截图代码块有 inner try/except
  T2: 主对话路径 fail 时 log 含 [Chat/NoScreenshot]
  T3: 云端补答路径有 inner try/except
  T4: nudge 路径 (旧 fix L6373) 仍存在 (regression guard)
"""
from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestLockedScreenGrabFix(unittest.TestCase):
    """3 路径 screen grab fail 治本."""

    @classmethod
    def setUpClass(cls):
        chat_path = os.path.join(ROOT, 'jarvis_chat_bypass.py')
        with open(chat_path, 'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_t1_stream_chat_has_inner_try_for_screen_grab(self):
        """主对话路径 (stream_chat L3050) 必有 inner try/except 包 ImageGrab."""
        # 找 Sir anchor marker (新加 fix marker)
        self.assertIn(
            'Sir 2026-05-27 12:25 真痛 anchor', self.src,
            "主对话路径必有 Sir 12:25 anchor marker"
        )
        # 必含 inner try + Chat/NoScreenshot log
        self.assertIn('Chat/NoScreenshot', self.src,
            "主对话路径 fail log 标签必为 'Chat/NoScreenshot'")
        self.assertIn('text-only fallback', self.src,
            "主对话路径 fail 必走 text-only fallback")

    def test_t2_main_chat_grab_fail_does_not_propagate(self):
        """模拟 ImageGrab.grab fail → img_bytes 必 None (text-only).

        实际单元测试 stream_chat 太重 — 我们检源码结构: ImageGrab.grab 调用
        必在 inner try 里, fail 后 img_bytes 必 set None.
        """
        # 找主对话路径 (Sir 12:25 anchor 区附近) - 用 anchor marker 定位
        idx_anchor = self.src.find('Sir 2026-05-27 12:25 真痛 anchor')
        self.assertGreater(idx_anchor, 0, "anchor marker 必存在")
        # anchor 后 1500 chars 范围内, 必有 'screen_img = ImageGrab.grab()' + 'img_bytes = None'
        snippet = self.src[idx_anchor:idx_anchor + 1500]
        self.assertIn('ImageGrab.grab()', snippet,
            "anchor 范围内必含 ImageGrab.grab() 调用")
        self.assertIn('img_bytes = None', snippet,
            "anchor 范围内 fail 必 set img_bytes = None")
        self.assertIn('except Exception as _ss_err', snippet,
            "anchor 范围内必有 except 捕获截图异常")

    def test_t3_cloud_fallback_has_inner_try(self):
        """云端补答路径 (L2375) 同 fix."""
        # 找云端补答 marker
        self.assertIn('CloudFallback/NoScreenshot', self.src,
            "云端补答路径 fail log 标签必为 'CloudFallback/NoScreenshot'")
        # 找 anchor 区
        idx_cf = self.src.find('CloudFallback/NoScreenshot')
        self.assertGreater(idx_cf, 0, "CloudFallback marker 必存在")
        # 反向找最近的 ImageGrab.grab() 必在 try 块内 (反查前 500 chars)
        prev_snippet = self.src[max(0, idx_cf - 500):idx_cf]
        self.assertIn('try:', prev_snippet,
            "云端补答 ImageGrab 调用必在 try 块内")
        self.assertIn('ImageGrab.grab()', prev_snippet,
            "云端补答 try 块内必含 ImageGrab.grab() 调用")

    def test_t4_nudge_path_old_fix_still_exists(self):
        """regression guard: nudge 路径 P5-fix33 (Nudge/NoScreenshot) 仍存在.

        不能因加新 fix 把旧 fix 删了.
        """
        self.assertIn('Nudge/NoScreenshot', self.src,
            "nudge 路径 P5-fix33 'Nudge/NoScreenshot' marker 必存在 (regression guard)")
        self.assertIn('P5-fix33', self.src,
            "P5-fix33 marker 必存在 (历史 fix 不能丢)")


if __name__ == '__main__':
    unittest.main(verbosity=2)
