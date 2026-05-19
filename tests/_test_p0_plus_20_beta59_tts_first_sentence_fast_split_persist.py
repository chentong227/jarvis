# -*- coding: utf-8 -*-
"""
[P0+20-β.5.9 / 2026-05-19] BUG-3 fix: TTS 卡顿 — 首句激进切 + Audio Trace 诊断

Sir 真机实测主诉: "字幕都打完了好久才说话".
Root cause 分析 (jarvis_20260519_141609.log turn 14:21:34):
  - TTFT 3.1s / stream 3.5s / full 7.2s — gap 3.7s 在 worker prep + TTS render
  - 短回复 ("Yes, Sir." 9 字符) splitter hard>=20 永远不切 → 等 stream end 才 flush
  - 长回复首句 ("A fortuitous outcome, Sir." 26 字符) 在 i=20 切, 仍偏晚
  - render_only 单 thread 串行, 长回复 4 句累积 ~6s

Fix (3 改动, 不动 render 并行):
  A. `_find_sentence_split_idx` 加 `is_first_sentence` 参数, 首句 hard>=8/soft>=4
  B. 4 处 splitter 调用 (主 stream_chat / cloud followup / local fallback / nudge)
     传 `is_first_sentence=not _first_sent_done`, 切完后置 True
  C. `_put_audio` / `_render_worker` / `_play_worker` 加 `[Audio Trace] seq=N` log
     4 节点 (enq / render_start / render_done / play_start) 让 Sir 下次实测精确定位

测试覆盖:
  A. _find_sentence_split_idx 首句 vs 后续句阈值差异
  B. 4 处调用点都传 is_first_sentence
  C. Audio Trace log marker 字面存在 (enq / render_start / render_done / play_start)
  D. ChatBypass 实例化时 _audio_trace_seq / _audio_trace_lock 存在
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
# C: Audio Trace timing log marker
# ==========================================================================

class TestBeta59AudioTraceLog(unittest.TestCase):
    """4 个节点 Audio Trace log 字面 marker."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_chat_bypass.py'))

    def test_log_marker_enq(self):
        self.assertIn('[Audio Trace] enq seq=', self.src,
            'Audio Trace enq log marker 必须存在 (_put_audio 节点)')

    def test_log_marker_render_start(self):
        self.assertIn('[Audio Trace] render_start seq=', self.src,
            'Audio Trace render_start log marker 必须存在 (_render_worker 进入 render 前)')

    def test_log_marker_render_done(self):
        self.assertIn('[Audio Trace] render_done seq=', self.src,
            'Audio Trace render_done log marker 必须存在 (vocal.render_only 返回后)')

    def test_log_marker_play_start(self):
        self.assertIn('[Audio Trace] play_start seq=', self.src,
            'Audio Trace play_start log marker 必须存在 (_play_worker 进入 play_only 前)')

    def test_log_includes_queue_wait(self):
        self.assertIn('queue_wait=', self.src,
            'Audio Trace render_start 必须 log queue_wait (audio_queue 等候时间)')

    def test_log_includes_e2e(self):
        self.assertIn('e2e=', self.src,
            'Audio Trace play_start 必须 log e2e (enq → play_start 端到端延迟)')


# ==========================================================================
# D: ChatBypass instance has _audio_trace_seq / _audio_trace_lock
# ==========================================================================

class TestBeta59ChatBypassInstanceAttrs(unittest.TestCase):
    """ChatBypass.__init__ 后必须有 trace counter + lock."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_chat_bypass.py'))

    def test_init_has_audio_trace_seq(self):
        self.assertIn('self._audio_trace_seq = 0', self.src,
            'ChatBypass.__init__ 必须初始化 _audio_trace_seq = 0')

    def test_init_has_audio_trace_lock(self):
        self.assertIn('self._audio_trace_lock = threading.Lock()', self.src,
            'ChatBypass.__init__ 必须初始化 _audio_trace_lock = threading.Lock()')


if __name__ == '__main__':
    unittest.main()
