# -*- coding: utf-8 -*-
"""[P0+18-c.2 / 2026-05-15] Reminder 触发后反问 "要不要设倒计时" — 测试

c.2 BUG (Sir 主诉)：
Sir 17:25 实测 "2 分钟后提醒我喝水" → 17:27:45 触发后 Jarvis 回
"You requested a reminder to hydrate in two minutes. Shall I set a countdown for you?"
"您曾要求...需要为您设置倒计时吗?" —— 时间语义被完全 invert。

c.2 BUG 链：
1. _escalate_reminder / ChronosSentinel 拼 "it is time to trigger the following reminder for Sir: {intent}"
   配合 directive "inform about this event"，让 LLM 误读为"我应该告诉他设了个提醒"
2. mail mode prompt 最小化，无"触发态 vs 调度态"指引，LLM 自然走过去时框架
3. DB 存原话 "提醒我两分钟后喝水"（含祈使动词 + 时间锚），LLM 看到 → 礼貌确认

c.2 修复（A + B + C）：
A. 重写 _escalate_reminder (line 2424-2435) 触发文案 →
   "[REMINDER FIRING NOW — TIME HAS ALREADY ELAPSED]\n
   Sir's original request was: '{intent}'.\n
   The countdown is OVER. The wait period has finished.
   You must DELIVER this reminder to Sir IN THIS MOMENT, as if a kitchen timer just rang.
   Extract the actual action from the request (the part after the time anchor)
   and tell Sir directly in short, present-tense imperative."
B. ChronosSentinel.run() (line 2559-2568) 同步触发文案
C. mail mode prompt (line 11445+) 注入 REMINDER_FIRING_DIRECTIVE：含禁忌词典 + 正例
   禁忌：shall I / would you like / 需要为您 / 要不要 / you requested / 您曾要求 / memory protocol
   正例：原 "两分钟后喝水" → "Sir, time to hydrate."
        原 "下午3点开会" → "Sir, your meeting is starting."
        原 "明天10点拿快递" → "Sir, time to pick up the package."

覆盖
----
A. _escalate_reminder 触发文案
    1. 包含 "[REMINDER FIRING NOW — TIME HAS ALREADY ELAPSED]" 标志串
    2. 包含 "countdown is OVER" / "wait period has finished"
    3. 包含 "DELIVER this reminder" / "IN THIS MOMENT"
    4. 包含 "kitchen timer just rang" 类比
    5. 包含 "present-tense imperative" 指令
    6. **不再包含**旧文案 "it is time to trigger the following reminder"

B. ChronosSentinel.run() 触发文案
    7. 同步包含 "[REMINDER FIRING NOW — TIME HAS ALREADY ELAPSED]"
    8. 同步**不含**旧文案

C. mail mode prompt 注入 REMINDER_FIRING_DIRECTIVE
    9. mail mode 分支存在 reminder_firing_directive 变量
    10. 含 anti-patterns 完整禁忌词典（≥8 条）
    11. 含正例（≥3 条原话 → 立刻执行的转换）
    12. 含 algorithm 指引（extract action verb + object）
    13. 含 "Do NOT ask permission" / "Do NOT re-confirm"
    14. directive 在 mail mode prompt **顶部**（在 user_input 之前）

D. 静态扫描 nerve.py
    15. _escalate_reminder 函数体内的新文案确实拼到 mailbox.deliver()
    16. ChronosSentinel.run() 函数体内的新文案确实拼到 mailbox.deliver()

跑法：
    cd d:\\Jarvis
    python tests/_test_p0_plus_18_c2_reminder_firing.py
"""

import os
import re
import sys
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

NERVE_PATH = os.path.join(ROOT, 'jarvis_nerve.py')

# [P0+19-6.a / 2026-05-16] 拆分后 ChronosTick/Sentinel 等已搬到 jarvis_sentinels.py
# 用 corpus helper 跨多文件扫描
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _source_corpus import read_nerve_corpus


# ============================================================
# 共享 nerve.py 文件读入（静态扫描）
# ============================================================

