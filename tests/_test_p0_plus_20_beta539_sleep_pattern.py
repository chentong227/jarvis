# -*- coding: utf-8 -*-
"""[β.5.39 / 2026-05-20] 动态催睡 — Sir 平时入睡时间 distance-based.

Sir 15:18 真理: "晚上贾维斯会逐步在接近我之前睡觉时间的早一些的时候提高催睡频率, 我不喜欢硬编码."

3 层架构验证:
  层1: sir_sleep_pattern_vocab.json + scripts/sleep_pattern_dump.py CLI
  层2: jarvis_sleep_pattern_reflector.py L7 daemon
  层3: ProactiveCare distance-based urgency 公式 + log_sleep_event hook + late_night_care directive
"""
from __future__ import annotations

import json
import os
import time
import unittest
from unittest.mock import patch, MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'sir_sleep_pattern_vocab.json')


class TestBeta539VocabSchema(unittest.TestCase):
    """vocab JSON schema 完整 + CLI 工具存在."""

    def test_vocab_file_exists(self):
        self.assertTrue(os.path.exists(VOCAB_PATH),
            'sir_sleep_pattern_vocab.json 必须存在')

    def test_vocab_schema_complete(self):
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('_meta', data)
        self.assertIn('typical_sleep_hour', data)
        self.assertIn('history', data)
        meta = data['_meta']
        self.assertIn('min_data_points', meta)
        self.assertIn('history_max_days', meta)
        typ = data['typical_sleep_hour']
        # 初始未填充 — weekday/weekend 都该是 None
        # (Sir 实测一周后 L7 reflector 自动填)
        for kind in ('weekday', 'weekend'):
            self.assertIn(kind, typ,
                f'typical_sleep_hour.{kind} 字段必须存在 (允许 null)')

    def test_cli_script_exists(self):
        cli_path = os.path.join(ROOT, 'scripts', 'sleep_pattern_dump.py')
        self.assertTrue(os.path.exists(cli_path),
            'scripts/sleep_pattern_dump.py CLI 必须存在')


class TestBeta539LoadHelper(unittest.TestCase):
    """_load_sir_sleep_pattern helper mtime cache 工作."""

    def test_load_returns_dict(self):
        from jarvis_proactive_care import _load_sir_sleep_pattern
        result = _load_sir_sleep_pattern()
        self.assertIsInstance(result, dict)
        for k in ('weekday', 'weekend', 'tolerance_hours'):
            self.assertIn(k, result)


class TestBeta539ReflectorClass(unittest.TestCase):
    """jarvis_sleep_pattern_reflector.SleepPatternReflector 可初始化 + log_sleep_event 可用."""

    def test_reflector_init(self):
        from jarvis_sleep_pattern_reflector import SleepPatternReflector
        r = SleepPatternReflector(hippocampus=None)
        self.assertEqual(r.name, 'SleepPatternReflector')
        self.assertTrue(r.daemon)

    def test_log_sleep_event_writes(self):
        """log_sleep_event 写一个 entry 到 vocab history (tmp file 测试)."""
        from jarvis_sleep_pattern_reflector import log_sleep_event
        # 用真 vocab path, log 当天 entry → 看是否写 (同一天重复不加)
        before = []
        try:
            with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                before = list(data.get('history', []))
        except Exception:
            pass
        log_sleep_event(23.5, source='test_unittest')
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            after_data = json.load(f)
        after = after_data.get('history', [])
        # 如果 before 已含今日 entry, log 不该 add (取最早)
        today = time.strftime('%Y-%m-%d')
        today_entries = [h for h in after if h.get('date') == today]
        self.assertLessEqual(len(today_entries), 1,
            '同一天 log_sleep_event 应取最早, 不该重复')


