# -*- coding: utf-8 -*-
"""[P0+18-c.3 ~ c.14 / 2026-05-15] Sir 17:21 实测 12 BUG 剩余项综合测试

c.1 / c.2 / c.5 已各有独立测试文件。这里覆盖剩余的：
- c.3  Fast Path 误触多步指令（查询动词+动作动词同存的多步检测 + hand command 白名单）
- c.4  Fast Path 状态行粘 Jarvis 头部（同 c.3 改的 \n）
- c.6  Smart Nudge return_greeting 路径破坏对话框（set_conversation_active 前置）
- c.7  SoulArchivist Sir的资料已更新 改 bg_log
- c.8  Time Hook / CommitmentWatcher / ║ 📝 [Commitment] / Anti-False-Positive 改 bg_log
- c.9/c.10 Time Hook ↔ CommitmentWatcher 双路径一致性 + CW 用 user_text 检测
- c.11 中文 subtitle 流到 TTS 的上游路径（3 处 buffer flush 检查 is_subtitle_mode）
- c.12 中文 subtitle 多段排版 ║ 前缀（subtitle print 走 _box_newline）
- c.13 Soft Focus 改 bg_log
- c.14 ScreenshotSentinel 截图失败改 bg_log

跑法：
    cd d:\\Jarvis
    python tests/_test_p0_plus_18_c3_to_c14_remaining.py
"""

import os
import re
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

NERVE_PATH = os.path.join(ROOT, 'jarvis_nerve.py')

# [P0+19-6.a / 2026-05-16] 拆分后 ScreenshotSentinel/SoulArchivist 等已搬到 jarvis_sentinels.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _source_corpus import read_nerve_corpus


def _read_nerve():
    return read_nerve_corpus()


# ============================================================
# c.3 — Fast Path 误触多步指令
# ============================================================

class TestC3FastPathMultiStep(unittest.TestCase):
    """c.3: 查询动词 + 动作动词同存 → 不走 Fast Path；hand command 白名单"""

    @classmethod
    def setUpClass(cls):
        cls.content = _read_nerve()

    def test_action_hand_commands_frozenset_exists(self):
        self.assertIn('_C3_ACTION_HAND_COMMANDS', self.content,
                      '缺 _C3_ACTION_HAND_COMMANDS 白名单常量')
        # 在模块顶层定义
        self.assertTrue(
            re.search(r'^_C3_ACTION_HAND_COMMANDS\s*=\s*frozenset\(', self.content, re.MULTILINE),
            '_C3_ACTION_HAND_COMMANDS 应该是模块顶层 frozenset',
        )

    def test_action_commands_in_whitelist(self):
        """关键动作命令必须在白名单"""
        from jarvis_nerve import _C3_ACTION_HAND_COMMANDS
        must_have = ['kill_process', 'set_volume', 'mute', 'unmute',
                     'launch_app', 'open_app', 'close_window',
                     'play', 'pause', 'shutdown', 'lock_workstation']
        missing = [c for c in must_have if c not in _C3_ACTION_HAND_COMMANDS]
        self.assertEqual(missing, [], f'动作命令白名单缺失: {missing}')

    def test_query_commands_NOT_in_whitelist(self):
        """查询命令不能在白名单（必须走二轮总结）"""
        from jarvis_nerve import _C3_ACTION_HAND_COMMANDS
        must_not = ['find_process', 'get_process_info', 'is_running',
                    'get_top_cpu', 'wait_for_process']
        leaked = [c for c in must_not if c in _C3_ACTION_HAND_COMMANDS]
        self.assertEqual(leaked, [], f'查询命令误入白名单: {leaked}')

    def test_query_verb_detection_logic_exists(self):
        """_is_simple_one_shot 附近应有查询动词检测"""
        # 关键代码：_has_query_verb / _is_action_command / _query_verb_patterns
        self.assertIn('_has_query_verb', self.content,
                      '_is_simple_one_shot 路径缺 _has_query_verb 检测')
        self.assertIn('_is_action_command', self.content,
                      '_is_simple_one_shot 路径缺 _is_action_command 检测')
        self.assertIn('_query_verb_patterns', self.content,
                      '_is_simple_one_shot 路径缺 _query_verb_patterns')

    def test_one_shot_uses_action_command_and_not_query(self):
        """_is_simple_one_shot 的条件里必须同时含 _is_action_command 和 not _has_query_verb"""
        # 找 _is_simple_one_shot = ( ... )  允许多行嵌套括号；用关键词扫描整段
        # 简化：从 _is_simple_one_shot = ( 开始，找到下一个空行 / `if _is_simple_one_shot:` 行
        m = re.search(
            r'_is_simple_one_shot\s*=\s*\(\s*\n(.*?)\n\s+\)\s*\n\s+if\s+_is_simple_one_shot',
            self.content, re.DOTALL,
        )
        self.assertIsNotNone(m, '找不到 _is_simple_one_shot 赋值段')
        cond = m.group(1)
        self.assertIn('_is_action_command', cond,
                      '_is_simple_one_shot 条件没用 _is_action_command')
        self.assertIn('not _has_query_verb', cond,
                      '_is_simple_one_shot 条件没排除 _has_query_verb')

    def test_query_verbs_include_chinese_and_english(self):
        """查询动词词典覆盖中英文双语"""
        # 中文：看一下 / 查一下 / 检查
        # 英文：check / find / search / look
        for kw in ['看一下', '查一下', '检查']:
            self.assertIn(kw, self.content, f'查询动词词典缺中文 "{kw}"')
        # 英文匹配 \b 边界
        for kw in ['check', 'find', 'search']:
            # 模式应该出现在 _query_verb_patterns 附近
            pattern = re.compile(r'_query_verb_patterns.*?' + kw, re.DOTALL)
            self.assertTrue(pattern.search(self.content),
                            f'查询动词英文词典缺 "{kw}"')


