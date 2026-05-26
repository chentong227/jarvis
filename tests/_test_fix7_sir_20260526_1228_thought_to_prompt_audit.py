# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 12:28 真痛 CRITICAL audit] 思考真影响 prompt 注入 — 5 actionable 闭环.

Sir 真意 anchor:
  "继续排查思考反向影响所有行为能否实现, 从根源到成效一个个排查, 让其能影响 prompt
  注入和挑选, 保证贾维斯的思考是真能调整他的行为, 而不是一个展示在面板给我看的玩具
  (我虽然很满意, 非常满意他自己能发现我觉得不舒服的地方, 但是如果不是真的就毫无
  意义了)"

排查链路 (Generate → State Change → Prompt Inject → Main Brain Sees):
  1. update_concern_severity → ledger.severity → Layer 1 to_prompt_block ✅
  2. publish_swm → event_bus → STANDARD event_bus_block + swm_block ✅
  3. suggest_inside_joke → relational.inside_jokes → Layer 2 "INSIDE JOKES" ✅
  4. propose_protocol → relational.unspoken_protocols → Layer 2 "STRICT RULES" ✅
     (Phase A persist 已修 e64ab29, Phase C.2 trigger filter 已加 cf67b98)
  5. adjust_concern_notes → ledger.notes_for_self → Layer 1 ❌ → ✅
     **CRITICAL 修**: ConcernsLedger.to_prompt_block 漏 inject notes_for_self,
     Phase B (Sir 真意 "减少对面试准备的打扰") silently 全废.
     dismiss / pending_ack / snooze 也写 notes_for_self, 全废.
     修: to_prompt_block 加 "⚠ note to self: <notes>" 行, cap 200 char.

测试覆盖 (10 个):
  L1 (FIX7 anchor) to_prompt_block 注入 notes_for_self 含 "⚠ note to self:"
  L2 to_prompt_block 空 notes_for_self 不污染输出 (向后兼容)
  L3 to_prompt_block 长 notes cap 200 char (防 prompt 膨胀)
  L4 端到端 Phase B: adjust_concern_notes → ledger.notes_for_self 改 →
     to_prompt_block 输出含主脑能读的 guidance ✅
  L5 端到端 dismiss: dismiss reason → notes_for_self [dismissed/sir_voice] →
     to_prompt_block 输出含 (这是老 ☆ 链路也被修)
  L6 update_concern_severity → ledger.severity → to_prompt_block 显 sev= ✅
  L7 propose_protocol → relational.unspoken_protocols → to_prompt_block (Layer 2)
     "STRICT RULES" 真含 (跨 Phase A 验证)
  L8 suggest_inside_joke → relational.inside_jokes → to_prompt_block "INSIDE JOKES" 真含
  L9 InnerThought build_soul_block 真注入 top by salience thought (Layer 1.5 验证)
  L10 综合: 一个 C-class thought + adjust_concern_notes → 90s 后下次 turn prompt
      Layer 1 真含 note (端到端真测)
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
# L1: 🎯 Sir 真痛 anchor — to_prompt_block 注入 notes_for_self
# ==========================================================================
class TestL1NotesForSelfInjected(unittest.TestCase):
    def test_notes_for_self_appears_in_prompt_block(self):
        """🎯 Sir 12:28 真痛 anchor: notes_for_self 必须 inject 主脑能看见."""
        from jarvis_concerns import ConcernsLedger, Concern
        tmp = tempfile.mktemp(suffix='.json')
        ledger = ConcernsLedger(persist_path=tmp)
        ledger.register(Concern(
            id='sir_interview_pr',
            what_i_watch='Sir interview preparation balance',
            why_i_care='Sir career-defining moment',
            severity=0.5,
            notes_for_self='DO NOT volunteer this topic — only address when Sir asks directly',
        ))
        block = ledger.to_prompt_block(top_n=3, max_chars=900)
        self.assertIn('⚠ note to self:', block,
            'Layer 1 prompt 必须含 "⚠ note to self:" tag (Sir 真痛 anchor)')
        self.assertIn('DO NOT volunteer', block,
            'note 内容必须真注入主脑 prompt')


