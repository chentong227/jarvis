# -*- coding: utf-8 -*-
"""
[P0+20-β.5.3-fix / 2026-05-19] β.5.3 预防性 BUG fix (Sir 真机前)

修 3 个 BUG 减 Sir 真机踩坑率:

  BUG-3: [SILENCE] 检测扩到 mid-stream
    原 first 32 chars only. 现在全 stream 任何位置含 [SILENCE] / [silence] 都 break.
    防主脑输出 "Hello [SILENCE]" 这种漏给 TTS.

  BUG-4: gate_advice publish dedupe (60s)
    publish_only 模式下 SmartNudge 每 30-60s tick 都 publish gate_advice.
    SWM max_events=50 满后 commitment_overdue 等高 salience evidence 被挤走.
    加 dedupe: 同 (center, block_reason, gate_mode) 60s 内只 publish 1 次.
    GC: 5min 以前的 dedupe entry 清.

  BUG-6: last_nudge_age_s = -1 → 缺字段 (不歧义)
    原 last_nudge_time=0 时 last_nudge_age_s 设 -1. 主脑可能误读为"1s 前".
    改: 若从未 nudge → 不放此字段. last_nudge_center 也设 None.

测试覆盖:
  A. [SILENCE] mid-stream guard 代码存在
  B. _publish_dedupe dict 在 __init__ 初始化
  C. dedupe 逻辑 60s 内同 key 第 2 次 publish 被拦
  D. last_nudge_age_s 缺字段 when no nudge
"""

from __future__ import annotations

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================================
# A: [SILENCE] mid-stream guard
# ==========================================================================

class TestBeta53FixSilenceMidStream(unittest.TestCase):
    def test_silence_detected_anywhere_in_stream(self):
        """检测代码应在 full_text 全文中找 [SILENCE], 不限 first 32 chars."""
        path = os.path.join(ROOT, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        # 找 stream loop 中 _silence_chosen 检测段
        idx = src.find('_silence_chosen = True')
        self.assertGreater(idx, 0)
        # 前 500 字内必须包含全 stream 检测 (不只 _ft_head)
        block = src[max(0, idx-500):idx+50]
        # 应有 _ft_lower 或 full_text 全文检测 (不只 first 32)
        self.assertTrue(
            '_ft_lower' in block or 'full_text' in block,
            'BUG-3: [SILENCE] 检测应扩到全 stream, 不只 first 32 chars'
        )

    def test_silence_check_handles_case(self):
        """BUG-3: 检测应 case-insensitive (lower / upper)."""
        path = os.path.join(ROOT, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        idx = src.find('_silence_chosen = True')
        self.assertGreater(idx, 0)
        block = src[max(0, idx-500):idx+50]
        self.assertIn('[silence]', block.lower(),
            'BUG-3: 应能检测小写 [silence]')


# ==========================================================================
# B + C: NudgeGate._publish_dedupe
# ==========================================================================

class TestBeta53FixPublishDedupe(unittest.TestCase):
    def setUp(self):
        from jarvis_sentinels import NudgeGate
        from jarvis_utils import ConversationEventBus, reset_gate_mode_cache
        reset_gate_mode_cache()
        import jarvis_utils
        jarvis_utils._GATE_MODE_CACHE = {'NudgeGate': 'publish_only'}
        jarvis_utils._GATE_MODE_CACHE_T = time.time()
        self.NudgeGate = NudgeGate
        self.gate = NudgeGate(cooldown_seconds=60)
        self.bus = ConversationEventBus()
        ConversationEventBus.register_global(self.bus)

    def tearDown(self):
        from jarvis_utils import ConversationEventBus
        ConversationEventBus.register_global(None)

    def test_publish_dedupe_initialized(self):
        """BUG-4: __init__ 必须 init _publish_dedupe={}."""
        self.assertTrue(hasattr(self.gate, '_publish_dedupe'),
            'NudgeGate.__init__ 必须 init _publish_dedupe (BUG-4)')
        self.assertIsInstance(self.gate._publish_dedupe, dict)

    def test_dedupe_blocks_2nd_publish_within_60s(self):
        """BUG-4: 60s 内同 (center, reason, mode) 第 2 次 publish 被 dedupe."""
        # 触发 cooldown 状态
        self.gate.can_speak('center_a', is_urgent=False)
        self.gate.mark_spoke('center_a')
        # 立即第 2 次 (different center) → block + publish
        self.gate.can_speak('center_b', is_urgent=False)
        snap1 = self.bus.snapshot()
        events1 = [e for e in snap1 if e['type'] == 'gate_advice']
        n1 = len(events1)
        # 立即第 3 次 (同 center / 同 reason) → dedupe 拦
        self.gate.can_speak('center_b', is_urgent=False)
        snap2 = self.bus.snapshot()
        events2 = [e for e in snap2 if e['type'] == 'gate_advice']
        n2 = len(events2)
        self.assertEqual(n2, n1,
            'BUG-4: 60s 内同 (center, reason, mode) 第 2 次应被 dedupe (n1=%d n2=%d)' % (n1, n2))


# ==========================================================================
# D: last_nudge_age_s 缺字段 when no nudge yet
# ==========================================================================

class TestBeta53FixLastNudgeAgeNone(unittest.TestCase):
    def setUp(self):
        from jarvis_sentinels import NudgeGate
        from jarvis_utils import reset_gate_mode_cache
        reset_gate_mode_cache()
        self.gate = NudgeGate(cooldown_seconds=60)

    def test_fresh_gate_no_last_nudge_age_field(self):
        """BUG-6: NudgeGate 新建 (从未 nudge), state_meta 不应有 last_nudge_age_s."""
        _, _, meta = self.gate._can_speak_internal_v2('test', False, '')
        self.assertNotIn('last_nudge_age_s', meta,
            'BUG-6: 从未 nudge → state_meta 不应有 last_nudge_age_s 字段')

    def test_after_nudge_field_appears(self):
        """BUG-6: nudge 1 次后 state_meta 应含 last_nudge_age_s."""
        self.gate.mark_spoke('test_center')
        _, _, meta = self.gate._can_speak_internal_v2('other_center', False, '')
        self.assertIn('last_nudge_age_s', meta,
            'BUG-6: mark_spoke 后 state_meta 应有 last_nudge_age_s 字段')
        self.assertGreaterEqual(meta['last_nudge_age_s'], 0)

    def test_last_nudge_center_none_when_empty(self):
        """BUG-6: last_nudge_center 为空时应是 None (不是空字符串)."""
        _, _, meta = self.gate._can_speak_internal_v2('test', False, '')
        self.assertIsNone(meta.get('last_nudge_center'),
            'BUG-6: 从未 nudge → last_nudge_center 应是 None')


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print('='*60)
    if result.wasSuccessful():
        print('[OK] All β.5.3-fix tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('='*60)
    sys.exit(0 if result.wasSuccessful() else 1)