# ============================================================
# c.4 — Fast Path 状态行粘 Jarvis 头部
# ============================================================

class TestC4FastPathPrintNewline(unittest.TestCase):
    """c.4: Fast Path 状态行用 \\n 开头，不粘 Jarvis 头部"""

    @classmethod
    def setUpClass(cls):
        cls.content = _read_nerve()

    def test_fast_path_print_has_leading_newline(self):
        """`║ 🚀 [Fast Path] 单步设备指令` print 应有 \\n 开头"""
        # 找 Fast Path print
        m = re.search(
            r'print\(f"(\\n)?(?:║)?\s*🚀\s*\[Fast Path\]\s*单步设备指令',
            self.content,
        )
        self.assertIsNotNone(m, '找不到 Fast Path 状态行 print')
        # group(1) 是 \n（如果有）
        self.assertEqual(m.group(1), r'\n',
                         'Fast Path print 没用 \\n 开头，会粘到 Jarvis 头部同一行')


# ============================================================
# c.6 — Smart Nudge return_greeting 路径破坏对话框
# ============================================================

class TestC6SmartNudgeBoxIntegrity(unittest.TestCase):
    """c.6: __NUDGE__ voice 分支 set_conversation_active(True) 前置 + finally 复位"""

    @classmethod
    def setUpClass(cls):
        cls.content = _read_nerve()

    def test_nudge_voice_branch_activates_conversation(self):
        """voice 档分支应有 set_conversation_active(True) 在 set_browser_ducking 之前"""
        # 切出 voice 档分支：从 "# [R7-α/NudgeChannel] VOICE 档" 到下一个 continue/break/elif
        m = re.search(
            r'#\s*\[R7-α/NudgeChannel\]\s*VOICE 档.*?(?=\n\s+# 如果没命中脊髓反射|\n\s+def )',
            self.content, re.DOTALL,
        )
        self.assertIsNotNone(m, '找不到 VOICE 档分支')
        body = m.group(0)
        # 必须含 set_conversation_active(True)
        self.assertIn('set_conversation_active', body,
                      'VOICE 档分支缺 set_conversation_active 调用')
        # 检查相对位置：set_conversation_active(True) 在 set_browser_ducking 之前
        # 找 _set_conv_active_c6(True) / set_conversation_active(True)
        active_true_match = re.search(
            r'(_set_conv_active_c6|set_conversation_active)\(True\)',
            body,
        )
        ducking_match = re.search(r'set_browser_ducking\(True\)', body)
        self.assertIsNotNone(active_true_match, 'VOICE 档分支缺 set_conversation_active(True)')
        self.assertIsNotNone(ducking_match, 'VOICE 档分支缺 set_browser_ducking(True)')
        self.assertLess(
            active_true_match.start(),
            ducking_match.start(),
            'set_conversation_active(True) 必须在 set_browser_ducking(True) 之前调用，'
            '否则 BrowserDucking 异步 bg_log 漏到 box 内'
        )

    def test_nudge_voice_branch_deactivates_conversation_in_finally(self):
        """finally 块必须 set_conversation_active(False) 复位"""
        m = re.search(
            r'#\s*\[R7-α/NudgeChannel\]\s*VOICE 档.*?(?=\n\s+# 如果没命中脊髓反射|\n\s+def )',
            self.content, re.DOTALL,
        )
        body = m.group(0) if m else ''
        # 必须有 set_conversation_active(False) 或 _set_conv_active_c6(False)
        self.assertTrue(
            re.search(r'(_set_conv_active_c6|set_conversation_active)\(False\)', body),
            'VOICE 档 finally 缺 set_conversation_active(False) 复位',
        )


