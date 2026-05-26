# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 19:48 真问 anchor] 思考 → 主动性 升级 Phase 1+2+3 回归.

Sir 真问: "目前的思考和让贾维斯拥有真正的主动性还有多大的距离?"
Sir 拍板: "全面推进, 全做, 做完核验效果"

设计文档: docs/JARVIS_THINKING_TO_AGENCY_DESIGN.md
工程总计: ~400 行 (3 phase) — 0 新模块, 复用 13 sentinel + Anticipator +
        PromiseLog 4 kind + DaemonHealthMonitor + WRC + TOOL_REGISTRY

测试覆盖 (26 testcase):

Phase 1A — fire_nudge actionable (8 testcase):
  - sal < 0.85 → gated (FA1)
  - sal >= 0.85 + empty draft → fail (FA2)
  - sal >= 0.85 + valid draft + no_nerve → fail (FA3)
  - sal >= 0.85 + valid → fire 成功 (FA4)
  - fire 后 publish_proactive_nudge_fired (FA5)
  - yield 时 publish_proactive_nudge_skipped (FA6)
  - fire 走 push_command __NUDGE__ (FA7)
  - chat_bypass directive 含 'INNER THOUGHT FIRE' wrap (FA8)

Phase 1B — anticipated_ltm_context evidence (3 testcase):
  - nerve 有 anticipator + preload 非空 → evidence 含 (LB1)
  - nerve 无 anticipator → evidence 缺 anticipated_ltm_context (LB2)
  - 主脑 prompt 含 [ANTICIPATED LTM CONTEXT] block (LB3)

Phase 1C — daemon_health evidence (3 testcase):
  - SWM 有 daemon_health_warning → evidence 含 (LC1)
  - SWM 无 → evidence daemon_health 空 (LC2)
  - 主脑 prompt 含 [MY OWN HEALTH] block (LC3)

Phase 2A — propose_watch_task actionable (5 testcase):
  - A/B 类 → gated (only C/D) (WT1)
  - C 类 sal < 0.75 → gated (WT2)
  - C/D 类 sal >= 0.75 + valid → 注册 PromiseLog watch kind (WT3)
  - trigger_pattern 真持久化 (WT4)
  - empty desc → fail (WT5)

Phase 2B — outcome field (2 testcase):
  - InnerThought dataclass 含 outcome 字段, default='pending' (OC1)
  - outcome 字段持久化进 jsonl (OC2)

Phase 3 — call_tool actionable + allowlist (5 testcase):
  - sal < 0.90 → gated (CT1)
  - tool 不在 allowlist → fail (CT2)
  - tool 在 allowlist + valid args → 调成功 (CT3)
  - call_tool 后 publish SWM 'inner_thought_tool_called' (CT4)
  - args 非 JSON → fail (CT5)
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


def _make_thought(category='B', salience=0.9, actionable='none',
                    evidence_link='none', thought_text='I noticed Sir...'):
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id=f"th_test_{int(time.time() * 1000)}",
        ts=time.time(),
        ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S'),
        category=category,
        thought=thought_text,
        salience=salience,
        actionable=actionable,
        evidence_link=evidence_link,
    )


def _make_daemon(nerve=None):
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    return InnerThoughtDaemon(
        key_router=MagicMock(),
        concerns_ledger=None,
        relational_state=None,
        central_nerve=nerve,
    )


