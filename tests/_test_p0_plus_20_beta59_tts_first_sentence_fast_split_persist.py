# -*- coding: utf-8 -*-
"""
[P0+20-β.5.9 / 2026-05-19] BUG-3 fix: TTS 卡顿 — 首句激进切

Sir 真机实测主诉: "字幕都打完了好久才说话".
Root cause 分析 (jarvis_20260519_141609.log turn 14:21:34):
  - TTFT 3.1s / stream 3.5s / full 7.2s — gap 3.7s 在 worker prep + TTS render
  - 短回复 ("Yes, Sir." 9 字符) splitter hard>=20 永远不切 → 等 stream end 才 flush
  - 长回复首句 ("A fortuitous outcome, Sir." 26 字符) 在 i=20 切, 仍偏晚
  - render_only 单 thread 串行, 长回复 4 句累积 ~6s

Fix (2 改动, 不动 render 并行):
  A. `_find_sentence_split_idx` 加 `is_first_sentence` 参数, 首句 hard>=8/soft>=4
  B. 4 处 splitter 调用 (主 stream_chat / cloud followup / local fallback / nudge)
     传 `is_first_sentence=not _first_sent_done`, 切完后置 True

Note: 原 C/D 部分 Audio Trace timing log 已于 2026-05-19 21:33 退役 (Sir 实测
确认 β.5.10 prompt cache render 6.67s→1.9-2.4s 诊断使命完成).

测试覆盖:
  A. _find_sentence_split_idx 首句 vs 后续句阈值差异
  B. 4 处调用点都传 is_first_sentence
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
# A: _find_sentence_split_idx 首句激进切阈值
# ==========================================================================

class TestBeta59FindSentenceSplitIdxFirstSentence(unittest.TestCase):
    """首句阈值降到 hard>=8 / soft>=4, 后续仍 hard>=20 / soft>=15."""

    def test_signature_has_is_first_sentence(self):
        """函数签名必须有 is_first_sentence 参数."""
        from jarvis_chat_bypass import _find_sentence_split_idx
        import inspect
        sig = inspect.signature(_find_sentence_split_idx)
        self.assertIn('is_first_sentence', sig.parameters,
            '_find_sentence_split_idx 必须新增 is_first_sentence 参数 (β.5.9)')
        # 默认 False (保留旧行为)
        self.assertEqual(sig.parameters['is_first_sentence'].default, False,
            'is_first_sentence 默认必须 False (向后兼容)')

    def test_first_sentence_hard_split_at_8(self):
        """首句 hard symbol 在 i>=8 即切; 后续句要 i>=20."""
        from jarvis_chat_bypass import _find_sentence_split_idx
        # 'Yes, Sir.' chars: Y(0) e(1) s(2) ,(3) ' '(4) S(5) i(6) r(7) .(8)
        # ',' 在 i=3 < soft_min(4), 不切
        # ' Sir' lookahead 即便满足也跳过
        # '.' 在 i=8 >= hard_min(8) → 切
        idx_first = _find_sentence_split_idx('Yes, Sir.', soft_split=True, is_first_sentence=True)
        self.assertEqual(idx_first, 8,
            f"首句 'Yes, Sir.' 应在 '.' (i=8) 切 (hard_min=8, ',' i=3<4 不切), 实际 {idx_first}")

        # is_first_sentence=False → 不切 (',' i=3 < 15, '.' i=8 < 20)
        idx_after = _find_sentence_split_idx('Yes, Sir.', soft_split=True, is_first_sentence=False)
        self.assertEqual(idx_after, -1,
            f"后续句 'Yes, Sir.' 应不切 (soft_min=15, hard_min=20), 实际 {idx_after}")

    def test_first_sentence_soft_split_at_4(self):
        """首句 soft symbol ',' 在 i>=4 + buf_len>i+5 (后跟 lookahead 至少 5 char) 即切."""
        from jarvis_chat_bypass import _find_sentence_split_idx
        # 长 buffer, ',' 在 i=12, 后面有足够 lookahead 不含 Sir/Jar
        # 'A fortuitous, ok then bye.' — ',' i=12, lookahead ' ok t' → 切
        idx_first = _find_sentence_split_idx('A fortuitous, ok then bye.', soft_split=True, is_first_sentence=True)
        self.assertEqual(idx_first, 12,
            f"首句 'A fortuitous, ok then bye.' 应在 ',' (i=12) 切, 实际 {idx_first}")

    def test_first_sentence_soft_split_min_4_explicit(self):
        """soft_min=4: 'Hi, mate!' — ',' i=2 < 4 → 不切, '!' i=8 >= 8 (hard_min) → 切."""
        from jarvis_chat_bypass import _find_sentence_split_idx
        # 'Hi, mate!' — ',' 在 i=2 (H=0 i=1 ,=2), lookahead ' mate' 满足
        # 但 i=2 < soft_min(4) → 不切
        # '!' 在 i=8, hard_min=8 → 切
        idx = _find_sentence_split_idx('Hi, mate!', soft_split=True, is_first_sentence=True)
        self.assertEqual(idx, 8,
            f"首句 'Hi, mate!' soft_min=4 但 ',' i=2<4, 应等到 '!' (i=8) 切, 实际 {idx}")

    def test_first_sentence_skip_sir_lookahead(self):
        """首句即便 i>=4, ', Sir' 仍要跳过 (保留 ' Sir' 在同一句)."""
        from jarvis_chat_bypass import _find_sentence_split_idx
        # 'Done, Sir, indeed.' — 第一个 ',' i=4 lookahead ' Sir,' → 跳过
        # 第二个 ',' i=9 lookahead ' inde' → 切
        idx = _find_sentence_split_idx('Done, Sir, indeed.', soft_split=True, is_first_sentence=True)
        self.assertEqual(idx, 9,
            f"首句 'Done, Sir, indeed.' 第一 ',' 跳过 'Sir' lookahead, 应在第二 ',' (i=9) 切, 实际 {idx}")

    def test_after_first_sentence_threshold_preserved(self):
        """后续句必须保留 hard>=20 / soft>=15 (保 prosody)."""
        from jarvis_chat_bypass import _find_sentence_split_idx
        # 长度 14: 'Short, normal.' — soft 在 i=5, hard 在 i=13
        # is_first_sentence=False → 都 < 阈值, -1
        idx = _find_sentence_split_idx('Short, normal.', soft_split=True, is_first_sentence=False)
        self.assertEqual(idx, -1,
            f"后续句 'Short, normal.' 应不切 (soft<15 + hard<20), 实际 {idx}")

    def test_long_sentence_still_splits(self):
        """长句不管 first 还是 after, 都该正常切."""
        from jarvis_chat_bypass import _find_sentence_split_idx
        long_buf = 'In a competitive field, excellence is relative.'
        idx_first = _find_sentence_split_idx(long_buf, soft_split=True, is_first_sentence=True)
        idx_after = _find_sentence_split_idx(long_buf, soft_split=True, is_first_sentence=False)
        # ',' 在 i=23, lookahead ' exce' → 切
        # is_first 切在 i=23 (soft_min=4), is_after 切在 i=23 (soft_min=15)
        self.assertEqual(idx_first, idx_after,
            f"长句首句和后续句应切在同一位置, 首={idx_first}, 后={idx_after}")
        self.assertGreater(idx_first, 15,
            f"长句切位 ≥15, 实际 {idx_first}")


# ==========================================================================
# B: 4 处 splitter 调用点都传 is_first_sentence=not _first_sent_done
# ==========================================================================

class TestBeta59SplitterCallSitesPassIsFirst(unittest.TestCase):
    """4 处 stream loop 内 splitter 调用都用 is_first_sentence=not _first_sent_done."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_chat_bypass.py'))

    def test_first_sent_done_init_count(self):
        """`_first_sent_done = False` 必须出现 4 次 (4 个 stream loop scope)."""
        count = self.src.count('_first_sent_done = False')
        self.assertGreaterEqual(count, 4,
            f"`_first_sent_done = False` 应 ≥ 4 次 (4 个 stream loop), 实际 {count}")

    def test_splitter_call_passes_is_first(self):
        """4 处 _find_sentence_split_idx 调用都该传 is_first_sentence."""
        # 找所有 _find_sentence_split_idx(...) 调用 (除 def 之外)
        import re
        # 排除 def 行
        lines = [l for l in self.src.split('\n') if '_find_sentence_split_idx(' in l and 'def _find_sentence_split_idx' not in l]
        # 至少 4 处
        self.assertGreaterEqual(len(lines), 4,
            f"_find_sentence_split_idx 调用应 ≥ 4 处, 实际 {len(lines)}")
        # 都该含 is_first_sentence
        missing = [l.strip() for l in lines if 'is_first_sentence' not in l]
        self.assertEqual(missing, [],
            f"以下 splitter 调用未传 is_first_sentence:\n" + '\n'.join(missing))

    def test_first_sent_done_set_after_put_audio(self):
        """切完一句 _put_audio 后必须置 _first_sent_done = True."""
        count = self.src.count('_first_sent_done = True')
        self.assertGreaterEqual(count, 4,
            f"`_first_sent_done = True` 应 ≥ 4 次 (每 stream loop 切第一句后), 实际 {count}")