# ============================================================
# c.7 / c.8 / c.13 / c.14 — 系统日志改 bg_log
# ============================================================

class TestC7C8C13C14BgLogRouting(unittest.TestCase):
    """各种系统状态打印改 bg_log，不再裸 print 漏到对话框"""

    @classmethod
    def setUpClass(cls):
        cls.content = _read_nerve()

    def test_c7_soul_archivist_uses_bg_log(self):
        """[SoulArchivist] Sir的资料已更新 改 bg_log"""
        # 旧 print 模式不再存在
        self.assertNotIn(
            'print(f"\\n[SoulArchivist] Sir的资料已更新',
            self.content,
            '[SoulArchivist] 还在用 print 漏到对话框',
        )
        # 新模式应该用 bg_log 拼 SoulArchivist 内容
        m = re.search(r'bg_log[^(]*\(.*?\[SoulArchivist\].*?Sir的资料', self.content, re.DOTALL)
        self.assertIsNotNone(m, '[SoulArchivist] 资料更新没改 bg_log')

    def test_c8_time_hook_task_scheduled_uses_bg_log(self):
        """[Time Hook] Task scheduled 改 bg_log"""
        # 旧 print 不再存在
        bad_pattern = re.compile(
            r'^\s+print\(f"⏰\s*\[Time Hook\]\s*Task scheduled',
            re.MULTILINE,
        )
        self.assertFalse(
            bad_pattern.search(self.content),
            '[Time Hook] Task scheduled 还在裸 print',
        )
        # 应该出现在 bg_log 调用
        m = re.search(r'bg_log[^(]*\(.*?\[Time Hook\].*?Task scheduled', self.content, re.DOTALL)
        self.assertIsNotNone(m, '[Time Hook] Task scheduled 没改 bg_log')

    def test_c8_commitment_print_uses_bg_log(self):
        """║ 📝 [Commitment] 改 bg_log（避免 box 外孤儿 ║）"""
        # 旧 print 不再存在
        bad = re.search(r'print\(f"║\s*📝\s*\[Commitment\]', self.content)
        self.assertIsNone(
            bad,
            '║ 📝 [Commitment] 还在 print（孤儿 ║ 漏到 box 外）',
        )
        # bg_log 中应有 [Commitment] 字符串
        m = re.search(r'bg_log[^(]*\(.*?\[Commitment\]', self.content, re.DOTALL)
        self.assertIsNotNone(m, '[Commitment] 行没改 bg_log')

    def test_c8_commitment_watcher_no_file_stderr(self):
        """[CommitmentWatcher] 不再用 print(..., file=sys.stderr)，统一改 bg_log"""
        # 不应再有 print(f"[CommitmentWatcher]..., file=sys.stderr) 形式
        bad = re.search(
            r'print\(f"\[CommitmentWatcher\][^"]*"[^)]*file=sys\.stderr',
            self.content,
        )
        self.assertIsNone(bad, '[CommitmentWatcher] 还在 print + file=sys.stderr')
        # 至少应有 bg_log 中含 [CommitmentWatcher]
        m = re.search(r'bg_log[^(]*\(.*?\[CommitmentWatcher\]', self.content, re.DOTALL)
        self.assertIsNotNone(m, '[CommitmentWatcher] 没改 bg_log')

    def test_c8_anti_false_positive_uses_bg_log(self):
        """[Anti-False-Positive] 未来任务标记已清除 改 bg_log"""
        bad = re.search(
            r'print\(f"\s*└─\s*🛡️\s*\[Anti-False-Positive\]',
            self.content,
        )
        self.assertIsNone(bad, '[Anti-False-Positive] 还在裸 print')
        m = re.search(r'bg_log[^(]*\(.*?\[Anti-False-Positive\]', self.content, re.DOTALL)
        self.assertIsNotNone(m, '[Anti-False-Positive] 没改 bg_log')

    def test_c13_soft_focus_uses_bg_log(self):
        """[Soft Focus] Verified / 检测到背景音 改 bg_log"""
        # 旧 print 不再存在
        bad1 = re.search(r'print\(f"🔒\s*\[Soft Focus\]\s*Verified', self.content)
        bad2 = re.search(r'print\(f"🔇\s*\[Soft Focus\]\s*检测到背景音', self.content)
        self.assertIsNone(bad1, '🔒 [Soft Focus] Verified 还在裸 print')
        self.assertIsNone(bad2, '🔇 [Soft Focus] 检测到背景音 还在裸 print')
        # 至少有 bg_log 中含 [Soft Focus]
        m = re.search(r'bg_log[^(]*\(.*?\[Soft Focus\]', self.content, re.DOTALL)
        self.assertIsNotNone(m, '[Soft Focus] 没改 bg_log')

    def test_c14_screenshot_sentinel_uses_bg_log(self):
        """[ScreenshotSentinel] 截图失败 / 截图异常 改 bg_log"""
        bad1 = re.search(r'print\(f"\[ScreenshotSentinel\]\s*截图失败', self.content)
        bad2 = re.search(r'print\(f"\[ScreenshotSentinel\]\s*截图异常', self.content)
        self.assertIsNone(bad1, '[ScreenshotSentinel] 截图失败 还在裸 print')
        self.assertIsNone(bad2, '[ScreenshotSentinel] 截图异常 还在裸 print')
        m = re.search(r'bg_log[^(]*\(.*?\[ScreenshotSentinel\]', self.content, re.DOTALL)
        self.assertIsNotNone(m, '[ScreenshotSentinel] 异常路径没改 bg_log')


