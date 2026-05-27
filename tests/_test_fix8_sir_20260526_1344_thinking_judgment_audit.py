# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 13:44 真痛 CRITICAL audit] 思考的判定 — 完整排查 8 BUG.

Sir 真意 anchor:
  "思考的判定也有很多问题，完全的排查一下"

Sir log 真证据 (13:32 → 13:42):
  - Sir 13:32 说"我睡觉了" + register "wake @ 13:30" commitment
  - 但 InnerThought daemon 全程 state=active/tick=60s 狂思考 10min
  - 5+ B 类重复 propose_protocol "Don't use formal apologies" (AutoArbiter DEFER)
  - notes 满 500/500 仍 propose adjust_concern_notes
  - LLM 编 concern_id 'jarvis_self_maintenance' (不存在)
  - 重复 "地基要打牢" inside_joke 3 次 dedup_or_fail
  - salience 通胀 (0.7-0.85 大部分)
  - 1:30 PM 闹钟没响, 12min 后 SmartNudge 补救 fire commitment_check
  - 13:42 6 秒内 3 nudge 连发 (commitment + return + dormant)

8 BUG 修复 (test 覆盖):
  BUG 1: _classify_sir_state 接 commitment_watcher 看 Sir 真意 sleep
  BUG 2: _gather_evidence + _build_prompt 注入 active + pending protocols 防 dedup
  BUG 3: _do_adjust_concern_notes notes 满 80% 早 reject + evidence 含 notes_chars
  BUG 4: prompt HARD RULE 强警告 invent concern_id
  BUG 5: evidence + prompt 注入 active + pending inside_jokes 防 dedup
  BUG 7: CommitmentWatcher alarm-style commitment bypass AFK skip (wake-up 真响)
  BUG 8: SmartNudge + ReturnSentinel 接 nudge_coordination yield (防 burst)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================================
