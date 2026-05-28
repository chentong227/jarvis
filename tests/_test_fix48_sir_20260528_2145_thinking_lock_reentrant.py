# -*- coding: utf-8 -*-
"""[fix48 / Sir 2026-05-28 21:45] _THINKING_BRAIN_DS_LOCK self-deadlock 治本.

Sir 真痛 (py-spy PID 51892 直接验证):
  InnerThoughtDaemon Thread 49768 卡死在:
    _record_thinking_brain_routing (jarvis_utils.py:5497)
      → invalidate_thinking_brain_ds_cache (jarvis_utils.py:5322)
  根因: `_record_thinking_brain_routing` 第 5433 行 `with _THINKING_BRAIN_DS_LOCK:`
  持锁状态下, 末尾第 5497 行调 `invalidate_thinking_brain_ds_cache()`, 后者第
  5322 行又 `with _THINKING_BRAIN_DS_LOCK:` — 同一把 lock 二次 acquire.
  老代码 `threading.Lock()` 不可重入 → 同线程二次 acquire 永久阻塞.

  从第 2 次 tick 起 (第 1 次 cache empty 不进 routing path), 思考脑全部 tick
  路径都走 _record_thinking_brain_routing → 全部死锁 → InnerThoughtDaemon
  从此沉默不 propose 不发声.

  fix48 一字治本 (jarvis_utils.py:5245):
    _THINKING_BRAIN_DS_LOCK = threading.Lock()    # 旧
    _THINKING_BRAIN_DS_LOCK = threading.RLock()   # 新, 同线程可重入

7 testcase 覆盖:
  T1: _THINKING_BRAIN_DS_LOCK 是 RLock 类型 (防退化回 Lock)
  T2: 同线程二次 acquire 不阻塞 (RLock 语义)
  T3: invalidate 在已持锁线程内调用不阻塞 (真实 reentrant scenario)
  T4: _record_thinking_brain_routing(routed=True) 完整 path 不阻塞 (含末尾 invalidate)
  T5: _record_thinking_brain_routing(routed=False) 完整 path 不阻塞 (skip_reason path)
  T6: _thinking_brain_ds_atomic_mutate 也是 reentrant 安全 (同款 lock 内 invalidate)
  T7: 跨线程互斥仍正确 (RLock 不破坏跨线程互斥, 同线程才可重入)
"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ============================================================
# 兜底超时 — 任何 test 卡 > N 秒 → fail (而不是吊死 pytest runner)
# ============================================================
def _run_with_timeout(fn, timeout_s: float = 5.0):
    """Run fn in daemon thread, return (done, exc). done=False → 超时."""
    result = {'done': False, 'exc': None, 'ret': None}

    def _target():
        try:
            result['ret'] = fn()
            result['done'] = True
        except Exception as e:
            result['exc'] = e
            result['done'] = True

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    return result


class TestLockType(unittest.TestCase):
    """T1: _THINKING_BRAIN_DS_LOCK 是 RLock 类型."""

    def test_lock_is_rlock(self):
        from jarvis_utils import _THINKING_BRAIN_DS_LOCK
        # threading.RLock() 返工厂函数, 实例 class name 含 'RLock'
        # threading.Lock() 实例 class name 是 'lock'
        cls_name = type(_THINKING_BRAIN_DS_LOCK).__name__
        self.assertIn(
            'RLock', cls_name,
            f"期望 RLock 防 self-deadlock, 实际 type={cls_name}. "
            f"fix48 退化! 检查 jarvis_utils.py:5245",
        )


class TestReentrant(unittest.TestCase):
    """T2-T3: 同线程可重入 acquire 不阻塞."""

    def test_T2_same_thread_double_acquire(self):
        """RLock 同线程二次 acquire 立刻返回 (Lock 会卡死)."""
        from jarvis_utils import _THINKING_BRAIN_DS_LOCK

        def _double_acquire():
            with _THINKING_BRAIN_DS_LOCK:
                with _THINKING_BRAIN_DS_LOCK:
                    return 'ok'

        r = _run_with_timeout(_double_acquire, timeout_s=3.0)
        self.assertTrue(r['done'], "RLock 二次 acquire 卡死 — fix48 退化!")
        self.assertIsNone(r['exc'])
        self.assertEqual(r['ret'], 'ok')

    def test_T3_invalidate_within_lock(self):
        """同线程持锁中调 invalidate (真实 _record_thinking_brain_routing path)."""
        from jarvis_utils import (
            _THINKING_BRAIN_DS_LOCK,
            invalidate_thinking_brain_ds_cache,
        )

        def _reentrant_invalidate():
            with _THINKING_BRAIN_DS_LOCK:
                # 这就是 _record_thinking_brain_routing 第 5497 行做的事
                invalidate_thinking_brain_ds_cache()
                return 'ok'

        r = _run_with_timeout(_reentrant_invalidate, timeout_s=3.0)
        self.assertTrue(
            r['done'],
            "持锁状态调 invalidate 卡死 — InnerThoughtDaemon "
            "py-spy 51892 验证的 self-deadlock 复现!",
        )
        self.assertIsNone(r['exc'])
        self.assertEqual(r['ret'], 'ok')


class TestRecordRouting(unittest.TestCase):
    """T4-T5: _record_thinking_brain_routing 完整路径不阻塞."""

    def test_T4_record_routed_completes(self):
        """routed=True path — vocab write + cache invalidate, 整链不卡."""
        from jarvis_utils import _record_thinking_brain_routing

        def _call():
            _record_thinking_brain_routing(
                routed=True, trigger='tick_origin:test_fix48',
                success=True, fallback=False,
            )
            return 'ok'

        r = _run_with_timeout(_call, timeout_s=3.0)
        self.assertTrue(
            r['done'],
            "_record_thinking_brain_routing(routed=True) 卡死 — 思考脑 tick "
            "永远走这条路, 卡死 = 思考脑沉默 (Sir 真痛 py-spy 51892)",
        )
        self.assertIsNone(r['exc'])

    def test_T5_record_skipped_completes(self):
        """routed=False path — skip_reason 不走 invalidate 但也要不卡."""
        from jarvis_utils import _record_thinking_brain_routing

        def _call():
            _record_thinking_brain_routing(
                routed=False, skip_reason='no_trigger',
            )
            return 'ok'

        r = _run_with_timeout(_call, timeout_s=3.0)
        self.assertTrue(r['done'])
        self.assertIsNone(r['exc'])


class TestAtomicMutate(unittest.TestCase):
    """T6: _thinking_brain_ds_atomic_mutate 同款 lock-then-invalidate 模式."""

    def test_T6_atomic_mutate_reentrant_safe(self):
        """通过 public mutation API 验证 atomic_mutate 也是可重入安全."""
        from jarvis_utils import set_thinking_brain_ds_gate

        def _call():
            # 拿当前 gate 状态 → flip → flip 回 (净 0 影响)
            from jarvis_utils import _load_thinking_brain_ds_vocab
            cur = int(_load_thinking_brain_ds_vocab().get('enabled', 0))
            target = 1 - cur
            ok1, _ = set_thinking_brain_ds_gate(
                bool(target), source='test_fix48',
                rationale='reentrant safety smoke test',
            )
            ok2, _ = set_thinking_brain_ds_gate(
                bool(cur), source='test_fix48',
                rationale='restore',
            )
            return (ok1, ok2)

        r = _run_with_timeout(_call, timeout_s=5.0)
        self.assertTrue(
            r['done'],
            "set_thinking_brain_ds_gate 卡死 — atomic_mutate 也走同款 "
            "lock-then-invalidate 模式, RLock 必须 cover",
        )
        # 注: 不 assert (ok1, ok2) 真值 — 即使 vocab 路径不存在 / write fail
        # mutator 返 False 也 OK, 关键是不卡死


class TestCrossThreadMutex(unittest.TestCase):
    """T7: RLock 不破坏跨线程互斥 (同线程才可重入)."""

    def test_T7_cross_thread_serializes(self):
        """两个不同线程同时 acquire — 应串行, 不并发持锁."""
        from jarvis_utils import _THINKING_BRAIN_DS_LOCK

        events = []
        ev_a_in = threading.Event()
        ev_b_done = threading.Event()
        ev_a_release = threading.Event()

        def _thread_a():
            with _THINKING_BRAIN_DS_LOCK:
                events.append('a_acquired')
                ev_a_in.set()
                # 等主测试 signal 才释放
                ev_a_release.wait(timeout=3.0)
                events.append('a_releasing')

        def _thread_b():
            # 等 A 先拿锁
            ev_a_in.wait(timeout=3.0)
            events.append('b_trying')
            with _THINKING_BRAIN_DS_LOCK:
                events.append('b_acquired')
            ev_b_done.set()

        ta = threading.Thread(target=_thread_a, daemon=True)
        tb = threading.Thread(target=_thread_b, daemon=True)
        ta.start()
        tb.start()

        # 给 A/B 启动 + B 尝试 acquire 时间
        self.assertTrue(ev_a_in.wait(timeout=2.0), 'A 没拿到锁')
        time.sleep(0.2)
        # 此刻 B 应在等 (events 不含 b_acquired)
        self.assertIn('b_trying', events)
        self.assertNotIn(
            'b_acquired', events,
            "RLock 破坏跨线程互斥! B 不应在 A 持锁时拿到锁",
        )

        # 放 A
        ev_a_release.set()
        ta.join(timeout=2.0)
        self.assertTrue(ev_b_done.wait(timeout=2.0), 'B 没完成')
        tb.join(timeout=2.0)
        # B 拿锁应在 A 释放后
        self.assertIn('a_releasing', events)
        self.assertIn('b_acquired', events)
        idx_a_rel = events.index('a_releasing')
        idx_b_acq = events.index('b_acquired')
        self.assertLess(
            idx_a_rel, idx_b_acq,
            "B 在 A 释放前拿到锁 — RLock 跨线程互斥失效!",
        )


if __name__ == '__main__':
    unittest.main()
