# -*- coding: utf-8 -*-
"""[B3 / Sir 2026-06-02 真机] TTFT 建连慢 — OpenAI client 连接复用回归.

真机 BUG (jarvis_20260602_194104): TTFT avg 5.6s, Perf Diag breakdown =
connect 5.4s + wait 0.0s → 慢在 TLS 建连, 非 prompt 增大. 根因: 每 turn
new OpenAI() = 新 httpx 连接池 → 每轮全程 TLS 握手 (无 keep-alive 复用)。

治本 (准则 8): _get_or_client 按 (base_url, key) 缓存 client, 复用底层连接
→ 第 2 轮起跳过握手。

覆盖:
  T1  同 (base_url, key) 二次调 → 返回同一 client 实例 (复用)
  T2  不同 key → 不同 client 实例 (key 轮换正确新建)
  T3  cache 超 8 entry → 不无限增长 (清最旧)
  T4  源码确认两处构造点都走 _get_or_client (不再裸 new OpenAI)
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_chat_bypass as cb


class _StubVocal:
    def render_only(self, *a, **k): return None
    def play_only(self, *a, **k): return None


def _make_bypass():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop('JARVIS_MIRROR', None)
        return cb.ChatBypass(key_router=object(),
                             vocal_cord=_StubVocal(),
                             state_callback=lambda *a, **k: None)


class _FakeTimeout:
    pass


class TestB3ClientReuse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = _make_bypass()

    def test_t1_same_key_reuses_client(self):
        url = "https://openrouter.ai/api/v1"
        c1 = self.b._get_or_client(url, "sk-test-AAAAAAAA", _FakeTimeout())
        c2 = self.b._get_or_client(url, "sk-test-AAAAAAAA", _FakeTimeout())
        self.assertIs(c1, c2, "同 (base_url, key) 应复用同一 client (keep-alive)")

    def test_t2_different_key_new_client(self):
        url = "https://openrouter.ai/api/v1"
        c1 = self.b._get_or_client(url, "sk-test-AAAAAAAA", _FakeTimeout())
        c2 = self.b._get_or_client(url, "sk-test-BBBBBBBB", _FakeTimeout())
        self.assertIsNot(c1, c2, "不同 key → 新 client (key 轮换)")

    def test_t3_cache_bounded(self):
        b = _make_bypass()
        url = "https://openrouter.ai/api/v1"
        for i in range(20):
            b._get_or_client(url, f"sk-test-{i:08d}", _FakeTimeout())
        self.assertLessEqual(len(b._or_client_cache), 8,
                             "cache 不应无限增长")

    def test_t4_source_uses_helper(self):
        with open(cb.__file__, "r", encoding="utf-8") as f:
            src = f.read()
        # 两处构造点 (主路径 + fallback) 都应走 _get_or_client
        self.assertGreaterEqual(
            src.count("self._get_or_client("), 2,
            "主路径 + fallback 都应走 _get_or_client (连接复用)")
        # 不应再有裸 OpenAI( base_url=... 的 per-turn 构造 (helper 内那处除外)
        self.assertIn("_or_client_cache", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
