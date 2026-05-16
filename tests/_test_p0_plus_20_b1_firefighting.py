# -*- coding: utf-8 -*-
"""[P0+20-β.1 / 2026-05-16] Phase 1 救火 5 修回归测试

覆盖（基于 Sir 12:43 实测 jarvis_20260516_123813.log 暴露的 BUG B1-B7）：
- B1 → F2: sanitize_trigger_time（时间默认推断按动词上下文 + 当前小时）
- B2 → F3: detect_semantic_category（睡觉 vs 起床等性质守卫）
- B3 → F4: 自我打断白名单（"不对不对" + "我我X"）pattern 不该误触发拒绝
- B7 → F5: KeyRouter 永久剔除持久化（重启后 dead 状态保留 + reset_permanent_death）

规范：详 AGENTS.md + docs/JARVIS_WORKFLOW_PROTOCOL.md
"""
import json
import os
import re
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_worker import sanitize_trigger_time, detect_semantic_category
from jarvis_key_router import KeyRouter


# ============================================================
# F2 / B1: sanitize_trigger_time
# ============================================================
class TestF2SanitizeTriggerTime(unittest.TestCase):
    """治 B1: Sir 12:43 说"两点起床" → 上游 LLM 给凌晨 02:00 → 应矫正成今天 14:00"""

    def test_daytime_wake_force_today_pm(self):
        """白天 + 起床 + 上游给凌晨 → 矫正成今天下午"""
        # 模拟当前 hour 12-18（中午说"两点起床"）：上游 02:00 → 14:00
        out, was, reason = sanitize_trigger_time(
            '2026-05-17 02:00:00', '两点起床', '我两点起床'
        )
        if 6 <= time.localtime().tm_hour <= 18:
            self.assertTrue(was, f"白天起床+凌晨小时应矫正，结果={out}")
            self.assertEqual(reason, 'daytime_wake_force_today_pm')
            self.assertIn('14:00', out)
        else:
            pass

    def test_pm_marker_force(self):
        """显式说"下午两点起床" + 上游给凌晨 → PM marker 强制 +12"""
        out, was, reason = sanitize_trigger_time(
            '2026-05-17 02:00:00', '两点起床', '我下午两点起床'
        )
        self.assertTrue(was)
        self.assertEqual(reason, 'pm_marker_force')
        self.assertIn('14:00', out)

    def test_am_marker_force(self):
        """显式说"明天早上两点" + 上游给 14:00 → AM marker 强制 -12"""
        out, was, reason = sanitize_trigger_time(
            '2026-05-17 14:00:00', '起床', '明天早上两点起床'
        )
        self.assertTrue(was)
        self.assertEqual(reason, 'am_marker_force')
        self.assertIn('02:00', out)

    def test_wake_verb_force_am_when_no_pm(self):
        """起床 + 上游给 14:00 + 没说 PM → 推到 next morning 02:00"""
        out, was, reason = sanitize_trigger_time(
            '2026-05-17 14:00:00', '两点起床', '我两点起床'
        )
        self.assertTrue(was)
        self.assertEqual(reason, 'wake_verb_force_am')
        self.assertIn('02:00', out)

    def test_sleep_verb_force_next_morning(self):
        """白天说睡觉 + 上游给 14:00 → 推到次日 02:00"""
        out, was, reason = sanitize_trigger_time(
            '2026-05-16 14:00:00', '睡觉', '我两点睡觉'
        )
        if 6 <= time.localtime().tm_hour <= 21:
            self.assertTrue(was)
            self.assertEqual(reason, 'sleep_verb_force_next_morning')
            self.assertIn('02:00', out)

    def test_today_pm_marker_no_correction(self):
        """显式 "今天下午两点睡觉" + 上游给 14:00 → 不矫正"""
        out, was, reason = sanitize_trigger_time(
            '2026-05-16 14:00:00', '午睡', '今天下午两点睡觉'
        )
        self.assertFalse(was, f"今天下午明示不应矫正，结果={out} reason={reason}")

    def test_no_intent_no_correction(self):
        """没有动词上下文 → 不矫正"""
        out, was, _ = sanitize_trigger_time(
            '2026-05-17 02:00:00', '随便', '随便说说'
        )
        self.assertFalse(was)
        self.assertEqual(out, '2026-05-17 02:00:00')

    def test_empty_input(self):
        """空输入 → 不崩 + 不矫正"""
        out, was, _ = sanitize_trigger_time('', '', '')
        self.assertFalse(was)

    def test_invalid_format_input(self):
        """非法格式 → 不崩 + 不矫正"""
        out, was, _ = sanitize_trigger_time('not-a-date', '起床', '我起床')
        self.assertFalse(was)


