# -*- coding: utf-8 -*-
"""
[P0+20-β.5.18 / 2026-05-19] publish_only override 不绕 hard_freeze (准则 5 言出必行)

发现 (大任务排查) - 跑全 119 测发现 _test_p2_refusal_and_audio.py
TestNudgeGateHardFreeze 4 fail - β.5.16 后 publish_only 真生效, NudgeGate.can_speak
永远 return True 把 Sir 显式 freeze_for(180/300/600) 也 override 了. 违反准则 5
言出必行 - Sir 说"急停" / "拒绝" / "告别" 后, Jarvis 不该再说话, 即便主脑想说.

修法 (jarvis_sentinels.py:849-852):
  if gate_mode == 'publish_only':
      if state_meta.get('freeze_active'):
          return False  # hard_freeze 永远拦
      return True

主脑 SWM 仍能通过 gate_advice metadata.freeze_active=True 看到状态自决不说.
设计上 - publish_only 是行为弱耦合, hard_freeze 是用户硬规拒绝 (不弱).

测试覆盖:
  A. publish_only 模式下 freeze_for(60) 让 can_speak 返 False (即使 is_urgent=True)
  B. freeze 过期后 can_speak 恢复 True (publish_only)
  C. 老测试 (TestNudgeGateHardFreeze 4 测) 全过
  D. publish_only 非 freeze 状态仍永真 (β.5.3 行为不破)
  E. β.5.18 marker comment 持久化
"""

from __future__ import annotations

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


class TestBeta518FreezeHardLock(unittest.TestCase):
    def setUp(self):
        from jarvis_nerve import NudgeGate
        import jarvis_utils as u
        u.reset_gate_mode_cache()
        self.gate = NudgeGate(cooldown_seconds=90)

    def test_freeze_blocks_in_publish_only_mode(self):
        """publish_only 模式下 freeze_for(60) 必须仍拦住."""
        import jarvis_utils as u
        # 前置: NudgeGate vocab 必须是 publish_only (β.5.x 默认)
        self.assertEqual(u.read_gate_mode('NudgeGate'), 'publish_only',
            'NudgeGate 必须配 publish_only 才能验证 β.5.18 修复')
        self.gate.freeze_for(60.0, source='user_rejection')
        self.assertFalse(self.gate.can_speak('guardian', is_urgent=False),
            'publish_only + freeze_active → 必须 False (β.5.18 准则 5 言出必行)')

    def test_freeze_blocks_urgent_in_publish_only(self):
        """publish_only + freeze 即使 is_urgent=True 也必须拦."""
        self.gate.freeze_for(60.0, source='user_emergency_stop')
        self.assertFalse(self.gate.can_speak('conductor', is_urgent=True),
            'publish_only + freeze + urgent → 仍 False (Sir 急停硬规)')

    def test_publish_only_allows_when_no_freeze(self):
        """publish_only 模式下没 freeze 时仍永真 (β.5.3 行为不破)."""
        # 不调 freeze_for, 直接 can_speak
        result = self.gate.can_speak('guardian', is_urgent=False)
        self.assertTrue(result,
            'publish_only 无 freeze 状态必须永真 (β.5.3 设计不破)')

    def test_freeze_expires_publish_only_resumes(self):
        """freeze 过期后 publish_only 恢复永真."""
        self.gate.freeze_for(0.05, source='test')  # 50ms
        self.assertFalse(self.gate.can_speak('guardian'),
            'freeze 期间应拦')
        time.sleep(0.1)
        self.assertTrue(self.gate.can_speak('guardian'),
            'freeze 过期后 publish_only 恢复永真')


class TestBeta518MarkerComment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_sentinels.py'))

    def test_marker_present(self):
        self.assertIn('β.5.18', self.src,
            'β.5.18 marker 必须在 jarvis_sentinels.py')

    def test_freeze_check_in_publish_only_branch(self):
        """publish_only 分支必须先 check freeze_active."""
        # 找 publish_only 分支
        idx = self.src.find("if gate_mode == 'publish_only':")
        # NudgeGate.can_speak 的 publish_only 分支应有 freeze_active 检查
        # (找 β.5.18 marker 附近的 publish_only)
        marker_idx = self.src.find('β.5.18')
        self.assertGreater(marker_idx, 0)
        block = self.src[marker_idx:marker_idx + 600]
        self.assertIn("freeze_active", block,
            'β.5.18 修复必须 check state_meta.freeze_active')
        self.assertIn("return False", block,
            'β.5.18 修复 freeze_active 时返 False')


if __name__ == '__main__':
    unittest.main()
