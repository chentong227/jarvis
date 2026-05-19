# -*- coding: utf-8 -*-
"""
[P0+20-β.5.4 / 2026-05-19] Conductor publish-only signal (准则 6 数据强耦合扩展)

接 β.5.3 vocab default publish_only (NudgeGate / OfferGuard 已), β.5.4 让 Conductor
也开始 publish 它的"想 propose alert 但被拦"信号到 SWM, 主脑能看到完整 picture.

β.5.4 minimalist 实施 (不破 Conductor hardcoded INTER_SOURCE_COOLDOWN):
  - Conductor._check_path_a INTER_SOURCE_COOLDOWN 触发 + 有 pending alert →
    publish 'gate_advice' source='Conductor' 到 SWM
  - metadata: gap_s / cooldown_s / has_shield_alert / has_wellness_alert
  - decision='block' block_reason='inter_source_cooldown_Xs'
  - salience=0.5 (中等, 不抢 commitment_overdue)

主脑下次 prompt 看 SWM 会看到:
  - (sal=0.50, age=15s) gate_advice [Conductor]: Conductor would-propose alert
    but blocked: inter_source_cooldown_42s_after_last_nudge

测试覆盖:
  A. Conductor _check_path_a 含 publish 逻辑
  B. Conductor publish 用 etype='gate_advice' source='Conductor'
  C. metadata 含 cooldown / alert flag 字段
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestP0Plus20Beta54ConductorPublish(unittest.TestCase):
    def _src(self):
        path = os.path.join(ROOT, 'jarvis_conductor.py')
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_conductor_check_path_a_has_publish_block(self):
        src = self._src()
        idx = src.find('def _check_path_a')
        self.assertGreater(idx, 0)
        block = src[idx:idx+3500]
        self.assertIn("source='Conductor'", block,
            'Conductor _check_path_a 必须 publish source=Conductor (β.5.4)')

    def test_conductor_publish_uses_gate_advice_etype(self):
        src = self._src()
        idx = src.find('def _check_path_a')
        block = src[idx:idx+3500]
        self.assertIn("etype='gate_advice'", block,
            "Conductor publish 必须用 etype='gate_advice' (统一 SWM 渠道)")

    def test_conductor_publish_metadata_has_cooldown_fields(self):
        src = self._src()
        idx = src.find('def _check_path_a')
        block = src[idx:idx+3500]
        for field in ("'gap_s'", "'cooldown_s'", "'block_reason'",
                      "'has_shield_alert'", "'has_wellness_alert'"):
            self.assertIn(field, block,
                f"Conductor publish metadata 必须含 {field}")

    def test_conductor_publish_only_when_pending(self):
        """只在 pending alert (shield_alert.active OR wellness_alert.active) 时 publish.
        否则 cooldown 内 Conductor 啥也没 propose, publish 噪音."""
        src = self._src()
        idx = src.find('def _check_path_a')
        block = src[idx:idx+3500]
        # 应有 _has_pending 判断保护
        self.assertIn('_has_pending', block,
            "Conductor publish 应只在有 pending alert 时触发, 减 SWM 噪音")


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print('='*60)
    if result.wasSuccessful():
        print('[OK] All β.5.4 Conductor publish tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('='*60)
    sys.exit(0 if result.wasSuccessful() else 1)