# ============================================================
# c.9 / c.10 — CommitmentWatcher 双路径一致性 + 用 user_text 检测
# ============================================================

class TestC9C10CommitmentDualPathConsistency(unittest.TestCase):
    """c.9/c.10: add_commitment 接受 user_text + is_future_task_confirmed；词典扩展"""

    @classmethod
    def setUpClass(cls):
        cls.content = _read_nerve()

    def test_add_commitment_signature_has_user_text_param(self):
        """add_commitment 函数签名必须含 user_text + is_future_task_confirmed 参数"""
        m = re.search(
            r'def add_commitment\(self,\s*description.*?\):',
            self.content, re.DOTALL,
        )
        self.assertIsNotNone(m, 'add_commitment 定义未找到')
        sig = m.group(0)
        self.assertIn('user_text', sig,
                      'add_commitment 签名缺 user_text 参数')
        self.assertIn('is_future_task_confirmed', sig,
                      'add_commitment 签名缺 is_future_task_confirmed 参数')

    def test_call_site_passes_user_text_and_future_confirmed(self):
        """gatekeeper 路径调用 add_commitment 应传 user_text=cmd + is_future_task_confirmed=..."""
        # 找 add_commitment 调用（commitment_watcher.add_commitment）
        m = re.search(
            r'commitment_watcher\.add_commitment\(\s*desc,\s*deadline,?\s*(.*?)\)',
            self.content, re.DOTALL,
        )
        self.assertIsNotNone(m, '找不到 commitment_watcher.add_commitment 调用')
        args = m.group(1)
        self.assertIn('user_text', args,
                      'add_commitment 调用没传 user_text（CW 会丢"我"字判断）')
        self.assertIn('is_future_task_confirmed', args,
                      'add_commitment 调用没传 is_future_task_confirmed（Time Hook ↔ CW 不一致）')

    def test_rest_intent_markers_expanded(self):
        """作息词典扩展：学习/做题/刷题/工作/编程/视频/会议/锻炼"""
        must_have = ['学习', '做题', '刷题', '复习', '工作', '编程', '剪视频', '锻炼', '吃药']
        for kw in must_have:
            # 这些关键词应出现在 rest_intent_markers 列表附近
            pattern = re.compile(r'rest_intent_markers.*?' + kw, re.DOTALL)
            self.assertTrue(
                pattern.search(self.content),
                f'作息词典缺 "{kw}"（c.10 修复要求扩展通用动作词）',
            )

    def test_first_person_markers_include_intent_words(self):
        """first_person 词典含意图词（不如/打算/准备/计划）"""
        for kw in ['不如', '打算', '准备', '计划']:
            pattern = re.compile(r'first_person_markers.*?' + kw, re.DOTALL)
            self.assertTrue(
                pattern.search(self.content),
                f'first_person 词典缺意图词 "{kw}"',
            )

    def test_is_future_task_confirmed_skips_rejection(self):
        """is_future_task_confirmed=True 时跳过 first_person/rest 检查（信任 Time Hook）"""
        # 函数体内必须有 `if is_future_task_confirmed:` 分支
        m = re.search(
            r'def add_commitment\(self.*?\n(.*?)(?:\n    def |\Z)',
            self.content, re.DOTALL,
        )
        body = m.group(1) if m else ''
        self.assertIn(
            'if is_future_task_confirmed:',
            body,
            'add_commitment 缺 is_future_task_confirmed 分支',
        )
        # 不一致时 bg_log warn
        self.assertIn(
            'Inconsistency',
            body,
            'add_commitment 缺 Time Hook↔CW 不一致 bg_log warn',
        )


