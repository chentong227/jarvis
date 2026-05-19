# -*- coding: utf-8 -*-
"""
[P0+20-β.5.15 / 2026-05-19] β.5 重构收尾 — InconsistencyWatcher 接入 NudgeGate + publish_skip

Sir 21:48 "把 5 层后面的都接入 LLM 怎么样" 准则 6 数据强耦合彻底落地最后 1 步.

修法:
  1. InconsistencyWatcher.__init__ 加 nudge_gate=None + _skip_publish_last_t = {}
  2. 加 _publish_skip helper (复用 WellnessGuardian 同设计 sal=0.15 不污染主脑 evidence)
  3. _tick startup_guard / global_cooldown skip 都调 _publish_skip
  4. _dispatch 前置 NudgeGate.can_speak('companion', nudge_type='proactive_care')
     publish_only 模式下永真但跨源 cooldown 统一
  5. ensure_inconsistency_watcher_started 接 nudge_gate 参数透传
  6. jarvis_routing.py:1025 CompanionCenter 传 self.gate (共享 NudgeGate)

测试覆盖:
  A. __init__ 接 nudge_gate 参数 + self.gate 字段
  B. _publish_skip helper 行为 (publish + sal=0.15 + dedupe + fail-safe)
  C. _tick startup_guard skip → publish
  D. _tick global_cooldown skip → publish
  E. _dispatch 前置 gate.can_speak (publish_only 永真)
  F. ensure_inconsistency_watcher_started 接 nudge_gate 透传 (字面)
  G. jarvis_routing.py 传 self.gate 字面 marker
"""

from __future__ import annotations

import inspect
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def _make_watcher_stub(nudge_gate=None):
    """构造 InconsistencyWatcher (不启动 thread)."""
    from jarvis_inconsistency_watcher import InconsistencyWatcher
    w = InconsistencyWatcher.__new__(InconsistencyWatcher)
    w.worker = MagicMock()
    w.nerve = None
    w.gate = nudge_gate
    w.tick = 60.0
    w._fired_promises = {}
    w._last_any_fire_ts = 0.0
    w._daemon_start_ts = time.time() - 1000  # 跳过 startup guard
    w._skip_publish_last_t = {}
    return w


# ==========================================================================
# A: __init__ 接 nudge_gate
# ==========================================================================

class TestBeta515InitAcceptsGate(unittest.TestCase):
    """InconsistencyWatcher.__init__ 接 nudge_gate 参数."""

    def test_init_signature_has_nudge_gate(self):
        from jarvis_inconsistency_watcher import InconsistencyWatcher
        sig = inspect.signature(InconsistencyWatcher.__init__)
        self.assertIn('nudge_gate', sig.parameters,
            'InconsistencyWatcher.__init__ 必须接 nudge_gate 参数 (β.5.15)')
        self.assertIsNone(sig.parameters['nudge_gate'].default,
            'nudge_gate 默认 None (向后兼容)')


# ==========================================================================
# B: _publish_skip helper
# ==========================================================================

class TestBeta515PublishSkipHelper(unittest.TestCase):
    """_publish_skip 行为正确."""

    def test_helper_exists(self):
        w = _make_watcher_stub()
        self.assertTrue(hasattr(w, '_publish_skip'),
            'InconsistencyWatcher 必须有 _publish_skip 方法')

    def test_publish_calls_event_bus(self):
        w = _make_watcher_stub()
        with patch('jarvis_utils.get_event_bus') as mock_get:
            mock_bus = MagicMock()
            mock_get.return_value = mock_bus
            w._publish_skip('test_reason', {'k': 'v'})
            mock_bus.publish.assert_called_once()
            ck = mock_bus.publish.call_args.kwargs
            self.assertEqual(ck.get('source'), 'InconsistencyWatcher')
            self.assertEqual(ck.get('etype'), 'gate_advice')
            self.assertIn('test_reason', ck.get('description', ''))

    def test_salience_below_render_floor(self):
        w = _make_watcher_stub()
        with patch('jarvis_utils.get_event_bus') as mock_get:
            mock_bus = MagicMock()
            mock_get.return_value = mock_bus
            w._publish_skip('sal_test')
            ck = mock_bus.publish.call_args.kwargs
            self.assertEqual(ck.get('salience'), 0.15)

    def test_dedupe_60s(self):
        w = _make_watcher_stub()
        with patch('jarvis_utils.get_event_bus') as mock_get:
            mock_bus = MagicMock()
            mock_get.return_value = mock_bus
            w._publish_skip('dup')
            w._publish_skip('dup')
            self.assertEqual(mock_bus.publish.call_count, 1,
                '60s 内同 reason dedupe')

    def test_no_bus_silent_fail(self):
        w = _make_watcher_stub()
        with patch('jarvis_utils.get_event_bus') as mock_get:
            mock_get.return_value = None
            try:
                w._publish_skip('no_bus')
            except Exception as e:
                self.fail(f'_publish_skip 应 fail-safe, 实际 raise: {e}')


# ==========================================================================
# C: _tick startup_guard skip → publish
# ==========================================================================

