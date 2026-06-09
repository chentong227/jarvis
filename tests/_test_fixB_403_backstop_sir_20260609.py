# -*- coding: utf-8 -*-
"""[fixB-403-region-backstop / Sir 2026-06-09] 403 区域兜底有限重试.

safe_openrouter_call: 403 (区域封) 偶发打死调用 → 同节点有限重试 backstop
(救间歇 403; 固定坏节点救不了, 耗尽 raise). 429/401/402/404 行为逐字节不变.
正常路径零额外调用/零延迟. mock client (不真打).

T1 成功路径零回归: 正常返回 → 一次调用、零重试。
T2 403 有限重试: 连续 403 → 重试 max_403_retries 次后 raise (不无限)。
T3 403 后成功: 第1次 403、第2次成功 → 返回成功 (间歇 403 被救)。
T4 429 不变: 429 → 走原 is_retryable 指数退避 (不被 403 分支影响)。
T5 401/402/404 立即 raise: 各自 → 立即 raise 不重试。
T6 max_403_retries=0 关闭: 403 → 立即 raise (回滚开关)。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _FakeMsg:
    def __init__(self, content):
        self.message = type('M', (), {'content': content})


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeMsg(content)]


def _make_client(side_effects):
    """side_effects: list of Exception 或 返回值; 模拟 client.chat.completions.create."""
    client = mock.MagicMock()
    client.chat.completions.create.side_effect = side_effects
    return client


def _err(msg):
    return Exception(msg)


class TestFixB403Backstop(unittest.TestCase):

    def _patch_openai(self, client):
        # patch openai.OpenAI 返回 mock client
        import jarvis_utils
        return mock.patch('openai.OpenAI', return_value=client)

    def _call(self, **kw):
        from jarvis_utils import safe_openrouter_call
        # 关闭 deepseek routing 干扰: 用一个不在 replace_models 的 model
        defaults = dict(openrouter_key='sk-test', model='zzz/none',
                        prompt='hi', max_tokens=5, max_retries=3,
                        base_delay=0.01, delay_403=0.01)
        defaults.update(kw)
        return safe_openrouter_call(**defaults)

    def test_t1_success_no_retry(self):
        client = _make_client([_FakeResp('OK')])
        with self._patch_openai(client):
            r = self._call()
        self.assertEqual(r, 'OK')
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_t2_403_limited_retry_then_raise(self):
        client = _make_client([_err('403 not available in your region')] * 5)
        with self._patch_openai(client):
            with self.assertRaises(RuntimeError):
                self._call(max_403_retries=2)
        # 1 初次 + 2 重试 = 3 次调用 (不无限)
        self.assertEqual(client.chat.completions.create.call_count, 3)

    def test_t3_403_then_success(self):
        client = _make_client([_err('403 forbidden'), _FakeResp('RECOVERED')])
        with self._patch_openai(client):
            r = self._call(max_403_retries=2)
        self.assertEqual(r, 'RECOVERED')
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_t4_429_unchanged_retryable(self):
        # 429 走原 is_retryable; 3 次都 429 → raise (与现有逻辑同)
        client = _make_client([_err('429 rate limit')] * 5)
        with self._patch_openai(client):
            with self.assertRaises(RuntimeError):
                self._call(max_retries=3)
        # 原逻辑: attempt 0,1 重试 (< max_retries-1), attempt 2 break → 3 次调用
        self.assertEqual(client.chat.completions.create.call_count, 3)

    def test_t5_401_immediate_raise(self):
        client = _make_client([_err('401 unauthorized')] * 3)
        with self._patch_openai(client):
            with self.assertRaises(RuntimeError):
                self._call()
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_t5b_402_immediate_raise(self):
        client = _make_client([_err('402 insufficient credits')] * 3)
        with self._patch_openai(client):
            with self.assertRaises(RuntimeError):
                self._call()
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_t5c_404_immediate_raise(self):
        client = _make_client([_err('404 model not found')] * 3)
        with self._patch_openai(client):
            with self.assertRaises(RuntimeError):
                self._call()
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_t6_403_retries_zero_disables(self):
        client = _make_client([_err('403 forbidden')] * 3)
        with self._patch_openai(client):
            with self.assertRaises(RuntimeError):
                self._call(max_403_retries=0)
        # 0 重试 = 立即 raise = 1 次调用 (回滚开关)
        self.assertEqual(client.chat.completions.create.call_count, 1)


if __name__ == '__main__':
    unittest.main()
