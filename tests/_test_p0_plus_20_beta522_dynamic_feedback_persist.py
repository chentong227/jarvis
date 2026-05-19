# -*- coding: utf-8 -*-
"""[P0+20-β.5.22 / 2026-05-19] β.5.22 全集 testcase.

覆盖 sub-step:
- β.5.22-A: dismissal flow → gate.activate_sleep_mode()
- β.5.22-B: ProactiveCare CareWindowGuard 看 _sleep_intent_until
- β.5.22-E: ReturnSentinel deactivate_sleep_mode → _check_short_sleep
- β.5.22-G: sleep_intent due timer 到点提醒
- β.5.22-F: refusal vocab JSON + dismissal_soft/sleep_soft 早退
- β.5.22-C: Concern.daily_progress + record_user_feedback + urgency 计算

测试模式: 静态源码扫 marker + 关键代码段, runtime 行为模拟 (mock-based).
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# ============================================================
# β.5.22-A: dismissal flow → activate_sleep_mode
# ============================================================

class TestBeta522ADismissalActivatesSleepMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_worker.py'))

    def test_marker(self):
        self.assertIn('β.5.22-A', self.src)

    def test_dismissal_calls_activate_sleep_mode(self):
        """is_dismissal=True 分支必须调 gate.activate_sleep_mode()."""
        # 找 "if is_dismissal:" 路径里有 activate_sleep_mode
        idx = self.src.find('if is_dismissal:')
        self.assertGreater(idx, 0, 'is_dismissal 分支必须存在')
        # 取后面 800 字符看
        snippet = self.src[idx:idx + 1500]
        self.assertIn('activate_sleep_mode', snippet,
            'dismissal 分支必须调 activate_sleep_mode')


# ============================================================
# β.5.22-B: CareWindowGuard 看 _sleep_intent_until
# ============================================================

class TestBeta522BCareWindowGuardSleepIntent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_proactive_care.py'))

    def test_marker(self):
        self.assertIn('β.5.22-B', self.src)

    def test_sleep_intent_window_check(self):
        """can_speak 必须含 _sleep_intent_until check."""
        self.assertIn('_sleep_intent_until', self.src,
            'CareWindowGuard 必须读 worker._sleep_intent_until')
        self.assertIn('sleep_intent_window', self.src,
            '必须有 sleep_intent_window 返回 reason')


# ============================================================
# β.5.22-E: ReturnSentinel deactivate → _check_short_sleep
# ============================================================

class TestBeta522EReturnSentinelShortSleepCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_return_sentinel.py'))

    def test_marker(self):
        self.assertIn('β.5.22-E', self.src)

    def test_deactivate_calls_check_short_sleep(self):
        """ReturnSentinel 解除 sleep_mode 时必须调 _check_short_sleep."""
        self.assertIn('_check_short_sleep', self.src,
            'ReturnSentinel 必须调 nerve._check_short_sleep')


# ============================================================
# β.5.22-G: sleep_intent due timer
# ============================================================

class TestBeta522GSleepIntentDueTimer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_worker.py'))

    def test_marker(self):
        self.assertIn('β.5.22-G', self.src)

    def test_fire_sleep_due_nudge_exists(self):
        self.assertIn('_fire_sleep_due_nudge', self.src,
            '必须定义 _fire_sleep_due_nudge 方法')

    def test_due_timer_scheduled(self):
        self.assertIn('_sleep_intent_due_timer', self.src,
            '必须用 _sleep_intent_due_timer 名 schedule')

    def test_due_timer_cancelled_on_cancel(self):
        """cancel_sleep_routine 必须同步 cancel due timer."""
        idx = self.src.find('def cancel_sleep_routine')
        self.assertGreater(idx, 0)
        snippet = self.src[idx:idx + 800]
        self.assertIn('_sleep_intent_due_timer', snippet,
            'cancel_sleep_routine 必须 cancel due timer')

    def test_due_nudge_type_sleep_due(self):
        """push 的 nudge type='sleep_due' (新类型)."""
        self.assertIn("'type': 'sleep_due'", self.src,
            "nudge type 必须 'sleep_due'")


# ============================================================
# β.5.22-F: refusal vocab JSON + dismissal_soft/sleep_soft 早退
# ============================================================

class TestBeta522FRefusalVocab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_worker.py'))
        cls.vocab_path = os.path.join(ROOT, 'memory_pool', 'refusal_vocab.json')

    def test_vocab_json_exists(self):
        self.assertTrue(os.path.exists(self.vocab_path),
            f'{self.vocab_path} must exist')

    def test_vocab_has_all_4_categories(self):
        with open(self.vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for cat in ('generic', 'strong', 'dismissal_soft', 'sleep_soft'):
            self.assertIn(cat, data, f'vocab 必须含 {cat}')
            self.assertTrue(isinstance(data[cat], list))

    def test_vocab_dismissal_soft_has_byebye(self):
        with open(self.vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('\u62dc\u62dc', data['dismissal_soft'],
            'dismissal_soft 必须含 "拜拜"')

    def test_vocab_sleep_soft_has_hao(self):
        """Sir 说 '好' 应在 sleep_soft 表里 — 不算 refusal."""
        with open(self.vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('\u597d\u7684', data['sleep_soft'],
            'sleep_soft 必须含 "好的"')

    def test_marker(self):
        self.assertIn('β.5.22-F', self.src)

    def test_load_refusal_vocab_method_exists(self):
        self.assertIn('_load_refusal_vocab', self.src,
            '必须有 _load_refusal_vocab 方法')

    def test_dismissal_soft_early_return_in_detect(self):
        """_detect_help_refusal 必须有 dismissal_soft 早退."""
        idx = self.src.find('def _detect_help_refusal')
        self.assertGreater(idx, 0)
        snippet = self.src[idx:idx + 2500]
        self.assertIn('dismissal_soft', snippet,
            '_detect_help_refusal 必须有 dismissal_soft 早退')
        self.assertIn('sleep_soft', snippet,
            '_detect_help_refusal 必须有 sleep_soft 早退')

    def test_cli_tool_exists(self):
        cli = os.path.join(ROOT, 'scripts', 'refusal_vocab_dump.py')
        self.assertTrue(os.path.exists(cli),
            'CLI tool refusal_vocab_dump.py 必须存在')


# ============================================================
# β.5.22-C: Concern.daily_progress + record_user_feedback + urgency
# ============================================================

class TestBeta522CConcernsLedgerFeedback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src_concerns = _read(os.path.join(ROOT, 'jarvis_concerns.py'))
        cls.src_pc = _read(os.path.join(ROOT, 'jarvis_proactive_care.py'))
        cls.src_worker = _read(os.path.join(ROOT, 'jarvis_worker.py'))

    def test_marker_in_concerns(self):
        self.assertIn('β.5.22-C', self.src_concerns)

    def test_marker_in_pc(self):
        self.assertIn('β.5.22-C', self.src_pc)

    def test_concern_has_daily_progress_field(self):
        self.assertIn('daily_progress', self.src_concerns)
        self.assertIn('last_user_feedback', self.src_concerns)
        self.assertIn('optimal_timing', self.src_concerns)

    def test_record_user_feedback_method_exists(self):
        self.assertIn('def record_user_feedback', self.src_concerns,
            'ConcernsLedger 必须有 record_user_feedback')

    def test_urgency_uses_progress_mul(self):
        self.assertIn('progress_mul', self.src_pc,
            'compute_urgency 必须用 progress_mul')

    def test_urgency_uses_timing_mul(self):
        self.assertIn('timing_mul', self.src_pc,
            'compute_urgency 必须用 timing_mul')

    def test_worker_has_judge_hook(self):
        """worker 必须在 user_input 处理时调 judge_async."""
        self.assertIn('judge_async', self.src_worker,
            'worker 必须调 ConcernFeedbackJudge.judge_async')
        self.assertIn('jarvis_concern_feedback', self.src_worker,
            'worker 必须 import jarvis_concern_feedback')

    def test_judge_module_exists(self):
        jcf = os.path.join(ROOT, 'jarvis_concern_feedback.py')
        self.assertTrue(os.path.exists(jcf),
            'jarvis_concern_feedback.py 必须存在')


class TestBeta522CRuntimeRecordFeedback(unittest.TestCase):
    """runtime 测 record_user_feedback 行为."""

    def setUp(self):
        from jarvis_concerns import ConcernsLedger, Concern, STATE_ACTIVE
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.ledger = ConcernsLedger(
            persist_path=os.path.join(self.tmp, 'c.json'),
            review_path=os.path.join(self.tmp, 'r.json'),
        )
        self.ledger.register(Concern(
            id='sir_hydration_habit',
            what_i_watch='Sir hydration target 8 cups',
            why_i_care='dehydration affects work',
            severity=0.6,
            state=STATE_ACTIVE,
        ))

    def test_record_feedback_writes_daily_progress(self):
        judgement = {
            'has_relevance': True,
            'progress': {'current': 6, 'target': 8, 'unit': 'cups'},
            'severity_delta': -0.3,
            'optimal_timing': 'before_sleep',
        }
        ok = self.ledger.record_user_feedback(
            'sir_hydration_habit', "我喝了 6 杯了", judgement)
        self.assertTrue(ok, 'record_user_feedback 应返 True')
        c = self.ledger.get('sir_hydration_habit')
        self.assertEqual(c.daily_progress.get('current'), 6)
        self.assertEqual(c.daily_progress.get('target'), 8)
        self.assertEqual(c.optimal_timing, 'before_sleep')
        # severity 应被 -0.3 削
        self.assertAlmostEqual(c.severity, 0.3, places=2)
        # last_user_feedback 记录
        self.assertEqual(c.last_user_feedback.get('raw_text'), "我喝了 6 杯了")

    def test_no_relevance_skips_record(self):
        judgement = {'has_relevance': False}
        ok = self.ledger.record_user_feedback(
            'sir_hydration_habit', "今天天气好", judgement)
        self.assertFalse(ok, 'has_relevance=False 应返 False')

    def test_urgency_削_with_progress(self):
        """6/8 杯 → progress_mul ≈ 0.475 (削 52.5%)."""
        from jarvis_proactive_care import CareSignalCollector
        # 先写 progress
        self.ledger.record_user_feedback(
            'sir_hydration_habit', "6 cups done", {
                'has_relevance': True,
                'progress': {'current': 6, 'target': 8},
            })
        c = self.ledger.get('sir_hydration_habit')
        collector = CareSignalCollector(self.ledger)
        urg, bd = collector.compute_urgency(c, time.time())
        self.assertLess(bd['progress_mul'], 0.8,
            f'progress_mul should be <0.8 with 6/8 progress, got {bd["progress_mul"]}')
        self.assertGreater(bd['progress_mul'], 0.3,
            'progress_mul should be >0.3 (not full削)')


# ============================================================
# β.5.22 整合 (Sir 设计哲学 — 准则 6 + 准则 5)
# ============================================================

class TestBeta522IntegritySirDesign(unittest.TestCase):
    """Sir 01:34 设计哲学修正必须落地的 charter."""

    def test_no_hardcoded_minus_02_decay(self):
        """Sir 直指: '不能说我回应一次固定-0.2'.
        record_user_feedback 应让 LLM 判 severity_delta, 不硬编码 -0.2."""
        src = _read(os.path.join(ROOT, 'jarvis_concerns.py'))
        idx = src.find('def record_user_feedback')
        self.assertGreater(idx, 0)
        snippet = src[idx:idx + 2500]
        # severity_delta 应来自 judgement, 不是硬编码
        self.assertIn('severity_delta', snippet)
        self.assertNotIn('= -0.2', snippet,
            '不应硬编码 -0.2 衰减')

    def test_dont_close_concern_use_削权_instead(self):
        """Sir 指: '不要 close, 用动态削权'. progress_mul 不应 0."""
        src = _read(os.path.join(ROOT, 'jarvis_proactive_care.py'))
        idx = src.find('progress_mul = max(')
        self.assertGreater(idx, 0)
        # max(0.3, ...) — 0.3 floor 表示永远不全 close
        self.assertIn('max(0.3', src[idx:idx + 100],
            'progress_mul 应有 0.3 floor — 不 close, 仅削')

    def test_optimal_timing_supports_before_sleep(self):
        """Sir 痛点: 睡前 30min 提醒喝最后一杯 — before_sleep 必须 supported."""
        src = _read(os.path.join(ROOT, 'jarvis_proactive_care.py'))
        self.assertIn("'before_sleep'", src,
            'urgency 计算必须支持 before_sleep timing')


if __name__ == '__main__':
    unittest.main(verbosity=2)
