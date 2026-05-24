# -*- coding: utf-8 -*-
"""[Reshape M6.5.3 / 2026-05-24] CentralNerve.run() 3-brain deprecation stub.

覆盖:
  - run() 立即 raise RuntimeError → existing except block 接管
  - chat_bypass.stream_chat 被调 (fallback 主脑 reply)
  - SWM event `deprecated_3_brain_invoked` 真 publish
  - state.set_active_task True → False 在 finally 走完
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestRunDeprecationStub(unittest.TestCase):
    def setUp(self):
        from jarvis_central_nerve import CentralNerve
        self.n = CentralNerve.__new__(CentralNerve)
        # set up minimal attributes for run() to reach raise + except block
        self.n.is_interrupted = False
        self.n.state = MagicMock()
        self.n.short_term_memory = []
        self.n.hand_manifests = {}
        self.n.chat_bypass = MagicMock()
        self.n.chat_bypass.translate_queue = MagicMock()
        self.n.chat_bypass.audio_queue = MagicMock()
        self.n.chat_bypass.last_ltm_context = ''
        self.n.voice_thread = None
        self.n._set_state = MagicMock()
        # _assemble_prompt 是真复杂, mock 掉
        self.n._assemble_prompt = MagicMock(return_value='[FAKE PROMPT]')
        # hands shutdown for finally clause
        self.n.hands = MagicMock()
        self.n.hands.shutdown = MagicMock()

    def test_raises_and_except_handled(self):
        """run() 进 try 立即 raise, except 调 chat_bypass.stream_chat fallback."""
        self.n.run('Sir, please open browser')
        # except block 调 chat_bypass.stream_chat
        self.n.chat_bypass.stream_chat.assert_called_once()
        # state set_active_task True (开头) + False (finally)
        calls = self.n.state.set_active_task.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].args[0], True)
        self.assertEqual(calls[1].args[0], False)

    def test_publishes_swm_deprecation_event(self):
        """deprecated_3_brain_invoked SWM event 真 publish."""
        with patch('jarvis_utils.get_event_bus') as mock_bus_get:
            mock_bus = MagicMock()
            mock_bus_get.return_value = mock_bus
            self.n.run('test cmd')
            # publish 至少调 1 次 (deprecated_3_brain_invoked event)
            self.assertGreaterEqual(mock_bus.publish.call_count, 1)
            # 看 publish 调用之中有没有 deprecated_3_brain_invoked etype
            etypes = [
                call.kwargs.get('etype') or
                (call.args[0] if call.args else None)
                for call in mock_bus.publish.call_args_list
            ]
            self.assertIn('deprecated_3_brain_invoked', etypes)

    def test_finally_resets_state_idle(self):
        """finally 块走 _set_state('IDLE')."""
        self.n.run('any input')
        # _set_state 至少调一次 IDLE (finally)
        idle_calls = [c for c in self.n._set_state.call_args_list if c.args[0] == 'IDLE']
        self.assertGreaterEqual(len(idle_calls), 1)

    def test_no_3_brain_attribute_accessed(self):
        """3-brain (None) 不应被访问 — raise 在 access self.right_brain 之前."""
        # right_brain/left_brain/l5_brain 留 None (mv 后状态)
        self.n.right_brain = None
        self.n.left_brain = None
        self.n.l5_brain = None
        # 不应 AttributeError, run() 优雅走 except + finally
        try:
            self.n.run('hi')
        except Exception as e:
            self.fail(f'run() 应优雅处理, 不向上 raise: {e}')


if __name__ == '__main__':
    unittest.main()
