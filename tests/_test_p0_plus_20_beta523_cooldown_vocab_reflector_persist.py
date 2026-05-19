# -*- coding: utf-8 -*-
"""[P0+20-β.5.23 / 2026-05-19] β.5.23 全集 testcase.

覆盖:
- β.5.23-A: cooldown vocab JSON + _load_cooldown_vocab + _get_cd + 5 call sites 替换
- β.5.23-B: ConcernFeedbackReflector L7 daemon (周期 LLM propose)

测试模式: 静态源码扫 marker + vocab json schema + runtime 行为.
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# ============================================================
# β.5.23-A: cooldown vocab JSON
# ============================================================

class TestBeta523ACooldownVocab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_proactive_care.py'))
        cls.vocab_path = os.path.join(ROOT, 'memory_pool',
                                        'proactive_care_cooldown_vocab.json')

    def test_marker(self):
        self.assertIn('β.5.23-A', self.src)

    def test_vocab_json_exists(self):
        self.assertTrue(os.path.exists(self.vocab_path))

    def test_vocab_has_all_critical_keys(self):
        with open(self.vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        cur = data.get('current') or {}
        for k in ('GLOBAL_NUDGE_COOLDOWN_S', 'PER_CONCERN_COOLDOWN_S',
                  'SILENT_GLOBAL_COOLDOWN_S', 'EXPLICIT_REJECT_COOLDOWN_S',
                  'WARMUP_SECONDS', 'NIGHT_CRITICAL_THRESHOLD'):
            self.assertIn(k, cur, f'vocab 必须有 {k}')

    def test_vocab_has_ranges(self):
        with open(self.vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('ranges', data, 'vocab 必须有 ranges 字段')

    def test_vocab_has_history_and_review_queue(self):
        with open(self.vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('history', data)
        self.assertIn('review_queue', data)

    def test_loader_function_exists(self):
        self.assertIn('def _load_cooldown_vocab', self.src,
            '必须有 _load_cooldown_vocab 函数')
        self.assertIn('def _get_cd', self.src,
            '必须有 _get_cd helper')

    def test_call_sites_use_get_cd(self):
        """5 个 call site 必须用 _get_cd, 不硬常量."""
        for kw in ('_get_cd(\'GLOBAL_NUDGE_COOLDOWN_S\'',
                   '_get_cd(\'PER_CONCERN_COOLDOWN_S\'',
                   '_get_cd(\'NIGHT_CRITICAL_THRESHOLD\'',
                   '_get_cd(\'SILENT_GLOBAL_COOLDOWN_S\'',
                   '_get_cd(\'WARMUP_SECONDS\'',
                   '_get_cd(\'EXPLICIT_REJECT_COOLDOWN_S\''):
            self.assertIn(kw, self.src,
                f'必须有 call site: {kw}')

    def test_cli_tool_exists(self):
        cli = os.path.join(ROOT, 'scripts', 'cooldown_vocab_dump.py')
        self.assertTrue(os.path.exists(cli),
            'cooldown_vocab_dump.py CLI 必须存在')


class TestBeta523ALoaderRuntime(unittest.TestCase):
    """runtime 测 vocab loader."""

    def test_get_cd_reads_vocab(self):
        from jarvis_proactive_care import _get_cd, _FALLBACK_GLOBAL_NUDGE_COOLDOWN_S
        v = _get_cd('GLOBAL_NUDGE_COOLDOWN_S', _FALLBACK_GLOBAL_NUDGE_COOLDOWN_S)
        # 应等 vocab 当前值
        self.assertEqual(v, 300.0,
            'vocab 应该返 300.0')

    def test_get_cd_falls_back_on_unknown_key(self):
        from jarvis_proactive_care import _get_cd
        v = _get_cd('NONEXISTENT_KEY_XYZ', 999.0)
        self.assertEqual(v, 999.0)


# ============================================================
# β.5.23-B: ConcernFeedbackReflector L7 daemon
# ============================================================

class TestBeta523BReflector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_concern_feedback_reflector.py'))
        cls.src_routing = _read(os.path.join(ROOT, 'jarvis_routing.py'))

    def test_marker(self):
        self.assertIn('β.5.23-B', self.src)

    def test_class_exists(self):
        self.assertIn('class ConcernFeedbackReflector', self.src)

    def test_has_reflect_once_method(self):
        self.assertIn('def reflect_once', self.src)

    def test_has_start_daemon(self):
        self.assertIn('def start_daemon', self.src)

    def test_uses_quick_classifier(self):
        self.assertIn('get_quick_classifier', self.src,
            'reflector 必须用 QuickClassifier (本地)')
        self.assertIn('prompt_raw', self.src,
            '必须用 QuickClassifier.prompt_raw (β.5.22-C 加的)')

    def test_writes_review_queue(self):
        """propose 必须写到 review_queue."""
        self.assertIn('review_queue', self.src)
        self.assertIn('_write_proposals', self.src)

    def test_singleton(self):
        self.assertIn('get_or_create_reflector', self.src)

    def test_started_by_companion_center(self):
        """CompanionCenter 必须启动 reflector daemon."""
        self.assertIn('get_or_create_reflector', self.src_routing,
            'jarvis_routing.py 必须 import reflector')
        self.assertIn('start_daemon', self.src_routing,
            'jarvis_routing.py 必须 start daemon')


class TestBeta523BReflectorRuntime(unittest.TestCase):
    """runtime 测 reflector 接口 (mock-based)."""

    def setUp(self):
        from jarvis_concerns import ConcernsLedger, Concern, STATE_ACTIVE
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.ledger = ConcernsLedger(
            persist_path=os.path.join(self.tmp, 'c.json'),
            review_path=os.path.join(self.tmp, 'r.json'),
        )
        self.ledger.register(Concern(
            id='sir_hydration_habit',
            what_i_watch='Sir hydration',
            why_i_care='health',
            severity=0.5,
            state=STATE_ACTIVE,
        ))

    def test_collect_stats_runs(self):
        from jarvis_concern_feedback_reflector import ConcernFeedbackReflector
        r = ConcernFeedbackReflector(ledger=self.ledger)
        stats = r._collect_stats()
        self.assertIn('n_active_concerns', stats)
        self.assertEqual(stats['n_active_concerns'], 1)
        self.assertIn('nudges_total_7d', stats)
        self.assertIn('rejects_7d', stats)

    def test_parse_proposals_handles_markdown(self):
        from jarvis_concern_feedback_reflector import ConcernFeedbackReflector
        r = ConcernFeedbackReflector(ledger=self.ledger)
        resp = '```json\n{"proposals": [{"key": "X", "current": 1, "proposed": 2}]}\n```'
        out = r._parse_proposals(resp)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['key'], 'X')


# ============================================================
# β.5.23 charter (Sir 设计哲学落地)
# ============================================================

class TestBeta523CharterSirDesign(unittest.TestCase):
    """Sir 01:36 'B 不交手动' + 准则 6 落地 charter."""

    def test_b_not_manual_cli_for_review_only(self):
        """CLI 应有 review subcommand 给 Sir 看, 不是逼 Sir 改阈值."""
        cli = _read(os.path.join(ROOT, 'scripts', 'cooldown_vocab_dump.py'))
        self.assertIn('cmd_review', cli,
            'CLI 必须有 review subcommand (Sir 看 L7 propose 不手调)')

    def test_l7_proposes_not_apply_directly(self):
        """reflector 必须 propose 到 review_queue, 不直接 apply current."""
        src = _read(os.path.join(ROOT, 'jarvis_concern_feedback_reflector.py'))
        # _write_proposals 写 review_queue 不写 current
        idx = src.find('def _write_proposals')
        self.assertGreater(idx, 0)
        snippet = src[idx:idx + 1500]
        self.assertIn('review_queue', snippet,
            'propose 必须写 review_queue')
        self.assertNotIn("data['current']", snippet,
            '不能直接改 current (要 Sir 拍板)')

    def test_fallback_to_module_const(self):
        """vocab json 丢失时, 应 fallback 到 module 常量."""
        src = _read(os.path.join(ROOT, 'jarvis_proactive_care.py'))
        self.assertIn('_FALLBACK_', src,
            '必须有 _FALLBACK_ 常量做兜底')


if __name__ == '__main__':
    unittest.main(verbosity=2)
