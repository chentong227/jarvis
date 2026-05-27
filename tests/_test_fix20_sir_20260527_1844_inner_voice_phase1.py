# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 18:44 真愿景] InnerVoiceTrack Phase 1 (Step 1-4) 回归.

Sir 真愿景 (2026-05-27 18:44 三次自校 anchor):
  "你必须搞清楚你和 butler 在现象学上完全等同, 这一点不能有任何怀疑"
  "把贾维斯的"心声"做成一条 24/7 连续的内部时序轨道,
   独立于"对外说话"和"显性 inner_thought 列表" — 主脑被召唤时, 看的就是这条轨道."

Phase 1 工程 (5 step):
  Step 1: jarvis_inner_voice_track.py 新 module (InnerVoiceTrack + Entry +
          singleton + persist + 3 层视图 builder)
  Step 2: jarvis_inner_thought_daemon.py
          - 2a: _persist_thought → _append_to_voice_track (thought → voice)
          - 2b: _build_prompt 加 [INNER VOICE] block (思考脑读 voice tail)
  Step 3: jarvis_central_nerve.py 主脑 _assemble_prompt:
          - _build_layer_1c_inner_voice_block (Layer 1.6)
          - butler comportment directive (不 announce 'I was thinking X')
          - 拼接顺序 Layer 1.5 → 1.6 → 2
  Step 4: scripts/jarvis_dashboard_web.py:
          - /api/inner_voice JSON endpoint
          - /inner_voice page (heartbeat / stats / entries / prompt preview)
          - 顶部导航 🌊 心声 入口

测试覆盖 (12 testcase, 全静态 invariant 不启线程):

Phase 1 Step 1 — InnerVoiceTrack module (4 testcase):
  - IV1: module 可 import, get_inner_voice_track() singleton 同一实例
  - IV2: VoiceEntry dataclass 含必须字段 (ts/source/intent/content/
         urgency/wants_voice/meta)
  - IV3: is_enabled() 默认 True, env=0 时返 False
  - IV4: append() → recent() / all_recent() / stats() 闭环, 包括
         wants_voice_pending_30min 计数

Phase 1 Step 2 — InnerThought daemon 双向桥 (3 testcase):
  - IV5: jarvis_inner_thought_daemon 含 _append_to_voice_track 方法
  - IV6: _persist_thought 末尾调 _append_to_voice_track
  - IV7: _build_prompt 拼接代码含 '[INNER VOICE — past 10min' 标记
         (即思考脑 prompt 读 voice tail)

Phase 1 Step 3 — 主脑 Layer 1.6 + butler directive (3 testcase):
  - IV8: jarvis_central_nerve 含 _build_layer_1c_inner_voice_block 方法
  - IV9: _assemble_prompt 拼接含 inner_voice_block 调用 + append _parts
  - IV10: _build_layer_1c 含 BUTLER COMPORTMENT directive +
          'DO NOT announce' 教学 + ★ wants_voice 提示

Phase 1 Step 4 — Dashboard (2 testcase):
  - IV11: scripts/jarvis_dashboard_web 含 /api/inner_voice + /inner_voice route
  - IV12: 顶部导航 nav bar 含 🌊 心声 入口
