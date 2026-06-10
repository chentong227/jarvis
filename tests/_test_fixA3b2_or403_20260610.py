# -*- coding: utf-8 -*-
"""[A3b-2 / Sir 2026-06-10] 共享 403 helper + _try_openrouter 区域 403 修毒 key + 3-flash 路由.

根因: _try_openrouter 老 AUTH 分支含 '403'/'forbidden' → 区域 403 (出口 IP 受限,
与 key 无关) 被 report_error 毒好 key. 治本: 共享纯函数 helper (_is_region_403 +
_should_retry_403), 区域 403 → 同 key 同 client 原地短退避重试, 耗尽 release 不毒;
真 AUTH 401 保持原毒 key 逻辑. 全 mock, 不打真 OpenRouter, 不写真档案.

T1 _is_region_403 判定 (区域 403 命中 / 普通错不命中 / 401 不命中 / auth 串优先)
T2 _should_retry_403 (未达上限 True / 达上限 False / max=0 关闭)
T3 _try_openrouter 区域 403 → 同 key 短退避重试, 不毒 key 不换 key
T4 区域 403 耗尽 → release 落正常轮转 (换 key / 抛), 仍不毒 key
T5 真 AUTH 401 → 仍毒 key ([AUTH] report_error 原逻辑保留)
T6 safe_openrouter_call 重构后 fixB 403 行为不变 (回归)
T7 3-flash force_openrouter 定向走 _try_openrouter (不碰 Google)
T8 key 轮转 / limiter acquire/release 平衡无回归
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_utils as JU  # noqa: E402

REGION_403 = '403 not available in your region'
AUTH_401 = '401 unauthorized invalid api key'


class _FakeMsg:
    def __init__(self, content):
        self.message = type('M', (), {'content': content})


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeMsg(content)]


def _client_with(side_effects):
    client = mock.MagicMock()
    client.chat.completions.create.side_effect = side_effects
    return client


class TestT1IsRegion403(unittest.TestCase):
    def test_region_403_variants_hit(self):
        for s in (REGION_403,
                  '403 Forbidden',
                  'Error code: 403 - provider blocked',
                  'Access Denied by upstream'):
            self.assertTrue(JU._is_region_403(s), s)

    def test_plain_errors_miss(self):
        for s in ('500 internal server error', '429 rate limit',
                  'timeout', '', None):
            self.assertFalse(JU._is_region_403(s), repr(s))

    def test_401_auth_miss(self):
        for s in (AUTH_401, '401 unauthorized', 'invalid_key'):
            self.assertFalse(JU._is_region_403(s), s)

    def test_auth_keyword_wins_over_403(self):
        # 403 + auth 串 → 真 AUTH 优先, 不算区域 403
        self.assertFalse(JU._is_region_403('403 api key not valid'))
        self.assertFalse(JU._is_region_403('403 API_KEY_INVALID'))


class TestT2ShouldRetry403(unittest.TestCase):
    def test_under_cap_true(self):
        self.assertTrue(JU._should_retry_403(1, 2))
        self.assertTrue(JU._should_retry_403(2, 2))

    def test_at_cap_false(self):
        self.assertFalse(JU._should_retry_403(3, 2))

    def test_zero_disables(self):
        self.assertFalse(JU._should_retry_403(1, 0))


class _GeminiCallBase(unittest.TestCase):
    """safe_gemini_call._try_openrouter 路径共用脚手架 (全 mock)."""

    FORCE_OR = {'force_openrouter': ['gemini-3-flash-preview'],
                'google_only_no_fallback': []}

    def _run(self, kr, client, **kw):
        limiter = mock.MagicMock()
        defaults = dict(caller='test', model_tier='flash',
                        call_func=lambda c: None,
                        model_name='gemini-3-flash-preview',
                        contents_text='x', max_retries=1,
                        delay_403=0.01)
        defaults.update(kw)
        with mock.patch.object(JU, '_load_google_model_routing',
                               lambda: dict(self.FORCE_OR)):
            with mock.patch.object(JU, 'get_rate_limiter',
                                   return_value=limiter):
                with mock.patch.object(JU, 'bg_log', mock.MagicMock()):
                    with mock.patch('openai.OpenAI', return_value=client):
                        result = JU.safe_gemini_call(kr, **defaults)
        return result, limiter


class TestT3Region403SameKeyRetry(_GeminiCallBase):
    def test_region_403_retries_same_key_no_poison(self):
        kr = mock.MagicMock()
        kr.get_openrouter_key.return_value = ('sk-1', 'openrouter_1')
        client = _client_with([Exception(REGION_403), _FakeResp('REC')])

        (res, key_name, _), limiter = self._run(kr, client)

        self.assertEqual(res.text, 'REC')
        self.assertEqual(key_name, 'openrouter_1')
        # 同 key 原地重试: 只 acquire 了一次 key, create 调了 2 次
        self.assertEqual(kr.get_openrouter_key.call_count, 1)
        self.assertEqual(client.chat.completions.create.call_count, 2)
        # 不毒 key, 不 release 换 key (成功路径 key 归 caller release)
        kr.report_error.assert_not_called()
        kr.release.assert_not_called()
        # limiter 平衡: 1 acquire = 1 release
        self.assertEqual(limiter.acquire.call_count, 1)
        self.assertEqual(limiter.release.call_count, 1)


class TestT4Region403ExhaustNoPoison(_GeminiCallBase):
    def test_exhaust_releases_rotates_never_poisons(self):
        kr = mock.MagicMock()
        kr.get_openrouter_key.side_effect = [('sk-1', 'openrouter_1'),
                                             ('sk-2', 'openrouter_2')]
        client = _client_with(Exception(REGION_403))

        with self.assertRaises(RuntimeError) as cm:
            self._run(kr, client, max_403_retries=2)

        self.assertIn('OpenRouter', str(cm.exception))
        # 每把 key: 1 初次 + 2 重试 = 3 次; 两把 key 轮转 = 6 次
        self.assertEqual(client.chat.completions.create.call_count, 6)
        self.assertEqual(kr.get_openrouter_key.call_count, 2)
        # 耗尽 → release 落正常轮转, 但绝不 report_error 毒键
        kr.report_error.assert_not_called()
        released = [c.args[0] for c in kr.release.call_args_list]
        self.assertEqual(released, ['openrouter_1', 'openrouter_2'])


class TestT5RealAuth401StillPoisons(_GeminiCallBase):
    def test_auth_401_reports_error(self):
        kr = mock.MagicMock()
        kr.get_openrouter_key.side_effect = [('sk-1', 'openrouter_1'),
                                             RuntimeError('no key')]
        client = _client_with(Exception(AUTH_401))

        with self.assertRaises(RuntimeError):
            self._run(kr, client)

        # 真 AUTH → 原毒 key 逻辑保留: report_error('[AUTH] ...') + release
        self.assertEqual(kr.report_error.call_count, 1)
        name, msg = kr.report_error.call_args.args
        self.assertEqual(name, 'openrouter_1')
        self.assertTrue(msg.startswith('[AUTH]'))
        kr.release.assert_called_once_with('openrouter_1')
        self.assertEqual(client.chat.completions.create.call_count, 1)


class TestT6FixBBehaviorUnchanged(unittest.TestCase):
    """safe_openrouter_call 重构走 helper 后, fixB 403 行为逐项不变."""

    def _call(self, client, **kw):
        defaults = dict(openrouter_key='sk-test', model='zzz/none',
                        prompt='hi', max_tokens=5, max_retries=3,
                        base_delay=0.01, delay_403=0.01)
        defaults.update(kw)
        with mock.patch('openai.OpenAI', return_value=client):
            return JU.safe_openrouter_call(**defaults)

    def test_403_limited_retry_then_raise(self):
        client = _client_with([Exception(REGION_403)] * 5)
        with self.assertRaises(RuntimeError):
            self._call(client, max_403_retries=2)
        self.assertEqual(client.chat.completions.create.call_count, 3)

    def test_403_then_success(self):
        client = _client_with([Exception('403 forbidden'), _FakeResp('OK')])
        self.assertEqual(self._call(client, max_403_retries=2), 'OK')
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_403_zero_disables(self):
        client = _client_with([Exception('403 forbidden')] * 3)
        with self.assertRaises(RuntimeError):
            self._call(client, max_403_retries=0)
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_401_immediate_raise(self):
        client = _client_with([Exception(AUTH_401)] * 3)
        with self.assertRaises(RuntimeError):
            self._call(client)
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_403_counter_independent_of_retry_budget(self):
        # 403 重试不吃 max_retries 预算: 403 → 429 → 成功 = 3 次调用
        client = _client_with([Exception(REGION_403),
                               Exception('429 rate limit'),
                               _FakeResp('MIX')])
        self.assertEqual(self._call(client, max_403_retries=2), 'MIX')
        self.assertEqual(client.chat.completions.create.call_count, 3)


class TestT7ThreeFlashForceOpenrouter(_GeminiCallBase):
    def test_3flash_routes_to_openrouter_only(self):
        kr = mock.MagicMock()
        kr.get_openrouter_key.return_value = ('sk-1', 'openrouter_1')
        client = _client_with([_FakeResp('hi')])

        (res, _, _), _ = self._run(kr, client)

        self.assertEqual(res.text, 'hi')
        # 定向 OpenRouter: Google 通道完全不碰
        kr.get_google_key.assert_not_called()
        # _OR_MODEL_MAP 映射到真 Gemini 3 (不降级 2.5)
        sent_model = client.chat.completions.create.call_args.kwargs['model']
        self.assertEqual(sent_model, 'google/gemini-3-flash-preview')

    def test_vocab_file_seed_consistent(self):
        # 真 vocab 文件自包含可载入, 3-flash 在 force_openrouter
        JU._google_routing_cache['data'] = None
        JU._google_routing_cache['mtime'] = 0.0
        r = JU._load_google_model_routing()
        self.assertIn('gemini-3-flash-preview', r['force_openrouter'])

    def test_cli_smoke_list(self):
        # CLI 自包含 (own path + stdlib), list 模式跑通
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'utf-8'
        p = subprocess.run(
            [sys.executable, os.path.join(ROOT, 'scripts',
                                          'google_routing_dump.py')],
            capture_output=True, timeout=60, env=env, cwd=ROOT)
        self.assertEqual(p.returncode, 0, p.stderr.decode('utf-8', 'replace'))
        self.assertIn('force_openrouter', p.stdout.decode('utf-8', 'replace'))


class TestT8RotationLimiterNoRegression(_GeminiCallBase):
    def test_quota_rotates_to_next_key_limiter_balanced(self):
        kr = mock.MagicMock()
        kr.get_openrouter_key.side_effect = [('sk-1', 'openrouter_1'),
                                             ('sk-2', 'openrouter_2')]
        client = _client_with([Exception('429 rate limit'), _FakeResp('OK2')])

        (res, key_name, _), limiter = self._run(kr, client)

        self.assertEqual(res.text, 'OK2')
        self.assertEqual(key_name, 'openrouter_2')
        # 老轮转保留: 429 → [QUOTA] report + release key1 → 换 key2 成功
        self.assertEqual(kr.get_openrouter_key.call_count, 2)
        self.assertEqual(kr.report_error.call_count, 1)
        name, msg = kr.report_error.call_args.args
        self.assertEqual(name, 'openrouter_1')
        self.assertTrue(msg.startswith('[QUOTA]'))
        kr.release.assert_called_once_with('openrouter_1')
        # limiter 平衡: 2 acquire = 2 release (失败 1 + 成功 1)
        self.assertEqual(limiter.acquire.call_count, 2)
        self.assertEqual(limiter.release.call_count, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
