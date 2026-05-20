# -*- coding: utf-8 -*-
"""[β.5.35-C/D / 2026-05-20] offer_help 触发源重设 + struggle vocab regression test.

Sir 2026-05-20 10:46 实测 BUG 2: offer_help 触发源不对.
老逻辑: ProactiveShield 看屏幕 error keyword → offer_help (Sir 没在挣扎也误推).
新逻辑 (Sir 决):
  - **offer_help 真触发源** = Sir 嘴里说困难 (struggle vocab 命中) [β.5.35-C]
  - 屏幕 frustration 信号 → 改 screen_tease (调皮观察, 不主动给方案)
  - struggle vocab 持久化 + CLI + L7 reflector [β.5.35-D 准则 6]

doc: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import MagicMock, patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRUGGLE_VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'sir_struggle_vocab.json')
STRUGGLE_CLI_PATH = os.path.join(ROOT, 'scripts', 'struggle_vocab_dump.py')


class TestBeta535CStruggleVocabFile(unittest.TestCase):
    """sir_struggle_vocab.json schema + seed phrases."""

    def test_vocab_json_exists(self):
        self.assertTrue(os.path.exists(STRUGGLE_VOCAB_PATH),
            f'sir_struggle_vocab.json 必须存在: {STRUGGLE_VOCAB_PATH}')

    def test_vocab_schema(self):
        with open(STRUGGLE_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for k in ('_meta', 'phrases', 'review_queue', 'rejected_history'):
            self.assertIn(k, data)
        self.assertEqual(data['_meta']['schema_version'], 1)

    def test_seed_phrases_present(self):
        with open(STRUGGLE_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        active_ids = {p['id'] for p in data['phrases']
                      if p.get('state', 'active') == 'active'}
        for seed in ('stuck_zh', 'stuck_en', 'frustrated_zh',
                     'expletive_zh', 'expletive_en', 'asking_how_zh'):
            self.assertIn(seed, active_ids, f'seed phrase {seed} 必须存在 (β.5.35-C)')

    def test_severity_values_valid(self):
        with open(STRUGGLE_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for p in data['phrases']:
            self.assertIn(p.get('severity', 'medium'),
                ('low', 'medium', 'high'),
                f'phrase {p.get("id")} severity 必须是 low/medium/high')


class TestBeta535CStruggleVocabCLI(unittest.TestCase):
    """scripts/struggle_vocab_dump.py CLI."""

    def test_cli_exists(self):
        self.assertTrue(os.path.exists(STRUGGLE_CLI_PATH))

    def test_cli_list_runs(self):
        r = subprocess.run(
            [sys.executable, STRUGGLE_CLI_PATH, '--active-only'],
            capture_output=True, text=True, cwd=ROOT, timeout=30,
            encoding='utf-8', errors='replace',
        )
        self.assertEqual(r.returncode, 0, f'CLI fail: {r.stderr}')
        self.assertIn('phrase', (r.stdout or '').lower())

    def test_cli_add_remove_pattern_roundtrip(self):
        fixture_pat = 'β.5.35C_test_fixture_pattern_xyz'
        phrase_id = 'asking_how_zh'

        r1 = subprocess.run(
            [sys.executable, STRUGGLE_CLI_PATH, '--add-pattern', phrase_id, fixture_pat],
            capture_output=True, text=True, cwd=ROOT, timeout=30,
            encoding='utf-8', errors='replace',
        )
        try:
            self.assertEqual(r1.returncode, 0)
            with open(STRUGGLE_VOCAB_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            phrase = next((p for p in data['phrases'] if p['id'] == phrase_id), None)
            self.assertIsNotNone(phrase)
            self.assertIn(fixture_pat, phrase['patterns'])
        finally:
            subprocess.run(
                [sys.executable, STRUGGLE_CLI_PATH, '--remove-pattern', phrase_id, fixture_pat],
                capture_output=True, text=True, cwd=ROOT, timeout=30,
                encoding='utf-8', errors='replace',
            )


class TestBeta535CVoiceThreadDetector(unittest.TestCase):
    """VoiceListenThread._detect_sir_struggle 行为."""

    def _make_voice_thread(self):
        """构造 minimal VoiceListenThread (skip super().__init__ side effects)."""
        from jarvis_worker import VoiceListenThread
        # QThread 不能 object.__new__ — 用 cls.__new__(cls)
        vt = VoiceListenThread.__new__(VoiceListenThread)
        vt._struggle_vocab_path = STRUGGLE_VOCAB_PATH
        vt._struggle_vocab_cache = None
        vt._struggle_vocab_mtime = 0.0
        vt.last_struggle_at = 0.0
        vt.last_struggle_phrase_id = ''
        vt.last_struggle_severity = ''
        vt.last_struggle_text = ''
        return vt

    def test_load_struggle_vocab_returns_active(self):
        vt = self._make_voice_thread()
        active = vt._load_struggle_vocab()
        self.assertIsInstance(active, list)
        self.assertGreater(len(active), 0, '至少 1 个 active phrase')

    def test_detect_chinese_stuck_hit(self):
        vt = self._make_voice_thread()
        hit = vt._detect_sir_struggle('我卡住了, 怎么搞')
        self.assertTrue(hit)
        # severity high (stuck_zh + asking_how_zh 同时命中, stuck=high 应胜)
        self.assertEqual(vt.last_struggle_severity, 'high')
        self.assertIn(vt.last_struggle_phrase_id, ('stuck_zh', 'asking_how_zh', 'frustrated_zh'))

    def test_detect_english_stuck_hit(self):
        vt = self._make_voice_thread()
        hit = vt._detect_sir_struggle('I am stuck on this')
        self.assertTrue(hit)
        self.assertEqual(vt.last_struggle_severity, 'high')

    def test_detect_low_severity_word_no_high_override(self):
        vt = self._make_voice_thread()
        hit = vt._detect_sir_struggle('how do i fix this')
        self.assertTrue(hit)
        # 命中 asking_how_en (medium)
        self.assertEqual(vt.last_struggle_severity, 'medium')

    def test_detect_no_hit(self):
        vt = self._make_voice_thread()
        hit = vt._detect_sir_struggle('hello world')
        self.assertFalse(hit)
        self.assertEqual(vt.last_struggle_at, 0.0)

    def test_detect_empty_cmd_safe(self):
        vt = self._make_voice_thread()
        self.assertFalse(vt._detect_sir_struggle(''))
        self.assertFalse(vt._detect_sir_struggle(None))
        self.assertFalse(vt._detect_sir_struggle('  '))


class TestBeta535CConductorStrugglePath(unittest.TestCase):
    """jarvis_conductor.py _check_path_a struggle signal 优先路径."""

    def _get_src(self):
        with open(os.path.join(ROOT, 'jarvis_conductor.py'), 'r', encoding='utf-8') as f:
            return f.read()

    def test_marker_present(self):
        src = self._get_src()
        self.assertIn('β.5.35-C', src,
            'β.5.35-C marker 必须在 jarvis_conductor.py')

    def test_sir_struggle_priority_path_exists(self):
        """_check_path_a 必须含 SirStruggleVocab 优先路径 (在 shield_alert 之前)."""
        src = self._get_src()
        idx = src.find('def _check_path_a')
        struggle_idx = src.find('SirStruggleVocab', idx)
        shield_idx = src.find('shield_alert.get(\'active\') and self._daily_action_count', idx)
        self.assertGreater(struggle_idx, 0,
            '_check_path_a 必须含 SirStruggleVocab 路径')
        self.assertLess(struggle_idx, shield_idx,
            'SirStruggleVocab 必须在 shield_alert 之前 (优先级)')

    def test_shield_alert_now_screen_tease(self):
        """shield_alert path 必须改 screen_tease (而非 offer_help)."""
        src = self._get_src()
        idx = src.find('def _check_path_a')
        end = src.find('def _dispatch_path_a', idx)
        region = src[idx:end]
        # path_a shield branch 必须是 nudge_type='screen_tease'
        self.assertIn("'nudge_type': 'screen_tease'", region,
            'shield_alert path 必须 nudge_type=screen_tease (β.5.35-C 重排)')
        # 同 region 内不能再有 nudge_type='offer_help' from shield path
        # (struggle path 的 nudge_type='offer_help' 是合法的, 但不在 shield branch)

    def test_struggle_context_propagated_to_nudge_context(self):
        """_dispatch_path_a 必须透传 struggle_phrase_id / severity / text 到 nudge_context."""
        src = self._get_src()
        idx = src.find('def _dispatch_path_a')
        # _dispatch_path_a 完整 ~ 10kb, 扩 region 到下一 def
        next_def = src.find('\n    def ', idx + 20)
        end = next_def if next_def > 0 else (idx + 12000)
        region = src[idx:end]
        for kw in ('struggle_phrase_id', 'struggle_severity', 'struggle_text', 'screen_category'):
            self.assertIn(kw, region,
                f'_dispatch_path_a 必须透传 {kw} 给 nudge_context')


class TestBeta535COfferHelpDirectiveRewrite(unittest.TestCase):
    """jarvis_chat_bypass.py offer_help directive evidence-driven 重写."""

    def _get_src(self):
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'), 'r', encoding='utf-8') as f:
            return f.read()

    def test_offer_help_directive_uses_struggle_evidence(self):
        src = self._get_src()
        idx = src.find('"offer_help": (')
        end = src.find('"suggest_break"', idx)
        directive = src[idx:end]
        # 必须引用 struggle context fields
        for kw in ('struggle_phrase_id', 'struggle_severity', 'struggle_text'):
            self.assertIn(kw, directive,
                f'offer_help directive 必须 evidence-reference {kw}')

    def test_offer_help_no_more_hard_phrasing(self):
        """旧 directive `Sir seems to be stuck on an error or debugging issue` 必须删除."""
        src = self._get_src()
        idx = src.find('"offer_help": (')
        end = src.find('"suggest_break"', idx)
        directive = src[idx:end]
        # β.5.35-C 重排, 不该再硬假设 "stuck on an error"
        self.assertNotIn('Sir seems to be stuck on an error or debugging issue', directive,
            'β.5.35-C 已重排 offer_help 触发源, 不再硬假设 "stuck on an error"')

    def test_offer_help_keeps_integrity_rule(self):
        """[INTEGRITY] 工具名禁令必须保留 (β.5.35-C 不动 BUG 3 规则)."""
        src = self._get_src()
        idx = src.find('"offer_help": (')
        end = src.find('"suggest_break"', idx)
        directive = src[idx:end]
        self.assertIn('INTEGRITY', directive,
            '[INTEGRITY] 工具名禁令必须保留 (β.5.36 BUG 3 修)')


if __name__ == '__main__':
    unittest.main()
