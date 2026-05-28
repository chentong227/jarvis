# -*- coding: utf-8 -*-
r"""[Sir 2026-05-28 14:54 真痛 BUG] 裸 intent identifier 泄 TTS

Sir image 真实 case:
- 用户说 "面板面板打开面板"
- Jarvis subtitle 显示 "已为您打开面板, 先生." (干净)
- Jarvis **TTS 念出** 'intent_dashboard_open' (Sir 听到)

Root cause: 主脑 emit 纯 identifier 'intent_dashboard_open' 当 verbal hint,
没 JSON 包装, 没 <TOOL_CALL> tag. 3 个老 sanitizer 全 miss:
  - _STRUCTURAL_TAG_BLOCK_RE: 只剥 <TOOL_CALL>...</TOOL_CALL>
  - _STRAY_INTENT_JSON_RE: 只剥 '{"intent":"X"}'
  - _INTERNAL_TOOL_NAME_RE: 只剥 organ.command (含 dot)
  → 裸 'intent_dashboard_open' 走 TTS 念出.

修法 (双源同源):
  - jarvis_utils._INTERNAL_INTENT_IDENTIFIER_RE (scrub_internal_names 接入)
  - jarvis_safety._STRAY_INTENT_IDENTIFIER_RE (_strip_structural_tag_blocks 接入)

regex: r'\bintent[_:]\s*[a-z][a-z0-9_]*\b'
约束:
  - lowercase snake_case only (主脑 normal reply 不写 'intent_xxx' 全小写)
  - 必须 _ 或 : 连接 (不剥单独 "intent" 普通英语词)
  - \b 单词边界

False positive guard test:
  - 'What is your intent?' 不剥
  - 'My intent is clear.' 不剥
  - 'Intent matters.' 不剥
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSirImageIntentIdentifierLeak(unittest.TestCase):
    """Sir image 真痛: TTS 念出 'intent_dashboard_open'."""

    def test_l1_scrub_strips_intent_identifier_sir_image_case(self):
        """L1 Sir image 真实 reply: 主脑 emit 裸 identifier 在 reply 里."""
        from jarvis_utils import scrub_internal_names
        # Sir image 推测原文 (主脑 emit identifier 当 verbal hint 在 Done 之前)
        text = 'intent_dashboard_open Done, Sir.'
        out = scrub_internal_names(text)
        self.assertNotIn('intent_dashboard_open', out,
                         f"Sir image BUG: identifier 必须剥. Got: {out!r}")
        self.assertIn('Done, Sir.', out,
                      f"合法 reply 必须保留. Got: {out!r}")

    def test_l2_scrub_strips_intent_colon_form(self):
        """L2 'intent: dashboard_open' (空格分隔) 也剥."""
        from jarvis_utils import scrub_internal_names
        for variant in (
            'intent:dashboard_open',
            'intent: dashboard_open',
            'intent:  dashboard_open',
        ):
            text = f'{variant} now.'
            out = scrub_internal_names(text)
            self.assertNotIn('dashboard_open', out,
                             f"variant {variant!r}: 必须剥. Got: {out!r}")

    def test_l3_scrub_does_NOT_strip_normal_english(self):
        """L3 false positive guard: 普通英语 'intent' 不剥."""
        from jarvis_utils import scrub_internal_names
        safe_cases = [
            'What is your intent?',
            'My intent is clear.',
            'Intent matters here.',
            'The intent was misunderstood.',
            'Sir, your intent is unclear.',
        ]
        for case in safe_cases:
            out = scrub_internal_names(case)
            # 'intent' 词必须保留
            self.assertIn('intent', out.lower(),
                          f"普通英语 false positive! {case!r} → {out!r}")

    def test_l4_strip_structural_tag_blocks_same_regex(self):
        """L4 jarvis_safety 同源同 regex (双源一致, 避发散)."""
        from jarvis_safety import _strip_structural_tag_blocks
        text = 'intent_dashboard_open Done, Sir.'
        out = _strip_structural_tag_blocks(text)
        self.assertNotIn('intent_dashboard_open', out,
                         f"jarvis_safety 必须同源剥. Got: {out!r}")
        self.assertIn('Done, Sir.', out)

    def test_l5_has_internal_name_detects_intent_identifier(self):
        """L5 has_internal_name 真识别 intent identifier (audit/log 用)."""
        from jarvis_utils import has_internal_name
        self.assertTrue(has_internal_name('intent_dashboard_open Done, Sir.'),
                        '裸 identifier 必须被 has_internal_name 检出 (audit)')
        # 普通文本不 false positive
        self.assertFalse(has_internal_name('What is your intent, Sir?'),
                         '普通英语不 false positive')

    def test_l6_existing_intent_json_still_strips(self):
        """L6 不破坏 已有 _STRAY_INTENT_JSON_RE 行为."""
        from jarvis_utils import scrub_internal_names
        text = 'Done. {"intent": "dashboard_open"} now.'
        out = scrub_internal_names(text)
        self.assertNotIn('intent', out.lower().replace('done', ''),
                         f"裸 JSON 必须剥. Got: {out!r}")

    def test_l7_existing_tool_call_tag_still_strips(self):
        """L7 不破坏 已有 _INTERNAL_TOOL_CALL_TAG_RE 行为."""
        from jarvis_utils import scrub_internal_names
        text = 'Hello <TOOL_CALL>{"intent":"X"}</TOOL_CALL> world.'
        out = scrub_internal_names(text)
        self.assertNotIn('TOOL_CALL', out)
        self.assertIn('Hello', out)
        self.assertIn('world', out)

    def test_l8_all_17_known_intent_names_strip(self):
        """L8 17 个已知 intent name 全部 cover."""
        from jarvis_utils import scrub_internal_names
        known = [
            'check_top_cpu', 'list_processes', 'kill_process',
            'mute_audio', 'unmute_audio', 'set_volume',
            'pause_media', 'play_media', 'send_notification',
            'list_recent_files', 'search_memory',
            'dashboard_open', 'dashboard_close', 'focus_window',
            'system_info', 'set_reminder', 'list_reminders',
        ]
        for name in known:
            text = f'intent_{name} Done.'
            out = scrub_internal_names(text)
            self.assertNotIn(f'intent_{name}', out,
                             f"intent_{name} 必须剥. Got: {out!r}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
