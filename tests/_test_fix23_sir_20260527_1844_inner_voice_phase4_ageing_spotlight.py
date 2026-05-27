# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 18:44 真愿景] InnerVoice Phase 4 — ageing + spotlight 回归.

Phase 4 工程:
  - VoiceEntry 加 entry_id / surfaced_to_sir / surface_attempts /
    last_surface_attempt_ts
  - memory_pool/inner_voice_aging_config.json (持久化, 准则 6)
  - 4 method: get_pending_wants_voice / apply_ageing / mark_surface_attempt /
              mark_recent_surfaced_by_overlap
  - build_prompt_block_for_brain 加 SPOTLIGHT 顶段
  - chat_bypass stream_chat hook 调 mark_recent_surfaced_by_overlap
  - CLI scripts/inner_voice_aging_dump.py

测试 18 testcase:

Step 4a — VoiceEntry 字段 (3 testcase):
  - PH4_1: VoiceEntry 含 4 新字段 + 默认值正确
  - PH4_2: append 自动 gen entry_id (iv_ 前缀 + 12 hex)
  - PH4_3: from_dict 兼容老 jsonl (无 entry_id 字段也能 load)

Step 4b — ageing config (3 testcase):
  - PH4_4: memory_pool/inner_voice_aging_config.json 存在
  - PH4_5: _load_aging_config() merge default 后 含 3 section / 关键字段
  - PH4_6: _note 字段被剔除

Step 4c — API (4 testcase):
  - PH4_7: get_pending_wants_voice 只返 wants_voice=True 且 surfaced=False
  - PH4_8: apply_ageing 超 max_attempts 降级
  - PH4_9: apply_ageing 超 max_age 降级
  - PH4_10: mark_surface_attempt ++ counter

Step 4d — overlap detection (3 testcase):
  - PH4_11: mark_recent_surfaced_by_overlap 命中 hydration 主题 (token overlap)
  - PH4_12: 不命中 (overlap 不足 min_overlap_words)
  - PH4_13: self-reflection entry (kind=main_reply) 被 skip 不 mark

Step 4e — build_prompt_block_for_brain (3 testcase):
  - PH4_14: SPOTLIGHT 段 render (含 header + entry)
  - PH4_15: SPOTLIGHT 段后 surface_attempts ++
  - PH4_16: show_spotlight=False 关闭 spotlight (老 L1/L2/L3 不动)

Step 4f — wire 集成 (2 testcase):
  - PH4_17: chat_bypass stream_chat 含 mark_recent_surfaced_by_overlap 调用
  - PH4_18: 顺序: mark_surfaced 在 Phase 3 append 前
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import time
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def _fresh_track():
    """每 testcase 都 new 一个隔离 track (持久路径用 tmp)."""
    import jarvis_inner_voice_track as ivt
    ivt.reset_for_test()
    td = tempfile.mkdtemp()
    track = ivt.InnerVoiceTrack(persist_path=os.path.join(td, 'iv.jsonl'))
    ivt._DEFAULT = track
    return track


# ============================================================
# Step 4a — VoiceEntry fields
# ============================================================

class TestStep4aVoiceEntryFields(unittest.TestCase):

    def test_ph4_1_voiceentry_has_4_new_fields_with_defaults(self):
        """PH4_1: VoiceEntry 含 4 新字段 + 默认值."""
        from jarvis_inner_voice_track import VoiceEntry
        e = VoiceEntry(ts=time.time(), source='noting', content='x')
        self.assertEqual(e.entry_id, '')           # 默认空 (append 时 gen)
        self.assertFalse(e.surfaced_to_sir)
        self.assertEqual(e.surface_attempts, 0)
        self.assertEqual(e.last_surface_attempt_ts, 0.0)

    def test_ph4_2_append_auto_generates_entry_id(self):
        """PH4_2: append 时自动 gen entry_id (iv_ + 12 hex)."""
        track = _fresh_track()
        e = track.append(source='noting', content='test', intent='noting')
        self.assertTrue(e.entry_id.startswith('iv_'),
                              f'entry_id should start with iv_, got {e.entry_id}')
        self.assertEqual(len(e.entry_id), 3 + 12,
                              f'iv_ + 12 hex = 15 chars, got {len(e.entry_id)}')
        # 2 个 entry 应该不同 ID
        e2 = track.append(source='noting', content='test2', intent='noting')
        self.assertNotEqual(e.entry_id, e2.entry_id)

    def test_ph4_3_from_dict_backward_compat_legacy_jsonl(self):
        """PH4_3: from_dict 兼容老 jsonl (无 entry_id / surfaced 字段)."""
        from jarvis_inner_voice_track import VoiceEntry
        # 老 jsonl 格式 (无 Phase 4 字段)
        legacy = {
            'ts': 1716000000.0, 'source': 'sensor', 'content': 'old entry',
            'intent': 'observation', 'urgency': 0.5, 'wants_voice': True,
        }
        e = VoiceEntry.from_dict(legacy)
        self.assertEqual(e.entry_id, '')
        self.assertFalse(e.surfaced_to_sir)
        self.assertEqual(e.surface_attempts, 0)
        self.assertEqual(e.last_surface_attempt_ts, 0.0)
        # 老字段也都对
        self.assertEqual(e.source, 'sensor')
        self.assertTrue(e.wants_voice)


