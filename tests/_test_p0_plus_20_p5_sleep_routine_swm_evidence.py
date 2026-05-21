# -*- coding: utf-8 -*-
"""[β.5.46-fix13 Fix-2 / 2026-05-22 00:35] SleepMode routine publish SWM evidence.

Sir 00:30:23 真测 (B3/B4/B7):
  B3. "I've muted the audio for you" (假, MuteApps hit=[])
  B4. "I lack the means to power down display" (冲突, sleep_display routine 明明有)
  B7. "I haven't actually muted yet" (自打脸)

真凶: 主脑不知道 SleepMode routine 真做了啥 + 不知道自己有哪些能力.
治本:
  1. routine 完成后 publish 'sleep_routine_armed' SWM event 含真实 result
     (mute_apps hits / misses / sleep_display msg / asr_mute ttl)
  2. _assemble_prompt 渲染 [SLEEP ROUTINE EVIDENCE] block, 主脑据 evidence 回答

Cover:
  A. _do_routine 调 publish (静态 check + 字面 marker)
  B. _assemble_prompt 渲染 [SLEEP ROUTINE EVIDENCE] block 字面
  C. block 含 FORBIDDEN 行 (防"我已经 muted"假声明)
  D. ConversationEventBus 真 publish + recent_events query 行为
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_WorkerRoutinePublishesSwm(unittest.TestCase):
    """静态 check jarvis_worker.py _do_routine 含 publish 'sleep_routine_armed'."""

    def setUp(self):
        import jarvis_worker
        with open(jarvis_worker.__file__, 'r', encoding='utf-8') as f:
            self.src = f.read()

    def test_swm_results_dict_initialized(self):
        """_swm_results dict 收集 3 段 result."""
        self.assertIn("_swm_results = {'mute_apps': None, 'sleep_display': None, 'asr_mute': None}",
                       self.src,
                       '_swm_results dict 应初始化 3 段 sub-result')

    def test_mute_apps_records_hits_misses(self):
        """mute_apps result 含 hits / misses_count / targets_attempted / success."""
        self.assertIn("'hits': list(hits)", self.src,
                       'mute_apps result 应记录 hits list')
        self.assertIn("'misses_count': len(misses)", self.src,
                       'mute_apps result 应记录 misses_count')
        self.assertIn("'success': bool(hits)", self.src,
                       'mute_apps success = bool(hits) (无 hit = fail)')

    def test_sleep_display_records_success_msg(self):
        """sleep_display result 含 success + msg."""
        self.assertIn("'msg': (r.msg or '')[:120]", self.src,
                       'sleep_display result 应记录 msg')

    def test_asr_mute_records_ttl(self):
        """asr_mute result 含 ttl_s + mute_until_ts."""
        self.assertIn("'mute_until_ts': self.mute_until", self.src,
                       'asr_mute result 应记录 mute_until_ts')
        self.assertIn("'ttl_s': 1800", self.src,
                       'asr_mute result 应记录 ttl_s (30min)')

    def test_publishes_sleep_routine_armed_event(self):
        """routine 完成后 publish 'sleep_routine_armed' SWM event."""
        self.assertIn("etype='sleep_routine_armed'", self.src,
                       '应 publish sleep_routine_armed event')
        self.assertIn("source='SleepModeRoutine'", self.src,
                       '应标 source SleepModeRoutine')
        # salience 高让主脑必读
        self.assertIn("salience=0.85", self.src,
                       'salience 应高 (0.85) 主脑必读')
        self.assertIn("ttl=600.0", self.src,
                       'ttl 10min — 让主脑下轮 prompt 必看')


class TestB_AssemblePromptRendersBlock(unittest.TestCase):
    """静态 check jarvis_central_nerve.py _assemble_prompt 渲染 [SLEEP ROUTINE EVIDENCE]."""

    def setUp(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            self.src = f.read()

    def test_block_header_present(self):
        """主脑 prompt 含 [SLEEP ROUTINE EVIDENCE] block."""
        self.assertIn('SLEEP ROUTINE EVIDENCE', self.src,
                       'prompt 应含 [SLEEP ROUTINE EVIDENCE] block header')

    def test_block_queries_swm_recent_events(self):
        """block 读 SWM recent_events for 'sleep_routine_armed'."""
        self.assertIn("'sleep_routine_armed'", self.src,
                       'block 应 query SWM type sleep_routine_armed')

    def test_block_includes_mute_apps_evidence(self):
        """block 应显 MuteApps hit / 0 hit 真实情况."""
        self.assertIn('MuteApps: hit', self.src,
                       'block 应有 MuteApps hit 报告')
        self.assertIn('MuteApps: 0 hit', self.src,
                       'block 应有 MuteApps 0 hit 报告 (audio session 空)')

    def test_block_includes_display_evidence(self):
        """block 应显 DisplaySleep OK/FAIL."""
        self.assertIn('DisplaySleep:', self.src,
                       'block 应有 DisplaySleep 报告')

    def test_block_includes_asr_mute_evidence(self):
        """block 应显 ASRMute 状态."""
        self.assertIn('ASRMute:', self.src,
                       'block 应有 ASRMute 报告')

    def test_block_has_forbidden_directive(self):
        """block 含 FORBIDDEN 防 B3/B4/B7."""
        self.assertIn('FORBIDDEN', self.src,
                       'block 应含 FORBIDDEN 标记防主脑撒谎')
        self.assertIn('"我已经 muted" 当 MuteApps 0 hit', self.src,
                       'FORBIDDEN 应针对 B3 (假"已 muted")')
        self.assertIn('"我没法 dim display"', self.src,
                       'FORBIDDEN 应针对 B4 (否认 display 能力)')


class TestC_SwmPublishAndQueryBehavior(unittest.TestCase):
    """integration — ConversationEventBus 真 publish + query 行为 OK."""

    def test_publish_query_roundtrip(self):
        from jarvis_utils import ConversationEventBus
        bus = ConversationEventBus()
        bus.publish(
            etype='sleep_routine_armed',
            description='SleepMode test: MuteApps OK (3 hit) | DisplaySleep OK',
            source='SleepModeRoutine',
            salience=0.85,
            ttl=600.0,
            metadata={
                'mute_apps': {'hits': ['WeChat', 'QQ', 'Chrome'],
                              'misses_count': 0,
                              'targets_attempted': 3,
                              'success': True},
                'sleep_display': {'success': True, 'msg': 'display sleeping'},
                'asr_mute': {'success': True, 'mute_until_ts': 9999999999,
                              'ttl_s': 1800},
            },
        )
        events = bus.recent_events(within_seconds=600.0,
                                     types={'sleep_routine_armed'})
        self.assertEqual(len(events), 1, '应能 query 到 1 条 event')
        meta = (events[0].get('metadata') or {})
        self.assertTrue(meta.get('mute_apps', {}).get('success'),
                          'mute_apps success 应 round-trip')
        self.assertEqual(meta.get('mute_apps', {}).get('hits'),
                          ['WeChat', 'QQ', 'Chrome'],
                          'hits list 应 round-trip')

    def test_no_event_no_block(self):
        """没 publish 时 recent_events 返空, block 不渲染."""
        from jarvis_utils import ConversationEventBus
        bus = ConversationEventBus()
        events = bus.recent_events(within_seconds=600.0,
                                     types={'sleep_routine_armed'})
        self.assertEqual(len(events), 0,
                          '没 routine 触发时 SWM 应空, block 不渲染')

    def test_failed_routine_records_error_path(self):
        """routine 失败 (e.g. mute_apps 0 hit) 也 publish, success=False."""
        from jarvis_utils import ConversationEventBus
        bus = ConversationEventBus()
        bus.publish(
            etype='sleep_routine_armed',
            description='SleepMode test: MuteApps NO-OP (0 audio session)',
            source='SleepModeRoutine',
            salience=0.85,
            metadata={
                'mute_apps': {'hits': [], 'misses_count': 3,
                              'targets_attempted': 3, 'success': False},
                'sleep_display': {'success': True, 'msg': 'display sleeping'},
                'asr_mute': {'success': True, 'ttl_s': 1800},
            },
        )
        events = bus.recent_events(within_seconds=600.0,
                                     types={'sleep_routine_armed'})
        self.assertEqual(len(events), 1)
        meta = events[0].get('metadata') or {}
        self.assertFalse(meta.get('mute_apps', {}).get('success'),
                           'mute_apps 0 hit 应 success=False (主脑据此说真话)')
        self.assertEqual(meta.get('mute_apps', {}).get('hits'), [],
                          '0 hit 时 hits 应空 list')


if __name__ == '__main__':
    unittest.main()
