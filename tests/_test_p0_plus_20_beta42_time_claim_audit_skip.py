# -*- coding: utf-8 -*-
"""[P0+20-β.4.2-hotfix / 2026-05-18] time kind claim 不入 audit (Sir 实测死循环治本)

Sir 18:46 真机实测暴露连环 BUG:
  - Round 3 主脑 reply 含 "23:14:06" 时间 hallucination → ClaimTracer 抓 → audit unverified
  - Round 4 ALERT 注入 "上轮 claim 23:14:06 未 verify" → 主脑道歉, 但又报当前时间 "6:46 PM"
  - Round 5 ALERT 又注入 "上轮 claim 6:46 未 verify" → 主脑又道歉, 又报 "6:47"
  - Round 6 死循环不止 (3+ 轮 ALERT 注入: log L208/L309/L374/L463)

根因: ClaimTracer (β.2.8.7) verify 路径只看 tool_results + STM, 不看 prompt SYSTEM CLOCK
注入的当前时间. 主脑从 SYSTEM CLOCK 读对的时间 ("6:46 PM" 实际正确) 仍 found=False.

临时止血 (本 hotfix): write_audit_entry 跳过 kind='time' 的 claim, 不进 audit.
诊断 bg_log 仍发 (保留 ClaimTracer trace 信号), 只是不进 ALERT 死循环路径.

真治本 (β.4.3+ TODO): 加 SYSTEM CLOCK ±2 min 比较 verify time claim.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _FakeClaim:
    def __init__(self, kind, text):
        self.kind = kind
        self.text = text
        self.trace_to = None


class TestTimeClaimAuditSkip(unittest.TestCase):
    """β.4.2-hotfix red line: kind='time' claim 不入 audit jsonl (防死循环)."""

    def setUp(self):
        from jarvis_claim_tracer import write_audit_entry
        self.write = write_audit_entry
        f = tempfile.NamedTemporaryFile(
            mode='w', suffix='.jsonl', delete=False, encoding='utf-8')
        f.close()
        self.path = f.name

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def _jsonl_lines(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path, 'r', encoding='utf-8') as f:
            return [json.loads(l) for l in f if l.strip()]

    def test_time_claim_unverified_does_not_enter_audit(self):
        """`kind='time'` + found=False → 不写 jsonl (β.4.2-hotfix 死循环治本)."""
        c = _FakeClaim('time', '6:46 PM')
        ok = self.write('turn_test_001', c, found=False,
                          reason='no match in tool_results or STM',
                          audit_path=self.path)
        self.assertFalse(ok, "time kind 必须返 False 跳过 audit")
        self.assertEqual(self._jsonl_lines(), [],
                          "time kind audit jsonl 必须保持空")

    def test_past_action_claim_unverified_still_enters_audit(self):
        """对比: kind='past_action' + found=False 仍正常写 jsonl (本 hotfix 只豁免 time)."""
        c = _FakeClaim('past_action', '已打开 dashboard')
        ok = self.write('turn_test_002', c, found=False,
                          reason='no ✅', audit_path=self.path)
        self.assertTrue(ok, "past_action kind 仍应进 audit")
        lines = self._jsonl_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['kind'], 'past_action')

    def test_time_claim_verified_also_skipped(self):
        """time kind + found=True 也跳过 (本来 found=True 就跳过, 验证不双重 write)."""
        c = _FakeClaim('time', '6:46 PM')
        ok = self.write('turn_test_003', c, found=True,
                          reason='', audit_path=self.path)
        self.assertFalse(ok)
        self.assertEqual(self._jsonl_lines(), [])

    def test_multiple_time_claims_all_skipped(self):
        """死循环复现: 3 个 time claim 连续写, jsonl 应保持空."""
        for t in ['23:14:06', '6:46 PM', '6:47']:
            c = _FakeClaim('time', t)
            self.write(f'turn_{t}', c, found=False,
                         reason='no match', audit_path=self.path)
        self.assertEqual(self._jsonl_lines(), [],
                          "多个 time claim 仍应保持 jsonl 空")

    def test_state_kind_still_enters_audit(self):
        """对比: kind='state' (其他 unverified kind) 仍进 audit, 仅 time 豁免."""
        c = _FakeClaim('state', 'dashboard is currently active')
        ok = self.write('turn_test_004', c, found=False,
                          reason='', audit_path=self.path)
        self.assertTrue(ok, "state kind 不在豁免列表, 应正常 audit")
        self.assertEqual(len(self._jsonl_lines()), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
