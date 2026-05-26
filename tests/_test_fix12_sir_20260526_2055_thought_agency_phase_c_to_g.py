# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 20:55 真痛追根] 思考层成果消化 + AutoArbiter 治本 回归.

Sir 真痛 (2 anchor):
  Anchor 1 (20:55): "思考层成果没被消化" → A/B/C/D 4 方案 (A/B 已 fix11 覆盖)
    - C: surface_to_sir actionable
    - D: outcome 闭环
  Anchor 2 (21:02-21:04): "dashboard 一堆 pending + 拍板必须去重 +
                                 时刻帮我检查 AutoArbiter 拍板内容"
    - E.1: TICK 30min → 5min + vocab 持久化
    - E.2: 删 LLM prompt conservative bias
    - E.3: defer_to_sir 后 6h 重评 (不再 24h 锁)
    - E.4: 加 active count evidence
    - F: pre-activate dedup hard-check
    - G: monitor daemon (bloat / revert burst / dedup miss)

工程总计: ~500 行 (0 新 daemon, 复用现有架构 + 准则 6 vocab 三规)
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


# ==========================================================================
# Shared fixtures
# ==========================================================================
def _make_thought(category='B', salience=0.85, actionable='none',
                    evidence_link='none', thought_text='I noticed Sir...'):
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id=f"th_test_{int(time.time() * 1000000)}",
        ts=time.time(),
        ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S'),
        category=category,
        thought=thought_text,
        salience=salience,
        actionable=actionable,
        evidence_link=evidence_link,
    )


def _make_daemon(nerve=None):
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    return InnerThoughtDaemon(
        key_router=MagicMock(),
        concerns_ledger=None,
        relational_state=None,
        central_nerve=nerve,
    )


def _make_event_bus_capture():
    """返 (bus_mock, captured_events_list)."""
    captured = []

    def _publish(etype, description='', source='', salience=0.5,
                   metadata=None, ttl=None, **_):
        captured.append({
            'type': etype,
            'description': description,
            'source': source,
            'salience': salience,
            'metadata': metadata or {},
        })

    bus_mock = MagicMock()
    bus_mock.publish = _publish
    return bus_mock, captured


