"""R7-β post-test 修复套件：Sir 20:05-20:28 实测发现的 6 个问题。

跑法：
    cd d:\\Jarvis
    python tests/_test_r7_beta_post_test_fixes.py

覆盖：
- 修 1: Backchannel chime 换 C5+E5 大三度音色（不是堵塞嘟声）
- 修 2: Hippocampus 403 → 60s embedding 冷却（不再刷屏）
- 修 3: 用户"不需要帮助" → freeze NudgeGate 5 分钟（不止看 stm[-1]）
- 修 4: 焦点结束 / stop / dismiss 时清空字幕；新一轮 user 输入也清旧字幕
- 修 5: tone 选择 → bg_log
- 修 6: verbosity cap 变化 → bg_log
"""
import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestBackchannelChimeAudioCharacter(unittest.TestCase):
    """修 1 → v5：backchannel chime 整体移除（与 play_acknowledgment_chime 重复）。
    
    [Sir-2026-05-14] '留大的前面那个叮' → 保留 play_acknowledgment_chime；
    删除 v4 加的小叮（_generate_backchannel_pcm + _maybe_play_chime）。
    本套件转为验证 chime **真的被移除** + acknowledgment_chime 还活着。
    """

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_backchannel_pcm_method_removed(self):
        self.assertNotIn('def _generate_backchannel_pcm', self.src,
                         "v5: _generate_backchannel_pcm 应被移除")

    def test_play_chime_closure_removed(self):
        self.assertNotIn('def _maybe_play_chime', self.src,
                         "v5: _maybe_play_chime 内嵌闭包应被移除")

    def test_acknowledgment_chime_preserved(self):
        # play_acknowledgment_chime（大叮）必须保留
        self.assertIn('def play_acknowledgment_chime', self.src,
                      "play_acknowledgment_chime 必须保留（Sir：留大的前面那个叮）")
        # 它应仍然合成 C5 (523.25) + E5 (659.25)
        m = re.search(
            r"def play_acknowledgment_chime\(self\):.*?523\.25.*?659\.25",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
                             "play_acknowledgment_chime 必须包含 C5+E5 大三度合成")


