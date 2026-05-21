# -*- coding: utf-8 -*-
"""[P5-Gap3 / 2026-05-21 18:35] Screen Vision Engine testcase

Sir 22:47 真意 — Vision LLM 描述屏幕给主脑. 后台 daemon, 不阻塞 TTFT, 准则 6 evidence-only.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_DataclassAndDefaults(unittest.TestCase):
    """ScreenSnapshot dataclass + age / fresh / to_dict."""

    def test_screen_snapshot_to_dict(self):
        from jarvis_screen_vision import ScreenSnapshot
        snap = ScreenSnapshot(
            captured_at=1234567890.0,
            captured_iso='2026-05-21T18:30:00',
            active_app='Cursor',
            screen_summary='test',
        )
        d = snap.to_dict()
        self.assertEqual(d['active_app'], 'Cursor')
        self.assertEqual(d['screen_summary'], 'test')
        self.assertIn('captured_at', d)

    def test_screen_snapshot_fresh(self):
        import time
        from jarvis_screen_vision import ScreenSnapshot
        # 5s ago → fresh
        snap = ScreenSnapshot(
            captured_at=time.time() - 5.0,
            captured_iso='now', active_app='', screen_summary='',
        )
        self.assertTrue(snap.is_fresh(60.0))
        # 120s ago → not fresh
        snap_old = ScreenSnapshot(
            captured_at=time.time() - 120.0,
            captured_iso='', active_app='', screen_summary='',
        )
        self.assertFalse(snap_old.is_fresh(60.0))


class TestB_EnvFlagDisabled(unittest.TestCase):
    """env flag JARVIS_SCREEN_VISION=0 时 engine 不工作."""

    def test_engine_disabled_by_default(self):
        # save / clear env
        original = os.environ.pop('JARVIS_SCREEN_VISION', None)
        try:
            from jarvis_screen_vision import ScreenVisionEngine
            engine = ScreenVisionEngine(key_router=None)
            self.assertFalse(engine.enabled())
        finally:
            if original is not None:
                os.environ['JARVIS_SCREEN_VISION'] = original

    def test_engine_enabled_with_flag(self):
        os.environ['JARVIS_SCREEN_VISION'] = '1'
        try:
            from jarvis_screen_vision import ScreenVisionEngine
            engine = ScreenVisionEngine(key_router=None)
            self.assertTrue(engine.enabled())
        finally:
            os.environ.pop('JARVIS_SCREEN_VISION', None)


class TestC_VisionJSONParsing(unittest.TestCase):
    """parse vision LLM JSON 输出 — 含 markdown fence / privacy detection."""

    def setUp(self):
        from jarvis_screen_vision import ScreenVisionEngine
        self.engine = ScreenVisionEngine(key_router=None)

    def test_parse_clean_json(self):
        raw = '{"active_app": "Cursor", "screen_summary": "code review", "confidence": 0.85}'
        snap = self.engine._parse_vision_json(raw, trigger='test')
        self.assertEqual(snap.active_app, 'Cursor')
        self.assertEqual(snap.screen_summary, 'code review')
        self.assertAlmostEqual(snap.confidence, 0.85, places=2)
        self.assertFalse(snap.privacy_redacted)

    def test_parse_markdown_fenced_json(self):
        raw = '```json\n{"active_app": "VS Code", "confidence": 0.7, "screen_summary": "test"}\n```'
        snap = self.engine._parse_vision_json(raw, trigger='test')
        self.assertEqual(snap.active_app, 'VS Code')

    def test_parse_privacy_redacted(self):
        raw = '{"active_app": "1Password", "screen_summary": "privacy-sensitive content, not described", "confidence": 0.0}'
        snap = self.engine._parse_vision_json(raw, trigger='test')
        self.assertTrue(snap.privacy_redacted)

    def test_parse_invalid_json_fallback(self):
        raw = 'not valid json'
        snap = self.engine._parse_vision_json(raw, trigger='test')
        # fallback returns ScreenSnapshot with low confidence
        self.assertEqual(snap.vision_model_used, 'fallback')


class TestD_PersistenceAtomic(unittest.TestCase):
    """ScreenSnapshot 持久化 — atomic 覆盖 + history append."""

    def test_persist_and_load(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_path = os.path.join(tmpdir, 'snap.json')
            hist_path = os.path.join(tmpdir, 'hist.jsonl')
            from jarvis_screen_vision import ScreenVisionEngine, ScreenSnapshot
            import time
            engine = ScreenVisionEngine(
                key_router=None,
                snapshot_path=snap_path,
                history_path=hist_path,
            )
            # 直接写入 latest
            engine._latest = ScreenSnapshot(
                captured_at=time.time(),
                captured_iso='2026-05-21T18:35:00',
                active_app='Cursor',
                screen_summary='test',
                confidence=0.8,
            )
            engine._persist_latest()
            engine._append_history()
            # load 回来
            self.assertTrue(os.path.exists(snap_path))
            with open(snap_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.assertEqual(data['active_app'], 'Cursor')
            # history append
            self.assertTrue(os.path.exists(hist_path))


class TestE_RenderBlock(unittest.TestCase):
    """render_screen_block — env flag + age + confidence + privacy gate."""

    def setUp(self):
        # disable engine for clean state
        os.environ.pop('JARVIS_SCREEN_VISION', None)
        # reset singleton
        import jarvis_screen_vision
        jarvis_screen_vision._DEFAULT_ENGINE = None

    def tearDown(self):
        os.environ.pop('JARVIS_SCREEN_VISION', None)
        import jarvis_screen_vision
        jarvis_screen_vision._DEFAULT_ENGINE = None

    def test_render_disabled_returns_empty(self):
        from jarvis_screen_vision import render_screen_block
        # env flag off + no engine
        self.assertEqual(render_screen_block(), '')

    def test_render_low_confidence_returns_empty(self):
        os.environ['JARVIS_SCREEN_VISION'] = '1'
        import time
        from jarvis_screen_vision import (
            init_default_engine, ScreenSnapshot, render_screen_block
        )
        engine = init_default_engine(key_router=None,
                                        snapshot_path='/tmp/snap_test.json',
                                        history_path='/tmp/hist_test.jsonl')
        engine._latest = ScreenSnapshot(
            captured_at=time.time(),
            captured_iso='now',
            active_app='Cursor',
            screen_summary='test',
            confidence=0.1,  # 太低不显
        )
        block = render_screen_block(max_age_s=120.0)
        self.assertEqual(block, '')

    def test_render_old_frame_returns_empty(self):
        os.environ['JARVIS_SCREEN_VISION'] = '1'
        import time
        from jarvis_screen_vision import (
            init_default_engine, ScreenSnapshot, render_screen_block
        )
        engine = init_default_engine(
            key_router=None,
            snapshot_path='/tmp/snap_test.json',
            history_path='/tmp/hist_test.jsonl')
        engine._latest = ScreenSnapshot(
            captured_at=time.time() - 300.0,  # 5min ago
            captured_iso='old',
            active_app='Cursor',
            screen_summary='test',
            confidence=0.8,
        )
        block = render_screen_block(max_age_s=120.0)
        self.assertEqual(block, '')

    def test_render_privacy_redacted_only_app(self):
        os.environ['JARVIS_SCREEN_VISION'] = '1'
        import time
        from jarvis_screen_vision import (
            init_default_engine, ScreenSnapshot, render_screen_block
        )
        engine = init_default_engine(
            key_router=None,
            snapshot_path='/tmp/snap_test.json',
            history_path='/tmp/hist_test.jsonl')
        engine._latest = ScreenSnapshot(
            captured_at=time.time(),
            captured_iso='now',
            active_app='1Password',
            screen_summary='privacy-sensitive content',
            confidence=0.0,
            privacy_redacted=True,
        )
        block = render_screen_block(max_age_s=120.0)
        self.assertIn('privacy-redacted', block.lower())
        self.assertIn('1Password', block)
        # 不显内容 keywords
        self.assertNotIn('Cursor', block)

    def test_render_normal_includes_all_fields(self):
        os.environ['JARVIS_SCREEN_VISION'] = '1'
        import time
        from jarvis_screen_vision import (
            init_default_engine, ScreenSnapshot, render_screen_block
        )
        engine = init_default_engine(
            key_router=None,
            snapshot_path='/tmp/snap_test.json',
            history_path='/tmp/hist_test.jsonl')
        engine._latest = ScreenSnapshot(
            captured_at=time.time(),
            captured_iso='now',
            active_app='Cursor',
            file_or_url_visible='jarvis_directives.py',
            cursor_line_approx=1547,
            screen_summary='Sir is reading callback guard directive',
            recent_visible_keywords=['callback', 'apology'],
            errors_visible=[],
            build_output_status='idle',
            confidence=0.85,
        )
        block = render_screen_block(max_age_s=120.0)
        self.assertIn('Cursor', block)
        self.assertIn('jarvis_directives.py', block)
        self.assertIn('1547', block)
        self.assertIn('callback', block.lower())
        self.assertIn('HOW TO USE THIS', block)


class TestF_StaticIntegrationCheck(unittest.TestCase):
    """central_nerve / chat_bypass 真接入 vision engine."""

    def test_central_nerve_imports_render_block(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('jarvis_screen_vision', src,
                       'central_nerve 应 import jarvis_screen_vision')
        self.assertIn('render_screen_block', src,
                       'central_nerve 应调 render_screen_block 注 prompt')
        self.assertIn('init_default_engine', src,
                       'central_nerve 应 init_default_engine on startup')

    def test_chat_bypass_feeds_jpeg_to_vision_engine(self):
        import jarvis_chat_bypass
        with open(jarvis_chat_bypass.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('async_describe', src,
                       'chat_bypass 应调 async_describe 复用 img_bytes')
        self.assertIn("trigger='wake'", src,
                       'chat_bypass 应用 trigger=wake')


class TestG_CLIScriptExists(unittest.TestCase):
    """scripts/screen_vision_dump.py 可用."""

    def test_cli_script_exists(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'screen_vision_dump.py'
        )
        self.assertTrue(os.path.exists(path))


if __name__ == '__main__':
    unittest.main()
