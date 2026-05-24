# -*- coding: utf-8 -*-
"""[Sir 2026-05-24 23:24 真测追根 BUG 治本] FAST_CALL vs TOOL_CALL channel boundary.

源 BUG (turn_20260524_232427):
  Sir: "早上7点叫我"
  主脑 emit: <TOOL_CALL>{"intent": "memory_hands/add_reminder",
                          "trigger_time": "2026-05-25 07:00:00"}</TOOL_CALL>
  → IntentRouter.resolve_intent('memory_hands/add_reminder') → None
  → 'unknown_intent' silently fail
  → 主脑虚报 "I have set a reminder" → ClaimTracer 4/4 unverified
  → Integrity Check 拦 (no_tool_called)
  → 下轮 INTEGRITY/Alert prepend → 主脑道歉 → PreFlight Q1 拦 unsolicited

3 层根因:
  1. intent_to_tool_map.json 缺 reminder 类 intent (14 个 hand-picked, 没 reminder)
  2. IntentParser 严格: 不容错 organ/command 路径 + 不容错 args 顶层平铺
  3. directive 没明确 channel 边界 — 主脑混 FAST_CALL/TOOL_CALL

修法 (A+B+C, Sir 拍板):
  A. intent_map 加 set_reminder + list_reminders 2 个 intent (cancel 走 FAST_CALL/delete_record)
  B. IntentParser 容错: intent='organ/command' passthrough + args 顶层 key 平铺
  C. directive `channel_boundary_fast_call_vs_tool_call` priority=14 明确教

本 test 验:
  A: intent_map 含 set_reminder + list_reminders, tool 正确
  B: IntentParser 接 organ/command intent + 顶层 trigger_time 平铺进 args
  B: IntentRouter passthrough mode (未注册但 organ/command → 容错 invoke)
  C: directive 含 channel_boundary 教导 + priority=14
"""
import os
import json
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


# ============================================================
# A. intent_map 加 set_reminder + list_reminders
# ============================================================

class TestAIntentMapReminderAdded(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        path = os.path.join(ROOT, 'memory_pool', 'intent_to_tool_map.json')
        with open(path, 'r', encoding='utf-8') as f:
            cls.data = json.load(f)

    def test_set_reminder_registered(self):
        intents = {c['id']: c for c in self.data.get('intents', [])}
        self.assertIn('set_reminder', intents)
        self.assertEqual(intents['set_reminder']['tool'], 'memory_hands.add_reminder')
        self.assertEqual(intents['set_reminder']['state'], 'active')

    def test_list_reminders_registered(self):
        intents = {c['id']: c for c in self.data.get('intents', [])}
        self.assertIn('list_reminders', intents)
        self.assertEqual(intents['list_reminders']['tool'], 'memory_hands.list_reminders')

    def test_cancel_reminder_NOT_registered_doc_explains_why(self):
        """cancel_reminder 故意不 register, _doc 解释为何."""
        intents = {c['id']: c for c in self.data.get('intents', [])}
        self.assertNotIn('cancel_reminder', intents,
                         'cancel_reminder 不应 register (走 FAST_CALL delete_record)')
        self.assertIn('_doc_cancel_reminder', self.data)


# ============================================================
# B. IntentParser 容错
# ============================================================

class TestBIntentParserTolerant(unittest.TestCase):

    def test_intent_with_dot_converted_to_slash(self):
        from jarvis_intent_router import IntentParser
        text = '<TOOL_CALL>{"intent": "memory_hands.add_reminder"}</TOOL_CALL>'
        calls = IntentParser.extract_all(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].intent_id, 'memory_hands/add_reminder',
                         '. 应转 /')

    def test_top_level_args_flattened_to_args_dict(self):
        from jarvis_intent_router import IntentParser
        # Sir 真测的实际格式: trigger_time 在顶层
        text = ('<TOOL_CALL>{"intent": "memory_hands/add_reminder", '
                '"trigger_time": "2026-05-25 07:00:00"}</TOOL_CALL>')
        calls = IntentParser.extract_all(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].intent_id, 'memory_hands/add_reminder')
        # 顶层 trigger_time 应被收进 args
        self.assertIn('trigger_time', calls[0].args)
        self.assertEqual(calls[0].args['trigger_time'], '2026-05-25 07:00:00')

    def test_explicit_args_takes_priority_over_top_level(self):
        """args 中显式给的优先于顶层平铺 (防意外覆盖)."""
        from jarvis_intent_router import IntentParser
        text = ('<TOOL_CALL>{"intent": "X", "trigger_time": "TOP", '
                '"args": {"trigger_time": "EXPLICIT"}}</TOOL_CALL>')
        calls = IntentParser.extract_all(text)
        self.assertEqual(calls[0].args['trigger_time'], 'EXPLICIT',
                         'args 显式给的优先')

    def test_reserved_keys_not_flattened(self):
        """intent / args 字段不应进 args dict 自身."""
        from jarvis_intent_router import IntentParser
        text = '<TOOL_CALL>{"intent": "X", "args": {"foo": 1}}</TOOL_CALL>'
        calls = IntentParser.extract_all(text)
        self.assertNotIn('intent', calls[0].args)
        self.assertNotIn('args', calls[0].args)

    def test_passthrough_invokes_organ_command_directly(self):
        """IntentRouter 未注册 intent 但形如 organ/command → 容错 invoke."""
        from jarvis_intent_router import IntentRouter, IntentCall

        invoked = []

        def _fake_executor(organ, command, params):
            invoked.append((organ, command, params))
            return '✅ test fake'

        router = IntentRouter(
            fast_call_executor=_fake_executor,
            event_bus=None,
            intent_map_path='/nonexistent/intent_map.json',  # 空 map
        )
        call = IntentCall(
            intent_id='memory_hands/add_reminder',
            args={'intent': 'X', 'trigger_time': '2026-05-25 07:00:00'},
        )
        result = router.route_and_invoke(call)
        self.assertTrue(result['success'], 'passthrough 应 invoke 成功')
        self.assertEqual(result['tool'], 'memory_hands.add_reminder')
        self.assertEqual(len(invoked), 1)
        self.assertEqual(invoked[0][0], 'memory_hands')
        self.assertEqual(invoked[0][1], 'add_reminder')