class TestHippocampusEmbeddingCircuit(unittest.TestCase):
    """修 2：403 PERMISSION_DENIED → 60s 冷却。"""

    def setUp(self):
        from jarvis_hippocampus import Hippocampus
        # 用临时 db，避免污染线上
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self.tmpdir, 'test.db')
        self.h = Hippocampus(db_path=db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_circuit_constants_defined(self):
        from jarvis_hippocampus import Hippocampus
        self.assertGreater(Hippocampus._EMBED_COOLDOWN_SECONDS, 0)
        self.assertIn('403', Hippocampus._NON_RETRYABLE_KEYWORDS)
        self.assertIn('permission_denied', Hippocampus._NON_RETRYABLE_KEYWORDS)

    def test_initially_not_in_cooldown(self):
        self.assertFalse(self.h._is_embed_in_cooldown())

    def test_403_triggers_cooldown(self):
        self.h._mark_embed_failed(
            "403 PERMISSION_DENIED. Your project has been denied access."
        )
        self.assertTrue(self.h._is_embed_in_cooldown())

    def test_network_error_does_not_trigger_cooldown(self):
        self.h._mark_embed_failed("Connection reset by peer (network blip)")
        self.assertFalse(self.h._is_embed_in_cooldown())

    def test_billing_error_triggers_cooldown(self):
        self.h._mark_embed_failed("billing not enabled for this project")
        self.assertTrue(self.h._is_embed_in_cooldown())

    def test_search_memory_returns_empty_in_cooldown(self):
        # 强制进入冷却
        self.h._embed_cooldown_until = time.time() + 60.0
        result = self.h.search_memory(api_key='fake', query='test')
        self.assertEqual(result, [], "冷却期内 search_memory 必须返回空列表，不调 API")

    def test_seal_chat_async_skips_in_cooldown(self):
        # 强制冷却 → seal_chat_async 应当立即返回不抛
        self.h._embed_cooldown_until = time.time() + 60.0
        try:
            self.h.seal_chat_async(api_key='fake', user_input='x', jarvis_reply='y')
        except Exception as e:
            self.fail(f"冷却期内 seal_chat_async 应当静默返回，不该抛：{e}")


class TestHelpRefusalSweep(unittest.TestCase):
    """修 3：用户拒绝信号 → freeze NudgeGate。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_detect_help_refusal_scans_recent_5_stm(self):
        # 旧版只看 stm[-1]；新版必须扫 stm[-5:]
        self.assertIn('stm[-5:]', self.src,
                      "_detect_help_refusal 必须扫 stm[-5:] 而非只看 stm[-1]")

    def test_detect_help_refusal_freezes_nudge_gate(self):
        m = re.search(
            r"def _detect_help_refusal.+?nudge_gate\.freeze_for\(",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
                             "_detect_help_refusal 必须调 nudge_gate.freeze_for")

    def test_refusal_patterns_include_chinese(self):
        # _GENERIC_REFUSAL_PATTERNS 必须含中文常用拒绝词
        for kw in ('不需要', '不用', '不需要你的帮助', '别再提'):
            with self.subTest(kw=kw):
                self.assertIn(f'"{kw}"', self.src,
                              f"拒绝词典必须含 '{kw}'")

    def test_refusal_publishes_help_refused_event(self):
        m = re.search(
            r"def _detect_help_refusal.+?'help_refused'",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
                             "_detect_help_refusal 必须 publish help_refused 到 event_bus")

    def test_refusal_distinguishes_strong_vs_weak_signal(self):
        # 强信号（最近 5 条 STM 有 offer_help）→ 300s
        # 弱信号 → 90s
        self.assertIn('had_offer_help', self.src,
                      "必须区分强/弱拒绝信号")
        # 300.0 / 90.0 任一出现
        self.assertTrue(
            ('300.0' in self.src and '90.0' in self.src),
            "强/弱信号需要不同的 freeze 时长（300s / 90s）"
        )


class TestSubtitleClearOnFocusEnd(unittest.TestCase):
    """修 4：焦点结束 / stop / dismiss / timeout 时清空字幕；新 user 也清旧字幕。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_timeout_path_clears_subtitle(self):
        # 用 DOTALL 让 . 匹配 \n，避免非贪婪 + 多行的踩坑
        m = re.search(
            r"active_timeout.*?_subtitle_queue\.put\(\(['\"]clear['\"]",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m, "焦点超时路径必须 push ('clear', '')")
        # 距离不应太远（避免误匹配其他段落）
        self.assertLess(len(m.group(0)), 1500,
                        "active_timeout 到 clear push 之间距离应在 1500 字以内")

    def test_stop_command_path_clears_subtitle(self):
        # 找 `if self.detect_stop_command(clean_text):` 的 call site，再找 clear push
        m = re.search(
            r"if self\.detect_stop_command\(clean_text\):.*?_subtitle_queue\.put\(\(['\"]clear['\"]",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m, "stop_cmd 路径必须清字幕")
        self.assertLess(len(m.group(0)), 2000)

    def test_dismiss_path_emits_focus_false(self):
        m = re.search(
            r"if self\.in_active_conversation and self\.detect_dismiss_command\(clean_text\):.*?_subtitle_queue\.put\(\(['\"]focus['\"]\s*,\s*False",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m, "dismiss 路径必须 push ('focus', False)")
        self.assertLess(len(m.group(0)), 2000)

    def test_user_lang_clears_old_subtitles(self):
        # 新一轮 'user' lang 进来时必须清空 _en_words / _zh_text
        m = re.search(
            r'elif lang == "user":(.+?)elif lang ==',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn('self._en_words = []', body,
                      "新 user 输入必须清空 _en_words")
        self.assertIn('self._zh_text = ""', body,
                      "新 user 输入必须清空 _zh_text")


class TestTonePromptLog(unittest.TestCase):
    """修 5：tone 选择 → bg_log。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_tone_bg_log_present(self):
        self.assertRegex(
            self.src,
            r'bg_log\(f"🎭 \[Tone\] \{tone_id\}',
            "tone 选择必须 bg_log，方便 Sir 复盘"
        )


class TestVerbosityCapLog(unittest.TestCase):
    """修 6：verbosity cap 变化 → bg_log。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_verbosity_cap_change_logged(self):
        self.assertRegex(
            self.src,
            r'bg_log\(f"📏 \[Verbosity\] cap_sentences',
            "verbosity cap 变化必须 bg_log"
        )


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestBackchannelChimeAudioCharacter),
        loader.loadTestsFromTestCase(TestHippocampusEmbeddingCircuit),
        loader.loadTestsFromTestCase(TestHelpRefusalSweep),
        loader.loadTestsFromTestCase(TestSubtitleClearOnFocusEnd),
        loader.loadTestsFromTestCase(TestTonePromptLog),
        loader.loadTestsFromTestCase(TestVerbosityCapLog),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] All R7-β post-test fix tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
