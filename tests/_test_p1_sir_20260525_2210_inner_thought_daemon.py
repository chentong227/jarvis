# -*- coding: utf-8 -*-
"""[P1 / Sir 2026-05-25 22:10 数字生命基础] Inner Thought Daemon 测试.

测试覆盖:
  L0: 模块导入 + 数据结构 (InnerThought dataclass)
  L1: Adaptive frequency (sir state classification + interval)
  L2: 5 类思考 prompt build (含 evidence 注入)
  L3: parse LLM output (4 tag strict + edge cases)
  L4: Actionable executor (4 档全可逆)
  L5: SOUL inject build_soul_block (top 3 by salience + 时间排序)
  L6: Cooldown + persist roundtrip
  L7: central_nerve integration (源码 anchor)
  L8: KeyRouter CALLER_INNER_THOUGHT + P2 LOW routing
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
# L0: 模块导入 + 数据结构
# ==========================================================================
class TestL0ModuleAndDataclass(unittest.TestCase):

    def test_module_imports(self):
        import jarvis_inner_thought_daemon as m
        self.assertTrue(hasattr(m, 'InnerThought'))
        self.assertTrue(hasattr(m, 'InnerThoughtDaemon'))
        self.assertTrue(hasattr(m, 'get_default_daemon'))
        self.assertTrue(hasattr(m, 'set_default_daemon'))

    def test_dataclass_fields(self):
        from jarvis_inner_thought_daemon import InnerThought
        t = InnerThought(
            id='thought_001', ts=1000.0, ts_iso='2026-05-25T22:00:00',
            category='A', thought='test', salience=0.5,
            actionable='none',
        )
        self.assertEqual(t.id, 'thought_001')
        self.assertEqual(t.actionable_done, False)
        self.assertEqual(t.actionable_result, 'pending')
        self.assertEqual(t.sir_state, 'unknown')


# ==========================================================================
# L1: Adaptive frequency + Sir state
# ==========================================================================
class TestL1AdaptiveFrequency(unittest.TestCase):

    def setUp(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        self.daemon = InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=None,
            relational_state=None,
        )

    def test_state_active_when_idle_low(self):
        with patch.object(self.daemon, '_get_idle_seconds', return_value=10.0):
            with patch('time.localtime') as mt:
                mt.return_value = time.struct_time(
                    (2026, 5, 25, 14, 0, 0, 0, 0, 0)  # 14:00
                )
                self.assertEqual(self.daemon._classify_sir_state(), 'active')

    def test_state_afk_short_when_idle_5min(self):
        with patch.object(self.daemon, '_get_idle_seconds', return_value=400.0):
            with patch('time.localtime') as mt:
                mt.return_value = time.struct_time(
                    (2026, 5, 25, 14, 0, 0, 0, 0, 0)
                )
                self.assertEqual(self.daemon._classify_sir_state(), 'afk_short')

    def test_state_afk_deep_when_idle_30min_plus(self):
        with patch.object(self.daemon, '_get_idle_seconds', return_value=2000.0):
            with patch('time.localtime') as mt:
                mt.return_value = time.struct_time(
                    (2026, 5, 25, 14, 0, 0, 0, 0, 0)
                )
                self.assertEqual(self.daemon._classify_sir_state(), 'afk_deep')

    def test_state_sleep_at_night_when_idle(self):
        with patch.object(self.daemon, '_get_idle_seconds', return_value=700.0):
            with patch('time.localtime') as mt:
                mt.return_value = time.struct_time(
                    (2026, 5, 25, 3, 0, 0, 0, 0, 0)  # 03:00
                )
                self.assertEqual(self.daemon._classify_sir_state(), 'sleep')

    def test_interval_matches_state(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        with patch.object(self.daemon, '_classify_sir_state',
                            return_value='active'):
            self.assertEqual(self.daemon._compute_adaptive_interval(),
                              InnerThoughtDaemon.INTERVAL_ACTIVE_S)
        with patch.object(self.daemon, '_classify_sir_state',
                            return_value='afk_short'):
            self.assertEqual(self.daemon._compute_adaptive_interval(),
                              InnerThoughtDaemon.INTERVAL_AFK_SHORT_S)
        with patch.object(self.daemon, '_classify_sir_state',
                            return_value='afk_deep'):
            self.assertEqual(self.daemon._compute_adaptive_interval(),
                              InnerThoughtDaemon.INTERVAL_AFK_DEEP_S)
        with patch.object(self.daemon, '_classify_sir_state',
                            return_value='sleep'):
            self.assertEqual(self.daemon._compute_adaptive_interval(),
                              InnerThoughtDaemon.INTERVAL_SLEEP_S)


# ==========================================================================
# L2: 5 类思考 prompt build
# ==========================================================================
class TestL2PromptBuild(unittest.TestCase):

    def setUp(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        self.daemon = InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=None,
            relational_state=None,
        )

    def test_prompt_contains_all_5_categories(self):
        sys_p, user_p = self.daemon._build_prompt(
            'active',
            {'sir_state': 'active', 'idle_seconds': 10, 'hour': 22},
        )
        for tag in ('OBSERVATION', 'SELF-REFLECT', 'CONCERN-EVOLUTION',
                     'PROACTIVE-SEED', 'RELATIONSHIP'):
            self.assertIn(tag, sys_p,
                f'system prompt 必须含 5 类标签 {tag}')

    def test_prompt_contains_4_output_tags(self):
        sys_p, _ = self.daemon._build_prompt('active', {})
        for tag in ('<CATEGORY>', '<THOUGHT>', '<SALIENCE>', '<ACTIONABLE>'):
            self.assertIn(tag, sys_p, f'system prompt 必须含 output tag {tag}')

    def test_prompt_contains_evidence_blocks(self):
        evidence = {
            'sir_state': 'active', 'idle_seconds': 30, 'hour': 22,
            'swm_events': [{'type': 'wake', 'desc': 'Sir 说 你好', 'age_s': 20}],
            'stm': [{'user': '你好', 'jarvis': 'Sir.', 'when': '22:00'}],
            'concerns': [{'id': 'sir_sleep', 'what': '熬夜', 'severity': 0.6}],
        }
        _, user_p = self.daemon._build_prompt('active', evidence)
        self.assertIn('CURRENT MOMENT', user_p)
        self.assertIn('RECENT SWM EVENTS', user_p)
        self.assertIn('STM LAST 2 TURNS', user_p)
        self.assertIn('YOUR ACTIVE CONCERNS', user_p)
        self.assertIn('Sir 说 你好', user_p)
        self.assertIn('sir_sleep', user_p)


# ==========================================================================
# L3: Parse LLM output (4 tag strict)
# ==========================================================================
class TestL3ParseLLMOutput(unittest.TestCase):

    def setUp(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        self.daemon = InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=None,
            relational_state=None,
        )

    def test_parse_valid_output(self):
        raw = """<CATEGORY>C</CATEGORY>
