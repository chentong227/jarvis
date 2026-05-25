# -*- coding: utf-8 -*-
"""[Sir 2026-05-25 21:32 真测追根 followup] 3 路 strict 治本.

Sir 真测 (jarvis_20260525_2131_priority_correction_truncate.log):
  Turn 1: ProactiveCare nudge 驾照 (含 'a week' 幻觉数字 — ClaimTracer 抓)
  Turn 2: Sir '嗯，不要再提这个科医复习的事情了，我们要把面试提到最重要的是'
    a) ✅ unfinished_jiazhao_ke1 sev_d=-0.40 (b 侧生效)
    b) ❌ sir_interview_prep_balance 没 sev_d=+0.6 (a 侧 LLM 漏)
    c) ❌ 主脑 reply 'I have adjusted the priority level' 但 no_tool_called
       (INTEGRITY 抓 — 准则 5 违反)
    d) ⚠️ correction_dispatcher directive 没 fire (vocab 没含 '不要再提' / '最重要的是')

3 路修法:
  - f1: _base_dismiss_vocab.json 加 '不要再提' / '不要提了' 等 (Sir 真用)
  - f2: _base_correction_vocab.json 加 priority correction phrases
        ('最重要的是' / '提到最重要' / '其实是' / '你忘了' / '我们要把')
  - f3: correction_dispatcher directive 加 例 6 PRIORITY CORRECTION —
        必须 emit FAST_CALL mutation.update profile.current_priority
  - f4: ConcernFeedback prompt 加 a 必出强约束 (即使 X concern severity 低)
"""
from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(name: str) -> str:
    with open(os.path.join(ROOT, name), 'r', encoding='utf-8') as f:
        return f.read()


def _load_json(name: str) -> dict:
    with open(os.path.join(ROOT, name), 'r', encoding='utf-8') as f:
        return json.load(f)


# ==========================================================================
# f1: _base_dismiss_vocab 加 '不要再提'
# ==========================================================================
class TestF1DismissVocabExpanded(unittest.TestCase):

    def test_buyao_zaiti_in_dismiss_vocab(self):
        data = _load_json('memory_pool/_base_dismiss_vocab.json')
        patterns = data.get('patterns', [])
        self.assertIn('不要再提', patterns,
                       "Sir 真用 '不要再提' 必须在 dismiss vocab")
        self.assertIn('不要提了', patterns)

    def test_correction_dispatcher_fires_on_sir_21_32(self):
        """Sir 真话应触发 correction_dispatcher directive."""
        from jarvis_directives import (
            DirectiveContext, _trigger_correction_dispatcher,
        )
        ctx = DirectiveContext(
            user_input='嗯，不要再提这个科医复习的事情了，我们要把面试提到最重要的是',
        )
        # vocab cache reset (test isolation)
        import jarvis_directives as _d
        _d._CORRECTION_DISPATCHER_CACHE = None
        fired = _trigger_correction_dispatcher(ctx)
        self.assertTrue(fired,
            "correction_dispatcher 应在 Sir 真话上 fire (含 '不要再提' + '最重要')")


# ==========================================================================
# f2: _base_correction_vocab 加 priority correction phrases
# ==========================================================================
class TestF2CorrectionVocabExpanded(unittest.TestCase):

    def test_priority_phrases_in_correction_vocab(self):
        data = _load_json('memory_pool/_base_correction_vocab.json')
        patterns = data.get('patterns', [])
        required = ['最重要的是', '提到最重要', '我们要把', '其实是',
                    '你忘了', '才是最重要']
        for req in required:
            self.assertIn(req, patterns,
                f"_base_correction_vocab 必须含 '{req}' (Sir priority correction phrase)")


# ==========================================================================
# f3: correction_dispatcher directive 加 例 6 PRIORITY CORRECTION
# ==========================================================================
class TestF3DirectiveTeachesPriorityMutation(unittest.TestCase):

    def test_directive_text_has_example_6(self):
        src = _read('jarvis_directives.py')
        self.assertIn('PRIORITY CORRECTION', src,
                       'directive 必须有 PRIORITY CORRECTION 例 6')
        self.assertIn('profile.current_priority', src,
                       '必须教 field_path=profile.current_priority')

    def test_directive_text_anchors_sir_21_32(self):
        src = _read('jarvis_directives.py')
        # 例 6 anchor Sir 21:32 真测
        self.assertIn('Sir 2026-05-25 21:32', src,
                       '必须 anchor Sir 21:32 真测痛点')
        self.assertIn('no_tool_called', src,
                       '必须警告 INTEGRITY no_tool_called')


# ==========================================================================
# f4: ConcernFeedback a 必出约束
# ==========================================================================
class TestF4ConcernFeedbackAMust(unittest.TestCase):

    def test_prompt_has_a_must_constraint(self):
        src = _read('jarvis_concern_feedback.py')
        self.assertIn('a) ✅ MUST', src,
                       'prompt 必须有 a MUST 约束')
        self.assertIn('即使该 concern 当前 severity 几乎 0', src,
                       'prompt 必须教即使 severity 低也要输出 a entry')

    def test_prompt_anchors_sir_21_32_pain(self):
        src = _read('jarvis_concern_feedback.py')
        self.assertIn('2026-05-25 21:32', src,
                       'prompt 必须 anchor Sir 21:32 真测痛点')
        self.assertIn('a 是 MUST', src,
                       '强调 a 是 MUST 而非 optional')


if __name__ == '__main__':
    unittest.main()
