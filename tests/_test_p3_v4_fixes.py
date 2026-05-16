"""P3 / R7-β post-test v4 修复测试。

跑法：
    cd d:\\Jarvis
    python tests/_test_p3_v4_fixes.py

覆盖 Sir 23:00-23:04 实测发现的 5 个问题修复：
1. UnboundLocalError: 'command' referenced before assignment（调音量失败崩溃）
2. Backchannel 本地补位罐头话（"One moment, Sir."）→ 完全禁用 + chime 阈值从 0.6s 提到 1.5s
3. BrowserDucking 状态去重 + 限频 → 不再刷屏
4. AFK 返回问候 → 全部走 LLM 动态生成（不再罐头）
5. 海马体 NULL 向量补 embedding → 冷却结束后台 worker 自动补
6. ASR 幻觉 "I am" / "thank you" / "bye" 加入 ghost_hallucinations 过滤
"""
import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestUnboundCommandFix(unittest.TestCase):
    """[v4-1] continuation_prompt 引用 command 时如果 command 未定义会崩。
    必须在 try 之前预置默认值 + JSON 解析独立 except 提前 continue。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_command_predefined_before_try(self):
        # 必须在 try 之前给 command 兜底
        m = re.search(
            r"command\s*=\s*'<malformed_fast_call>'.*?try:\s*\n\s*(?:import json|call_data\s*=)",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "command 必须在 try 之前预置默认值，防止 json.loads 抛异常时 continuation_prompt 引用 UnboundLocal")

    def test_json_loads_has_dedicated_except(self):
        # json.loads 必须有专属 except，命中后 continue，不让流程走到 continuation_prompt
        self.assertIn('FAST_CALL JSON 解析失败', self.src,
                      "json.loads 必须有专属错误日志")
        # 命中 except 必须 continue 而非 fall through
        m = re.search(
            r"FAST_CALL JSON 解析失败.*?continue",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "JSON 解析失败的 except 分支必须 continue，不能让流程走到 continuation_prompt")


class TestBackchannelDisabledLocalUtterance(unittest.TestCase):
    """[v4-2] _LOCAL_UTTERANCE_ENABLED=False + chime 阈值 1.5s"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_local_utterance_disabled_class_const(self):
        self.assertIn('_LOCAL_UTTERANCE_ENABLED = False', self.src)

    def test_chime_threshold_default_15s(self):
        self.assertIn('_CHIME_THRESHOLD_DEFAULT = 1.5', self.src)

    def test_maybe_say_local_short_circuits(self):
        # _maybe_say_local 必须先查 _LOCAL_UTTERANCE_ENABLED 并 return
        m = re.search(
            r"def _maybe_say_local.*?_LOCAL_UTTERANCE_ENABLED.*?return",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "_maybe_say_local 必须先查 _LOCAL_UTTERANCE_ENABLED 否则不发声")

    def test_stream_chat_uses_chime_const(self):
        # stream_chat 入口调用必须用 self._CHIME_THRESHOLD_DEFAULT
        self.assertIn('threshold_sec=self._CHIME_THRESHOLD_DEFAULT', self.src,
                      "stream_chat 必须用 _CHIME_THRESHOLD_DEFAULT 而不是字面 0.6")


class TestBrowserDuckingStateDedup(unittest.TestCase):
    """[v4-3] BrowserDucking 状态去重 + 限频"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_state_global_dict_exists(self):
        self.assertIn('_BROWSER_DUCKING_STATE', self.src)
        self.assertIn("'currently_ducked'", self.src)
        self.assertIn("'last_action_time'", self.src)

    def test_lock_protects_state(self):
        self.assertIn('_BROWSER_DUCKING_LOCK', self.src)

    def test_same_state_short_circuits(self):
        # 同状态必须 return 直接跳过实际 COM 枚举
        m = re.search(
            r"_BROWSER_DUCKING_STATE\['currently_ducked'\]\s*==\s*target_state.*?return",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "set_browser_ducking 同状态请求必须 return 不动作")

    def test_anti_jitter_200ms_window(self):
        # 200ms 内重复触发视为抖动
        self.assertRegex(self.src, r"now\s*-\s*_BROWSER_DUCKING_STATE\['last_action_time'\]\s*<\s*0\.2",
                         "必须有 200ms 抖动过滤")


class TestAfkGreetingDynamicLLM(unittest.TestCase):
    """[v4-4] AFK 返回问候 → 全部走 LLM"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_first_active_today_uses_llm(self):
        # first_active_today=True 时也走 LLM（不再走罐头）
        m = re.search(
            r"if self\.first_active_today:.*?is_first_today\s*=\s*True.*?use_llm\s*=\s*True",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "first_active_today=True 必须 use_llm=True")

    def test_afk_above_900s_uses_llm(self):
        # AFK > 900s（15 min）也走 LLM
        m = re.search(
            r"elif afk_duration > 900:.*?use_llm\s*=\s*True",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "AFK > 15 min 必须 use_llm=True，不再走 4 小时门槛")

    def test_return_greeting_directive_references_stm(self):
        # return_greeting prompt 必须强调"reference STM"
        self.assertIn('references the actual work', self.src,
                      "return_greeting 必须强调引用 STM 实际工作内容")
        self.assertIn('ONE sentence under 12 words', self.src,
                      "return_greeting 必须强调克制（一句话，<12 词）")


