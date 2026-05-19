# -*- coding: utf-8 -*-
"""
[P0+20-β.5.14 / 2026-05-19] β.5 重构收尾 — WellnessGuardian publish_skip 补齐

Sir 21:48 提问 "把 5 层后面的都接入 LLM 怎么样" 准则 6 数据强耦合彻底落地.

实际状态 (本轮调研):
  - SmartNudge:     ✓ β.5.6 完成 (publish_skip + dedupe)
  - ReturnSentinel: ✓ β.5.5 完成 (publish_skip + dedupe)
  - Conductor:      ✓ β.5.4 完成 (publish gate_advice on inter_source_cooldown)
  - WellnessGuardian: ❌ 缺 — β.5.14 本轮补

修法:
  1. WellnessGuardian.__init__ 加 _skip_publish_last_t dedupe map
  2. WellnessGuardian._publish_skip helper (sal=0.15 不污染主脑 evidence 默认 render)
  3. run() 3 处 skip (cooldown / daily_quota / AFK) 都调 _publish_skip

测试覆盖:
  A. _publish_skip helper 存在 + 调用 event_bus.publish + sal=0.15
  B. dedupe: 同 reason 60s 内只 publish 1 次
  C. 3 处 skip 路径都调 _publish_skip (字面 marker check)
  D. _skip_publish_last_t 实例字段存在 + GC 5min 以前
  E. publish 出来的 source='WellnessGuardian' / etype='gate_advice'
"""

from __future__ import annotations

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


# ==========================================================================
# A: _publish_skip helper 存在 + 调用 event_bus + sal=0.15
# ==========================================================================

class TestBeta514PublishSkipHelper(unittest.TestCase):
    """WellnessGuardian._publish_skip 行为正确."""

    def setUp(self):
        from jarvis_sentinels import WellnessGuardian
        # 用 __new__ 跳过 Thread.__init__ 避免 daemon 真启动
        self.wg = WellnessGuardian.__new__(WellnessGuardian)
        self.wg._skip_publish_last_t = {}

    def test_helper_method_exists(self):
        self.assertTrue(hasattr(self.wg, '_publish_skip'),
            'WellnessGuardian 必须有 _publish_skip 方法 (β.5.14)')

    def test_publish_skip_calls_event_bus(self):
        """_publish_skip 触发 event_bus.publish 一次."""
        with patch('jarvis_utils.get_event_bus') as mock_get:
            mock_bus = MagicMock()
            mock_get.return_value = mock_bus
            self.wg._publish_skip('test_reason', {'foo': 'bar'})
            mock_bus.publish.assert_called_once()
            call_kwargs = mock_bus.publish.call_args.kwargs
            self.assertEqual(call_kwargs.get('etype'), 'gate_advice')
            self.assertEqual(call_kwargs.get('source'), 'WellnessGuardian')
            self.assertIn('test_reason', call_kwargs.get('description', ''))
            meta = call_kwargs.get('metadata', {})
            self.assertEqual(meta.get('decision'), 'block')
            self.assertEqual(meta.get('block_reason'), 'test_reason')
            self.assertEqual(meta.get('foo'), 'bar')

    def test_publish_salience_below_render_floor(self):
        """sal=0.15 < 0.3 默认 SWM render floor — 不污染主脑视图."""
        with patch('jarvis_utils.get_event_bus') as mock_get:
            mock_bus = MagicMock()
            mock_get.return_value = mock_bus
            self.wg._publish_skip('low_sal_test')
            call_kwargs = mock_bus.publish.call_args.kwargs
            self.assertLess(call_kwargs.get('salience', 1.0), 0.3,
                'WellnessGuardian skip salience 必须 < 0.3 (不污染主脑 evidence)')
            self.assertEqual(call_kwargs.get('salience'), 0.15)

    def test_publish_no_bus_silent_fail(self):
        """get_event_bus 返 None 不 raise."""
        with patch('jarvis_utils.get_event_bus') as mock_get:
            mock_get.return_value = None
            try:
                self.wg._publish_skip('no_bus_test')
            except Exception as e:
                self.fail(f'_publish_skip 应 fail-safe, 实际 raise: {e}')


# ==========================================================================
# B: dedupe — 同 reason 60s 内只 publish 1 次
# ==========================================================================

