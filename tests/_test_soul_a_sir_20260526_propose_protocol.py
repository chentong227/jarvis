# -*- coding: utf-8 -*-
"""[SOUL Phase A / Sir 2026-05-26] InnerThought B 类反思 → propose_protocol →
AutoArbiter 自决 → RelationalState protocols active → Layer 2 STRICT RULES 闭环.

Sir 真意 (双约束):
  不加新 Layer / 不加新 daemon / 不加新 module — 只在现有 InnerThought.actionable
  parser + execute 加 propose_protocol 分支, 接现有 RelationalState + AutoArbiter
  钩子. 让 B 类反思真改变贾维斯下次行为.

Sir 启动 log 真证据缺口:
  💞 [RelationalState] jokes=5 protocols=0 ← protocols 接口空着, 这是闭环的最大缺口.

设计 (准则 5 言出必行 + 6 evidence + 7 Sir 元否决 + 8 优雅):
  - InnerThought B 类 sal≥0.75 + propose_protocol:<rule>
  - Python 双 gate (category=B + sal≥0.75) 拒非法 propose
  - 复用 evidence_link 双层校验 (cite 在 thought + cite ↔ rule overlap)
  - RelationalState.propose_protocol (dedup substring + jaccard)
  - AutoArbiter 30min tick 自决 (thr=0.80 严过 joke)
  - Sir 元否决: AutoArbiter sir_revert 一键撤销

测试覆盖 (18 个):
  L1 RelationalState propose_protocol (basic / dedup substring / dedup jaccard / empty rule)
  L2 RelationalState review pipe (list_protocols_review / activate_from_review / reject_from_review)
  L3 RelationalState write_review_queue 含 protocols
  L4 AutoArbiter thresholds + RISK_LOW 含 protocol
  L5 AutoArbiter _tick 拉 protocol queue
  L6 AutoArbiter _collect_evidence protocol branch
  L7 AutoArbiter _build_prompt protocol criteria + user block
  L8 InnerThought _do_propose_protocol (B-class gate / sal gate / empty rule / rule too short / success)
  L9 InnerThought _execute_actionable 'propose_protocol:' 分支 route
  L10 prompt 含 propose_protocol option + B 类 example
  L11 端到端: B 类 sal=0.8 + propose_protocol → relational queue 有新条目
  L12 端到端: 非 B 类 propose_protocol → 拒
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


def _empty_relational():
    """临时 RelationalState (不污染 production memory_pool)."""
    from jarvis_relational import RelationalStateStore
    tmp_dir = tempfile.mkdtemp(prefix='soul_a_rs_')
    rs = RelationalStateStore(
        persist_path=os.path.join(tmp_dir, 'state.json'),
        review_path=os.path.join(tmp_dir, 'review.json'),
    )
    return rs


def _empty_daemon(relational=None):
    """临时 InnerThoughtDaemon (临时 PERSIST_PATH + 可选 relational)."""
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    tmp = os.path.join(tempfile.gettempdir(),
                          f'soul_a_it_{time.time()}.jsonl')
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp
    try:
        d = InnerThoughtDaemon(
            key_router=None,
            relational_state=relational,
        )
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp
    return d


def _mk_thought(thought_text: str, actionable: str = 'none',
                  evidence_link: str = '', category: str = 'B',
                  salience: float = 0.8):
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id=f't_{time.time()}',
        ts=time.time(),
        ts_iso='?',
        category=category,
        thought=thought_text,
        salience=salience,
        actionable=actionable,
        evidence_link=evidence_link,
    )


# ==========================================================================
# L1: RelationalState.propose_protocol
# ==========================================================================
class TestL1ProposeProtocol(unittest.TestCase):
    def test_basic_propose_creates_review_state(self):
        from jarvis_relational import UnspokenProtocol, STATE_REVIEW
        rs = _empty_relational()
        p = UnspokenProtocol(
            id='proto_001',
            rule='Do not open replies with formal apologies',
            source='inner_thought',
        )
        ok = rs.propose_protocol(p)
        self.assertTrue(ok)
        # state 强制 REVIEW
        self.assertEqual(rs.unspoken_protocols['proto_001'].state, STATE_REVIEW)

    def test_dedup_exact_match_rejected(self):
        from jarvis_relational import UnspokenProtocol
        rs = _empty_relational()
        p1 = UnspokenProtocol(id='p1', rule='Do not use formal apologies')
        p2 = UnspokenProtocol(id='p2', rule='Do not use formal apologies')
        self.assertTrue(rs.propose_protocol(p1))
        self.assertFalse(rs.propose_protocol(p2),
            '完全相同 rule 必须 dedup')
        self.assertEqual(len(rs.unspoken_protocols), 1)

    def test_dedup_substring_rejected(self):
        from jarvis_relational import UnspokenProtocol
        rs = _empty_relational()
        p1 = UnspokenProtocol(id='p1',
            rule='Do not open replies with formal apologies like My apologies Sir')
        p2 = UnspokenProtocol(id='p2',
            rule='Do not open replies with formal apologies')
        self.assertTrue(rs.propose_protocol(p1))
        self.assertFalse(rs.propose_protocol(p2),
            'substring 子集必须 dedup')

    def test_dedup_jaccard_rejected(self):
        from jarvis_relational import UnspokenProtocol
        rs = _empty_relational()
        p1 = UnspokenProtocol(id='p1',
            rule='Always confirm tool calls before executing')
        p2 = UnspokenProtocol(id='p2',
            rule='Always confirm tool before executing calls')  # 词序换
        self.assertTrue(rs.propose_protocol(p1))
        self.assertFalse(rs.propose_protocol(p2),
            'jaccard ≥0.7 必须 dedup (词序换不算新)')

    def test_empty_rule_rejected(self):
        from jarvis_relational import UnspokenProtocol
        rs = _empty_relational()
        p = UnspokenProtocol(id='p_empty', rule='')
        self.assertFalse(rs.propose_protocol(p))


# ==========================================================================
# L2 + L3: RelationalState review pipe + write_review_queue
# ==========================================================================
class TestL2L3ReviewPipe(unittest.TestCase):
    def setUp(self):
        from jarvis_relational import UnspokenProtocol
        self.rs = _empty_relational()
        p = UnspokenProtocol(id='p_rev', rule='Test protocol for review pipe')
        self.rs.propose_protocol(p)

    def test_list_protocols_review_returns_proposed(self):
        from jarvis_relational import STATE_REVIEW
        items = self.rs.list_protocols_review()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].state, STATE_REVIEW)

    def test_activate_from_review_protocol(self):
        from jarvis_relational import STATE_ACTIVE
        res = self.rs.activate_from_review('p_rev')
        self.assertEqual(res, 'protocol')
        self.assertEqual(
            self.rs.unspoken_protocols['p_rev'].state, STATE_ACTIVE
        )

    def test_reject_from_review_protocol(self):
        from jarvis_relational import STATE_ARCHIVED
        res = self.rs.reject_from_review('p_rev')
        self.assertEqual(res, 'protocol')
        self.assertEqual(
            self.rs.unspoken_protocols['p_rev'].state, STATE_ARCHIVED
        )

    def test_write_review_queue_includes_protocols(self):
        self.rs.write_review_queue()
        with open(self.rs.review_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('unspoken_protocols', data)
        self.assertEqual(len(data['unspoken_protocols']), 1)
        self.assertEqual(
            data['unspoken_protocols'][0]['rule'],
            'Test protocol for review pipe'
        )


# ==========================================================================
# L4-L7: AutoArbiter 扩展
# ==========================================================================
class TestL4L7AutoArbiterProtocol(unittest.TestCase):
    def test_thresholds_has_protocol(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        self.assertIn('protocol', AutoArbiterDaemon.DEFAULT_THRESHOLDS)
        self.assertGreater(
            AutoArbiterDaemon.DEFAULT_THRESHOLDS['protocol'],
            AutoArbiterDaemon.DEFAULT_THRESHOLDS['inside_joke'],
            'protocol 阈值必须严过 joke (行为 STRICT)'
        )
        self.assertLess(
            AutoArbiterDaemon.DEFAULT_THRESHOLDS['protocol'],
            AutoArbiterDaemon.DEFAULT_THRESHOLDS['directive'],
            'protocol 阈值松过 directive (后者全链路 trigger 复杂)'
        )

    def test_risk_low_includes_protocol(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        self.assertIn('protocol', AutoArbiterDaemon.RISK_LOW,
            'protocol 必须在 RISK_LOW 真自决 (Sir 元否决可 revert)')

    def test_collect_evidence_protocol_branch(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        from jarvis_relational import UnspokenProtocol
        rs = _empty_relational()
        aa = AutoArbiterDaemon(key_router=None, relational_state=rs)
        proto = UnspokenProtocol(
            id='p_test', rule='Test rule for evidence', source='inner_thought'
        )
        ev = aa._collect_evidence('protocol', proto)
        self.assertEqual(ev['kind'], 'protocol')
        self.assertEqual(ev['entity']['rule'], 'Test rule for evidence')
        self.assertEqual(ev['entity']['source'], 'inner_thought')
        self.assertIn('existing_active_protocols', ev)

    def test_build_prompt_protocol_criteria(self):
        from jarvis_auto_arbiter import AutoArbiterDaemon
        from jarvis_relational import UnspokenProtocol
        rs = _empty_relational()
        aa = AutoArbiterDaemon(key_router=None, relational_state=rs)
        proto = UnspokenProtocol(id='p_t', rule='Do not be too formal')
        ev = aa._collect_evidence('protocol', proto)
        sys_p, user_p = aa._build_prompt('protocol', proto, ev)
        # protocol criteria 关键词
        self.assertIn('IMPERATIVE', sys_p,
            'prompt 必须教 LLM 看 IMPERATIVE 形式')
        self.assertIn('OBSERVABLE', sys_p,
            'prompt 必须教 LLM 看 OBSERVABLE')
        self.assertIn('STRICT RULES', sys_p,
            'prompt 必须告 LLM 这条会进 STRICT RULES')
        # user block 含 candidate rule
        self.assertIn('Do not be too formal', user_p)


# ==========================================================================
# L8-L9: InnerThought _do_propose_protocol + actionable route
# ==========================================================================
class TestL8L9InnerThoughtProposeProtocol(unittest.TestCase):
    def setUp(self):
        self.rs = _empty_relational()
        self.d = _empty_daemon(relational=self.rs)

    def test_l8_cross_class_with_high_sal_accepted(self):
        """🆕 [Sir 2026-05-26 23:17 BUG-4/A 准则 6] 删 B-class hard gate.
        cross-class propose_protocol 允许, 只要 sal ≥ 0.75 + rule 合法.
        (老 hard gate 拦 A/C/D/E 不合理, LLM 自决类别用法.)
        """
        t = _mk_thought(
            'Sir is coding rapidly without proper breaks now',
            actionable='propose_protocol:Do not let Sir skip breaks',
            evidence_link='without proper breaks',
            category='A',  # 非 B — 新 design 允许 cross-class
            salience=0.8,  # 高 sal → 通过 sal gate
        )
        ok, result = self.d._do_propose_protocol(t, t.actionable)
        # 新 design: A-class + sal=0.8 → 不被 category gate 拦
        # (可能被 relational_state propose_protocol 内部 dedup, 但 not gated:protocol_only_from_B)
        self.assertNotIn('gated:protocol_only_from_B_reflect', result,
            '准则 6: cross-class propose_protocol 不应被 hard gate 拦')

    def test_l8_sal_gate_low_sal_rejected(self):
        """gated: B 类但 sal<0.75 → rejected."""
        t = _mk_thought(
            'I sounded a bit formal in that reply maybe softer next time',
            actionable='propose_protocol:Do not open replies with formal apologies',
            evidence_link='formal',
            category='B',
            salience=0.5,  # 太低
        )
        ok, result = self.d._do_propose_protocol(t, t.actionable)
        self.assertFalse(ok)
        self.assertIn('gated:protocol_requires_sal', result)

    def test_l8_empty_rule_rejected(self):
        t = _mk_thought(
            'I noticed something interesting about my tone here',
            actionable='propose_protocol:',
            evidence_link='tone',
            category='B',
            salience=0.8,
        )
        ok, result = self.d._do_propose_protocol(t, t.actionable)
        self.assertFalse(ok)
        self.assertIn('empty_rule', result)

    def test_l8_rule_too_short_rejected(self):
        t = _mk_thought(
            'I need to be more careful with my tone going forward',
            actionable='propose_protocol:short',  # < 10 char
            evidence_link='tone',
            category='B',
            salience=0.8,
        )
        ok, result = self.d._do_propose_protocol(t, t.actionable)
        self.assertFalse(ok)
        self.assertIn('rule_too_short', result)

    def test_l8_success_creates_protocol_in_review(self):
        from jarvis_relational import STATE_REVIEW
        t = _mk_thought(
            'I opened that reply with My apologies Sir which was too formal',
            actionable='propose_protocol:Do not open replies with formal apologies',
            evidence_link='formal',
            category='B',
            salience=0.8,
        )
        ok, result = self.d._do_propose_protocol(t, t.actionable)
        self.assertTrue(ok, f'should succeed, got: {result}')
        self.assertIn('proposed:', result)
        # 真在 review queue
        review_items = self.rs.list_protocols_review()
        self.assertEqual(len(review_items), 1)
        self.assertEqual(
            review_items[0].rule,
            'Do not open replies with formal apologies'
        )
        self.assertEqual(review_items[0].source, 'inner_thought')

    def test_l9_execute_actionable_routes_propose_protocol(self):
        """_execute_actionable 真 route 到 _do_propose_protocol."""
        t = _mk_thought(
            'I opened that reply with My apologies Sir which was too formal',
            actionable='propose_protocol:Do not open replies with formal apologies',
            evidence_link='formal',
            category='B',
            salience=0.8,
        )
        ok, result = self.d._execute_actionable(t)
        self.assertTrue(ok, f'should succeed, got: {result}')
        self.assertIn('proposed:', result)


# ==========================================================================
# L10: prompt 含 propose_protocol option + B 类 example
# ==========================================================================
class TestL10PromptIncludesPropose(unittest.TestCase):
    def test_prompt_has_propose_protocol_actionable(self):
        d = _empty_daemon()
        sys_p, _ = d._build_prompt('active', {'sir_state': 'active'},
                                       free_categories=['A', 'B', 'C', 'D', 'E'])
        self.assertIn('propose_protocol', sys_p,
            'prompt 必须含 propose_protocol actionable option')
        # B 类 anchor: "If sal≥0.75 ... use propose_protocol"
        self.assertIn('propose_protocol to make it', sys_p,
            'prompt 必须教 B 类用 propose_protocol')
        # B-class example anchor
        self.assertIn('formal apologies', sys_p,
            'prompt 必须含 Sir 真痛 anchor B 类 example')


# ==========================================================================
# L11-L12: 端到端
# ==========================================================================
class TestL11L12EndToEnd(unittest.TestCase):
    def test_l11_end_to_end_b_class_sal_high_proposes(self):
        """端到端: B 类 sal=0.8 + propose_protocol → review queue 真有."""
        rs = _empty_relational()
        d = _empty_daemon(relational=rs)
        t = _mk_thought(
            'I opened my last reply with My apologies Sir — too formal stiffness',
            actionable='propose_protocol:Do not open replies with formal apologies',
            evidence_link='formal',
            category='B',
            salience=0.85,
        )
        ok, result = d._execute_actionable(t)
        self.assertTrue(ok)
        # 真在 review queue
        self.assertEqual(len(rs.list_protocols_review()), 1)

    def test_l12_end_to_end_cross_class_accepted(self):
        """🆕 [Sir 2026-05-26 23:17 BUG-4/A 准则 6] 删 B-class hard gate.
        端到端: A 类 + sal=0.85 propose_protocol → review queue 应有 1 (跨类允许).
        老 design: A class 被拦 → queue 0; 新 design: cross-class OK → queue 1.
        """
        rs = _empty_relational()
        d = _empty_daemon(relational=rs)
        t = _mk_thought(
            'Sir is coding rapidly with general tasks switching frequently',
            actionable='propose_protocol:Stop interrupting when Sir is in deep work',
            evidence_link='coding rapidly',
            category='A',  # 非 B — 新 design 允许 cross-class
            salience=0.85,  # 高 sal → 通过 sal gate
        )
        ok, _ = d._execute_actionable(t)
        # 跨类 + 高 sal → 应成功进 review queue
        self.assertTrue(ok, '准则 6: cross-class propose_protocol with high sal 应成功')
        self.assertEqual(len(rs.list_protocols_review()), 1,
            'review queue 应有 1 个 protocol (cross-class accepted)')


if __name__ == '__main__':
    unittest.main()
