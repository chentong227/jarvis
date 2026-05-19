# -*- coding: utf-8 -*-
"""
[P0+20-β.5.0-B / 2026-05-19] Reaction Space — 准则 6 第 2 维 (行为弱耦合) 启动

Sir 拍板第一性原理 (准则 6 升级版):
  数据强耦合 (β.5.0-A ✅) + 行为弱耦合 (本) + 决策集中主脑

β.5.0-B 改造:
  1. stream_nudge prompt 加 [REACTION SPACE] 块, 告诉主脑可选 [SILENCE]
  2. stream 早期 token 检测 [SILENCE] / [silence] → 立刻 break
  3. 检测到 silence → 不投 TTS / 不字幕 + publish 'self_critique' 到 SWM + return None
  4. 主脑下次 prompt 看 SWM 含 "Brain chose [SILENCE] for nudge_type=X" → 知道刚选过沉默

测试覆盖:
  A. nudge directive 含 [REACTION SPACE] block
  B. directive 明确列 [SILENCE] 触发条件 (重复 / 拒绝 / 短回应 / evidence 冲突)
  C. stream 早期 token 检测路径 ([SILENCE] in head 32 chars → break)
  D. silence 后处理: 跳过 TTS, return None, publish self_critique
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================================
# A: directive 含 [REACTION SPACE] block
# ==========================================================================

class TestP0Plus20Beta50BDirectiveReactionSpace(unittest.TestCase):
    """stream_nudge prompt 必须含 [REACTION SPACE] block."""

    def _get_src(self):
        path = os.path.join(ROOT, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_directive_has_reaction_space_header(self):
        src = self._get_src()
        self.assertIn('[REACTION SPACE', src,
            'stream_nudge directive 必须含 [REACTION SPACE 块 (β.5.0-B)')

    def test_directive_documents_silence_choice(self):
        src = self._get_src()
        self.assertIn('[SILENCE]', src,
            'directive 必须告诉主脑 [SILENCE] 选项 (β.5.0-B)')

    def test_directive_lists_silence_triggers(self):
        """directive 必须列具体 silence 触发条件 (evidence-only 不教句式)."""
        src = self._get_src()
        # 至少 3 个 silence 触发 evidence anchor
        anchors = [
            'gate_advice',           # SWM gate 建议拦
            'last 60s',              # 最近 60s 已建议拦
            "Sir's recent utterance",  # Sir 短回应
            'evidence',              # evidence 冲突
        ]
        for anchor in anchors:
            self.assertIn(anchor, src,
                f'[REACTION SPACE] 必须含触发 anchor: {anchor}')


# ==========================================================================
# C: stream 早期 token 检测 + return None 路径
# ==========================================================================

class TestP0Plus20Beta50BStreamSilenceDetection(unittest.TestCase):
    """stream_nudge 早期 [SILENCE] 检测代码存在性."""

    def _get_src(self):
        path = os.path.join(ROOT, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_silence_chosen_flag(self):
        src = self._get_src()
        self.assertIn('_silence_chosen = False', src,
            'stream_nudge 必须 init _silence_chosen = False (β.5.0-B)')
        self.assertIn('_silence_chosen = True', src,
            'stream 内必须 set _silence_chosen=True (β.5.0-B)')

    def test_silence_detection_in_stream_loop(self):
        src = self._get_src()
        # [β.5.3-fix BUG-3] 检测扩到全 stream (不只 first 32 chars)
        # 验证: 必须有 [SILENCE] 检测在 full_text 全文中
        self.assertTrue(
            "'[SILENCE]' in full_text" in src or "'[silence]' in _ft_lower" in src,
            'stream 必须检测 [SILENCE] in full_text (β.5.0-B + β.5.3-fix BUG-3)'
        )

    def test_silence_break_before_tts(self):
        """[SILENCE] 检测必须在 _put_audio 之前 break."""
        src = self._get_src()
        # [β.5.3-fix BUG-3] _ft_head → full_text 全 stream 检测
        idx_check = src.find("'[SILENCE]' in full_text")
        if idx_check < 0:
            idx_check = src.find("'[silence]' in _ft_lower")
        self.assertGreater(idx_check, 0, '检测代码必须存在')
        idx_break_silence = src.find("_silence_chosen = True", idx_check)
        self.assertGreater(idx_break_silence, 0)
        self.assertLess(idx_check, idx_break_silence,
            'silence detection 必须在 set flag + break 之前')

    def test_silence_handler_skips_buffer_flush(self):
        """_silence_chosen=True → 跳过末尾 buffer flush + return None."""
        src = self._get_src()
        # 找 _silence_chosen 后处理
        idx = src.find('if _silence_chosen:')
        self.assertGreater(idx, 0)
        block = src[idx:idx+1500]
        self.assertIn('return None', block,
            'silence handler 必须 return None')
        # publish self_critique
        self.assertIn("etype='self_critique'", block,
            'silence handler 必须 publish self_critique 到 SWM')

    def test_silence_handler_publishes_to_swm(self):
        """silence → publish 'self_critique' 让下次 prompt 主脑看到."""
        src = self._get_src()
        idx = src.find('if _silence_chosen:')
        block = src[idx:idx+1500]
        self.assertIn("source='BrainReactionSpace'", block,
            "publish source 必须标 BrainReactionSpace (主脑自己选)")
        self.assertIn("'reaction': 'silence'", block,
            "metadata 必须含 reaction='silence'")


# ==========================================================================
# D: 准则 6.5 / evidence-only 反例守护
# ==========================================================================

class TestP0Plus20Beta50BEvidenceOnly(unittest.TestCase):
    """准则 6: directive 不教句式, 只告诉主脑'什么时候选 silence'."""

    def test_directive_does_not_teach_silence_phrases(self):
        """directive 不能写 'Say 我闭嘴 / I'll keep quiet' 这种硬编码句式."""
        path = os.path.join(ROOT, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        # 提取 [REACTION SPACE] 块
        idx = src.find('[REACTION SPACE')
        if idx > 0:
            end = src.find('"""', idx)
            block = src[idx:end] if end > 0 else src[idx:idx+2000]
            forbidden = [
                'Say "I\'ll be quiet"',
                'Reply with "Yes Sir"',
                "Output 'Going quiet'",
            ]
            for p in forbidden:
                self.assertNotIn(p, block,
                    f"reaction_space 不应硬编码句式: {p}")

    def test_directive_uses_evidence_anchors_not_imperatives(self):
        """directive 列触发条件应基于 SWM evidence, 不命令式."""
        path = os.path.join(ROOT, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        # 至少含 "SWM" / "evidence" 关键词
        idx = src.find('[REACTION SPACE')
        block = src[idx:idx+2000] if idx > 0 else ''
        self.assertIn('SWM', block, '触发条件必须 reference SWM evidence')
        self.assertIn('evidence', block.lower(), 'directive 必须强调 evidence-driven')


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print('='*60)
    if result.wasSuccessful():
        print('[OK] All β.5.0-B reaction_space tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('='*60)
    sys.exit(0 if result.wasSuccessful() else 1)
