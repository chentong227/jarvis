# -*- coding: utf-8 -*-
"""[B1 / Sir 2026-06-02 真机] 睡眠意图未来日期守门回归.

真机 BUG (jarvis_20260602_194104): Sir "6月3号晚上8点后提醒我不喝水、早点休息"
(为后天体检准备) 命中睡眠关键词 → _detect_sleep_intent 误判成"现在要睡" →
启动 632s 睡眠倒数 + SleepMode 静音 app。Jarvis 自己承认"将禁食要求与休息时间
混为一谈, 应用到了今晚"。

治本: 命中睡眠关键词时, 若句含未来某天指代 (明天/后天/N月N号/星期X) → 判为
排程提醒 (Time Hook 已另调度), 不触发**此刻** SleepMode 窗口。

覆盖:
  T1  "6月3号晚上...早点休息" → 不触发 (_sleep_intent_until 保持 0)
  T2  "明天早点睡" → 不触发
  T3  "后天晚上要早休息" → 不触发
  T4  "周三晚上早点睡" → 不触发
  T5  回归: "我30分钟后睡" (无未来日期) → 仍正常触发
  T6  回归: "我马上去睡" → 仍正常触发 immediate
"""
from __future__ import annotations

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_worker():
    from jarvis_nerve import JarvisWorkerThread

    class _DummyJarvis:
        event_bus = None

    worker = JarvisWorkerThread.__new__(JarvisWorkerThread)
    worker.jarvis = _DummyJarvis()
    worker._sleep_intent_until = 0.0
    return worker


class TestB1FutureDayGuard(unittest.TestCase):
    def test_t1_future_date_jun3_not_triggered(self):
        w = _make_worker()
        w._detect_sleep_intent(
            "6月3号晚上8点以后提醒我不要喝水，也不要吃东西了，然后要早点休息")
        self.assertEqual(w._sleep_intent_until, 0.0,
                         "B1: 6月3号(未来日)的早点休息不应触发此刻 SleepMode")

    def test_t2_tomorrow_not_triggered(self):
        w = _make_worker()
        w._detect_sleep_intent("明天早点睡，记得叫我")
        self.assertEqual(w._sleep_intent_until, 0.0,
                         "B1: 明天的睡不应触发此刻 SleepMode")

    def test_t3_day_after_tomorrow_not_triggered(self):
        w = _make_worker()
        w._detect_sleep_intent("后天晚上我要早点休息")
        self.assertEqual(w._sleep_intent_until, 0.0,
                         "B1: 后天的休息不应触发此刻 SleepMode")

    def test_t4_weekday_not_triggered(self):
        w = _make_worker()
        w._detect_sleep_intent("周三晚上早点睡觉")
        self.assertEqual(w._sleep_intent_until, 0.0,
                         "B1: 周三(未来日)的睡不应触发此刻 SleepMode")

    def test_t5_regression_30min_still_triggers(self):
        """回归: 无未来日期的'30分钟后睡' 仍正常触发窗口。"""
        w = _make_worker()
        before = time.time()
        w._detect_sleep_intent("我30分钟后睡")
        delta = w._sleep_intent_until - before
        self.assertGreater(delta, 2680, "回归: 30min 后睡应正常设窗口")
        self.assertLess(delta, 2720)

    def test_t6_regression_immediate_still_triggers(self):
        """回归: '我马上去睡' 仍正常触发 immediate。"""
        w = _make_worker()
        before = time.time()
        w._detect_sleep_intent("我马上去睡")
        delta = w._sleep_intent_until - before
        self.assertGreater(delta, 880, "回归: 马上去睡应 immediate 触发")
        self.assertLess(delta, 920)


if __name__ == "__main__":
    unittest.main(verbosity=2)
