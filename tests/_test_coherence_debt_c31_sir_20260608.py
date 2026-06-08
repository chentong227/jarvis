# -*- coding: utf-8 -*-
"""[C3.1 / 2026-06-08] 自一致张力计 — coherence-debt 分型记账 单测.

只读派生态: 只算债 + append 账本 + 可查;绝不触发反思/写 directive/给 reward/
喂节律/动路由。三轴分型 (E_rel/E_commit/E_ground) + 冻结类型学 + grounded ref。

覆盖:
  ① 债能从真实 watcher source 算出且 grounded (每条带非空 provenance_ref)
  ② 无信号 → 债=0 (不凭空生痛)
  ③ append 后可 grep {type, ref}
  ④ 零行为: 记债仅 append ledger, 不喂 value_backoff (断言其状态不被改)
  ⑤ 类型学 config 冻结: 模块无写 typology 的 API/路径
  ⑥ I2 修正: publish 带非空 turn ref 且 flagged 不变 (在 inner_thought 测)
  ⑦ 紧迫度只算不喂: compute_urgency 不接行为路径
  ⑧ 空 ref 拒记 (无接地不生债)
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_coherence_debt as CD


class _LedgerHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='c31_')
        self._orig_ledger = CD._LEDGER_PATH
        CD._LEDGER_PATH = os.path.join(self.tmp, 'coherence_debt_ledger.jsonl')

    def tearDown(self):
        CD._LEDGER_PATH = self._orig_ledger
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestClassifyFrozenTypology(_LedgerHarness):
    def test_classify_e_rel(self):
        self.assertEqual(CD.classify_debt_type('correction_loop', 'correction'), 'E_rel')
        self.assertEqual(CD.classify_debt_type('correction_loop', 'confusion'), 'E_rel')

    def test_classify_e_rel_rejects_nonwhitelist_signal(self):
        # correction_loop 但 signal_type 不在白名单 (positive/neutral) → 不算债
        self.assertIsNone(CD.classify_debt_type('correction_loop', 'positive'))
        self.assertIsNone(CD.classify_debt_type('correction_loop', 'neutral'))

    def test_classify_e_commit(self):
        self.assertEqual(CD.classify_debt_type('inconsistency_watcher'), 'E_commit')

    def test_classify_e_ground(self):
        self.assertEqual(CD.classify_debt_type('semantic_claim'), 'E_ground')

    def test_unknown_source_none(self):
        self.assertIsNone(CD.classify_debt_type('random_source'))


class TestDebtGroundedAndLedger(_LedgerHarness):
    def test_01_taps_produce_grounded_debt(self):
        # ① 三轴 tap 各产 grounded 债 (带非空 ref)
        self.assertTrue(CD.tap_correction('correction', 'turn_abc', 'Sir 纠正'))
        self.assertTrue(CD.tap_inconsistency('p_123', '说睡却醒'))
        self.assertTrue(CD.tap_semantic_claim('turn_xyz', 'c0ffee', '未接地断言'))
        led = CD.read_ledger()
        self.assertEqual(len(led), 3)
        for r in led:
            self.assertIn(r['type'], CD.VALID_TYPES)
            self.assertTrue(r['provenance_ref']['ref'].strip(), "grounded: ref 非空")

    def test_02_no_signal_zero_debt(self):
        # ② 无 watcher 信号 → 债=0 (不凭空生痛)
        self.assertEqual(CD.debt_counts(), {'E_rel': 0, 'E_commit': 0, 'E_ground': 0})
        self.assertEqual(CD.compute_urgency(), 0.0)

    def test_03_ledger_greppable(self):
        # ③ append 后可 grep {type, ref}
        CD.tap_inconsistency('p_999', 'x')
        raw = open(CD._LEDGER_PATH, encoding='utf-8').read()
        self.assertIn('"type": "E_commit"', raw)
        self.assertIn('p_999', raw)
        rec = json.loads(raw.strip().splitlines()[-1])
        self.assertEqual(rec['type'], 'E_commit')
        self.assertEqual(rec['provenance_ref']['ref'], 'p_999')
        self.assertIn('opened_ts', rec)

    def test_08_empty_ref_rejected(self):
        # ⑧ 空 ref 拒记 (无接地不生债)
        self.assertFalse(CD.open_debt('E_commit', {'source_kind': 'inconsistency_watcher', 'ref': ''}))
        self.assertFalse(CD.open_debt('E_commit', {'source_kind': 'x'}))  # 无 ref
        self.assertFalse(CD.tap_inconsistency('', 'x'))  # promise_id 空
        self.assertEqual(len(CD.read_ledger()), 0)

    def test_invalid_type_rejected(self):
        self.assertFalse(CD.open_debt('E_bogus', {'ref': 'x'}))

    def test_correction_nonwhitelist_no_debt(self):
        # tap_correction 对非白名单 signal → 不记
        self.assertFalse(CD.tap_correction('positive', 'turn_x'))
        self.assertEqual(len(CD.read_ledger()), 0)


class TestZeroBehaviorAndFrozen(_LedgerHarness):
    def test_05_no_write_typology_api(self):
        # ⑤ 类型学冻结: 模块无任何写 typology 的 API/函数
        public = [n for n in dir(CD) if not n.startswith('_')]
        for n in public:
            self.assertFalse('write_typology' in n or 'set_typology' in n or
                             'save_typology' in n,
                             f"环不应有写类型学的 API: {n}")
        # 源码不含写 _TYPOLOGY_PATH
        src = open(CD.__file__, encoding='utf-8').read()
        self.assertNotIn("open(_TYPOLOGY_PATH, 'w'", src)
        self.assertNotIn('open(_TYPOLOGY_PATH, "w"', src)

    def test_04_no_value_backoff_coupling(self):
        # ④ 零行为: 模块不真 import/调 value_backoff/rest_floor (docstring 提及不算).
        import re as _re
        src = open(CD.__file__, encoding='utf-8').read()
        # 真 import value_backoff/inner_thought daemon → 耦合
        self.assertIsNone(
            _re.search(r'^\s*(import|from)\s+jarvis_inner_thought', src, _re.M),
            "记债路径不应 import inner_thought daemon (节律在那)")
        self.assertNotIn('_update_value_backoff', src,
                         "记债路径不应调 _update_value_backoff")
        self.assertNotIn('_emergent_rest_floor', src,
                         "记债路径不应调 rest_floor")
        # 不 import canonical (自定 provenance_ref 范式)
        self.assertIsNone(_re.search(r'^\s*(import|from)\s+jarvis_canonical', src, _re.M),
                          "⑤ 不 import canonical (自定 provenance_ref 范式)")

    def test_07_urgency_compute_only(self):
        # ⑦ 紧迫度只算 (返标量), 不触发任何行为
        CD.tap_inconsistency('p_1')
        CD.tap_correction('correction', 'turn_1')
        u = CD.compute_urgency()
        self.assertGreater(u, 0)
        self.assertIsInstance(u, float)


class TestI2GroundingFix(unittest.TestCase):
    """⑥ I2 接地修正: publish semantic_claim_flagged 带非空 turn ref, flagged 不变。"""

    def test_i2_publish_has_turn_ref(self):
        import jarvis_inner_thought_daemon as M
        src = open(M.__file__, encoding='utf-8').read()
        # 修正: metadata 含 audited_turn_id, 取自 TraceContext.get_global_turn_id
        self.assertIn("'audited_turn_id': _audited_turn_id", src,
                      "⑥ publish metadata 应含 audited_turn_id")
        self.assertIn('get_global_turn_id', src,
                      "⑥ turn ref 取自 TraceContext.get_global_turn_id")
        # flagged 字段原样保留 (老消费者不破)
        self.assertIn("metadata={'flagged': flagged,", src,
                      "⑥ flagged 字段原样保留")


class TestI2TurnBindRuntime(_LedgerHarness):
    """⑥+ [C3.1-I2-turnbind-fix] 运行态"指对轮": 真驱 _maybe_semantic_claim_audit,
    断言 publish/记账的 audited_turn_id 指的是**被审那条轮**, 不是事后抓的全局当前轮。
    """

    def _make_daemon(self, stm_last):
        import jarvis_inner_thought_daemon as M
        d = M.InnerThoughtDaemon.__new__(M.InnerThoughtDaemon)

        class _Nerve:
            pass
        nerve = _Nerve()
        nerve.short_term_memory = [stm_last]
        d.nerve = nerve
        d._last_semantic_audit_ts = 0
        d._last_audited_reply = ''
        d._load_lifetime_vocab = lambda: {
            'semantic_claim_check_enabled': True,
            'semantic_claim_check_cooldown_s': 0,
        }
        d._bg_log = lambda *a, **k: None
        return d, M

    def _drive(self, d):
        """运行 audit, 捕获 publish 事件。返 list of publish kwargs。"""
        import jarvis_utils as JU
        published = []

        class _Bus:
            def publish(self, **kw):
                published.append(kw)

        orig = JU.get_event_bus
        JU.get_event_bus = lambda: _Bus()
        try:
            d._maybe_semantic_claim_audit()
        finally:
            JU.get_event_bus = orig
        return published

    def test_binds_to_audited_turn_own_id(self):
        # stm[-1] 自带 turn_id → 绑定必须指它 (最真接地)
        d, _ = self._make_daemon({
            'user': 'hi', 'jarvis': 'I emailed him at 3pm.',
            'time': 't', 'turn_id': 'turn_AUDITED_001',
        })
        d.semantic_claim_audit = lambda reply, tr, blob: [
            {'claim': 'I emailed him at 3pm', 'reason': 'no evidence'}]
        published = self._drive(d)
        self.assertEqual(len(published), 1)
        self.assertEqual(
            published[0]['metadata']['audited_turn_id'], 'turn_AUDITED_001',
            "audited_turn_id 必须 == 被审那条轮自带 turn_id")
        # flagged 原样不变 (老消费者不破)
        self.assertEqual(published[0]['metadata']['flagged'],
                         [{'claim': 'I emailed him at 3pm', 'reason': 'no evidence'}])
        # E_ground 债 ref 指对轮
        led = CD.read_ledger()
        self.assertEqual(len(led), 1)
        self.assertEqual(led[0]['type'], 'E_ground')
        self.assertTrue(led[0]['provenance_ref']['ref'].startswith('turn_AUDITED_001'),
                        "E_ground ref 必须指被审轮, 非任意非空值")

    def test_global_fallback_captured_before_llm_no_drift(self):
        # stm[-1] 无 turn_id → 退全局态, 但必须在 LLM 调用**前**捕获:
        # 模拟审计期间主线程 new_turn() 推进全局 → 断言记的仍是被审旧轮, 不漂。
        import jarvis_utils as JU
        d, _ = self._make_daemon({
            'user': 'hi', 'jarvis': 'claim text here', 'time': 't'})
        orig_tid = JU.TraceContext._turn_id
        JU.TraceContext._turn_id = 'turn_OLD_before_audit'

        def _audit(reply, tr, blob):
            # 模拟: LLM 调用耗时期间, 主线程切了新轮
            JU.TraceContext._turn_id = 'turn_NEW_during_llm'
            return [{'claim': 'claim text here', 'reason': 'x'}]

        d.semantic_claim_audit = _audit
        try:
            published = self._drive(d)
        finally:
            JU.TraceContext._turn_id = orig_tid
        self.assertEqual(len(published), 1)
        self.assertEqual(
            published[0]['metadata']['audited_turn_id'], 'turn_OLD_before_audit',
            "退全局态时必须在 LLM 前捕获, 不被审计期间 new_turn 带漂")
        self.assertNotEqual(
            published[0]['metadata']['audited_turn_id'], 'turn_NEW_during_llm',
            "绝不能抓到审计期间推进的新轮")
        led = CD.read_ledger()
        self.assertEqual(len(led), 1)
        self.assertTrue(
            led[0]['provenance_ref']['ref'].startswith('turn_OLD_before_audit'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
