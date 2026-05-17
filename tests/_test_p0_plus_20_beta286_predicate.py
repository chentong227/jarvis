# -*- coding: utf-8 -*-
"""[P0+20-β.2.8.6 / 2026-05-17] Predicate-Driven Commitment

Sir 22:42 / 22:48 反馈痛点:
> "加某个类型, 是不是有点类似硬编码? 如果不是睡觉的情况呢? 是我'导出完视频
>  就去喝水'之类的抽象承诺呢? 我们能不能设计一套这种抽象语义的承诺系统?"
> "导出完视频去喝水的主体是我, 承诺人不是我, 完整版应该是'等我导出完视频
>  (贾维斯看导出完没有?) 提醒(sir)去喝水'."

测点:
- 7 个内置 Predicate evaluate
- AND/OR/NOT Composite
- to_dict/from_dict round-trip 持久化
- heuristic_predicate_from_text (β-3 LLM parser 未上前的兜底)
- CommitmentWatcher add_commitment(commit_type='conditional_reminder')
"""
import os
import sys
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _now():
    return time.time()


class TestBuiltinPredicates(unittest.TestCase):
    def test_wake_first_active_hit(self):
        from jarvis_predicate import WakeFirstActive
        p = WakeFirstActive()
        self.assertTrue(p.evaluate({'first_active_today': True, 'idle_ms': 1000}))

    def test_wake_first_active_miss_idle(self):
        from jarvis_predicate import WakeFirstActive
        p = WakeFirstActive(max_idle_ms=60_000)
        self.assertFalse(p.evaluate({'first_active_today': True, 'idle_ms': 120_000}))

    def test_wake_first_active_miss_not_first(self):
        from jarvis_predicate import WakeFirstActive
        p = WakeFirstActive()
        self.assertFalse(p.evaluate({'first_active_today': False, 'idle_ms': 1000}))

    def test_time_after(self):
        from jarvis_predicate import TimeAfter
        p = TimeAfter('09:00')
        # 模拟 now_ts 是 2026-05-17 09:30
        ts = time.mktime((2026, 5, 17, 9, 30, 0, 0, 0, -1))
        self.assertTrue(p.evaluate({'now_ts': ts}))
        ts2 = time.mktime((2026, 5, 17, 8, 59, 0, 0, 0, -1))
        self.assertFalse(p.evaluate({'now_ts': ts2}))

    def test_process_exit_hit(self):
        from jarvis_predicate import ProcessExited
        p = ProcessExited('Adobe Premiere Pro.exe', max_recent_s=300)
        ctx = {
            'now_ts': time.time(),
            'process_died_events': [
                {'exe': 'Adobe Premiere Pro.exe', 'when': time.time() - 60},
            ],
        }
        self.assertTrue(p.evaluate(ctx))

    def test_process_exit_miss_too_old(self):
        from jarvis_predicate import ProcessExited
        p = ProcessExited('Premiere', max_recent_s=60)
        ctx = {
            'now_ts': time.time(),
            'process_died_events': [
                {'exe': 'Adobe Premiere Pro.exe', 'when': time.time() - 600},
            ],
        }
        self.assertFalse(p.evaluate(ctx))

    def test_process_running(self):
        from jarvis_predicate import ProcessRunning
        p = ProcessRunning('cursor.exe')
        self.assertTrue(p.evaluate({'running_processes': ['Cursor.exe', 'chrome.exe']}))
        self.assertFalse(p.evaluate({'running_processes': ['chrome.exe']}))

    def test_window_title_contains(self):
        from jarvis_predicate import WindowTitleContains
        p = WindowTitleContains('cursor')
        self.assertTrue(p.evaluate({'window_title': 'main.py — Cursor — Jarvis'}))
        self.assertFalse(p.evaluate({'window_title': 'chrome'}))

    def test_idle_for(self):
        from jarvis_predicate import IdleFor
        p = IdleFor(30)
        self.assertTrue(p.evaluate({'idle_ms': 40_000}))
        self.assertFalse(p.evaluate({'idle_ms': 5_000}))

    def test_active_for(self):
        from jarvis_predicate import ActiveFor
        p = ActiveFor(45)
        self.assertTrue(p.evaluate({'sensor_snap': {'session_duration_minutes': 60}}))
        self.assertFalse(p.evaluate({'sensor_snap': {'session_duration_minutes': 10}}))

    def test_stm_contains(self):
        from jarvis_predicate import StmContains
        p = StmContains(['水', 'water'], lookback_turns=3)
        ctx = {'recent_stm': [
            {'user': 'something unrelated'},
            {'user': '我刚喝了水, 真渴'},
        ]}
        self.assertTrue(p.evaluate(ctx))
        ctx2 = {'recent_stm': [{'user': 'banana smoothie'}]}
        self.assertFalse(p.evaluate(ctx2))


class TestComposite(unittest.TestCase):
    def test_and(self):
        from jarvis_predicate import AndPredicate, WakeFirstActive, TimeAfter
        p = AndPredicate(WakeFirstActive(), TimeAfter('06:00'))
        ts_morning = time.mktime((2026, 5, 17, 9, 0, 0, 0, 0, -1))
        self.assertTrue(p.evaluate({'first_active_today': True, 'idle_ms': 1000, 'now_ts': ts_morning}))
        # 任意一条 false → 整体 false
        self.assertFalse(p.evaluate({'first_active_today': False, 'idle_ms': 1000, 'now_ts': ts_morning}))

    def test_or(self):
        from jarvis_predicate import OrPredicate, ProcessExited, IdleFor
        p = OrPredicate(ProcessExited('xxx'), IdleFor(10))
        self.assertTrue(p.evaluate({'idle_ms': 20_000, 'now_ts': time.time(),
                                       'process_died_events': []}))
        self.assertFalse(p.evaluate({'idle_ms': 1_000, 'now_ts': time.time(),
                                        'process_died_events': []}))

    def test_not(self):
        from jarvis_predicate import NotPredicate, IdleFor
        p = NotPredicate(IdleFor(30))
        self.assertTrue(p.evaluate({'idle_ms': 5_000}))
        self.assertFalse(p.evaluate({'idle_ms': 60_000}))


