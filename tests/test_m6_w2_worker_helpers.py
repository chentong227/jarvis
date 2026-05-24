# -*- coding: utf-8 -*-
"""[Reshape M6.W2 / 2026-05-24 18:00] worker_helpers 抽出验证.

抽出的 fn:
  - sanitize_trigger_time
  - detect_semantic_category + _SEMANTIC_CATEGORIES

向后兼容验证:
  - jarvis_worker_helpers 直接 import OK
  - jarvis_worker re-export 仍 work (老 caller `from jarvis_worker import ...`)
  - 行为与抽出前一致 (regression)
"""
from __future__ import annotations
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestM6W2WorkerHelpersSplit(unittest.TestCase):
    """W2 抽出: sanitize_trigger_time + detect_semantic_category 走 jarvis_worker_helpers."""

    def test_helpers_module_importable(self):
        """jarvis_worker_helpers 直接 import."""
        import jarvis_worker_helpers as h
        self.assertTrue(hasattr(h, 'sanitize_trigger_time'))
        self.assertTrue(hasattr(h, 'detect_semantic_category'))
        self.assertTrue(hasattr(h, '_SEMANTIC_CATEGORIES'))

    def test_worker_reexport_backward_compat(self):
        """from jarvis_worker import ... 老 caller 仍 work."""
        from jarvis_worker import (
            sanitize_trigger_time, detect_semantic_category, _SEMANTIC_CATEGORIES,
        )
        from jarvis_worker_helpers import (
            sanitize_trigger_time as h_st,
            detect_semantic_category as h_dc,
            _SEMANTIC_CATEGORIES as h_cat,
        )
        # re-export 必须是同一对象
        self.assertIs(sanitize_trigger_time, h_st)
        self.assertIs(detect_semantic_category, h_dc)
        self.assertIs(_SEMANTIC_CATEGORIES, h_cat)

    def test_sanitize_trigger_time_wake_pm_force_am(self):
        """起床动词 + LLM 给 14:00 → 强制改 02:00 (am)."""
        from jarvis_worker_helpers import sanitize_trigger_time
        # 14:00 起床 + 没 PM marker → AM
        out, was, reason = sanitize_trigger_time(
            '2026-05-24 14:00:00', 'set wake alarm', '两点起床'
        )
        self.assertTrue(was)
        self.assertEqual(reason, 'wake_verb_force_am')
        self.assertIn('02:00:00', out)

    def test_sanitize_trigger_time_short_input(self):
        """太短的 trigger_time_str → 不矫正."""
        from jarvis_worker_helpers import sanitize_trigger_time
        out, was, _ = sanitize_trigger_time('', '', '')
        self.assertFalse(was)
        out, was, _ = sanitize_trigger_time('short', '', '')
        self.assertFalse(was)

    def test_detect_semantic_category_basic(self):
        """各类别基本命中."""
        from jarvis_worker_helpers import detect_semantic_category
        self.assertEqual(detect_semantic_category('明天早上起床'), 'wake')
        self.assertEqual(detect_semantic_category('我去睡觉了'), 'sleep')
        self.assertEqual(detect_semantic_category('吃晚饭'), 'eat')
        self.assertEqual(detect_semantic_category('开会'), 'work')
        self.assertEqual(detect_semantic_category('做题'), 'study')
        self.assertEqual(detect_semantic_category('健身'), 'sport')
        self.assertEqual(detect_semantic_category('剪视频'), 'video')

    def test_detect_semantic_category_misc_and_priority(self):
        """无类别 → misc; 同时含 wake+sleep → wake (默认起床闹钟)."""
        from jarvis_worker_helpers import detect_semantic_category
        self.assertEqual(detect_semantic_category(''), 'misc')
        self.assertEqual(detect_semantic_category('随便聊聊'), 'misc')
        # 含 'wake' 和 'sleep' 都能命中 — 起床+睡觉 边界 case
        out = detect_semantic_category('起床睡觉')
        self.assertEqual(out, 'wake')


