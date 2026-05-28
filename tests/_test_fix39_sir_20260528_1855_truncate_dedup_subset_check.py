# -*- coding: utf-8 -*-
"""[Sir 2026-05-28 18:55 真测追根 BUG 治本] truncate dedup 漏一刀 → TTS 重念.

源 BUG (Sir 真测 turn 20260528_185529_795e):
  Sir 输入: "我今天还喝了一瓶的水, 就是550毫升"
  Jarvis EN reply: "That brings you to approximately 7.75 cups for the day, Sir" (59ch)
  Jarvis ZH reply: "" (空 → 触发 [Bilingual/Truncated] worker)
  worker LLM 续写返 <EN>"7.75 cups for the day, Sir."</EN> (27ch) — 重复了已念部分
  fix78 dedup 3 check 都漏:
    - check 1 (substring): cont 末 "." 不在 snip → False
    - check 2 (snip endswith cont head 20ch): snip 末 "ups for the day, Sir" != cont 头 "7.75 cups for the da" → False
    - check 3 (jaccard ≥ 0.6): inter=7 ({7,75,cups,for,the,day,sir}) union=12 → 0.583 < 0.6 → False
  → put_audio 又念 "7.75 cups for the day, Sir" → Sir 听到 2 遍.

治本 (准则 8 优雅高效, 不糖衣调阈值 0.6 → 0.55):
  jarvis_chat_bypass.py truncate worker 加 check 4 subset rule:
    cont_tokens ⊆ snip_tokens 且 len(cont_tokens) ≥ 3 → skip put_audio.
  evidence 维度: cont 没引入任何新词 = 它 100% 是 snip 已念部分 = 重复.
  合法 cont 必含新词 (e.g. "Sir, anything else?" = {sir,anything,else} ⊄ snip)
  不会被误伤.
  系统级常量 (准则 6 边界, 不进 vocab JSON).

防回退: 6 testcase 覆盖 (Sir 真 case + 4 regression + 1 source marker).
"""
from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(name: str) -> str:
    with open(os.path.join(ROOT, name), 'r', encoding='utf-8') as f:
        return f.read()


# ==========================================================================
# Helper — 内联复现 chat_bypass dedup 4-check 链 (本 fix 修后版本)
# ==========================================================================

def _dedup_skip(en_cont: str, en_snippet: str) -> tuple:
    """复现 chat_bypass.py 5133-5184 dedup logic (4 check 链).

    Returns:
      (skip_cont: bool, skip_reason: str)
    """
    skip_cont = False
    skip_reason = ''
    if not en_cont or len(en_cont) < 2:
        return False, ''
    cont_lower = en_cont.lower().strip()
    snip_lower = (en_snippet or '').lower().strip()
    if not (cont_lower and snip_lower):
        return False, ''
    # check 1: cont 是 snip 的 substring (完全重复)
    if cont_lower in snip_lower:
        return True, 'substring_of_snip'
    # check 2: snip 末尾 == cont 开头 20ch (大段 overlap)
    if (len(cont_lower) >= 20 and snip_lower.endswith(cont_lower[:20])):
        return True, 'snip_endswith_cont_head'
    # check 3 / check 4: jaccard + subset
    ctoks = set(re.findall(r'\w+', cont_lower))
    stoks = set(re.findall(r'\w+', snip_lower))
    if not (ctoks and stoks):
        return False, ''
    inter = len(ctoks & stoks)
    union = len(ctoks | stoks)
    jacc = inter / union if union else 0.0
    if jacc >= 0.6:
        return True, f'jaccard={jacc:.2f}>=0.6'
    # check 4 (本 fix 新加): cont tokens ⊆ snip tokens 且 ≥ 3 tokens
    if ctoks <= stoks and len(ctoks) >= 3:
        return True, (f'cont_tokens_subset_of_snip'
                       f'(jacc={jacc:.2f},n_cont={len(ctoks)})')
    return False, ''


# ==========================================================================
# 主测试 — Sir 真痛点 + regression + source marker
# ==========================================================================

