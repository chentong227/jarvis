# -*- coding: utf-8 -*-
"""[fix31 / Sir 2026-05-28 00:36 真意 β.6 Phase 1d 收口准则 6 vocab 持久化]

Phase 1d 改动 (β.6 收口 — 把硬编码挪去 memory_pool/thinking_brain_speak_config.json):
  1. _SPEAK_RATE_WINDOW_S / _SPEAK_RATE_MAX_YES / valid styles / default style
     全部 vocab-driven (运行时 lazy-load + 30s mtime throttle).
  2. Schema v2: styles = [{name, description, default_if_invalid}], 加 style 改
     JSON 即可, .py 不动. Loader 兼容 v1 (valid_styles + default_style_if_invalid).
  3. Prompt SPEAK_STYLE schema line 从 vocab 自动拼接 (_build_speak_style_prompt_line),
     新增 style → prompt 自动同步, 不必改 .py.
  4. _should_smooth_force_silent 改用 vocab rate cap (Python smoothing 物理保底).

测试覆盖 (符合 Sir 设计准则 6 三维耦合 + 4 问筛查):
  L31 vocab 文件存在, JSON valid
  L32 schema v2 loader 解析正确 (默认配置 = 3 styles + rate_cap)
  L33 _get_valid_speak_styles 返 tuple of (silent_text, voice, visual_pulse)
  L34 _get_default_speak_style 返 'silent_text' (default_if_invalid=True 的那个)
  L35 _get_speak_rate_cap 返 (300, 3)
  L36 _build_speak_style_prompt_line 含所有 style name + description + default 提示
  L37 schema v1 兼容 (valid_styles + default_style_if_invalid 老格式)
  L38 schema v2 + 缺 default_if_invalid → fallback 第 1 个
  L39 vocab 损坏 (非 JSON) → fallback default (loader 不崩)
  L40 _should_smooth_force_silent 用 vocab rate cap (不再硬编码 5/3)
  L41 prompt 含 vocab-driven SPEAK_STYLE schema line (反向验证主链路)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _reset_speak_cache():
    """清 vocab cache 让下次 load 真读文件."""
    import jarvis_inner_thought_daemon as m
    m._SPEAK_CONFIG_CACHE['data'] = None
    m._SPEAK_CONFIG_CACHE['mtime'] = 0.0
    m._SPEAK_CONFIG_CACHE['checked_at'] = 0.0


# ==========================================================
# L31-L36 vocab 文件 + loader + getter + prompt 拼装
# ==========================================================

class TestL31VocabFileExistsAndValid(unittest.TestCase):
    """memory_pool/thinking_brain_speak_config.json 存在且 JSON 合法."""

    def test_file_exists_and_valid_json(self):
        path = os.path.join(ROOT, 'memory_pool', 'thinking_brain_speak_config.json')
        self.assertTrue(os.path.exists(path), f"vocab JSON missing: {path}")
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)


class TestL32LoaderParsesV2Schema(unittest.TestCase):
    """schema v2: loader 返回 dict 含 styles (list) + rate_cap (dict)."""

    def test_v2_loader(self):
        _reset_speak_cache()
        from jarvis_inner_thought_daemon import _load_speak_config
        cfg = _load_speak_config()
        self.assertIn('styles', cfg)
        self.assertIsInstance(cfg['styles'], list)
        self.assertGreaterEqual(len(cfg['styles']), 1)
        self.assertIn('rate_cap', cfg)
        self.assertIn('window_s', cfg['rate_cap'])
        self.assertIn('max_yes_in_window', cfg['rate_cap'])


class TestL33ValidSpeakStylesFromVocab(unittest.TestCase):
    """_get_valid_speak_styles 返 tuple, 含至少 3 default style."""

    def test_valid_styles(self):
        _reset_speak_cache()
        from jarvis_inner_thought_daemon import _get_valid_speak_styles
        styles = _get_valid_speak_styles()
        self.assertIsInstance(styles, tuple)
        for s in ('silent_text', 'voice', 'visual_pulse'):
            self.assertIn(s, styles, f"missing canonical style: {s}")


class TestL34DefaultStyleIsSilentText(unittest.TestCase):
    """_get_default_speak_style 返 vocab 里 default_if_invalid=True 的 (silent_text)."""

    def test_default_style(self):
        _reset_speak_cache()
        from jarvis_inner_thought_daemon import _get_default_speak_style
        d = _get_default_speak_style()
        self.assertEqual(d, 'silent_text')


class TestL35RateCapFromVocab(unittest.TestCase):
    """_get_speak_rate_cap 返 vocab 设定 (window_s, max_yes_in_window)."""

    def test_rate_cap(self):
        _reset_speak_cache()
        from jarvis_inner_thought_daemon import _get_speak_rate_cap
        window, max_yes = _get_speak_rate_cap()
        self.assertGreater(window, 0)
        self.assertGreater(max_yes, 0)
        # 与默认 vocab 一致 (5min / 3)
        self.assertEqual(window, 300)
        self.assertEqual(max_yes, 3)


class TestL36PromptLineBuiltFromVocab(unittest.TestCase):
    """_build_speak_style_prompt_line 含 enum 名 + description + default 提示."""

    def test_prompt_line(self):
        _reset_speak_cache()
        from jarvis_inner_thought_daemon import _build_speak_style_prompt_line
        line = _build_speak_style_prompt_line()
        self.assertIsInstance(line, str)
        # enum 名
        for name in ('silent_text', 'voice', 'visual_pulse'):
            self.assertIn(name, line, f"prompt line missing style: {name}")
        # 描述 (任 1 个真描述 substring)
        self.assertIn('subtitle', line.lower())
        # default 提示
        self.assertIn('default', line.lower())


# ==========================================================
# L37 schema v1 向后兼容
# ==========================================================

class TestL37V1SchemaBackwardCompat(unittest.TestCase):
    """老 schema v1 (valid_styles + default_style_if_invalid) → loader 自动转 v2."""

    def test_v1_schema_normalized(self):
        v1_data = {
            'valid_styles': {'values': ['foo', 'bar', 'baz']},
            'default_style_if_invalid': {'value': 'bar'},
            'rate_cap': {'window_s': 120, 'max_yes_in_window': 2},
        }
        from jarvis_inner_thought_daemon import _normalize_speak_config
        out = _normalize_speak_config(v1_data)
        self.assertIn('styles', out)
        names = [s['name'] for s in out['styles']]
        self.assertEqual(names, ['foo', 'bar', 'baz'])
        # 'bar' 是 default
        defaults = [s for s in out['styles'] if s.get('default_if_invalid')]
        self.assertEqual(len(defaults), 1)
        self.assertEqual(defaults[0]['name'], 'bar')
        # rate_cap 也带过
        self.assertEqual(out['rate_cap']['window_s'], 120)
        self.assertEqual(out['rate_cap']['max_yes_in_window'], 2)


# ==========================================================
# L38 v2 缺 default_if_invalid 全 False → fallback 第 1 个
# ==========================================================

class TestL38V2NoDefaultFallbackToFirst(unittest.TestCase):
    """v2 styles 全 default_if_invalid=False → _get_default_speak_style 回第 1 个."""

    def test_no_default_returns_first(self):
        import jarvis_inner_thought_daemon as m
        _reset_speak_cache()
        fake_cfg = {
            'styles': [
                {'name': 'alpha', 'description': '', 'default_if_invalid': False},
                {'name': 'beta', 'description': '', 'default_if_invalid': False},
            ],
            'rate_cap': {'window_s': 60, 'max_yes_in_window': 1},
        }
        with patch.object(m, '_load_speak_config', return_value=fake_cfg):
            self.assertEqual(m._get_default_speak_style(), 'alpha')


# ==========================================================
# L39 vocab 损坏 → fallback default
# ==========================================================

class TestL39CorruptedVocabFallback(unittest.TestCase):
    """vocab 不是合法 JSON → loader 不崩, 返默认配置."""

    def test_corrupted_vocab(self):
        import jarvis_inner_thought_daemon as m
        # 临写 bad JSON 到 tmp 路径, 临 patch _SPEAK_CONFIG_PATH
        with tempfile.NamedTemporaryFile(
            'w', suffix='.json', delete=False, encoding='utf-8'
        ) as tf:
            tf.write('{not valid json at all,')
            bad_path = tf.name
        try:
            _reset_speak_cache()
            with patch.object(m, '_SPEAK_CONFIG_PATH', bad_path):
                cfg = m._load_speak_config()
            # 损坏 vocab → loader 应回 _SPEAK_DEFAULT_CONFIG (含 styles)
            self.assertIn('styles', cfg)
            self.assertGreaterEqual(len(cfg['styles']), 3)
        finally:
            try:
                os.remove(bad_path)
            except OSError:
                pass
            _reset_speak_cache()


# ==========================================================
# L40 _should_smooth_force_silent 走 vocab rate cap
# ==========================================================

class TestL40SmoothForceSilentUsesVocabRateCap(unittest.TestCase):
    """_should_smooth_force_silent 用 vocab rate cap (改 vocab 改判定)."""

    def test_vocab_drives_smoothing(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        import jarvis_inner_thought_daemon as m
        _reset_speak_cache()
        d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        d._recent_should_speak_yes_ts = []
        d._bg_log = lambda *a, **kw: None
        now = time.time()

        # 1) 默认 vocab (5min / 3): 3 个 yes 后 smooth 启动
        d._record_should_speak_yes(now - 240)
        d._record_should_speak_yes(now - 120)
        d._record_should_speak_yes(now - 60)
        self.assertTrue(d._should_smooth_force_silent(now))

        # 2) patch vocab 改宽松 cap (5min / 100) → 同样 3 个 yes 不应 smooth
        loose_cfg = {
            'styles': [{'name': 'silent_text', 'description': '',
                        'default_if_invalid': True}],
            'rate_cap': {'window_s': 300, 'max_yes_in_window': 100},
        }
        with patch.object(m, '_load_speak_config', return_value=loose_cfg):
            d._recent_should_speak_yes_ts = []
            d._record_should_speak_yes(now - 240)
            d._record_should_speak_yes(now - 120)
            d._record_should_speak_yes(now - 60)
            self.assertFalse(d._should_smooth_force_silent(now))


# ==========================================================
# L41 反向验证: _build_prompt 输出含 vocab-driven SPEAK_STYLE 行
# ==========================================================

class TestL41PromptUsesVocabSpeakStyleLine(unittest.TestCase):
    """_build_prompt 输出含 _build_speak_style_prompt_line 真内容
    (反向验证主链路 prompt → vocab 联通, 改 vocab 改 prompt)."""

    def _make_daemon(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        d._thoughts = []
        d._lock = MagicMock()
        d._next_attention_focus = ''
        d._recent_should_speak_yes_ts = []
        d._bg_log = lambda *a, **kw: None
        d.build_lifetime_block = lambda mode='mini': ''
        d.concerns_ledger = None
        d.nerve = None
        d.relational_state = None
        d._tick_count = 0
        d._thought_count = 0
        d._today_thought_count = 0
        d._today_date = ''
        d._last_category_ts = {}
        d._llm_fail_count = 0
        d._cooldown_skip_count = 0
        d._tick_origin_stats = {}
        return d

    def test_prompt_contains_vocab_speak_style_line(self):
        _reset_speak_cache()
        daemon = self._make_daemon()
        evidence = {
            'sir_state': 'active', 'idle_seconds': 0, 'hour': 14,
            'swm_events': [], 'stm': [], 'recent_thoughts': [],
            'concerns': [], 'recent_jarvis_actions': [],
        }
        prompt_system, _prompt_user = daemon._build_prompt(
            sir_state='active', evidence=evidence,
            free_categories=['A', 'B', 'C', 'D', 'E'],
        )
        # SPEAK_STYLE schema 行在 system prompt (不在 user), 含 vocab style 名
        self.assertIn('<SPEAK_STYLE>', prompt_system)
        self.assertIn('silent_text', prompt_system)
        self.assertIn('voice', prompt_system)
        self.assertIn('visual_pulse', prompt_system)
        # vocab description 也注入 (subtitle = silent_text 的描述)
        self.assertIn('subtitle', prompt_system.lower())


if __name__ == '__main__':
    unittest.main(verbosity=2)
