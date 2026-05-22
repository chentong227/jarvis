# -*- coding: utf-8 -*-
"""[β.5.46-fix14 / 2026-05-22] Gemini 3.5 Flash A/B 副链升级 verify

Sir 拍板"副链 A/B": IntentResolver + WatchTaskRegistrar primary 升级
google/gemini-3.5-flash, fallback 降级 google/gemini-2.5-flash-lite. 跑 1-2 周
看 telemetry 决定是否升级主脑.

Cover:
  A. IntentResolver primary/fallback model 配置正确
  B. WatchTask config primary/fallback model 配置正确
  C. WatchTask judge 不动 (高频省价)
  D. IntentResolver telemetry 字段存在 (init)
  E. IntentResolver telemetry persist 行为 (持久化到 JSON)
  F. CLI script: intent_resolver_telemetry_dump.py 可 import + 关键函数存在
  G. 主脑 chat_bypass / 主对话路径 不切 3.5-flash (主脑稳定不变)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_IntentResolverConfig(unittest.TestCase):
    """IntentResolver primary/fallback model 配置."""

    def test_primary_is_gemini_3_5_flash(self):
        from jarvis_intent_resolver import INTENT_RESOLVER_CONFIG
        self.assertEqual(
            INTENT_RESOLVER_CONFIG['primary_model'],
            'google/gemini-3.5-flash',
            'primary 应升级 google/gemini-3.5-flash (Sir β.5.46-fix14 拍板)'
        )

    def test_fallback_is_gemini_2_5_flash_lite(self):
        from jarvis_intent_resolver import INTENT_RESOLVER_CONFIG
        self.assertEqual(
            INTENT_RESOLVER_CONFIG['fallback_model'],
            'google/gemini-2.5-flash-lite',
            'fallback 应降级 google/gemini-2.5-flash-lite (3.5 挂时兜底, '
            '不用 pro-preview 的 timeout 风险)'
        )

    def test_marker_present(self):
        import jarvis_intent_resolver
        with open(jarvis_intent_resolver.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.46-fix14', src,
                       'Fix-14 marker 应在源码 (Gemini 3.5 Flash A/B)')


class TestB_WatchTaskConfig(unittest.TestCase):
    """WatchTask config primary/fallback."""

    def setUp(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'memory_pool', 'watch_task_config.json')
        with open(path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

    def test_registrar_primary_is_3_5_flash(self):
        self.assertEqual(
            self.config['registrar']['primary_model'],
            'google/gemini-3.5-flash',
            'WatchTaskRegistrar primary 应升级 3.5-flash (agentic 提取强项)'
        )

    def test_registrar_fallback_is_2_5_flash_lite(self):
        self.assertEqual(
            self.config['registrar']['fallback_model'],
            'google/gemini-2.5-flash-lite',
            'WatchTaskRegistrar fallback 应降级 2.5-flash-lite'
        )

    def test_judge_stays_on_lite(self):
        """Judge 频次高 (每 ScreenVision describe 都跑), 不切 3.5-flash 省价."""
        self.assertEqual(
            self.config['judge']['primary_model'],
            'google/gemini-2.5-flash-lite',
            'WatchTaskJudge primary 应保留 2.5-flash-lite (高频省价, '
            '5.5x cost 涨不可承受 daemon 频率)'
        )


class TestC_TelemetryFieldsExist(unittest.TestCase):
    """IntentResolver telemetry 字段存在 (init 完成)."""

    def setUp(self):
        from jarvis_intent_resolver import IntentResolver
        self.resolver = IntentResolver(
            key_router=None, central_nerve=None, tool_registry={},
        )

    def test_primary_call_counters(self):
        for f in ['llm_primary_calls', 'llm_primary_ok', 'llm_primary_fail',
                   'llm_primary_latency_sum_ms']:
            self.assertIn(f, self.resolver._stats,
                           f'{f} 应在 _stats')
            self.assertEqual(self.resolver._stats[f], 0
                              if 'sum_ms' not in f else 0.0,
                              f'{f} 初始应 0')

    def test_fallback_call_counters(self):
        for f in ['llm_fallback_calls', 'llm_fallback_ok',
                   'llm_fallback_fail', 'llm_fallback_latency_sum_ms']:
            self.assertIn(f, self.resolver._stats,
                           f'{f} 应在 _stats')

    def test_parse_fail_counter(self):
        self.assertIn('llm_parse_fail', self.resolver._stats,
                       '应有 llm_parse_fail 计数')


class TestD_TelemetryPersist(unittest.TestCase):
    """telemetry 持久化到 JSON 行为 check."""

    def setUp(self):
        from jarvis_intent_resolver import IntentResolver
        self.resolver = IntentResolver(
            key_router=None, central_nerve=None, tool_registry={},
        )
        # 改 stats 看 persist
        self.resolver._stats['llm_primary_calls'] = 100
        self.resolver._stats['llm_primary_ok'] = 95
        self.resolver._stats['llm_primary_latency_sum_ms'] = 234567.0
        self.resolver._stats['llm_fallback_calls'] = 5

    def test_persist_writes_json(self):
        # cwd 临时切到 tmp 防污染
        tmpdir = tempfile.mkdtemp()
        cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            self.resolver._persist_telemetry()
            path = os.path.join('memory_pool', 'intent_resolver_telemetry.json')
            self.assertTrue(os.path.exists(path),
                              'telemetry JSON 应写到 memory_pool/')
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.assertEqual(data['primary_model'], 'google/gemini-3.5-flash')
            self.assertEqual(data['stats']['llm_primary_calls'], 100)
            self.assertEqual(data['stats']['llm_primary_ok'], 95)
        finally:
            os.chdir(cwd)
            try:
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass

    def test_persist_atomic(self):
        """tmp + replace 路径."""
        import jarvis_intent_resolver
        with open(jarvis_intent_resolver.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        idx = src.find('def _persist_telemetry')
        self.assertGreater(idx, 0)
        body = src[idx:idx + 1500]
        self.assertIn('os.replace', body, '应用 os.replace atomic 写')
        self.assertIn('.tmp', body, '应先写 tmp 文件')


class TestE_CLIScriptImports(unittest.TestCase):
    """CLI script 可 import + 关键函数存在."""

    def test_import_and_functions(self):
        import importlib.util
        cli_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'intent_resolver_telemetry_dump.py')
        self.assertTrue(os.path.exists(cli_path),
                          'CLI script 应在 scripts/')
        spec = importlib.util.spec_from_file_location('ir_dump_test', cli_path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)  # type: ignore
        self.assertTrue(hasattr(m, 'cmd_show'),
                          '应有 cmd_show 函数')
        self.assertTrue(hasattr(m, 'cmd_reset'),
                          '应有 cmd_reset 函数')


class TestF_MainBrainStaysStable(unittest.TestCase):
    """主脑 chat_bypass 不切 3.5-flash (Sir 准则 1 高效 + 准则 3 butler 短句)."""

    def test_chat_bypass_main_model_unchanged(self):
        import jarvis_chat_bypass
        with open(jarvis_chat_bypass.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # ChatBypass 主对话 model_name 仍是 3-flash-preview, 不能是 3.5
        self.assertIn("'gemini-3-flash-preview'", src,
                       '主对话 model 应仍是 gemini-3-flash-preview (不动)')
        # 主对话 OR 路径 (line 700, 2252) 也是 3-flash-preview
        # 不直接 assertNotIn '3.5-flash' (config JSON 可能引用), 看 ChatBypass 类
        idx_class = src.find('class ChatBypass')
        self.assertGreater(idx_class, 0)
        # 看 ChatBypass.__init__ self.model_name
        idx_init = src.find('def __init__', idx_class)
        body_init = src[idx_init:idx_init + 1500]
        self.assertIn('gemini-3-flash-preview', body_init,
                       'ChatBypass.__init__.self.model_name 应仍是 3-flash-preview')


class TestG_ConductorStaysStable(unittest.TestCase):
    """Conductor sentinel 决策 model 不动 (高频, 不切 3.5)."""

    def test_conductor_uses_lite(self):
        import jarvis_conductor
        with open(jarvis_conductor.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # Conductor 决策模型应仍是 lite 系列 (高频)
        self.assertIn('flash-lite', src,
                       'Conductor 应仍用 flash-lite (高频省价)')
        # 不应切 3.5-flash 主路径
        # (允许 fallback 包含 3.5, 但 primary 不应)


if __name__ == '__main__':
    unittest.main()
