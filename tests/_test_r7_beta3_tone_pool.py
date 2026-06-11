"""R7-β3 单元测试：ToneSelector 8 档 tone 池 + 硬触发词

跑法：
    cd d:\\Jarvis
    python tests/_test_r7_beta3_tone_pool.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jarvis_utils import (
    ToneSelector, ALL_TONES, TONE_DRY, TONE_PLAYFUL, TONE_CONCERNED,
    TONE_MOCK_FORMAL, TONE_UNDERSTATED, TONE_WRY, TONE_TENDER, TONE_DRY_WITTY,
    TONE_DESCRIPTIONS, TONE_HARD_TRIGGERS,
    get_default_tone_selector,
)


class TestToneConstants(unittest.TestCase):
    def test_eight_tones_defined(self):
        self.assertEqual(len(ALL_TONES), 8)
        for t in ALL_TONES:
            self.assertIn(t, TONE_DESCRIPTIONS)

    def test_all_descriptions_non_trivial(self):
        for t, desc in TONE_DESCRIPTIONS.items():
            self.assertGreater(len(desc), 20, f"{t} 描述太短")


class TestHardTriggers(unittest.TestCase):
    def setUp(self):
        self.ts = ToneSelector()

    def test_fuck_triggers_dry_witty(self):
        for phrase in ("That's fucking broken.", "fuck this", "what the fuck",
                       "fucking hell"):
            with self.subTest(phrase=phrase):
                tone, _ = self.ts.select(phrase)
                self.assertEqual(tone, TONE_DRY_WITTY, f"'{phrase}' 应切 dry-witty")

    def test_zh_swear_triggers_dry_witty(self):
        for phrase in ("操，又崩了", "卧槽这什么破玩意", "我去这也行", "尼玛的"):
            with self.subTest(phrase=phrase):
                tone, _ = self.ts.select(phrase)
                self.assertEqual(tone, TONE_DRY_WITTY, f"'{phrase}' 应切 dry-witty")

    def test_damn_triggers_dry_witty(self):
        tone, _ = self.ts.select("damn it")
        self.assertEqual(tone, TONE_DRY_WITTY)

    def test_non_swear_does_not_trigger(self):
        tone, _ = self.ts.select("Please open the file.", hour=14)
        self.assertNotEqual(tone, TONE_DRY_WITTY)


class TestLedgerEmotion(unittest.TestCase):
    def setUp(self):
        self.ts = ToneSelector()

    def test_frustrated_in_daytime_concerned(self):
        tone, _ = self.ts.select("the build is broken", ledger_data={'emotion': 'Frustrated'}, hour=14)
        self.assertEqual(tone, TONE_CONCERNED)

    def test_frustrated_at_night_tender(self):
        tone, _ = self.ts.select("still stuck", ledger_data={'emotion': 'Frustrated'}, hour=2)
        self.assertEqual(tone, TONE_TENDER)

    def test_happy_playful(self):
        tone, _ = self.ts.select("nice", ledger_data={'mood': 'Happy'}, hour=15)
        self.assertEqual(tone, TONE_PLAYFUL)

    def test_focused_stays_dry(self):
        tone, _ = self.ts.select("open D drive", ledger_data={'current_emotion': 'Focused'}, hour=15)
        self.assertEqual(tone, TONE_DRY)

    def test_hard_trigger_overrides_emotion(self):
        """硬触发优先级 > ledger 情绪。"""
        tone, _ = self.ts.select("fuck this build", ledger_data={'emotion': 'Frustrated'}, hour=2)
        self.assertEqual(tone, TONE_DRY_WITTY,
                         "硬触发应该胜过 ledger emotion")


class TestTimeOfDay(unittest.TestCase):
    """无 ledger 情绪、无硬触发的默认时段倾向。"""

    def setUp(self):
        # 用一个独特字符串避免随机化把 dry → playful 翻
        # 'aabbccdd' 的 hash 不容易触发 15% 概率
        self.ts = ToneSelector()
        self.unique_input = "neutral filler text that hashes to nowhere"

    def test_late_night_understated(self):
        # 0-5 点；hash 可能 15% 概率切 playful，所以 assertIn
        tone, _ = self.ts.select(self.unique_input, hour=3)
        self.assertIn(tone, (TONE_UNDERSTATED, TONE_PLAYFUL))

    def test_morning_mock_formal(self):
        tone, _ = self.ts.select(self.unique_input, hour=8)
        # 可能被 15% 随机切到 playful，需要稳定 input
        self.assertIn(tone, (TONE_MOCK_FORMAL, TONE_PLAYFUL))

    def test_evening_wry(self):
        tone, _ = self.ts.select(self.unique_input, hour=20)
        self.assertIn(tone, (TONE_WRY, TONE_PLAYFUL))

    def test_midnight_understated(self):
        # hash 可能 15% 概率切 playful
        tone, _ = self.ts.select(self.unique_input, hour=23)
        self.assertIn(tone, (TONE_UNDERSTATED, TONE_PLAYFUL))


class TestRenderDirective(unittest.TestCase):
    def test_renders(self):
        ts = ToneSelector()
        directive = ts.render_directive(TONE_DRY, TONE_DESCRIPTIONS[TONE_DRY])
        self.assertIn('[TONE DIRECTIVE]:', directive)
        self.assertIn('dry', directive)

    def test_empty_returns_empty(self):
        ts = ToneSelector()
        self.assertEqual(ts.render_directive('', ''), '')


class TestSingleton(unittest.TestCase):
    def test_singleton(self):
        a = get_default_tone_selector()
        b = get_default_tone_selector()
        self.assertIs(a, b)


class TestSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_central_nerve_instantiates_tone_selector(self):
        self.assertRegex(
            self.src,
            r'self\.tone_selector\s*=\s*ToneSelector\(\)',
            "CentralNerve 必须实例化 self.tone_selector"
        )

    def test_full_prompt_has_tone_directive(self):
        self.assertIn('{tone_directive}', self.src,
                      "full prompt 必须含 {tone_directive} 占位")

    def test_short_chat_has_tone(self):
        # SHORT_CHAT 分支应当也注入 tone
        # 🆕 [fixT-r7 / Sir 2026-06-11 裁决I 修轨] M6.2 tier 体抽 helper, 双锚现代化.
        m_dispatch = re.search(
            r"if prompt_tier == self\.PROMPT_TIER_SHORT_CHAT:.+?"
            r"_assemble_short_chat_prompt",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m_dispatch, "SHORT_CHAT dispatch 必须接 helper")
        m = re.search(
            r"def _assemble_short_chat_prompt.+?_short_tone",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "SHORT_CHAT 必须注入 _short_tone")

    def test_factual_recall_has_tone(self):
        # 🆕 [fixT-r7] 同款双锚现代化 (M6.2 FACTUAL_RECALL 抽 helper).
        m_dispatch = re.search(
            r"if prompt_tier == self\.PROMPT_TIER_FACTUAL_RECALL:.+?"
            r"_assemble_factual_recall_prompt",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m_dispatch, "FACTUAL_RECALL dispatch 必须接 helper")
        m = re.search(
            r"def _assemble_factual_recall_prompt.+?_fr_tone",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "FACTUAL_RECALL 必须注入 _fr_tone")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestToneConstants),
        loader.loadTestsFromTestCase(TestHardTriggers),
        loader.loadTestsFromTestCase(TestLedgerEmotion),
        loader.loadTestsFromTestCase(TestTimeOfDay),
        loader.loadTestsFromTestCase(TestRenderDirective),
        loader.loadTestsFromTestCase(TestSingleton),
        loader.loadTestsFromTestCase(TestSourceContract),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] All R7-β3/TonePool tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
