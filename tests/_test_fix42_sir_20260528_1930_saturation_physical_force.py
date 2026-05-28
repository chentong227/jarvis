"""fix42 (Sir 2026-05-28 19:30) — Saturation 物理 force 覆盖测.

Sir 真意 anchor: "Jarvis 该懂得自己休息. 没必要花时间想这么多, 我又不需要".

设计 (准则 6 三维耦合 + 准则 8 优雅):
  - 数据强耦合: `_check_and_update_saturation` 算 counter + publish SWM
  - 行为弱耦合: counter 达阈写 `_saturation_force_due` 标志 (不 hard mutate)
  - 决策集中主脑: 标志由 `_resolve_next_interval` 读, force NEXT_INTERVAL
                  = `force_next_interval_s` (类 _SMOOTH_LOW_SAL 物理保底)
  - vocab: `memory_pool/inner_thought_saturation_config.json`
  - CLI: `scripts/inner_thought_saturation_dump.py`

测试覆盖 (11 个):
  L1 saturation check: 不足 N thought → False, counter=0
  L2 saturation check: cross-category recent N → False, counter=0
  L3 saturation check: 任一 should_speak=True → False, counter=0
  L4 saturation check: actionable done (有 effect) → False, counter=0
  L5 saturation check: 三条件全 OK + counter < threshold → True 仅当达阈
  L6 saturation check: counter 达阈 → return True (force 触发)
  L7 saturation check: 中间非 saturated → counter 清 0, 不累计
  L8 resolve: force_due=True + LLM 选 30 → force 600 + 'saturation_force'
  L9 resolve: force_due=True + LLM default (=0) → force 600 + 'saturation_force'
  L10 resolve: force_due=True + LLM 选 180 (> max_short) → 不 force, 走 case 4 → 'llm_chosen'
  L11 resolve: config enabled=False + force_due=True + LLM 30 → 不 force, 走 case 4 → 'llm_chosen'
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _build_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    tmp = os.path.join(
        tempfile.gettempdir(),
        f'saturation_force_{time.time()}.jsonl',
    )
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp
    try:
        d = InnerThoughtDaemon(key_router=None)
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp
    return d


def _mk_thought(
    next_int: int = 0,
    sal: float = 0.5,
    cat: str = 'A',
    actionable: str = 'none',
    actionable_done: bool = False,
    actionable_result: str = '',
    should_speak: bool = False,
):
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id=f't_{time.time()}_{id(object())}',
        ts=time.time(),
        ts_iso='?',
        category=cat,
        thought='test inner thought',
        salience=sal,
        actionable=actionable,
        actionable_done=actionable_done,
        actionable_result=actionable_result,
        should_speak=should_speak,
        next_interval_s=next_int,
    )


def _force_cfg(
    enabled: bool = True,
    threshold: int = 5,
    force_interval: int = 600,
    max_short: int = 60,
) -> dict:
    """Build a full saturation config dict for patching."""
    return {
        'saturation_trigger': {
            'min_thoughts_same_thread': 3,
            'require_all_should_speak_false': True,
            'actionable_done_states': ['none', 'rejected', 'gated', 'failed'],
        },
        'concern_fatigue_softening': {
            'enabled': True,
            'fatigue_delta_per_saturation': 0.05,
            'decay_back_half_life_hours': 24.0,
            'fatigue_cap': 0.5,
        },
        'python_physical_force': {
            'enabled': enabled,
            'min_consecutive_saturated_for_force': threshold,
            'force_next_interval_s': force_interval,
            'force_max_short_choice_s': max_short,
        },
    }


# ==========================================================================
# L1-L7: _check_and_update_saturation behavior
# ==========================================================================
class TestL1NotEnoughThoughts(unittest.TestCase):
    def test_below_min_thread_returns_false(self):
        d = _build_daemon()
        d._thoughts.clear()
        with patch(
            'jarvis_inner_thought_daemon._load_saturation_config',
            return_value=_force_cfg(threshold=5),
        ):
            t = _mk_thought()
            d._thoughts.append(t)
            self.assertFalse(
                d._check_and_update_saturation(t),
                '不足 min_thoughts_same_thread → 不算 saturated'
            )
            self.assertEqual(d._consecutive_saturation_count, 0,
                'counter 也得清 0')


class TestL2CrossCategoryResets(unittest.TestCase):
    def test_cross_category_recent_resets_counter(self):
        d = _build_daemon()
        d._thoughts.clear()
        d._consecutive_saturation_count = 3  # 模拟已累计
        with patch(
            'jarvis_inner_thought_daemon._load_saturation_config',
            return_value=_force_cfg(threshold=5),
        ):
            d._thoughts.append(_mk_thought(cat='A'))
            d._thoughts.append(_mk_thought(cat='B'))
            t = _mk_thought(cat='A')
            d._thoughts.append(t)
            self.assertFalse(
                d._check_and_update_saturation(t),
                'recent N 跨 category → 不 saturated'
            )
            self.assertEqual(d._consecutive_saturation_count, 0,
                'counter 清 0')


class TestL3HasShouldSpeakResets(unittest.TestCase):
    def test_any_should_speak_resets_counter(self):
        d = _build_daemon()
        d._thoughts.clear()
        d._consecutive_saturation_count = 2
        with patch(
            'jarvis_inner_thought_daemon._load_saturation_config',
            return_value=_force_cfg(threshold=5),
        ):
            d._thoughts.append(_mk_thought(cat='A', should_speak=True))
            d._thoughts.append(_mk_thought(cat='A'))
            t = _mk_thought(cat='A')
            d._thoughts.append(t)
            self.assertFalse(
                d._check_and_update_saturation(t),
                '任一 should_speak=True → 不算 saturated (有 effect)'
            )
            self.assertEqual(d._consecutive_saturation_count, 0)


class TestL4ActionableDoneResets(unittest.TestCase):
    def test_actionable_done_is_not_saturation(self):
        d = _build_daemon()
        d._thoughts.clear()
        d._consecutive_saturation_count = 4
        with patch(
            'jarvis_inner_thought_daemon._load_saturation_config',
            return_value=_force_cfg(threshold=5),
        ):
            for _ in range(2):
                d._thoughts.append(_mk_thought(cat='A'))
            t = _mk_thought(
                cat='A',
                actionable='call_tool:foo:{}',
                actionable_done=True,
                actionable_result='ok',
            )
            d._thoughts.append(t)
            self.assertFalse(
                d._check_and_update_saturation(t),
                "actionable 真 done → state='done' 不在 whitelist → 不 saturated"
            )
            self.assertEqual(d._consecutive_saturation_count, 0)


class TestL5SaturationIncrementsBelowThreshold(unittest.TestCase):
    def test_increments_but_below_threshold_returns_false(self):
        d = _build_daemon()
        d._thoughts.clear()
        d._consecutive_saturation_count = 0
        with patch(
            'jarvis_inner_thought_daemon._load_saturation_config',
            return_value=_force_cfg(threshold=5),
        ):
            for _ in range(3):
                d._thoughts.append(_mk_thought(cat='A'))
            t = _mk_thought(cat='A')
            # 第 1 tick saturated (counter 0→1, threshold=5)
            result = d._check_and_update_saturation(t)
            self.assertFalse(
                result,
                'counter=1 < threshold=5 → 不 force, return False'
            )
            self.assertEqual(d._consecutive_saturation_count, 1,
                'counter ++')


class TestL6SaturationReachesThreshold(unittest.TestCase):
    def test_consecutive_saturated_reaches_force(self):
        d = _build_daemon()
        d._thoughts.clear()
        d._consecutive_saturation_count = 0
        with patch(
            'jarvis_inner_thought_daemon._load_saturation_config',
            return_value=_force_cfg(threshold=3),
        ):
            for _ in range(3):
                d._thoughts.append(_mk_thought(cat='A'))
            t = _mk_thought(cat='A')
            # 第 3 个 saturated tick (counter 0→1→2→3) 应到阈
            r1 = d._check_and_update_saturation(t)
            r2 = d._check_and_update_saturation(t)
            r3 = d._check_and_update_saturation(t)
            self.assertFalse(r1, 'tick1 counter=1 < 3, False')
            self.assertFalse(r2, 'tick2 counter=2 < 3, False')
            self.assertTrue(r3, 'tick3 counter=3 ≥ threshold, force due')
            self.assertEqual(d._consecutive_saturation_count, 3)


class TestL7CounterResetsOnNonSaturatedInMiddle(unittest.TestCase):
    def test_non_saturated_tick_in_middle_resets_counter(self):
        d = _build_daemon()
        d._thoughts.clear()
        d._consecutive_saturation_count = 0
        with patch(
            'jarvis_inner_thought_daemon._load_saturation_config',
            return_value=_force_cfg(threshold=5),
        ):
            # 3 saturated A → counter=3
            for _ in range(3):
                d._thoughts.append(_mk_thought(cat='A'))
            t = _mk_thought(cat='A')
            d._check_and_update_saturation(t)
            d._check_and_update_saturation(t)
            self.assertEqual(d._consecutive_saturation_count, 2)

            # 突然 should_speak=True (有 effect) → counter 清 0
            d._thoughts.clear()
            d._thoughts.append(_mk_thought(cat='A', should_speak=True))
            d._thoughts.append(_mk_thought(cat='A'))
            t_speak = _mk_thought(cat='A')
            d._thoughts.append(t_speak)
            self.assertFalse(d._check_and_update_saturation(t_speak))
            self.assertEqual(d._consecutive_saturation_count, 0,
                'non-saturated 中断 → 必须清 0, 不累计')


# ==========================================================================
# L8-L11: _resolve_next_interval 看 _saturation_force_due
# ==========================================================================
class TestL8ResolveForceWhenLlmChose30(unittest.TestCase):
    def test_force_due_short_llm_choice_forces_long_interval(self):
        d = _build_daemon()
        d._saturation_force_due = True
        with patch(
            'jarvis_inner_thought_daemon._load_saturation_config',
            return_value=_force_cfg(force_interval=600, max_short=60),
        ):
            t = _mk_thought(next_int=30)
            interval, origin = d._resolve_next_interval(t, 'active')
        self.assertEqual(interval, 600,
            'force_due + LLM 选 30 (≤ max_short 60) → 强制 force_interval=600')
        self.assertEqual(origin, 'saturation_force',
            'origin = saturation_force (优先级 > llm_chosen / gate)')


class TestL9ResolveForceWhenLlmDefault(unittest.TestCase):
    def test_force_due_llm_default_also_forces(self):
        d = _build_daemon()
        d._saturation_force_due = True
        with patch(
            'jarvis_inner_thought_daemon._load_saturation_config',
            return_value=_force_cfg(force_interval=600),
        ):
            t = _mk_thought(next_int=0)  # LLM 没选 = default
            interval, origin = d._resolve_next_interval(t, 'active')
        self.assertEqual(interval, 600,
            'force_due + LLM default (=0) → 强制 force_interval=600')
        self.assertEqual(origin, 'saturation_force')


class TestL10ResolveSkipForceWhenLongLlmChoice(unittest.TestCase):
    def test_force_due_long_llm_choice_not_overridden(self):
        d = _build_daemon()
        d._saturation_force_due = True
        with patch(
            'jarvis_inner_thought_daemon._load_saturation_config',
            return_value=_force_cfg(force_interval=600, max_short=60),
        ):
            t = _mk_thought(next_int=180, sal=0.9)  # LLM 自觉选大 + 高 sal 不被 smoothing
            interval, origin = d._resolve_next_interval(t, 'active')
        self.assertEqual(interval, 180,
            'LLM 自觉选 > max_short (180) → 不 override, 走正常 case 4')
        self.assertEqual(origin, 'llm_chosen',
            'origin = llm_chosen (信任 LLM 已自觉休息)')


class TestL11ResolveSkipForceWhenConfigDisabled(unittest.TestCase):
    def test_force_disabled_in_config_skips_force(self):
        d = _build_daemon()
        d._saturation_force_due = True
        with patch(
            'jarvis_inner_thought_daemon._load_saturation_config',
            return_value=_force_cfg(enabled=False),
        ):
            t = _mk_thought(next_int=30, sal=0.9)
            interval, origin = d._resolve_next_interval(t, 'active')
        self.assertEqual(interval, 30,
            'config enabled=False → 不 force, 走正常 case 4 (LLM 选 30)')
        self.assertEqual(origin, 'llm_chosen',
            'origin = llm_chosen (config kill switch)')


if __name__ == '__main__':
    unittest.main()
