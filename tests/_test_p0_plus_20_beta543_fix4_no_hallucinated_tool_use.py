"""[β.5.43-fix4 / 2026-05-20 18:55] Sir 真理 — 主脑撒谎 "I've corrected".

Sir 实测痛点: Sir 说 "应该是第八杯", Jarvis 回 "I've corrected my internal count
to eight" — 但本轮零 mutation tool 调用. ConcernFeedback record 仍 current=3, 
MemCorrection 存为孤儿 cell. **主脑撒谎**.

修法: 加 no_hallucinated_tool_use_judge directive (priority 12 极顶 always-on), 
让主脑每轮自审 "我有没有暗示 mutation 完成但实际没调 tool".

注: 真治本是 IntentResolver 重构 (后续 6h sprint). 此 directive 是 30min critical 
stop-bleed (主脑层 self-check), 不是根治.
"""
from __future__ import annotations

import os
import sys
import json
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestFix4NoHallucinatedToolUse(unittest.TestCase):

    def test_trigger_function_exists_and_always_fires(self):
        from jarvis_directives import _trigger_no_hallucinated_tool_use_judge
        self.assertTrue(callable(_trigger_no_hallucinated_tool_use_judge))
        # always-on (无 ctx)
        self.assertTrue(_trigger_no_hallucinated_tool_use_judge(None))

    def test_directive_registered_in_seed_with_priority_12(self):
        src = open(
            os.path.join(ROOT, 'jarvis_directives.py'), encoding='utf-8'
        ).read()
        self.assertIn("id='no_hallucinated_tool_use_judge'", src,
                      'directive seed 必须含 no_hallucinated_tool_use_judge')
        # priority 12 (极顶, 比 over_offer 11 高)
        self.assertIn('priority=12', src,
                      'no_hallucinated_tool_use_judge 必 priority 12')

    def test_directive_text_includes_critical_examples(self):
        """directive 必含 Sir 18:55 实测反例 + 正例."""
        src = open(
            os.path.join(ROOT, 'jarvis_directives.py'), encoding='utf-8'
        ).read()
        self.assertIn('β.5.43-fix4', src)
        # 必含 Sir 实测反例
        self.assertIn("I've corrected my internal count", src,
                      'directive 必引用 Sir 18:55 实测反例')
        # FORBIDDEN 词汇
        for forbidden in ['corrected', 'updated', 'saved', 'stored', 'recorded']:
            self.assertIn(forbidden, src.lower(),
                          f'directive FORBIDDEN list 应含 {forbidden}')
        # 允许的替代
        self.assertIn('Noted', src,
                      'directive 应给 acknowledge-only 替代')
        self.assertIn('Understood', src,
                      'directive 应给 acknowledge-only 替代')

    def test_vocab_json_has_entry(self):
        path = os.path.join(ROOT, 'memory_pool', 'directives_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        ids = [d.get('id') for d in data.get('directives', [])]
        self.assertIn('no_hallucinated_tool_use_judge', ids,
                      'vocab json 必有 no_hallucinated_tool_use_judge entry')
        # priority match
        entry = next(d for d in data['directives']
                     if d.get('id') == 'no_hallucinated_tool_use_judge')
        self.assertEqual(entry['priority'], 12,
                         'vocab json priority 应与 seed 一致 = 12')
        self.assertEqual(entry['state'], 'active')

    def test_directive_higher_priority_than_other_red_lines(self):
        """no_hallucinated_tool_use_judge (12) 必高于 over_offer (11) + capability_boundary (10)."""
        src = open(
            os.path.join(ROOT, 'jarvis_directives.py'), encoding='utf-8'
        ).read()
        # 抓 priority 数字
        import re
        # no_hallucinated priority
        m_nh = re.search(
            r"id='no_hallucinated_tool_use_judge'[\s\S]{0,500}?priority=(\d+)",
            src,
        )
        self.assertIsNotNone(m_nh, '应找到 no_hallucinated_tool_use_judge priority')
        nh_pri = int(m_nh.group(1))
        self.assertEqual(nh_pri, 12,
                         f'no_hallucinated priority 应 12, 实际 {nh_pri}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
