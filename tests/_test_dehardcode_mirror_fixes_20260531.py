# -*- coding: utf-8 -*-
"""[thinking-dehardcode mirror-fixes / Sir 2026-05-31] 镜像实机测试挖出的 fix 回归.

镜像 (scripts/jarvis_mirror.py) 真跑 Phase0 代码挖到 (详双层报告):
  #1 假称完成: MutationEvidenceGuard 拦了 protocol.proactive_reminders 写入, 但主脑
     continuation 看 raw "evidence_guard_blocked: no_evidence..." 没懂, 仍抢答
     "已为您更新个人偏好配置" → 违准则 5. Fix: block 消息改 LLM 可懂的明确指令.
  #2 硬编码词面闸丢高价值思考: C 思考(sal 0.85)识别真问题→adjust_concern_notes 被
     _evidence_links_to_concern no_token_overlap 拒 (cite"coding without rest" 跟
     concern[pomodoro,compliance] 零词面重叠), 虽 thought 整体明说 "pomodoro compliance".
     Fix: cite 无重叠 → fallback 看 full thought (准则6 信任 LLM + 准则8 不丢高价值).
     + churn 防护: wrong_concern 进 denied-actionable cooldown.

覆盖 (无 LLM):
  #2:
    T1 cite 命中 concern → pass (老路径不破)
    T2 cite 无命中但 thought 命中 → pass (本 fix; pomodoro 真实 case)
    T3 cite + thought 都跟 concern 无关 → reject (真 wrong-concern 防护不破)
    T4 cite + thought 都空/全 stopword → trust LLM (pass)
    T5 concern 无 meaningful token → trust (pass)
    T6 churn: evidence_link_wrong_concern 在结构性拒绝 cooldown 列表
  #1:
    T7 guard block message 含明确指令 (NOT saved + Do NOT claim done)
"""
from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_inner_thought_daemon import InnerThoughtDaemon


def _daemon():
    d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
    d._bg_log = lambda *a, **k: None
    return d


def _concern(cid, what=''):
    return SimpleNamespace(id=cid, what_i_watch=what, severity=0.5,
                           notes_for_self='')


class TestFix2ConcernLinkGate(unittest.TestCase):
    """#2: _evidence_links_to_concern cite 无重叠 fallback 看 full thought."""

    def test_t1_cite_overlap_passes(self):
        d = _daemon()
        c = _concern('sir_pomodoro_compliance', 'breaks every 25 min')
        ok, msg = d._evidence_links_to_concern('pomodoro breaks', c, 'whatever')
        self.assertTrue(ok, msg)
        self.assertIn('overlap', msg)

    def test_t2_thought_overlap_passes(self):
        """真实镜像 case: cite 词面不重叠, 但 thought 整体明说 concern 主题."""
        d = _daemon()
        c = _concern('sir_pomodoro_compliance', 'take breaks every 25 min')
        cite = 'coding without rest'   # 词 [coding, rest, without] 跟 concern 零重叠
        thought = ("Sir's lack of breaks despite six hours of coding indicates "
                   "his pomodoro compliance is failing.")
        ok, msg = d._evidence_links_to_concern(cite, c, thought)
        self.assertTrue(ok, f'thought 含 pomodoro/compliance 应 pass, got: {msg}')
        self.assertIn('thought_overlap', msg)

    def test_t3_truly_wrong_concern_still_rejected(self):
        """thought 整体跟 concern 无关 → 仍拒 (wrong-concern 防护不破)."""
        d = _daemon()
        c = _concern('sir_interview_pr', 'interview preparation readiness')
        cite = 'toggling general coding'
        thought = 'Sir keeps toggling between general and coding windows.'
        ok, msg = d._evidence_links_to_concern(cite, c, thought)
        self.assertFalse(ok, f'toggling/coding 跟 interview 无关应 reject, got: {msg}')
        self.assertIn('no_token_overlap', msg)

    def test_t4_empty_cite_and_thought_trusts_llm(self):
        d = _daemon()
        c = _concern('sir_pomodoro_compliance', 'breaks every 25 min')
        ok, msg = d._evidence_links_to_concern('the a of', c, 'i my you it')
        self.assertTrue(ok, msg)

    def test_t5_concern_no_tokens_trusts_llm(self):
        d = _daemon()
        c = _concern('', '')
        ok, msg = d._evidence_links_to_concern('coding rest', c, 'some thought')
        self.assertTrue(ok, msg)

    def test_t6_wrong_concern_in_churn_cooldown_list(self):
        """churn 防护: evidence_link_wrong_concern 触发 denied-actionable 记录."""
        import inspect
        src = inspect.getsource(InnerThoughtDaemon._execute_actionable)
        self.assertIn('evidence_link_wrong_concern', src,
                      'wrong_concern 应进 _record_actionable_denied 触发列表 (防 churn)')


class TestFix1GuardBlockMessage(unittest.TestCase):
    """#1: guard block 消息含 LLM 可懂的明确指令 (不假称完成)."""

    def test_t7_block_message_is_imperative(self):
        import inspect
        import jarvis_memory_hub
        src = inspect.getsource(jarvis_memory_hub)
        # 保留 token (下游 console/circuit/SWM detector 依赖)
        self.assertIn('evidence_guard_blocked', src)
        # 新增明确指令
        self.assertIn('NOT saved', src)
        self.assertIn('Do NOT tell Sir', src)


if __name__ == '__main__':
    unittest.main()
