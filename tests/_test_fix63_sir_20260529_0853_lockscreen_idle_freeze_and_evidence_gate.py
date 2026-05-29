# -*- coding: utf-8 -*-
"""[BUG FIX / Sir 2026-05-29 08:53 真测] 锁屏降频冻结 + 支柱A 指纹污染 双修.

Sir 真测: 昨晚息屏/锁屏整晚, 思考脑 309 次空转 state 全 active 没降频 +
支柱A evidence-gate skip=0 (省 token 完全失效). Sir 洞察"会不会和息屏有关?
息屏后不能截图" 直接命中元凶.

双重根因 (共同源: 锁屏后进程丢桌面访问):
1. 锁屏降频死: env_probe._monitor_loop 的 GetCursorPos 在锁屏/secure desktop 抛
   Access denied → loop 每轮在 idle 更新前炸 → idle_seconds_real 冻结小值 →
   InnerThought._get_idle_seconds 读冻结缓存 → state 永远 active → tick 45s.
   (ReturnSentinel 直调 GetLastInputInfo 不受影响, 印证根因.)
2. 支柱A 指纹污染: evidence 指纹含 swm_events 但不 filter source, 自产
   (inner_thought) + sensor (PhysicalEnvProbe) + daemon advice (*_advice) 每 tick
   变 → 指纹永变 → 永不 skip.

修复:
- env_probe._monitor_loop: idle 更新前置到 GetLastInputInfo 后立即 + GetCursorPos
  单独 try 锁屏降级 (源码结构 LOOP1/LOOP2).
- InnerThought._get_idle_seconds: 直调 GetLastInputInfo 不依赖缓存 (IDLE1/IDLE2).
- _compute_evidence_fingerprint: 排除自产/高频 event (vocab 驱动) (FP1-6).
- CLI scripts/inner_thought_cost_dump.py (CLI1-3).
- screen_vision 截图锁屏诊断标签 (SS1).

测试覆盖 (14 testcase).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    return InnerThoughtDaemon.__new__(InnerThoughtDaemon)


def _load_cli():
    """从文件路径 load CLI module (不依赖 scripts package)."""
    path = os.path.join(ROOT, 'scripts', 'inner_thought_cost_dump.py')
    spec = importlib.util.spec_from_file_location('itc_dump', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 固定 cost config (测试不依赖 json 文件内容, 防 Sir 改 json 破坏测试)
_FAKE_COST_CFG = {
    'evidence_gate': {
        'enabled': True,
        'max_skip_streak': 20,
        'idle_buckets_s': [300, 1800],
        'fingerprint_exclude_sources': ['inner_thought', 'PhysicalEnvProbe'],
        'fingerprint_exclude_etype_suffixes': ['_advice'],
    }
}


class TestIdleDirectAPI(unittest.TestCase):
    """fix_idle: _get_idle_seconds 直调 GetLastInputInfo (不依赖冻结缓存)."""

    def test_IDLE1_realtime_nonneg(self):
        d = _make_daemon()
        idle = d._get_idle_seconds()
        self.assertIsInstance(idle, float)
        self.assertGreaterEqual(idle, 0.0)

    def test_IDLE2_source_prefers_getlastinput_over_cache(self):
        with open(os.path.join(ROOT, 'jarvis_inner_thought_daemon.py'),
                  encoding='utf-8') as f:
            src = f.read()
        idx = src.find('def _get_idle_seconds')
        self.assertGreater(idx, 0)
        snippet = src[idx:idx + 800]
        self.assertIn('GetLastInputInfo', snippet)
        idx_api = snippet.find('GetLastInputInfo')
        idx_cache = snippet.find('idle_seconds_real')
        self.assertGreater(idx_cache, 0, '缓存 fallback 应保留')
        self.assertLess(idx_api, idx_cache,
                        'GetLastInputInfo 应在缓存 fallback 之前 (首选实时)')


class TestFingerprintExcludeSelfProduced(unittest.TestCase):
    """fix_gate: _compute_evidence_fingerprint 排除自产/高频 event (核心)."""

    def _fp(self, daemon, sir_state, evidence):
        with patch('jarvis_inner_thought_daemon._load_cost_config',
                   return_value=_FAKE_COST_CFG):
            return daemon._compute_evidence_fingerprint(sir_state, evidence)

    def test_FP1_exclude_inner_thought_source(self):
        d = _make_daemon()
        ev_a = {'idle_seconds': 3600, 'swm_events': [
            {'type': 'self_reflection_noted', 'desc': 'AAA',
             'source': 'inner_thought'},
        ], 'stm': []}
        ev_b = {'idle_seconds': 3600, 'swm_events': [
            {'type': 'self_reflection_noted', 'desc': 'BBB DIFFERENT',
             'source': 'inner_thought'},
        ], 'stm': []}
        # 自产 event 内容不同, 但都排除 → 指纹相同
        self.assertEqual(self._fp(d, 'sleep', ev_a), self._fp(d, 'sleep', ev_b))

    def test_FP2_exclude_physenvprobe_source(self):
        d = _make_daemon()
        ev_a = {'idle_seconds': 3600, 'swm_events': [
            {'type': 'sensor_change', 'desc': 'win X', 'source': 'PhysicalEnvProbe'},
        ], 'stm': []}
        ev_b = {'idle_seconds': 3600, 'swm_events': [
            {'type': 'sensor_change', 'desc': 'win Y', 'source': 'PhysicalEnvProbe'},
        ], 'stm': []}
        self.assertEqual(self._fp(d, 'sleep', ev_a), self._fp(d, 'sleep', ev_b))

    def test_FP3_exclude_advice_suffix(self):
        d = _make_daemon()
        ev_a = {'idle_seconds': 3600, 'swm_events': [
            {'type': 'proactive_care_advice', 'desc': 'u=0.5',
             'source': 'ProactiveCare'},
        ], 'stm': []}
        ev_b = {'idle_seconds': 3600, 'swm_events': [
            {'type': 'nudge_window_advice', 'desc': 'u=0.9',
             'source': 'ProactiveCare'},
        ], 'stm': []}
        # 都是 *_advice → suffix 排除 → 指纹相同
        self.assertEqual(self._fp(d, 'sleep', ev_a), self._fp(d, 'sleep', ev_b))

    def test_FP4_keep_external_event(self):
        d = _make_daemon()
        ev_a = {'idle_seconds': 3600, 'swm_events': [
            {'type': 'sir_afk_detected', 'desc': 'idle 76min',
             'source': 'ReturnSentinel'},
        ], 'stm': []}
        ev_b = {'idle_seconds': 3600, 'swm_events': [
            {'type': 'sir_afk_detected', 'desc': 'idle 80min DIFF',
             'source': 'ReturnSentinel'},
        ], 'stm': []}
        # 真外部 event desc 变 → 指纹变 (正确触发 think)
        self.assertNotEqual(self._fp(d, 'sleep', ev_a), self._fp(d, 'sleep', ev_b))

    def test_FP5_idle_only_self_produced_stable(self):
        """挂机场景: 只有自产/高频 event → 指纹稳定 → skip 生效 (支柱A 核心)."""
        d = _make_daemon()
        ev1 = {'idle_seconds': 3600, 'swm_events': [
            {'type': 'self_reflection_noted', 'desc': 't1', 'source': 'inner_thought'},
            {'type': 'sensor_change', 'desc': 'w1', 'source': 'PhysicalEnvProbe'},
            {'type': 'proactive_care_advice', 'desc': 'a1', 'source': 'ProactiveCare'},
        ], 'stm': []}
        ev2 = {'idle_seconds': 3650, 'swm_events': [  # 同 idle 桶 (>1800)
            {'type': 'self_reflection_noted', 'desc': 't2', 'source': 'inner_thought'},
            {'type': 'sensor_change', 'desc': 'w2', 'source': 'PhysicalEnvProbe'},
            {'type': 'nudge_window_advice', 'desc': 'a2', 'source': 'ProactiveCare'},
        ], 'stm': []}
        self.assertEqual(self._fp(d, 'sleep', ev1), self._fp(d, 'sleep', ev2))

    def test_FP6_stm_new_turn_changes_fp(self):
        """Sir 说新话 (STM 新 turn) → 指纹变 (不 skip)."""
        d = _make_daemon()
        ev_a = {'idle_seconds': 100, 'swm_events': [], 'stm': [
            {'when': '10:00:00', 'user': 'hello'},
        ]}
        ev_b = {'idle_seconds': 100, 'swm_events': [], 'stm': [
            {'when': '10:00:30', 'user': 'jarvis help'},
        ]}
        self.assertNotEqual(self._fp(d, 'active', ev_a), self._fp(d, 'active', ev_b))


class TestCostConfigCLI(unittest.TestCase):
    """CLI: inner_thought_cost_dump 增删改 (准则6)."""

    @classmethod
    def setUpClass(cls):
        cls.cli = _load_cli()

    def test_CLI1_exclude_source_add_remove(self):
        with patch.object(self.cli, '_save'):
            cfg = {'evidence_gate': {'fingerprint_exclude_sources': ['inner_thought']}}
            self.cli.cmd_list_edit(cfg, 'fingerprint_exclude_sources', 'NewSrc', None)
            self.assertIn('NewSrc',
                          cfg['evidence_gate']['fingerprint_exclude_sources'])
            self.cli.cmd_list_edit(cfg, 'fingerprint_exclude_sources',
                                   None, 'inner_thought')
            self.assertNotIn('inner_thought',
                             cfg['evidence_gate']['fingerprint_exclude_sources'])

    def test_CLI2_set_max_skip(self):
        with patch.object(self.cli, '_save'):
            cfg = {'evidence_gate': {'max_skip_streak': 20}}
            self.cli.cmd_set(cfg, ['max_skip_streak=30'])
            self.assertEqual(cfg['evidence_gate']['max_skip_streak'], 30)

    def test_CLI3_toggle_disable(self):
        with patch.object(self.cli, '_save'):
            cfg = {'evidence_gate': {'enabled': True}}
            self.cli.cmd_toggle(cfg, False)
            self.assertFalse(cfg['evidence_gate']['enabled'])


class TestEnvProbeLoopLockScreen(unittest.TestCase):
    """fix_loop: env_probe 源码结构 (idle 前置 + GetCursorPos try 保护)."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_env_probe.py'), encoding='utf-8') as f:
            cls.src = f.read()

    def test_LOOP1_idle_update_before_mouse_block(self):
        # idle_seconds_real 赋值 应在 loop 内鼠标监控(GetCursorPos)块之前 (锁屏防炸).
        # 用 '# === 鼠标监控 ===' 锰点, 避开 loop 前 L432 _last_cursor_pos 初始化干扰.
        idx_idle = self.src.find('cls.idle_seconds_real = cls.idle_seconds')
        idx_mouse = self.src.find('# === 鼠标监控 ===')
        self.assertGreater(idx_idle, 0, 'idle_seconds_real 赋值必存在')
        self.assertGreater(idx_mouse, 0, '鼠标监控块必存在')
        self.assertLess(idx_idle, idx_mouse,
                        'idle 更新必在鼠标监控(GetCursorPos)块之前')

    def test_LOOP2_getcursorpos_has_try_guard(self):
        # 鼠标监控块 (GetCursorPos) 应在 try 块 (锁屏降级)
        idx_mouse = self.src.find('# === 鼠标监控 ===')
        block = self.src[idx_mouse:idx_mouse + 500]
        self.assertIn('try:', block, '鼠标监控块应有 try (锁屏降级 GetCursorPos)')
        # 用 'win32api.GetCursorPos()' (带前缀+括号) 区分实际调用 vs 注释里的 "GetCursorPos"
        self.assertIn('win32api.GetCursorPos()', block)
        self.assertLess(block.find('try:'), block.find('win32api.GetCursorPos()'),
                        'try 应在 GetCursorPos 实际调用之前 (包住它)')


class TestScreenVisionLockLabel(unittest.TestCase):
    """screenshot: 锁屏诊断标签."""

    def test_SS1_capture_locked_label(self):
        with open(os.path.join(ROOT, 'jarvis_screen_vision.py'),
                  encoding='utf-8') as f:
            src = f.read()
        self.assertIn('capture_locked', src,
                      '截图锁屏失败应标 capture_locked 便于诊断')


if __name__ == '__main__':
    unittest.main(verbosity=2)
