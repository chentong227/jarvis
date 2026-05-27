# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 12:13 真痛 anchor] 思考脑跟主脑沟通清晰化.

Sir 反问根因 (12:08): "思考意识到了 没办法影响主脑吗?"
我钻研 (12:13): 通路已有 3 个, L1067 真问题是**思考脑选错通路 + 内容太抽象 +
AutoArbiter 慢通路积压**, 4 个环节全在挡.

修法 (Sir 12:17 拍板):
  Phase A: 教思考脑 prompt - 加 B 类 surface_to_sir example + 加通路选择决策树
           + 加反抽象红线 (jarvis_inner_thought_daemon.py:1432-1472)
  Phase B: AutoArbiter pre-reject abstract protocol - 不再 DEFER 积压
           (jarvis_auto_arbiter.py:531-646 + memory_pool/auto_arbiter_abstract_reject_vocab.json)

测试 (7 testcase):
  - T1: prompt 含 B-class surface_to_sir example
  - T2: prompt 含通路选择决策树 (跨午夜后是否仍适用)
  - T3: prompt 含反抽象红线 ('prioritize', 'be more', etc forbidden)
  - T4: AutoArbiter vocab 文件存在 + enabled=true
  - T5: _is_abstract_protocol abstract case (含 'prioritize' + 'concise' 命中)
  - T6: _is_abstract_protocol concrete case (含 'Do not open with X' 不命中)
  - T7: _is_abstract_protocol too_short case
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestPhaseAPromptTeachThinking(unittest.TestCase):
    """思考脑 prompt 教导分类 + 反抽象 (Phase A)."""

    def test_t1_prompt_has_surface_to_sir_b_class_example(self):
        """_build_prompt B 类示例区必有 surface_to_sir:next_turn_inject 案例."""
        import jarvis_inner_thought_daemon
        with open(jarvis_inner_thought_daemon.__file__, 'r',
                  encoding='utf-8') as f:
            src = f.read()
        self.assertIn("B-class surface_to_sir example", src,
            'prompt 必有 B-class surface_to_sir example 标签')
        self.assertIn("surface_to_sir:next_turn_inject:Sir", src,
            'prompt 必有 surface_to_sir:next_turn_inject 具体示范')
        self.assertIn("SHORT-TERM CONTEXTUAL", src,
            'prompt 必有 SHORT-TERM CONTEXTUAL 标签明示语义')

    def test_t2_prompt_has_channel_decision_tree(self):
        """prompt 必有通路选择决策树 (跨午夜后是否仍适用)."""
        import jarvis_inner_thought_daemon
        with open(jarvis_inner_thought_daemon.__file__, 'r',
                  encoding='utf-8') as f:
            src = f.read()
        self.assertIn("通路选择决策树", src,
            'prompt 必有通路选择决策树标题')
        self.assertIn("跨午夜后", src,
            'prompt 必有跨午夜判定 (long-term vs short-term)')
        self.assertIn("long-term policy", src.lower() if 'long-term policy' not in src else src,
            'prompt 必含 long-term policy 概念')

    def test_t3_prompt_has_anti_abstract_red_line(self):
        """prompt 必有反抽象红线 (forbidden abstract vocab)."""
        import jarvis_inner_thought_daemon
        with open(jarvis_inner_thought_daemon.__file__, 'r',
                  encoding='utf-8') as f:
            src = f.read()
        self.assertIn("反抽象红线", src,
            'prompt 必有反抽象红线标题')
        # 必含至少 3 个 forbidden 词的明示禁用
        forbidden_in_prompt = ['prioritize', 'be more', 'maintain', 'genuine']
        for word in forbidden_in_prompt:
            self.assertIn(f"'{word}'", src,
                f"prompt 必显式禁 abstract vocab '{word}'")


class TestPhaseBAutoArbiterAbstractReject(unittest.TestCase):
    """AutoArbiter abstract protocol pre-reject (Phase B)."""

    def test_t4_abstract_reject_vocab_exists_and_enabled(self):
        """memory_pool/auto_arbiter_abstract_reject_vocab.json 必存在 + enabled=true."""
        vocab_path = os.path.join(ROOT, 'memory_pool',
                                       'auto_arbiter_abstract_reject_vocab.json')
        self.assertTrue(os.path.exists(vocab_path),
            f'vocab 文件必存在: {vocab_path}')
        with open(vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertTrue(data.get('enabled'),
            'vocab enabled 必为 true (默认开启 pre-reject)')
        keywords = data.get('abstract_keywords', [])
        self.assertGreater(len(keywords), 5,
            f'vocab abstract_keywords 必含 > 5 个词, 实际 {len(keywords)}')
        # 关键词必含 Sir 真痛 L1067 propose 的 abstract 词
        self.assertIn('prioritize', keywords,
            'vocab 必含 "prioritize" (L1067 真案例)')
        self.assertIn('concise', keywords,
            'vocab 必含 "concise" (L1067 真案例)')

    def _make_arbiter(self):
        """构 AutoArbiterDaemon 实例 (mock dependencies)."""
        from jarvis_auto_arbiter import AutoArbiterDaemon
        kr = MagicMock()
        rel = MagicMock()
        arb = AutoArbiterDaemon(key_router=kr, relational_state=rel)
        return arb

    def test_t5_is_abstract_kw_hit(self):
        """L1067 真案例: 'Always prioritize concise direct cadence' → abstract."""
        arb = self._make_arbiter()
        # L1067 真 actionable 内容
        rule = "Always prioritize concise direct cadence and maintain professional restraint"
        is_abs, reason = arb._is_abstract_protocol(rule)
        self.assertTrue(is_abs,
            f'真 L1067 案例必判 abstract, got is_abs={is_abs}, reason={reason}')
        self.assertIn('abstract_kw_hit', reason,
            f'reason 必含 abstract_kw_hit 标签, got {reason}')

    def test_t6_is_concrete_pass(self):
        """具体 'Do not open replies with X' → concrete (不 reject)."""
        arb = self._make_arbiter()
        rule = "Do not open replies with formal apologies like 'My apologies, Sir'"
        is_abs, reason = arb._is_abstract_protocol(rule)
        self.assertFalse(is_abs,
            f'具体规则必不判 abstract, got is_abs={is_abs}, reason={reason}')

    def test_t7_too_short_rejected(self):
        """太短 rule (< min_words=4) 直接 reject."""
        arb = self._make_arbiter()
        rule = "Be nicer"  # 2 词
        is_abs, reason = arb._is_abstract_protocol(rule)
        self.assertTrue(is_abs,
            f'< 4 词 rule 必 reject, got is_abs={is_abs}')
        self.assertIn('too_short', reason,
            f'reason 必含 too_short 标签, got {reason}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