# ==========================================================================
# C/D: Audio Trace timing log + ChatBypass trace attrs (均于 2026-05-19 21:33 退役)
# ==========================================================================

class TestBeta59AudioTraceRetired(unittest.TestCase):
    """送别测: Audio Trace bg_log 已除, 反向锁 — 不该再出现在代码.

    退役原因: β.5.10 prompt encoding cache 落地后 Sir 实测证实 render 从 6.67s
    降到 1.9-2.4s (【Audio Trace】诊断使命完成). Sir 2026-05-19 21:33 明确
    "这个部分可以去掉了" — 4 处 bg_log + metadata 透传 + _audio_trace_seq
    + _audio_trace_lock 全部移除, 净化 noise log.

    下次再需诊断: git show e216a0a — 【jarvis_chat_bypass.py】 可恢复.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_chat_bypass.py'))

    def test_audio_trace_bg_log_removed(self):
        """[Audio Trace] bg_log 字面 marker 不该出现在运行时 emit 处.

        注: bg_log f-string 内容 【Audio Trace] enq seq=】等字面应全别.
        允许出现在注释/docstring 里说明"已退役".
        """
        # bg_log emit 的 4 个 marker 必须不出现
        forbidden = ['enq seq=', 'render_start seq=', 'render_done seq=', 'play_start seq=']
        for marker in forbidden:
            self.assertNotIn(f'[Audio Trace] {marker}', self.src,
                f'Audio Trace bg_log marker "{marker}" 已退役, 不该再在代码中出现')

    def test_audio_trace_attrs_removed(self):
        """_audio_trace_seq / _audio_trace_lock 实例字段 已除."""
        self.assertNotIn('self._audio_trace_seq = 0', self.src,
            '_audio_trace_seq 实例字段已退役')
        self.assertNotIn('self._audio_trace_lock = threading.Lock()', self.src,
            '_audio_trace_lock 实例字段已退役')


if __name__ == '__main__':
    unittest.main()
