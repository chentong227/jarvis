# -*- coding: utf-8 -*-
"""[P5-fix39 / 2026-05-23 12:18] build_integrity_alert staleness filter.

Sir 12:08 真测 audit 发现:
  Sir 重启 Jarvis 后, 每 turn 都看到 '🛑 [INTEGRITY/Alert skip] unverified=279c'
  同长度反复出现.

Audit jsonl 内容:
  Total 31 lines, 最新 unverified turn: 11:05:15 turn_20260523_110507_b53c
  ([count] 90 minutes, [past_action] 'I set').
  
  Sir 12:08 后每 turn 都被这个 1 小时前的 stale claim 反复 inject.

根因:
  build_integrity_alert 读 audit jsonl 尾 20 行, 按 ts 排选 latest_turn.
  但**没 staleness threshold** → N 小时前的 stale unverified 仍被选为 'latest'.

治本:
  加 max_age_s 参数默认 600s (10min). claim ts < now - max_age_s → 过滤掉
  (太老 = stale, 主脑别被强迫 ack).

覆盖:
A. fresh claim (ts < max_age) 仍 inject ✅
B. stale claim (ts > max_age) 不 inject ✅
C. mixed (fresh + stale) 仅 fresh inject
D. all stale → 空字符串
E. max_age_s 参数可调
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestStalenessFilter(unittest.TestCase):

    def _make_audit(self, entries):
        """Create temp audit jsonl with given entries."""
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.jsonl', delete=False, encoding='utf-8')
        for e in entries:
            tmp.write(json.dumps(e, ensure_ascii=False) + '\n')
        tmp.close()
        return tmp.name

    def test_a_fresh_claim_injected(self):
        from jarvis_claim_tracer import build_integrity_alert
        now = time.time()
        path = self._make_audit([
            {'turn_id': 'turn_fresh_001', 'ts': now - 60.0,
             'claim': '95%', 'kind': 'percent', 'found': False},
        ])
        try:
            alert = build_integrity_alert(audit_path=path)
            self.assertIn('INTEGRITY ALERT', alert,
                            'fresh claim (60s ago) 应 inject')
            self.assertIn('95%', alert)
            self.assertIn('turn_fresh_001', alert)
        finally:
            os.remove(path)

    def test_b_stale_claim_filtered(self):
        from jarvis_claim_tracer import build_integrity_alert
        now = time.time()
        path = self._make_audit([
            {'turn_id': 'turn_stale_001', 'ts': now - 7200.0,  # 2h ago
             'claim': '95%', 'kind': 'percent', 'found': False},
        ])
        try:
            alert = build_integrity_alert(audit_path=path)
            self.assertEqual(alert, '',
                                f'stale claim (2h ago) 不应 inject. got: {alert!r}')
        finally:
            os.remove(path)

    def test_c_mixed_only_fresh_inject(self):
        from jarvis_claim_tracer import build_integrity_alert
        now = time.time()
        path = self._make_audit([
            # stale 90 minutes ago
            {'turn_id': 'turn_stale_001', 'ts': now - 5400.0,
             'claim': '90%', 'kind': 'percent', 'found': False},
            # stale 30 min ago
            {'turn_id': 'turn_stale_002', 'ts': now - 1800.0,
             'claim': '99%', 'kind': 'percent', 'found': False},
            # fresh 30s ago
            {'turn_id': 'turn_fresh_003', 'ts': now - 30.0,
             'claim': '50%', 'kind': 'percent', 'found': False},
        ])
        try:
            alert = build_integrity_alert(audit_path=path)
            self.assertIn('turn_fresh_003', alert)
            self.assertIn('50%', alert)
            self.assertNotIn('90%', alert,
                              'stale 90% 不应 inject')
            self.assertNotIn('99%', alert,
                              'stale 99% 不应 inject')
        finally:
            os.remove(path)

    def test_d_all_stale_no_alert(self):
        from jarvis_claim_tracer import build_integrity_alert
        now = time.time()
        path = self._make_audit([
            {'turn_id': 'turn_old_a', 'ts': now - 3600.0,
             'claim': '4%', 'kind': 'percent', 'found': False},
            {'turn_id': 'turn_old_b', 'ts': now - 1200.0,
             'claim': '0.01%', 'kind': 'percent', 'found': False},
        ])
        try:
            alert = build_integrity_alert(audit_path=path, max_age_s=600.0)
            self.assertEqual(alert, '',
                                'all stale → empty alert')
        finally:
            os.remove(path)

    def test_e_max_age_param_tunable(self):
        from jarvis_claim_tracer import build_integrity_alert
        now = time.time()
        path = self._make_audit([
            {'turn_id': 'turn_30min', 'ts': now - 1800.0,
             'claim': '50%', 'kind': 'percent', 'found': False},
        ])
        try:
            # default 600s → stale, no inject
            alert_default = build_integrity_alert(audit_path=path)
            self.assertEqual(alert_default, '')
            # tuned 7200s (2h) → fresh, inject
            alert_tuned = build_integrity_alert(
                audit_path=path, max_age_s=7200.0)
            self.assertIn('50%', alert_tuned)
        finally:
            os.remove(path)


if __name__ == '__main__':
    unittest.main()