# ==========================================================================
# L2: 空 notes 不污染
# ==========================================================================
class TestL2EmptyNotesNoPollution(unittest.TestCase):
    def test_empty_notes_no_pollution(self):
        from jarvis_concerns import ConcernsLedger, Concern
        tmp = tempfile.mktemp(suffix='.json')
        ledger = ConcernsLedger(persist_path=tmp)
        ledger.register(Concern(
            id='c1', what_i_watch='watch x', why_i_care='care y',
            severity=0.5,
        ))
        block = ledger.to_prompt_block()
        self.assertNotIn('⚠ note to self:', block,
            '空 notes_for_self 不应出现 tag (向后兼容)')


# ==========================================================================
# L3: 长 notes cap 防膨胀
# ==========================================================================
class TestL3NotesCapped(unittest.TestCase):
    def test_long_notes_capped_at_200_char(self):
        from jarvis_concerns import ConcernsLedger, Concern
        tmp = tempfile.mktemp(suffix='.json')
        ledger = ConcernsLedger(persist_path=tmp)
        long_note = 'X' * 500
        ledger.register(Concern(
            id='c1', what_i_watch='watch', why_i_care='care',
            severity=0.5, notes_for_self=long_note,
        ))
        block = ledger.to_prompt_block(top_n=3, max_chars=900)
        # cap 200 char on the inject line (整行 ≤ 240 含 tag)
        for line in block.split('\n'):
            if '⚠ note to self:' in line:
                self.assertLessEqual(len(line), 240,
                    f'note line cap 240 防 prompt 膨胀, got {len(line)}')
                break


# ==========================================================================
# L4: 🎯 端到端 Phase B (Sir 真意 "减少对面试准备的打扰")
# ==========================================================================
class TestL4PhaseBClosedLoop(unittest.TestCase):
    def test_adjust_concern_notes_to_prompt_full_loop(self):
        """C 类 thought → adjust_concern_notes → ledger.notes_for_self →
        to_prompt_block 输出 → 主脑下轮真读 guidance ✅"""
        from jarvis_concerns import ConcernsLedger, Concern
        from jarvis_inner_thought_daemon import InnerThoughtDaemon, InnerThought
        tmp = tempfile.mktemp(suffix='.json')
        ledger = ConcernsLedger(persist_path=tmp)
        ledger.register(Concern(
            id='sir_interview_pr',
            what_i_watch='Sir interview preparation balance and progress',
            why_i_care='Sir career-defining moment',
            severity=0.5,
        ))
        # Build daemon + run actionable
        daemon_persist = tempfile.mktemp(suffix='.jsonl')
        saved = InnerThoughtDaemon.PERSIST_PATH
        InnerThoughtDaemon.PERSIST_PATH = daemon_persist
        try:
            d = InnerThoughtDaemon(
                key_router=None,
                concerns_ledger=ledger,
            )
        finally:
            InnerThoughtDaemon.PERSIST_PATH = saved
        t = InnerThought(
            id='t_phase_b_e2e',
            ts=time.time(),
            ts_iso='?',
            category='C',
            thought='Sir asked me to stop bringing up interview prep unprompted',
            salience=0.85,
            actionable=(
                'adjust_concern_notes:sir_interview_pr:'
                'DO NOT volunteer this topic — only address when Sir asks'
            ),
            evidence_link='interview prep',
        )
        # Step 1: actionable 真改 state
        ok, result = d._execute_actionable(t)
        self.assertTrue(ok, f'actionable should succeed: {result}')
        # Step 2: ledger.notes_for_self 真改
        c = ledger.get('sir_interview_pr')
        self.assertIn('DO NOT volunteer', c.notes_for_self,
            'ledger.notes_for_self 真改 (Phase B step 2)')
        # Step 3: to_prompt_block 真显 note
        block = ledger.to_prompt_block(top_n=3, max_chars=900)
        self.assertIn('DO NOT volunteer', block,
            '🎯 Sir 真痛 anchor: 主脑 Layer 1 prompt 真含 "DO NOT volunteer this topic"')
        self.assertIn('⚠ note to self:', block)


