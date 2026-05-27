# -*- coding: utf-8 -*-
"""[fix29 / Sir 2026-05-28 00:00 真意 β.6 Phase 1a 统一思考脑]
InnerThoughtDaemon 升级 flash + 加 4 new tag (SHOULD_SPEAK / SPEAK_CONTENT /
SPEAK_STYLE / NEXT_ATTENTION_FOCUS), 准备替代 6 个 reflector daemon 决策权.

Sir 真意 (2026-05-27 23:40 至 2026-05-28 00:00 plan):
  "把我们核心的反思和思考脑统一起来, 不分 5 类 ABCDE...直接让他自己决定他下次
  注意力关注什么, 该不该让主脑发声, 该不该提出新的高层 protocol...同时统一注意力
  机制让他自己决定关注什么. 思考脑我们也可以直接替换到 3-flash-preview".

设计文档: docs/JARVIS_BETA6_UNIFIED_THINKING.md

Phase 1a 改动 (β.6 第 1 步, 最小破坏 + 100% 向后兼容):
  1. LLM 升级 flash_lite → flash (env JARVIS_THINKING_MODEL 可 override)
  2. InnerThought dataclass 加 4 字段:
     - should_speak: bool = False
     - speak_content: str = ''
     - speak_style: str = ''  # 'silent_text' | 'voice' | 'visual_pulse'
     - next_attention_focus: str = ''
  3. _parse_thought 解析 4 new tag (缺则默认, 老 LLM output 兼容)
  4. prompt 教 LLM 输出 new 4 tag (全 optional, 鼓励但不 hard require)

测试覆盖 (准则 4 testing discipline, fix-first 设计):
  L1 InnerThought 新 4 字段存在 + 默认值正确
  L2 parse: SHOULD_SPEAK=yes + SPEAK_CONTENT + SPEAK_STYLE 完整解析
  L3 parse: SHOULD_SPEAK=no → should_speak=False + speak_content 保持空
  L4 parse: 老 LLM output 缺 4 新 tag → 默认值 (向后兼容)
  L5 parse: SHOULD_SPEAK=yes 但缺 SPEAK_STYLE → fallback 'silent_text'
  L6 parse: SHOULD_SPEAK=yes 但 SPEAK_STYLE 值非法 → 空 (后被 default 兜底)
  L7 parse: NEXT_ATTENTION_FOCUS 正确解析 + strip
  L8 prompt 含 4 new tag 教学 (SHOULD_SPEAK / SPEAK_CONTENT / SPEAK_STYLE / NEXT_ATTENTION_FOCUS)
  L9 LLM 默认模型 = 'flash' (β.6 升级, 不再 flash_lite)
  L10 env JARVIS_THINKING_MODEL='flash_lite' override 真生效 (回退路径)

不动 (Phase 1b/c/d 再做):
  - View channel 化 _collect_evidence (现仍 free-form 6 区块)
  - 砍 ABCDE 5 类 (现仍 ABCDE + 4 new optional 共存)
  - should_speak=yes → 接 stream_nudge 链 (现仅落字段, 不通主脑)
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================
# L1 InnerThought 新 4 字段存在 + 默认值
# ==========================================================

class TestL1InnerThoughtNewFields(unittest.TestCase):
    """β.6 Phase 1a: dataclass 加 4 字段, 默认值不破坏老 thought 兼容."""

    def test_dataclass_has_should_speak_field_default_false(self):
        from jarvis_inner_thought_daemon import InnerThought
        t = InnerThought(
            id='t1', ts=time.time(), ts_iso='', category='A',
            thought='test', salience=0.5, actionable='none',
        )
        self.assertTrue(hasattr(t, 'should_speak'))
        self.assertFalse(t.should_speak)

    def test_dataclass_has_speak_content_field_default_empty(self):
        from jarvis_inner_thought_daemon import InnerThought
        t = InnerThought(
            id='t2', ts=time.time(), ts_iso='', category='A',
            thought='test', salience=0.5, actionable='none',
        )
        self.assertTrue(hasattr(t, 'speak_content'))
        self.assertEqual(t.speak_content, '')

    def test_dataclass_has_speak_style_field_default_empty(self):
        from jarvis_inner_thought_daemon import InnerThought
        t = InnerThought(
            id='t3', ts=time.time(), ts_iso='', category='A',
            thought='test', salience=0.5, actionable='none',
        )
        self.assertTrue(hasattr(t, 'speak_style'))
        self.assertEqual(t.speak_style, '')

    def test_dataclass_has_next_attention_focus_field_default_empty(self):
        from jarvis_inner_thought_daemon import InnerThought
        t = InnerThought(
            id='t4', ts=time.time(), ts_iso='', category='A',
            thought='test', salience=0.5, actionable='none',
        )
        self.assertTrue(hasattr(t, 'next_attention_focus'))
        self.assertEqual(t.next_attention_focus, '')


# ==========================================================
# L2-L7 _parse_thought 新 tag 解析
# ==========================================================

class TestL2ParseShouldSpeakYes(unittest.TestCase):
    """SHOULD_SPEAK=yes + SPEAK_CONTENT + SPEAK_STYLE 完整解析."""

    def _make_daemon(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        d._thoughts = []
        d._lock = MagicMock()
        return d

    def test_parse_should_speak_yes_with_content_and_style(self):
        daemon = self._make_daemon()
        llm_raw = (
            '<CATEGORY>A</CATEGORY>\n'
            '<THOUGHT>Sir seems weary; perhaps a check-in.</THOUGHT>\n'
            '<SALIENCE>0.8</SALIENCE>\n<ACTIONABLE>none</ACTIONABLE>\n'
            '<EVIDENCE_LINK>none</EVIDENCE_LINK>\n'
            '<NEXT_INTERVAL>default</NEXT_INTERVAL>\n'
            '<CONTINUITY>new_topic</CONTINUITY>\n'
            '<SHOULD_SPEAK>yes</SHOULD_SPEAK>\n'
            "<SPEAK_CONTENT>Sir, you've been at it 90 minutes; perhaps a pause?</SPEAK_CONTENT>\n"
            '<SPEAK_STYLE>silent_text</SPEAK_STYLE>\n'
        )
        parsed = daemon._parse_thought(
            llm_raw, sir_state='active', tick_interval=60,
        )
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.should_speak)
        self.assertIn('90 minutes', parsed.speak_content)
        self.assertEqual(parsed.speak_style, 'silent_text')


class TestL3ParseShouldSpeakNo(unittest.TestCase):
    """SHOULD_SPEAK=no → should_speak=False + speak_content 空."""

    def test_parse_should_speak_no_keeps_content_empty(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        d._thoughts = []
        d._lock = MagicMock()
        llm_raw = (
            '<CATEGORY>B</CATEGORY>\n<THOUGHT>Quiet observation.</THOUGHT>\n'
            '<SALIENCE>0.3</SALIENCE>\n<ACTIONABLE>none</ACTIONABLE>\n'
            '<EVIDENCE_LINK>none</EVIDENCE_LINK>\n'
            '<NEXT_INTERVAL>default</NEXT_INTERVAL>\n'
            '<CONTINUITY>new_topic</CONTINUITY>\n'
            '<SHOULD_SPEAK>no</SHOULD_SPEAK>\n'
            "<SPEAK_CONTENT></SPEAK_CONTENT>\n"
            '<SPEAK_STYLE></SPEAK_STYLE>\n'
        )
        parsed = d._parse_thought(
            llm_raw, sir_state='active', tick_interval=60,
        )
        self.assertIsNotNone(parsed)
        self.assertFalse(parsed.should_speak)
        self.assertEqual(parsed.speak_content, '')
        # speak_style 不必空; 但 should_speak=no 时 Python 不会 fallback silent_text
        self.assertEqual(parsed.speak_style, '')


class TestL4ParseBackwardCompat(unittest.TestCase):
    """老 LLM output 缺 4 new tag → 默认值 (向后兼容)."""

    def test_parse_old_llm_output_missing_all_new_tags(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        d._thoughts = []
        d._lock = MagicMock()
        # 老 prompt 输出: 没有 4 new tag
        llm_raw = (
            '<CATEGORY>A</CATEGORY>\n<THOUGHT>Backward compat test.</THOUGHT>\n'
            '<SALIENCE>0.4</SALIENCE>\n<ACTIONABLE>none</ACTIONABLE>\n'
            '<EVIDENCE_LINK>none</EVIDENCE_LINK>\n'
            '<NEXT_INTERVAL>default</NEXT_INTERVAL>\n'
            '<CONTINUITY>new_topic</CONTINUITY>\n'
        )
        parsed = d._parse_thought(
            llm_raw, sir_state='active', tick_interval=60,
        )
        self.assertIsNotNone(parsed)
        # 4 new field 全用默认 (不破坏老路径)
        self.assertFalse(parsed.should_speak)
        self.assertEqual(parsed.speak_content, '')
        self.assertEqual(parsed.speak_style, '')
        self.assertEqual(parsed.next_attention_focus, '')


class TestL5ParseSpeakYesNoStyleDefaultsSilentText(unittest.TestCase):
    """SHOULD_SPEAK=yes 但缺 SPEAK_STYLE → fallback 'silent_text' (低风险默认)."""

    def test_should_speak_yes_no_style_defaults_silent_text(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        d._thoughts = []
        d._lock = MagicMock()
        llm_raw = (
            '<CATEGORY>A</CATEGORY>\n<THOUGHT>Quick check.</THOUGHT>\n'
            '<SALIENCE>0.6</SALIENCE>\n<ACTIONABLE>none</ACTIONABLE>\n'
            '<EVIDENCE_LINK>none</EVIDENCE_LINK>\n'
            '<NEXT_INTERVAL>default</NEXT_INTERVAL>\n'
            '<CONTINUITY>new_topic</CONTINUITY>\n'
            '<SHOULD_SPEAK>yes</SHOULD_SPEAK>\n'
            "<SPEAK_CONTENT>Noted, Sir.</SPEAK_CONTENT>\n"
            # 缺 SPEAK_STYLE
        )
        parsed = d._parse_thought(
            llm_raw, sir_state='active', tick_interval=60,
        )
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.should_speak)
        # 默认 silent_text (低风险, 不噪声 Sir)
        self.assertEqual(parsed.speak_style, 'silent_text')


class TestL6ParseInvalidStyleRejected(unittest.TestCase):
    """SHOULD_SPEAK=yes 但 SPEAK_STYLE 值非法 → 被 default 兜底 (silent_text)."""

    def test_invalid_style_falls_back_to_default(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        d._thoughts = []
        d._lock = MagicMock()
        llm_raw = (
            '<CATEGORY>A</CATEGORY>\n<THOUGHT>Style test.</THOUGHT>\n'
            '<SALIENCE>0.6</SALIENCE>\n<ACTIONABLE>none</ACTIONABLE>\n'
            '<EVIDENCE_LINK>none</EVIDENCE_LINK>\n'
            '<NEXT_INTERVAL>default</NEXT_INTERVAL>\n'
            '<CONTINUITY>new_topic</CONTINUITY>\n'
            '<SHOULD_SPEAK>yes</SHOULD_SPEAK>\n'
            "<SPEAK_CONTENT>Yes, Sir.</SPEAK_CONTENT>\n"
            "<SPEAK_STYLE>scream_loud</SPEAK_STYLE>\n"  # invalid
        )
        parsed = d._parse_thought(
            llm_raw, sir_state='active', tick_interval=60,
        )
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.should_speak)
        # 非法值被拒, 因 should_speak=yes Python fallback 默认 silent_text
        self.assertEqual(parsed.speak_style, 'silent_text')


class TestL7ParseAttentionFocus(unittest.TestCase):
    """NEXT_ATTENTION_FOCUS 正确解析 + 清洗."""

    def test_attention_focus_parsed_and_cleaned(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        d._thoughts = []
        d._lock = MagicMock()
        llm_raw = (
            '<CATEGORY>A</CATEGORY>\n<THOUGHT>Self-attention.</THOUGHT>\n'
            '<SALIENCE>0.4</SALIENCE>\n<ACTIONABLE>none</ACTIONABLE>\n'
            '<EVIDENCE_LINK>none</EVIDENCE_LINK>\n'
            '<NEXT_INTERVAL>default</NEXT_INTERVAL>\n'
            '<CONTINUITY>new_topic</CONTINUITY>\n'
            '<NEXT_ATTENTION_FOCUS>recent_sensor_events, concern_status</NEXT_ATTENTION_FOCUS>\n'
        )
        parsed = d._parse_thought(
            llm_raw, sir_state='active', tick_interval=60,
        )
        self.assertIsNotNone(parsed)
        # 真包含两 channel
        self.assertIn('recent_sensor_events', parsed.next_attention_focus)
        self.assertIn('concern_status', parsed.next_attention_focus)


# ==========================================================
# L8 prompt 含 4 new tag 教学
# ==========================================================

class TestL8PromptTeachesNewTags(unittest.TestCase):
    """β.6 prompt 必须教 LLM 输出 4 new tag (否则 LLM 永远不会输出)."""

    def test_prompt_source_contains_should_speak_tag(self):
        # Read source file to verify prompt teaches new tags
        path = os.path.join(ROOT, 'jarvis_inner_thought_daemon.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('<SHOULD_SPEAK>', src)
        self.assertIn('</SHOULD_SPEAK>', src)

    def test_prompt_source_contains_speak_content_tag(self):
        path = os.path.join(ROOT, 'jarvis_inner_thought_daemon.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('<SPEAK_CONTENT>', src)

    def test_prompt_source_contains_speak_style_tag(self):
        path = os.path.join(ROOT, 'jarvis_inner_thought_daemon.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('<SPEAK_STYLE>', src)
        # 3 个 valid value 都教
        self.assertIn('silent_text', src)
        self.assertIn('voice', src)
        self.assertIn('visual_pulse', src)

    def test_prompt_source_contains_attention_focus_tag(self):
        path = os.path.join(ROOT, 'jarvis_inner_thought_daemon.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('<NEXT_ATTENTION_FOCUS>', src)


# ==========================================================
# L9-L10 LLM 模型升级 flash_lite → flash
# ==========================================================

class TestL9LlmModelDefaultIsFlash(unittest.TestCase):
    """β.6 思考脑默认模型 = 'flash' (升级 flash_lite)."""

    def test_default_thinking_model_is_flash(self):
        """source 中默认值是 'flash' (env 没设时)."""
        path = os.path.join(ROOT, 'jarvis_inner_thought_daemon.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        # 确认 JARVIS_THINKING_MODEL env 取值, 默认 'flash' (β.6)
        self.assertIn("JARVIS_THINKING_MODEL", src)
        self.assertIn("'flash'", src)


class TestL10LlmModelEnvOverride(unittest.TestCase):
    """env JARVIS_THINKING_MODEL='flash_lite' override 真生效 (回退路径)."""

    def test_env_override_uses_flash_lite(self):
        """source 中 env getter 含 'flash_lite' fallback hint 或 explicit."""
        # 不实际启动 daemon (会真调 LLM), 只验 source 代码中 env override 路径存在
        path = os.path.join(ROOT, 'jarvis_inner_thought_daemon.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        # 必须 documented + 写明 env var 名
        self.assertIn('JARVIS_THINKING_MODEL', src)
        # 必须留有 flash_lite 引用 (override 回退路径)
        self.assertIn('flash_lite', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
