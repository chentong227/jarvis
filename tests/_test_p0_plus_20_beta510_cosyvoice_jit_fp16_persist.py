# -*- coding: utf-8 -*-
"""
[P0+20-β.5.10 / 2026-05-19] BUG-3 root cause fix: CosyVoice JIT + fp16 启用

β.5.9 [Audio Trace] 实测发现: 19 字符短句 render 6.67s, 不是 splitter / queue 问题.
根因: `jarvis_vocal_cord.py:54` 加载 CosyVoice 时未传 load_jit / fp16 加速参数,
退到 fp32 + 无 JIT 最慢配置. 4070 Ti SUPER 应 ~1-1.5s, 实际 6.67s.

模型目录已备齐 fp16 + JIT 文件:
  - llm.llm.fp16.zip
  - flow.encoder.fp16.zip
  - llm.text_encoder.fp16.zip

修法: 改一行 `CosyVoice('iic/CosyVoice-300M', load_jit=True, fp16=True)`.
预期: render 6.67s → ~2-3s (3x speedup).

测试覆盖:
  A. jarvis_vocal_cord.py:VocalCord.__init__ 调 CosyVoice 时传 load_jit=True
  B. fp16=True 也传
  C. β.5.10 marker 注释存在
  D. JIT 加载提示 print 存在 (Sir 启动时能看到 ⚡ [声带器官] log)
  E. 模型目录 (smoke check, 若不存在 skip) — fp16 .zip 文件齐全
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


class TestBeta510CosyVoiceJitFp16Enable(unittest.TestCase):
    """β.5.10 启用 JIT + fp16 加速."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_vocal_cord.py'))

    def test_load_jit_true(self):
        """CosyVoice() 调用必须传 load_jit=True."""
        self.assertIn("CosyVoice('iic/CosyVoice-300M', load_jit=True, fp16=True)", self.src,
            "VocalCord.__init__ 必须以 load_jit=True + fp16=True 加载 CosyVoice (β.5.10)")

    def test_fp16_true_present(self):
        """fp16=True 必须在 CosyVoice 加载行内."""
        # 找 CosyVoice( 调用行
        for line in self.src.split('\n'):
            if 'CosyVoice(' in line and 'iic/CosyVoice-300M' in line:
                self.assertIn('fp16=True', line,
                    f"加载行未含 fp16=True: {line.strip()}")
                self.assertIn('load_jit=True', line,
                    f"加载行未含 load_jit=True: {line.strip()}")
                break
        else:
            self.fail("找不到 CosyVoice('iic/CosyVoice-300M', ...) 加载行")

    def test_marker_comment_present(self):
        """β.5.10 marker 注释必须存在 (便于 git blame 追溯)."""
        self.assertIn('β.5.10', self.src,
            'β.5.10 marker 必须出现在 jarvis_vocal_cord.py 注释')

    def test_no_old_unaccelerated_load(self):
        """旧 fp32 无加速调用 `CosyVoice('iic/CosyVoice-300M')` 单独参数不能再出现.

        (允许新加速版的 `CosyVoice('iic/CosyVoice-300M', load_jit=True, ...)` 通过.)
        """
        import re
        # 匹配 CosyVoice('iic/CosyVoice-300M') 这种只有 model_dir 一个参数的形式
        bad_pattern = re.compile(r"CosyVoice\(\s*['\"]iic/CosyVoice-300M['\"]\s*\)")
        matches = bad_pattern.findall(self.src)
        self.assertEqual(matches, [],
            f"jarvis_vocal_cord.py 仍存在 fp32 无加速 `CosyVoice('iic/CosyVoice-300M')` 调用: {matches}")

    def test_jit_loading_print_marker(self):
        """启动时必须 print '启用 JIT + fp16 加速' 让 Sir 看到激活态."""
        self.assertIn('JIT + fp16 加速', self.src,
            '启动 print 必须告知 Sir 已启用加速 (便于真机验收)')


class TestBeta510ModelFilesAvailable(unittest.TestCase):
    """smoke check: 模型目录里 fp16 JIT .zip 文件齐全 (若目录不存在则 skip)."""

    @classmethod
    def setUpClass(cls):
        # 模型 cache 路径 (Windows)
        userprofile = os.environ.get('USERPROFILE', '')
        cls.model_dir = os.path.join(
            userprofile, '.cache', 'modelscope', 'hub', 'iic', 'CosyVoice-300M'
        )

    def test_fp16_zip_files_present(self):
        """fp16 JIT .zip 文件必须齐全; 不齐全则 load_jit=True 会 fallback fp32."""
        if not os.path.isdir(self.model_dir):
            self.skipTest(f'CosyVoice 模型目录不存在: {self.model_dir}')

        required = [
            'llm.llm.fp16.zip',
            'flow.encoder.fp16.zip',
            'llm.text_encoder.fp16.zip',
        ]
        missing = [f for f in required if not os.path.isfile(os.path.join(self.model_dir, f))]
        self.assertEqual(missing, [],
            f"以下 fp16 JIT .zip 缺失, 加载会 fallback: {missing}\n"
            f"目录: {self.model_dir}")


if __name__ == '__main__':
    unittest.main()
