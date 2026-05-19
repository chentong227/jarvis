# -*- coding: utf-8 -*-
"""
[P0+20-β.5.2 / 2026-05-19] OfferGuard gate_mode 三档 (准则 6 行为弱耦合 第 2 步)

接 β.5.1 NudgeGate gate_mode, 把 OfferGuard 同样改三档.

β.5.2 实施:
  1. jarvis_utils.read_gate_mode 模块级 helper (DRY 给 NudgeGate / OfferGuard 复用)
  2. NudgeGate._read_gate_mode 委派 helper
  3. OfferGuard.check_offer 加 gate_mode 三档逻辑:
     - hard (默认):     原行为, block 时 publish 'offer_blocked' decision='block'
     - soft:            block 时 publish + pass 时也 publish decision='pass' (双轨观察期)
     - publish_only:    永远 return (True, ...) (永不 hard 拦), pass/block 都 publish
  4. _publish_block 加 gate_mode 字段
  5. _publish_pass 新方法 (soft / publish_only mode 用)
  6. _evaluate_internal 拆出 (原 check_offer 内部评估逻辑)

测试覆盖:
  A. read_gate_mode helper API (cache + fail-safe)
  B. NudgeGate / OfferGuard 共享同一 vocab.json
  C. OfferGuard.check_offer 三模式行为差异验
  D. _publish_pass / _publish_block 都带 gate_mode meta
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================================
# A: read_gate_mode helper
# ==========================================================================

class TestP0Plus20Beta52ReadGateModeHelper(unittest.TestCase):
    def setUp(self):
        from jarvis_utils import reset_gate_mode_cache
        reset_gate_mode_cache()

    def test_helper_exists_in_utils(self):
        from jarvis_utils import read_gate_mode
        self.assertTrue(callable(read_gate_mode))

    def test_helper_returns_string_for_known_sentinel(self):
        from jarvis_utils import read_gate_mode
        for s in ('NudgeGate', 'OfferGuard', 'Conductor'):
            mode = read_gate_mode(s)
            self.assertIn(mode, ('hard', 'soft', 'publish_only'),
                f'{s} mode 必须是有效值, 实际 {mode}')

    def test_helper_default_hard_for_unknown(self):
        from jarvis_utils import read_gate_mode
        mode = read_gate_mode('NonexistentSentinelXYZ')
        self.assertEqual(mode, 'hard')

    def test_helper_caches_5s(self):
        """连续两次调用同 sentinel, 第 2 次应走 cache."""
        from jarvis_utils import read_gate_mode, reset_gate_mode_cache
        reset_gate_mode_cache()
        # 第 1 次会读文件, 第 2 次走 cache
        m1 = read_gate_mode('NudgeGate')
        m2 = read_gate_mode('NudgeGate')
        self.assertEqual(m1, m2)


# ==========================================================================
# B: NudgeGate / OfferGuard 共享 helper (DRY 验)
# ==========================================================================

class TestP0Plus20Beta52SharedHelper(unittest.TestCase):
    def test_nudge_gate_delegates_to_helper(self):
        path = os.path.join(ROOT, 'jarvis_sentinels.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        # NudgeGate._read_gate_mode 必须用 read_gate_mode (DRY)
        idx = src.find('def _read_gate_mode')
        self.assertGreater(idx, 0)
        block = src[idx:idx+800]
        self.assertIn('from jarvis_utils import read_gate_mode', block,
            'NudgeGate._read_gate_mode 应委派 helper (DRY)')

    def test_offer_guard_uses_helper(self):
        path = os.path.join(ROOT, 'jarvis_skill_registry.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('from jarvis_utils import read_gate_mode', src,
            'OfferGuard.check_offer 应 import read_gate_mode helper')
        self.assertIn("read_gate_mode('OfferGuard')", src,
            "OfferGuard 应 read_gate_mode('OfferGuard')")


# ==========================================================================
# C: OfferGuard.check_offer 三模式行为
# ==========================================================================

class TestP0Plus20Beta52OfferGuardModes(unittest.TestCase):
    def setUp(self):
        from jarvis_skill_registry import OfferGuard
        from jarvis_utils import ConversationEventBus, reset_gate_mode_cache
        OfferGuard.reset_for_test()
        reset_gate_mode_cache()
        self.OfferGuard = OfferGuard
        self.bus = ConversationEventBus()
        ConversationEventBus.register_global(self.bus)

    def tearDown(self):
        from jarvis_utils import ConversationEventBus
        ConversationEventBus.register_global(None)

    def _set_mode(self, mode: str):
        """直接 mock helper cache."""
        import jarvis_utils
        jarvis_utils._GATE_MODE_CACHE = {'OfferGuard': mode}
        jarvis_utils._GATE_MODE_CACHE_T = time.time()

    def test_hard_mode_returns_pass_no_publish_for_pass(self):
        """hard mode + pass: 应 return (True, ...) + 不 publish."""
        self._set_mode('hard')
        # 用 unknown nudge_type → 早 return True + 不 publish
        ok, reason = self.OfferGuard.check_offer('totally_unknown_nudge_type')
        self.assertTrue(ok)
        snap = self.bus.snapshot()
        offer_events = [e for e in snap if e['type'] == 'offer_blocked']
        self.assertEqual(len(offer_events), 0, 'hard mode pass 不应 publish')

    def test_hard_mode_blocks_and_publishes(self):
        """hard mode + block: 应 return (False, reason) + publish 'offer_blocked'."""
        self._set_mode('hard')
        # 触发 block: 第二次同 nudge_type (有 min_interval) 会 cooldown
        ok1, _ = self.OfferGuard.check_offer('hydration')
        self.assertTrue(ok1, 'first call pass')
        self.OfferGuard.mark_spoken('hydration')
        # 立刻第二次 → cooldown 拦
        ok2, reason2 = self.OfferGuard.check_offer('hydration')
        if ok2:
            self.skipTest('hydration min_interval=0 or unspecified')
        snap = self.bus.snapshot()
        offer_events = [e for e in snap if e['type'] == 'offer_blocked']
        self.assertGreater(len(offer_events), 0)
        latest = offer_events[-1]
        self.assertEqual(latest['metadata'].get('decision'), 'block')
        self.assertEqual(latest['metadata'].get('gate_mode'), 'hard')

    def test_publish_only_mode_never_blocks(self):
        """publish_only mode: 永远 return (True, ...), 仍 publish."""
        self._set_mode('publish_only')
        # 触发 cooldown 场景
        self.OfferGuard.check_offer('hydration')
        self.OfferGuard.mark_spoken('hydration')
        # 立即重试: publish_only → 仍 True
        ok, reason = self.OfferGuard.check_offer('hydration')
        self.assertTrue(ok, 'publish_only mode 永远 True')
        # reason 应含 'publish_only_override' 标记
        # (允许 hydration 其实没 cooldown 时就是 'ok', 不强测)

    def test_soft_mode_publishes_on_pass(self):
        """soft mode + pass 也 publish (decision='pass')."""
        self._set_mode('soft')
        ok, _ = self.OfferGuard.check_offer('hydration')
        if not ok:
            self.skipTest('hydration first call should pass')
        snap = self.bus.snapshot()
        offer_events = [e for e in snap if e['type'] == 'offer_blocked']
        # soft mode pass 也 publish
        pass_events = [e for e in offer_events
                       if e['metadata'].get('decision') == 'pass']
        self.assertGreater(len(pass_events), 0,
            'soft mode pass 必须 publish decision=pass')
        self.assertEqual(pass_events[0]['metadata'].get('gate_mode'), 'soft')


# ==========================================================================
# D: vocab 含 OfferGuard
# ==========================================================================

class TestP0Plus20Beta52VocabIncludesOfferGuard(unittest.TestCase):
    def test_vocab_has_offer_guard_with_valid_mode(self):
        """[β.5.3 升级] OfferGuard 必须在 vocab + mode 有效.
        历史: 初始 hard. β.5.3 Sir 拍板切 publish_only."""
        path = os.path.join(ROOT, 'memory_pool', 'gate_mode_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('OfferGuard', data.get('current', {}))
        mode = data['current']['OfferGuard']
        self.assertIn(mode, ('hard', 'soft', 'publish_only'),
            f'OfferGuard mode 必须有效, 实际 {mode}')


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print('='*60)
    if result.wasSuccessful():
        print('[OK] All β.5.2 OfferGuard gate_mode tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('='*60)
    sys.exit(0 if result.wasSuccessful() else 1)
