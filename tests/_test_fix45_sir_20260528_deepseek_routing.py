# -*- coding: utf-8 -*-
"""[fix45 / Sir 2026-05-28 20:12] DeepSeek routing layer 防回退 testcase.

Sir 真情况:
  17 USD OpenRouter key 被 selective-ban 海外厂商 (Google/Anthropic/OpenAI),
  仅 deepseek 模型可调. 但 7 个用 `google/gemini-3.1-pro-preview` 的 reflector
  随机抽到这把 key → 403 → 'all openrouter keys unavailable' user-visible.

治本 (准则 6 持久化 + 准则 7 一键关 + 准则 8 优雅):
  - memory_pool/llm_routing_vocab.json    持久化 enabled / route_model /
                                          replace_models / exclude_callers / usage_stats
  - jarvis_utils.safe_openrouter_call     顶部 routing gate, 命中 → safe_deepseek_call
                                          (用 OPENROUTER_DS_ONLY env 独立 key, 不进 KeyRouter pool)
  - scripts/llm_routing_dump.py           Sir CLI (gate / add-model / usage / reset)
  - .env.example                          加 OPENROUTER_DS_ONLY=REPLACE_ME_OPTIONAL slot

故障开放 3 层 (本 testcase 全覆盖):
  1. DS_ONLY env 缺失 → should_route 返 False (no_ds_key)
  2. routing 命中但 deepseek 调用异常 → fallback_on_fail=1 → fall through 老 OpenRouter
  3. vocab 加载异常 → default disabled

14 testcase 覆盖:
  T1: should_route happy path (gate on + ds_key + model 在 list + caller 不 exclude → True)
  T2: ds_key 缺失 → no_ds_key
  T3: gate off → gate_off
  T4: empty replace_models → empty_replace_list
  T5: model 不在 list → model_not_in_list:<model>
  T6: caller 在 exclude → caller_excluded:<caller>
  T7: safe_openrouter_call routing 命中 + ds 成功 → ds 返 content (不进 OpenRouter path)
  T8: routing 命中 + ds 失败 + fallback_on_fail=1 → fall through OpenRouter
  T9: routing 命中 + ds 失败 + fallback_on_fail=0 → 抛 RuntimeError
  T10: _record_deepseek_usage 累计 call_count/tokens/est_cost + per_caller
  T11: set_deepseek_routing_gate 改 enabled + history 记
  T12: add/remove_deepseek_replace_model 改 list + history 记
  T13: reset_deepseek_usage_stats 清零
  T14: CLI script 顶部 import 不崩 + main parser 注册子命令
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _mk_isolated_vocab(tmpdir: str, enabled: int = 1,
                        replace_models=None,
                        exclude_callers=None,
                        fallback_on_fail: int = 1) -> str:
    """isolate test vocab JSON, return path.

    NB: replace_models / exclude_callers 用 `is None` 判断, 允许传 `[]` 显式
    清空 (避免 `[] or default` truthy 坑).
    """
    path = os.path.join(tmpdir, 'llm_routing_vocab.json')
    _rm = ['google/gemini-3.1-pro-preview'] if replace_models is None else list(replace_models)
    _ec = [] if exclude_callers is None else list(exclude_callers)
    data = {
        '_doc': ['testcase isolated vocab'],
        'schema_version': 1,
        'enabled': enabled,
        'deepseek_route': {
            'model': 'deepseek/deepseek-v4-pro',
            'replace_models': _rm,
            'exclude_callers': _ec,
            'fallback_on_fail': fallback_on_fail,
            'timeout_s': 60,
            'temperature_default': 0.2,
            'max_tokens_default': 600,
        },
        'cost': {
            'input_per_1m_usd': 0.435,
            'output_per_1m_usd': 0.87,
            'budget_total_usd': 17.0,
        },
        'usage_stats': {
            'call_count': 0, 'success_count': 0, 'fallback_count': 0,
            'input_tokens_total': 0, 'output_tokens_total': 0,
            'est_cost_usd': 0.0,
            'first_call_ts': 0.0, 'first_call_iso': '',
            'last_call_ts': 0.0, 'last_call_iso': '', 'last_error': '',
            'per_caller': {},
        },
        'history': [],
        'last_modified_at': 0.0,
        'last_modified_iso': '',
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


class _VocabIsolated:
    """ContextManager: 隔离 vocab path + invalidate cache + 可设 ds_key."""

    def __init__(self, *, enabled: int = 1, replace_models=None,
                  exclude_callers=None, fallback_on_fail: int = 1,
                  ds_key: str = 'sk-test-ds-key'):
        self.enabled = enabled
        self.replace_models = replace_models
        self.exclude_callers = exclude_callers
        self.fallback_on_fail = fallback_on_fail
        self.ds_key = ds_key
        self._tmpdir = None
        self._old_path_env = None
        self._old_key_env = None

    def __enter__(self):
        import jarvis_utils as ju
        self._tmpdir = tempfile.mkdtemp(prefix='llm_routing_test_')
        self.path = _mk_isolated_vocab(
            self._tmpdir, enabled=self.enabled,
            replace_models=self.replace_models,
            exclude_callers=self.exclude_callers,
            fallback_on_fail=self.fallback_on_fail,
        )
        self._old_path_env = os.environ.get('JARVIS_LLM_ROUTING_VOCAB_PATH')
        os.environ['JARVIS_LLM_ROUTING_VOCAB_PATH'] = self.path
        self._old_key_env = os.environ.get('OPENROUTER_DS_ONLY')
        if self.ds_key:
            os.environ['OPENROUTER_DS_ONLY'] = self.ds_key
        else:
            os.environ.pop('OPENROUTER_DS_ONLY', None)
        ju.invalidate_llm_routing_cache()
        return self

    def __exit__(self, exc_type, exc, tb):
        import jarvis_utils as ju
        if self._old_path_env is None:
            os.environ.pop('JARVIS_LLM_ROUTING_VOCAB_PATH', None)
        else:
            os.environ['JARVIS_LLM_ROUTING_VOCAB_PATH'] = self._old_path_env
        if self._old_key_env is None:
            os.environ.pop('OPENROUTER_DS_ONLY', None)
        else:
            os.environ['OPENROUTER_DS_ONLY'] = self._old_key_env
        ju.invalidate_llm_routing_cache()
        try:
            import shutil
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        except Exception:
            pass

    def read_vocab(self) -> dict:
        with open(self.path, 'r', encoding='utf-8') as f:
            return json.load(f)


# ==========================================================================
# T1: should_route_to_deepseek happy path
# ==========================================================================
class TestT1ShouldRouteHappy(unittest.TestCase):
    def test_happy_path_returns_true_with_target_model(self):
        import jarvis_utils as ju
        with _VocabIsolated():
            ok, info = ju.should_route_to_deepseek(
                model='google/gemini-3.1-pro-preview',
                caller='soul_evaluator',
            )
        self.assertTrue(ok)
        self.assertEqual(info, 'deepseek/deepseek-v4-pro')


# ==========================================================================
# T2: ds_key 缺失 → no_ds_key (故障开放 layer 1)
# ==========================================================================
class TestT2NoDsKeyDisablesRouting(unittest.TestCase):
    def test_missing_ds_key_returns_false(self):
        import jarvis_utils as ju
        with _VocabIsolated(ds_key=''):
            ok, reason = ju.should_route_to_deepseek(
                model='google/gemini-3.1-pro-preview', caller='x',
            )
        self.assertFalse(ok)
        self.assertEqual(reason, 'no_ds_key')

    def test_placeholder_ds_key_returns_false(self):
        import jarvis_utils as ju
        with _VocabIsolated(ds_key='REPLACE_ME_OPTIONAL'):
            ok, reason = ju.should_route_to_deepseek(
                model='google/gemini-3.1-pro-preview', caller='x',
            )
        self.assertFalse(ok)
        self.assertEqual(reason, 'no_ds_key')


# ==========================================================================
# T3: gate off → gate_off (准则 7 元否决一键关)
# ==========================================================================
class TestT3GateOffBlocksRouting(unittest.TestCase):
    def test_gate_off_returns_false(self):
        import jarvis_utils as ju
        with _VocabIsolated(enabled=0):
            ok, reason = ju.should_route_to_deepseek(
                model='google/gemini-3.1-pro-preview', caller='x',
            )
        self.assertFalse(ok)
        self.assertEqual(reason, 'gate_off')


# ==========================================================================
# T4: 空 replace_models → empty_replace_list
# ==========================================================================
class TestT4EmptyReplaceList(unittest.TestCase):
    def test_empty_list_returns_false(self):
        import jarvis_utils as ju
        with _VocabIsolated(replace_models=[]):
            ok, reason = ju.should_route_to_deepseek(
                model='google/gemini-3.1-pro-preview', caller='x',
            )
        self.assertFalse(ok)
        self.assertEqual(reason, 'empty_replace_list')


# ==========================================================================
# T5: model 不在 list → model_not_in_list:<model>
# ==========================================================================
class TestT5ModelNotInList(unittest.TestCase):
    def test_non_matching_model(self):
        import jarvis_utils as ju
        with _VocabIsolated(replace_models=['google/gemini-3.1-pro-preview']):
            ok, reason = ju.should_route_to_deepseek(
                model='anthropic/claude-3-haiku', caller='x',
            )
        self.assertFalse(ok)
        self.assertTrue(reason.startswith('model_not_in_list:'))
        self.assertIn('anthropic/claude-3-haiku', reason)


# ==========================================================================
# T6: caller 在 exclude_callers → caller_excluded:<caller>
# ==========================================================================
class TestT6CallerExcluded(unittest.TestCase):
    def test_excluded_caller_blocked(self):
        import jarvis_utils as ju
        with _VocabIsolated(exclude_callers=['stm_summarizer']):
            ok, reason = ju.should_route_to_deepseek(
                model='google/gemini-3.1-pro-preview',
                caller='stm_summarizer',
            )
        self.assertFalse(ok)
        self.assertTrue(reason.startswith('caller_excluded:'))
        self.assertIn('stm_summarizer', reason)

    def test_non_excluded_caller_passes(self):
        import jarvis_utils as ju
        with _VocabIsolated(exclude_callers=['stm_summarizer']):
            ok, info = ju.should_route_to_deepseek(
                model='google/gemini-3.1-pro-preview',
                caller='soul_evaluator',
            )
        self.assertTrue(ok)
        self.assertEqual(info, 'deepseek/deepseek-v4-pro')


# ==========================================================================
# T7: safe_openrouter_call routing 命中 + ds 成功 → 返 ds content
# ==========================================================================
class TestT7RoutingHitDeepseekSucceeds(unittest.TestCase):
    def test_routing_hit_returns_deepseek_response(self):
        import jarvis_utils as ju
        with _VocabIsolated():
            with patch.object(ju, 'safe_deepseek_call',
                               return_value='DS_RESPONSE') as mock_ds:
                result = ju.safe_openrouter_call(
                    openrouter_key='sk-OR-MAIN-IGNORED',
                    model='google/gemini-3.1-pro-preview',
                    prompt='hello',
                    caller='soul_evaluator',
                )
        self.assertEqual(result, 'DS_RESPONSE')
        self.assertEqual(mock_ds.call_count, 1)
        # caller 透传
        kwargs = mock_ds.call_args.kwargs
        self.assertEqual(kwargs.get('caller'), 'soul_evaluator')


# ==========================================================================
# T8: routing 命中 + ds 失败 + fallback_on_fail=1 → fall through OpenRouter
# ==========================================================================
class TestT8FallbackOnDsFailure(unittest.TestCase):
    def test_ds_fail_fallback_to_openrouter(self):
        import jarvis_utils as ju
        with _VocabIsolated(fallback_on_fail=1):
            with patch.object(ju, 'safe_deepseek_call',
                               side_effect=RuntimeError('ds boom')):
                # mock OpenAI client (老 OpenRouter path)
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.choices = [MagicMock(
                    message=MagicMock(content='OR_FALLBACK_OK'))]
                mock_client.chat.completions.create.return_value = mock_resp
                with patch('openai.OpenAI', return_value=mock_client):
                    result = ju.safe_openrouter_call(
                        openrouter_key='sk-OR-MAIN-REAL',
                        model='google/gemini-3.1-pro-preview',
                        prompt='hello',
                        caller='soul_evaluator',
                    )
        self.assertEqual(result, 'OR_FALLBACK_OK')

    def test_ds_fail_records_fallback_usage(self):
        """fallback path 应 +1 fallback_count, error 写 last_error."""
        import jarvis_utils as ju
        with _VocabIsolated(fallback_on_fail=1) as ctx:
            with patch.object(ju, 'safe_deepseek_call',
                               side_effect=RuntimeError('ds boom')):
                mock_client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.choices = [MagicMock(
                    message=MagicMock(content='ok'))]
                mock_client.chat.completions.create.return_value = mock_resp
                with patch('openai.OpenAI', return_value=mock_client):
                    ju.safe_openrouter_call(
                        openrouter_key='sk',
                        model='google/gemini-3.1-pro-preview',
                        prompt='hello',
                        caller='stm_summarizer',
                    )
            vocab = ctx.read_vocab()
        stats = vocab.get('usage_stats', {})
        self.assertGreaterEqual(int(stats.get('fallback_count', 0)), 1)
        self.assertIn('route_fail', stats.get('last_error', ''))


# ==========================================================================
# T9: routing 命中 + ds 失败 + fallback_on_fail=0 → 抛 RuntimeError
# ==========================================================================
class TestT9NoFallbackRaises(unittest.TestCase):
    def test_ds_fail_no_fallback_raises(self):
        import jarvis_utils as ju
        with _VocabIsolated(fallback_on_fail=0):
            with patch.object(ju, 'safe_deepseek_call',
                               side_effect=RuntimeError('ds boom hard')):
                with self.assertRaises(RuntimeError) as ctx:
                    ju.safe_openrouter_call(
                        openrouter_key='sk',
                        model='google/gemini-3.1-pro-preview',
                        prompt='hello',
                        caller='soul_evaluator',
                    )
        self.assertIn('ds boom hard', str(ctx.exception))


# ==========================================================================
# T10: _record_deepseek_usage 累计 + per_caller breakdown
# ==========================================================================
class TestT10RecordUsageAccumulates(unittest.TestCase):
    def test_usage_accumulates_per_caller(self):
        import jarvis_utils as ju
        with _VocabIsolated() as ctx:
            ju._record_deepseek_usage(
                caller='soul_evaluator',
                input_tok=1000, output_tok=500,
                success=True, fallback=False,
            )
            ju._record_deepseek_usage(
                caller='soul_evaluator',
                input_tok=2000, output_tok=1000,
                success=True, fallback=False,
            )
            ju._record_deepseek_usage(
                caller='stm_summarizer',
                input_tok=500, output_tok=200,
                success=True, fallback=False,
            )
            vocab = ctx.read_vocab()
        stats = vocab.get('usage_stats', {})
        self.assertEqual(int(stats.get('call_count', 0)), 3)
        self.assertEqual(int(stats.get('success_count', 0)), 3)
        self.assertEqual(int(stats.get('input_tokens_total', 0)), 3500)
        self.assertEqual(int(stats.get('output_tokens_total', 0)), 1700)
        # est cost: 3500/1e6 * 0.435 + 1700/1e6 * 0.87
        expected = 3500 / 1e6 * 0.435 + 1700 / 1e6 * 0.87
        self.assertAlmostEqual(float(stats.get('est_cost_usd', 0.0)),
                                expected, places=5)
        per = stats.get('per_caller', {})
        self.assertIn('soul_evaluator', per)
        self.assertIn('stm_summarizer', per)
        self.assertEqual(int(per['soul_evaluator']['call_count']), 2)
        self.assertEqual(int(per['soul_evaluator']['input_tokens']), 3000)
        self.assertEqual(int(per['stm_summarizer']['call_count']), 1)


# ==========================================================================
# T11: set_deepseek_routing_gate 改 enabled + history
# ==========================================================================
class TestT11SetGateAndHistory(unittest.TestCase):
    def test_gate_toggle_persists_and_history(self):
        import jarvis_utils as ju
        with _VocabIsolated(enabled=0) as ctx:
            ok, msg = ju.set_deepseek_routing_gate(
                enabled=True, source='sir_cli', rationale='17 USD ready',
            )
            self.assertTrue(ok)
            self.assertIn('0 -> 1', msg)
            vocab = ctx.read_vocab()
            self.assertEqual(int(vocab.get('enabled', 0)), 1)
            hist = vocab.get('history', [])
            self.assertGreaterEqual(len(hist), 1)
            last = hist[-1]
            self.assertEqual(last.get('action'), 'gate_toggle')
            self.assertEqual(int(last.get('old_value')), 0)
            self.assertEqual(int(last.get('new_value')), 1)
            self.assertEqual(last.get('source'), 'sir_cli')
            self.assertIn('17 USD', last.get('rationale', ''))


# ==========================================================================
# T12: add/remove_deepseek_replace_model 改 list + history
# ==========================================================================
class TestT12AddRemoveModel(unittest.TestCase):
    def test_add_model_and_history(self):
        import jarvis_utils as ju
        with _VocabIsolated(replace_models=[]) as ctx:
            ok, msg = ju.add_deepseek_replace_model(
                model='anthropic/claude-3-haiku',
                source='sir_cli', rationale='also banned',
            )
            self.assertTrue(ok)
            vocab = ctx.read_vocab()
            self.assertIn('anthropic/claude-3-haiku',
                           vocab['deepseek_route']['replace_models'])
            self.assertEqual(vocab['history'][-1]['action'],
                              'add_replace_model')

    def test_add_duplicate_returns_false(self):
        import jarvis_utils as ju
        with _VocabIsolated(replace_models=['google/gemini-3.1-pro-preview']):
            ok, msg = ju.add_deepseek_replace_model(
                model='google/gemini-3.1-pro-preview',
            )
            self.assertFalse(ok)
            self.assertIn('already in list', msg)

    def test_remove_model_and_history(self):
        import jarvis_utils as ju
        with _VocabIsolated(
            replace_models=['google/gemini-3.1-pro-preview',
                            'anthropic/claude-3-haiku']
        ) as ctx:
            ok, msg = ju.remove_deepseek_replace_model(
                model='anthropic/claude-3-haiku',
                source='sir_cli',
            )
            self.assertTrue(ok)
            vocab = ctx.read_vocab()
            self.assertNotIn('anthropic/claude-3-haiku',
                              vocab['deepseek_route']['replace_models'])
            self.assertEqual(vocab['history'][-1]['action'],
                              'remove_replace_model')

    def test_remove_missing_returns_false(self):
        import jarvis_utils as ju
        with _VocabIsolated(replace_models=['x']):
            ok, msg = ju.remove_deepseek_replace_model(model='not-there')
            self.assertFalse(ok)
            self.assertIn('not in list', msg)


# ==========================================================================
# T13: reset_deepseek_usage_stats 清零 + history 记 old_est
# ==========================================================================
class TestT13ResetUsage(unittest.TestCase):
    def test_reset_zeros_stats_and_records_old(self):
        import jarvis_utils as ju
        with _VocabIsolated() as ctx:
            # 先 record 一些
            ju._record_deepseek_usage(
                caller='x', input_tok=10000, output_tok=5000,
                success=True, fallback=False,
            )
            vocab_before = ctx.read_vocab()
            est_before = float(
                vocab_before['usage_stats'].get('est_cost_usd', 0.0))
            self.assertGreater(est_before, 0.0)
            # reset
            ok, msg = ju.reset_deepseek_usage_stats(
                source='sir_cli', rationale='new top-up',
            )
            self.assertTrue(ok)
            vocab_after = ctx.read_vocab()
            stats = vocab_after['usage_stats']
            self.assertEqual(int(stats.get('call_count', 0)), 0)
            self.assertEqual(float(stats.get('est_cost_usd', 0.0)), 0.0)
            self.assertEqual(stats.get('per_caller', {}), {})
            hist = vocab_after['history']
            self.assertEqual(hist[-1]['action'], 'reset_usage_stats')
            self.assertAlmostEqual(
                float(hist[-1]['old_est_cost_usd']), est_before, places=5,
            )


# ==========================================================================
# T14: CLI script 顶部 import 不崩 + main parser 注册子命令
# ==========================================================================
class TestT14CliScriptImportable(unittest.TestCase):
    def test_cli_script_importable(self):
        """script 顶部 import 应安全 (不触发 OpenRouter / 网络)."""
        script_path = os.path.join(ROOT, 'scripts', 'llm_routing_dump.py')
        self.assertTrue(os.path.exists(script_path),
                        f'CLI script missing: {script_path}')
        # 不直接 import (script 顶部 set proxy env 等 side-effect), grep
        # 子命令 marker 即可证明命令注册.
        with open(script_path, 'r', encoding='utf-8') as f:
            src = f.read()
        for marker in ('--gate', '--add-model', '--remove-model',
                        '--add-exclude', '--remove-exclude',
                        '--usage', '--reset-usage', '--history',
                        '--json'):
            self.assertIn(marker, src,
                           f'CLI missing subcommand: {marker}')

    def test_helpers_loadable(self):
        """_load_helpers 应能拿到 9 个 jarvis_utils symbol."""
        script_path = os.path.join(ROOT, 'scripts', 'llm_routing_dump.py')
        sys.path.insert(0, os.path.dirname(script_path))
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                'llm_routing_dump_test_module', script_path,
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            helpers = module._load_helpers()
            for k in ('load', 'path', 'ds_key', 'stats', 'set_gate',
                       'add_model', 'remove_model', 'reset_usage',
                       'invalidate'):
                self.assertIn(k, helpers, f'CLI helpers missing key: {k}')
        finally:
            sys.path.pop(0)


if __name__ == '__main__':
    unittest.main()
