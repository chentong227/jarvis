# -*- coding: utf-8 -*-
"""[P0+20-β.2.7.1 / 2026-05-17] 灵魂通用化 Phase 1 — nudge 路径接通 Layer 0-3 测试

详 docs/JARVIS_SOUL_UNIVERSALIZATION.md Phase 1。

测试目标：
1. _build_nudge_prompt helper 接受 core_persona 参数 + 调 chat_bypass._build_public_layers
2. _build_public_layers 头部的裸 JARVIS_CORE_PERSONA 被替换成 core_persona（含 Layer 0-3）
3. chat_bypass 缺失时退化返回 core_persona
4. _build_public_layers 抛异常时退化返回 core_persona
5. _assemble_prompt(mode='nudge') 是 _build_nudge_prompt 的简单 dispatcher
6. stream_nudge 静态扫码确认调 _assemble_prompt(mode='nudge')，保留 _build_public_layers fallback
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# A. _build_nudge_prompt helper 单元测试（核心逻辑）
# ============================================================
class TestBuildNudgePromptHelper(unittest.TestCase):
    """测试 nerve._build_nudge_prompt 的所有分支。"""

    def _make_nerve_with_chat_bypass(self, build_layers_return=None,
                                      build_layers_raises=None,
                                      no_chat_bypass=False):
        """构造一个最小 nerve，只暴露 _build_nudge_prompt 需要的接口。"""
        from jarvis_central_nerve import CentralNerve, JARVIS_CORE_PERSONA

        class _MinimalNerve:
            pass

        nerve = _MinimalNerve()
        nerve._build_nudge_prompt = CentralNerve._build_nudge_prompt.__get__(nerve)

        if no_chat_bypass:
            nerve.chat_bypass = None
        else:
            cb = MagicMock()
            if build_layers_raises is not None:
                cb._build_public_layers.side_effect = build_layers_raises
            else:
                cb._build_public_layers.return_value = (
                    build_layers_return
                    if build_layers_return is not None
                    else JARVIS_CORE_PERSONA + "\n\n[REST] some context"
                )
            nerve.chat_bypass = cb
        return nerve

    def test_no_chat_bypass_returns_core_persona(self):
        nerve = self._make_nerve_with_chat_bypass(no_chat_bypass=True)
        out = nerve._build_nudge_prompt(core_persona='HELLO_PERSONA')
        self.assertEqual(out, 'HELLO_PERSONA')

    def test_chat_bypass_calls_build_public_layers_with_ledger(self):
        nerve = self._make_nerve_with_chat_bypass()
        ledger = {'emotional_tone': 'Tired'}
        nerve._build_nudge_prompt(core_persona='X', ledger_data=ledger)
        nerve.chat_bypass._build_public_layers.assert_called_once_with(ledger)

    def test_jcp_head_replaced_with_core_persona(self):
        from jarvis_central_nerve import JARVIS_CORE_PERSONA
        nerve = self._make_nerve_with_chat_bypass(
            build_layers_return=JARVIS_CORE_PERSONA + "\n\n[REST]"
        )
        out = nerve._build_nudge_prompt(core_persona='[CORE_WITH_SOUL]')
        # JCP 应被替换成 core_persona
        self.assertTrue(out.startswith('[CORE_WITH_SOUL]'))
        self.assertIn('[REST]', out)
        # 不再含原始 JCP 头部前 200 字符（避免 PERSONA 文字本身含相同短语）
        self.assertNotIn(JARVIS_CORE_PERSONA[:200], out[:300])

    def test_unexpected_head_prepends_core_persona(self):
        """若 _build_public_layers 头部不是 JCP（兼容性场景），前置 core_persona。"""
        nerve = self._make_nerve_with_chat_bypass(
            build_layers_return="[ALTERNATIVE_HEAD]\n[BODY]"
        )
        out = nerve._build_nudge_prompt(core_persona='[CORE]')
        self.assertTrue(out.startswith('[CORE]'))
        self.assertIn('[ALTERNATIVE_HEAD]', out)
        self.assertIn('[BODY]', out)

    def test_build_public_layers_exception_fallback(self):
        nerve = self._make_nerve_with_chat_bypass(
            build_layers_raises=RuntimeError('mock fail')
        )
        out = nerve._build_nudge_prompt(core_persona='[CORE_FALLBACK]')
        self.assertEqual(out, '[CORE_FALLBACK]')

    def test_diag_sizes_does_not_break(self):
        """诊断 sizes dict 是 optional，传或不传都不应报错。"""
        from jarvis_central_nerve import JARVIS_CORE_PERSONA
        nerve = self._make_nerve_with_chat_bypass(
            build_layers_return=JARVIS_CORE_PERSONA + "\n[X]"
        )
        out = nerve._build_nudge_prompt(
            core_persona='[CORE]',
            _diag_sizes={'L0': 100, 'L1': 200, 'L2': 300, 'L3': 50},
        )
        self.assertIn('[CORE]', out)


# ============================================================
# B. _assemble_prompt(mode='nudge') 是 helper 的 dispatcher
# ============================================================
class TestAssemblePromptNudgeDispatch(unittest.TestCase):
    def test_assemble_prompt_nudge_mode_calls_helper(self):
        """静态扫码：_assemble_prompt 的 mode='nudge' 分支应调 _build_nudge_prompt。"""
        import inspect
        from jarvis_central_nerve import CentralNerve
        src = inspect.getsource(CentralNerve._assemble_prompt)
        # 应有 if mode == "nudge" 分支
        self.assertIn('mode == "nudge"', src)
        # 调 helper
        self.assertIn('_build_nudge_prompt', src)


# ============================================================
# C. stream_nudge 静态扫码：调 _assemble_prompt(mode='nudge')
# ============================================================
class TestStreamNudgeUsesAssemblePrompt(unittest.TestCase):
    def test_stream_nudge_calls_assemble_prompt_nudge_mode(self):
        import inspect
        from jarvis_chat_bypass import ChatBypass
        src = inspect.getsource(ChatBypass.stream_nudge)
        self.assertIn("_assemble_prompt", src)
        self.assertIn("mode='nudge'", src)
        # 保留 _build_public_layers 作 fallback
        self.assertIn("_build_public_layers", src)


# ============================================================
# D. _build_public_layers 不被删（向后兼容 + fallback）
# ============================================================
class TestBuildPublicLayersStillExists(unittest.TestCase):
    def test_build_public_layers_still_callable(self):
        from jarvis_chat_bypass import ChatBypass
        self.assertTrue(hasattr(ChatBypass, '_build_public_layers'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
