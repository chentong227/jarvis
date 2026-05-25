# -*- coding: utf-8 -*-
"""[WRC / Sir 2026-05-25 23:52 真问 "Step 3 也做"] WeeklyReflectionConsolidator.

Sir 真意:
  "Step 3 周反思 → sir_profile.work_rhythms 演化 也要做",
  +
  "全部修好了？刚才要做的东西呢？继续做吧" (2026-05-26 00:07 验证测试)

灵魂工程 Layer 4.5 — 周反思合并器. 验证:
  L1 模块基础 + 数据结构 (WeeklyInsight schema, _maybe_fire 时机)
  L2 evidence 收集 (hippocampus 7d search, MIN_EVIDENCE_COUNT 阈值)
  L3 LLM extract pattern (3 tag 解析, confidence floor, 'no clear pattern' filter)
  L4 持久化 (JSONL + maybe_rotate + load 90 天 cutoff)
  L5 SWM publish (etype=weekly_insight_proposed, salience >= 0.85, 14d TTL)
  L6 Sir decide API (accept/reject 切 state + persist)
  L7 central_nerve 集成 anchor (避免再次漏 _init_weekly_reflection_consolidator)
  L8 dashboard API + page 集成 anchor (Sir 真看到 + 一键 decide)
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


def _empty_consolidator(tmp_jsonl: str):
    """Build 一个 fresh consolidator with PERSIST_PATH 指向临时 jsonl.

    用 instance attribute set 确保 _persist_insight 全程读 tmp (避免 patch.object
    在 with 退出后恢复 class attr 导致写到生产 memory_pool/ 路径).
    init 时也需要正确 PERSIST_PATH 给 _load_persist 用, 所以先 class-level 临时
    替换, init 后 instance-level 持续 override.
    """
    from jarvis_weekly_reflection_consolidator import WeeklyReflectionConsolidator
    saved = WeeklyReflectionConsolidator.PERSIST_PATH
    WeeklyReflectionConsolidator.PERSIST_PATH = tmp_jsonl
    try:
        c = WeeklyReflectionConsolidator(key_router=None, central_nerve=None)
    finally:
        WeeklyReflectionConsolidator.PERSIST_PATH = saved
    c.PERSIST_PATH = tmp_jsonl  # instance-level 持续 override
    return c


# ==========================================================================
# L1: 模块 + schema
# ==========================================================================
class TestL1Schema(unittest.TestCase):
    def test_module_imports(self):
        from jarvis_weekly_reflection_consolidator import (
            WeeklyReflectionConsolidator, WeeklyInsight,
            get_default_consolidator, set_default_consolidator,
        )
        self.assertTrue(hasattr(WeeklyReflectionConsolidator, '_maybe_fire'))
        self.assertTrue(hasattr(WeeklyReflectionConsolidator,
                                  '_llm_extract_pattern'))
        self.assertTrue(hasattr(WeeklyReflectionConsolidator, 'sir_accept'))
        self.assertTrue(hasattr(WeeklyReflectionConsolidator, 'sir_reject'))

    def test_insight_schema_fields(self):
        from jarvis_weekly_reflection_consolidator import WeeklyInsight
        ins = WeeklyInsight(
            id='wi_test', ts=time.time(), ts_iso='2026-05-25T00:00:00',
            week_range_iso='2026-05-19 → 2026-05-25',
            pattern_summary='pat', suggested_action='act',
            evidence_count=5, evidence_excerpts=['a', 'b', 'c'],
            confidence=0.8,
        )
        self.assertEqual(ins.state, 'review',
            '默认 state 必须是 review (准则 7 Sir 元否决)')
        self.assertEqual(ins.sir_decision_at, 0.0)

    def test_fire_only_sunday_03(self):
        """_maybe_fire 仅 Sunday 03 点 fire."""
        from jarvis_weekly_reflection_consolidator import WeeklyReflectionConsolidator
        self.assertEqual(WeeklyReflectionConsolidator.FIRE_WEEKDAY, 6)
        self.assertEqual(WeeklyReflectionConsolidator.FIRE_HOUR, 3)

    def test_thresholds_sane(self):
        from jarvis_weekly_reflection_consolidator import WeeklyReflectionConsolidator
        # 不要太频繁
        self.assertGreaterEqual(
            WeeklyReflectionConsolidator.CHECK_INTERVAL_S, 300)
        # evidence min 不能 0 (准则 6 evidence-driven)
        self.assertGreaterEqual(
            WeeklyReflectionConsolidator.MIN_EVIDENCE_COUNT, 2)
        # 7d 时间窗
        self.assertEqual(
            WeeklyReflectionConsolidator.SEARCH_TIME_LIMIT_DAYS, 7)


# ==========================================================================
# L2: evidence 收集
# ==========================================================================
class TestL2EvidenceCollection(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join(tempfile.gettempdir(),
                                  f'wrc_l2_{time.time()}.jsonl')
        self.c = _empty_consolidator(self.tmp)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_no_nerve_returns_empty(self):
        """nerve=None → silent skip."""
        self.assertEqual(self.c._collect_reflection_evidence(), [])

    def test_no_hippo_returns_empty(self):
        """nerve 无 hippocampus → silent skip."""
        self.c.nerve = MagicMock(spec=[])
        self.assertEqual(self.c._collect_reflection_evidence(), [])

    def test_hippo_search_called_with_time_limit(self):
        """search_memory 调用时 query='self_reflection' + time_limit 7d."""
        mock_hippo = MagicMock()
        mock_hippo.search_memory.return_value = [
            {'summary': 'reflection 1'}, {'summary': 'reflection 2'},
        ]
        self.c.nerve = MagicMock()
        self.c.nerve.hippocampus = mock_hippo
        res = self.c._collect_reflection_evidence()
        self.assertEqual(len(res), 2)
        kw = mock_hippo.search_memory.call_args.kwargs
        self.assertEqual(kw['query'], 'self_reflection')
        self.assertEqual(kw['top_k'], 10)
        # time_limit 应该是 now - 7d, 容忍 1min 误差
        expected = time.time() - 7 * 86400
        self.assertAlmostEqual(kw['time_limit'], expected, delta=60)

    def test_skip_below_min_evidence(self):
        """evidence < MIN_EVIDENCE_COUNT → 不 LLM call + 不 publish."""
        mock_hippo = MagicMock()
        mock_hippo.search_memory.return_value = [
            {'summary': 'only one reflection'}
        ]
        self.c.nerve = MagicMock()
        self.c.nerve.hippocampus = mock_hippo
        with patch.object(self.c, '_llm_extract_pattern') as mock_llm:
            with patch.object(self.c, '_publish_swm') as mock_pub:
                self.c._do_weekly_consolidation('2026-W21')
        mock_llm.assert_not_called()
        mock_pub.assert_not_called()


# ==========================================================================
# L3: LLM extract pattern (tag 解析 + filter)
# ==========================================================================
class TestL3LlmExtractPattern(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join(tempfile.gettempdir(),
                                  f'wrc_l3_{time.time()}.jsonl')
        self.c = _empty_consolidator(self.tmp)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_empty_evidence_returns_zero(self):
        pat, act, conf = self.c._llm_extract_pattern([])
        self.assertEqual(pat, '')
        self.assertEqual(conf, 0.0)

    def test_parse_3_tag_success(self):
        """LLM 返回 3 tag → 正确 parse."""
        fake_raw = (
            '<PATTERN>Over-emphasizing interview prep in ambiguous queries</PATTERN>\n'
            '<SUGGESTED_ACTION>Add protocol: short ambiguous queries → minimal reply</SUGGESTED_ACTION>\n'
            '<CONFIDENCE>0.85</CONFIDENCE>'
        )
        mock_reflector = MagicMock()
        mock_reflector.reflect.return_value = {
            'success': True, 'raw_text': fake_raw,
        }
        with patch('jarvis_llm_reflector.LlmReflector',
                     return_value=mock_reflector):
            pat, act, conf = self.c._llm_extract_pattern(
                [{'summary': 'r1'}, {'summary': 'r2'}, {'summary': 'r3'}]
            )
        self.assertIn('Over-emphasizing', pat)
        self.assertIn('Add protocol', act)
        self.assertAlmostEqual(conf, 0.85, places=2)

    def test_no_clear_pattern_filtered(self):
        """LLM 返回 'no clear pattern' → 视同空."""
        fake_raw = (
            '<PATTERN>(no clear pattern)</PATTERN>\n'
            '<SUGGESTED_ACTION>none</SUGGESTED_ACTION>\n'
            '<CONFIDENCE>0.0</CONFIDENCE>'
        )
        mock_reflector = MagicMock()
        mock_reflector.reflect.return_value = {
            'success': True, 'raw_text': fake_raw,
        }
        with patch('jarvis_llm_reflector.LlmReflector',
                     return_value=mock_reflector):
            pat, _, conf = self.c._llm_extract_pattern(
                [{'summary': 'r1'}] * 3
            )
        self.assertEqual(pat, '')
        self.assertEqual(conf, 0.0)

    def test_low_confidence_filtered(self):
        """conf < 0.4 → 视同空 (准则 6 不刷屏)."""
        fake_raw = (
            '<PATTERN>Some weak pattern</PATTERN>\n'
            '<SUGGESTED_ACTION>some action</SUGGESTED_ACTION>\n'
            '<CONFIDENCE>0.3</CONFIDENCE>'
        )
        mock_reflector = MagicMock()
        mock_reflector.reflect.return_value = {
            'success': True, 'raw_text': fake_raw,
        }
        with patch('jarvis_llm_reflector.LlmReflector',
                     return_value=mock_reflector):
            pat, _, conf = self.c._llm_extract_pattern(
                [{'summary': 'r1'}] * 3
            )
        self.assertEqual(pat, '')

    def test_llm_fail_returns_zero(self):
        """LLM success=False → 空."""
        mock_reflector = MagicMock()
        mock_reflector.reflect.return_value = {'success': False}
        with patch('jarvis_llm_reflector.LlmReflector',
                     return_value=mock_reflector):
            pat, _, conf = self.c._llm_extract_pattern(
                [{'summary': 'r1'}] * 3
            )
        self.assertEqual(pat, '')

    def test_prompt_has_grounding_rules(self):
        """system prompt 必须含 "DO NOT invent" + Sir 准则 anchor."""
        # 重读 module source 验证 prompt 已防幻觉
        with open(os.path.join(ROOT, 'jarvis_weekly_reflection_consolidator.py'),
                    'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('DO NOT invent', src,
            'LLM prompt 必须防幻觉 (准则 5 言出必行 evidence)')
        self.assertIn('准则', src,
            'LLM prompt anchor Sir 准则 (持续性追溯)')


# ==========================================================================
# L4: 持久化 + rotate + load
# ==========================================================================
class TestL4Persistence(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join(tempfile.gettempdir(),
                                  f'wrc_l4_{time.time()}.jsonl')
        self.c = _empty_consolidator(self.tmp)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_persist_writes_jsonl_line(self):
        from jarvis_weekly_reflection_consolidator import WeeklyInsight
        ins = WeeklyInsight(
            id='wi_t', ts=time.time(), ts_iso='?',
            week_range_iso='?', pattern_summary='p',
            suggested_action='a', evidence_count=3,
            evidence_excerpts=[], confidence=0.7,
        )
        self.c._persist_insight(ins)
        self.assertTrue(os.path.exists(self.tmp))
        with open(self.tmp, 'r', encoding='utf-8') as f:
            line = f.readline().strip()
        d = json.loads(line)
        self.assertEqual(d['id'], 'wi_t')
        self.assertEqual(d['confidence'], 0.7)
        self.assertEqual(d['state'], 'review')

    def test_persist_calls_maybe_rotate(self):
        """write 时调 maybe_rotate (防爆 list 已加 long_term_insights.jsonl)."""
        from jarvis_weekly_reflection_consolidator import WeeklyInsight
        ins = WeeklyInsight(
            id='wi_r', ts=time.time(), ts_iso='?',
            week_range_iso='?', pattern_summary='p',
            suggested_action='a', evidence_count=3,
            evidence_excerpts=[], confidence=0.7,
        )
        with patch('jarvis_jsonl_rotator.maybe_rotate') as mock_rot:
            self.c._persist_insight(ins)
        mock_rot.assert_called_once()
        args, kwargs = mock_rot.call_args
        self.assertEqual(args[0], self.tmp,
            'rotate 必须对 PERSIST_PATH 操作')
        self.assertEqual(kwargs.get('check_every_n_writes'), 10)

    def test_load_persist_cutoff_90d(self):
        """超过 90 天的 insight 不 load 进 memory (cutoff)."""
        old = json.dumps({
            'id': 'wi_old', 'ts': time.time() - 100 * 86400,
            'ts_iso': '?', 'week_range_iso': '?',
            'pattern_summary': 'old', 'suggested_action': 'old',
            'evidence_count': 3, 'evidence_excerpts': [],
            'confidence': 0.7, 'state': 'review',
            'sir_decision_at': 0.0, 'sir_decision_reason': '',
        })
        recent = json.dumps({
            'id': 'wi_new', 'ts': time.time() - 1 * 86400,
            'ts_iso': '?', 'week_range_iso': '?',
            'pattern_summary': 'recent', 'suggested_action': 'recent',
            'evidence_count': 4, 'evidence_excerpts': [],
            'confidence': 0.8, 'state': 'review',
            'sir_decision_at': 0.0, 'sir_decision_reason': '',
        })
        with open(self.tmp, 'w', encoding='utf-8') as f:
            f.write(old + '\n' + recent + '\n')
        # 重建 consolidator → 重 load
        from jarvis_weekly_reflection_consolidator import WeeklyReflectionConsolidator
        with patch.object(WeeklyReflectionConsolidator, 'PERSIST_PATH', self.tmp):
            c2 = WeeklyReflectionConsolidator(key_router=None,
                                                central_nerve=None)
        ids = [i.id for i in c2._insights]
        self.assertIn('wi_new', ids)
        self.assertNotIn('wi_old', ids,
            '超 90 天 cutoff → 不 load (准则 8 sustainability)')

    def test_load_persist_dedup_by_id(self):
        """同 id 多次 append (e.g. Sir accept 后再 persist) → load 取 latest."""
        from jarvis_weekly_reflection_consolidator import WeeklyReflectionConsolidator
        d1 = {
            'id': 'wi_dup', 'ts': time.time() - 1000,
            'ts_iso': '?', 'week_range_iso': '?',
            'pattern_summary': 'v1', 'suggested_action': 'a',
            'evidence_count': 3, 'evidence_excerpts': [],
            'confidence': 0.7, 'state': 'review',
            'sir_decision_at': 0.0, 'sir_decision_reason': '',
        }
        d2 = dict(d1)
        d2['state'] = 'accepted'  # 同 id, 后版
        d2['sir_decision_at'] = time.time()
        with open(self.tmp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(d1) + '\n' + json.dumps(d2) + '\n')
        with patch.object(WeeklyReflectionConsolidator, 'PERSIST_PATH', self.tmp):
            c2 = WeeklyReflectionConsolidator(key_router=None,
                                                central_nerve=None)
        self.assertEqual(len(c2._insights), 1)
        self.assertEqual(c2._insights[0].state, 'accepted',
            '同 id 多 append → 取 latest (last-write-wins)')


# ==========================================================================
# L5: SWM publish
# ==========================================================================
class TestL5SwmPublish(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join(tempfile.gettempdir(),
                                  f'wrc_l5_{time.time()}.jsonl')
        self.c = _empty_consolidator(self.tmp)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_publish_swm_etype_and_salience(self):
        from jarvis_weekly_reflection_consolidator import WeeklyInsight
        ins = WeeklyInsight(
            id='wi_pub', ts=time.time(), ts_iso='?',
            week_range_iso='2026-05-19 → 2026-05-25',
            pattern_summary='Sir prefers short ambiguous replies',
            suggested_action='Add protocol XYZ',
            evidence_count=5, evidence_excerpts=['e1', 'e2'],
            confidence=0.88,
        )
        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            self.c._publish_swm(ins)
        self.assertTrue(mock_bus.publish.called)
        kw = mock_bus.publish.call_args.kwargs
        self.assertEqual(kw['etype'], 'weekly_insight_proposed')
        self.assertGreaterEqual(kw['salience'], 0.85,
            'salience >= 0.85 让 SOUL inject 主脑下次 turn')
        self.assertEqual(kw['source'], 'weekly_reflection_consolidator')
        # TTL 14 天 让 Sir 跨周看
        self.assertGreaterEqual(kw['ttl'], 7 * 86400)
        # metadata 含可点击 insight_id 让 dashboard 关联
        self.assertEqual(kw['metadata']['insight_id'], 'wi_pub')
        self.assertIn('pattern', kw['metadata'])
        self.assertIn('suggested_action', kw['metadata'])


# ==========================================================================
# L6: Sir decide API (accept / reject)
# ==========================================================================
class TestL6SirDecide(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join(tempfile.gettempdir(),
                                  f'wrc_l6_{time.time()}.jsonl')
        self.c = _empty_consolidator(self.tmp)
        from jarvis_weekly_reflection_consolidator import WeeklyInsight
        self.ins = WeeklyInsight(
            id='wi_decide', ts=time.time(), ts_iso='?',
            week_range_iso='?', pattern_summary='p',
            suggested_action='a', evidence_count=3,
            evidence_excerpts=[], confidence=0.8,
        )
        self.c._insights.append(self.ins)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_sir_accept_changes_state(self):
        ok = self.c.sir_accept('wi_decide', 'Sir 真喜欢这个 insight')
        self.assertTrue(ok)
        self.assertEqual(self.ins.state, 'accepted')
        self.assertGreater(self.ins.sir_decision_at, 0)
        self.assertIn('喜欢', self.ins.sir_decision_reason)

    def test_sir_reject_changes_state(self):
        ok = self.c.sir_reject('wi_decide', 'Sir 拒')
        self.assertTrue(ok)
        self.assertEqual(self.ins.state, 'rejected')

    def test_sir_decide_unknown_id_returns_false(self):
        ok = self.c.sir_accept('wi_not_exist', '')
        self.assertFalse(ok)

    def test_sir_decide_persists(self):
        """Sir decide → 触发 persist append (load 时取 latest state)."""
        # baseline jsonl 没有
        if os.path.exists(self.tmp):
            os.remove(self.tmp)
        self.c.sir_accept('wi_decide', 'ok')
        # 应该至少 1 行 append
        self.assertTrue(os.path.exists(self.tmp))
        with open(self.tmp, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('wi_decide', content)
        self.assertIn('accepted', content)


# ==========================================================================
# L7: central_nerve 集成 anchor (Sir 真意: hotfix 不要再漏)
# ==========================================================================
class TestL7CentralNerveIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'),
                    'r', encoding='utf-8') as f:
            cls.nerve_src = f.read()

    def test_init_calls_method(self):
        self.assertIn('self._init_weekly_reflection_consolidator()',
                       self.nerve_src,
            'CentralNerve.__init__ 必须调 _init_weekly_reflection_consolidator')

    def test_method_defined(self):
        self.assertIn('def _init_weekly_reflection_consolidator',
                       self.nerve_src,
            '方法定义必须存在 (HOTFIX anchor — 防 AttributeError)')

    def test_method_imports_module(self):
        self.assertIn('jarvis_weekly_reflection_consolidator', self.nerve_src)
        self.assertIn('WeeklyReflectionConsolidator', self.nerve_src)
        self.assertIn('set_default_consolidator', self.nerve_src)

    def test_method_safe_init_pattern(self):
        """init 必须用 try/except 包 (非致命, 不能炸主线程)."""
        # 取方法 body
        idx = self.nerve_src.find('def _init_weekly_reflection_consolidator')
        end = self.nerve_src.find('\n    def ', idx + 10)
        body = self.nerve_src[idx:end]
        self.assertIn('try:', body)
        self.assertIn('except', body)
        self.assertIn('非致命', body,
            '错误日志必须明示 非致命 (Sir 不慌)')


# ==========================================================================
# L8: dashboard 集成 anchor (Sir 真看到 + 一键 decide)
# ==========================================================================
class TestL8DashboardIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'scripts', 'jarvis_dashboard_web.py'),
                    'r', encoding='utf-8') as f:
            cls.dash_src = f.read()

    def test_api_route_exists(self):
        """GET /api/weekly_insights — Sir 看 insight queue."""
        self.assertIn('/api/weekly_insights', self.dash_src,
            'dashboard 必须有 /api/weekly_insights 让 Sir 看 queue')

    def test_decide_route_exists(self):
        """POST /api/weekly_insights/decide — Sir 一键 accept/reject."""
        self.assertIn('/api/weekly_insights/decide', self.dash_src,
            'dashboard 必须有 decide 路由让 Sir 一键决策')

    def test_page_route_exists(self):
        """GET /weekly_insights — Sir 看 UI."""
        self.assertIn('/weekly_insights', self.dash_src,
            'dashboard 必须有 /weekly_insights page (Sir 真看到)')

    def test_nav_entry_exists(self):
        """nav 必须有入口 (Sir 不要 url 手输)."""
        self.assertIn('weekly_insights', self.dash_src.lower())


if __name__ == '__main__':
    unittest.main()