class TestBeta515StartupGuardSkipPublishes(unittest.TestCase):
    """startup_guard 期间 skip 同时 publish."""

    def test_startup_guard_publishes(self):
        w = _make_watcher_stub()
        # 重置 daemon_start_ts 让 startup guard 仍生效
        w._daemon_start_ts = time.time()
        with patch('jarvis_utils.get_event_bus') as mock_get:
            mock_bus = MagicMock()
            mock_get.return_value = mock_bus
            w._tick()  # 应在 startup_guard 区间内
            mock_bus.publish.assert_called_once()
            ck = mock_bus.publish.call_args.kwargs
            self.assertIn('startup_guard', ck.get('description', ''))


# ==========================================================================
# D: _tick global_cooldown skip → publish
# ==========================================================================

class TestBeta515GlobalCooldownSkipPublishes(unittest.TestCase):
    """global_cooldown 期间 skip 同时 publish."""

    def test_global_cooldown_publishes(self):
        w = _make_watcher_stub()
        # 设最近 fire 过 → 触发 global cooldown
        w._last_any_fire_ts = time.time() - 30
        with patch('jarvis_utils.get_event_bus') as mock_get:
            mock_bus = MagicMock()
            mock_get.return_value = mock_bus
            w._tick()
            # 至少 publish 1 次 (global_cooldown_*)
            self.assertGreaterEqual(mock_bus.publish.call_count, 1,
                'global_cooldown skip 必须 publish')
            # 检查至少一次 publish 的 description 含 global_cooldown
            calls = mock_bus.publish.call_args_list
            descs = [c.kwargs.get('description', '') for c in calls]
            self.assertTrue(any('global_cooldown' in d for d in descs),
                'global_cooldown 字面必须出现在某次 publish 的 description')


# ==========================================================================
# E: _dispatch 前置 gate.can_speak
# ==========================================================================

class TestBeta515DispatchGateCheck(unittest.TestCase):
    """_dispatch 调 gate.can_speak (publish_only 永真但跨源 cooldown 统一)."""

    def test_dispatch_calls_gate(self):
        gate = MagicMock()
        gate.can_speak.return_value = True
        w = _make_watcher_stub(nudge_gate=gate)
        p = MagicMock()
        p.id = 'p1'
        p.jarvis_reply = 'I will sleep at 23:30'
        w._dispatch(p, 'inconsistency desc')
        gate.can_speak.assert_called_once()
        ck = gate.can_speak.call_args
        # nudge_type='proactive_care' (跟 CommitmentWatcher 一致 caller='companion')
        self.assertEqual(ck.args[0] if ck.args else ck.kwargs.get('center_name'),
                          'companion')

    def test_dispatch_gate_block_no_push(self):
        """gate.can_speak 返 False → 不 push (publish_only 模式下不会发生, 但 hard 模式会)."""
        gate = MagicMock()
        gate.can_speak.return_value = False
        w = _make_watcher_stub(nudge_gate=gate)
        p = MagicMock()
        p.id = 'p1'
        p.jarvis_reply = 'sleep'
        with patch('jarvis_utils.get_event_bus') as mock_get:
            mock_bus = MagicMock()
            mock_get.return_value = mock_bus
            w._dispatch(p, 'desc')
            # 应 publish skip (nudge_gate_block_proactive_care)
            self.assertGreaterEqual(mock_bus.publish.call_count, 1)
            # worker.push_command 不该被调
            w.worker.push_command.assert_not_called()

    def test_dispatch_no_gate_still_works(self):
        """nudge_gate=None 时仍能 dispatch (向后兼容)."""
        w = _make_watcher_stub(nudge_gate=None)
        p = MagicMock()
        p.id = 'p1'
        p.jarvis_reply = 'sleep'
        # 不应 raise
        w._dispatch(p, 'desc')
        # worker.push_command 应被调 1 次
        w.worker.push_command.assert_called_once()


# ==========================================================================
# F: ensure_inconsistency_watcher_started 接 nudge_gate 透传
# ==========================================================================

class TestBeta515EnsureStarterAcceptsGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_inconsistency_watcher.py'))

    def test_ensure_signature_has_nudge_gate(self):
        self.assertIn('nudge_gate=None', self.src,
            'ensure_inconsistency_watcher_started 必须接 nudge_gate 参数')

    def test_routing_passes_gate(self):
        rt = _read(os.path.join(ROOT, 'jarvis_routing.py'))
        self.assertIn('nudge_gate=self.gate', rt,
            'jarvis_routing.py CompanionCenter 必须传 nudge_gate=self.gate')


# ==========================================================================
# G: marker comment 持久化
# ==========================================================================

class TestBeta515PersistMarker(unittest.TestCase):
    def test_inconsistency_marker(self):
        src = _read(os.path.join(ROOT, 'jarvis_inconsistency_watcher.py'))
        self.assertIn('β.5.15', src,
            'β.5.15 marker 必须在 jarvis_inconsistency_watcher.py')

    def test_routing_marker(self):
        src = _read(os.path.join(ROOT, 'jarvis_routing.py'))
        self.assertIn('β.5.15', src,
            'β.5.15 marker 必须在 jarvis_routing.py')


if __name__ == '__main__':
    unittest.main()
