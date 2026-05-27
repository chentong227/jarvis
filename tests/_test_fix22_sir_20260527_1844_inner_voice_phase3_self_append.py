# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 18:44 真愿景] InnerVoice Phase 3 — 主脑 reply self-append 回归.

Phase 3 工程: jarvis_chat_bypass.py 主对话 (stream_chat) + 主动 nudge
(stream_nudge) 末尾都加 voice append, 形成 jarvis 自我感知闭环.

测试覆盖 (8 testcase, 全静态 invariant + 1 dynamic VoiceEntry):

Step 3a — stream_chat self-append (4 testcase):
  - PH3_1: stream_chat 源码含 voice import + get_inner_voice_track 调用
  - PH3_2: source='self_reflection' intent='noting'
  - PH3_3: content template 'i replied to sir:' + meta kind='main_reply' +
           wants_voice=False + urgency=0.3
  - PH3_4: system_event skip (clean_intent starts with '[后台系统') +
           env disabled skip

Step 3b — stream_nudge self-append (3 testcase):
  - PH3_5: stream_nudge 源码含 voice import + 调用
  - PH3_6: content template 'i nudged sir' + meta kind='nudge_reply' +
           urgency=0.4 + wants_voice=False
  - PH3_7: source='self_reflection' intent='noting'

