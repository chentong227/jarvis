# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 18:07 真测 anchor] ProjectHold vocab 漏 Cursor 收尾 phrase.

Sir 真测对话:
> Sir: '什么什么什么咖啡因，还有你刚刚说的什么科手，我跟你讲了那个 CORSOR 手
>       我们已经不用啦, 把它忘了好吗'
> Jarvis: 'Duly noted, Sir. I shall scrub Cursor from the active roster
>          and refrain from further mentions of its dormancy.'
> Sir 反问: '实现了吗?'

真痛 (准则 5 INTEGRITY ABSOLUTE 失败):
  Jarvis reply 'shall scrub from active roster' 是**嘴上承诺**, 真的没调
  tool_project_hold. ProjectTimeline.held_until_ts 没更新. 6h 后 SmartNudge
  还会冒 dormant_project Cursor.

根因链 (4 步全断):
  1. vocab 漏覆盖 '不用啦' / '已经不用' / '把它忘了' / '把它忘掉' / '把这忘了' /
     '忘掉吧' 6 类 Sir 收尾 phrase
  2. ProjectHoldDetector.detect_hold_phrase() = None
  3. 没 publish 'sir_intent_project_hold_candidate' SWM event
  4. IntentResolver 没看到 candidate → 没调 tool_project_hold

修法 (准则 6 vocab 范式持久化):
  memory_pool/project_hold_phrases_vocab.json 加 6 个新 phrase, 全 168h hold
  (Sir 说 '不用了/忘了' 语义远比 '放一放' 更绝, 时长长). 含指代代词锁定
  ('把它/把这') 避免误命中 'I forgot' 等无关.

测试 (8 testcase):
  T1: vocab 含 6 个新 phrase id (bu_yong_la / yi_jing_bu_yong / ba_ta_wang_le /
      ba_ta_wang_diao / ba_zhe_wang_le / wang_diao_ba)
  T2: detect_hold_phrase Sir 真话原句命中
  T3: detect_hold_phrase 短句变体 'Cursor 我们已经不用啦' 命中
  T4: detect_hold_phrase '把它忘了好吗' 命中
  T5: detect_hold_phrase '把它忘掉吧' 命中
  T6: detect_hold_phrase '忘掉吧' 命中
  T7: detect_hold_phrase '我忘了一件事' NOT 命中 (没指代代词锁定保护)
  T8: 老 case 不破 '驾照考试先放一放' / 'on hold' 仍命中
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _reload_vocab():
    """清 vocab cache 让 json 改动立刻生效."""
    import jarvis_project_hold_detector as m
    m._VOCAB_CACHE = None
    m._VOCAB_MTIME = 0


class TestVocabFix20(unittest.TestCase):
    """vocab json 加 6 个新 phrase 必存在."""

    @classmethod
    def setUpClass(cls):
        import json
        vocab_path = os.path.join(
            ROOT, 'memory_pool', 'project_hold_phrases_vocab.json'
        )
        with open(vocab_path, 'r', encoding='utf-8') as f:
            cls.data = json.load(f)
        cls.phrase_ids = {p['id'] for p in cls.data.get('phrases', [])}

    def test_t1_new_phrase_ids_exist(self):
        """6 个新 phrase id 必加入 vocab."""
        required = [
            'bu_yong_la', 'yi_jing_bu_yong',
            'ba_ta_wang_le', 'ba_ta_wang_diao',
            'ba_zhe_wang_le', 'wang_diao_ba',
        ]
        for pid in required:
            self.assertIn(pid, self.phrase_ids,
                f"phrase id '{pid}' 必加入 vocab (fix20)")

    def test_t1b_version_bumped(self):
        """version 必含 'fix20' marker."""
        ver = self.data.get('version', '')
        self.assertIn('fix20', ver,
            f"version 必 bump 含 'fix20' marker, got: {ver}")

    def test_t1c_new_phrases_all_168h(self):
        """新 6 phrase 全为 168h hold (Sir '不用了/忘了' 语义最绝)."""
        new_ids = {'bu_yong_la', 'yi_jing_bu_yong', 'ba_ta_wang_le',
                    'ba_ta_wang_diao', 'ba_zhe_wang_le', 'wang_diao_ba'}
        for p in self.data.get('phrases', []):
            if p['id'] in new_ids:
                self.assertEqual(p['default_hours'], 168,
                    f"phrase '{p['id']}' default_hours 必 168, "
                    f"got {p['default_hours']}")


