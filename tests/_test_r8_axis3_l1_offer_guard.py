# -*- coding: utf-8 -*-
"""[轴3-L1 / 2026-05-15] OfferGuard 中央闸 — 测试套件

覆盖：
  TestOfferRequirementsConfig    — OFFER_REQUIREMENTS 配置完整性
  TestOfferGuardRhythm           — 节奏闸（min_interval_s）
  TestOfferGuardCapability       — capability 闸（offer_help 必须有 healthy safe）
  TestOfferGuardUnknownType      — 未知 nudge_type 默认放行
  TestOfferGuardMarkSpoken       — mark_spoken 更新 last_ts
  TestNudgeGateOfferGuardIntegration — 源码契约 + can_speak 兜底
  TestVerifiableCases            — Cs1 (10:23 path_b suggest_break) / Cs2 (offer_help 宽泛)

跑法：
    cd d:\\Jarvis
    python tests/_test_r8_axis3_l1_offer_guard.py
"""
import os
import sys
import time
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_skill_registry import (
    SkillRegistry,
    SkillManifest,
    OfferGuard,
    OFFER_REQUIREMENTS,
    REQ_ANY_HEALTHY_SAFE,
    DANGER_SAFE,
    DANGER_RISKY,
    DANGER_DANGEROUS,
    get_registry,
)


def _make(command='audio.list', danger=DANGER_SAFE, **k):
    base = dict(command=command, module='m', callable_name='c',
                description='d', dangerous_flag=danger)
    base.update(k)
    return SkillManifest(**base)


# ==========================================================================
# 配置完整性
# ==========================================================================

class TestOfferRequirementsConfig(unittest.TestCase):
    """OFFER_REQUIREMENTS 必须覆盖所有已知 nudge_type"""

    def test_all_nudge_types_have_entry(self):
        """已知 8 种 nudge_type 至少都要在配置里"""
        expected = {'check_in', 'return_greeting', 'commitment_check',
                    'suggest_break', 'late_night', 'flow_end', 'offer_help',
                    'context_switch_alert', 'atmosphere'}
        for nt in expected:
            self.assertIn(nt, OFFER_REQUIREMENTS,
                f"OFFER_REQUIREMENTS 缺少 {nt!r}")

    def test_each_entry_has_required_keys(self):
        for nt, spec in OFFER_REQUIREMENTS.items():
            self.assertIn('requires', spec, f"{nt} 缺 requires")
            self.assertIn('min_interval_s', spec, f"{nt} 缺 min_interval_s")
            self.assertIn('note', spec, f"{nt} 缺 note")

    def test_offer_help_requires_any_healthy_safe(self):
        """offer_help 必须 require 某种能力（修 Cs2 宽泛 offer）"""
        spec = OFFER_REQUIREMENTS['offer_help']
        self.assertIn(REQ_ANY_HEALTHY_SAFE, spec['requires'])

    def test_suggest_break_has_2h_rhythm(self):
        """suggest_break 必须有 2h 节奏（修 Cs1 path_b 绕过）"""
        spec = OFFER_REQUIREMENTS['suggest_break']
        self.assertGreaterEqual(spec['min_interval_s'], 7200)


# ==========================================================================
# 节奏闸
# ==========================================================================

class TestOfferGuardRhythm(unittest.TestCase):

    def setUp(self):
        OfferGuard.reset_for_test()
        SkillRegistry.reset_instance_for_test()

    def tearDown(self):
        OfferGuard.reset_for_test()
        SkillRegistry.reset_instance_for_test()

    def test_first_call_passes(self):
        ok, reason = OfferGuard.check_offer('suggest_break',
                                            publish_event_bus_on_block=False)
        self.assertTrue(ok, f"首次调用应放行，reason={reason}")

    def test_second_call_within_cooldown_blocked(self):
        OfferGuard.mark_spoken('suggest_break')
        ok, reason = OfferGuard.check_offer('suggest_break',
                                            publish_event_bus_on_block=False)
        self.assertFalse(ok)
        self.assertIn('rhythm_cooldown', reason)
        self.assertIn('remaining_', reason)

    def test_call_after_cooldown_passes(self):
        # 模拟 last_ts 在 8000s 之前
        OfferGuard._last_offer_ts['suggest_break'] = time.time() - 8000
        ok, _ = OfferGuard.check_offer('suggest_break',
                                       publish_event_bus_on_block=False)
        self.assertTrue(ok)

    def test_zero_interval_never_blocks_on_rhythm(self):
        """min_interval_s=0 的 nudge_type（如 commitment_check）不被节奏挡"""
        # commitment_check 没 capability 要求 + 节奏 0
        ok, _ = OfferGuard.check_offer('commitment_check',
                                       publish_event_bus_on_block=False)
        self.assertTrue(ok)
        OfferGuard.mark_spoken('commitment_check')
        ok, _ = OfferGuard.check_offer('commitment_check',
                                       publish_event_bus_on_block=False)
        self.assertTrue(ok, '节奏 0 → 立刻可再 publish')