class TestM6W3TierKeywordsAlias(unittest.TestCase):
    """W3 抽出: TIER_*_KEYWORDS 4 lists 走 jarvis_worker_helpers."""

    def test_tier_lists_in_helpers(self):
        """4 个 list 都 export from helpers."""
        from jarvis_worker_helpers import (
            TIER_CRITICAL_KEYWORDS,
            TIER_FACTUAL_RECALL_KEYWORDS,
            TIER_TOOL_KEYWORDS,
            TIER_DEEP_KEYWORDS,
        )
        # 非空且类型正确
        self.assertIsInstance(TIER_CRITICAL_KEYWORDS, list)
        self.assertGreater(len(TIER_CRITICAL_KEYWORDS), 5)
        self.assertGreater(len(TIER_FACTUAL_RECALL_KEYWORDS), 5)
        self.assertGreater(len(TIER_TOOL_KEYWORDS), 10)
        self.assertGreater(len(TIER_DEEP_KEYWORDS), 10)

    def test_worker_class_attr_alias_to_helpers(self):
        """JarvisWorkerThread._TIER_*_KEYWORDS 与 helpers 是同一对象 (alias)."""
        from jarvis_worker import JarvisWorkerThread
        from jarvis_worker_helpers import (
            TIER_CRITICAL_KEYWORDS,
            TIER_FACTUAL_RECALL_KEYWORDS,
            TIER_TOOL_KEYWORDS,
            TIER_DEEP_KEYWORDS,
        )
        self.assertIs(JarvisWorkerThread._TIER_CRITICAL_KEYWORDS, TIER_CRITICAL_KEYWORDS)
        self.assertIs(JarvisWorkerThread._TIER_FACTUAL_RECALL_KEYWORDS, TIER_FACTUAL_RECALL_KEYWORDS)
        self.assertIs(JarvisWorkerThread._TIER_TOOL_KEYWORDS, TIER_TOOL_KEYWORDS)
        self.assertIs(JarvisWorkerThread._TIER_DEEP_KEYWORDS, TIER_DEEP_KEYWORDS)

    def test_tier_critical_contains_known_patterns(self):
        """TIER_CRITICAL 含 reminder/alarm 关键 pattern."""
        import re
        from jarvis_worker_helpers import TIER_CRITICAL_KEYWORDS
        joined = ' '.join(TIER_CRITICAL_KEYWORDS)
        self.assertIn('提醒我', joined)
        # 测一个 regex pattern 真能 match
        for pat in TIER_CRITICAL_KEYWORDS:
            try:
                if re.search(pat, 'remind me to drink water'):
                    return  # 至少一个 pattern hit
            except re.error:
                pass
        self.fail('No TIER_CRITICAL pattern matches "remind me ..."')


