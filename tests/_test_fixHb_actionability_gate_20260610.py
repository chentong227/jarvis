# -*- coding: utf-8 -*-
"""[fixH-b 可行动性门控 / Sir 2026-06-10] body_stir 唤醒前判"醒来能干什么".

设计 (工单#2): 仅当本轮**所有**过阈非豁免 fresh delta 都是 [tension × concern: ×
concern_nudge_map 命中 × OfferGuard.check_offer 拒且 reason=rhythm_cooldown*] 才压住
唤醒; 任何不确定 → fail-open 照醒. 被压指纹绝不写 _last_woke_delta_fp (cooldown 解除
后下轮 poll 必醒). 开关 rest.body_stir_actionability_gate=false 完全旁路.

G1  tension+映射中+cooldown 中 → 不醒 (resting 保持, 指纹不记)
G2  cooldown 过 → 醒
G3  novelty 豁免仍醒 (cooldown 中也醒)
G4  映射不中 → 醒
G5  check_offer 抛异常 → 醒 (fail-open)
G6  被压指纹不入 _last_woke_delta_fp; cooldown 解后下轮可醒
G7  开关 false → 旁路 (cooldown 中也醒)
G8  非 concern node (thread:) tension → 醒
G9  skill 类 reason (missing/degraded) → 醒 (skill 坏不该让体哑掉)
G10 混合 delta (一个可压 + 一个映射不中) → ALL 量词不满足 → 醒
G11 _resolve_concern_nudge_type: exact / 最长 prefix / 不中
红线: 纯 mock/临时 state, 不写真档案; OfferGuard 状态测后 reset.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def _build_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    mock_router = MagicMock()
    mock_ledger = MagicMock()
    mock_ledger.list_active = MagicMock(return_value=[])
    daemon = InnerThoughtDaemon(key_router=mock_router, concerns_ledger=mock_ledger)
    daemon._resting = True
    return daemon


def _focus_item(node, magnitude, kind='tension', fresh=True):
    return {
        'node': node, 'kind': kind, 'why': kind,
        'magnitude': magnitude,
        'score': magnitude + 1.0 if fresh else magnitude,
        'fresh': fresh, 'text': '',
    }


class _FakeFocus:
    def __init__(self, items):
        self._items = list(items)

    def has_fresh_delta(self, *, min_magnitude=0.0):
        return any(it.get('fresh') and float(it.get('magnitude', 0.0)) >= min_magnitude
                   for it in self._items)

    def current_focus(self, *, limit=6):
        return list(self._items)[:limit]


class TestFixHbActionabilityGate(unittest.TestCase):

    def setUp(self):
        import jarvis_body_focus as bf
        import jarvis_utils as ju
        from jarvis_skill_registry import OfferGuard
        self._orig_get_focus = bf.get_body_focus
        self.addCleanup(lambda: setattr(bf, 'get_body_focus', self._orig_get_focus))
        # gate_mode 钉死 'hard' (不受本机 gate_mode_vocab.json 影响, 测试确定性)
        self._orig_read_gate_mode = ju.read_gate_mode
        ju.read_gate_mode = lambda name: 'hard'
        self.addCleanup(lambda: setattr(ju, 'read_gate_mode', self._orig_read_gate_mode))
        # OfferGuard 节奏状态隔离 (类级单例)
        OfferGuard.reset_for_test()
        self.addCleanup(OfferGuard.reset_for_test)

    # ---- helpers ----

    def _patch_focus(self, items):
        import jarvis_body_focus as bf
        bf.get_body_focus = lambda: _FakeFocus(items)

    def _bedtime_cooldown_on(self):
        """真 OfferGuard 路径: mark_spoken('bedtime') → 3600s rhythm_cooldown 生效。"""
        from jarvis_skill_registry import OfferGuard
        OfferGuard.mark_spoken('bedtime')

    # ---- G1 ----
    def test_g1_tension_mapped_cooldown_suppresses(self):
        daemon = _build_daemon()
        self._patch_focus([_focus_item('concern:sir_sleep_streak', 0.6)])
        self._bedtime_cooldown_on()
        self.assertFalse(daemon._check_body_stir(),
                         "老张力+映射中+cooldown 中 → 应压住不唤醒")
        self.assertTrue(daemon._resting, "未醒应保持 _resting=True")
        self.assertFalse(daemon._last_woke_delta_fp,
                         "被压 delta 指纹不应写入 _last_woke_delta_fp")

    # ---- G2 ----
    def test_g2_cooldown_passed_wakes(self):
        daemon = _build_daemon()
        self._patch_focus([_focus_item('concern:sir_sleep_streak', 0.6)])
        # 无 mark_spoken → 无 rhythm cooldown → check_offer ok → 醒
        self.assertTrue(daemon._check_body_stir(), "cooldown 过/未起 → 应唤醒")
        self.assertFalse(daemon._resting)

    # ---- G3 ----
    def test_g3_novelty_exempt_still_wakes(self):
        daemon = _build_daemon()
        self._bedtime_cooldown_on()
        self._patch_focus([_focus_item('thread:t1', 0.6, kind='novelty')])
        self.assertTrue(daemon._check_body_stir(), "novelty 豁免 → cooldown 中也醒")

    # ---- G4 ----
    def test_g4_map_miss_wakes(self):
        daemon = _build_daemon()
        self._bedtime_cooldown_on()
        self._patch_focus([_focus_item('concern:sir_water', 0.6)])
        self.assertTrue(daemon._check_body_stir(),
                        "映射不中 (sir_water 不在 map) → 不敢判 → 照醒")

    # ---- G5 ----
    def test_g5_offer_probe_exception_fail_open(self):
        from jarvis_skill_registry import OfferGuard
        daemon = _build_daemon()
        self._patch_focus([_focus_item('concern:sir_sleep_streak', 0.6)])
        orig = OfferGuard._evaluate_internal
        try:
            OfferGuard._evaluate_internal = classmethod(
                lambda cls, *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
            self.assertTrue(daemon._check_body_stir(),
                            "节奏探针异常 → fail-open 照醒")
        finally:
            OfferGuard._evaluate_internal = orig

    # ---- G6 ----
    def test_g6_suppressed_fp_not_recorded_then_wakes_after_release(self):
        from jarvis_skill_registry import OfferGuard
        daemon = _build_daemon()
        self._patch_focus([_focus_item('concern:sir_sleep_streak', 0.6)])
        self._bedtime_cooldown_on()
        self.assertFalse(daemon._check_body_stir(), "cooldown 中第一轮: 压住")
        self.assertFalse(daemon._last_woke_delta_fp, "压住期指纹必须为空")
        # cooldown 解除 (reset 节奏状态) → 同 delta 下轮 poll → 必醒
        OfferGuard.reset_for_test()
        self.assertTrue(daemon._check_body_stir(),
                        "cooldown 解除后下轮 poll 必须能醒 (指纹未被污染)")
        self.assertFalse(daemon._resting)

    # ---- G7 ----
    def test_g7_switch_off_bypasses(self):
        import jarvis_inner_thought_daemon as mod
        daemon = _build_daemon()
        self._patch_focus([_focus_item('concern:sir_sleep_streak', 0.6)])
        self._bedtime_cooldown_on()
        orig = mod._load_saturation_config
        try:
            cfg = orig()
            patched = {k: dict(v) if isinstance(v, dict) else v for k, v in cfg.items()}
            patched['rest'] = dict(patched.get('rest', {}))
            patched['rest']['body_stir_actionability_gate'] = False
            mod._load_saturation_config = lambda: patched
            self.assertTrue(daemon._check_body_stir(),
                            "开关 false → 完全旁路 → cooldown 中也醒 (原行为)")
        finally:
            mod._load_saturation_config = orig

    # ---- G8 ----
    def test_g8_non_concern_node_wakes(self):
        daemon = _build_daemon()
        self._bedtime_cooldown_on()
        self._patch_focus([_focus_item('thread:t2', 0.6, kind='tension')])
        self.assertTrue(daemon._check_body_stir(),
                        "非 concern node 的 tension → 不敢判 → 照醒")

    # ---- G9 ----
    def test_g9_skill_reason_wakes(self):
        from jarvis_skill_registry import OfferGuard
        daemon = _build_daemon()
        self._patch_focus([_focus_item('concern:sir_sleep_streak', 0.6)])
        orig = OfferGuard._evaluate_internal
        try:
            OfferGuard._evaluate_internal = classmethod(
                lambda cls, *a, **k: (False, 'missing_skill:foo'))
            self.assertTrue(daemon._check_body_stir(),
                            "skill 类 reason → 照醒 (skill 坏不该让体哑掉)")
        finally:
            OfferGuard._evaluate_internal = orig

    # ---- G12 (真机配置场景: gate_mode=publish_only 时门控仍有效) ----
    def test_g12_gate_effective_under_publish_only_mode(self):
        """真机 gate_mode_vocab 现 OfferGuard=publish_only (check_offer 永 True).
        探针走 _evaluate_internal 不掺 gate_mode → 门控在真机配置下仍能压住。"""
        import jarvis_utils as ju
        daemon = _build_daemon()
        ju.read_gate_mode = lambda name: 'publish_only'  # 模拟真机档
        self._patch_focus([_focus_item('concern:sir_sleep_streak', 0.6)])
        self._bedtime_cooldown_on()
        self.assertFalse(daemon._check_body_stir(),
                         "publish_only 档下门控必须仍有效 (探针绕 gate_mode 政策)")
        self.assertTrue(daemon._resting)

    # ---- G10 ----
    def test_g10_mixed_deltas_any_unmapped_wakes(self):
        daemon = _build_daemon()
        self._bedtime_cooldown_on()
        self._patch_focus([
            _focus_item('concern:sir_sleep_streak', 0.6),   # 可压
            _focus_item('concern:sir_water', 0.6),          # 映射不中
        ])
        self.assertTrue(daemon._check_body_stir(),
                        "ALL 量词: 任一 delta 不满足门控条件 → 整轮照醒")

    # ---- G11 ----
    def test_g11_resolver_exact_prefix_miss(self):
        from jarvis_inner_thought_daemon import _resolve_concern_nudge_type
        self.assertEqual(_resolve_concern_nudge_type('sir_sleep_streak'), 'bedtime',
                         "exact 命中")
        self.assertEqual(_resolve_concern_nudge_type('sir_sleep_quality'), 'bedtime',
                         "prefix sir_sleep 命中")
        self.assertEqual(_resolve_concern_nudge_type('sir_water'), '', "不中 → ''")
        self.assertEqual(_resolve_concern_nudge_type(''), '', "空 id → ''")


if __name__ == '__main__':
    unittest.main(verbosity=2)
