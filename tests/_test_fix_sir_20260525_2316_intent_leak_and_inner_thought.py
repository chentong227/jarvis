# -*- coding: utf-8 -*-
"""[Sir 2026-05-25 23:14-23:20 真测] 5 BUG fix 全面回归测试.

1. {intent: dashboard_open} raw JSON 泄 TTS+字幕 (Sir 截图真发生过)
2. InnerThought daemon cooldown skip 浪费 LLM call (4 次 skip log)
3. LLM hallucinate concern_id (jarvis_internal_health 不存在)
4. B 类 self-reflect 没真闭环 (主脑 next turn 还会重复)
5. <TOOL_CALL> tag 漏 _STRUCTURAL_TAGS 不被 TTS path strip

测试覆盖:
  L1: safety/strip — TOOL_CALL + 裸 JSON 真剥 (Sir 截图 BUG #1, #5)
  L2: IntentParser — 裸 JSON 也真路由 (准则 6 容错, Sir 真能开 dashboard)
  L3: InnerThought — cooldown 预选 (Sir 真痛 #2)
  L4: InnerThought — concerns 全 active id (Sir 真痛 #3)
  L5: InnerThought — actionable fail SWM publish (Sir 真痛 #3 闭环)
  L6: InnerThought — B 类 self-correction 闭环 (Sir 真痛 #4)
"""
from __future__ import annotations

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
# L1: safety._strip_structural_tag_blocks 剥 TOOL_CALL + 裸 JSON
# ==========================================================================
class TestL1StripTooLCallAndStrayJSON(unittest.TestCase):
    """Sir 截图 BUG #1: raw {"intent":"dashboard_open"} 泄 TTS+字幕."""

    def test_structural_tags_contains_tool_call(self):
        from jarvis_safety import _STRUCTURAL_TAGS
        self.assertIn('TOOL_CALL', _STRUCTURAL_TAGS,
            'TOOL_CALL 必须在 _STRUCTURAL_TAGS (Sir 截图 BUG)')

    def test_strip_removes_tool_call_block(self):
        from jarvis_safety import _strip_structural_tag_blocks
        text = ('Hello <TOOL_CALL>{"intent":"dashboard_open"}</TOOL_CALL> '
                'world')
        out = _strip_structural_tag_blocks(text)
        self.assertNotIn('"intent"', out)
        self.assertNotIn('dashboard_open', out)
        self.assertIn('Hello', out)
        self.assertIn('world', out)

    def test_strip_removes_stray_intent_json(self):
        """主脑 emit 裸 JSON 不带 tag — 必须剥 (Sir 截图真发生过)."""
        from jarvis_safety import _strip_structural_tag_blocks
        # Sir 截图原文模式
        text = ('{"intent": "dashboard_open"}\n\nOf course, Sir. '
                'Bringing up the dashboard now.')
        out = _strip_structural_tag_blocks(text)
        self.assertNotIn('"intent"', out, f'裸 JSON 没剥: {out}')
        self.assertNotIn('dashboard_open', out)
        self.assertIn('Of course', out)
        self.assertIn('Bringing up', out)

    def test_strip_handles_intent_with_params(self):
        """裸 JSON 带 params 也剥."""
        from jarvis_safety import _strip_structural_tag_blocks
        text = '{"intent":"x","params":{"a":1}} legitimate reply'
        out = _strip_structural_tag_blocks(text)
        self.assertNotIn('"intent"', out)
        self.assertIn('legitimate reply', out)

    def test_strip_preserves_normal_braces(self):
        """合法文本含 { 不被误剥."""
        from jarvis_safety import _strip_structural_tag_blocks
        text = 'I think {math expression} is interesting.'
        out = _strip_structural_tag_blocks(text)
        self.assertIn('math expression', out, '合法 { 不应被剥')


