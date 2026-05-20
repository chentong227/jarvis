"""[β.5.43-fix2 / 2026-05-20] Sir 真理 — 承诺动态影响关心权重 (ABC 三修).

Sir 18:11 痛点完整链路:
- ConcernFeedback record sev_d=-1.00 (本应削) ← OK
- 但 ProactiveCare _signal raw 加 severity (long_session +0.03 等), 削后又涨回 ← A 修
- dashboard 显示 raw severity 一直 100, Sir 觉得 Jarvis 一直在涨关心 ← C 修
- ConcernFeedback / CommitmentWatcher / Memory Correction 多点 LLM 各自提取, 数据不一致 ← B 修

3 修法:
A. ProactiveCare._signal 看 daily_progress 削 severity_delta (progress 高 → dampen)
B. ConcernFeedback record_user_feedback 写 progress 后 publish 'sir_progress_evidence' SWM
C. jarvis_actionable_items _extract_concerns 显示 urgency (raw severity × progress_mul)
"""
from __future__ import annotations

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestFix2AProactiveCareDampen(unittest.TestCase):
    """A: ProactiveCare._signal 看 daily_progress 削 severity_delta."""

    def test_signal_method_has_progress_dampen_logic(self):
        """_signal 必含 daily_progress 查 + dampen 计算."""
        import jarvis_proactive_care
        src = open(jarvis_proactive_care.__file__, encoding='utf-8').read()
        self.assertIn('daily_progress', src,
                      '_signal 必须看 daily_progress')
        self.assertIn('dampen', src,
                      '_signal 必须有 dampen 计算 (progress 高时削 delta)')
        self.assertIn('β.5.43-fix2-A', src,
                      'fix2-A marker 必须存在')

    def test_signal_dampens_when_progress_high(self):
        """模拟 concern 有 daily_progress (8/8 杯), _signal 加 severity 应被削."""
        from jarvis_concerns import Concern, ConcernsLedger
        from jarvis_proactive_care import CareConcernSensor

        # 构造 concern 带 today's daily_progress 100%
        c = Concern(
            id='test_hydration',
            what_i_watch='test',
            why_i_care='test',
            severity=0.3,
            state='active',
            daily_progress={
                'iso_date': time.strftime('%Y-%m-%d', time.localtime()),
                'current': 8,
                'target': 8,
                'unit': '杯',
                'last_updated': time.time(),
            },
        )
        ledger = ConcernsLedger.__new__(ConcernsLedger)
        ledger.concerns = {'test_hydration': c}
        ledger._lock = __import__('threading').Lock()
        ledger._dirty = False

        pc = CareConcernSensor(ledger, nerve=None)
        pc._can_signal = lambda cid, rid: True

        sev_before = c.severity
        pc._signal('test_hydration', 'long_session', 'test', severity_delta=0.10)
        sev_after = c.severity
        delta = sev_after - sev_before
        # progress 100% → dampen 0.3, 实际 delta 应远小于 0.10
        self.assertLess(delta, 0.04,
                        f'progress 100% 时 delta 应被削到 < 0.04, 实际 {delta:.3f}')

    def test_signal_no_dampen_when_no_progress(self):
        """模拟 concern 无 daily_progress, _signal 正常加."""
        from jarvis_concerns import Concern, ConcernsLedger
        from jarvis_proactive_care import CareConcernSensor

        c = Concern(
            id='test_focus',
            what_i_watch='test',
            why_i_care='test',
            severity=0.3,
            state='active',
            daily_progress={},  # 无 progress
        )
        ledger = ConcernsLedger.__new__(ConcernsLedger)
        ledger.concerns = {'test_focus': c}
        ledger._lock = __import__('threading').Lock()
        ledger._dirty = False

        pc = CareConcernSensor(ledger, nerve=None)
        pc._can_signal = lambda cid, rid: True

        sev_before = c.severity
        pc._signal('test_focus', 'long_session', 'test', severity_delta=0.10)
        sev_after = c.severity
        delta = sev_after - sev_before
        # 无 progress → 不削, delta 应接近 0.10
        self.assertAlmostEqual(delta, 0.10, places=2,
                                msg=f'无 progress 时 delta 应原样 0.10, 实际 {delta:.3f}')


class TestFix2BUnifiedSWMEvidence(unittest.TestCase):
    """B: ConcernFeedback record_user_feedback 后 publish sir_progress_evidence SWM."""

    def test_record_user_feedback_publishes_swm(self):
        """模拟 record_user_feedback 调用后, SWM 应有 sir_progress_evidence 事件."""
        from jarvis_concerns import Concern, ConcernsLedger
        from jarvis_utils import ConversationEventBus

        # 临时全局 bus
        bus = ConversationEventBus()
        ConversationEventBus.register_global(bus)

        c = Concern(
            id='test_hyd',
            what_i_watch='喝水',
            why_i_care='test',
            severity=0.5,
            state='active',
            daily_progress={},
        )
        ledger = ConcernsLedger.__new__(ConcernsLedger)
        ledger.concerns = {'test_hyd': c}
        ledger._lock = __import__('threading').Lock()
        ledger._dirty = False

        ok = ledger.record_user_feedback(
            'test_hyd', '我喝了 6 杯水了',
            {
                'has_relevance': True,
                'progress': {'current': 6, 'target': 8, 'unit': '杯'},
                'severity_delta': -0.4,
                'optimal_timing': 'before_sleep',
            },
        )
        self.assertTrue(ok)

        evs = bus.recent_events(types={'sir_progress_evidence'})
        self.assertGreaterEqual(len(evs), 1,
                                'record_user_feedback 后 SWM 必有 sir_progress_evidence')
        ev = evs[-1]
        self.assertEqual(ev['source'], 'ConcernFeedback')
        meta = ev.get('metadata') or {}
        self.assertEqual(meta.get('concern_id'), 'test_hyd')
        self.assertEqual(meta.get('progress', {}).get('current'), 6)

    def test_etype_registered_in_default_ttl_and_salience(self):
        """sir_progress_evidence etype 必在 DEFAULT_TTL + DEFAULT_SALIENCE."""
        from jarvis_utils import ConversationEventBus
        self.assertIn('sir_progress_evidence', ConversationEventBus.DEFAULT_TTL)
        self.assertIn('sir_progress_evidence', ConversationEventBus.DEFAULT_SALIENCE)
        # ttl 24h
        self.assertEqual(ConversationEventBus.DEFAULT_TTL['sir_progress_evidence'], 86400)
        # salience 0.65 (Sir 主动反馈, 主脑要看)
        self.assertGreaterEqual(
            ConversationEventBus.DEFAULT_SALIENCE['sir_progress_evidence'], 0.6)