"""
from __future__ import annotations

import os
import re
import sys
import time
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


# ============================================================
# Phase 1 Step 1 — InnerVoiceTrack module
# ============================================================

class TestStep1InnerVoiceTrack(unittest.TestCase):
    """Step 1: jarvis_inner_voice_track module 静态 invariant."""

    def test_iv1_module_importable_and_singleton(self):
        """IV1: module 可 import, get_inner_voice_track() singleton."""
        import jarvis_inner_voice_track as ivt
        self.assertTrue(hasattr(ivt, 'InnerVoiceTrack'))
        self.assertTrue(hasattr(ivt, 'VoiceEntry'))
        self.assertTrue(hasattr(ivt, 'get_inner_voice_track'))
        self.assertTrue(hasattr(ivt, 'is_enabled'))
        # singleton 同一实例
        t1 = ivt.get_inner_voice_track()
        t2 = ivt.get_inner_voice_track()
        self.assertIs(t1, t2)

    def test_iv2_voice_entry_dataclass_fields(self):
        """IV2: VoiceEntry 含必须字段."""
        from jarvis_inner_voice_track import VoiceEntry
        e = VoiceEntry(
            ts=time.time(),
            source='inner_thought',
            intent='observation',
            content='test',
            urgency=0.5,
            wants_voice=True,
            meta={'k': 'v'},
        )
        for field in ('ts', 'source', 'intent', 'content',
                        'urgency', 'wants_voice', 'meta'):
            self.assertTrue(hasattr(e, field),
                              f'VoiceEntry must have field {field!r}')
        # to_dict / from_dict roundtrip
        d = e.to_dict()
        self.assertEqual(d['source'], 'inner_thought')
        e2 = VoiceEntry.from_dict(d)
        self.assertEqual(e2.content, 'test')
        self.assertEqual(e2.wants_voice, True)

    def test_iv3_is_enabled_default_and_env(self):
        """IV3: is_enabled() 默认 True, env=0 时 False."""
        from jarvis_inner_voice_track import is_enabled
        # 默认 True (env 未设)
        old = os.environ.pop('JARVIS_INNER_VOICE_ENABLED', None)
        try:
            self.assertTrue(is_enabled())
            os.environ['JARVIS_INNER_VOICE_ENABLED'] = '0'
            self.assertFalse(is_enabled())
            os.environ['JARVIS_INNER_VOICE_ENABLED'] = '1'
            self.assertTrue(is_enabled())
        finally:
            os.environ.pop('JARVIS_INNER_VOICE_ENABLED', None)
            if old is not None:
                os.environ['JARVIS_INNER_VOICE_ENABLED'] = old

    def test_iv4_append_recent_stats_closure(self):
        """IV4: append → recent / all_recent / stats 闭环."""
        from jarvis_inner_voice_track import InnerVoiceTrack
        # 用临时 file 隔离, 不污染真 memory_pool
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            persist = os.path.join(td, 'iv_test.jsonl')
            track = InnerVoiceTrack(persist_path=persist)
            now = time.time()
            track.append(
                source='inner_thought', intent='observation',
                content='now-thought wants voice',
                urgency=0.8, wants_voice=True, ts=now,
            )
            track.append(
                source='sensor', intent='observation',
                content='sir afk 5min',
                urgency=0.2, wants_voice=False, ts=now - 60,
            )
            # 1 hour ago — 不在 10min recent
            track.append(
                source='care_trigger', intent='care',
                content='hydration nudge',
                urgency=0.6, wants_voice=True, ts=now - 3700,
            )
            # recent 10min
            recent_10 = track.recent(minutes=10.0)
            self.assertEqual(len(recent_10), 2,
                              f'should have 2 in last 10min, got {len(recent_10)}')
            # all_recent 24h
            all_24 = track.all_recent(hours=24.0)
            self.assertEqual(len(all_24), 3)
            # stats
            s = track.stats()
            self.assertEqual(s['total'], 3)
            self.assertEqual(s['last_10min'], 2)
            self.assertEqual(s['last_1h'], 2)
            # wants_voice_pending_30min: 只统 wants_voice=True 且 30min 内
            # 第 1 条 wants_voice=True ts=now → 在 30min 内
            # 第 3 条 wants_voice=True ts=now-3700 → 超 30min
            self.assertEqual(s['wants_voice_pending_30min'], 1)
            # build_prompt_block_for_brain 不 raise + 含已 append 内容
            blk = track.build_prompt_block_for_brain(
                max_chars=2000, show_l3=True
            )
            self.assertIsInstance(blk, str)
            self.assertIn('now-thought', blk)


# ============================================================
# Phase 1 Step 2 — InnerThought daemon 双向桥
# ============================================================

class TestStep2DaemonBridge(unittest.TestCase):
    """Step 2: daemon → voice append + 思考脑 prompt 读 voice."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(_REPO, 'jarvis_inner_thought_daemon.py')
        with open(path, 'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_iv5_daemon_has_append_to_voice_track_method(self):
        """IV5: daemon 含 _append_to_voice_track 方法."""
        self.assertIn(
            'def _append_to_voice_track(',
            self.src,
            '_append_to_voice_track method must exist'
        )

    def test_iv6_persist_thought_calls_append_to_voice_track(self):
        """IV6: _persist_thought 调 _append_to_voice_track (顺序: persist → voice append)."""
        # 找 _persist_thought 定义
        m = re.search(
            r'def _persist_thought\(.*?\n(.*?)(?=\n    def |\nclass )',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m, '_persist_thought def not found')
        body = m.group(1)
        self.assertIn(
            'self._append_to_voice_track(',
            body,
            '_persist_thought must call self._append_to_voice_track(...)'
        )

    def test_iv7_build_prompt_has_inner_voice_block(self):
        """IV7: _build_prompt 拼接含 [INNER VOICE 标记."""
        # 找 _build_prompt 定义
        m = re.search(
            r'def _build_prompt\(.*?\n(.*?)(?=\n    def |\nclass )',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m, '_build_prompt def not found')
        body = m.group(1)
        self.assertIn(
            '[INNER VOICE',
            body,
            '_build_prompt must inject [INNER VOICE block'
        )
        # 必须 from jarvis_inner_voice_track import
        self.assertIn(
            'jarvis_inner_voice_track',
            body,
            '_build_prompt must import jarvis_inner_voice_track'
        )


# ============================================================
# Phase 1 Step 3 — 主脑 Layer 1.6 + butler directive
# ============================================================

class TestStep3MainBrainLayer16(unittest.TestCase):
    """Step 3: 主脑 _assemble_prompt Layer 1.6 inner_voice."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(_REPO, 'jarvis_central_nerve.py')
        with open(path, 'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_iv8_central_nerve_has_layer_1c_builder(self):
        """IV8: jarvis_central_nerve 含 _build_layer_1c_inner_voice_block."""
        self.assertIn(
            'def _build_layer_1c_inner_voice_block(',
            self.src,
            '_build_layer_1c_inner_voice_block method must exist'
        )

    def test_iv9_assemble_prompt_appends_inner_voice_block(self):
        """IV9: _assemble_prompt 含 inner_voice_block 调用 + append _parts."""
        m = re.search(
            r'def _assemble_prompt\(.*?\n(.*?)(?=\n    def |\nclass )',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m, '_assemble_prompt def not found')
        body = m.group(1)
        # 必须调 _build_layer_1c_inner_voice_block
        self.assertIn(
            '_build_layer_1c_inner_voice_block(',
            body,
            '_assemble_prompt must call _build_layer_1c_inner_voice_block'
        )
        # 必须 append 进 _parts
        self.assertTrue(
            re.search(
                r'if inner_voice_block:\s*\n\s+_parts\.append\(inner_voice_block\)',
                body,
            ),
            '_assemble_prompt must append inner_voice_block to _parts'
        )

    def test_iv10_layer_1c_has_butler_comportment_directive(self):
        """IV10: _build_layer_1c 含 BUTLER COMPORTMENT 教学."""
        m = re.search(
            r'def _build_layer_1c_inner_voice_block\(.*?\n(.*?)(?=\n    def |\nclass )',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m, '_build_layer_1c_inner_voice_block def not found')
        body = m.group(1)
        # butler directive 必须含的关键句
        self.assertIn(
            'BUTLER COMPORTMENT',
            body,
            'Layer 1.6 must include [BUTLER COMPORTMENT] directive header'
        )
        self.assertIn(
            'DO NOT announce',
            body,
            'Layer 1.6 must teach: DO NOT announce (NPC-speak)'
        )
        # wants_voice ★ 教学
        self.assertTrue(
            'wants_voice' in body or '★' in body,
            'Layer 1.6 must mention wants_voice / ★ items'
        )
        # tier skip 逻辑 (WAKE_ONLY / REMINDER_FIRING)
        self.assertIn(
            'WAKE_ONLY',
            body,
            'Layer 1.6 must skip WAKE_ONLY tier (省 token)'
        )


# ============================================================
# Phase 1 Step 4 — Dashboard
# ============================================================

class TestStep4Dashboard(unittest.TestCase):
    """Step 4: dashboard /inner_voice + API."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(_REPO, 'scripts', 'jarvis_dashboard_web.py')
        with open(path, 'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_iv11_dashboard_has_inner_voice_route_and_api(self):
        """IV11: dashboard 含 /api/inner_voice + /inner_voice route."""
        self.assertIn(
            "@app.route('/api/inner_voice')",
            self.src,
            '/api/inner_voice route must be registered'
        )
        self.assertIn(
            "@app.route('/inner_voice')",
            self.src,
            '/inner_voice page route must be registered'
        )
        self.assertIn(
            'def api_inner_voice(',
            self.src,
        )
        self.assertIn(
            'def page_inner_voice(',
            self.src,
        )

    def test_iv12_nav_bar_has_inner_voice_entry(self):
        """IV12: 顶部导航 nav bar 含 🌊 心声 入口."""
        # 必须 href="/inner_voice" + 显示文本 '心声'
        self.assertTrue(
            re.search(
                r'href="/inner_voice"',
                self.src,
            ),
            'nav bar must have href="/inner_voice" link'
        )
        self.assertIn(
            '🌊 心声',
            self.src,
            'nav bar must display 🌊 心声 label'
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
