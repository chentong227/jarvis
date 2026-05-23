# -*- coding: utf-8 -*-
"""[β.5.46-fix12 / 2026-05-22 00:20] IntegrityWatcher Alert inject gating verify.

Sir 真测 3 次连续 unsolicited apology callback (22:13/00:13/00:18):
  - 主脑回 "regarding my previous mention of '0.01%' I must withdraw..."
  - 真凶: jarvis_central_nerve._assemble_prompt line 1520 build_integrity_alert
    无条件读 audit jsonl 上轮 unverified claim, prepend 到 system_alert_text.
  - prompt 含 [INTEGRITY ALERT] "had N unverified factual claim(s) ...
    either acknowledge and withdraw plainly, or supply the missing evidence"
    → 主脑被字面强迫 → 道歉.

修法: 套 SOUL Concern 同款双门 gating
  (a) Sir 召唤 (concern_summon_vocab keyword 命中)
  (b) 上轮 PreFlight verdict=edit/scrap in last 5 min

Sir 没召唤 + PreFlight 没 fail → publish-only (audit jsonl 仍写, ClaimTracer/
ClaimRevision 仍跟踪, 但不 prepend prompt). 主脑不被强迫翻老账.

Cover:
  A. 静态 check _assemble_prompt 含 gating 三段 (concern_summon / preflight / log)
  B. build_integrity_alert 单测行为不变 (函数本身没改, 只 caller 加 gating)
  C. 默认沉默 marker (gated_silent)
  D. log reason 暴露 (summon / preflight_fail / silent)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_GatingStaticCheck(unittest.TestCase):
    """静态 check _assemble_prompt 含 gating 三段."""

    def setUp(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            self.src = f.read()

    def test_summon_gate_present(self):
        """gating (a): concern_summon vocab 检测."""
        # IntegrityAlert prepend 处必须 import is_summoned (用别名 _is_summoned_ia)
        self.assertIn('_is_summoned_ia', self.src,
                      'IntegrityAlert 处应 import is_summoned (复用 SOUL Concern vocab)')
        self.assertIn('_ia_summoned', self.src,
                      'IntegrityAlert 处应有 _ia_summoned flag')

    def test_preflight_gate_present(self):
        """gating (b): PreFlight verdict=edit/scrap recent 检测."""
        self.assertIn('_ia_preflight_failed', self.src,
                      'IntegrityAlert 处应有 _ia_preflight_failed flag')
        # 复用同款 5min recent_events
        self.assertIn("'preflight_verdict'", self.src,
                      'IntegrityAlert 处应 query SWM preflight_verdict 事件')

    def test_silent_default_skip_log(self):
        """默认沉默 — log 输出 'gated_silent' marker."""
        self.assertIn('gated_silent', self.src,
                      '默认沉默时应 log gated_silent marker (Sir grep 用)')
        self.assertIn('INTEGRITY/Alert skip', self.src,
                      'gated_silent 时应 log skip 标识')

    def test_inject_log_reason_marker(self):
        """inject 时 log 应含 reason= 标记 (summon / preflight_fail)."""
        self.assertIn('_ia_reason', self.src,
                      'IntegrityAlert reason 标识应 expose')
        self.assertIn('reason={_ia_reason}', self.src,
                      'inject 时 log 应印 reason= 标记')


class TestB_BuildAlertBehaviorUnchanged(unittest.TestCase):
    """build_integrity_alert 函数本身没改 — 行为应一致.

    本组确保 caller 加 gating 不破坏底层 reader.
    """

    def setUp(self):
        # 临时 audit jsonl
        self.tmpdir = tempfile.mkdtemp()
        self.audit_path = os.path.join(self.tmpdir, 'integrity_audit.jsonl')

    def tearDown(self):
        try:
            import shutil
            shutil.rmtree(self.tmpdir, ignore_errors=True)
        except Exception:
            pass

    def _write_entry(self, **kwargs):
        with open(self.audit_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(kwargs, ensure_ascii=False) + '\n')

    def test_empty_audit_returns_empty(self):
        from jarvis_claim_tracer import build_integrity_alert
        alert = build_integrity_alert(audit_path=self.audit_path)
        self.assertEqual(alert, '', '空 audit 应返 empty alert')

    def test_unverified_claim_builds_alert(self):
        from jarvis_claim_tracer import build_integrity_alert
        # 🆕 [P5-fix39] use fresh ts so staleness filter (default 600s) doesn't drop it
        import time as _t_pf39
        self._write_entry(turn_id='turn_test_1', kind='percent',
                            claim='0.01%', found=False, ts=_t_pf39.time() - 60.0)
        alert = build_integrity_alert(audit_path=self.audit_path)
        self.assertIn('INTEGRITY ALERT', alert,
                      '有 unverified claim 应构造 alert')
        self.assertIn('0.01%', alert, 'alert 应含 claim 文本')

    def test_exclude_current_turn(self):
        """defensively 排除当前轮 entry (重试场景)."""
        from jarvis_claim_tracer import build_integrity_alert
        # 🆕 [P5-fix39] use fresh ts (staleness filter)
        import time as _t_pf39
        self._write_entry(turn_id='turn_curr', kind='percent',
                            claim='4%', found=False, ts=_t_pf39.time() - 60.0)
        alert = build_integrity_alert(current_turn_id='turn_curr',
                                       audit_path=self.audit_path)
        self.assertEqual(alert, '',
                          '当前轮的 unverified 应被排除 (避免自环)')

    def test_found_entries_excluded(self):
        """found=True (已 verify) 不应入 alert."""
        from jarvis_claim_tracer import build_integrity_alert
        # 🆕 [P5-fix39] use fresh ts (staleness filter)
        import time as _t_pf39
        self._write_entry(turn_id='turn_test_2', kind='percent',
                            claim='50%', found=True, ts=_t_pf39.time() - 60.0)
        alert = build_integrity_alert(audit_path=self.audit_path)
        self.assertEqual(alert, '',
                          'found=True entry 不应入 alert')


class TestC_PreFlightGateIntegration(unittest.TestCase):
    """integration test — 模拟 SWM publish + recent_events 行为."""

    def test_preflight_verdict_query_pattern(self):
        """gating (b) 复用 SOUL Concern 同款 query — 5 min within + types filter."""
        from jarvis_utils import ConversationEventBus
        bus = ConversationEventBus()
        bus.publish(etype='preflight_verdict',
                    description='turn=t1 verdict=edit',
                    source='ReplyPreFlight',
                    salience=0.7,
                    metadata={'verdict': 'edit'})
        events = bus.recent_events(within_seconds=300.0,
                                     types={'preflight_verdict'})
        verdicts = [(e.get('metadata') or {}).get('verdict') for e in events]
        self.assertIn('edit', verdicts,
                      'recent_events 应能 query 到 preflight verdict=edit')

    def test_no_preflight_event_returns_empty(self):
        """无 PreFlight 事件 → recent_events 返空 → gating (b) 不触发."""
        from jarvis_utils import ConversationEventBus
        bus = ConversationEventBus()
        events = bus.recent_events(within_seconds=300.0,
                                     types={'preflight_verdict'})
        self.assertEqual(len(events), 0,
                          '无 preflight 事件 → recent_events 空')


class TestD_SummonGateIntegration(unittest.TestCase):
    """integration — concern_summon is_summoned 真行为 check."""

    def test_summon_keyword_detected(self):
        from jarvis_concern_summon import is_summoned
        # 至少一条 fallback / 已知 vocab 关键词应命中
        self.assertTrue(is_summoned('any concerns?'),
                          'Sir 召唤 phrase "any concerns" 应被 is_summoned 命中')

    def test_normal_chat_not_summoned(self):
        from jarvis_concern_summon import is_summoned
        # 平常聊天不应被误判为召唤
        self.assertFalse(is_summoned('好的, 马上就睡'),
                           '平常聊天 (无召唤 phrase) 不应被命中')
        self.assertFalse(is_summoned("帮我看着这个导出"),
                           '正常请求 (非 concern 召唤) 不应被命中')


if __name__ == '__main__':
    unittest.main()