# BUG 1: Sir 真意 sleep 识别 — daemon 看 SirStatusTracker + idle 短路
# 🆕 [Sir 2026-05-26 19:01 准则 6 极致版] 老路径 _has_active_rest_commitment 已删
# (它是把"硬编码时间窗"换"硬编码 vocab"). 新路径 _classify_sir_state 看:
#   1. idle < 5min → 永远 active (Sir 在键鼠真在用)
#   2. SirStatusTracker.current_status() (Sir 真意 sensor, vocab 已持久化)
#   3. Fallback: 物理 idle 阈值
# 测试调 mock idle + mock SirStatusTracker 验证 3 路径.
# ==========================================================================
class TestBug1SleepIntentRecognition(unittest.TestCase):
    """daemon 看 SirStatusTracker + idle 短路 → state 真意决定.

    Sir 19:01 真痛: "怎么我看你的思考链里一堆硬编码? 知道我不在/在电脑前很困难吗?"
    BUG 1 fix (13:32) 用 _REST_INTENT_VOCAB hardcode 反推 sleep, 19:01 实测仍 fire
    (commitment 已 fulfilled 但 daemon 不知道). 治本: 删 hardcode vocab + 用
    SirStatusTracker (vocab 持久化 jarvis_sir_status_tracker.py) + idle 短路.
    """

    def _make_daemon(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        return InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=None,
            relational_state=None,
            central_nerve=None,
        )

    def test_idle_short_circuits_to_active(self):
        """idle < 5min → 永远 active (Sir 真在键鼠). 即使 SirStatusTracker
        声明 sleep, idle 物理短路优先 — 这是 Sir Q1 真痛治本."""
        daemon = self._make_daemon()
        with patch.object(daemon, '_get_idle_seconds', return_value=10.0), \
             patch('jarvis_sir_status_tracker.current_status',
                    return_value={'status': 'sleep', 'age_s': 100,
                                   'is_overdue': False}):
            state = daemon._classify_sir_state()
            self.assertEqual(state, 'active',
                'idle 10s 短路 — 即使声明 sleep 也 active (Sir 在键鼠)')

    def test_sir_status_sleep_makes_state_sleep(self):
        """SirStatusTracker 声明 sleep + idle 高 + 未 overdue → state=sleep."""
        daemon = self._make_daemon()
        with patch.object(daemon, '_get_idle_seconds', return_value=600.0), \
             patch('jarvis_sir_status_tracker.current_status',
                    return_value={'status': 'sleep', 'age_s': 100,
                                   'is_overdue': False}):
            state = daemon._classify_sir_state()
            self.assertEqual(state, 'sleep',
                "SirStatusTracker 声明 sleep + idle 10min + 未 overdue → sleep")

    def test_sir_status_nap_makes_state_sleep(self):
        """nap 跟 sleep 同档 (都 'sleep' state)."""
        daemon = self._make_daemon()
        with patch.object(daemon, '_get_idle_seconds', return_value=400.0), \
             patch('jarvis_sir_status_tracker.current_status',
                    return_value={'status': 'nap', 'age_s': 100,
                                   'is_overdue': False}):
            state = daemon._classify_sir_state()
            self.assertEqual(state, 'sleep',
                "SirStatusTracker nap → state=sleep")

    def test_sir_status_out_makes_state_afk_deep(self):
        """out/lunch/dinner + idle 长 → afk_deep."""
        daemon = self._make_daemon()
        with patch.object(daemon, '_get_idle_seconds', return_value=400.0), \
             patch('jarvis_sir_status_tracker.current_status',
                    return_value={'status': 'out', 'age_s': 100,
                                   'is_overdue': False}):
            state = daemon._classify_sir_state()
            self.assertEqual(state, 'afk_deep',
                "SirStatusTracker out + idle > 5min → afk_deep")

    def test_sir_status_dnd_makes_state_sleep(self):
        """dnd → state=sleep (Sir 不要打扰)."""
        daemon = self._make_daemon()
        with patch.object(daemon, '_get_idle_seconds', return_value=400.0), \
             patch('jarvis_sir_status_tracker.current_status',
                    return_value={'status': 'dnd', 'age_s': 100,
                                   'is_overdue': False}):
            state = daemon._classify_sir_state()
            self.assertEqual(state, 'sleep',
                "SirStatusTracker dnd → state=sleep (不打扰)")

    def test_overdue_status_ignored_falls_through(self):
        """is_overdue=True → 不再以声明状态为准, 走 idle fallback."""
        daemon = self._make_daemon()
        with patch.object(daemon, '_get_idle_seconds', return_value=400.0), \
             patch('jarvis_sir_status_tracker.current_status',
                    return_value={'status': 'lunch', 'age_s': 14400,
                                   'is_overdue': True}):
            state = daemon._classify_sir_state()
            # overdue → fallback idle: 400s > 300s (THRESHOLD_AFK_SHORT_S) → afk_short
            self.assertEqual(state, 'afk_short',
                "overdue lunch 不再算 sleep, idle fallback → afk_short")

    def test_unknown_status_uses_idle_fallback(self):
        """SirStatusTracker unknown → 用 idle 物理阈值."""
        daemon = self._make_daemon()
        with patch.object(daemon, '_get_idle_seconds', return_value=2000.0), \
             patch('jarvis_sir_status_tracker.current_status',
                    return_value={'status': 'unknown', 'age_s': 0,
                                   'is_overdue': False}):
            state = daemon._classify_sir_state()
            # unknown + idle 2000s > 1800s (THRESHOLD_AFK_DEEP_S) → afk_deep
            self.assertEqual(state, 'afk_deep',
                "unknown status + idle 33min → afk_deep (idle fallback)")