class TestSerialization(unittest.TestCase):
    def test_round_trip_simple(self):
        from jarvis_predicate import Predicate, TimeAfter
        p = TimeAfter('09:00')
        d = p.to_dict()
        self.assertEqual(d['type'], 'time_after')
        self.assertEqual(d['hh_mm'], '09:00')
        p2 = Predicate.from_dict(d)
        self.assertIsInstance(p2, TimeAfter)
        self.assertEqual(p2.hh_mm, '09:00')

    def test_round_trip_composite(self):
        from jarvis_predicate import (
            Predicate, AndPredicate, ProcessExited, IdleFor,
        )
        p = AndPredicate(ProcessExited('Premiere'), IdleFor(60))
        d = p.to_dict()
        self.assertEqual(d['type'], 'AND')
        self.assertEqual(len(d['args']), 2)
        p2 = Predicate.from_dict(d)
        self.assertIsInstance(p2, AndPredicate)
        self.assertEqual(len(p2.children), 2)

    def test_unknown_type_raises(self):
        from jarvis_predicate import Predicate
        with self.assertRaises(ValueError):
            Predicate.from_dict({'type': 'xxx_unknown_xx'})

    def test_parse_predicate_safe_none(self):
        from jarvis_predicate import parse_predicate
        self.assertIsNone(parse_predicate({'type': 'xxx_unknown'}))
        self.assertIsNone(parse_predicate("not a dict"))
        self.assertIsNone(parse_predicate(None))


class TestHeuristicParser(unittest.TestCase):
    """β-3 LLM parser 未上前的兜底 — 启发式关键词推断."""

    def test_wake_keyword(self):
        from jarvis_predicate import heuristic_predicate_from_text, AndPredicate
        p = heuristic_predicate_from_text('明早醒了提醒我刷题')
        self.assertIsNotNone(p)
        self.assertIsInstance(p, AndPredicate)
        # 应含 wake + time_after 子谓词
        names = [c.name for c in p.children]
        self.assertIn('wake_first_active', names)
        self.assertIn('time_after', names)

    def test_export_keyword(self):
        from jarvis_predicate import heuristic_predicate_from_text
        p = heuristic_predicate_from_text('等我导出完视频提醒我喝水')
        self.assertIsNotNone(p)
        # 应有 ProcessExited + IdleFor 子谓词
        children = getattr(p, 'children', [p])
        names = [c.name for c in children]
        self.assertIn('process_exit', names)

    def test_no_keyword_returns_none(self):
        from jarvis_predicate import heuristic_predicate_from_text
        p = heuristic_predicate_from_text('随便聊一下天气')
        self.assertIsNone(p)


class TestCommitmentWatcherConditionalReminder(unittest.TestCase):
    """conditional_reminder 类型: Sir 托付 Jarvis 监视 predicate, 不是 Sir 自承诺."""

    def setUp(self):
        from jarvis_commitment_watcher import CommitmentWatcher
        self.worker = MagicMock()
        self.worker.jarvis = MagicMock()
        self.worker.jarvis.short_term_memory = []
        gate = MagicMock()
        gate.is_sleep_mode.return_value = False
        gate.can_speak.return_value = True
        self.cw = CommitmentWatcher.__new__(CommitmentWatcher)
        self.cw.commitments = []
        self.cw._lock = __import__('threading').Lock()
        self.cw.worker = self.worker
        self.cw.gate = gate
        self.cw._get_hippo = lambda: None
        self.cw._dispatch_commitment_nudge = MagicMock()

    def test_conditional_reminder_without_predicate_rejected(self):
        """conditional_reminder 必须有 predicate, 否则拒."""
        self.cw.add_commitment(
            description='导出完视频喝水',
            deadline_str='',
            user_text='等我导出完视频提醒我喝水',
            commit_type='conditional_reminder',
            predicate=None,
        )
        self.assertEqual(len(self.cw.commitments), 0)

    def test_conditional_reminder_bypasses_first_person_check(self):
        """正常 sir_self_promise 路径会因为没"我"被拒, conditional_reminder 必须接受."""
        from jarvis_predicate import ProcessExited
        # 注意: "导出完视频喝水" 无第一人称 + 无作息词 → 老路径会拒
        self.cw.add_commitment(
            description='导出完视频喝水',
            deadline_str='',
            user_text='等我导出完视频提醒我喝水',
            commit_type='conditional_reminder',
            predicate=ProcessExited('Adobe Premiere Pro.exe'),
        )
        self.assertEqual(len(self.cw.commitments), 1)
        c = self.cw.commitments[0]
        self.assertEqual(c['commit_type'], 'conditional_reminder')
        self.assertIsNotNone(c['predicate'])

    def test_build_ctx_smoke(self):
        """_build_predicate_ctx 不抛异常 (sensor 无可用也降级返回空 dict)."""
        ctx = self.cw._build_predicate_ctx(time.time())
        self.assertIn('now_ts', ctx)
        self.assertIn('idle_ms', ctx)
        self.assertIn('recent_stm', ctx)


if __name__ == '__main__':
    unittest.main(verbosity=2)
