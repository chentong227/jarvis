# -*- coding: utf-8 -*-
"""[Gap 1 / P5-ToM / 2026-05-21 01:15] ToM SirMentalState verify

Cover:
  A. SirMentalState dataclass basics + has_meaningful_content + is_stale
  B. SirMentalStateStore CRUD + persist
  C. revision_history tracking
  D. render_prompt_block format + skip empty/stale
  E. Sir manual correct via store
  F. ToMReflector basic (no LLM available → noop)
  G. Static integration check
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _StoreTempMixin:
    """Tmpdir-based store for test isolation."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix='sir_mental_test_')
        cls.path = os.path.join(cls.tmpdir, 'sir_mental_state.json')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _new_store(self):
        from jarvis_sir_mental_model import SirMentalStateStore
        # use unique path per test for isolation
        path = os.path.join(self.tmpdir, f'state_{id(self)}.json')
        return SirMentalStateStore(persist_path=path)


# ============================================================
# A. dataclass basics
# ============================================================

class TestA_DataclassBasics(_StoreTempMixin, unittest.TestCase):

    def test_default_empty(self):
        from jarvis_sir_mental_model import SirMentalState
        s = SirMentalState()
        self.assertFalse(s.has_meaningful_content())
        self.assertTrue(s.is_stale())  # last_updated=0
        self.assertEqual(s.relational_temp, 'neutral')
        self.assertEqual(s.emotional_state, 'unknown')

    def test_meaningful_after_set(self):
        from jarvis_sir_mental_model import SirMentalState
        s = SirMentalState(current_task_hypothesis='debugging')
        self.assertTrue(s.has_meaningful_content())

    def test_stale_after_threshold(self):
        from jarvis_sir_mental_model import SirMentalState
        s = SirMentalState(last_updated=time.time() - 700)  # 700s > 600s threshold
        self.assertTrue(s.is_stale())

    def test_not_stale_recent(self):
        from jarvis_sir_mental_model import SirMentalState
        s = SirMentalState(last_updated=time.time() - 60)
        self.assertFalse(s.is_stale())


# ============================================================
# B. Store CRUD + persist
# ============================================================

class TestB_StoreCRUD(_StoreTempMixin, unittest.TestCase):

    def test_update_and_persist(self):
        store = self._new_store()
        revisions = store.update({
            'current_task_hypothesis': 'debugging Jarvis ToM',
            'task_confidence': 0.85,
            'surface_need': 'verify ToM works',
            'need_layers_confidence': {'surface': 0.95, 'deeper': 0.6, 'unspoken': 0.2},
        }, source_turn_id='turn_test_1')
        self.assertEqual(len(revisions), 4)
        # reload from disk
        from jarvis_sir_mental_model import SirMentalStateStore
        store2 = SirMentalStateStore(persist_path=store.persist_path)
        s = store2.get_snapshot()
        self.assertEqual(s.current_task_hypothesis, 'debugging Jarvis ToM')
        self.assertAlmostEqual(s.task_confidence, 0.85, places=2)
        self.assertEqual(s.surface_need, 'verify ToM works')

    def test_no_revision_when_unchanged(self):
        store = self._new_store()
        store.update({'current_task_hypothesis': 'debug X'}, source_turn_id='t1')
        # 2nd update with same value → no revision
        revisions = store.update({'current_task_hypothesis': 'debug X'}, source_turn_id='t2')
        self.assertEqual(len(revisions), 0)


# ============================================================
# C. revision_history
# ============================================================

class TestC_RevisionHistory(_StoreTempMixin, unittest.TestCase):

    def test_revision_recorded(self):
        store = self._new_store()
        store.update({'surface_need': 'first'}, source_turn_id='t1')
        store.update({'surface_need': 'second'}, source_turn_id='t2')
        s = store.get_snapshot()
        self.assertEqual(len(s.revision_history), 2)
        self.assertEqual(s.revision_history[-1]['field'], 'surface_need')
        self.assertEqual(s.revision_history[-1]['old'], 'first')
        self.assertEqual(s.revision_history[-1]['new'], 'second')


# ============================================================
# D. render_prompt_block
# ============================================================

