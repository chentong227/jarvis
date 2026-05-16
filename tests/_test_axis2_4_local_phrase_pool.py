"""轴 2.4 单元测试：本地短句 PCM 池 —— 取代 v3 罐头随机抽

[Sir-2026-05-15] v3/v4 罐头池被 Sir 反馈"语气割裂、内容不相关"全局禁用。
2.4 重写为：
- 启动时 vocal.render_only() 预渲 5 句 PCM 入内存
- TTFT > 2.5s 时按 prompt_tier 选 phrase → vocal.play_only(pcm) 零延迟
- 路由：TOOL_REQUEST→on_it / DEEP_QUERY→one_moment / FACTUAL_RECALL→pulling_up

跑法：
    cd d:\\Jarvis
    python tests/_test_axis2_4_local_phrase_pool.py
"""
import os
import re
import sys
import time
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class _MockVocal:
    """假 VocalCord：render_only 返回伪 PCM bytes；play_only 计数。"""
    def __init__(self):
        self.render_calls = []
        self.play_calls = []
        self._render_delay = 0.01

    def render_only(self, text: str):
        self.render_calls.append(text)
        time.sleep(self._render_delay)
        # 返回伪 PCM bytes（带 text 的 hash 让每条 phrase 内容不同）
        return f"PCM:{text}".encode('utf-8')

    def play_only(self, audio_bytes: bytes):
        self.play_calls.append(audio_bytes)


class _MockSubtitleQueue:
    def __init__(self):
        self.items = []
    def put(self, item):
        self.items.append(item)


class _MockBypass:
    """轻量 ChatBypass mock —— 复用 ChatBypass 真实方法。"""
    def __init__(self):
        from jarvis_nerve import ChatBypass
        self.vocal = _MockVocal()
        self.subtitle_queue = _MockSubtitleQueue()
        self._first_token_received = False
        self._backchannel_timer = None
        self._local_utterance_timer = None
        self._local_utterance_in_progress = False
        self.is_interrupted = False
        self.jarvis = None
        # 真实类常量
        self._LOCAL_PHRASE_POOL_SPEC = ChatBypass._LOCAL_PHRASE_POOL_SPEC
        self._LOCAL_PHRASE_TIER_ROUTE = ChatBypass._LOCAL_PHRASE_TIER_ROUTE
        self._LOCAL_PHRASE_THRESHOLD = ChatBypass._LOCAL_PHRASE_THRESHOLD
        self._LOCAL_PHRASE_POOL_ENABLED = ChatBypass._LOCAL_PHRASE_POOL_ENABLED
        self._LOCAL_UTTERANCE_ENABLED = ChatBypass._LOCAL_UTTERANCE_ENABLED
        self._LOCAL_UTTERANCE_POOL = ChatBypass._LOCAL_UTTERANCE_POOL
        # 池字段
        self._local_phrase_pool = {}
        self._local_phrase_pool_lock = threading.Lock()
        self._local_phrase_pool_ready = False
        # 绑真实方法
        self._warmup_local_phrase_pool = lambda: ChatBypass._warmup_local_phrase_pool(self)
        self._get_local_phrase_for_tier = (
            lambda tier: ChatBypass._get_local_phrase_for_tier(self, tier)
        )
        self._start_backchannel_timer = (
            lambda *a, **kw: ChatBypass._start_backchannel_timer(self, *a, **kw)
        )
        self._mark_first_token = lambda: ChatBypass._mark_first_token(self)
        self._pick_local_utterance = (
            lambda *a, **kw: ChatBypass._pick_local_utterance(self, *a, **kw)
        )


class TestWarmupPool(unittest.TestCase):
    """预渲池：启动后 _local_phrase_pool 含 5 条 PCM。"""

    def test_warmup_renders_all_phrases(self):
        bypass = _MockBypass()
        bypass._warmup_local_phrase_pool()
        self.assertTrue(bypass._local_phrase_pool_ready)
        self.assertEqual(len(bypass._local_phrase_pool), len(bypass._LOCAL_PHRASE_POOL_SPEC))
        # vocal.render_only 应被调 5 次
        self.assertEqual(len(bypass.vocal.render_calls), 5)

    def test_pool_contains_expected_keys(self):
        bypass = _MockBypass()
        bypass._warmup_local_phrase_pool()
        expected_keys = {'on_it', 'one_moment', 'pulling_up', 'bear_with', 'let_me_see'}
        self.assertEqual(set(bypass._local_phrase_pool.keys()), expected_keys)

    def test_pool_entries_are_pcm_and_text(self):
        bypass = _MockBypass()
        bypass._warmup_local_phrase_pool()
        for key, val in bypass._local_phrase_pool.items():
            self.assertIsInstance(val, tuple)
            self.assertEqual(len(val), 2)
            pcm, text = val
            self.assertIsInstance(pcm, bytes)
            self.assertIsInstance(text, str)
            self.assertGreater(len(pcm), 0)
            self.assertGreater(len(text), 0)


