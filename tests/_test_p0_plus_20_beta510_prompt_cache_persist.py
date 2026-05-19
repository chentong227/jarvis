# -*- coding: utf-8 -*-
"""
[P0+20-β.5.10 / 2026-05-19 重做] BUG-3 真因修: CosyVoice prompt encoding cache

β.5.10 第一次尝试 (load_jit+fp16) 已 revert (commit 9211c51) — 不是真因.
通过 5.11 / 5.14 备份对比 + scripts/_bench_vocal_render.py benchmark 实证:
  - 5.11/5.14 时也是 fp32 无 jit, Sir 主观仍不卡 (≠ 现在 6.67s)
  - benchmark: 9 chars 6.2s / 88 chars 8.5s, 增量极小 → 固定开销
  - 检查 CosyVoice frontend.py:168 frontend_zero_shot 内部:
    * _extract_speech_feat (mel)  ← 5 秒 prompt_wav
    * _extract_speech_token (onnx)  ← 5 秒 prompt_wav
    * _extract_spk_embedding (campplus.onnx)  ← 5 秒 prompt_wav
  - 这 3 个 op 每次 inference 都重做 → 6s 固定 prompt encoding 开销

CosyVoice 提供 add_zero_shot_spk(prompt_text, prompt_wav, spk_id) 一次性 cache 到
spk2info dict, inference 时传 zero_shot_spk_id 跳过 encoding.

修法:
  __init__ 里调 add_zero_shot_spk() 缓存 prompt encoding 为 spk_id='jarvis_default'
  render_only 里 inference_zero_shot(zero_shot_spk_id=self._jarvis_spk_id)

实测 (scripts/_bench_vocal_render.py 运行结果):
  9 chars: 6.20s → 1.09s (5.7x)
  19 chars: 7.22s → 1.93s (3.7x)
  88 chars: 8.50s → 3.21s (2.6x)

测试覆盖:
  A. __init__ 调 add_zero_shot_spk
  B. render_only 调 inference_zero_shot 传 zero_shot_spk_id
  C. _jarvis_spk_id 字段存在
  D. fallback 路径 (cache 失败 → spk_id='' 走 legacy)
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


class TestBeta510PromptEncodingCache(unittest.TestCase):
    """β.5.10 prompt encoding cache 启用."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_vocal_cord.py'))

    def test_init_calls_add_zero_shot_spk(self):
        """__init__ 必须调 add_zero_shot_spk 缓存 prompt encoding."""
        self.assertIn('self.cosyvoice.add_zero_shot_spk(', self.src,
            'VocalCord.__init__ 必须调 add_zero_shot_spk 缓存 prompt encoding (β.5.10)')

    def test_jarvis_spk_id_field_present(self):
        """实例字段 _jarvis_spk_id 必须存在."""
        self.assertIn('self._jarvis_spk_id', self.src,
            '必须有 _jarvis_spk_id 字段保存 cache 后的 spk_id')

    def test_default_spk_id_value(self):
        """默认 _jarvis_spk_id = 'jarvis_default'."""
        self.assertIn("self._jarvis_spk_id = 'jarvis_default'", self.src,
            'cache spk_id 默认必须为 jarvis_default')

    def test_inference_passes_zero_shot_spk_id(self):
        """render_only 调 inference_zero_shot 时必须传 zero_shot_spk_id."""
        self.assertIn('zero_shot_spk_id=self._jarvis_spk_id', self.src,
            'inference_zero_shot 调用必须传 zero_shot_spk_id=self._jarvis_spk_id (β.5.10)')

    def test_fallback_on_cache_failure(self):
        """add_zero_shot_spk 失败时 _jarvis_spk_id 降级为 '' (走 legacy 路径)."""
        # 必须有 except 分支把 _jarvis_spk_id 设回空字符串
        self.assertIn("self._jarvis_spk_id = ''", self.src,
            'add_zero_shot_spk 失败时必须 fallback _jarvis_spk_id = "" (走 legacy 每次重算 prompt encoding)')

    def test_marker_comment_present(self):
        """β.5.10 marker 注释存在."""
        self.assertIn('β.5.10', self.src,
            'β.5.10 marker 必须出现在源码 (便于 git blame 追溯)')

    def test_no_old_inference_without_spk_id(self):
        """旧版 inference_zero_shot 不传 zero_shot_spk_id 的调用不能再有.

        允许新版 inference_zero_shot(... zero_shot_spk_id=...) 通过.
        """
        # 找所有 inference_zero_shot( 调用
        import re
        # 用更宽的多行匹配抓所有 inference_zero_shot 调用
        # 新版调用必须含 zero_shot_spk_id; 旧版不含
        pattern = re.compile(
            r'inference_zero_shot\([^)]*?\)',
            re.DOTALL
        )
        calls = pattern.findall(self.src)
        # 每个 call 都必须含 zero_shot_spk_id
        missing = [c for c in calls if 'zero_shot_spk_id' not in c]
        self.assertEqual(missing, [],
            f"以下 inference_zero_shot 调用未传 zero_shot_spk_id (会走慢路径每次重算 6s):\n"
            f"{missing}")


class TestBeta510LoadJitFp16Reverted(unittest.TestCase):
    """β.5.10 第一次尝试 (load_jit+fp16) 已 revert, 不能再有."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_vocal_cord.py'))

    def test_no_load_jit_param(self):
        """CosyVoice() 加载行不能含 load_jit=True (β.5.10 v1 已 revert, 非真因)."""
        self.assertNotIn('load_jit=True', self.src,
            'load_jit=True 已 revert (β.5.10 v1 走错方向, 真因是 prompt encoding cache)')

    def test_no_fp16_param(self):
        """CosyVoice() 加载行不能含 fp16=True (同上)."""
        self.assertNotIn('fp16=True', self.src,
            'fp16=True 已 revert (β.5.10 v1 走错方向)')


if __name__ == '__main__':
    unittest.main()