class TestBeta514PublishSkipDedupe(unittest.TestCase):
    """同 reason 60s 内 dedupe (防 SWM 堆爆)."""

    def setUp(self):
        from jarvis_sentinels import WellnessGuardian
        self.wg = WellnessGuardian.__new__(WellnessGuardian)
        self.wg._skip_publish_last_t = {}

    def test_dedupe_within_60s(self):
        """同 reason 连 publish 2 次, event_bus.publish 只调 1 次."""
        with patch('jarvis_utils.get_event_bus') as mock_get:
            mock_bus = MagicMock()
            mock_get.return_value = mock_bus
            self.wg._publish_skip('dup_reason')
            self.wg._publish_skip('dup_reason')  # 60s 内重复
            self.assertEqual(mock_bus.publish.call_count, 1,
                'dedupe 失效: 同 reason 60s 内应只 publish 1 次')

    def test_different_reasons_both_publish(self):
        """不同 reason 不 dedupe."""
        with patch('jarvis_utils.get_event_bus') as mock_get:
            mock_bus = MagicMock()
            mock_get.return_value = mock_bus
            self.wg._publish_skip('r1')
            self.wg._publish_skip('r2')
            self.assertEqual(mock_bus.publish.call_count, 2,
                '不同 reason 应都 publish')

    def test_dedupe_expires_after_60s(self):
        """fake 时钟前进 60s 后, 同 reason 可再 publish."""
        with patch('jarvis_utils.get_event_bus') as mock_get:
            mock_bus = MagicMock()
            mock_get.return_value = mock_bus
            # 第一次
            with patch('time.time', return_value=1000.0):
                self.wg._publish_skip('expiry_reason')
            # 60s 内第二次 (应被 dedupe)
            with patch('time.time', return_value=1030.0):
                self.wg._publish_skip('expiry_reason')
            # 60s 后第三次 (应放过)
            with patch('time.time', return_value=1100.0):
                self.wg._publish_skip('expiry_reason')
            self.assertEqual(mock_bus.publish.call_count, 2,
                'dedupe 60s expire 后同 reason 应能再 publish')


# ==========================================================================
# C: src 字面 marker — 3 处 skip 都调 _publish_skip
# ==========================================================================

class TestBeta514SrcMarkers(unittest.TestCase):
    """src 字面 check: 3 处 skip 路径都接入了 _publish_skip."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_sentinels.py'))

    def test_marker_present(self):
        self.assertIn('β.5.14', self.src,
            'β.5.14 marker 必须在 jarvis_sentinels.py')

    def test_init_dedupe_map(self):
        self.assertIn('self._skip_publish_last_t = {}', self.src,
            'WellnessGuardian.__init__ 必须 init _skip_publish_last_t')

    def test_cooldown_skip_publishes(self):
        """cooldown skip 路径调 _publish_skip."""
        self.assertIn("self._publish_skip(f'cooldown_", self.src,
            'cooldown skip 必须调 _publish_skip')

    def test_daily_quota_skip_publishes(self):
        self.assertIn("self._publish_skip('daily_quota_exhausted'", self.src,
            'daily_quota skip 必须调 _publish_skip')

    def test_afk_skip_publishes(self):
        self.assertIn("self._publish_skip('afk_not_at_screen'", self.src,
            'AFK skip 必须调 _publish_skip')

    def test_publish_skip_helper_def(self):
        self.assertIn('def _publish_skip(self, skip_reason: str', self.src,
            '_publish_skip 方法签名必须存在')


# ==========================================================================
# D: 4 sentinel 收尾验证 (关联性 check)
# ==========================================================================

class TestBeta514FourSentinelsCovered(unittest.TestCase):
    """β.5.14 验收: SmartNudge / ReturnSentinel / Conductor / WellnessGuardian
    4 个 sentinel 全部有 publish skip 信号路径."""

    def test_smart_nudge_has_publish_skip(self):
        src = _read(os.path.join(ROOT, 'jarvis_smart_nudge.py'))
        self.assertIn('_publish_skip', src,
            'SmartNudge 必须有 _publish_skip (β.5.6)')

    def test_return_sentinel_has_publish_skip(self):
        src = _read(os.path.join(ROOT, 'jarvis_return_sentinel.py'))
        self.assertIn('_publish_skip', src,
            'ReturnSentinel 必须有 _publish_skip (β.5.5)')

    def test_conductor_publishes_gate_advice(self):
        src = _read(os.path.join(ROOT, 'jarvis_conductor.py'))
        self.assertIn("etype='gate_advice'", src,
            'Conductor 必须 publish gate_advice (β.5.4)')
        self.assertIn("source='Conductor'", src,
            'Conductor publish source 必须是 Conductor')

    def test_wellness_guardian_has_publish_skip(self):
        src = _read(os.path.join(ROOT, 'jarvis_sentinels.py'))
        # WellnessGuardian _publish_skip 在 β.5.14 才补
        idx = src.find('class WellnessGuardian')
        self.assertGreater(idx, 0)
        # 找 class 结束 (下一个 class)
        next_class = src.find('\nclass ', idx + 10)
        wg_block = src[idx:next_class] if next_class > 0 else src[idx:]
        self.assertIn('_publish_skip', wg_block,
            'WellnessGuardian 必须有 _publish_skip (β.5.14)')


if __name__ == '__main__':
    unittest.main()