class _NerveSource:
    """单例读 nerve.py 文本 + 切出 _escalate_reminder / ChronosSentinel.run / mail mode 分支"""

    _content = None
    _escalate_body = None
    _chronos_run_body = None
    _mail_branch_body = None

    @classmethod
    def content(cls):
        if cls._content is None:
            cls._content = read_nerve_corpus()
        return cls._content

    @classmethod
    def escalate_body(cls):
        """切 _escalate_reminder 函数体（从 `def _escalate_reminder` 到下一个 `def `）"""
        if cls._escalate_body is None:
            m = re.search(
                r'def _escalate_reminder\(self.*?\n(.*?)\n    def ',
                cls.content(), re.DOTALL,
            )
            cls._escalate_body = m.group(1) if m else ''
        return cls._escalate_body

    @classmethod
    def chronos_run_body(cls):
        """切 ChronosSentinel.run 函数体"""
        if cls._chronos_run_body is None:
            # ChronosSentinel 类定义 → run 方法 → 下一个 class
            m = re.search(
                r'class ChronosSentinel.*?def run\(self\).*?\n(.*?)\nclass ',
                cls.content(), re.DOTALL,
            )
            cls._chronos_run_body = m.group(1) if m else ''
        return cls._chronos_run_body

    @classmethod
    def mail_branch_body(cls):
        """切 mail mode 分支（从 `if mode == "mail":` 到下一个 `if prompt_tier` 或 `def `）"""
        if cls._mail_branch_body is None:
            m = re.search(
                r'if mode == "mail":(.*?)(?=\n        # \[R7-β1\]|\n        if prompt_tier|\n    def )',
                cls.content(), re.DOTALL,
            )
            cls._mail_branch_body = m.group(1) if m else ''
        return cls._mail_branch_body


# ============================================================
# A. _escalate_reminder 触发文案
# ============================================================

class TestEscalateReminderTriggerMessage(unittest.TestCase):
    """[c.2/A] _escalate_reminder 用新"FIRING NOW"文案，废弃旧"it is time to trigger" """

    def setUp(self):
        self.body = _NerveSource.escalate_body()
        self.assertTrue(self.body, '_escalate_reminder 函数体未找到')

    def test_has_firing_now_marker(self):
        self.assertIn('[REMINDER FIRING NOW', self.body,
                      '触发文案缺 "[REMINDER FIRING NOW" 标志串')
        self.assertIn('TIME HAS ALREADY ELAPSED', self.body,
                      '触发文案缺 "TIME HAS ALREADY ELAPSED"')

    def test_has_countdown_over_phrasing(self):
        self.assertTrue(
            'countdown is OVER' in self.body or 'wait period has finished' in self.body,
            '触发文案缺"countdown is OVER / wait period has finished"语义',
        )

    def test_has_deliver_imperative(self):
        self.assertIn('DELIVER this reminder', self.body,
                      '触发文案缺 "DELIVER this reminder" 祈使语义')
        self.assertIn('IN THIS MOMENT', self.body,
                      '触发文案缺 "IN THIS MOMENT" 紧急感')

    def test_has_kitchen_timer_analogy(self):
        self.assertIn('kitchen timer', self.body,
                      '触发文案缺 "kitchen timer just rang" 类比（让 LLM 进入"通知"模式）')

    def test_has_present_tense_imperative_directive(self):
        self.assertIn('present-tense imperative', self.body,
                      '触发文案缺 "present-tense imperative" 显式语法指令')

    def test_no_old_phrasing(self):
        """旧的"it is time to trigger the following reminder" 让 LLM 困惑 → string literal 必须清除。
        注释里提及（作为修复说明）是允许的。"""
        # 抽出 content = ( ... ) 这一段 string literal（不含注释）
        literal = _extract_content_string_literal(self.body)
        self.assertIsNotNone(literal, '_escalate_reminder 缺 content = (...) 赋值')
        self.assertNotIn(
            'it is time to trigger the following reminder',
            literal,
            '旧触发文案 "it is time to trigger the following reminder" 仍在 content 字符串里',
        )
        self.assertNotIn(
            'inform about this event',
            literal,
            '旧 directive "inform about this event" 仍在 content 字符串里',
        )


def _extract_content_string_literal(body: str) -> str:
    """从函数体里抽出 `content = (\n    f"..."\n    f"..."\n)` 这一段 string literal 的拼接。
    返回所有 f"..."/"..." 内容的 concat。注释行（# 开头）会被排除。
    """
    m = re.search(r'content\s*=\s*\(\s*\n(.*?)\n\s*\)', body, re.DOTALL)
    if not m:
        return None
    block = m.group(1)
    # 抽所有 f"..." / "..." 字面量内容
    lits = re.findall(r'f?"([^"]*)"', block)
    return ''.join(lits)


# ============================================================
# B. ChronosSentinel.run 触发文案
# ============================================================

