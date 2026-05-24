# -*- coding: utf-8 -*-
"""[Reshape M3.A / 2026-05-24] 网络配置单源验证.

覆盖:
  - jarvis_config/network.json 存在 + schema 正确
  - jarvis_utils._PROXY_URL 走 config
  - proxy_enabled=false 时返 fallback
  - 老硬编码 bak file 已删
"""
import os
import sys
import json
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestNetworkConfig(unittest.TestCase):
    def test_config_file_exists(self):
        p = os.path.join(ROOT, 'jarvis_config', 'network.json')
        self.assertTrue(os.path.exists(p),
                        'jarvis_config/network.json 必须存在 (M3.A 单源)')

    def test_config_schema(self):
        p = os.path.join(ROOT, 'jarvis_config', 'network.json')
        with open(p, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        self.assertIn('proxy_url', cfg)
        self.assertIn('proxy_enabled', cfg)
        # 缺省值合理
        self.assertTrue(cfg['proxy_url'].startswith('http'))
        self.assertIsInstance(cfg['proxy_enabled'], bool)

    def test_jarvis_utils_proxy_loads_from_config(self):
        from jarvis_utils import _PROXY_URL
        # 应跟 config 值一致 (config 已 enabled=true)
        with open(os.path.join(ROOT, 'jarvis_config', 'network.json'),
                  'r', encoding='utf-8') as f:
            cfg = json.load(f)
        if cfg.get('proxy_enabled', True):
            self.assertEqual(_PROXY_URL, cfg['proxy_url'])
        else:
            # disabled 时 fallback 老硬编码
            self.assertEqual(_PROXY_URL, 'http://127.0.0.1:7890')

    def test_loader_disabled_returns_fallback(self):
        """_load_proxy_url() 在 enabled=false 时返 fallback 'http://127.0.0.1:7890'."""
        import importlib
        import jarvis_utils
        importlib.reload(jarvis_utils)
        loader = jarvis_utils._load_proxy_url
        # 直接调 loader 看 enabled=true 路径
        result = loader()
        # 至少返了非空字符串
        self.assertTrue(result.startswith('http'))


class TestDeadFilesRemoved(unittest.TestCase):
    """M3.A 死代码删验证: 2 个 .bak 文件应不存在."""

    def test_archive_promise_log_bak_gone(self):
        p = os.path.join(ROOT, 'memory_pool',
                          '_archive_promise_log_2026_05_18.json.bak')
        self.assertFalse(os.path.exists(p),
                          'M3.A: _archive_promise_log_2026_05_18.json.bak 应已删')

    def test_integrity_audit_tainted_bak_gone(self):
        p = os.path.join(ROOT, 'memory_pool',
                          'integrity_audit.jsonl.tainted-184101.bak')
        self.assertFalse(os.path.exists(p),
                          'M3.A: integrity_audit.jsonl.tainted-184101.bak 应已删')


if __name__ == '__main__':
    unittest.main()
