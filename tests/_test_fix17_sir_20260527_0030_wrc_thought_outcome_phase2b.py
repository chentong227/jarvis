# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 00:30] Phase 2B 后半 — WRC 接 thought.outcome 自适应

Sir 真痛 (design doc §2.B 后半):
> "thought_outcome field 已写, 但没人看. WRC 7d 反思 → LLM propose
>  surface_to_sir_vocab 阈值调 进 review queue. Sir dashboard 一键拍板."

测试覆盖 (准则 4 testing discipline):
  1. WeeklyInsight dataclass 加 5 新 field, 老 record load 兼容
  2. _collect_thought_outcome_stats: 读 inner_thoughts.jsonl 真返 schema
  3. _collect_thought_outcome_stats: 文件不存在 → 返 {'total': 0}
  4. _load_surface_vocab: 真读 + fail-safe
  5. _llm_propose_vocab_tune: mock LLM 返合规 → 真返 dict + clamp 安全范围
  6. _llm_propose_vocab_tune: mock LLM 返 'no_tune' → 返 {}
  7. _llm_propose_vocab_tune: mock LLM 返 conf<0.4 → 返 {} (signal weak)
  8. _do_inner_thought_outcome_consolidation: thought 不足 → skip
  9. _do_inner_thought_outcome_consolidation: 完整跑通 → 真写 insight
 10. _maybe_fire: Sunday 03:xx 真 fire 两条 path (一条 fail 不阻另一条)
 11. WeeklyInsight load_persist: 老 record (无新 fields) 真 load OK
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from dataclasses import asdict
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================
# 测试隔离: 每个 test 用 tmpdir 防污染真 prod
# ==========================================================

