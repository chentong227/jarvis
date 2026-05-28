# -*- coding: utf-8 -*-
"""[Sir 2026-05-28 16:55 方案 B 治本] InnerThought propose 质量反馈环

Sir 真痛 (dashboard 7-8 页 139 review 待办):
  "AutoArbiter 怎么会让 review 待办堆这么多?
   我担心他没有正确的反思评估自己 propose 的质量."

真因: AutoArbiter defer_to_sir 是被动等 — 它接 InnerThought 推过来的
propose, 但 InnerThought 不知道自己 propose 的质量低 (sal=0.4 也 fire).
17h propose 60+ inside_joke + 70+ protocol, 多数 sal 低品质 →
AutoArbiter 不敢自决 → 全 defer_to_sir → review 堆积.

治本 (方案 B): InnerThoughtDaemon 加自适应 propose quality gate —
  - 24h 周期看 auto_arbiter_log activate_rate
  - rate >= 70% → 降阈 (放松, 阈值 -0.02)
  - rate <= 30% → 升阈 (收紧, 阈值 +0.05)
  - 阈值 [floor=0.40, ceiling=0.85], 阶梯 calibrate
  - propose 类 actionable (suggest_inside_joke:/propose_protocol:)
    salience < threshold → gate (actionable 降级 none, thought 仍 persist)
  - 准则 6 vocab 持久化: memory_pool/inner_thought_propose_quality_vocab.json
  - 准则 6 CLI: scripts/propose_quality_dump.py (list/enable/disable/
    set-threshold/set-cooldown/calibrate-now/history)

Cover:
  A. propose 类 sal < threshold → gate (True)
  B. propose 类 sal >= threshold → 不 gate (False)
  C. 非 propose 类 (update_concern_severity:) → 不 gate (绕过)
  D. enabled=0 → 不 gate (Sir 总开关 OFF)
  E. marker 在源码
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_inner_thought_daemon import InnerThoughtDaemon, InnerThought


def _make_thought(actionable: str, sal: float) -> InnerThought:
    return InnerThought(
        id=f'test_t_{actionable[:10]}_{sal}',
        ts=time.time(),
        ts_iso='2026-05-28T16:55:00',
        category='E',
        thought='test thought',
        salience=sal,
        actionable=actionable,
    )


def _make_daemon_with_vocab(vocab: dict, tmp_dir: str) -> InnerThoughtDaemon:
    """构造 daemon 实例 + monkey-patch vocab 路径到 tmp dir (隔离 memory_pool)."""
    vocab_path = os.path.join(tmp_dir, 'inner_thought_propose_quality_vocab.json')
    with open(vocab_path, 'w', encoding='utf-8') as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)
    # 实例化时 skip IO heavy ops
    with patch.object(InnerThoughtDaemon, '_load_persist', lambda self: None), \
         patch.object(InnerThoughtDaemon, '_append_cold_start_record',
                       lambda self: None):
        daemon = InnerThoughtDaemon(key_router=MagicMock())
    # patch vocab path + invalidate cache (instance attr, 不影响其他 test)
    daemon._PROPOSE_QUALITY_VOCAB_PATH = vocab_path
    daemon._PROPOSE_QUALITY_VOCAB_CACHE = {
        'data': None, 'mtime': 0.0, 'checked_at': 0.0,
    }
    return daemon


class TestA_ProposeBelowThresholdGated(unittest.TestCase):
    def test_propose_low_sal_gated(self):
        """propose 类 sal < threshold → gate (True)."""
        with tempfile.TemporaryDirectory(prefix='fix38_A_') as tmp:
            daemon = _make_daemon_with_vocab({
                'enabled': True, 'sal_threshold': 0.60,
                'gated_actionable_prefixes': [
                    'suggest_inside_joke:', 'propose_protocol:',
                ],
            }, tmp)
            t = _make_thought('suggest_inside_joke:foo', sal=0.40)
            gated, reason = daemon._should_gate_propose(t)
            self.assertTrue(gated, msg=f'sal=0.40 < 0.60 应 gate, reason={reason}')
            self.assertIn('sal=', reason)


class TestB_ProposeAboveThresholdPassed(unittest.TestCase):
    def test_propose_high_sal_not_gated(self):
        """propose 类 sal >= threshold → 不 gate."""
        with tempfile.TemporaryDirectory(prefix='fix38_B_') as tmp:
            daemon = _make_daemon_with_vocab({
                'enabled': True, 'sal_threshold': 0.60,
                'gated_actionable_prefixes': [
                    'suggest_inside_joke:', 'propose_protocol:',
                ],
            }, tmp)
            t = _make_thought('suggest_inside_joke:foo', sal=0.80)
            gated, reason = daemon._should_gate_propose(t)
            self.assertFalse(gated, msg=f'sal=0.80 >= 0.60 应 pass, reason={reason}')


class TestC_NonProposeBypassed(unittest.TestCase):
    def test_non_propose_actionable_bypassed(self):
        """非 propose 类 (update_concern_severity:) → 不 gate (绕过)."""
        with tempfile.TemporaryDirectory(prefix='fix38_C_') as tmp:
            daemon = _make_daemon_with_vocab({
                'enabled': True, 'sal_threshold': 0.60,
                'gated_actionable_prefixes': [
                    'suggest_inside_joke:', 'propose_protocol:',
                ],
            }, tmp)
            t = _make_thought('update_concern_severity:foo:5', sal=0.30)
            gated, reason = daemon._should_gate_propose(t)
            self.assertFalse(gated,
                              msg='非 propose actionable 应 bypass gate')


class TestD_DisabledSwitchHonored(unittest.TestCase):
    def test_enabled_zero_no_gate(self):
        """enabled=0 → 不 gate (Sir 总开关 OFF)."""
        with tempfile.TemporaryDirectory(prefix='fix38_D_') as tmp:
            daemon = _make_daemon_with_vocab({
                'enabled': False, 'sal_threshold': 0.60,
                'gated_actionable_prefixes': [
                    'suggest_inside_joke:', 'propose_protocol:',
                ],
            }, tmp)
            t = _make_thought('suggest_inside_joke:foo', sal=0.10)
            gated, reason = daemon._should_gate_propose(t)
            self.assertFalse(gated, msg='enabled=0 应 bypass gate')


class TestE_MarkerPresent(unittest.TestCase):
    def test_marker_in_source(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'jarvis_inner_thought_daemon.py',
        )
        src = open(path, 'r', encoding='utf-8').read()
        self.assertIn('_should_gate_propose', src,
                       msg='方案 B: _should_gate_propose 应在源码')
        self.assertIn('_maybe_calibrate_propose_quality', src,
                       msg='方案 B: _maybe_calibrate_propose_quality 应在源码')
        self.assertIn('inner_thought_propose_quality_vocab.json', src,
                       msg='方案 B: vocab JSON 路径应在源码')
        self.assertIn('Sir 2026-05-28 16:55', src,
                       msg='方案 B: Sir marker 应在源码')

    def test_cli_dump_exists(self):
        cli = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'propose_quality_dump.py',
        )
        self.assertTrue(os.path.exists(cli),
                        msg='方案 B 准则 6: CLI 必须存在')


if __name__ == '__main__':
    unittest.main()