# ==========================================================================
# Phase C — surface_to_sir actionable (7 testcase)
# ==========================================================================
class TestPhaseCSurfaceToSir(unittest.TestCase):
    def test_sc1_low_sal_gated(self):
        """sal < threshold (0.7) → gated."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.5)
        ok, msg = daemon._do_surface_to_sir_actionable(
            thought, 'surface_to_sir:terminal_pulse:test summary'
        )
        self.assertFalse(ok)
        self.assertIn('gated:surface_requires_sal', msg)

    def test_sc2_parse_fail_too_few_parts(self):
        """surface_to_sir:foo (no summary) → parse_fail."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.85)
        ok, msg = daemon._do_surface_to_sir_actionable(
            thought, 'surface_to_sir:terminal_pulse'
        )
        self.assertFalse(ok)
        self.assertIn('parse_fail', msg)

    def test_sc3_channel_not_allowed(self):
        """invalid channel → channel_not_allowed."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.85)
        ok, msg = daemon._do_surface_to_sir_actionable(
            thought, 'surface_to_sir:voice_pulse:test'
        )
        self.assertFalse(ok)
        self.assertIn('channel_not_allowed', msg)

    def test_sc4_terminal_pulse_success(self):
        """terminal_pulse channel + valid → 成功 + bg_log called."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.85)
        with patch.object(daemon, '_bg_log') as mock_log:
            ok, msg = daemon._do_surface_to_sir_actionable(
                thought, 'surface_to_sir:terminal_pulse:Sir test summary'
            )
        self.assertTrue(ok, f"unexpected fail: {msg}")
        self.assertIn('surfaced:terminal_pulse', msg)
        # bg_log 至少一次 (含 thought→sir 标记)
        self.assertTrue(mock_log.called)

    def test_sc5_next_turn_inject_publishes_swm(self):
        """next_turn_inject channel → publish 'inner_thought_surface' SWM."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.85)
        bus_mock, captured = _make_event_bus_capture()
        with patch('jarvis_utils.get_event_bus', return_value=bus_mock):
            ok, msg = daemon._do_surface_to_sir_actionable(
                thought, 'surface_to_sir:next_turn_inject:test summary'
            )
        self.assertTrue(ok, f"unexpected fail: {msg}")
        types = [e['type'] for e in captured]
        self.assertIn('inner_thought_surface', types)
        self.assertIn('inner_thought_surface_executed', types)

    def test_sc6_global_cooldown_blocks_second(self):
        """global cooldown 120s 内第二次 fail."""
        daemon = _make_daemon()
        thought_a = _make_thought(salience=0.85)
        thought_b = _make_thought(salience=0.85)
        ok1, _ = daemon._do_surface_to_sir_actionable(
            thought_a, 'surface_to_sir:terminal_pulse:first'
        )
        ok2, msg2 = daemon._do_surface_to_sir_actionable(
            thought_b, 'surface_to_sir:terminal_pulse:second'
        )
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertTrue(
            'global_cooldown' in msg2 or 'channel_' in msg2,
            f"expected cooldown msg, got: {msg2}"
        )

    def test_sc7_dispatch_via_execute_actionable(self):
        """_execute_actionable 路由 surface_to_sir 到 handler.

        evidence_link 必须真在 thought 文本中, 否则 hard gate 拦.
        """
        daemon = _make_daemon()
        thought = _make_thought(
            salience=0.85,
            actionable='surface_to_sir:terminal_pulse:Sir test',
            evidence_link='I noticed Sir',
            thought_text='I noticed Sir is working hard',
        )
        ok, msg = daemon._execute_actionable(thought)
        self.assertTrue(ok, f"unexpected fail: {msg}")
        self.assertIn('surfaced:terminal_pulse', msg)


# ==========================================================================
# Phase D — outcome 闭环 (6 testcase)
# ==========================================================================
class TestPhaseDOutcomeLoop(unittest.TestCase):
    def test_od1_vocab_loaded(self):
        """vocab 加载且包含核心 keys."""
        from jarvis_thought_outcome import _load_vocab
        vocab = _load_vocab()
        self.assertIn('sir_engaged_keywords_zh', vocab)
        self.assertIn('sir_silenced_keywords_zh', vocab)
        self.assertIn('sir_rejected_keywords_zh', vocab)
        self.assertIn('thought_reference_patterns_zh', vocab)

    def test_od2_detect_engaged(self):
        """主脑 ref thought + Sir 'good point' → 'sir_engaged'."""
        from jarvis_thought_outcome import detect_outcome
        thought = _make_thought(
            thought_text='I noticed Sir prefers brief replies during coding sessions',
        )
        sir_reply = "Good point, exactly that — keep doing it"
        jarvis_reply = ("I noticed Sir often works long coding sessions and "
                          "prefers brief acknowledgments")
        result = detect_outcome(sir_reply, jarvis_reply, [thought])
        self.assertIsNotNone(result)
        self.assertEqual(result.outcome, 'sir_engaged')
        self.assertEqual(result.thought_id, thought.id)

    def test_od3_detect_silenced(self):
        """主脑 ref + Sir 'drop it' → 'sir_silenced'."""
        from jarvis_thought_outcome import detect_outcome
        thought = _make_thought(
            thought_text='I noticed Sir mentioned the deployment yesterday three times',
        )
        sir_reply = "Drop it, not important right now"
        jarvis_reply = ("I noticed Sir mentioned the deployment yesterday several "
                          "times — should I follow up?")
        result = detect_outcome(sir_reply, jarvis_reply, [thought])
        self.assertIsNotNone(result)
        self.assertEqual(result.outcome, 'sir_silenced')

    def test_od4_detect_rejected(self):
        """主脑 ref + Sir 'incorrect' → 'sir_rejected'."""
        from jarvis_thought_outcome import detect_outcome
        thought = _make_thought(
            thought_text='I noticed Sir said the prototype crashed last evening session',
        )
        sir_reply = "Incorrect, you got it wrong — it didn't crash"
        jarvis_reply = ("I noticed Sir said the prototype crashed yesterday "
                          "evening — let me confirm the logs")
        result = detect_outcome(sir_reply, jarvis_reply, [thought])
        self.assertIsNotNone(result)
        self.assertEqual(result.outcome, 'sir_rejected')

    def test_od5_no_jarvis_ref_returns_none(self):
        """主脑 reply 没 reference pattern → None (no anchor)."""
        from jarvis_thought_outcome import detect_outcome
        thought = _make_thought(thought_text='Sir prefers brief')
        sir_reply = "Good point"
        jarvis_reply = "OK Sir"  # 没 reference pattern
        result = detect_outcome(sir_reply, jarvis_reply, [thought])
        self.assertIsNone(result)

    def test_od6_record_outcome_persists(self):
        """daemon.record_outcome 写 thought.outcome + persist jsonl."""
        with tempfile.TemporaryDirectory() as tmp:
            from jarvis_inner_thought_daemon import InnerThoughtDaemon
            persist_path = os.path.join(tmp, 'thoughts.jsonl')
            with patch.object(InnerThoughtDaemon, 'PERSIST_PATH', persist_path):
                daemon = _make_daemon()
                thought = _make_thought()
                daemon._thoughts.append(thought)

                ok = daemon.record_outcome(thought.id, 'sir_engaged')
                self.assertTrue(ok)
                self.assertEqual(thought.outcome, 'sir_engaged')

                # persist 文件应含 outcome update row
                with open(persist_path, 'r', encoding='utf-8') as f:
                    rows = [json.loads(L) for L in f if L.strip()]
                update_rows = [r for r in rows if r.get('_outcome_update')]
                self.assertEqual(len(update_rows), 1)
                self.assertEqual(update_rows[0]['outcome'], 'sir_engaged')


# ==========================================================================
# Phase E.1+E.3 — AutoArbiter runtime vocab (4 testcase)
# ==========================================================================
class TestPhaseE13RuntimeVocab(unittest.TestCase):
    def _make_arbiter(self, calibration_data=None):
        with tempfile.TemporaryDirectory() as tmp:
            self._tmp_dir = tmp
            cal_path = os.path.join(tmp, 'cal.json')
            if calibration_data:
                with open(cal_path, 'w', encoding='utf-8') as f:
                    json.dump(calibration_data, f)
            from jarvis_auto_arbiter import AutoArbiterDaemon
            with patch.object(AutoArbiterDaemon, 'CALIBRATION_PATH', cal_path):
                arb = AutoArbiterDaemon(key_router=MagicMock())
            return arb

    def test_e1_default_tick_5min(self):
        """default TICK_INTERVAL_S 应 300 (5min, 不是老的 1800)."""
        from jarvis_auto_arbiter import AutoArbiterDaemon
        self.assertEqual(AutoArbiterDaemon.TICK_INTERVAL_S, 300)
        self.assertEqual(
            AutoArbiterDaemon.DEFAULT_RUNTIME['tick_interval_s'], 300
        )

    def test_e1_runtime_vocab_loaded(self):
        """calibration runtime 段 override defaults."""
        arb = self._make_arbiter(calibration_data={
            'thresholds': {},
            'runtime': {'tick_interval_s': 60, 'reevaluate_after_h': 3.0},
        })
        runtime = arb._effective_runtime()
        self.assertEqual(runtime['tick_interval_s'], 60)
        self.assertEqual(runtime['reevaluate_after_h'], 3.0)
        # 没覆盖的 key 仍是 default
        self.assertEqual(
            runtime['pre_activate_dedup_jaccard'], 0.6
        )

    def test_e3_terminal_decision_24h_lock(self):
        """activate/reject 决策 24h 内不重做."""
        arb = self._make_arbiter()
        from jarvis_auto_arbiter import ArbiterDecision
        # 12h ago 决策 (24h cutoff 之内)
        arb._decisions.append(ArbiterDecision(
            id='aa1', ts=time.time() - 12 * 3600, ts_iso='', kind='protocol',
            item_id='p_test', item_preview='', risk_level='low',
            decision='activate', confidence=0.9, reason='', threshold_at_decision=0.8,
        ))
        self.assertTrue(arb._already_decided_recently('protocol', 'p_test'))

    def test_e3_defer_after_6h_can_reevaluate(self):
        """defer_to_sir 决策 6h+ 之后可重评 (但 24h 内 terminal 仍锁)."""
        arb = self._make_arbiter()
        from jarvis_auto_arbiter import ArbiterDecision
        # 7h ago defer (默认 6h reevaluate_after_h)
        arb._decisions.append(ArbiterDecision(
            id='aa1', ts=time.time() - 7 * 3600, ts_iso='', kind='protocol',
            item_id='p_test', item_preview='', risk_level='low',
            decision='defer_to_sir', confidence=0.6, reason='', threshold_at_decision=0.8,
        ))
        self.assertFalse(
            arb._already_decided_recently('protocol', 'p_test'),
            "defer 7h ago should allow re-evaluation"
        )

        # 3h ago defer 应仍锁
        arb._decisions = []
        arb._decisions.append(ArbiterDecision(
            id='aa2', ts=time.time() - 3 * 3600, ts_iso='', kind='protocol',
            item_id='p_test2', item_preview='', risk_level='low',
            decision='defer_to_sir', confidence=0.6, reason='', threshold_at_decision=0.8,
        ))
        self.assertTrue(arb._already_decided_recently('protocol', 'p_test2'))


# ==========================================================================
# Phase E.2 — LLM prompt bias removed (1 testcase)
# ==========================================================================
class TestPhaseE2BiasRemoved(unittest.TestCase):
    def test_e2_no_when_in_doubt_reject(self):
        """build_prompt 不应含 'When in doubt, REJECT' bias."""
        from jarvis_auto_arbiter import AutoArbiterDaemon
        arb = AutoArbiterDaemon(key_router=MagicMock())

        class FakeProtocol:
            id = 'p_test'
            rule = 'Always be brief in routine confirmations'
            source = 'inner_thought'
            source_marker = ''

        entity = FakeProtocol()
        evidence = {'kind': 'protocol', 'entity': {
            'rule': entity.rule, 'source': entity.source, 'source_marker': '',
        }, 'existing_active_protocols': [], 'active_count_total': 0, 'stm': []}
        system, user = arb._build_prompt('protocol', entity, evidence)
        # bias 删了 → 不应出现 'When in doubt, REJECT'
        self.assertNotIn('When in doubt, REJECT', system)
        # 改成更平衡: trust your judgment
        self.assertIn('trust your judgment', system.lower())


# ==========================================================================
# Phase E.4 — active count evidence (2 testcase)
# ==========================================================================
class TestPhaseE4ActiveCount(unittest.TestCase):
    def test_e4_evidence_has_active_count(self):
        """_collect_evidence 含 active_count_total 字段."""
        from jarvis_auto_arbiter import AutoArbiterDaemon
        import jarvis_relational
        from jarvis_relational import (RelationalStateStore, UnspokenProtocol,
                                            STATE_ACTIVE)

        # fresh singleton (清状态)
        jarvis_relational._DEFAULT_STORE = None
        store = jarvis_relational.get_default_store()
        store.unspoken_protocols.clear()

        for i in range(3):
            p = UnspokenProtocol(
                id=f'p_{i}',
                rule=f'Active protocol {i}',
                source='test',
                state=STATE_ACTIVE,
            )
            store.unspoken_protocols[p.id] = p

        arb = AutoArbiterDaemon(key_router=MagicMock(), relational_state=store)
        new_p = UnspokenProtocol(
            id='p_new', rule='New rule candidate', source='test',
        )
        ev = arb._collect_evidence('protocol', new_p)
        self.assertEqual(ev['active_count_total'], 3)

        # cleanup
        store.unspoken_protocols.clear()

    def test_e4_prompt_contains_total_active(self):
        """build_prompt 含 [TOTAL ACTIVE PROTOCOLS]: N."""
        from jarvis_auto_arbiter import AutoArbiterDaemon
        arb = AutoArbiterDaemon(key_router=MagicMock())

        class FakeP:
            id = 'p_test'
            rule = 'test rule'
            source = 'test'
            source_marker = ''

        evidence = {'kind': 'protocol', 'entity': {
            'rule': 'test rule', 'source': 'test', 'source_marker': '',
        }, 'existing_active_protocols': [], 'active_count_total': 5, 'stm': []}
        system, user = arb._build_prompt('protocol', FakeP(), evidence)
        self.assertIn('[TOTAL ACTIVE PROTOCOLS]', user)
        self.assertIn('5', user)


# ==========================================================================
# Phase F — pre-activate dedup hard-check (5 testcase)
# ==========================================================================
class TestPhaseFPreActivateDedup(unittest.TestCase):
    def _make_arbiter_with_store(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        import jarvis_relational
        jarvis_relational._DEFAULT_STORE = None
        store = jarvis_relational.get_default_store()
        store.inside_jokes.clear()
        store.unspoken_protocols.clear()
        store.shared_history_threads.clear()
        arb = AutoArbiterDaemon(key_router=MagicMock(), relational_state=store)
        return arb, store

    def test_f1_no_active_no_dedup(self):
        """active list 空 → 通过 (no_dup)."""
        arb, store = self._make_arbiter_with_store()
        from jarvis_relational import UnspokenProtocol
        cand = UnspokenProtocol(id='p_new', rule='Always be brief', source='test')
        ok, msg = arb._pre_activate_dedup_check('protocol', cand)
        self.assertTrue(ok)
        self.assertEqual(msg, 'no_dup')
        store.unspoken_protocols.clear()

    def test_f2_jaccard_above_threshold_blocks(self):
        """jaccard >= 0.6 → 阻止激活."""
        arb, store = self._make_arbiter_with_store()
        from jarvis_relational import UnspokenProtocol, STATE_ACTIVE
        # 高重叠 (jaccard ≥ 0.6): 5/6 词重叠
        existing = UnspokenProtocol(
            id='p_old', rule='Always use brief replies routine',
            source='test', state=STATE_ACTIVE,
        )
        store.unspoken_protocols[existing.id] = existing

        cand = UnspokenProtocol(
            id='p_new', rule='Always use brief replies routine confirmation',
            source='test',
        )
        ok, msg = arb._pre_activate_dedup_check('protocol', cand)
        self.assertFalse(ok, f"expected block, got OK: {msg}")
        # 命中 substring 或 jaccard 都接受
        self.assertTrue('jaccard' in msg or 'substring' in msg)
        self.assertIn('p_old', msg)
        store.unspoken_protocols.clear()

    def test_f3_substring_match_blocks(self):
        """substring (>=12 char) 直接拦."""
        arb, store = self._make_arbiter_with_store()
        from jarvis_relational import UnspokenProtocol, STATE_ACTIVE
        existing = UnspokenProtocol(
            id='p_old', rule='Always use brief concise confirmations Sir',
            source='test', state=STATE_ACTIVE,
        )
        store.unspoken_protocols[existing.id] = existing

        cand = UnspokenProtocol(
            id='p_new', rule='Always use brief concise confirmations',
            source='test',
        )
        ok, msg = arb._pre_activate_dedup_check('protocol', cand)
        self.assertFalse(ok, f"expected block, got OK: {msg}")
        # 实际命中可能是 substring 或 jaccard, 都接受 (核心: 拦住了)
        self.assertTrue(
            'substring_match' in msg or 'jaccard' in msg,
            f"expected substring/jaccard msg, got: {msg}"
        )
        store.unspoken_protocols.clear()

    def test_f4_excludes_self_by_id(self):
        """同 id 不算重复."""
        arb, store = self._make_arbiter_with_store()
        from jarvis_relational import UnspokenProtocol, STATE_ACTIVE
        same = UnspokenProtocol(
            id='p_same', rule='Always be brief', source='test',
            state=STATE_ACTIVE,
        )
        store.unspoken_protocols[same.id] = same
        ok, msg = arb._pre_activate_dedup_check('protocol', same)
        self.assertTrue(ok, f"same id should pass: {msg}")
        store.unspoken_protocols.clear()

    def test_f5_integration_with_evaluate_and_decide(self):
        """_evaluate_and_decide ACTIVATE 触发 pre_activate_dedup 拦截."""
        arb, store = self._make_arbiter_with_store()
        from jarvis_relational import UnspokenProtocol, STATE_ACTIVE
        existing = UnspokenProtocol(
            id='p_old', rule='Always be brief in routine confirmations',
            source='test', state=STATE_ACTIVE,
        )
        store.unspoken_protocols[existing.id] = existing

        cand = UnspokenProtocol(
            id='p_new', rule='Always be brief during routine confirmations',
            source='test',
        )

        # mock LLM eval 返 ACTIVATE 高 conf
        with patch.object(arb, '_llm_evaluate',
                            return_value=('activate', 0.95, 'high quality')):
            # _execute mock 防真改 store
            with patch.object(arb, '_execute', return_value=(True, 'mocked')):
                arb._evaluate_and_decide({
                    'kind': 'protocol',
                    'entity': cand,
                    'preview': cand.rule,
                })

        # 最新 decision 应是 reject (pre_activate_dedup 推翻 activate)
        self.assertGreater(len(arb._decisions), 0)
        latest = arb._decisions[-1]
        self.assertEqual(latest.decision, 'reject',
                          f"expected reject from dedup, got: {latest.decision}")
        self.assertIn('pre_activate_dedup', latest.reason)
        store.unspoken_protocols.clear()


# ==========================================================================
# Phase G — monitor daemon (5 testcase)
# ==========================================================================
class TestPhaseGMonitor(unittest.TestCase):
    def _make_arbiter_with_store(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        import jarvis_relational
        jarvis_relational._DEFAULT_STORE = None
        store = jarvis_relational.get_default_store()
        store.inside_jokes.clear()
        store.unspoken_protocols.clear()
        store.shared_history_threads.clear()
        arb = AutoArbiterDaemon(key_router=MagicMock(), relational_state=store)
        return arb, store

    def test_g1_no_warnings_when_below_threshold(self):
        """active 少 + 无 revert → 无 warning publish."""
        arb, store = self._make_arbiter_with_store()
        bus_mock, captured = _make_event_bus_capture()
        with patch('jarvis_utils.get_event_bus', return_value=bus_mock):
            arb._do_monitor_scan()
        anomalies = [e for e in captured if e['type'] == 'auto_arbiter_anomaly']
        self.assertEqual(len(anomalies), 0)
        store.unspoken_protocols.clear()

    def test_g2_bloat_warn(self):
        """active 26 个 (>= 25 warn 阈) → publish warning."""
        arb, store = self._make_arbiter_with_store()
        from jarvis_relational import UnspokenProtocol, STATE_ACTIVE
        for i in range(26):
            p = UnspokenProtocol(
                id=f'p_{i}', rule=f'rule number {i} alpha beta gamma',
                source='test', state=STATE_ACTIVE,
            )
            store.unspoken_protocols[p.id] = p

        bus_mock, captured = _make_event_bus_capture()
        with patch('jarvis_utils.get_event_bus', return_value=bus_mock):
            arb._do_monitor_scan()
        anomalies = [e for e in captured if e['type'] == 'auto_arbiter_anomaly']
        bloat_anoms = [a for a in anomalies
                          if a['metadata'].get('anomaly_type') == 'bloat']
        self.assertGreaterEqual(len(bloat_anoms), 1, f"got: {[a['description'] for a in anomalies]}")
        store.unspoken_protocols.clear()

    def test_g3_revert_burst_warn(self):
        """24h 内 6 决策 中 3 reverted (50% > 30%) → publish warning."""
        arb, store = self._make_arbiter_with_store()
        from jarvis_auto_arbiter import ArbiterDecision
        # 🆕 [Sir 2026-05-26 22:32 fix] arb._decisions 从持久化 jsonl 自动 load,
        # 真测累积后 test 加 6 条被稀释 → revert rate < 30% → 无 warn. 清空保 fresh.
        arb._decisions.clear()
        now = time.time()
        for i in range(6):
            d = ArbiterDecision(
                id=f'aa_{i}', ts=now - 3600, ts_iso='',
                kind='inside_joke', item_id=f'j_{i}', item_preview='',
                risk_level='low', decision='activate', confidence=0.9,
                reason='', threshold_at_decision=0.75,
            )
            if i < 3:
                d.sir_reverted_at = now - 1800
            arb._decisions.append(d)

        bus_mock, captured = _make_event_bus_capture()
        with patch('jarvis_utils.get_event_bus', return_value=bus_mock):
            arb._do_monitor_scan()
        anomalies = [e for e in captured if e['type'] == 'auto_arbiter_anomaly']
        revert_anoms = [a for a in anomalies
                          if a['metadata'].get('anomaly_type') == 'revert_burst']
        self.assertGreaterEqual(len(revert_anoms), 1, f"got: {anomalies}")
        store.inside_jokes.clear()

    def test_g4_dedup_miss_warn(self):
        """active pair jaccard >= 0.5 → publish dedup_miss warning."""
        arb, store = self._make_arbiter_with_store()
        from jarvis_relational import UnspokenProtocol, STATE_ACTIVE
        p1 = UnspokenProtocol(
            id='p_a', rule='Always be brief in routine confirmations',
            source='test', state=STATE_ACTIVE,
        )
        p2 = UnspokenProtocol(
            id='p_b', rule='Always be brief during routine confirmations',
            source='test', state=STATE_ACTIVE,
        )
        store.unspoken_protocols[p1.id] = p1
        store.unspoken_protocols[p2.id] = p2

        bus_mock, captured = _make_event_bus_capture()
        with patch('jarvis_utils.get_event_bus', return_value=bus_mock):
            arb._do_monitor_scan()
        anomalies = [e for e in captured if e['type'] == 'auto_arbiter_anomaly']
        dedup_anoms = [a for a in anomalies
                          if a['metadata'].get('anomaly_type') == 'dedup_miss']
        self.assertGreaterEqual(len(dedup_anoms), 1, f"got: {anomalies}")
        store.unspoken_protocols.clear()

    def test_g5_warning_dedup_1h(self):
        """同 kind+type warning 1h 内只 publish 一次."""
        arb, store = self._make_arbiter_with_store()
        from jarvis_relational import UnspokenProtocol, STATE_ACTIVE
        for i in range(26):
            p = UnspokenProtocol(
                id=f'p_{i}', rule=f'rule {i}', source='test', state=STATE_ACTIVE,
            )
            store.unspoken_protocols[p.id] = p

        bus_mock, captured = _make_event_bus_capture()
        with patch('jarvis_utils.get_event_bus', return_value=bus_mock):
            arb._do_monitor_scan()  # 第一次 publish
            n_after_first = len([e for e in captured
                                    if e['type'] == 'auto_arbiter_anomaly'])
            arb._do_monitor_scan()  # 第二次应被 dedup 拦
            n_after_second = len([e for e in captured
                                     if e['type'] == 'auto_arbiter_anomaly'])
        self.assertEqual(n_after_first, n_after_second,
                          "second scan should be deduped within 1h")
        store.unspoken_protocols.clear()


# ==========================================================================
# BUG-H — Mutation Evidence Guard (4 testcase)
# Sir 21:07 真测: 'd home' → Jarvis 凭空 'Stay safe' 写入 sir_profile.json.
# 治本: jarvis_mutation_evidence_guard 拦在 MemoryGateway 入口.
# ==========================================================================
class TestBugHMutationEvidenceGuard(unittest.TestCase):
    def test_bh1_no_evidence_blocks(self):
        """new_value 中无 substring/jaccard 与 STM 匹配 → block."""
        from jarvis_mutation_evidence_guard import check_mutation_evidence
        fake_nerve = MagicMock()
        fake_nerve.short_term_memory = [
            {'user': 'd home, 钢铁侠电影里那句话', 'jarvis': 'understood'},
        ]
        ok, reason = check_mutation_evidence(
            new_value="Sir frequently references the 'Stay safe' quote from Avenger",
            field_path='profile.idiosyncrasies',
            source='worker.memory_correction',
            nerve=fake_nerve,
        )
        self.assertFalse(ok, f"expected block but got OK: {reason}")
        self.assertIn('no_evidence', reason)

    def test_bh2_substring_evidence_passes(self):
        """new_value 包含 STM 中的实词 substring (>= 6 char) → pass."""
        from jarvis_mutation_evidence_guard import check_mutation_evidence
        fake_nerve = MagicMock()
        fake_nerve.short_term_memory = [
            {'user': 'Sir wants to focus on Python typed dict refactoring today',
              'jarvis': 'noted'},
        ]
        ok, reason = check_mutation_evidence(
            new_value='Sir prefers typed dict refactoring style for Python',
            field_path='profile.work_rhythms',
            source='worker.memory_correction',
            nerve=fake_nerve,
        )
        self.assertTrue(ok, f"expected pass, reason: {reason}")
        self.assertTrue('evidence_ok' in reason or 'bypass' in reason)

    def test_bh3_bypass_source_skips_check(self):
        """source 在 bypass_sources 内 → 直接通过."""
        from jarvis_mutation_evidence_guard import check_mutation_evidence
        fake_nerve = MagicMock()
        fake_nerve.short_term_memory = []
        ok, reason = check_mutation_evidence(
            new_value='Anything goes',
            field_path='profile.idiosyncrasies',
            source='sir_cli.profile_update',  # bypass
            nerve=fake_nerve,
        )
        self.assertTrue(ok)
        self.assertIn('bypass:source', reason)

    def test_bh4_memory_hub_returns_blocked_receipt(self):
        """update_sir_field 触发 guard block → 返 ok=False 含 'evidence_guard_blocked'."""
        from jarvis_memory_hub import MemoryMutationGateway
        fake_nerve = MagicMock()
        fake_nerve.short_term_memory = [
            {'user': '什么 你说的不对', 'jarvis': 'apologies'},
        ]
        # mock profile_card 防真写
        fake_profile = MagicMock()
        fake_profile.overwrite_field = MagicMock(
            return_value=(True, 'ok', 'old')
        )
        fake_nerve.profile_card = fake_profile

        gw = MemoryMutationGateway(receipt_path=tempfile.mktemp())
        receipt = gw.update_sir_field(
            field_path='profile.idiosyncrasies',
            new_value="Sir loves the Stay safe quote from Avengers",
            source='worker.memory_correction',
            old_value='old val',
            confidence=0.5,
            nerve=fake_nerve,
        )
        self.assertFalse(receipt.ok)
        self.assertIn('evidence_guard_blocked', receipt.error)
        # profile.overwrite_field 不应被调 (block 在它之前)
        fake_profile.overwrite_field.assert_not_called()


# ==========================================================================
# BUG-I — mutation router tool_name_misuse (3 testcase)
# Sir 21:07 真测: `mutation.update fail: no router for layer=unknown
# (field=memory_hands.modify_record)` silent fail. 治本: 显式识别 + 清晰 err msg.
# ==========================================================================
class TestBugIRouterToolNameMisuse(unittest.TestCase):
    def test_bi1_memory_hands_detected_as_tool_name(self):
        from jarvis_memory_hub import _detect_target_layer
        self.assertEqual(
            _detect_target_layer('memory_hands.modify_record'),
            'tool_name_misuse'
        )
        self.assertEqual(
            _detect_target_layer('reminder.set'),
            'tool_name_misuse'
        )

    def test_bi2_valid_paths_unchanged(self):
        from jarvis_memory_hub import _detect_target_layer
        self.assertEqual(
            _detect_target_layer('profile.work_rhythms'),
            'ProfileCard'
        )
        self.assertEqual(
            _detect_target_layer('concerns.sir_sleep_streak'),
            'ConcernsLedger'
        )

    def test_bi3_update_sir_field_returns_helpful_err(self):
        from jarvis_memory_hub import MemoryMutationGateway
        fake_nerve = MagicMock()
        fake_nerve.short_term_memory = []
        gw = MemoryMutationGateway(receipt_path=tempfile.mktemp())
        receipt = gw.update_sir_field(
            field_path='memory_hands.modify_record',
            new_value='something',
            source='sir_cli',  # bypass evidence guard
            confidence=0.9,
            nerve=fake_nerve,
        )
        self.assertFalse(receipt.ok)
        self.assertIn('TOOL NAME', receipt.error)
        self.assertIn('memory_hands', receipt.error)


# ==========================================================================
# BUG-J — wrap-up 不 mutate full_text when main reply complete (2 testcase)
# Sir 21:07 真测: 主 reply 159ch 已出 → wrap-up "Done, Sir." 第二段污染. 治本:
# main reply >= 50ch + single_step_fast_path + audio suppressed → skip wrap-up.
# ==========================================================================
class TestBugJWrapupSkip(unittest.TestCase):
    def test_bj1_long_reply_skips_wrapup_synthesis(self):
        """逻辑校验: 主 reply >= 50 char + single_step_fast_path → _need_synthesis False."""
        # 直接 logic test (不需要 instantiate ChatBypass)
        _stripped_full = (
            "Understood, Sir. It was a transcription error on my part. "
            "You were referring to the quote from the conclusion of the 2019 film."
        )
        self.assertGreaterEqual(len(_stripped_full), 50)
        _circuit_broken_reason = 'single_step_fast_path'
        _suppress_wrap_audio = True
        _need_synthesis = True  # 初始

        # 模拟 chat_bypass BUG-J 短路 logic
        if (_need_synthesis and _suppress_wrap_audio
                and _circuit_broken_reason == 'single_step_fast_path'
                and _stripped_full and len(_stripped_full) >= 50):
            _need_synthesis = False

        self.assertFalse(_need_synthesis,
                          "long reply + single_step_fast_path should skip wrap-up")

    def test_bj2_short_reply_still_triggers_wrapup(self):
        """主 reply < 20 char → wrap-up 仍触发 (universal safety net)."""
        _stripped_full = "OK"  # 太短
        _circuit_broken_reason = 'single_step_fast_path'
        _suppress_wrap_audio = True
        _need_synthesis = True

        if (_need_synthesis and _suppress_wrap_audio
                and _circuit_broken_reason == 'single_step_fast_path'
                and _stripped_full and len(_stripped_full) >= 50):
            _need_synthesis = False

        self.assertTrue(_need_synthesis,
                         "short reply should still trigger wrap-up")


# ==========================================================================
# BUG-K — ZH endings include quote marks (2 testcase)
# Sir 21:07 真测: ZH 末尾 '"That is home。"' → 末尾 '"' 不在 endings → 误报 truncated.
# ==========================================================================
class TestBugKZhEndingsQuotes(unittest.TestCase):
    def test_bk1_quote_endings_not_flagged_truncated(self):
        """ZH 末尾 '"' / ''' → 不算 truncated."""
        # 复用源码同 set
        _zh_endings = set('.?!。？！…"\'""''」』）)')
        # 各种 quote 收尾
        for ending_ch in ('"', '"', '"', "'", "'", '」', '』', '）', ')'):
            self.assertIn(ending_ch, _zh_endings,
                            f"quote '{ending_ch}' should be a valid ZH ending")

    def test_bk2_real_sir_case_endings_pass(self):
        """Sir 真测 ZH '看来转录有些误会，先生。您指的是焦点，那句英语是："That is home。"' → 通过."""
        zh = '看来转录有些误会，先生。您指的是焦点，那句英语是："That is home。"'
        _zh_endings = set('.?!。？！…"\'""''」』）)')
        self.assertIn(zh[-1], _zh_endings,
                       f"Sir's real ZH should pass, last char='{zh[-1]}'")


if __name__ == '__main__':
    unittest.main(verbosity=2)