# ==========================================================================
# BUG 2: propose_protocol 重复 — evidence + prompt 注入 active/pending protocols
# ==========================================================================
class TestBug2ProposeProtocolDedup(unittest.TestCase):
    """_gather_evidence 含 active_protocols + pending_review_protocols,
    _build_prompt 显示 ACTIVE PROTOCOLS block + DO NOT propose dup 规则.

    Sir 真痛 13:33-13:31: LLM 5+ 次 propose 同 "Do not use formal apologies"
    类 protocol, AutoArbiter DEFER. 真因: prompt 没 inject 已 propose 的, LLM
    每 tick 全新发现 → 重复 propose.
    """

    def _make_daemon_with_relational(self, active_protos, review_protos):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        rs = MagicMock()
        rs.list_protocols = MagicMock(return_value=active_protos)
        rs.list_protocols_review = MagicMock(return_value=review_protos)
        rs.list_inside_jokes = MagicMock(return_value=[])
        rs.list_inside_jokes_review = MagicMock(return_value=[])
        nerve = MagicMock()
        nerve.short_term_memory = []
        daemon = InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=None,
            relational_state=rs,
            central_nerve=nerve,
        )
        return daemon

    def test_evidence_includes_active_protocols(self):
        """_collect_evidence 返 active_protocols 列表."""
        proto1 = MagicMock(rule='Do not open with formal apologies')
        proto2 = MagicMock(rule='Always use concise sentences')
        daemon = self._make_daemon_with_relational([proto1, proto2], [])
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        self.assertIn('active_protocols', ev,
            'evidence 应含 active_protocols')
        self.assertEqual(len(ev['active_protocols']), 2)
        self.assertIn('formal apologies', ev['active_protocols'][0])

    def test_evidence_includes_pending_review_protocols(self):
        """_collect_evidence 返 pending_review_protocols."""
        review1 = MagicMock(rule='Do not be verbose')
        daemon = self._make_daemon_with_relational([], [review1])
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        self.assertIn('pending_review_protocols', ev)
        self.assertEqual(len(ev['pending_review_protocols']), 1)

    def test_prompt_displays_active_protocols(self):
        """_build_prompt 输出含 ACTIVE PROTOCOLS block."""
        proto1 = MagicMock(rule='Do not open with formal apologies')
        daemon = self._make_daemon_with_relational([proto1], [])
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        system, user = daemon._build_prompt('active', ev)
        self.assertIn('ACTIVE PROTOCOLS', user,
            'prompt 应含 ACTIVE PROTOCOLS section')
        self.assertIn('formal apologies', user,
            '已 active protocol rule 必须显示')

    def test_prompt_warns_against_redundant_propose(self):
        """prompt 含 DO NOT propose_protocol 重复 warn."""
        proto1 = MagicMock(rule='Do not be too formal')
        daemon = self._make_daemon_with_relational([proto1], [])
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        system, user = daemon._build_prompt('active', ev)
        self.assertIn('DO NOT propose_protocol', user,
            'prompt 必须教 LLM 不要重复 propose 同概念')


# ==========================================================================
# BUG 3: notes 满 500/500 仍 propose — 早 reject + evidence 含 notes_chars
# ==========================================================================
class TestBug3NotesFullEarlyReject(unittest.TestCase):
    """_do_adjust_concern_notes notes 满 80%+ → reject 'notes_near_cap'.
    
    Sir 真痛: notes_for_self sir_cursor_payment 已满 500/500, 但 LLM 仍 propose
    adjust_concern_notes 给它 → log 显示 "total 500/500" 但实质没真 append.
    """

    def _build_daemon(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        from jarvis_concerns import ConcernsLedger, Concern
        tmp = tempfile.mktemp(suffix='.json')
        ledger = ConcernsLedger(persist_path=tmp)
        ledger.register(Concern(
            id='c1',
            what_i_watch='watch x',
            why_i_care='care y',
            severity=0.5,
            notes_for_self='X' * 450,  # 90% cap (>80%)
        ))
        daemon = InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=ledger,
            relational_state=None,
            central_nerve=None,
        )
        return daemon, ledger

    def test_full_notes_early_reject(self):
        """🩹 [Sir 2026-05-27 21:11 真测 P3 升级] 旧行为已退役.

        旧 (BUG 3): notes 满 80% → 直接 reject 'notes_near_cap', 不 mutate.
        新 (P3):    notes 满 80% → 自动 prune (archive 老段 jsonl) → 继续 append.

        这里测的 setUp `'X' * 450` 是单 segment (没 ' | ' 分隔), prune 算法看到
        "smallest segment 已超 target_chars=250" → no-op (老 segment 整段比
        target 大, 切不动), 退回老 reject 行为. 所以 single-segment 老 case
        仍 reject, 多 segment case 走 auto-prune (单独 test 覆盖).
        """
        from jarvis_inner_thought_daemon import InnerThought
        daemon, ledger = self._build_daemon()
        thought = InnerThought(
            id='th1', ts=time.time(), ts_iso='2026-05-26T13:00',
            category='C', thought='Sir reaction pattern noticed when watch x',
            salience=0.8,
            actionable='adjust_concern_notes:c1:remember to dampen',
            evidence_link='watch x',
        )
        ok, msg = daemon._do_adjust_concern_notes(
            thought, 'adjust_concern_notes:c1:remember to dampen'
        )
        # single-segment 老 case: prune no-op → 退回 reject (老行为兼容)
        self.assertFalse(ok,
            'single-segment notes 满 80%, prune no-op → 退回 reject')
        self.assertIn('notes_near_cap', msg,
            'reject reason 应是 notes_near_cap')
        # ledger 未被 mutate (single-segment 无段可 archive)
        self.assertEqual(len(ledger.get('c1').notes_for_self), 450,
            'single-segment reject 后 ledger 不该被 mutate')

    def test_evidence_concerns_includes_notes_chars(self):
        """_collect_evidence concerns 含 notes_chars 字段."""
        daemon, ledger = self._build_daemon()
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        cc = ev.get('concerns', [])
        self.assertGreater(len(cc), 0)
        self.assertIn('notes_chars', cc[0],
            'evidence concerns 必须含 notes_chars 字段 (BUG 3 prompt 信号)')
        self.assertEqual(cc[0]['notes_chars'], 450)

    def test_prompt_displays_notes_near_full_warn(self):
        """_build_prompt 显 NEAR FULL warn 当 notes >= 400."""
        daemon, ledger = self._build_daemon()
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        system, user = daemon._build_prompt('active', ev)
        self.assertIn('NEAR FULL', user,
            'prompt 必须 warn LLM concern notes near full')


