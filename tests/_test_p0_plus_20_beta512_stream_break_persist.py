# -*- coding: utf-8 -*-
"""
[P0+20-β.5.12 / 2026-05-19] BUG: cloud stream 半路断 + 道歉拼接 = 体感分裂

Sir 21:37 实测原文 (jarvis_20260519_213xxx.log):
  Sir: "嗯，你说的有道理"
  Jarvis 主回复: "I try to be, Sir. It is often the most practical approach."  (cloud stream 已 fetch)
  突兀道歉:    "Forgive me Sir, the evening network traffic..."              (罐头)
  err:        RemoteProtocolError: peer closed connection (after 18.8s)
  full:       40.5s

3 层 BUG 一起修:
  BUG-A: except 路径无脑 _speak_fallback() 加道歉 — 不看 cloud stream 是否已实质成句
        修法: jarvis_chat_bypass.py:3199 加 spoken_so_far 守卫 (>= 12 字符净文本则跳过道歉)
  BUG-B: _create_stream 用 timeout=60.0 是 *total* request 超时, chunk 间无超时
        修法: jarvis_chat_bypass.py:683 改用 httpx.Timeout(read=12.0) 做 chunk inter-arrival
  BUG-C: _try_local_fallback 用 timeout=5.0, CosyVoice 占 GPU 时 qwen2.5:14b 排不上
        修法: jarvis_chat_bypass.py:782 改用 timeout=8.0

测试策略: 全 src 字面 marker check, 不实例化 ChatBypass (避 KeyRouter/VocalCord 依赖).
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# ==========================================================================
# BUG-A: except 加 spoken_so_far 守卫
# ==========================================================================

class TestBeta512BugA_SpokenSoFarGuard(unittest.TestCase):
    """除非 cloud stream 啥也没流回, 否则不追加道歉."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_chat_bypass.py'))

    def test_marker_comment_present(self):
        self.assertIn('β.5.12', self.src, 'β.5.12 marker 必须在 jarvis_chat_bypass.py')
        self.assertIn('BUG-A', self.src, 'BUG-A 标记必须存在')

    def test_guard_uses_spoken_threshold(self):
        """守卫用 _spoken_threshold 变量 (12 字符) — 不能写魔法数字."""
        self.assertIn('_spoken_threshold = 12', self.src,
            'spoken 阈值必须显式 12 字符, 便于后续调')

    def test_guard_skips_fallback_when_spoken(self):
        """已说 >= 阈值 → return True + 不调 _speak_fallback/_try_local_fallback."""
        # 关键: 守卫块内 return True 之前不能有 _speak_fallback 或 _try_local_fallback
        # 找到 BUG-A 守卫开始到 return True 的 block
        marker = '[β.5.12/BUG-A]'
        idx = self.src.find(marker)
        self.assertGreater(idx, 0, 'BUG-A bg_log marker 必须存在')
        # 从 BUG-A marker 找下一行 return True
        block_end = self.src.find('return True, _spoken_net', idx)
        self.assertGreater(block_end, idx,
            'BUG-A 守卫块必须 return True, _spoken_net')
        block = self.src[idx:block_end]
        self.assertNotIn('_speak_fallback()', block,
            '守卫块内不能调 _speak_fallback (那是无脑道歉)')
        self.assertNotIn('_try_local_fallback', block,
            '守卫块内不能调 _try_local_fallback (cloud 已说够就不该 Ollama)')

    def test_guard_emits_diagnostic_log(self):
        """守卫触发时必须 bg_log 让 Sir 能 grep."""
        self.assertIn('skip 道歉', self.src,
            'BUG-A 守卫触发时必须 bg_log 含 "skip 道歉" marker')

    def test_guard_strips_structural_tags(self):
        """net 长度计算前必须剥 ---ZH--- / <tag> / [WAKE_ONLY] 等结构化标签."""
        self.assertIn('_strip_structural_tag_blocks(_spoken_net)', self.src,
            '净化必须用 _strip_structural_tag_blocks 剥 PROMISE/ACTIVATE_PLAN 等')
        # 验证 ---ZH--- / <[^>]+> / [WAKE_ONLY] 等都被剥
        # marker 找位
        idx = self.src.find('_spoken_threshold = 12')
        self.assertGreater(idx, 0)
        block = self.src[max(0, idx-800):idx]
        self.assertIn("---ZH---", block, "守卫块内必须剥 ---ZH---")
        self.assertIn("<[^>]+>", block, "守卫块内必须剥 <...> 行内 tag")