class TestTierRouting(unittest.TestCase):
    """按 prompt_tier 路由到正确的 phrase。"""

    def setUp(self):
        self.bypass = _MockBypass()
        self.bypass._warmup_local_phrase_pool()

    def test_tool_request_picks_on_it(self):
        """[P0+18-a.9 / 2026-05-15] Sir 反馈 "On it, Sir." 在 Fast Path 反而割裂
        → TOOL_REQUEST 改成 None（不补位）。"""
        picked = self.bypass._get_local_phrase_for_tier('TOOL_REQUEST')
        self.assertIsNone(picked,
            "P0+18-a.9 后 TOOL_REQUEST 不再补位")

    def test_deep_query_picks_one_moment(self):
        picked = self.bypass._get_local_phrase_for_tier('DEEP_QUERY')
        self.assertIsNotNone(picked)
        _, text = picked
        self.assertIn('One moment', text)

    def test_critical_does_not_use_local_phrase(self):
        """[P0+15 / 2026-05-15] 同步 P0-5 路由：CRITICAL 档不再补本地短句
        （Sir 实测反馈"罐头话语气割裂"）。`_LOCAL_PHRASE_TIER_ROUTE['CRITICAL'] = None`，
        本地池不出声，让 CRITICAL 档完全交给云端 LLM 一气呵成。"""
        picked = self.bypass._get_local_phrase_for_tier('CRITICAL')
        self.assertIsNone(picked, "P0-5 后 CRITICAL 档不补位本地短句")

    def test_factual_recall_picks_pulling_up(self):
        picked = self.bypass._get_local_phrase_for_tier('FACTUAL_RECALL')
        self.assertIsNotNone(picked)
        _, text = picked
        self.assertIn('Pulling', text)

    def test_short_chat_returns_none(self):
        self.assertIsNone(self.bypass._get_local_phrase_for_tier('SHORT_CHAT'))

    def test_wake_only_returns_none(self):
        self.assertIsNone(self.bypass._get_local_phrase_for_tier('WAKE_ONLY'))

    def test_unknown_tier_falls_back_to_let_me_see(self):
        picked = self.bypass._get_local_phrase_for_tier('SOMETHING_NEW')
        self.assertIsNotNone(picked)
        _, text = picked
        # 默认 let_me_see
        self.assertIn('Let me see', text)


class TestPhrasePoolNotReadyFallback(unittest.TestCase):
    """池未预渲完时 _get_local_phrase 返回 None（不报错）。"""

    def test_returns_none_when_not_ready(self):
        bypass = _MockBypass()
        # 不调 warmup，池保持 not ready
        self.assertIsNone(bypass._get_local_phrase_for_tier('TOOL_REQUEST'))


class TestTimerPlaysPcm(unittest.TestCase):
    """运行时：timer 触发时按 tier 播放 PCM 池里对应 phrase。"""

    def test_timer_plays_correct_phrase(self):
        """[P0+18-a.9 / 2026-05-15] TOOL_REQUEST 改成 None 后该 tier 不补位。
        改用 DEEP_QUERY tier 验证 timer 仍能正确按 tier 播 PCM。"""
        bypass = _MockBypass()
        bypass._warmup_local_phrase_pool()
        bypass._start_backchannel_timer(
            threshold_sec=2.0,
            local_utterance_threshold=0.1,  # 100ms 后就触发
            prompt_tier='DEEP_QUERY',
        )
        time.sleep(0.4)
        # play_only 应被调 1 次（DEEP_QUERY 仍补位 "One moment, Sir."）
        self.assertEqual(len(bypass.vocal.play_calls), 1)
        # 播放的 PCM 应是 one_moment 这条
        pcm = bypass.vocal.play_calls[0]
        self.assertIn(b'One moment', pcm)

    def test_short_chat_no_play(self):
        bypass = _MockBypass()
        bypass._warmup_local_phrase_pool()
        bypass._start_backchannel_timer(
            threshold_sec=2.0,
            local_utterance_threshold=0.1,
            prompt_tier='SHORT_CHAT',
        )
        time.sleep(0.4)
        # SHORT_CHAT 不补位 → play_only 不应被调
        self.assertEqual(len(bypass.vocal.play_calls), 0)

    def test_first_token_cancels(self):
        bypass = _MockBypass()
        bypass._warmup_local_phrase_pool()
        bypass._start_backchannel_timer(
            threshold_sec=2.0,
            local_utterance_threshold=0.5,
            prompt_tier='TOOL_REQUEST',
        )
        time.sleep(0.1)
        bypass._mark_first_token()
        time.sleep(0.7)
        # 首 token 到了 → 不应播
        self.assertEqual(len(bypass.vocal.play_calls), 0)


class TestSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # [P0+19-7 / 2026-05-16] ChatBypass 已搬到 jarvis_chat_bypass.py，扫 corpus
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        cls.src = read_nerve_corpus()

    def test_phrase_pool_enabled_const(self):
        self.assertIn('_LOCAL_PHRASE_POOL_ENABLED = True', self.src)

    def test_pool_spec_defined(self):
        self.assertIn('_LOCAL_PHRASE_POOL_SPEC', self.src)
        self.assertIn("'on_it'", self.src)
        self.assertIn("'one_moment'", self.src)
        self.assertIn("'pulling_up'", self.src)

    def test_tier_route_defined(self):
        self.assertIn('_LOCAL_PHRASE_TIER_ROUTE', self.src)
        self.assertIn("'TOOL_REQUEST'", self.src)
        self.assertIn("'DEEP_QUERY'", self.src)

    def test_warmup_method_defined(self):
        self.assertIn('def _warmup_local_phrase_pool', self.src)

    def test_get_phrase_method_defined(self):
        self.assertIn('def _get_local_phrase_for_tier', self.src)

    def test_stream_chat_passes_tier_to_timer(self):
        # stream_chat 入口 _start_backchannel_timer 必须传 prompt_tier
        self.assertRegex(
            self.src,
            r'_start_backchannel_timer\([^)]*prompt_tier=prompt_tier',
        )


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestWarmupPool),
        loader.loadTestsFromTestCase(TestTierRouting),
        loader.loadTestsFromTestCase(TestPhrasePoolNotReadyFallback),
        loader.loadTestsFromTestCase(TestTimerPlaysPcm),
        loader.loadTestsFromTestCase(TestSourceContract),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] 轴 2.4 Local Phrase Pool tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