# ==========================================================================
# BUG 4: LLM 编 concern_id — prompt HARD RULE 强警告
# ==========================================================================
class TestBug4ConcernIdHallucinationWarn(unittest.TestCase):
    """prompt 强警告 LLM "DO NOT invent concern_id".
    
    Sir 真痛: LLM 编 'jarvis_self_maintenance' 不存在的 concern_id, 浪费 tick.
    """

    def test_prompt_contains_hard_rule_warn(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        from jarvis_concerns import ConcernsLedger, Concern
        tmp = tempfile.mktemp(suffix='.json')
        ledger = ConcernsLedger(persist_path=tmp)
        ledger.register(Concern(
            id='real_concern_1',
            what_i_watch='something',
            why_i_care='reason',
            severity=0.5,
        ))
        daemon = InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=ledger,
            relational_state=None,
            central_nerve=None,
        )
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        system, user = daemon._build_prompt('active', ev)
        self.assertIn('HARD RULE', user,
            'prompt 必须含 HARD RULE 警告')
        self.assertIn('DO NOT invent', user,
            'prompt 必须警告 LLM 不要 invent concern_id')
        self.assertIn('real_concern_1', user,
            'prompt 必须列真实 concern_id 让 LLM 选')


# ==========================================================================
# BUG 5: inside_joke 重复 — evidence + prompt 注入 active + pending jokes
# ==========================================================================
class TestBug5InsideJokeDedup(unittest.TestCase):
    """_gather_evidence + _build_prompt 含 active_inside_jokes + pending."""

    def _build_daemon(self, jokes_active, jokes_review):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        rs = MagicMock()
        rs.list_protocols = MagicMock(return_value=[])
        rs.list_protocols_review = MagicMock(return_value=[])
        rs.list_inside_jokes = MagicMock(return_value=jokes_active)
        rs.list_inside_jokes_review = MagicMock(return_value=jokes_review)
        nerve = MagicMock()
        nerve.short_term_memory = []
        daemon = InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=None,
            relational_state=rs,
            central_nerve=nerve,
        )
        return daemon

    def test_evidence_includes_jokes(self):
        joke1 = MagicMock(phrase='地基要打牢')
        daemon = self._build_daemon([joke1], [])
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        self.assertIn('active_inside_jokes', ev)
        self.assertEqual(len(ev['active_inside_jokes']), 1)

    def test_prompt_displays_jokes_warn(self):
        joke1 = MagicMock(phrase='地基要打牢')
        daemon = self._build_daemon([joke1], [])
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        system, user = daemon._build_prompt('active', ev)
        self.assertIn('地基要打牢', user)
        self.assertIn('DO NOT suggest_inside_joke', user,
            'prompt 必须教 LLM 不要重复 propose joke')


