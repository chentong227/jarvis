# -*- coding: utf-8 -*-
"""[Reshape M6.1 third wave / 2026-05-24] Soul layer 0/1/2/3 抽 helper.

覆盖:
  - Layer 0 self_anchor.build_block called
  - Layer 1 concern summon detection + preflight gating
  - Layer 1 副作用 self._soul_concern_inject_reason 设置
  - Layer 2 复用 _soul_concern_inject_reason 决定 baggage
  - Layer 3 attention_block 调 build_attention_block
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestLayer0SelfAnchor(unittest.TestCase):
    def test_returns_block_when_anchor_set(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        sa = MagicMock()
        sa.build_block = MagicMock(return_value='[ANCHOR] I am JARVIS')
        n.self_anchor = sa
        result = n._build_layer_0_self_anchor_block()
        self.assertEqual(result, '[ANCHOR] I am JARVIS')
        sa.build_block.assert_called_once_with(max_chars=1700)

    def test_returns_empty_when_anchor_none(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.self_anchor = None
        self.assertEqual(n._build_layer_0_self_anchor_block(), '')


class TestLayer1Concerns(unittest.TestCase):
    def test_summon_detected_inject(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        cl = MagicMock()
        cl.to_prompt_block = MagicMock(return_value='[CONCERNS] keyrouter')
        n.concerns_ledger = cl
        n.event_bus = None
        with patch('jarvis_concern_summon.is_summoned', return_value=True):
            result = n._build_layer_1_concerns_block('any concern about Sir?')
        self.assertEqual(result, '[CONCERNS] keyrouter')
        self.assertEqual(n._soul_concern_inject_reason, 'summon')

    def test_silent_when_no_summon_no_preflight(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        cl = MagicMock()
        n.concerns_ledger = cl
        n.event_bus = None
        with patch('jarvis_concern_summon.is_summoned', return_value=False):
            result = n._build_layer_1_concerns_block('hello')
        self.assertEqual(result, '')
        self.assertEqual(n._soul_concern_inject_reason, 'silent')

    def test_preflight_failed_inject(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        cl = MagicMock()
        cl.to_prompt_block = MagicMock(return_value='[CONCERNS]')
        n.concerns_ledger = cl
        bus = MagicMock()
        bus.recent_events = MagicMock(return_value=[
            {'metadata': {'verdict': 'edit'}}
        ])
        n.event_bus = bus
        with patch('jarvis_concern_summon.is_summoned', return_value=False):
            result = n._build_layer_1_concerns_block('hi')
        self.assertEqual(result, '[CONCERNS]')
        self.assertEqual(n._soul_concern_inject_reason, 'preflight_fail')


class TestLayer2Relational(unittest.TestCase):
    def test_baggage_injected_when_summon_reason(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        rs = MagicMock()
        rs.to_prompt_block = MagicMock(return_value='[REL]')
        n.relational_state = rs
        n._soul_concern_inject_reason = 'summon'
        n._build_layer_2_relational_block()
        rs.to_prompt_block.assert_called_once_with(
            top_jokes=3, top_unfinished=2, top_threads=2, max_chars=700)

    def test_no_baggage_when_silent_reason(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        rs = MagicMock()
        rs.to_prompt_block = MagicMock(return_value='[REL]')
        n.relational_state = rs
        n._soul_concern_inject_reason = 'silent'
        n._build_layer_2_relational_block()
        rs.to_prompt_block.assert_called_once_with(
            top_jokes=3, top_unfinished=0, top_threads=0, max_chars=700)


class TestLayer3Attention(unittest.TestCase):
    def test_calls_build_attention_block(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.concerns_ledger = MagicMock()
        n.relational_state = MagicMock()
        n.short_term_memory = []
        with patch('jarvis_attention.build_attention_block',
                    return_value='[ATTN] now') as mock_attn:
            result = n._build_layer_3_attention_block('working on coding')
        self.assertEqual(result, '[ATTN] now')
        mock_attn.assert_called_once()


if __name__ == '__main__':
    unittest.main()