# ==========================================================================
# capability 闸
# ==========================================================================

class TestOfferGuardCapability(unittest.TestCase):

    def setUp(self):
        OfferGuard.reset_for_test()
        SkillRegistry.reset_instance_for_test()
        self.reg = get_registry()

    def tearDown(self):
        OfferGuard.reset_for_test()
        SkillRegistry.reset_instance_for_test()

    def test_offer_help_blocked_when_no_safe_skill(self):
        """空 registry → offer_help 拒"""
        ok, reason = OfferGuard.check_offer('offer_help',
                                            publish_event_bus_on_block=False)
        self.assertFalse(ok)
        self.assertIn('no_healthy_safe_skill_to_offer', reason)

    def test_offer_help_blocked_when_only_dangerous(self):
        self.reg.register(_make('file.delete', danger=DANGER_DANGEROUS))
        ok, reason = OfferGuard.check_offer('offer_help',
                                            publish_event_bus_on_block=False)
        self.assertFalse(ok, 'dangerous 不能算 offer 资格')

    def test_offer_help_passes_when_safe_skill_healthy(self):
        self.reg.register(_make('audio.list', danger=DANGER_SAFE))
        ok, _ = OfferGuard.check_offer('offer_help',
                                       publish_event_bus_on_block=False)
        self.assertTrue(ok)

    def test_offer_help_blocked_when_safe_skill_degraded(self):
        self.reg.register(_make('audio.list', danger=DANGER_SAFE))
        # 让它失败 10 次
        for _ in range(10):
            self.reg.record_invocation('audio.list', success=False)
        ok, reason = OfferGuard.check_offer('offer_help',
                                            publish_event_bus_on_block=False)
        self.assertFalse(ok, 'safe skill degraded → offer_help 拒')


# ==========================================================================
# 未知 nudge_type
# ==========================================================================

class TestOfferGuardUnknownType(unittest.TestCase):

    def setUp(self):
        OfferGuard.reset_for_test()

    def test_unknown_nudge_type_default_allow(self):
        """未注册的 nudge_type → 默认放行（不挡新功能）"""
        ok, reason = OfferGuard.check_offer('brand_new_type_xyz',
                                            publish_event_bus_on_block=False)
        self.assertTrue(ok)
        self.assertIn('unknown_nudge_type', reason)

    def test_empty_nudge_type_default_allow(self):
        ok, _ = OfferGuard.check_offer('', publish_event_bus_on_block=False)
        self.assertTrue(ok)


# ==========================================================================
# mark_spoken
# ==========================================================================

class TestOfferGuardMarkSpoken(unittest.TestCase):

    def setUp(self):
        OfferGuard.reset_for_test()

    def test_mark_spoken_updates_last_ts(self):
        before = OfferGuard._last_offer_ts.get('check_in', 0)
        OfferGuard.mark_spoken('check_in')
        after = OfferGuard._last_offer_ts['check_in']
        self.assertGreater(after, before)


# ==========================================================================
# NudgeGate 集成 (源码契约)
# ==========================================================================