class TestM6W4SleepRefusalConstAlias(unittest.TestCase):
    """W4 抽出: GENERIC/STRONG_REFUSAL_PATTERNS + SLEEP_INTENT_PATTERNS +
    SLEEP_TIME_EXTRACTORS + CN_DIGIT_MAP 都抽到 helpers."""

    def test_helpers_const_importable(self):
        """5 个 const 都从 helpers export."""
        from jarvis_worker_helpers import (
            GENERIC_REFUSAL_PATTERNS, STRONG_REFUSAL_PATTERNS,
            SLEEP_INTENT_PATTERNS, SLEEP_TIME_EXTRACTORS, CN_DIGIT_MAP,
        )
        self.assertIsInstance(GENERIC_REFUSAL_PATTERNS, list)
        self.assertGreater(len(GENERIC_REFUSAL_PATTERNS), 20)
        self.assertIsInstance(STRONG_REFUSAL_PATTERNS, list)
        self.assertGreater(len(STRONG_REFUSAL_PATTERNS), 10)
        self.assertIsInstance(SLEEP_INTENT_PATTERNS, list)
        self.assertGreater(len(SLEEP_INTENT_PATTERNS), 10)
        self.assertIsInstance(SLEEP_TIME_EXTRACTORS, list)
        self.assertGreater(len(SLEEP_TIME_EXTRACTORS), 5)
        self.assertIsInstance(CN_DIGIT_MAP, dict)
        # 中文数字 0-12
        self.assertEqual(CN_DIGIT_MAP['两'], 2)
        self.assertEqual(CN_DIGIT_MAP['十'], 10)

    def test_worker_class_attr_alias(self):
        """worker class _GENERIC_/_STRONG_/_SLEEP_*/_CN_DIGIT_MAP 与 helpers 同对象."""
        from jarvis_worker import JarvisWorkerThread
        from jarvis_worker_helpers import (
            GENERIC_REFUSAL_PATTERNS, STRONG_REFUSAL_PATTERNS,
            SLEEP_INTENT_PATTERNS, SLEEP_TIME_EXTRACTORS, CN_DIGIT_MAP,
        )
        self.assertIs(JarvisWorkerThread._GENERIC_REFUSAL_PATTERNS, GENERIC_REFUSAL_PATTERNS)
        self.assertIs(JarvisWorkerThread._STRONG_REFUSAL_PATTERNS, STRONG_REFUSAL_PATTERNS)
        self.assertIs(JarvisWorkerThread._SLEEP_INTENT_PATTERNS, SLEEP_INTENT_PATTERNS)
        self.assertIs(JarvisWorkerThread._SLEEP_TIME_EXTRACTORS, SLEEP_TIME_EXTRACTORS)
        self.assertIs(JarvisWorkerThread._CN_DIGIT_MAP, CN_DIGIT_MAP)

    def test_sleep_pattern_real_match(self):
        """sleep intent regex 真能 match 已知 Sir 真测语料."""
        import re
        from jarvis_worker_helpers import SLEEP_INTENT_PATTERNS
        # Sir 实测痛点: "我会在大概两点的时候睡觉"
        sample = '我会在大概两点的时候睡觉'.lower()
        hits = [p for p in SLEEP_INTENT_PATTERNS if re.search(p, sample)]
        self.assertGreater(len(hits), 0, f'no SLEEP pattern matched: {sample}')

    def test_sleep_extractor_real_extract(self):
        """time extractor 真能算秒数."""
        import re
        from jarvis_worker_helpers import SLEEP_TIME_EXTRACTORS
        # '30 分钟' → 1800s
        for pat, fn in SLEEP_TIME_EXTRACTORS:
            m = re.search(pat, '30 分钟后睡觉')
            if m:
                self.assertEqual(fn(m), 1800)
                return
        self.fail('no extractor matched "30 分钟"')

    def test_refusal_strong_contains_shut_up(self):
        """STRONG refusal 含 'shut up' / '闭嘴'."""
        from jarvis_worker_helpers import STRONG_REFUSAL_PATTERNS
        joined = ' '.join(STRONG_REFUSAL_PATTERNS).lower()
        self.assertIn('shut up', joined)
        self.assertIn('闭嘴', joined)