# ============================================================
# c.11 — 中文 subtitle 流到 TTS 上游路径
# ============================================================

class TestC11ChineseSubtitleLeak(unittest.TestCase):
    """c.11: 3 处 buffer flush 检查 is_subtitle_mode，避免 ZH 喂给 _put_audio"""

    @classmethod
    def setUpClass(cls):
        cls.content = _read_nerve()

    def test_all_buffer_flush_check_is_subtitle_mode(self):
        """所有 `if buffer.strip()` 末尾 flush 块必须有 ZH 守门（is_subtitle_mode 或 _zh_seen）
        （包括 cloud_followup FAST_CALL flush + cloud_followup 末尾 flush + main stream_chat
        gatekeeper_triggered flush + main stream_chat 末尾 flush + local fallback 末尾 flush +
        stream_nudge 末尾 flush）
        """
        pattern = re.compile(
            r"if buffer\.strip\(\) and not getattr\(self, 'is_interrupted'.*?\n((?:.*?\n){0,18})",
            re.DOTALL,
        )
        matches = list(pattern.finditer(self.content))
        self.assertGreaterEqual(
            len(matches), 4,
            f'应至少有 4 处 buffer flush（找到 {len(matches)} 处）',
        )
        # 每个 match 内应有 ZH 守门：is_subtitle_mode 或 _zh_seen
        unguarded = []
        for i, m in enumerate(matches):
            block = m.group(1)
            has_guard = ('is_subtitle_mode' in block or '_zh_seen' in block)
            if not has_guard and '_put_audio' in block:
                unguarded.append((i, block[:80]))
        self.assertEqual(
            unguarded, [],
            f'有 {len(unguarded)} 处 buffer flush 没检查 ZH 守门'
            f'（会把 ZH 喂给 _put_audio）: {unguarded}'
        )

    def test_put_audio_audio_guard_still_in_place(self):
        """_put_audio Audio Guard 兜底防线仍存在"""
        m = re.search(r'def _put_audio\(self.*?def ', self.content, re.DOTALL)
        self.assertIsNotNone(m)
        body = m.group(0)
        self.assertIn('Audio Guard', body, '_put_audio 缺 Audio Guard 兜底')
        self.assertIn('[\\u4e00-\\u9fa5]', body, 'Audio Guard 缺中文检测正则')


# ============================================================
# c.12 — 中文 subtitle 多段排版 ║ 前缀
# ============================================================

class TestC12SubtitleMultilineBox(unittest.TestCase):
    """c.12: 所有 Subtitle print 走 _box_newline（多段 ZH 每行加 ║ 前缀）"""

    @classmethod
    def setUpClass(cls):
        cls.content = _read_nerve()

    def test_no_raw_subtitle_print_without_box_newline(self):
        """所有 print(f"...║ 📺 [Subtitle]...") 都应走 _box_newline 包裹"""
        # 旧不安全模式：print(f"\\n║ 📺  [Subtitle] {clean_zh}") 这种没 _box_newline 包裹
        bad_pattern = re.compile(
            r'print\(f"\\n?║\s*📺\s*\[Subtitle\]\s*\{',
            re.MULTILINE,
        )
        bad_matches = bad_pattern.findall(self.content)
        self.assertEqual(
            bad_matches, [],
            f'还有 {len(bad_matches)} 处 Subtitle print 没用 _box_newline 包裹：{bad_matches}'
        )

    def test_subtitle_print_uses_box_newline(self):
        """Subtitle 主路径应该走 _box_newline(f"║ 📺  [Subtitle] ...")"""
        # 至少有 4 处 _box_newline(f"║ 📺...") 调用
        m = re.findall(
            r'_box_newline\(f"║\s*📺\s*\[Subtitle\]',
            self.content,
        )
        self.assertGreaterEqual(
            len(m), 4,
            f'_box_newline 包裹的 Subtitle print 不足 4 处（找到 {len(m)} 处）',
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