<THOUGHT>I noticed my keyrouter health improved tonight.</THOUGHT>
<SALIENCE>0.65</SALIENCE>
<ACTIONABLE>update_concern_severity:jarvis_keyrouter:-0.2</ACTIONABLE>"""
        t = self.daemon._parse_thought(raw, 'active', 60)
        self.assertIsNotNone(t)
        self.assertEqual(t.category, 'C')
        self.assertEqual(t.salience, 0.65)
        self.assertIn('keyrouter', t.thought)
        self.assertEqual(t.actionable, 'update_concern_severity:jarvis_keyrouter:-0.2')
        self.assertEqual(t.sir_state, 'active')
        self.assertEqual(t.tick_interval_s, 60)

    def test_parse_quiet_skip(self):
        raw = """<CATEGORY>A</CATEGORY>
<THOUGHT>(quiet)</THOUGHT>
<SALIENCE>0.0</SALIENCE>
<ACTIONABLE>none</ACTIONABLE>"""
        t = self.daemon._parse_thought(raw, 'sleep', 1800)
        self.assertIsNone(t, '(quiet) thought 应跳过')

    def test_parse_missing_tags_returns_none(self):
        raw = "no tags at all just garbage"
        self.assertIsNone(self.daemon._parse_thought(raw, 'active', 60))

    def test_parse_clamps_salience(self):
        raw = """<CATEGORY>B</CATEGORY>
