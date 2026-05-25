# -*- coding: utf-8 -*-
"""[Sir 2026-05-25 21:38 真测追根] Truncate 续写 EN cont 也走 TTS.

Sir 真测 (jarvis_20260525_213655.log Turn 1):
  ASR: '好的，我现在又喝了一杯，我大概喝了1100毫升加三杯，就是嗯嗯嗯2000毫升'
  主脑 reply EN: 'Noted, Sir. I have updated your total intake to' ← 卡在 'to' 没下文
  - ZH zh_len=0ch (完全没出)
  - 触发: SoulEvaluator override / Bilingual Truncated / Truncate Cont 三 layer
  - ZH 补字幕 28ch ✅
  - 但 EN reply 半截 TTS 已说完 → Sir 听到 'to' 卡死

真根因 (网络层):
  google_1 SSL EOF 中途 → KeyRouter 切 key, 但当前 stream 已终止. 上轮治本只
  补 ZH 字幕, EN 没续 TTS.

2 路追加治本:
  - e1: continuation worker EN cont 也走 _put_audio → TTS 续播
  - e2: continuation prompt 加 INTEGRITY RED LINE (准则 5): 禁编数字/事实,
        用模糊收尾 ('reflect your recent input' / 'the new value')
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(name: str) -> str:
    with open(os.path.join(ROOT, name), 'r', encoding='utf-8') as f:
        return f.read()


# ==========================================================================
# e1: EN cont 进 TTS 队列
# ==========================================================================
class TestE1ENContPutAudio(unittest.TestCase):

    def test_continuation_worker_puts_en_cont_to_audio(self):
        src = _read('jarvis_chat_bypass.py')
        # 在 truncate continuation worker 内部含 self._put_audio(_en_cont)
        idx = src.find('_truncate_continuation_worker')
        self.assertGreater(idx, 0)
        block = src[idx:idx + 10000]
        self.assertIn('self._put_audio(_en_cont', block,
                       'EN cont 必须进 _put_audio 走 TTS')
        # 必须 anchor Sir 21:38 真测
        self.assertIn('Sir 2026-05-25 21:38', block,
                       '必须 anchor Sir 21:38 真测痛点')

    def test_en_cont_length_check_protects(self):
        src = _read('jarvis_chat_bypass.py')
        # if _en_cont and len(_en_cont) >= 2 防空 cont 进 TTS
        idx = src.find('_truncate_continuation_worker')
        block = src[idx:idx + 10000]
        self.assertIn('len(_en_cont) >= 2', block,
                       'EN cont 长度 >= 2 才进 TTS (防空字)')


# ==========================================================================
# e2: continuation prompt INTEGRITY RED LINE
# ==========================================================================
class TestE2ContPromptIntegrityRedLine(unittest.TestCase):

    def test_prompt_has_red_line(self):
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('INTEGRITY RED LINE', src,
                       'cont prompt 必须有 INTEGRITY RED LINE')
        self.assertIn('准则 5', src)
        self.assertIn('DO NOT invent facts/numbers/data', src)

    def test_prompt_offers_vague_close_example(self):
        src = _read('jarvis_chat_bypass.py')
        # vague close 例子 (防 LLM 编数字)
        self.assertIn('reflect your recent input', src,
                       '必须给 vague close 示例')
        self.assertIn('NEVER fabricate specific numbers/units', src,
                       '强制禁编数字/单位')


if __name__ == '__main__':
    unittest.main()
