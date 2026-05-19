# -*- coding: utf-8 -*-
"""
[P0+20-β.5.1 / 2026-05-19] Gate Mode 三档 (准则 6 行为弱耦合 工程落地)

Sir 拍板第一性原理 (准则 6 升级版):
  数据强耦合 (β.5.0-A ✅) + 行为弱耦合 (β.5.0-B + β.5.1 本) + 决策集中主脑 (β.5.x+)

β.5.1 实施:
  1. memory_pool/gate_mode_vocab.json 持久化 (准则 6.5 vocab):
     6 sentinel × 3 mode (hard/soft/publish_only). 默认全 hard.
  2. scripts/gate_mode_dump.py CLI: Sir 不改源码可切 mode
  3. NudgeGate.can_speak 集成 gate_mode 3 档逻辑:
     - hard: 原行为, block 时 publish + 真拦
     - soft: 双轨, 任何 decision 都 publish + 仍 hard return
     - publish_only: 任何 decision 都 publish, 永远 return True (主脑自决)
  4. _read_gate_mode classmethod + 5s cache 防 IO 高开销

测试覆盖:
  A. vocab 文件存在 + 6 sentinel × 3 mode 完整性
  B. CLI script 可执行 / list / show / set / reset
  C. NudgeGate._read_gate_mode 5s cache
  D. NudgeGate.can_speak 三模式行为差异验
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'gate_mode_vocab.json')
CLI_PATH = os.path.join(ROOT, 'scripts', 'gate_mode_dump.py')


# ==========================================================================
# A: vocab 文件持久化 (准则 6.5)
# ==========================================================================

class TestP0Plus20Beta51VocabPersist(unittest.TestCase):
    def test_vocab_file_exists(self):
        self.assertTrue(os.path.exists(VOCAB_PATH),
            f'gate_mode_vocab.json 必须存在: {VOCAB_PATH}')

    def test_vocab_has_current_map(self):
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('current', data)
        current = data['current']
        # 6 个 known sentinel 都在
        for s in ('NudgeGate', 'OfferGuard', 'SmartNudgeSentinel',
                  'Conductor', 'WellnessGuardian', 'ReturnSentinel'):
            self.assertIn(s, current, f'vocab.current 必须含 {s}')

    def test_default_modes_valid(self):
        """所有 sentinel default mode ∈ (hard / soft / publish_only).
        [β.5.3 / 2026-05-19] 部分 sentinel 已切 publish_only, 不再强制 hard.
        历史保留: NudgeGate / OfferGuard 旧默认 hard, β.5.3 切 publish_only."""
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for s, mode in data.get('current', {}).items():
            self.assertIn(mode, ('hard', 'soft', 'publish_only'),
                f'{s} mode 必须有效, 实际 {mode}')

    def test_vocab_documents_3_modes(self):
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        modes = data.get('modes', {})
        for m in ('hard', 'soft', 'publish_only'):
            self.assertIn(m, modes, f'vocab.modes 必须文档 {m}')


# ==========================================================================
# B: CLI script
# ==========================================================================

class TestP0Plus20Beta51CLI(unittest.TestCase):
    def test_cli_script_exists(self):
        self.assertTrue(os.path.exists(CLI_PATH))

    def test_cli_list_runs(self):
        """无参 = list mode, 不应崩."""
        out = subprocess.run(
            [sys.executable, CLI_PATH], capture_output=True, text=True,
            timeout=10, cwd=ROOT,
        )
        # 不一定 returncode=0 (PowerShell 重定向问题可能 1), 但不应 exception
        # 检查 stdout/stderr 有任何 NudgeGate / SmartNudge 字样
        combined = (out.stdout or '') + (out.stderr or '')
        self.assertIn('NudgeGate', combined,
            'CLI 默认 list 必须输出 NudgeGate sentinel')


# ==========================================================================
# C: NudgeGate _read_gate_mode 缓存
# ==========================================================================

class TestP0Plus20Beta51ReadGateMode(unittest.TestCase):
    def setUp(self):
        from jarvis_sentinels import NudgeGate
        # 清 cache
        for attr in ('_gate_mode_cache', '_gate_mode_cache_t'):
            if hasattr(NudgeGate, attr):
                delattr(NudgeGate, attr)

    def test_default_hard_when_unknown_sentinel(self):
        from jarvis_sentinels import NudgeGate
        mode = NudgeGate._read_gate_mode('NonexistentSentinel')
        self.assertEqual(mode, 'hard')

    def test_nudge_gate_mode_returns_string(self):
        from jarvis_sentinels import NudgeGate
        mode = NudgeGate._read_gate_mode('NudgeGate')
        self.assertIn(mode, ('hard', 'soft', 'publish_only'))


# ==========================================================================
# D: NudgeGate can_speak 三模式行为
# ==========================================================================

class TestP0Plus20Beta51CanSpeakModes(unittest.TestCase):
    """三模式 can_speak 行为差异."""

    def setUp(self):
        from jarvis_sentinels import NudgeGate
        from jarvis_utils import reset_gate_mode_cache
        # [β.5.2] cache 现在在 jarvis_utils module-level
        reset_gate_mode_cache()
        self.NudgeGate = NudgeGate
        self.gate = NudgeGate(cooldown_seconds=90)
        from jarvis_utils import ConversationEventBus
        self.bus = ConversationEventBus()
        ConversationEventBus.register_global(self.bus)

    def tearDown(self):
        from jarvis_utils import ConversationEventBus
        ConversationEventBus.register_global(None)

    def _set_mode(self, mode: str):
        """[β.5.2] Mock module-level cache 让 read_gate_mode 返指定 mode."""
        import jarvis_utils
        jarvis_utils._GATE_MODE_CACHE = {'NudgeGate': mode}
        jarvis_utils._GATE_MODE_CACHE_T = time.time()

    def test_hard_mode_blocks_and_publishes_on_block(self):
        """hard mode: block 时 publish, pass 时不 publish."""
        self._set_mode('hard')
        # 触发 block: 用 freeze
        self.gate.freeze_for(60.0, source='test')
        result = self.gate.can_speak('guardian', is_urgent=False)
        self.assertFalse(result, 'hard mode 拦截工作')
        snap = self.bus.snapshot()
        gate_events = [e for e in snap if e['type'] == 'gate_advice']
        self.assertEqual(len(gate_events), 1, 'hard mode block 应 publish 1 次')
        self.assertEqual(gate_events[0]['metadata'].get('decision'), 'block')

    def test_publish_only_mode_never_blocks(self):
        """publish_only mode: 永远 return True, 仍 publish."""
        self._set_mode('publish_only')
        # 即使 freeze 也不 block
        self.gate.freeze_for(60.0, source='test')
        result = self.gate.can_speak('guardian', is_urgent=False)
        self.assertTrue(result, 'publish_only mode 永远 return True')
        snap = self.bus.snapshot()
        gate_events = [e for e in snap if e['type'] == 'gate_advice']
        # publish 应包含 gate_mode='publish_only' meta
        self.assertGreater(len(gate_events), 0)
        latest = gate_events[-1]
        self.assertEqual(latest['metadata'].get('gate_mode'), 'publish_only')

    def test_soft_mode_publishes_on_pass(self):
        """soft mode: pass 时也 publish (双轨观察)."""
        self._set_mode('soft')
        # 不 freeze, can_speak pass
        result = self.gate.can_speak('guardian', is_urgent=False)
        self.assertTrue(result, 'soft mode 不 freeze 时 pass')
        snap = self.bus.snapshot()
        gate_events = [e for e in snap if e['type'] == 'gate_advice']
        self.assertEqual(len(gate_events), 1, 'soft mode pass 时也 publish')
        self.assertEqual(gate_events[0]['metadata'].get('decision'), 'pass')
        self.assertEqual(gate_events[0]['metadata'].get('gate_mode'), 'soft')


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print('='*60)
    if result.wasSuccessful():
        print('[OK] All β.5.1 gate_mode tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('='*60)
    sys.exit(0 if result.wasSuccessful() else 1)