class TestHippocampusBackfillWorker(unittest.TestCase):
    """[v4-5] 海马体 NULL 向量 backfill worker"""

    @classmethod
    def setUpClass(cls):
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'jarvis_hippocampus.py'))
        with open(path, 'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_backfill_worker_method_exists(self):
        self.assertIn('def _start_backfill_worker', self.src)
        self.assertIn('def _run_backfill_batch', self.src)

    def test_worker_started_in_init(self):
        # __init__ 必须启动 backfill worker
        m = re.search(
            r"def __init__.*?self\._start_backfill_worker\(\)",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "Hippocampus.__init__ 必须启动 _start_backfill_worker")

    def test_worker_is_daemon(self):
        self.assertIn('daemon=True', self.src)
        self.assertIn("name='HippocampusBackfill'", self.src)

    def test_backfill_respects_cooldown(self):
        # [P0-7 / 2026-05-15] worker 内必须先查 _is_embed_in_cooldown，冷却中跳过
        # 新版结构：cooldown 时 time.sleep(tick_interval) + continue
        m = re.search(
            r"if self\._is_embed_in_cooldown\(\):\s*\n\s*time\.sleep\(tick_interval\)\s*\n\s*continue",
            self.src,
        )
        self.assertIsNotNone(m,
            "backfill worker 必须先查冷却状态")

    def test_backfill_batch_size_limited(self):
        # 每轮 max_per_batch=20 防止单次太久
        self.assertIn('max_per_batch: int = 20', self.src,
                      "默认 max_per_batch=20 防止单次卡死 API")

    def test_backfill_handles_403_midway(self):
        # 补 embedding 过程中再次 403 必须重新进冷却 + break
        m = re.search(
            r"_NON_RETRYABLE_KEYWORDS\).*?_mark_embed_failed.*?break",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "backfill 中途 403 必须重新进冷却 + 终止本轮")

    def test_backfill_emits_progress_log(self):
        self.assertIn('Embedding Backfill', self.src,
                      "backfill 必须 bg_log 进度")


class TestBackfillRuntime(unittest.TestCase):
    """[v4-5 runtime] 实际跑一次 backfill batch 验证逻辑"""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test_backfill.db')
        from jarvis_hippocampus import Hippocampus
        self.h = Hippocampus(db_path=self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_backfill_skips_when_in_cooldown(self):
        # 强制冷却
        self.h._embed_cooldown_until = time.time() + 60.0
        filled = self.h._run_backfill_batch(max_per_batch=5)
        # 冷却期间 _run_backfill_batch 本身不查 cooldown（worker 在调用前查），
        # 但因为没 key router 也没真 client，必然 0
        self.assertEqual(filled, 0)

    def test_backfill_empty_db_returns_zero(self):
        # 空库
        filled = self.h._run_backfill_batch(max_per_batch=5)
        self.assertEqual(filled, 0,
                         "空库 backfill 应当返回 0")

    def test_backfill_with_null_vectors_no_key_router(self):
        """有 NULL 向量记忆但没 key_router → 静默退出（不抛异常）"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO TaskMemories
            (timestamp, environment, user_intent, macro_goal, execution_summary,
             raw_actions, semantic_embedding, memory_type, entities_json, is_future_task, trigger_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            time.time(), 'CHAT', '测试意图', '测试目标', '测试摘要',
            '[]', None, 'CHAT', '{}', 0, 0.0,
        ))
        conn.commit()
        conn.close()

        # 无 key_router + 无 api_key → 静默 0，不抛
        # （实际跑时会 _get_key_and_client 失败 → return 0）
        filled = self.h._run_backfill_batch(max_per_batch=5)
        # 期望 0，但不应抛
        self.assertIsInstance(filled, int)


class TestAsrGhostHallucinationExpanded(unittest.TestCase):
    """[v4-6] ASR ghost_hallucinations 加入 'I am' / 'thank you' / 'bye'"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_iam_in_hallucinations(self):
        for phrase in ('"i am.", "i am"', '"thank you.", "thank you"', '"bye.", "bye"'):
            self.assertIn(phrase, self.src,
                          f"ghost_hallucinations 必须包含 {phrase}")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestUnboundCommandFix),
        loader.loadTestsFromTestCase(TestBackchannelDisabledLocalUtterance),
        loader.loadTestsFromTestCase(TestBrowserDuckingStateDedup),
        loader.loadTestsFromTestCase(TestAfkGreetingDynamicLLM),
        loader.loadTestsFromTestCase(TestHippocampusBackfillWorker),
        loader.loadTestsFromTestCase(TestBackfillRuntime),
        loader.loadTestsFromTestCase(TestAsrGhostHallucinationExpanded),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] All P3/v4 fix tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