# ============================================================
# F3 / B2: detect_semantic_category
# ============================================================
class TestF3SemanticCategory(unittest.TestCase):
    """治 B2: Memory Correction 把"两点起床" → "两点睡觉"，性质完全不同"""

    def test_wake_category(self):
        for t in ['两点起床', '8点起床', 'wake up at 7', 'get up early']:
            self.assertEqual(detect_semantic_category(t), 'wake', f"{t} 应识别为 wake")

    def test_sleep_category(self):
        for t in ['两点睡觉', '11点睡', 'sleep early', 'go to bed', '休息一下']:
            self.assertEqual(detect_semantic_category(t), 'sleep', f"{t} 应识别为 sleep")

    def test_eat_category(self):
        for t in ['吃午饭', '吃晚饭', 'lunch at noon', 'eat dinner', '吃药']:
            self.assertEqual(detect_semantic_category(t), 'eat', f"{t} 应识别为 eat")

    def test_work_category(self):
        for t in ['开会', '加班到晚上', 'write code', 'meeting at 3']:
            self.assertEqual(detect_semantic_category(t), 'work', f"{t} 应识别为 work")

    def test_misc_for_unknown(self):
        for t in ['散步', '看小说', '看电影']:
            self.assertEqual(detect_semantic_category(t), 'misc', f"{t} 应识别为 misc")

    def test_wake_vs_sleep_different_categories(self):
        """B2 核心：起床 vs 睡觉 必须不同类别 → 触发 Memory Correction Guard"""
        self.assertNotEqual(
            detect_semantic_category('两点起床'),
            detect_semantic_category('两点睡觉'),
        )

    def test_same_intent_different_time_same_category(self):
        """8点起床 vs 9点起床 → 同类别，允许替换"""
        self.assertEqual(
            detect_semantic_category('8点起床'),
            detect_semantic_category('9点起床'),
        )


# ============================================================
# F4 / B3: 自我打断白名单 pattern
# ============================================================
class TestF4SelfInterruptionPatterns(unittest.TestCase):
    """治 B3: Sir 自我打断"不对不对，我我两点起床"被误判拒绝帮助"""

    PATTERNS = [
        r'不对不对',
        r'不是不是',
        r'不不不',
        r'(?:no\s+){2,}',
        r'我我[^\s,，。.]',
        r'(我要|我想|我得|我会|我得).{0,12}(跟你|和你|给你|对你|跟我自己).{0,3}说',
        r'(?:wait|hold|hang)\s+on',
        r'let\s+me\s+(say|tell|explain|finish)',
        r'(等[一下下]|等等|等我说)',
        r'(?:um|uh|er|呃|嗯).{0,6}我',
    ]

    def _matched(self, text):
        return any(re.search(p, text.lower()) for p in self.PATTERNS)

    def test_sir_real_case_matches(self):
        """Sir 12:43 实测原话必须命中至少 1 个 self-interrupt pattern"""
        sir_text = "跟我说说啊，不对不对不对，不用不用跟我说，我我要跟你说，我我两点起床"
        self.assertTrue(self._matched(sir_text), "Sir 实测自我打断原话应命中 pattern")

    def test_strong_refusal_not_matched(self):
        """硬拒绝词不应命中自我打断 → 走原拒绝路径"""
        for text in ['shut up', 'leave me alone', 'stop offering', '不要再提']:
            self.assertFalse(self._matched(text), f"{text} 是强拒绝，不应被自我打断白名单跳过")

    def test_normal_no_match(self):
        """普通 affirmation 不应命中"""
        for text in ['ok', 'sounds good', '好的', '是的']:
            self.assertFalse(self._matched(text), f"{text} 不应命中自我打断 pattern")

    def test_wait_let_me_explain(self):
        self.assertTrue(self._matched('wait, let me explain'))
        self.assertTrue(self._matched('hang on, let me say something'))