class TestChronosSentinelTriggerMessage(unittest.TestCase):
    """[c.2/B] ChronosSentinel.run 同步使用新"FIRING NOW"文案"""

    def setUp(self):
        self.body = _NerveSource.chronos_run_body()
        self.assertTrue(self.body, 'ChronosSentinel.run 函数体未找到')

    def test_has_firing_now_marker(self):
        self.assertIn('[REMINDER FIRING NOW', self.body,
                      'ChronosSentinel.run 缺 "[REMINDER FIRING NOW"')
        self.assertIn('TIME HAS ALREADY ELAPSED', self.body,
                      'ChronosSentinel.run 缺 "TIME HAS ALREADY ELAPSED"')

    def test_no_old_phrasing(self):
        """同样只看 content = (...) string literal 部分"""
        literal = _extract_content_string_literal(self.body)
        self.assertIsNotNone(literal, 'ChronosSentinel.run 缺 content = (...) 赋值')
        self.assertNotIn(
            'it is time to trigger the following reminder',
            literal,
            'ChronosSentinel.run 旧触发文案仍在 content 字符串里',
        )


# ============================================================
# C. mail mode prompt 注入 REMINDER_FIRING_DIRECTIVE
# ============================================================

class TestMailModeReminderDirective(unittest.TestCase):
    """[c.2/C] mail mode prompt 含 REMINDER_FIRING_DIRECTIVE：禁忌词典 + 正例 + 算法"""

    def setUp(self):
        self.body = _NerveSource.mail_branch_body()
        self.assertTrue(self.body, 'mail mode 分支未找到（mode == "mail" branch）')

    def test_has_directive_variable(self):
        self.assertTrue(
            'reminder_firing_directive' in self.body or 'REMINDER_FIRING_DIRECTIVE' in self.body,
            'mail mode 分支缺 reminder_firing_directive 变量',
        )

    def test_has_critical_marker(self):
        self.assertIn('CRITICAL', self.body, 'directive 缺 CRITICAL 提醒标记')
        self.assertIn('REMINDER DELIVERY MODE', self.body,
                      'directive 缺 "REMINDER DELIVERY MODE" 模式标题')

    def test_has_anti_patterns_blacklist_english(self):
        """禁忌英文短语（LLM 常用过去时/确认框架）"""
        anti = [
            'shall I set a countdown',
            'would you like me to remind',
            'do you want',
            'you requested a reminder',
        ]
        missing = [p for p in anti if p not in self.body]
        self.assertEqual(missing, [], f'禁忌英文短语缺失: {missing}')

    def test_has_anti_patterns_blacklist_chinese(self):
        """禁忌中文短语"""
        anti = ['需要为您', '要不要', '您曾要求', '根据您的记忆协议']
        missing = [p for p in anti if p not in self.body]
        self.assertEqual(missing, [], f'禁忌中文短语缺失: {missing}')

    def test_has_positive_examples(self):
        """正例：原话 → 立刻执行的转换（至少 3 个）"""
        # 必须含 3 个典型场景的原话和正确输出
        positive_pairs = [
            # (原话片段, 正确输出片段)
            ('提醒我两分钟后喝水', 'time to hydrate'),
            ('下午3点开会', 'meeting is starting'),
            ('明天 10 点拿快递', 'pick up the package'),
        ]
        for original, expected in positive_pairs:
            self.assertIn(
                original,
                self.body,
                f'正例缺原话 "{original}"（让 LLM 明白这种输入该怎么处理）',
            )
            self.assertIn(
                expected,
                self.body,
                f'正例缺期望输出 "{expected}"',
            )

    def test_has_algorithm_instruction(self):
        """显式算法指引（extract action verb + object）"""
        self.assertIn('extract', self.body.lower(),
                      'directive 缺 "extract" 算法关键词')
        self.assertIn('time anchor', self.body,
                      'directive 缺 "time anchor" 概念（让 LLM 知道时间锚和动作的关系）')

    def test_has_do_not_directives(self):
        """显式禁止：Do NOT ask / Do NOT re-confirm / Do NOT explain"""
        do_nots = ['Do NOT ask', 'Do NOT re-confirm']
        missing = [p for p in do_nots if p not in self.body]
        self.assertEqual(
            missing,
            [],
            f'禁止指令缺失（让 LLM 不重复确认）: {missing}',
        )

    def test_directive_placed_before_user_input(self):
        """directive 必须在 user_input 之前注入（让 LLM 先读规则再看请求）"""
        # 找 reminder_firing_directive 变量定义位置
        directive_pos = self.body.find('reminder_firing_directive')
        # 找 return f""" / user_input 位置
        return_pos = self.body.find('return f"""')
        if directive_pos >= 0 and return_pos >= 0:
            self.assertLess(
                directive_pos,
                return_pos,
                'reminder_firing_directive 应在 return f""" 之前定义',
            )
        # 在 return template 内，directive 应在 user_input 之前
        return_template = self.body[return_pos:] if return_pos >= 0 else ''
        if '{reminder_firing_directive}' in return_template and '{user_input}' in return_template:
            dpos = return_template.find('{reminder_firing_directive}')
            upos = return_template.find('{user_input}')
            self.assertLess(
                dpos,
                upos,
                '{reminder_firing_directive} 应在 {user_input} 之前（LLM 先读规则再看请求）',
            )


