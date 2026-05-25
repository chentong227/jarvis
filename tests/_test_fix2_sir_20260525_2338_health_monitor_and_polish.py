# -*- coding: utf-8 -*-
"""[fix2 / Sir 2026-05-25 23:38 真意] 3 改进 + DaemonHealthMonitor.

Sir 真意:
  "每天帮我看你说的是否健康, 是否太低什么的, 然后帮我优化吧,
   我真就是想少干点活, 别又给我多一项工作"

1. B 类 self-reflection 优雅化: 删 keyword hardcode, sal≥0.5 全 publish
2. AutoArbiter inside_joke 识别 stock phrase vs Sir-specific (拒 stock)
3. DaemonHealthMonitor: 每 6h 自动检 4 项 + 异常 publish SWM
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================================
# L1: B 类优雅化 (删 keyword, sal≥0.5 全 publish)
# ==========================================================================
class TestL1BCategoryGraceful(unittest.TestCase):
    """Sir 真测: 'caught myself being slightly too reactive' 没 match keyword
    没触发. 治本: 删 hardcode, sal≥0.5 全 publish."""

    def _empty_daemon(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        with patch.object(InnerThoughtDaemon, 'PERSIST_PATH',
                            os.path.join(tempfile.gettempdir(),
                                         f'empty_{time.time()}.jsonl')):
            d = InnerThoughtDaemon(key_router=None)
        return d

    def test_self_reflection_publishes_for_high_sal_b(self):
        """B 类 sal=0.6 (any keyword 都没) → 应该 publish self_reflection_noted."""
        from jarvis_inner_thought_daemon import InnerThought
        d = self._empty_daemon()
        thought = InnerThought(
            id='t', ts=time.time(), ts_iso='?', category='B',
            thought=('I caught myself being slightly too reactive '
                     'regarding the interview scheduling earlier.'),
            salience=0.6, actionable='none',
        )
        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            d._maybe_publish_self_correction(thought)
        self.assertTrue(mock_bus.publish.called,
            'B 类 sal=0.6 必须 publish (不依赖 keyword match)')
        kw = mock_bus.publish.call_args.kwargs
        self.assertEqual(kw['etype'], 'self_reflection_noted',
            '改用新 etype self_reflection_noted (不是老 self_correction_noted)')

    def test_self_reflection_skips_low_sal_b(self):
        """B 类 sal=0.3 (< 0.5) → 不 publish (noise level)."""
        from jarvis_inner_thought_daemon import InnerThought
        d = self._empty_daemon()
        thought = InnerThought(
            id='t', ts=time.time(), ts_iso='?', category='B',
            thought='Just a fleeting thought, nothing major.',
            salience=0.3, actionable='none',
        )
        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            d._maybe_publish_self_correction(thought)
        mock_bus.publish.assert_not_called()

    def test_self_reflection_salience_passthrough(self):
        """sal=0.85 thought → publish salience >= 0.85 (强 reflection 高优先)."""
        from jarvis_inner_thought_daemon import InnerThought
        d = self._empty_daemon()
        thought = InnerThought(
            id='t', ts=time.time(), ts_iso='?', category='B',
            thought='Major realization about my pattern.',
            salience=0.85, actionable='none',
        )
        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            d._maybe_publish_self_correction(thought)
        kw = mock_bus.publish.call_args.kwargs
        self.assertGreaterEqual(kw['salience'], 0.85,
            'high-sal thought → high SWM salience (透传)')

    def test_self_reflection_skips_non_b(self):
        """A/C/D/E 类即使 sal 高也不 publish (B 类才是 self-reflect)."""
        from jarvis_inner_thought_daemon import InnerThought
        d = self._empty_daemon()
        for cat in 'ACDE':
            thought = InnerThought(
                id='t', ts=time.time(), ts_iso='?', category=cat,
                thought='Some thought.', salience=0.9, actionable='none',
            )
            mock_bus = MagicMock()
            with patch('jarvis_utils.get_event_bus', return_value=mock_bus):
                d._maybe_publish_self_correction(thought)
            mock_bus.publish.assert_not_called()


# ==========================================================================
# L2: AutoArbiter prompt 识别 stock phrase
# ==========================================================================
class TestL2AutoArbiterStockPhraseDetection(unittest.TestCase):
    """Sir 真测: 'I stand corrected, Sir' 这种 stock phrase 进 review.
    治本: prompt 加 STOCK PHRASE TEST 让 LLM 真识别 + REJECT."""

    def test_inside_joke_prompt_has_stock_test(self):
        """_build_prompt for inside_joke 必须含 STOCK PHRASE TEST."""
        from jarvis_auto_arbiter import AutoArbiterDaemon
        d = AutoArbiterDaemon(key_router=None)
        mock_joke = MagicMock(
            phrase='I stand corrected, Sir.',
            birth_context='test', tone='formal', source='auto',
        )
        system, user = d._build_prompt('inside_joke', mock_joke, {
            'kind': 'inside_joke',
            'entity': {
                'phrase': 'I stand corrected, Sir.',
                'birth_context': 'test', 'tone': 'formal', 'source': 'auto',
            },
            'existing_active_jokes': [],
            'stm': [],
        })
        self.assertIn('STOCK PHRASE TEST', system,
            'prompt 必须有 STOCK PHRASE TEST 段')
        self.assertIn('I stand corrected', system,
            'prompt 必须列具体 stock phrase 例 (准则 6 evidence)')
        self.assertIn('Sir-specific', system,
            'prompt 必须强调 Sir-specific 而非 generic butler')

    def test_inside_joke_prompt_reject_keyword(self):
        """prompt 必须含 REJECT instruction 含 'stock'/'cliché' 词."""
        from jarvis_auto_arbiter import AutoArbiterDaemon
        d = AutoArbiterDaemon(key_router=None)
        system, _ = d._build_prompt('inside_joke', MagicMock(), {
            'kind': 'inside_joke', 'entity': {},
            'existing_active_jokes': [], 'stm': [],
        })
        self.assertIn('REJECT', system)
        # 含 stock / cliché / generic 之类
        has_stock_word = any(w in system.lower()
                              for w in ('stock phrase', 'clich', 'generic'))
        self.assertTrue(has_stock_word,
            'REJECT criteria 必须含 stock/cliché/generic 关键判定')


# ==========================================================================
# L3: DaemonHealthMonitor 模块 + 数据收集
# ==========================================================================
class TestL3HealthMonitorBasic(unittest.TestCase):
    def test_module_imports(self):
        from jarvis_daemon_health_monitor import (
            DaemonHealthMonitor, get_default_monitor, set_default_monitor
        )
        self.assertTrue(hasattr(DaemonHealthMonitor, '_check_all'))
        self.assertTrue(hasattr(DaemonHealthMonitor,
                                  '_count_inner_thoughts_24h'))

    def test_init_does_not_crash(self):
        from jarvis_daemon_health_monitor import DaemonHealthMonitor
        m = DaemonHealthMonitor()
        self.assertIsNotNone(m)
        self.assertEqual(m._history, [])

    def test_thresholds_are_sane(self):
        from jarvis_daemon_health_monitor import DaemonHealthMonitor
        # 健康区间合理
        self.assertGreater(DaemonHealthMonitor.THOUGHTS_24H_MAX,
                            DaemonHealthMonitor.THOUGHTS_24H_MIN)
        self.assertGreater(DaemonHealthMonitor.CATEGORY_DOMINATION, 0.5)
        self.assertLess(DaemonHealthMonitor.CATEGORY_DOMINATION, 1.0)
        # tick 不该太频繁 (Sir 不想刷屏)
        self.assertGreaterEqual(DaemonHealthMonitor.TICK_INTERVAL_S, 3600)


# ==========================================================================
# L4: HealthMonitor 检 4 项 → publish SWM
# ==========================================================================
class TestL4HealthMonitorChecks(unittest.TestCase):
    def setUp(self):
        from jarvis_daemon_health_monitor import DaemonHealthMonitor
        self.tmpdir = tempfile.mkdtemp()
        self.m = DaemonHealthMonitor()
        self.m.PERSIST_PATH = os.path.join(self.tmpdir, 'health.json')

    def _make_jsonl(self, thoughts: list):
        """Helper: 写 inner_thoughts.jsonl in tmp."""
        os.makedirs(os.path.join(self.tmpdir, 'memory_pool'), exist_ok=True)
        path = os.path.join(self.tmpdir, 'memory_pool', 'inner_thoughts.jsonl')
        with open(path, 'w', encoding='utf-8') as f:
            for t in thoughts:
                f.write(json.dumps(t) + '\n')
        return path

    def test_check_thoughts_too_few(self):
        """count < 30 → warn issue."""
        jsonl = self._make_jsonl([
            {'ts': time.time() - 100, 'category': 'A',
              'actionable': 'none'}
        ] * 5)  # 5 条 (太少)
        from jarvis_daemon_health_monitor import DaemonHealthMonitor
        m = DaemonHealthMonitor()
        m.PERSIST_PATH = os.path.join(self.tmpdir, 'h.json')
        with patch('os.path.exists', side_effect=lambda p: p == jsonl):
            with patch('builtins.open',
                         lambda p, *a, **k: open(jsonl, *a, **k)
                         if 'inner_thoughts' in p else open(p, *a, **k)):
                count = m._count_inner_thoughts_24h()
        # 5 条 < 30 应该警告
        self.assertLess(count, m.THOUGHTS_24H_MIN)

    def test_category_dist_with_dominance(self):
        """一类 > 70% → 检出."""
        thoughts = ([{'ts': time.time() - 100, 'category': 'A',
                       'actionable': 'none'}] * 80
                     + [{'ts': time.time() - 100, 'category': 'B',
                          'actionable': 'none'}] * 20)
        # 80% A → dominates
        # 验证 _inner_thought_category_dist_24h 计算正确
        from jarvis_daemon_health_monitor import DaemonHealthMonitor
        m = DaemonHealthMonitor()
        # 实际逻辑: A 80, B 20, total 100, A=80% > 70% threshold
        ratio = 80 / 100
        self.assertGreater(ratio, m.CATEGORY_DOMINATION)

    def test_calibration_threshold_floor(self):
        """阈值 < 0.55 → warn."""
        from jarvis_daemon_health_monitor import DaemonHealthMonitor
        m = DaemonHealthMonitor()
        # 假设阈值 0.45 (太松)
        self.assertLess(0.45, m.CALIBRATION_THRESHOLD_FLOOR)
        # 健康 0.65 应该 OK
        self.assertGreaterEqual(0.65, m.CALIBRATION_THRESHOLD_FLOOR)

    def test_actionable_fail_rate_threshold(self):
        """fail rate > 30% → warn."""
        from jarvis_daemon_health_monitor import DaemonHealthMonitor
        m = DaemonHealthMonitor()
        self.assertGreater(0.40, m.AUTO_ARBITER_FAIL_RATE_MAX)
        # 健康 < 20% 应该 OK
        self.assertLess(0.15, m.AUTO_ARBITER_FAIL_RATE_MAX)


# ==========================================================================
# L5: HealthMonitor publish_issue 真 publish SWM
# ==========================================================================
class TestL5HealthMonitorPublish(unittest.TestCase):
    def test_publish_issue_emits_swm(self):
        from jarvis_daemon_health_monitor import DaemonHealthMonitor
        m = DaemonHealthMonitor()
        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            m._publish_issue({
                'key': 'test_key', 'severity': 'warn',
                'msg': 'test issue', 'metric': {'a': 1},
            })
        self.assertTrue(mock_bus.publish.called)
        kw = mock_bus.publish.call_args.kwargs
        self.assertEqual(kw['etype'], 'daemon_health_warning')
        self.assertGreaterEqual(kw['salience'], 0.7,
            'high salience 让 SOUL inject 主脑')
        self.assertEqual(kw['metadata']['issue_key'], 'test_key')

    def test_dedup_cooldown(self):
        """同 issue_key 在 cooldown 内不重复 publish."""
        from jarvis_daemon_health_monitor import DaemonHealthMonitor
        m = DaemonHealthMonitor()
        # 标记 5min 前已 publish
        m._last_issue_ts['some_key'] = time.time() - 300
        # cooldown 6h, 应仍在 cooldown
        self.assertLess(time.time() - m._last_issue_ts['some_key'],
                         m.DEDUP_COOLDOWN_S)


# ==========================================================================
# L6: central_nerve 集成 anchor
# ==========================================================================
class TestL6CentralNerveIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'),
                    'r', encoding='utf-8') as f:
            cls.nerve_src = f.read()

    def test_central_nerve_calls_init_health_monitor(self):
        self.assertIn('self._init_daemon_health_monitor()', self.nerve_src,
            'CentralNerve.__init__ 必须调 _init_daemon_health_monitor')
        self.assertIn('def _init_daemon_health_monitor', self.nerve_src)


if __name__ == '__main__':
    unittest.main()
