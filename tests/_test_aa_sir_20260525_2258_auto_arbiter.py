# -*- coding: utf-8 -*-
"""[AA / Sir 2026-05-25 22:58 自决] AutoArbiterDaemon 测试.

L0: 模块导入 + 数据结构
L1: Risk classification + threshold mapping
L2: LLM output parser (3 tag strict)
L3: Decide mapping (low/medium risk × conf vs threshold)
L4: Execute (mock relational store activate/reject)
L5: Sir revert (反向 active/archived)
L6: Daily reflection (24h revert_rate → threshold 调)
L7: Persistence (load + save calibration)
L8: Central nerve + KeyRouter + Dashboard 集成 anchor
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
# L0: 模块 + 数据结构
# ==========================================================================
class TestL0ModuleAndDataclass(unittest.TestCase):
    def test_module_imports(self):
        import jarvis_auto_arbiter as m
        self.assertTrue(hasattr(m, 'AutoArbiterDaemon'))
        self.assertTrue(hasattr(m, 'ArbiterDecision'))
        self.assertTrue(hasattr(m, 'get_default_daemon'))
        self.assertTrue(hasattr(m, 'set_default_daemon'))

    def test_dataclass_fields(self):
        from jarvis_auto_arbiter import ArbiterDecision
        d = ArbiterDecision(
            id='aa_001', ts=1000.0, ts_iso='2026-05-25T22:58:00',
            kind='inside_joke', item_id='joke_001', item_preview='test',
            risk_level='low', decision='activate', confidence=0.85,
            reason='test reason', threshold_at_decision=0.75,
        )
        self.assertEqual(d.id, 'aa_001')
        self.assertEqual(d.executed_ok, False)
        self.assertEqual(d.sir_reverted, False)


# ==========================================================================
# L1: Risk + threshold
# ==========================================================================
class TestL1RiskAndThreshold(unittest.TestCase):
    def setUp(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        self.daemon = AutoArbiterDaemon(key_router=None)

    def test_risk_classification(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        self.assertIn('inside_joke', AutoArbiterDaemon.RISK_LOW)
        self.assertIn('thread', AutoArbiterDaemon.RISK_LOW)
        self.assertIn('concern', AutoArbiterDaemon.RISK_MEDIUM)
        self.assertIn('directive', AutoArbiterDaemon.RISK_MEDIUM)

    def test_default_thresholds(self):
        thr = self.daemon._effective_thresholds()
        self.assertEqual(thr['inside_joke'], 0.75)
        self.assertEqual(thr['thread'], 0.75)
        self.assertEqual(thr['concern'], 0.85)
        self.assertEqual(thr['directive'], 0.90)

    def test_threshold_floor_ceiling(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        self.assertGreaterEqual(AutoArbiterDaemon.THRESHOLD_FLOOR, 0.5)
        self.assertLessEqual(AutoArbiterDaemon.THRESHOLD_CEILING, 0.95)


# ==========================================================================
# L2: LLM output parser
# ==========================================================================
class TestL2ParseLLMOutput(unittest.TestCase):
    def setUp(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        self.daemon = AutoArbiterDaemon(key_router=None)

    def test_parse_valid_activate(self):
        raw = """<ACTION>ACTIVATE</ACTION>
<CONFIDENCE>0.85</CONFIDENCE>
<REASON>Phrase appeared 3 times in STM with playful tone.</REASON>"""
        a, c, r = self.daemon._parse_llm_output(raw)
        self.assertEqual(a, 'activate')
        self.assertEqual(c, 0.85)
        self.assertIn('STM', r)

    def test_parse_valid_reject(self):
        raw = """<ACTION>REJECT</ACTION>
<CONFIDENCE>0.40</CONFIDENCE>
<REASON>Overlaps with existing joke 'old_phrase'.</REASON>"""
        a, c, r = self.daemon._parse_llm_output(raw)
        self.assertEqual(a, 'reject')
        self.assertEqual(c, 0.40)

    def test_parse_missing_tags_returns_reject(self):
        a, c, r = self.daemon._parse_llm_output('garbage no tags')
        self.assertEqual(a, 'reject')
        self.assertEqual(c, 0.0)
        self.assertIn('parse fail', r)

    def test_parse_clamps_confidence(self):
        raw = """<ACTION>ACTIVATE</ACTION>
