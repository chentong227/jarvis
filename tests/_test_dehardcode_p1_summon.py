# -*- coding: utf-8 -*-
"""[thinking-dehardcode-P1 / Sir 2026-05-31] summon 锚体势能区 + CATEGORY optional.

工程 Phase 1 (设计 §4 / §5.2): emergent 模式下思考由**体焦点区** (BODY SIGNALS,
current_focus 渲染) summon, 不再强制选 A-E 槽 — <CATEGORY> 退化为 optional. legacy
模式 0 行为变 (CATEGORY 仍必需 + 冷却框架). flag thinking_kind_mode 切换.

覆盖 (纯函数 / parse, 无 LLM):
  T1  _compat_category_from_actionable 全映射 (A/B/C/D/E)
  T2  _build_category_framing legacy: cat_line 含冷却框架, summon_note 空
  T3  _build_category_framing emergent: cat_line 含 OPTIONAL, summon_note 含 SUMMON+BODY SIGNALS
  T4  legacy parse: 无 <CATEGORY> → None (拒, 0 行为变)
  T5  emergent parse: 无 <CATEGORY> → 解析成功, category 从 actionable 反推
  T6  legacy parse: 有 <CATEGORY> → 正常 (0 行为变)
  T7  emergent parse: 有 <CATEGORY> → 用 LLM 给的 (不覆盖)
  T8  emergent parse: 无 CATEGORY + actionable=none → category=A (compat)
"""
from __future__ import annotations

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_inner_thought_daemon as itd
from jarvis_inner_thought_daemon import (
    InnerThoughtDaemon,
    _compat_category_from_actionable,
)


def _set_mode(mode: str) -> None:
    """注入 mode 到 cache (隔离 vocab 文件)."""
    itd._THINKING_KIND_CACHE['data'] = {
        'thinking_kind_mode': mode,
        'effect_to_kind': itd._THINKING_KIND_DEFAULT['effect_to_kind'],
        'kind_for_rest': 'rest', 'kind_for_none': 'empty',
        'kind_for_unknown': 'act',
    }
    itd._THINKING_KIND_CACHE['checked_at'] = time.time()


def _reset_mode() -> None:
    itd._THINKING_KIND_CACHE['data'] = None
    itd._THINKING_KIND_CACHE['mtime'] = 0.0
    itd._THINKING_KIND_CACHE['checked_at'] = 0.0


def _daemon():
    d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
    d._bg_log = lambda *a, **k: None
    d._thoughts = []
    return d


class TestP1CompatCategory(unittest.TestCase):
    def test_t1_compat_mapping(self):
        cases = {
            'none': 'A',
            '': 'A',
            'update_concern_severity:x:+0.1': 'C',
            'adjust_concern_notes:x:note': 'C',
            'propose_protocol:do x': 'B',
            'propose_stance:sir:view': 'B',
            'propose_vocab_adjustment:f:k:v': 'B',
            'request_capability:x': 'B',
            'adjust_sensor_threshold:p:v': 'B',
            'fire_nudge:care:hi': 'D',
            'propose_watch_task:t:g': 'D',
            'call_tool:x:y': 'D',
            'compose_main_brain_directive:x': 'D',
            'suggest_inside_joke:x': 'E',
            'some_unknown_action:x': 'A',
        }
        for a, expect in cases.items():
            self.assertEqual(_compat_category_from_actionable(a), expect,
                             f"{a} 应反推 {expect}")


class TestP1CategoryFraming(unittest.TestCase):
    def test_t2_legacy_framing(self):
        cat_line, summon = InnerThoughtDaemon._build_category_framing(
            'legacy', list('ABCDE'))
        self.assertIn('cooldown', cat_line)
        self.assertEqual(summon, '')

    def test_t3_emergent_framing(self):
        cat_line, summon = InnerThoughtDaemon._build_category_framing(
            'emergent', list('ABCDE'))
        self.assertIn('OPTIONAL', cat_line)
        self.assertIn('SUMMON', summon)
        self.assertIn('BODY SIGNALS', summon)


class TestP1ParseCategoryOptional(unittest.TestCase):
    def setUp(self):
        _reset_mode()

    def tearDown(self):
        _reset_mode()

    _RAW_NO_CAT = (
        "<THOUGHT>Sir's lack of breaks despite six hours of coding indicates "
        "his pomodoro compliance is failing.</THOUGHT> <SALIENCE>0.85</SALIENCE> "
        "<ACTIONABLE>adjust_concern_notes:sir_pomodoro:take breaks</ACTIONABLE> "
        "<EVIDENCE_LINK>pomodoro</EVIDENCE_LINK>"
    )
    _RAW_WITH_CAT = (
        "<CATEGORY>C</CATEGORY> <THOUGHT>Sir skipped lunch again.</THOUGHT> "
        "<SALIENCE>0.7</SALIENCE> <ACTIONABLE>none</ACTIONABLE>"
    )
    _RAW_NO_CAT_NONE = (
        "<THOUGHT>Sir is active and focused.</THOUGHT> <SALIENCE>0.4</SALIENCE> "
        "<ACTIONABLE>none</ACTIONABLE>"
    )

    def test_t4_legacy_no_category_rejected(self):
        _set_mode('legacy')
        d = _daemon()
        t = d._parse_thought(self._RAW_NO_CAT, 'active', 45)
        self.assertIsNone(t, 'legacy 无 CATEGORY 应拒 (0 行为变)')

    def test_t5_emergent_no_category_parses(self):
        _set_mode('emergent')
        d = _daemon()
        t = d._parse_thought(self._RAW_NO_CAT, 'active', 45)
        self.assertIsNotNone(t, 'emergent 无 CATEGORY 应解析成功')
        # actionable=adjust_concern_notes → compat category C
        self.assertEqual(t.category, 'C')
        self.assertEqual(t.actionable, 'adjust_concern_notes:sir_pomodoro:take breaks')

    def test_t6_legacy_with_category_works(self):
        _set_mode('legacy')
        d = _daemon()
        t = d._parse_thought(self._RAW_WITH_CAT, 'active', 45)
        self.assertIsNotNone(t)
        self.assertEqual(t.category, 'C')

    def test_t7_emergent_with_category_uses_given(self):
        _set_mode('emergent')
        d = _daemon()
        t = d._parse_thought(self._RAW_WITH_CAT, 'active', 45)
        self.assertIsNotNone(t)
        # LLM 给了 C → 用 C (不被 compat 覆盖; actionable=none compat 会是 A)
        self.assertEqual(t.category, 'C')

    def test_t8_emergent_no_category_none_actionable(self):
        _set_mode('emergent')
        d = _daemon()
        t = d._parse_thought(self._RAW_NO_CAT_NONE, 'active', 45)
        self.assertIsNotNone(t)
        self.assertEqual(t.category, 'A')  # none → compat A


if __name__ == '__main__':
    unittest.main()
