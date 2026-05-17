# -*- coding: utf-8 -*-
"""[P0+20-β.2.5 / 2026-05-17] 灵魂工程 Layer 4 - Reflector daemons 测试

ConcernsReflector (同步 helper / 每轮对话末尾启发式 keyword 匹配)
WeeklyReflector  (daemon / 7d LLM 反思 → propose 新 concerns 进 review)

详 docs/JARVIS_SOUL_DRIVE.md §6
"""
import os
import sys
import time
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_concerns import (
    Concern, ConcernsLedger,
    bootstrap_default_concerns,
    STATE_ACTIVE, STATE_REVIEW, STATE_ARCHIVED,
)
from jarvis_soul_reflector import (
    ConcernsReflector, WeeklyReflector, CONCERN_KEYWORDS,
    WEEKLY_REFLECTOR_CONFIG,
    get_default_concerns_reflector,
    reset_default_reflectors_for_test,
)


# ============================================================
# A. CONCERN_KEYWORDS 表 sanity
# ============================================================
class TestConcernKeywordsTable(unittest.TestCase):

    def test_all_5_seed_concerns_have_keywords(self):
        for cid in ('sir_sleep_streak', 'sir_pomodoro_compliance',
                    'sir_cursor_payment', 'unfinished_jiazhao_ke1',
                    'jarvis_keyrouter_health'):
            self.assertIn(cid, CONCERN_KEYWORDS, f"keyword 表缺 {cid}")
            self.assertGreater(len(CONCERN_KEYWORDS[cid]), 0)

    def test_keyword_entries_have_delta(self):
        for cid, kw_list in CONCERN_KEYWORDS.items():
            for kw, delta in kw_list:
                self.assertIsInstance(kw, str)
                self.assertIsInstance(delta, (int, float))
                self.assertGreater(delta, 0)
                self.assertLess(delta, 0.2, f"single keyword delta 过大: {cid}/{kw}")


# ============================================================
# B. ConcernsReflector._scan_text
# ============================================================
class TestConcernsReflectorScan(unittest.TestCase):

    def setUp(self):
        ledger = ConcernsLedger()
        self.reflector = ConcernsReflector(ledger)

    def test_empty_text_no_hits(self):
        self.assertEqual(self.reflector._scan_text(''), {})
        self.assertEqual(self.reflector._scan_text('   '), {})

    def test_sleep_keyword_hits(self):
        hits = self.reflector._scan_text("I'm exhausted, going to bed")
        self.assertIn('sir_sleep_streak', hits)
        self.assertGreater(hits['sir_sleep_streak'], 0)

    def test_chinese_keyword_hits(self):
        hits = self.reflector._scan_text("熬夜到凌晨三点了")
        self.assertIn('sir_sleep_streak', hits)

    def test_cursor_payment_hits(self):
        hits = self.reflector._scan_text("Cursor subscription billing failed today")
        self.assertIn('sir_cursor_payment', hits)

    def test_jiazhao_chinese_hits(self):
        hits = self.reflector._scan_text("驾照科一还没考")
        self.assertIn('unfinished_jiazhao_ke1', hits)

    def test_multi_concern_hits(self):
        """一句话同时触发多个 concern"""
        hits = self.reflector._scan_text("熬夜赶 cursor 项目，颈椎都僵了")
        self.assertIn('sir_sleep_streak', hits)
        self.assertIn('sir_cursor_payment', hits)
        self.assertIn('sir_pomodoro_compliance', hits)

    def test_severity_delta_capped_per_concern_per_turn(self):
        """单 concern 单轮 cap=0.15，避免一句话出现 5 个 keyword 涨太多"""
        text = "sleep tired bed exhausted 熬夜 困 累 睡眠 凌晨"
        hits = self.reflector._scan_text(text)
        self.assertIn('sir_sleep_streak', hits)
        self.assertLessEqual(hits['sir_sleep_streak'], 0.15)

    def test_no_false_positive_neutral_text(self):
        """中性文本不应触发 concern"""
        hits = self.reflector._scan_text("hello jarvis, what time is it?")
        self.assertEqual(hits, {})