# ============================================================
# F5 / B7: KeyRouter 永久剔除持久化
# ============================================================
class TestF5KeyRouterPersistence(unittest.TestCase):
    """治 B7: google_1 永久剔除状态写盘 → 重启后保留"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix='kr_test_')
        self._statefile = os.path.join(self._tmpdir, 'key_router_state.json')
        # patch class attribute so KeyRouter writes/reads from tmp file
        self._orig_path = KeyRouter._STATE_FILE_PATH
        KeyRouter._STATE_FILE_PATH = self._statefile

    def tearDown(self):
        KeyRouter._STATE_FILE_PATH = self._orig_path
        try:
            if os.path.exists(self._statefile):
                os.remove(self._statefile)
            os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_no_state_file_no_dead(self):
        kr = KeyRouter('main_k', ['k1', 'k2'], ['o1'])
        for label in ['google_1', 'google_2']:
            self.assertFalse(kr.is_permanently_dead(label))

    def test_3_permission_errors_triggers_permanent_death_and_writes_disk(self):
        kr = KeyRouter('main_k', ['k1', 'k2'], ['o1'])
        for _ in range(3):
            kr.report_error('google_1', 'permission_denied: project has been denied')
        self.assertTrue(kr.is_permanently_dead('google_1'))
        self.assertTrue(os.path.exists(self._statefile))
        with open(self._statefile, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        self.assertIn('google_1', payload['permanently_dead'])

    def test_restart_loads_dead_state(self):
        """模拟重启：第一个实例标 dead → 写盘 → 第二个实例读取 → 仍 dead"""
        kr1 = KeyRouter('main_k', ['k1', 'k2'], ['o1'])
        for _ in range(3):
            kr1.report_error('google_1', 'permission_denied: project has been denied')
        self.assertTrue(kr1.is_permanently_dead('google_1'))

        kr2 = KeyRouter('main_k', ['k1', 'k2'], ['o1'])
        self.assertTrue(kr2.is_permanently_dead('google_1'),
                        "重启后应从 disk 恢复永久死亡标记")
        self.assertFalse(kr2.is_permanently_dead('google_2'))

    def test_reset_permanent_death(self):
        """Sir rotate key 后调 reset_permanent_death → 清空磁盘 + 状态"""
        kr = KeyRouter('main_k', ['k1', 'k2'], ['o1'])
        for _ in range(3):
            kr.report_error('google_1', 'permission_denied')
        self.assertTrue(kr.is_permanently_dead('google_1'))

        ok = kr.reset_permanent_death('google_1')
        self.assertTrue(ok)
        self.assertFalse(kr.is_permanently_dead('google_1'))

        with open(self._statefile, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        self.assertNotIn('google_1', payload.get('permanently_dead', {}))

    def test_reset_invalid_label(self):
        kr = KeyRouter('main_k', ['k1'], ['o1'])
        self.assertFalse(kr.reset_permanent_death('nonexistent_label'))

    def test_reset_when_not_dead(self):
        kr = KeyRouter('main_k', ['k1'], ['o1'])
        self.assertFalse(kr.reset_permanent_death('google_1'))


if __name__ == '__main__':
    unittest.main()
