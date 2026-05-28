# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 23:34 P13+P14 治本] 两个 BUG 综合回归.

P13: subtitle 字幕泄漏 LLM 输出 {"intent": "dashboard_open"} JSON tail.
  Sir 截图: '好的，先生。正在为您打开面板。\\nOf course, Sir. Opening the
  dashboard now. {"intent": "dashboard_open"}' — 字幕显示了裸 intent JSON.
  根因: jarvis_utils.scrub_internal_names 之前只剥 <TOOL_CALL> paired tag,
  没剥裸 inline JSON. jarvis_ui._poll_queue zh/en channel 调 scrub 后还残留.
  治本: scrub_internal_names 加 _INTERNAL_STRAY_INTENT_JSON_RE 剥裸 JSON.

P14: AutoArbiter pre-reject abstract protocol min_hits=2 门槛过松.
  Sir dashboard 截图 7+ abstract propose 含 1 个 'prioritize' / 'be more'
  keyword 没被 reject (因 single hit 不达 min_hits=2). Sir 反问 "这些全要
  我拍板吗?" — 元否决根因 = 不该手动.
  治本: schema 加 hard_reject_keywords tier (1 hit 即 reject, 放最确定
  aspirational verb), 旧 abstract_keywords 退化 soft tier (2+ hits 才 reject).

测试覆盖:
  P13:
    T01 scrub_internal_names 剥 paired <TOOL_CALL>{...}</TOOL_CALL>
    T02 scrub_internal_names 剥裸 {"intent": "dashboard_open"} (Sir 截图)
    T03 scrub_internal_names 剥裸带空格 / 带 params 变体
    T04 scrub_internal_names 不误伤合法 { ... } (math/code)
    T05 has_internal_name 识别裸 intent JSON
    T06 双源同步: jarvis_safety + jarvis_utils 两 regex 输出一致

  P14:
    T07 vocab schema v2 含 hard_reject_keywords + abstract_keywords
    T08 _is_abstract_protocol: hard kw 单 hit 即 reject (Sir 截图原 rule)
    T09 _is_abstract_protocol: soft kw 单 hit 不 reject
    T10 _is_abstract_protocol: soft kw 2 hits reject
    T11 _is_abstract_protocol: 短 rule (< min_words) reject
    T12 _is_abstract_protocol: 合法 imperative rule pass (不误伤)
    T13 _is_abstract_protocol: vocab disabled 退化 (不 reject 任何)
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
from unittest import mock

if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# =====================================================================
# P13: subtitle 裸 intent JSON 字幕泄漏修复
# =====================================================================