# ============================================================
# Step 4b — ageing config
# ============================================================

class TestStep4bAgeingConfig(unittest.TestCase):

    def test_ph4_4_config_file_exists(self):
        """PH4_4: memory_pool/inner_voice_aging_config.json 存在."""
        path = os.path.join(
            _REPO, 'memory_pool', 'inner_voice_aging_config.json'
        )
        self.assertTrue(os.path.exists(path),
                              f'config not found: {path}')

    def test_ph4_5_load_aging_config_merge_default(self):
        """PH4_5: _load_aging_config merge default 后 含关键字段."""
        from jarvis_inner_voice_track import _load_aging_config
        cfg = _load_aging_config()
        self.assertIn('spotlight', cfg)
        self.assertIn('ageing', cfg)
        self.assertIn('surface_detection', cfg)
        # 关键字段
        self.assertIn('max_pending_min', cfg['spotlight'])
        self.assertIn('ageing_max_age_sec', cfg['ageing'])
        self.assertIn('min_overlap_words', cfg['surface_detection'])

    def test_ph4_6_note_fields_stripped(self):
        """PH4_6: _note 字段被剔除 (不污染 config)."""
        from jarvis_inner_voice_track import _load_aging_config
        cfg = _load_aging_config()
        for section_name, section in cfg.items():
            if isinstance(section, dict):
                for k in section.keys():
                    self.assertFalse(
                        k.endswith('_note'),
                        f'{section_name}.{k} should be stripped'
                    )


# ============================================================
# Step 4c — API methods
# ============================================================

class TestStep4cApiMethods(unittest.TestCase):

    def test_ph4_7_get_pending_returns_only_wants_voice_not_surfaced(self):
        """PH4_7: get_pending_wants_voice 只返 ★ 且未 surface."""
        track = _fresh_track()
        now = time.time()
        e1 = track.append(source='care', content='hydration ★', urgency=0.8,
                                  wants_voice=True, ts=now-300)
        e2 = track.append(source='sensor', content='just noting',
                                  wants_voice=False, ts=now-200)  # 无 ★
        e3 = track.append(source='care', content='already surfaced ★',
                                  wants_voice=True, ts=now-100)
        e3.surfaced_to_sir = True  # 标已 surface
        pending = track.get_pending_wants_voice()
        ids = {e.entry_id for e in pending}
        self.assertIn(e1.entry_id, ids)
        self.assertNotIn(e2.entry_id, ids, 'wants_voice=False should not show')
        self.assertNotIn(e3.entry_id, ids, 'surfaced=True should not show')

    def test_ph4_8_apply_ageing_demotes_by_attempts(self):
        """PH4_8: apply_ageing 超 max_attempts 降级."""
        track = _fresh_track()
        e = track.append(source='care', content='aged by attempts',
                                  wants_voice=True)
        e.surface_attempts = 10  # 远超 default max=6
        n = track.apply_ageing()
        self.assertEqual(n, 1)
        self.assertFalse(e.wants_voice, 'should be demoted')

    def test_ph4_9_apply_ageing_demotes_by_age(self):
        """PH4_9: apply_ageing 超 max_age_sec 降级."""
        track = _fresh_track()
        # 老 entry (24h 之前, 远超 default 2h)
        old_ts = time.time() - 25 * 3600
        e = track.append(source='care', content='aged by time',
                                  wants_voice=True, ts=old_ts)
        n = track.apply_ageing()
        self.assertEqual(n, 1)
        self.assertFalse(e.wants_voice, 'should be demoted by age')

    def test_ph4_10_mark_surface_attempt_increments(self):
        """PH4_10: mark_surface_attempt ++ counter."""
        track = _fresh_track()
        e = track.append(source='care', content='counter test',
                                  wants_voice=True)
        self.assertEqual(e.surface_attempts, 0)
        track.mark_surface_attempt([e])
        self.assertEqual(e.surface_attempts, 1)
        track.mark_surface_attempt([e])
        track.mark_surface_attempt([e])
        self.assertEqual(e.surface_attempts, 3)
        self.assertGreater(e.last_surface_attempt_ts, 0)


# ============================================================
# Step 4d — overlap detection
# ============================================================