# ==========================================================================
# L2: IntentParser 兼容裸 JSON 真路由
# ==========================================================================
class TestL2IntentParserCompatibility(unittest.TestCase):
    """准则 6 容错: 主脑省 tag 也能真路由 (Sir 真能开 dashboard)."""

    def test_extract_all_handles_tag_wrapped(self):
        from jarvis_intent_router import IntentParser
        calls = IntentParser.extract_all(
            '<TOOL_CALL>{"intent":"dashboard_open"}</TOOL_CALL>'
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].intent_id, 'dashboard_open')

    def test_extract_all_handles_bare_json(self):
        """主脑省 tag 直接 emit 裸 JSON 也提 IntentCall (Sir 真痛点)."""
        from jarvis_intent_router import IntentParser
        calls = IntentParser.extract_all(
            '{"intent": "dashboard_open"} Of course, Sir.'
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].intent_id, 'dashboard_open')

    def test_extract_all_no_double_count(self):
        """同一 intent 出现 tag 和裸 JSON 不重复 count (只看 tag)."""
        from jarvis_intent_router import IntentParser
        # tag 包了的, stray regex 不应再抓 (因为 stripped 后没了)
        calls = IntentParser.extract_all(
            '<TOOL_CALL>{"intent":"x"}</TOOL_CALL>'
        )
        self.assertEqual(len(calls), 1)

    def test_has_tool_call_tag_accepts_bare(self):
        from jarvis_intent_router import IntentParser
        self.assertTrue(IntentParser.has_tool_call_tag(
            '<TOOL_CALL>{"intent":"x"}</TOOL_CALL>'))
        self.assertTrue(IntentParser.has_tool_call_tag(
            '{"intent": "dashboard_open"}'))
        self.assertFalse(IntentParser.has_tool_call_tag(
            'no intent here at all'))

    def test_strip_tags_removes_bare(self):
        from jarvis_intent_router import IntentParser
        out = IntentParser.strip_tags(
            '{"intent": "dashboard_open"} Of course, Sir.'
        )
        self.assertNotIn('"intent"', out)
        self.assertIn('Of course', out)


