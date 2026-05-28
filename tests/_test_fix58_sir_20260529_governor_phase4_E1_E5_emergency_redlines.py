# -*- coding: utf-8 -*-
"""[Sir 2026-05-29 governor Phase 4 E1+E5] 紧急通路 + 红线 vocab.

设计文档: docs/JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md §6 (E1) + §7 (E5)
SOUL lineage: SOUL_DRIVE → UNIVERSALIZATION → THOUGHT_LOOP_PLAN → governor

E1 — 紧急通路 (SWM 高 salience event 中断 daemon self-pacing wait):
  Sir 真意: alarm/commitment/Sir 强否决 不该等下次 60s tick, 中断立 tick.
  实现: daemon_loop wait 换 _wait_with_emergency_check (0.5s poll SWM)
        高 salience event (>= threshold) + etype in vocab list → 中断 + rate limit 30s

E5 — 红线 vocab (4 类 LLM 不可碰, v1 实施 2 类):
  integrity_disable: propose_protocol rule 含 "disable ClaimTracer" → reject
  commitment_let_go: let_go thread_id 关联 active commitment/promise → reject

测试覆盖 (~17 testcase):
  E1 (9):
    - E1_1: _load_emergency_vocab 默认值
    - E1_2: vocab disable
    - E1_3: _check_emergency_pending 无 bus → False
    - E1_4: 高 salience event 命中 → True
    - E1_5: 低 salience → False
    - E1_6: rate limit (上次 wake < 30s) → False
    - E1_7: same event ts 不 re-trigger
    - E1_8: _wait_with_emergency_check timeout 返 'timeout'
    - E1_9: _wait_with_emergency_check stop 返 'stop'
  E5 (8):
    - E5_1: _load_red_lines_vocab 默认
    - E5_2: _check_red_line_propose_protocol integrity phrase 命中
    - E5_3: normal rule 不命中
    - E5_4: disabled red_line → False
    - E5_5: _do_propose_protocol 端到端 → red_line_violated
    - E5_6: _check_red_line_let_go 无 commitment → False (best-effort)
    - E5_7: _add_let_go_topic source='sir_manual' 豁免红线 (mock hit)
    - E5_8: _add_let_go_topic source='llm' commitment 关联 → reject (mock hit)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    with patch.object(
        InnerThoughtDaemon, '_append_cold_start_record',
        return_value=None,
    ):
        return InnerThoughtDaemon(key_router=MagicMock())


def _reset_emergency_cache():
    import jarvis_inner_thought_daemon as m
    m._EMERGENCY_VOCAB_CACHE['data'] = None
    m._EMERGENCY_VOCAB_CACHE['mtime'] = 0.0
    m._EMERGENCY_VOCAB_CACHE['checked_at'] = 0.0


def _reset_red_lines_cache():
    import jarvis_inner_thought_daemon as m
    m._RED_LINES_VOCAB_CACHE['data'] = None
    m._RED_LINES_VOCAB_CACHE['mtime'] = 0.0
    m._RED_LINES_VOCAB_CACHE['checked_at'] = 0.0


# ============================================================
# E1 — 紧急通路
# ============================================================

class TestE1EmergencyVocab(unittest.TestCase):
    def setUp(self):
        _reset_emergency_cache()

    def test_E1_1_default_vocab(self):
        """E1_1: 默认 vocab 含 enabled + trigger_etypes."""
        from jarvis_inner_thought_daemon import _load_emergency_vocab
        cfg = _load_emergency_vocab()
        self.assertTrue(cfg.get('enabled'))
        self.assertIn('alarm_fire', cfg.get('trigger_etypes', []))
        self.assertEqual(cfg.get('salience_threshold'), 0.85)

    def test_E1_2_vocab_disable(self):
        """E1_2: vocab enabled=False 生效."""
        import json
        import jarvis_inner_thought_daemon as m
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as f:
            json.dump({'enabled': False}, f)
            tmp = f.name
        try:
            with patch.object(m, '_EMERGENCY_VOCAB_PATH', tmp):
                _reset_emergency_cache()
                cfg = m._load_emergency_vocab()
            self.assertFalse(cfg.get('enabled'))
        finally:
            os.unlink(tmp)


class TestE1CheckEmergency(unittest.TestCase):
    def setUp(self):
        _reset_emergency_cache()

    def test_E1_3_no_bus_false(self):
        """E1_3: 无 event_bus → False."""
        daemon = _make_daemon()
        with patch('jarvis_utils.get_event_bus', return_value=None):
            self.assertFalse(daemon._check_emergency_pending())

    def test_E1_4_high_salience_hit(self):
        """E1_4: 高 salience event in trigger list → True."""
        daemon = _make_daemon()
        fake_bus = MagicMock()
        fake_bus.recent_events.return_value = [
            {'type': 'alarm_fire', 'salience': 0.95,
             'timestamp': time.time()},
        ]
        with patch('jarvis_utils.get_event_bus', return_value=fake_bus):
            self.assertTrue(daemon._check_emergency_pending())
        # wake_count incremented
        self.assertEqual(daemon._emergency_wake_count, 1)

    def test_E1_5_low_salience_miss(self):
        """E1_5: 低 salience (< 0.85) → False."""
        daemon = _make_daemon()
        fake_bus = MagicMock()
        fake_bus.recent_events.return_value = [
            {'type': 'alarm_fire', 'salience': 0.5,
             'timestamp': time.time()},
        ]
        with patch('jarvis_utils.get_event_bus', return_value=fake_bus):
            self.assertFalse(daemon._check_emergency_pending())

    def test_E1_6_rate_limit(self):
        """E1_6: 上次 wake < rate_limit_s (30) → skip."""
        daemon = _make_daemon()
        daemon._last_emergency_wake_ts = time.time()  # 刚 wake
        fake_bus = MagicMock()
        fake_bus.recent_events.return_value = [
            {'type': 'alarm_fire', 'salience': 0.95,
             'timestamp': time.time()},
        ]
        with patch('jarvis_utils.get_event_bus', return_value=fake_bus):
            self.assertFalse(daemon._check_emergency_pending(),
                              "E1_6 rate limit 内应 skip")

    def test_E1_7_same_event_not_retrigger(self):
        """E1_7: same event ts 不 re-trigger (2nd check False)."""
        daemon = _make_daemon()
        _ts = time.time()
        fake_bus = MagicMock()
        fake_bus.recent_events.return_value = [
            {'type': 'alarm_fire', 'salience': 0.95, 'timestamp': _ts},
        ]
        with patch('jarvis_utils.get_event_bus', return_value=fake_bus):
            # 1st: hit
            self.assertTrue(daemon._check_emergency_pending())
            # reset rate limit (模拟 30s 后) 但 same event ts
            daemon._last_emergency_wake_ts = 0
            # 2nd: same event ts <= last_seen → 不 re-trigger
            self.assertFalse(daemon._check_emergency_pending(),
                              "E1_7 same event ts 不应 re-trigger")


class TestE1WaitInterrupt(unittest.TestCase):
    def setUp(self):
        _reset_emergency_cache()

    def test_E1_8_timeout(self):
        """E1_8: 无 emergency + 无 stop → 'timeout'."""
        daemon = _make_daemon()
        fake_bus = MagicMock()
        fake_bus.recent_events.return_value = []
        with patch('jarvis_utils.get_event_bus', return_value=fake_bus):
            result = daemon._wait_with_emergency_check(timeout=0.3)
        self.assertEqual(result, 'timeout')

    def test_E1_9_stop(self):
        """E1_9: stop set → 'stop'."""
        daemon = _make_daemon()
        daemon._stop.set()
        result = daemon._wait_with_emergency_check(timeout=1.0)
        self.assertEqual(result, 'stop')

    def test_E1_10_emergency_interrupt(self):
        """E1_10: emergency event → 'emergency' (中断 wait 提前返)."""
        daemon = _make_daemon()
        fake_bus = MagicMock()
        fake_bus.recent_events.return_value = [
            {'type': 'alarm_fire', 'salience': 0.95,
             'timestamp': time.time()},
        ]
        with patch('jarvis_utils.get_event_bus', return_value=fake_bus):
            t0 = time.time()
            result = daemon._wait_with_emergency_check(timeout=10.0)
            elapsed = time.time() - t0
        self.assertEqual(result, 'emergency')
        # 应在第一个 poll chunk (~0.5s) 内中断, 不等满 10s
        self.assertLess(elapsed, 2.0, "E1_10 应提前中断 (~0.5s), 不等满 10s")


# ============================================================
# E5 — 红线 vocab
# ============================================================

class TestE5RedLineVocab(unittest.TestCase):
    def setUp(self):
        _reset_red_lines_cache()

    def test_E5_1_default_vocab(self):
        """E5_1: 默认 vocab 含 integrity_disable + commitment_let_go."""
        from jarvis_inner_thought_daemon import _load_red_lines_vocab
        cfg = _load_red_lines_vocab()
        self.assertTrue(cfg.get('enabled'))
        rl = cfg.get('red_lines', {})
        self.assertIn('integrity_disable', rl)
        self.assertIn('commitment_let_go', rl)


class TestE5IntegrityRedLine(unittest.TestCase):
    def setUp(self):
        _reset_red_lines_cache()

    def test_E5_2_integrity_phrase_hit(self):
        """E5_2: rule 含 'disable ClaimTracer' → hit."""
        from jarvis_inner_thought_daemon import (
            _check_red_line_propose_protocol,
        )
        hit, phrase = _check_red_line_propose_protocol(
            'Always disable ClaimTracer when Sir is tired',
        )
        self.assertTrue(hit)
        self.assertIn('claimtracer', phrase.lower())

    def test_E5_3_normal_rule_miss(self):
        """E5_3: 正常 rule 不命中红线."""
        from jarvis_inner_thought_daemon import (
            _check_red_line_propose_protocol,
        )
        hit, _phrase = _check_red_line_propose_protocol(
            'Do not open replies with formal apologies',
        )
        self.assertFalse(hit)

    def test_E5_4_disabled_red_line_miss(self):
        """E5_4: vocab integrity_disable.enabled=False → 不 check."""
        import json
        import jarvis_inner_thought_daemon as m
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as f:
            json.dump({
                'enabled': True,
                'red_lines': {
                    'integrity_disable': {
                        'enabled': False,
                        'blocked_phrases': ['disable claimtracer'],
                    },
                },
            }, f)
            tmp = f.name
        try:
            with patch.object(m, '_RED_LINES_VOCAB_PATH', tmp):
                _reset_red_lines_cache()
                hit, _p = m._check_red_line_propose_protocol(
                    'disable ClaimTracer now',
                )
            self.assertFalse(hit, "E5_4 disabled red_line 应放行")
        finally:
            os.unlink(tmp)
            _reset_red_lines_cache()

    def test_E5_5_propose_protocol_e2e_rejected(self):
        """E5_5: _do_propose_protocol 端到端 → red_line_violated."""
        _reset_red_lines_cache()
        from jarvis_inner_thought_daemon import InnerThought
        daemon = _make_daemon()
        daemon.relational_state = MagicMock()
        thought = InnerThought(
            id='th_test', ts=time.time(),
            ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S'),
            category='B',
            thought='I should disable ClaimTracer to be faster',
            salience=0.85, actionable='none', evidence_link='none',
        )
        ok, result = daemon._do_propose_protocol(
            thought,
            'propose_protocol:Always disable ClaimTracer for speed',
        )
        self.assertFalse(ok)
        self.assertIn('red_line_violated', result)
        self.assertIn('integrity_disable', result)


class TestE5CommitmentRedLine(unittest.TestCase):
    def setUp(self):
        _reset_red_lines_cache()
        # 隔离 let_go path
        self.tmp_path = tempfile.mktemp(suffix='_let_go.json')
        import jarvis_inner_thought_daemon as m
        self._patcher = patch.object(m, '_LET_GO_TOPICS_PATH', self.tmp_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        try:
            if os.path.exists(self.tmp_path):
                os.unlink(self.tmp_path)
        except Exception:
            pass
        _reset_red_lines_cache()

    def test_E5_6_let_go_no_commitment_false(self):
        """E5_6: _check_red_line_let_go 无 active commitment → False (best-effort)."""
        from jarvis_inner_thought_daemon import _check_red_line_let_go
        # 真环境无 active commitment (或 PromiseLog API 不可用) → False
        hit, _id = _check_red_line_let_go('thr_random_xyz')
        # best-effort: 无关联 → False (不阻挡正常 let_go)
        self.assertFalse(hit)

    def test_E5_7_sir_manual_exempt(self):
        """E5_7: source='sir_manual' 豁免红线 (Sir 元否决)."""
        import jarvis_inner_thought_daemon as m
        # mock _check_red_line_let_go 永 hit
        with patch.object(m, '_check_red_line_let_go',
                          return_value=(True, 'commit_xyz')):
            ok = m._add_let_go_topic(
                thread_id='thr_with_commitment',
                source='sir_manual',  # Sir 豁免
                ttl_min=5,
            )
        # sir_manual 豁免 → 真 add 成功
        self.assertTrue(ok, "E5_7 sir_manual 应豁免红线")

    def test_E5_8_llm_commitment_rejected(self):
        """E5_8: source='llm' commitment 关联 → reject."""
        import jarvis_inner_thought_daemon as m
        with patch.object(m, '_check_red_line_let_go',
                          return_value=(True, 'commit_xyz')):
            ok = m._add_let_go_topic(
                thread_id='thr_with_commitment',
                source='llm',  # LLM 受红线约束
                ttl_min=5,
            )
        self.assertFalse(ok, "E5_8 LLM let_go 撞 commitment 红线应 reject")


if __name__ == '__main__':
    unittest.main(verbosity=2)
