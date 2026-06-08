# -*- coding: utf-8 -*-
"""[bugB(c) Part 1 / Sir 2026-06-08] ProfileReflector 挂载 — env-gated default-off.

接 bugB(c) 前半环: 照 TranslatorReflector 范式把 ProfileReflector 挂进 CentralNerve,
让 corrections.jsonl → propose → review queue 自动跑 (治"我教的 profile 修正读不回")。

Part 1 只挂载 (不碰 activate 写回)。本测覆盖:
  T1 env=1 → start_daemon 真启后台线程 (_daemon_running=True)
  T2 env 未设 (默认) → start_daemon 不启 (_daemon_running=False) — behavior-preserving
  T3 env=0 显式关 → 不启
  T4 挂载块 source 契约: central_nerve 含 get_default_reflector 挂载 + env-gated 注释
  T5 daemon 纯后台 — start_daemon 不 push_command / 不碰 tick (源码无这些调用)
"""
from __future__ import annotations

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestProfileReflectorEnvGate(unittest.TestCase):
    def setUp(self):
        from jarvis_profile_reflector import reset_default_reflector_for_test
        reset_default_reflector_for_test()
        self._orig_env = os.environ.get('JARVIS_PROFILE_REFLECTOR')

    def tearDown(self):
        from jarvis_profile_reflector import get_default_reflector
        # 停掉可能起的 daemon, 还原 env
        try:
            r = get_default_reflector()
            r.stop_daemon()
        except Exception:
            pass
        if self._orig_env is None:
            os.environ.pop('JARVIS_PROFILE_REFLECTOR', None)
        else:
            os.environ['JARVIS_PROFILE_REFLECTOR'] = self._orig_env
        from jarvis_profile_reflector import reset_default_reflector_for_test
        reset_default_reflector_for_test()

    def _fresh(self):
        from jarvis_profile_reflector import ProfileReflector
        return ProfileReflector()

    def test_t1_env_1_starts_daemon(self):
        os.environ['JARVIS_PROFILE_REFLECTOR'] = '1'
        r = self._fresh()
        self.assertFalse(r._daemon_running)
        r.start_daemon()
        self.assertTrue(r._daemon_running, "env=1 应启 daemon")
        r.stop_daemon()

    def test_t2_env_unset_no_daemon(self):
        # behavior-preserving: 默认 (env 未设) 不启
        os.environ.pop('JARVIS_PROFILE_REFLECTOR', None)
        r = self._fresh()
        r.start_daemon()
        self.assertFalse(r._daemon_running, "env 未设 → daemon 不应启 (默认零行为变更)")

    def test_t3_env_0_no_daemon(self):
        os.environ['JARVIS_PROFILE_REFLECTOR'] = '0'
        r = self._fresh()
        r.start_daemon()
        self.assertFalse(r._daemon_running, "env=0 → daemon 不应启")


class TestMountContract(unittest.TestCase):
    """挂载块 source 契约 — 不实例化重 CentralNerve, 验挂载接线存在且 env-gated。"""

    def _nerve_src(self):
        import jarvis_central_nerve as M
        return open(M.__file__, encoding='utf-8').read()

    def test_t4_mount_block_present(self):
        src = self._nerve_src()
        # 照 TranslatorReflector 范式: get_default_reflector 挂载 + nerve 注入 + start_daemon
        self.assertIn('from jarvis_profile_reflector import get_default_reflector', src,
                      "T4 central_nerve 应 import ProfileReflector get_default_reflector")
        self.assertIn('self.profile_reflector', src,
                      "T4 应挂 self.profile_reflector")
        self.assertIn('.start_daemon()', src)
        # env-gated 注释标明默认 off
        self.assertIn('JARVIS_PROFILE_REFLECTOR', src,
                      "T4 挂载块应注明 env-gated")
        # Part 1 红线: 不碰 activate 写回
        # (挂载块不应直接调 activate / overwrite_field)
        # 取挂载块附近片段验
        idx = src.find('self.profile_reflector')
        seg = src[idx:idx + 800]
        self.assertNotIn('activate(', seg, "Part 1 挂载块不应碰 activate 写回")
        self.assertNotIn('overwrite_field', seg, "Part 1 挂载块不应碰 overwrite_field")

    def test_t5_daemon_no_push_command_no_tick(self):
        # daemon 纯后台 — 源码无 push_command / value_backoff / _next_tick
        import jarvis_profile_reflector as PR
        src = open(PR.__file__, encoding='utf-8').read()
        self.assertNotIn('push_command', src, "daemon 不应 push_command (不进主脑队列)")
        self.assertNotIn('value_backoff', src, "daemon 不应碰 value_backoff")
        self.assertNotIn('_next_tick_interval', src, "daemon 不应碰主脑 tick")


if __name__ == '__main__':
    unittest.main(verbosity=2)