# ==========================================================================
# L3: InnerThought cooldown 预选 (Sir 真痛 #2)
# ==========================================================================
class TestL3InnerThoughtCooldownPreselect(unittest.TestCase):
    """Sir 真痛: '为什么一直跳过? 都修, 全修'.

    老 BUG: tick → LLM → LLM 选 cooldown 中 → skip → 浪费.
    治本: tick 开头算 free, 全 cooldown 直接 skip 不调 LLM.
    """

    def _empty_daemon(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        with patch.object(InnerThoughtDaemon, 'PERSIST_PATH',
                            os.path.join(tempfile.gettempdir(),
                                         f'empty_{time.time()}.jsonl')):
            d = InnerThoughtDaemon(key_router=None)
        return d

    def test_compute_free_categories_all_at_start(self):
        d = self._empty_daemon()
        free = d._compute_free_categories()
        self.assertEqual(set(free), set('ABCDE'),
            '空 daemon 启动时, 5 类全 free')

    def test_compute_free_excludes_cooldown(self):
        d = self._empty_daemon()
        d._last_category_ts['A'] = time.time()
        d._last_category_ts['B'] = time.time()
        free = d._compute_free_categories()
        self.assertEqual(set(free), set('CDE'))

    def test_compute_free_empty_when_all_cooldown(self):
        d = self._empty_daemon()
        for c in 'ABCDE':
            d._last_category_ts[c] = time.time()
        free = d._compute_free_categories()
        self.assertEqual(free, [],
            '全 cooldown 时返空 list (tick 不调 LLM)')

    def test_build_prompt_with_free_categories(self):
        d = self._empty_daemon()
        sys_p, user_p = d._build_prompt(
            'active', {}, free_categories=['B', 'C', 'D']
        )
        self.assertIn('B|C|D', sys_p,
            'system prompt 必须含 free categories list')
        self.assertIn('COOLDOWN', user_p,
            'user prompt 必须含 COOLDOWN 提示')

    def test_tick_skips_when_all_cooldown(self):
        """全 cooldown 时 _tick 不该调 LLM."""
        d = self._empty_daemon()
        for c in 'ABCDE':
            d._last_category_ts[c] = time.time()
        # mock _call_llm 检测有没有调
        d._call_llm = MagicMock(return_value='')
        d._tick()
        d._call_llm.assert_not_called()


# ==========================================================================
# L4: InnerThought concerns 全 active id 防 hallucinate (Sir 真痛 #3)
# ==========================================================================
class TestL4InnerThoughtConcernsList(unittest.TestCase):
    """Sir 真痛: jarvis_internal_health 不存在 → concern_not_found.

    治本: evidence 给全 active concern id list (不光 top 3).
    """

    def _empty_daemon_with_concerns(self, n=8):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        mock_ledger = MagicMock()
        # 模拟 8 个 active concerns, severity 0.9 → 0.1
        mock_concerns = []
        for i in range(n):
            c = MagicMock()
            c.id = f'sir_concern_{i:02d}'
            c.what_i_watch = f'watch {i}'
            c.severity = 1.0 - i * 0.12
            mock_concerns.append(c)
        mock_ledger.list_active.return_value = mock_concerns
        with patch.object(InnerThoughtDaemon, 'PERSIST_PATH',
                            os.path.join(tempfile.gettempdir(),
                                         f'empty_{time.time()}.jsonl')):
            d = InnerThoughtDaemon(
                key_router=None, concerns_ledger=mock_ledger
            )
        return d

    def test_evidence_returns_top_5_concerns(self):
        d = self._empty_daemon_with_concerns(n=8)
        ev = d._collect_evidence('active', within_seconds=120)
        self.assertEqual(len(ev['concerns']), 5,
            'top 5 by severity (升级自老 top 3)')

    def test_evidence_returns_all_active_ids(self):
        d = self._empty_daemon_with_concerns(n=8)
        ev = d._collect_evidence('active', within_seconds=120)
        self.assertIn('all_active_concern_ids', ev,
            '必须有 all_active_concern_ids field')
        self.assertEqual(len(ev['all_active_concern_ids']), 8,
            '全部 8 个 active id 都给')

    def test_build_prompt_includes_all_active_ids(self):
        d = self._empty_daemon_with_concerns(n=8)
        ev = d._collect_evidence('active', within_seconds=120)
        _, user_p = d._build_prompt('active', ev)
        self.assertIn('ALL VALID concern_ids', user_p,
            'user prompt 必须告知 all valid concern_ids')
        # 真含所有 8 个 id
        for i in range(8):
            self.assertIn(f'sir_concern_{i:02d}', user_p)
        self.assertIn('Inventing IDs will fail', user_p,
            '必须警告 LLM 别 invent id')


# ==========================================================================
# L5: actionable fail → publish SWM (Sir 真痛 #3 闭环)
# ==========================================================================
class TestL5ActionableFailureSWM(unittest.TestCase):
    """主脑下轮 prompt 看到上轮 fail → 改进选 concern_id."""

    def _empty_daemon(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        with patch.object(InnerThoughtDaemon, 'PERSIST_PATH',
                            os.path.join(tempfile.gettempdir(),
                                         f'empty_{time.time()}.jsonl')):
            d = InnerThoughtDaemon(key_router=None)
        return d

    def test_publish_actionable_failure_emits_swm(self):
        from jarvis_inner_thought_daemon import InnerThought
        d = self._empty_daemon()
        thought = InnerThought(
            id='t1', ts=time.time(), ts_iso='?',
            category='C', thought='test',
            salience=0.6,
            actionable='update_concern_severity:jarvis_internal_health:0.1',
        )
        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            d._publish_actionable_failure(
                thought, 'concern_not_found: jarvis_internal_health'
            )
        self.assertTrue(mock_bus.publish.called)
        kw = mock_bus.publish.call_args.kwargs
        self.assertEqual(kw['etype'], 'inner_thought_actionable_failed')
        self.assertIn('jarvis_internal_health',
                       kw['description'] + str(kw['metadata']))


# ==========================================================================
# L6: B 类 self-correction 闭环 (Sir 真痛 #4)
# ==========================================================================
class TestL6BCategorySelfCorrectionLoop(unittest.TestCase):
    """Sir 真痛: 贾维斯意识到自己反复说 interview 但没真治本.

    治本: B 类 thought 含 'i keep repeating' 类 → publish self_correction_noted
    SWM event → SOUL inject 下轮主脑 prompt 真看到 → 真不重复.
    """

    def _empty_daemon(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        with patch.object(InnerThoughtDaemon, 'PERSIST_PATH',
                            os.path.join(tempfile.gettempdir(),
                                         f'empty_{time.time()}.jsonl')):
            d = InnerThoughtDaemon(key_router=None)
        return d

    def test_b_self_correction_publishes_swm(self):
        """B 类 sal >= 0.5 → publish self_reflection_noted.

        🆕 [fix2 Sir 23:38] etype 改 self_correction_noted → self_reflection_noted
        + 删 keyword hardcode (sal 阈值替).
        """
        from jarvis_inner_thought_daemon import InnerThought
        d = self._empty_daemon()
        thought = InnerThought(
            id='t', ts=time.time(), ts_iso='?',
            category='B',
            thought=('I keep repeating that interview preparation line '
                     'despite the preflight warning, which is becoming '
                     'a rather embarrassing pattern of circular logic.'),
            salience=0.8, actionable='none',
        )
        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            d._maybe_publish_self_correction(thought)
        self.assertTrue(mock_bus.publish.called,
            'B 类 sal=0.8 必须 publish SWM')
        kw = mock_bus.publish.call_args.kwargs
        self.assertEqual(kw['etype'], 'self_reflection_noted',
            'fix2 改 etype 为 self_reflection_noted')
        # high salience (主脑下轮真 inject)
        self.assertGreaterEqual(kw['salience'], 0.8)

    def test_b_low_sal_no_publish(self):
        """B 类 sal < 0.5 → 不 publish (noise level).

        🆕 [fix2 Sir 23:38] 原 test_b_without_pattern_no_publish — 现在
        keyword 删了 (准则 6), 改用 sal 阈值. sal < 0.5 当 noise 不 publish.
        """
        from jarvis_inner_thought_daemon import InnerThought
        d = self._empty_daemon()
        thought = InnerThought(
            id='t', ts=time.time(), ts_iso='?',
            category='B',
            thought='My tone was a bit dry just now.',
            salience=0.3, actionable='none',  # sal < 0.5
        )
        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            d._maybe_publish_self_correction(thought)
        mock_bus.publish.assert_not_called()

    def test_non_b_category_no_publish(self):
        """A/C/D/E 类即使含 keyword 也不 publish."""
        from jarvis_inner_thought_daemon import InnerThought
        d = self._empty_daemon()
        thought = InnerThought(
            id='t', ts=time.time(), ts_iso='?',
            category='A',
            thought='I keep repeating myself',
            salience=0.5, actionable='none',
        )
        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            d._maybe_publish_self_correction(thought)
        mock_bus.publish.assert_not_called()

    def test_chinese_pattern_also_matched(self):
        from jarvis_inner_thought_daemon import InnerThought
        d = self._empty_daemon()
        thought = InnerThought(
            id='t', ts=time.time(), ts_iso='?',
            category='B',
            thought='我反复提到面试这件事, 应该停了.',
            salience=0.7, actionable='none',
        )
        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            d._maybe_publish_self_correction(thought)
        self.assertTrue(mock_bus.publish.called,
            '中文 "我反复" 也应触发 self-correction')


if __name__ == '__main__':
    unittest.main()
