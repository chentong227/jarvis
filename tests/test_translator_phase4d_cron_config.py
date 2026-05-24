# -*- coding: utf-8 -*-
"""[Translator Phase 4.D / 2026-05-24 22:55] reflector CRON tuning config test.

详 docs/JARVIS_TRANSLATOR_ARCHITECTURE.md §7.9

覆盖:
  A. _load_config() 默认值 (config 文件不存在时)
  B. _load_config() 读 config 文件覆盖
  C. _load_config() 损坏 JSON → fallback 默认
  D. run_cycle 用 config 的 propose_threshold (不 hardcoded)
  E. start_daemon _loop 用 config 的 tick_interval (动态 reload)
  F. dashboard CLI invoke 加 encoding='utf-8' 防 GBK 解码 fail
  G. dashboard 中文化: 表头/badge/字段说明全中文
  H. CLI script 存在 + show/set/reset 命令
"""
import os
import json
import tempfile
import shutil
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


# ============================================================
# A + B + C. _load_config()
# ============================================================

class TestLoadConfig(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tmp_config = os.path.join(self._tmpdir, 'config.json')
        import jarvis_translator_reflector as trr
        self._orig = trr.CONFIG_PATH
        trr.CONFIG_PATH = self._tmp_config

    def tearDown(self):
        import jarvis_translator_reflector as trr
        trr.CONFIG_PATH = self._orig
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_defaults_when_no_file(self):
        from jarvis_translator_reflector import _load_config
        cfg = _load_config()
        self.assertEqual(cfg['tick_interval_s'], 1800.0)
        self.assertEqual(cfg['startup_delay_s'], 600.0)
        self.assertEqual(cfg['propose_threshold'], 3)
        self.assertEqual(cfg['scan_window_s'], 7200.0)

    def test_override_via_config_file(self):
        with open(self._tmp_config, 'w', encoding='utf-8') as f:
            json.dump({
                'schema_version': 1,
                'tick_interval_s': 60,
                'propose_threshold': 2,
                'scan_window_s': 3600,
            }, f)
        from jarvis_translator_reflector import _load_config
        cfg = _load_config()
        self.assertEqual(cfg['tick_interval_s'], 60.0)
        self.assertEqual(cfg['propose_threshold'], 2)
        self.assertEqual(cfg['scan_window_s'], 3600.0)
        # 没 override 的字段保留默认
        self.assertEqual(cfg['startup_delay_s'], 600.0)

    def test_malformed_json_fallback_defaults(self):
        with open(self._tmp_config, 'w', encoding='utf-8') as f:
            f.write('{ not valid json')
        from jarvis_translator_reflector import _load_config
        cfg = _load_config()
        self.assertEqual(cfg['tick_interval_s'], 1800.0)  # 默认

    def test_non_numeric_field_ignored(self):
        with open(self._tmp_config, 'w', encoding='utf-8') as f:
            json.dump({
                'tick_interval_s': 'not_a_number',  # 应被忽略
                'propose_threshold': 5,
            }, f)
        from jarvis_translator_reflector import _load_config
        cfg = _load_config()
        self.assertEqual(cfg['tick_interval_s'], 1800.0)  # fallback 默认
        self.assertEqual(cfg['propose_threshold'], 5)


# ============================================================
# D. run_cycle 用 config (不再 hardcoded const)
# ============================================================

class TestRunCycleUsesConfig(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tmp_vocab = os.path.join(self._tmpdir, 'vocab.json')
        self._tmp_config = os.path.join(self._tmpdir, 'config.json')
        import jarvis_translator_reflector as trr
        self._orig_vocab = trr.VOCAB_PATH
        self._orig_config = trr.CONFIG_PATH
        trr.VOCAB_PATH = self._tmp_vocab
        trr.CONFIG_PATH = self._tmp_config

    def tearDown(self):
        import jarvis_translator_reflector as trr
        trr.VOCAB_PATH = self._orig_vocab
        trr.CONFIG_PATH = self._orig_config
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_low_threshold_via_config_triggers_propose(self):
        """config 把 propose_threshold 降到 2 → 仅 2 次也 propose."""
        with open(self._tmp_config, 'w', encoding='utf-8') as f:
            json.dump({'propose_threshold': 2}, f)
        with open(self._tmp_vocab, 'w', encoding='utf-8') as f:
            json.dump({'schema_version': 1, 'aliases': []}, f)

        import time
        from jarvis_translator_reflector import TranslatorReflector

        class _Bus:
            def __init__(self): self.events = []
            def recent_events(self, within_seconds=None, types=None):
                return [e for e in self.events
                        if not types or e.get('etype') in types]
            def publish(self, **kw): pass

        bus = _Bus()
        # 仅 2 次 — 默认 threshold 3 不该 propose, 但 config 设 2 应 propose
        bus.events = [
            {'etype': 'translator_aliased',
             'metadata': {'from_organ': 'foo', 'to_organ': 'bar',
                          'alias_kind': 'by_command', 'command': f'c{i}'},
             'ts': time.time()}
            for i in range(2)
        ]
        r = TranslatorReflector(event_bus=bus)
        out = r.run_cycle()
        self.assertEqual(len(out), 1, 'config threshold=2 → 2 次也 propose')


# ============================================================
# E. start_daemon _loop 用 config
# ============================================================

class TestStartDaemonUsesConfig(unittest.TestCase):

    def test_loop_calls_load_config(self):
        """start_daemon _loop 内部应 call _load_config (静态 grep)."""
        with open(os.path.join(ROOT, 'jarvis_translator_reflector.py'),
                  'r', encoding='utf-8') as f:
            src = f.read()
        # _loop 函数体应含 _load_config()
        loop_section = src[src.find('def _loop'):src.find('def _loop') + 500]
        self.assertIn('_load_config()', loop_section,
                      '_loop 必须 call _load_config (动态 reload)')
        self.assertIn("cfg['tick_interval_s']", loop_section)
        self.assertIn("cfg['startup_delay_s']", loop_section)


# ============================================================
# F + G. dashboard fix + i18n
# ============================================================

class TestDashboardCLIInvokeFixAndI18N(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'scripts', 'jarvis_dashboard_web.py'),
                  'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_subprocess_uses_utf8(self):
        """dashboard CLI invoke 必须加 encoding='utf-8' 防 GBK 解码 fail."""
        idx = self.src.find("'translator_alias_dump.py')")
        self.assertGreater(idx, 0)
        section = self.src[idx:idx + 2000]
        self.assertIn("encoding='utf-8'", section,
                      'CLI invoke 必须 encoding=utf-8')
        self.assertIn("PYTHONIOENCODING", section,
                      '必须设 PYTHONIOENCODING env')

    def test_response_returns_message_zh(self):
        """API 返回必须含 message_zh 中文友好提示."""
        idx = self.src.find('已激活 alias')
        self.assertGreater(idx, 0, "API 应有 '已激活 alias' 中文提示")
        self.assertIn('已拒绝 alias', self.src)
        self.assertIn("'message_zh'", self.src)

    def test_html_headers_chinese(self):
        """表头/按钮/字段说明全中文."""
        self.assertIn('待审核', self.src)
        self.assertIn('已启用', self.src)
        self.assertIn('已拒绝', self.src)
        self.assertIn('启用', self.src)
        self.assertIn('拒绝', self.src)
        self.assertIn('翻译层别名总管', self.src)
        self.assertIn('反思器运行轮数', self.src)
        self.assertIn('字段说明', self.src)

    def test_status_zh_mapping_js(self):
        """JS 含 STATUS_ZH 字典 (badge i18n)."""
        self.assertIn('STATUS_ZH', self.src)
        self.assertIn("review:'📋 待审核'", self.src)
        self.assertIn("active:'✅ 已启用'", self.src)


# ============================================================
# H. CLI tool 存在
# ============================================================

class TestCronConfigCLI(unittest.TestCase):

    def test_cli_script_exists(self):
        script = os.path.join(ROOT, 'scripts',
                              'translator_reflector_config_dump.py')
        self.assertTrue(os.path.exists(script),
                        'translator_reflector_config_dump.py 必须存在')

    def test_cli_has_show_set_reset(self):
        script = os.path.join(ROOT, 'scripts',
                              'translator_reflector_config_dump.py')
        with open(script, 'r', encoding='utf-8') as f:
            src = f.read()
        for cmd in ('show', 'set', 'reset'):
            self.assertIn(f"add_parser('{cmd}'", src,
                          f'CLI 必须有 {cmd} 子命令')

    def test_config_default_json_exists(self):
        config = os.path.join(ROOT, 'memory_pool',
                              'translator_reflector_config.json')
        self.assertTrue(os.path.exists(config),
                        'memory_pool/translator_reflector_config.json 默认应存在')
        with open(config, 'r', encoding='utf-8') as f:
            d = json.load(f)
        self.assertIn('tick_interval_s', d)
        self.assertIn('propose_threshold', d)


if __name__ == '__main__':
    unittest.main()
