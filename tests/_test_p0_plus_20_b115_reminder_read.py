# -*- coding: utf-8 -*-
"""[P0+20-β.1.15 / 2026-05-16] reminder_read_truth_source directive 回归测试

how_to_respond 段 2 (SMART ROUTING / TOOL USE / MEMORY WRITE / REMINDER READ)
已删除（搬到 L2 directive），14 号 directive reminder_read_truth_source 覆盖
"Sir 问代办事项" 这个 READ 路径，禁止 LLM 从 STM / projects 编造。

规范：详 docs/PROMPT_REFACTOR_PLAN.md §3 + AGENTS.md
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_directives import (
    DirectiveRegistry,
    DirectiveContext,
    bootstrap_default_registry,
    _user_input_is_reminder_read,
)


class TestReminderReadDetection(unittest.TestCase):
    """检测 'Sir 问代办' 模式（READ 路径）vs '记一下/提醒我' 模式（WRITE 路径）"""

    def test_english_read_phrasing(self):
        cases = [
            'what is on my plate today?',
            "what's on my plate?",
            'whats on my plate',
            'what is on my agenda',
            'what is on my schedule',
            'what are my reminders?',
            'show me my todos',
            'show me my todo list',
            'list my reminders',
            'proxy me my todos',
        ]
        for c in cases:
            self.assertTrue(_user_input_is_reminder_read(c),
                            f"Should match READ: {c!r}")

    def test_chinese_read_phrasing(self):
        cases = [
            '我的代办事项是什么',
            '我有什么待办',
            '今天有什么安排',
            '今天要做什么',
            '提醒我什么',
            '有什么事项',
        ]
        for c in cases:
            self.assertTrue(_user_input_is_reminder_read(c),
                            f"Should match Chinese READ: {c!r}")

    def test_write_intent_not_matched(self):
        """WRITE 路径（设新提醒/记一下）应被排除，走 correction_writepath_no_tool"""
        cases = [
            '提醒我明天 8 点起床',
            '记住这个',
            '记一下我刚说的',
            '明天 8 点去打球',
            '今晚 10 点去睡觉',
            'set a reminder for tomorrow',
            'schedule a meeting',
        ]
        for c in cases:
            self.assertFalse(_user_input_is_reminder_read(c),
                             f"Should NOT match (WRITE intent): {c!r}")

    def test_unrelated_input_not_matched(self):
        for c in ['hello', 'how are you', 'today is monday', 'open chrome',
                  '你好', '今天天气如何']:
            self.assertFalse(_user_input_is_reminder_read(c),
                             f"Should NOT match (unrelated): {c!r}")

    def test_empty_input(self):
        self.assertFalse(_user_input_is_reminder_read(''))
        self.assertFalse(_user_input_is_reminder_read(None))


class TestDirectiveTriggerIntegration(unittest.TestCase):
    """L2 directive trigger 集成"""

    def setUp(self):
        self.tmp = os.path.join('memory_pool', '_test_b115_int.json')
        self.r = DirectiveRegistry(persist_path=self.tmp)
        bootstrap_default_registry(self.r)

    def tearDown(self):
        try:
            os.remove(self.tmp)
        except Exception:
            pass

    def test_directive_registered(self):
        self.assertIn('reminder_read_truth_source', self.r.directives)
        d = self.r.directives['reminder_read_truth_source']
        self.assertEqual(d.priority, 9)
        self.assertEqual(d.source_marker, 'P0+20-β.1.15')

    def test_directive_text_keywords(self):
        d = self.r.directives['reminder_read_truth_source']
        for kw in ['ACTIVE REMINDERS', 'COMMITMENTS', 'VERBATIM',
                   'DO NOT manufacture', '承诺必行', '编造']:
            self.assertIn(kw, d.text, f"directive text 缺关键词: {kw}")

    def test_fires_on_read_phrasing(self):
        ctx = DirectiveContext(
            user_input='what are my reminders?',
            last_jarvis_reply='', stm=[],
            tier='SHORT_CHAT', ledger_data={},
            soul_tags=[], current_hour=14,
            has_active_plan=False, has_screenshot=False,
            working_feed_nonempty=False, last_tool_results=[],
        )
        fired = self.r.collect(ctx)
        fired_ids = [d.id for d in fired]
        self.assertIn('reminder_read_truth_source', fired_ids)

    def test_skips_on_write_phrasing(self):
        ctx = DirectiveContext(
            user_input='提醒我明天 8 点起床',
            last_jarvis_reply='', stm=[],
            tier='SHORT_CHAT', ledger_data={},
            soul_tags=[], current_hour=14,
            has_active_plan=False, has_screenshot=False,
            working_feed_nonempty=False, last_tool_results=[],
        )
        fired = self.r.collect(ctx)
        fired_ids = [d.id for d in fired]
        self.assertNotIn('reminder_read_truth_source', fired_ids)


class TestPersonaHowToRespondSlimmed(unittest.TestCase):
    """β.1.15 验证 PERSONA + how_to_respond 总体瘦身"""

    def test_persona_under_3000_chars(self):
        # 🩹 [β.2.9.6 / 2026-05-18] 上限 3000→5500. β.2.8.7 加 [INTEGRITY — CLAIM HONESTY]
        # 通用反幻觉条款 (Sir 准则 5 通用化) + β.2.9.1 加 future-action honesty 段, 涨到 ~4862.
        # 这些是必要的 integrity 防御不该裁. 仍 < 5500 防膨胀失控.
        from jarvis_central_nerve import JARVIS_CORE_PERSONA
        self.assertLess(len(JARVIS_CORE_PERSONA), 5500,
                        f"PERSONA 应 < 5500 chars (β.2.9.6 后), 实际 {len(JARVIS_CORE_PERSONA)}")

    def test_how_to_respond_block_does_not_contain_search_routing(self):
        """SMART ROUTING / TOOL USE 段已搬 L2，不应再在 how_to_respond 源码里"""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'jarvis_central_nerve.py'
        )
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        # 找 how_to_respond 块边界
        start = src.find("'how_to_respond'")
        end = src.find("ttl=86400.0", start)
        block = src[start:end] if start > 0 else ''
        # how_to_respond 块本身不应有 SMART ROUTING 段（已搬 L2）
        self.assertNotIn('[SMART ROUTING', block,
                         "how_to_respond 不应再含 [SMART ROUTING] 段（已搬 L2）")
        self.assertNotIn('[REMINDER/TODO LIST', block,
                         "how_to_respond 不应再含 [REMINDER/TODO LIST] 段（已搬 L2 reminder_read_truth_source）")


if __name__ == '__main__':
    unittest.main(verbosity=2)
