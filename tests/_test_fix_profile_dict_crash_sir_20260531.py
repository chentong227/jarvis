# -*- coding: utf-8 -*-
"""[Sir 2026-05-31 22:17 真机 — 两个 BUG]

Sir 真机跑 jarvis_nerve.py 撞:
1. **终端死了 (主脑哑火)**: jarvis_routing.py _build_likes_boundaries
   `profile.get('conversational_boundaries','')[:200]` — 该字段已是 dict (schema 漂移)
   → dict[slice] → `TypeError: unhashable type: 'slice'` → _assemble_prompt 每轮崩 (整机不回复)。
2. **字幕打印思考**: kind=empty (actionable=none) 的 B 类自省 (sal=0.80, "我刚回复太啰嗦,
   该简洁") 被标 wants_voice=True → 主脑 prompt ★spotlight "surface to Sir" → 主脑真
   开口 → Sir 字幕看到空想 (无法影响自身的 filler 不该 surface)。

修:
1. ProfileCard._safe_clip(val, n) — 非 str (dict/list/None) 先转 JSON 串再截断, 永不崩。
   4 处直接 profile.get()[:N] 全走 helper (core_philosophy/work_rhythms/idiosyncrasies/
   conversational_boundaries)。准则 8 治本: 不让同 bug 换字段复发。
2. _maybe_publish_self_correction 的 wants_voice 加 has_effect 闸 (与 _append_to_voice_track
   Path 2 已有的 has_actionable 对齐) — kind=empty 无效果不 ★ spotlight。

覆盖:
  T1 _safe_clip(dict) → str 不崩 (复现真机崩点)
  T2 _safe_clip(str, 3) → 截断
  T3 _safe_clip(None) → ''
  T4 _safe_clip(list) → str
  T5 _build_likes_boundaries(dict boundaries) → 不崩, boundaries 是 str
  T6 _build_identity(dict 字段) → 不崩, 字段全 str
  T7 self_reflection: actionable=none (kind=empty) sal=0.9 → wants_voice=False (不泄漏字幕)
  T8 self_reflection: actionable 非 none sal=0.9 → wants_voice=True (真效果才 ★)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _FakeNerve:
    habit_clock = None
    project_timeline = None


class TestSafeClipCrash(unittest.TestCase):
    """T1-T6: profile 字段 schema 漂移 (dict/list) 不再崩 _assemble_prompt。"""

    def _card(self):
        from jarvis_routing import ProfileCard
        return ProfileCard(_FakeNerve())

    def test_t1_safe_clip_dict_no_crash(self):
        from jarvis_routing import ProfileCard
        # 真机崩点: dict[:200] → unhashable slice. 现在转 JSON 串。
        out = ProfileCard._safe_clip({'no_meetings': True}, 200)
        self.assertIsInstance(out, str)
        self.assertIn('no_meetings', out)

    def test_t2_safe_clip_str_truncates(self):
        from jarvis_routing import ProfileCard
        self.assertEqual(ProfileCard._safe_clip('abcdef', 3), 'abc')

    def test_t3_safe_clip_none(self):
        from jarvis_routing import ProfileCard
        self.assertEqual(ProfileCard._safe_clip(None, 50), '')

    def test_t4_safe_clip_list(self):
        from jarvis_routing import ProfileCard
        out = ProfileCard._safe_clip(['a', 'b'], 100)
        self.assertIsInstance(out, str)

    def test_t5_build_likes_boundaries_dict(self):
        card = self._card()
        with patch.object(card, '_load_profile',
                          return_value={'conversational_boundaries':
                                        {'no_meetings_before_10': True}}):
            out = card._build_likes_boundaries()  # 不该抛 TypeError
        self.assertIsInstance(out.get('boundaries'), str)

    def test_t6_build_identity_dict_fields(self):
        card = self._card()
        with patch.object(card, '_load_profile',
                          return_value={'core_philosophy': {'x': 1},
                                        'work_rhythms': {'y': 2},
                                        'idiosyncrasies': ['a', 'b']}):
            out = card._build_identity()  # 不该抛 TypeError
        self.assertIsInstance(out.get('core_traits'), str)
        self.assertIsInstance(out.get('work_rhythm'), str)
        self.assertIsInstance(out.get('idiosyncrasies'), str)


def _build_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    tmp = os.path.join(tempfile.gettempdir(), f'profcrash_{time.time()}.jsonl')
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp
    try:
        d = InnerThoughtDaemon(key_router=None)
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp
    return d


def _mk_b_thought(actionable: str, sal: float = 0.9):
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id='t1', ts=time.time(), ts_iso='2026-05-31T22:17:00',
        category='B', thought='I was too verbose; I should be concise.',
        salience=sal, actionable=actionable,
    )


class _FakeTrack:
    def __init__(self):
        self.appends = []

    def recent(self, minutes=0.0, max_n=0):
        return []

    def append(self, **kw):
        self.appends.append(kw)


class TestSelfReflectionWantsVoiceGate(unittest.TestCase):
    """T7-T8: kind=empty 自省不 ★ spotlight (不泄漏字幕), 有效果才 ★。"""

    def setUp(self):
        self.d = _build_daemon()
        import jarvis_inner_thought_daemon as itd
        self.itd = itd

    def _run(self, actionable, sal=0.9):
        fake = _FakeTrack()
        with patch('jarvis_inner_voice_track.get_inner_voice_track',
                   return_value=fake), \
             patch('jarvis_inner_voice_track.is_enabled', return_value=True), \
             patch.object(self.itd, '_get_self_reflection_dedup_config',
                          return_value=(True, 30.0, 0.6)), \
             patch('jarvis_utils.get_event_bus', return_value=None):
            self.d._maybe_publish_self_correction(_mk_b_thought(actionable, sal))
        return fake

    def test_t7_empty_kind_no_wants_voice(self):
        fake = self._run('none', sal=0.9)
        self.assertTrue(fake.appends, 'B 反思应 append voice track')
        self.assertFalse(fake.appends[0]['wants_voice'],
                         'kind=empty (actionable=none) 不该 ★ spotlight (防字幕泄漏)')

    def test_t8_effectful_wants_voice(self):
        fake = self._run('propose_stance', sal=0.9)
        self.assertTrue(fake.appends, 'B 反思应 append voice track')
        self.assertTrue(fake.appends[0]['wants_voice'],
                        '高 sal + 真效果 (actionable!=none) 应 ★ spotlight')


if __name__ == '__main__':
    unittest.main(verbosity=2)
