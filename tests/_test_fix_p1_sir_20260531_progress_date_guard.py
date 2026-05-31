# -*- coding: utf-8 -*-
"""[P1 / Sir 2026-05-31 16:32 真测] 进度数据跨天守门 — 旧数据不当今天报.

真痛 (16:32 日志, 今天 5-31):
  Sir: "记得我今天喝了多少水吗"
  Jarvis: "9 cups ... 2,700ml"  ← 来自 LTM [2026-05-28] 3 天前旧记录
  InnerThought: "8 of 10 cups today"  ← ledger daily_progress(7.75, iso=2026-05-28) 旧值

Root cause: 今天 daily_progress 空 (今天还没记录) → 系统没说"今天没记录", 而是:
  - 主脑 to_prompt_block: stale 时静默 → 主脑 fallback 捞旧 LTM 当今天
  - 思考脑 :4635 truth 行: 漏 iso_date==today 过滤 → 旧值当今天注

Fix (准则 5 接地 / 准则 6 非硬编码, 通用任何 daily_progress concern):
  - concerns.to_prompt_block: 有 target 但今天没记录 → 显式 "NOT logged yet today" evidence
  - inner_thought :4635: stale → "NO entry logged today; last ... (STALE)"

覆盖 (无 LLM):
  T1 今天 dp → "today progress: X/Y" (老行为保留)
  T2 跨天 stale dp → "NOT logged yet today" + 不把 stale 数字当今天报 (核心治本)
  T3 跨天 stale 仍显示 target (让主脑知道这是个被跟踪的习惯, 只是今天没记)
"""
from __future__ import annotations

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_concerns import ConcernsLedger, Concern, STATE_ACTIVE


def _ledger_with(dp: dict) -> ConcernsLedger:
    lg = ConcernsLedger()
    lg.concerns.clear()  # 隔离: 只留测试 concern
    c = Concern(id='sir_hydration_habit', what_i_watch="Sir's daily water intake",
                why_i_care="chronic deficiency", severity=0.8, state=STATE_ACTIVE)
    c.daily_progress = dp
    lg.register(c)
    return lg


class TestP1ProgressDateGuard(unittest.TestCase):
    def test_t1_today_shows_progress(self):
        today = time.strftime('%Y-%m-%d', time.localtime())
        block = _ledger_with({'current': 7.75, 'target': 10.0,
                              'unit': '杯', 'iso_date': today}).to_prompt_block()
        self.assertIn('today progress', block)
        self.assertIn('7.75', block)            # 今天的真值正常报
        self.assertNotIn('NOT logged', block)

    def test_t2_stale_says_not_logged(self):
        stale = time.strftime('%Y-%m-%d', time.localtime(time.time() - 3 * 86400))
        block = _ledger_with({'current': 7.75, 'target': 10.0,
                             'unit': '杯', 'iso_date': stale}).to_prompt_block()
        self.assertIn('NOT logged yet today', block)   # 核心: 显式"今天没记录"
        self.assertNotIn('7.75', block)                # stale 数字不当今天报 (准则5)

    def test_t3_stale_still_shows_target(self):
        stale = time.strftime('%Y-%m-%d', time.localtime(time.time() - 3 * 86400))
        block = _ledger_with({'current': 7.75, 'target': 10.0,
                             'unit': '杯', 'iso_date': stale}).to_prompt_block()
        self.assertIn('10.0', block)   # target 仍在 (主脑知道这是被跟踪的习惯)

    def test_t4_no_daily_progress_no_line(self):
        # 没 daily_progress 的 concern → 不该冒出 progress 行
        block = _ledger_with({}).to_prompt_block()
        self.assertNotIn('today progress', block)
        self.assertNotIn('NOT logged', block)


if __name__ == '__main__':
    unittest.main(verbosity=2)
