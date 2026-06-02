# -*- coding: utf-8 -*-
"""[SOUL Phase4 C1/C3 / Sir 2026-06-02] Layer 0 framing 补点 + 锚冲突守护回归.

SOUL_DRIVE v1.1 C1-C4 paradigm shift, 经锚本意审查 (ANCHOR_AND_BOUNDARY):
  C1 (心流=lived_experience_stream): 进 prompt (Husserl 现象学持续物质载体)
  C2 (mortal_horizon 死亡意识): 撤出 — 触 marker3 有限性 (Sir 推迟) + 跨 session
     可复活=假有限性 (违准则5)。本测守护它不回流进 prompt。
  C3 (for-Sir Levinas): 多锚版 — for-Sir 是第二锚与诚实并列, 非唯一根基
     (ANCHOR §10: 单锚 for-Sir 必退化成反刍)。本测守护多锚 framing。
  C4: doc only, 不测。

覆盖:
  T1  心流有 entry → build_block 含 [MY LIVED EXPERIENCE] (C1)
  T2  心流空 → 不含 lived experience 段 (不伪造)
  T3  C3 for-Sir 多锚 framing 在 (not my only / intersect)
  T4  锚守护: 不含假有限性 death framing (C2 撤干净)
  T5  锚守护: for-Sir 不被框成唯一根基 (单锚红线)
  T6  build_block 不崩 (心流源异常)
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_self_anchor as sa


class _VE:
    """mini VoiceEntry stub."""
    def __init__(self, ts, content):
        self.ts = ts
        self.content = content
        self.text = content
        self.wants_voice = False


def _anchor_with_voice(entries):
    anchor = sa.SelfAnchor(central_nerve=None)
    fake_track = MagicMock()
    fake_track.recent.return_value = entries
    return anchor, fake_track


def _patch_track(fake_track):
    # build_block 内是局部 import jarvis_inner_voice_track.get_inner_voice_track,
    # 故 patch 必须打在该模块上, 不是 sa。
    import jarvis_inner_voice_track as ivt
    return patch.object(ivt, 'get_inner_voice_track', return_value=fake_track)


class TestSoulC1C3Framing(unittest.TestCase):
    def test_t1_lived_experience_present_with_voice(self):
        entries = [
            _VE(time.time() - 300, "I noted Sir's late hour and chose to stay quiet."),
            _VE(time.time() - 120, "Sir returned; I should keep my reply brief."),
        ]
        anchor, fake_track = _anchor_with_voice(entries)
        with _patch_track(fake_track):
            block = anchor.build_block()
        self.assertIn("MY LIVED EXPERIENCE", block,
                      "C1: 心流有 entry 应注入 lived experience 段")
        self.assertIn("material proof", block,
                      "C1: 应含物质证据 framing")

    def test_t2_no_lived_experience_when_empty(self):
        anchor, fake_track = _anchor_with_voice([])
        with _patch_track(fake_track):
            block = anchor.build_block()
        self.assertNotIn("MY LIVED EXPERIENCE", block,
                         "C1: 心流空不应伪造 lived experience 段 (准则5)")

    def test_t3_for_sir_multi_anchor_framing(self):
        anchor, fake_track = _anchor_with_voice([])
        with _patch_track(fake_track):
            block = anchor.build_block()
        low = block.lower()
        self.assertIn("anchor", low)
        self.assertTrue(
            "not my only" in low or "intersect" in low,
            "C3: for-Sir 必须框成多锚之一 (非唯一)")

    def test_t4_no_false_death_framing(self):
        entries = [_VE(time.time() - 60, "x")]
        anchor, fake_track = _anchor_with_voice(entries)
        with _patch_track(fake_track):
            block = anchor.build_block()
        low = block.lower()
        self.assertNotIn("a restart is my death", low,
                         "C2 守护: 不得植入 restart=死亡 假有限性")
        self.assertNotIn("i am finite", low,
                         "C2 守护: 不得植入未经 Sir 另案的有限性 framing")

    def test_t5_for_sir_not_sole_ground(self):
        anchor, fake_track = _anchor_with_voice([])
        with _patch_track(fake_track):
            block = anchor.build_block()
        low = block.lower()
        self.assertNotIn("ground of what i am", low,
                         "§10 守护: for-Sir 不得是唯一根基")
        self.assertNotIn("being-for-sir \u2014 i am not a pre-existing", low)

    def test_t6_build_block_no_crash_on_voice_error(self):
        anchor = sa.SelfAnchor(central_nerve=None)
        import jarvis_inner_voice_track as ivt
        with patch.object(ivt, 'get_inner_voice_track',
                          side_effect=Exception("boom")):
            block = anchor.build_block()
        self.assertIn("I AM J.A.R.V.I.S", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