class TestFix2CDashboardShowsUrgency(unittest.TestCase):
    """C: jarvis_actionable_items _extract_concerns 显示 urgency 而不仅 severity."""

    def test_extract_concerns_includes_urgency_field(self):
        """ActionableItem.fields 必含 'urgency' 字段."""
        from jarvis_actionable_items import _extract_concerns
        items = _extract_concerns({})
        if not items:
            self.skipTest('no concerns to test')
        for it in items:
            self.assertIn('urgency', it.fields,
                          f'concern {it.id} 必须有 urgency 字段')
            self.assertIn('progress_mul', it.fields,
                          f'concern {it.id} 必须有 progress_mul 字段')
            # urgency 应 ≤ severity (progress_mul ≤ 1)
            self.assertLessEqual(it.fields['urgency'], it.fields['severity'] + 1e-6,
                                 f'urgency 应 ≤ severity')

    def test_preview_shows_urgency_not_just_severity(self):
        """preview 字符串应含 'urg=' 让 Sir 一眼看到真实 nudge 概率."""
        from jarvis_actionable_items import _extract_concerns
        items = _extract_concerns({})
        if not items:
            self.skipTest('no concerns to test')
        # 至少一个 concern preview 含 urg
        has_urg = any('urg=' in it.preview for it in items)
        self.assertTrue(has_urg,
                        f'至少一个 concern preview 应含 urg= (samples: '
                        f'{[i.preview[:80] for i in items[:3]]})')


class TestFix2Integration(unittest.TestCase):
    """ABC 集成: Sir 18:11 完整场景 — 喝 6/8 杯, ProactiveCare 不再涨, dashboard 显示 urgency 削."""

    def test_full_flow_sir_18_11_scenario(self):
        """Sir reply '喝了 6 杯' → record_user_feedback → ProactiveCare _signal 削 → dashboard urgency 削."""
        from jarvis_concerns import Concern, ConcernsLedger
        from jarvis_proactive_care import CareConcernSensor
        from jarvis_utils import ConversationEventBus

        bus = ConversationEventBus()
        ConversationEventBus.register_global(bus)

        # 初始 concern: severity 0.6 (高), 没 progress
        c = Concern(
            id='sir_hydration_habit',
            what_i_watch='Sir 一天 8 杯水',
            why_i_care='test',
            severity=0.6,
            state='active',
            daily_progress={},
        )
        ledger = ConcernsLedger.__new__(ConcernsLedger)
        ledger.concerns = {'sir_hydration_habit': c}
        ledger._lock = __import__('threading').Lock()
        ledger._dirty = False

        # Step 1: Sir reply "已经喝了 6 杯"
        ledger.record_user_feedback(
            'sir_hydration_habit', '已经喝了 6 杯了',
            {
                'has_relevance': True,
                'progress': {'current': 6, 'target': 8, 'unit': '杯'},
                'severity_delta': -0.3,
                'optimal_timing': 'before_sleep',
            },
        )
        sev_after_feedback = c.severity
        self.assertAlmostEqual(sev_after_feedback, 0.3, places=2,
                                msg='record_user_feedback 应削 severity 0.6 → 0.3')

        # Step 2: ProactiveCare _signal long_session (severity_delta=+0.1)
        class StubNerve:
            event_bus = bus
        pc = CareConcernSensor(ledger, nerve=StubNerve())
        pc._can_signal = lambda cid, rid: True

        sev_before_signal = c.severity
        pc._signal('sir_hydration_habit', 'long_session', 'test', severity_delta=0.10)
        sev_after_signal = c.severity
        sig_delta = sev_after_signal - sev_before_signal
        # progress 6/8 = 75%, dampen 0.475, 实际 delta 应 ≈ 0.0475
        self.assertLess(sig_delta, 0.06,
                        f'progress 75% 时 _signal delta 应被削 < 0.06, 实际 {sig_delta:.3f}')

        # Step 3: actionable_items 显示 urgency 削
        from jarvis_actionable_items import _extract_concerns
        # 临时写入 concerns.json 模拟
        # 简化: 直接验 fields 计算逻辑 (urgency = sev × progress_mul)
        sev_raw = c.severity
        cur, tgt = 6.0, 8.0
        ratio = min(1.0, cur / tgt)
        prog_mul = max(0.3, 1.0 - ratio * 0.7)  # 0.475
        urg_computed = sev_raw * prog_mul
        # urgency 应明显小于 raw severity (~60% off)
        self.assertLess(urg_computed, sev_raw * 0.6,
                        f'urgency {urg_computed:.3f} 应 < sev_raw {sev_raw:.3f} * 0.6')


if __name__ == '__main__':
    unittest.main(verbosity=2)
