# -*- coding: utf-8 -*-
"""[SOUL Phase 5 P2 / Sir 2026-05-29] 思考脑 self-knowledge inject.

设计文档: docs/JARVIS_DYNAMIC_MAP_AND_SELF_DEBUG_DESIGN.md Layer 4

P2 目标: 思考脑 prompt 加 [MY ARCHITECTURE] block — 随时知道自己由哪些模块组成
  → self-debug 时知道改哪 module/vocab. 自我认知元架构延伸 (我是谁 → 我的身体构造).

测试覆盖 (~7 testcase):
  - P2_1: build_architecture_block 含 [MY ARCHITECTURE] + thinking layer
  - P2_2: 含 vocab 标注 (self-debug 知道改哪)
  - P2_3: cache by mtime (二次调同 text)
  - P2_4: max_per_layer 控制数量
  - P2_5: map 不存在 → lazy refresh 不崩
  - P2_6: daemon _build_prompt 集成含 [MY ARCHITECTURE]
  - P2_7: layer 顺序 (thinking 优先)
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _reset_arch_cache():
    import jarvis_module_scanner as m
    m._ARCH_BLOCK_CACHE['text'] = None
    m._ARCH_BLOCK_CACHE['mtime'] = 0.0


class TestBuildArchitectureBlock(unittest.TestCase):
    """P2_1-5: build_architecture_block."""

    def setUp(self):
        _reset_arch_cache()

    def test_P2_1_contains_architecture_header_and_thinking(self):
        from jarvis_module_scanner import build_architecture_block
        block = build_architecture_block()
        self.assertIn('[MY ARCHITECTURE', block)
        self.assertIn('thinking:', block)
        self.assertIn('inner_thought', block)
        # self-debug 引导语
        self.assertIn('self-debug', block.lower())

    def test_P2_2_contains_vocab_annotation(self):
        from jarvis_module_scanner import build_architecture_block
        block = build_architecture_block()
        # 至少某模块带 vocab 标注 (self-debug 知道改哪)
        self.assertIn('vocab:', block)

    def test_P2_3_cache_by_mtime(self):
        from jarvis_module_scanner import build_architecture_block
        b1 = build_architecture_block()
        b2 = build_architecture_block()
        self.assertEqual(b1, b2)  # cache hit 同 text

    def test_P2_4_max_per_layer(self):
        from jarvis_module_scanner import build_architecture_block
        _reset_arch_cache()
        b1 = build_architecture_block(max_per_layer=1)
        _reset_arch_cache()
        b3 = build_architecture_block(max_per_layer=3)
        # max=3 每 layer 列更多 → 总体更长 (或相等若 layer 模块少)
        self.assertGreaterEqual(len(b3), len(b1))

    def test_P2_5_missing_map_lazy_refresh(self):
        """P2_5: map 不存在 → lazy refresh 不崩."""
        import jarvis_module_scanner as m
        _reset_arch_cache()
        bogus = tempfile.mktemp(suffix='_nomap.json')
        with patch.object(m, '_MODULE_MAP_PATH', bogus):
            # bogus 不存在 → load 返 None → lazy refresh (真扫)
            block = m.build_architecture_block()
        # 应不崩 (返 block 或空, 不 raise)
        self.assertIsInstance(block, str)


class TestDaemonIntegration(unittest.TestCase):
    """P2_6-7: daemon _build_prompt 集成."""

    def setUp(self):
        _reset_arch_cache()

    def _make_daemon(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        with patch.object(
            InnerThoughtDaemon, '_append_cold_start_record',
            return_value=None,
        ):
            return InnerThoughtDaemon(key_router=MagicMock())

    def test_P2_6_prompt_contains_architecture_block(self):
        """P2_6: 思考脑 _build_prompt 含 [MY ARCHITECTURE]."""
        daemon = self._make_daemon()
        mock_ev = {
            'sir_state': 'active', 'idle_seconds': 60, 'hour': 0,
            'recent_thoughts': [], 'swm_events': [],
        }
        with patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
            return_value=MagicMock(recent=MagicMock(return_value=[]))
        ), patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True,
        ):
            _sys, user_prompt = daemon._build_prompt(
                sir_state='active', evidence=mock_ev,
            )
        self.assertIn('[MY ARCHITECTURE', user_prompt,
                      "P2_6 思考脑 prompt 应含 [MY ARCHITECTURE] self-knowledge")
        self.assertIn('inner_thought', user_prompt)

    def test_P2_7_layer_order_thinking_first(self):
        """P2_7: layer 顺序 thinking 在 soul 前."""
        from jarvis_module_scanner import build_architecture_block
        _reset_arch_cache()
        block = build_architecture_block()
        idx_thinking = block.find('thinking:')
        idx_soul = block.find('soul:')
        if idx_thinking >= 0 and idx_soul >= 0:
            self.assertLess(idx_thinking, idx_soul,
                            "P2_7 thinking 应在 soul 前")


if __name__ == '__main__':
    unittest.main(verbosity=2)
