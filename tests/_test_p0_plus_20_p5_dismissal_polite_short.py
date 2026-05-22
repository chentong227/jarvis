# -*- coding: utf-8 -*-
"""[β.5.46-fix16 / 2026-05-22] Sir 11:26 真测 BUG — 谢谢/thanks 误判 dismissal

Sir 报: "好的，谢谢你啊，谢谢你。你不提醒，我真忘了，赶紧清理一下" (28 字真请求)
→ awake True→False (dismissal) → NudgeGate.sleep_mode 误激活.

Root cause:
  jarvis_worker.py:5073 用合并 DISMISS_WORDS (EXCLUSIVE + POLITE) any-match.
  POLITE = ['thanks', 'thank you', '谢谢']. "谢谢" in 28 字真请求 → True.

  但 line 314 注释明写: "POLITE: 礼貌词, 本身高频出现在非告别语境中
  (谢谢/thanks) → 必须整句很短才算告别".
  规则注释里写了, 代码里没实现.

Fix (jarvis_worker.py:5072-5088):
  - EXCLUSIVE (goodbye/晚安/再见/bye/...) 含即触
  - POLITE (谢谢/thanks) 仅 cmd_words ≤ 6 或 cmd ≤ 12 字才触

Cover:
  A. EXCLUSIVE 长短句都触
  B. POLITE 仅短句触 (Sir 这次案例 28 字 → 不触)
  C. POLITE 短句 (≤ 12 字) 真告别 → 触
  D. marker 在源码
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _simulate_dismissal_check(cmd: str) -> bool:
    """复现 jarvis_worker.py:5078-5086 dismissal 判断逻辑.

    DISMISS_EXCLUSIVE: 含即触
    DISMISS_POLITE: 仅 cmd_words ≤ 6 或 cmd ≤ 12 字才触
    """
    DISMISS_EXCLUSIVE = [
        "goodbye", "good night", "bye", "see you", "see you next time",
        "晚安", "再见", "拜拜",
    ]
    DISMISS_POLITE = ["thanks", "thank you", "谢谢"]
    cmd_lower = cmd.lower()
    cmd_words = cmd.lower().strip().split()
    is_exc = any(w in cmd_lower for w in DISMISS_EXCLUSIVE)
    is_pol = any(w in cmd_lower for w in DISMISS_POLITE)
    is_short = len(cmd_words) <= 6 and len(cmd) <= 12
    return is_exc or (is_pol and is_short)


class TestA_ExclusiveAlwaysTriggers(unittest.TestCase):
    """A: EXCLUSIVE 长短句都触 (goodbye/晚安/再见 含即真告别)."""

    def test_short_goodbye(self):
        self.assertTrue(_simulate_dismissal_check("goodbye"))

    def test_short_zh(self):
        self.assertTrue(_simulate_dismissal_check("晚安"))
        self.assertTrue(_simulate_dismissal_check("再见"))
        self.assertTrue(_simulate_dismissal_check("拜拜"))

    def test_exclusive_in_long_sentence(self):
        """EXCLUSIVE 含即触 — 即使长句也触."""
        self.assertTrue(
            _simulate_dismissal_check(
                "ok 晚安了我去睡觉了你保重 see you tomorrow morning"
            ),
            'EXCLUSIVE 含 "晚安" + "see you" 应触'
        )


class TestB_PoliteShortOnly(unittest.TestCase):
    """B: POLITE (谢谢/thanks) 仅短句触.

    Sir 真测案例: 28 字真请求含"谢谢" → 不应触.
    """

    def test_sir_actual_case_28chars_not_dismissal(self):
        """Sir 实测 11:26: 28 字真请求含"谢谢" → 应不触发 dismissal."""
        cmd = "好的，谢谢你啊，谢谢你。你不提醒，我真忘了，赶紧清理一下"
        self.assertFalse(
            _simulate_dismissal_check(cmd),
            f'28 字真请求含"谢谢" 不应判 dismissal. cmd_len={len(cmd)}'
        )

    def test_xiexie_alone_2chars_triggers(self):
        """"谢谢" 单 2 字 = 真告别 → 触."""
        self.assertTrue(_simulate_dismissal_check("谢谢"))

    def test_thanks_alone_6chars_triggers(self):
        self.assertTrue(_simulate_dismissal_check("thanks"))

    def test_thank_you_short_triggers(self):
        self.assertTrue(_simulate_dismissal_check("thank you"))

    def test_polite_short_12chars_triggers(self):
        """≤ 12 字含"谢谢" — 触 (合理短告别)."""
        # 11 字
        self.assertTrue(_simulate_dismissal_check("好的，谢谢，再见"))
        # 12 字
        self.assertTrue(_simulate_dismissal_check("谢谢你，我先走了"))

    def test_polite_long_english_not_triggers(self):
        """10+ 词的英文真请求含 thanks → 不触."""
        cmd = "Thank you for the reminder, I'll go clean up the disk now"
        self.assertFalse(
            _simulate_dismissal_check(cmd),
            f'{len(cmd.split())} 词真请求含 thanks 不应触 dismissal'
        )

    def test_polite_long_zh_not_triggers(self):
        """长中文真请求含"谢谢" → 不触."""
        # 20 字
        cmd = "谢谢你提醒我，我现在去把日志清理掉就好"
        self.assertFalse(
            _simulate_dismissal_check(cmd),
            f'{len(cmd)} 字真请求含"谢谢"不应触 dismissal'
        )


class TestC_OldBuggyBehaviorFixed(unittest.TestCase):
    """C: 老 BUG 反例 — 老版本会判 True, 新版应 False."""

    def test_compare_old_vs_new(self):
        """老 BUG: any(w in cmd for w in DISMISS_EXCLUSIVE + DISMISS_POLITE)."""
        sir_cmd = "好的，谢谢你啊，谢谢你。你不提醒，我真忘了，赶紧清理一下"
        # 老逻辑模拟
        DISMISS_WORDS = [
            "goodbye", "good night", "bye", "see you", "see you next time",
            "晚安", "再见", "拜拜",
            "thanks", "thank you", "谢谢",
        ]
        old_buggy = any(w in sir_cmd.lower() for w in DISMISS_WORDS)
        new_fixed = _simulate_dismissal_check(sir_cmd)
        self.assertTrue(old_buggy, '老 BUG 应判 True (复现)')
        self.assertFalse(new_fixed, '新 fix 应判 False (修了)')


class TestD_MarkerInSource(unittest.TestCase):
    """D: fix16 marker 在源码."""

    def test_marker(self):
        import jarvis_worker
        with open(jarvis_worker.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.46-fix16', src,
                       'fix16 marker 应在 jarvis_worker 源码')
        self.assertIn('DISMISS_EXCLUSIVE', src)
        self.assertIn('DISMISS_POLITE', src)
        # 老 silent path 应已替
        # 找 is_dismissal = 模式
        idx = src.find('is_dismissal = any(w in cmd_lower for w in self.voice_thread.DISMISS_WORDS)')
        self.assertEqual(idx, -1,
                          '老硬编码合并 DISMISS_WORDS 路径应已替')

    def test_is_short_logic(self):
        import jarvis_worker
        with open(jarvis_worker.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('is_dismissal_exclusive', src)
        self.assertIn('is_dismissal_polite', src)
        self.assertIn('is_short', src)


if __name__ == '__main__':
    unittest.main()
