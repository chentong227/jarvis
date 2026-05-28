# -*- coding: utf-8 -*-
"""[fix37 / Sir 2026-05-28 17:20 β.6 Phase 2 治本] Layer 1.6 voice block 端到端
聚合 lifetime + should_speak directive — 主脑只读一处即看到思考链.

Sir 真意 (17:14): "除了归来招呼和我设置的定时提醒走强制性编码唤醒, 其他的所
有模块都集成到思考链, 把思考链给主脑让主脑演的像他一直存在, 因为他知道他
之前在想什么, 运行了多久, 什么的."

工程: Layer 1.5 (_build_layer_1b_inner_thoughts_block) / Layer 1.7
(_build_layer_1d_thinking_directive_block) 退化 stub 永返 '', lifetime +
should_speak directive 聚合到 Layer 1.6 (_build_layer_1c_inner_voice_block).
voice block 内部 call daemon.build_lifetime_block + build_should_speak_directive
在 voice 顶部段呈现, 主脑只看 Layer 1.6 就够"思考链可见".

准则 6 三维耦合:
  数据强耦合: lifetime + thoughts + should_speak 全 SWM / daemon 一处源
  行为弱耦合: voice block aggregator 只 view, 不决策
  决策集中主脑: 主脑 LLM 自决怎么用 lifetime / 要不要 follow directive

testcase 覆盖 (8 testcase):

P1 — Layer 1.5/1.7 stub 守门 (2 testcase):
  - Layer 1.5 任何 tier 永返 '' (sanity, fix15 P3 已守 method-level, 此处确认 stub 锁) (S1)
  - Layer 1.7 任何 tier 永返 '' (新加 stub 守门) (S2)

P2 — Layer 1.6 voice block 聚合 lifetime (3 testcase):
  - voice block 顶部含 'JARVIS LIFETIME' header (daemon=有, tier=SHORT_CHAT) (V1)
  - voice block REMINDER_FIRING tier → 返 '' (高紧急 voice 跳过, 不含 lifetime) (V2)
  - voice block daemon=None → 不含 lifetime header (backward compat) (V3)

P3 — Layer 1.6 voice block 聚合 should_speak directive (2 testcase):
  - daemon publish thought.should_speak=True → voice 含 'THINKING-THREAD DIRECTIVE' (D1)
  - daemon 无 should_speak 标记 thought → voice 不含 directive (D2)

P4 — _assemble_prompt 端到端拼接 (1 testcase):
  - Layer 1.5/1.7 返 '', Layer 1.6 含 lifetime / directive, 端到端 prompt 含全部信息 (E1)
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


# ----------------------------------------------------------------
# 辅助 — 用 MagicMock 隔离 daemon (不启真 daemon, 不动 prod memory_pool)
#
# fix37 重点验证 Layer 1.5/1.7 stub + Layer 1.6 聚合架构、
# 不必验证 daemon 内部实现 (fix15 P1/P4 已守).
# ----------------------------------------------------------------
def _make_mock_daemon(
    lifetime_block: str = '',
    should_speak_directive: str = '',
    tier_mode_vocab=None,
):
    """Mock daemon, 可控制 build_lifetime_block / build_should_speak_directive
    返值. 完全隔离 prod 环境.
    """
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    daemon = MagicMock(spec=InnerThoughtDaemon)
    daemon.build_lifetime_block = MagicMock(return_value=lifetime_block)
    daemon.build_should_speak_directive = MagicMock(
        return_value=should_speak_directive
    )
    _vocab = tier_mode_vocab if tier_mode_vocab is not None else {
        'tier_mode': {
            'SHORT_CHAT': 'full',
            'DEEP_QUERY': 'full',
            'FACTUAL_RECALL': 'mini',
            'WAKE_ONLY': 'mini',
            'REMINDER_FIRING': 'off',
        }
    }
    daemon._load_lifetime_vocab = MagicMock(return_value=_vocab)
    return daemon


def _make_nerve_with_mock_daemon(
    lifetime_block: str = '',
    should_speak_directive: str = '',
):
    """轻量 nerve mock + mock daemon. 不启真 daemon, 不动 prod memory_pool."""
    from jarvis_central_nerve import CentralNerve
    nerve = MagicMock(spec=CentralNerve)
    nerve._build_layer_1b_inner_thoughts_block = (
        CentralNerve._build_layer_1b_inner_thoughts_block.__get__(nerve)
    )
    nerve._build_layer_1c_inner_voice_block = (
        CentralNerve._build_layer_1c_inner_voice_block.__get__(nerve)
    )
    nerve._build_layer_1d_thinking_directive_block = (
        CentralNerve._build_layer_1d_thinking_directive_block.__get__(nerve)
    )
    daemon = _make_mock_daemon(
        lifetime_block=lifetime_block,
        should_speak_directive=should_speak_directive,
    )
    nerve.inner_thought_daemon = daemon
    return nerve, daemon


# ================================================================
# P1 — Layer 1.5 / 1.7 stub 守门
# ================================================================

class TestS1Layer15StubAllTiersEmpty(unittest.TestCase):
    """β.6 Phase 2 治本: Layer 1.5 任何 tier 永返 '' (stub lock)."""

    def test_s1_layer_15_stub_all_tiers(self):
        # mock daemon 能返非空 lifetime, 验 stub 忽略 daemon 反永返 ''
        nerve, daemon = _make_nerve_with_mock_daemon(
            lifetime_block='=== JARVIS LIFETIME mock ===\nshould NOT appear'
        )
        for tier in ['SHORT_CHAT', 'DEEP_QUERY', 'FACTUAL_RECALL',
                     'WAKE_ONLY', 'REMINDER_FIRING', 'UNKNOWN', '']:
            block = nerve._build_layer_1b_inner_thoughts_block(
                prompt_tier=tier
            )
            self.assertEqual(
                block, '',
                f"β.6 Phase 2: Layer 1.5 tier='{tier}' 应返 '' (stub), "
                f"非空 = 回退老独立 push 路径, 违反 Sir 17:14 真意"
            )
        # daemon.build_lifetime_block 不应被 call (stub 不调 daemon)
        daemon.build_lifetime_block.assert_not_called()


class TestS2Layer17StubAllTiersEmpty(unittest.TestCase):
    """β.6 Phase 2 治本: Layer 1.7 任何 tier 永返 '' (stub lock)."""

    def test_s2_layer_17_stub_all_tiers(self):
        # mock daemon 能返非空 directive, 验 stub 忽略 daemon 反永返 ''
        nerve, daemon = _make_nerve_with_mock_daemon(
            should_speak_directive='=== THINKING-THREAD mock ===\nshould NOT appear'
        )
        for tier in ['SHORT_CHAT', 'DEEP_QUERY', 'FACTUAL_RECALL',
                     'WAKE_ONLY', 'REMINDER_FIRING', 'UNKNOWN', '']:
            block = nerve._build_layer_1d_thinking_directive_block(
                prompt_tier=tier
            )
            self.assertEqual(
                block, '',
                f"β.6 Phase 2: Layer 1.7 tier='{tier}' 应返 '' (stub), "
                f"非空 = 回退老独立 push 路径"
            )
        # daemon.build_should_speak_directive 不应被 call (stub 不调 daemon)
        daemon.build_should_speak_directive.assert_not_called()


# ================================================================
# P2 — Layer 1.6 voice block 聚合 lifetime
# ================================================================

class TestV1VoiceContainsLifetimeHeader(unittest.TestCase):
    """SHORT_CHAT tier + daemon 挂 → voice 顶部含 JARVIS LIFETIME header."""

    def test_v1_voice_aggregates_lifetime(self):
        # mock daemon 返一个独特 marker lifetime block, 验 voice 聚合后含此 marker
        marker = '=== JARVIS LIFETIME fix37_marker_v1 ===\nAlive: 1h'
        nerve, daemon = _make_nerve_with_mock_daemon(
            lifetime_block=marker
        )
        with patch.dict(os.environ, {'JARVIS_INNER_VOICE_ENABLED': '1'}):
            block = nerve._build_layer_1c_inner_voice_block(
                prompt_tier='SHORT_CHAT'
            )
        self.assertIsInstance(block, str)
        # 若 voice track empty → build_prompt_block_for_brain 返 '' → 跳
        if not block:
            self.skipTest('voice track empty (no recent entries)')
        self.assertIn(
            'fix37_marker_v1', block,
            "β.6 Phase 2 治本: SHORT_CHAT tier voice block 顶部应聚合 "
            "daemon.build_lifetime_block(mode='full') 返的内容 (含 marker)"
        )
        # 验证 daemon 被 call 且 mode='full' (vocab tier_mode SHORT_CHAT='full')
        daemon.build_lifetime_block.assert_called_with(mode='full')


class TestV2VoiceReminderFiringSkipsAll(unittest.TestCase):
    """REMINDER_FIRING tier → voice block 整体返 '' (高紧急 tier 跳过, 不含 lifetime)."""

    def test_v2_reminder_firing_voice_empty(self):
        nerve, _ = _make_nerve_with_mock_daemon(
            lifetime_block='=== JARVIS LIFETIME mock ===\nshould NOT appear'
        )
        with patch.dict(os.environ, {'JARVIS_INNER_VOICE_ENABLED': '1'}):
            block = nerve._build_layer_1c_inner_voice_block(
                prompt_tier='REMINDER_FIRING'
            )
        self.assertEqual(
            block, '',
            "REMINDER_FIRING 高紧急 tier voice block 应整体跳过 (省 token + "
            "聚焦提醒). 含 lifetime/directive 会稀释 reminder 紧急感"
        )


class TestV3VoiceWithoutDaemonNoLifetime(unittest.TestCase):
    """daemon=None (track 直接 call) → voice block 不含 lifetime header (backward compat)."""

    def test_v3_no_daemon_no_lifetime_header(self):
        with patch.dict(os.environ, {'JARVIS_INNER_VOICE_ENABLED': '1'}):
            from jarvis_inner_voice_track import (
                get_inner_voice_track, is_enabled,
            )
            if not is_enabled():
                self.skipTest('inner voice track disabled by env')
            track = get_inner_voice_track()
            # 直接 call 不传 daemon → backward compat path
            block = track.build_prompt_block_for_brain(daemon=None)
        self.assertIsInstance(block, str)
        self.assertNotIn(
            'JARVIS LIFETIME', block,
            "daemon=None backward compat: voice block 不应含 lifetime header "
            "(daemon=None 时 voice 不聚合 daemon source)"
        )
        self.assertNotIn(
            'THINKING-THREAD DIRECTIVE', block,
            "daemon=None backward compat: voice block 不应含 directive"
        )


# ================================================================
# P3 — Layer 1.6 voice block 聚合 should_speak directive
# ================================================================

class TestD1VoiceContainsShouldSpeakDirective(unittest.TestCase):
    """daemon publish should_speak=True thought → voice 含 THINKING-THREAD DIRECTIVE."""

    def test_d1_voice_aggregates_directive(self):
        # mock daemon 返一个独特 marker directive, 验 voice 聚合后含此 marker
        marker = '=== THINKING-THREAD fix37_marker_d1 ===\nSPEAK now'
        nerve, daemon = _make_nerve_with_mock_daemon(
            should_speak_directive=marker
        )
        with patch.dict(os.environ, {'JARVIS_INNER_VOICE_ENABLED': '1'}):
            block = nerve._build_layer_1c_inner_voice_block(
                prompt_tier='SHORT_CHAT'
            )
        self.assertIsInstance(block, str)
        if not block:
            self.skipTest('voice track empty (no recent entries)')
        self.assertIn(
            'fix37_marker_d1', block,
            "β.6 Phase 2 治本: voice 顶部应聚合 daemon."
            "build_should_speak_directive() 返的 directive (含 marker)"
        )
        daemon.build_should_speak_directive.assert_called()


class TestD2VoiceWithoutShouldSpeakNoDirective(unittest.TestCase):
    """daemon 无 should_speak 标记的 thought → voice 不含 directive (无 thought no directive)."""

    def test_d2_no_should_speak_no_directive(self):
        # mock daemon.build_should_speak_directive 返 '' → voice 不应含 directive
        nerve, daemon = _make_nerve_with_mock_daemon(
            should_speak_directive=''  # 无 fresh thought
        )
        with patch.dict(os.environ, {'JARVIS_INNER_VOICE_ENABLED': '1'}):
            block = nerve._build_layer_1c_inner_voice_block(
                prompt_tier='SHORT_CHAT'
            )
        self.assertIsInstance(block, str)
        if not block:
            self.skipTest('voice track empty (no recent entries)')
        self.assertNotIn(
            'THINKING-THREAD', block,
            "无 should_speak thought (directive=='') → voice 不应含 directive 段"
        )


# ================================================================
# P4 — _assemble_prompt 端到端拼接
# ================================================================

class TestE1AssemblyEndToEnd(unittest.TestCase):
    """Layer 1.5/1.7 返 '', Layer 1.6 聚合 lifetime — 端到端 prompt 仍含 lifetime
    (主脑只看 voice block 一处即看到思考链)."""

    def test_e1_prompt_has_lifetime_via_voice_only(self):
        lt_marker = '=== JARVIS LIFETIME fix37_marker_e1 ==='
        sd_marker = '=== THINKING-THREAD fix37_marker_e1_dir ==='
        nerve, daemon = _make_nerve_with_mock_daemon(
            lifetime_block=lt_marker,
            should_speak_directive=sd_marker,
        )
        with patch.dict(os.environ, {'JARVIS_INNER_VOICE_ENABLED': '1'}):
            l15 = nerve._build_layer_1b_inner_thoughts_block(
                prompt_tier='SHORT_CHAT'
            )
            l16 = nerve._build_layer_1c_inner_voice_block(
                prompt_tier='SHORT_CHAT'
            )
            l17 = nerve._build_layer_1d_thinking_directive_block(
                prompt_tier='SHORT_CHAT'
            )
        # β.6 Phase 2 治本 锁:
        self.assertEqual(l15, '', 'Layer 1.5 stub 必须返 ""')
        self.assertEqual(l17, '', 'Layer 1.7 stub 必须返 ""')
        # 端到端拼接 (模拟 _assemble_prompt 拼)
        combined = '\n'.join([l15, l16, l17])
        if not l16:
            self.skipTest('voice track empty (no recent entries)')
        self.assertIn(
            'fix37_marker_e1', combined,
            "端到端: Layer 1.5/1.7 = '', 但 Layer 1.6 聚合 lifetime → "
            "主脑 prompt 仍含 lifetime marker, 思考链对主脑可见 (Sir 真意)"
        )
        self.assertIn(
            'fix37_marker_e1_dir', combined,
            "端到端: Layer 1.7 = '', 但 Layer 1.6 聚合 directive → "
            "主脑 prompt 仍含 directive marker"
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