# ============================================================
# D. 静态扫描确认 mailbox.deliver 调用
# ============================================================

class TestMailboxDeliverCalls(unittest.TestCase):
    """[c.2/D] 新文案确实拼进 mailbox.deliver() 调用"""

    def setUp(self):
        self.content = _NerveSource.content()

    def test_escalate_reminder_delivers_new_content(self):
        """_escalate_reminder 内的 mailbox.deliver(content) 用的是新 content 变量"""
        body = _NerveSource.escalate_body()
        # 应该有 content = ( "[REMINDER FIRING NOW..." ) 的赋值
        # 然后 self.mailbox.deliver(... content ...)
        self.assertIn('mailbox.deliver(', body,
                      '_escalate_reminder 缺 mailbox.deliver() 调用')
        # content 变量应在 deliver 之前定义
        content_pos = body.find('content = ')
        deliver_pos = body.find('mailbox.deliver(')
        self.assertGreater(content_pos, -1, '_escalate_reminder 缺 content = ... 赋值')
        self.assertLess(
            content_pos,
            deliver_pos,
            'content 赋值应在 deliver 之前',
        )

    def test_chronos_run_delivers_new_content(self):
        body = _NerveSource.chronos_run_body()
        self.assertIn('mailbox.deliver(', body,
                      'ChronosSentinel.run 缺 mailbox.deliver() 调用')
        content_pos = body.find('content = ')
        deliver_pos = body.find('mailbox.deliver(')
        self.assertGreater(content_pos, -1, 'ChronosSentinel.run 缺 content = ... 赋值')
        self.assertLess(content_pos, deliver_pos)


# ============================================================
# E. 集成测试 —— 模拟 reminder 触发 → 验证 prompt 拼接结果
# ============================================================

class TestReminderPromptIntegration(unittest.TestCase):
    """[c.2/E] 集成测试：模拟 mail mode prompt 装配 → 确认 directive 真的拼进了 prompt"""

    def test_prompt_assembly_includes_directive(self):
        """直接读 mail mode 分支的 return template，验证 directive 在最终拼接里"""
        body = _NerveSource.mail_branch_body()
        m = re.search(r'return f"""(.*?)"""', body, re.DOTALL)
        self.assertIsNotNone(m, 'mail mode 分支缺 return f"""...""" 模板')
        template = m.group(1)
        # 模板里必须含 {reminder_firing_directive} 占位符
        self.assertIn(
            '{reminder_firing_directive}',
            template,
            'mail mode 的 return template 没把 reminder_firing_directive 拼进去',
        )

    def test_anti_patterns_will_reach_llm(self):
        """end-to-end：mail mode prompt 模板拼接后，LLM 看到的字符串里必须含 anti-patterns"""
        body = _NerveSource.mail_branch_body()
        # directive 变量内容（在 return 之前定义）+ 模板拼接 = 最终 prompt
        # 直接验证 directive 变量含 anti-patterns 即可
        directive_match = re.search(
            r'reminder_firing_directive\s*=\s*"""(.*?)"""',
            body,
            re.DOTALL,
        )
        self.assertIsNotNone(
            directive_match,
            '找不到 reminder_firing_directive 三引号字符串定义',
        )
        directive_text = directive_match.group(1)
        critical_anti = ['shall I', '需要为您', 'Do NOT ask']
        missing = [p for p in critical_anti if p not in directive_text]
        self.assertEqual(
            missing,
            [],
            f'directive 字符串内缺关键 anti-pattern: {missing}',
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