# ============================================================
# C. ConcernsReflector.reflect_turn 端到端
# ============================================================
class TestConcernsReflectorReflectTurn(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.ledger = ConcernsLedger(persist_path=self.tmp.name)
        bootstrap_default_concerns(self.ledger)
        self.reflector = ConcernsReflector(self.ledger)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_reflect_turn_records_signals(self):
        recorded = self.reflector.reflect_turn(
            user_input='I am exhausted, going to bed soon',
            jarvis_reply='Of course, Sir. Sleep well.',
            turn_id='turn_test_1',
        )
        self.assertIn('sir_sleep_streak', recorded)
        c = self.ledger.get('sir_sleep_streak')
        self.assertGreater(len(c.recent_signals), 0)
        last = c.recent_signals[-1]
        self.assertEqual(last['turn_id'], 'turn_test_1')
        # snippet 取第一个命中 keyword 周围，含 bed/exhausted/sleep 任一即可
        self.assertTrue(
            any(kw in last['what'].lower() for kw in ('bed', 'exhausted', 'sleep')),
            f"signal snippet 应含 sleep 相关 keyword，实际: {last['what']!r}"
        )

    def test_reflect_turn_no_signal_clean_text(self):
        recorded = self.reflector.reflect_turn(
            user_input='hello there',
            jarvis_reply='Hello, Sir.',
        )
        self.assertEqual(recorded, {})

    def test_reflect_turn_severity_increased(self):
        old = self.ledger.get('sir_sleep_streak').severity
        self.reflector.reflect_turn(
            user_input='exhausted, late night again',
            jarvis_reply='I see, Sir.',
        )
        new = self.ledger.get('sir_sleep_streak').severity
        self.assertGreater(new, old)

    def test_reflect_turn_stats_updated(self):
        self.reflector.reflect_turn(user_input='exhausted')
        self.reflector.reflect_turn(user_input='cursor billing fail')
        stats = self.reflector.get_stats()
        self.assertEqual(stats['turns_reflected'], 2)
        self.assertGreaterEqual(stats['signals_recorded'], 2)

    def test_reflect_turn_none_ledger_no_crash(self):
        r = ConcernsReflector(None)
        self.assertEqual(r.reflect_turn(user_input='exhausted'), {})


# ============================================================
# D. ConcernsLedger.propose（β.2.5 新加）
# ============================================================
class TestConcernsLedgerPropose(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.ledger = ConcernsLedger(persist_path=self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_propose_forces_review_state(self):
        c = Concern(
            id='new_c', what_i_watch='X', why_i_care='Y',
            severity=0.5, state=STATE_ACTIVE  # 即使来时是 active 也应被强制 review
        )
        self.assertTrue(self.ledger.propose(c))
        got = self.ledger.get('new_c')
        self.assertEqual(got.state, STATE_REVIEW)

    def test_propose_in_list_review(self):
        c = Concern(id='c1', what_i_watch='X', why_i_care='Y')
        self.ledger.propose(c)
        review_list = self.ledger.list_review()
        self.assertEqual(len(review_list), 1)
        self.assertEqual(review_list[0].id, 'c1')

    def test_propose_not_in_list_active(self):
        c = Concern(id='c1', what_i_watch='X', why_i_care='Y')
        self.ledger.propose(c)
        self.assertEqual(len(self.ledger.list_active()), 0)

    def test_propose_then_activate(self):
        c = Concern(id='c1', what_i_watch='X', why_i_care='Y')
        self.ledger.propose(c)
        self.assertTrue(self.ledger.activate('c1'))
        self.assertEqual(self.ledger.get('c1').state, STATE_ACTIVE)


# ============================================================
# E. WeeklyReflector mock 端到端
# ============================================================
class TestWeeklyReflectorMockedLLM(unittest.TestCase):
    """mock safe_openrouter_call + key_router 测 propose 流程。
    不真调 OpenRouter（避免 cost / 抖动）。"""

    def setUp(self):
        reset_default_reflectors_for_test()
        self.tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.ledger = ConcernsLedger(persist_path=self.tmp.name)
        bootstrap_default_concerns(self.ledger)

        # Fake key router
        self.key_router = MagicMock()
        self.key_router.get_openrouter_key.return_value = ('fake_key', 'or_1')

        # 模拟 50 条 STM（够 min_stm_for_reflection 10）
        self.stm = [
            {'time': '10:00', 'user': f'turn {i} user', 'jarvis': f'turn {i} reply'}
            for i in range(30)
        ]
        self.profile = {
            'core_philosophy': 'pragmatic dev',
            'work_rhythms': 'night owl',
        }

    def tearDown(self):
        reset_default_reflectors_for_test()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def _make_reflector(self):
        return WeeklyReflector(
            concerns_ledger=self.ledger,
            key_router=self.key_router,
            stm_provider=lambda: self.stm,
            profile_provider=lambda: self.profile,
        )

    def test_force_run_now_proposes_new_concerns(self):
        """LLM 返回合法 JSON 含 proposed_concerns → ledger.propose 调用 → review 队列加条"""
        mock_response = (
            '{"proposed_concerns": ['
            '{"id":"sir_eye_strain","what_i_watch":"Sir long screen sessions",'
            '"why_i_care":"frequent eye complaints in STM","severity":0.4}'
            ']}'
        )
        with patch('jarvis_soul_reflector.safe_openrouter_call',
                   return_value=mock_response):
            r = self._make_reflector()
            result = r.force_run_now()
        self.assertEqual(result.get('proposed_n'), 1)
        proposed = self.ledger.get('sir_eye_strain')
        self.assertIsNotNone(proposed)
        self.assertEqual(proposed.state, STATE_REVIEW)
        self.assertEqual(proposed.source, 'weekly_reflector')

    def test_empty_array_no_propose(self):
        with patch('jarvis_soul_reflector.safe_openrouter_call',
                   return_value='{"proposed_concerns": []}'):
            r = self._make_reflector()
            result = r.force_run_now()
        self.assertEqual(result.get('proposed_n'), 0)

    def test_invalid_json_no_crash(self):
        with patch('jarvis_soul_reflector.safe_openrouter_call',
                   return_value='this is not json'):
            r = self._make_reflector()
            result = r.force_run_now()
        self.assertEqual(result.get('proposed_n'), 0)
        self.assertIn('reason', result)

    def test_llm_failure_no_crash(self):
        """LLM 调用抛异常 → 不影响主路径"""
        def _raise(*a, **kw):
            raise RuntimeError('mock LLM down')
        with patch('jarvis_soul_reflector.safe_openrouter_call', side_effect=_raise):
            r = self._make_reflector()
            result = r.force_run_now()
        self.assertEqual(result.get('proposed_n'), 0)
        self.assertIn('LLM', result.get('reason', ''))

    def test_max_propose_cap_enforced(self):
        """LLM 返 10 条 → 只取 max_propose_per_run=3"""
        many = ','.join([
            f'{{"id":"c{i}","what_i_watch":"watch {i}","why_i_care":"reason {i}","severity":0.3}}'
            for i in range(10)
        ])
        mock = f'{{"proposed_concerns": [{many}]}}'
        with patch('jarvis_soul_reflector.safe_openrouter_call', return_value=mock):
            r = self._make_reflector()
            result = r.force_run_now()
        self.assertEqual(result.get('proposed_n'),
                         WEEKLY_REFLECTOR_CONFIG['max_propose_per_run'])

    def test_no_key_router_no_crash(self):
        r = WeeklyReflector(
            concerns_ledger=self.ledger, key_router=None,
            stm_provider=lambda: self.stm,
            profile_provider=lambda: self.profile,
        )
        result = r.force_run_now()
        self.assertEqual(result.get('proposed_n'), 0)
        self.assertIn('no key_router', result.get('reason', ''))

    def test_proposed_concerns_validated(self):
        """propose entry 缺 required 字段时被跳过"""
        mock = (
            '{"proposed_concerns": ['
            '{"id":"valid","what_i_watch":"X","why_i_care":"Y","severity":0.3},'
            '{"id":"no_watch","why_i_care":"Y","severity":0.3},'
            '{"what_i_watch":"X","why_i_care":"Y","severity":0.3},'
            '{"id":"empty","what_i_watch":"","why_i_care":"","severity":0.3}'
            ']}'
        )
        with patch('jarvis_soul_reflector.safe_openrouter_call', return_value=mock):
            r = self._make_reflector()
            result = r.force_run_now()
        # 只有 'valid' 被添加
        self.assertEqual(result.get('proposed_n'), 1)
        self.assertIsNotNone(self.ledger.get('valid'))


# ============================================================
# [β.2.7.4 / 2026-05-17] WeeklyReflector prompt + 模型升级回归测试
# 治 Sir 反馈：把 "01:55 goodnight → 08:25 morning" 沉默 6.5h 误判成 insomnia
# ============================================================
class TestWeeklyReflectorInterpretationRules(unittest.TestCase):
    """验证 prompt 含 STM 时间戳间隔 ≠ 行为推断 的约束 + 模型升级"""

    def test_prompt_contains_interpretation_rules(self):
        """[β.2.7.4] prompt 必须含 INTERPRETATION RULES 段"""
        from jarvis_soul_reflector import WEEKLY_REFLECTOR_PROMPT
        self.assertIn('INTERPRETATION RULES', WEEKLY_REFLECTOR_PROMPT)
        # 关键约束：长间隔不算失眠证据
        self.assertIn('失眠', WEEKLY_REFLECTOR_PROMPT)
        self.assertIn('正常睡眠', WEEKLY_REFLECTOR_PROMPT)
        self.assertIn('insomnia', WEEKLY_REFLECTOR_PROMPT)
        # 必须有直接证据条款
        self.assertIn('直接证据', WEEKLY_REFLECTOR_PROMPT)

    def test_prompt_warns_about_timestamp_interval(self):
        from jarvis_soul_reflector import WEEKLY_REFLECTOR_PROMPT
        # 必须明确"时间戳间隔" + "不是行为推断"
        self.assertIn('时间戳', WEEKLY_REFLECTOR_PROMPT)
        # 必须有 4h 阈值说明
        self.assertTrue('4h' in WEEKLY_REFLECTOR_PROMPT or '>= 4' in WEEKLY_REFLECTOR_PROMPT)

    def test_primary_model_upgraded_to_gemini_3_1_pro(self):
        """[β.2.7.4] primary model 升级到 gemini-3.1-pro-preview 提高判断质量"""
        from jarvis_soul_reflector import WEEKLY_REFLECTOR_CONFIG
        self.assertEqual(
            WEEKLY_REFLECTOR_CONFIG['primary_model'],
            'google/gemini-3.1-pro-preview'
        )

    def test_fallback_model_still_lite_for_quota_safety(self):
        """fallback 保留 lite 兜底，primary 失败时不挂"""
        from jarvis_soul_reflector import WEEKLY_REFLECTOR_CONFIG
        self.assertIn('flash-lite', WEEKLY_REFLECTOR_CONFIG['fallback_model'])


# ============================================================
# F. Singleton + lifecycle
# ============================================================
class TestReflectorSingleton(unittest.TestCase):

    def setUp(self):
        reset_default_reflectors_for_test()

    def tearDown(self):
        reset_default_reflectors_for_test()

    def test_get_default_concerns_reflector_returns_same(self):
        ledger = ConcernsLedger()
        bootstrap_default_concerns(ledger)
        r1 = get_default_concerns_reflector(ledger)
        r2 = get_default_concerns_reflector(ledger)
        self.assertIs(r1, r2)

    def test_get_default_returns_none_when_ledger_missing(self):
        r = get_default_concerns_reflector(None)
        self.assertIsNone(r)


if __name__ == '__main__':
    unittest.main(verbosity=2)