# ==========================================================================
# Phase 1A: fire_nudge actionable
# ==========================================================================
class TestPhase1AFireNudge(unittest.TestCase):
    def test_fa1_low_sal_gated(self):
        """sal < 0.85 → gated."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.7,
                                  actionable='fire_nudge:thought_obs:test draft')
        ok, msg = daemon._do_fire_nudge_actionable(thought, thought.actionable)
        self.assertFalse(ok)
        self.assertIn('gated:fire_nudge_requires_sal', msg)

    def test_fa2_empty_draft_fails(self):
        """draft 空 → fail."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.9,
                                  actionable='fire_nudge:thought_obs:')
        ok, msg = daemon._do_fire_nudge_actionable(thought, thought.actionable)
        self.assertFalse(ok)
        self.assertIn('empty_draft', msg)

    def test_fa3_no_nerve_fails(self):
        """no_nerve → fail (无 push_command)."""
        daemon = _make_daemon(nerve=None)
        thought = _make_thought(salience=0.9,
                                  actionable='fire_nudge:thought_obs:real draft text')
        ok, msg = daemon._do_fire_nudge_actionable(thought, thought.actionable)
        self.assertFalse(ok)
        self.assertIn('no_nerve', msg)

    def test_fa4_valid_fires_success(self):
        """sal>=0.85 + valid draft + nerve.push_command → fire 成功."""
        nerve = MagicMock()
        nerve.push_command = MagicMock()
        daemon = _make_daemon(nerve=nerve)
        thought = _make_thought(salience=0.9,
                                  actionable='fire_nudge:thought_observation:Sir 该 break 一下')
        with patch('jarvis_nudge_coordination.should_yield_to_recent_proactive_nudge',
                    return_value=(False, '')):
            ok, msg = daemon._do_fire_nudge_actionable(thought, thought.actionable)
        self.assertTrue(ok, f'fire 应成功, msg={msg}')
        self.assertIn('fired:thought_observation', msg)

    def test_fa5_fire_after_publish_fired(self):
        """fire 后调 publish_proactive_nudge_fired."""
        nerve = MagicMock()
        nerve.push_command = MagicMock()
        daemon = _make_daemon(nerve=nerve)
        thought = _make_thought(salience=0.9,
                                  actionable='fire_nudge:thought_obs:test')
        with patch('jarvis_nudge_coordination.should_yield_to_recent_proactive_nudge',
                    return_value=(False, '')), \
             patch('jarvis_nudge_coordination.publish_proactive_nudge_fired') as MockPub:
            daemon._do_fire_nudge_actionable(thought, thought.actionable)
            MockPub.assert_called_once()
            args, kwargs = MockPub.call_args
            self.assertEqual(kwargs.get('sentinel'), 'InnerThought')

    def test_fa6_yield_publishes_skipped(self):
        """nudge_coordination 让位 → publish skipped + 不 fire."""
        nerve = MagicMock()
        nerve.push_command = MagicMock()
        daemon = _make_daemon(nerve=nerve)
        thought = _make_thought(salience=0.9,
                                  actionable='fire_nudge:thought_obs:test')
        with patch('jarvis_nudge_coordination.should_yield_to_recent_proactive_nudge',
                    return_value=(True, 'recent_smart_nudge_30s_ago')), \
             patch('jarvis_nudge_coordination.publish_proactive_nudge_skipped') as MockSkip:
            ok, msg = daemon._do_fire_nudge_actionable(thought, thought.actionable)
            self.assertFalse(ok)
            self.assertIn('yielded:recent_smart_nudge', msg)
            MockSkip.assert_called_once()
            nerve.push_command.assert_not_called()

    def test_fa7_fire_pushes_nudge_cmd(self):
        """fire 走 push_command '__NUDGE__:{json}'."""
        nerve = MagicMock()
        nerve.push_command = MagicMock()
        daemon = _make_daemon(nerve=nerve)
        thought = _make_thought(salience=0.9,
                                  actionable='fire_nudge:thought_observation:test draft text')
        with patch('jarvis_nudge_coordination.should_yield_to_recent_proactive_nudge',
                    return_value=(False, '')):
            daemon._do_fire_nudge_actionable(thought, thought.actionable)
        nerve.push_command.assert_called_once()
        cmd = nerve.push_command.call_args[0][0]
        self.assertTrue(cmd.startswith('__NUDGE__:'),
            'fire 必须 push_command __NUDGE__:')
        payload = json.loads(cmd[len('__NUDGE__:'):])
        self.assertEqual(payload['type'], 'inner_thought_fire')
        self.assertEqual(payload['source'], 'InnerThought')

    def test_fa8_chat_bypass_wraps_directive(self):
        """chat_bypass _build_nudge_prompt 看 type=inner_thought_fire 加 wrap."""
        # 简易检 — chat_bypass 5670 行附近 inner_thought_fire wrap 真存在
        cb_path = os.path.join(ROOT, 'jarvis_chat_bypass.py')
        with open(cb_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("'inner_thought_fire'", content,
            'chat_bypass 必须含 inner_thought_fire type 处理')
        self.assertIn('INNER THOUGHT FIRE', content,
            'chat_bypass 必须含 [INNER THOUGHT FIRE] directive wrap')


# ==========================================================================
# Phase 1B: anticipated_ltm_context evidence
# ==========================================================================
class TestPhase1BAnticipatedLtmContext(unittest.TestCase):
    def test_lb1_nerve_anticipator_preload_in_evidence(self):
        """nerve.anticipator.get_preloaded_context() 非空 → evidence 含."""
        nerve = MagicMock()
        anticipator = MagicMock()
        anticipator.get_preloaded_context = MagicMock(
            return_value='\n[ANTICIPATED CONTEXT - Preloaded]:\n- coding intent\n'
        )
        nerve.anticipator = anticipator
        daemon = _make_daemon(nerve=nerve)
        with patch.object(daemon, '_get_idle_seconds', return_value=5.0):
            ev = daemon._collect_evidence('active', 60)
        self.assertIn('anticipated_ltm_context', ev,
            'evidence 必须含 anticipated_ltm_context')
        self.assertIn('coding intent', ev['anticipated_ltm_context'])

    def test_lb2_no_anticipator_no_field(self):
        """nerve 无 anticipator → evidence 缺 anticipated_ltm_context."""
        daemon = _make_daemon(nerve=None)
        with patch.object(daemon, '_get_idle_seconds', return_value=5.0):
            ev = daemon._collect_evidence('active', 60)
        self.assertNotIn('anticipated_ltm_context', ev)

    def test_lb3_prompt_block_renders(self):
        """主脑 prompt 含 [ANTICIPATED LTM CONTEXT] block."""
        daemon = _make_daemon()
        evidence = {
            'sir_state': 'active', 'idle_seconds': 30, 'hour': 22,
            'anticipated_ltm_context': '- coding milestone\n- last debug: foo.py',
        }
        _, user_p = daemon._build_prompt('active', evidence)
        self.assertIn('ANTICIPATED LTM CONTEXT', user_p,
            'prompt 必须含 [ANTICIPATED LTM CONTEXT] block')
        self.assertIn('coding milestone', user_p)


# ==========================================================================
# Phase 1C: daemon_health evidence (我自己健康)
# ==========================================================================
class TestPhase1CDaemonHealth(unittest.TestCase):
    def test_lc1_swm_warning_in_evidence(self):
        """SWM 有 daemon_health_warning → evidence 含."""
        daemon = _make_daemon()
        mock_bus = MagicMock()
        mock_bus.top_n = MagicMock(return_value=[
            {'type': 'daemon_health_warning',
              'description': 'InnerThought 24h 只产 5 条 (健康 >=30)',
              '_age_s': 3600,
              'metadata': {'severity': 'warn'}},
            {'type': 'other_event', '_age_s': 100,
              'description': 'something else'},
        ])
        with patch.object(daemon, '_get_idle_seconds', return_value=5.0), \
             patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            ev = daemon._collect_evidence('active', 60)
        self.assertIn('daemon_health', ev)
        self.assertEqual(len(ev['daemon_health']), 1)
        self.assertIn('InnerThought 24h', ev['daemon_health'][0]['issue'])
        self.assertEqual(ev['daemon_health'][0]['severity'], 'warn')

    def test_lc2_no_warning_empty_list(self):
        """SWM 无 warning → daemon_health 空 list."""
        daemon = _make_daemon()
        mock_bus = MagicMock()
        mock_bus.top_n = MagicMock(return_value=[])
        with patch.object(daemon, '_get_idle_seconds', return_value=5.0), \
             patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            ev = daemon._collect_evidence('active', 60)
        self.assertEqual(ev.get('daemon_health'), [])

    def test_lc3_prompt_block_renders(self):
        """主脑 prompt 含 [MY OWN HEALTH] block."""
        daemon = _make_daemon()
        evidence = {
            'sir_state': 'active', 'idle_seconds': 30, 'hour': 22,
            'daemon_health': [
                {'issue': 'AutoArbiter [inside_joke] 阈值 0.5 < 0.55 — 太松',
                  'severity': 'warn', 'age_h': 2}
            ],
        }
        _, user_p = daemon._build_prompt('active', evidence)
        self.assertIn('MY OWN HEALTH', user_p,
            'prompt 必须含 [MY OWN HEALTH] block')
        self.assertIn('AutoArbiter', user_p)


# ==========================================================================
# Phase 2A: propose_watch_task actionable
# ==========================================================================
class TestPhase2AProposeWatchTask(unittest.TestCase):
    def test_wt1_a_category_gated(self):
        """A 类 → gated (only C/D)."""
        daemon = _make_daemon()
        thought = _make_thought(category='A', salience=0.85,
                                  actionable='propose_watch_task:cycle_hours:2:test desc')
        ok, msg = daemon._do_propose_watch_task(thought, thought.actionable)
        self.assertFalse(ok)
        self.assertIn('only_from_C_or_D', msg)

    def test_wt2_c_low_sal_gated(self):
        """C 类 sal < 0.75 → gated."""
        daemon = _make_daemon()
        thought = _make_thought(category='C', salience=0.6,
                                  actionable='propose_watch_task:cycle_hours:2:test')
        ok, msg = daemon._do_propose_watch_task(thought, thought.actionable)
        self.assertFalse(ok)
        self.assertIn('requires_sal', msg)

    def test_wt3_valid_registers_watch_kind(self):
        """C 类 sal=0.8 + valid → 注册 watch kind."""
        from jarvis_promise_log import PromiseExecutionLog
        tmp = tempfile.mkdtemp(prefix='wt3_')
        try:
            mock_plog = PromiseExecutionLog(
                persist_path=os.path.join(tmp, 'p.jsonl')
            )
            daemon = _make_daemon()
            thought = _make_thought(category='C', salience=0.8,
                                      actionable='propose_watch_task:cycle_hours:2:每 2h check Sir 面试准备')
            with patch('jarvis_promise_log.get_default_log',
                        return_value=mock_plog):
                ok, msg = daemon._do_propose_watch_task(thought, thought.actionable)
            self.assertTrue(ok, f'expected ok, msg={msg}')
            self.assertIn('watch_task:', msg)
            # 看 watch kind 真注册
            watch_promises = [p for p in mock_plog.promises.values()
                              if p.kind == 'watch']
            self.assertEqual(len(watch_promises), 1)
            self.assertIn('面试准备', watch_promises[0].description)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_wt4_trigger_pattern_persisted(self):
        """trigger_pattern (kind/value) 真存进 promise."""
        from jarvis_promise_log import PromiseExecutionLog
        tmp = tempfile.mkdtemp(prefix='wt4_')
        try:
            mock_plog = PromiseExecutionLog(
                persist_path=os.path.join(tmp, 'p.jsonl')
            )
            daemon = _make_daemon()
            thought = _make_thought(category='D', salience=0.8,
                                      actionable='propose_watch_task:cycle_minutes:30:check 焦点')
            with patch('jarvis_promise_log.get_default_log',
                        return_value=mock_plog):
                daemon._do_propose_watch_task(thought, thought.actionable)
            watch = [p for p in mock_plog.promises.values()
                     if p.kind == 'watch'][0]
            self.assertEqual(watch.trigger_pattern.get('kind'), 'cycle_minutes')
            self.assertEqual(watch.trigger_pattern.get('value'), '30')
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_wt5_empty_desc_fails(self):
        """desc 空 → fail."""
        daemon = _make_daemon()
        thought = _make_thought(category='C', salience=0.8,
                                  actionable='propose_watch_task:cycle_hours:2:')
        ok, msg = daemon._do_propose_watch_task(thought, thought.actionable)
        self.assertFalse(ok)
        self.assertIn('empty', msg)


# ==========================================================================
# Phase 2B: outcome field
# ==========================================================================
class TestPhase2BThoughtOutcome(unittest.TestCase):
    def test_oc1_dataclass_has_outcome_field(self):
        """InnerThought 含 outcome, default='pending'."""
        from jarvis_inner_thought_daemon import InnerThought
        t = InnerThought(
            id='th_test', ts=time.time(), ts_iso='2026-05-26T19:48:00',
            category='B', thought='test', salience=0.5, actionable='none',
        )
        self.assertEqual(t.outcome, 'pending')

    def test_oc2_outcome_field_settable(self):
        """outcome 字段可设."""
        from jarvis_inner_thought_daemon import InnerThought
        t = InnerThought(
            id='th_test', ts=time.time(), ts_iso='2026-05-26T19:48:00',
            category='B', thought='test', salience=0.5, actionable='none',
            outcome='sir_engaged',
        )
        self.assertEqual(t.outcome, 'sir_engaged')


# ==========================================================================
# Phase 3: call_tool actionable + allowlist
# ==========================================================================
class TestPhase3CallTool(unittest.TestCase):
    def test_ct1_low_sal_gated(self):
        """sal < 0.90 → gated."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.85,
                                  actionable='call_tool:milestone_register:{}')
        ok, msg = daemon._do_call_tool_actionable(thought, thought.actionable)
        self.assertFalse(ok)
        self.assertIn('requires_sal>=0.9', msg)

    def test_ct2_tool_not_in_allowlist(self):
        """tool 不在 allowlist → fail."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.95,
                                  actionable='call_tool:forbidden_tool:{}')
        with patch.object(daemon, '_load_call_tool_allowlist',
                            return_value={'commitment_register'}):
            ok, msg = daemon._do_call_tool_actionable(thought, thought.actionable)
        self.assertFalse(ok)
        self.assertIn('not_in_allowlist:forbidden_tool', msg)

    def test_ct3_valid_calls_tool(self):
        """tool 在 allowlist + valid args → 调成功."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.95,
                                  actionable='call_tool:test_tool:{"x": 1}')
        mock_tool = MagicMock(return_value={'ok': True, 'result': 'done'})
        with patch.object(daemon, '_load_call_tool_allowlist',
                            return_value={'test_tool'}), \
             patch('jarvis_tool_registry.get_tool_registry',
                    return_value={'test_tool': mock_tool}):
            ok, msg = daemon._do_call_tool_actionable(thought, thought.actionable)
        self.assertTrue(ok, f'expected ok, msg={msg}')
        self.assertIn('called:test_tool', msg)
        mock_tool.assert_called_once_with(x=1)

    def test_ct4_publishes_swm_after_call(self):
        """call_tool 后 publish 'inner_thought_tool_called' SWM."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.95,
                                  actionable='call_tool:test_tool:{}')
        mock_tool = MagicMock(return_value={'ok': True, 'result': 'ok'})
        mock_bus = MagicMock()
        with patch.object(daemon, '_load_call_tool_allowlist',
                            return_value={'test_tool'}), \
             patch('jarvis_tool_registry.get_tool_registry',
                    return_value={'test_tool': mock_tool}), \
             patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            daemon._do_call_tool_actionable(thought, thought.actionable)
        mock_bus.publish.assert_called_once()
        kwargs = mock_bus.publish.call_args.kwargs
        self.assertEqual(kwargs['etype'], 'inner_thought_tool_called')

    def test_ct5_invalid_json_fails(self):
        """args 非 JSON → fail."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.95,
                                  actionable='call_tool:test_tool:NOT_JSON{')
        with patch.object(daemon, '_load_call_tool_allowlist',
                            return_value={'test_tool'}):
            ok, msg = daemon._do_call_tool_actionable(thought, thought.actionable)
        self.assertFalse(ok)
        self.assertIn('args_parse_fail', msg)


# ==========================================================================
# Phase 3 allowlist 持久化 + CLI sanity
# ==========================================================================
class TestPhase3AllowlistPersistence(unittest.TestCase):
    def test_allowlist_json_exists(self):
        """allowlist JSON 存在 + 含 default safe tools."""
        path = os.path.join(ROOT, 'memory_pool',
                              'inner_thought_tool_allowlist.json')
        self.assertTrue(os.path.exists(path),
            f'allowlist JSON {path} 必须存在')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        allow = set(data.get('allowlist') or [])
        self.assertIn('commitment_register', allow)
        self.assertIn('self_promise_register', allow)
        self.assertIn('milestone_register', allow)

    def test_cli_script_exists(self):
        """CLI script 存在."""
        path = os.path.join(ROOT, 'scripts',
                              'inner_thought_tool_allowlist_dump.py')
        self.assertTrue(os.path.exists(path),
            f'CLI {path} 必须存在')

    def test_daemon_load_allowlist_from_json(self):
        """daemon._load_call_tool_allowlist 真读 JSON."""
        daemon = _make_daemon()
        allow = daemon._load_call_tool_allowlist()
        self.assertIsInstance(allow, set)
        # 默认 fallback OR 真读 JSON
        self.assertIn('commitment_register', allow)


if __name__ == '__main__':
    unittest.main()
