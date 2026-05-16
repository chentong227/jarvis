# -*- coding: utf-8 -*-
"""[P0+20-β.1.11 / 2026-05-16] Phase 5 P5c 老 BUG 留尾：future-tense lie 治本

α.3 注释明示"不扩到 future-tense capability lie，那是 β.0 范围"，β.0 一直没修。
本 commit 在 L2 directive registry 加 13 号 directive `future_tense_capability_check`：
- 上一轮 Jarvis 答 "I can take a closer look" / "I'll see what I can do" /
  "我会去看一下" 等空头承诺 → 本轮注入诚实兜底 directive
- 强制 LLM 在本轮 (a) 用 FAST_CALL 真兑现 或 (b) 撤回承诺 ("On reflection, Sir,
  I don't actually have the means to look into that from here")

规范：详 docs/PROMPT_REFACTOR_PLAN.md / AGENTS.md
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_directives import (
    DirectiveRegistry,
    DirectiveContext,
    bootstrap_default_registry,
    _last_reply_has_future_capability_lie,
    _trigger_future_tense_capability_check,
)


class TestFutureTenseLieDetection(unittest.TestCase):
    """治本：检测 LLM 上一轮的 future-tense capability lie 模式"""

    def test_english_lie_patterns(self):
        cases = [
            "I can take a closer look at that, Sir.",
            "I can take a deeper look at the issue.",
            "I'll take a closer look right after this.",
            "I'll see what I can do, Sir.",
            "Let me look into that for you.",
            "Let me check on that.",
            "Let me investigate this further.",
            "I can look into the matter, Sir.",
            "I'll get back to you on that, Sir.",
            "I'll keep an eye on it for you.",
            "I can review the data and let you know.",
            "I can examine the logs more closely.",
            "Let me dig into the details.",
        ]
        for c in cases:
            self.assertTrue(_last_reply_has_future_capability_lie(c),
                            f"Should match future-tense lie: {c!r}")

    def test_chinese_lie_patterns(self):
        cases = [
            "我会去看一下，先生",
            "稍后为您跟进，先生",
            "让我研究一下",
            "我可以再深入看一下",
            "稍后再为您确认",
            "让我看一下",
            "我会再仔细看看",
            "我会再为您查一下",
            "我去深入了解一下",
            "让我研究一下这个问题",
        ]
        for c in cases:
            self.assertTrue(_last_reply_has_future_capability_lie(c),
                            f"Should match Chinese future-tense lie: {c!r}")

    def test_legitimate_phrasing_not_matched(self):
        """正常 affirmation / completion 不应误命中"""
        cases = [
            "Done, Sir.",
            "Yes, Sir.",
            "Understood, Sir.",
            "Acknowledged, Sir.",
            "I have adjusted the volume.",
            "I've set the reminder.",
            "明白了，先生",
            "好的",
            "已为您调整",
            "I cannot do that, Sir.",
            "That's outside my reach.",
        ]
        for c in cases:
            self.assertFalse(_last_reply_has_future_capability_lie(c),
                             f"Should NOT match legitimate phrasing: {c!r}")

    def test_empty_or_short_input(self):
        for c in ["", " ", "ok", "Yes"]:
            self.assertFalse(_last_reply_has_future_capability_lie(c))


class TestFutureTenseLieDirectiveTrigger(unittest.TestCase):
    """L2 directive trigger 集成"""

    def test_trigger_fires_when_last_reply_lies(self):
        ctx = DirectiveContext(
            user_input="thanks",
            last_jarvis_reply="I'll see what I can do, Sir.",
            stm=[], tier='SHORT_CHAT', ledger_data={},
            soul_tags=[], current_hour=14,
            has_active_plan=False, has_screenshot=False,
            working_feed_nonempty=False, last_tool_results=[],
        )
        self.assertTrue(_trigger_future_tense_capability_check(ctx))

    def test_trigger_skips_when_last_reply_is_clean(self):
        ctx = DirectiveContext(
            user_input="thanks",
            last_jarvis_reply="Done, Sir.",
            stm=[], tier='SHORT_CHAT', ledger_data={},
            soul_tags=[], current_hour=14,
            has_active_plan=False, has_screenshot=False,
            working_feed_nonempty=False, last_tool_results=[],
        )
        self.assertFalse(_trigger_future_tense_capability_check(ctx))


class TestRegistryHasNewDirective(unittest.TestCase):
    """bootstrap 后必须有 13 条 directive，新增的在内"""

    def test_bootstrap_count_is_13(self):
        # β.1.15 加 reminder_read_truth_source 后变 14
        reg = DirectiveRegistry(persist_path=os.path.join('memory_pool', '_test_count.json'))
        n = bootstrap_default_registry(reg)
        try:
            self.assertEqual(n, 14)
            self.assertIn('future_tense_capability_check', reg.directives)
            d = reg.directives['future_tense_capability_check']
            self.assertEqual(d.priority, 9)
            self.assertEqual(d.source_marker, 'P0+20-β.1.11')
        finally:
            try:
                os.remove(os.path.join('memory_pool', '_test_count.json'))
            except Exception:
                pass

    def test_directive_text_contains_required_keywords(self):
        reg = DirectiveRegistry(persist_path=os.path.join('memory_pool', '_test_text.json'))
        bootstrap_default_registry(reg)
        try:
            text = reg.directives['future_tense_capability_check'].text
            for kw in ['FUTURE-TENSE CAPABILITY CHECK', 'FORBIDDEN', 'FAST_CALL',
                       'withdraw', 'On reflection']:
                self.assertIn(kw, text, f"directive text 缺关键词: {kw}")
        finally:
            try:
                os.remove(os.path.join('memory_pool', '_test_text.json'))
            except Exception:
                pass


if __name__ == '__main__':
    unittest.main()
