# -*- coding: utf-8 -*-
"""[Sir 2026-05-28 12:10 真痛 anchor] 思考脑 reconcile 物理 vs 声明状态 — STALE 不编故事

Sir 真痛 (12:10 thought 实况):
> 💭 [InnerThought] [A/sal=0.75/state=active/tick=45s] Sir has returned after a
>    14-minute absence, and while Adobe Media Encoder has finished its task, his
>    declared status remains 'sleep'. This discrepancy suggests he may only be
>    checking progress briefly before retiring or is simply forgetful regarding
>    his manual status toggle.
> Sir: "思考脑的逻辑要不要优化? 感觉看起来有点怪, 我是去吃饭前弄了导出, 然后回来的
>    时候看到的"

根因:
  Sir 早上 declare 'sleep' (去吃饭/外出) → SirStatusTracker 记 status='sleep'
  Sir 中午 12 点回来看 Adobe 进度 → 物理 idle < 5min → _classify_sir_state() 短路
    返 'active' (物理短路一 已对)
  但 evidence 同时给思考脑:
    - [CURRENT MOMENT] Sir state: active (物理)
    - [SIR DECLARED STATUS] status: sleep | declared X min ago
    - ⚠️ "Honor Sir's declaration. status=sleep → NO surface_to_sir"

  这俩矛盾 + ⚠️ "Honor declared → suppress" 导致思考脑 hedge:
    "may only be checking progress briefly before retiring OR is simply
     forgetful regarding his manual status toggle"
  — 编两个不相干的故事拼接, 没识破"声明 stale".

治本 (准则 6 evidence-only + 准则 8 优雅):
  _render_evidence 渲染 sir_declared_status block 时, 拿 evidence['sir_state']
  cross-reference. 物理 active + 声明 in (sleep/nap/dnd/out/lunch/dinner/afk_short)
  → 标 STALE + 换 directive ("don't anchor narrative on stale", "options:
  silence / publish 'sir_status_stale'"). 不删 declared inject (它仍是 sensor
  signal), 不改 _classify_sir_state 物理短路 (已对). 只动 render copy.

测试覆盖:
  T1. inconsistent (active + sleep) → render 出现 STALE warning
  T2. inconsistent (active + sleep) → render NOT 出现 "Honor Sir's declaration"
  T3. inconsistent (active + sleep) → STALE warning 含 "don't anchor" + 选项
  T4. consistent (sleep + sleep) → render 仍 "Honor Sir's declaration" (老 path 不破)
  T5. consistent (active + active) → declared='active' 不算需 honor, 不出现 STALE
  T6. consistent (afk_deep + lunch) → 老 path "Honor" 留 (lunch 期间合理)
  T7. inconsistent (active + out) → STALE 触发 (Sir out 但物理 active = 回来了)
  T8. inconsistent (active + afk_short) → STALE 触发
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_daemon():
    """Make a daemon instance just for calling _build_prompt (no real init).

    Pre-populate enough attributes for _build_prompt to walk without crashing.
    """
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
    # Minimal stubs that _build_prompt path may touch
    d._thoughts = []
    d._lock = __import__('threading').Lock()
    d.nerve = None
    d._IDENTITY_VOCAB_CACHE = {}
    d._IDENTITY_VOCAB_MTIME = 0.0
    return d


def _render(daemon, evidence: dict) -> str:
    """Call _build_prompt and return user prompt (declared-status block lives there)."""
    sir_state = evidence.get('sir_state', 'active')
    try:
        _system, user = daemon._build_prompt(
            sir_state=sir_state,
            evidence=evidence,
            free_categories=['A', 'B', 'C', 'D', 'E'],
            channel_view=None,
        )
    except Exception as e:
        raise AssertionError(f"_build_prompt crashed: {e}")
    return user


# ==========================================================
# T1-T3. inconsistent: active + sleep → STALE + 不 honor
# ==========================================================

class TestStaleReconcileActiveSleep(unittest.TestCase):
    """Sir 真痛 case: 物理 active (键鼠在用) + 声明 sleep (没切回)."""

    def setUp(self):
        self.daemon = _make_daemon()
        self.evidence = {
            'sir_state': 'active',
            'idle_seconds': 5,
            'hour': 12,
            'sir_declared_status': {
                'status': 'sleep',
                'age_s': 14 * 60,
                'is_overdue': False,
            },
        }

    def test_t1_stale_warning_appears(self):
        """T1. inconsistent → render 含 STALE 标."""
        out = _render(self.daemon, self.evidence)
        self.assertIn('STALE', out,
            "物理 active + 声明 sleep 应触发 STALE warning")

    def test_t2_no_honor_directive(self):
        """T2. inconsistent → NOT 含老 'Honor Sir's declaration' directive."""
        out = _render(self.daemon, self.evidence)
        self.assertNotIn("Honor Sir's declaration", out,
            "STALE case 应 suppress 'Honor declared', 否则思考脑被误导")

    def test_t3_stale_offers_anti_anchor_and_options(self):
        """T3. STALE warning 含反 anchor 提示 + 选项 (silence / publish)."""
        out = _render(self.daemon, self.evidence)
        self.assertIn("don't anchor", out.lower().replace("don\u2019t", "don't"),
            "STALE 应提醒不要 anchor narrative on stale status")
        self.assertIn('silence', out.lower(),
            "STALE 应给 silence 选项")
        self.assertIn('sir_status_stale', out,
            "STALE 应给 publish 'sir_status_stale' 选项")