# ==========================================================================
# L5: dismiss 老链路 — notes_for_self 真注入主脑
# ==========================================================================
class TestL5DismissNotesInjected(unittest.TestCase):
    def test_dismiss_writes_notes_and_prompt_shows(self):
        """老 dismiss 路径也写 notes_for_self ("[dismissed/sir_voice] ...") —
        也被 fix7 修, 主脑下轮真知 Sir dismissed."""
        from jarvis_concerns import ConcernsLedger, Concern
        tmp = tempfile.mktemp(suffix='.json')
        ledger = ConcernsLedger(persist_path=tmp)
        ledger.register(Concern(
            id='sir_topic_x',
            what_i_watch='watching topic x',
            why_i_care='care',
            severity=0.7,
        ))
        ledger.dismiss('sir_topic_x', reason='I do not want to discuss x anymore',
                        source='sir_voice')
        block = ledger.to_prompt_block(top_n=3, max_chars=900)
        self.assertIn('⚠ note to self:', block,
            'dismiss 写 notes_for_self 必须显示给主脑')
        self.assertIn('[dismissed/sir_voice]', block,
            'dismiss tag 必须真注入主脑 (主脑下轮知 Sir 已 dismissed)')


# ==========================================================================
# L6: update_concern_severity → severity 显 sev= (老闭环验证)
# ==========================================================================
class TestL6SeverityInjected(unittest.TestCase):
    def test_severity_shown_in_prompt(self):
        from jarvis_concerns import ConcernsLedger, Concern
        tmp = tempfile.mktemp(suffix='.json')
        ledger = ConcernsLedger(persist_path=tmp)
        ledger.register(Concern(
            id='c_urgent',
            what_i_watch='watching',
            why_i_care='because',
            severity=0.85,
        ))
        block = ledger.to_prompt_block()
        self.assertIn('sev=0.85', block,
            'severity 必须真显 sev=X.XX 给主脑')
        self.assertIn('[⚠ URGENT]', block,
            'severity > 0.6 真加 URGENT 前缀')


# ==========================================================================
# L7: propose_protocol → Layer 2 "STRICT RULES" 注入 (跨 Phase A 验证)
# ==========================================================================
class TestL7ProtocolInjected(unittest.TestCase):
    def test_protocol_in_layer_2_strict_rules(self):
        from jarvis_relational import RelationalStateStore, UnspokenProtocol
        tmp = tempfile.mktemp(suffix='.json')
        rs = RelationalStateStore(persist_path=tmp)
        rs.add_protocol(UnspokenProtocol(
            id='p_test',
            rule='Do not open replies with formal apologies',
            source='inner_thought',
        ))
        block = rs.to_prompt_block()
        self.assertIn('STRICT RULES', block,
            'Layer 2 必须含 "STRICT RULES" 段')
        self.assertIn('Do not open replies', block,
            'protocol rule 真注入主脑')


# ==========================================================================
# L8: suggest_inside_joke → Layer 2 "INSIDE JOKES" 注入
# ==========================================================================
class TestL8InsideJokeInjected(unittest.TestCase):
    def test_inside_joke_in_layer_2(self):
        from jarvis_relational import RelationalStateStore, InsideJoke
        tmp = tempfile.mktemp(suffix='.json')
        rs = RelationalStateStore(persist_path=tmp)
        rs.add_inside_joke(InsideJoke(
            id='j_test',
            phrase='vocal cord logic',
            tone='wry',
        ))
        block = rs.to_prompt_block()
        self.assertIn('INSIDE JOKES', block,
            'Layer 2 必须含 "INSIDE JOKES" 段')
        self.assertIn('vocal cord logic', block,
            'inside joke phrase 真注入主脑')