class TestFix39TruncateDedupSubsetCheck(unittest.TestCase):

    def test_sir_real_case_185529_795e_subset_skip(self):
        """Sir 真痛 28 日 18:55 case — jacc=0.583<0.6 但 cont⊂snip → check 4 skip."""
        snip = "That brings you to approximately 7.75 cups for the day, Sir"
        cont = "7.75 cups for the day, Sir."
        # 前提 sanity: jaccard 真的 < 0.6 (fix78 漏)
        ctoks = set(re.findall(r'\w+', cont.lower()))
        stoks = set(re.findall(r'\w+', snip.lower()))
        inter = len(ctoks & stoks)
        union = len(ctoks | stoks)
        jacc = inter / union
        self.assertLess(jacc, 0.6,
                         f'前提: jaccard={jacc:.3f} 应 < 0.6 (fix78 阈值漏)')
        # 前提 sanity: cont 真的 ⊂ snip (本 fix 救)
        self.assertTrue(ctoks <= stoks,
                         f'前提: cont_tokens ⊂ snip_tokens (cont={ctoks-stoks} extra)')
        self.assertGreaterEqual(len(ctoks), 3, '前提: cont ≥ 3 token')
        # 真测: 必须 skip
        skip, reason = _dedup_skip(cont, snip)
        self.assertTrue(skip,
                         f'Sir 真 case 必须 skip (reason={reason!r}, 否则 TTS 重念)')
        self.assertIn('subset_of_snip', reason,
                       f'命中 check 4 subset rule (got: {reason!r})')

    def test_legit_cont_with_new_word_not_skip(self):
        """合法 cont 含新词 ("anything", "else") → cont ⊄ snip → 不该 skip."""
        snip = "That brings you to approximately 7.75 cups for the day, Sir"
        cont = "Sir, anything else?"
        ctoks = set(re.findall(r'\w+', cont.lower()))
        stoks = set(re.findall(r'\w+', snip.lower()))
        self.assertFalse(ctoks <= stoks,
                          f'前提: cont 必有新词 (new={ctoks-stoks})')
        skip, reason = _dedup_skip(cont, snip)
        self.assertFalse(skip,
                          f'合法 cont 不该 skip (reason={reason!r})')

    def test_substring_check1_still_works(self):
        """check 1 regression — cont 整 in snip → 仍 skip (fix78 path)."""
        snip = "That brings you to approximately 7.75 cups for the day, Sir"
        cont = "7.75 cups for the day, Sir"  # 无末 ".", 是 snip 真子串
        self.assertIn(cont.lower(), snip.lower(), '前提: cont 真 substring of snip')
        skip, reason = _dedup_skip(cont, snip)
        self.assertTrue(skip, f'substring 必 skip (reason={reason!r})')
        self.assertEqual(reason, 'substring_of_snip',
                          f'应命中 check 1 (got: {reason!r})')

    def test_jaccard_high_check3_still_works(self):
        """check 3 regression — jacc ≥ 0.6 且 cont ⊄ snip → 仍 skip (fix78 path)."""
        # 构造 cont 含 snip 没有的词 (避免命中本 fix 的 check 4 subset),
        # 但 jaccard 仍 ≥ 0.6
        snip = "I updated log to 9 cups Sir."
        cont = "Updated log to 9 cups Sir today."  # "today" snip 没有
        ctoks = set(re.findall(r'\w+', cont.lower()))
        stoks = set(re.findall(r'\w+', snip.lower()))
        # 前提: cont 含新词 (不是 subset, 避免被 check 4 截获)
        self.assertFalse(ctoks <= stoks,
                          f'前提: cont 必含新词 ({ctoks-stoks})')
        inter = len(ctoks & stoks)
        union = len(ctoks | stoks)
        jacc = inter / union
        self.assertGreaterEqual(jacc, 0.6,
                                  f'前提: jaccard={jacc:.3f} 应 ≥ 0.6')
        skip, reason = _dedup_skip(cont, snip)
        self.assertTrue(skip, f'jacc≥0.6 必 skip (reason={reason!r})')
        self.assertIn('jaccard', reason,
                       f'应命中 check 3 (got: {reason!r})')

    def test_short_cont_subset_no_skip_guard(self):
        """check 4 guard — cont < 3 token 即使 ⊂ snip 也不 skip (太短不可靠)."""
        # cont 只 2 个 token, 都在 snip
        snip = "That brings you to approximately 7.75 cups for the day, Sir"
        cont = "the day Sir"  # 3 token? "the","day","sir" = 3
        # 改成真 2 token 场景
        cont = "day Sir"  # 2 token
        ctoks = set(re.findall(r'\w+', cont.lower()))
        stoks = set(re.findall(r'\w+', snip.lower()))
        self.assertEqual(len(ctoks), 2, f'前提: cont 只 2 token (got: {ctoks})')
        self.assertTrue(ctoks <= stoks, '前提: 2 token 都 ⊂ snip')
        skip, reason = _dedup_skip(cont, snip)
        # 注意 check 1 (substring) 可能 match — "day sir" in "...day, sir"?
        # snip="...for the day, Sir", lower="...for the day, sir"
        # cont="day sir" lower="day sir" → "day sir" not in "day, sir" (有逗号)
        # → check 1 不命中
        # check 2 cont 长度 < 20 → 跳过
        # check 3 jacc = 2/13 ≈ 0.15 < 0.6 → 不命中
        # check 4 ctoks ⊆ stoks ✓ 但 len(ctoks)=2 < 3 → guard skip → 不命中
        self.assertFalse(skip,
                          f'短 cont (<3 token) 即使 subset 也不该 skip (reason={reason!r})')

    def test_source_has_check4_subset_marker(self):
        """source check — chat_bypass.py 含本 fix 新加的 marker."""
        src = _read('jarvis_chat_bypass.py')
        # marker 1: 注释 anchor
        self.assertIn('Sir 2026-05-28 18:55 fix39', src,
                       'source 应有 fix39 Sir 真测 anchor 注释')
        # marker 2: subset 逻辑 elif
        self.assertIn('_ctoks <= _stoks', src,
                       'source 应有 cont_tokens ⊆ snip_tokens elif (check 4)')
        self.assertIn('len(_ctoks) >= 3', src,
                       'source 应有 len(_ctoks) >= 3 guard (防短 cont)')
        # marker 3: skip_reason 字符串
        self.assertIn('cont_tokens_subset_of_snip', src,
                       'source 应有 skip_reason="cont_tokens_subset_of_snip" 标识')


if __name__ == '__main__':
    unittest.main()
