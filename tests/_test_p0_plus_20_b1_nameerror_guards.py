# -*- coding: utf-8 -*-
"""[P0+20-β.1.6-7 / 2026-05-16] NameError 防护回归测试

覆盖 Sir 14:30 实测暴露的 P0+19 拆分留尾 BUG：
- F6/B8: jarvis_chat_bypass.py 未 import JARVIS_CORE_PERSONA → OfferHelp NameError 静默吞 → "未出声"
- F7/B9: jarvis_return_sentinel.py 未 import win32api → idle_ms 永 0 → was_afk 永 False → 归来感知失效
- F7/B9b: jarvis_smart_nudge.py 未 import win32api → 主循环 idle 失真
- F7/B9c: jarvis_commitment_watcher.py 未 import win32api → 承诺过期分支静默丢失

策略：用 Python 运行时反射检查模块级符号 + 实际属性访问 → 一旦有 NameError 留尾立刻 fail。

规范：详 AGENTS.md + docs/JARVIS_WORKFLOW_PROTOCOL.md
"""
import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestF6ChatBypassPersonaImport(unittest.TestCase):
    """治 B8: chat_bypass.py 函数体内引用 JARVIS_CORE_PERSONA 但顶部没 import"""

    def test_module_imports_clean(self):
        mod = importlib.import_module('jarvis_chat_bypass')
        self.assertTrue(hasattr(mod, 'ChatBypass'))

    def test_persona_accessible_via_central_nerve(self):
        """JARVIS_CORE_PERSONA 应能从 jarvis_central_nerve 拿到（chat_bypass 函数体内延迟 import 走这条）"""
        from jarvis_central_nerve import JARVIS_CORE_PERSONA
        self.assertIsInstance(JARVIS_CORE_PERSONA, str)
        self.assertGreater(len(JARVIS_CORE_PERSONA), 1000, "PERSONA 应 ≥ 1000 chars")
        self.assertIn('J.A.R.V.I.S', JARVIS_CORE_PERSONA)

    def test_persona_use_sites_have_local_import(self):
        """grep chat_bypass.py 源码：每个用 JARVIS_CORE_PERSONA 的位置附近必须有 import"""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'jarvis_chat_bypass.py'
        )
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('from jarvis_central_nerve import JARVIS_CORE_PERSONA',
                      src, "chat_bypass.py 必须延迟 import JARVIS_CORE_PERSONA")
        self.assertNotIn('{JARVIS_CORE_PERSONA}', src,
                         "不应再有裸用 {JARVIS_CORE_PERSONA}（应换成 _JCP 局部别名）")


class TestF7ReturnSentinelWin32Import(unittest.TestCase):
    """治 B9: return_sentinel.py 主循环用 win32api 但顶部没 import → idle_ms 永 0"""

    def test_module_imports_clean(self):
        mod = importlib.import_module('jarvis_return_sentinel')
        self.assertTrue(hasattr(mod, 'ReturnSentinel'))

    def test_win32api_module_level_symbol(self):
        """模块级必须有 win32api 这个名（即使 ImportError 也得有占位 None）"""
        import jarvis_return_sentinel as mod
        self.assertTrue(hasattr(mod, 'win32api'),
                        "win32api 必须在模块级存在（避免主循环 NameError）")
        self.assertTrue(hasattr(mod, '_WIN32_OK'),
                        "_WIN32_OK flag 必须存在（决定走 idle 路径还是兜底）")

    def test_win32api_actually_imported_on_windows(self):
        """实际 Windows 环境下 win32api 应 import 成功"""
        if sys.platform != 'win32':
            self.skipTest("非 Windows 环境")
        import jarvis_return_sentinel as mod
        self.assertTrue(mod._WIN32_OK,
                        "Windows 环境下 win32api 应 import 成功；如果失败说明 pywin32 未装")
        self.assertIsNotNone(mod.win32api)

    def test_idle_probe_returns_int(self):
        """模拟主循环：win32api.GetTickCount - GetLastInputInfo 应能返回 int"""
        if sys.platform != 'win32':
            self.skipTest("非 Windows 环境")
        import jarvis_return_sentinel as mod
        if not mod._WIN32_OK:
            self.skipTest("win32api 不可用")
        idle_ms = mod.win32api.GetTickCount() - mod.win32api.GetLastInputInfo()
        self.assertIsInstance(idle_ms, int)
        self.assertGreaterEqual(idle_ms, 0)


class TestF7SmartNudgeWin32Import(unittest.TestCase):
    """治 B9b: smart_nudge.py 主循环 idle_ms 失真"""

    def test_module_imports_clean(self):
        mod = importlib.import_module('jarvis_smart_nudge')
        self.assertTrue(hasattr(mod, 'SmartNudgeSentinel'))

    def test_win32api_module_level_symbol(self):
        import jarvis_smart_nudge as mod
        self.assertTrue(hasattr(mod, 'win32api'),
                        "win32api 必须在模块级存在")


class TestF7CommitmentWatcherWin32Import(unittest.TestCase):
    """治 B9c: commitment_watcher.py 承诺过期分支"""

    def test_module_imports_clean(self):
        mod = importlib.import_module('jarvis_commitment_watcher')
        self.assertTrue(hasattr(mod, 'CommitmentWatcher'))

    def test_win32api_module_level_symbol(self):
        import jarvis_commitment_watcher as mod
        self.assertTrue(hasattr(mod, 'win32api'),
                        "win32api 必须在模块级存在")


class TestAllSplitModulesImportClean(unittest.TestCase):
    """全量 import smoke：所有 jarvis_*.py 模块都能 clean import 不抛 NameError"""

    SPLIT_MODULES = [
        'jarvis_safety',
        'jarvis_key_router',
        'jarvis_llm_reflector',
        'jarvis_env_probe',
        'jarvis_sensors',
        'jarvis_routing',
        'jarvis_memory_core',
        'jarvis_sentinels',
        'jarvis_conductor',
        'jarvis_return_sentinel',
        'jarvis_commitment_watcher',
        'jarvis_smart_nudge',
        'jarvis_chat_bypass',
        'jarvis_central_nerve',
        'jarvis_blood',
        'jarvis_hippocampus',
        'jarvis_vocal_cord',
        'jarvis_enhanced',
        'jarvis_skill_registry',
        'jarvis_directives',
        'jarvis_utils',
        'jarvis_worker',
        'jarvis_fuzzy_resolver',
    ]

    def test_all_split_modules_import(self):
        failed = []
        for name in self.SPLIT_MODULES:
            try:
                importlib.import_module(name)
            except Exception as e:
                failed.append((name, type(e).__name__, str(e)[:120]))
        if failed:
            msg = "以下模块 import 失败：\n" + "\n".join(
                f"  - {n}: {t}: {e}" for n, t, e in failed
            )
            self.fail(msg)


if __name__ == '__main__':
    unittest.main()
