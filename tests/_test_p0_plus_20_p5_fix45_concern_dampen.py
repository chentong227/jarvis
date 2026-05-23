# -*- coding: utf-8 -*-
"""[P5-fix45 / 2026-05-23 14:55] CONCERN_DAMPEN tag — 主脑自决调 concern severity.

Sir 14:51 真测痛点:
  Sir: '我中午睡了 1 小时, 你记录一下'
  mutation organ ✅ 写 ProfileCard.daily_logs.2026-05-23='Midday nap: 1 hour'
  但 sir_sleep_streak severity 没削 (仍 1.0) → 担心度不降.
  Sir: '这会动态降低贾维斯对我睡眠的担心吗? 链路是否实现?' — 没实现.

Sir 真意 (准则 6/8):
  '不要堆 LLM, 不要 hot-fix cooldown, 让主脑看 SWM evidence 自决调 severity'

设计 (准则 6 三维耦合):
  数据强耦合: mutation organ publish 'sir_field_updated' SWM (现有) ✅
  行为弱耦合: <CONCERN_DAMPEN/> tag (主脑可 emit, 可不 emit)
  决策集中主脑: directive 教主脑看 SWM + active concerns → 自决 emit

  chat_bypass 后处理: parse → ledger.record_signal + publish 'concern_dampen_applied'

测试覆盖:
A. parse_dampen_tags 解析多种 tag 格式 (self-closing / paired / multi)
B. apply_dampen 调 ledger.record_signal + publish SWM event
C. process_reply 一站式 (parse + apply)
D. invalid tag 拒 (无 cid / delta 超范围 / delta 接近 0)
E. _STRUCTURAL_TAGS 含 CONCERN_DAMPEN (TTS 剥)
F. directive 注册 concern_dampen_self_decide
G. chat_bypass 接入 process_reply
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestParseDampenTags(unittest.TestCase):

    def test_a_self_closing(self):
        from jarvis_concern_dampen import parse_dampen_tags
        text = (
            'Noted Sir. '
            '<CONCERN_DAMPEN cid="sir_sleep_streak" delta="-0.3" reason="Sir nap 1h"/>'
            ' I shall log the rest.'
        )
        parsed = parse_dampen_tags(text)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].cid, 'sir_sleep_streak')
        self.assertAlmostEqual(parsed[0].delta, -0.3)
        self.assertEqual(parsed[0].reason, 'Sir nap 1h')

    def test_a_paired(self):
        from jarvis_concern_dampen import parse_dampen_tags
        text = '<CONCERN_DAMPEN cid="x" delta="-0.5" reason="y"></CONCERN_DAMPEN>'
        parsed = parse_dampen_tags(text)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].cid, 'x')

    def test_a_multiple(self):
        from jarvis_concern_dampen import parse_dampen_tags
        text = (
            '<CONCERN_DAMPEN cid="a" delta="-0.2" reason="r1"/>'
            ' middle text '
            '<CONCERN_DAMPEN cid="b" delta="-0.4" reason="r2"/>'
        )
        parsed = parse_dampen_tags(text)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0].cid, 'a')
        self.assertEqual(parsed[1].cid, 'b')

    def test_d_no_tag_empty(self):
        from jarvis_concern_dampen import parse_dampen_tags
        self.assertEqual(parse_dampen_tags(''), [])
        self.assertEqual(parse_dampen_tags('plain text no tag'), [])
        self.assertEqual(parse_dampen_tags(None), [])

    def test_d_invalid_delta_out_of_range(self):
        from jarvis_concern_dampen import parse_dampen_tags
        text = '<CONCERN_DAMPEN cid="x" delta="-1.5" reason="too big"/>'
        parsed = parse_dampen_tags(text)
        # delta=-1.5 超 [-1, 1] → is_valid 拒
        self.assertEqual(len(parsed), 0)

    def test_d_invalid_delta_near_zero(self):
        from jarvis_concern_dampen import parse_dampen_tags
        text = '<CONCERN_DAMPEN cid="x" delta="0.005" reason="too small"/>'
        parsed = parse_dampen_tags(text)
        # delta=0.005 接近 0 → reject (避免主脑刷无效 tag)
        self.assertEqual(len(parsed), 0)


class TestApplyDampen(unittest.TestCase):

    def test_b_apply_calls_record_signal(self):
        from jarvis_concern_dampen import ParsedDampen, apply_dampen

        class MockLedger:
            def __init__(self):
                self.called = []
            def record_signal(self, cid, what, severity_delta, source_turn_id=''):
                self.called.append((cid, what, severity_delta, source_turn_id))
                return True

        ledger = MockLedger()
        pd = ParsedDampen(cid='sir_sleep_streak', delta=-0.3, reason='nap',
                            raw_match='<...>')
        ok = apply_dampen(pd, ledger, turn_id='turn_test_1')
        self.assertTrue(ok)
        self.assertEqual(len(ledger.called), 1)
        cid, what, delta, tid = ledger.called[0]
        self.assertEqual(cid, 'sir_sleep_streak')
        self.assertAlmostEqual(delta, -0.3)
        self.assertEqual(tid, 'turn_test_1')

    def test_b_no_ledger_returns_false(self):
        from jarvis_concern_dampen import ParsedDampen, apply_dampen
        pd = ParsedDampen(cid='x', delta=-0.3, reason='r', raw_match='<...>')
        self.assertFalse(apply_dampen(pd, None))

    def test_b_invalid_pd_returns_false(self):
        from jarvis_concern_dampen import ParsedDampen, apply_dampen

        class MockLedger:
            def record_signal(self, *a, **k): return True

        # invalid: empty cid
        pd = ParsedDampen(cid='', delta=-0.3, reason='r', raw_match='<...>')
        self.assertFalse(apply_dampen(pd, MockLedger()))


class TestProcessReply(unittest.TestCase):

    def test_c_process_reply_end_to_end(self):
        from jarvis_concern_dampen import process_reply

        class MockLedger:
            def __init__(self):
                self.called = []
            def record_signal(self, cid, what, severity_delta, source_turn_id=''):
                self.called.append((cid, severity_delta))
                return True

        ledger = MockLedger()
        text = (
            'Noted Sir. '
            '<CONCERN_DAMPEN cid="sir_sleep_streak" delta="-0.3" reason="nap 1h"/>'
            ' Logged.'
        )
        n = process_reply(text, ledger, turn_id='turn_t1')
        self.assertEqual(n, 1)
        self.assertEqual(len(ledger.called), 1)
        self.assertEqual(ledger.called[0][0], 'sir_sleep_streak')

    def test_c_no_tag_returns_zero(self):
        from jarvis_concern_dampen import process_reply

        class MockLedger:
            def record_signal(self, *a, **k): return True

        self.assertEqual(process_reply('plain text', MockLedger()), 0)


class TestStructuralIntegration(unittest.TestCase):

    def test_e_concern_dampen_in_structural_tags(self):
        from jarvis_safety import _STRUCTURAL_TAGS
        self.assertIn('CONCERN_DAMPEN', _STRUCTURAL_TAGS,
                          'CONCERN_DAMPEN 应在 _STRUCTURAL_TAGS (TTS 不读)')

    def test_e_strip_removes_concern_dampen(self):
        from jarvis_safety import _strip_structural_tag_blocks
        text = (
            'Hello Sir '
            '<CONCERN_DAMPEN cid="x" delta="-0.3" reason="y"/>'
            ' goodbye.'
        )
        stripped = _strip_structural_tag_blocks(text)
        self.assertNotIn('<CONCERN_DAMPEN', stripped)
        self.assertIn('Hello Sir', stripped)
        self.assertIn('goodbye', stripped)

    def test_e_strip_paired(self):
        from jarvis_safety import _strip_structural_tag_blocks
        text = 'A <CONCERN_DAMPEN cid="x" delta="-0.3" reason="y"></CONCERN_DAMPEN> B'
        stripped = _strip_structural_tag_blocks(text)
        self.assertNotIn('CONCERN_DAMPEN', stripped)


class TestDirectiveRegistered(unittest.TestCase):
    """fix45 directive 真注册."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_directives.py'), encoding='utf-8') as f:
            cls.src = f.read()

    def test_f_directive_present(self):
        self.assertIn("id='concern_dampen_self_decide'", self.src,
                          'concern_dampen_self_decide directive 应注册')

    def test_f_directive_has_tag_schema(self):
        self.assertIn('CONCERN_DAMPEN cid=', self.src,
                          'directive 应教主脑 tag schema 含 cid/delta/reason')
        idx = self.src.find('concern_dampen_self_decide')
        body = self.src[idx:idx + 4000]
        self.assertIn('-0.3', body, 'directive 应给推荐 delta 数值')

    def test_g_chat_bypass_wired(self):
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'), encoding='utf-8') as f:
            bypass_src = f.read()
        self.assertIn('jarvis_concern_dampen', bypass_src,
                          'chat_bypass 应 import jarvis_concern_dampen')
        self.assertIn('process_reply', bypass_src,
                          'chat_bypass 应调 process_reply')


if __name__ == '__main__':
    unittest.main()
