# -*- coding: utf-8 -*-
"""[P5-fix35-E / 2026-05-23 11:36] AmbientSensor config 持久化 + CLI tests.

Sir 11:27 真测痛点: AmbientSensor 启用了但没体感. 21MB log 0 publish.
治本: config JSON 持久化 (准则 6) + CLI 调 + mtime cache reload + stats log.

覆盖:
A. AmbientSensor config 默认值正确
B. AmbientSensor 从 JSON 读 config (mtime cache)
C. get_stats 含详细 counters
D. CLI scripts/ambient_sensor_dump.py 存在 + actions
E. memory_pool/ambient_sensor_config.json 存在
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestADefaultConfig(unittest.TestCase):

    def test_defaults_are_relaxed(self):
        """v2 defaults: 比 v1 放宽 (Sir 11:27 真痛点)."""
        from jarvis_ambient_sensor import (
            DEFAULT_MIN_CONFIDENCE, DEFAULT_CONSECUTIVE_AGREE_THRESHOLD,
            DEFAULT_MAX_VOLUME_FOR_ANALYSIS,
        )
        # v2: 0.50 (v1 was 0.60)
        self.assertEqual(DEFAULT_MIN_CONFIDENCE, 0.50)
        # v2: 2 (v1 was 3)
        self.assertEqual(DEFAULT_CONSECUTIVE_AGREE_THRESHOLD, 2)
        # v2: 3000 (v1 was 1500)
        self.assertEqual(DEFAULT_MAX_VOLUME_FOR_ANALYSIS, 3000)


class TestBConfigPersistence(unittest.TestCase):

    def test_config_file_exists(self):
        path = os.path.join(ROOT, 'memory_pool',
                              'ambient_sensor_config.json')
        self.assertTrue(os.path.exists(path),
                          'ambient_sensor_config.json 必须存在 (准则 6 持久化)')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('config', data)
        cfg = data['config']
        for key in ('min_confidence', 'consecutive_agree_threshold',
                      'max_volume_for_analysis', 'min_volume_for_analysis',
                      'analyze_in_active_chat'):
            self.assertIn(key, cfg, f'config 缺 {key}')

    def test_loader_reads_from_json(self):
        """AmbientSensor 启动时从 JSON 读 config."""
        from jarvis_ambient_sensor import AmbientSensor
        sensor = AmbientSensor(event_bus=None)
        # config should be loaded (not just defaults)
        self.assertIsInstance(sensor._config, dict)
        # 应有所有必填 key
        for key in ('min_confidence', 'consecutive_agree_threshold',
                      'max_volume_for_analysis'):
            self.assertIn(key, sensor._config)

    def test_mtime_cache_reload(self):
        """改 JSON file → 下次 _reload_config_if_changed 重读."""
        # 用 tmp file 测
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8')
        tmp.write(json.dumps({'config': {'min_confidence': 0.30}},
                                ensure_ascii=False))
        tmp.close()

        try:
            import jarvis_ambient_sensor as ams
            old_path = ams._CONFIG_PATH
            try:
                ams._CONFIG_PATH = tmp.name
                sensor = ams.AmbientSensor(event_bus=None)
                self.assertEqual(sensor._config['min_confidence'], 0.30)

                # change file
                time.sleep(0.05)
                with open(tmp.name, 'w', encoding='utf-8') as f:
                    json.dump({'config': {'min_confidence': 0.99}}, f)

                # touch mtime forward
                os.utime(tmp.name, None)
                time.sleep(0.05)

                sensor._reload_config_if_changed()
                self.assertEqual(sensor._config['min_confidence'], 0.99)
            finally:
                ams._CONFIG_PATH = old_path
        finally:
            os.remove(tmp.name) if os.path.exists(tmp.name) else None


class TestCDetailedStats(unittest.TestCase):

    def test_get_stats_has_detailed_counters(self):
        from jarvis_ambient_sensor import AmbientSensor
        sensor = AmbientSensor(event_bus=None)
        stats = sensor.get_stats()
        # detailed counters Sir 看跳过原因
        for key in ('n_windows_analyzed', 'n_signals_published',
                      'n_skipped_state_gate', 'n_skipped_volume',
                      'n_classified_no_match',
                      'n_below_consensus', 'n_below_cooldown',
                      'stats_per_type', 'config'):
            self.assertIn(key, stats, f'stats 缺 {key}')


class TestDCLI(unittest.TestCase):

    def test_cli_exists(self):
        path = os.path.join(ROOT, 'scripts', 'ambient_sensor_dump.py')
        self.assertTrue(os.path.exists(path),
                          'ambient_sensor_dump.py 必须存在 (准则 6 CLI 可改)')

    def test_cli_has_actions(self):
        path = os.path.join(ROOT, 'scripts', 'ambient_sensor_dump.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        for arg in ('--json', '--set', '--reset'):
            self.assertIn(arg, src, f'CLI missing {arg}')


if __name__ == '__main__':
    unittest.main()
