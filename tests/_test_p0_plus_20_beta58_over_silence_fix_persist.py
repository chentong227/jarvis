# -*- coding: utf-8 -*-
"""
[P0+20-β.5.8-fix / 2026-05-19 14:00] Sir 真机实测 BUG-1 急修

Sir 起床 (98min AFK + first_today + return_greeting) 第一句 → 主脑选 [SILENCE].
log 显示 4/4 nudge 全 silent (offer_help / check_in / return_greeting / suggest_break).

Root cause:
  1. reaction_space prompt bias-toward-silence + "When in doubt: prefer [SILENCE]"
  2. β.5.5/β.5.6 sentinel tick skip publish 大量 'gate_advice decision=block' 到 SWM
     (SmartNudge sal=0.4 / ReturnSentinel sal=0.55 / Conductor sal=0.5)
  3. SWM render floor=0.3, 所有 tick skip 都进 SWM → 主脑读"满屏 block" → silence

Fix (3 改动):
  A. prompt 反转 bias-toward-voice + 加 MUST SPEAK list + DO NOT silence 反例
  B. SmartNudge tick skip sal 0.4 → 0.2 (低于 floor 不进 SWM)
  C. ReturnSentinel skip sal 0.55 → 0.25
  D. Conductor cooldown skip sal 0.5 → 0.25

测试覆盖:
  A. prompt 含 MUST SPEAK + bias-toward-voice + DO NOT silence
  B. 3 sentinel skip publish salience ≤ 0.25
  C. NudgeGate.can_speak publish 仍 sal ≥ 0.55 (保留真信号)
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# ==========================================================================
# A: reaction_space prompt 反转 bias + MUST SPEAK
# ==========================================================================

class TestBeta58PromptBiasInversion(unittest.TestCase):
    def setUp(self):
        self.src = _read(os.path.join(ROOT, 'jarvis_chat_bypass.py'))

    def test_prompt_has_default_is_voice(self):
        self.assertIn('DEFAULT IS VOICE', self.src,
            'reaction_space prompt 必须明示 DEFAULT IS VOICE (β.5.8-fix)')

    def test_prompt_no_bias_toward_silence(self):
        """旧 bias 'Default toward silence' 应被移除."""
        # 旧 bias 不能再出现
        self.assertNotIn('Default toward silence when evidence does not justify', self.src,
            '旧 bias-toward-silence 必须被移除')
        # 旧 'When in doubt: prefer [SILENCE]' 也要移除
        self.assertNotIn('When in doubt: prefer [SILENCE]', self.src,
            '旧 "When in doubt: prefer [SILENCE]" 必须被移除')

    def test_prompt_has_must_speak_section(self):
        self.assertIn('MUST SPEAK', self.src,
            'prompt 必须含 MUST SPEAK section (β.5.8-fix)')

    def test_must_speak_covers_return_greeting_afk_60min(self):
        self.assertIn('return_greeting', self.src)
        # 应明示 afk_minutes >= 60 触发 MUST SPEAK
        idx = self.src.find('MUST SPEAK')
        block = self.src[idx:idx+2000]
        self.assertIn('return_greeting', block,
            'MUST SPEAK section 必须含 return_greeting trigger')
        self.assertIn('afk_minutes', block)

    def test_must_speak_covers_morning_greeting_and_commitment(self):
        idx = self.src.find('MUST SPEAK')
        block = self.src[idx:idx+2000]
        self.assertIn('morning_greeting', block,
            'MUST SPEAK 应含 morning_greeting')
        self.assertIn('commitment_overdue', block,
            'MUST SPEAK 应含 commitment_overdue')

    def test_prompt_has_do_not_silence_pitfalls(self):
        self.assertIn('DO NOT silence', self.src,
            'prompt 必须含 DO NOT silence 反例提示 (BUG-1 pitfalls)')

    def test_when_in_doubt_now_speak(self):
        """新 prompt 在 doubt 时应 SPEAK 而非 silence."""
        self.assertIn('When in doubt: SPEAK', self.src,
            'prompt "When in doubt" 应改成 SPEAK (β.5.8-fix)')

    def test_return_greeting_truth_anchor_speaks(self):
        """[β.5.8-fix 第 3 处] return_greeting directive 内 [TRUTH ANCHOR] 必须明示
        BUT STILL GREET (旧文只说"不要 speculate", 主脑可能误读为"silence")."""
        # 第 1 个 [TRUTH ANCHOR — Sir 准则 5 是 return_greeting directive
        idx = self.src.find('[TRUTH ANCHOR')
        self.assertGreater(idx, 0)
        block = self.src[idx:idx+800]
        self.assertIn('BUT STILL GREET', block,
            'return_greeting [TRUTH ANCHOR] 必须明示 BUT STILL GREET (β.5.8-fix 第 3 处)')
        self.assertIn("Don't go silent", block,
            'return_greeting [TRUTH ANCHOR] 必须明示 Don\'t go silent (β.5.8-fix)')

    def test_soul_to_use_no_skip_silently(self):
        """[β.5.8-fix 第 4 处] [SOUL TO USE] 旧文 'skip silently' 可能被主脑读为全沉默.
        改成 "just don't use the callback (still reply normally)"."""
        # 旧 'skip silently' 不能再作 callback skip 的 rule (但可能在注释里)
        # 找 _parts 列表内的 "skip silently" 应消失
        idx = self.src.find('[SOUL TO USE')
        self.assertGreater(idx, 0)
        block = self.src[idx:idx+800]
        self.assertIn('still reply normally', block,
            'SOUL TO USE 必须含 "still reply normally" (β.5.8-fix 第 4 处)')

    def test_truth_anchor_no_silence_on_unknown(self):
        """[β.5.8-fix 第 2 处] TRUTH ANCHOR (RULES 段内) 旧文 'silence on unknown beats
        invented detail' 让主脑全沉默. 必须改为 omit unknown facts but still SPEAK."""
        # 文件里有 2 个 TRUTH ANCHOR — 第 1 个在 return_greeting nudge_directive (line 3567),
        # 第 2 个在 [RULES] section (line 3784) — 后者是我们要 fix 的目标
        first = self.src.find('[TRUTH ANCHOR')
        self.assertGreater(first, 0)
        idx = self.src.find('[TRUTH ANCHOR', first + 10)
        self.assertGreater(idx, 0, '应有 2 个 [TRUTH ANCHOR (β.5.8-fix 修第 2 个)')
        # 只看第 2 个 TRUTH ANCHOR 段直到下一个 [INTEGRITY section
        end = self.src.find('\n- [INTEGRITY', idx)
        if end < 0:
            end = idx + 2000
        block = self.src[idx:end]
        # actionable rule 段必须含 "but still SPEAK" (新规)
        self.assertIn('but still SPEAK', block,
            'TRUTH ANCHOR (RULES 段内) 必须含 "but still SPEAK" (β.5.8-fix)')
        self.assertIn('Generic greeting / acknowledgement', block,
            'TRUTH ANCHOR 必须明示 generic 类型仍 safe (β.5.8-fix)')


