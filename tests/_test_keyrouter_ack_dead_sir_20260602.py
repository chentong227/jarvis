# -*- coding: utf-8 -*-
"""[放权-mask / Sir 2026-06-02] 死 key 焦虑屏蔽 (acknowledge_dead_key) 回归.

Sir 真痛 (log jarvis_20260602_074737): google_2/google_3 永久死 (403 PROJECT_DENIED),
思考脑 70% thought 反刍 keyrouter (sal=0.98-1.00), SELF anchor 每轮报"我残疾/焦虑"。
Sir 指示: "key 可以先暂时屏蔽等我加新的"。

治本 (准则 8 优雅非糖衣): 不删 key 不改路由 — 加"Sir 确认屏蔽"持久标记:
  - acknowledge_dead_key(label): key 仍永久剔除 (不路由不复活), 标 acknowledged_dead;
  - get_stats() 暴露 acknowledged_dead list + per-key flag;
  - SELF anchor _get_own_health 把 acked 死 key 算 acked_dead_keys (不算 dead_keys/焦虑);
  - reset_permanent_death (Sir rotate 新 key) 自动清 ack → 恢复汇报。

覆盖:
  T1  acknowledge_dead_key 只对 permanently_dead key 生效 (健康 key 返 False)
  T2  ack 后 get_stats acknowledged_dead 含该 label + per-key flag=True
  T3  ack 'all' 确认全部死 key
  T4  ack 不改 healthy (key 仍 dead, 不复活, 不参与路由)
  T5  reset_permanent_death 后 ack 标记自动清除
  T6  ack 持久化到 state.json + 重建 router 后仍生效
  T7  SELF anchor: acked 死 key 不算 dead_keys, 不报"diminished"焦虑
  T8  SELF anchor: 未 ack 的死 key 仍报焦虑 (回归保护, 别误杀真焦虑)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_router():
    from jarvis_key_router import KeyRouter
    tmp_dir = tempfile.mkdtemp(prefix='kr_ack_test_')
    KeyRouter._STATE_FILE_PATH = os.path.join(tmp_dir, 'state.json')
    KeyRouter._HEALTH_SNAPSHOT_PATH = os.path.join(tmp_dir, 'health.json')
    KeyRouter._RESET_REQUEST_PATH = os.path.join(tmp_dir, 'req.json')
    KeyRouter._RESET_AUDIT_PATH = os.path.join(tmp_dir, 'audit.jsonl')
    kr = KeyRouter(
        main_brain_key='sk-or-v1-mainbrain-fake',
        google_keys=['AIzaSyFAKE_G1', 'AIzaSyFAKE_G2', 'AIzaSyFAKE_G3'],
        openrouter_keys=['sk-or-v1-fake1'],
    )
    try:
        kr._snapshot_stop.set()
        if hasattr(kr, '_snapshot_thread'):
            kr._snapshot_thread.join(timeout=2.0)
    except Exception:
        pass
    return kr, tmp_dir


def _kill(kr, label):
    """把某 label 标 permanently_dead (模拟 403)."""
    with kr._lock:
        for k, v in kr._key_status.items():
            if v['label'] == label:
                v['healthy'] = False
                v['permanently_dead'] = True
                v['permanent_death_count'] = 3
                v['permanent_death_reason'] = '403 PERMISSION_DENIED (test)'
                break
    kr._save_permanent_death_state()


class TestKeyRouterAck(unittest.TestCase):
    def test_t1_ack_only_dead(self):
        kr, _ = _make_router()
        # 健康 key 不能 ack
        self.assertFalse(kr.acknowledge_dead_key('google_1'))
        _kill(kr, 'google_2')
        self.assertTrue(kr.acknowledge_dead_key('google_2'))

    def test_t2_stats_exposes_ack(self):
        kr, _ = _make_router()
        _kill(kr, 'google_2')
        kr.acknowledge_dead_key('google_2')
        s = kr.get_stats()
        self.assertIn('google_2', s.get('acknowledged_dead', []))
        self.assertTrue(s['key_status']['google_2']['acknowledged_dead'])
        # 健康 key flag=False
        self.assertFalse(s['key_status']['google_1']['acknowledged_dead'])

    def test_t3_ack_all(self):
        kr, _ = _make_router()
        _kill(kr, 'google_2')
        _kill(kr, 'google_3')
        self.assertTrue(kr.acknowledge_dead_key('all'))
        acked = set(kr.acknowledged_dead_labels())
        self.assertIn('google_2', acked)
        self.assertIn('google_3', acked)

    def test_t4_ack_does_not_revive(self):
        kr, _ = _make_router()
        _kill(kr, 'google_2')
        kr.acknowledge_dead_key('google_2')
        # 仍 dead — 不复活, 不参与路由
        s = kr.get_stats()
        self.assertFalse(s['key_status']['google_2']['healthy'])
        self.assertTrue(s['key_status']['google_2']['permanently_dead'])

    def test_t5_reset_clears_ack(self):
        kr, _ = _make_router()
        _kill(kr, 'google_2')
        kr.acknowledge_dead_key('google_2')
        self.assertIn('google_2', kr.acknowledged_dead_labels())
        # Sir rotate 新 key → reset → ack 自动清
        kr.reset_permanent_death('google_2')
        self.assertNotIn('google_2', kr.acknowledged_dead_labels())

    def test_t6_ack_persists_across_reload(self):
        from jarvis_key_router import KeyRouter
        kr, tmp = _make_router()
        _kill(kr, 'google_2')
        kr.acknowledge_dead_key('google_2')
        # 重建 router (同 state 路径) → 应从 disk 恢复 ack
        kr2 = KeyRouter(
            main_brain_key='sk-or-v1-mainbrain-fake',
            google_keys=['AIzaSyFAKE_G1', 'AIzaSyFAKE_G2', 'AIzaSyFAKE_G3'],
            openrouter_keys=['sk-or-v1-fake1'],
        )
        try:
            kr2._snapshot_stop.set()
        except Exception:
            pass
        self.assertIn('google_2', kr2.acknowledged_dead_labels())

    def test_t7_self_anchor_acked_not_anxious(self):
        import jarvis_self_anchor as sa
        kr, _ = _make_router()
        _kill(kr, 'google_2')
        _kill(kr, 'google_3')
        kr.acknowledge_dead_key('all')

        class _Nerve:
            pass
        nerve = _Nerve()
        nerve.key_router = kr
        anchor = sa.SelfAnchor(central_nerve=nerve)
        health = anchor._get_own_health()
        # acked 死 key 不算 dead_keys
        self.assertEqual(health['dead_keys'], 0)
        self.assertGreaterEqual(health['acked_dead_keys'], 2)
        # mood 不焦虑
        mood = sa._derive_mood(health, [])
        self.assertNotIn('diminished', mood)
        self.assertNotIn('anxious', mood)
        # build_block 不报 "permanently dead ... This is real" 焦虑句
        block = anchor.build_block()
        self.assertNotIn("This is real, not a hypothetical", block)
        self.assertIn("Sir already knows", block)

    def test_t8_unacked_dead_still_anxious(self):
        import jarvis_self_anchor as sa
        kr, _ = _make_router()
        _kill(kr, 'google_2')  # 不 ack

        class _Nerve:
            pass
        nerve = _Nerve()
        nerve.key_router = kr
        anchor = sa.SelfAnchor(central_nerve=nerve)
        health = anchor._get_own_health()
        # 未 ack → 仍算 dead_keys (别误杀真焦虑)
        self.assertGreaterEqual(health['dead_keys'], 1)
        self.assertEqual(health['acked_dead_keys'], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
