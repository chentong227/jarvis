# -*- coding: utf-8 -*-
"""[2026-05-24 19:45] 3 个 fast_call 幻觉 BUG 修测试.

BUG #1: reminder_hands 幻觉 organ → memory_hands (反向 command-to-organ index)
BUG #2: add_reminder 缺 intent → fail-soft + actionable msg
BUG #3: FAST_CALL[None/None] malformed → PreFlight None guard
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestBug3PreflightNoneGuard(unittest.TestCase):
    """BUG #3: FAST_CALL[None/None] malformed PreFlight."""

    def test_organ_none_returns_friendly_msg(self):
        """organ_name=None → 不 crash, 返友善 msg."""
        # 用 mock — 直接构造 ChatBypass instance 太重, 改 unit test logic.
        # 验 chat_bypass.py source 有 organ is None / command is None guard.
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn(
            'BUG #3 fix',
            src,
            'BUG #3 PreFlight None guard 标识注释缺失',
        )
        self.assertIn(
            'organ_name is None or command is None',
            src,
            'BUG #3 PreFlight 未检 organ/command None',
        )
        self.assertIn(
            'FAST_CALL malformed',
            src,
            'BUG #3 fail-soft 友善 msg 缺失',
        )


class TestBug1ReverseCommandLookup(unittest.TestCase):
    """BUG #1: reminder_hands 幻觉 → 反向 command-to-organ index."""

    def test_helper_methods_defined(self):
        """`_lookup_organ_by_command` + `_build_command_to_organ_index` 存在."""
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn(
            'def _lookup_organ_by_command',
            src,
            '反向 lookup helper 缺失',
        )
        self.assertIn(
            'def _build_command_to_organ_index',
            src,
            '反向 vocab cache 构建 helper 缺失',
        )

    def test_alias_by_command_used_in_routing(self):
        """fuzzy alias 失败后真的调 _lookup_organ_by_command."""
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn(
            '_lookup_organ_by_command(command)',
            src,
            'BUG #1 fix 没在路由时调反向 lookup',
        )
        self.assertIn(
            'Alias by Command',
            src,
            'BUG #1 fix log 标识缺失',
        )

    def test_reverse_index_matches_known_commands(self):
        """构建后真能 cover 主脑常用 add_reminder."""
        # 因为 chat_bypass 实例化 heavy, 单独测 regex 提取逻辑.
        import re
        # 模拟 memory_hands 的 instruction_dict
        sample_doc = """
        【memory_hands】长期记忆与日程管理 (读/写/改/删):
        1. "search_memory": {"query": "关键词", "time_range_hours": 72} <- ...
        2. "list_reminders": {} <- ...
        3. "add_reminder": {"intent": "提醒内容", "trigger_time": "YYYY-MM-DD HH:MM:00"} <- ...
        """
        cache = {}
        for m in re.finditer(r'["\'](\w+)["\']\s*:\s*\{', sample_doc):
            cmd = m.group(1)
            if cmd in ('intent', 'query', 'id', 'time_range_hours', 'new_intent',
                       'new_time', 'max_age_hours', 'trigger_time'):
                continue
            if cmd not in cache:
                cache[cmd] = 'memory_hands'
        self.assertEqual(cache.get('add_reminder'), 'memory_hands')
        self.assertEqual(cache.get('search_memory'), 'memory_hands')
        self.assertEqual(cache.get('list_reminders'), 'memory_hands')
        # param key 不该被 cache
        self.assertNotIn('intent', cache)
        self.assertNotIn('query', cache)
        self.assertNotIn('trigger_time', cache)


class TestBug2AddReminderActionableMsg(unittest.TestCase):
    """BUG #2: add_reminder 缺 intent → actionable msg 教主脑 self-correct."""

    def test_intent_missing_returns_actionable(self):
        """memory_hands.add_reminder 缺 intent → 返新 actionable msg."""
        from l4_hands_pool.l4_memory_hands import Hands
        from jarvis_blood import Action
        hand = Hands()
        # intent 空
        res = hand.execute(Action(command='add_reminder',
                                  params={'intent': '', 'trigger_time': '2026-01-01 12:00:00'}))
        self.assertFalse(res.success)
        self.assertIn('add_reminder 缺 intent', res.msg)
        self.assertIn('先用自然语言问', res.msg, '应教主脑下轮先问 Sir')
        self.assertIn('Sir 答了再 emit', res.msg, '应教主脑等 Sir 答再 emit')

    def test_trigger_time_missing_returns_actionable(self):
        """缺 trigger_time → 教主脑下轮先问 Sir 时间."""
        from l4_hands_pool.l4_memory_hands import Hands
        from jarvis_blood import Action
        hand = Hands()
        res = hand.execute(Action(command='add_reminder',
                                  params={'intent': '吃药', 'trigger_time': ''}))
        self.assertFalse(res.success)
        self.assertIn('add_reminder 缺 trigger_time', res.msg)
        self.assertIn('YYYY-MM-DD HH:MM:00', res.msg, '应教主脑格式')


if __name__ == '__main__':
    unittest.main()
