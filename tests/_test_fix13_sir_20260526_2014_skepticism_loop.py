# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 20:14 真意 anchor 3] Sir Skepticism Learning Loop regression test.

Sir 真意 (第三次细化):
  "通过我跟他对话能动态调整 — 一个奇怪的 inside joke 我提质疑时它会降低
   使用权重, 多次质疑甚至考虑删除. 不希望调工具."

覆盖 (准则 6 数据强耦合 + 准则 8 优雅):
  - Detector: skepticism / reactivation / confusion + priority
  - Attribution: SWM 'inside_joke_injected' 30s 内 → 匹到 joke
  - Decay: count 1→2→3 weight decay / auto archive / reactivation 反悔
  - End-to-end: process_sir_reply (Detector → Attribution → Decay → SWM)
  - Wire: chat_bypass 已 hook + thought evidence + 7 tool 不暴露
"""
from __future__ import annotations

import os
import sys
import time
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(name: str) -> str:
    with open(os.path.join(ROOT, name), 'r', encoding='utf-8') as f:
        return f.read()


def _fresh_bus():
    """fresh ConversationEventBus + register_global."""
    from jarvis_utils import ConversationEventBus
    bus = ConversationEventBus()
    ConversationEventBus.register_global(bus)
    return bus


def _fresh_store():
    """fresh RelationalStateStore (隔离 singleton, 防数据污染)."""
    import jarvis_relational as _jr
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        persist = f.name
    store = _jr.RelationalStateStore(persist_path=persist)
    _jr._DEFAULT_STORE = store
    return store, persist


def _fresh_ledger():
    """fresh ConcernsLedger (隔离 singleton)."""
    import jarvis_concerns as _jc
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        persist = f.name
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        review = f.name
    ledger = _jc.ConcernsLedger(persist_path=persist, review_path=review)
    _jc._DEFAULT_LEDGER = ledger
    return ledger, persist, review


# ==========================================================================
# L1: SkepticismDetector
# ==========================================================================
class TestSkepticismDetector(unittest.TestCase):

    def test_detect_skepticism_zh(self):
        from jarvis_sir_skepticism import detect_skepticism
        sig = detect_skepticism("这梗好奇怪")
        self.assertIsNotNone(sig)
        self.assertEqual(sig.kind, 'skepticism')
        self.assertIn('奇怪', sig.matched_phrase)

    def test_detect_skepticism_en(self):
        from jarvis_sir_skepticism import detect_skepticism
        sig = detect_skepticism("That joke is just weird")
        self.assertIsNotNone(sig)
        self.assertEqual(sig.kind, 'skepticism')

    def test_detect_reactivation(self):
        from jarvis_sir_skepticism import detect_skepticism
        sig = detect_skepticism("再提一下那个 hydration concern")
        self.assertIsNotNone(sig)
        self.assertEqual(sig.kind, 'reactivation')

    def test_detect_confusion(self):
        from jarvis_sir_skepticism import detect_skepticism
        sig = detect_skepticism("你什么意思?")
        self.assertIsNotNone(sig)
        self.assertEqual(sig.kind, 'confusion')

    def test_detect_no_skepticism_returns_none(self):
        from jarvis_sir_skepticism import detect_skepticism
        self.assertIsNone(detect_skepticism("好的, 谢谢你"))
        self.assertIsNone(detect_skepticism(""))
        self.assertIsNone(detect_skepticism(None))

    def test_reactivation_priority_over_skepticism(self):
        """reactivation > skepticism > confusion (反悔最优先)."""
        from jarvis_sir_skepticism import detect_skepticism
        # 含 reactivation + skepticism 词 → 应优先 reactivation
        sig = detect_skepticism("再提一下那个奇怪的事")
        self.assertEqual(sig.kind, 'reactivation')


# ==========================================================================
# L2: Attribution
# ==========================================================================
class TestAttribution(unittest.TestCase):

    def test_attribute_to_inside_joke_via_swm(self):
        from jarvis_sir_skepticism import attribute_skepticism
        bus = _fresh_bus()
        bus.publish(
            etype='inside_joke_injected',
            description='inject joke X',
            source='test',
            salience=0.5,
            metadata={'joke_id': 'joke_001', 'phrase': "the alpha test phrase"},
        )
        res = attribute_skepticism(sir_reply="这梗好奇怪")
        self.assertIsNotNone(res)
        self.assertEqual(res.target_kind, 'inside_joke')
        self.assertEqual(res.target_id, 'joke_001')

    def test_attribute_to_concern_via_nudge_fired(self):
        from jarvis_sir_skepticism import attribute_skepticism
        bus = _fresh_bus()
        bus.publish(
            etype='proactive_nudge_fired',
            description='nudge for hydration',
            source='test',
            salience=0.5,
            metadata={
                'concern_id': 'sir_hydration',
                'kind': 'hydration',
                'sentinel': 'ProactiveCare',
            },
        )
        res = attribute_skepticism(sir_reply="别提了")
        self.assertIsNotNone(res)
        # concern attribution has higher confidence than bare nudge
        self.assertEqual(res.target_kind, 'concern')
        self.assertEqual(res.target_id, 'sir_hydration')

    def test_attribute_no_recent_event_returns_none(self):
        from jarvis_sir_skepticism import attribute_skepticism
        _fresh_bus()  # empty bus
        self.assertIsNone(attribute_skepticism(sir_reply="奇怪"))


# ==========================================================================
# L3: Decay
# ==========================================================================
class TestDecayEngine(unittest.TestCase):

    def setUp(self):
        self.bus = _fresh_bus()
        self.store, self.store_path = _fresh_store()

    def tearDown(self):
        try:
            os.unlink(self.store_path)
        except Exception:
            pass

    def test_decay_inside_joke_count_1_weight_decay(self):
        from jarvis_relational import InsideJoke
        from jarvis_sir_skepticism import (
            apply_decay, AttributionResult, SkepticismSignal,
        )
        joke = InsideJoke(id='j1', phrase="test phrase")
        self.store.inside_jokes['j1'] = joke
        attr = AttributionResult(
            target_kind='inside_joke', target_id='j1',
            target_preview='test', confidence=0.9, reason='test',
        )
        sig = SkepticismSignal(
            kind='skepticism', matched_phrase='奇怪', sir_reply='this is 奇怪',
        )
        action = apply_decay(attr, sig)
        self.assertIsNotNone(action)
        self.assertEqual(action.action, 'weight_lowered')
        self.assertEqual(action.new_skepticism_count, 1)
        self.assertAlmostEqual(joke.use_weight, 0.7, places=2)

    def test_decay_inside_joke_count_3_auto_archive(self):
        from jarvis_relational import InsideJoke
        from jarvis_sir_skepticism import (
            apply_decay, AttributionResult, SkepticismSignal,
        )
        joke = InsideJoke(id='j2', phrase="another phrase")
        joke.skepticism_count = 2  # 已 2 次, 这次第 3 触发 archive
        joke.use_weight = 0.5
        self.store.inside_jokes['j2'] = joke
        attr = AttributionResult(
            target_kind='inside_joke', target_id='j2',
            target_preview='', confidence=0.9, reason='test',
        )
        sig = SkepticismSignal(
            kind='skepticism', matched_phrase='别提了', sir_reply='别提了',
        )
        action = apply_decay(attr, sig)
        self.assertEqual(action.action, 'archived')
        self.assertEqual(joke.state, 'archived')
        self.assertAlmostEqual(joke.use_weight, 0.0, places=2)

    def test_decay_reactivation_decrements_count(self):
        from jarvis_relational import InsideJoke
        from jarvis_sir_skepticism import (
            apply_decay, AttributionResult, SkepticismSignal,
        )
        joke = InsideJoke(id='j3', phrase="reactivation test")
        joke.skepticism_count = 2
        joke.use_weight = 0.5
        self.store.inside_jokes['j3'] = joke
        attr = AttributionResult(
            target_kind='inside_joke', target_id='j3',
            target_preview='', confidence=0.9, reason='test',
        )
        sig = SkepticismSignal(
            kind='reactivation', matched_phrase='再提一下', sir_reply='再提一下那个',
        )
        action = apply_decay(attr, sig)
        self.assertEqual(action.action, 'reactivated')
        self.assertEqual(joke.skepticism_count, 1)  # 2 → 1
        self.assertGreater(joke.use_weight, 0.5)    # 0.5 / 0.7 ≈ 0.71


# ==========================================================================
# L4: End-to-end (process_sir_reply 主入口)
# ==========================================================================
class TestProcessSirReply(unittest.TestCase):

    def setUp(self):
        self.bus = _fresh_bus()
        self.store, self.store_path = _fresh_store()

    def tearDown(self):
        try:
            os.unlink(self.store_path)
        except Exception:
            pass

    def test_e2e_sir_skepticism_decays_recent_joke(self):
        """Sir 自然说 "好奇怪" 后, 30s 内 inject 的 joke 自动 decay."""
        from jarvis_relational import InsideJoke
        from jarvis_sir_skepticism import process_sir_reply

        joke = InsideJoke(id='j_e2e', phrase="some inside joke")
        self.store.inside_jokes['j_e2e'] = joke
        # inject SWM event
        self.bus.publish(
            etype='inside_joke_injected',
            description='inject j_e2e',
            source='test',
            salience=0.5,
            metadata={'joke_id': 'j_e2e', 'phrase': 'some inside joke'},
        )

        action = process_sir_reply("这梗好奇怪")
        self.assertIsNotNone(action)
        self.assertEqual(action.target_kind, 'inside_joke')
        self.assertEqual(action.target_id, 'j_e2e')
        self.assertEqual(joke.skepticism_count, 1)
        # SWM 应有 sir_skepticism 和 item_skepticism_decay event
        all_events = self.bus.top_n(n=20) or []
        etypes = [e.get('type') for e in all_events]
        self.assertIn('sir_skepticism', etypes)
        self.assertIn('item_skepticism_decay', etypes)

    def test_e2e_confusion_does_not_decay(self):
        """Sir 困惑不算质疑 — 只 publish event, 不 decay item."""
        from jarvis_relational import InsideJoke
        from jarvis_sir_skepticism import process_sir_reply
        joke = InsideJoke(id='j_conf', phrase="phrase")
        self.store.inside_jokes['j_conf'] = joke
        self.bus.publish(
            etype='inside_joke_injected',
            description='inject',
            source='test',
            salience=0.5,
            metadata={'joke_id': 'j_conf', 'phrase': 'phrase'},
        )
        action = process_sir_reply("你什么意思?")
        self.assertIsNone(action, 'confusion 不该 trigger decay')
        self.assertEqual(joke.skepticism_count, 0, 'count 不应变')


# ==========================================================================
# L5: Wire / 集成检查
# ==========================================================================
class TestWireIntegration(unittest.TestCase):

    def test_chat_bypass_hook_present(self):
        """chat_bypass 必须含 SirSkepticismDetect worker hook."""
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('SirSkepticismDetect', src,
                       'chat_bypass 必须含 skepticism worker thread')
        self.assertIn('from jarvis_sir_skepticism import process_sir_reply', src,
                       'chat_bypass 必须 import process_sir_reply')

    def test_chat_bypass_skips_system_event(self):
        """skepticism hook 必须 skip is_system_event ([SYSTEM ALERT] 非 Sir 真话)."""
        src = _read('jarvis_chat_bypass.py')
        # 抓 skepticism worker 段, 看是否含 is_system_event guard
        idx = src.find('SirSkepticismDetect')
        self.assertGreater(idx, 0)
        block = src[max(0, idx - 500):idx + 100]
        self.assertIn('not is_system_event', block,
                       'skepticism worker 必须 skip system event')

    def test_thought_evidence_includes_recent_skepticism(self):
        """InnerThoughtDaemon _collect_evidence 必须含 recent_skepticism_events."""
        src = _read('jarvis_inner_thought_daemon.py')
        self.assertIn('recent_skepticism_events', src,
                       'thought evidence 必须含 recent_skepticism_events')
        self.assertIn('_SKEPTICISM_ETYPES', src,
                       'thought evidence 必须含 skepticism etype filter')

    def test_thought_prompt_renders_skepticism_block(self):
        """_build_prompt 必须渲染 SIR SKEPTICISM RECENT block."""
        src = _read('jarvis_inner_thought_daemon.py')
        self.assertIn('SIR SKEPTICISM RECENT', src,
                       'prompt 必须含 [SIR SKEPTICISM RECENT] block')

    def test_7_mutation_tools_not_registered(self):
        """Sir 真意 anchor 3: 7 mutation tool fn 保留但不注册到 TOOL_REGISTRY."""
        from jarvis_tool_registry import get_tool_registry
        registry = get_tool_registry()
        for name in (
            'revert_auto_arbiter_decision',
            'tune_auto_arbiter_threshold',
            'dismiss_concern',
            'archive_relational_item',
            'cancel_promise',
            'tune_inner_thought_allowlist',
            'tune_runtime_log_marker',
        ):
            self.assertNotIn(
                name, registry,
                f'mutation tool {name!r} 不应在 TOOL_REGISTRY (Sir 真意: 不让主脑直接调)'
            )

    def test_7_mutation_tools_fn_still_importable(self):
        """7 mutation tool fn 必须保留 (Skepticism Loop 内部可 import)."""
        import jarvis_tool_registry as _jtr
        for fn_name in (
            'tool_revert_auto_arbiter_decision',
            'tool_tune_auto_arbiter_threshold',
            'tool_dismiss_concern',
            'tool_archive_relational_item',
            'tool_cancel_promise',
            'tool_tune_inner_thought_allowlist',
            'tool_tune_runtime_log_marker',
        ):
            self.assertTrue(hasattr(_jtr, fn_name),
                             f'fn {fn_name} 必须保留以供 Loop 内部调用')


# ==========================================================================
# L6: dataclass field 扩展
# ==========================================================================
class TestDataclassFields(unittest.TestCase):

    def test_inside_joke_has_skepticism_count_and_use_weight(self):
        from jarvis_relational import InsideJoke
        j = InsideJoke(id='x', phrase='y')
        self.assertEqual(j.skepticism_count, 0)
        self.assertEqual(j.use_weight, 1.0)

    def test_protocol_has_skepticism_count_and_rejected(self):
        from jarvis_relational import UnspokenProtocol
        p = UnspokenProtocol(id='x', rule='y')
        self.assertEqual(p.skepticism_count, 0)
        self.assertEqual(p.rejected, 0)

    def test_concern_has_skepticism_count(self):
        from jarvis_concerns import Concern
        c = Concern(id='x', what_i_watch='y', why_i_care='z')
        self.assertEqual(c.skepticism_count, 0)


if __name__ == '__main__':
    unittest.main()
