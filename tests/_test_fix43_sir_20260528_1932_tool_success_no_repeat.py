# -*- coding: utf-8 -*-
"""[fix43 / Sir 2026-05-28 19:32 real-screen anchor] tool ✅ success + 已 speak → 主脑 iter 2 又 repeat 同句.

真实场景 (Sir 真测 image 截图 19:31):
  Sir 命令: "我现在准备开始休息，至少 1 小时内不要打扰我"
  Jarvis iter 1 输出:
    "Very well, Sir. I have set a reminder for 8:00 PM. I suggest resting
     your hands completely; perhaps some 'theoretical rest' is in order.
     <FAST_CALL>add_reminder(...)</FAST_CALL>"
  tool 执行 add_reminder → ✅ 成功
  Jarvis iter 2 输出 (BUG):
    "Very well, Sir. I have set a reminder for 8:00 PM. I suggest resting
     your hands completely; perhaps some 'theoretical rest' is in order."
  ←—— 又说一遍同句 — Sir 看见英文双份, ZH subtitle 只翻译第一份.

根因 (jarvis_chat_bypass.py:4452-4493 老逻辑):
  _dedup_directive 仅在 `_tool_failed and _speak_already` 触发.
  tool SUCCESS + speak_already 时 _dedup_directive 为空, 主脑被
  continuation_prompt "Speak a SINGLE concluding sentence summarizing
  ALL the actions you just performed" 引导, 又说一遍 ack.

修法 (准则 5 言出必行 + 准则 6 evidence + 准则 8 优雅):
  condition 改 `if _speak_already`, 内分:
    - _tool_failed → 现有 FAILURE HANDLING directive (不动)
    - elif not _tool_failed → 新 NO-REPEAT success directive
  success directive 不写死 forbidden list, 给反例 + 正例 + evidence 让主脑
  自决 Option A (silent + ZH cover earlier EN) / Option B (brief new info).

防回退: 5 testcase 源码 marker check.
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(name: str) -> str:
    with open(os.path.join(ROOT, name), 'r', encoding='utf-8') as f:
        return f.read()


# ==========================================================================
# T1: source — condition 已从 `_tool_failed and _speak_already` 改成
#     `_speak_already` 主干 + 内部 if/elif 分支 (修后必须存在)
# ==========================================================================
class TestT1ConditionStructure(unittest.TestCase):
    def test_speak_already_main_branch_present(self):
        """修后: `if _speak_already and _tool_failed:` (fail 分支) 必须在 source."""
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('if _speak_already and _tool_failed:', src,
                      '修后 fail 分支条件 `if _speak_already and _tool_failed:` 必须在 source')

    def test_speak_already_success_elif_branch_present(self):
        """修后: `elif _speak_already and not _tool_failed:` (success 分支 新加) 必须在 source."""
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('elif _speak_already and not _tool_failed:', src,
                      '修后 success 分支条件 `elif _speak_already and not _tool_failed:` 必须在 source')

    def test_old_condition_removed(self):
        """老 condition `if _tool_failed and _speak_already:` 必须移除 (顺序换了)."""
        src = _read('jarvis_chat_bypass.py')
        self.assertNotIn('if _tool_failed and _speak_already:', src,
                         '老 condition `if _tool_failed and _speak_already:` 必须不再出现')


# ==========================================================================
# T2: source — success directive 含关键 marker
# ==========================================================================
class TestT2SuccessDirectiveMarkers(unittest.TestCase):
    def test_anchor_comment_present(self):
        """source 必须含 Sir 真痛 anchor 注释."""
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('Sir 2026-05-28 19:31 真痛 BUG-RPT', src,
                      'source 必须含 fix43 anchor 注释 (Sir 真测 image 19:31)')

    def test_no_repeat_header_present(self):
        """success directive header 含 NO-REPEAT 关键字."""
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('BUG-RPT', src,
                      'success directive 必须含 BUG-RPT 标识')
        self.assertIn('NO-REPEAT after successful tool', src,
                      'success directive header 必须含 NO-REPEAT after successful tool')

    def test_option_a_and_b_patterns(self):
        """success directive 给 Option A (silent) + Option B (brief new info) 两套正例."""
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('Option A (preferred', src,
                      'success directive 必须有 Option A (silent confirmation)')
        self.assertIn('Option B (brief confirmation', src,
                      'success directive 必须有 Option B (brief new info confirmation)')

    def test_override_chaining_rule_explicit(self):
        """success directive 必须明确教主脑 override 'Speak a SINGLE concluding' rule."""
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('Override the "Speak a SINGLE concluding sentence', src,
                      "success directive 必须明确告诉主脑 override 'Speak a SINGLE concluding' rule")


# ==========================================================================
# T3: source — fail directive intact (不破老 fix BUG-Q+S)
# ==========================================================================
class TestT3FailDirectiveIntact(unittest.TestCase):
    def test_fail_directive_still_present(self):
        """老 fail directive (Sir 2026-05-26/27 BUG-Q+S+β) 必须仍 intact."""
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('CRITICAL FAILURE HANDLING', src,
                      'fail directive header 必须保留')
        self.assertIn('Sir 2026-05-26/27 BUG-Q+S+β', src,
                      'fail directive anchor 必须保留')
        self.assertIn('NO PAST-TENSE COMPLETION CLAIMS', src,
                      'fail directive NO PAST-TENSE rule 必须保留')


# ==========================================================================
# T4: source — anti-pattern marker 教主脑识别 Sir 19:31 image 痛点
# ==========================================================================
class TestT4AntiPatternMarkers(unittest.TestCase):
    def test_anti_pattern_re_stating_action_verb(self):
        """success directive 含反例: Re-stating same action verb."""
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('Re-stating the same action verb', src,
                      'success directive 必须含反例 Re-stating the same action verb')

    def test_anti_pattern_paraphrasing(self):
        """success directive 含反例: Paraphrasing same content."""
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('Paraphrasing the same content', src,
                      'success directive 必须含反例 Paraphrasing the same content')

    def test_anti_pattern_re_emit_inside_joke(self):
        """success directive 含反例: re-emit same inside-joke (Sir 19:31 image 'theoretical rest' 痛点)."""
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('Re-emitting an inside-joke', src,
                      'success directive 必须含反例 Re-emitting an inside-joke / playful tag')


# ==========================================================================
# T5: source — directive 嵌入 continuation_prompt 的位置正确
# ==========================================================================
class TestT5DirectiveInjection(unittest.TestCase):
    def test_dedup_directive_inserted_into_continuation_prompt(self):
        """_dedup_directive 必须拼到 continuation_prompt 内 (在 [SYSTEM TOOL RESULT] 后)."""
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('[SYSTEM TOOL RESULT for {command}]: {tool_result}{_dedup_directive}', src,
                      '_dedup_directive 必须 inline 拼进 continuation_prompt')


if __name__ == '__main__':
    unittest.main(verbosity=2)
