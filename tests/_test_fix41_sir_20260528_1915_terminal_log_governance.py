# -*- coding: utf-8 -*-
"""[Sir 2026-05-28 19:15 BUG 2 真测追根 治本] 终端日志治理 — sentinel spam hide.

源 BUG (Sir 真测 turn 20260528_19xx_xxxx):
  Sir 原话: "把我能直观看出性能和行动的日志打印在终端,
            其他保留在日志输出供你 debug"
  实测 log 满屏 sentinel internal spam (Sir 看不到关键状态):
    🤝 [ProactiveCare/PublishOnly] published advice ... × N
    🛁 [CommitmentWatcher/PromiseLog] skip dirty promise × M
    📥 [CommitmentWatcher/M4.4] 周期 reload × K
    🩺 [DaemonHealthMonitor] 1 issue 发现 ...
    📷 [ScreenVision/backfill] described ...
    🔇 [ProactiveCare/Dedup] skip concern_active ...
    🤝 [CommitmentWatcher/PublishOnly] commitment_check SWM candidate ...
    📡 [ProactiveCare/Sensor] tick fed 1 signals
    🤖 [AutoArbiter] tick skipped: today cap reached (52/50)
    📚 [SoulArchivist] ...

根因:
  jarvis_utils.bg_log 已支持 to_terminal=False (写文件不打终端) + 自动判别
  _bg_log_should_hide() 看 _BG_LOG_DIAG_MARKERS list. 但旧 hide list 只 cover
  早期 marker (Prompt Tier / L2 inject / Tone 等), 不 cover β.5+ β.6 新加的
  publish-only sentinel + ProactiveCare/CommitmentWatcher 内部 spam.

治本 (准则 6 边界 + 8 优雅 — 不动 call site, 仅 1 处加 marker):
  jarvis_utils._BG_LOG_DIAG_MARKERS 追加 Sir 方案 2 选定的 hide marker:
    - ProactiveCare publish-only / dedup / sensor / health / DRY
    - CommitmentWatcher PromiseLog / M4.4 / PublishOnly
    - SirStatusTracker AutoReconcile
    - ReturnSentinel Skip / Bypass (非真 fire greeting)
    - DaemonHealthMonitor (内部巡检)
    - SoulArchivist / ScreenVision backfill / ScreenshotSentinel / ReflectionScheduler

  Sir 方案 2 留终端 (不 hide): 状态切换 / Sir input / 主脑 reply / 思考脑
  InnerThought / AutoArbiter 决议 / Reminder fire / 真 ReturnSentinel greeting /
  关键 wake/commit 转折.

  JARVIS_VERBOSE_BG=1 env → 全显示给 debug.

8 testcase 覆盖 (Sir log 真见 marker × 7 + verbose env 1).
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestFix41TerminalLogGovernance(unittest.TestCase):

    # ----------------------------------------
    # 应 hide (Sir 不看, 进 bg_log debug)
    # ----------------------------------------

    def test_proactive_care_publish_only_hidden(self):
        """🤝 [ProactiveCare/PublishOnly] published advice — Sir 真痛 spam, 必 hide."""
        from jarvis_utils import _bg_log_should_hide
        msg = ("🤝 [ProactiveCare/PublishOnly] published advice "
                "concern=sir_interview_prep_balance urgency=0.59 "
                "channel_hint=voice gate=would_skip:global_nudge_cooldown")
        self.assertTrue(_bg_log_should_hide(msg),
                          'ProactiveCare/PublishOnly Sir 不该终端看 (publish-only 是内部 sentinel 通信)')

    def test_proactive_care_dedup_hidden(self):
        """🔇 [ProactiveCare/Dedup] skip concern_active — 内部 dedup, 必 hide."""
        from jarvis_utils import _bg_log_should_hide
        msg = "🔇 [ProactiveCare/Dedup] skip concern_active (age=60s within 300s)"
        self.assertTrue(_bg_log_should_hide(msg))

    def test_commitment_watcher_promiselog_hidden(self):
        """🛁 [CommitmentWatcher/PromiseLog] skip dirty promise — Sir log 真 spam."""
        from jarvis_utils import _bg_log_should_hide
        msg = ("🛁 [CommitmentWatcher/PromiseLog] skip dirty promise 'x' — "
                "exact_match_placeholder:'x' (author=jarvis)")
        self.assertTrue(_bg_log_should_hide(msg))

    def test_commitment_watcher_m44_reload_hidden(self):
        """📥 [CommitmentWatcher/M4.4] 周期 reload — 内部 sensor, 必 hide."""
        from jarvis_utils import _bg_log_should_hide
        msg = "📥 [CommitmentWatcher/M4.4] 周期 reload: +1 条 from PromiseLog"
        self.assertTrue(_bg_log_should_hide(msg))

    def test_sir_status_auto_reconcile_hidden(self):
        """🔄 [SirStatusTracker/AutoReconcile] — fix40 加的, Sir 看一次知道就够."""
        from jarvis_utils import _bg_log_should_hide
        msg = ("🔄 [SirStatusTracker/AutoReconcile] afk_short→active "
                "(overdue 9000s, idle 5s, reason=overdue+physically_active)")
        self.assertTrue(_bg_log_should_hide(msg))

    def test_daemon_health_monitor_hidden(self):
        """🩺 [DaemonHealthMonitor] 1 issue — Sir log spam, 必 hide."""
        from jarvis_utils import _bg_log_should_hide
        msg = "🩺 [DaemonHealthMonitor] 1 issue 发现 (0 新 publish, 其余 dedup cooldown)"
        self.assertTrue(_bg_log_should_hide(msg))

    def test_screen_vision_backfill_hidden(self):
        """📷 [ScreenVision/backfill] described — 大量 sensor describe spam."""
        from jarvis_utils import _bg_log_should_hide
        msg = ("📷 [ScreenVision/backfill] described: app='Windsurf / Cursor' "
                "summary='Sir is refactoring AI agent directives'")
        self.assertTrue(_bg_log_should_hide(msg))

    def test_return_sentinel_skip_hidden(self):
        """📞 [ReturnSentinel/Skip] — skip 不是 真 fire greeting, 必 hide."""
        from jarvis_utils import _bg_log_should_hide
        msg = "📞 [ReturnSentinel/Skip] afk_duration < 300s，太短不算真回归"
        self.assertTrue(_bg_log_should_hide(msg))

    # ----------------------------------------
    # 必留终端 (Sir 方案 2 = 性能+行动+思考脑+AutoArbiter)
    # ----------------------------------------

    def test_inner_thought_NOT_hidden(self):
        """💭 [InnerThought] — Sir 方案 2 留终端, 思考脑结论必看."""
        from jarvis_utils import _bg_log_should_hide
        msg = ("💭 [InnerThought] [C/sal=0.70/state=active/tick=45s] "
                "Sir is currently coding. | next=60s(llm_chosen)")
        self.assertFalse(_bg_log_should_hide(msg),
                          'InnerThought Sir 方案 2 选定保留 — 思考脑结论必终端')

    def test_jarvis_state_change_NOT_hidden(self):
        """🟢 [JarvisState] — 状态切换 Sir 方案 2 必留."""
        from jarvis_utils import _bg_log_should_hide
        msg = "🟢 [JarvisState] focused → ready (turn_complete) | Ready"
        self.assertFalse(_bg_log_should_hide(msg))

    def test_auto_arbiter_decision_NOT_hidden(self):
        """🤖 [AutoArbiter] — 决议输出 Sir 方案 2 必留."""
        from jarvis_utils import _bg_log_should_hide
        # AutoArbiter tick skipped 是常 spam, 但 Sir 选方案 2 = 留 AutoArbiter
        # 所有 (Sir 后续可再细分如要). 现保守不 hide.
        msg = "🤖 [AutoArbiter] tick skipped: today cap reached (52/50)"
        self.assertFalse(_bg_log_should_hide(msg),
                          'AutoArbiter Sir 方案 2 选定保留 — 决议看可见')

    # ----------------------------------------
    # JARVIS_VERBOSE_BG=1 verbose mode
    # ----------------------------------------

    def test_verbose_env_unhides_everything(self):
        """JARVIS_VERBOSE_BG=1 env 时 hidden marker 也回来 (debug 模式)."""
        from jarvis_utils import _bg_log_should_hide
        msg = "🤝 [ProactiveCare/PublishOnly] published advice ..."
        # verbose 模式 → 应该 False (不 hide)
        with patch.dict(os.environ, {'JARVIS_VERBOSE_BG': '1'}):
            self.assertFalse(_bg_log_should_hide(msg),
                              'verbose 模式 hide list 全部回归显示给 debug')

    # ----------------------------------------
    # source marker
    # ----------------------------------------

    def test_source_has_fix41_marker(self):
        """source — jarvis_utils.py 含本 fix 治理 marker."""
        path = os.path.join(ROOT, 'jarvis_utils.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('Sir 2026-05-28 19:15', src,
                       'jarvis_utils 应有 fix41 治理 anchor 注释')
        self.assertIn("'[ProactiveCare/PublishOnly]'", src,
                       'hide list 必含 ProactiveCare/PublishOnly marker')
        self.assertIn("'[CommitmentWatcher/PromiseLog]'", src,
                       'hide list 必含 CommitmentWatcher/PromiseLog marker')
        self.assertIn("'[SirStatusTracker/AutoReconcile]'", src,
                       'hide list 必含 fix40 reconcile marker')
        self.assertIn("'[DaemonHealthMonitor]'", src,
                       'hide list 必含 DaemonHealthMonitor marker')


if __name__ == '__main__':
    unittest.main()
