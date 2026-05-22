# -*- coding: utf-8 -*-
"""[β.5.46-fix17 / 2026-05-22] Sir 11:39 真测 BUG — Jarvis withdraw 95% 无中生有道歉

Sir 反馈:
  > "95% 这个事情, 具体多少我没看, 但是确实快满了, 他不算骗人, 为啥道歉呢?"

Root cause (audit jsonl trace):
  - 11:26:13 写了 {"turn_id": "", "claim": "95%", "found": false}  ← 空 turn_id!
  - 11:26 那次因 dismissal 误激活 sleep_mode (fix16 已修), daemon 路径
    TraceContext.clear_turn() 已执行 → ClaimTracer 抓 95% 时 turn_id 已空
  - 11:39:14 build_integrity_alert 按 ts 排选 "上轮", 把空 turn_id 这条算上轮
    → inject prompt "你上轮有 95% claim, 应 withdraw" → Jarvis 主动道歉

Fix (jarvis_claim_tracer.py:build_integrity_alert):
  过滤 turn_id="" entry. 不对应 main turn 的 claim 不 inject ALERT, 避免 Jarvis
  道歉一个 Sir 没要求道歉的事 (估算值 ≠ 撒谎).

Cover:
  A. 空 turn_id audit 不进 ALERT (Sir 实测 case)
  B. 真 turn_id audit 仍触发 ALERT (老路径不破)
  C. 混合 (真 + 空) 时仅算真 turn_id, 空的被过滤
  D. marker 在源码
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _write_audit(path: str, entries: list):
    with open(path, 'w', encoding='utf-8') as f:
        for e in entries:
            f.write(json.dumps(e) + '\n')


class TestA_EmptyTurnIdFiltered(unittest.TestCase):
    """A: 空 turn_id audit 不应触发 ALERT (Sir 11:39 实测 case)."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.jsonl', delete=False, encoding='utf-8')
        self.tmp.close()

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_sir_actual_case_empty_turn_id_not_alert(self):
        """Sir 11:39 实测: 空 turn_id 的 95% audit 不应触发 ALERT."""
        from jarvis_claim_tracer import build_integrity_alert
        _write_audit(self.tmp.name, [
            {
                'ts': time.time() - 60,
                'iso': '2026-05-22T11:26:13',
                'turn_id': '',  # ← Sir 实测 case 的关键
                'claim': '95%',
                'kind': 'percent',
                'evidence_kind': '',
                'found': False,
                'reason': 'no match',
            },
        ])
        alert = build_integrity_alert(
            current_turn_id='turn_20260522_113908_ece9',
            audit_path=self.tmp.name,
        )
        self.assertEqual(alert, '',
                          '空 turn_id audit 不应触发 ALERT (fix17)')

    def test_multiple_empty_turn_id_still_no_alert(self):
        _write_audit(self.tmp.name, [
            {'ts': 1.0, 'turn_id': '', 'claim': 'X', 'kind': 'time', 'found': False},
            {'ts': 2.0, 'turn_id': '', 'claim': 'Y', 'kind': 'percent', 'found': False},
            {'ts': 3.0, 'turn_id': '', 'claim': 'Z', 'kind': 'count', 'found': False},
        ])
        from jarvis_claim_tracer import build_integrity_alert
        alert = build_integrity_alert(
            current_turn_id='turn_curr',
            audit_path=self.tmp.name,
        )
        self.assertEqual(alert, '',
                          '全是空 turn_id 应返 ""')


class TestB_RealTurnIdStillTriggers(unittest.TestCase):
    """B: 真 turn_id audit 仍触发 ALERT — 不破老路径."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.jsonl', delete=False, encoding='utf-8')
        self.tmp.close()

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_real_turn_id_triggers(self):
        from jarvis_claim_tracer import build_integrity_alert
        _write_audit(self.tmp.name, [
            {
                'ts': time.time() - 30,
                'turn_id': 'turn_prior_real',  # ← 真 turn_id
                'claim': '已经发送邮件',
                'kind': 'past_action',
                'found': False,
                'reason': 'no ✓ marker',
            },
        ])
        alert = build_integrity_alert(
            current_turn_id='turn_curr',
            audit_path=self.tmp.name,
        )
        self.assertNotEqual(alert, '',
                             '真 turn_id audit 应触发 ALERT')
        self.assertIn('turn_prior_real', alert,
                       'ALERT 应包含 prior turn id')
        self.assertIn('已经发送邮件', alert)


class TestC_MixedFiltersEmptyKeepsReal(unittest.TestCase):
    """C: 混合 (真 + 空) 时仅算真 turn_id."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.jsonl', delete=False, encoding='utf-8')
        self.tmp.close()

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_real_kept_empty_skipped(self):
        from jarvis_claim_tracer import build_integrity_alert
        now = time.time()
        _write_audit(self.tmp.name, [
            # 空 turn_id, ts 较新 (老 bug 会选这条)
            {'ts': now - 10, 'turn_id': '', 'claim': '95%',
              'kind': 'percent', 'found': False},
            # 真 turn_id, ts 较旧
            {'ts': now - 60, 'turn_id': 'turn_real_old',
              'claim': '20 分钟', 'kind': 'time', 'found': False},
        ])
        alert = build_integrity_alert(
            current_turn_id='turn_curr',
            audit_path=self.tmp.name,
        )
        # 应选真 turn_id (空被过滤)
        self.assertIn('turn_real_old', alert,
                       '应仅算真 turn_id, 空被过滤')
        # 不应含空 turn_id 的 claim
        self.assertNotIn('95%', alert,
                          '空 turn_id 的 95% 不应进 ALERT')


class TestD_Marker(unittest.TestCase):

    def test_marker_in_source(self):
        import jarvis_claim_tracer
        with open(jarvis_claim_tracer.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.46-fix17', src,
                       'fix17 marker 应在 jarvis_claim_tracer 源码')
        self.assertIn("if (e.get('turn_id') or '').strip()", src,
                       'fix17 过滤逻辑应在源码')


if __name__ == '__main__':
    unittest.main()
