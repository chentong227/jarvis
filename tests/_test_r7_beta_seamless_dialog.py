"""R7-β post-test v2 单元测试：无缝对话 + 长期记忆兜底 + 主动 nudge ducking。

跑法：
    cd d:\\Jarvis
    python tests/_test_r7_beta_seamless_dialog.py

覆盖：
- 修 1: 本地"说一句话"二档 backchannel（TTFT > 2.5s 触发 vocal.say）
- 修 2: 海马体冷却期间 search 走 fuzzy 兜底 + seal 仍写 SQLite（NULL 向量）
- 修 3: 主动 nudge 路径调 set_browser_ducking(True/False)
- 修 4: 字幕 clear 时不立即清空文本（让 fade 真正起效）
- 修 5: SHORT_CHAT + FACTUAL_RECALL 档也 bg_log tone
"""
import os
import re
import sys
import time
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestLocalUtteranceBackchannel(unittest.TestCase):
    """修 1：本地说一句话二档 backchannel。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_local_utterance_pool_defined(self):
        self.assertIn('_LOCAL_UTTERANCE_POOL', self.src)
        for category in ('tool', 'recall', 'query', 'casual'):
            self.assertIn(f"'{category}'", self.src,
                          f"_LOCAL_UTTERANCE_POOL 必须包含 '{category}' 类别")

    def test_pick_local_utterance_method(self):
        self.assertIn('def _pick_local_utterance', self.src)

    def test_local_utterance_timer_field(self):
        self.assertIn('self._local_utterance_timer', self.src)
        self.assertIn('self._local_utterance_in_progress', self.src)

    def test_start_backchannel_starts_local_utterance_timer(self):
        # [v5 Sir-2026-05-14] chime Timer 已删除；只保留 local_utterance Timer（虽然 _LOCAL_UTTERANCE_ENABLED=False）
        m = re.search(
            r"def _start_backchannel_timer.*?self\._local_utterance_timer\s*=\s*threading\.Timer",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
                             "_start_backchannel_timer 必须启动 local_utterance Timer（chime Timer v5 已删）")

    def test_chime_timer_removed(self):
        # [v5] chime Timer 的创建语句不应再出现
        m = re.search(
            r"def _start_backchannel_timer.*?self\._backchannel_timer\s*=\s*threading\.Timer",
            self.src, re.DOTALL,
        )
        self.assertIsNone(m,
                          "v5: chime Timer (_backchannel_timer = threading.Timer) 应已被移除")

    def test_local_utterance_uses_vocal_play_only(self):
        # [轴 2.4 / 2026-05-15] _maybe_say_local 改用 vocal.play_only(pcm) 播预渲 PCM 池
        # 不再用 vocal.say (同步 render + play 0.8-1.2s 阻塞)；预渲池零延迟
        m = re.search(
            r"_maybe_say_local.*?self\.vocal\.play_only\(pcm\)",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "[轴 2.4] _maybe_say_local 必须改用 vocal.play_only(pcm) 播预渲 PCM 池")

    def test_local_phrase_pool_warmup_registers_echo(self):
        # [轴 2.4] 预渲短句池在 _warmup_local_phrase_pool 时统一 register_jarvis_tts
        # 取代 v3 在 _maybe_say_local 内单条 register
        m = re.search(
            r"def _warmup_local_phrase_pool.*?register_jarvis_tts\(text\)",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "[轴 2.4] _warmup_local_phrase_pool 必须 register_jarvis_tts 防 ASR 拾回")

    def test_local_utterance_threshold_2_5s(self):
        # 默认 local_utterance_threshold = 2.5
        self.assertIn('local_utterance_threshold: float = 2.5', self.src)

    def test_mark_first_token_cancels_both_timers(self):
        # _mark_first_token 必须 cancel chime + local utterance 两个 timer
        m = re.search(
            r"def _mark_first_token.*?self\._backchannel_timer\.cancel.*?self\._local_utterance_timer\.cancel",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
                             "_mark_first_token 必须 cancel 两个 timer")


class TestHippocampusFuzzyFallback(unittest.TestCase):
    """修 2：海马体冷却期间 search 走 fuzzy 兜底 + seal 仍写 SQLite。"""

    def setUp(self):
        from jarvis_hippocampus import Hippocampus
        self.tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self.tmpdir, 'test.db')
        self.h = Hippocampus(db_path=db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fuzzy_fallback_method_exists(self):
        self.assertTrue(hasattr(self.h, '_fuzzy_fallback_search'))

    def test_fuzzy_search_returns_relevant_memories_in_cooldown(self):
        # 先手动插入两条记忆
        import sqlite3
        conn = sqlite3.connect(self.h.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO TaskMemories
            (timestamp, environment, user_intent, macro_goal, execution_summary,
             raw_actions, semantic_embedding, memory_type, entities_json,
             is_future_task, trigger_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            time.time(), 'CHAT', '帮我调一下音量', '调音量',
            'Done, Sir. Set volume to 30%.', '[]', None, 'CHAT', '{}', 0, 0.0,
        ))
        cursor.execute('''
            INSERT INTO TaskMemories
            (timestamp, environment, user_intent, macro_goal, execution_summary,
             raw_actions, semantic_embedding, memory_type, entities_json,
             is_future_task, trigger_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            time.time(), 'CHAT', '打开浏览器', '打开 chrome',
            'Browser opened.', '[]', None, 'CHAT', '{}', 0, 0.0,
        ))
        conn.commit()
        conn.close()
        # 强制冷却
        self.h._embed_cooldown_until = time.time() + 60.0
        # 查询"音量"应当命中第一条
        results = self.h.search_memory(query='音量', top_k=3)
        self.assertGreater(len(results), 0, "冷却期 fuzzy 检索必须能找到相关记忆")
        self.assertTrue(any('音量' in r['intent'] for r in results),
                        "fuzzy 检索应该命中 intent 含'音量'的记忆")

    def test_fuzzy_search_returns_empty_on_irrelevant_query(self):
        self.h._embed_cooldown_until = time.time() + 60.0
        results = self.h.search_memory(query='完全不相关的查询关键词xyz123')
        # 没匹配上，返回空
        self.assertEqual(results, [])

    def test_seal_chat_still_writes_in_cooldown(self):
        """冷却期间 seal_chat 仍写 SQLite（用 NULL 向量），不丢长期记忆。"""
        self.h._embed_cooldown_until = time.time() + 60.0
        # seal 一条
        self.h.seal_chat_async(api_key='fake', user_input='测试输入',
                                jarvis_reply='测试回复',
                                memory_protocol={'memory_type': 'CHAT'})
        # 等异步写入完成
        time.sleep(0.6)
        # 数据库应有这条
        import sqlite3
        conn = sqlite3.connect(self.h.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT user_intent, execution_summary, semantic_embedding "
                       "FROM TaskMemories WHERE user_intent = ?", ('测试输入',))
        row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(row, "冷却期 seal_chat 必须仍写 SQLite")
        # semantic_embedding 应为 NULL（冷却期没调 embedding）
        self.assertIsNone(row[2], "冷却期写入的 semantic_embedding 必须是 NULL")


class TestActiveNudgeDucking(unittest.TestCase):
    """修 3：主动 nudge 路径调 set_browser_ducking。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_nudge_voice_path_ducks_before_say(self):
        # __NUDGE__ 的 VOICE 分支必须在 stream_nudge 前 set_browser_ducking(True)
        m = re.search(
            r"VOICE 档：保持原行为.*?set_browser_ducking\(True\).*?stream_nudge",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
                             "VOICE 档 nudge 必须在 stream_nudge 前 set_browser_ducking(True)")

    def test_nudge_voice_path_unducks_after(self):
        # 必须在 finally 里安排延迟恢复
        m = re.search(
            r"stream_nudge.*?finally.*?set_browser_ducking\(False\)",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
                             "VOICE 档 nudge 完成后必须恢复浏览器音量")


