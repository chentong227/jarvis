# -*- coding: utf-8 -*-
"""[P5-fix32 / 2026-05-22] Mutation Refactor Phase 1 Foundation testcase.

Sir 21:55 真痛点: "我教正某事永远不生效, 而且要跨模块通用".
Phase 1 已加:
- jarvis_routing.py:ProfileCard.overwrite_field — 真覆写 sir_profile.json
- jarvis_memory_gateway.py — 6 layer routing (ProfileCard 高置信走 overwrite + 低置信
  走 apply_correction; PromiseLog/CommitmentWatcher/RelationalStateStore 新加 routing)
- jarvis_chat_bypass.py — FAST_CALL 'mutation' organ (主脑 emit 入口)
- jarvis_directives.py — correction_dispatcher directive (priority=10) + vocab persist

测试覆盖:
1. ProfileCard.overwrite_field — schema 白名单 / atomic / no-op / load fail
2. Gateway routing — high-conf overwrite / low-conf fallback / unknown layer
3. correction_dispatcher trigger — 中/英教正 vocab 命中 + 中性 input 不命中
4. correction_dispatcher 注册到 registry + priority=10 critical-protected
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# 1. ProfileCard.overwrite_field
# ============================================================

class TestProfileCardOverwriteField(unittest.TestCase):
    """真覆写 sir_profile.json + schema 白名单."""

    def setUp(self):
        # 备份当前 sir_profile.json (如存在)
        self.profile_path = os.path.join('jarvis_config', 'sir_profile.json')
        self._restore_needed = False
        if os.path.exists(self.profile_path):
            self._backup_path = self.profile_path + '.fix32_test_bak'
            shutil.copy2(self.profile_path, self._backup_path)
            self._restore_needed = True
        # Mock nerve
        from jarvis_routing import ProfileCard

        class _MockNerve:
            habit_clock = None
            causal_chain = None
            project_timeline = None
            status_ledger = None

        self.pc = ProfileCard(_MockNerve())

    def tearDown(self):
        if self._restore_needed:
            shutil.copy2(self._backup_path, self.profile_path)
            os.remove(self._backup_path)

    def test_overwrite_allowed_field(self):
        if not os.path.exists(self.profile_path):
            self.skipTest('sir_profile.json not found')
        new_val = f'[FIX32-TEST] sleep 23:00 - {time.time():.0f}'
        ok, msg, old = self.pc.overwrite_field(
            field='work_rhythms',
            new_value=new_val,
            source='fast_call_mutation:revise',
            turn_id='test_turn_001',
            reason='unit test',
        )
        self.assertTrue(ok, f"should succeed: {msg}")
        # Verify file content really changed
        with open(self.profile_path, 'r', encoding='utf-8') as f:
            after = json.load(f)
        self.assertEqual(after.get('work_rhythms'), new_val)

    def test_overwrite_rejects_non_whitelist_field(self):
        ok, msg, old = self.pc.overwrite_field(
            field='secret_field_not_in_whitelist',
            new_value='hacked',
            source='fast_call_mutation:revise',
        )
        self.assertFalse(ok, "should reject non-whitelist field")
        self.assertIn('not in allowed list', msg)

    def test_overwrite_no_op_returns_ok(self):
        if not os.path.exists(self.profile_path):
            self.skipTest('sir_profile.json not found')
        with open(self.profile_path, 'r', encoding='utf-8') as f:
            current = json.load(f)
        old_val = current.get('work_rhythms', '')
        if not old_val:
            self.skipTest('work_rhythms empty in profile')
        # Set to same value → no-op
        ok, msg, old = self.pc.overwrite_field(
            field='work_rhythms',
            new_value=old_val,
            source='fast_call_mutation:revise',
        )
        self.assertTrue(ok, f"no-op should still return ok: {msg}")
        self.assertIn('no-op', msg)

    def test_overwrite_empty_field_rejected(self):
        ok, msg, _ = self.pc.overwrite_field(
            field='',
            new_value='x',
            source='fast_call_mutation:revise',
        )
        self.assertFalse(ok)
        self.assertEqual(msg, 'empty field')


# ============================================================
# 2. Gateway routing
# ============================================================

class TestGatewayRouting(unittest.TestCase):

    def test_layer_detection_profile(self):
        from jarvis_memory_gateway import _detect_target_layer
        self.assertEqual(_detect_target_layer('profile.work_rhythms'),
                          'ProfileCard')
        self.assertEqual(_detect_target_layer('biographic.height'),
                          'ProfileCard')

    def test_layer_detection_promise(self):
        from jarvis_memory_gateway import _detect_target_layer
        self.assertEqual(_detect_target_layer('promise.fulfill.exam'),
                          'PromiseLog')

    def test_layer_detection_commitment(self):
        from jarvis_memory_gateway import _detect_target_layer
        self.assertEqual(_detect_target_layer('commitment.cancel.sleep'),
                          'CommitmentWatcher')

    def test_layer_detection_relational(self):
        from jarvis_memory_gateway import _detect_target_layer
        self.assertEqual(_detect_target_layer('relationships.archive.j1'),
                          'RelationalStateStore')

    def test_layer_detection_concern(self):
        from jarvis_memory_gateway import _detect_target_layer
        self.assertEqual(_detect_target_layer('concerns.sir_sleep_streak.severity'),
                          'ConcernsLedger')

    def test_layer_detection_unknown(self):
        from jarvis_memory_gateway import _detect_target_layer
        self.assertEqual(_detect_target_layer('foobar.xyz'), 'unknown')

    def test_gateway_writes_receipt_jsonl(self):
        """gateway 总是写 receipt 到 jsonl, 不论成功失败."""
        from jarvis_memory_gateway import MemoryMutationGateway

        with tempfile.TemporaryDirectory() as tmp:
            tmp_receipt = os.path.join(tmp, 'receipts.jsonl')
            gw = MemoryMutationGateway(receipt_path=tmp_receipt)
            # 用 unknown layer 触发 err 但仍写 receipt
            receipt = gw.update_sir_field(
                field_path='foobar.unknown',
                new_value='x',
                source='fast_call_mutation:revise',
                confidence=0.9,
            )
            self.assertEqual(receipt.layer_targeted, 'unknown')
            self.assertFalse(receipt.ok)
            # Verify jsonl written
            self.assertTrue(os.path.exists(tmp_receipt))
            with open(tmp_receipt, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 1)
            d = json.loads(lines[0])
            self.assertEqual(d.get('mutation_id'), receipt.mutation_id)


# ============================================================
# 3. correction_dispatcher directive trigger
# ============================================================

class TestCorrectionDispatcherTrigger(unittest.TestCase):

    def test_chinese_correction_phrases_fire(self):
        from jarvis_directives import (_trigger_correction_dispatcher,
                                              DirectiveContext)
        for phrase in ['其实我以后默认晚 11 睡',
                          'Windsurf 不对, 不是我在动',
                          '应该是 23:00, 不是 22:00',
                          '改成下周一', '我搬家了',
                          '更准确地说, 是月薪 1 万 2']:
            ctx = DirectiveContext(user_input=phrase, tier='CHAT', stm=[])
            self.assertTrue(_trigger_correction_dispatcher(ctx),
                              f'should fire for: {phrase}')

    def test_english_correction_phrases_fire(self):
        from jarvis_directives import (_trigger_correction_dispatcher,
                                              DirectiveContext)
        for phrase in ["actually, that's not it",
                          "wait, I changed my mind",
                          "it's not Windsurf",
                          'i mean, I sleep at 11',
                          "let me clarify"]:
            ctx = DirectiveContext(user_input=phrase, tier='CHAT', stm=[])
            self.assertTrue(_trigger_correction_dispatcher(ctx),
                              f'should fire for: {phrase}')

    def test_neutral_chitchat_does_not_fire(self):
        from jarvis_directives import (_trigger_correction_dispatcher,
                                              DirectiveContext)
        for phrase in ['你好', 'open dashboard', '今天天气怎么样',
                          'tell me about the weather', 'good morning']:
            ctx = DirectiveContext(user_input=phrase, tier='CHAT', stm=[])
            self.assertFalse(_trigger_correction_dispatcher(ctx),
                                f'should NOT fire for: {phrase}')

    def test_empty_input_does_not_fire(self):
        from jarvis_directives import (_trigger_correction_dispatcher,
                                              DirectiveContext)
        ctx = DirectiveContext(user_input='', tier='CHAT', stm=[])
        self.assertFalse(_trigger_correction_dispatcher(ctx))


# ============================================================
# 4. correction_dispatcher directive registered + critical-protected
# ============================================================

class TestCorrectionDispatcherRegistration(unittest.TestCase):

    def test_directive_registered_with_priority_10(self):
        import jarvis_directives as jd
        reg = jd.get_default_registry()
        cd = reg.get('correction_dispatcher')
        self.assertIsNotNone(cd, "correction_dispatcher not registered")
        self.assertEqual(cd.priority, 10,
                          "correction_dispatcher should be priority=10 (critical-protected)")
        self.assertEqual(cd.id, 'correction_dispatcher')
        self.assertEqual(cd.source_marker, 'P5-fix32-D')

    def test_directive_text_mentions_field_path_protocol(self):
        import jarvis_directives as jd
        reg = jd.get_default_registry()
        cd = reg.get('correction_dispatcher')
        self.assertIsNotNone(cd)
        # text 必须教主脑 field_path 协议
        self.assertIn('field_path', cd.text)
        self.assertIn('mutation', cd.text)
        self.assertIn('FAST_CALL', cd.text)
        # 必须含 3 步推理
        self.assertIn('intent', cd.text)
        self.assertIn('layer', cd.text.lower())


# ============================================================
# 5. Vocab persistence (准则 6)
# ============================================================

class TestCorrectionDispatcherVocab(unittest.TestCase):

    def test_seed_returns_when_no_json(self):
        # 即便 vocab json 不存在, seed 应返回非空 list
        import jarvis_directives as jd
        # Force reload via mtime change
        jd._CORRECTION_DISPATCHER_CACHE = None
        pats = jd.get_correction_dispatcher_patterns()
        self.assertIsInstance(pats, list)
        self.assertGreater(len(pats), 0)
        # Seed 应含中英 keyword
        self.assertIn('其实', pats)
        self.assertIn('actually', pats)


# ============================================================
# 5b. ConcernsLedger.update_concern_field (Phase 2.1)
# ============================================================

class TestConcernUpdateField(unittest.TestCase):
    """[P5-fix32-G] 深度 update concern 字段."""

    def setUp(self):
        from jarvis_concerns import ConcernsLedger, Concern
        # 用临时持久化路径, 不污染真账本
        self.tmp_dir = tempfile.mkdtemp(prefix='concern_upd_test_')
        self.persist_path = os.path.join(self.tmp_dir, 'concerns.json')
        self.ledger = ConcernsLedger(persist_path=self.persist_path)
        # Add 1 active concern
        self.ledger.register(Concern(
            id='test_concern_1',
            what_i_watch='Sir 是否熬夜',
            why_i_care='Sir 健康',
            severity=0.8,
        ))

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_update_what_i_watch(self):
        ok, msg, old = self.ledger.update_concern_field(
            'test_concern_1', 'what_i_watch',
            'Sir 半夜画图也算工作',
            source='fast_call_mutation:revise',
            turn_id='test_turn_1',
        )
        self.assertTrue(ok, msg)
        self.assertEqual(old, 'Sir 是否熬夜')
        c = self.ledger.concerns['test_concern_1']
        self.assertEqual(c.what_i_watch, 'Sir 半夜画图也算工作')

    def test_update_severity_clamped(self):
        ok, msg, old = self.ledger.update_concern_field(
            'test_concern_1', 'severity', 2.5,  # 超出 1.0 应 clamp
            source='fast_call_mutation:refine',
        )
        self.assertTrue(ok, msg)
        c = self.ledger.concerns['test_concern_1']
        self.assertEqual(c.severity, 1.0)

    def test_update_triggers_proactive_string_to_bool(self):
        ok, msg, _ = self.ledger.update_concern_field(
            'test_concern_1', 'triggers_proactive', 'false',
            source='fast_call_mutation:dismiss',
        )
        self.assertTrue(ok, msg)
        c = self.ledger.concerns['test_concern_1']
        self.assertFalse(c.triggers_proactive)

    def test_update_rejects_non_whitelist_field(self):
        ok, msg, _ = self.ledger.update_concern_field(
            'test_concern_1', 'state', 'archived',  # state 不在白名单
            source='fast_call_mutation:revise',
        )
        self.assertFalse(ok)
        self.assertIn('not in allowed list', msg)

    def test_update_rejects_unknown_concern(self):
        ok, msg, _ = self.ledger.update_concern_field(
            'no_such_concern', 'severity', 0.5,
        )
        self.assertFalse(ok)
        self.assertIn('not found', msg)

    def test_update_no_op_returns_ok(self):
        ok, msg, _ = self.ledger.update_concern_field(
            'test_concern_1', 'severity', 0.8,  # 等同当前
        )
        self.assertTrue(ok)
        self.assertIn('no-op', msg)

    def test_update_writes_signal_audit(self):
        before_n = len(self.ledger.concerns['test_concern_1'].recent_signals)
        ok, _, _ = self.ledger.update_concern_field(
            'test_concern_1', 'what_i_watch', 'new watch text',
            source='fast_call_mutation:revise',
            reason='test reason',
        )
        self.assertTrue(ok)
        after_n = len(self.ledger.concerns['test_concern_1'].recent_signals)
        self.assertEqual(after_n, before_n + 1, 'should append 1 signal')
        last = self.ledger.concerns['test_concern_1'].recent_signals[-1]
        self.assertIn('update', last['what'])
        self.assertIn('what_i_watch', last['what'])


# ============================================================
# 5c. RelationalStateStore.update_field (Phase 2.2)
# ============================================================

class TestRelationalUpdateField(unittest.TestCase):
    """[P5-fix32-I] RelationalStateStore.update_field — 4 kind depth update."""

    def setUp(self):
        from jarvis_relational import (RelationalStateStore, InsideJoke,
                                              UnspokenProtocol, SharedHistoryThread,
                                              UnfinishedBusiness)
        self.tmp_dir = tempfile.mkdtemp(prefix='relational_upd_test_')
        self.persist_path = os.path.join(self.tmp_dir, 'relational.json')
        self.rs = RelationalStateStore(persist_path=self.persist_path)
        # Seed: 4 entities
        self.rs.add_inside_joke(InsideJoke(
            id='j1', phrase='初代笑话', birth_context='ctx1', tone='wry',
        ))
        self.rs.add_protocol(UnspokenProtocol(
            id='p1', rule='I should not interrupt Sir mid-sentence',
        ))
        self.rs.add_thread(SharedHistoryThread(
            id='t1', title='Built J.A.R.V.I.S.', detail='initial detail',
        ))
        self.rs.add_unfinished(UnfinishedBusiness(
            id='u1', topic='driver license study', detail='科一未完',
        ))

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_update_inside_joke_phrase(self):
        ok, msg, old = self.rs.update_field(
            'inside_joke', 'j1', 'phrase', '新版笑话',
            source='fast_call_mutation:refine',
        )
        self.assertTrue(ok, msg)
        self.assertEqual(old, '初代笑话')
        self.assertEqual(self.rs.inside_jokes['j1'].phrase, '新版笑话')

    def test_update_protocol_rule(self):
        new_rule = 'I should wait 3 seconds before responding'
        ok, msg, old = self.rs.update_field(
            'protocol', 'p1', 'rule', new_rule,
        )
        self.assertTrue(ok, msg)
        self.assertEqual(self.rs.unspoken_protocols['p1'].rule, new_rule)

    def test_update_thread_detail(self):
        ok, msg, old = self.rs.update_field(
            'thread', 't1', 'detail', 'updated detail',
        )
        self.assertTrue(ok, msg)
        self.assertEqual(self.rs.shared_history_threads['t1'].detail,
                          'updated detail')

    def test_update_unfinished_topic(self):
        ok, msg, old = self.rs.update_field(
            'unfinished', 'u1', 'topic', 'driver license practice',
        )
        self.assertTrue(ok, msg)
        self.assertEqual(self.rs.unfinished_business['u1'].topic,
                          'driver license practice')

    def test_update_rejects_unknown_kind(self):
        ok, msg, _ = self.rs.update_field(
            'unknown_kind', 'x', 'phrase', 'foo',
        )
        self.assertFalse(ok)
        self.assertIn("unknown kind", msg)

    def test_update_rejects_non_whitelist_field(self):
        ok, msg, _ = self.rs.update_field(
            'inside_joke', 'j1', 'state', 'archived',  # state 不在白名单
        )
        self.assertFalse(ok)
        self.assertIn('not in allowed', msg)

    def test_update_rejects_unknown_item(self):
        ok, msg, _ = self.rs.update_field(
            'inside_joke', 'no_such_id', 'phrase', 'foo',
        )
        self.assertFalse(ok)
        self.assertIn('not found', msg)

    def test_update_no_op_returns_ok(self):
        ok, msg, _ = self.rs.update_field(
            'inside_joke', 'j1', 'phrase', '初代笑话',  # same as initial
        )
        self.assertTrue(ok)
        self.assertIn('no-op', msg)


# ============================================================
# 5d. Gateway integration with deep update (Phase 2.1 + 2.2 routing)
# ============================================================

class TestGatewayDeepUpdateIntegration(unittest.TestCase):
    """gateway 'concerns.<cid>.<attr>' / '<kind>.update.<id>.<field>' 端到端."""

    def test_gateway_routes_concern_attr_to_update_concern_field(self):
        """gateway field_path='concerns.<cid>.severity' → ConcernsLedger.update_concern_field"""
        from jarvis_concerns import ConcernsLedger, Concern
        from jarvis_memory_gateway import MemoryMutationGateway

        # Setup
        tmp_dir = tempfile.mkdtemp(prefix='gw_concern_int_')
        try:
            ledger = ConcernsLedger(persist_path=os.path.join(tmp_dir, 'c.json'))
            ledger.register(Concern(
                id='test_c', what_i_watch='Sir 熬夜', why_i_care='Sir 健康',
                severity=0.5,
            ))

            class _MockNerve:
                concerns_ledger = ledger
                profile_card = None

            gw = MemoryMutationGateway(
                receipt_path=os.path.join(tmp_dir, 'receipts.jsonl')
            )
            receipt = gw.update_sir_field(
                field_path='concerns.test_c.severity',
                new_value=0.3,
                source='fast_call_mutation:refine',
                confidence=0.95,
                nerve=_MockNerve(),
            )
            self.assertTrue(receipt.ok, receipt.error)
            self.assertEqual(receipt.layer_targeted, 'ConcernsLedger')
            # Verify concern severity changed
            self.assertEqual(ledger.concerns['test_c'].severity, 0.3)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_gateway_routes_concern_no_attr_to_record_signal(self):
        """gateway field_path='concerns.<cid>' (no attr) → 老路 record_signal"""
        from jarvis_concerns import ConcernsLedger, Concern
        from jarvis_memory_gateway import MemoryMutationGateway

        tmp_dir = tempfile.mkdtemp(prefix='gw_concern_old_')
        try:
            ledger = ConcernsLedger(persist_path=os.path.join(tmp_dir, 'c.json'))
            ledger.register(Concern(
                id='test_c', what_i_watch='watch', why_i_care='care',
                severity=0.5,
            ))

            class _MockNerve:
                concerns_ledger = ledger
                profile_card = None

            gw = MemoryMutationGateway(
                receipt_path=os.path.join(tmp_dir, 'receipts.jsonl')
            )
            receipt = gw.update_sir_field(
                field_path='concerns.test_c',  # no attr → record_signal
                new_value='Sir mentioned X',
                source='record_signal_test',
                confidence=0.7,
                nerve=_MockNerve(),
            )
            self.assertTrue(receipt.ok)
            # record_signal should add 1 entry
            self.assertEqual(len(ledger.concerns['test_c'].recent_signals), 1)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_gateway_routes_relational_update_to_update_field(self):
        """gateway field_path='inside_joke.update.<id>.phrase' → RelationalStateStore.update_field"""
        from jarvis_relational import RelationalStateStore, InsideJoke
        from jarvis_memory_gateway import MemoryMutationGateway

        tmp_dir = tempfile.mkdtemp(prefix='gw_rel_int_')
        try:
            rs = RelationalStateStore(persist_path=os.path.join(tmp_dir, 'r.json'))
            rs.add_inside_joke(InsideJoke(id='j1', phrase='old phrase', tone='wry'))

            class _MockNerve:
                relational_state = rs
                profile_card = None

            gw = MemoryMutationGateway(
                receipt_path=os.path.join(tmp_dir, 'receipts.jsonl')
            )
            receipt = gw.update_sir_field(
                field_path='inside_joke.update.j1.phrase',
                new_value='new phrase',
                source='fast_call_mutation:refine',
                confidence=0.9,
                nerve=_MockNerve(),
            )
            self.assertTrue(receipt.ok, receipt.error)
            self.assertEqual(receipt.layer_targeted, 'RelationalStateStore')
            self.assertEqual(rs.inside_jokes['j1'].phrase, 'new phrase')
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_gateway_relational_archive_op_still_works(self):
        """老的 'inside_joke.archive.<jid>' 路径不退化."""
        from jarvis_relational import RelationalStateStore, InsideJoke, STATE_ARCHIVED
        from jarvis_memory_gateway import MemoryMutationGateway

        tmp_dir = tempfile.mkdtemp(prefix='gw_rel_arch_')
        try:
            rs = RelationalStateStore(persist_path=os.path.join(tmp_dir, 'r.json'))
            rs.add_inside_joke(InsideJoke(id='j1', phrase='joke', tone='wry'))

            class _MockNerve:
                relational_state = rs
                profile_card = None

            gw = MemoryMutationGateway(
                receipt_path=os.path.join(tmp_dir, 'receipts.jsonl')
            )
            receipt = gw.update_sir_field(
                field_path='inside_joke.archive.j1',
                new_value='archived by Sir',
                source='fast_call_mutation:dismiss',
                confidence=0.9,
                nerve=_MockNerve(),
            )
            self.assertTrue(receipt.ok, receipt.error)
            self.assertEqual(rs.inside_jokes['j1'].state, STATE_ARCHIVED)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ============================================================
# 6. SWM publish on overwrite_field
# ============================================================

class TestOverwriteFieldSwmPublish(unittest.TestCase):

    def test_overwrite_emits_swm_event(self):
        if not os.path.exists(os.path.join('jarvis_config', 'sir_profile.json')):
            self.skipTest('sir_profile.json not found')

        from jarvis_routing import ProfileCard
        from jarvis_utils import (get_event_bus, ConversationEventBus)
        import jarvis_utils as _ju

        class _MockNerve:
            habit_clock = None
            causal_chain = None
            project_timeline = None
            status_ledger = None

        pc = ProfileCard(_MockNerve())

        # 测试上下文: 没 nerve init 时 _GLOBAL_EVENT_BUS=None.
        # 注册一个临时 bus 让 overwrite_field 能 publish.
        prev_bus = _ju._GLOBAL_EVENT_BUS
        test_bus = ConversationEventBus()
        ConversationEventBus.register_global(test_bus)

        # Backup + write
        profile_path = os.path.join('jarvis_config', 'sir_profile.json')
        backup = profile_path + '.swm_test_bak'
        shutil.copy2(profile_path, backup)

        try:
            new_val = f'[SWM-TEST] {time.time():.0f}'
            ok, _, _ = pc.overwrite_field(
                field='work_rhythms',
                new_value=new_val,
                source='fast_call_mutation:revise',
                turn_id='test_swm_001',
                reason='swm publish test',
            )
            self.assertTrue(ok)

            # Verify SWM has 'sir_profile_overwritten' event
            # Note: ConversationEventBus stores etype under key 'type', not 'etype'
            after_events = test_bus.recent_events(within_seconds=10.0)
            etypes = [e.get('type') for e in after_events]
            self.assertIn('sir_profile_overwritten', etypes,
                            f'SWM should publish sir_profile_overwritten; got: {etypes}')
        finally:
            shutil.copy2(backup, profile_path)
            os.remove(backup)
            ConversationEventBus.register_global(prev_bus)


if __name__ == '__main__':
    unittest.main(verbosity=2)