<CONFIDENCE>1.5</CONFIDENCE>
<REASON>too high</REASON>"""
        _, c, _ = self.daemon._parse_llm_output(raw)
        self.assertEqual(c, 1.0)


# ==========================================================================
# L3: Decide mapping
# ==========================================================================
class TestL3DecideMapping(unittest.TestCase):
    def setUp(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        self.daemon = AutoArbiterDaemon(key_router=None)

    def test_low_risk_high_conf_activates(self):
        d = self.daemon._decide('activate', 0.85, 0.75, 'low')
        self.assertEqual(d, 'activate')

    def test_low_risk_low_conf_defers(self):
        d = self.daemon._decide('activate', 0.60, 0.75, 'low')
        self.assertEqual(d, 'defer_to_sir')

    def test_low_risk_reject_high_conf(self):
        d = self.daemon._decide('reject', 0.90, 0.75, 'low')
        self.assertEqual(d, 'reject')

    def test_medium_risk_always_defers(self):
        """中风险即使 conf 高也只 defer (不真执行 concern/directive)."""
        d = self.daemon._decide('activate', 0.95, 0.85, 'medium')
        self.assertEqual(d, 'defer_to_sir')
        d = self.daemon._decide('reject', 0.95, 0.85, 'medium')
        self.assertEqual(d, 'defer_to_sir')

    def test_invalid_action_noop(self):
        d = self.daemon._decide('something_else', 0.95, 0.75, 'low')
        self.assertEqual(d, 'noop')


# ==========================================================================
# L4: Execute (mock relational)
# ==========================================================================
class TestL4Execute(unittest.TestCase):
    def setUp(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        self.mock_relational = MagicMock()
        self.daemon = AutoArbiterDaemon(
            key_router=None,
            relational_state=self.mock_relational,
        )

    def test_execute_activate_inside_joke(self):
        self.mock_relational.activate_from_review = MagicMock(return_value='joke')
        ok, msg = self.daemon._execute('inside_joke', 'joke_001', 'activate')
        self.assertTrue(ok)
        self.assertIn('activated as joke', msg)
        self.mock_relational.activate_from_review.assert_called_once_with('joke_001')

    def test_execute_reject_thread(self):
        self.mock_relational.reject_from_review = MagicMock(return_value='thread')
        ok, msg = self.daemon._execute('thread', 'thread_001', 'reject')
        self.assertTrue(ok)
        self.assertIn('rejected as thread', msg)

    def test_execute_unknown_kind_fails(self):
        ok, msg = self.daemon._execute('something', 'x', 'activate')
        self.assertFalse(ok)
        self.assertIn('not supported', msg)

    def test_execute_empty_returns_false(self):
        self.mock_relational.activate_from_review = MagicMock(return_value='')
        ok, msg = self.daemon._execute('inside_joke', 'joke_001', 'activate')
        self.assertFalse(ok)


# ==========================================================================
# L5: Sir revert (反向 active/archived)
# ==========================================================================
class TestL5SirRevert(unittest.TestCase):
    def setUp(self):
        # 🆕 [Sir 2026-05-26 SOUL Phase A test isolation] patch class attr 在 __init__ 前,
        # 防 prod memory_pool/auto_arbiter_log.jsonl 污染 _decisions list.
        from jarvis_auto_arbiter import AutoArbiterDaemon
        self._tmp = tempfile.mkdtemp(prefix='aa_l5_')
        self._saved_persist = AutoArbiterDaemon.PERSIST_PATH
        self._saved_calib = AutoArbiterDaemon.CALIBRATION_PATH
        AutoArbiterDaemon.PERSIST_PATH = os.path.join(self._tmp, 'log.jsonl')
        AutoArbiterDaemon.CALIBRATION_PATH = os.path.join(self._tmp, 'cal.json')

    def tearDown(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        AutoArbiterDaemon.PERSIST_PATH = self._saved_persist
        AutoArbiterDaemon.CALIBRATION_PATH = self._saved_calib
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_daemon(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon, ArbiterDecision
        mock_rel = MagicMock()
        mock_entity = MagicMock(state='active')
        mock_rel.inside_jokes = {'joke_001': mock_entity}
        mock_rel.shared_history_threads = {}
        mock_rel._dirty = False
        d = AutoArbiterDaemon(key_router=None, relational_state=mock_rel)
        # 添加一条已 activate 的 decision
        d._decisions.append(ArbiterDecision(
            id='aa_test_001', ts=time.time(),
            ts_iso='2026-05-25T22:58:00',
            kind='inside_joke', item_id='joke_001',
            item_preview='test', risk_level='low',
            decision='activate', confidence=0.85,
            reason='test', threshold_at_decision=0.75,
            executed_ok=True,
        ))
        return d, mock_entity

    def test_revert_unknown_id_fails(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        d = AutoArbiterDaemon(key_router=None)
        ok, msg = d.sir_revert('does_not_exist')
        self.assertFalse(ok)
        self.assertIn('not found', msg)

    def test_revert_activate_archives_entity(self):
        d, ent = self._make_daemon()
        with tempfile.TemporaryDirectory() as tmp:
            d.PERSIST_PATH = os.path.join(tmp, 'log.jsonl')
            ok, msg = d.sir_revert('aa_test_001', 'Sir 不喜欢这个 joke')
        self.assertTrue(ok)
        self.assertEqual(ent.state, 'archived',
            '撤销 activate 后, entity.state 必须 → archived')
        # mark sir_reverted
        target = d._decisions[0]
        self.assertTrue(target.sir_reverted)
        self.assertIn('不喜欢', target.sir_revert_reason)

    def test_revert_twice_fails(self):
        d, _ = self._make_daemon()
        with tempfile.TemporaryDirectory() as tmp:
            d.PERSIST_PATH = os.path.join(tmp, 'log.jsonl')
            ok1, _ = d.sir_revert('aa_test_001', 'first')
            self.assertTrue(ok1)
            ok2, msg2 = d.sir_revert('aa_test_001', 'second')
            self.assertFalse(ok2)
            self.assertIn('already reverted', msg2)


# ==========================================================================
# L6: Daily reflection (revert_rate → threshold 调)
# ==========================================================================
class TestL6DailyReflection(unittest.TestCase):
    def _make_daemon_with_decisions(self, decisions_data):
        from jarvis_auto_arbiter import AutoArbiterDaemon, ArbiterDecision
        d = AutoArbiterDaemon(key_router=None)
        d._decisions = [ArbiterDecision(**dd) for dd in decisions_data]
        return d

    def _decision(self, kind, decision, sir_reverted=False, ts_offset=0):
        return {
            'id': f'aa_{kind}_{decision}_{int(time.time() * 1000) + ts_offset}',
            'ts': time.time() - ts_offset,
            'ts_iso': '?',
            'kind': kind, 'item_id': f'{kind}_x', 'item_preview': '',
            'risk_level': 'low', 'decision': decision,
            'confidence': 0.8, 'reason': '', 'threshold_at_decision': 0.75,
            'executed_ok': True,
            'sir_reverted': sir_reverted,
        }

    def test_high_revert_rate_raises_threshold(self):
        """6 个 decisions, 5 个 reverted → revert_rate=83% > 30% → 阈值升 0.05."""
        decisions = [
            self._decision('inside_joke', 'activate',
                            sir_reverted=(i < 5), ts_offset=i * 10)
            for i in range(6)
        ]
        d = self._make_daemon_with_decisions(decisions)
        with tempfile.TemporaryDirectory() as tmp:
            d.CALIBRATION_PATH = os.path.join(tmp, 'cal.json')
            d._do_daily_reflection()
        new_thr = d._effective_thresholds()['inside_joke']
        self.assertAlmostEqual(new_thr, 0.80, places=2,
            msg='revert_rate>30% → 阈值升 0.05 (0.75 → 0.80)')

    def test_low_revert_rate_lowers_threshold(self):
        """10 decisions 全 OK → revert_rate=0% < 10% & total>=5 → 阈值降 0.02."""
        decisions = [
            self._decision('thread', 'activate', sir_reverted=False,
                            ts_offset=i * 10)
            for i in range(10)
        ]
        d = self._make_daemon_with_decisions(decisions)
        with tempfile.TemporaryDirectory() as tmp:
            d.CALIBRATION_PATH = os.path.join(tmp, 'cal.json')
            d._do_daily_reflection()
        new_thr = d._effective_thresholds()['thread']
        self.assertAlmostEqual(new_thr, 0.73, places=2,
            msg='revert_rate<10% & total>=5 → 阈值降 0.02 (0.75 → 0.73)')

    def test_few_decisions_no_change(self):
        """少 decisions (<5) 不动."""
        decisions = [
            self._decision('inside_joke', 'activate', sir_reverted=False,
                            ts_offset=i * 10)
            for i in range(2)
        ]
        d = self._make_daemon_with_decisions(decisions)
        with tempfile.TemporaryDirectory() as tmp:
            d.CALIBRATION_PATH = os.path.join(tmp, 'cal.json')
            d._do_daily_reflection()
        self.assertEqual(d._effective_thresholds()['inside_joke'], 0.75,
            '少 decisions 不调')


# ==========================================================================
# L7: Persistence
# ==========================================================================
class TestL7Persistence(unittest.TestCase):
    def setUp(self):
        # 🆕 [Sir 2026-05-26 SOUL Phase A test isolation] patch class attr 在 __init__ 前.
        from jarvis_auto_arbiter import AutoArbiterDaemon
        self._tmp = tempfile.mkdtemp(prefix='aa_l7_')
        self._saved_persist = AutoArbiterDaemon.PERSIST_PATH
        self._saved_calib = AutoArbiterDaemon.CALIBRATION_PATH
        AutoArbiterDaemon.PERSIST_PATH = os.path.join(self._tmp, 'class_log.jsonl')
        AutoArbiterDaemon.CALIBRATION_PATH = os.path.join(self._tmp, 'cal.json')

    def tearDown(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        AutoArbiterDaemon.PERSIST_PATH = self._saved_persist
        AutoArbiterDaemon.CALIBRATION_PATH = self._saved_calib
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_persist_and_load_decision(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon, ArbiterDecision
        with tempfile.TemporaryDirectory() as tmp:
            persist = os.path.join(tmp, 'log.jsonl')
            AutoArbiterDaemon.PERSIST_PATH = persist  # patch 在 init 前
            d = AutoArbiterDaemon(key_router=None)
            d.PERSIST_PATH = persist
            dec = ArbiterDecision(
                id='aa_t1', ts=time.time(), ts_iso='?',
                kind='inside_joke', item_id='joke_001',
                item_preview='hello', risk_level='low',
                decision='activate', confidence=0.85, reason='ok',
                threshold_at_decision=0.75, executed_ok=True,
            )
            d._persist_decision(dec)
            # reload (d2 init 时已经 load 一次, 重置 + reload 验证 disk 有 1 条)
            d2 = AutoArbiterDaemon(key_router=None)
            d2.PERSIST_PATH = persist
            d2._decisions = []
            d2._load_persist()
            self.assertEqual(len(d2._decisions), 1)
            self.assertEqual(d2._decisions[0].id, 'aa_t1')

    def test_load_dedup_by_id(self):
        """同 id 多次写 (revert 后), 应只 load 最新."""
        from jarvis_auto_arbiter import AutoArbiterDaemon, ArbiterDecision
        with tempfile.TemporaryDirectory() as tmp:
            persist = os.path.join(tmp, 'log.jsonl')
            AutoArbiterDaemon.PERSIST_PATH = persist  # patch 在 init 前
            d = AutoArbiterDaemon(key_router=None)
            d.PERSIST_PATH = persist
            dec = ArbiterDecision(
                id='aa_t2', ts=time.time(), ts_iso='?',
                kind='thread', item_id='thread_001',
                item_preview='', risk_level='low',
                decision='activate', confidence=0.85, reason='',
                threshold_at_decision=0.75, executed_ok=True,
            )
            d._persist_decision(dec)
            dec.sir_reverted = True
            dec.sir_revert_reason = 'Sir 撤了'
            d._persist_decision(dec)
            # 2 行 jsonl 同 id
            AutoArbiterDaemon.PERSIST_PATH = persist  # 保证 d2 也 init 前 patch
            d2 = AutoArbiterDaemon(key_router=None)
            d2.PERSIST_PATH = persist
            d2._decisions = []  # 重置 避免 init 时 load 遗留
            d2._load_persist()
            self.assertEqual(len(d2._decisions), 1,
                'load 必须按 id dedup (取最新)')
            self.assertTrue(d2._decisions[0].sir_reverted,
                'load 后应该看到 sir_reverted=True (最新版)')

    def test_save_and_load_calibration(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        with tempfile.TemporaryDirectory() as tmp:
            cal_path = os.path.join(tmp, 'cal.json')
            d = AutoArbiterDaemon(key_router=None)
            d.CALIBRATION_PATH = cal_path
            d._calibration['thresholds']['inside_joke'] = 0.82
            d._save_calibration()
            # reload
            d2 = AutoArbiterDaemon(key_router=None)
            d2.CALIBRATION_PATH = cal_path
            d2._load_calibration()
            self.assertEqual(d2._calibration['thresholds']['inside_joke'], 0.82)


# ==========================================================================
# L8: Central nerve + KeyRouter + Dashboard 集成 anchor
# ==========================================================================
class TestL8Integration(unittest.TestCase):
    """纯源码 anchor (避 dashboard sys.stdout 跟 pytest capture 冲突)."""

    @classmethod
    def setUpClass(cls):
        cls.nerve_src = open(
            os.path.join(ROOT, 'jarvis_central_nerve.py'),
            'r', encoding='utf-8'
        ).read()
        cls.key_router_src = open(
            os.path.join(ROOT, 'jarvis_key_router.py'),
            'r', encoding='utf-8'
        ).read()
        cls.dashboard_src = open(
            os.path.join(ROOT, 'scripts', 'jarvis_dashboard_web.py'),
            'r', encoding='utf-8'
        ).read()

    def test_central_nerve_calls_init_auto_arbiter(self):
        self.assertIn('self._init_auto_arbiter()', self.nerve_src,
            'CentralNerve.__init__ 必须调 _init_auto_arbiter')
        self.assertIn('def _init_auto_arbiter', self.nerve_src,
            '必须有 _init_auto_arbiter method')

    def test_key_router_has_auto_arbiter_caller(self):
        from jarvis_key_router import KeyRouter
        self.assertTrue(hasattr(KeyRouter, 'CALLER_AUTO_ARBITER'))
        self.assertEqual(KeyRouter.CALLER_AUTO_ARBITER, 'auto_arbiter')

    def test_auto_arbiter_is_low_priority(self):
        from jarvis_key_router import KeyRouter
        kr = KeyRouter(
            main_brain_key='m', google_keys=['g'], openrouter_keys=['o']
        )
        self.assertEqual(kr._default_priority('auto_arbiter'),
                          KeyRouter.PRIORITY_LOW,
            'auto_arbiter 必须默认 LOW priority')

    def test_dashboard_has_auto_arbiter_routes(self):
        self.assertIn("@app.route('/auto_arbiter')", self.dashboard_src)
        self.assertIn("@app.route('/api/auto_arbiter')", self.dashboard_src)
        self.assertIn("@app.route('/api/auto_arbiter/revert'",
                       self.dashboard_src)

    def test_dashboard_translates_kinds_to_chinese(self):
        for zh in ('内梗', '历史线', '关怀', '指令'):
            self.assertIn(zh, self.dashboard_src,
                f'dashboard 必须含中文 "{zh}"')

    def test_dashboard_translates_decisions_to_chinese(self):
        for zh in ('通过', '拒绝', '建议 Sir 看', '不动'):
            self.assertIn(zh, self.dashboard_src,
                f'dashboard 必须含中文 decision "{zh}"')

    def test_dashboard_header_has_auto_arbiter_button(self):
        self.assertIn('🤖 自决', self.dashboard_src,
            'header 必须有 "🤖 自决" 按钮')
        self.assertIn('href="/auto_arbiter"', self.dashboard_src,
            'header 按钮必须链到 /auto_arbiter')


if __name__ == '__main__':
    unittest.main()