class TestPhraseHitFix20(unittest.TestCase):
    """vocab 加完必命中 Sir 真话 + 变体."""

    def setUp(self):
        _reload_vocab()

    def test_t2_sir_actual_utterance_hits(self):
        """Sir 真话原句 (含 ASR 错认 'CORSOR') 必命中."""
        from jarvis_project_hold_detector import detect_hold_phrase
        cmd = ('什么什么什么咖啡因，还有你刚刚说的什么科手，'
                '我跟你讲了那个CORSOR手我们已经不用啦，把它忘了好吗')
        hit = detect_hold_phrase(cmd)
        self.assertIsNotNone(hit,
            f"Sir 真话必命中 vocab, got None: {cmd[:80]}")
        # 命中 phrase 必在新加的 6 个里
        self.assertIn(hit['phrase'],
                       ['不用啦', '已经不用', '把它忘了', '把它忘掉',
                        '把这忘了', '忘掉吧'],
                       f"命中 phrase 必为 fix20 新加, got: {hit['phrase']}")

    def test_t3_short_variant_yi_jing_bu_yong(self):
        """短句变体 1: 'Cursor 我们已经不用啦'."""
        from jarvis_project_hold_detector import detect_hold_phrase
        hit = detect_hold_phrase('Cursor 我们已经不用啦')
        self.assertIsNotNone(hit)

    def test_t4_ba_ta_wang_le_hits(self):
        """'把它忘了好吗' 必命中."""
        from jarvis_project_hold_detector import detect_hold_phrase
        hit = detect_hold_phrase('Cursor, 把它忘了好吗')
        self.assertIsNotNone(hit)
        self.assertIn(hit['phrase'], ['把它忘了'])

    def test_t5_ba_ta_wang_diao_hits(self):
        """'把它忘掉吧' 必命中."""
        from jarvis_project_hold_detector import detect_hold_phrase
        hit = detect_hold_phrase('Cursor 把它忘掉吧')
        self.assertIsNotNone(hit)
        # 命中 '把它忘掉' 或 '忘掉吧' 都 OK
        self.assertIn(hit['phrase'], ['把它忘掉', '忘掉吧'])

    def test_t6_wang_diao_ba_hits(self):
        """'忘掉吧' 短促命中 (Sir 简短指示)."""
        from jarvis_project_hold_detector import detect_hold_phrase
        hit = detect_hold_phrase('驾照, 忘掉吧')
        self.assertIsNotNone(hit)
        self.assertEqual(hit['phrase'], '忘掉吧')


class TestNoFalsePositive(unittest.TestCase):
    """误命中保护: 指代代词锁定 + project keyword 二次保护."""

    def setUp(self):
        _reload_vocab()

    def test_t7_wo_wang_le_not_hit(self):
        """'我忘了一件事' 不该命中 (代词锁定保护)."""
        from jarvis_project_hold_detector import detect_hold_phrase
        hit = detect_hold_phrase('我忘了一件事')
        # 'ba_ta_wang_le' / 'ba_zhe_wang_le' 含 '把' 前缀, 不会命中 '我忘了'
        # 'wang_diao_ba' = '忘掉吧' 也不命中 '我忘了'
        self.assertIsNone(hit,
            f"'我忘了一件事' 不该命中 (代词锁定保护失败), got: {hit}")


class TestNoRegression(unittest.TestCase):
    """老 case 不破: '放一放' / 'on hold' / '暂停' 仍命中."""

    def setUp(self):
        _reload_vocab()

    def test_t8_old_zh_phrase_still_hits(self):
        """老 zh '驾照考试先放一放呢' 仍命中 (不破 fix18)."""
        from jarvis_project_hold_detector import detect_hold_phrase
        hit = detect_hold_phrase('驾照考试先放一放呢')
        self.assertIsNotNone(hit)
        self.assertIn(hit['phrase'], ['放一放', '先放一放'])

    def test_t8b_old_en_phrase_still_hits(self):
        """老 en 'on hold' 仍命中."""
        from jarvis_project_hold_detector import detect_hold_phrase
        hit = detect_hold_phrase('Let me put driver license on hold')
        self.assertIsNotNone(hit)
        self.assertEqual(hit['phrase'], 'on hold')

    def test_t8c_old_zh_zan_ting_still_hits(self):
        """老 zh '暂停一下' 仍命中."""
        from jarvis_project_hold_detector import detect_hold_phrase
        hit = detect_hold_phrase('驾照可以暂停一下')
        self.assertIsNotNone(hit)


if __name__ == '__main__':
    unittest.main(verbosity=2)
