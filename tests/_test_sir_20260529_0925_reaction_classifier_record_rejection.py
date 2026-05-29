# -*- coding: utf-8 -*-
"""[Sir 2026-05-29 Option A] #1+#2 reaction classifier + 精准 record_rejection.

docs/JARVIS_CLOSURE_AND_RELATIONAL_UPLIFT_DESIGN.md §3 #1 #2.

覆盖:
  #2 classify_fast (窄: rejected/engaged) + has_negative_candidate (宽闸)
  #2 vocab CLI add/remove + 热加载 invalidate
  #2 _parse_reaction_response 多场景
  #1 ReactionClassifier._judge_one: behavioral_reject=yes → record_rejection(fired)
     → apply_decay → review; =no → 不衰减
  #1 预筛闸: 非疑似负面不调 LLM; 空 fired no-op; 疑似负面提交
  #1 priority>=10 红线 directive record_rejection 后仍被 apply_decay 保护
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_reaction_classifier import (  # noqa: E402
    ReactionClassifier,
    classify_fast,
    has_negative_candidate,
    add_term,
    remove_term,
    list_all,
    _parse_reaction_response,
    reset_default_classifier_for_test,
)
from jarvis_directives import (  # noqa: E402
    DirectiveRegistry,
    Directive,
    STATE_ACTIVE,
    STATE_REVIEW,
)


def _mk_registry(tmpdir):
    return DirectiveRegistry(
        persist_path=os.path.join(tmpdir, 'reg.json'),
        review_path=os.path.join(tmpdir, 'review.json'),
    )


def _mk_directive(did, priority=5):
    return Directive(id=did, text=f'demo {did}',
                     trigger=lambda ctx: True, priority=priority)


# ============================================================
# #2 classify_fast + gate
# ============================================================
class TestClassifyFast(unittest.TestCase):

    def test_semantic_negative_rejected(self):
        self.assertEqual(classify_fast('这不是我想要的'), 'rejected')
        self.assertEqual(classify_fast('你这样不太行啊'), 'rejected')
        self.assertEqual(classify_fast('别提了'), 'rejected')

    def test_positive_engaged(self):
        self.assertEqual(classify_fast('好的谢谢'), 'engaged')
        self.assertEqual(classify_fast(''), 'engaged')

    def test_soft_not_fast_rejected_but_gate_open(self):
        # soft 词 (算了/无所谓) 不在 fast 判 rejected, 但开 LLM 闸 (交精判)
        self.assertEqual(classify_fast('算了，无所谓吧'), 'engaged')
        self.assertTrue(has_negative_candidate('算了，无所谓吧'))

    def test_external_venting_gate_closed(self):
        # 外部情绪不触发 ("烦" != "烦死")
        self.assertFalse(has_negative_candidate('今天天气真烦'))
        self.assertFalse(has_negative_candidate('好的谢谢'))


# ============================================================
# #2 vocab CLI
# ============================================================
class TestVocabCLI(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'reaction_vocab.json')
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump({
                '_meta': {}, 'negative_candidates': ['不对'],
                'strong_correction': [], 'soft': [],
                'ignored_after_min': 8.0, 'history': [], 'review_queue': [],
            }, f, ensure_ascii=False)

    def test_add_remove_roundtrip(self):
        self.assertTrue(add_term('跑题', path=self.path))
        self.assertIn('跑题', list_all(self.path)['negative_candidates'])
        self.assertFalse(add_term('跑题', path=self.path))  # dup → no-op
        self.assertTrue(remove_term('跑题', path=self.path))
        self.assertNotIn('跑题', list_all(self.path)['negative_candidates'])

    def test_add_history_logged(self):
        add_term('搞错', path=self.path)
        hist = list_all(self.path)['history']
        self.assertTrue(any(h.get('term') == '搞错' for h in hist))

    def test_invalid_kind_rejected(self):
        self.assertFalse(add_term('x', kind='bogus', path=self.path))

    def test_strong_correction_kind(self):
        self.assertTrue(add_term('你错了', kind='strong_correction',
                                 path=self.path))
        self.assertIn('你错了', list_all(self.path)['strong_correction'])


# ============================================================
# #2 parse
# ============================================================
class TestParseResponse(unittest.TestCase):

    def test_clean_json_yes(self):
        v, _ = _parse_reaction_response('{"behavioral_reject":"yes","reason":"r"}')
        self.assertEqual(v, 'yes')

    def test_embedded_json_no(self):
        v, _ = _parse_reaction_response('blah {"behavioral_reject":"no"} tail')
        self.assertEqual(v, 'no')

    def test_garbage_unknown(self):
        self.assertEqual(_parse_reaction_response('not json at all')[0],
                         'unknown')

    def test_empty_unknown(self):
        self.assertEqual(_parse_reaction_response('')[0], 'unknown')

    def test_invalid_value_unknown(self):
        self.assertEqual(
            _parse_reaction_response('{"behavioral_reject":"maybe"}')[0],
            'unknown')


# ============================================================
# #1 record_rejection 强闭环
# ============================================================
class TestRecordRejectionClosure(unittest.TestCase):

    def setUp(self):
        reset_default_classifier_for_test()
        self.tmp = tempfile.mkdtemp()
        self.reg = _mk_registry(self.tmp)
        self.reg.register(_mk_directive('d1', priority=5))
        self.kr = MagicMock()
        self.kr.get_openrouter_key.return_value = ('fake', 'label1')
        self.kr.release.return_value = None
        self.rc = ReactionClassifier(key_router=self.kr, registry=self.reg)

    def tearDown(self):
        self.rc.shutdown(wait=True)

    def test_yes_records_rejection_and_reviews(self):
        with patch('jarvis_reaction_classifier.safe_openrouter_call',
                   return_value='{"behavioral_reject":"yes"}'):
            for _ in range(3):
                self.rc._judge_one(sir_input='不对', prev_reply='r',
                                   prev_fired_ids=['d1'])
        self.assertEqual(self.reg.get('d1').rejected, 3)
        self.reg.apply_decay()
        self.assertEqual(self.reg.get('d1').state, STATE_REVIEW)
        self.assertEqual(self.rc.stats['recorded_rejection'], 3)

    def test_no_does_not_record(self):
        with patch('jarvis_reaction_classifier.safe_openrouter_call',
                   return_value='{"behavioral_reject":"no"}'):
            self.rc._judge_one(sir_input='不对', prev_reply='r',
                               prev_fired_ids=['d1'])
        self.assertEqual(self.reg.get('d1').rejected, 0)

    def test_priority_10_protected_from_decay(self):
        self.reg.register(_mk_directive('d_core', priority=10))
        with patch('jarvis_reaction_classifier.safe_openrouter_call',
                   return_value='{"behavioral_reject":"yes"}'):
            for _ in range(3):
                self.rc._judge_one(sir_input='不对', prev_reply='r',
                                   prev_fired_ids=['d_core'])
        self.assertEqual(self.reg.get('d_core').rejected, 3)
        self.reg.apply_decay()
        # 红线: priority>=10 不被 auto-decay (apply_decay:293)
        self.assertEqual(self.reg.get('d_core').state, STATE_ACTIVE)

    def test_multi_fired_all_attributed(self):
        self.reg.register(_mk_directive('d2', priority=6))
        with patch('jarvis_reaction_classifier.safe_openrouter_call',
                   return_value='{"behavioral_reject":"yes"}'):
            self.rc._judge_one(sir_input='答非所问', prev_reply='r',
                               prev_fired_ids=['d1', 'd2'])
        self.assertEqual(self.reg.get('d1').rejected, 1)
        self.assertEqual(self.reg.get('d2').rejected, 1)


# ============================================================
# #1 预筛闸 + 异步提交
# ============================================================
class TestGatePrefilter(unittest.TestCase):

    def setUp(self):
        reset_default_classifier_for_test()
        self.tmp = tempfile.mkdtemp()
        self.reg = _mk_registry(self.tmp)
        self.reg.register(_mk_directive('d1'))
        self.kr = MagicMock()
        self.kr.get_openrouter_key.return_value = ('fake', 'label1')
        self.kr.release.return_value = None
        self.rc = ReactionClassifier(key_router=self.kr, registry=self.reg)

    def tearDown(self):
        self.rc.shutdown(wait=True)

    def test_non_negative_input_no_llm(self):
        with patch('jarvis_reaction_classifier.safe_openrouter_call',
                   return_value='{"behavioral_reject":"yes"}') as m:
            self.rc.judge_behavioral_reject_async(
                sir_input='好的谢谢', prev_reply='r', prev_fired_ids=['d1'])
            self.rc.shutdown(wait=True)
        self.assertEqual(self.rc.stats['submitted'], 0)
        m.assert_not_called()
        self.assertEqual(self.reg.get('d1').rejected, 0)

    def test_empty_fired_no_submit(self):
        self.rc.judge_behavioral_reject_async(
            sir_input='不对', prev_reply='r', prev_fired_ids=[])
        self.assertEqual(self.rc.stats['submitted'], 0)

    def test_negative_input_submits(self):
        with patch('jarvis_reaction_classifier.safe_openrouter_call',
                   return_value='{"behavioral_reject":"no"}'):
            self.rc.judge_behavioral_reject_async(
                sir_input='不对', prev_reply='r', prev_fired_ids=['d1'])
            self.rc.shutdown(wait=True)
        self.assertEqual(self.rc.stats['submitted'], 1)

    def test_no_registry_no_submit(self):
        rc2 = ReactionClassifier(key_router=self.kr, registry=None)
        rc2.judge_behavioral_reject_async(
            sir_input='不对', prev_reply='r', prev_fired_ids=['d1'])
        self.assertEqual(rc2.stats['submitted'], 0)
        rc2.shutdown(wait=True)


# ============================================================
# #2 ignored sweep (inner_voice_track.mark_stale_pending_main_replies_ignored)
# ============================================================
def _fresh_track(tmpdir):
    """fresh InnerVoiceTrack with injected tmp jsonl (零 prod 污染)."""
    from jarvis_inner_voice_track import InnerVoiceTrack
    return InnerVoiceTrack(persist_path=os.path.join(tmpdir, 'iv.jsonl'))


class TestIgnoredSweep(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _add_pending(self, track, age_min, reaction='pending'):
        track.append(
            source='self_reflection', intent='noting',
            content='i replied to sir: "x"', urgency=0.3, wants_voice=False,
            meta={'kind': 'main_reply', 'sir_reaction': reaction},
            ts=time.time() - age_min * 60.0,
        )

    def test_stale_pending_marked_ignored(self):
        t = _fresh_track(self.tmp)
        self._add_pending(t, age_min=15)  # 老于 8min 阈值
        n = t.mark_stale_pending_main_replies_ignored(
            older_than_min=8.0, max_age_min=60.0)
        self.assertEqual(n, 1)
        self.assertEqual(t._buffer[-1].meta['sir_reaction'], 'ignored')

    def test_fresh_pending_not_marked(self):
        t = _fresh_track(self.tmp)
        self._add_pending(t, age_min=2)  # 才 2min < 8min 阈值
        n = t.mark_stale_pending_main_replies_ignored(older_than_min=8.0)
        self.assertEqual(n, 0)
        self.assertEqual(t._buffer[-1].meta['sir_reaction'], 'pending')

    def test_too_old_not_marked(self):
        t = _fresh_track(self.tmp)
        self._add_pending(t, age_min=90)  # 超 max_age 60min
        n = t.mark_stale_pending_main_replies_ignored(
            older_than_min=8.0, max_age_min=60.0)
        self.assertEqual(n, 0)

    def test_already_reacted_not_marked(self):
        t = _fresh_track(self.tmp)
        self._add_pending(t, age_min=15, reaction='engaged')
        n = t.mark_stale_pending_main_replies_ignored(older_than_min=8.0)
        self.assertEqual(n, 0)
        self.assertEqual(t._buffer[-1].meta['sir_reaction'], 'engaged')


if __name__ == '__main__':
    unittest.main(verbosity=2)
