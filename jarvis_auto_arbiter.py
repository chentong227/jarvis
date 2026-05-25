# -*- coding: utf-8 -*-
"""[AA / Sir 2026-05-25 22:58 自决] AutoArbiterDaemon — 让贾维斯自己拍板.

Sir 真意 (22:58):
  "让他自己拍板吧, 有任何不对地方我发日志给你, 你给我修复, 能做到吗?
   然后让他能自己迭代这种拍板的准确性, 通过每日的思考"

灵魂工程 Layer 2.5 — 自决引擎 (sit between Relational + Reflectors).

设计 (准则 6 evidence-driven + 准则 7 Sir 元否决 + 准则 8 优雅):

  ## 三档风险 (RISK)
    LOW    = {inside_joke, thread}      # 真自决 (activate/reject)
    MEDIUM = {concern, directive}        # propose_to_sir + UI badge "🤖 建议"
    HIGH   = (暂无, 全留 Sir)             # 不动

  ## 4 档决策 (DECISION)
    activate       — 真激活 (调 relational.activate_from_review)
    reject         — 真拒绝 (调 relational.reject_from_review)
    defer_to_sir   — 不执行, 写 'recommended' queue (UI badge)
    noop           — 不评 (confidence 太低 / dedup 已 fail / cap reached)

  ## per-category confidence 阈值 (calibration 可调, 准则 6 不写死)
    DEFAULT_THRESHOLDS = {
      'inside_joke': 0.75,  # 低风险, 中阈值
      'thread':      0.75,
      'concern':     0.85,  # 中风险, 高阈值
      'directive':   0.90,  # 中-高风险
    }

  ## Daily Self-Iteration (Sir 真问 "通过每日的思考")
    凌晨 03:xx 一次 reflection:
      - 看 24h decisions
      - per kind: count sir_reverted / total = revert_rate
      - rate > 30% → 阈值 +0.05 (cap 0.95) — 太激进, 收敛
      - rate < 10% AND total ≥ 5 → 阈值 -0.02 (floor 0.5) — 太保守, 放松
      - 持久化 calibration + publish SWM event

  ## Sir 反馈 (准则 7 元否决)
    Sir 在 dashboard 点撤销:
      - reverse 真动作 (activate→reject_from_review, reject→re-propose)
      - 标 sir_reverted=True + 记 reason
      - 计入 daily reflection 的 revert_rate
      - publish SWM 'sir_reverted_auto_arbitrate' event

  ## 防爆 cap (准则 1 高效)
    MAX_AUTO_DECISIONS_PER_DAY = 50 (per-kind 各 25)

  ## Caller 路由 (P2 集成)
    LLM caller='auto_arbiter' → 默认 LOW priority + 30/min 限速

成本估算:
  ~10 reviewable items/day × $0.000125/call (Flash-Lite) = $0.04/day = $1.2/月

参考:
  jarvis_relational.py  (activate_from_review / reject_from_review API)
  jarvis_inner_thought_daemon.py  (daemon pattern 参考)
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
class ArbiterDecision:
    """单条自决记录. 持久化 + Sir 一键撤销基础."""
    id: str
    ts: float
    ts_iso: str
    kind: str               # 'inside_joke' | 'thread' | 'concern' | 'directive'
    item_id: str            # 目标条目 id
    item_preview: str       # 短预览 (Sir dashboard 一眼)
    risk_level: str         # 'low' | 'medium' | 'high'
    decision: str           # 'activate' | 'reject' | 'defer_to_sir' | 'noop'
    confidence: float       # 0.0-1.0
    reason: str             # LLM 给的理由
    threshold_at_decision: float  # 当时用的阈值 (calibration 时回看)
    executed_ok: bool = False
    executed_at: float = 0.0
    execution_msg: str = ''
    sir_reverted: bool = False
    sir_reverted_at: float = 0.0
    sir_revert_reason: str = ''


# ==========================================================================
# Daemon
# ==========================================================================

class AutoArbiterDaemon:
    """Auto arbitration daemon. Jarvis 自己审 review queues + 真拍板.

    生命周期:
      __init__(key_router, relational_state, concerns_ledger, central_nerve)
      start() → 启 2 thread (tick + daily_reflection)
      stop()  → 停
      sir_revert(decision_id, reason) → Sir 一键撤销
    """

    PERSIST_PATH = 'memory_pool/auto_arbiter_log.jsonl'
    CALIBRATION_PATH = 'memory_pool/auto_arbiter_calibration.json'

    DEFAULT_THRESHOLDS = {
        'inside_joke': 0.75,
        'thread':      0.75,
        'concern':     0.85,
        'directive':   0.90,
    }
    THRESHOLD_FLOOR = 0.50
    THRESHOLD_CEILING = 0.95
    REVERT_RATE_HIGH = 0.30       # >30% → 阈值升 0.05
    REVERT_RATE_LOW = 0.10        # <10% & total≥5 → 阈值降 0.02
    THRESHOLD_RAISE_STEP = 0.05
    THRESHOLD_LOWER_STEP = 0.02

    # 风险分类
    RISK_LOW = frozenset({'inside_joke', 'thread'})
    RISK_MEDIUM = frozenset({'concern', 'directive'})
    KNOWN_KINDS = RISK_LOW | RISK_MEDIUM

    # tick
    TICK_INTERVAL_S = 1800           # 30min
    STARTUP_DELAY_S = 60             # 60s 让系统稳定
    DAILY_REFLECTION_HOUR = 3        # 03:xx
    REFLECTION_CHECK_INTERVAL_S = 600  # 10min 检查 hour

    # cap
    MAX_AUTO_DECISIONS_PER_DAY = 50  # 全局 cap
    MAX_PER_KIND_PER_DAY = 25        # per-kind cap

    def __init__(self, key_router, relational_state=None,
                  concerns_ledger=None, central_nerve=None):
        self.key_router = key_router
        self.relational = relational_state
        self.concerns = concerns_ledger
        self.nerve = central_nerve

        self._decisions: List[ArbiterDecision] = []
        self._calibration: dict = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._reflection_thread: Optional[threading.Thread] = None
        self._last_reflection_date = ''

        # stats
        self._tick_count = 0
        self._llm_call_count = 0
        self._llm_fail_count = 0

        # 启动加载
        self._load_persist()
        self._load_calibration()

    # ----------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._daemon_loop, name='AutoArbiterDaemon', daemon=True
        )
        self._thread.start()
        self._reflection_thread = threading.Thread(
            target=self._reflection_loop, name='AutoArbiterReflection',
            daemon=True
        )
        self._reflection_thread.start()
        self._bg_log(
            f"🤖 [AutoArbiter] daemon started "
            f"(loaded {len(self._decisions)} decisions from 7d, "
            f"thresholds={self._effective_thresholds()})"
        )

    def stop(self) -> None:
        self._stop.set()

    def _daemon_loop(self) -> None:
        self._stop.wait(timeout=self.STARTUP_DELAY_S)
        if self._stop.is_set():
            return
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                self._bg_log(f"⚠️ [AutoArbiter] tick exception: {e}")
            self._stop.wait(timeout=self.TICK_INTERVAL_S)

    def _reflection_loop(self) -> None:
        # 等 startup 后再启
        self._stop.wait(timeout=self.STARTUP_DELAY_S + 30)
        if self._stop.is_set():
            return
        while not self._stop.is_set():
            try:
                self._maybe_do_daily_reflection()
            except Exception as e:
                self._bg_log(
                    f"⚠️ [AutoArbiter] reflection exception: {e}"
                )
            self._stop.wait(timeout=self.REFLECTION_CHECK_INTERVAL_S)

    # ----------------------------------------------------------
    # Calibration (per-category confidence threshold)
    # ----------------------------------------------------------
    def _effective_thresholds(self) -> dict:
        """合并默认 + calibration (calibration 不存在则全用默认)."""
        out = dict(self.DEFAULT_THRESHOLDS)
        cal_th = (self._calibration or {}).get('thresholds') or {}
        for k, v in cal_th.items():
            if k in out:
                try:
                    out[k] = max(self.THRESHOLD_FLOOR,
                                  min(self.THRESHOLD_CEILING, float(v)))
                except (TypeError, ValueError):
                    pass
        return out

    def _load_calibration(self) -> None:
        if not os.path.exists(self.CALIBRATION_PATH):
            self._calibration = {
                'thresholds': dict(self.DEFAULT_THRESHOLDS),
                'revert_history_24h': {},
                'last_calibrated_at': 0,
                'last_calibrated_iso': '',
            }
            return
        try:
            with open(self.CALIBRATION_PATH, 'r', encoding='utf-8') as f:
                self._calibration = json.load(f) or {}
            if 'thresholds' not in self._calibration:
                self._calibration['thresholds'] = dict(self.DEFAULT_THRESHOLDS)
        except Exception as e:
            self._bg_log(f"⚠️ [AutoArbiter] load calibration fail: {e}")
            self._calibration = {
                'thresholds': dict(self.DEFAULT_THRESHOLDS),
                'revert_history_24h': {},
            }

    def _save_calibration(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.CALIBRATION_PATH), exist_ok=True)
            tmp = self.CALIBRATION_PATH + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._calibration, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.CALIBRATION_PATH)
        except Exception as e:
            self._bg_log(f"⚠️ [AutoArbiter] save calibration fail: {e}")

    # ----------------------------------------------------------
    # Tick (核心: 拉 review queues, per item evaluate + decide)
    # ----------------------------------------------------------
    def _tick(self) -> None:
        self._tick_count += 1
        if not self.relational:
            return
        # cap 检查
        today_count = self._count_today_decisions()
        if today_count >= self.MAX_AUTO_DECISIONS_PER_DAY:
            self._bg_log(
                f"🤖 [AutoArbiter] tick skipped: today cap reached "
                f"({today_count}/{self.MAX_AUTO_DECISIONS_PER_DAY})"
            )
            return

        # 拉 review queue (inside_joke + thread)
        items_to_eval: List[dict] = []
        try:
            jokes_review = self.relational.list_inside_jokes_review() or []
            for j in jokes_review:
                items_to_eval.append({
                    'kind': 'inside_joke', 'entity': j,
                    'preview': (j.phrase or '')[:80],
                })
        except Exception:
            pass
        try:
            threads_review = self.relational.list_threads_review() or []
            for t in threads_review:
                items_to_eval.append({
                    'kind': 'thread', 'entity': t,
                    'preview': (t.title or '')[:80],
                })
        except Exception:
            pass

        if not items_to_eval:
            return

        self._bg_log(
            f"🤖 [AutoArbiter] tick: {len(items_to_eval)} review items "
            f"(jokes + threads), evaluating..."
        )

        for item in items_to_eval:
            # 看决策过吗 (防重复)
            if self._already_decided_recently(item['kind'],
                                                self._entity_id(item['entity'])):
                continue

            # per-kind cap
            if self._count_today_decisions_by_kind(item['kind']) \
                    >= self.MAX_PER_KIND_PER_DAY:
                self._bg_log(
                    f"🤖 [AutoArbiter] {item['kind']} per-kind cap reached, skip"
                )
                continue
            # 评估 + 决策 + 执行 + 持久
            try:
                self._evaluate_and_decide(item)
            except Exception as e:
                self._bg_log(
                    f"⚠️ [AutoArbiter] eval fail for "
                    f"{item['kind']}/{self._entity_id(item['entity'])}: {e}"
                )

    def _entity_id(self, entity) -> str:
        return getattr(entity, 'id', '') or ''

    def _already_decided_recently(self, kind: str, item_id: str,
                                     within_h: float = 24) -> bool:
        cutoff = time.time() - within_h * 3600
        with self._lock:
            for d in self._decisions:
                if d.kind == kind and d.item_id == item_id and d.ts > cutoff:
                    return True
        return False

    def _count_today_decisions(self) -> int:
        today = time.strftime('%Y-%m-%d')
        with self._lock:
            return sum(1 for d in self._decisions
                        if time.strftime('%Y-%m-%d',
                                           time.localtime(d.ts)) == today
                        and d.decision in ('activate', 'reject'))

    def _count_today_decisions_by_kind(self, kind: str) -> int:
        today = time.strftime('%Y-%m-%d')
        with self._lock:
            return sum(1 for d in self._decisions
                        if d.kind == kind
                        and time.strftime('%Y-%m-%d',
                                           time.localtime(d.ts)) == today
                        and d.decision in ('activate', 'reject'))

    # ----------------------------------------------------------
    # Evaluate + decide
    # ----------------------------------------------------------
    def _evaluate_and_decide(self, item: dict) -> None:
        kind = item['kind']
        entity = item['entity']
        item_id = self._entity_id(entity)
        preview = item['preview']

        risk = ('low' if kind in self.RISK_LOW
                  else 'medium' if kind in self.RISK_MEDIUM
                  else 'high')

        # 收集 evidence
        evidence = self._collect_evidence(kind, entity)

        # LLM eval
        action, conf, reason = self._llm_evaluate(kind, entity, evidence)

        # 决策映射
        thresholds = self._effective_thresholds()
        thr = thresholds.get(kind, 0.80)
        decision = self._decide(action, conf, thr, risk)

        # build ArbiterDecision
        now = time.time()
        d = ArbiterDecision(
            id=f"aa_{time.strftime('%Y%m%d_%H%M%S')}_"
                f"{int(now * 1000) % 10000:04x}",
            ts=now,
            ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
            kind=kind,
            item_id=item_id,
            item_preview=preview[:100],
            risk_level=risk,
            decision=decision,
            confidence=conf,
            reason=reason[:300],
            threshold_at_decision=thr,
        )

        # 执行
        if decision in ('activate', 'reject'):
            ok, msg = self._execute(kind, item_id, decision)
            d.executed_ok = ok
            d.executed_at = time.time()
            d.execution_msg = msg[:200]
        # defer_to_sir / noop: 不执行

        # persist + log
        with self._lock:
            self._decisions.append(d)
        self._persist_decision(d)
        self._publish_swm(d)

        self._bg_log(
            f"🤖 [AutoArbiter] [{kind}/{item_id[:20]}] "
            f"sal={conf:.2f}/thr={thr:.2f} → {decision.upper()} "
            f"({'OK' if d.executed_ok else 'NOEXEC' if decision in ('defer_to_sir', 'noop') else 'FAIL'}) "
            f"| reason: {reason[:80]}"
        )

    def _decide(self, action: str, conf: float, thr: float,
                  risk: str) -> str:
        """映射 LLM action + confidence → 最终 decision (4 档).

        LOW risk: confidence >= thr → 真 activate/reject; else defer_to_sir
        MEDIUM risk: 不真执行, 全 defer_to_sir (Sir 在 dashboard 看 '🤖 建议')
        """
        if action not in ('activate', 'reject'):
            return 'noop'
        if conf < thr:
            return 'defer_to_sir'
        if risk == 'low':
            return action
        # medium: 只建议不真做
        return 'defer_to_sir'

    # ----------------------------------------------------------
    # Evidence collection
    # ----------------------------------------------------------
    def _collect_evidence(self, kind: str, entity) -> dict:
        ev = {'kind': kind, 'entity': {}}
        try:
            if kind == 'inside_joke':
                ev['entity'] = {
                    'phrase': getattr(entity, 'phrase', ''),
                    'birth_context': getattr(entity, 'birth_context', ''),
                    'tone': getattr(entity, 'tone', ''),
                    'source': getattr(entity, 'source', ''),
                }
                # 现有 active jokes (dedup 参考)
                active_jokes = [j for j in self.relational.inside_jokes.values()
                                  if getattr(j, 'state', '') == 'active']
                ev['existing_active_jokes'] = [
                    {'phrase': j.phrase[:80], 'tone': j.tone}
                    for j in active_jokes[:5]
                ]
            elif kind == 'thread':
                ev['entity'] = {
                    'title': getattr(entity, 'title', ''),
                    'detail': getattr(entity, 'detail', '')[:200],
                    'source': getattr(entity, 'source', ''),
                }
                active_threads = [t for t in
                                    self.relational.shared_history_threads.values()
                                    if getattr(t, 'state', '') == 'active']
                ev['existing_active_threads'] = [
                    {'title': t.title[:80]}
                    for t in active_threads[:5]
                ]
        except Exception:
            pass
        # STM 最近 5 turn (主脑近况)
        try:
            stm = []
            if self.nerve and getattr(self.nerve, 'short_term_memory', None):
                for t in list(self.nerve.short_term_memory)[-5:]:
                    stm.append({
                        'user': (t.get('user') or '')[:120],
                        'jarvis': (t.get('jarvis') or '')[:150],
                    })
            ev['stm'] = stm
        except Exception:
            ev['stm'] = []
        return ev

    # ----------------------------------------------------------
    # LLM evaluate (Flash-Lite, caller='auto_arbiter' → LOW)
    # ----------------------------------------------------------
    def _llm_evaluate(self, kind: str, entity,
                        evidence: dict) -> Tuple[str, float, str]:
        """调 LLM 评估 + 返 (action, confidence, reason).

        action: 'activate' | 'reject'  (LLM 不输出 defer/noop, 那是阈值映射)
        confidence: 0.0-1.0
        reason: <= 300 char
        """
        system, user = self._build_prompt(kind, entity, evidence)
        raw = self._call_llm(system, user)
        if not raw:
            self._llm_fail_count += 1
            return 'reject', 0.0, 'LLM call failed (treat as reject by default)'
        return self._parse_llm_output(raw)

    def _build_prompt(self, kind: str, entity,
                        evidence: dict) -> Tuple[str, str]:
        system = (
            f"You are J.A.R.V.I.S. acting as Sir's deputy auditor for the "
            f"{kind} review queue. A reflector has proposed a new {kind}; you "
            f"must decide ACTIVATE or REJECT based on evidence.\n\n"
            f"Output FORMAT (strict, 3 tags all required):\n"
            f"<ACTION>ACTIVATE|REJECT</ACTION>\n"
            f"<CONFIDENCE>0.0-1.0</CONFIDENCE>\n"
            f"<REASON>1-2 sentences explaining your judgment, citing "
            f"specific evidence (existing dedup / Sir's STM usage / "
            f"quality / tone fit).</REASON>\n\n"
            f"Decision criteria for {kind}:\n"
        )
        if kind == 'inside_joke':
            system += (
                "  ACTIVATE if: phrase is genuinely callback-worthy, fits "
                "Sir's casual tone, NOT redundant with existing active jokes, "
                "has real evidence in Sir's recent STM.\n"
                "  REJECT if: dry / forced / one-off / overlaps with existing "
                "joke / no STM evidence / Sir would find it cringey.\n"
                "  CONFIDENCE high (0.8+) only when 2+ STM hits OR very clean "
                "callback. Otherwise <0.7.\n"
            )
        elif kind == 'thread':
            system += (
                "  ACTIVATE if: real milestone Sir mentioned ≥ 2 times, "
                "distinct from existing active threads, has clear "
                "title + concrete detail.\n"
                "  REJECT if: vague / generic / overlaps with existing thread "
                "(e.g. another 'data alignment milestone' #4) / no STM "
                "evidence Sir cares.\n"
                "  CONFIDENCE high (0.8+) only when 2+ STM hits AND clearly "
                "distinct. Otherwise <0.7.\n"
            )
        else:
            system += (
                "  (Generic) Use evidence to judge. Be conservative — when "
                "in doubt REJECT with low confidence.\n"
            )
        system += (
            "\nRules (准则 5+6+8):\n"
            "  - Cite specific evidence; do NOT hallucinate facts not in "
            "the input below.\n"
            "  - When in doubt, REJECT with low confidence (Sir 会兜底).\n"
            "  - Brief, factual, no Sir-flatter."
        )

        # user
        ent = evidence.get('entity', {})
        if kind == 'inside_joke':
            user_lines = ["[CANDIDATE INSIDE_JOKE]"]
            user_lines.append(f"  phrase:        \"{ent.get('phrase', '')}\"")
            user_lines.append(
                f"  birth_context: \"{(ent.get('birth_context') or '')[:160]}\""
            )
            user_lines.append(f"  tone:          {ent.get('tone', '')}")
            user_lines.append(f"  source:        {ent.get('source', '')}")
            user_lines.append("")
            user_lines.append("[EXISTING ACTIVE JOKES (dedup reference)]")
            existing = evidence.get('existing_active_jokes') or []
            if existing:
                for j in existing:
                    user_lines.append(
                        f"  - \"{j['phrase']}\" (tone={j['tone']})"
                    )
            else:
                user_lines.append("  (none active)")
        elif kind == 'thread':
            user_lines = ["[CANDIDATE SHARED_HISTORY_THREAD]"]
            user_lines.append(f"  title:  \"{ent.get('title', '')}\"")
            user_lines.append(
                f"  detail: \"{(ent.get('detail') or '')[:180]}\""
            )
            user_lines.append(f"  source: {ent.get('source', '')}")
            user_lines.append("")
            user_lines.append("[EXISTING ACTIVE THREADS (dedup reference)]")
            existing = evidence.get('existing_active_threads') or []
            if existing:
                for t in existing:
                    user_lines.append(f"  - \"{t['title']}\"")
            else:
                user_lines.append("  (none active)")
        else:
            user_lines = [f"[CANDIDATE {kind.upper()}]", repr(ent)[:300]]

        user_lines.append("")
        user_lines.append("[SIR RECENT STM (last 5 turns)]")
        stm = evidence.get('stm') or []
        if stm:
            for t in stm:
                if t.get('user'):
                    user_lines.append(f"  Sir:    \"{t['user']}\"")
                if t.get('jarvis'):
                    user_lines.append(f"  Me:     \"{t['jarvis']}\"")
        else:
            user_lines.append("  (no recent STM)")
        user_lines.append("")
        user_lines.append(
            "Now output your decision (3 tags strict)."
        )
        return system, '\n'.join(user_lines)

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        try:
            from jarvis_llm_reflector import LlmReflector
            from jarvis_key_router import KeyRouter
            reflector = LlmReflector(key_router=self.key_router)
            self._llm_call_count += 1
            res = reflector.reflect(
                model='flash_lite',
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                force=True,
                caller=getattr(KeyRouter, 'CALLER_AUTO_ARBITER',
                                'auto_arbiter'),  # auto_arbiter → LOW
            )
            if not res.get('success'):
                return ''
            return res.get('raw_text', '') or ''
        except Exception as e:
            self._bg_log(f"⚠️ [AutoArbiter] LLM call exception: {e}")
            return ''

    def _parse_llm_output(self, raw: str) -> Tuple[str, float, str]:
        action_m = re.search(r'<ACTION>\s*(ACTIVATE|REJECT)\s*</ACTION>',
                                raw, re.IGNORECASE)
        conf_m = re.search(r'<CONFIDENCE>\s*([0-9.]+)\s*</CONFIDENCE>', raw)
        reason_m = re.search(r'<REASON>(.*?)</REASON>', raw, re.DOTALL)
        if not (action_m and conf_m):
            return 'reject', 0.0, f'LLM output parse fail: {raw[:120]}'
        action = action_m.group(1).lower()
        try:
            conf = max(0.0, min(1.0, float(conf_m.group(1))))
        except (ValueError, TypeError):
            conf = 0.0
        reason = reason_m.group(1).strip()[:300] if reason_m else ''
        return action, conf, reason

    # ----------------------------------------------------------
    # Execute decision (真调 relational API)
    # ----------------------------------------------------------
    def _execute(self, kind: str, item_id: str,
                  action: str) -> Tuple[bool, str]:
        if kind in ('inside_joke', 'thread'):
            try:
                if action == 'activate':
                    res_kind = self.relational.activate_from_review(item_id)
                    if not res_kind:
                        return False, f'activate_from_review returned empty (item_id={item_id})'
                    # persist
                    try:
                        self.relational.persist()
                        self.relational.write_review_queue()
                    except Exception:
                        pass
                    return True, f'activated as {res_kind}'
                elif action == 'reject':
                    res_kind = self.relational.reject_from_review(item_id)
                    if not res_kind:
                        return False, f'reject_from_review returned empty'
                    try:
                        self.relational.persist()
                        self.relational.write_review_queue()
                    except Exception:
                        pass
                    return True, f'rejected as {res_kind}'
                else:
                    return False, f'unknown action {action}'
            except Exception as e:
                return False, f'exec exception: {str(e)[:100]}'
        return False, f'kind {kind} not supported for auto-execute'

    # ----------------------------------------------------------
    # Sir 撤销 (准则 7 元否决)
    # ----------------------------------------------------------
    def sir_revert(self, decision_id: str,
                    reason: str = '') -> Tuple[bool, str]:
        """Sir 一键撤销某条 auto decision.

        撤销规则:
          - 当时 activate → 撤销 = reject_from_review (退回 review 状态需重 propose)
            实际: archive 已 active 的 → Sir 看不到, joke 不会再 inject
          - 当时 reject → 撤销 = 重 propose (难: archive 已 archive 的 → ???)
            简化: 仅记 sir_reverted 标记, 不真撤回 (rejected 的不易回)
          - 当时 defer_to_sir / noop → 仅记标记, 无副作用
        """
        target: Optional[ArbiterDecision] = None
        with self._lock:
            for d in self._decisions:
                if d.id == decision_id:
                    target = d
                    break
        if target is None:
            return False, f'decision {decision_id} not found'
        if target.sir_reverted:
            return False, f'already reverted at {target.sir_reverted_at}'

        msg = 'marked as reverted'
        try:
            if target.decision == 'activate' and target.executed_ok:
                # 反向 reject (archive 已 active 的)
                if self.relational and target.kind in ('inside_joke', 'thread'):
                    # 直接 setattr state=archived (因 active 的不能 reject_from_review)
                    try:
                        store_map = {
                            'inside_joke': self.relational.inside_jokes,
                            'thread': self.relational.shared_history_threads,
                        }
                        store = store_map.get(target.kind)
                        if store and target.item_id in store:
                            entity = store[target.item_id]
                            entity.state = 'archived'
                            self.relational._dirty = True
                            self.relational.persist()
                            self.relational.write_review_queue()
                            msg = f'reverted: {target.kind} {target.item_id} → archived'
                    except Exception as e:
                        msg = f'revert exec exception: {str(e)[:100]}'
            elif target.decision == 'reject' and target.executed_ok:
                # 反向 activate: 把已 archive 的重激活 (Sir 后悔拒了)
                if self.relational and target.kind in ('inside_joke', 'thread'):
                    try:
                        store_map = {
                            'inside_joke': self.relational.inside_jokes,
                            'thread': self.relational.shared_history_threads,
                        }
                        store = store_map.get(target.kind)
                        if store and target.item_id in store:
                            entity = store[target.item_id]
                            entity.state = 'active'
                            self.relational._dirty = True
                            self.relational.persist()
                            self.relational.write_review_queue()
                            msg = f'reverted: {target.kind} {target.item_id} → active'
                    except Exception as e:
                        msg = f'revert exec exception: {str(e)[:100]}'
        except Exception as e:
            msg = f'revert exception: {str(e)[:100]}'

        # 标记 + 持久 + publish SWM
        with self._lock:
            target.sir_reverted = True
            target.sir_reverted_at = time.time()
            target.sir_revert_reason = (reason or '')[:200]
        # rewrite (append a new line with same id, dashboard 看时取最新)
        self._persist_decision(target)

        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                bus.publish(
                    etype='sir_reverted_auto_arbitrate',
                    description=(
                        f"Sir reverted auto {target.decision} of "
                        f"{target.kind} {target.item_id} — reason: {reason[:80]}"
                    ),
                    source='auto_arbiter',
                    salience=0.7,
                    metadata={
                        'decision_id': decision_id,
                        'kind': target.kind,
                        'item_id': target.item_id,
                        'orig_decision': target.decision,
                        'reason': reason[:200],
                    },
                    ttl=86400.0,
                )
        except Exception:
            pass

        self._bg_log(
            f"🔄 [AutoArbiter] sir_revert {target.kind}/{target.item_id} "
            f"({target.decision}) → {msg} | Sir reason: {reason[:80]}"
        )
        return True, msg

    # ----------------------------------------------------------
    # Daily reflection (Sir 真问 "通过每日的思考迭代准确性")
    # ----------------------------------------------------------
    def _maybe_do_daily_reflection(self) -> None:
        """每天 03:xx 检查时 fire 一次 (一天最多 1 次)."""
        now_local = time.localtime()
        today = time.strftime('%Y-%m-%d', now_local)
        if now_local.tm_hour != self.DAILY_REFLECTION_HOUR:
            return
        if self._last_reflection_date == today:
            return
        self._last_reflection_date = today
        self._do_daily_reflection()

    def _do_daily_reflection(self) -> None:
        """看 24h decisions, per kind 算 revert_rate, 调阈值."""
        cutoff = time.time() - 86400.0
        recent: List[ArbiterDecision] = []
        with self._lock:
            recent = [d for d in self._decisions if d.ts > cutoff]
        if not recent:
            self._bg_log(
                "🌙 [AutoArbiter] daily reflection: no decisions in last 24h"
            )
            return

        per_kind = {}
        for d in recent:
            if d.decision not in ('activate', 'reject'):
                continue
            k = d.kind
            if k not in per_kind:
                per_kind[k] = {'total': 0, 'reverted': 0}
            per_kind[k]['total'] += 1
            if d.sir_reverted:
                per_kind[k]['reverted'] += 1

        changes = []
        thresholds = self._effective_thresholds()
        for kind, stat in per_kind.items():
            total = stat['total']
            if total == 0:
                continue
            revert_rate = stat['reverted'] / total
            old_thr = thresholds.get(kind, 0.80)
            new_thr = old_thr
            why = ''
            if revert_rate > self.REVERT_RATE_HIGH:
                new_thr = min(self.THRESHOLD_CEILING,
                                old_thr + self.THRESHOLD_RAISE_STEP)
                why = f'revert_rate={revert_rate:.0%} > {int(self.REVERT_RATE_HIGH*100)}% (over-confident)'
            elif (revert_rate < self.REVERT_RATE_LOW and total >= 5
                    and old_thr > self.THRESHOLD_FLOOR):
                new_thr = max(self.THRESHOLD_FLOOR,
                                old_thr - self.THRESHOLD_LOWER_STEP)
                why = f'revert_rate={revert_rate:.0%} < {int(self.REVERT_RATE_LOW*100)}% (too conservative)'
            if abs(new_thr - old_thr) > 1e-3:
                self._calibration.setdefault('thresholds', {})[kind] = new_thr
                changes.append({
                    'kind': kind, 'total': total, 'reverted': stat['reverted'],
                    'old_thr': old_thr, 'new_thr': new_thr, 'why': why,
                })

        self._calibration['revert_history_24h'] = per_kind
        self._calibration['last_calibrated_at'] = time.time()
        self._calibration['last_calibrated_iso'] = time.strftime(
            '%Y-%m-%dT%H:%M:%S'
        )
        self._save_calibration()

        if changes:
            summary = '; '.join(
                f"{c['kind']}: {c['old_thr']:.2f}→{c['new_thr']:.2f} ({c['why']})"
                for c in changes
            )
            self._bg_log(
                f"🌙 [AutoArbiter] daily reflection: {len(recent)} decisions, "
                f"adjusted {len(changes)} thresholds | {summary}"
            )
            try:
                from jarvis_utils import get_event_bus
                bus = get_event_bus()
                if bus is not None:
                    bus.publish(
                        etype='auto_arbiter_calibration_updated',
                        description=summary,
                        source='auto_arbiter',
                        salience=0.6,
                        metadata={'changes': changes,
                                    'total_decisions_24h': len(recent)},
                        ttl=86400.0 * 3,
                    )
            except Exception:
                pass
        else:
            self._bg_log(
                f"🌙 [AutoArbiter] daily reflection: {len(recent)} decisions, "
                f"thresholds stable"
            )

    # ----------------------------------------------------------
    # Persistence
    # ----------------------------------------------------------
    def _persist_decision(self, d: ArbiterDecision) -> None:
        try:
            os.makedirs(os.path.dirname(self.PERSIST_PATH), exist_ok=True)
            with open(self.PERSIST_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps(asdict(d), ensure_ascii=False) + '\n')
        except Exception as e:
            self._bg_log(f"⚠️ [AutoArbiter] persist fail: {e}")

    def _load_persist(self) -> None:
        if not os.path.exists(self.PERSIST_PATH):
            return
        try:
            cutoff = time.time() - 7 * 86400.0  # 7d 历史
            latest_by_id: dict = {}
            with open(self.PERSIST_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get('ts', 0) < cutoff:
                            continue
                        # 同 id 多次写 (revert), 取最新
                        latest_by_id[rec.get('id')] = rec
                    except (json.JSONDecodeError, TypeError):
                        continue
            for rec in latest_by_id.values():
                try:
                    self._decisions.append(ArbiterDecision(**rec))
                except (TypeError, KeyError):
                    continue
        except Exception as e:
            self._bg_log(f"⚠️ [AutoArbiter] load fail: {e}")

    def _publish_swm(self, d: ArbiterDecision) -> None:
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            bus.publish(
                etype='auto_arbiter_decision',
                description=(
                    f"[{d.decision}/{d.kind}] {d.item_preview[:80]} "
                    f"(conf {d.confidence:.2f}/thr {d.threshold_at_decision:.2f})"
                ),
                source='auto_arbiter',
                salience=d.confidence if d.decision != 'noop' else 0.3,
                metadata={
                    'decision_id': d.id,
                    'kind': d.kind,
                    'item_id': d.item_id,
                    'decision': d.decision,
                    'confidence': d.confidence,
                    'executed_ok': d.executed_ok,
                    'risk_level': d.risk_level,
                },
                ttl=86400.0,
            )
        except Exception:
            pass

    # ----------------------------------------------------------
    # Stats (dashboard / CLI 用)
    # ----------------------------------------------------------
    def get_stats(self) -> dict:
        with self._lock:
            decisions = list(self._decisions)
        now = time.time()
        h24 = now - 86400.0
        h24_decisions = [d for d in decisions if d.ts > h24]
        per_kind_24h = {}
        for d in h24_decisions:
            k = d.kind
            if k not in per_kind_24h:
                per_kind_24h[k] = {
                    'total': 0, 'activate': 0, 'reject': 0,
                    'defer_to_sir': 0, 'noop': 0, 'reverted': 0,
                }
            per_kind_24h[k]['total'] += 1
            per_kind_24h[k][d.decision] = per_kind_24h[k].get(d.decision, 0) + 1
            if d.sir_reverted:
                per_kind_24h[k]['reverted'] += 1
        return {
            'total_decisions_loaded': len(decisions),
            'decisions_24h': len(h24_decisions),
            'per_kind_24h': per_kind_24h,
            'effective_thresholds': self._effective_thresholds(),
            'tick_count': self._tick_count,
            'llm_call_count': self._llm_call_count,
            'llm_fail_count': self._llm_fail_count,
            'last_reflection_iso': (self._calibration or {}).get(
                'last_calibrated_iso', ''
            ),
        }

    def list_recent_decisions(self, max_n: int = 50,
                                 hours: float = 24.0) -> List[dict]:
        cutoff = time.time() - hours * 3600.0
        with self._lock:
            recent = [d for d in self._decisions if d.ts > cutoff]
        recent.sort(key=lambda d: -d.ts)
        return [asdict(d) for d in recent[:max_n]]

    # ----------------------------------------------------------
    # bg_log helper
    # ----------------------------------------------------------
    def _bg_log(self, msg: str) -> None:
        try:
            from jarvis_utils import bg_log
            bg_log(msg)
        except Exception:
            pass


# ==========================================================================
# Module-level singleton
# ==========================================================================
_DEFAULT_DAEMON: Optional[AutoArbiterDaemon] = None


def get_default_daemon() -> Optional[AutoArbiterDaemon]:
    return _DEFAULT_DAEMON


def set_default_daemon(d: AutoArbiterDaemon) -> None:
    global _DEFAULT_DAEMON
    _DEFAULT_DAEMON = d