class TestPhase2BWRCThoughtOutcome(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='wrc_p2b_')
        self.thoughts_path = os.path.join(self.tmpdir, 'inner_thoughts.jsonl')
        self.vocab_path = os.path.join(self.tmpdir, 'surface_vocab.json')
        self.insights_path = os.path.join(self.tmpdir,
                                            'long_term_insights.jsonl')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ----- helpers -----
    def _make_consolidator(self):
        """造 WRC 实例 + 隔离所有 path."""
        from jarvis_weekly_reflection_consolidator import (
            WeeklyReflectionConsolidator,
        )
        c = WeeklyReflectionConsolidator()
        c.INNER_THOUGHT_PERSIST_PATH = self.thoughts_path
        c.SURFACE_VOCAB_PATH = self.vocab_path
        c.PERSIST_PATH = self.insights_path
        return c

    def _write_thoughts(self, items: list):
        """写 inner_thoughts.jsonl 测试 fixture."""
        with open(self.thoughts_path, 'w', encoding='utf-8') as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + '\n')

    def _make_thought(self, cat: str = 'C', outcome: str = 'pending',
                       salience: float = 0.7, age_days: float = 1):
        """generate 1 thought fixture."""
        return {
            'id': f'thought_test_{cat}_{outcome}_{age_days}',
            'ts': time.time() - age_days * 86400,
            'ts_iso': '',
            'category': cat,
            'thought': f'test {cat} {outcome}',
            'salience': salience,
            'actionable': 'none',
            'outcome': outcome,
        }

    # ==========================================================
    # 1. dataclass 新 field
    # ==========================================================

    def test_01_weekly_insight_has_new_fields(self):
        from jarvis_weekly_reflection_consolidator import WeeklyInsight
        ins = WeeklyInsight(
            id='x', ts=0, ts_iso='', week_range_iso='',
            pattern_summary='', suggested_action='', evidence_count=0,
            evidence_excerpts=[], confidence=0.5,
        )
        for k in ('insight_type', 'target_vocab_path', 'target_field',
                  'proposed_old_value', 'proposed_new_value'):
            self.assertTrue(hasattr(ins, k), f'missing field {k}')
        # default
        self.assertEqual(ins.insight_type, 'self_reflection_pattern')
        self.assertEqual(ins.target_field, '')

    # ==========================================================
    # 2-3. _collect_thought_outcome_stats
    # ==========================================================

    def test_02_collect_stats_returns_full_schema(self):
        thoughts = [
            self._make_thought('A', 'pending', 0.5),
            self._make_thought('A', 'sir_engaged', 0.8),
            self._make_thought('B', 'sir_silenced', 0.7),
            self._make_thought('C', 'sir_engaged', 0.9),
            self._make_thought('C', 'sir_rejected', 0.6),
        ]
        self._write_thoughts(thoughts)
        c = self._make_consolidator()
        stats = c._collect_thought_outcome_stats()
        self.assertEqual(stats['total'], 5)
        self.assertIn('outcomes', stats)
        self.assertEqual(stats['outcomes']['pending'], 1)
        self.assertEqual(stats['outcomes']['sir_engaged'], 2)
        self.assertEqual(stats['outcomes']['sir_silenced'], 1)
        self.assertEqual(stats['outcomes']['sir_rejected'], 1)
        self.assertIn('by_category', stats)
        self.assertEqual(stats['by_category']['A']['total'], 2)
        self.assertEqual(stats['by_category']['C']['sir_engaged'], 1)
        self.assertGreater(stats['by_category']['A']['avg_sal'], 0)

    def test_03_collect_stats_no_file_returns_zero(self):
        c = self._make_consolidator()
        c.INNER_THOUGHT_PERSIST_PATH = '/nonexistent/file.jsonl'
        stats = c._collect_thought_outcome_stats()
        self.assertEqual(stats, {'total': 0})

    def test_04_collect_stats_skips_old_thoughts(self):
        """7d 外的 thought 不算 (cutoff)."""
        thoughts = [
            self._make_thought('A', 'sir_engaged', 0.8, age_days=10),
            self._make_thought('A', 'sir_engaged', 0.8, age_days=1),
        ]
        self._write_thoughts(thoughts)
        c = self._make_consolidator()
        stats = c._collect_thought_outcome_stats()
        self.assertEqual(stats['total'], 1)

    # ==========================================================
    # 4. _load_surface_vocab
    # ==========================================================

    def test_05_load_surface_vocab_reads_json(self):
        with open(self.vocab_path, 'w', encoding='utf-8') as f:
            json.dump({'salience_threshold': 0.65, 'max_per_hour': 8}, f)
        c = self._make_consolidator()
        vocab = c._load_surface_vocab()
        self.assertEqual(vocab['salience_threshold'], 0.65)
        self.assertEqual(vocab['max_per_hour'], 8)

    def test_06_load_surface_vocab_missing_returns_empty(self):
        c = self._make_consolidator()
        c.SURFACE_VOCAB_PATH = '/nonexistent/file.json'
        self.assertEqual(c._load_surface_vocab(), {})

    # ==========================================================
    # 5-7. _llm_propose_vocab_tune (mock LLM)
    # ==========================================================

    def _mock_llm_reflector(self, raw_text: str):
        """patch LlmReflector + KeyRouter 防真 LLM call."""
        mock_reflector = MagicMock()
        mock_reflector.reflect.return_value = {
            'success': True, 'raw_text': raw_text,
        }
        return patch(
            'jarvis_llm_reflector.LlmReflector',
            return_value=mock_reflector,
        )

    def test_07_propose_tune_valid_response(self):
        c = self._make_consolidator()
        stats = {
            'total': 50,
            'outcomes': {'pending': 10, 'sir_engaged': 30,
                         'sir_silenced': 5, 'sir_rejected': 5},
            'by_category': {
                'A': {'total': 20, 'sir_engaged': 12, 'sir_silenced': 4,
                      'sir_rejected': 2, 'avg_sal': 0.7},
                'C': {'total': 30, 'sir_engaged': 18, 'sir_silenced': 6,
                      'sir_rejected': 3, 'avg_sal': 0.65},
            },
        }
        vocab = {'salience_threshold': 0.7, 'cooldown_global_s': 120,
                 'max_per_hour': 6}
        raw = (
            "<PATTERN_SUMMARY>Sir engages with 60% of thoughts</PATTERN_SUMMARY>\n"
            "<SUGGESTED_ACTION>Lower threshold to welcome more chatter</SUGGESTED_ACTION>\n"
            "<TARGET_FIELD>salience_threshold</TARGET_FIELD>\n"
            "<OLD_VALUE>0.7</OLD_VALUE>\n"
            "<NEW_VALUE>0.65</NEW_VALUE>\n"
            "<CONFIDENCE>0.8</CONFIDENCE>\n"
        )
        with self._mock_llm_reflector(raw):
            tune = c._llm_propose_vocab_tune(stats, vocab)
        self.assertTrue(tune)
        self.assertEqual(tune['target_field'], 'salience_threshold')
        self.assertEqual(tune['new_value'], 0.65)
        self.assertGreaterEqual(tune['confidence'], 0.4)

    def test_08_propose_tune_no_tune_returns_empty(self):
        c = self._make_consolidator()
        raw = (
            "<PATTERN_SUMMARY>Pending dominant</PATTERN_SUMMARY>\n"
            "<SUGGESTED_ACTION>Wait more weeks</SUGGESTED_ACTION>\n"
            "<TARGET_FIELD>no_tune</TARGET_FIELD>\n"
            "<OLD_VALUE>0.7</OLD_VALUE>\n"
            "<NEW_VALUE>0.7</NEW_VALUE>\n"
            "<CONFIDENCE>0.0</CONFIDENCE>\n"
        )
        with self._mock_llm_reflector(raw):
            tune = c._llm_propose_vocab_tune(
                {'total': 50, 'outcomes': {}, 'by_category': {}}, {},
            )
        self.assertEqual(tune, {})

    def test_09_propose_tune_low_conf_returns_empty(self):
        c = self._make_consolidator()
        raw = (
            "<PATTERN_SUMMARY>weak signal</PATTERN_SUMMARY>\n"
            "<SUGGESTED_ACTION>maybe lower</SUGGESTED_ACTION>\n"
            "<TARGET_FIELD>salience_threshold</TARGET_FIELD>\n"
            "<OLD_VALUE>0.7</OLD_VALUE>\n"
            "<NEW_VALUE>0.6</NEW_VALUE>\n"
            "<CONFIDENCE>0.3</CONFIDENCE>\n"
        )
        with self._mock_llm_reflector(raw):
            tune = c._llm_propose_vocab_tune(
                {'total': 50, 'outcomes': {}, 'by_category': {}}, {},
            )
        self.assertEqual(tune, {})

    def test_10_propose_tune_clamps_unsafe_value(self):
        """LLM 提议越界值 → clamp 到安全范围."""
        c = self._make_consolidator()
        raw = (
            "<PATTERN_SUMMARY>Sir rejects everything</PATTERN_SUMMARY>\n"
            "<SUGGESTED_ACTION>Raise threshold</SUGGESTED_ACTION>\n"
            "<TARGET_FIELD>salience_threshold</TARGET_FIELD>\n"
            "<OLD_VALUE>0.7</OLD_VALUE>\n"
            "<NEW_VALUE>1.5</NEW_VALUE>\n"  # 越界 (max 0.95)
            "<CONFIDENCE>0.9</CONFIDENCE>\n"
        )
        with self._mock_llm_reflector(raw):
            tune = c._llm_propose_vocab_tune(
                {'total': 50, 'outcomes': {}, 'by_category': {}}, {},
            )
        self.assertTrue(tune)
        self.assertLessEqual(tune['new_value'], 0.95)

    # ==========================================================
    # 8-9. _do_inner_thought_outcome_consolidation
    # ==========================================================

    def test_11_consolidation_skips_low_thought_count(self):
        # 只 5 个 thought < MIN_THOUGHT_COUNT_FOR_TUNE=20
        thoughts = [self._make_thought('A', 'sir_engaged', 0.8)
                    for _ in range(5)]
        self._write_thoughts(thoughts)
        c = self._make_consolidator()
        c._do_inner_thought_outcome_consolidation('2026-W21')
        # 没 insight 写入
        self.assertFalse(os.path.exists(self.insights_path))

    def test_12_consolidation_skips_low_resolved_rate(self):
        # 50 个 thought 但 95% pending (低 resolved rate)
        thoughts = [self._make_thought('A', 'pending', 0.5)
                    for _ in range(48)]
        thoughts += [self._make_thought('A', 'sir_engaged', 0.8)
                     for _ in range(2)]
        self._write_thoughts(thoughts)
        c = self._make_consolidator()
        c._do_inner_thought_outcome_consolidation('2026-W21')
        self.assertFalse(os.path.exists(self.insights_path))

    def test_13_consolidation_full_path_writes_insight(self):
        """🆕 [Sir 2026-05-28 12:30 β.5.45 退化] reflector path no-op 不写 insight.

        历史: 此 test 原 assert "充足数据 + 高 conf LLM → 真写 insight,
              type=inner_thought_vocab_tune".
        退化: surface_to_sir 机制全 retired (见 jarvis_inner_thought_daemon.py:271-300
              顶部 anchor). 该 reflector path 提的是 vocab 阈值
              (salience_threshold / cooldown / max_per_hour), 阈值现已 dead.
              入口 method 早退 no-op, 即便满足条件也不写 insight.
        准则 4 testing discipline: assert 反着 (强化 spec, 不弱化 — 这是
              regression guard 防 reflector 被无意重启).
        """
        # 30 个 thought, 60% resolved — 仍同样数据, 但 reflector retired
        thoughts = []
        thoughts += [self._make_thought('A', 'sir_engaged', 0.8)
                     for _ in range(12)]
        thoughts += [self._make_thought('A', 'sir_silenced', 0.7)
                     for _ in range(6)]
        thoughts += [self._make_thought('A', 'pending', 0.5)
                     for _ in range(12)]
        self._write_thoughts(thoughts)
        # vocab fixture
        with open(self.vocab_path, 'w', encoding='utf-8') as f:
            json.dump({'salience_threshold': 0.7, 'max_per_hour': 6,
                       'cooldown_global_s': 120}, f)
        c = self._make_consolidator()
        raw = (
            "<PATTERN_SUMMARY>Sir engages 40%, silenced 20%</PATTERN_SUMMARY>\n"
            "<SUGGESTED_ACTION>Lower threshold</SUGGESTED_ACTION>\n"
            "<TARGET_FIELD>salience_threshold</TARGET_FIELD>\n"
            "<OLD_VALUE>0.7</OLD_VALUE>\n"
            "<NEW_VALUE>0.6</NEW_VALUE>\n"
            "<CONFIDENCE>0.75</CONFIDENCE>\n"
        )
        with self._mock_llm_reflector(raw):
            c._do_inner_thought_outcome_consolidation('2026-W21')
        # 退化后 insight 不写
        self.assertFalse(
            os.path.exists(self.insights_path),
            'β.5.45 retired: reflector path 应 no-op 不写 insight, '
            '但 insights_path 真存在 → reflector 被无意重启?'
        )

    # ==========================================================
    # 10. _maybe_fire — 两条 path 并行
    # ==========================================================

    def test_14_maybe_fire_runs_both_paths_on_sunday(self):
        """Sunday 03:xx 两条 reflector 都 fire (一 fail 不阻另一)."""
        c = self._make_consolidator()
        # mock time → Sunday 03:00
        # (skipping real time mock — direct test via patching tm_wday/tm_hour)
        with patch.object(c, '_do_weekly_consolidation') as m1, \
             patch.object(c, '_do_inner_thought_outcome_consolidation') as m2, \
             patch('time.localtime') as tlt:
            # Sunday tm_wday=6, hour=3
            fake_lt = MagicMock()
            fake_lt.tm_wday = 6
            fake_lt.tm_hour = 3
            tlt.return_value = fake_lt
            # 防 week_key parse fail: mock strftime
            with patch('time.strftime', return_value='2026 21 7'):
                c._maybe_fire()
        m1.assert_called_once()
        m2.assert_called_once()

    def test_15_maybe_fire_one_path_fail_does_not_block_other(self):
        c = self._make_consolidator()
        with patch.object(c, '_do_weekly_consolidation',
                          side_effect=Exception('boom')) as m1, \
             patch.object(c, '_do_inner_thought_outcome_consolidation') as m2, \
             patch('time.localtime') as tlt:
            fake_lt = MagicMock()
            fake_lt.tm_wday = 6
            fake_lt.tm_hour = 3
            tlt.return_value = fake_lt
            with patch('time.strftime', return_value='2026 21 7'):
                c._maybe_fire()
        # m1 raise 但 m2 仍跑
        m1.assert_called_once()
        m2.assert_called_once()

    # ==========================================================
    # 11. backward-compat load
    # ==========================================================

    def test_16_load_old_record_without_new_fields(self):
        """老 record (无 insight_type/target_*) load OK."""
        old_record = {
            'id': 'wi_old_x', 'ts': time.time(), 'ts_iso': '',
            'week_range_iso': '2026-05-01 → 2026-05-07',
            'pattern_summary': 'old pattern',
            'suggested_action': 'old action', 'evidence_count': 5,
            'evidence_excerpts': ['e1', 'e2'], 'confidence': 0.6,
            'state': 'review',
            'sir_decision_at': 0.0, 'sir_decision_reason': '',
            # 故意 没 insight_type / target_vocab_path / etc.
        }
        with open(self.insights_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps(old_record) + '\n')
        from jarvis_weekly_reflection_consolidator import (
            WeeklyReflectionConsolidator,
        )
        c = WeeklyReflectionConsolidator()
        c.PERSIST_PATH = self.insights_path
        # 重新 load (init 已 load 真 path, 这里手动 trigger)
        c._insights = []
        c._load_persist()
        # 老 record load OK + default insight_type
        self.assertEqual(len(c._insights), 1)
        self.assertEqual(c._insights[0].insight_type,
                          'self_reflection_pattern')
        self.assertEqual(c._insights[0].target_field, '')


if __name__ == '__main__':
    unittest.main()
