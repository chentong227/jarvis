# -*- coding: utf-8 -*-
"""[fix44 / Sir 2026-05-28 19:47 真痛 P0] LLM semantic dedup 治 inside_joke / protocol bloat.

Sir 真痛 (19:20 monitor warn):
  🚨 inside_joke active count = 30 (>= warn 25)
  🚨 protocol active count = 29 (>= warn 25)
  🚨 thread dedup_miss jaccard = 0.50

诊断: 30 active jokes 内 9 个 sleep 主题同义换皮 ('theoretical rest' /
  'conceptual rest' / 'Decorative slumber' / 'Productive somnambulism' /
  'industrious unconsciousness' / 'industrious insomnia' / ...). 字面
  jaccard < 0.6 全部漏拦 pre-activate dedup. protocols 同样模式 ('concise
  direct language' 4 个变体). 25/30 来自 inner_thought source.

根因: `_pre_activate_dedup_check` 用 lexical jaccard 阈值 0.6, 同义换皮
  jaccard ≈ 0.0-0.33 全部 < 0.6 → 全部 activate. monitor `_do_monitor_scan`
  dedup_miss 同样 jaccard, 看不到 semantic dup.

治本 (准则 6 拒绝硬编码 + 信任 LLM):
  - DEFAULT_RUNTIME 加 semantic_dedup_* 7 keys
  - 新方法 `_semantic_dedup_check(kind, text_a, text_b) -> (is_dup, conf, reason)`
    内含 LRU cache + LLM call + 故障开放
  - `_pre_activate_dedup_check`: jaccard ∈ [low_kind, 0.6) 灰色带 → call LLM
  - `_do_monitor_scan` dedup_miss: 同样 grey-band, LLM cost cap = 30 pair/tick

10 testcase 覆盖.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_arbiter():
    """构造 AutoArbiterDaemon stub (skip __init__ 减少 IO)."""
    from jarvis_auto_arbiter import AutoArbiterDaemon
    from collections import OrderedDict
    d = AutoArbiterDaemon.__new__(AutoArbiterDaemon)
    d._calibration = {}
    d._semantic_dedup_cache = OrderedDict()
    d._semantic_dedup_llm_calls = 0
    d._semantic_dedup_llm_hits = 0
    d._semantic_dedup_cache_hits = 0
    d._llm_call_count = 0
    d._llm_fail_count = 0
    d._last_monitor_warning_ts = {}
    d.relational = None
    return d


def _llm_response(decision: str, conf: float, reason: str) -> str:
    return (
        f'<DECISION>{decision}</DECISION>\n'
        f'<CONFIDENCE>{conf}</CONFIDENCE>\n'
        f'<REASON>{reason}</REASON>'
    )


# ==========================================================================
# T1: _semantic_dedup_check — LLM DUP + conf >= threshold → is_dup=True
# ==========================================================================
class TestT1SemanticDedupCheckDup(unittest.TestCase):
    def test_dup_high_conf_returns_true(self):
        d = _make_arbiter()
        with patch.object(d, '_call_llm',
                          return_value=_llm_response('DUP', 0.85,
                                                      'synonym swap')) as mlc:
            is_dup, conf, reason = d._semantic_dedup_check(
                'inside_joke', 'theoretical rest', 'conceptual rest'
            )
        self.assertTrue(is_dup)
        self.assertAlmostEqual(conf, 0.85, places=2)
        self.assertIn('llm_dup', reason)
        self.assertEqual(mlc.call_count, 1)
        self.assertEqual(d._semantic_dedup_llm_calls, 1)
        self.assertEqual(d._semantic_dedup_llm_hits, 1)

    def test_unique_decision_returns_false(self):
        d = _make_arbiter()
        with patch.object(d, '_call_llm',
                          return_value=_llm_response('UNIQUE', 0.90,
                                                      'different stage')):
            is_dup, conf, _ = d._semantic_dedup_check(
                'thread', 'exam pending', 'exam results'
            )
        self.assertFalse(is_dup)
        self.assertAlmostEqual(conf, 0.90, places=2)


# ==========================================================================
# T2: _semantic_dedup_check — LLM DUP 但 conf < threshold (0.70) → not dup
# ==========================================================================
class TestT2LowConfDupNotTrusted(unittest.TestCase):
    def test_dup_low_conf_returns_false(self):
        d = _make_arbiter()
        with patch.object(d, '_call_llm',
                          return_value=_llm_response('DUP', 0.55,
                                                      'maybe similar')):
            is_dup, conf, reason = d._semantic_dedup_check(
                'protocol', 'A', 'B'
            )
        self.assertFalse(is_dup)
        self.assertAlmostEqual(conf, 0.55, places=2)
        self.assertEqual(d._semantic_dedup_llm_hits, 0)


# ==========================================================================
# T3: LRU cache — 第二次 call same pair 不调 LLM
# ==========================================================================
class TestT3CacheHit(unittest.TestCase):
    def test_cache_hit_avoids_llm_recall(self):
        d = _make_arbiter()
        with patch.object(d, '_call_llm',
                          return_value=_llm_response('DUP', 0.90,
                                                      'same idea')) as mlc:
            r1 = d._semantic_dedup_check('inside_joke', 'foo bar', 'bar foo')
            r2 = d._semantic_dedup_check('inside_joke', 'bar foo', 'foo bar')
        self.assertEqual(r1, r2)
        self.assertEqual(mlc.call_count, 1)  # 只调一次 (cache + key 排序)
        self.assertEqual(d._semantic_dedup_cache_hits, 1)


# ==========================================================================
# T4: 故障开放 — LLM 返空 / parse 失败 → (False, 0.0, ...)
# ==========================================================================
class TestT4FailOpen(unittest.TestCase):
    def test_empty_llm_returns_false(self):
        d = _make_arbiter()
        with patch.object(d, '_call_llm', return_value=''):
            is_dup, conf, reason = d._semantic_dedup_check(
                'inside_joke', 'x', 'y'
            )
        self.assertFalse(is_dup)
        self.assertEqual(conf, 0.0)
        self.assertIn('llm_empty', reason)

    def test_parse_fail_returns_false(self):
        d = _make_arbiter()
        with patch.object(d, '_call_llm', return_value='garbage no tags'):
            is_dup, _, reason = d._semantic_dedup_check('protocol', 'a', 'b')
        self.assertFalse(is_dup)
        self.assertIn('parse_fail', reason)

    def test_llm_exception_returns_false(self):
        d = _make_arbiter()
        with patch.object(d, '_call_llm', side_effect=RuntimeError('boom')):
            is_dup, _, reason = d._semantic_dedup_check('thread', 'a', 'b')
        self.assertFalse(is_dup)
        self.assertIn('llm_exc', reason)


# ==========================================================================
# T5: disabled — semantic_dedup_enabled=0 直接 return (不调 LLM)
# ==========================================================================
class TestT5DisabledSkipsLlm(unittest.TestCase):
    def test_disabled_no_llm_call(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        d = _make_arbiter()
        d._calibration = {'runtime': {'semantic_dedup_enabled': 0}}
        with patch.object(d, '_call_llm', return_value='') as mlc:
            is_dup, _, reason = d._semantic_dedup_check(
                'inside_joke', 'theoretical rest', 'conceptual rest'
            )
        self.assertFalse(is_dup)
        self.assertIn('semantic_disabled', reason)
        self.assertEqual(mlc.call_count, 0)


# ==========================================================================
# T6 / T7: _pre_activate_dedup_check — jaccard ≥ high 硬拒 (no LLM)
#                                     + jaccard < low 放行 (no LLM)
# ==========================================================================
class TestT6T7PreActivateBoundary(unittest.TestCase):
    def _setup(self, active_phrase: str):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        d = _make_arbiter()
        # relational mock with inside_jokes
        rel = MagicMock()
        joke = MagicMock()
        joke.id = 'joke_existing_1'
        joke.phrase = active_phrase
        joke.state = 'active'
        rel.inside_jokes = {'joke_existing_1': joke}
        d.relational = rel
        return d

    def test_t6_jaccard_high_hard_reject_no_llm(self):
        """jaccard ≥ 0.6 (high) → 硬拒, 不调 LLM."""
        d = self._setup('theoretical rest pattern')
        cand = MagicMock()
        cand.id = 'joke_cand'
        cand.phrase = 'theoretical rest pattern habit'  # jaccard ≈ 4/5 = 0.8
        with patch.object(d, '_call_llm') as mlc:
            ok, reason = d._pre_activate_dedup_check('inside_joke', cand)
        self.assertFalse(ok)
        self.assertEqual(mlc.call_count, 0)  # 没调 LLM (jaccard 已 ≥ high)
        # 注意 12+ char substring 也命中 — 验证拦截即可

    def test_t7_jaccard_below_low_passes_no_llm(self):
        """jaccard < low (joke=0.15) → 放行, 不调 LLM."""
        d = self._setup('alpha beta gamma delta')
        cand = MagicMock()
        cand.id = 'joke_cand'
        cand.phrase = 'epsilon zeta eta theta iota'  # jaccard = 0
        with patch.object(d, '_call_llm') as mlc:
            ok, reason = d._pre_activate_dedup_check('inside_joke', cand)
        self.assertTrue(ok)
        self.assertEqual(mlc.call_count, 0)


# ==========================================================================
# T8 / T9: 灰色带 (low ≤ jaccard < high) → LLM 判
# ==========================================================================
class TestT8T9GreyBandLlm(unittest.TestCase):
    def _setup(self):
        d = _make_arbiter()
        rel = MagicMock()
        joke = MagicMock()
        joke.id = 'joke_ex'
        joke.phrase = 'theoretical rest'  # jaccard 与 candidate ~ 0.33
        joke.state = 'active'
        rel.inside_jokes = {'joke_ex': joke}
        d.relational = rel
        return d

    def test_t8_grey_band_llm_dup_rejects(self):
        """灰色带 + LLM DUP → 拒."""
        d = self._setup()
        cand = MagicMock()
        cand.id = 'joke_cand'
        cand.phrase = 'conceptual rest'  # jaccard = 1/3 ≈ 0.33 ∈ [0.15, 0.6)
        with patch.object(d, '_call_llm',
                          return_value=_llm_response('DUP', 0.88,
                                                      'synonym swap')) as mlc:
            ok, reason = d._pre_activate_dedup_check('inside_joke', cand)
        self.assertFalse(ok)
        self.assertEqual(mlc.call_count, 1)
        self.assertIn('semantic_dup', reason)
        self.assertIn('0.88', reason)  # conf

    def test_t9_grey_band_llm_unique_passes(self):
        """灰色带 + LLM UNIQUE → 放行."""
        d = self._setup()
        cand = MagicMock()
        cand.id = 'joke_cand'
        cand.phrase = 'visual rest'  # jaccard = 1/3 灰色带, 但语义不同
        with patch.object(d, '_call_llm',
                          return_value=_llm_response('UNIQUE', 0.85,
                                                      'eye rest different')) as mlc:
            ok, reason = d._pre_activate_dedup_check('inside_joke', cand)
        self.assertTrue(ok)
        self.assertEqual(mlc.call_count, 1)


# ==========================================================================
# T10: source marker — fix44 anchor 注释在 source
# ==========================================================================
class TestT10SourceMarker(unittest.TestCase):
    def test_anchor_in_source(self):
        with open(os.path.join(ROOT, 'jarvis_auto_arbiter.py'),
                  'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('Sir 2026-05-28 19:47 fix44', src,
                      'source 必须含 fix44 anchor 注释')
        self.assertIn('_semantic_dedup_check', src,
                      'source 必须含 _semantic_dedup_check 方法')
        self.assertIn("'semantic_dedup_enabled'", src,
                      'DEFAULT_RUNTIME 必须含 semantic_dedup_enabled key')
        self.assertIn("'semantic_dedup_jaccard_low_joke'", src,
                      'DEFAULT_RUNTIME 必须含 joke kind-specific low key')


if __name__ == '__main__':
    unittest.main(verbosity=2)