class TestStep4dOverlapDetection(unittest.TestCase):

    def test_ph4_11_overlap_hits_hydration_theme(self):
        """PH4_11: reply mention 3+ token of entry → surfaced=True."""
        track = _fresh_track()
        e = track.append(
            source='care',
            content='sir worked 1h hydration water tracker pending',
            urgency=0.8, wants_voice=True,
        )
        # reply 共享 token: hydration, water, tracker (3 个) ≥ min_overlap=3
        n = track.mark_recent_surfaced_by_overlap(
            'i have updated hydration water tracker to 2000ml', within_min=60.0,
        )
        self.assertEqual(n, 1)
        self.assertTrue(e.surfaced_to_sir)

    def test_ph4_12_overlap_misses_below_threshold(self):
        """PH4_12: 不足 min_overlap 不命中."""
        track = _fresh_track()
        e = track.append(
            source='care', content='sir hydration pending',
            urgency=0.8, wants_voice=True,
        )
        # reply 只 hit 'hydration' 1 个 token (sir 也 hit 但 'sir' 出现) — 2 个
        n = track.mark_recent_surfaced_by_overlap(
            'good afternoon sir hydration tracker', within_min=60.0,
        )
        # hydration + sir + tracker (tracker 不在 entry tokens) = 2 hits
        # entry tokens: sir, hydration, pending → reply tokens: good, afternoon,
        # sir, hydration, tracker → overlap: {sir, hydration} = 2 < 3
        self.assertEqual(n, 0, 'should not mark with overlap=2 < min=3')
        self.assertFalse(e.surfaced_to_sir)

    def test_ph4_13_self_reflection_entries_skipped(self):
        """PH4_13: self-reflection entry (kind=main_reply) 不被 overlap mark."""
        track = _fresh_track()
        # 模拟 Phase 3 self-append entry (wants_voice=False, kind=main_reply)
        # 但人为标 wants_voice=True 看 helper 是否 skip
        e = track.append(
            source='self_reflection', intent='noting',
            content='i replied to sir: "yes sir hydration done"',
            urgency=0.3, wants_voice=False,
            meta={'kind': 'main_reply'},
        )
        e.wants_voice = True  # 异常 case: 也不该被 overlap mark
        n = track.mark_recent_surfaced_by_overlap(
            'sir hydration done yes good', within_min=60.0,
        )
        self.assertEqual(n, 0)
        self.assertFalse(e.surfaced_to_sir)


# ============================================================
# Step 4e — build_prompt_block_for_brain SPOTLIGHT
# ============================================================

class TestStep4eBuildPromptSpotlight(unittest.TestCase):

    def test_ph4_14_spotlight_section_rendered(self):
        """PH4_14: SPOTLIGHT 段含 header + ★ entry."""
        track = _fresh_track()
        track.append(source='care', content='pending hydration',
                            urgency=0.8, wants_voice=True)
        out = track.build_prompt_block_for_brain(max_chars=3000)
        # spotlight header (来自 config)
        self.assertIn('pending to surface to Sir', out)
        # entry content
        self.assertIn('pending hydration', out)
        # 教导句
        self.assertIn("do not announce", out.lower())

    def test_ph4_15_spotlight_increments_attempts(self):
        """PH4_15: build_prompt_block_for_brain 后 ★ entry attempts ++."""
        track = _fresh_track()
        e = track.append(source='care', content='test',
                                wants_voice=True)
        self.assertEqual(e.surface_attempts, 0)
        _ = track.build_prompt_block_for_brain(max_chars=3000)
        self.assertGreaterEqual(e.surface_attempts, 1,
                                                  'should ++ after spotlight render')

    def test_ph4_16_show_spotlight_false_disables(self):
        """PH4_16: show_spotlight=False 关闭 spotlight 段."""
        track = _fresh_track()
        track.append(source='care', content='pending should not appear',
                            wants_voice=True)
        out = track.build_prompt_block_for_brain(
            max_chars=3000, show_spotlight=False
        )
        self.assertNotIn('pending to surface to Sir', out,
                                'spotlight header should not appear')
        # 但 entry 仍在 L1 段 (近 10min)
        self.assertIn('pending should not appear', out)


# ============================================================
# Step 4f — wire 集成
# ============================================================

class TestStep4fChatBypassIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        path = os.path.join(_REPO, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            cls.src = f.read()
        # 隔离 stream_chat
        m = re.search(
            r'def stream_chat\(self.*?(?=\n    def stream_nudge\()',
            cls.src, re.DOTALL,
        )
        cls.chat_body = m.group(0)

    def test_ph4_17_stream_chat_calls_mark_recent_surfaced(self):
        """PH4_17: stream_chat 含 mark_recent_surfaced_by_overlap 调用."""
        self.assertIn('mark_recent_surfaced_by_overlap', self.chat_body)

    def test_ph4_18_mark_surfaced_before_self_append(self):
        """PH4_18: mark_surfaced 必须在 Phase 3 self-append (main_reply) 之前."""
        pos_mark = self.chat_body.find('mark_recent_surfaced_by_overlap')
        pos_append = self.chat_body.find("'kind': 'main_reply'")
        self.assertGreater(pos_mark, 0)
        self.assertGreater(pos_append, 0)
        self.assertLess(pos_mark, pos_append,
                                'mark_surfaced MUST be before main_reply append '
                                '— 否则 self-append 自己污染了 overlap detection')


if __name__ == '__main__':
    unittest.main(verbosity=2)
