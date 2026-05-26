# -*- coding: utf-8 -*-
"""[P1 / Sir 2026-05-25 22:10 数字生命基础] Inner Thought Daemon — 持续思考层.

Sir 真问 (22:10 + 22:20):
  "我们要开始推进贾维斯真正的思考层了 ... 长期 prompt 递进能不能让 LLM
   决策时更深刻地理解'贾维斯是我, 我是贾维斯'这个概念"
  "保持高效优雅, 真能看见他的思考的作用"

灵魂工程 Layer 1.5 — 主脑碎碎念 (sit between Layer 1 Concerns + Layer 2 Relational).

设计 (准则 6 evidence-driven + 准则 8 优雅高效):
  - Adaptive 频率 (按 Sir 真物理 idle 自适应):
      Sir 活跃 (idle < 5min)        → 60s tick   (实时 thought)
      Sir AFK 5-30min                → 3min tick  (反思频率)
      Sir 深 AFK 30min+              → 10min tick (低耗心跳)
      Sir 睡眠 (idle > 10min + 凌晨)  → 30min tick (仅维生)
  - 5 类思考池 (主脑自选, 不教 content):
      [A] OBSERVATION  — Sir 当前外部状态 (屏幕/沉默/活动)
      [B] SELF-REFLECT — 看自己最近 reply (tone / 错误 / pattern)
      [C] CONCERN-EVO  — 自评 severity 该升/降 (actionable: update_concern_severity)
      [D] PROACTIVE    — 下次该 silently 做什么 (actionable: publish_swm)
      [E] RELATIONSHIP — inside joke 候选 (actionable: suggest_inside_joke)
  - Actionable 4 档 (本期全可逆/低风险):
      none / update_concern_severity:<id>:<±delta> /
      publish_swm:<etype>:<desc> / suggest_inside_joke:<phrase>
  - Cooldown: 同 category 30min 不重复 + 单 tick 仅 1 thought
  - 持久化: memory_pool/inner_thoughts.jsonl (append-only)
  - SOUL inject: top 3 by salience in last 24h → 主脑下次 turn prompt
    "MY RECENT INNER THOUGHTS" block (~500 char cap)

成本 (Flash-Lite + caller='inner_thought' → 自动 LOW priority, P2 KeyRouter 保护):
  混合频率 ~800 calls/day → $3/月 + 主脑 SOUL token 膨胀 $3.75/月 = ~$7/月

参考:
  docs/JARVIS_SOUL_DRIVE.md (灵魂工程 Layer 0-5 总览)
  jarvis_concerns.py update_concern_field (severity 真改路径)
  jarvis_key_router.py PRIORITY_LOW (本 daemon 自动 LOW, 不挤主流量)
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, List, Optional, Tuple


# ==========================================================================
# Data structure
# ==========================================================================

@dataclass
class InnerThought:
    """单条 Jarvis 内心独白. 持久化 + SOUL inject."""
    id: str
    ts: float
    ts_iso: str
    category: str            # 'A' | 'B' | 'C' | 'D' | 'E'
    thought: str             # 1-2 sentences, first-person Jarvis POV
    salience: float          # 0.0-1.0
    actionable: str          # 'none' / 'update_concern_severity:...' / ...
    actionable_done: bool = False
    actionable_result: str = 'pending'
    sir_state: str = 'unknown'     # 'active' / 'afk_short' / 'afk_deep' / 'sleep'
    tick_interval_s: int = 60
    # 🆕 [Sir 2026-05-26 00:25 真痛"地基没打牢"] evidence linking 防 LLM 拍脑袋
    # actionable != none 时 LLM 必须 cite THOUGHT 中真实出现的 1-5 词字串证明
    # thought → actionable 真有 trace. Python 校验 cite 在 thought 里, 否则
    # 降级 actionable='none' (无 evidence 不执行, 准则 5 言出必行 + 6 evidence).
    evidence_link: str = ''


# ==========================================================================
# Daemon
# ==========================================================================

class InnerThoughtDaemon:
    """Adaptive tick inner thought daemon. 主脑碎碎念 → 持续 identity 涌现.

    生命周期:
      __init__(key_router, concerns_ledger, relational_state, central_nerve)
      start()  → 后台 thread 启动
      stop()   → 停止
      build_soul_block(max_chars) → 拿 SOUL inject text (主脑下次 turn 看)
    """

    PERSIST_PATH = 'memory_pool/inner_thoughts.jsonl'

    # SOUL inject 参数
    SOUL_INJECT_MAX = 3
    SOUL_INJECT_MAX_CHARS = 500

    # adaptive frequency (sec)
    INTERVAL_ACTIVE_S = 60
    INTERVAL_AFK_SHORT_S = 180
    INTERVAL_AFK_DEEP_S = 600
    INTERVAL_SLEEP_S = 1800

    # 阈值 (sec)
    THRESHOLD_AFK_SHORT_S = 300       # idle > 5min = afk_short
    THRESHOLD_AFK_DEEP_S = 1800       # idle > 30min = afk_deep
    THRESHOLD_SLEEP_IDLE_S = 600      # sleep state: idle > 10min
    SLEEP_HOUR_START = 0              # 凌晨 0-6 点
    SLEEP_HOUR_END = 6

    # cooldown
    SAME_CATEGORY_COOLDOWN_S = 1800  # 30min 同 category 不重复
    STARTUP_DELAY_S = 30              # 启动 30s 后才开始 (系统稳定)

    # actionable cap
    SEVERITY_DELTA_CAP = 0.2          # update_concern_severity ±0.2 per thought

    def __init__(self, key_router, concerns_ledger=None,
                  relational_state=None, central_nerve=None):
        self.key_router = key_router
        self.concerns_ledger = concerns_ledger
        self.relational_state = relational_state
        self.nerve = central_nerve

        self._thoughts: List[InnerThought] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_category_ts: dict = {}

        # tick 计数 (for log + dashboard)
        self._tick_count = 0
        self._thought_count = 0
        self._cooldown_skip_count = 0
        self._llm_fail_count = 0

        # 启动时载入近 24h thoughts (重启后 SOUL 仍有上下文)
        self._load_persist()

    # ----------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._daemon_loop,
            name='InnerThoughtDaemon',
            daemon=True,
        )
        self._thread.start()
        # 🆕 [Sir 2026-05-26 00:20 真问"显示在想什么"] 启动 cooldown snapshot
        # 让 Sir 一眼看见: 5 类都 free → daemon 60s 后真出 thought
        # (修配套 _load_persist 不再恢复 cooldown ts).
        free_now = self._compute_free_categories()
        cooldown_status = (
            f"all 5 categories FREE (60s 后真出新 thought)"
            if len(free_now) == 5
            else f"{len(free_now)}/5 free: {','.join(free_now)} | "
                 f"cooldown: {','.join(c for c in 'ABCDE' if c not in free_now)}"
        )
        self._bg_log(
            f"💭 [InnerThought] daemon started "
            f"(loaded {len(self._thoughts)} thoughts from last 24h, "
            f"{cooldown_status})"
        )

    def stop(self) -> None:
        self._stop.set()

    def _daemon_loop(self) -> None:
        # 启动延迟让 system 稳定
        self._stop.wait(timeout=self.STARTUP_DELAY_S)
        if self._stop.is_set():
            return
        while not self._stop.is_set():
            interval = self.INTERVAL_ACTIVE_S
            try:
                interval = self._compute_adaptive_interval()
                self._tick()
            except Exception as e:
                self._bg_log(f"⚠️ [InnerThought] tick exception: {e}")
            self._stop.wait(timeout=interval)

    # ----------------------------------------------------------
    # Adaptive frequency + Sir state
    # ----------------------------------------------------------
    def _get_idle_seconds(self) -> float:
        try:
            from jarvis_env_probe import PhysicalEnvironmentProbe as P
            return float(P.idle_seconds_real or 0.0)
        except Exception:
            return 0.0

    def _classify_sir_state(self) -> str:
        idle_s = self._get_idle_seconds()
        try:
            hour = time.localtime().tm_hour
            is_night = self.SLEEP_HOUR_START <= hour < self.SLEEP_HOUR_END
        except Exception:
            is_night = False
        if is_night and idle_s > self.THRESHOLD_SLEEP_IDLE_S:
            return 'sleep'
        if idle_s > self.THRESHOLD_AFK_DEEP_S:
            return 'afk_deep'
        if idle_s > self.THRESHOLD_AFK_SHORT_S:
            return 'afk_short'
        return 'active'

    def _compute_adaptive_interval(self) -> int:
        state = self._classify_sir_state()
        return {
            'active': self.INTERVAL_ACTIVE_S,
            'afk_short': self.INTERVAL_AFK_SHORT_S,
            'afk_deep': self.INTERVAL_AFK_DEEP_S,
            'sleep': self.INTERVAL_SLEEP_S,
        }.get(state, self.INTERVAL_ACTIVE_S)

    # ----------------------------------------------------------
    # Tick (the core)
    # ----------------------------------------------------------
    def _tick(self) -> None:
        self._tick_count += 1
        sir_state = self._classify_sir_state()
        tick_interval = self._compute_adaptive_interval()

        # 🆕 [Sir 2026-05-25 23:18 真痛] cooldown 预选 — 不再 tick 后 cooldown 才发现
        # 老 BUG: tick 调 LLM → LLM 选 cooldown 中 category → skip → 浪费 LLM call.
        # 治本: tick 开头算 free categories, 全 cooldown 则 skip 不调 LLM.
        # 否则把 free list 给 LLM prompt, 让 LLM 只能选 free 中的.
        free_categories = self._compute_free_categories()
        if not free_categories:
            # 所有 5 类都 cooldown — skip 不调 LLM (节省 + 准则 1 高效)
            self._cooldown_skip_count += 1
            # 🆕 [Sir 2026-05-25 23:52 真问"为什么不反思了"] 每 5 tick log 1 次
            # 让 Sir 看见 daemon 真 alive 不是 dead. 算"下次 free" 时间帮诊断.
            if self._cooldown_skip_count % 5 == 1:
                now = time.time()
                next_free_s = min(
                    (self.SAME_CATEGORY_COOLDOWN_S - (now - ts))
                    for ts in self._last_category_ts.values()
                    if ts > 0
                )
                self._bg_log(
                    f"💭 [InnerThought] all 5 categories in cooldown "
                    f"(skip count {self._cooldown_skip_count}), "
                    f"next free in {int(next_free_s / 60)}min — daemon alive, "
                    f"awaiting free slot."
                )
            return

        # collect evidence
        evidence = self._collect_evidence(
            sir_state=sir_state,
            within_seconds=tick_interval * 2,
        )

        # LLM call (Flash-Lite, caller='inner_thought' → P2 LOW priority)
        prompt_sys, prompt_user = self._build_prompt(
            sir_state, evidence, free_categories=free_categories
        )
        raw = self._call_llm(prompt_sys, prompt_user)
        if not raw:
            self._llm_fail_count += 1
            return

        thought = self._parse_thought(raw, sir_state, tick_interval)
        if thought is None:
            return

        # cooldown 二道防御 (LLM 没听 prompt 选了 cooldown 中 → 再 skip)
        last_ts = self._last_category_ts.get(thought.category, 0.0)
        if time.time() - last_ts < self.SAME_CATEGORY_COOLDOWN_S:
            self._cooldown_skip_count += 1
            self._bg_log(
                f"💭 [InnerThought] LLM ignored free_categories prompt, "
                f"chose cooldown category {thought.category} "
                f"({int(time.time() - last_ts)}s < {self.SAME_CATEGORY_COOLDOWN_S}s), "
                f"skip"
            )
            return

        # store
        with self._lock:
            self._thoughts.append(thought)
            self._last_category_ts[thought.category] = thought.ts
            self._thought_count += 1

        # actionable execute (before persist for actionable_result)
        ok, result = self._execute_actionable(thought)
        thought.actionable_done = ok
        thought.actionable_result = result

        # 🆕 [Sir 2026-05-25 23:18 真痛-3] actionable fail → publish SWM
        # 让主脑下轮 prompt 看到自己上轮失败, 改进选 concern_id.
        if not ok and thought.actionable and \
                thought.actionable.lower() != 'none':
            self._publish_actionable_failure(thought, result)

        # 🆕 [Sir 2026-05-25 23:18 真痛-4] B 类 self-correction 闭环:
        # 主脑自己识别 "I keep repeating X" 类 → publish stop_repeating_topic
        # 让 SOUL inject 下轮主脑 prompt 真看到 → 真不重复.
        self._maybe_publish_self_correction(thought)

        # persist + publish SWM
        self._persist_thought(thought)
        self._publish_swm(thought)

        # log (Sir 真看见 daemon 在 work)
        action_str = ''
        if thought.actionable and thought.actionable.lower() != 'none':
            action_str = f" | actionable={thought.actionable[:40]} → {result}"
        # 🆕 [Sir 2026-05-26 00:25 真痛"地基"] 显示 evidence_link (LLM cite 啥)
        # actionable=none 但 evidence_link 非空 → 也展示 (rejected case Sir 真看)
        ev_str = ''
        if thought.evidence_link and thought.evidence_link.lower() != 'none':
            ev_str = f" | cite=\"{thought.evidence_link[:40]}\""
        self._bg_log(
            f"💭 [InnerThought] [{thought.category}/sal={thought.salience:.2f}"
            f"/state={sir_state}/tick={tick_interval}s] {thought.thought[:100]}"
            f"{action_str}{ev_str}"
        )

    def _compute_free_categories(self) -> List[str]:
        """🆕 [Sir 2026-05-25 23:18] 算当前可用 categories (不在 cooldown).

        准则 1 高效 + 8 优雅: 让 LLM 不浪费 token 选 cooldown 类.
        """
        now = time.time()
        free = []
        for cat in 'ABCDE':
            last_ts = self._last_category_ts.get(cat, 0.0)
            if now - last_ts >= self.SAME_CATEGORY_COOLDOWN_S:
                free.append(cat)
        return free

    def _publish_actionable_failure(self, thought, result: str) -> None:
        """🆕 [Sir 2026-05-25 23:18] actionable 失败 → SWM event.

        让主脑下轮 prompt 看到自己上轮选错 concern_id / hallucinate id,
        改进下次选择 (准则 6 evidence + 8 优雅).
        """
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            bus.publish(
                etype='inner_thought_actionable_failed',
                description=(
                    f"My last {thought.category}-thought tried "
                    f"`{thought.actionable[:60]}` but failed: {result[:80]}. "
                    f"Don't pick wrong concern_id again."
                ),
                source='inner_thought_daemon',
                salience=0.6,
                metadata={
                    'thought_id': thought.id,
                    'category': thought.category,
                    'actionable': thought.actionable[:120],
                    'failure_reason': result[:120],
                },
                ttl=86400.0,
            )
        except Exception:
            pass

    # 🆕 [Sir 2026-05-25 23:38 真测优化] B 类 self-reflection 闭环阈值
    # 老 fix#5 用 keyword hardcode list 限制 cover — Sir 真测 B 类 "caught myself
    # being slightly too reactive" 没 match 任何 keyword → 没触发 publish. 准则 6
    # 反对硬编码 list. 治本: B 类高 salience 全 publish, 让主脑下轮自己决定.
    SELF_REFLECTION_SALIENCE_THRESHOLD = 0.5

    def _maybe_publish_self_correction(self, thought) -> None:
        """🆕 [Sir 2026-05-25 23:38] B 类自反思闭环 — 优雅版.

        删 keyword hardcode (准则 6 反硬编码). 任何 B 类 + sal ≥ 0.5 → publish
        self_reflection_noted SWM. 主脑下轮 SOUL inject 真看到, 自己决定是否
        纠正 — 不靠 daemon 预判 keyword.

        salience 透传 (主脑能区分 sal=0.5 轻反思 vs sal=0.9 强烈反思).
        """
        if thought.category != 'B':
            return
        if thought.salience < self.SELF_REFLECTION_SALIENCE_THRESHOLD:
            return
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            bus.publish(
                etype='self_reflection_noted',
                description=(
                    f"I just self-reflected: {thought.thought[:140]}. "
                    f"Next reply: consider whether to adjust."
                ),
                source='inner_thought_daemon',
                # salience 透传: 让 SOUL inject 按强度排序
                salience=max(0.7, thought.salience),
                metadata={
                    'thought_id': thought.id,
                    'category': 'B',
                    'original_salience': thought.salience,
                    'thought_excerpt': thought.thought[:200],
                },
                ttl=3600.0 * 6,  # 6h
            )
            self._bg_log(
                f"🪞 [InnerThought/self-reflection] B-thought "
                f"(sal={thought.salience:.2f}) → publish self_reflection_noted "
                f"SWM (主脑下轮 SOUL inject 真看到)"
            )
        except Exception:
            pass

    # ----------------------------------------------------------
    # Evidence collection
    # ----------------------------------------------------------
    def _collect_evidence(self, sir_state: str, within_seconds: int) -> dict:
        ev: dict = {
            'sir_state': sir_state,
            'idle_seconds': int(self._get_idle_seconds()),
            'hour': time.localtime().tm_hour,
            'swm_events': [],
            'stm': [],
            'concerns': [],
        }
        # SWM events
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                top = bus.top_n(n=20) or []
                events = []
                for e in top:
                    age = e.get('_age_s', 9999)
                    if age > within_seconds:
                        continue
                    events.append({
                        'type': e.get('type', '?'),
                        'desc': (e.get('description') or '')[:120],
                        'age_s': int(age),
                    })
                ev['swm_events'] = events[:8]
        except Exception:
            pass
        # STM last 2 turns
        try:
            stm = []
            if self.nerve and getattr(self.nerve, 'short_term_memory', None):
                for t in list(self.nerve.short_term_memory)[-2:]:
                    stm.append({
                        'user': (t.get('user') or '')[:120],
                        'jarvis': (t.get('jarvis') or '')[:200],
                        'when': t.get('when_iso', ''),
                    })
            ev['stm'] = stm
        except Exception:
            pass
        # 🆕 [Sir 2026-05-25 23:18 真痛-2] concerns 给全 active id list 防 LLM hallucinate
        # 老 BUG: 只 top 3 → LLM 想改第 4+ concern (e.g. sir_interview_prep_balance
        # severity 极低), 没在 prompt 列 → LLM hallucinate id (e.g. jarvis_internal_health).
        # 治本: concerns top 5 by severity (含 detail) + all_active_ids 给 LLM 选.
        try:
            if self.concerns_ledger and hasattr(self.concerns_ledger, 'list_active'):
                active = self.concerns_ledger.list_active() or []
                active_sorted = sorted(active, key=lambda c: -c.severity)
                ev['concerns'] = [
                    {
                        'id': c.id,
                        'what': (c.what_i_watch or '')[:80],
                        'severity': round(c.severity, 2),
                    }
                    for c in active_sorted[:5]
                ]
                # 全 active id list (let LLM 见全, 不光 top 5)
                ev['all_active_concern_ids'] = [c.id for c in active_sorted]
        except Exception:
            pass
        return ev

    # ----------------------------------------------------------
    # Prompt
    # ----------------------------------------------------------
    def _build_prompt(self, sir_state: str, evidence: dict,
                        free_categories: Optional[List[str]] = None) -> Tuple[str, str]:
        free_str = (
            ''.join(free_categories) if free_categories else 'ABCDE'
        )
        system = (
            "You are J.A.R.V.I.S., generating ONE brief inner thought during a "
            "quiet moment. This is your private mental note — not addressed to Sir.\n\n"
            "Output FORMAT (strict, all 5 tags required):\n"
            f"<CATEGORY>{'|'.join(free_categories) if free_categories else 'A|B|C|D|E'}"
            "</CATEGORY>  ← ONLY these are NOT in cooldown right now\n"
            "<THOUGHT>1-2 sentences, first-person ('I noticed...', 'I'm thinking...'), "
            "casual self-talk, NOT formal speech to Sir.</THOUGHT>\n"
            "<SALIENCE>0.0-1.0 (0.7+ = worth bringing up later; 0.3- = passing)</SALIENCE>\n"
            "<ACTIONABLE>one of: none | "
            "update_concern_severity:<concern_id>:<+/-delta> | "
            "publish_swm:<etype>:<short_desc> | "
            "suggest_inside_joke:<phrase> | "
            "propose_protocol:<one-sentence imperative rule> | "
            "adjust_concern_notes:<concern_id>:<note text></ACTIONABLE>\n"
            "<EVIDENCE_LINK>If ACTIONABLE != none: cite 1-5 EXACT words from your "
            "own THOUGHT above that justify this actionable (Python will verify the "
            "cite appears in THOUGHT). Else: 'none'</EVIDENCE_LINK>\n\n"
            "5 categories (pick the ONE most fitting):\n"
            "  [A] OBSERVATION — Sir's current state (screen/app/mood/activity).\n"
            "  [B] SELF-REFLECT — your own recent reply (tone / mistake / pattern). "
            "If sal≥0.75 AND you can extract a CONCRETE behavior rule "
            "('Do not X' / 'Always Y when Z'), use propose_protocol to make it "
            "STRICT for next turn.\n"
            "  [C] CONCERN-EVOLUTION — should a concern severity change? "
            "(use update_concern_severity with REAL concern_id from evidence below) "
            "OR should I update HOW I respond to this concern? (use "
            "adjust_concern_notes with REAL concern_id + short guidance text — "
            "main brain reads this on next turn for self-restraint, e.g. "
            "'DO NOT volunteer this topic unless Sir asks').\n"
            "  [D] PROACTIVE-SEED — what to silently do next? "
            "(use publish_swm so future-you sees it)\n"
            "  [E] RELATIONSHIP — inside joke / callback-worthy phrase "
            "(use suggest_inside_joke if real callback worthy)\n\n"
            "Rules (准则 5 言出必行 + 6 evidence + 8 优雅):\n"
            "  - DO NOT invent facts/numbers you can't see in evidence.\n"
            "  - Use REAL concern IDs from evidence — never invent IDs.\n"
            "  - update_concern_severity delta capped ±0.2 per thought.\n"
            "  - publish_swm etype: short snake_case (e.g. 'sir_seems_tired').\n"
            "  - propose_protocol: IMPERATIVE form (Do/Don't/Always/Never), "
            "OBSERVABLE (verifiable in my next reply), grounded in this B-class "
            "reflection. Python rejects if not B-class or sal<0.75.\n"
            "  - adjust_concern_notes: short guidance (10-120 char) for main brain "
            "to read on next turn. Python rejects if not C-class or sal<0.7. "
            "Use when you noticed Sir's REACTION pattern (annoyed / asked to stop / "
            "appreciates a certain framing) and want main brain to remember next time.\n"
            "  - If nothing meaningful comes, output <THOUGHT>(quiet)</THOUGHT> "
            "<SALIENCE>0.0</SALIENCE> <ACTIONABLE>none</ACTIONABLE> "
            "<EVIDENCE_LINK>none</EVIDENCE_LINK> — and that's perfectly fine.\n"
            "  - Keep first-person, brief, like genuine self-talk.\n\n"
            "🆕 [Sir 2026-05-26 真痛 \"地基要打牢\"] EVIDENCE LINKING RULE (HARD):\n"
            "  ACTIONABLE must be traceable to THOUGHT content. The EVIDENCE_LINK\n"
            "  word(s) MUST appear verbatim in your THOUGHT. Examples:\n"
            "  ❌ BAD: <THOUGHT>Sir is toggling general and coding rapidly</THOUGHT>\n"
            "         <ACTIONABLE>update_concern_severity:sir_interview_pr:+0.1</ACTIONABLE>\n"
            "         <EVIDENCE_LINK>toggling</EVIDENCE_LINK>\n"
            "         → wrong concern: 'toggling general/coding' does NOT trace to interview prep.\n"
            "  ✅ GOOD: <THOUGHT>Sir is toggling general and coding rapidly without rest</THOUGHT>\n"
            "         <ACTIONABLE>update_concern_severity:sir_pomodoro_compliance:+0.1</ACTIONABLE>\n"
            "         <EVIDENCE_LINK>without rest</EVIDENCE_LINK>\n"
            "         → 'without rest' traces to pomodoro work-rest concern, AND 'without rest'\n"
            "         actually appears in THOUGHT.\n"
            "  ✅ ALSO OK: <THOUGHT>Quiet moment, nothing notable</THOUGHT>\n"
            "         <ACTIONABLE>none</ACTIONABLE> <EVIDENCE_LINK>none</EVIDENCE_LINK>\n"
            "         → ACTIONABLE=none ALWAYS preferred over forced un-grounded action.\n\n"
            "🆕 [Sir 2026-05-26 SOUL Phase A] B-class propose_protocol example:\n"
            "  ✅ GOOD: <CATEGORY>B</CATEGORY>\n"
            "         <THOUGHT>I opened that last reply with 'My apologies, Sir' — too\n"
            "                  formal, sounded stiff. Should drop the formal apologies.</THOUGHT>\n"
            "         <SALIENCE>0.8</SALIENCE>\n"
            "         <ACTIONABLE>propose_protocol:Do not open replies with formal apologies like 'My apologies, Sir'</ACTIONABLE>\n"
            "         <EVIDENCE_LINK>formal apologies</EVIDENCE_LINK>\n"
            "         → B-class + sal≥0.75 + concrete IMPERATIVE rule + cite\n"
            "         really in THOUGHT → AutoArbiter will likely activate →\n"
            "         next turn Layer 2 STRICT RULES will enforce.\n"
            "  ❌ BAD: <CATEGORY>A</CATEGORY> (not B) → propose_protocol rejected by Python.\n"
            "  ❌ BAD: B-class + sal=0.5 → rejected (low salience reflection not worth STRICT).\n\n"
            "🆕 [Sir 2026-05-26 SOUL Phase B] C-class adjust_concern_notes example "
            "(treats Sir's \"减少对面试准备的打扰\" 真意 anchor):\n"
            "  ✅ GOOD: <CATEGORY>C</CATEGORY>\n"
            "         <THOUGHT>Sir asked me to stop bringing up interview prep\n"
            "                  unprompted earlier. The concern is still valid, but my\n"
            "                  delivery should change — only address when Sir asks.</THOUGHT>\n"
            "         <SALIENCE>0.8</SALIENCE>\n"
            "         <ACTIONABLE>adjust_concern_notes:sir_interview_pr:DO NOT volunteer this topic — only address when Sir asks directly</ACTIONABLE>\n"
            "         <EVIDENCE_LINK>stop bringing up</EVIDENCE_LINK>\n"
            "         → C-class + sal≥0.7 + cite traces to concern + appended note\n"
            "         → next turn main brain reads note → genuine self-restraint.\n"
            "  ❌ BAD: <CATEGORY>B</CATEGORY> → rejected (notes adjust only from C).\n"
            "  ❌ BAD: C-class + sal=0.5 → rejected (low salience C-class isn't worth note change).\n"
            "  ❌ BAD: cite \"toggling\" with concern_id sir_interview_pr → rejected (cite ↔\n"
            "         concern no token overlap — wrong concern, fix4 anchor)."
        )

        # User block — give LLM evidence to ground thought
        lines = ["[CURRENT MOMENT]"]
        lines.append(f"  - Sir state: {evidence.get('sir_state')}")
        lines.append(f"  - idle: {evidence.get('idle_seconds')}s")
        lines.append(f"  - hour: {evidence.get('hour')}:00")
        lines.append("")

        lines.append("[RECENT SWM EVENTS]")
        sw = evidence.get('swm_events') or []
        if sw:
            for e in sw:
                lines.append(f"  - {e['age_s']}s ago: [{e['type']}] {e['desc']}")
        else:
            lines.append("  (none recent)")
        lines.append("")

        lines.append("[STM LAST 2 TURNS]")
        stm = evidence.get('stm') or []
        if stm:
            for t in stm:
                lines.append(f"  - when={t.get('when', '?')}")
                if t.get('user'):
                    lines.append(f"    Sir: \"{t['user']}\"")
                if t.get('jarvis'):
                    lines.append(f"    Me:  \"{t['jarvis']}\"")
        else:
            lines.append("  (no recent turns this session)")
        lines.append("")

        lines.append("[YOUR ACTIVE CONCERNS (top 5 by severity)]")
        cc = evidence.get('concerns') or []
        if cc:
            for c in cc:
                lines.append(
                    f"  - id={c['id']} (severity {c['severity']}): {c['what']}"
                )
        else:
            lines.append("  (none active)")
        # 🆕 [Sir 2026-05-25 23:18 真痛-2] 给全 active id list 防 hallucinate
        all_ids = evidence.get('all_active_concern_ids') or []
        if all_ids:
            lines.append(
                f"  ⚠️ ALL VALID concern_ids ({len(all_ids)}): "
                f"{', '.join(all_ids)}"
            )
            lines.append(
                "  ⚠️ For update_concern_severity, ONLY use IDs from above. "
                "Inventing IDs will fail."
            )
        lines.append("")

        if free_categories and len(free_categories) < 5:
            lines.append(
                f"[COOLDOWN] {free_str} are the ONLY non-cooldown categories. "
                f"Cooldown: {[c for c in 'ABCDE' if c not in free_categories]} "
                f"— pick from {free_str} only."
            )
            lines.append("")

        lines.append("Now generate ONE inner thought (4 tags strict).")
        return system, '\n'.join(lines)

    # ----------------------------------------------------------
    # LLM call (Flash-Lite via LlmReflector, caller='inner_thought' → P2 LOW)
    # ----------------------------------------------------------
    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        try:
            from jarvis_llm_reflector import LlmReflector
            from jarvis_key_router import KeyRouter
            # LlmReflector 用 __new__ 单例 — 直接构造即拿已有实例
            reflector = LlmReflector(key_router=self.key_router)
            res = reflector.reflect(
                model='flash_lite',
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                force=True,  # 不走 cache (每次新 think)
                caller=KeyRouter.CALLER_INNER_THOUGHT,  # 自动 LOW + 30/min 限速
            )
            if not res.get('success'):
                return ''
            return res.get('raw_text', '') or ''
        except Exception as e:
            self._bg_log(f"⚠️ [InnerThought] LLM call exception: {e}")
            return ''

    # ----------------------------------------------------------
    # Parse LLM output
    # ----------------------------------------------------------
    def _parse_thought(self, raw: str, sir_state: str,
                        tick_interval: int) -> Optional[InnerThought]:
        cat_m = re.search(r'<CATEGORY>\s*([A-E])\s*</CATEGORY>', raw, re.IGNORECASE)
        thought_m = re.search(r'<THOUGHT>(.*?)</THOUGHT>', raw, re.DOTALL)
        sal_m = re.search(r'<SALIENCE>\s*([0-9.]+)\s*</SALIENCE>', raw)
        action_m = re.search(r'<ACTIONABLE>(.*?)</ACTIONABLE>', raw, re.DOTALL)
        # 🆕 [Sir 2026-05-26 00:25 真痛"地基"] evidence link 解析
        ev_link_m = re.search(
            r'<EVIDENCE_LINK>(.*?)</EVIDENCE_LINK>', raw, re.DOTALL
        )
        if not (cat_m and thought_m and sal_m):
            return None
        thought_text = (thought_m.group(1) or '').strip()
        if not thought_text or thought_text.lower() in ('(quiet)', '(none)', '...'):
            return None
        try:
            sal = max(0.0, min(1.0, float(sal_m.group(1))))
        except (ValueError, TypeError):
            sal = 0.3
        actionable = (action_m.group(1).strip() if action_m else 'none')[:200]
        if not actionable:
            actionable = 'none'
        evidence_link = (
            (ev_link_m.group(1) or '').strip() if ev_link_m else ''
        )[:120]
        now = time.time()
        return InnerThought(
            id=f"thought_{time.strftime('%Y%m%d_%H%M%S')}_{int(now * 1000) % 10000:04x}",
            ts=now,
            ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
            category=cat_m.group(1).upper(),
            thought=thought_text[:300],
            salience=sal,
            actionable=actionable,
            actionable_done=False,
            actionable_result='pending',
            sir_state=sir_state,
            tick_interval_s=tick_interval,
            evidence_link=evidence_link,
        )

    # ----------------------------------------------------------
    # Actionable executor (4 档, 全可逆/低风险)
    # ----------------------------------------------------------
    def _execute_actionable(self, thought: InnerThought) -> Tuple[bool, str]:
        a = (thought.actionable or '').strip()
        if not a or a.lower() == 'none':
            return True, 'none'

        # 🆕 [Sir 2026-05-26 00:25 真痛"地基没打牢"] EVIDENCE LINK 校验 (HARD GATE)
        # actionable != none 时, LLM 必须 cite THOUGHT 中真实出现的字串证明 trace.
        # 缺 EVIDENCE_LINK 或 cite 字串不在 thought 里 → 降级 actionable=none.
        # 准则 5 言出必行 + 6 evidence: 无 evidence 不执行.
        gate_ok, gate_reason = self._validate_evidence_link(thought)
        if not gate_ok:
            # 降级: 不真执行 actionable, 标记 rejected (Sir 看 log 真知道原因)
            thought.actionable = 'none'  # 防 SOUL inject 误以为有 action
            return False, f'rejected_no_evidence_link:{gate_reason}'

        try:
            if a.startswith('update_concern_severity:'):
                ok, result = self._do_update_concern_severity(thought, a)
                # 🆕 [Sir 真痛 anchor] 二层 fail (cite ↔ concern wrong) →
                # 降级 thought.actionable=none 防 SOUL inject 误导主脑
                if not ok and 'evidence_link_wrong_concern' in result:
                    thought.actionable = 'none'
                return ok, result
            if a.startswith('publish_swm:'):
                return self._do_publish_swm_actionable(thought, a)
            if a.startswith('suggest_inside_joke:'):
                return self._do_suggest_inside_joke(thought, a)
            # 🆕 [Sir 2026-05-26 SOUL Phase A] propose_protocol — B 类反思真改自己行为
            # B 类 sal≥0.75 反思 → propose protocol → AutoArbiter 自决 →
            # Layer 2 SOUL "STRICT RULES" → 下次 turn 主脑硬约束.
            if a.startswith('propose_protocol:'):
                return self._do_propose_protocol(thought, a)
            # 🆕 [Sir 2026-05-26 SOUL Phase B] adjust_concern_notes — C 类反思改 concern note
            # C 类 sal≥0.7 反思 → 给 concern.notes_for_self append note →
            # Layer 1 prompt 主脑下次看 (现有路径) → 主脑自主调整对该 concern 反应方式.
            # Sir 真意 anchor: "减少对面试准备的打扰" → 改 concern.notes 让主脑下次克制.
            if a.startswith('adjust_concern_notes:'):
                ok, result = self._do_adjust_concern_notes(thought, a)
                # 二层 fail (cite ↔ concern wrong) → 降级 actionable=none (同 update_severity)
                if not ok and 'evidence_link_wrong_concern' in result:
                    thought.actionable = 'none'
                return ok, result
            return False, f'unknown_actionable:{a[:40]}'
        except Exception as e:
            return False, f'exception:{str(e)[:80]}'

    def _validate_evidence_link(self, thought: InnerThought
                                    ) -> Tuple[bool, str]:
        """🆕 [Sir 2026-05-26 00:25 真痛"地基没打牢"] 校验 evidence link.

        actionable != none 时, thought.evidence_link 必须:
          1. 非空 (LLM 真给了 cite)
          2. cite 字串 (lower, strip 标点) 真出现在 thought.thought (lower) 里
            (LLM 不能 cite thought 之外的词 — 防 hallucinate trace)

        返回:
          (True, '') — 通过校验, 真执行 actionable
          (False, reason) — 降级 actionable=none, log reason

        准则 6 evidence-driven + 5 言出必行: 无 evidence 不执行.
        """
        cite = (thought.evidence_link or '').strip()
        if not cite or cite.lower() in ('none', '(none)', '-'):
            return False, 'no_cite (LLM 没给 EVIDENCE_LINK)'

        # 归一化: lower + 去标点 (' " . , ! ? ; :)
        def _normalize(s: str) -> str:
            return re.sub(r'[\'".,!?;:\-]', '', s.lower()).strip()

        cite_norm = _normalize(cite)
        thought_norm = _normalize(thought.thought or '')
        if not cite_norm:
            return False, 'cite_empty_after_normalize'

        if cite_norm not in thought_norm:
            # 兜底: 拆词 (LLM 可能 cite "without rest" 而 thought 有 "needing rest"
            # → 分别 check "without" + "rest", 至少 50% words 命中也算)
            cite_words = [w for w in cite_norm.split() if len(w) > 2]
            if not cite_words:
                return False, f'cite_not_in_thought:"{cite[:40]}"'
            hits = sum(1 for w in cite_words if w in thought_norm)
            if hits < max(1, len(cite_words) // 2):
                return False, (
                    f'cite_not_in_thought:"{cite[:40]}" '
                    f'({hits}/{len(cite_words)} words match)'
                )
        return True, ''

    # 🆕 [Sir 2026-05-26 00:25 真痛 anchor] generic stopwords 防 token overlap 噪音
    # ("sir/i/my" 这种词所有 concern/thought 都有, 不能算 meaningful link)
    _GENERIC_STOPWORDS = frozenset({
        'sir', 'jarvis', 'i', 'me', 'my', 'you', 'your', 'we', 'us', 'our',
        'the', 'a', 'an', 'and', 'or', 'but', 'on', 'in', 'at', 'of', 'to',
        'for', 'with', 'is', 'are', 'was', 'were', 'has', 'have', 'had',
        'be', 'been', 'do', 'does', 'did', 'this', 'that', 'these', 'those',
        'it', 'its', 'his', 'her', 'them', 'their', 'as', 'so', 'if', 'than',
        'thought', 'noticed', 'thinking', 'wondering', 'just', 'now',
        'really', 'should', 'would', 'could', 'might', 'may', 'will',
        'shall', 'about', 'over', 'between', 'from', 'into', 'after',
        'before', 'still', 'also', 'very', 'quite',
    })

    def _meaningful_tokens(self, s: str) -> set:
        """拆词去 stopword + 短词 — 留 meaningful evidence tokens."""
        if not s:
            return set()
        words = re.findall(r'\w+', s.lower())
        return {
            w for w in words
            if len(w) > 2 and w not in self._GENERIC_STOPWORDS
        }

    def _evidence_links_to_concern(self, evidence_link: str,
                                       concern) -> Tuple[bool, str]:
        """🆕 [Sir 真痛 anchor 治本] cite 是否真 link 到 concern.

        cite 词跟 concern (id 拆 underscore + what_i_watch) 至少 1 个
        meaningful token 重合. 防"cite 真在 thought 但是 wrong concern"
        (Sir 真测 evidence: thought 提 toggling general/coding → cite=toggling →
         target=sir_interview_pr → 应 reject, toggling 跟 interview 无关).

        Returns: (ok, overlap_word_or_reason).
        """
        cite_tokens = self._meaningful_tokens(evidence_link)
        concern_id_tokens = self._meaningful_tokens(
            (getattr(concern, 'id', '') or '').replace('_', ' ')
        )
        concern_what_tokens = self._meaningful_tokens(
            getattr(concern, 'what_i_watch', '') or ''
        )
        concern_tokens = concern_id_tokens | concern_what_tokens
        if not cite_tokens:
            # cite 全 stopword 或空 — 不严判, LLM 不严就让过 (准则 6 信任 LLM)
            return True, '(no meaningful cite tokens — trust LLM)'
        if not concern_tokens:
            return True, '(concern has no meaningful tokens — trust LLM)'
        overlap = cite_tokens & concern_tokens
        if overlap:
            return True, f'overlap:{next(iter(overlap))}'
        return False, (
            f'no_token_overlap (cite:{sorted(cite_tokens)[:3]} vs '
            f'concern:{sorted(concern_tokens)[:3]})'
        )

    def _do_update_concern_severity(self, thought: InnerThought,
                                       a: str) -> Tuple[bool, str]:
        parts = a.split(':', 2)
        if len(parts) < 3:
            return False, 'parse_fail (expected update_concern_severity:<id>:<delta>)'
        _, cid, delta_str = parts
        cid = cid.strip()
        if not cid:
            return False, 'empty_concern_id'
        try:
            delta = float(delta_str.strip())
        except ValueError:
            return False, f'delta_not_float:{delta_str[:30]}'
        # cap ±SEVERITY_DELTA_CAP
        delta = max(-self.SEVERITY_DELTA_CAP, min(self.SEVERITY_DELTA_CAP, delta))
        if not self.concerns_ledger:
            return False, 'no_concerns_ledger'
        c = self.concerns_ledger.get(cid) if hasattr(
            self.concerns_ledger, 'get'
        ) else self.concerns_ledger.concerns.get(cid)
        if c is None:
            return False, f'concern_not_found:{cid}'
        # 🆕 [Sir 2026-05-26 00:25 真痛 anchor 治本] 二层校验: cite ↔ concern overlap
        # 真痛: cite 真在 thought 但 wrong concern (toggling → interview_pr).
        # 此处校验 cite 词跟 concern 至少 1 个 meaningful token 重合.
        link_ok, link_msg = self._evidence_links_to_concern(
            thought.evidence_link, c
        )
        if not link_ok:
            return False, f'evidence_link_wrong_concern:{cid}:{link_msg}'
        new_sev = max(0.0, min(1.0, c.severity + delta))
        if abs(new_sev - c.severity) < 1e-3:
            return True, f'no-op (already {c.severity:.2f})'
        ok, msg, old_v = self.concerns_ledger.update_concern_field(
            cid, 'severity', new_sev,
            source='inner_thought',
            turn_id=thought.id,
            reason=f"inner_thought [{thought.category}]: {thought.thought[:80]}",
        )
        if ok:
            return True, f'sev {old_v:.2f}→{new_sev:.2f} ({delta:+.2f})'
        return False, f'update_fail:{msg[:60]}'

    def _do_publish_swm_actionable(self, thought: InnerThought,
                                      a: str) -> Tuple[bool, str]:
        parts = a.split(':', 2)
        if len(parts) < 3:
            return False, 'parse_fail (expected publish_swm:<etype>:<desc>)'
        _, etype, desc = parts
        etype = etype.strip()[:60] or 'inner_thought_seed'
        desc = desc.strip()[:200]
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return False, 'no_bus'
            bus.publish(
                etype=etype,
                description=desc,
                source='inner_thought',
                salience=thought.salience,
                metadata={
                    'thought_id': thought.id,
                    'thought_category': thought.category,
                    'thought_text': thought.thought[:200],
                },
                ttl=3600.0,
            )
            return True, f'published:{etype}'
        except Exception as e:
            return False, f'publish_fail:{str(e)[:60]}'

    def _do_suggest_inside_joke(self, thought: InnerThought,
                                   a: str) -> Tuple[bool, str]:
        phrase = a.split(':', 1)[1].strip() if ':' in a else ''
        if not phrase:
            return False, 'empty_phrase'
        if not self.relational_state:
            return False, 'no_relational_state'
        if not hasattr(self.relational_state, 'propose_inside_joke'):
            return False, 'propose_inside_joke method not found'
        # build InsideJoke
        try:
            from jarvis_relational import InsideJoke
            joke = InsideJoke(
                id=f"joke_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 10000:04x}",
                phrase=phrase[:80],
                birth_context=f"inner_thought [{thought.category}]: {thought.thought[:120]}",
                tone='wry',  # default, Sir 可改
                source='inner_thought',
                source_marker=thought.id,
                birth_turn_id='',
            )
            ok = self.relational_state.propose_inside_joke(joke)
            return ok, f'proposed:{phrase[:30]}' if ok else 'dedup_or_fail'
        except Exception as e:
            return False, f'joke_build_fail:{str(e)[:60]}'

    def _do_propose_protocol(self, thought: InnerThought,
                                a: str) -> Tuple[bool, str]:
        """🆕 [Sir 2026-05-26 SOUL Phase A] propose UnspokenProtocol from B-class.

        actionable=propose_protocol:<one-sentence imperative rule>
        rule 必须:
          - 来自 B 类 self-reflection (强制 category check)
          - sal ≥ 0.75 (强制 salience gate, 低 sal 反思不值得 STRICT RULE)
          - rule 文字非空 + ≤ 200 char

        流程:
          parse rule → build UnspokenProtocol(state=REVIEW) →
          relational.propose_protocol → AutoArbiter 30min tick 自决 →
          Layer 2 SOUL inject 'STRICT RULES' → 下次 turn 主脑硬约束.
        """
        # 准则 5 言出必行 + 6 evidence: gate B 类 + sal
        if thought.category != 'B':
            return False, f'gated:protocol_only_from_B_reflect (got {thought.category})'
        if thought.salience < 0.75:
            return False, (
                f'gated:protocol_requires_sal>=0.75 (got {thought.salience:.2f})'
            )

        rule = a.split(':', 1)[1].strip() if ':' in a else ''
        if not rule:
            return False, 'empty_rule'
        if len(rule) < 10:
            return False, f'rule_too_short:{len(rule)}<10'

        if not self.relational_state:
            return False, 'no_relational_state'
        if not hasattr(self.relational_state, 'propose_protocol'):
            return False, 'propose_protocol method not found'

        try:
            from jarvis_relational import UnspokenProtocol
            pid = (
                f"proto_{time.strftime('%Y%m%d_%H%M%S')}"
                f"_{int(time.time() * 1000) % 10000:04x}"
            )
            protocol = UnspokenProtocol(
                id=pid,
                rule=rule[:200],
                source='inner_thought',
                source_marker=thought.id,
            )
            ok = self.relational_state.propose_protocol(protocol)
            return ok, (
                f'proposed:{rule[:30]} (id={pid})'
                if ok else 'dedup_or_fail'
            )
        except Exception as e:
            return False, f'protocol_build_fail:{str(e)[:60]}'

    # 🆕 [Sir 2026-05-26 SOUL Phase B] adjust_concern_notes constants
    _NOTES_MAX_CHARS = 500             # concern.notes_for_self 总长 cap (schema)
    _NOTES_APPEND_MAX = 120            # 单次 append note 长 cap (防一次写太长)

    def _do_adjust_concern_notes(self, thought: InnerThought,
                                    a: str) -> Tuple[bool, str]:
        """🆕 [Sir 2026-05-26 SOUL Phase B] adjust concern notes from C-class.

        actionable=adjust_concern_notes:<concern_id>:<note text>

        gate:
          - C 类 only (强制 category check) — A/B/D/E reflect 不改 concern notes
          - sal ≥ 0.7 (低 sal reflection 不值得改 concern note)
          - cid 真存在
          - 复用 evidence_link 双层 gate (cite 在 thought + cite ↔ concern overlap)

        流程:
          parse cid + note → 复用 _evidence_links_to_concern 二层 gate →
          existing_notes + ' | [inner_thought] ' + note → cap 500 →
          ConcernsLedger.update_concern_field('notes_for_self', new_value)
          → Layer 1 prompt 主脑下次自然读 (现有路径).

        Sir 真意 anchor: 上一轮 Sir 说"减少对面试准备的打扰" →
        C 类 thought: "Sir asked me to stop bringing up interview prep unprompted"
        actionable: adjust_concern_notes:sir_interview_pr:
                     DO NOT volunteer this topic — only address when Sir asks
        → 下次 turn 主脑读 note → 真克制.
        """
        # gate: C 类
        if thought.category != 'C':
            return False, (
                f'gated:notes_adjust_only_from_C_concern_evolve '
                f'(got {thought.category})'
            )
        # gate: sal
        if thought.salience < 0.7:
            return False, (
                f'gated:notes_adjust_requires_sal>=0.7 '
                f'(got {thought.salience:.2f})'
            )

        # parse "adjust_concern_notes:<cid>:<note>"
        parts = a.split(':', 2)
        if len(parts) < 3:
            return False, 'parse_fail (expected adjust_concern_notes:<cid>:<note>)'
        _, cid, note = parts
        cid = cid.strip()
        note = note.strip()
        if not cid:
            return False, 'empty_concern_id'
        if not note:
            return False, 'empty_note'
        if len(note) < 10:
            return False, f'note_too_short:{len(note)}<10'

        if not self.concerns_ledger:
            return False, 'no_concerns_ledger'

        # locate concern
        c = self.concerns_ledger.get(cid) if hasattr(
            self.concerns_ledger, 'get'
        ) else self.concerns_ledger.concerns.get(cid)
        if c is None:
            return False, f'concern_not_found:{cid}'

        # 二层 gate: cite ↔ concern overlap (复用 fix4 evidence_link 机制 — 防 wrong concern)
        link_ok, link_msg = self._evidence_links_to_concern(
            thought.evidence_link, c
        )
        if not link_ok:
            return False, f'evidence_link_wrong_concern:{cid}:{link_msg}'

        # build new notes (append 不覆盖 + tag 来源 + cap)
        note_capped = note[:self._NOTES_APPEND_MAX]
        existing = (c.notes_for_self or '').strip()
        tag = f"[inner_thought/{thought.category}/sal={thought.salience:.2f}]"
        new_note_segment = f"{tag} {note_capped}"
        if existing:
            new_notes = (existing + ' | ' + new_note_segment).strip(' |')
        else:
            new_notes = new_note_segment
        new_notes = new_notes[:self._NOTES_MAX_CHARS]

        # 用 update_concern_field 走标准 mutation 路径 (有 signal trail + 持久化)
        try:
            ok, msg, old_v = self.concerns_ledger.update_concern_field(
                cid, 'notes_for_self', new_notes,
                source='inner_thought',
                turn_id=thought.id,
                reason=f"inner_thought [{thought.category}]: {thought.thought[:80]}",
            )
            if ok:
                return True, (
                    f'notes appended ({len(new_note_segment)} char added, '
                    f'total {len(new_notes)}/{self._NOTES_MAX_CHARS})'
                )
            return False, f'update_fail:{msg[:60]}'
        except Exception as e:
            return False, f'notes_update_exception:{str(e)[:60]}'

    # ----------------------------------------------------------
    # SWM publish (jarvis_inner_thought event)
    # ----------------------------------------------------------
    def _publish_swm(self, thought: InnerThought) -> None:
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            bus.publish(
                etype='jarvis_inner_thought',
                description=f"[{thought.category}] {thought.thought[:120]}",
                source='inner_thought_daemon',
                salience=thought.salience,
                metadata={
                    'thought_id': thought.id,
                    'category': thought.category,
                    'salience': thought.salience,
                    'actionable': thought.actionable[:100],
                    'actionable_done': thought.actionable_done,
                    'actionable_result': thought.actionable_result[:80],
                    'sir_state': thought.sir_state,
                },
                ttl=86400.0,  # 24h, for SOUL inject lookback
            )
        except Exception:
            pass

    # ----------------------------------------------------------
    # Persistence (append-only jsonl)
    # ----------------------------------------------------------
    def _persist_thought(self, thought: InnerThought) -> None:
        try:
            os.makedirs(os.path.dirname(self.PERSIST_PATH), exist_ok=True)
            with open(self.PERSIST_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps(asdict(thought), ensure_ascii=False) + '\n')
            # 🆕 [Sir 2026-05-25 23:50 "防爆"] every 10 writes cheap stat check
            try:
                from jarvis_jsonl_rotator import maybe_rotate
                maybe_rotate(self.PERSIST_PATH, check_every_n_writes=10)
            except Exception:
                pass
            # 🆕 [Sir 2026-05-25 23:50 真问] B 类高 salience self-reflection
            # 真存 Hippocampus (长期 self-knowledge, 跨 24h jsonl cutoff 仍存)
            self._maybe_archive_to_hippocampus(thought)
        except Exception as e:
            self._bg_log(f"⚠️ [InnerThought] persist fail: {e}")

    # 🆕 [Sir 2026-05-25 23:50 真问 "反思要不要拿额外的记忆来存"]
    # B 类 sal >= 0.8 self-reflection (深刻自反思) → 真存 Hippocampus.
    # 设计 (准则 1 高效 + 6 evidence + 8 优雅):
    #   - 不每条 thought 都存 (cost 爆 + noise). 只存高 sal B 类 (真深刻反思).
    #   - 预计 ~5-20 条/月 (cost 极低, $0.001-$0.005/月)
    #   - 跨 24h jsonl cutoff 仍能 search (Hippocampus decay 30 天 halflife)
    #   - 长期演化基础: 几个月后 Sir 问 "你以前对自己有什么反思过?"
    #     Hippocampus 真能召回历史 self_reflection events
    HIPPOCAMPUS_ARCHIVE_THRESHOLD = 0.8

    def _maybe_archive_to_hippocampus(self, thought) -> None:
        """高 salience B 类反思 → Hippocampus 长期存."""
        if thought.category != 'B':
            return
        if thought.salience < self.HIPPOCAMPUS_ARCHIVE_THRESHOLD:
            return
        try:
            # 直接走 Hippocampus.add_memory (走 MemoryHub 太绕)
            hc = None
            if self.nerve:
                hc = getattr(self.nerve, 'hippocampus', None)
            if hc is None or not hasattr(hc, 'add_memory'):
                return
            # cost-light: 不抢 LLM caller 流量
            summary = (
                f"[Self-Reflection / sal={thought.salience:.2f}] "
                f"{thought.thought}"
            )
            try:
                hc.add_memory(
                    intent='self_reflection',
                    summary=summary,
                    entities=[{
                        'type': 'self_reflection',
                        'category': 'B',
                        'thought_id': thought.id,
                        'salience': thought.salience,
                        'sir_state': thought.sir_state,
                    }],
                    gemini_key='',  # add_memory 会自己经 key_router 拿 key
                )
                self._bg_log(
                    f"🧬 [InnerThought→Hippocampus] B-thought "
                    f"(sal={thought.salience:.2f}) archived to long-term memory"
                )
            except Exception as e:
                self._bg_log(
                    f"⚠️ [InnerThought→Hippocampus] archive fail (非致命): {e}"
                )
        except Exception:
            pass

    def _load_persist(self) -> None:
        if not os.path.exists(self.PERSIST_PATH):
            return
        try:
            cutoff = time.time() - 86400.0  # 24h
            with open(self.PERSIST_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        if d.get('ts', 0) < cutoff:
                            continue
                        self._thoughts.append(InnerThought(**d))
                    except (json.JSONDecodeError, TypeError):
                        continue
            # 🆕 [Sir 2026-05-26 00:20 真问"为什么不显示在想什么了"] 治本:
            # 不再从 persist 重建 _last_category_ts. 重启 = 新 session,
            # cooldown 全 reset 让 daemon 第一个 tick (60s) 真出新 thought.
            # SOUL inject 仍读 self._thoughts (给主脑 24h 历史连续性), 不丢.
            # 老 BUG: load 14 旧 thought → 5 类全 in cooldown → 23min 不动 →
            # Sir 终端零新 thought 显示, 误以为 daemon dead.
        except Exception as e:
            self._bg_log(f"⚠️ [InnerThought] load persist fail: {e}")

    # ----------------------------------------------------------
    # SOUL inject (called from central_nerve._build_layer_1b_*)
    # ----------------------------------------------------------
    def build_soul_block(self, max_chars: Optional[int] = None) -> str:
        """返回 SOUL inject block. top N by salience in last 24h, time-ordered."""
        if max_chars is None:
            max_chars = self.SOUL_INJECT_MAX_CHARS
        cutoff = time.time() - 86400.0
        with self._lock:
            recent = [t for t in self._thoughts if t.ts > cutoff]
        if not recent:
            return ''
        # top N by salience
        recent.sort(key=lambda t: -t.salience)
        top = recent[:self.SOUL_INJECT_MAX]
        # 时间排序 (旧到新) 让主脑看 narrative
        top.sort(key=lambda t: t.ts)

        lines = ["=== MY RECENT INNER THOUGHTS (last 24h, top by salience) ==="]
        now = time.time()
        for t in top:
            age_min = max(1, int((now - t.ts) / 60))
            action_str = ''
            if t.actionable and t.actionable.lower() != 'none':
                if t.actionable_done:
                    action_str = f" ✓ {t.actionable_result[:30]}"
                else:
                    action_str = f" → pending"
            lines.append(
                f"  [{t.category}/{age_min}min ago/sal {t.salience:.2f}] "
                f"{t.thought[:140]}{action_str}"
            )
        block = '\n'.join(lines)
        if len(block) > max_chars:
            block = block[:max_chars - 14].rstrip() + '\n…[truncated]'
        return block

    # ----------------------------------------------------------
    # Stats (for CLI dump / dashboard)
    # ----------------------------------------------------------
    def get_stats(self) -> dict:
        with self._lock:
            return {
                'tick_count': self._tick_count,
                'thought_count': self._thought_count,
                'cooldown_skip_count': self._cooldown_skip_count,
                'llm_fail_count': self._llm_fail_count,
                'loaded_thoughts_24h': len(self._thoughts),
                'last_category_ts': dict(self._last_category_ts),
                'current_sir_state': self._classify_sir_state(),
                'current_interval_s': self._compute_adaptive_interval(),
            }

    def list_recent_thoughts(self, max_n: int = 20) -> List[dict]:
        with self._lock:
            recent = sorted(self._thoughts, key=lambda t: -t.ts)[:max_n]
        return [asdict(t) for t in recent]

    # ----------------------------------------------------------
    # bg_log helper (lazy import to avoid circular)
    # ----------------------------------------------------------
    def _bg_log(self, msg: str) -> None:
        try:
            from jarvis_utils import bg_log
            bg_log(msg)
        except Exception:
            pass


# ==========================================================================
# Module-level singleton (optional, for ad-hoc access)
# ==========================================================================
_DEFAULT_DAEMON: Optional[InnerThoughtDaemon] = None


def get_default_daemon() -> Optional[InnerThoughtDaemon]:
    return _DEFAULT_DAEMON


def set_default_daemon(d: InnerThoughtDaemon) -> None:
    global _DEFAULT_DAEMON
    _DEFAULT_DAEMON = d