class TestM6W8NoiseFloorCompute(unittest.TestCase):
    """W8 抽出: compute_adaptive_noise_threshold (BUG-2 中期治本 logic 抽 helper).
    
    设计验证:
      - warmup (buffer < 30): floor=0, threshold=gaming (Sir 起步说话仍触发)
      - 安静 (low floor 50): threshold = max(gaming, 125, 80) = gaming (默认 180)
      - 游戏背景音 (high floor 300): threshold = max(gaming, 750, 80) = 750 (挡背景, Sir 大声仍触发)
    """

    def test_warmup_returns_gaming_threshold(self):
        """buffer 不足 30 帧 → floor=0, threshold 退化到 gaming."""
        from jarvis_worker_helpers import compute_adaptive_noise_threshold
        nf, th = compute_adaptive_noise_threshold([100, 200, 50], gaming_threshold=180)
        self.assertEqual(nf, 0.0)
        self.assertEqual(th, 180)

    def test_quiet_office_keeps_gaming_threshold(self):
        """30 帧低音 (floor=50) → threshold=max(180, 125, 80)=180."""
        from jarvis_worker_helpers import compute_adaptive_noise_threshold
        nf, th = compute_adaptive_noise_threshold([50] * 30, gaming_threshold=180)
        self.assertEqual(nf, 50.0)
        self.assertEqual(th, 180)  # gaming 优先

    def test_gaming_bg_lifts_threshold(self):
        """30 帧 300 dB 游戏背景音 → floor=300, threshold=750 (挡背景音)."""
        from jarvis_worker_helpers import compute_adaptive_noise_threshold
        nf, th = compute_adaptive_noise_threshold([300] * 30, gaming_threshold=180)
        self.assertEqual(nf, 300.0)
        self.assertEqual(th, 750)

    def test_min_threshold_floor_zero_safety(self):
        """floor=0 + 极低 gaming → 至少 MIN_THRESHOLD."""
        from jarvis_worker_helpers import compute_adaptive_noise_threshold
        nf, th = compute_adaptive_noise_threshold([], gaming_threshold=10, min_threshold=80)
        self.assertEqual(th, 80)  # min_threshold 兜底

    def test_percentile_index_excludes_high_speech(self):
        """30 帧低 + 偶发高峰: percentile-30 排掉 Sir 突峰, floor 仍低."""
        from jarvis_worker_helpers import compute_adaptive_noise_threshold
        # 25 个 50 + 5 个 1500 (Sir 说话突峰)
        buffer = [50] * 25 + [1500] * 5
        nf, th = compute_adaptive_noise_threshold(buffer, gaming_threshold=180)
        # percentile-30 of 30-element sorted list = index 9, 仍是 50
        self.assertEqual(nf, 50.0)
        self.assertEqual(th, 180)

    def test_voice_listen_thread_imports_helper(self):
        """voice_listen_thread.py 真用 compute_adaptive_noise_threshold helper."""
        import jarvis_voice_listen_thread as vlt
        self.assertTrue(hasattr(vlt, 'compute_adaptive_noise_threshold'))


class TestM6W7PatternLists(unittest.TestCase):
    """W7 抽出: PRACTICE / DISMISSIVE / SELF_INTERRUPTION 3 个 method-local list 抽 const."""

    def test_const_export(self):
        """3 const 都从 helpers 可 import."""
        from jarvis_worker_helpers import (
            PRACTICE_PATTERNS, DISMISSIVE_PATTERNS, SELF_INTERRUPTION_PATTERNS,
        )
        self.assertIsInstance(PRACTICE_PATTERNS, list)
        self.assertGreaterEqual(len(PRACTICE_PATTERNS), 5)
        self.assertIsInstance(DISMISSIVE_PATTERNS, list)
        self.assertGreaterEqual(len(DISMISSIVE_PATTERNS), 30)
        self.assertIsInstance(SELF_INTERRUPTION_PATTERNS, list)
        self.assertGreaterEqual(len(SELF_INTERRUPTION_PATTERNS), 8)

    def test_worker_reexport(self):
        """worker re-export 与 helpers 同对象."""
        from jarvis_worker import (
            PRACTICE_PATTERNS as W_PR, DISMISSIVE_PATTERNS as W_DI,
            SELF_INTERRUPTION_PATTERNS as W_SI,
        )
        from jarvis_worker_helpers import (
            PRACTICE_PATTERNS as H_PR, DISMISSIVE_PATTERNS as H_DI,
            SELF_INTERRUPTION_PATTERNS as H_SI,
        )
        self.assertIs(W_PR, H_PR)
        self.assertIs(W_DI, H_DI)
        self.assertIs(W_SI, H_SI)

    def test_practice_pattern_match(self):
        """PRACTICE pattern 真能 match 已知 sample."""
        import re
        from jarvis_worker_helpers import PRACTICE_PATTERNS
        sample = 'how to say hello'
        hits = [p for p in PRACTICE_PATTERNS if re.search(p, sample)]
        self.assertGreater(len(hits), 0)

    def test_dismissive_contains_keys(self):
        """DISMISSIVE 含 'not funny' / '不好笑' / 'stop joking'."""
        from jarvis_worker_helpers import DISMISSIVE_PATTERNS
        joined = ' '.join(DISMISSIVE_PATTERNS).lower()
        self.assertIn('not funny', joined)
        self.assertIn('不好笑', joined)
        self.assertIn('stop joking', joined)

    def test_self_interruption_match(self):
        """SELF_INTERRUPTION 真能 match '不对不对' / 'wait on'."""
        import re
        from jarvis_worker_helpers import SELF_INTERRUPTION_PATTERNS
        for sample in ('不对不对', 'wait on', 'let me say'):
            hits = [p for p in SELF_INTERRUPTION_PATTERNS if re.search(p, sample)]
            self.assertGreater(len(hits), 0, f'no SELF_INTERRUPTION matched: {sample}')


