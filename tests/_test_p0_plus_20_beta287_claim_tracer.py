# -*- coding: utf-8 -*-
"""[P0+20-β.2.8.7 / 2026-05-17] ClaimTracer — 通用反幻觉框架

Sir 23:32 反馈尖锐:
> "不写硬编码吧? 硬编码只是时间不能编造幻觉吗? 这为什么在之前的言出必行
>  中没实现?"

测点:
- extract_claims 抽时间/百分数/计数/quote
- uncertainty marker 标记 (claim.has_uncertainty)
- trace_to_evidence 三档 (uncertainty / tool / stm)
- trace_reply 端到端 (Sir 实测场景)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestExtractClaims(unittest.TestCase):
    def test_extract_time_hhmmss(self):
        from jarvis_claim_tracer import extract_claims
        claims = extract_claims("registered at 23:14:06 tonight")
        kinds = [c.kind for c in claims]
        self.assertIn('time', kinds)
        time_claim = next(c for c in claims if c.kind == 'time')
        self.assertEqual(time_claim.text, '23:14:06')

    def test_extract_time_ampm(self):
        from jarvis_claim_tracer import extract_claims
        claims = extract_claims("you said 3pm earlier")
        # 注意 3pm 不带 : 也算 time
        kinds = [c.kind for c in claims]
        self.assertIn('time', kinds)

    def test_extract_chinese_time(self):
        from jarvis_claim_tracer import extract_claims
        claims = extract_claims("您下午三点提到")
        kinds = [c.kind for c in claims]
        self.assertIn('time', kinds)

    def test_extract_percent(self):
        from jarvis_claim_tracer import extract_claims
        claims = extract_claims("the keyrouter is at 87% capacity")
        kinds = [c.kind for c in claims]
        self.assertIn('percent', kinds)

    def test_extract_count_zh(self):
        from jarvis_claim_tracer import extract_claims
        claims = extract_claims("我们这周聊了3次这件事")
        kinds = [c.kind for c in claims]
        self.assertIn('count', kinds)

    def test_extract_count_en(self):
        from jarvis_claim_tracer import extract_claims
        claims = extract_claims("we've discussed this 5 times")
        kinds = [c.kind for c in claims]
        self.assertIn('count', kinds)

    def test_extract_count_en_word_hyphenated(self):
        """🆕 [Sir 2026-05-25 20:01 真测追根] 'eight-hour rest' 必须抓
        — 老 _PAT_EN_COUNT 只抓 \\d+, 主脑用 'eight' 单词绕过 → 撒"8 小时"谎漏 trace."""
        from jarvis_claim_tracer import extract_claims
        claims = extract_claims(
            "I trust your eight-hour rest was restorative."
        )
        kinds = [c.kind for c in claims]
        self.assertIn('count', kinds,
                       "eight-hour 必须被抓 count claim (准则 5 言出必行底线)")

    def test_extract_count_en_word_space(self):
        """英文单词数字 + 空格 + 单位也算 count (one hour / three days)."""
        from jarvis_claim_tracer import extract_claims
        for text in (
            "we worked for three hours",
            "you've been away for two days",
            "she texted five times this morning",
        ):
            claims = extract_claims(text)
            kinds = [c.kind for c in claims]
            self.assertIn('count', kinds,
                          f"'{text}' 应抓 count claim")

    def test_extract_quote_attr_en(self):
        from jarvis_claim_tracer import extract_claims
        claims = extract_claims('you said "I want to retire by 11"')
        kinds = [c.kind for c in claims]
        self.assertIn('quote', kinds)

    def test_no_claims_in_safe_text(self):
        from jarvis_claim_tracer import extract_claims
        claims = extract_claims("Noted, Sir. I understand.")
        # 普通 ack 无 specific claim
        self.assertEqual(len(claims), 0)


class TestUncertaintyMarker(unittest.TestCase):
    def test_about_marks_uncertainty(self):
        from jarvis_claim_tracer import extract_claims
        claims = extract_claims("about 23:14 last night")
        time_claim = [c for c in claims if c.kind == 'time'][0]
        self.assertTrue(time_claim.has_uncertainty)

    def test_zh_estimate_marks_uncertainty(self):
        from jarvis_claim_tracer import extract_claims
        claims = extract_claims("我印象中大概3点的时候")
        self.assertTrue(any(c.has_uncertainty for c in claims))

    def test_no_marker_means_strict_claim(self):
        from jarvis_claim_tracer import extract_claims
        claims = extract_claims("registered at exactly 23:14:06")
        time_claim = [c for c in claims if c.kind == 'time'][0]
        self.assertFalse(time_claim.has_uncertainty)


class TestTraceToEvidence(unittest.TestCase):
    def test_uncertainty_passes(self):
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('time', '23:14:06')
        c.has_uncertainty = True
        ok = trace_to_evidence(c, [], [])
        self.assertTrue(ok)
        self.assertEqual(c.trace_to, 'uncertainty')

    def test_tool_result_match(self):
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('time', '23:14:06')
        tool_results = ['Commitments (...): [DB#3] PENDING 注册于 2026-05-17 23:14:06 | deadline=...']
        ok = trace_to_evidence(c, tool_results, [])
        self.assertTrue(ok)
        self.assertEqual(c.trace_to, 'tool')

    def test_stm_match(self):
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('time', '11:00')
        stm = [{'user': 'I want to retire by 11:00 tonight', 'jarvis': 'noted'}]
        ok = trace_to_evidence(c, [], stm)
        self.assertTrue(ok)
        self.assertEqual(c.trace_to, 'stm')

    def test_no_evidence_returns_false(self):
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('time', '14:30')
        ok = trace_to_evidence(c, [], [])
        self.assertFalse(ok)


class TestTraceReplyEndToEnd(unittest.TestCase):
    def test_sir_2319_real_scenario_unverified(self):
        """Sir 23:19 实测: Jarvis 编造 '23:14:06 记录的' 时间戳, 无 tool 无 STM trace"""
        from jarvis_claim_tracer import trace_reply
        reply = (
            "My logs indicate that the commitment regarding your sleep schedule "
            "was registered at 23:14:06 tonight, following your decision to settle "
            "on 23:00."
        )
        result = trace_reply(reply, tool_results=[], stm_recent=[])
        self.assertGreater(result['n_unverified'], 0)
        # 起码 23:14:06 是 unverified
        self.assertTrue(any('23:14' in ex for ex in result['unverified_examples']))

    def test_with_tool_evidence_verified(self):
        """如果主脑真 fast_call 拿了 timestamp, 就 verified"""
        from jarvis_claim_tracer import trace_reply
        reply = "Registered at 23:14:06 per memory_hands."
        tool_results = ['list_commitments: [DB#3] 注册于 2026-05-17 23:14:06 | ...']
        result = trace_reply(reply, tool_results=tool_results, stm_recent=[])
        self.assertEqual(result['n_unverified'], 0)

    def test_with_uncertainty_marker_verified(self):
        from jarvis_claim_tracer import trace_reply
        reply = "I estimate it was around 23:14 last night, though I'd want to verify."
        result = trace_reply(reply, tool_results=[], stm_recent=[])
        self.assertEqual(result['n_unverified'], 0)

    def test_safe_reply_no_claims(self):
        from jarvis_claim_tracer import trace_reply
        reply = "Noted, Sir. I shall do that."
        result = trace_reply(reply, tool_results=[], stm_recent=[])
        self.assertEqual(result['n_claims'], 0)
        self.assertEqual(result['n_unverified'], 0)

    def test_stats_accumulate(self):
        from jarvis_claim_tracer import trace_reply, update_stats, get_stats
        # 干净重置
        from jarvis_claim_tracer import _CLAIM_STATS
        _CLAIM_STATS['total_replies_traced'] = 0
        _CLAIM_STATS['total_claims'] = 0
        _CLAIM_STATS['total_unverified'] = 0

        for _ in range(3):
            r = trace_reply("registered at 22:00", [], [])
            update_stats(r)
        s = get_stats()
        self.assertEqual(s['total_replies_traced'], 3)
        self.assertGreater(s['total_unverified'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
