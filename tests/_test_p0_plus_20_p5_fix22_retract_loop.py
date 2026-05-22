# -*- coding: utf-8 -*-
"""[P5-fix22 / 2026-05-22] ClaimTracer retract context skip — 治死循环

Sir 17:05 真测痛点:
> "贾维斯连续道歉了七八次, 这个情况在你修的上个版本到 layer1 刚做好之间是没出现的"

死循环路径:
1. Turn N 主脑 reply 含 "95%" → ClaimTracer audit 写 unverified
2. Turn N+1 build_integrity_alert 看到 audit → prepend ALERT → 主脑被强迫撤回
3. Turn N+1 reply 含 "withdraw 95%" → ClaimTracer 又把 95% 当 unverified → 又 audit
4. Turn N+2 又 prepend ALERT → 又撤 → 死循环 7-8 轮

修法 (jarvis_claim_tracer.py:_is_claim_in_retract_context):
- claim 周围 ±150 chars 含 retract phrases (withdraw/retract/撤回/...) → skip audit
- 主脑明确撤回 = 不 commit, 不应当 factual claim
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRetractContextDetection(unittest.TestCase):
    """单测 _is_claim_in_retract_context"""

    def test_english_withdraw_phrase_detects(self):
        from jarvis_claim_tracer import _is_claim_in_retract_context
        reply = ('Regarding my earlier mention of a "95%" figure, '
                 'I must withdraw that statistic. I have no data to support it.')
        self.assertTrue(_is_claim_in_retract_context(reply, '95%'))

    def test_english_retract_phrase_detects(self):
        from jarvis_claim_tracer import _is_claim_in_retract_context
        reply = ('I must formally retract the 95% threshold I mentioned earlier. '
                 'It was unfounded.')
        self.assertTrue(_is_claim_in_retract_context(reply, '95%'))

    def test_english_unfounded_detects(self):
        from jarvis_claim_tracer import _is_claim_in_retract_context
        reply = ('My earlier "95%" figure was an unfounded estimate, Sir. '
                 'I lack the data to support it.')
        self.assertTrue(_is_claim_in_retract_context(reply, '95%'))

    def test_chinese_chehui_detects(self):
        from jarvis_claim_tracer import _is_claim_in_retract_context
        reply = '关于之前提到的 95% 一数, 我必须撤回. 目前没有数据支持.'
        self.assertTrue(_is_claim_in_retract_context(reply, '95%'))

    def test_no_data_to_support_detects(self):
        from jarvis_claim_tracer import _is_claim_in_retract_context
        reply = ('I mentioned 95% earlier but I have no data to support such '
                 'a specific percentage.')
        self.assertTrue(_is_claim_in_retract_context(reply, '95%'))

    def test_normal_claim_does_not_detect(self):
        """没 retract phrase 时不该 detect — 正常 commit factual claim 仍要 audit"""
        from jarvis_claim_tracer import _is_claim_in_retract_context
        reply = "The keyrouter is at 87% capacity, Sir."
        self.assertFalse(_is_claim_in_retract_context(reply, '87%'))

    def test_far_from_retract_does_not_detect(self):
        """retract phrase 距 claim > 150 chars → 不 detect (相隔太远不算同一陈述)"""
        from jarvis_claim_tracer import _is_claim_in_retract_context
        reply = ('We are at 87% load. ' + ('Padding text. ' * 30) +
                 'I must withdraw my earlier estimate.')
        # 87% 在最前, withdraw 在 ~400 chars 后 → 不算同一 claim 的撤回
        self.assertFalse(_is_claim_in_retract_context(reply, '87%'))


class TestTraceReplyRetractSkip(unittest.TestCase):
    """端到端: trace_reply 在 retract context 跳过 audit"""

    def setUp(self):
        # 隔离 audit file (不污染 prod jsonl)
        import tempfile
        self._tmpdir = tempfile.mkdtemp(prefix='claim_audit_')
        self._audit_path = os.path.join(self._tmpdir, 'integrity_audit.jsonl')
        # patch global audit path
        import jarvis_claim_tracer as ct
        self._orig_audit_path = ct._INTEGRITY_AUDIT_PATH
        ct._INTEGRITY_AUDIT_PATH = self._audit_path

    def tearDown(self):
        import jarvis_claim_tracer as ct
        ct._INTEGRITY_AUDIT_PATH = self._orig_audit_path
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _read_audit(self):
        if not os.path.exists(self._audit_path):
            return []
        with open(self._audit_path, 'r', encoding='utf-8') as f:
            return [line for line in f if line.strip()]

    def test_retract_reply_does_not_audit(self):
        """retract reply 不入 audit"""
        from jarvis_claim_tracer import trace_reply
        reply = ('Regarding my earlier mention of a "95%" figure, I must '
                 'withdraw that statistic. I have no data to support it.')
        result = trace_reply(reply, tool_results=[], stm_recent=[],
                              turn_id='turn_test_retract_1',
                              include_swm_tool_called=False)
        # 95% 是 percent claim, 但被 retract context skip → 不入 audit
        self.assertEqual(len(self._read_audit()), 0,
                          'retract reply 中的 claim 不应入 audit')

    def test_normal_factual_claim_still_audits(self):
        """正常 commit factual claim 仍入 audit (unverified)"""
        from jarvis_claim_tracer import trace_reply
        reply = "The system is at 87% capacity, Sir."
        result = trace_reply(reply, tool_results=[], stm_recent=[],
                              turn_id='turn_test_normal_1',
                              include_swm_tool_called=False)
        # 87% 是 percent claim, 没 retract context → unverified → 入 audit
        self.assertGreaterEqual(len(self._read_audit()), 1,
                                 'normal claim 仍应入 audit')

    def test_chinese_retract_does_not_audit(self):
        """中文 retract context 不入 audit"""
        from jarvis_claim_tracer import trace_reply
        reply = '关于之前提到的 95% 一数, 我必须撤回. 目前没有数据支持.'
        result = trace_reply(reply, tool_results=[], stm_recent=[],
                              turn_id='turn_test_retract_zh',
                              include_swm_tool_called=False)
        self.assertEqual(len(self._read_audit()), 0,
                          '中文 retract 也应 skip audit')


class TestNoLoopRegression(unittest.TestCase):
    """端到端模拟死循环 — 应证明修法切断循环"""

    def test_simulated_loop_truncates(self):
        """模拟 8 轮 retract reply, 验证 audit 不再累积"""
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix='claim_audit_loop_')
        audit_path = os.path.join(tmpdir, 'integrity_audit.jsonl')
        try:
            import jarvis_claim_tracer as ct
            orig = ct._INTEGRITY_AUDIT_PATH
            ct._INTEGRITY_AUDIT_PATH = audit_path

            from jarvis_claim_tracer import trace_reply
            for i in range(8):
                reply = (f'Regarding my earlier mention of "95%" — '
                         f'I must withdraw. (turn {i})')
                trace_reply(reply, tool_results=[], stm_recent=[],
                              turn_id=f'turn_loop_{i}',
                              include_swm_tool_called=False)

            ct._INTEGRITY_AUDIT_PATH = orig

            # 期望: 8 轮 retract reply 都 skip → audit 0 entries
            entries = []
            if os.path.exists(audit_path):
                with open(audit_path, 'r', encoding='utf-8') as f:
                    entries = [line for line in f if line.strip()]
            self.assertEqual(len(entries), 0,
                              f'8 轮 retract reply 不应累积 audit, 实际 {len(entries)} entries')
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
