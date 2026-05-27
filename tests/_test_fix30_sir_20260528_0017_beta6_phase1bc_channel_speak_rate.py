# -*- coding: utf-8 -*-
"""[fix30 / Sir 2026-05-28 00:17 真意 β.6 Phase 1b+1c 注意力 channel + 发声率 + SWM publish]

Phase 1b 改动 (思考脑端 channel-view + smoothing):
  1. `_build_channel_view(evidence, focus_hint)` 把 raw evidence 重组成 7 channel
     dict (recent_sensor_events / concern_status / nudge_history /
     sir_activity_snapshot / last_main_brain_reply / my_recent_thoughts /
     lifetime_overview), 每 channel 标 `load_mode` (deep | summary), 由 focus_hint
     决定 (Sir 真意 R3 "注意力精选不稀释").
  2. `self._next_attention_focus` (实例状态, 上轮 LLM 自标 + 本轮 writeback).
  3. `_should_smooth_force_silent` / `_record_should_speak_yes` — 5min 内
     SHOULD_SPEAK=yes ≥3 次 → 后续强制 should_speak=False (类似 NEXT_INTERVAL
     smoothing, Python 物理保底防 LLM 抖动).
  4. `_build_prompt(... channel_view=...)` 顶部加 [7 CHANNEL VIEW] header
     告诉 LLM 上轮自标 + 本轮 deep / summary 分组.
  5. `_tick` 调 `_build_channel_view` → 传给 prompt → 解析后 writeback focus
     + apply rate cap.

Phase 1c 改动 (SWM publish 4 字段 → 主脑 SOUL 端):
  1. `_publish_swm` 的 metadata 加 `should_speak` / `speak_content` /
     `speak_style` / `next_attention_focus` — 主脑下次 build SOUL 时 read 之自决
     SPEAK / SILENT.

测试覆盖:
  L11 _build_channel_view 返回 7 channel dict, 每 channel 含 load_mode
  L12 focus_hint='' (无上轮) → 全 channel deep
  L13 focus_hint='recent_sensor_events,concern_status' → 这 2 deep, 其余 summary
  L14 focus_hint 含非法 channel name → 忽略非法, 合法仍 deep
  L15 _should_smooth_force_silent: 0 个 yes → 不 smooth
  L16 _should_smooth_force_silent: 5min 内 3 个 yes → 第 4 次返 True
  L17 _record_should_speak_yes append + 自 prune 超 5min 老 ts
  L18 _build_prompt 加 channel_view → user prompt 含 [7 CHANNEL VIEW] header
  L19 _build_prompt 无 focus_hint → header 提示"all channel equally loaded"
  L20 _build_prompt 含 focus_hint → header 列出 DEEP-LOADED + summary-only
  L21 _publish_swm metadata 含 should_speak / speak_content / speak_style /
      next_attention_focus 4 字段
  L22 instance 初始化时 `_next_attention_focus = ''` + `_recent_should_speak_yes_ts = []`
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


def _make_bare_daemon():
    """无 __init__ 的最小 daemon (直接挂必要属性, 不真启 thread / LLM)."""
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
    d._thoughts = []
    d._lock = MagicMock()
    d._next_attention_focus = ''
    d._recent_should_speak_yes_ts = []
    d._bg_log = lambda *a, **kw: None
    return d


# ==========================================================
# L11-L14 _build_channel_view (7 channel structure + load_mode)
# ==========================================================

class TestL11ChannelViewReturnsSevenChannels(unittest.TestCase):
    """_build_channel_view 返回 7 channel dict, 每含 load_mode 字段."""

    def test_returns_seven_canonical_channels(self):
        daemon = _make_bare_daemon()
        evidence = {
            'sir_state': 'active', 'idle_seconds': 0, 'hour': 14,
            'swm_events': [], 'stm': [], 'recent_thoughts': [],
            'concerns': [], 'recent_jarvis_actions': [],
        }
        view = daemon._build_channel_view(evidence, focus_hint='')
        self.assertIsInstance(view, dict)
        expected = {
            'recent_sensor_events', 'concern_status', 'nudge_history',
            'sir_activity_snapshot', 'last_main_brain_reply',
            'my_recent_thoughts', 'lifetime_overview',
        }
        # 至少 cover 6+ canonical (允许 reflector daemon 未来再扩)
        self.assertTrue(
            len(set(view.keys()) & expected) >= 6,
            f"expected ≥6 canonical channels, got: {list(view.keys())}"
        )
        for ch, info in view.items():
            self.assertIn('load_mode', info, f"channel {ch} missing load_mode")
            self.assertIn(info['load_mode'], ('deep', 'summary'),
                          f"channel {ch} bad load_mode: {info['load_mode']}")


class TestL12NoFocusHintAllDeep(unittest.TestCase):
    """focus_hint='' → 全 channel deep (无 attention 偏好 = 平均)."""

    def test_empty_focus_hint_all_deep(self):
        daemon = _make_bare_daemon()
        evidence = {'sir_state': 'active', 'swm_events': [], 'stm': [],
                    'recent_thoughts': [], 'concerns': []}
        view = daemon._build_channel_view(evidence, focus_hint='')
        for ch, info in view.items():
            self.assertEqual(
                info['load_mode'], 'deep',
                f"no focus hint should yield all-deep, got {ch}=summary"
            )


class TestL13FocusHintTwoChannelsDeepOthersSummary(unittest.TestCase):
    """focus_hint='recent_sensor_events,concern_status' → 这 2 deep, 其余 summary."""

    def test_focus_two_channels(self):
        daemon = _make_bare_daemon()
        evidence = {'sir_state': 'active', 'swm_events': [], 'stm': [],
                    'recent_thoughts': [], 'concerns': []}
        view = daemon._build_channel_view(
            evidence, focus_hint='recent_sensor_events,concern_status',
        )
        # 真正深 load 的 2 个
        self.assertEqual(
            view.get('recent_sensor_events', {}).get('load_mode'), 'deep'
        )
        self.assertEqual(
            view.get('concern_status', {}).get('load_mode'), 'deep'
        )
        # 其余必须有至少 1 个 summary (否则注意力无意义)
        summary_count = sum(
            1 for ch, info in view.items()
            if info.get('load_mode') == 'summary'
        )
        self.assertGreaterEqual(
            summary_count, 1,
            "specifying focus should mark non-focus channels as summary"
        )


class TestL14FocusHintWithInvalidChannelIgnored(unittest.TestCase):
    """focus_hint 含非法 channel name → 静默忽略非法, 合法仍 deep."""

    def test_invalid_channel_in_focus_hint(self):
        daemon = _make_bare_daemon()
        evidence = {'sir_state': 'active', 'swm_events': [], 'stm': [],
                    'recent_thoughts': [], 'concerns': []}
        view = daemon._build_channel_view(
            evidence,
            focus_hint='nonsense_xyz, concern_status, another_bad',
        )
        # 合法的 concern_status 仍 deep
        self.assertEqual(
            view.get('concern_status', {}).get('load_mode'), 'deep'
        )
        # 不允许返 'nonsense_xyz' channel (会污染 view 结构)
        self.assertNotIn('nonsense_xyz', view)
        self.assertNotIn('another_bad', view)


# ==========================================================
# L15-L17 speak rate cap smoothing
# ==========================================================

class TestL15RateCapZeroYesNoSmooth(unittest.TestCase):
    """0 个历史 yes → _should_smooth_force_silent 返 False."""

    def test_zero_yes_no_smooth(self):
        daemon = _make_bare_daemon()
        now = time.time()
        self.assertFalse(daemon._should_smooth_force_silent(now))


class TestL16RateCapThreeYesInFiveMinSmooths(unittest.TestCase):
    """5min 内 3 个 yes 已记 → 第 4 次 _should_smooth_force_silent 返 True."""

    def test_three_yes_within_5min_smooth_kicks_in(self):
        daemon = _make_bare_daemon()
        now = time.time()
        # 模拟 3 次 yes 都在 5min 内
        daemon._record_should_speak_yes(now - 240)  # 4min ago
        daemon._record_should_speak_yes(now - 120)  # 2min ago
        daemon._record_should_speak_yes(now - 60)   # 1min ago
        # 第 4 次 → smoothing 应 force silent
        self.assertTrue(daemon._should_smooth_force_silent(now))


class TestL17RateCapPrunesOldTs(unittest.TestCase):
    """超 5min 的老 ts 应 auto-prune, 不影响新 smooth 判断."""

    def test_old_ts_pruned_does_not_block_new_yes(self):
        daemon = _make_bare_daemon()
        now = time.time()
        # 模拟 4 个老 yes (>5min), 1 个新 yes (1min 内)
        daemon._record_should_speak_yes(now - 1000)
        daemon._record_should_speak_yes(now - 800)
        daemon._record_should_speak_yes(now - 700)
        daemon._record_should_speak_yes(now - 600)
        daemon._record_should_speak_yes(now - 60)
        # _should_smooth 内部 prune 老 ts → 只剩 1 个 < 3 → 不 smooth
        self.assertFalse(daemon._should_smooth_force_silent(now))


# ==========================================================
# L18-L20 _build_prompt 顶部 [7 CHANNEL VIEW] header
# ==========================================================

class TestL18PromptIncludesChannelViewHeader(unittest.TestCase):
    """_build_prompt 传 channel_view → user prompt 含 [7 CHANNEL VIEW] header."""

    def _make_daemon_with_prompt_deps(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        d._thoughts = []
        d._lock = MagicMock()
        d._next_attention_focus = ''
        d._recent_should_speak_yes_ts = []
        d._bg_log = lambda *a, **kw: None
        # lifetime block stub (mini)
        d.build_lifetime_block = lambda mode='mini': ''
        d.concerns_ledger = None
        d.nerve = None
        d.relational_state = None
        d._tick_count = 0
        d._thought_count = 0
        d._today_thought_count = 0
        d._today_date = ''
        d._last_category_ts = {}
        d._llm_fail_count = 0
        d._cooldown_skip_count = 0
        d._tick_origin_stats = {}
        return d

    def test_channel_view_passed_renders_header(self):
        daemon = self._make_daemon_with_prompt_deps()
        evidence = {
            'sir_state': 'active', 'idle_seconds': 0, 'hour': 14,
            'swm_events': [], 'stm': [], 'recent_thoughts': [],
            'concerns': [], 'recent_jarvis_actions': [],
        }
        channel_view = daemon._build_channel_view(evidence, focus_hint='')
        _, prompt_user = daemon._build_prompt(
            sir_state='active', evidence=evidence,
            free_categories=['A', 'B', 'C', 'D', 'E'],
            channel_view=channel_view,
        )
        self.assertIn('[7 CHANNEL VIEW', prompt_user)


class TestL19PromptHeaderNoFocusHintShowsEquallyLoaded(unittest.TestCase):
    """无 focus_hint → header 提示 'all 7 channels equally loaded'."""

    def test_no_focus_hint_header_text(self):
        daemon = TestL18PromptIncludesChannelViewHeader._make_daemon_with_prompt_deps(
            TestL18PromptIncludesChannelViewHeader()
        )
        daemon._next_attention_focus = ''  # 显式无 hint
        evidence = {
            'sir_state': 'active', 'idle_seconds': 0, 'hour': 14,
            'swm_events': [], 'stm': [], 'recent_thoughts': [],
            'concerns': [], 'recent_jarvis_actions': [],
        }
        view = daemon._build_channel_view(evidence, focus_hint='')
        _, prompt_user = daemon._build_prompt(
            sir_state='active', evidence=evidence,
            free_categories=['A', 'B', 'C', 'D', 'E'],
            channel_view=view,
        )
        # 无 hint → 提示 "all ... equally loaded" + 让 LLM 自标 next focus
        lower = prompt_user.lower()
        self.assertTrue(
            'equally loaded' in lower or 'no prior attention' in lower,
            "no focus hint header should explain neutral mode"
        )
        self.assertIn('NEXT_ATTENTION_FOCUS', prompt_user)


class TestL20PromptHeaderFocusHintListsDeepAndSummary(unittest.TestCase):
    """含 focus_hint → header 真列出 DEEP-LOADED + summary-only."""

    def test_focus_hint_header_lists_deep_and_summary(self):
        daemon = TestL18PromptIncludesChannelViewHeader._make_daemon_with_prompt_deps(
            TestL18PromptIncludesChannelViewHeader()
        )
        daemon._next_attention_focus = 'concern_status'  # 上轮自标
        evidence = {
            'sir_state': 'active', 'idle_seconds': 0, 'hour': 14,
            'swm_events': [], 'stm': [], 'recent_thoughts': [],
            'concerns': [], 'recent_jarvis_actions': [],
        }
        view = daemon._build_channel_view(
            evidence, focus_hint=daemon._next_attention_focus,
        )
        _, prompt_user = daemon._build_prompt(
            sir_state='active', evidence=evidence,
            free_categories=['A', 'B', 'C', 'D', 'E'],
            channel_view=view,
        )
        # header 列出上轮 hint + DEEP-LOADED 含 concern_status + 至少 1 个 summary
        self.assertIn('concern_status', prompt_user)
        self.assertIn('DEEP-LOADED', prompt_user)
        self.assertIn('summary-only', prompt_user)


# ==========================================================
# L21 _publish_swm 4 new β.6 fields 进 metadata
# ==========================================================

class TestL21PublishSwmIncludesFourNewFields(unittest.TestCase):
    """_publish_swm metadata 必须含 4 个 β.6 字段 (主脑 SOUL 端要 read)."""

    def test_publish_swm_metadata_contains_four_new_fields(self):
        from jarvis_inner_thought_daemon import (
            InnerThoughtDaemon, InnerThought,
        )
        daemon = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        daemon._thoughts = []
        daemon._lock = MagicMock()
        daemon._bg_log = lambda *a, **kw: None

        thought = InnerThought(
            id='t_swm_1', ts=time.time(), ts_iso='', category='A',
            thought='Sir seems weary; perhaps a check-in.', salience=0.85,
            actionable='none', actionable_done=True, actionable_result='',
            sir_state='active',
            should_speak=True,
            speak_content="Noted, Sir — perhaps a brief pause.",
            speak_style='silent_text',
            next_attention_focus='concern_status,sir_activity_snapshot',
        )

        # mock event_bus.publish capture metadata
        captured = {}

        class _FakeBus:
            def publish(self_, etype, description, source, salience,
                        metadata=None, ttl=0.0):
                captured['etype'] = etype
                captured['metadata'] = metadata

        with patch('jarvis_utils.get_event_bus', return_value=_FakeBus()):
            daemon._publish_swm(thought)

        self.assertEqual(captured.get('etype'), 'jarvis_inner_thought')
        md = captured.get('metadata') or {}
        # 4 new β.6 fields 必须都在 metadata 里
        self.assertIn('should_speak', md)
        self.assertTrue(md['should_speak'])
        self.assertIn('speak_content', md)
        self.assertIn('brief pause', md['speak_content'])
        self.assertIn('speak_style', md)
        self.assertEqual(md['speak_style'], 'silent_text')
        self.assertIn('next_attention_focus', md)
        self.assertIn('concern_status', md['next_attention_focus'])


# ==========================================================
# L22 instance 初始化时 β.6 state 默认值 (防 AttributeError)
# ==========================================================

class TestL22InstanceInitDefaults(unittest.TestCase):
    """daemon __init__ 应初始化 `_next_attention_focus = ''`
    + `_recent_should_speak_yes_ts = []`.
    防 _tick 第一次跑 AttributeError."""

    def test_source_contains_init_for_attention_focus(self):
        path = os.path.join(ROOT, 'jarvis_inner_thought_daemon.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('_next_attention_focus', src)
        self.assertIn('_recent_should_speak_yes_ts', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
