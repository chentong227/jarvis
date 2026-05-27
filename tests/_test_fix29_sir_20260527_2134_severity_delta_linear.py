# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 21:34 真测 P4] hydration progress_update severity_delta=0.

Sir 真测看到:
  🛠️ ✅ concerns.progress_update: sir_hydration_habit → 1 杯
       (severity_delta=+0.00)

Sir 反应: "这个回应好像太简单了, 而且好像没添加成功？"

BUG 链:
  - BUG-A: handler `concerns.progress_update` 只用 LLM 传的 `target`,
           没 fallback ledger 已存 `daily_progress.target` (实际存 10.0)
  - BUG-B: severity_delta 算法是 "75% gate" → 1/10 = 0.0 让 Sir 觉得
           "没添加成功". 应改 linear decay.
  - BUG-C: 主脑 emit current=1 (absolute) 非 +=1 (delta) — directive 层
           暂跳, 不在本 fix 范围.

治本:
  1. 新 helper `jarvis_concerns.compute_severity_delta_from_progress(
       current, target, baseline=-0.5)` — linear decay
  2. handler `jarvis_chat_bypass.progress_update` 调 helper +
     tgt fallback 到 `ledger.get(cid).daily_progress.target`

测试覆盖:
  - Part A: helper 单元 (linear, edge case)
  - Part B: handler 集成 (tgt fallback, helper 被调)
