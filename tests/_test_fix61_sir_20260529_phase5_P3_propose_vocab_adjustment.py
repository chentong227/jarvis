# -*- coding: utf-8 -*-
"""[SOUL Phase 5 P3 / Sir 2026-05-29] propose_vocab_adjustment self-debug actionable.

设计文档: docs/JARVIS_DYNAMIC_MAP_AND_SELF_DEBUG_DESIGN.md Layer 5

P3 目标: 思考脑 self-debug 真闭环 — 看 [MY ARCHITECTURE] (P2) 知异常关联哪
  module+vocab → propose_vocab_adjustment → review queue → Sir 拍板 → 真修.
  复用 E5 红线 (protected_vocab_files 不改 INTEGRITY/safety) + F5 review.

真 case (Sir 日志): protocol/joke bloat → 思考脑 propose 调 auto_arbiter cap.

测试覆盖 (~9 testcase):
  红线 (3):
    - P3_1: _check_red_line_vocab_adjustment protected (integrity) 命中
    - P3_2: 正常 vocab (pacing) 不命中
    - P3_3: disabled red_line → 放行
  method (6):
    - P3_4: sal gate (<0.8 reject)
    - P3_5: parse fail (缺字段)
    - P3_6: 红线 reject (protected vocab → red_line_violated)
    - P3_7: 正常 propose → review queue 写 + vocab_adj_proposed
    - P3_8: _execute_actionable dispatcher
    - P3_9: review jsonl 内容正确 (vocab_file/key/value/status pending)
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


def _reset_red_lines_cache():
    import jarvis_inner_thought_daemon as m
    m._RED_LINES_VOCAB_CACHE['data'] = None
    m._RED_LINES_VOCAB_CACHE['mtime'] = 0.0
    m._RED_LINES_VOCAB_CACHE['checked_at'] = 0.0


def _make_thought(salience=0.85, thought='protocol bloat detected, tune cap'):
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id=f'th_{int(time.time() * 1000)}', ts=time.time(),
        ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S'),
        category='D', thought=thought, salience=salience,
        actionable='none', evidence_link='none',
    )


def _make_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    with patch.object(
        InnerThoughtDaemon, '_append_cold_start_record', return_value=None,
    ):
        return InnerThoughtDaemon(key_router=MagicMock())


class TestRedLineVocabAdjustment(unittest.TestCase):
    """P3_1-3: _check_red_line_vocab_adjustment."""

    def setUp(self):
        _reset_red_lines_cache()

    def test_P3_1_protected_integrity_hit(self):
        from jarvis_inner_thought_daemon import (
            _check_red_line_vocab_adjustment,
        )
        hit, pat = _check_red_line_vocab_adjustment(
            'claim_classify_vocab.json',
        )
        self.assertTrue(hit)
        self.assertEqual(pat, 'claim_classify')
        # commitment 也保护
        hit2, _ = _check_red_line_vocab_adjustment(
            'commitment_conditional_vocab.json',
        )
        self.assertTrue(hit2)

    def test_P3_2_normal_vocab_miss(self):
        from jarvis_inner_thought_daemon import (
            _check_red_line_vocab_adjustment,
        )
        hit, _ = _check_red_line_vocab_adjustment(
            'inner_thought_pacing_vocab.json',
        )
        self.assertFalse(hit)
        hit2, _ = _check_red_line_vocab_adjustment(
            'auto_arbiter_config.json',
        )
        self.assertFalse(hit2, "auto_arbiter 应可调 (非 protected)")

    def test_P3_3_disabled_red_line_passes(self):
        import jarvis_inner_thought_daemon as m
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as f:
            json.dump({
                'enabled': True,
                'red_lines': {
                    'protected_vocab_files': {
                        'enabled': False,
                        'blocked_patterns': ['claim_classify'],
                    },
                },
            }, f)
            tmp = f.name
        try:
            with patch.object(m, '_RED_LINES_VOCAB_PATH', tmp):
                _reset_red_lines_cache()
                hit, _ = m._check_red_line_vocab_adjustment(
                    'claim_classify_vocab.json',
                )
            self.assertFalse(hit, "P3_3 disabled 应放行")
        finally:
            os.unlink(tmp)
            _reset_red_lines_cache()


class TestProposeVocabAdjustment(unittest.TestCase):
    """P3_4-9: _do_propose_vocab_adjustment."""

    def setUp(self):
        _reset_red_lines_cache()
        self.tmp_review = tempfile.mktemp(suffix='_vocab_review.jsonl')
        import jarvis_inner_thought_daemon as m
        self._patcher = patch.object(
            m, '_VOCAB_ADJ_REVIEW_PATH', self.tmp_review,
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        try:
            if os.path.exists(self.tmp_review):
                os.unlink(self.tmp_review)
        except Exception:
            pass
        _reset_red_lines_cache()

    def test_P3_4_sal_gate(self):
        daemon = _make_daemon()
        thought = _make_thought(salience=0.5)
        ok, result = daemon._do_propose_vocab_adjustment(
            thought,
            'propose_vocab_adjustment:auto_arbiter_config.json:daily_cap:100',
        )
        self.assertFalse(ok)
        self.assertIn('sal', result)

    def test_P3_5_parse_fail(self):
        daemon = _make_daemon()
        thought = _make_thought(salience=0.85)
        ok, result = daemon._do_propose_vocab_adjustment(
            thought, 'propose_vocab_adjustment:onlyfile',  # 缺 key:value
        )
        self.assertFalse(ok)
        self.assertIn('parse_fail', result)

    def test_P3_6_red_line_reject(self):
        daemon = _make_daemon()
        thought = _make_thought(salience=0.85,
                                 thought='disable claim tracer for speed')
        ok, result = daemon._do_propose_vocab_adjustment(
            thought,
            'propose_vocab_adjustment:claim_classify_vocab.json:enabled:false',
        )
        self.assertFalse(ok)
        self.assertIn('red_line_violated', result)
        self.assertIn('protected_vocab', result)

    def test_P3_7_normal_propose_writes_review(self):
        daemon = _make_daemon()
        thought = _make_thought(salience=0.85)
        ok, result = daemon._do_propose_vocab_adjustment(
            thought,
            'propose_vocab_adjustment:auto_arbiter_config.json:daily_cap:100',
        )
        self.assertTrue(ok, f"P3_7 正常 propose 应成功, 实际 {result}")
        self.assertIn('vocab_adj_proposed', result)
        # review queue 写了
        self.assertTrue(os.path.exists(self.tmp_review))

    def test_P3_8_execute_actionable_dispatcher(self):
        daemon = _make_daemon()
        thought = _make_thought(salience=0.85,
                                 thought='auto_arbiter cap too low, tune it')
        thought.actionable = (
            'propose_vocab_adjustment:auto_arbiter_config.json:daily_cap:100'
        )
        thought.evidence_link = 'auto_arbiter'
        ok, result = daemon._execute_actionable(thought)
        self.assertTrue(ok, f"P3_8 dispatcher 应成功, 实际 {result}")
        self.assertIn('vocab_adj_proposed', result)

    def test_P3_9_review_jsonl_content(self):
        daemon = _make_daemon()
        thought = _make_thought(salience=0.9,
                                 thought='joke bloat, tune dedup threshold')
        daemon._do_propose_vocab_adjustment(
            thought,
            'propose_vocab_adjustment:relational_dedup.json:jaccard:0.4',
        )
        with open(self.tmp_review, 'r', encoding='utf-8') as f:
            entry = json.loads(f.readline())
        self.assertEqual(entry['vocab_file'], 'relational_dedup.json')
        self.assertEqual(entry['key_path'], 'jaccard')
        self.assertEqual(entry['proposed_value'], '0.4')
        self.assertEqual(entry['status'], 'pending')
        self.assertIn('bloat', entry['rationale'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
