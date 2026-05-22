# -*- coding: utf-8 -*-
"""[P5-fix24-concern-dismiss / 2026-05-22] 语言控制 concern (Sir 18:42 真痛点)

Sir 真测痛点 18:42:
> "Cursor subscription payment failed earlier; perhaps worth a look..."
> "这件事我跟他说了很多次不要在意了, 他还是提, 感觉是我们没有语言控制
>  长期关心的手段, 帮我分析下日志, 一起修复"

Root cause:
- sir_cursor_payment severity=1.0, triggers_proactive=True, missed_count=37,
  aligned_count=0 — Sir 37 次拒答, system 仍未学到
- 17:17 主脑已说 "Understood, Sir, I shall stop monitoring the Cursor payment
  status..." 但 concerns.json 没真改 (嘴上停了, state 仍 active)
- ProactiveCare 每 60s tick 仍 push concern=sir_cursor_payment urgency=0.91

修法 (3 个文件):
1. jarvis_concerns.py: 加 ConcernsLedger.dismiss / reactivate API
   - dismiss: triggers_proactive=False + severity floor (0.3) + signal + SWM event
   - reactivate: 复原 triggers_proactive=True, severity 不动
2. jarvis_chat_bypass.py: 加 'concerns' organ FAST_CALL handler
   - dismiss / reactivate command with params={"id":..., "reason":...}
3. jarvis_directives.py: 加 concern_dismissal_judge directive
   - 触发 vocab 持久化 memory_pool/concern_dismiss_vocab.json
   - 教主脑 emit FAST_CALL 真改 state (不只是嘴上答应)
4. scripts/concerns_dump.py: 加 --dismiss / --reactivate CLI
5. 热修 sir_cursor_payment 当前 state (triggers_proactive False, severity 0.3)
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_concerns import (
    Concern,
    ConcernsLedger,
    STATE_ACTIVE,
)
from jarvis_directives import (
    _trigger_concern_dismissal,
    DirectiveContext,
    get_concern_dismiss_patterns,
)


def _make_ctx(user_input: str, tier: str = 'CHAT'):
    """构造 DirectiveContext for trigger test."""
    return DirectiveContext(
        user_input=user_input,
        tier=tier,
        stm=[],
    )


def _make_ledger():
    """临时 ledger, 隔离 disk."""
    tmpdir = tempfile.mkdtemp()
    p = os.path.join(tmpdir, 'concerns.json')
    rp = os.path.join(tmpdir, 'review.json')
    L = ConcernsLedger(persist_path=p, review_path=rp)
    return L, tmpdir


class TestDismissAPI(unittest.TestCase):
    """ConcernsLedger.dismiss / reactivate API."""

    def setUp(self):
        self.L, self.tmpdir = _make_ledger()
        c = Concern(id='test_concern',
                      what_i_watch='x', why_i_care='y',
                      severity=1.0)
        self.L.register(c)

    def test_dismiss_sets_triggers_proactive_false(self):
        self.assertTrue(self.L.concerns['test_concern'].triggers_proactive)
        ok = self.L.dismiss('test_concern', reason='Sir 不在意了')
        self.assertTrue(ok)
        self.assertFalse(self.L.concerns['test_concern'].triggers_proactive)

    def test_dismiss_caps_severity_to_floor(self):
        """severity 1.0 → dismiss 后 ≤ 0.3 (默认 floor)."""
        ok = self.L.dismiss('test_concern', reason='x')
        self.assertTrue(ok)
        self.assertLessEqual(self.L.concerns['test_concern'].severity, 0.3)

    def test_dismiss_records_signal(self):
        ok = self.L.dismiss('test_concern', reason='Sir 不在意')
        self.assertTrue(ok)
        signals = self.L.concerns['test_concern'].recent_signals
        self.assertEqual(len(signals), 1)
        self.assertIn('dismiss', signals[-1]['what'])
        self.assertIn('Sir 不在意', signals[-1]['what'])

    def test_dismiss_writes_notes_for_self(self):
        ok = self.L.dismiss('test_concern', reason='不重要', source='sir_voice')
        self.assertTrue(ok)
        notes = self.L.concerns['test_concern'].notes_for_self
        self.assertIn('dismissed', notes)
        self.assertIn('不重要', notes)

    def test_dismiss_returns_false_for_missing(self):
        ok = self.L.dismiss('does_not_exist', reason='x')
        self.assertFalse(ok)

    def test_dismiss_state_unchanged(self):
        """dismiss 是软关闭, state 仍 active (Sir 后续问起仍可答)."""
        ok = self.L.dismiss('test_concern', reason='x')
        self.assertTrue(ok)
        self.assertEqual(self.L.concerns['test_concern'].state, STATE_ACTIVE)


class TestReactivateAPI(unittest.TestCase):
    """ConcernsLedger.reactivate."""

    def setUp(self):
        self.L, self.tmpdir = _make_ledger()
        c = Concern(id='test_concern',
                      what_i_watch='x', why_i_care='y',
                      severity=0.3,
                      triggers_proactive=False)
        self.L.register(c)

    def test_reactivate_sets_triggers_proactive_true(self):
        ok = self.L.reactivate('test_concern', reason='重新盯着')
        self.assertTrue(ok)
        self.assertTrue(self.L.concerns['test_concern'].triggers_proactive)

    def test_reactivate_does_not_change_severity(self):
        """reactivate 仅切 trigger, severity 不动 (后续真实 signal 重 calibrate)."""
        old_sev = self.L.concerns['test_concern'].severity
        ok = self.L.reactivate('test_concern', reason='x')
        self.assertTrue(ok)
        self.assertEqual(self.L.concerns['test_concern'].severity, old_sev)

    def test_reactivate_records_signal(self):
        ok = self.L.reactivate('test_concern', reason='想重新监控')
        self.assertTrue(ok)
        signals = self.L.concerns['test_concern'].recent_signals
        self.assertEqual(len(signals), 1)
        self.assertIn('reactivated', signals[-1]['what'])


class TestDismissPersistence(unittest.TestCase):
    """dismiss 后 persist → load 仍正确."""

    def test_dismiss_survives_persist_load(self):
        L, tmpdir = _make_ledger()
        c = Concern(id='persisted', what_i_watch='x', why_i_care='y',
                      severity=1.0)
        L.register(c)
        L.dismiss('persisted', reason='Sir 不在意')
        L.persist()

        # 新 ledger load
        L2 = ConcernsLedger(persist_path=L.persist_path,
                              review_path=L.review_path)
        L2.load()
        c2 = L2.get('persisted')
        self.assertIsNotNone(c2)
        self.assertFalse(c2.triggers_proactive)
        self.assertLessEqual(c2.severity, 0.3)


class TestConcernDismissTrigger(unittest.TestCase):
    """jarvis_directives._trigger_concern_dismissal — vocab match."""

    def test_chinese_dismiss_phrase_triggers(self):
        for phrase in ['不在意了', '别再提了', '不用管', '算了', '不重要',
                          '别监控了', '不用监控了']:
            ctx = _make_ctx(f'Cursor 订阅 {phrase}')
            self.assertTrue(_trigger_concern_dismissal(ctx),
                              f'should fire for: {phrase}')

    def test_english_dismiss_phrase_triggers(self):
        for phrase in ['drop it', 'let it go', "don't worry about", 'never mind']:
            ctx = _make_ctx(f'just {phrase} please')
            self.assertTrue(_trigger_concern_dismissal(ctx),
                              f'should fire for: {phrase}')

    def test_neutral_chat_does_not_trigger(self):
        for phrase in ['你好', '今天天气怎么样', 'open dashboard',
                          'tell me about the weather']:
            ctx = _make_ctx(phrase)
            self.assertFalse(_trigger_concern_dismissal(ctx),
                                f'should NOT fire for: {phrase}')

    def test_empty_input_does_not_trigger(self):
        ctx = _make_ctx('')
        self.assertFalse(_trigger_concern_dismissal(ctx))


class TestVocabPersistence(unittest.TestCase):
    """vocab 持久化 (准则 6.5)."""

    def test_seed_patterns_loaded_when_no_json(self):
        patterns = get_concern_dismiss_patterns()
        self.assertGreater(len(patterns), 5)
        self.assertIn('不在意', patterns)
        self.assertIn('drop it', patterns)


class TestCursorPaymentHotfix(unittest.TestCase):
    """热修验证: 真实 concerns.json 里 sir_cursor_payment 应已被 dismiss."""

    def test_sir_cursor_payment_dismissed(self):
        """Sir 18:42 真痛点对应的 concern 应已软关闭."""
        p = os.path.join('memory_pool', 'concerns.json')
        if not os.path.exists(p):
            self.skipTest('concerns.json not present (CI env)')
        with open(p, 'r', encoding='utf-8') as f:
            d = json.load(f)
        if 'sir_cursor_payment' not in d:
            self.skipTest('sir_cursor_payment not in concerns.json (CI env)')
        c = d['sir_cursor_payment']
        self.assertFalse(c.get('triggers_proactive', True),
                          'P5-fix24-aux: sir_cursor_payment should be dismissed')
        self.assertLessEqual(c.get('severity', 1.0), 0.3,
                              'P5-fix24-aux: severity should be ≤ 0.3 after dismiss')


if __name__ == '__main__':
    unittest.main()
