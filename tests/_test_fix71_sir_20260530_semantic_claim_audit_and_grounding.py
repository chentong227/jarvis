# -*- coding: utf-8 -*-
"""[言出必行 I2 + I3 / Sir 2026-05-30] 语义 claim 审计 + 主脑开口前接地 回归.

I2 枚举→语义: ClaimTracer 老 extract_claims 是正则枚举 (每个新幻觉加一条 regex,
和"要他记得什么就 hand-code"同病). 治本 (准则 6 信任 LLM): 思考脑后台 LLM 语义判
claim 接地, 不靠无限加 regex. 准则 1: 默 off + cooldown + 只后台, 不碰主脑热路径.

I3 预防>拦截: full-mode lifetime block 注入 Jarvis 活跃 open 线程 (经 Layer 1.6 既有
管道到主脑) → 主脑开口前 grounded → 少凭空编造 → 减少 post-hoc 撤回.

测试覆盖:
  I2A semantic_claim_audit: LLM flag ungrounded; 无 key_router/空/非JSON → []
  I2B _maybe_semantic_claim_audit: 默 off no-op; 开启+新 reply → 跑
  I3 build_lifetime_block(full) 注 OPEN THREADS; mini 不注 (省 token)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    return InnerThoughtDaemon(
        key_router=MagicMock(), concerns_ledger=None,
        relational_state=None, central_nerve=None,
    )


class TestI2SemanticAudit(unittest.TestCase):
    def setUp(self):
        self.daemon = _make_daemon()

    def test_flags_ungrounded(self):
        self.daemon._call_llm = (
            lambda s, u, caller_origin=None:
            '[{"claim":"CPU at 87%","grounded":false,"reason":"no telemetry"}]')
        out = self.daemon.semantic_claim_audit("The CPU is at 87% right now.")
        self.assertEqual(len(out), 1)
        self.assertIn('CPU', out[0]['claim'])
        self.assertIn('telemetry', out[0]['reason'])

    def test_grounded_returns_empty(self):
        self.daemon._call_llm = (
            lambda s, u, caller_origin=None:
            '[{"claim":"opened dashboard","grounded":true,"reason":"tool ok"}]')
        self.assertEqual(
            self.daemon.semantic_claim_audit("I opened the dashboard."), [])

    def test_empty_list(self):
        self.daemon._call_llm = lambda s, u, caller_origin=None: '[]'
        self.assertEqual(self.daemon.semantic_claim_audit("Hello Sir."), [])

    def test_non_json_safe(self):
        self.daemon._call_llm = (
            lambda s, u, caller_origin=None: 'I think everything is fine')
        self.assertEqual(
            self.daemon.semantic_claim_audit("The CPU is at 87%."), [])

    def test_no_key_router(self):
        self.daemon.key_router = None
        self.assertEqual(
            self.daemon.semantic_claim_audit("The CPU is at 87%."), [])


class TestI2MaybeAudit(unittest.TestCase):
    def setUp(self):
        self.daemon = _make_daemon()

    def test_disabled_is_noop(self):
        """vocab disabled → 不调 LLM (准则 1 token 安全). [Sir 23:38 默认已改 ON,
        故此处显式 override 成 disabled 验证 gate 本身]."""
        self.daemon._load_lifetime_vocab = lambda: {
            'semantic_claim_check_enabled': False}
        calls = []
        self.daemon._call_llm = (
            lambda *a, **k: calls.append(1) or '[]')
        self.daemon.nerve = MagicMock()
        self.daemon.nerve.short_term_memory = [
            {'user': 'hi', 'jarvis': 'The CPU is at 87%'}]
        self.daemon._maybe_semantic_claim_audit()
        self.assertEqual(calls, [], "disabled 不该调 LLM")

    def test_enabled_runs_on_new_reply(self):
        self.daemon._load_lifetime_vocab = lambda: {
            'semantic_claim_check_enabled': True,
            'semantic_claim_check_cooldown_s': 0,
        }
        self.daemon._call_llm = (
            lambda s, u, caller_origin=None:
            '[{"claim":"87%","grounded":false,"reason":"no data"}]')
        self.daemon.nerve = MagicMock()
        self.daemon.nerve.short_term_memory = [
            {'user': 'cpu?', 'jarvis': 'The CPU is at 87% right now.'}]
        self.daemon._last_audited_reply = ''
        self.daemon._last_semantic_audit_ts = 0.0
        self.daemon._maybe_semantic_claim_audit()
        self.assertEqual(self.daemon._last_audited_reply,
                         'The CPU is at 87% right now.',
                         "enabled + 新 reply → 应跑审计")


class TestI3Grounding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.daemon = _make_daemon()
        self.daemon._SELF_THREADS_PATH = os.path.join(
            self.tmp, 'self_threads.json')
        self.daemon._save_self_threads({'threads': [
            {'thread_id': 't_o', 'summary': "OPENMARKER live concern thread",
             'status': 'open', 'salience_decayed': 0.6, 'tier': 'hot',
             'occurrences': 3},
        ]})

    def test_full_mode_injects_open_threads(self):
        block = self.daemon.build_lifetime_block(mode='full')
        self.assertIn('OPEN THREADS', block,
            "full mode (主聊) 应注入 open 线程供主脑接地 (I3 预防)")
        self.assertIn('OPENMARKER', block)

    def test_mini_mode_no_open_threads(self):
        block = self.daemon.build_lifetime_block(mode='mini')
        self.assertNotIn('OPENMARKER', block,
            "mini mode 省 token, 不注 open 线程")


if __name__ == '__main__':
    unittest.main(verbosity=2)
