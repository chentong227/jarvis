# -*- coding: utf-8 -*-
"""[SOUL Phase B / Sir 2026-05-26] InnerThought C 类反思 → adjust_concern_notes →
ConcernsLedger.notes_for_self → Layer 1 prompt 主脑下次自主调整 — 闭环.

Sir 真意 (双约束 + 真痛 anchor):
  不加新 Layer / 不加新 daemon / 不加新 module.
  Sir "减少对面试准备的打扰" — 反思认到 Sir 反应后, 该改"主脑下次怎么 handle 这个
  concern", 不是改 severity. 接 Concern.notes_for_self (现有字段, 500 char cap,
  Layer 1 prompt 自然 inject 主脑).

设计 (复用现有 update_concern_field 标准 mutation 路径):
  - InnerThought C 类 sal≥0.7 + adjust_concern_notes:<cid>:<note>
  - Python 三 gate (category=C + sal≥0.7 + cite ↔ concern overlap)
  - append 不覆盖, 加 [inner_thought/C/sal=X.XX] 来源 tag
  - 总长 cap 500 (schema), 单次 append cap 120 (防一次写太长)

测试覆盖 (12 个):
  L1 actionable parse + route (_execute_actionable 'adjust_concern_notes:')
  L2 gate C-class only (B/A/D/E rejected)
  L3 gate sal≥0.7 (低 sal rejected)
  L4 gate empty cid / empty note / note too short
  L5 gate concern_not_found
  L6 gate evidence_link_wrong_concern (cite ↔ concern overlap fail)
  L7 success append 不覆盖 + 加 source tag
  L8 success 第一次 (existing 空) 直接写
  L9 cap 500 char (超长截) + 单次 cap 120
  L10 prompt 含 adjust_concern_notes option + C 类 example
  L11 端到端: C sal=0.8 + adjust_concern_notes → concern.notes 真改
  L12 二层 fail → actionable 降级 none (防 SOUL inject 误导)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _empty_daemon(concerns=None):
    """临时 InnerThoughtDaemon (临时 PERSIST_PATH + 可选 concerns_ledger)."""
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    tmp = os.path.join(tempfile.gettempdir(),
                          f'soul_b_it_{time.time()}.jsonl')
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp
    try:
        d = InnerThoughtDaemon(
            key_router=None,
            concerns_ledger=concerns,
        )
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp
    return d


def _mk_thought(thought_text: str, actionable: str = 'none',
                  evidence_link: str = '', category: str = 'C',
                  salience: float = 0.8):
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id=f't_{time.time()}',
        ts=time.time(),
        ts_iso='?',
        category=category,
        thought=thought_text,
        salience=salience,
        actionable=actionable,
        evidence_link=evidence_link,
    )


def _mk_concern(cid: str, what: str,
                  notes_for_self: str = '', severity: float = 0.5):
    """Mock concern with what_i_watch + notes_for_self (mutable)."""
    c = MagicMock()
    c.id = cid
    c.what_i_watch = what
    c.notes_for_self = notes_for_self
    c.severity = severity
    return c


def _mk_ledger(concerns_dict):
    """Mock ledger that supports get() + update_concern_field() (真改 notes)."""
    ledger = MagicMock()
    ledger.concerns = concerns_dict
    ledger.get = MagicMock(side_effect=lambda cid: concerns_dict.get(cid))

    def _update_field(cid, field, new_value, source='', turn_id='', reason=''):
        if cid not in concerns_dict:
            return False, f'concern_not_found:{cid}', None
        c = concerns_dict[cid]
        old_v = getattr(c, field, None)
        setattr(c, field, new_value)
        return True, '', old_v
    ledger.update_concern_field = MagicMock(side_effect=_update_field)
    return ledger


# ==========================================================================
# L1: actionable parse + route
# ==========================================================================
class TestL1ActionableRoute(unittest.TestCase):
    def test_execute_actionable_routes_adjust_concern_notes(self):
        c = _mk_concern('sir_interview_pr',
                          'Sir interview preparation balance and progress',
                          notes_for_self='')
        ledger = _mk_ledger({'sir_interview_pr': c})
        d = _empty_daemon(concerns=ledger)
        t = _mk_thought(
            'Sir asked me to stop bringing up interview prep unprompted earlier',
            actionable='adjust_concern_notes:sir_interview_pr:DO NOT volunteer this topic unless Sir asks',
            evidence_link='interview prep',
            category='C',
            salience=0.8,
        )
        ok, result = d._execute_actionable(t)
        self.assertTrue(ok, f'should succeed, got: {result}')
        self.assertIn('notes appended', result)


# ==========================================================================
# L2: 🆕 [Sir 2026-05-26 23:17 BUG-4/A 准则 6] 删 C-class hard gate.
# cross-class adjust_concern_notes 允许, 只要 sal ≥ 0.7 + cid 存在 + cite 合法.
# 老 hard gate 拦 B-self-reflect 想给 concern 加 note 不合理 (准则 6 违反).
# ==========================================================================
class TestL2GateClass(unittest.TestCase):
    def setUp(self):
        c = _mk_concern('sir_interview_pr',
                          'Sir interview preparation', notes_for_self='')
        self.ledger = _mk_ledger({'sir_interview_pr': c})
        self.d = _empty_daemon(concerns=self.ledger)
        self.actionable = (
            'adjust_concern_notes:sir_interview_pr:'
            'DO NOT volunteer this topic'
        )

    def _run_with_category(self, cat):
        t = _mk_thought(
            'Sir asked me to stop bringing up interview prep unprompted',
            actionable=self.actionable,
            evidence_link='interview',
            category=cat,
            salience=0.8,
        )
        return self.d._do_adjust_concern_notes(t, t.actionable)

    def test_cross_class_not_gated_by_category(self):
        """🆕 [Sir 23:17 BUG-4] 删 hard gate, A/B/D/E 不应被 category 拦.
        仍可能被 cite gate / cid gate / sal gate 拦 — 但不是 notes_adjust_only_from_C.
        准则 6: LLM 自决 cross-class 适用性.
        """
        for cat in ('A', 'B', 'D', 'E'):
            ok, result = self._run_with_category(cat)
            self.assertNotIn(
                'gated:notes_adjust_only_from_C', result,
                f'cat={cat}: 准则 6 cross-class adjust_concern_notes 不应被 hard gate 拦, got {result}'
            )


# ==========================================================================
# L3: gate sal≥0.7
# ==========================================================================
class TestL3GateSalience(unittest.TestCase):
    def test_low_sal_rejected(self):
        c = _mk_concern('sir_interview_pr',
                          'Sir interview preparation', notes_for_self='')
        ledger = _mk_ledger({'sir_interview_pr': c})
        d = _empty_daemon(concerns=ledger)
        t = _mk_thought(
            'Sir mentioned interview prep briefly, somewhat tired',
            actionable='adjust_concern_notes:sir_interview_pr:DO NOT volunteer this topic',
            evidence_link='interview',
            category='C',
            salience=0.5,  # 低
        )
        ok, result = d._do_adjust_concern_notes(t, t.actionable)
        self.assertFalse(ok)
        self.assertIn('gated:notes_adjust_requires_sal', result)


# ==========================================================================
# L4: empty cid / note / too short
# ==========================================================================
class TestL4GateInputValidation(unittest.TestCase):
    def setUp(self):
        c = _mk_concern('sir_interview_pr',
                          'Sir interview preparation', notes_for_self='')
        self.ledger = _mk_ledger({'sir_interview_pr': c})
        self.d = _empty_daemon(concerns=self.ledger)

    def _run(self, actionable):
        t = _mk_thought(
            'Sir asked me to stop bringing up interview prep unprompted',
            actionable=actionable,
            evidence_link='interview',
            category='C',
            salience=0.8,
        )
        return self.d._do_adjust_concern_notes(t, t.actionable)

    def test_empty_cid(self):
        ok, result = self._run('adjust_concern_notes::DO NOT volunteer this topic')
        self.assertFalse(ok)
        self.assertIn('empty_concern_id', result)

    def test_empty_note(self):
        ok, result = self._run('adjust_concern_notes:sir_interview_pr:')
        self.assertFalse(ok)
        self.assertIn('empty_note', result)

    def test_note_too_short(self):
        ok, result = self._run('adjust_concern_notes:sir_interview_pr:short')
        self.assertFalse(ok)
        self.assertIn('note_too_short', result)

    def test_parse_fail_missing_colon(self):
        ok, result = self._run('adjust_concern_notes:sir_interview_pr')
        self.assertFalse(ok)
        self.assertIn('parse_fail', result)


# ==========================================================================
# L5: concern_not_found
# ==========================================================================
class TestL5ConcernNotFound(unittest.TestCase):
    def test_concern_not_found_rejected(self):
        ledger = _mk_ledger({})  # 无 concern
        d = _empty_daemon(concerns=ledger)
        t = _mk_thought(
            'Sir asked me to stop bringing up interview prep unprompted',
            actionable='adjust_concern_notes:nonexistent_cid:DO NOT volunteer this topic',
            evidence_link='interview',
            category='C',
            salience=0.8,
        )
        ok, result = d._do_adjust_concern_notes(t, t.actionable)
        self.assertFalse(ok)
        self.assertIn('concern_not_found', result)


# ==========================================================================
# L6: evidence_link_wrong_concern (Sir 真痛 anchor 二层 gate)
# ==========================================================================
class TestL6EvidenceLinkWrongConcern(unittest.TestCase):
    def test_wrong_concern_rejected_with_actionable_demotion(self):
        """🎯 Sir 真痛 anchor: cite "toggling" + target sir_interview_pr (无 overlap) → reject."""
        c = _mk_concern('sir_interview_pr',
                          'Sir interview preparation balance and progress',
                          notes_for_self='')
        ledger = _mk_ledger({'sir_interview_pr': c})
        d = _empty_daemon(concerns=ledger)
        t = _mk_thought(
            'Sir is toggling between general tasks and coding rapidly',
            actionable='adjust_concern_notes:sir_interview_pr:DO NOT volunteer this topic',
            evidence_link='toggling',  # 真在 thought 但 wrong concern
            category='C',
            salience=0.8,
        )
        ok, result = d._execute_actionable(t)
        self.assertFalse(ok)
        self.assertIn('evidence_link_wrong_concern', result)
        # actionable 降级 none (SOUL inject 不误导)
        self.assertEqual(t.actionable, 'none')
        # ledger 真没被改
        ledger.update_concern_field.assert_not_called()


# ==========================================================================
# L7: success append 不覆盖 + 加 source tag
# ==========================================================================
class TestL7AppendNotOverwrite(unittest.TestCase):
    def test_append_preserves_existing_notes(self):
        existing_notes = '[dismissed/sir_voice] Sir 让我别提面试'
        c = _mk_concern('sir_interview_pr',
                          'Sir interview preparation balance',
                          notes_for_self=existing_notes)
        ledger = _mk_ledger({'sir_interview_pr': c})
        d = _empty_daemon(concerns=ledger)
        t = _mk_thought(
            'Sir asked me to stop bringing up interview prep unprompted',
            actionable='adjust_concern_notes:sir_interview_pr:DO NOT volunteer this topic',
            evidence_link='interview prep',
            category='C',
            salience=0.8,
        )
        ok, _ = d._do_adjust_concern_notes(t, t.actionable)
        self.assertTrue(ok)
        # 真改 + existing 保留
        self.assertIn('[dismissed/sir_voice]', c.notes_for_self,
            'existing note 必须保留')
        self.assertIn('[inner_thought/C/sal=0.80]', c.notes_for_self,
            '新 note 必须带 source tag')
        self.assertIn('DO NOT volunteer', c.notes_for_self,
            'note text 真 append')


# ==========================================================================
# L8: success 第一次 (existing 空) 直接写
# ==========================================================================
class TestL8FirstNote(unittest.TestCase):
    def test_first_note_empty_existing(self):
        c = _mk_concern('sir_interview_pr',
                          'Sir interview preparation balance',
                          notes_for_self='')
        ledger = _mk_ledger({'sir_interview_pr': c})
        d = _empty_daemon(concerns=ledger)
        t = _mk_thought(
            'Sir asked me to stop bringing up interview prep unprompted',
            actionable='adjust_concern_notes:sir_interview_pr:DO NOT volunteer this topic',
            evidence_link='interview',
            category='C',
            salience=0.8,
        )
        ok, _ = d._do_adjust_concern_notes(t, t.actionable)
        self.assertTrue(ok)
        # 第一次写 — 无 '|' 分隔符开头
        self.assertFalse(c.notes_for_self.startswith('|'),
            '第一次 append 不应有 | 前缀')
        self.assertIn('[inner_thought/C/sal=0.80]', c.notes_for_self)


# ==========================================================================
# L9: cap 500 char + 单次 cap 120
# ==========================================================================
class TestL9CharCaps(unittest.TestCase):
    def test_single_note_capped_at_120(self):
        c = _mk_concern('sir_interview_pr',
                          'Sir interview preparation balance',
                          notes_for_self='')
        ledger = _mk_ledger({'sir_interview_pr': c})
        d = _empty_daemon(concerns=ledger)
        long_note = 'DO NOT volunteer this topic ' * 20  # > 120
        t = _mk_thought(
            'Sir asked me to stop bringing up interview prep unprompted',
            actionable=f'adjust_concern_notes:sir_interview_pr:{long_note}',
            evidence_link='interview',
            category='C',
            salience=0.8,
        )
        ok, _ = d._do_adjust_concern_notes(t, t.actionable)
        self.assertTrue(ok)
        # 单次 append 段 ≤ 120 char + tag 约 30 char ≈ 150
        # check note 中 'DO NOT volunteer this topic' 重复次数 ≤ 5 (120 / 22 ≈ 5)
        repeat_count = c.notes_for_self.count('DO NOT volunteer this topic')
        self.assertLessEqual(repeat_count, 6,
            f'单次 append 应 cap 120 char, got {repeat_count} repeats')

    def test_total_capped_at_500(self):
        # 🆕 [Sir 2026-05-26 13:32 BUG 3 治本] notes >=80% (400+) 改成早 reject (避免
        # 浪费 mutation). 这里用 existing=350 (70%, 未达 reject 阈值) 仍验证 500 cap.
        # 80% reject 行为单独由 _test_fix8 TestBug3NotesFullEarlyReject 覆盖.
        long_existing = 'x' * 350
        c = _mk_concern('sir_interview_pr',
                          'Sir interview preparation balance',
                          notes_for_self=long_existing)
        ledger = _mk_ledger({'sir_interview_pr': c})
        d = _empty_daemon(concerns=ledger)
        t = _mk_thought(
            'Sir asked me to stop bringing up interview prep unprompted',
            actionable='adjust_concern_notes:sir_interview_pr:DO NOT volunteer this topic anymore please',
            evidence_link='interview',
            category='C',
            salience=0.8,
        )
        ok, _ = d._do_adjust_concern_notes(t, t.actionable)
        self.assertTrue(ok)
        self.assertLessEqual(len(c.notes_for_self), 500,
            '总长必须 cap 500 (schema)')


# ==========================================================================
# L10: prompt 含 adjust_concern_notes option + C 类 example
# ==========================================================================
class TestL10PromptIncludes(unittest.TestCase):
    def test_prompt_has_adjust_concern_notes_option(self):
        d = _empty_daemon()
        sys_p, _ = d._build_prompt(
            'active', {'sir_state': 'active'},
            free_categories=['A', 'B', 'C', 'D', 'E'],
        )
        self.assertIn('adjust_concern_notes', sys_p,
            'prompt 必须含 adjust_concern_notes actionable option')
        # C 类 anchor: "OR should I update HOW I respond"
        self.assertIn('update HOW I respond', sys_p,
            'prompt 必须教 C 类用 adjust_concern_notes')
        # Sir 真痛 anchor C-class example
        self.assertIn('DO NOT volunteer', sys_p,
            'prompt 必须含 Sir 真痛 anchor C 类 example')
        self.assertIn('减少对面试准备的打扰', sys_p,
            'prompt 必须 explicitly cite Sir 真痛 anchor 中文原话')


# ==========================================================================
# L11: 端到端 (C sal=0.8 + adjust_concern_notes → concern.notes 真改)
# ==========================================================================
class TestL11EndToEnd(unittest.TestCase):
    def test_end_to_end_real_pain_anchor_treated(self):
        """🎯 Sir 真意 anchor 端到端: "减少对面试准备的打扰" 闭环.

        C 类 thought 反思 → adjust_concern_notes:sir_interview_pr:DO NOT volunteer
        → ledger.notes_for_self 真改 → Layer 1 prompt 主脑下次自然读 (现有路径).
        """
        c = _mk_concern('sir_interview_pr',
                          'Sir interview preparation balance and progress',
                          notes_for_self='')
        ledger = _mk_ledger({'sir_interview_pr': c})
        d = _empty_daemon(concerns=ledger)
        t = _mk_thought(
            'Sir asked me to stop bringing up interview prep unprompted earlier today',
            actionable=(
                'adjust_concern_notes:sir_interview_pr:'
                'DO NOT volunteer this topic — only address when Sir asks directly'
            ),
            evidence_link='interview prep',
            category='C',
            salience=0.85,
        )
        ok, result = d._execute_actionable(t)
        self.assertTrue(ok, f'端到端应 pass, got: {result}')
        # ledger 真被调用
        ledger.update_concern_field.assert_called_once()
        # concern.notes_for_self 真含 Sir 期待的引导
        self.assertIn('DO NOT volunteer', c.notes_for_self)
        self.assertIn('only address when Sir asks', c.notes_for_self)


# ==========================================================================
# L12: 二层 fail → actionable 降级 none
# ==========================================================================
class TestL12ActionableDemotion(unittest.TestCase):
    def test_wrong_concern_demotes_actionable_to_none(self):
        c = _mk_concern('sir_interview_pr',
                          'Sir interview preparation balance',
                          notes_for_self='')
        ledger = _mk_ledger({'sir_interview_pr': c})
        d = _empty_daemon(concerns=ledger)
        t = _mk_thought(
            'Sir is toggling between coding sessions rapidly without rest',
            actionable=(
                'adjust_concern_notes:sir_interview_pr:'
                'DO NOT volunteer this topic'
            ),
            evidence_link='toggling',  # cite 真在 thought 但跟 interview 无 overlap
            category='C',
            salience=0.8,
        )
        ok, result = d._execute_actionable(t)
        self.assertFalse(ok)
        # 降级 — actionable=none 防 SOUL inject 误导主脑
        self.assertEqual(t.actionable, 'none')
        # ledger 真没被改
        self.assertEqual(c.notes_for_self, '',
            'wrong concern 必须不改 notes')


if __name__ == '__main__':
    unittest.main()
