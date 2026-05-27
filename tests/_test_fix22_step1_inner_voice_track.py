# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 18:44 真愿景 Phase 1 Step 1] InnerVoiceTrack 单例 + 持久化 + 3 层视图.

Sir 真愿景: 现象学等同人类 butler. InnerVoiceTrack = Jarvis 24/7 心声轨道.

Step 1 cover:
  T1-T3: append / recent / range API
  T4-T5: 3 层 prompt block (L1 full / L2 5min bucket / L3 1h bucket)
  T6: 持久化 (write + reload)
  T7: wants_voice 标记 + has_wants_voice_pending
  T8: env flag is_enabled
  T9: cap content 300 char
  T10: stats
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestInnerVoiceTrack(unittest.TestCase):

    def setUp(self):
        # 每个 test 用临时 jsonl
        self.tmp_dir = tempfile.mkdtemp(prefix='inner_voice_test_')
        self.tmp_path = os.path.join(self.tmp_dir, 'voice.jsonl')
        from jarvis_inner_voice_track import InnerVoiceTrack
        self.track = InnerVoiceTrack(persist_path=self.tmp_path)

    def tearDown(self):
        import shutil
        try:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        except Exception:
            pass

    # ----- API -----

    def test_t1_append_and_recent(self):
        """append 后 recent() 能取到."""
        self.track.append('inner_thought', 'first', intent='noting')
        self.track.append('care_trigger', 'second', intent='care', urgency=0.5)
        rec = self.track.recent(minutes=10)
        self.assertEqual(len(rec), 2)
        self.assertEqual(rec[0].content, 'first')
        self.assertEqual(rec[1].source, 'care_trigger')
        self.assertEqual(rec[1].urgency, 0.5)

    def test_t2_recent_filters_old(self):
        """recent(minutes=10) 不返回 11min 前的."""
        old_ts = time.time() - 15 * 60
        self.track.append('sensor', 'old entry', ts=old_ts)
        self.track.append('sensor', 'fresh entry')
        rec = self.track.recent(minutes=10)
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0].content, 'fresh entry')

    def test_t3_range_window(self):
        """range(min_min_ago, max_min_ago) 切窗口."""
        now = time.time()
        self.track.append('sensor', 'a_30min', ts=now - 30 * 60)
        self.track.append('sensor', 'b_50min', ts=now - 50 * 60)
        self.track.append('sensor', 'c_5min', ts=now - 5 * 60)
        self.track.append('sensor', 'd_2h', ts=now - 2 * 3600)
        # 10-60min 窗口应含 a + b
        ent = self.track.range(min_min_ago=10, max_min_ago=60)
        contents = sorted(e.content for e in ent)
        self.assertEqual(contents, ['a_30min', 'b_50min'])

    # ----- 3 层 prompt block -----

    def test_t4_l1_full_block(self):
        """近 10min full block 含全 entry."""
        self.track.append('inner_thought', 'I am thinking X')
        self.track.append('care_trigger', 'hydration soon', urgency=0.6)
        block = self.track.build_prompt_block_for_brain()
        self.assertIn('YOUR INNER VOICE', block)
        self.assertIn('past 10 min', block)
        self.assertIn('I am thinking X', block)
        self.assertIn('hydration soon', block)
        # urgency 显示
        self.assertIn('u=0.6', block)

    def test_t5_l2_l3_bucket_digest(self):
        """L2 (5min bucket) / L3 (1h bucket) digest 含 'entries' 计数."""
        now = time.time()
        # L2 数据 (10-60min)
        for i in range(5):
            self.track.append('sensor', f'mid_{i}',
                                intent='observation',
                                ts=now - (15 + i * 8) * 60)
        # L3 数据 (1-24h)
        for i in range(3):
            self.track.append('inner_thought', f'old_{i}',
                                intent='reflection',
                                ts=now - (90 + i * 30) * 60)
        block = self.track.build_prompt_block_for_brain()
        self.assertIn('10min', block)
        self.assertIn('1h — 24h', block)
        self.assertIn('entries:', block,
            "bucket digest 必含 'entries:' 计数标签")
        # L2 + L3 都聚合, 不一一显原 content
        self.assertIn('observation=', block)

    def test_t5b_empty_block(self):
        """空 buffer block 含 'voice empty' 说明."""
        block = self.track.build_prompt_block_for_brain()
        self.assertIn('voice empty', block)
        self.assertIn('just woke', block)

    # ----- 持久化 -----

    def test_t6_persistence(self):
        """append 写 jsonl, 重启新实例能 load 回来."""
        self.track.append('inner_thought', 'persisted entry', urgency=0.8)
        self.track.append('care_trigger', 'persisted care', wants_voice=True)
        # 新实例
        from jarvis_inner_voice_track import InnerVoiceTrack
        track2 = InnerVoiceTrack(persist_path=self.tmp_path)
        rec = track2.recent(minutes=10)
        self.assertEqual(len(rec), 2)
        self.assertEqual(rec[0].content, 'persisted entry')
        self.assertEqual(rec[0].urgency, 0.8)
        self.assertTrue(rec[1].wants_voice)

    def test_t6b_persistence_filters_old(self):
        """load 时跳过 24h+ 老 entry."""
        # 手写 jsonl 含 25h 前的 entry
        with open(self.tmp_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps({
                'ts': time.time() - 25 * 3600,
                'source': 'sensor', 'content': 'too old',
                'intent': 'observation', 'urgency': 0,
                'wants_voice': False,
            }) + '\n')
            f.write(json.dumps({
                'ts': time.time() - 1 * 3600,
                'source': 'sensor', 'content': 'fresh',
                'intent': 'observation', 'urgency': 0,
                'wants_voice': False,
            }) + '\n')
        from jarvis_inner_voice_track import InnerVoiceTrack
        track3 = InnerVoiceTrack(persist_path=self.tmp_path)
        rec = track3.recent(minutes=24 * 60 + 10)  # 24h+ 窗口
        contents = [e.content for e in rec]
        self.assertNotIn('too old', contents)
        self.assertIn('fresh', contents)

    # ----- wants_voice -----

    def test_t7_wants_voice_pending(self):
        """has_wants_voice_pending 检测近期 wants_voice."""
        self.track.append('inner_thought', 'casual', wants_voice=False)
        self.assertFalse(self.track.has_wants_voice_pending())
        self.track.append('care_trigger', 'urgent', wants_voice=True,
                          urgency=0.8)
        self.assertTrue(self.track.has_wants_voice_pending())
        # 老的 wants_voice 不算 (40min 前)
        from jarvis_inner_voice_track import InnerVoiceTrack
        track_old = InnerVoiceTrack(persist_path=self.tmp_path + '.old')
        track_old.append('care_trigger', 'old_urgent', wants_voice=True,
                          ts=time.time() - 40 * 60)
        self.assertFalse(track_old.has_wants_voice_pending(within_min=30))

    # ----- env flag -----

    def test_t8_is_enabled_default(self):
        """env JARVIS_INNER_VOICE_ENABLED 默认开."""
        from jarvis_inner_voice_track import is_enabled
        # 保存原值
        orig = os.environ.get('JARVIS_INNER_VOICE_ENABLED')
        try:
            if 'JARVIS_INNER_VOICE_ENABLED' in os.environ:
                del os.environ['JARVIS_INNER_VOICE_ENABLED']
            self.assertTrue(is_enabled(), 'default 必开')
            os.environ['JARVIS_INNER_VOICE_ENABLED'] = '0'
            self.assertFalse(is_enabled(), "env=0 必关")
            os.environ['JARVIS_INNER_VOICE_ENABLED'] = '1'
            self.assertTrue(is_enabled(), "env=1 必开")
        finally:
            if orig is None:
                os.environ.pop('JARVIS_INNER_VOICE_ENABLED', None)
            else:
                os.environ['JARVIS_INNER_VOICE_ENABLED'] = orig

    # ----- cap -----

    def test_t9_content_cap_300_char(self):
        """content 超过 300 char 必截."""
        long_text = 'x' * 500
        e = self.track.append('inner_thought', long_text)
        self.assertEqual(len(e.content), 300)

    # ----- stats -----

    def test_t10_stats_fields(self):
        """stats 返关键字段."""
        self.track.append('inner_thought', 'a')
        self.track.append('care_trigger', 'b', wants_voice=True,
                          urgency=0.7)
        s = self.track.stats()
        for key in ('total', 'last_10min', 'last_1h', 'last_24h',
                     'wants_voice_pending_30min', 'oldest_age_min',
                     'newest_age_sec'):
            self.assertIn(key, s)
        self.assertEqual(s['total'], 2)
        self.assertEqual(s['wants_voice_pending_30min'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
