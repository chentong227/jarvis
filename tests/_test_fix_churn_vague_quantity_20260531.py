# -*- coding: utf-8 -*-
"""[fix-churn / 2026-05-31] 模糊近似量词不算 specific claim — 治时间 churn.

Sir 真测 BUG (真机 log 08:53-08:57): 主脑说 "a few minutes" → ClaimTracer 当
[count] specific claim 标 unverified → INTEGRITY alert 逼主脑下轮纠正 →
"five minutes not a few" → PreFlight 判 unsolicited callback → 循环 4 轮强迫纠正一个
Sir 不在乎、本就是约数的时间。

治本 (准则 5): 约数 (few/couple/several/几/一会) = hedge, 不是 specific factual claim,
不审计。具体数 (five/3 times) 仍审。断 churn 于源头 (初始 flag 不发生 → 无纠正级联)。
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_claim_tracer import extract_claims


def _count_claims(text):
    return [c for c in extract_claims(text) if c.kind == 'count']


class TestVagueQuantityHedge(unittest.TestCase):
    def test_a_few_minutes_is_hedge(self):
        cs = _count_claims("It has been a few minutes, Sir.")
        self.assertEqual(len(cs), 1)
        self.assertTrue(cs[0].has_uncertainty, "'few minutes' 应判 hedge, 不审计")

    def test_several_couple_some_hedge(self):
        for t in ("I waited several minutes.", "give me a couple hours",
                  "some days ago"):
            cs = _count_claims(t)
            if cs:  # 有匹配的才查
                self.assertTrue(cs[0].has_uncertainty, f"{t!r} 应判 hedge")

    def test_specific_number_still_audited(self):
        # 具体数仍是 specific claim (言出必行不放松)
        for t in ("We have been active for five minutes.",
                  "I have said this 3 times.",
                  "you rested eight hours"):
            cs = _count_claims(t)
            self.assertTrue(cs, f"{t!r} 应抽到 count claim")
            self.assertFalse(cs[0].has_uncertainty,
                             f"{t!r} 是具体数, 不该判 hedge (言出必行)")

    def test_churn_origin_broken(self):
        # 真机 churn 起点: 主脑 "a few minutes" 不再被 flag → 不触发 INTEGRITY 纠正级联
        cs = _count_claims("The most immediate test would take a few minutes.")
        self.assertTrue(all(c.has_uncertainty for c in cs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