# ==========================================================================
# L9: InnerThought build_soul_block 真注入 top thought (Layer 1.5)
# ==========================================================================
class TestL9ThoughtSoulInject(unittest.TestCase):
    def test_top_thought_in_soul_block(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon, InnerThought
        daemon_persist = tempfile.mktemp(suffix='.jsonl')
        saved = InnerThoughtDaemon.PERSIST_PATH
        InnerThoughtDaemon.PERSIST_PATH = daemon_persist
        try:
            d = InnerThoughtDaemon(key_router=None)
        finally:
            InnerThoughtDaemon.PERSIST_PATH = saved
        d._thoughts.append(InnerThought(
            id='t1', ts=time.time(), ts_iso='?',
            category='B', thought='I noticed I keep apologizing too much',
            salience=0.9, actionable='none',
        ))
        block = d.build_soul_block(max_chars=500)
        self.assertIn('MY RECENT INNER THOUGHTS', block,
            'Layer 1.5 必须含 "MY RECENT INNER THOUGHTS" header')
        self.assertIn('keep apologizing', block,
            'top thought 真注入主脑')


# ==========================================================================
# L10: 综合端到端 — C-class adjust_concern_notes 完整闭环
# ==========================================================================
class TestL10ComprehensiveEndToEnd(unittest.TestCase):
    def test_complete_loop_phase_b(self):
        """C-class thought → execute_actionable → ledger 改 →
        to_prompt_block 输出 → 模拟主脑下轮真读"""
        from jarvis_concerns import ConcernsLedger, Concern
        from jarvis_inner_thought_daemon import InnerThoughtDaemon, InnerThought
        from jarvis_relational import RelationalStateStore, UnspokenProtocol

        # 全 setup
        ledger_tmp = tempfile.mktemp(suffix='.json')
        rel_tmp = tempfile.mktemp(suffix='.json')
        rel_review = tempfile.mktemp(suffix='.json')
        daemon_persist = tempfile.mktemp(suffix='.jsonl')

        ledger = ConcernsLedger(persist_path=ledger_tmp)
        ledger.register(Concern(
            id='sir_interview_pr',
            what_i_watch='Sir interview preparation balance',
            why_i_care='career',
            severity=0.5,
        ))

        rs = RelationalStateStore(persist_path=rel_tmp, review_path=rel_review)

        saved = InnerThoughtDaemon.PERSIST_PATH
        InnerThoughtDaemon.PERSIST_PATH = daemon_persist
        try:
            d = InnerThoughtDaemon(
                key_router=None,
                concerns_ledger=ledger,
                relational_state=rs,
            )
        finally:
            InnerThoughtDaemon.PERSIST_PATH = saved

        # 1. C-class thought + adjust_concern_notes
        t = InnerThought(
            id='t_e2e',
            ts=time.time(),
            ts_iso='?',
            category='C',
            thought='Sir asked me to stop bringing up interview prep',
            salience=0.85,
            actionable=(
                'adjust_concern_notes:sir_interview_pr:'
                'DO NOT volunteer this topic — only when Sir asks'
            ),
            evidence_link='interview prep',
        )
        ok, _ = d._execute_actionable(t)
        self.assertTrue(ok)

        # 2. 模拟下轮主脑 prompt 组装 — Layer 1 真含 note
        layer_1_block = ledger.to_prompt_block(top_n=3, max_chars=900)
        self.assertIn('DO NOT volunteer', layer_1_block,
            '🎯 端到端: Sir 真意 "减少对面试准备的打扰" 主脑下轮 prompt 真读到 guidance')


if __name__ == '__main__':
    unittest.main()
