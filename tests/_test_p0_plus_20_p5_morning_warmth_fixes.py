# -*- coding: utf-8 -*-
"""[P5-fixA/B/C/D / 2026-05-21 09:35-10:00] 早起问候 hot fix cover.

Sir 09:05-09:12 真测 3 连发数落 + hallucination — 真治本 4 fix:
  A. morning_mood_judge trigger 改用 SWM `afk_return` event (替 is_first_active_today race)
  B. 加 morning_warmth_priority directive (priority 11, always-on 6-10am+afk>4h)
  C. ReturnSentinel publish proactive_nudge_fired SWM + SmartNudge/Conductor/ProactiveCare 看 SWM 让位
  D. JARVIS_PREFLIGHT 默认 ON (取代之前默认 off)
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# A. morning_mood_judge trigger fix (race condition 修)
# ============================================================
class TestA_MorningMoodTriggerSWM(unittest.TestCase):
    """[P5-fixA] trigger 改用 SWM afk_return event metadata (替 is_first_active_today race)."""

    def test_trigger_returns_false_outside_morning_window(self):
        from jarvis_directives import _trigger_morning_mood_judge, DirectiveContext
        ctx = DirectiveContext(
            user_input='',
            current_hour=14,  # afternoon, 不在 6-10
            last_jarvis_reply='',
            tier='SHORT_CHAT',
        )
        self.assertFalse(_trigger_morning_mood_judge(ctx))

    def test_trigger_uses_swm_afk_return_metadata(self):
        """trigger 改用 SWM event 不再看 is_first_active_today flag."""
        from jarvis_directives import _trigger_morning_mood_judge, DirectiveContext

        ctx = DirectiveContext(
            user_input='',
            current_hour=9,  # in 6-10
            last_jarvis_reply='',
            tier='SHORT_CHAT',
        )

        # mock _swm_event_meta to return afk_minutes=300 (>240, overnight)
        with patch('jarvis_directives._swm_event_meta') as _mock:
            _mock.return_value = {'afk_minutes': 300, 'first_today': True}
            self.assertTrue(_trigger_morning_mood_judge(ctx))
            _mock.assert_called_once_with('afk_return', max_age_s=900.0)

    def test_trigger_returns_false_when_afk_short(self):
        """afk_minutes < 240 (短 AFK 不是过夜) → 不 fire."""
        from jarvis_directives import _trigger_morning_mood_judge, DirectiveContext
        ctx = DirectiveContext(
            user_input='', current_hour=8, last_jarvis_reply='',
            tier='SHORT_CHAT',
        )
        with patch('jarvis_directives._swm_event_meta') as _mock:
            _mock.return_value = {'afk_minutes': 60}  # 1h, 不是 overnight
            self.assertFalse(_trigger_morning_mood_judge(ctx))

    def test_trigger_returns_false_when_no_swm_event(self):
        from jarvis_directives import _trigger_morning_mood_judge, DirectiveContext
        ctx = DirectiveContext(
            user_input='', current_hour=8, last_jarvis_reply='',
            tier='SHORT_CHAT',
        )
        with patch('jarvis_directives._swm_event_meta') as _mock:
            _mock.return_value = None
            self.assertFalse(_trigger_morning_mood_judge(ctx))

    def test_swm_event_meta_helper_exists(self):
        """_swm_event_meta helper 存在 + callable."""
        from jarvis_directives import _swm_event_meta
        self.assertTrue(callable(_swm_event_meta))


# ============================================================
# B. morning_warmth_priority directive
# ============================================================
class TestB_MorningWarmthDirective(unittest.TestCase):
    """[P5-fixB] 加 morning_warmth_priority directive 教主脑早起原则."""

    def _seed_only_directives(self):
        """force seed-only path (no JSON vocab) → 拿 fresh registry 含 _SEED_DEFS, return list."""
        from jarvis_directives import DirectiveRegistry, _bootstrap_seed_only
        reg = DirectiveRegistry()
        _bootstrap_seed_only(reg)
        return list(reg.directives.values())

    def test_directive_registered_in_seed(self):
        directives = self._seed_only_directives()
        ids = {d.id for d in directives}
        self.assertIn('morning_warmth_priority', ids)

    def test_directive_priority_11(self):
        """priority=11 (高于 capability_boundary=10, 低于 no_hallucinated=12)."""
        directives = self._seed_only_directives()
        target = next(d for d in directives if d.id == 'morning_warmth_priority')
        self.assertEqual(target.priority, 11)

    def test_directive_text_forbids_weaponize(self):
        """text 含 FORBIDDEN tone fragments + DO NOT lead with negative."""
        directives = self._seed_only_directives()
        target = next(d for d in directives if d.id == 'morning_warmth_priority')
        self.assertIn('DO NOT lead with negative facts', target.text)
        self.assertIn('FORBIDDEN tone fragments', target.text)
        self.assertIn('significantly overlooked', target.text)

    def test_directive_reuses_morning_mood_trigger(self):
        """morning_warmth + morning_mood 复用同 trigger (跨夜 morning 6-10)."""
        from jarvis_directives import _trigger_morning_mood_judge
        directives = self._seed_only_directives()
        warmth = next(d for d in directives if d.id == 'morning_warmth_priority')
        self.assertIs(warmth.trigger, _trigger_morning_mood_judge)


# ============================================================
# C. nudge coordination — 多 sentinel 让位最近 proactive nudge
# ============================================================
class TestC_NudgeCoordination(unittest.TestCase):
    """[P5-fixC] ReturnSentinel / SmartNudge / Conductor / ProactiveCare 互让位."""

    def test_helper_module_imports(self):
        import jarvis_nudge_coordination as nc
        self.assertTrue(callable(nc.should_yield_to_recent_proactive_nudge))
        self.assertTrue(callable(nc.publish_proactive_nudge_fired))
        self.assertTrue(callable(nc.publish_proactive_nudge_skipped))

    def test_yield_check_no_bus_returns_false(self):
        """no event_bus → don't yield (defensive)."""
        from jarvis_nudge_coordination import should_yield_to_recent_proactive_nudge
        with patch('jarvis_nudge_coordination.__name__', new='jarvis_nudge_coordination'):
            # 直接 patch get_event_bus in jarvis_utils
            with patch('jarvis_utils.get_event_bus') as _bus_mock:
                _bus_mock.return_value = None
                yld, reason = should_yield_to_recent_proactive_nudge(
                    within_s=600.0,
                    current_kind='commitment_check',
                    current_sentinel='SmartNudge',
                )
                self.assertFalse(yld)

    def test_yield_check_with_recent_nudge_yields(self):
        """SWM 含 proactive_nudge_fired < 600s 内 → 让位."""
        from jarvis_nudge_coordination import should_yield_to_recent_proactive_nudge

        fake_top = [
            {
                'type': 'proactive_nudge_fired',
                '_age_s': 100,  # 100s ago, < 600
                'metadata': {'kind': 'return_greeting', 'sentinel': 'ReturnSentinel'},
            }
        ]

        class _MockBus:
            def top_n(self, n=20):
                return fake_top

        with patch('jarvis_utils.get_event_bus') as _bus_mock:
            _bus_mock.return_value = _MockBus()
            yld, reason = should_yield_to_recent_proactive_nudge(
                within_s=600.0,
                current_kind='commitment_check',
                current_sentinel='SmartNudge',
            )
            self.assertTrue(yld)
            self.assertIn('return_greeting', reason)

    def test_yield_check_too_old_does_not_yield(self):
        """SWM 含 proactive_nudge_fired 但 > 600s 内 → 不让位."""
        from jarvis_nudge_coordination import should_yield_to_recent_proactive_nudge

        fake_top = [
            {
                'type': 'proactive_nudge_fired',
                '_age_s': 700,
                'metadata': {'kind': 'return_greeting', 'sentinel': 'ReturnSentinel'},
            }
        ]

        class _MockBus:
            def top_n(self, n=20):
                return fake_top

        with patch('jarvis_utils.get_event_bus') as _bus_mock:
            _bus_mock.return_value = _MockBus()
            yld, _reason = should_yield_to_recent_proactive_nudge(
                within_s=600.0,
                current_kind='commitment_check',
                current_sentinel='SmartNudge',
            )
            self.assertFalse(yld)

    def test_yield_check_same_sentinel_same_kind_does_not_yield(self):
        """SmartNudge 自己上次 fire 的 commitment_check 不算让位 (避免自我 deadlock)."""
        from jarvis_nudge_coordination import should_yield_to_recent_proactive_nudge

        fake_top = [
            {
                'type': 'proactive_nudge_fired',
                '_age_s': 100,
                'metadata': {'kind': 'commitment_check', 'sentinel': 'SmartNudge'},
            }
        ]

        class _MockBus:
            def top_n(self, n=20):
                return fake_top

        with patch('jarvis_utils.get_event_bus') as _bus_mock:
            _bus_mock.return_value = _MockBus()
            yld, _reason = should_yield_to_recent_proactive_nudge(
                within_s=600.0,
                current_kind='commitment_check',
                current_sentinel='SmartNudge',
            )
            self.assertFalse(yld)

    def test_return_sentinel_publishes_after_fire(self):
        """ReturnSentinel _on_return 真 fire 后调 publish_proactive_nudge_fired."""
        import jarvis_return_sentinel
        with open(jarvis_return_sentinel.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('publish_proactive_nudge_fired', src)
        self.assertIn("'return_greeting'", src)

    def test_commitment_watcher_checks_yield_before_dispatch(self):
        """CommitmentWatcher._dispatch_commitment_nudge 先 check yield."""
        import jarvis_commitment_watcher
        with open(jarvis_commitment_watcher.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('should_yield_to_recent_proactive_nudge', src)
        self.assertIn("'commitment_check'", src)

    def test_conductor_checks_yield_in_both_paths(self):
        """Conductor _execute_path_a + _execute_path_b 都 check yield."""
        import jarvis_conductor
        with open(jarvis_conductor.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # 应至少 2 次 yield_check (path_a + path_b)
        self.assertGreaterEqual(src.count('should_yield_to_recent_proactive_nudge'), 2)

    def test_proactive_care_checks_yield(self):
        """ProactiveCare push_command 前 check yield."""
        import jarvis_proactive_care
        with open(jarvis_proactive_care.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('should_yield_to_recent_proactive_nudge', src)
        self.assertIn("'proactive_care'", src)


# ============================================================
# D. PreFlight default ON (取代 default off)
# ============================================================
class TestC2_AmbientSensorInitFix(unittest.TestCase):
    """[P5-fix-AmbientBus / 2026-05-21 09:55] Sir 09:53 真测真报
    'init 异常不启用: VoiceListenThread object has no attribute jarvis'.

    AmbientSensor 整个 sprint 从启动起没工作 — 主脑 ambient_state SWM signal
    一直 0. 治本: 改用 jarvis_utils.get_event_bus() 全局 singleton, 不依赖类
    继承链.
    """

    def test_ambient_init_no_self_jarvis_in_voice_listen_thread(self):
        """worker.py 的 AmbientSensor init block 不能用 self.jarvis."""
        import jarvis_worker
        with open(jarvis_worker.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # 提取 AmbientSensor init block (在 VoiceListenThread.run() 内)
        anchor = '[β.5.40-A1'
        idx = src.find(anchor)
        self.assertGreater(idx, 0, 'AmbientSensor init block 找不到')
        # 截 anchor 后 800 chars 看是否含 self.jarvis (不该有)
        section = src[idx:idx + 800]
        # block 内不能再有 self.jarvis (注释里有 'self.jarvis' 是 BUG 说明, 不算 — 检查代码 line)
        for line in section.split('\n'):
            stripped = line.strip()
            if stripped.startswith('#') or stripped.startswith("'") or stripped.startswith('"'):
                continue
            self.assertNotIn(
                'self.jarvis',
                line,
                f'AmbientSensor init block 仍含 self.jarvis: {line.strip()}',
            )

    def test_ambient_init_uses_get_event_bus(self):
        """改用 jarvis_utils.get_event_bus() 全局 singleton."""
        import jarvis_worker
        with open(jarvis_worker.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        anchor = '[β.5.40-A1'
        idx = src.find(anchor)
        section = src[idx:idx + 1200]
        self.assertIn('get_event_bus', section)


class TestD_PreFlightDefaultOn(unittest.TestCase):
    """[P5-fixD] JARVIS_PREFLIGHT 默认 ON, Sir 关掉设 =0."""

    def setUp(self):
        from jarvis_reply_preflight import reset_default_preflight_for_test
        reset_default_preflight_for_test()

    def test_default_no_env_enabled(self):
        """no env var → enabled (default ON)."""
        from jarvis_reply_preflight import is_enabled
        os.environ.pop('JARVIS_PREFLIGHT', None)
        self.assertTrue(is_enabled())

    def test_env_zero_disabled(self):
        """JARVIS_PREFLIGHT=0 → disabled."""
        from jarvis_reply_preflight import is_enabled
        os.environ['JARVIS_PREFLIGHT'] = '0'
        try:
            self.assertFalse(is_enabled())
        finally:
            os.environ.pop('JARVIS_PREFLIGHT', None)

    def test_env_one_enabled(self):
        """JARVIS_PREFLIGHT=1 → enabled (backward compat)."""
        from jarvis_reply_preflight import is_enabled
        os.environ['JARVIS_PREFLIGHT'] = '1'
        try:
            self.assertTrue(is_enabled())
        finally:
            os.environ.pop('JARVIS_PREFLIGHT', None)

    def test_env_other_treated_as_on(self):
        """任何非 '0' 值都视为 ON (类似 fix3 默认开)."""
        from jarvis_reply_preflight import is_enabled
        os.environ['JARVIS_PREFLIGHT'] = 'true'
        try:
            self.assertTrue(is_enabled())
        finally:
            os.environ.pop('JARVIS_PREFLIGHT', None)


if __name__ == '__main__':
    unittest.main()
