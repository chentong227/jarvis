# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 18:44 真愿景] InnerVoice Phase 5 — sir_injected + CLI tools.

Phase 5 工程:
  - scripts/inner_voice_inject.py: Sir 注入 sir_injected source
  - scripts/inner_voice_aging_dump.py 加 tail subcommand

测试 (10 testcase, 不实际跑 tail 守门, 测 CLI 静态 invariant + inject 集成):

Step 5a — inject CLI (5 testcase):
  - PH5_1: scripts/inner_voice_inject.py 存在 + main() callable
  - PH5_2: inject 默认 source='sir_injected' intent='reflection' urgency=0.5 ★=True
  - PH5_3: --no-want flag 关闭 wants_voice
  - PH5_4: --intent / --urgency / --source 覆盖默认
  - PH5_5: empty content → exit 2

Step 5b — tail subcommand (3 testcase):
  - PH5_6: aging_dump.py 含 cmd_tail
  - PH5_7: argparse 注册 'tail' subcommand
  - PH5_8: tail --from-start flag 注册

Step 5c — sir_injected source 集成 (2 testcase):
  - PH5_9: 注入的 entry 含 meta.kind='sir_injection'
  - PH5_10: prompt block render 时 sir_injected entry 跟其它 entry 一样显示
            (source 标在 (sir_injected/intent) 段)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def _fresh_track():
    import jarvis_inner_voice_track as ivt
    ivt.reset_for_test()
    td = tempfile.mkdtemp()
    track = ivt.InnerVoiceTrack(persist_path=os.path.join(td, 'iv.jsonl'))
    ivt._DEFAULT = track
    return track


# ============================================================
# Step 5a — inject CLI
# ============================================================

class TestStep5aInjectCli(unittest.TestCase):

    def test_ph5_1_inject_script_exists_and_callable(self):
        """PH5_1: inject script 存在且 main() callable."""
        path = os.path.join(_REPO, 'scripts', 'inner_voice_inject.py')
        self.assertTrue(os.path.exists(path), 'inject script not found')
        import importlib.util as _iu
        spec = _iu.spec_from_file_location('_inject_mod', path)
        mod = _iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(callable(getattr(mod, 'main', None)))

    def test_ph5_2_inject_defaults(self):
        """PH5_2: 默认 source=sir_injected intent=reflection urgency=0.5 ★=True."""
        track = _fresh_track()
        import importlib.util as _iu
        path = os.path.join(_REPO, 'scripts', 'inner_voice_inject.py')
        spec = _iu.spec_from_file_location('_inj', path)
        mod = _iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rc = mod.main(['test content default'])
        self.assertEqual(rc, 0)
        # 验证 buffer 有一条
        entries = track.all_recent(hours=1.0)
        # 找 sir_injected source
        sir_entries = [e for e in entries if e.source == 'sir_injected']
        self.assertEqual(len(sir_entries), 1)
        e = sir_entries[0]
        self.assertEqual(e.intent, 'reflection')
        self.assertAlmostEqual(e.urgency, 0.5, places=2)
        self.assertTrue(e.wants_voice)
        self.assertEqual(e.content, 'test content default')

    def test_ph5_3_no_want_flag(self):
        """PH5_3: --no-want 关闭 wants_voice."""
        track = _fresh_track()
        import importlib.util as _iu
        path = os.path.join(_REPO, 'scripts', 'inner_voice_inject.py')
        spec = _iu.spec_from_file_location('_inj2', path)
        mod = _iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rc = mod.main(['silent inject', '--no-want'])
        self.assertEqual(rc, 0)
        entries = [e for e in track.all_recent(hours=1.0)
                          if e.source == 'sir_injected']
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0].wants_voice)

    def test_ph5_4_intent_urgency_source_override(self):
        """PH5_4: --intent / --urgency / --source 覆盖默认."""
        track = _fresh_track()
        import importlib.util as _iu
        path = os.path.join(_REPO, 'scripts', 'inner_voice_inject.py')
        spec = _iu.spec_from_file_location('_inj3', path)
        mod = _iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rc = mod.main([
            'reminder content',
            '--intent', 'reminder', '--urgency', '0.85',
            '--source', 'noting',
        ])
        self.assertEqual(rc, 0)
        entries = [e for e in track.all_recent(hours=1.0)
                          if e.content == 'reminder content']
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e.intent, 'reminder')
        self.assertAlmostEqual(e.urgency, 0.85, places=2)
        self.assertEqual(e.source, 'noting')

    def test_ph5_5_empty_content_exits_2(self):
        """PH5_5: empty content (空白) → argparse 报错 exit 2."""
        import importlib.util as _iu
        path = os.path.join(_REPO, 'scripts', 'inner_voice_inject.py')
        spec = _iu.spec_from_file_location('_inj4', path)
        mod = _iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # 直接 main(['   ']) -- 空白 content (strip 后空) → return 2
        # 用 stderr 重定向
        rc = mod.main(['   '])
        self.assertEqual(rc, 2)


# ============================================================
# Step 5b — tail subcommand
# ============================================================

class TestStep5bTailSubcommand(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        path = os.path.join(_REPO, 'scripts', 'inner_voice_aging_dump.py')
        with open(path, 'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_ph5_6_has_cmd_tail(self):
        """PH5_6: aging_dump.py 含 cmd_tail 函数."""
        self.assertIn('def cmd_tail(', self.src)

    def test_ph5_7_tail_registered_in_subparsers(self):
        """PH5_7: argparse 注册 'tail' subcommand + dispatch map."""
        self.assertIn("'tail'", self.src)
        # 也要在 dispatch dict 里
        self.assertIn("'tail': cmd_tail", self.src)

    def test_ph5_8_tail_has_from_start_flag(self):
        """PH5_8: tail --from-start 注册."""
        self.assertIn('--from-start', self.src)


# ============================================================
# Step 5c — sir_injected source 集成
# ============================================================

class TestStep5cSirInjectedIntegration(unittest.TestCase):

    def test_ph5_9_injected_entry_has_meta_kind(self):
        """PH5_9: 注入的 entry meta.kind='sir_injection'."""
        track = _fresh_track()
        import importlib.util as _iu
        path = os.path.join(_REPO, 'scripts', 'inner_voice_inject.py')
        spec = _iu.spec_from_file_location('_inj5', path)
        mod = _iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rc = mod.main(['meta test'])
        self.assertEqual(rc, 0)
        entries = [e for e in track.all_recent(hours=1.0)
                          if e.content == 'meta test']
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertIsNotNone(e.meta)
        self.assertEqual(e.meta.get('kind'), 'sir_injection')

    def test_ph5_10_injected_entry_renders_in_prompt_block(self):
        """PH5_10: prompt block render 时 sir_injected entry 显示."""
        track = _fresh_track()
        import importlib.util as _iu
        path = os.path.join(_REPO, 'scripts', 'inner_voice_inject.py')
        spec = _iu.spec_from_file_location('_inj6', path)
        mod = _iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rc = mod.main(['prompt render test from sir'])
        self.assertEqual(rc, 0)
        out = track.build_prompt_block_for_brain(max_chars=3000)
        self.assertIn('prompt render test from sir', out)
        # source 段 (sir_injected) 显示在 entry render 中
        self.assertIn('sir_injected', out)


if __name__ == '__main__':
    unittest.main(verbosity=2)
