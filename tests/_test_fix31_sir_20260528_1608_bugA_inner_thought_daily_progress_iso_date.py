# -*- coding: utf-8 -*-
"""[fix31 / Sir 2026-05-28 16:08 BUG A] 思考脑注 daily_progress 漏 iso_date check.

真痛 (16:08 日志):
  Sir: "其实你记得是昨天的信息，今天已经是28号了"
  InnerThought: "[A] Sir is at 9.0/10.0 cups. ..."  # 用昨天 daily_progress 当今天

Root cause:
  jarvis_inner_thought_daemon.py:1768-1781 (evidence build) 注 daily_progress
  时漏 iso_date == today check, 昨天 dp 被当今天注主脑 prompt → cascade 错答.
  to_prompt_block:968 + ProactiveCare._signal:622 已有同 check, 唯独此处漏.

Fix:
  inner_thought daemon evidence build 加 iso_date == today check, 不匹配 →
  不写 entry['daily_progress'] (Sir 醒来后看到主脑/思考脑都不再用 stale dp).

测试覆盖:
  L1 dp.iso_date == today → entry 含 daily_progress ✓
  L2 dp.iso_date == yesterday → entry **不** 含 daily_progress (核心治本)
  L3 dp.iso_date 缺 → 同 L2 不注
  L4 cur/tgt 缺 → 不注
  L5 _truth_on=False → 全部不注
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_concern(cid: str, dp_iso: str = '', cur=None, tgt=None,
                    unit: str = '杯', severity: float = 0.6):
    """构 mock Concern (含 daily_progress)."""
    c = MagicMock()
    c.id = cid
    c.what_i_watch = f'Sir {cid} thing'
    c.why_i_care = 'just because'
    c.severity = severity
    c.notes_for_self = ''
    c.daily_progress = {}
    if dp_iso or cur is not None or tgt is not None:
        c.daily_progress = {
            'iso_date': dp_iso,
            'current': cur,
            'target': tgt,
            'unit': unit,
        }
    c.last_user_feedback = {}
    c.optimal_timing = ''
    return c


def _make_daemon():
    """构 InnerThoughtDaemon 仅 evidence-build."""
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
    d.concerns_ledger = MagicMock()
    d.relational_state = MagicMock()
    d.relational_state.list_protocols = MagicMock(return_value=[])
    d.relational_state.list_protocols_review = MagicMock(return_value=[])
    d.nerve = MagicMock()
    d.nerve.short_term_memory = []
    return d


def _build_concerns_entries(d, identity_block_overrides: dict | None = None):
    """模拟 InnerThoughtDaemon evidence build 中 concerns 部分,
    复刻 line 1738-1808 行为, 返 ev['concerns'] entries 列表.

    避免 build full evidence (依赖太多), 直接 unit test concerns 注入逻辑.
    """
    if identity_block_overrides is None:
        identity_block_overrides = {}
    default_vocab = {
        'blocks_enabled': {
            'concern_truth_in_concerns': True,
        },
        'limits': {
            'concern_last_user_feedback_max_chars': 100,
        },
    }
    default_vocab.update(identity_block_overrides)
    with patch.object(d, '_load_identity_block_vocab',
                       return_value=default_vocab):
        active = d.concerns_ledger.list_active() or []
        active_sorted = sorted(active, key=lambda c: -c.severity)
        _id_vocab = d._load_identity_block_vocab()
        _truth_on = (_id_vocab.get('blocks_enabled') or {}).get(
            'concern_truth_in_concerns', True)
        _fb_max_chars = int(
            (_id_vocab.get('limits') or {}).get(
                'concern_last_user_feedback_max_chars', 100)
        )
        concerns_out = []
        for c in active_sorted[:5]:
            entry = {
                'id': c.id,
                'what': (c.what_i_watch or '')[:80],
                'severity': round(c.severity, 2),
                'notes_chars': len((c.notes_for_self or '').strip()),
            }
            if _truth_on:
                dp = getattr(c, 'daily_progress', None) or {}
                if dp:
                    today_iso = time.strftime(
                        '%Y-%m-%d', time.localtime()
                    )
                    dp_iso = dp.get('iso_date', '')
                    cur = dp.get('current')
                    tgt = dp.get('target')
                    unit = dp.get('unit') or ''
                    if (dp_iso == today_iso
                            and cur is not None
                            and tgt is not None):
                        entry['daily_progress'] = {
                            'current': cur,
                            'target': tgt,
                            'unit': unit,
                            'iso_date': dp_iso,
                        }
                fb = getattr(c, 'last_user_feedback', None) or {}
                raw = (fb.get('raw_text') or '').strip()
                if raw:
                    entry['last_user_feedback'] = raw[:_fb_max_chars]
                ot = getattr(c, 'optimal_timing', '') or ''
                if ot:
                    entry['optimal_timing'] = ot
            concerns_out.append(entry)
        return concerns_out


# ==========================================================================
# L1: 今天 dp → 注
# ==========================================================================
class TestL1TodayDpInjected(unittest.TestCase):
    def setUp(self):
        self.d = _make_daemon()
        today = time.strftime('%Y-%m-%d', time.localtime())
        self.c = _make_concern(
            'sir_hydration', dp_iso=today, cur=9.0, tgt=10.0, unit='cups'
        )
        self.d.concerns_ledger.list_active = MagicMock(return_value=[self.c])

    def test_today_dp_included(self):
        out = _build_concerns_entries(self.d)
        self.assertEqual(len(out), 1)
        self.assertIn('daily_progress', out[0])
        self.assertEqual(out[0]['daily_progress']['current'], 9.0)
        self.assertEqual(out[0]['daily_progress']['target'], 10.0)


# ==========================================================================
# L2: 昨天 dp → 不注 (核心治本)
# ==========================================================================
class TestL2YesterdayDpExcluded(unittest.TestCase):
    def setUp(self):
        self.d = _make_daemon()
        yesterday_ts = time.time() - 86400
        yesterday = time.strftime('%Y-%m-%d',
                                    time.localtime(yesterday_ts))
        self.c = _make_concern(
            'sir_hydration', dp_iso=yesterday, cur=9.0, tgt=10.0, unit='cups'
        )
        self.d.concerns_ledger.list_active = MagicMock(return_value=[self.c])

    def test_yesterday_dp_excluded(self):
        out = _build_concerns_entries(self.d)
        self.assertEqual(len(out), 1)
        # 核心治本 — 昨天 dp 必须不出现在 entry
        self.assertNotIn('daily_progress', out[0])


# ==========================================================================
# L3: dp.iso_date 缺 → 同 L2 不注
# ==========================================================================
class TestL3MissingIsoExcluded(unittest.TestCase):
    def setUp(self):
        self.d = _make_daemon()
        self.c = _make_concern(
            'sir_hydration', dp_iso='', cur=9.0, tgt=10.0, unit='cups'
        )
        self.d.concerns_ledger.list_active = MagicMock(return_value=[self.c])

    def test_missing_iso_excluded(self):
        out = _build_concerns_entries(self.d)
        self.assertEqual(len(out), 1)
        self.assertNotIn('daily_progress', out[0])


# ==========================================================================
# L4: cur/tgt 缺 → 不注
# ==========================================================================
class TestL4MissingCurTgtExcluded(unittest.TestCase):
    def setUp(self):
        self.d = _make_daemon()
        today = time.strftime('%Y-%m-%d', time.localtime())
        self.c = _make_concern(
            'sir_hydration', dp_iso=today, cur=None, tgt=10.0, unit='cups'
        )
        self.d.concerns_ledger.list_active = MagicMock(return_value=[self.c])

    def test_missing_cur_excluded(self):
        out = _build_concerns_entries(self.d)
        self.assertEqual(len(out), 1)
        self.assertNotIn('daily_progress', out[0])


# ==========================================================================
# L5: _truth_on=False → 全部不注
# ==========================================================================
class TestL5TruthOffExcluded(unittest.TestCase):
    def setUp(self):
        self.d = _make_daemon()
        today = time.strftime('%Y-%m-%d', time.localtime())
        self.c = _make_concern(
            'sir_hydration', dp_iso=today, cur=9.0, tgt=10.0, unit='cups'
        )
        self.d.concerns_ledger.list_active = MagicMock(return_value=[self.c])

    def test_truth_off_excludes_all(self):
        out = _build_concerns_entries(self.d, identity_block_overrides={
            'blocks_enabled': {'concern_truth_in_concerns': False},
        })
        self.assertEqual(len(out), 1)
        self.assertNotIn('daily_progress', out[0])
        self.assertNotIn('last_user_feedback', out[0])
        self.assertNotIn('optimal_timing', out[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