# ==========================================================
# T4. consistent: sleep + sleep → 老 path 保留
# ==========================================================

class TestConsistentSleepKeepsHonor(unittest.TestCase):

    def test_t4_consistent_sleep_keeps_honor(self):
        """T4. sir_state=sleep + declared=sleep → 老 'Honor' directive 留."""
        daemon = _make_daemon()
        evidence = {
            'sir_state': 'sleep',
            'idle_seconds': 3600,
            'hour': 2,
            'sir_declared_status': {
                'status': 'sleep',
                'age_s': 30 * 60,
                'is_overdue': False,
            },
        }
        out = _render(daemon, evidence)
        self.assertIn("Honor Sir's declaration", out,
            "consistent (sleep+sleep) 仍应 Honor")
        self.assertNotIn('STALE', out,
            "consistent 不应触发 STALE")


# ==========================================================
# T5. consistent: active + active (declared) → 无 STALE, 也无 Honor block
# ==========================================================

class TestActiveDeclaredActiveNoStale(unittest.TestCase):

    def test_t5_active_declared_active(self):
        """T5. declared='active' 不在 honor list (Sir 没声明休息), 不算 STALE."""
        daemon = _make_daemon()
        evidence = {
            'sir_state': 'active',
            'idle_seconds': 5,
            'hour': 14,
            'sir_declared_status': {
                'status': 'active',
                'age_s': 60,
                'is_overdue': False,
            },
        }
        out = _render(daemon, evidence)
        self.assertNotIn('STALE', out,
            "active+active 不矛盾, 不应触发 STALE")


# ==========================================================
# T6. consistent: afk_deep + lunch → 老 path 留 (lunch 期间合理)
# ==========================================================

class TestAfkLunchConsistent(unittest.TestCase):

    def test_t6_afk_deep_lunch_keeps_honor(self):
        """T6. sir_state=afk_deep + declared=lunch → consistent, 仍 Honor."""
        daemon = _make_daemon()
        evidence = {
            'sir_state': 'afk_deep',
            'idle_seconds': 1200,
            'hour': 12,
            'sir_declared_status': {
                'status': 'lunch',
                'age_s': 15 * 60,
                'is_overdue': False,
            },
        }
        out = _render(daemon, evidence)
        self.assertNotIn('STALE', out,
            "afk_deep+lunch consistent, 不应 STALE")
        self.assertIn("Honor Sir's declaration", out,
            "lunch 期间应仍 Honor (delay actionable)")


# ==========================================================
# T7-T8. 其他 stale 触发场景
# ==========================================================

class TestOtherStaleTriggers(unittest.TestCase):

    def test_t7_active_out_triggers_stale(self):
        """T7. active + out → Sir 出去说但其实在键鼠 = STALE."""
        daemon = _make_daemon()
        evidence = {
            'sir_state': 'active',
            'idle_seconds': 5,
            'hour': 15,
            'sir_declared_status': {
                'status': 'out',
                'age_s': 60 * 60,
                'is_overdue': False,
            },
        }
        out = _render(daemon, evidence)
        self.assertIn('STALE', out,
            "active+out 矛盾 → STALE (Sir 回来了没切回)")

    def test_t8_active_afk_short_triggers_stale(self):
        """T8. active + afk_short → 同 STALE."""
        daemon = _make_daemon()
        evidence = {
            'sir_state': 'active',
            'idle_seconds': 5,
            'hour': 10,
            'sir_declared_status': {
                'status': 'afk_short',
                'age_s': 10 * 60,
                'is_overdue': False,
            },
        }
        out = _render(daemon, evidence)
        self.assertIn('STALE', out,
            "active+afk_short 矛盾 → STALE")


if __name__ == '__main__':
    unittest.main()