class TestP13SubtitleStripsBareIntentJSON(unittest.TestCase):
    """jarvis_utils.scrub_internal_names 剥裸 intent JSON 防字幕泄漏."""

    def test_t01_scrub_strips_paired_tool_call_tag(self):
        """T1 paired <TOOL_CALL>...</TOOL_CALL> 剥 (老行为不破)."""
        from jarvis_utils import scrub_internal_names
        text = ('Hello <TOOL_CALL>{"intent":"x"}</TOOL_CALL> world')
        out = scrub_internal_names(text)
        self.assertNotIn('<TOOL_CALL>', out)
        self.assertNotIn('"intent"', out)
        self.assertIn('Hello', out)
        self.assertIn('world', out)

    def test_t02_scrub_strips_bare_intent_json_sir_screenshot(self):
        """T2 Sir 截图原文 '... {"intent": "dashboard_open"}' 剥."""
        from jarvis_utils import scrub_internal_names
        # Sir 截图原文 (中英双行)
        text = (
            '好的，先生。正在为您打开面板。\n'
            'Of course, Sir. Opening the dashboard now. '
            '{"intent": "dashboard_open"}'
        )
        out = scrub_internal_names(text)
        self.assertNotIn('"intent"', out,
            f'裸 JSON 没剥, Sir 截图 BUG 复现. out={out!r}')
        self.assertNotIn('dashboard_open', out)
        self.assertIn('好的，先生', out)
        self.assertIn('Of course', out)

    def test_t03_scrub_strips_intent_with_variants(self):
        """T3 裸 JSON 不同变体: 无空格 / 带 args / 多 key."""
        from jarvis_utils import scrub_internal_names
        cases = [
            '{"intent":"dashboard_open"}',
            '{"intent": "set_reminder", "time": "10am"}',
            '{"intent": "x", "args": {"a": 1}}',
            'something {"intent":"y"} else',
        ]
        for s in cases:
            out = scrub_internal_names(s)
            self.assertNotIn('"intent"', out, f"未剥: {s!r} → {out!r}")

    def test_t04_scrub_preserves_legal_braces(self):
        """T4 合法 { ... } (math/code) 不误伤."""
        from jarvis_utils import scrub_internal_names
        cases = [
            'I think {math expression} is interesting.',
            'function foo() { return 1; }',
            'JSON-like {"name": "Alice"} but not intent',
        ]
        for s in cases:
            out = scrub_internal_names(s)
            # 不应剥 (没 "intent" key)
            # math expression / function / Alice 应保留
            for marker in ('math expression', 'function', 'Alice'):
                if marker in s:
                    self.assertIn(marker, out,
                        f'合法文本被误剥: {s!r} → {out!r}')

    def test_t05_has_internal_name_detects_bare_intent(self):
        """T5 has_internal_name 识别裸 intent JSON (用于诊断)."""
        from jarvis_utils import has_internal_name
        self.assertTrue(has_internal_name('{"intent": "x"}'))
        self.assertTrue(has_internal_name('foo {"intent":"y"} bar'))
        self.assertFalse(has_internal_name('no intent here at all'))
        self.assertFalse(has_internal_name('{"name": "Alice"}'),
            '不含 intent key 的 JSON 不应识别')

    def test_t06_safety_and_utils_regex_consistent(self):
        """T6 双源 (jarvis_safety + jarvis_utils) 两 regex 输出一致.

        避免规则发散: 同一 input safety._strip_structural_tag_blocks 和
        utils.scrub_internal_names 都要剥裸 intent JSON.
        """
        from jarvis_safety import _strip_structural_tag_blocks
        from jarvis_utils import scrub_internal_names
        text = 'hello {"intent": "dashboard_open"} world'
        a = _strip_structural_tag_blocks(text)
        b = scrub_internal_names(text)
        # 二者都不应保留 intent JSON
        self.assertNotIn('"intent"', a)
        self.assertNotIn('"intent"', b)
        # 至少 hello + world 都保留
        self.assertIn('hello', a)
        self.assertIn('hello', b)
        self.assertIn('world', a)
        self.assertIn('world', b)


# =====================================================================
# P14: AutoArbiter abstract protocol hard tier reject
# =====================================================================

