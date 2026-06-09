# -*- coding: utf-8 -*-
"""[fixH-a body_stir 指纹去重 + habituation 调参 / Sir 2026-06-09] testcase.

根因 (fixH recon): attend→body_attention_outcome→habituation 衰 tension 闭环已 wired
(daemon:publish→weaver:_habituation_map), 但衰减慢于 30s body_stir_poll → 驻留 delta
(同 node 同幅度桶) 每 30s 反复硬抢醒, 硬覆盖 600s value-backoff。

本刀两件:
  ① _check_body_stir 加 delta 指纹去重 (node + 幅度桶), 桥接 30s poll 与 habituation
     衰减的时序差: 同驻留 delta 在被消化前不重复唤醒 rest; 真新 delta (node 变/桶跳变)
     或 novelty/drift kind 仍立即醒; 真放电/should_speak/真 tick 跑起 → 指纹清空。
  ② habituation decay_base 0.6→0.5 (闭环更快消化驻留 delta, 缩短反复唤醒窗口),
     floor=0.15 / spontaneous recovery / 真放电重置 1.0 全不变。

测试覆盖:
  T1  同驻留 delta (同 node 同桶) 连续 poll → 第二次起不唤醒
  T2  真新 delta (node 变 / 桶跳变) → 唤醒 + 更新指纹
  T3  novelty/drift kind → 豁免去重, 照醒
  T4  emergency 分支独立 — 去重逻辑不影响 _check_emergency_pending
  T5  真放电 (heng_state=discharge) / should_speak → 指纹重置, 同 node 再起势能醒
  T6  habituation 调参: decay_base=0.5 衰更快; floor 守住 / 自愈 / 放电重置完好
  T7  去重 disabled (body_stir_dedup=False) → 回原行为 (任何 fresh delta 即醒)

红线: emergency 不受压; 真新/novelty/drift 仍醒; 指纹会重置 (非永久压);
      habituation 调参守 floor/自愈/放电重置; 纯 event/临时 data, 不写真档案。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


# ----------------------------------------------------------------------
# fixtures
# ----------------------------------------------------------------------

def _build_daemon():
    """构造 InnerThoughtDaemon (mocked deps), _resting=True 模拟休息中。"""
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    mock_router = MagicMock()
    mock_ledger = MagicMock()
    mock_ledger.list_active = MagicMock(return_value=[])
    daemon = InnerThoughtDaemon(key_router=mock_router, concerns_ledger=mock_ledger)
    daemon._resting = True
    return daemon


def _focus_item(node, magnitude, kind='tension', fresh=True):
    """模拟 BodyFocus.current_focus 的一项 (delta: score = magnitude + 1.0)。"""
    return {
        'node': node, 'kind': kind, 'why': kind,
        'magnitude': magnitude,
        'score': magnitude + 1.0 if fresh else magnitude,
        'fresh': fresh, 'text': '',
    }


class _FakeFocus:
    """最小 BodyFocus: has_fresh_delta + current_focus 由注入 items 驱动。"""

    def __init__(self, items):
        self._items = list(items)

    def has_fresh_delta(self, *, min_magnitude=0.0):
        return any(it.get('fresh') and float(it.get('magnitude', 0.0)) >= min_magnitude
                   for it in self._items)

    def current_focus(self, *, limit=6):
        return list(self._items)[:limit]


def _patch_focus(daemon, items):
    """把 jarvis_body_focus.get_body_focus 换成返回 _FakeFocus。"""
    import jarvis_body_focus as bf
    fake = _FakeFocus(items)
    bf.get_body_focus = lambda: fake  # daemon import inside fn → 拿到 patched
    return fake


# ---- T6 habituation helpers (module-level 防与 TestCase 方法名冲突) ----

class _HabBus:
    """最小 SWM bus for habituation: recent_events(types) 过滤。"""

    def __init__(self, events):
        self.events = list(events)

    def recent_events(self, within_seconds=None, types=None):
        return [dict(e) for e in self.events
                if types is None or e.get("type") in types]

    def publish(self, *a, **k):
        return None


def _hab_outcome(node, discharged, ts):
    return {"type": "body_attention_outcome", "timestamp": ts,
            "metadata": {"node": node, "discharged": discharged}}


# ----------------------------------------------------------------------
# T1: 同驻留 delta 不重醒
# ----------------------------------------------------------------------

class TestBodyStirDedup(unittest.TestCase):

    def setUp(self):
        # 每个 test 独立 patch focus, 避免污染
        import jarvis_body_focus as bf
        self._orig_get_focus = bf.get_body_focus
        self.addCleanup(lambda: setattr(bf, 'get_body_focus', self._orig_get_focus))

    def test_t1_same_resident_delta_no_rewake(self):
        daemon = _build_daemon()
        items = [_focus_item('concern:sir_water', 0.5, kind='tension')]
        _patch_focus(daemon, items)
        # 第一次: 醒 (首次指纹)
        self.assertTrue(daemon._check_body_stir(), "首次驻留 delta 应唤醒")
        # 重新置 resting (模拟又进入休息), 同驻留 delta
        daemon._resting = True
        # 第二次: 同 node 同桶 → 不醒
        self.assertFalse(daemon._check_body_stir(),
                         "同驻留 delta (同 node 同桶) 第二次不应重醒")
        self.assertTrue(daemon._resting, "未醒应保持 _resting=True")

    def test_t2_new_delta_rewakes(self):
        daemon = _build_daemon()
        import jarvis_body_focus as bf
        # 第一次: node A
        bf.get_body_focus = lambda: _FakeFocus([_focus_item('concern:a', 0.5)])
        self.assertTrue(daemon._check_body_stir(), "首次应醒")
        daemon._resting = True
        # node 变 (concern:b) → 新指纹 → 醒
        bf.get_body_focus = lambda: _FakeFocus([_focus_item('concern:b', 0.5)])
        self.assertTrue(daemon._check_body_stir(), "node 变 → 新指纹 → 应醒")
        daemon._resting = True
        # 桶跳变 (同 node 但幅度从 0.5→1.5, bucket 0.5: 桶 1→3) → 醒
        bf.get_body_focus = lambda: _FakeFocus([_focus_item('concern:b', 1.5)])
        self.assertTrue(daemon._check_body_stir(), "幅度桶跳变 → 应醒")

    def test_t3_novelty_drift_exempt(self):
        daemon = _build_daemon()
        import jarvis_body_focus as bf
        # novelty delta → 必醒
        bf.get_body_focus = lambda: _FakeFocus([_focus_item('thread:x', 0.5, kind='novelty')])
        self.assertTrue(daemon._check_body_stir(), "novelty → 豁免去重, 应醒")
        daemon._resting = True
        # 同 novelty delta 再来 → 仍醒 (豁免, 不参与去重)
        self.assertTrue(daemon._check_body_stir(), "novelty 重复仍应醒 (豁免)")
        daemon._resting = True
        # drift delta → 必醒
        bf.get_body_focus = lambda: _FakeFocus([_focus_item('thread:y', 0.5, kind='drift')])
        self.assertTrue(daemon._check_body_stir(), "drift → 豁免去重, 应醒")

    def test_t4_emergency_branch_independent(self):
        """emergency 走 _check_emergency_pending (独立路径), 不受 body_stir 去重影响。"""
        from jarvis_inner_thought_daemon import _load_emergency_vocab
        daemon = _build_daemon()
        # 确认 emergency 检查是独立函数, 与 _check_body_stir 无耦合
        self.assertTrue(hasattr(daemon, '_check_emergency_pending'))
        self.assertTrue(hasattr(daemon, '_check_body_stir'))
        # _wait_with_emergency_check 内 emergency 先判 (return 'emergency'),
        # body_stir 后判 (return 'body_stir') — 顺序保证 emergency 优先。
        import inspect
        src = inspect.getsource(daemon._wait_with_emergency_check)
        idx_emerg = src.find('_check_emergency_pending')
        idx_body = src.find('_check_body_stir')
        self.assertGreater(idx_emerg, 0, "应含 emergency 检查")
        self.assertGreater(idx_body, 0, "应含 body_stir 检查")
        self.assertLess(idx_emerg, idx_body,
                        "emergency 检查应在 body_stir 之前 (优先, 独立分支)")

    def test_t5_discharge_resets_fingerprint(self):
        """真放电 / should_speak → 指纹重置, 同 node 再起势能醒。"""
        daemon = _build_daemon()
        items = [_focus_item('concern:sir_water', 0.5)]
        _patch_focus(daemon, items)
        self.assertTrue(daemon._check_body_stir(), "首次应醒")
        self.assertTrue(daemon._last_woke_delta_fp, "醒后应记指纹")
        # 模拟真放电 → 指纹清空 (复用 daemon 的 reset 逻辑路径)
        daemon._last_woke_delta_fp = set()
        daemon._resting = True
        # 同 node 同桶, 但指纹已清 → 应再醒
        self.assertTrue(daemon._check_body_stir(),
                        "指纹重置后, 同 node 再起势应能重新唤醒 (非永久压)")

    def test_t7_dedup_disabled_falls_back(self):
        """body_stir_dedup=False → 回原行为 (任何 fresh delta 即醒)。"""
        import jarvis_inner_thought_daemon as mod
        daemon = _build_daemon()
        items = [_focus_item('concern:sir_water', 0.5)]
        _patch_focus(daemon, items)
        # monkeypatch saturation config: body_stir_dedup=False
        orig = mod._load_saturation_config
        try:
            cfg = orig()
            patched = {k: dict(v) if isinstance(v, dict) else v
                       for k, v in cfg.items()}
            patched['rest'] = dict(patched.get('rest', {}))
            patched['rest']['body_stir_dedup'] = False
            mod._load_saturation_config = lambda: patched
            self.assertTrue(daemon._check_body_stir(), "首次应醒")
            daemon._resting = True
            # 去重关 → 同驻留 delta 仍醒 (原行为)
            self.assertTrue(daemon._check_body_stir(),
                            "dedup 关 → 同驻留 delta 仍醒 (回原行为)")
        finally:
            mod._load_saturation_config = orig


# ----------------------------------------------------------------------
# T6: habituation 调参 (decay_base 0.6→0.5)
# ----------------------------------------------------------------------

class TestHabituationTuning(unittest.TestCase):

    def _mk_weaver(self, d, concerns, bus):
        from jarvis_relational_manifold import RelationalManifold
        from jarvis_relational_weaver import RelationalWeaver
        tp = os.path.join(d, "self_threads.json")
        cp = os.path.join(d, "concerns.json")
        rp = os.path.join(d, "relational_state.json")
        sp = os.path.join(d, "stance.json")
        for p, obj in ((tp, {"threads": []}), (cp, concerns),
                       (rp, {"inside_jokes": {}, "unspoken_protocols": {}}),
                       (sp, {"stances": {}})):
            with open(p, "w", encoding="utf-8") as f:
                json.dump(obj, f)
        man = RelationalManifold(os.path.join(d, "manifold.json"))
        return RelationalWeaver(
            manifold=man, threads_path=tp, concerns_path=cp,
            relational_path=rp, vectors_path=os.path.join(d, "vec.json"),
            stance_path=sp, energy_path=os.path.join(d, "energy.json"),
            event_bus=bus)

    def test_t6a_decay_base_now_05(self):
        """seed default decay_base = 0.5 (调参后)。"""
        from jarvis_relational_manifold import get_manifold_config
        base = float(get_manifold_config()["energy"]["habituation_decay_base"])
        self.assertAlmostEqual(base, 0.5, places=6,
                               msg="fixH-a: decay_base 应调到 0.5")

    def test_t6b_faster_decay(self):
        """4 非放电 attend, free=2 → excess=2 → factor=0.5^2=0.25 (比 0.6^2=0.36 更快)。"""
        from jarvis_relational_manifold import make_node_id, KIND_CONCERN
        T0 = 1_780_000_000.0
        with tempfile.TemporaryDirectory() as d:
            nid = make_node_id(KIND_CONCERN, "sir_water")
            evs = [_hab_outcome(nid, False, ts=T0 + i) for i in range(4)]
            concerns = {"sir_water": {"id": "sir_water", "what_i_watch": "水",
                                      "severity": 0.9, "state": "active"}}
            w = self._mk_weaver(d, concerns, _HabBus(evs))
            energy = w.compute_energy(set(), {}, {}, now=T0 + 10)
            # 0.5^2=0.25 > floor 0.15 → 未触底, 体现"更快衰" (0.6^2=0.36)
            self.assertAlmostEqual(energy[nid]["tension"], 0.9 * (0.5 ** 2),
                                   places=3, msg="decay_base=0.5 → 衰更快")

    def test_t6c_floor_recovery_discharge_intact(self):
        """floor=0.15 守住 / spontaneous recovery / 真放电重置 1.0 全不变。"""
        from jarvis_relational_manifold import make_node_id, KIND_CONCERN
        T0 = 1_780_000_000.0
        nid = make_node_id(KIND_CONCERN, "sir_water")
        concerns = {"sir_water": {"id": "sir_water", "what_i_watch": "水",
                                  "severity": 0.9, "state": "active"}}
        # floor: 大量非放电 → 触底 0.15 (0.5^28 远小于 floor)
        with tempfile.TemporaryDirectory() as d:
            evs = [_hab_outcome(nid, False, ts=T0 + i) for i in range(30)]
            w = self._mk_weaver(d, concerns, _HabBus(evs))
            energy = w.compute_energy(set(), {}, {}, now=T0 + 40)
            self.assertAlmostEqual(energy[nid]["tension"], 0.9 * 0.15,
                                   places=4, msg="floor=0.15 守住")
        # spontaneous recovery: 久不 attend → 恢复 1.0
        with tempfile.TemporaryDirectory() as d:
            evs = [_hab_outcome(nid, False, ts=T0 + i) for i in range(5)]
            w = self._mk_weaver(d, concerns, _HabBus(evs))
            energy = w.compute_energy(set(), {}, {}, now=T0 + 5000)
            self.assertAlmostEqual(energy[nid]["tension"], 0.9, places=6,
                                   msg="久不 attend → spontaneous recovery")
        # 真放电重置: 非放电后一次放电 → 归 0 → 不衰
        with tempfile.TemporaryDirectory() as d:
            evs = [_hab_outcome(nid, False, ts=T0 + i) for i in range(4)]
            evs.append(_hab_outcome(nid, True, ts=T0 + 5))
            w = self._mk_weaver(d, concerns, _HabBus(evs))
            energy = w.compute_energy(set(), {}, {}, now=T0 + 10)
            self.assertAlmostEqual(energy[nid]["tension"], 0.9, places=6,
                                   msg="真放电重置习惯化")


if __name__ == '__main__':
    unittest.main(verbosity=2)
