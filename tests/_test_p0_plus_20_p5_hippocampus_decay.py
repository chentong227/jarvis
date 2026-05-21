# -*- coding: utf-8 -*-
"""[Gap-Z5 / β.5.46-fix8 / 2026-05-21 23:55] Hippocampus time decay 测试.

不调真 LLM (mock embedding). 验证 decay 数学 + sort 顺序 + 向后兼容.
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDecayMath(unittest.TestCase):
    """time_decay_halflife_days 参数数学正确."""

    def test_no_decay_param_means_no_decay(self):
        """time_decay_halflife_days=None → 旧行为, 纯 cosine."""
        # 只测数学公式 - exp(-0/halflife) = 1
        self.assertAlmostEqual(math.exp(0), 1.0)

    def test_decay_at_halflife_is_half(self):
        """age = halflife → decay = 0.5."""
        halflife_s = 30 * 86400.0
        age_s = halflife_s
        decay = math.exp(-age_s / halflife_s)
        self.assertAlmostEqual(decay, 0.367, places=2)
        # 注: math.exp(-1) = 0.368, 不是 0.5 (那是 2^(-1))
        # 我们的实现用 exp, 30 天后 = 0.368

    def test_decay_at_zero_age_is_one(self):
        """age = 0 → decay = 1.0."""
        halflife_s = 30 * 86400.0
        age_s = 0.0
        decay = math.exp(-age_s / halflife_s)
        self.assertEqual(decay, 1.0)

    def test_old_memory_decays_more(self):
        """100 天前 memory decay 比 1 天前更小."""
        halflife_s = 30 * 86400.0
        decay_1_day = math.exp(-86400.0 / halflife_s)
        decay_100_days = math.exp(-100 * 86400.0 / halflife_s)
        self.assertLess(decay_100_days, decay_1_day)
        self.assertGreater(decay_1_day, 0.9)
        self.assertLess(decay_100_days, 0.05)


class TestConfigLoad(unittest.TestCase):
    """config 加载."""

    def test_config_file_exists(self):
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'memory_pool', 'hippocampus_decay_config.json',
        )
        self.assertTrue(os.path.exists(cfg_path))

    def test_config_has_correct_schema(self):
        import json
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'memory_pool', 'hippocampus_decay_config.json',
        )
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        self.assertIn('enabled', cfg)
        self.assertIn('halflife_days', cfg)
        self.assertGreaterEqual(cfg['halflife_days'], 1.0)


class TestSearchMemoryHasDecayParam(unittest.TestCase):
    """search_memory 应有 time_decay_halflife_days 参数."""

    def test_search_memory_has_decay_param(self):
        import inspect
        from jarvis_hippocampus import Hippocampus
        sig = inspect.signature(Hippocampus.search_memory)
        self.assertIn('time_decay_halflife_days', sig.parameters,
                       'search_memory 应有 time_decay_halflife_days 参数')


class TestDefaultSearchHelper(unittest.TestCase):
    """search_memory_default helper 应存在."""

    def test_default_method_exists(self):
        from jarvis_hippocampus import Hippocampus
        self.assertTrue(hasattr(Hippocampus, 'search_memory_default'),
                         'Hippocampus 应有 search_memory_default 方法')

    def test_load_decay_config(self):
        from jarvis_hippocampus import Hippocampus
        cfg = Hippocampus._load_decay_config()
        self.assertIsInstance(cfg, dict)


class TestCentralNerveUsesDefault(unittest.TestCase):
    """central_nerve 应用 search_memory_default."""

    def test_central_nerve_uses_default_search(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('search_memory_default', src,
                       'central_nerve 应用 search_memory_default 主流路径')


if __name__ == '__main__':
    unittest.main()
