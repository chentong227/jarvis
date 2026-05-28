# -*- coding: utf-8 -*-
"""[Sir 2026-05-28 19:08 真测追根 BUG 治本] afk_short sensor 自动 reset.

源 BUG (Sir 真测 turn 20260528_19xx_xxxx, 多处 InnerThought log):
  💭 [InnerThought] Sir remains active despite his status lingering as
    'afk_short', indicating a manual toggle was overlooked.
  💭 [InnerThought] Sir's sustained engagement with the terminal confirms
    he is no longer 'afk_short', a status now nearly two and a half hours
    out of date.
  💭 [InnerThought] Sir is currently coding, neglecting the 17:00 interview
    prep reminder by two hours. (实际 Sir 在 coding, status 卡 afk_short)
根因:
  jarvis_sir_status_tracker 只听 Sir utterance vocab 触发 (observe_sir_utterance),
  没物理活动 sensor 自动 reset. Sir 说"afk 一下" 触发 STATUS_AFK_SHORT 后没说
  "back" → store 卡 afk_short 2.5h, age 远超 expected 1800s, is_overdue=True
  但 store 不自 reset → 思考脑反复看 stale 反复 reason → spam log.

治本 (准则 6 数据强耦合 + 8 优雅, §6 4 问全 Yes):
  jarvis_sir_status_tracker.current_status() 加 reconcile pre-check
  (_try_auto_reconcile_afk_short):
    - status == afk_short
    - is_overdue() == True (age > 1800s)
    - 物理 idle (env_probe PhysicalEnvironmentProbe.idle_seconds_real) < 300s
    → 自动 update_status('back', ...) reset 到 active + publish SWM
      'sir_status_auto_reconciled' raw signal (含 overdue_age_s/physical_idle_s).
  边界保守: 只 reconcile afk_short, 不动 sleep/lunch/out (Sir 真离开的状态
  不该被短时手机/上厕所 idle<300 误 reset).
  防回退: env_probe 不可用 (test/CI) → 不 reconcile + 不 crash. idle=0 (无 sample)
  → 不 reconcile (防 init 假阳).

6 testcase 覆盖 (Sir 真 case + 4 边界 + 1 source marker).
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(name: str) -> str:
    with open(os.path.join(ROOT, name), 'r', encoding='utf-8') as f:
        return f.read()


def _fresh_store():
    """每个 test 用独立 tempfile store, 防互染."""
    import jarvis_sir_status_tracker as sst
    tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
    tmp.close()
    sst.reset_default_store_for_tests(tmp.name)
    return sst.get_default_store(), tmp.name


class TestFix40AfkShortAutoReconcile(unittest.TestCase):

    def tearDown(self):
        # 还原默认 store 防影响其他 test
        try:
            import jarvis_sir_status_tracker as sst
            sst.reset_default_store_for_tests()
        except Exception:
            pass

    def test_sir_real_case_afk_short_overdue_active_reconciles(self):
        """Sir 真痛 case — afk_short overdue 2.5h + 物理 idle 5s → 自动 reset active."""
        import jarvis_sir_status_tracker as sst
        store, _ = _fresh_store()
        # 制造 Sir 真痛场景: afk_short 已 9000s (2.5h, 远超 1800s expected)
        store.update_status(
            new_status=sst.STATUS_AFK_SHORT,
            keyword='afk_short_test',
            utterance='afk 一下',
            turn_id='t_setup',
        )
        # 手动倒回 since_ts 模拟 2.5h 前 set
        with store._lock:
            store._status.since_ts = time.time() - 9000
        # 前提 sanity
        cur_before = store.current()
        self.assertEqual(cur_before.status, sst.STATUS_AFK_SHORT)
        self.assertTrue(cur_before.is_overdue(),
                         '前提: 2.5h 远超 30min expected → is_overdue=True')

        # mock env_probe 返物理 idle 5s (Sir 真在用键鼠)
        mock_bus = MagicMock()
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as _MP, \
             patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            _MP.idle_seconds_real = 5.0
            cur = sst.current_status()

        # 真测 1: status 已 reset 到 active
        self.assertEqual(cur['status'], sst.STATUS_ACTIVE,
                          'afk_short overdue + 物理 idle 5s 必须 reset 到 active')
        # 真测 2: SWM publish 触发 (准则 6 数据强耦合)
        self.assertTrue(mock_bus.publish.called,
                         '必须 publish SWM sir_status_auto_reconciled raw signal')
        _call = mock_bus.publish.call_args
        self.assertEqual(_call.kwargs.get('etype'), 'sir_status_auto_reconciled')
        _meta = _call.kwargs.get('metadata', {})
        self.assertEqual(_meta.get('from_status'), sst.STATUS_AFK_SHORT)
        self.assertEqual(_meta.get('to_status'), sst.STATUS_ACTIVE)
        self.assertGreaterEqual(_meta.get('overdue_age_s', 0), 1800,
                                  'overdue_age_s raw signal 必含真实超期秒数')
        self.assertEqual(_meta.get('physical_idle_s'), 5,
                          'physical_idle_s raw signal 必含真实 idle 秒数')

    def test_afk_short_not_overdue_no_reconcile(self):
        """afk_short 还没 overdue (age < 1800s) → 不动."""
        import jarvis_sir_status_tracker as sst
        store, _ = _fresh_store()
        store.update_status(
            new_status=sst.STATUS_AFK_SHORT,
            keyword='afk_short_test',
            utterance='afk 一下',
            turn_id='t_setup',
        )
        # 默认 since_ts=now → age ≈ 0s < 1800s
        cur_before = store.current()
        self.assertFalse(cur_before.is_overdue(), '前提: 没 overdue')

        mock_bus = MagicMock()
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as _MP, \
             patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            _MP.idle_seconds_real = 5.0  # 即使物理活跃
            cur = sst.current_status()

        self.assertEqual(cur['status'], sst.STATUS_AFK_SHORT,
                          '未 overdue 不该 reset')
        mock_bus.publish.assert_not_called()

    def test_sleep_overdue_no_reconcile_protect_context(self):
        """sleep + overdue + 物理 idle 5s → 仍不动 (保 sleep return context)."""
        import jarvis_sir_status_tracker as sst
        store, _ = _fresh_store()
        store.update_status(
            new_status=sst.STATUS_SLEEP,
            keyword='sleep_test',
            utterance='Good night',
            turn_id='t_setup',
        )
        # 模拟 18h 前 (sleep expected 8h, is_overdue 2x 宽容 = 16h 阈值)
        with store._lock:
            store._status.since_ts = time.time() - 18 * 3600
        cur_before = store.current()
        self.assertEqual(cur_before.status, sst.STATUS_SLEEP)
        self.assertTrue(cur_before.is_overdue(),
                         '前提: 18h>8h×2=16h 阈值 → overdue')

        mock_bus = MagicMock()
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as _MP, \
             patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            _MP.idle_seconds_real = 5.0
            cur = sst.current_status()

        # sleep 仍 sleep — 不被 reconcile
        self.assertEqual(cur['status'], sst.STATUS_SLEEP,
                          'sleep overdue 即使物理活跃也不该 auto reset (保护 sleep return greeting context)')
        mock_bus.publish.assert_not_called()

    def test_afk_short_overdue_but_real_afk_no_reconcile(self):
        """afk_short overdue 但 物理 idle ≥ 300s (Sir 真还离开) → 不 reset."""
        import jarvis_sir_status_tracker as sst
        store, _ = _fresh_store()
        store.update_status(
            new_status=sst.STATUS_AFK_SHORT,
            keyword='afk_short_test',
            utterance='afk 一下',
            turn_id='t_setup',
        )
        with store._lock:
            store._status.since_ts = time.time() - 9000  # 2.5h overdue
        cur_before = store.current()
        self.assertTrue(cur_before.is_overdue())

        mock_bus = MagicMock()
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as _MP, \
             patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            _MP.idle_seconds_real = 600.0  # Sir 真 10min 没动
            cur = sst.current_status()

        self.assertEqual(cur['status'], sst.STATUS_AFK_SHORT,
                          'Sir 真还离开 (idle ≥300s) 不该 reset, afk_short overdue 也合理 keep')
        mock_bus.publish.assert_not_called()

    def test_env_probe_unavailable_no_crash_no_reconcile(self):
        """env_probe import 失败 (test/CI 无 sensor) → 不 reconcile + 不 crash."""
        import jarvis_sir_status_tracker as sst
        store, _ = _fresh_store()
        store.update_status(
            new_status=sst.STATUS_AFK_SHORT,
            keyword='afk_short_test',
            utterance='afk 一下',
            turn_id='t_setup',
        )
        with store._lock:
            store._status.since_ts = time.time() - 9000
        cur_before = store.current()
        self.assertTrue(cur_before.is_overdue())

        mock_bus = MagicMock()
        # 模拟 env_probe import 失败 — patch 让 import 时 raise
        import builtins
        orig_import = builtins.__import__
        def _bad_import(name, *args, **kwargs):
            if name == 'jarvis_env_probe':
                raise ImportError('simulated: env_probe missing')
            return orig_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=_bad_import), \
             patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            try:
                cur = sst.current_status()
            except Exception as e:
                self.fail(f'env_probe 不可用不该 crash, 但抛了 {type(e).__name__}: {e}')

        # 不 reconcile (但 status 仍可读, current_status return dict 仍正常)
        self.assertEqual(cur['status'], sst.STATUS_AFK_SHORT,
                          'env_probe 不可用 → 不 reconcile (保守安全)')
        # 不 publish (因为 reconcile 没触发)
        # 注: mock_bus.publish 可能被其他模块调 — 我们只看 sir_status_auto_reconciled 这种 etype
        for _call in mock_bus.publish.call_args_list:
            _et = _call.kwargs.get('etype', '')
            self.assertNotEqual(_et, 'sir_status_auto_reconciled',
                                  'env_probe 失败不该 publish reconcile event')

    def test_source_has_reconcile_marker(self):
        """source — jarvis_sir_status_tracker.py 含本 fix 治本 marker."""
        src = _read('jarvis_sir_status_tracker.py')
        # marker 1: fix 注释 anchor
        self.assertIn('Sir 2026-05-28 19:08', src,
                       'source 应有 fix40 Sir 真测 anchor 注释')
        # marker 2: reconcile 函数
        self.assertIn('_try_auto_reconcile_afk_short', src,
                       'source 应有 reconcile 函数')
        # marker 3: event etype
        self.assertIn('sir_status_auto_reconciled', src,
                       'source 应有 SWM publish etype 标识')
        # marker 4: current_status 调用 reconcile pre-check
        self.assertIn('_try_auto_reconcile_afk_short(store)', src,
                       'current_status 必须调 reconcile pre-check')


if __name__ == '__main__':
    unittest.main()
