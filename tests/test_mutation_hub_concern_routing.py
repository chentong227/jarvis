"""[Reshape / 2026-05-24] Test mutation hub 宽容 ConcernsLedger routing.

Sir 12:14 真测痛点:
  ❌ field=sir_hydration_habit.current_count → layer=unknown (no router)
  ❌ field=ledger.sir_hydration_habit → layer=unknown

修后:
  ✅ field=sir_hydration_habit.current_count → layer=ConcernsLedger, dispatch record_user_feedback
  ✅ field=ledger.sir_hydration_habit → layer=ConcernsLedger
  ✅ field=concerns.sir_hydration_habit.current → record_user_feedback
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from jarvis_memory_hub import _detect_target_layer


class TestDetectTargetLayer(unittest.TestCase):
    def test_concerns_prefix(self):
        self.assertEqual(_detect_target_layer('concerns.sir_X.current'), 'ConcernsLedger')
        self.assertEqual(_detect_target_layer('concern.sir_X'), 'ConcernsLedger')

    def test_ledger_prefix_alias(self):
        # 主脑常写
        self.assertEqual(_detect_target_layer('ledger.sir_hydration_habit'), 'ConcernsLedger')
        self.assertEqual(_detect_target_layer('ledger.sir_pomodoro_compliance.current'),
                         'ConcernsLedger')

    def test_bare_sir_X_routes_to_concerns(self):
        # 主脑常写: 裸 concern_id
        self.assertEqual(_detect_target_layer('sir_hydration_habit'), 'ConcernsLedger')
        self.assertEqual(_detect_target_layer('sir_hydration_habit.current_count'),
                         'ConcernsLedger')
        self.assertEqual(_detect_target_layer('sir_pomodoro_compliance'), 'ConcernsLedger')

    def test_sir_dot_prefix_still_profile(self):
        # 'sir.X' 是 profile, 不能跟 'sir_X' 撞 (regression test)
        self.assertEqual(_detect_target_layer('sir.work_rhythms'), 'ProfileCard')

    def test_profile_unchanged(self):
        self.assertEqual(_detect_target_layer('profile.work_rhythms'), 'ProfileCard')
        self.assertEqual(_detect_target_layer('biographic.height'), 'ProfileCard')

    def test_relational_unchanged(self):
        self.assertEqual(_detect_target_layer('inside_joke.update.j1.phrase'),
                         'RelationalStateStore')

    def test_promise_commitment_unchanged(self):
        self.assertEqual(_detect_target_layer('promise.fulfill.abc'), 'PromiseLog')
        self.assertEqual(_detect_target_layer('commitment.cancel.def'), 'CommitmentWatcher')

    def test_empty_returns_unknown(self):
        self.assertEqual(_detect_target_layer(''), 'unknown')

    def test_garbage_returns_unknown(self):
        self.assertEqual(_detect_target_layer('random.gibberish'), 'unknown')


class TestProgressFieldDispatch(unittest.TestCase):
    """progress-style attr (current / current_count / count / progress / amount / done /
    daily_progress) 应该 dispatch 到 record_user_feedback, 不 update_concern_field.

    需要 mock ledger 验证.
    """

    def setUp(self):
        self.calls_record_feedback = []
        self.calls_update_field = []

        # mock ledger
        class _MockLedger:
            def __init__(_self):
                _self.parent = self

            def record_user_feedback(_self, cid, raw, judgement):
                self.calls_record_feedback.append((cid, raw, judgement))
                return True

            def update_concern_field(_self, concern_id, field, new_value,
                                     source='', turn_id='', reason=''):
                self.calls_update_field.append((concern_id, field, new_value))
                return True, '', None

        # mock nerve
        class _MockNerve:
            def __init__(_self):
                _self.concerns_ledger = _MockLedger()

        self.nerve = _MockNerve()

    def _call_update(self, field_path, new_value):
        from jarvis_memory_hub import MemoryMutationGateway
        gw = MemoryMutationGateway()
        return gw.update_sir_field(
            field_path=field_path,
            new_value=new_value,
            source='test',
            nerve=self.nerve,
        )

    def test_current_count_goes_to_record_feedback(self):
        rcpt = self._call_update('sir_hydration_habit.current_count', 3)
        self.assertTrue(rcpt.ok, f'Expected ok, got error: {rcpt.error}')
        self.assertEqual(len(self.calls_record_feedback), 1)
        self.assertEqual(len(self.calls_update_field), 0)
        cid, raw, j = self.calls_record_feedback[0]
        self.assertEqual(cid, 'sir_hydration_habit')
        self.assertEqual(j.get('progress', {}).get('current'), 3)

    def test_current_goes_to_record_feedback(self):
        rcpt = self._call_update('concerns.sir_hydration_habit.current', 5)
        self.assertTrue(rcpt.ok)
        self.assertEqual(len(self.calls_record_feedback), 1)
        cid, raw, j = self.calls_record_feedback[0]
        self.assertEqual(cid, 'sir_hydration_habit')

    def test_ledger_prefix_with_current(self):
        rcpt = self._call_update('ledger.sir_hydration_habit.current', 8)
        self.assertTrue(rcpt.ok)
        self.assertEqual(len(self.calls_record_feedback), 1)

    def test_severity_goes_to_update_field(self):
        # severity NOT in progress-style list → update_concern_field
        rcpt = self._call_update('concerns.sir_hydration_habit.severity', 0.5)
        self.assertTrue(rcpt.ok)
        self.assertEqual(len(self.calls_update_field), 1)
        cid, field, val = self.calls_update_field[0]
        self.assertEqual(cid, 'sir_hydration_habit')
        self.assertEqual(field, 'severity')


if __name__ == '__main__':
    unittest.main()