# ==========================================================================
# BUG-B: chunk inter-arrival timeout (httpx.Timeout)
# ==========================================================================

class TestBeta512BugB_ChunkTimeout(unittest.TestCase):
    """_create_stream 用 httpx.Timeout 替换 float timeout."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_chat_bypass.py'))

    def test_marker_comment_present(self):
        self.assertIn('BUG-B', self.src, 'BUG-B 标记必须存在')

    def test_httpx_import(self):
        """_create_stream 内必须 import httpx (本地 import 即可)."""
        # 找 _create_stream 定义后 ~30 行内有 import httpx
        idx = self.src.find('def _create_stream(')
        self.assertGreater(idx, 0, '_create_stream 必须存在')
        # 找下一 def 边界
        next_def = self.src.find('\n    def ', idx + 10)
        block = self.src[idx:next_def if next_def > 0 else idx + 3000]
        self.assertIn('import httpx', block,
            '_create_stream 内必须 import httpx (做 Timeout 对象)')

    def test_uses_httpx_timeout_object(self):
        """client = OpenAI(timeout=httpx.Timeout(...)) 而非 float."""
        idx = self.src.find('def _create_stream(')
        next_def = self.src.find('\n    def ', idx + 10)
        block = self.src[idx:next_def if next_def > 0 else idx + 3000]
        # 检测使用了 Timeout(...) 形式
        self.assertIn('.Timeout(', block,
            'client timeout 必须用 httpx.Timeout(...) 对象, 非 float')
        # read=12.0 是 chunk inter-arrival 关键
        self.assertIn('read=12.0', block,
            'httpx.Timeout 必须 read=12.0 (chunk inter-arrival 12s)')

    def test_no_more_legacy_float_timeout(self):
        """老 timeout=60.0 line 必须不再出现在 _create_stream 内."""
        idx = self.src.find('def _create_stream(')
        next_def = self.src.find('\n    def ', idx + 10)
        block = self.src[idx:next_def if next_def > 0 else idx + 3000]
        # _create_stream 不能有 timeout=60.0 (旧值)
        self.assertNotIn('timeout=60.0', block,
            '_create_stream 内老 float timeout=60.0 必须移除')


# ==========================================================================
# BUG-C: Ollama timeout bump
# ==========================================================================

class TestBeta512BugC_OllamaTimeout(unittest.TestCase):
    """_try_local_fallback 用 timeout=8.0."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_chat_bypass.py'))

    def test_marker_comment_present(self):
        self.assertIn('BUG-C', self.src, 'BUG-C 标记必须存在')

    def test_ollama_timeout_bumped(self):
        """fallback.chat(timeout=8.0) 替换 5.0."""
        idx = self.src.find('def _try_local_fallback(')
        self.assertGreater(idx, 0, '_try_local_fallback 必须存在')
        next_def = self.src.find('\n    def ', idx + 10)
        block = self.src[idx:next_def if next_def > 0 else idx + 1500]
        self.assertIn('timeout=8.0', block,
            'Ollama chat timeout 必须 8s (GPU 争抢余量)')
        self.assertNotIn('timeout=5.0', block,
            '老 5s timeout 必须替换')

    def test_diagnostic_log_mentions_gpu(self):
        """空 reply 时 print 必须提 GPU 争抢可能性, Sir 能 grep."""
        self.assertIn('GPU 被 CosyVoice 占', self.src,
            'Ollama 空内容时 print 必须提示 GPU 资源争抢假设')


# ==========================================================================
# 综合: 不破坏老 fallback 链路 (regression guard)
# ==========================================================================

class TestBeta512NoRegression(unittest.TestCase):
    """β.5.12 三 fix 不能破坏 _speak_fallback / _try_local_fallback 老接口."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_chat_bypass.py'))

    def test_speak_fallback_still_exists(self):
        self.assertIn('def _speak_fallback(self):', self.src,
            '_speak_fallback 老接口必须保留 (cloud stream 啥也没流时仍走它)')

    def test_try_local_fallback_still_exists(self):
        self.assertIn('def _try_local_fallback(', self.src,
            '_try_local_fallback 老接口必须保留 (cloud err 但啥也没说时仍走它)')

    def test_pick_fallback_response_still_exists(self):
        self.assertIn('def _pick_fallback_response(self):', self.src,
            '_pick_fallback_response (罐头池) 必须保留')


if __name__ == '__main__':
    unittest.main()