# ==========================================================================
# BUG 7: 闹钟没响 — alarm-style commitment bypass AFK skip
# ==========================================================================
class TestBug7AlarmStyleCommitmentBypass(unittest.TestCase):
    """CommitmentWatcher _is_alarm_style_commitment 识别 wake-up vocab.
    
    Sir 真痛: 13:30 闹钟没响 (Sir 睡, idle > 5min), AFK skip 拦. 12min 后
    SmartNudge 才补救. 修法: alarm-style commitment bypass AFK skip.
    """

    def _make_watcher(self):
        from jarvis_commitment_watcher import CommitmentWatcher
        watcher = CommitmentWatcher.__new__(CommitmentWatcher)
        return watcher

    def test_wake_up_commitment_identified(self):
        watcher = self._make_watcher()
        c = {
            'description': 'I shall wake Sir at 13:30',
            'source_text': 'wake me up',
        }
        self.assertTrue(watcher._is_alarm_style_commitment(c),
            "'wake' keyword 必须识别为 alarm-style")

    def test_zh_qichuang_identified(self):
        watcher = self._make_watcher()
        c = {
            'description': '13:30 叫 Sir 起床',
            'source_text': '起床叫我',
        }
        self.assertTrue(watcher._is_alarm_style_commitment(c),
            "中文 '起床/叫醒' 必须识别为 alarm-style")

    def test_alarm_keyword_identified(self):
        watcher = self._make_watcher()
        c = {
            'description': 'set alarm for 14:00',
            'source_text': '',
        }
        self.assertTrue(watcher._is_alarm_style_commitment(c),
            "'alarm' keyword 必须识别")

    def test_non_alarm_commitment_not_identified(self):
        watcher = self._make_watcher()
        c = {
            'description': 'remind me about meeting',
            'source_text': '提醒会议',
        }
        self.assertFalse(watcher._is_alarm_style_commitment(c),
            'meeting reminder 不是 alarm-style (Sir 在场可见时再 fire)')

    def test_empty_commitment_not_identified(self):
        watcher = self._make_watcher()
        c = {'description': '', 'source_text': ''}
        self.assertFalse(watcher._is_alarm_style_commitment(c),
            '空 desc 应安全 return False')


# ==========================================================================
# BUG 8: nudge burst — SmartNudge + ReturnSentinel 接 nudge_coordination
# ==========================================================================
class TestBug8NudgeBurstYieldWiring(unittest.TestCase):
    """SmartNudge + ReturnSentinel 源码含 should_yield_to_recent_proactive_nudge.
    
    Sir 真痛: 13:42 6 秒内 3 nudge 连发. 真因: SmartNudge / ReturnSentinel
    没接 nudge_coordination. 修法: fire 前查 SWM 让位 + fire 后 publish.
    """

    def test_smart_nudge_imports_yield_check(self):
        """jarvis_smart_nudge.py 源码含 should_yield_to_recent_proactive_nudge."""
        path = os.path.join(ROOT, 'jarvis_smart_nudge.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('should_yield_to_recent_proactive_nudge', src,
            'SmartNudge 必须接 nudge_coordination yield (BUG 8 修)')
        self.assertIn('publish_proactive_nudge_fired', src,
            'SmartNudge fire 后必须 publish 让别 sentinel yield')

    def test_return_sentinel_imports_yield_check(self):
        """jarvis_return_sentinel.py 源码含 should_yield_to_recent_proactive_nudge."""
        path = os.path.join(ROOT, 'jarvis_return_sentinel.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('should_yield_to_recent_proactive_nudge', src,
            'ReturnSentinel 必须接 nudge_coordination yield (BUG 8 修)')

    def test_commitment_watcher_alarm_bypass_afk_skip(self):
        """CommitmentWatcher _dispatch_commitment_nudge AFK skip 含 alarm bypass."""
        path = os.path.join(ROOT, 'jarvis_commitment_watcher.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('_is_alarm_style_commitment', src,
            'CommitmentWatcher 必须含 _is_alarm_style_commitment helper')
        self.assertIn('_is_alarm_dispatch', src,
            '_dispatch_commitment_nudge AFK skip 必须 bypass alarm-style')
        self.assertIn('_is_alarm = self._is_alarm_style_commitment', src,
            'idle<2min check 必须 bypass alarm-style')


if __name__ == '__main__':
    unittest.main()