Step 3c — placement (1 testcase):
  - PH3_8: stream_chat voice append 必须在 RecentNudgeMemory record_nudge 之后
           (P3-BUG#1 anchor 在前), 在 ToM trigger 之前
"""
from __future__ import annotations

import os
import re
import sys
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


# ============================================================
# Step 3a — stream_chat self-append (静态源码 invariant)
# ============================================================

class TestStep3aStreamChatSelfAppend(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        path = os.path.join(_REPO, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            cls.src = f.read()
        # 隔离 stream_chat body
        # find 'def stream_chat(' ... 'def stream_nudge('
        m = re.search(
            r'def stream_chat\(self.*?(?=\n    def stream_nudge\()',
            cls.src, re.DOTALL,
        )
        assert m, 'stream_chat body not isolated'
        cls.chat_body = m.group(0)

    def test_ph3_1_stream_chat_has_voice_import(self):
        """PH3_1: stream_chat 源码含 voice import + get_inner_voice_track."""
        # voice append hook 必含
        self.assertIn(
            'jarvis_inner_voice_track', self.chat_body,
            'stream_chat must import jarvis_inner_voice_track'
        )
        self.assertIn(
            'get_inner_voice_track', self.chat_body,
            'stream_chat must call get_inner_voice_track'
        )

    def test_ph3_2_source_and_intent_correct(self):
        """PH3_2: source=self_reflection intent=noting."""
        # 必含 source='self_reflection' intent='noting' (kind=main_reply 区分)
        # 取 'main_reply' 后到下一个 except 的片段
        m = re.search(
            r"'main_reply'.*?except Exception:",
            self.chat_body, re.DOTALL,
        )
        self.assertIsNotNone(m, 'main_reply hook block not found')
        block = m.group(0)
        self.assertIn("source='self_reflection'", block)
        self.assertIn("intent='noting'", block)

    def test_ph3_3_content_template_meta_urgency_wants_voice(self):
        """PH3_3: content / meta / urgency / wants_voice 正确."""
        self.assertIn(
            "i replied to sir:", self.chat_body,
            'content template must say "i replied to sir:"'
        )
        self.assertIn(
            "'kind': 'main_reply'", self.chat_body,
            "meta kind='main_reply' required"
        )
        # urgency=0.3 wants_voice=False (具体在 main_reply hook)
        m = re.search(
            r"'main_reply'.*?wants_voice=False",
            self.chat_body, re.DOTALL,
        )
        self.assertIsNotNone(m,
            'wants_voice=False must be set in main_reply hook')
        # urgency=0.3 也必须在同段
        m2 = re.search(
            r"'main_reply'.*?urgency=0\.3",
            self.chat_body, re.DOTALL,
        )
        self.assertIsNotNone(m2,
            'urgency=0.3 must be set in main_reply hook')

    def test_ph3_4_system_event_and_env_disabled_skip(self):
        """PH3_4: system_event skip + env disabled skip."""
        # system_event 守门: clean_intent 以 '[后台系统' 开头
        self.assertIn(
            "'[后台系统'", self.chat_body,
            'must check clean_intent starts with [后台系统'
        )
        # env disabled 守门: is_enabled() check
        self.assertIn(
            'is_enabled', self.chat_body,
            'must check is_enabled() (env JARVIS_INNER_VOICE_ENABLED)'
        )


# ============================================================
# Step 3b — stream_nudge self-append
# ============================================================

class TestStep3bStreamNudgeSelfAppend(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        path = os.path.join(_REPO, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            cls.src = f.read()
        # 隔离 stream_nudge body (从 def stream_nudge 到 def 下一个或文件尾)
        m = re.search(
            r'def stream_nudge\(self.*?(?=\n    def \w|\Z)',
            cls.src, re.DOTALL,
        )
        assert m, 'stream_nudge body not isolated'
        cls.nudge_body = m.group(0)

    def test_ph3_5_stream_nudge_has_voice_import(self):
        """PH3_5: stream_nudge 含 voice import + 调用."""
        self.assertIn(
            'jarvis_inner_voice_track', self.nudge_body,
            'stream_nudge must import jarvis_inner_voice_track'
        )
        self.assertIn(
            'get_inner_voice_track', self.nudge_body,
            'stream_nudge must call get_inner_voice_track'
        )

    def test_ph3_6_nudge_content_meta_urgency(self):
        """PH3_6: nudge content / meta / urgency / wants_voice."""
        self.assertIn(
            'i nudged sir', self.nudge_body,
            'nudge content template must say "i nudged sir"'
        )
        self.assertIn(
            "'kind': 'nudge_reply'", self.nudge_body,
            "meta kind='nudge_reply' required"
        )
        # urgency=0.4 (略高于 reply 0.3)
        m = re.search(
            r"'nudge_reply'.*?urgency=0\.4",
            self.nudge_body, re.DOTALL,
        )
        self.assertIsNotNone(m, 'urgency=0.4 must be set in nudge_reply hook')
        # wants_voice=False (内部记账)
        m2 = re.search(
            r"'nudge_reply'.*?wants_voice=False",
            self.nudge_body, re.DOTALL,
        )
        self.assertIsNotNone(m2, 'wants_voice=False must be set in nudge_reply hook')

    def test_ph3_7_nudge_source_intent_correct(self):
        """PH3_7: nudge source=self_reflection intent=noting."""
        m = re.search(
            r"'nudge_reply'.*?except Exception:",
            self.nudge_body, re.DOTALL,
        )
        self.assertIsNotNone(m, 'nudge_reply hook block not found')
        block = m.group(0)
        self.assertIn("source='self_reflection'", block)
        self.assertIn("intent='noting'", block)


# ============================================================
# Step 3c — placement (hook 顺序)
# ============================================================

class TestStep3cPlacement(unittest.TestCase):

    def test_ph3_8_chat_hook_after_record_nudge_before_tom(self):
        """PH3_8: stream_chat voice hook 必须在 record_nudge 之后, ToM 之前."""
        path = os.path.join(_REPO, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        # 找 stream_chat body
        m_body = re.search(
            r'def stream_chat\(self.*?(?=\n    def stream_nudge\()',
            src, re.DOTALL,
        )
        chat_body = m_body.group(0)
        # 关键 anchor 顺序: record_nudge → main_reply voice hook → ToMReflector
        pos_rn = chat_body.find('P3-BUG#1')
        pos_voice = chat_body.find("'kind': 'main_reply'")
        pos_tom = chat_body.find('Gap 1 / P5-ToM')
        self.assertGreater(pos_rn, 0, 'P3-BUG#1 anchor not found in stream_chat')
        self.assertGreater(pos_voice, 0,
                              "main_reply voice hook not found in stream_chat")
        self.assertGreater(pos_tom, 0,
                              'ToMReflector anchor not found in stream_chat')
        self.assertLess(pos_rn, pos_voice,
                          'voice hook must be AFTER P3-BUG#1 record_nudge anchor')
        self.assertLess(pos_voice, pos_tom,
                          'voice hook must be BEFORE ToMReflector trigger')


if __name__ == '__main__':
    unittest.main(verbosity=2)
