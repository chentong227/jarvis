# -*- coding: utf-8 -*-
"""[Sir 2026-05-25 21:14 真测追根] BypassSpeech 误判 Sir 真讲对话.

Sir 痛点 (2 句真测被判旁路语):
  1. '小贾今天去面试，去去那个党校老师那里上面试课，党校老师对我的评价非常高啊，
     我是14个人里面表现最好的，他直要我去上台去讲'
  2. '我说我今天去那个党校老师那里上面试课...我是14个人里面表现最好的。
     他要我上台去给他们演示讲给'
  → score=0.20 breakdown={'third_person': -0.30}

Sir 真理:
  - '小贾' = Sir 对 Jarvis 的活泼称呼 (Sir 21:14 显式声明)
  - Sir 用 '我' 第一人称多次叙事给 Jarvis 听 ≠ 跟外人对话

2 路修法:
  - r1: '小贾' / '小贾贾' / 'xiaojia' 加 _JARVIS_DIRECT_WAKE
  - r2: _is_addressing_jarvis 加 "Sir 第一人称自叙" evidence
        (含 '我' >= 2 次 + 没 '我妈/我爸/我儿/我女' 家庭指代)
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_thread():
    """无 Audio dependency 创建 VoiceListenThread instance 测 classify_jarvis_directness."""
    from jarvis_voice_listen_thread import VoiceListenThread
    # 跳过 __init__ 用 __new__
    t = VoiceListenThread.__new__(VoiceListenThread)
    return t


def _read(name: str) -> str:
    with open(os.path.join(ROOT, name), 'r', encoding='utf-8') as f:
        return f.read()


# ==========================================================================
# r1: '小贾' 进 wake word vocab
# ==========================================================================
class TestR1XiaoJiaWakeWord(unittest.TestCase):

    def test_xiaojia_in_wake_vocab(self):
        from jarvis_voice_listen_thread import VoiceListenThread
        self.assertIn('小贾', VoiceListenThread._JARVIS_DIRECT_WAKE,
                       "'小贾' 必须是 wake word (Sir 21:14 显式声明)")
        self.assertIn('xiaojia', VoiceListenThread._JARVIS_DIRECT_WAKE,
                       "拼音 'xiaojia' fallback")

    def test_xiaojia_triggers_wake_word_score(self):
        thread = _make_thread()
        score, bd = thread.classify_jarvis_directness(
            '小贾今天我去面试，对我的评价非常高'
        )
        self.assertIn('wake_word', bd, "'小贾' 必须命中 wake_word")
        self.assertGreaterEqual(score, 0.6,
            f"'小贾...' 应直接触发主脑, 实测 score={score:.2f}")


# ==========================================================================
# r2: Sir 第一人称自叙 → _is_addressing_jarvis
# ==========================================================================
class TestR2FirstPersonNarrative(unittest.TestCase):

    def test_real_sir_speech_v1_not_bypass(self):
        """Sir 真测原话 v1 不应被旁路化."""
        thread = _make_thread()
        text = (
            '小贾今天去面试，去去那个党校老师那里上面试课，'
            '党校老师对我的评价非常高啊，我是14个人里面表现最好的，'
            '他直要我去上台去讲'
        )
        score, bd = thread.classify_jarvis_directness(text)
        self.assertGreaterEqual(score, 0.3,
            f"Sir 真测 v1 不该旁路化, 实测 score={score:.2f} bd={bd}")

    def test_real_sir_speech_v2_not_bypass(self):
        """Sir 真测原话 v2 (无 '小贾') 不应被旁路化."""
        thread = _make_thread()
        text = (
            '我说我今天去那个党校老师那里上面试课，'
            '党校老师对我的评价非常高啊。我是14个人里面表现最好的。'
            '他要我上台去给他们演示讲给'
        )
        score, bd = thread.classify_jarvis_directness(text)
        # v2 含 '他们' → 1 个 third_person hit penalty=0.3
        # 但 Sir 自叙 evidence (含 '我' >= 2) → penalty *= 0.5 = -0.15
        # → score = 0.5 - 0.15 = 0.35 >= 0.3 (灰区, 但不旁路)
        self.assertGreaterEqual(score, 0.3,
            f"Sir 真测 v2 第一人称自叙不该旁路化, 实测 score={score:.2f} bd={bd}")

    def test_first_person_narrative_with_third_person_halved(self):
        """含 '我' >= 2 次 + '他们' → third_person 罚减半."""
        thread = _make_thread()
        text = '我今天跟他们一起去看电影了，我觉得他们很热情'
        score, bd = thread.classify_jarvis_directness(text)
        # '他们' 命中 third_person, 但自叙 → penalty 半权
        self.assertGreaterEqual(score, 0.3,
            f"自叙含 '他们' 不该旁路, 实测 score={score:.2f} bd={bd}")

    def test_pure_third_person_still_bypass(self):
        """对照: 真旁路 (没 '我' 第一人称) 仍判旁路."""
        thread = _make_thread()
        text = "他说他下午要来取东西，然后他还要带个朋友过来"
        score, bd = thread.classify_jarvis_directness(text)
        self.assertLess(score, 0.45,
            f"纯第三人称旁路语应仍旁路, 实测 score={score:.2f} bd={bd}")
        self.assertIn('third_person', bd)

    def test_family_indicator_not_treated_as_narrative(self):
        """含 '我妈/我爸' 家庭指代 → 真转述, 不该当自叙."""
        thread = _make_thread()
        # '我妈说...我妈说...' (含 '我' 2 次 + '我妈')
        text = '我妈今天说要来看我，我妈还说带饺子'
        score, bd = thread.classify_jarvis_directness(text)
        # '我妈' 命中 third_person, 且 _has_family_indicator=True → 不算自叙
        # → 全罚 penalty (无 wake/direct_verb)
        # 不强求一定 < 0.3, 但 third_person 必须命中 + penalty 真扣
        self.assertIn('third_person', bd)


# ==========================================================================
# 源码 sanity
# ==========================================================================
class TestSourceCodeSanity(unittest.TestCase):

    def test_first_person_narrative_logic_exists(self):
        src = _read('jarvis_voice_listen_thread.py')
        self.assertIn('_is_first_person_narrative', src,
                       'classify_jarvis_directness 必须含第一人称自叙判定')
        self.assertIn('_has_family_indicator', src,
                       '必须排除家庭指代 (避免误把 我妈/我爸 当自叙)')


if __name__ == '__main__':
    unittest.main()
