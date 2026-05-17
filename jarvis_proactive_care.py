# -*- coding: utf-8 -*-
"""
[P0+20-β.2.8 / 2026-05-17] ProactiveCareEngine — 主动关心引擎

设计参见: docs/JARVIS_PROACTIVE_CARE_ENGINE.md

替代 SmartNudge 8 类硬模板 + 4 次/天硬上限的旧机制. 新机制由 L1 ConcernsLedger
驱动: 所有 active concerns 综合 urgency 评分 + L0/L2 修正, top 1 concern 转为
nudge directive 走 stream_nudge 出声.

阶段:
- β-1 (本): 框架 + CareSignalCollector + ProactiveCareEngine daemon, 默认 dry-run
- β-2:     CareWindowGuard 强化 + CareSubjectSelector 选素材
- β-3:     替换 nudge_directives 8 类模板 + 关旧 SmartNudge
- β-4:     学习反馈循环 (aligned / missed / fatigue 衰减)

dry-run 默认开: env JARVIS_PROACTIVE_CARE_LIVE=1 才真发声 (Sir 24h 看数据再决定).
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

try:
    from jarvis_utils import bg_log
except Exception:  # pragma: no cover
    def bg_log(msg: str) -> None:
        print(msg)


# ============================================================
# Tunables (集中在顶部, 方便 Sir 调)
# ============================================================

TICK_INTERVAL_S = 60.0                  # daemon tick
WARMUP_SECONDS = 300                    # 启动 5 分钟 silent
DEFAULT_URGENCY_THRESHOLD = 0.55        # urgency ≥ 阈值才考虑发
NIGHT_CRITICAL_THRESHOLD = 0.85         # 凌晨 2-5 点仅 critical
HIGH_ACTIVITY_DAMPEN = 0.85             # Sir 高活跃 (≥10 turn 最近 1h) 降权
UNHEALTHY_KEY_DAMPEN = 0.75             # KeyRouter 不健康降权
SIGNAL_RECENCY_HALFLIFE_H = 24.0        # signal age 半衰
SILENCE_PRESSURE_FULL_H = 12.0          # 未提满 12h 算"该提了"
SIGNAL_DENSITY_FULL_COUNT = 5           # 24h 内信号数 5 个算"密集"
FATIGUE_PENALTY_PER_REJECT = 0.15       # 每次拒绝降 15%
FATIGUE_FLOOR = 0.2                     # 疲劳惩罚下限

# 防双发: 距上次任何 nudge (SmartNudge 或自身) 至少 X 秒
GLOBAL_NUDGE_COOLDOWN_S = 300.0
# 同一 concern 至少 X 秒不重复
PER_CONCERN_COOLDOWN_S = 1800.0
# Sir 显式拒绝 ("别催了") 后 X 秒静默
EXPLICIT_REJECT_COOLDOWN_S = 1800.0


# ============================================================
# 数据结构
# ============================================================

@dataclass
class CareSignal:
    """L4 ConcernsReflector / 主脑 / sensor 报来的"和某 concern 相关的最新观察"."""
    concern_id: str
    what: str                       # 观察文本
    severity_delta: float = 0.0
    when: float = field(default_factory=time.time)
    source: str = ''                # 'l4_reflector' / 'sensor' / 'self_promise' / ...


@dataclass
class CareEvidence:
    """选好的 top concern + 给主脑的素材包."""
    concern_id: str
    urgency_score: float
    what_i_watch: str
    why_i_care: str
    severity: float
    breakdown: dict                 # urgency 各因子明细 (debug)
    sir_recent_quote: str = ''      # STM 找到的 Sir 自己提过的话
    last_signal_what: str = ''      # concern.recent_signals[-1].what
    inside_joke_ref: str = ''       # L2 找到的可引用 joke phrase


# ============================================================
# CareSignalCollector — urgency 算法
# ============================================================

class CareSignalCollector:
    """每 tick 算所有 active concerns 的 urgency 分."""

    def __init__(self, ledger, anchor=None, nerve=None):
        self.ledger = ledger
        self.anchor = anchor
        self.nerve = nerve

    def compute_urgency(self, concern, now_ts: float,
                          fatigue_count: int = 0) -> Tuple[float, dict]:
        breakdown: dict = {}

        base = float(getattr(concern, 'severity', 0.3))
        breakdown['base_severity'] = round(base, 3)

        # 1. signal 新鲜度: 最近 signal 越新 → recency 越高
        last_sig_ts = 0.0
        recent_signals = getattr(concern, 'recent_signals', []) or []
        if recent_signals:
            last_sig_ts = max(s.get('when', 0) for s in recent_signals)
        if last_sig_ts > 0:
            age_h = max(0.0, (now_ts - last_sig_ts) / 3600.0)
            recency = math.exp(-age_h / SIGNAL_RECENCY_HALFLIFE_H)
        else:
            recency = 0.5  # 无 signal: 中性
        breakdown['recency'] = round(recency, 3)

        # 2. signal 密度: 24h 内 signal 数 / 5
        cutoff_24h = now_ts - 86400
        recent_24h = [s for s in recent_signals if s.get('when', 0) >= cutoff_24h]
        density = min(1.0, len(recent_24h) / max(1, SIGNAL_DENSITY_FULL_COUNT))
        breakdown['signal_density'] = round(density, 3)

        # 3. 沉默压力: last_triggered 至今越久 → pressure 越高
        last_triggered = float(getattr(concern, 'last_triggered', 0) or 0)
        if last_triggered > 0:
            silence_h = max(0.0, (now_ts - last_triggered) / 3600.0)
        else:
            silence_h = SILENCE_PRESSURE_FULL_H  # 从未触发: 满压
        pressure = min(1.0, silence_h / SILENCE_PRESSURE_FULL_H)
        breakdown['silence_pressure'] = round(pressure, 3)

        # 4. 疲劳惩罚
        fatigue_mul = max(FATIGUE_FLOOR, 1.0 - fatigue_count * FATIGUE_PENALTY_PER_REJECT)
        breakdown['fatigue_mul'] = round(fatigue_mul, 3)

        # 5. L0 anchor 状态修正
        l0_mul = 1.0
        if self.anchor is not None:
            try:
                turn_count = self.anchor.get_turn_count()
                # 最近 session 已经 ≥ 10 turn → Sir 高活跃, 少打扰
                if turn_count >= 10:
                    l0_mul *= HIGH_ACTIVITY_DAMPEN
                health = self.anchor._get_own_health()
                if health.get('dead_keys', 0) > 0:
                    l0_mul *= UNHEALTHY_KEY_DAMPEN
            except Exception:
                pass
        breakdown['l0_mul'] = round(l0_mul, 3)

        # 综合: base 是主导 (70%), recency/density/pressure 综合 modulator (30%)
        # 避免"无 signal 但 severity 高 + 长久未提"反而 urgency 极低的怪现象.
        signal_modulator = (recency + density + pressure) / 3.0
        urgency = base * (0.7 + 0.3 * signal_modulator) * fatigue_mul * l0_mul
        urgency = max(0.0, min(1.0, urgency))
        breakdown['urgency'] = round(urgency, 3)
        return urgency, breakdown

    def collect(self, now_ts: float, fatigue_map: dict) -> List[Tuple[object, float, dict]]:
        """返回 [(concern, urgency, breakdown), ...] 已按 urgency 降序."""
        out: List[Tuple[object, float, dict]] = []
        try:
            actives = self.ledger.list_active()
        except Exception as e:
            bg_log(f"⚠️ [CareSignalCollector] ledger.list_active fail: {e}")
            return out

        for c in actives:
            if not getattr(c, 'triggers_proactive', True):
                continue
            fatigue = int(fatigue_map.get(c.id, 0))
            urg, bd = self.compute_urgency(c, now_ts, fatigue)
            out.append((c, urg, bd))
        out.sort(key=lambda x: -x[1])
        return out


# ============================================================
# CareWindowGuard — 能否打扰
# ============================================================

class CareWindowGuard:
    """判定当下能不能发 nudge."""

    def __init__(self, worker, central_nerve=None):
        self.worker = worker
        self.nerve = central_nerve

    def can_speak(self, concern, urgency: float, now_ts: float,
                    last_any_nudge_ts: float,
                    explicit_reject_until: float) -> Tuple[bool, str]:
        # 1. warm-up
        # (上层处理)

        # 2. Sir 在 active conversation: 让位
        try:
            vt = getattr(self.worker, 'voice_thread', None)
            if vt is not None and getattr(vt, 'in_active_conversation', False):
                return False, 'active_conversation'
            # β.2.7.10 旁路对话期间也让位
            if vt is not None and getattr(vt, '_bypass_speech_count', 0) >= 2:
                return False, 'bypass_speech'
        except Exception:
            pass

        # 3. Jarvis 正在说话
        try:
            vt = getattr(self.worker, 'voice_thread', None)
            if vt is not None and getattr(vt, 'is_jarvis_speaking', False):
                return False, 'jarvis_speaking'
        except Exception:
            pass

        # 4. 显式 reject 冷却中
        if now_ts < explicit_reject_until:
            return False, f'explicit_reject_cooldown ({int(explicit_reject_until - now_ts)}s left)'

        # 5. 全局 nudge 冷却
        if now_ts - last_any_nudge_ts < GLOBAL_NUDGE_COOLDOWN_S:
            return False, f'global_nudge_cooldown ({int(GLOBAL_NUDGE_COOLDOWN_S - (now_ts - last_any_nudge_ts))}s left)'

        # 6. 同 concern 冷却
        last_trig = float(getattr(concern, 'last_triggered', 0) or 0)
        if last_trig > 0 and now_ts - last_trig < PER_CONCERN_COOLDOWN_S:
            return False, f'per_concern_cooldown ({int(PER_CONCERN_COOLDOWN_S - (now_ts - last_trig))}s left)'

        # 7. 时段判断
        hour = time.localtime(now_ts).tm_hour
        if 2 <= hour <= 5:
            if urgency < NIGHT_CRITICAL_THRESHOLD:
                return False, f'night_quiet (hour={hour}, urgency={urgency:.2f} < {NIGHT_CRITICAL_THRESHOLD})'

        # 8. Sir 在睡眠模式?
        try:
            gate = None
            if self.nerve is not None:
                gate = getattr(self.nerve, 'nudge_gate', None)
            if gate is not None and gate.is_sleep_mode():
                return False, 'sleep_mode'
        except Exception:
            pass

        return True, 'ok'


# ============================================================
# CareSubjectSelector — 选 top concern + 找素材
# ============================================================

class CareSubjectSelector:
    """选 top urgency concern + 从 L2/STM 找素材."""

    def __init__(self, ledger, l2_store=None, nerve=None):
        self.ledger = ledger
        self.l2_store = l2_store
        self.nerve = nerve

    def build_evidence(self, concern, urgency: float, breakdown: dict) -> CareEvidence:
        evi = CareEvidence(
            concern_id=concern.id,
            urgency_score=urgency,
            what_i_watch=getattr(concern, 'what_i_watch', '')[:200],
            why_i_care=getattr(concern, 'why_i_care', '')[:200],
            severity=float(getattr(concern, 'severity', 0.0)),
            breakdown=breakdown,
        )

        recent_signals = getattr(concern, 'recent_signals', []) or []
        if recent_signals:
            evi.last_signal_what = str(recent_signals[-1].get('what', ''))[:200]

        evi.sir_recent_quote = self._find_recent_sir_quote(concern) or ''
        evi.inside_joke_ref = self._find_inside_joke(concern) or ''
        return evi

    def _find_recent_sir_quote(self, concern, max_age_hours: float = 4.0) -> str:
        """从 STM 找 Sir 最近 X 小时内提过此 concern keyword 的话."""
        if self.nerve is None:
            return ''
        try:
            stm = getattr(self.nerve, 'short_term_memory', None) or []
        except Exception:
            return ''
        if not stm:
            return ''
        keywords = self._concern_keywords(concern)
        if not keywords:
            return ''
        cutoff_ts = time.time() - max_age_hours * 3600
        for entry in reversed(stm[-30:]):
            ts = entry.get('when', 0) or 0
            if ts and ts < cutoff_ts:
                continue
            user_txt = str(entry.get('user', '') or '')
            if not user_txt:
                continue
            ul = user_txt.lower()
            if any(k.lower() in ul for k in keywords):
                return user_txt[:160]
        return ''

    def _find_inside_joke(self, concern) -> str:
        if self.l2_store is None:
            return ''
        try:
            jokes = self.l2_store.list_inside_jokes()
        except Exception:
            return ''
        if not jokes:
            return ''
        keywords = self._concern_keywords(concern)
        if not keywords:
            return ''
        for joke in jokes:
            phrase_l = str(getattr(joke, 'phrase', '')).lower()
            ctx_l = str(getattr(joke, 'birth_context', '')).lower()
            if any(k.lower() in phrase_l or k.lower() in ctx_l for k in keywords):
                return str(joke.phrase)[:80]
        return ''

    _STOP_WORDS_KW = frozenset((
        'the', 'and', 'for', 'with', 'that', 'this', 'sir',
        'his', 'her', 'are', 'have', 'has', 'about',
        'jarvis', 'mine', 'our', 'their', 'they', 'them',
    ))

    def _concern_keywords(self, concern) -> List[str]:
        """从 concern id / what_i_watch 抽 keyword list."""
        kws: List[str] = []
        cid = str(getattr(concern, 'id', '') or '')
        if cid:
            parts = [p for p in cid.replace('-', '_').split('_')
                     if len(p) >= 3 and p.lower() not in self._STOP_WORDS_KW]
            kws.extend(parts)
        what = str(getattr(concern, 'what_i_watch', '') or '')
        for word in what.split():
            wl = word.strip(' ,.!?:;"\'')
            if 3 <= len(wl) <= 18 and wl.lower() not in self._STOP_WORDS_KW:
                kws.append(wl)
        seen, uniq = set(), []
        for k in kws:
            kl = k.lower()
            if kl in seen:
                continue
            seen.add(kl)
            uniq.append(k)
        return uniq[:12]


# ============================================================
# CareSpeechSynth — 构造 directive 走 stream_nudge
# ============================================================

class CareSpeechSynth:
    """从 evidence 构造 nudge_directive + push 到 worker."""

    def build_directive(self, evi: CareEvidence) -> str:
        sir_quote = evi.sir_recent_quote or '(no recent quote on this topic)'
        last_sig = evi.last_signal_what or '(no logged signal)'
        joke = evi.inside_joke_ref or '(none — only reference if joke fits naturally)'

        directive = (
            "You are making a brief proactive remark to Sir.\n"
            "This is NOT a scheduled reminder. This is YOU noticing something based on\n"
            "what you watch over for Sir — one of your long-term concerns has surfaced.\n\n"
            f"[CONCERN YOU'RE TOUCHING ON]\n"
            f"  id: {evi.concern_id}\n"
            f"  what you watch: {evi.what_i_watch}\n"
            f"  why you care:   {evi.why_i_care}\n"
            f"  severity:       {evi.severity:.2f}\n"
            f"  urgency now:    {evi.urgency_score:.2f}\n\n"
            f"[EVIDENCE FROM RECENT MEMORY]\n"
            f"  - Sir's recent words on this topic: \"{sir_quote}\"\n"
            f"  - Last signal you noticed:          \"{last_sig}\"\n"
            f"  - Inside joke you may reference (sparingly): \"{joke}\"\n\n"
            "[ANTI-HALLUCINATION]\n"
            "- Quote Sir's exact recent words above if relevant. NEVER invent specifics\n"
            "  (no fake dinner times, no fake activities he didn't actually mention).\n"
            "- If 'no recent quote on this topic', speak in general 'I notice you've been ...' form.\n"
            "- If 'no logged signal', speak from the watching itself, not specifics.\n\n"
            "[STYLE]\n"
            "- ONE sentence, ≤ 22 words English + ZH translation after ---ZH--- .\n"
            "- Dry butler tone, no chatter, no notification feel.\n"
            "- Reference YOUR watching ('I've been watching...' / 'I notice...'), not\n"
            "  Sir's behavior judgment ('you always...' / 'you should...').\n"
            "- If irony arises naturally, mild wit; else direct.\n"
        )
        return directive

    def push(self, worker, evi: CareEvidence, dry_run: bool) -> bool:
        directive = self.build_directive(evi)
        nudge_ctx = {
            'type': 'proactive_care',
            'channel': 'voice',
            'nudge_directive': directive,
            'concern_id': evi.concern_id,
            'urgency_score': round(evi.urgency_score, 3),
            'source': 'ProactiveCareEngine',
            'urgency_breakdown': evi.breakdown,
        }
        if dry_run:
            bg_log(
                f"🤝 [ProactiveCare/DRY] would nudge concern={evi.concern_id} "
                f"urgency={evi.urgency_score:.2f} quote='{evi.sir_recent_quote[:40]}' "
                f"joke='{evi.inside_joke_ref[:40]}'"
            )
            return False
        try:
            payload = "__NUDGE__:" + json.dumps(nudge_ctx, ensure_ascii=False)
            worker.push_command(payload)
            bg_log(
                f"🤝 [ProactiveCare/LIVE] pushed concern={evi.concern_id} "
                f"urgency={evi.urgency_score:.2f}"
            )
            return True
        except Exception as e:
            bg_log(f"⚠️ [ProactiveCare] push fail: {e}")
            return False


# ============================================================
# ProactiveCareEngine — daemon
# ============================================================

class ProactiveCareEngine(threading.Thread):
    """主动关心引擎 daemon. 与 SmartNudge 并行跑.

    阶段:
    - β-1 (本): dry-run 默认 (env JARVIS_PROACTIVE_CARE_LIVE=1 才发声), 不影响生产
    - β-3:     替换 SmartNudge

    线程安全: 共享 last_any_nudge_ts / explicit_reject_until / fatigue_map (有锁).
    """

    def __init__(self, worker, central_nerve=None,
                  tick_interval_s: float = TICK_INTERVAL_S,
                  threshold: float = DEFAULT_URGENCY_THRESHOLD):
        super().__init__(daemon=True, name='ProactiveCareEngine')
        self.worker = worker
        self.nerve = central_nerve
        self.tick = tick_interval_s
        self.threshold = threshold
        self._stop = threading.Event()
        self._state_lock = threading.Lock()

        self.last_any_nudge_ts: float = 0.0
        self.explicit_reject_until: float = 0.0
        self.fatigue_map: dict = {}      # concern_id → int rejection count

        # 关键依赖 lazy resolved (start 时再拿)
        self.ledger = None
        self.l2_store = None
        self.anchor = None
        self.collector: Optional[CareSignalCollector] = None
        self.guard: Optional[CareWindowGuard] = None
        self.selector: Optional[CareSubjectSelector] = None
        self.synth = CareSpeechSynth()

        self.dry_run: bool = os.environ.get('JARVIS_PROACTIVE_CARE_LIVE', '0') != '1'
        self.start_ts: float = time.time()
        self._tick_count = 0
        self._last_tick_log_at = 0.0

    # ---- API exposed to other modules ----

    def notify_sir_explicit_reject(self) -> None:
        """主脑 / Gatekeeper 发现 Sir 显式拒绝 ("别催了" / "knock it off") 调."""
        with self._state_lock:
            self.explicit_reject_until = time.time() + EXPLICIT_REJECT_COOLDOWN_S
        bg_log(
            f"🚫 [ProactiveCare] Sir 显式拒绝 → 静默 {int(EXPLICIT_REJECT_COOLDOWN_S/60)} min"
        )

    def notify_any_nudge_sent(self) -> None:
        """SmartNudge / Conductor / 自己发了 nudge 都来登记, 防双发."""
        with self._state_lock:
            self.last_any_nudge_ts = time.time()

    def notify_concern_rejected(self, concern_id: str) -> None:
        """Sir 拒绝某具体 concern (主脑/L5 判)."""
        with self._state_lock:
            self.fatigue_map[concern_id] = self.fatigue_map.get(concern_id, 0) + 1
        bg_log(
            f"🥱 [ProactiveCare] concern={concern_id} fatigue={self.fatigue_map[concern_id]}"
        )

    def notify_concern_aligned(self, concern_id: str) -> None:
        """Sir 响应 / L5 判 aligned → 衰减 fatigue."""
        with self._state_lock:
            cur = self.fatigue_map.get(concern_id, 0)
            if cur > 0:
                self.fatigue_map[concern_id] = max(0, cur - 1)

    def stop(self) -> None:
        self._stop.set()

    # ---- internal ----

    def _resolve_deps(self) -> bool:
        if self.ledger is None:
            try:
                from jarvis_concerns import get_default_ledger
                self.ledger = get_default_ledger()
            except Exception as e:
                bg_log(f"⚠️ [ProactiveCare] resolve ledger fail: {e}")
                return False
        if self.l2_store is None:
            try:
                from jarvis_relational import get_default_store
                self.l2_store = get_default_store()
            except Exception:
                self.l2_store = None  # 可选
        if self.anchor is None:
            try:
                from jarvis_self_anchor import get_default_self_anchor
                self.anchor = get_default_self_anchor(self.nerve)
            except Exception:
                self.anchor = None
        if self.collector is None:
            self.collector = CareSignalCollector(self.ledger, self.anchor, self.nerve)
        if self.guard is None:
            self.guard = CareWindowGuard(self.worker, self.nerve)
        if self.selector is None:
            self.selector = CareSubjectSelector(self.ledger, self.l2_store, self.nerve)
        return True

    def _tick(self) -> None:
        self._tick_count += 1
        now_ts = time.time()

        # 1. warm-up
        if now_ts - self.start_ts < WARMUP_SECONDS:
            return

        # 2. 算 urgency
        with self._state_lock:
            fatigue_snapshot = dict(self.fatigue_map)
        scored = self.collector.collect(now_ts, fatigue_snapshot)
        if not scored:
            return

        # 3. 周期 health log (每 30 tick = 30 min 一次)
        if now_ts - self._last_tick_log_at > 1800:
            top3 = scored[:3]
            top3_str = ", ".join([
                f"{getattr(c, 'id', '?')}={u:.2f}" for c, u, _ in top3
            ])
            bg_log(
                f"📊 [ProactiveCare/Health] tick={self._tick_count} "
                f"actives={len(scored)} top3=[{top3_str}] dry_run={self.dry_run}"
            )
            self._last_tick_log_at = now_ts

        # 4. top concern 是否过阈
        top_c, top_u, top_bd = scored[0]
        if top_u < self.threshold:
            return

        # 5. guard 判定
        with self._state_lock:
            last_any = self.last_any_nudge_ts
            reject_until = self.explicit_reject_until
        ok, reason = self.guard.can_speak(top_c, top_u, now_ts, last_any, reject_until)
        if not ok:
            bg_log(
                f"🛑 [ProactiveCare] skip concern={getattr(top_c, 'id', '?')} "
                f"urgency={top_u:.2f} reason={reason}"
            )
            return

        # 6. build evidence + push
        evi = self.selector.build_evidence(top_c, top_u, top_bd)
        sent = self.synth.push(self.worker, evi, dry_run=self.dry_run)
        if sent:
            with self._state_lock:
                self.last_any_nudge_ts = now_ts
            try:
                self.ledger.record_triggered(top_c.id)
            except Exception:
                pass

    def run(self) -> None:
        time.sleep(min(15, self.tick))
        bg_log(
            f"💡 [ProactiveCareEngine] started "
            f"(threshold={self.threshold}, tick={self.tick}s, "
            f"dry_run={self.dry_run}, warmup={WARMUP_SECONDS}s)"
        )
        while not self._stop.is_set():
            try:
                if self._resolve_deps():
                    self._tick()
            except Exception as e:
                bg_log(f"⚠️ [ProactiveCareEngine] tick err: {type(e).__name__}: {e}")
            self._stop.wait(self.tick)


# ============================================================
# Module singleton helper
# ============================================================

_DEFAULT_ENGINE: Optional[ProactiveCareEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_default_engine(worker=None, central_nerve=None) -> Optional[ProactiveCareEngine]:
    """单例 getter. 第一次调用时建好, 后续返回同一实例.
    worker / central_nerve 只在第一次时用."""
    global _DEFAULT_ENGINE
    with _ENGINE_LOCK:
        if _DEFAULT_ENGINE is None and worker is not None:
            _DEFAULT_ENGINE = ProactiveCareEngine(worker, central_nerve)
        return _DEFAULT_ENGINE


def reset_default_engine_for_test() -> None:
    global _DEFAULT_ENGINE
    with _ENGINE_LOCK:
        if _DEFAULT_ENGINE is not None:
            try:
                _DEFAULT_ENGINE.stop()
            except Exception:
                pass
        _DEFAULT_ENGINE = None