class TestP14ArbiterAbstractHardTier(unittest.TestCase):
    """vocab schema v2: hard_reject_keywords (1 hit reject) +
    abstract_keywords (soft, N hits reject)."""

    def test_t07_vocab_has_hard_and_soft_tier(self):
        """T7 vocab JSON 必含 schema v2 双 tier."""
        vocab_path = os.path.join(
            ROOT, 'memory_pool', 'auto_arbiter_abstract_reject_vocab.json',
        )
        self.assertTrue(os.path.exists(vocab_path))
        with open(vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data.get('schema_version'), 2,
            'schema_version 应升 2 (P14)')
        self.assertIn('hard_reject_keywords', data,
            'hard_reject_keywords (1 hit reject) 必需')
        self.assertIn('abstract_keywords', data,
            'abstract_keywords (soft, N hits reject) 保留')
        self.assertTrue(data.get('enabled', False))
        # Sir 截图触发词必须在 hard list
        hard_lower = [k.lower() for k in data['hard_reject_keywords']]
        self.assertIn('prioritize', hard_lower,
            "'prioritize' 是 Sir 截图最常见 aspirational, 必须在 hard list")

    def _make_arbiter(self, vocab_override=None):
        """构造 AutoArbiterDaemon stub 用 mock vocab."""
        import jarvis_auto_arbiter as aa
        daemon = aa.AutoArbiterDaemon.__new__(aa.AutoArbiterDaemon)
        # _is_abstract_protocol 用到的 _load_abstract_reject_vocab
        # 用 mock 注入 vocab
        if vocab_override is not None:
            daemon._load_abstract_reject_vocab = lambda: vocab_override
        return daemon

    def test_t08_hard_kw_single_hit_rejects(self):
        """T8 含 1 个 hard kw 即 reject (Sir 截图原 rule)."""
        from jarvis_auto_arbiter import AutoArbiterDaemon
        daemon = AutoArbiterDaemon.__new__(AutoArbiterDaemon)
        with mock.patch.object(daemon, '_load_abstract_reject_vocab',
                                  return_value={
            'enabled': True,
            'hard_reject_keywords': ['prioritize', 'be more'],
            'abstract_keywords': ['maintain'],
            'min_keyword_hits_to_reject': 2,
            'min_words_in_rule': 4,
        }):
            # Sir 截图原 rule 1
            is_abs, reason = daemon._is_abstract_protocol(
                'Prioritize conversational flow over log-like syntax '
                'when confirming system states'
            )
            self.assertTrue(is_abs,
                f'含 hard kw "prioritize" 单 hit 必 reject. reason={reason}')
            self.assertIn('hard_kw_hit', reason)
            self.assertIn('prioritize', reason)

    def test_t09_soft_kw_single_hit_does_not_reject(self):
        """T9 含 1 个 soft kw 不 reject (避免误伤合法 imperative)."""
        from jarvis_auto_arbiter import AutoArbiterDaemon
        daemon = AutoArbiterDaemon.__new__(AutoArbiterDaemon)
        with mock.patch.object(daemon, '_load_abstract_reject_vocab',
                                  return_value={
            'enabled': True,
            'hard_reject_keywords': ['prioritize'],
            'abstract_keywords': ['maintain', 'tone'],
            'min_keyword_hits_to_reject': 2,
            'min_words_in_rule': 4,
        }):
            # 含 1 个 soft 'maintain', 但其余具体
            is_abs, reason = daemon._is_abstract_protocol(
                'Always maintain user file path when confirming reminder set'
            )
            self.assertFalse(is_abs,
                f'1 个 soft kw 不应 reject. reason={reason}')
            self.assertIn('concrete', reason)

    def test_t10_soft_kw_two_hits_reject(self):
        """T10 含 2 个 soft kw reject (Sir 截图 'maintain ... tone')."""
        from jarvis_auto_arbiter import AutoArbiterDaemon
        daemon = AutoArbiterDaemon.__new__(AutoArbiterDaemon)
        with mock.patch.object(daemon, '_load_abstract_reject_vocab',
                                  return_value={
            'enabled': True,
            'hard_reject_keywords': [],
            'abstract_keywords': ['maintain', 'tone', 'natural'],
            'min_keyword_hits_to_reject': 2,
            'min_words_in_rule': 4,
        }):
            is_abs, reason = daemon._is_abstract_protocol(
                'Always maintain a natural tone when responding'
            )
            self.assertTrue(is_abs)
            self.assertIn('soft_kw_hit', reason)

    def test_t11_short_rule_rejects(self):
        """T11 短 rule (< min_words) reject (太抽象)."""
        from jarvis_auto_arbiter import AutoArbiterDaemon
        daemon = AutoArbiterDaemon.__new__(AutoArbiterDaemon)
        with mock.patch.object(daemon, '_load_abstract_reject_vocab',
                                  return_value={
            'enabled': True,
            'hard_reject_keywords': [],
            'abstract_keywords': [],
            'min_keyword_hits_to_reject': 2,
            'min_words_in_rule': 4,
        }):
            is_abs, reason = daemon._is_abstract_protocol('Be concise')
            self.assertTrue(is_abs)
            self.assertIn('too_short', reason)

    def test_t12_concrete_imperative_passes(self):
        """T12 合法具体 imperative rule pass (不误伤)."""
        from jarvis_auto_arbiter import AutoArbiterDaemon
        daemon = AutoArbiterDaemon.__new__(AutoArbiterDaemon)
        with mock.patch.object(daemon, '_load_abstract_reject_vocab',
                                  return_value={
            'enabled': True,
            'hard_reject_keywords': ['prioritize', 'aspire'],
            'abstract_keywords': ['maintain', 'tone'],
            'min_keyword_hits_to_reject': 2,
            'min_words_in_rule': 4,
        }):
            # 具体 imperative — 含 0 hard, 0 soft
            for rule in [
                "Do not open replies with formal apologies like 'My apologies, Sir'",
                "Never say 'Good morning' more than once per morning",
                "Always include user file path when confirming reminder",
            ]:
                is_abs, reason = daemon._is_abstract_protocol(rule)
                self.assertFalse(is_abs,
                    f"合法 imperative 被误 reject: '{rule}' reason={reason}")

    def test_t13_vocab_disabled_passes_all(self):
        """T13 vocab disabled 退化 (不 reject 任何, 主路径走 LLM eval)."""
        from jarvis_auto_arbiter import AutoArbiterDaemon
        daemon = AutoArbiterDaemon.__new__(AutoArbiterDaemon)
        with mock.patch.object(daemon, '_load_abstract_reject_vocab',
                                  return_value={
            'enabled': False,
            'hard_reject_keywords': ['prioritize'],
        }):
            # 即便含 hard kw, disabled 时不 reject
            is_abs, reason = daemon._is_abstract_protocol(
                'Prioritize concise responses always'
            )
            self.assertFalse(is_abs)
            self.assertEqual(reason, 'vocab_disabled')


if __name__ == '__main__':
    unittest.main(verbosity=2)