# ==========================================================================
# B/C/D: sentinel skip publish salience 降到 floor 以下
# ==========================================================================

class TestBeta58SentinelSkipSalienceDrop(unittest.TestCase):
    def test_smartnudge_skip_salience_below_floor(self):
        src = _read(os.path.join(ROOT, 'jarvis_smart_nudge.py'))
        # 找 publish 调用 (含 source='SmartNudge' + salience=)
        idx = src.find("source='SmartNudge'")
        self.assertGreater(idx, 0)
        block = src[idx:idx+500]
        self.assertIn('salience=0.2', block,
            'SmartNudge skip publish salience 必须 0.2 (β.5.8-fix, 低于 SWM floor 0.3)')

    def test_returnsentinel_skip_salience_below_floor(self):
        src = _read(os.path.join(ROOT, 'jarvis_return_sentinel.py'))
        # 找 f"ReturnSentinel wanted greet but blocked: {skip_reason}" 的 publish
        idx = src.find('description=f"ReturnSentinel wanted greet')
        self.assertGreater(idx, 0)
        block = src[idx:idx+700]
        self.assertIn('salience=0.25', block,
            'ReturnSentinel skip publish salience 必须 0.25 (β.5.8-fix)')

    def test_conductor_cooldown_skip_salience_below_floor(self):
        src = _read(os.path.join(ROOT, 'jarvis_conductor.py'))
        idx = src.find("source='Conductor'")
        self.assertGreater(idx, 0)
        block = src[idx:idx+800]
        self.assertIn('salience=0.25', block,
            'Conductor cooldown skip salience 必须 0.25 (β.5.8-fix)')


# ==========================================================================
# E: NudgeGate.can_speak publish 保留 sal ≥ 0.55 (真信号不该降)
# ==========================================================================

class TestBeta58NudgeGatePublishSalienceUnchanged(unittest.TestCase):
    def test_nudgegate_can_speak_publish_salience_unchanged(self):
        """NudgeGate.can_speak 自己的 publish 是真信号 (freeze_active/sleep/cooldown),
        sal 应保留 0.55-0.7 让主脑确实看到."""
        src = _read(os.path.join(ROOT, 'jarvis_sentinels.py'))
        # 找 NudgeGate sal = ... 计算式
        idx = src.find("sal = 0.7 if (gate_mode == 'publish_only' and not result) else 0.55")
        self.assertGreater(idx, 0,
            'NudgeGate.can_speak publish 应保留 sal=0.7/0.55 计算式 (β.5.8 不该降)')


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print('='*60)
    if result.wasSuccessful():
        print('[OK] β.5.8-fix over-silence BUG tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('='*60)
    sys.exit(0 if result.wasSuccessful() else 1)