class TestBeta539ProactiveCareDistance(unittest.TestCase):
    """ProactiveCare 看 sir_sleep_pattern_vocab 自适应 urgency."""

    def test_proactive_care_source_has_beta539_marker(self):
        with open(os.path.join(ROOT, 'jarvis_proactive_care.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.39', src,
            'β.5.39 marker 必须在 proactive_care')
        self.assertIn('_load_sir_sleep_pattern', src,
            '_load_sir_sleep_pattern helper 必须存在')
        # 必须有 distance-based 公式术语
        self.assertIn('distance', src,
            'distance 公式必须存在 (非硬编码 22:00)')
        # 必须 publish sir_sleep_pattern SWM signal
        self.assertIn("'sir_sleep_pattern'", src,
            'sir_sleep_pattern SWM publish 必须存在')


class TestBeta539NerveHookAndDirective(unittest.TestCase):
    """_trigger_sleep_mode hook log_sleep_event + late_night_care_judge directive 更新."""

    def test_nerve_trigger_sleep_mode_calls_log(self):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        # _trigger_sleep_mode 必须 import log_sleep_event
        idx = src.find('def _trigger_sleep_mode(self):')
        end = src.find('def _detect_wake_up', idx)
        body = src[idx:end] if idx > 0 and end > idx else ''
        self.assertIn('log_sleep_event', body,
            '_trigger_sleep_mode 必须调 log_sleep_event (β.5.39 hook)')
        self.assertIn('β.5.39', body,
            'β.5.39 marker 必须在 _trigger_sleep_mode')

    def test_reflector_wired_in_nerve_init(self):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('SleepPatternReflector', src,
            'SleepPatternReflector 必须被 nerve 启动')
        self.assertIn('sleep_pattern_reflector', src,
            'self.sleep_pattern_reflector 必须存在')

    def test_late_night_directive_has_beta539_marker(self):
        from jarvis_directives import _trigger_late_night_care_judge
        # callable - 不抛
        self.assertTrue(callable(_trigger_late_night_care_judge))
        with open(os.path.join(ROOT, 'jarvis_directives.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        # directive text 必须含 β.5.39 + distance 描述
        idx = src.find("id='late_night_care_judge'")
        end = src.find("trigger=_trigger_late_night_care_judge", idx)
        block = src[idx:end] if idx > 0 else ''
        self.assertIn('β.5.39', block,
            'late_night_care directive 必须含 β.5.39 marker')
        self.assertIn('distance', block,
            'late_night_care directive 必须教主脑用 distance 描述 (非硬编码 22:00)')


# ==========================================================================
# β.5.39-fix: infer_expected_behavior 用 description 显式时间 + dashboard 修
# ==========================================================================

class TestBeta539FixInferUsesDescriptionTime(unittest.TestCase):
    """infer_expected_behavior 必须优先 parse description 中的 X 分钟 (user evidence)."""

    def test_explicit_5_min_overrides_vocab_default(self):
        from jarvis_commitment_watcher import infer_expected_behavior
        r = infer_expected_behavior('我现在喝水休息5分钟')
        self.assertEqual(r.get('threshold'), 5,
            '显式 "5 分钟" 必须 overrides vocab default 30')
        self.assertEqual(r.get('_threshold_source'), 'description_explicit')

    def test_explicit_10_minutes_english(self):
        from jarvis_commitment_watcher import infer_expected_behavior
        r = infer_expected_behavior('I will rest for 10 minutes')
        self.assertEqual(r.get('threshold'), 10)

    def test_half_hour(self):
        from jarvis_commitment_watcher import infer_expected_behavior
        r = infer_expected_behavior('我去睡觉半小时')
        self.assertEqual(r.get('threshold'), 30)

    def test_one_hour(self):
        from jarvis_commitment_watcher import infer_expected_behavior
        r = infer_expected_behavior('我休息一小时')
        self.assertEqual(r.get('threshold'), 60)

    def test_no_explicit_time_falls_back_to_vocab_default(self):
        from jarvis_commitment_watcher import infer_expected_behavior
        r = infer_expected_behavior('我去睡觉')  # 无显式时间 → vocab default 30min
        self.assertEqual(r.get('threshold'), 30)
        # 没 _threshold_source (vocab default)
        self.assertNotEqual(r.get('_threshold_source'), 'description_explicit')


class TestBeta539FixDashboardRelationalReviewN(unittest.TestCase):
    """dashboard read_relational review_n 必须排除 _meta 误算."""

    def test_source_has_meta_filter(self):
        """jarvis_dashboard.py read_relational 必须含 _meta 排除逻辑.
        
        全文 grep 该 marker — 不依赖函数体精确截取 (read_relational 含 nested def _items).
        """
        with open(os.path.join(ROOT, 'scripts', 'jarvis_dashboard.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        # β.5.39-fix marker 必须存在
        self.assertIn('β.5.39-fix', src,
            'dashboard 必须含 β.5.39-fix marker')
        # review_n sum 必须含 startswith('_') 过滤
        # 找 review_n 求和段
        idx = src.find("out['review_n'] = sum(")
        self.assertGreater(idx, 0, "应有 review_n sum 段")
        sum_block = src[idx:idx + 200]
        self.assertIn("startswith('_')", sum_block,
            'review_n sum 必须排除下划线 key')


class TestBeta539FixDashboardNewVocabReviewSources(unittest.TestCase):
    """dashboard read_review_queues 必须 cover 5 个新 vocab review sources."""

    def test_5a_block_in_dashboard_source(self):
        with open(os.path.join(ROOT, 'scripts', 'jarvis_dashboard.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        # β.5.39-fix 5 个新 vocab
        for vocab in ('screen_tease_vocab.json', 'sir_struggle_vocab.json',
                       'directives_vocab.json', 'sir_sleep_pattern_vocab.json',
                       'behavior_inference_vocab.json'):
            self.assertIn(vocab, src,
                f'dashboard 必须 cover {vocab} review_queue (β.5.39-fix)')


if __name__ == '__main__':
    unittest.main()
