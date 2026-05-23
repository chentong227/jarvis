# -*- coding: utf-8 -*-
"""[P5-fix78 / 2026-05-23 21:25] Phase 4b.3 + 4b.2 — persona trim.

4b.3: JARVIS_CORE_PERSONA STM TAGS + CLAIM HONESTY 静态精简 (~1K)
4b.2: _is_light_tier guard 跳 4 个重型 block (~2K for WAKE_ONLY/SHORT_CHAT)
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def _read(p: str) -> str:
    with open(ROOT / p, 'r', encoding='utf-8') as f:
        return f.read()


# ============================================================
# Phase 4b.3 — JARVIS_CORE_PERSONA 静态精简
# ============================================================
class TestPhase4b3PersonaShrunk(unittest.TestCase):

    def test_4b3_persona_smaller_than_baseline(self):
        from jarvis_central_nerve import JARVIS_CORE_PERSONA
        # baseline 19:00 = 8641 chars, target after 4b.3 ≤ 7700
        self.assertLessEqual(
            len(JARVIS_CORE_PERSONA), 7700,
            f'fix78-4b.3: persona 应 ≤ 7700 chars (was 8641), now {len(JARVIS_CORE_PERSONA)}'
        )
        # 也不能砍太狠 < 6000 那核心可能没了
        self.assertGreaterEqual(
            len(JARVIS_CORE_PERSONA), 6500,
            f'fix78-4b.3: persona 不能 < 6500 (核心可能丢)'
        )

    def test_4b3_stm_tags_compressed(self):
        from jarvis_central_nerve import JARVIS_CORE_PERSONA
        # 4 个 source tag 必须仍可识别
        for tag in ('[SIR]', '[SYS]', '[JARVIS]', '[AMBIENT]'):
            self.assertIn(tag, JARVIS_CORE_PERSONA,
                          f'fix78-4b.3: {tag} 必须保留 (主脑解析 STM 用)')

    def test_4b3_integrity_claim_honesty_compressed(self):
        from jarvis_central_nerve import JARVIS_CORE_PERSONA
        # 关键 keyword 必须保留
        self.assertIn('FACTUAL CLAIM', JARVIS_CORE_PERSONA,
                      'fix78-4b.3: CLAIM HONESTY 核心保留')
        self.assertIn('uncertainty', JARVIS_CORE_PERSONA,
                      'fix78-4b.3: uncertainty marker 概念保留')
        self.assertIn('hallucination', JARVIS_CORE_PERSONA,
                      'fix78-4b.3: hallucination 警告保留')

    def test_4b3_integrity_absolute_preserved(self):
        """INTEGRITY ABSOLUTE forbidden list 必须完整保留 (核心反幻觉)"""
        from jarvis_central_nerve import JARVIS_CORE_PERSONA
        for phrase in ('I have adjusted', "I've silenced", 'I shall',
                        'while you rest', '我会继续', '准则 5'):
            self.assertIn(phrase, JARVIS_CORE_PERSONA,
                          f'fix78-4b.3: forbidden 关键例子 "{phrase}" 必须保留')


# ============================================================
# Phase 4b.2 — light tier guard
# ============================================================
class TestPhase4b2LightTierGuard(unittest.TestCase):

    def test_4b2_is_light_tier_flag_exists(self):
        src = _read('jarvis_central_nerve.py')
        self.assertIn('_is_light_tier', src,
                      'fix78-4b.2: _is_light_tier 标志应存在')
        self.assertIn('PROMPT_TIER_WAKE_ONLY', src,
                      'fix78-4b.2: 标志应包 WAKE_ONLY')
        self.assertIn('PROMPT_TIER_SHORT_CHAT', src,
                      'fix78-4b.2: 标志应包 SHORT_CHAT')

    def test_4b2_sir_mental_model_guarded(self):
        src = _read('jarvis_central_nerve.py')
        # render_prompt_block as _tom_block 上下应该有 _is_light_tier guard
        import re
        m = re.search(
            r'if not _is_light_tier:\s*\n\s*from jarvis_sir_mental_model',
            src,
        )
        self.assertIsNotNone(
            m, 'fix78-4b.2: sir_mental_model import 应在 if not _is_light_tier 内'
        )

    def test_4b2_watch_task_guarded(self):
        src = _read('jarvis_central_nerve.py')
        import re
        m = re.search(
            r'if not _is_light_tier:\s*\n\s*from jarvis_watch_task',
            src,
        )
        self.assertIsNotNone(
            m, 'fix78-4b.2: watch_task import 应在 if not _is_light_tier 内'
        )

    def test_4b2_screen_vision_guarded(self):
        src = _read('jarvis_central_nerve.py')
        import re
        m = re.search(
            r'if not _is_light_tier:\s*\n\s*from jarvis_screen_vision',
            src,
        )
        self.assertIsNotNone(
            m, 'fix78-4b.2: screen_vision import 应在 if not _is_light_tier 内'
        )

    def test_4b2_sleep_routine_guarded(self):
        src = _read('jarvis_central_nerve.py')
        # sleep_routine_armed events: 条件加 'and not _is_light_tier'
        self.assertIn(
            "_bus_sr is not None and not _is_light_tier", src,
            'fix78-4b.2: sleep_routine_evidence 应有 not _is_light_tier guard'
        )

    def test_4b2_sir_status_NOT_guarded(self):
        """sir_status (Sir 状态) light tier 也要知道 — 不应被 gate."""
        src = _read('jarvis_central_nerve.py')
        # sir_status_tracker 不应有 _is_light_tier guard
        import re
        # 找 sir_status_tracker render 周围 ±5 lines, 不能有 _is_light_tier
        m = re.search(
            r'from jarvis_sir_status_tracker.{0,200}render_status_block_for_prompt',
            src, re.DOTALL,
        )
        self.assertIsNotNone(m, 'sir_status_tracker render 调用应存在')
        # 看前 5 行没 _is_light_tier
        idx = src.find('from jarvis_sir_status_tracker')
        pre = src[max(0, idx - 500):idx]
        # pre 区段最后 50 字符不应有 _is_light_tier
        # (pre 末尾应是 try: 而不是 if not _is_light_tier:)
        last_50 = pre[-50:]
        self.assertNotIn(
            '_is_light_tier', last_50,
            'fix78-4b.2: sir_status_tracker 不应被 _is_light_tier gate'
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
