# -*- coding: utf-8 -*-
"""[Gap-Z1 / β.5.46-fix4 / 2026-05-21 23:15] STM Reply Summarizer 测试.

Sir 23:14 真凶: Jarvis 仅听 wake word "he" 即翻 4% backspace + 0.01% 老账.
治本: post-stream async LLM 压缩 STM 自身 reply, 下轮主脑看 brief, 不翻.

测试覆盖:
- TestA: config 加载 + fallback
- TestB: should_summarize 阈值
- TestC: summarize_async 不阻塞 (启 thread)
- TestD: in-place 修改 entry['jarvis']
- TestE: env JARVIS_STM_SUMMARIZE=0 时 disabled
- TestF: short reply 不压缩 (skip_short)
- TestG: jarvis_raw 备份保留 (debug 用)
- TestH: stats 累加正确
- TestI: register/get singleton
"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_stm_summarizer import (
    STMSummarizer,
    is_enabled,
    get_default_summarizer,
    register_summarizer,
    reset_default_summarizer_for_test,
    reset_cache_for_test,
    _load_config,
)


class TestA_ConfigLoad(unittest.TestCase):
    """config 加载 + fallback."""

    def test_config_loads_from_json(self):
        cfg = _load_config()
        self.assertIn('enabled', cfg)
        self.assertIn('min_chars_to_summarize', cfg)
        self.assertIn('max_summary_chars', cfg)
        self.assertIn('model', cfg)
        # 默认 ON
        self.assertTrue(cfg['enabled'])

    def test_config_has_correct_defaults(self):
        cfg = _load_config()
        # config 应符合 fallback 同 schema
        self.assertGreaterEqual(cfg['min_chars_to_summarize'], 50)
        self.assertGreaterEqual(cfg['max_summary_chars'], 50)


class TestB_ShouldSummarizeThreshold(unittest.TestCase):
    """长 reply 应压, 短 reply 应跳."""

    def setUp(self):
        reset_cache_for_test()

    def test_long_reply_should_summarize(self):
        s = STMSummarizer()
        long_reply = "I should clarify some specific percentages I mentioned earlier. " * 20
        self.assertTrue(s.should_summarize(long_reply))

    def test_short_reply_should_not_summarize(self):
        s = STMSummarizer()
        self.assertFalse(s.should_summarize("Yes, Sir."))
        self.assertFalse(s.should_summarize("I'm here."))

    def test_empty_should_not_summarize(self):
        s = STMSummarizer()
        self.assertFalse(s.should_summarize(""))
        self.assertFalse(s.should_summarize(None))


class TestC_SummarizeAsyncNonBlocking(unittest.TestCase):
    """summarize_async 立即返回, 不阻塞."""

    def setUp(self):
        reset_cache_for_test()

    def test_async_returns_immediately(self):
        s = STMSummarizer()
        entry = {'time': '12:00:00', 'user': 'test', 'jarvis': 'long reply ' * 30}
        t_start = time.time()
        s.summarize_async(
            entry_ref=entry,
            sir_utterance='test',
            raw_reply='long reply ' * 30,
            turn_id='turn_test_123',
        )
        elapsed = time.time() - t_start
        # 应 < 50ms 返回 (thread 启动)
        self.assertLess(elapsed, 0.5,
                        '应 fire-and-forget, 不阻塞调用者')


class TestD_InPlaceModification(unittest.TestCase):
    """summarize 完成后 in-place 修改 entry['jarvis']."""

    def setUp(self):
        reset_cache_for_test()
        reset_default_summarizer_for_test()

    def test_entry_modified_after_summarize(self):
        # mock LLM 返回 brief summary
        s = STMSummarizer()
        entry = {
            'time': '12:00:00',
            'user': 'evaluate analysis',
            'jarvis': 'I should clarify percentages I mentioned earlier ' * 10,
        }
        original_reply = entry['jarvis']
        # mock summarize 直接返 brief
        with mock.patch.object(s, 'summarize', return_value='discussed evaluation; gave balanced view'):
            s.summarize_async(
                entry_ref=entry,
                sir_utterance='evaluate analysis',
                raw_reply=original_reply,
                turn_id='turn_d_1',
            )
            # 等 thread 完成
            time.sleep(0.3)
        # entry['jarvis'] 应被替换
        self.assertEqual(entry['jarvis'], 'discussed evaluation; gave balanced view',
                         'in-place 替换应生效')
        # raw 备份保留
        self.assertEqual(entry.get('jarvis_raw'), original_reply,
                         '原始 reply 应保留在 jarvis_raw')
        # 标记 flag
        self.assertTrue(entry.get('stm_summarized'),
                        '应有 stm_summarized=True flag')


class TestE_EnvDisabled(unittest.TestCase):
    """env JARVIS_STM_SUMMARIZE=0 时 disabled."""

    def test_env_zero_disables(self):
        with mock.patch.dict(os.environ, {'JARVIS_STM_SUMMARIZE': '0'}):
            self.assertFalse(is_enabled())

    def test_env_one_enables(self):
        with mock.patch.dict(os.environ, {'JARVIS_STM_SUMMARIZE': '1'}):
            self.assertTrue(is_enabled())

    def test_env_unset_falls_back_to_config(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('JARVIS_STM_SUMMARIZE', None)
            # config 默认 ON
            self.assertTrue(is_enabled())


class TestF_SkipShort(unittest.TestCase):
    """短 reply 走 skip 路径, stats 累加."""

    def setUp(self):
        reset_cache_for_test()

    def test_short_reply_increments_stats(self):
        s = STMSummarizer()
        entry = {'jarvis': 'OK'}
        s.summarize_async(entry, '', 'OK', turn_id='t1')
        time.sleep(0.1)
        stats = s.stats()
        self.assertGreaterEqual(stats['skipped_short'], 1)
        self.assertEqual(stats['compressed'], 0)


class TestG_RawBackup(unittest.TestCase):
    """jarvis_raw 备份用于 debug / 回溯."""

    def setUp(self):
        reset_cache_for_test()

    def test_raw_preserved_after_summarize(self):
        s = STMSummarizer()
        original = 'A specific over-claim about 4% with details ' * 10
        entry = {'jarvis': original}
        with mock.patch.object(s, 'summarize', return_value='compressed brief'):
            s.summarize_async(entry, 'sir said', original, 't_g_1')
            time.sleep(0.3)
        # 压缩后 jarvis 是 brief, raw 是原始
        self.assertEqual(entry['jarvis'], 'compressed brief')
        self.assertEqual(entry['jarvis_raw'], original)


class TestH_StatsAccumulation(unittest.TestCase):
    """stats 计数器累加正确."""

    def setUp(self):
        reset_cache_for_test()

    def test_stats_dict_keys(self):
        s = STMSummarizer()
        stats = s.stats()
        for k in ('total_calls', 'compressed', 'skipped_short',
                  'skipped_disabled', 'failed_llm', 'cache_hits'):
            self.assertIn(k, stats, f'stats 应含 {k} 计数')

    def test_total_calls_increments(self):
        s = STMSummarizer()
        entry = {'jarvis': 'OK'}
        s.summarize_async(entry, '', 'OK', turn_id='t_h_1')
        s.summarize_async(entry, '', 'OK', turn_id='t_h_2')
        time.sleep(0.1)
        self.assertGreaterEqual(s.stats()['total_calls'], 2)


class TestI_Singleton(unittest.TestCase):
    """global summarizer singleton."""

    def setUp(self):
        reset_default_summarizer_for_test()

    def test_get_default_initially_none(self):
        self.assertIsNone(get_default_summarizer())

    def test_register_and_get(self):
        s = STMSummarizer()
        register_summarizer(s)
        self.assertIs(get_default_summarizer(), s)

    def tearDown(self):
        reset_default_summarizer_for_test()


class TestJ_StaticIntegrationCheck(unittest.TestCase):
    """central_nerve + jarvis_worker 真接入 STMSummarizer."""

    def test_central_nerve_registers_summarizer(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('from jarvis_stm_summarizer import STMSummarizer', src,
                       'central_nerve 应 import STMSummarizer')
        self.assertIn('register_summarizer', src,
                       'central_nerve 应 register summarizer')
        self.assertIn('self.stm_summarizer', src,
                       'central_nerve 应保存 self.stm_summarizer')

    def test_worker_calls_summarize_async(self):
        import jarvis_worker
        with open(jarvis_worker.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('from jarvis_stm_summarizer import get_default_summarizer', src,
                       'worker 应 import get_default_summarizer')
        self.assertIn('summarize_async', src,
                       'worker 应调 summarize_async')
        # 至少在 3 处 STM append 加 hook
        hook_count = src.count('summarize_async(')
        self.assertGreaterEqual(hook_count, 3,
                                 f'STM append 至少 3 处加 hook, 实际 {hook_count}')


if __name__ == '__main__':
    unittest.main()
