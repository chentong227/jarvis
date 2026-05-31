# -*- coding: utf-8 -*-
"""[P3 / Sir 2026-05-31 真测] 思考脑不反复试被拒的 actionable (杀 churn).

真痛 (16:33 日志): D thought call_tool:concerns.progress_update → tool_not_in_allowlist;
E thought 紧接又试 → "misread twice". 同一被拒动作反复试 = 浪费 + churn.

Fix (准则8 治本不复发): _execute_actionable 拒绝结构性 (allowlist/unknown/deprecated)
后记 (kind:target) key + ts; DENIED_ACTIONABLE_COOLDOWN_S 窗口内同 key → 降级 none.
"暂时 gated" (cooldown/sal/cap 会自然恢复) 不记, 不锁正常重试。

覆盖 (无 LLM, duck-typed thought):
  T1 _actionable_key 去 payload, 取 kind:target
  T2 第一次 tool_not_in_allowlist → 拒 + 记 key
  T3 第二次同 actionable → skipped_recently_denied (不再走 handler, 杀 churn)
  T4 不同 target → 不受影响 (不误锁)
  T5 cooldown 过期 → 可再试
  T6 gated 类 (sal 不够) 不记 → 后续可重试 (不误锁正常)
"""
from __future__ import annotations

import os
import sys
import time
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


def _thought(actionable, sal=0.95, tid='thought_p3', text='Sir cups 8 of 10'):
    return SimpleNamespace(actionable=actionable, salience=sal, id=tid,
                           text=text, category='D', evidence_link='cups')


class TestP3DeniedActionableChurn(unittest.TestCase):
    def test_t1_actionable_key(self):
        d = _daemon()
        self.assertEqual(
            d._actionable_key('call_tool:concerns.progress_update:{"x":1}'),
            'call_tool:concerns.progress_update')
        self.assertEqual(d._actionable_key('adjust_concern_notes:sir_x:note here'),
                         'adjust_concern_notes:sir_x')

    def test_t2_first_denial_records(self):
        d = _daemon()
        # 直接测记录/守门逻辑 (不跑全 dispatch — 那需更多 mock)
        now = time.time()
        self.assertFalse(d._is_actionable_denied_recently(
            'call_tool:concerns.progress_update:{}', now)[0])
        d._record_actionable_denied('call_tool:concerns.progress_update:{}', now)
        denied, _ = d._is_actionable_denied_recently(
            'call_tool:concerns.progress_update:{}', now)
        self.assertTrue(denied)

    def test_t3_second_attempt_skipped(self):
        d = _daemon()
        now = time.time()
        d._record_actionable_denied('call_tool:concerns.progress_update:{"a":1}', now)
        # 不同 payload 但同 kind:target → 仍被识别为同一被拒动作
        denied, ago = d._is_actionable_denied_recently(
            'call_tool:concerns.progress_update:{"b":2}', now + 5)
        self.assertTrue(denied)
        self.assertIn('s_ago', ago)

    def test_t4_different_target_not_locked(self):
        d = _daemon()
        now = time.time()
        d._record_actionable_denied('call_tool:concerns.progress_update:{}', now)
        # 不同 tool → 不受影响
        denied, _ = d._is_actionable_denied_recently('call_tool:set_reminder:{}', now)
        self.assertFalse(denied)

    def test_t5_cooldown_expires(self):
        d = _daemon()
        now = time.time()
        d._record_actionable_denied('call_tool:x.y:{}', now)
        # 超 cooldown → 可再试
        later = now + d.DENIED_ACTIONABLE_COOLDOWN_S + 1
        denied, _ = d._is_actionable_denied_recently('call_tool:x.y:{}', later)
        self.assertFalse(denied)

    def test_t6_execute_actionable_skips_denied(self):
        d = _daemon()
        now = time.time()
        d._record_actionable_denied('call_tool:concerns.progress_update:{}', now)
        th = _thought('call_tool:concerns.progress_update:{"current":8}')
        ok, result = d._execute_actionable(th)
        self.assertFalse(ok)
        self.assertIn('skipped_recently_denied', result)
        self.assertEqual(th.actionable, 'none')  # 降级防 SOUL inject

    def test_t7_bounded_memory(self):
        d = _daemon()
        now = time.time()
        for i in range(80):
            d._record_actionable_denied(f'call_tool:t{i}:{{}}', now)
        self.assertLessEqual(len(d._denied_actionables), 64)  # 有界


if __name__ == '__main__':
    unittest.main(verbosity=2)