class TestNudgeGateOfferGuardIntegration(unittest.TestCase):
    """jarvis_nerve.py NudgeGate.can_speak 必须接 OfferGuard 兜底"""

    @classmethod
    def setUpClass(cls):
        # [P0+19-6.a / 2026-05-16] NudgeGate 已搬到 jarvis_sentinels.py，用 corpus 扫描
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        cls.src = read_nerve_corpus()

    def test_marker_present(self):
        self.assertIn('[轴3-L1 / 2026-05-15]', self.src,
            'jarvis_nerve.py 必须有 [轴3-L1] marker')

    def test_offer_guard_pass_method_exists(self):
        self.assertIn('def _offer_guard_pass', self.src,
            'NudgeGate 必须有 _offer_guard_pass 方法')

    def test_can_speak_calls_offer_guard_for_normal_path(self):
        """can_speak 普通路径必须调 _offer_guard_pass"""
        import re
        m = re.search(
            r'def can_speak\(self.*?if nudge_type and not self\._offer_guard_pass\(nudge_type\)',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            'can_speak 必须在普通路径调 _offer_guard_pass(nudge_type)')

    def test_can_speak_calls_offer_guard_for_urgent_path(self):
        """is_urgent 路径也必须调 OfferGuard（修 Cs1 path_b is_urgent=True 绕过）"""
        import re
        # 找 if is_urgent: 块内是否有 _offer_guard_pass 调用
        m = re.search(
            r'if is_urgent:\s*\n.*?_offer_guard_pass',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            'is_urgent 路径必须调 _offer_guard_pass（修 Cs1 path_b 绕过）')

    def test_offer_guard_failure_safe_default_pass(self):
        """OfferGuard 异常时必须默认放行（不卡死现有逻辑）"""
        import re
        m = re.search(
            r'def _offer_guard_pass.*?except Exception:\s*\n\s*return True',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            '_offer_guard_pass 必须 try/except + 异常时 return True')


# ==========================================================================
# 验收 Cases (10:23 实测 case + offer_help 宽泛 case)
# ==========================================================================

class TestVerifiableCases(unittest.TestCase):
    """轴 3 看板的验收 case 必须真过"""

    def setUp(self):
        OfferGuard.reset_for_test()
        SkillRegistry.reset_instance_for_test()
        self.reg = get_registry()

    def tearDown(self):
        OfferGuard.reset_for_test()
        SkillRegistry.reset_instance_for_test()

    def test_cs1_path_b_cannot_bypass_suggest_break_cooldown(self):
        """Cs1 (10:23): path_a 触发 suggest_break 后，2h 内 path_b 不能再触发。
        OfferGuard 节奏闸是中央化的 → path_a 和 path_b 都过同一道闸。"""
        # path_a 触发
        ok1, _ = OfferGuard.check_offer('suggest_break',
                                        publish_event_bus_on_block=False)
        self.assertTrue(ok1, 'path_a 第一次应通过')
        OfferGuard.mark_spoken('suggest_break')
        # path_b 试图绕过（哪怕过 1 小时也不行）
        OfferGuard._last_offer_ts['suggest_break'] = time.time() - 3600  # 1h
        ok2, reason = OfferGuard.check_offer('suggest_break',
                                             publish_event_bus_on_block=False)
        self.assertFalse(ok2, 'path_b 在 2h cooldown 内必须被挡')
        self.assertIn('rhythm_cooldown', reason)

    def test_cs2_offer_help_blocked_when_no_real_capability(self):
        """Cs2: 没有真能力时不能开口"替我排查 403"。
        registry 空 / 只有 dangerous skill → offer_help 必须被挡"""
        # 空 registry
        ok, reason = OfferGuard.check_offer('offer_help',
                                            publish_event_bus_on_block=False)
        self.assertFalse(ok, '空 registry → offer_help 必须挡')
        self.assertIn('no_healthy_safe_skill_to_offer', reason)

    def test_cs2_offer_help_passes_with_real_safe_capability(self):
        """Cs2 续：注册 KeyHealthInspector 后 offer_help 通过"""
        self.reg.register(_make('key_health_inspector.report_status',
                                danger=DANGER_SAFE,
                                description='排查 API key 健康状态 (例如 403 错误根因)'))
        ok, _ = OfferGuard.check_offer('offer_help',
                                       publish_event_bus_on_block=False)
        self.assertTrue(ok, '有 healthy safe skill → offer_help 应通过')


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("[OK] All R8 axis3 L1 OfferGuard tests passed.")
    else:
        print(f"[FAIL] {len(result.failures)} failures, {len(result.errors)} errors")
    print("=" * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