class TestSubtitleClearKeepContentForFade(unittest.TestCase):
    """修 4：字幕 clear 时不立即清空文本（让 fade 真起作用）。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_clear_outside_focus_only_targets_opacity(self):
        """非焦点模式 clear 时只改 target_opacity，不立即 _en_words = []。"""
        # 找到 'if lang == "clear":' 分支
        m = re.search(
            r'if lang == "clear":(.+?)elif lang ==',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m)
        body = m.group(1)
        # 非 focus 分支应当只设 target_opacity，不直接 _en_words = []
        non_focus_block = re.search(
            r"if not self\._focus_mode:(.+?)else:",
            body, re.DOTALL,
        )
        self.assertIsNotNone(non_focus_block, "clear 必须区分焦点/非焦点路径")
        non_focus_body = non_focus_block.group(1)
        self.assertIn('_target_opacity = 0.0', non_focus_body)
        # 非焦点分支不该立即清空 _en_words（让 _fade_step 在 opacity 到 0 时再清）
        self.assertNotIn('_en_words = []', non_focus_body,
                         "非焦点 clear 路径不该立即清空 _en_words，否则字幕瞬间消失看不到淡出")


class TestToneLogInShortChatAndFactual(unittest.TestCase):
    """修 5：SHORT_CHAT + FACTUAL_RECALL 档也 bg_log tone。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_short_chat_tone_log(self):
        self.assertIn('tier=SHORT_CHAT', self.src,
                      "SHORT_CHAT 档 tone 必须 bg_log")

    def test_factual_recall_tone_log(self):
        self.assertIn('tier=FACTUAL_RECALL', self.src,
                      "FACTUAL_RECALL 档 tone 必须 bg_log")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestLocalUtteranceBackchannel),
        loader.loadTestsFromTestCase(TestHippocampusFuzzyFallback),
        loader.loadTestsFromTestCase(TestActiveNudgeDucking),
        loader.loadTestsFromTestCase(TestSubtitleClearKeepContentForFade),
        loader.loadTestsFromTestCase(TestToneLogInShortChatAndFactual),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] All R7-β seamless dialog tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