class TestD_PromptBlock(_StoreTempMixin, unittest.TestCase):

    def test_empty_returns_empty_string(self):
        store = self._new_store()
        block = store.render_prompt_block()
        self.assertEqual(block, '')

    def test_full_block_format(self):
        store = self._new_store()
        store.update({
            'current_task_hypothesis': 'Sir is debugging Jarvis ToM module',
            'task_confidence': 0.85,
            'task_evidence': ['cursor active', 'STM mentions ToM'],
            'emotional_state': 'engaged',
            'emotional_confidence': 0.7,
            'surface_need': 'verify ToM works',
            'deeper_need': 'long-term Sir-aware foundation',
            'unspoken_need': 'wants Cascade to deliver fast',
            'need_layers_confidence': {'surface': 0.95, 'deeper': 0.7, 'unspoken': 0.5},
            'relational_temp': 'warm',
        })
        block = store.render_prompt_block()
        self.assertIn("SIR'S MIND RIGHT NOW", block)
        self.assertIn('debugging Jarvis ToM', block)
        self.assertIn('engaged', block)
        self.assertIn('surface', block)
        self.assertIn('deeper', block)
        # unspoken at conf 0.5 (>= 0.4 threshold) shows
        self.assertIn('unspoken', block)
        self.assertIn('warm', block)

    def test_unspoken_skipped_low_conf(self):
        store = self._new_store()
        store.update({
            'surface_need': 'X',
            'unspoken_need': 'maybe Y',
            'need_layers_confidence': {'surface': 0.9, 'unspoken': 0.2},  # < 0.4
        })
        block = store.render_prompt_block()
        # unspoken not shown
        self.assertNotIn('maybe Y', block)


# ============================================================
# E. Sir manual correct
# ============================================================

class TestE_ManualCorrect(_StoreTempMixin, unittest.TestCase):

    def test_correct_field(self):
        store = self._new_store()
        store.update({'surface_need': 'AI proposed'})
        ok = store.correct_field('surface_need', 'Sir corrected', decided_by='sir_cli')
        self.assertTrue(ok)
        s = store.get_snapshot()
        self.assertEqual(s.surface_need, 'Sir corrected')
        # revision recorded
        self.assertGreater(len(s.revision_history), 1)

    def test_correct_invalid_field(self):
        store = self._new_store()
        ok = store.correct_field('nonexistent_field', 'X')
        self.assertFalse(ok)


# ============================================================
# F. ToMReflector basic (no LLM available → noop)
# ============================================================

class TestF_ToMReflector(unittest.TestCase):

    def setUp(self):
        from jarvis_sir_mental_model import (
            reset_default_reflector_for_test, reset_default_store_for_test,
        )
        reset_default_reflector_for_test()
        reset_default_store_for_test()

    def test_no_key_router_skips(self):
        from jarvis_sir_mental_model import ToMReflector
        reflector = ToMReflector(key_router=None)
        # should not crash
        reflector._reflect_impl(
            sir_utterance='hello',
            jarvis_reply='hi Sir',
            turn_id='t1',
            context_summary='',
        )
        # no update should have happened
        self.assertEqual(reflector.stats()['reflections_total'], 0)

    def test_async_does_not_block(self):
        from jarvis_sir_mental_model import ToMReflector
        reflector = ToMReflector(key_router=None)
        # async call returns immediately even though _reflect_sync called
        _t0 = time.time()
        reflector.reflect_async(
            sir_utterance='hello', jarvis_reply='hi', turn_id='t1',
        )
        elapsed = time.time() - _t0
        self.assertLess(elapsed, 0.5)  # didn't block

    def test_empty_input_skips(self):
        from jarvis_sir_mental_model import ToMReflector
        reflector = ToMReflector(key_router=None)
        reflector.reflect_async('', 'hi', 't1')  # empty sir → skip
        reflector.reflect_async('hello', '', 't1')  # empty reply → skip


# ============================================================
# G. Static integration check
# ============================================================

class TestG_StaticIntegration(unittest.TestCase):

    def test_central_nerve_imports_tom(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('from jarvis_sir_mental_model import ToMReflector', src)
        self.assertIn('self.tom_reflector', src)
        self.assertIn("SIR'S MIND RIGHT NOW", src)

    def test_chat_bypass_calls_tom(self):
        import jarvis_chat_bypass
        with open(jarvis_chat_bypass.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('tom_reflector', src)
        self.assertIn('reflect_async', src)


if __name__ == '__main__':
    unittest.main()