"""
from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


# ==========================================================================
# Part A — helper 单元
# ==========================================================================
class TestComputeSeverityDeltaFromProgress(unittest.TestCase):

    def setUp(self):
        from jarvis_concerns import compute_severity_delta_from_progress
        self.fn = compute_severity_delta_from_progress

    def test_zero_progress_zero_delta(self):
        """current=0 → 0.0 (没动 = 不掉 severity)."""
        self.assertEqual(self.fn(0, 10), 0.0)
        self.assertEqual(self.fn(None, 10), 0.0)
        self.assertEqual(self.fn(-5, 10), 0.0)

    def test_full_progress_full_delta(self):
        """100% → baseline (-0.5)."""
        self.assertAlmostEqual(self.fn(10, 10), -0.5, places=3)
        # over 100% — clamped
        self.assertAlmostEqual(self.fn(15, 10), -0.5, places=3)

    def test_linear_decay_intermediate(self):
        """中间值 linear: 1/10 → -0.05, 5/10 → -0.25, 8/10 → -0.4."""
        self.assertAlmostEqual(self.fn(1, 10), -0.05, places=3)
        self.assertAlmostEqual(self.fn(5, 10), -0.25, places=3)
        self.assertAlmostEqual(self.fn(8, 10), -0.4, places=3)

    def test_no_target_small_delta(self):
        """target=None/0 → -0.05 (有 signal 但不知 target)."""
        self.assertAlmostEqual(self.fn(5, None), -0.05, places=3)
        self.assertAlmostEqual(self.fn(5, 0), -0.05, places=3)

    def test_custom_baseline(self):
        """baseline 可定制 (e.g. 严厉的 concern 用 -1.0)."""
        self.assertAlmostEqual(self.fn(5, 10, baseline=-1.0), -0.5, places=3)
        self.assertAlmostEqual(self.fn(10, 10, baseline=-1.0), -1.0, places=3)

    def test_sir_real_test_case_1_cup_of_10(self):
        """🩹 Sir 21:34 真测 case: 喝了 1 杯水, target 10.

        旧算法返 0.0 (75% gate), Sir 反应"没添加成功".
        新算法应返 -0.05 (有动, 表达"喝了点").
        """
        out = self.fn(1.0, 10.0)
        self.assertLess(out, 0.0, f'真测 case 应有负 delta, 得 {out}')
        self.assertAlmostEqual(out, -0.05, places=3)


# ==========================================================================
# Part B — handler 集成 (静态扫描 + ledger fallback)
# ==========================================================================
class TestProgressUpdateHandlerIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(
            os.path.join(_REPO, 'jarvis_chat_bypass.py'),
            'r', encoding='utf-8'
        ) as f:
            cls.body = f.read()

    def test_handler_uses_helper(self):
        """handler 必须 import + 用 compute_severity_delta_from_progress."""
        # import 形式 (灵活: 可 `import` / `from ... import`)
        self.assertIn('compute_severity_delta_from_progress', self.body,
            'handler 必须用 helper compute_severity_delta_from_progress')
        # 不该再有旧 75% gate (反例: `cur_f >= tgt_f * 0.75`)
        import re
        bad = re.search(r'cur_f\s*>=\s*tgt_f\s*\*\s*0\.75', self.body)
        self.assertIsNone(bad,
            '旧 75% gate 算法应已删 (替成 linear helper)')

    def test_handler_fallback_to_ledger_target(self):
        """handler 应 fallback ledger `daily_progress.target` 当主脑 omit target."""
        # 关键证: 应有 `_c.daily_progress` 或 `ledger.get(cid)` 拿 target 路径
        self.assertIn('daily_progress', self.body,
            'handler 应 lookup ledger daily_progress 作 target fallback')
        # 应有 `if tgt_f is None:` 进入 fallback 分支
        self.assertIn('if tgt_f is None:', self.body,
            'handler 必须有 fallback 分支')


# ==========================================================================
# Part C — 端到端: 真模拟 Sir 21:34 case (mock ledger)
# ==========================================================================
class TestEndToEndSirRealCase(unittest.TestCase):
    """模拟 Sir 21:34 真 case 走 ledger.record_user_feedback 全链路."""

    def setUp(self):
        from jarvis_concerns import (
            ConcernsLedger, Concern, STATE_ACTIVE,
            compute_severity_delta_from_progress,
        )
        import tempfile
        _tmp = tempfile.gettempdir()
        self._tmpf = os.path.join(_tmp, '_test_fix29.json')
        self._tmpr = os.path.join(_tmp, '_test_fix29r.json')
        self.ledger = ConcernsLedger(persist_path=self._tmpf,
                                       review_path=self._tmpr)
        # 模拟 sir_hydration_habit (target=10 已存 daily_progress)
        c = Concern(
            id='sir_hydration_habit',
            what_i_watch='Sir water',
            why_i_care='health',
            severity=0.75,  # Sir 21:34 看到 0.75
            state=STATE_ACTIVE,
        )
        c.daily_progress = {
            'current': 0.0,
            'target': 10.0,
            'unit': '杯',
            'iso_date': '2026-05-27',
        }
        self.ledger.register(c)
        self.fn = compute_severity_delta_from_progress

    def tearDown(self):
        for p in (self._tmpf, self._tmpr):
            try:
                os.remove(p)
            except OSError:
                pass

    def test_sir_drank_1_cup_severity_drops(self):
        """Sir 真 case: 喝了 1 杯, severity 应从 0.75 → 0.70 (动 -0.05)."""
        cur_f, tgt_f = 1.0, 10.0  # target fallback 模拟
        sev_d = self.fn(cur_f, tgt_f)
        judgement = {
            'has_relevance': True,
            'progress': {'current': cur_f, 'target': tgt_f, 'unit': '杯'},
            'severity_delta': sev_d,
        }
        ok = self.ledger.record_user_feedback('sir_hydration_habit',
                                                '又喝了一杯', judgement)
        self.assertTrue(ok, 'record_user_feedback 应成功')
        c = self.ledger.get('sir_hydration_habit')
        self.assertAlmostEqual(c.severity, 0.70, places=2,
            msg=f'severity 应 0.75 - 0.05 = 0.70, 得 {c.severity}')

    def test_sir_drank_8_cups_severity_drops_significantly(self):
        """喝了 8/10, severity 应大幅下降 0.75 - 0.4 = 0.35."""
        sev_d = self.fn(8.0, 10.0)
        judgement = {
            'has_relevance': True,
            'progress': {'current': 8.0, 'target': 10.0, 'unit': '杯'},
            'severity_delta': sev_d,
        }
        self.ledger.record_user_feedback('sir_hydration_habit',
                                          '喝完 8 杯了', judgement)
        c = self.ledger.get('sir_hydration_habit')
        self.assertAlmostEqual(c.severity, 0.35, places=2)


# ==========================================================================
# Part D — tool_registry 路径也用 helper (一致性)
# ==========================================================================
class TestToolRegistryUsesHelper(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(
            os.path.join(_REPO, 'jarvis_tool_registry.py'),
            'r', encoding='utf-8'
        ) as f:
            cls.body = f.read()

    def test_tool_progress_update_uses_helper(self):
        """tool_concern_progress_update 应 import + 用 helper."""
        self.assertIn('compute_severity_delta_from_progress', self.body,
            'tool_registry 必须用 helper')

    def test_tool_progress_update_target_fallback(self):
        """tool_registry 也应 fallback ledger daily_progress.target."""
        self.assertIn('daily_progress', self.body,
            'tool_registry 应 lookup ledger daily_progress 当 fallback')


if __name__ == '__main__':
    unittest.main(verbosity=2)
