# -*- coding: utf-8 -*-
"""[P0+20-β.2.7.10 / 2026-05-17] 焦点退出"小心翼翼"痛点修复

Sir 反馈: 焦点期间打电话/和家人说话/视频音被录入 → 触发 Jarvis. 不想小心翼翼.

3 层防御:
- L1 旁路语过滤 (classify_jarvis_directness score < 0.3)
- L2 显式 dismiss 词 + ASR mute 30s
- L3 动态 TIMEOUT 缩放 (连续 3 次旁路 → TIMEOUT 30s→8s)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestClassifyJarvisDirectness(unittest.TestCase):
    """classify_jarvis_directness 启发式打分"""

    def setUp(self):
        from jarvis_worker import VoiceListenThread
        # 不用真 __init__ (会启动 daemon), 只取 classmethod
        self.cls = VoiceListenThread

    def _score(self, text):
        # 用一个最小 dummy instance 调
        from jarvis_worker import VoiceListenThread
        inst = VoiceListenThread.__new__(VoiceListenThread)
        return inst.classify_jarvis_directness(text)

    # === 高分 (jarvis-direct) ===
    def test_wake_word_direct(self):
        score, bd = self._score("Jarvis 帮我开 cursor")
        self.assertGreaterEqual(score, 0.7)
        self.assertIn('wake_word', bd)

    def test_zh_direct_verb(self):
        score, bd = self._score("帮我查一下天气")
        self.assertGreaterEqual(score, 0.6)
        self.assertIn('zh_direct_verb', bd)

    def test_en_direct_verb(self):
        score, bd = self._score("Tell me what time it is")
        self.assertGreaterEqual(score, 0.6)
        self.assertIn('en_direct_verb', bd)

    def test_remind_me(self):
        score, _ = self._score("提醒我 9 点睡觉")
        self.assertGreaterEqual(score, 0.6)

    # === 低分 (旁路语) ===
    def test_phone_opener_en(self):
        score, bd = self._score("Hello? Can you hear me?")
        self.assertLess(score, 0.3)
        self.assertIn('phone_opener', bd)

    def test_phone_opener_zh(self):
        score, bd = self._score("喂，你好，听得到吗")
        self.assertLess(score, 0.3)
        self.assertIn('phone_opener', bd)

    def test_third_person_with_long(self):
        score, bd = self._score("他说他下午要来取东西，然后他还要带个朋友过来")
        self.assertLess(score, 0.45)
        self.assertIn('third_person', bd)

    def test_short_filler(self):
        """极短助词 (嗯/对/好) 默认旁路"""
        for filler in ['嗯', '对', '好']:
            score, bd = self._score(filler)
            self.assertLess(score, 0.45, f"'{filler}' 应识为旁路语")

    def test_conversational_marker(self):
        """'我和我妈说话呢' 类对外信号"""
        score, bd = self._score("我和我妈说话呢，等会儿再聊")
        self.assertLess(score, 0.4)
        self.assertIn('conversational_marker', bd)

    # === 灰区 (0.3-0.6, 仍触发但 log) ===
    def test_neutral_question_grayzone(self):
        """中性陈述 (无 wake 无 verb) — 灰区"""
        score, _ = self._score("今天天气好像不错")
        self.assertGreaterEqual(score, 0.3)
        self.assertLess(score, 0.6)


class TestStopCommandExpanded(unittest.TestCase):
    """β.2.7.10 扩 STRICT_STOP_WORDS 含 dismiss 类语义"""

    def setUp(self):
        from jarvis_worker import VoiceListenThread
        self.inst = VoiceListenThread.__new__(VoiceListenThread)

    def test_phone_call_dismiss(self):
        """'我去打电话' / 'taking a call' 立刻停"""
        for txt in ['我去打电话', '我在打电话', "I'm taking a call",
                     '我和我妈说话', '我跟我妈说话']:
            self.assertTrue(
                self.inst.detect_stop_command(txt),
                f"'{txt}' 应识为 stop_command"
            )

    def test_done_dismiss(self):
        """'好的就这样' / 'OK that's all'"""
        for txt in ['好的就这样', "ok that's all", '就这样吧']:
            self.assertTrue(
                self.inst.detect_stop_command(txt),
                f"'{txt}' 应识为 stop_command"
            )

    def test_normal_chat_not_stop(self):
        """普通对话不应误触"""
        for txt in ['我们今天讨论什么呢', '你帮我看看这个']:
            self.assertFalse(
                self.inst.detect_stop_command(txt),
                f"'{txt}' 不应识为 stop_command"
            )


if __name__ == '__main__':
    unittest.main(verbosity=2)