<THOUGHT>too high</THOUGHT>
<SALIENCE>2.5</SALIENCE>
<ACTIONABLE>none</ACTIONABLE>"""
        t = self.daemon._parse_thought(raw, 'active', 60)
        self.assertEqual(t.salience, 1.0, 'salience 必须 clamp 到 [0,1]')

    def test_parse_actionable_defaults_to_none(self):
        raw = """<CATEGORY>A</CATEGORY>
<THOUGHT>test</THOUGHT>
<SALIENCE>0.3</SALIENCE>
<ACTIONABLE></ACTIONABLE>"""
        t = self.daemon._parse_thought(raw, 'active', 60)
        self.assertEqual(t.actionable, 'none')


# ==========================================================================
# L4: Actionable executor
# ==========================================================================
class TestL4ActionableExecutor(unittest.TestCase):

    def _make_thought(self, actionable: str):
        from jarvis_inner_thought_daemon import InnerThought
        return InnerThought(
            id='thought_test',
            ts=time.time(),
            ts_iso='2026-05-25T22:00:00',
            category='C',
            thought='test thought',
            salience=0.5,
            actionable=actionable,
        )

    def test_actionable_none_returns_ok(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        d = InnerThoughtDaemon(key_router=MagicMock())
        t = self._make_thought('none')
        ok, result = d._execute_actionable(t)
        self.assertTrue(ok)
        self.assertEqual(result, 'none')

    def test_actionable_update_concern_severity_caps_delta(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        # mock concern
        mock_concern = MagicMock(severity=0.5)
        mock_ledger = MagicMock()
        mock_ledger.get = MagicMock(return_value=mock_concern)
        mock_ledger.update_concern_field = MagicMock(
            return_value=(True, 'ok', 0.5)
        )
        d = InnerThoughtDaemon(key_router=MagicMock(),
                                  concerns_ledger=mock_ledger)
        # 试 +0.5 (超 cap 0.2 → 应被 cap 到 +0.2)
        t = self._make_thought('update_concern_severity:sir_sleep:0.5')
        ok, result = d._execute_actionable(t)
        self.assertTrue(ok)
        # 验证 update 用的 new_sev <= 0.7 (0.5 + 0.2)
        call_args = mock_ledger.update_concern_field.call_args
        self.assertAlmostEqual(call_args.args[2], 0.7, places=2,
            msg='delta 应被 cap 到 +0.2, new_sev=0.7')

    def test_actionable_update_concern_not_found(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        mock_ledger = MagicMock()
        mock_ledger.get = MagicMock(return_value=None)
        d = InnerThoughtDaemon(key_router=MagicMock(),
                                  concerns_ledger=mock_ledger)
        t = self._make_thought('update_concern_severity:nonexistent:0.1')
        ok, result = d._execute_actionable(t)
        self.assertFalse(ok)
        self.assertIn('not_found', result)

    def test_actionable_publish_swm(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        d = InnerThoughtDaemon(key_router=MagicMock())
        # mock event bus
        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            t = self._make_thought('publish_swm:sir_seems_tired:Sir 22:30 still up')
            ok, result = d._execute_actionable(t)
            self.assertTrue(ok)
            self.assertIn('published', result)
            mock_bus.publish.assert_called_once()
            kwargs = mock_bus.publish.call_args.kwargs
            self.assertEqual(kwargs['etype'], 'sir_seems_tired')

    def test_actionable_unknown_returns_fail(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        d = InnerThoughtDaemon(key_router=MagicMock())
        t = self._make_thought('delete_everything:lol')
        ok, result = d._execute_actionable(t)
        self.assertFalse(ok)
        self.assertIn('unknown_actionable', result)


# ==========================================================================
# L5: SOUL inject (build_soul_block)
# ==========================================================================
class TestL5SoulInjectBlock(unittest.TestCase):

    def _daemon_with_thoughts(self, thoughts_data):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon, InnerThought
        d = InnerThoughtDaemon(key_router=MagicMock())
        # __init__ 已 _load_persist 真 default jsonl, test 必须清
        d._thoughts = [InnerThought(**td) for td in thoughts_data]
        return d

    def test_empty_returns_empty_string(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        d = InnerThoughtDaemon(key_router=MagicMock())
        d._thoughts = []  # 清掉 default jsonl 真 thoughts (Sir 重启后有)
        self.assertEqual(d.build_soul_block(), '')

    def test_top_3_by_salience(self):
        now = time.time()
        thoughts = [
            {'id': f't{i}', 'ts': now - i * 60, 'ts_iso': '?',
             'category': 'A', 'thought': f'thought {i}',
             'salience': 0.1 * i, 'actionable': 'none'}
            for i in range(1, 8)  # sal 0.1, 0.2, ..., 0.7
        ]
        d = self._daemon_with_thoughts(thoughts)
        block = d.build_soul_block()
        # 应含 top 3 (sal 0.7 0.6 0.5)
        self.assertIn('sal 0.70', block)
        self.assertIn('sal 0.60', block)
        self.assertIn('sal 0.50', block)
        # 不应含低 salience
        self.assertNotIn('sal 0.10', block)
        self.assertNotIn('sal 0.20', block)

    def test_block_respects_max_chars(self):
        now = time.time()
        long_thought = 'A' * 300
        thoughts = [
            {'id': f't{i}', 'ts': now - i, 'ts_iso': '?',
             'category': 'A', 'thought': long_thought,
             'salience': 0.5, 'actionable': 'none'}
            for i in range(3)
        ]
        d = self._daemon_with_thoughts(thoughts)
        block = d.build_soul_block(max_chars=200)
        self.assertLessEqual(len(block), 220)  # 200 + truncate suffix margin

    def test_excludes_old_thoughts(self):
        now = time.time()
        # 老 thought (25h ago) 应被排除
        thoughts = [
            {'id': 'old', 'ts': now - 25 * 3600, 'ts_iso': '?',
             'category': 'A', 'thought': 'too old',
             'salience': 0.9, 'actionable': 'none'},
            {'id': 'new', 'ts': now - 60, 'ts_iso': '?',
             'category': 'A', 'thought': 'fresh',
             'salience': 0.3, 'actionable': 'none'},
        ]
        d = self._daemon_with_thoughts(thoughts)
        block = d.build_soul_block()
        self.assertIn('fresh', block)
        self.assertNotIn('too old', block)


# ==========================================================================
# L6: Cooldown + persist roundtrip
# ==========================================================================
class TestL6CooldownAndPersist(unittest.TestCase):

    def test_persist_then_load_roundtrip(self):
        from jarvis_inner_thought_daemon import (
            InnerThoughtDaemon, InnerThought
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, 'thoughts.jsonl')
            # patch class attr 在 __init__ 前 → _load_persist 读 empty path
            with patch.object(InnerThoughtDaemon, 'PERSIST_PATH', persist_path):
                d = InnerThoughtDaemon(key_router=MagicMock())
                # persist 3 thoughts
                for i in range(3):
                    t = InnerThought(
                        id=f't{i}', ts=time.time(), ts_iso='?',
                        category='A', thought=f'th{i}',
                        salience=0.5, actionable='none',
                    )
                    d._persist_thought(t)
                # load
                d2 = InnerThoughtDaemon(key_router=MagicMock())
                self.assertEqual(len(d2._thoughts), 3)
                self.assertEqual(d2._thoughts[0].id, 't0')

    def test_load_skips_old_thoughts(self):
        from jarvis_inner_thought_daemon import (
            InnerThoughtDaemon, InnerThought
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, 'thoughts.jsonl')
            with patch.object(InnerThoughtDaemon, 'PERSIST_PATH', persist_path):
                d = InnerThoughtDaemon(key_router=MagicMock())
                now = time.time()
                t_old = InnerThought(
                    id='old', ts=now - 86400 * 2, ts_iso='?',
                    category='A', thought='old', salience=0.5, actionable='none',
                )
                t_new = InnerThought(
                    id='new', ts=now - 60, ts_iso='?',
                    category='B', thought='new', salience=0.5, actionable='none',
                )
                d._persist_thought(t_old)
                d._persist_thought(t_new)
                d2 = InnerThoughtDaemon(key_router=MagicMock())
                self.assertEqual(len(d2._thoughts), 1)
                self.assertEqual(d2._thoughts[0].id, 'new')


# ==========================================================================
# L7: central_nerve integration anchor (源码 anchor 防回归)
# ==========================================================================
class TestL7CentralNerveIntegration(unittest.TestCase):

    def _read(self, fname):
        with open(os.path.join(ROOT, fname), 'r', encoding='utf-8') as f:
            return f.read()

    def test_central_nerve_calls_init_daemon(self):
        src = self._read('jarvis_central_nerve.py')
        self.assertIn('self._init_inner_thought_daemon()', src,
            'CentralNerve.__init__ 必须调 _init_inner_thought_daemon')

    def test_central_nerve_has_init_method(self):
        src = self._read('jarvis_central_nerve.py')
        self.assertIn('def _init_inner_thought_daemon(self)', src)
        self.assertIn('InnerThoughtDaemon', src)

    def test_central_nerve_has_layer_1b_method(self):
        src = self._read('jarvis_central_nerve.py')
        self.assertIn('_build_layer_1b_inner_thoughts_block', src)

    def test_assemble_prompt_uses_layer_1b(self):
        src = self._read('jarvis_central_nerve.py')
        # _assemble_prompt 必须调 _build_layer_1b_inner_thoughts_block
        self.assertIn('inner_thoughts_block = self._build_layer_1b_inner_thoughts_block()',
            src,
            '_assemble_prompt 必须用 Layer 1.5 inner_thoughts')

    def test_soul_inject_log_has_l1_5(self):
        src = self._read('jarvis_central_nerve.py')
        self.assertIn('L1.5', src,
            'SOUL inject diag log 必须含 L1.5 (Sir grep 真看到)')


# ==========================================================================
# L8: KeyRouter CALLER_INNER_THOUGHT + LLM caller routing
# ==========================================================================
class TestL8KeyRouterCaller(unittest.TestCase):

    def test_key_router_has_inner_thought_caller(self):
        from jarvis_key_router import KeyRouter
        self.assertTrue(hasattr(KeyRouter, 'CALLER_INNER_THOUGHT'))
        self.assertEqual(KeyRouter.CALLER_INNER_THOUGHT, 'inner_thought')

    def test_inner_thought_is_low_priority_by_default(self):
        from jarvis_key_router import KeyRouter
        # 不在 HIGH/MEDIUM 列表 → 默认 LOW
        kr = KeyRouter(
            main_brain_key='test_main',
            google_keys=['g1', 'g2'],
            openrouter_keys=['or1', 'or2'],
        )
        priority = kr._default_priority('inner_thought')
        self.assertEqual(priority, KeyRouter.PRIORITY_LOW,
            'inner_thought 必须默认 LOW priority (P2 30/min 限速保护)')

    def test_llm_reflector_accepts_caller_param(self):
        import jarvis_llm_reflector as m
        import inspect
        sig = inspect.signature(m.LlmReflector.reflect)
        self.assertIn('caller', sig.parameters,
            'LlmReflector.reflect 必须接 caller 参数 (P1 inner_thought 路由)')

    def test_daemon_passes_inner_thought_caller(self):
        src_path = os.path.join(ROOT, 'jarvis_inner_thought_daemon.py')
        with open(src_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('CALLER_INNER_THOUGHT', src,
            'daemon 必须传 CALLER_INNER_THOUGHT 给 LlmReflector')

    def test_daemon_uses_correct_llm_reflector_singleton_api(self):
        """🩹 [P1-fix1 / Sir 22:48 真测 BUG] daemon 必须用 LlmReflector(key_router=...)
        构造单例 (它 __new__ 单例), 不能用 .get_instance() (不存在的 API).

        Sir 22:48 真测 log: '⚠️ [InnerThought] LLM call exception:
        type object LlmReflector has no attribute get_instance' — 首波 thought 即 fail.
        """
        src_path = os.path.join(ROOT, 'jarvis_inner_thought_daemon.py')
        with open(src_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('LlmReflector(key_router=', src,
            'daemon 必须用 LlmReflector(key_router=...) 单例构造')
        self.assertNotIn('LlmReflector.get_instance', src,
            'daemon 不应用错误的 .get_instance() (Sir 22:48 真测 BUG)')

    def test_llm_reflector_is_actual_singleton(self):
        """anti-regression: LlmReflector 必须保持单例 (__new__ pattern)."""
        from jarvis_llm_reflector import LlmReflector
        r1 = LlmReflector(key_router=None)
        r2 = LlmReflector(key_router=None)
        self.assertIs(r1, r2,
            'LlmReflector 必须单例 (__new__ pattern)')


# ==========================================================================
# L9: Dashboard 集成 (Sir 22:52 真意: 都集成到 dashboard 直观)
# ==========================================================================
class TestL9DashboardIntegration(unittest.TestCase):
    """Sir 22:52 真意 — '都集成到 dashboard 直观一点, 英文翻译成中文, 带图文'.

    纯源码 anchor 测试 (不 import dashboard_web 避免 sys.stdout reassign 跟 pytest
    capture 冲突, 这是老 jarvis_dashboard 的 pre-existing pattern, β.5.41 之前 test
    都中过这个雷). 真功能验证靠运行时跑 'python scripts/jarvis_dashboard_web.py'.
    """

    @classmethod
    def setUpClass(cls):
        scripts_path = os.path.join(ROOT, 'scripts', 'jarvis_dashboard_web.py')
        with open(scripts_path, 'r', encoding='utf-8') as f:
            cls.dashboard_src = f.read()

    def test_dashboard_has_inner_thoughts_page_route(self):
        self.assertIn("@app.route('/inner_thoughts')", self.dashboard_src,
            "dashboard 必须有 @app.route('/inner_thoughts') (Sir 22:52)")
        self.assertIn('def page_inner_thoughts', self.dashboard_src)

    def test_dashboard_has_api_inner_thoughts_route(self):
        self.assertIn("@app.route('/api/inner_thoughts')", self.dashboard_src,
            "dashboard 必须有 /api/inner_thoughts API (Sir 22:52)")
        self.assertIn('def api_inner_thoughts', self.dashboard_src)

    def test_dashboard_translates_5_categories_to_chinese(self):
        """5 类必须翻译成中文 + 含 icon (Sir 22:52 真要求)."""
        for cat_zh in ('观察', '自我反思', '关怀演化', '主动想法', '关系维系'):
            self.assertIn(cat_zh, self.dashboard_src,
                f'5 类必须翻译: 缺 "{cat_zh}"')
        for icon in ('👁️', '🪞', '🎯', '🌱', '💝'):
            self.assertIn(icon, self.dashboard_src,
                f'5 类 icon 必须含 {icon}')

    def test_dashboard_translates_actionable_to_chinese(self):
        """actionable 4 档英文 → 中文人话 (translate function 含 4 个分支)."""
        self.assertIn('def _translate_inner_actionable', self.dashboard_src)
        for phrase in ('无后续操作', '调整关怀', '通知主脑事件', '提议 inside joke'):
            self.assertIn(phrase, self.dashboard_src,
                f'actionable 翻译必须含 "{phrase}"')

    def test_dashboard_header_has_inner_thoughts_button(self):
        """dashboard header 必须有 💭 思考层 入口按钮."""
        self.assertIn('💭 思考层', self.dashboard_src,
            "header 必须有 '💭 思考层' 按钮 (Sir 22:52)")
        self.assertIn('href="/inner_thoughts"', self.dashboard_src,
            'header 按钮必须链到 /inner_thoughts')

    def test_dashboard_page_has_chinese_ui_labels(self):
        """page HTML 模板必须含中文 UI 标签 (Sir 22:52 真意)."""
        for needle in ('思考层', '关注度', '当前思考间隔',
                        '观察', '自我反思', '关怀演化',
                        '真做了', '主脑会看到'):
            self.assertIn(needle, self.dashboard_src,
                f'page UI 必须含中文 "{needle}"')

    def test_dashboard_5_sir_state_translations(self):
        """Sir 4 个 state (active/afk_short/afk_deep/sleep) 必须翻译."""
        for label in ('活跃', '短暂离开', '深度离开', '睡眠'):
            self.assertIn(label, self.dashboard_src,
                f'Sir state 必须翻译: 缺 "{label}"')


if __name__ == '__main__':
    unittest.main()