# ============================================================
# C. directive channel_boundary 教导
# ============================================================

class TestCChannelBoundaryDirective(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_directives.py'),
                  'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_directive_id_registered(self):
        self.assertIn("id='channel_boundary_fast_call_vs_tool_call'", self.src)

    def test_priority_14(self):
        """priority=14 最高档 — 必 inject."""
        idx = self.src.find("id='channel_boundary_fast_call_vs_tool_call'")
        self.assertGreater(idx, 0)
        section = self.src[idx:idx + 500]
        self.assertIn('priority=14', section,
                      'channel_boundary priority 必须 14')

    def test_teaches_fast_call_vs_tool_call_boundary(self):
        idx = self.src.find("id='channel_boundary_fast_call_vs_tool_call'")
        section = self.src[idx:idx + 5000]
        self.assertIn('FAST_CALL', section)
        self.assertIn('TOOL_CALL', section)
        self.assertIn('intent_to_tool_map', section)
        # 教 forbidden patterns
        self.assertIn('memory_hands/add_reminder', section)
        # 教 canonical examples
        self.assertIn('"organ":"memory_hands"', section)
        self.assertIn('"intent":"set_reminder"', section)
        self.assertIn('RULE OF THUMB', section)


# ============================================================
# D. concerns.progress_update handler (上轮 Sir 真测追根另一 BUG)
# ============================================================

class TestDConcernsProgressUpdateHandler(unittest.TestCase):
    """[Sir 2026-05-24 23:01 真测] concerns.progress_update handler 漏写, 也修了."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'),
                  'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_progress_update_handler_present(self):
        self.assertIn('command == "progress_update"', self.src,
                      'concerns FAST_CALL handler 必须有 progress_update 分支')

    def test_handler_calls_record_user_feedback(self):
        idx = self.src.find('command == "progress_update"')
        section = self.src[idx:idx + 2500]
        self.assertIn('record_user_feedback', section,
                      'progress_update 必须调 ConcernsLedger.record_user_feedback')

    def test_supports_directive_taught_params(self):
        """handler 接 concern_id / current / target / unit 4 个 params (directive 教的)."""
        idx = self.src.find('command == "progress_update"')
        section = self.src[idx:idx + 2500]
        for p in ('concern_id', 'current', 'target', 'unit'):
            self.assertIn(f"'{p}'", section, f'必须接 {p} param')

    def test_error_msg_lists_supported_commands(self):
        """fallback 错误信息列已支持的全部命令."""
        self.assertIn('dismiss/reactivate/progress_update', self.src,
                      'fallback msg 必须列 progress_update')

    def test_translator_schema_registered(self):
        """translator schema 也注册了 concerns.progress_update."""
        path = os.path.join(ROOT, 'memory_pool', 'translator_schema_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        organs = {(s['organ'], s['command']) for s in data.get('schema_hints', [])}
        self.assertIn(('concerns', 'progress_update'), organs,
                      'translator schema 必须注册 concerns.progress_update')


# ============================================================
# E. Tool Chain dedup 文案真话 (不撒谎 "上一次已成功")
# ============================================================

class TestEDedupHonestMessage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'),
                  'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_dedup_checks_last_tool_result_status(self):
        """dedup 文案应检查 _tool_results 最后 ✅/❌ 真情况."""
        idx = self.src.find('检测到重复调用')
        self.assertGreater(idx, 0)
        # 向前找上下文 (含 _last_status 判断)
        section = self.src[max(0, idx - 1500):idx + 500]
        self.assertIn('_last_status', section,
                      'dedup 必须区分 success/fail (_last_status 变量)')
        self.assertIn('上一次失败', section,
                      'dedup 必须支持 "上一次失败" 文案')


if __name__ == '__main__':
    unittest.main()
