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
        self._bg_log(
            f"💭 [InnerThought] daemon started "
            f"(loaded {len(self._thoughts)} thoughts from last 24h)"
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
        self._bg_log(
            f"💭 [InnerThought] [{thought.category}/sal={thought.salience:.2f}"
            f"/state={sir_state}/tick={tick_interval}s] {thought.thought[:100]}"
            f"{action_str}"
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

    # 准则 6 — keyword 检测 self-correction 模式 (vocab 持久化后续)
    _SELF_CORRECTION_PATTERNS = (
        'i keep repeating', 'i keep saying', 'embarrassing pattern',
        'circular logic', 'shouldn\'t bring up', 'i should stop',
        '我反复', '我又说', '我不该再', '我不应该再',
    )

    def _maybe_publish_self_correction(self, thought) -> None:
        """🆕 [Sir 2026-05-25 23:18] B 类自反思闭环.

        看到 'i keep repeating X' 类 thought → publish SWM 让主脑下轮真看到.
        准则 6: keyword 持久化是后续 (现在 inline list, 等 reflector L7 propose 迁 vocab).
        """
        if thought.category != 'B':
            return
        thought_lower = (thought.thought or '').lower()
        hit_pattern = None
        for p in self._SELF_CORRECTION_PATTERNS:
            if p in thought_lower:
                hit_pattern = p
                break
        if not hit_pattern:
            return
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            bus.publish(
                etype='self_correction_noted',
                description=(
                    f"I just noticed myself: {thought.thought[:140]}. "
                    f"Next reply: don't repeat this pattern."
                ),
                source='inner_thought_daemon',
                salience=0.85,  # 高 salience 让 SOUL 真 inject
                metadata={
                    'thought_id': thought.id,
                    'category': 'B',
                    'hit_pattern': hit_pattern,
                    'thought_excerpt': thought.thought[:200],
                },
                ttl=3600.0 * 6,  # 6h ttl — 短期纠正足够
            )
            self._bg_log(
                f"🪞 [InnerThought/self-correction] B-thought matched "
                f"'{hit_pattern}' → publish self_correction_noted SWM "
                f"(主脑下轮 SOUL inject 真看到)"
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
            "Output FORMAT (strict, all 4 tags required):\n"
            f"<CATEGORY>{'|'.join(free_categories) if free_categories else 'A|B|C|D|E'}"
            "</CATEGORY>  ← ONLY these are NOT in cooldown right now\n"
            "<THOUGHT>1-2 sentences, first-person ('I noticed...', 'I'm thinking...'), "
            "casual self-talk, NOT formal speech to Sir.</THOUGHT>\n"
            "<SALIENCE>0.0-1.0 (0.7+ = worth bringing up later; 0.3- = passing)</SALIENCE>\n"
            "<ACTIONABLE>one of: none | "
            "update_concern_severity:<concern_id>:<+/-delta> | "
            "publish_swm:<etype>:<short_desc> | "
            "suggest_inside_joke:<phrase></ACTIONABLE>\n\n"
            "5 categories (pick the ONE most fitting):\n"
            "  [A] OBSERVATION — Sir's current state (screen/app/mood/activity).\n"
            "  [B] SELF-REFLECT — your own recent reply (tone / mistake / pattern).\n"
            "  [C] CONCERN-EVOLUTION — should a concern severity change? "
            "(use update_concern_severity with REAL concern_id from evidence below)\n"
            "  [D] PROACTIVE-SEED — what to silently do next? "
            "(use publish_swm so future-you sees it)\n"
            "  [E] RELATIONSHIP — inside joke / callback-worthy phrase "
            "(use suggest_inside_joke if real callback worthy)\n\n"
            "Rules (准则 5 言出必行 + 6 evidence + 8 优雅):\n"
            "  - DO NOT invent facts/numbers you can't see in evidence.\n"
            "  - Use REAL concern IDs from evidence — never invent IDs.\n"
            "  - update_concern_severity delta capped ±0.2 per thought.\n"
            "  - publish_swm etype: short snake_case (e.g. 'sir_seems_tired').\n"
            "  - If nothing meaningful comes, output <THOUGHT>(quiet)</THOUGHT> "
            "<SALIENCE>0.0</SALIENCE> <ACTIONABLE>none</ACTIONABLE> — "
            "and that's perfectly fine.\n"
            "  - Keep first-person, brief, like genuine self-talk."
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
        )

    # ----------------------------------------------------------
    # Actionable executor (4 档, 全可逆/低风险)
    # ----------------------------------------------------------
    def _execute_actionable(self, thought: InnerThought) -> Tuple[bool, str]:
        a = (thought.actionable or '').strip()
        if not a or a.lower() == 'none':
            return True, 'none'

        try:
            if a.startswith('update_concern_severity:'):
                return self._do_update_concern_severity(thought, a)
            if a.startswith('publish_swm:'):
                return self._do_publish_swm_actionable(thought, a)
            if a.startswith('suggest_inside_joke:'):
                return self._do_suggest_inside_joke(thought, a)
            return False, f'unknown_actionable:{a[:40]}'
        except Exception as e:
            return False, f'exception:{str(e)[:80]}'

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
        except Exception as e:
            self._bg_log(f"⚠️ [InnerThought] persist fail: {e}")

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
            # rebuild _last_category_ts from loaded
            for t in self._thoughts:
                cat_ts = self._last_category_ts.get(t.category, 0.0)
                if t.ts > cat_ts:
                    self._last_category_ts[t.category] = t.ts
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
