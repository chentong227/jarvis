# -*- coding: utf-8 -*-
"""[Sir 2026-05-25 20:23 真测追根 BUG 治本] 4 路线 regression test.

源 BUG (Sir 真测 log: jarvis_20260525_200517.log):
  - Turn 1 (20:21:47): 主脑回 "Noted... That puts you at" 半截没 ZH (LLM 自然 stop)
  - Turn 2 (20:22:24): 主脑混 silo, 用 progress.status track_id 查 (从未 register)
                       → not found → 迷茫输出 '---' 被 Audio Guard 剥空

4 路线治本 (Sir 选 '3 者都上' + 加 Turn 2 silo 治本):
  - t0: jarvis_concerns.py to_prompt_block 注入 daily_progress (Turn 2 真根因)
  - t1: jarvis_chat_bypass.py truncate 检 → spawn thread 调 flash_lite 续写补 ZH
  - t2: jarvis_soul_evaluator.py truncate override → alignment='no' 不被漏抓
  - t3: jarvis_directives.py bilingual_truncated_recover directive +
        _trigger_bilingual_truncated_recover trigger 看 SWM 自决复述
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(name: str) -> str:
    with open(os.path.join(ROOT, name), 'r', encoding='utf-8') as f:
        return f.read()


class TestT0DailyProgressInjectedInPromptBlock(unittest.TestCase):
    """t0: to_prompt_block 注入 daily_progress (Turn 2 silo 真根因治本)."""

    def test_to_prompt_block_emits_today_progress(self):
        from jarvis_concerns import Concern, ConcernsLedger
        import tempfile, time
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            persist = f.name
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            review = f.name
        try:
            ledger = ConcernsLedger(persist_path=persist, review_path=review)
            c = Concern(
                id='sir_hydration_habit',
                what_i_watch='Sir 今天喝水',
                why_i_care='Sir 健康',
                severity=0.5,
                state='active',
            )
            today_iso = time.strftime('%Y-%m-%d', time.localtime())
            c.daily_progress = {
                'current': 1100, 'target': 3000, 'unit': 'ml',
                'iso_date': today_iso, 'last_updated': time.time(),
            }
            ledger.concerns[c.id] = c
            block = ledger.to_prompt_block(top_n=3, max_chars=800)
            # 关键: prompt 注入了 progress 数据
            self.assertIn('today progress', block,
                           '主脑 prompt 必须看到 today progress')
            self.assertIn('1100', block, 'current 必须注入')
            self.assertIn('3000', block, 'target 必须注入')
            self.assertIn('ml', block, 'unit 必须注入')
            self.assertIn('remaining', block, 'remaining 应 derive (主脑直接答)')
            self.assertIn('1900', block, 'remaining=1900 应算出')
        finally:
            for p in (persist, review):
                try:
                    os.unlink(p)
                except Exception:
                    pass

    def test_to_prompt_block_skip_stale_progress(self):
        """跨天旧 daily_progress (iso_date != today) 不注入."""
        from jarvis_concerns import Concern, ConcernsLedger
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            persist = f.name
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            review = f.name
        try:
            ledger = ConcernsLedger(persist_path=persist, review_path=review)
            c = Concern(
                id='sir_hydration_habit',
                what_i_watch='Sir 今天喝水',
                why_i_care='Sir 健康',
                severity=0.5,
                state='active',
            )
            c.daily_progress = {
                'current': 500, 'target': 3000, 'unit': 'ml',
                'iso_date': '2020-01-01',  # stale
            }
            ledger.concerns[c.id] = c
            block = ledger.to_prompt_block(top_n=3, max_chars=800)
            self.assertNotIn('today progress', block,
                              'stale (跨天) daily_progress 不该注入')
        finally:
            for p in (persist, review):
                try:
                    os.unlink(p)
                except Exception:
                    pass


class TestT1ChatBypassTruncateContinuation(unittest.TestCase):
    """t1: chat_bypass 检 truncate → spawn thread 调 flash_lite 续写."""

    def test_truncate_continuation_worker_exists(self):
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('_truncate_continuation_worker', src,
                       'chat_bypass 必须含 truncate 续写 worker')

    def test_truncate_continuation_uses_flash_lite(self):
        src = _read('jarvis_chat_bypass.py')
        # 关键: 调 flash_lite (轻量, 准则 8 优雅高效)
        self.assertIn("model='flash_lite'", src,
                       '续写必须用 flash_lite (准则 8 优雅高效)')

    def test_truncate_continuation_skips_cache(self):
        src = _read('jarvis_chat_bypass.py')
        # 关键: force=True 不走 cache (truncate 续写每次新算)
        # 找 truncate 区段
        idx = src.find('_truncate_continuation_worker')
        self.assertGreater(idx, 0)
        block = src[idx:idx + 2500]
        self.assertIn('force=True', block, '续写不走 cache')


class TestT2SoulEvaluatorTruncateOverride(unittest.TestCase):
    """t2: SoulEvaluator truncate override → 强 alignment='no'."""

    def test_evaluator_has_truncate_override_block(self):
        src = _read('jarvis_soul_evaluator.py')
        self.assertIn('TRUNCATE-OVERRIDE', src,
                       'SoulEvaluator 必须含 TRUNCATE-OVERRIDE 标记')
        self.assertIn('TruncateOverride', src,
                       'SoulEvaluator bg_log 必须 grep-able')

    def test_evaluator_override_block_checks_zh_marker(self):
        src = _read('jarvis_soul_evaluator.py')
        idx = src.find('TRUNCATE-OVERRIDE')
        self.assertGreater(idx, 0)
        block = src[max(0, idx - 1500):idx + 500]
        self.assertIn('---ZH---', block, '必须检 ---ZH--- 是否缺')
        self.assertIn("alignment = 'no'", block, '强降级 alignment=no')


class TestT3DirectiveBilingualTruncatedRecover(unittest.TestCase):
    """t3: bilingual_truncated_recover directive + trigger."""

    def test_directive_registered(self):
        src = _read('jarvis_directives.py')
        self.assertIn("id='bilingual_truncated_recover'", src,
                       'directive id 必须为 bilingual_truncated_recover')
        self.assertIn('_trigger_bilingual_truncated_recover', src,
                       'trigger 函数必须定义')

    def test_trigger_reads_swm_bilingual_truncated(self):
        from jarvis_directives import _trigger_bilingual_truncated_recover
        from jarvis_directives import DirectiveContext
        from jarvis_utils import ConversationEventBus
        # 用 fresh bus 注册全局
        bus = ConversationEventBus()
        ConversationEventBus.register_global(bus)
        ctx = DirectiveContext(user_input='hi', stm=[],
                                tier='SHORT_CHAT')
        # 1. 无 event → trigger False
        self.assertFalse(_trigger_bilingual_truncated_recover(ctx),
                          '无 SWM bilingual_truncated event 不该 fire')
        # 2. publish event → trigger True
        bus.publish(
            etype='bilingual_truncated',
            description='test truncate',
            source='test',
            salience=0.5,
        )
        self.assertTrue(_trigger_bilingual_truncated_recover(ctx),
                         'SWM 含 bilingual_truncated event 时必须 fire')

    def test_directive_text_evidence_only_no_hardcode_phrase(self):
        """准则 6: directive 必须 evidence-only, 不硬编码 'Sir~' / 句式."""
        src = _read('jarvis_directives.py')
        idx = src.find("id='bilingual_truncated_recover'")
        self.assertGreater(idx, 0)
        block = src[idx:idx + 2000]
        # 必须用 SWM evidence 字段
        self.assertIn('SWM', block, 'directive 必须 reference SWM evidence')
        self.assertIn('en_snippet', block,
                       'directive 必须教主脑用 SWM en_snippet 作为 anchor')


if __name__ == '__main__':
    unittest.main()