class TestM6W6VocabLoaders(unittest.TestCase):
    """W6 抽出: load_sleep_cancel_vocab + load_audio_ducking_targets 抽到 helpers."""

    def test_load_sleep_cancel_vocab_export(self):
        """load_sleep_cancel_vocab module-level fn 可调."""
        from jarvis_worker_helpers import load_sleep_cancel_vocab
        out = load_sleep_cancel_vocab()
        self.assertIsInstance(out, list)
        # 至少 seed 10 个
        self.assertGreaterEqual(len(out), 10)
        # seed 含 'wait' 或 '等等'
        joined = ' '.join(out)
        self.assertTrue('等等' in joined or 'wait' in joined)

    def test_load_audio_ducking_targets_export(self):
        """load_audio_ducking_targets module-level fn 可调."""
        from jarvis_worker_helpers import load_audio_ducking_targets
        out = load_audio_ducking_targets()
        self.assertIsInstance(out, list)
        # 至少 1 个 (seed = ['WeChat'])
        self.assertGreaterEqual(len(out), 1)

    def test_worker_method_delegates_to_helpers(self):
        """JarvisWorkerThread._load_*_vocab method 仍 work (delegate to helpers)."""
        from jarvis_worker import (
            load_sleep_cancel_vocab as fn_sleep,
            load_audio_ducking_targets as fn_audio,
        )
        # 仅验 fn 对象可获取 (不需 instantiate worker — 涉及 PyQt thread)
        self.assertTrue(callable(fn_sleep))
        self.assertTrue(callable(fn_audio))
        out_sleep = fn_sleep()
        self.assertIsInstance(out_sleep, list)


class TestM6W5ReflexDict(unittest.TestCase):
    """W5 抽出: REFLEX_DICT 70 行脊髓反射词典抽到 helpers."""

    def test_helpers_export(self):
        """REFLEX_DICT 从 helpers export, dict 类型, 60+ key."""
        from jarvis_worker_helpers import REFLEX_DICT
        self.assertIsInstance(REFLEX_DICT, dict)
        self.assertGreater(len(REFLEX_DICT), 60)

    def test_worker_reexport(self):
        """worker re-export REFLEX_DICT 与 helpers 同对象."""
        from jarvis_worker import REFLEX_DICT as W_RD
        from jarvis_worker_helpers import REFLEX_DICT as H_RD
        self.assertIs(W_RD, H_RD)

    def test_known_reflexes(self):
        """关键 reflex (jarvis/garbage/closet 空耳/中文 闭嘴) 都在."""
        from jarvis_worker_helpers import REFLEX_DICT
        # 唤醒
        self.assertEqual(REFLEX_DICT['jarvis'], 'I am here, sir.')
        self.assertEqual(REFLEX_DICT['garbage'], 'I am here, sir.')  # 空耳
        # 中文唤醒
        self.assertEqual(REFLEX_DICT['贾维斯'], 'Yes, sir.')
        # 告退
        self.assertEqual(REFLEX_DICT['闭嘴'], 'Entering silent mode, sir.')
        self.assertEqual(REFLEX_DICT['shut up'], 'Entering silent mode, sir.')


if __name__ == '__main__':
    unittest.main()
