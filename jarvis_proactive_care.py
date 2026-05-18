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

# Sir 总开关 (env JARVIS_PROACTIVE_CARE_LEVEL):
# - 'silent' (0): 完全不主动 (急救模式 / Sir 太忙)
# - 'low' (1):    高阈值 (0.7), 长冷却 (10min), 仅 critical 主动
# - 'normal' (2): 默认 (0.55 / 5min)
# - 'high' (3):   低阈值 (0.4), 短冷却 (3min), 更勤主动 (Sir 想多陪伴)
_LEVEL_PRESETS = {
    'silent': dict(threshold=2.0, global_cooldown=86400),    # 实质禁用
    'low':    dict(threshold=0.70, global_cooldown=600),
    'normal': dict(threshold=0.55, global_cooldown=300),
    'high':   dict(threshold=0.40, global_cooldown=180),
}
_DEFAULT_LEVEL = os.environ.get('JARVIS_PROACTIVE_CARE_LEVEL', 'normal').strip().lower()
_LEVEL_CONF = _LEVEL_PRESETS.get(_DEFAULT_LEVEL, _LEVEL_PRESETS['normal'])

TICK_INTERVAL_S = 60.0                  # daemon tick
WARMUP_SECONDS = 300                    # 启动 5 分钟 silent
DEFAULT_URGENCY_THRESHOLD = _LEVEL_CONF['threshold']
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
    # [β-2] L2 协议提示 — 让 LLM 避免违反 Sir 反过的话
    protocol_hints: List[str] = field(default_factory=list)
    # [β-2] L2 unfinished_business 关联 — 如果此 concern 和某 unfinished 关联
    related_unfinished: str = ''
    # [β-2] 当前活动上下文 — 让生成的话有 "right now" 实感
    current_activity: str = ''


# ============================================================
# CareConcernSensor — 从 sensor 派生 signal 喂给 concern (β-2.5)
# ============================================================

class CareConcernSensor:
    """从 PhysicalEnvironmentProbe / KeyRouter / Hippocampus 等 sensor 派生 signal
    自动喂给 ConcernsLedger. 让"主动关心"不依赖 Sir 主动开口才知道.

    rule: 每 tick 跑一次, 命中 → ledger.record_signal(cid, what, severity_delta).
    severity_delta 故意小 (0.02-0.05) 让长期累积而非单 tick 暴涨.
    """

    def __init__(self, ledger, nerve=None):
        self.ledger = ledger
        self.nerve = nerve
        # 防同一条信号重复刷 (e.g. coding>60min 持续 30min 不应每 tick 都喂)
        self._recent_signal_cooldown: dict = {}  # (cid, rule_id) → last_ts
        self._cooldown_sec = 1800.0              # 30min 内同 rule 不重复

    def _can_signal(self, cid: str, rule_id: str) -> bool:
        # 🩹 [β.2.9.6 audit] 顺带清理过期 entries 防内存泄漏
        if len(self._recent_signal_cooldown) > 500:
            cutoff = time.time() - self._cooldown_sec * 2
            self._recent_signal_cooldown = {
                k: ts for k, ts in self._recent_signal_cooldown.items()
                if ts > cutoff
            }
        key = (cid, rule_id)
        last = self._recent_signal_cooldown.get(key, 0)
        if time.time() - last < self._cooldown_sec:
            return False
        self._recent_signal_cooldown[key] = time.time()
        return True

    def tick(self) -> int:
        """跑所有 rule, 返回新 signal 数."""
        n = 0
        try:
            from jarvis_env_probe import PhysicalEnvironmentProbe as P
            snap = P.get_sensor_snapshot() or {}
        except Exception:
            snap = {}

        # rule 1: Sir 连续 coding/work > 60min 无 break → hydration + pomodoro
        try:
            sess_min = snap.get('session_duration_minutes', 0)
            cat = snap.get('work_category', '')
            if sess_min > 60 and cat in ('Coding', 'General', 'Media'):
                if self._signal('sir_hydration_habit', 'long_session',
                                  f"{cat} {sess_min:.0f}min without obvious break", 0.03):
                    n += 1
                if self._signal('sir_pomodoro_compliance', 'long_session',
                                  f"{cat} {sess_min:.0f}min — pomodoro overdue", 0.04):
                    n += 1
            # 90min 加重
            if sess_min > 90 and cat == 'Coding':
                if self._signal('sir_hydration_habit', 'very_long_session',
                                  f"Coding {sess_min:.0f}min, dehydration risk", 0.05):
                    n += 1
        except Exception:
            pass

        # rule 2: 凌晨 1-5 点 + 仍活跃 → sleep_streak
        try:
            hour = time.localtime().tm_hour
            idle_s = snap.get('idle_seconds', 999)
            if 1 <= hour <= 5 and idle_s < 60:
                if self._signal('sir_sleep_streak', 'late_night_active',
                                  f"active at {hour}:00 (idle={idle_s}s)", 0.06):
                    n += 1
        except Exception:
            pass

        # rule 3: Sir 高 backspace_ratio (frustration) → 不直接 nudge offer_help
        # 但喂 hydration / pomodoro signal (frustration 时更可能脱水/无休)
        try:
            br = snap.get('backspace_ratio', 0)
            if br > 0.18:
                if self._signal('sir_hydration_habit', 'frustration_observed',
                                  f"high backspace ratio {br:.0%} — possible long debug", 0.02):
                    n += 1
        except Exception:
            pass

        # rule 4: KeyRouter dead → jarvis_keyrouter_health
        try:
            if self.nerve is not None:
                kr = getattr(self.nerve, 'key_router', None)
                if kr is not None:
                    stats = kr.get_stats() if hasattr(kr, 'get_stats') else {}
                    ks = stats.get('key_status', {})
                    dead = sum(1 for info in ks.values() if not info.get('healthy', True))
                    if dead > 0:
                        if self._signal('jarvis_keyrouter_health', 'dead_keys',
                                          f"{dead} dead key(s) observed", 0.05):
                            n += 1
        except Exception:
            pass

        # rule 5: [β-3.2] error_visible → 不直接喂 offer_help (Sir 没要), 但派生 signal
        # 给 sir_pomodoro_compliance + sir_hydration (报错时容易死磕)
        try:
            if snap.get('error_visible'):
                if self._signal('sir_pomodoro_compliance', 'error_battle',
                                  "error on screen during long session — likely grinding", 0.02):
                    n += 1
        except Exception:
            pass

        # rule 6: [β-3.2] context_switch 频繁 → 散乱 → 也喂 hydration (散乱状态自我照顾差)
        try:
            sw5 = snap.get('switch_frequency_5min', 0)
            if sw5 >= 12:
                if self._signal('sir_hydration_habit', 'high_context_switching',
                                  f"high switching ({sw5}/5min) — scattered focus", 0.02):
                    n += 1
        except Exception:
            pass

        # rule 7: [β-3.2] AFK 长时段后回来 → 触发 hydration signal (Sir 离开通常没喝水)
        try:
            idle_s = snap.get('idle_seconds', 0)
            cat = snap.get('work_category', '')
            # idle 短但前面 AFK 长 — 通过 PhysicalEnvironmentProbe.is_first_active_today
            if snap.get('is_first_active_today'):
                if self._signal('sir_hydration_habit', 'first_active',
                                  "first active period today — hydration check", 0.04):
                    n += 1
        except Exception:
            pass

        # rule 8: [β-3.2] L2 unfinished_business 长期未碰 → 派生 signal 给关联 concern
        try:
            if self.nerve is not None:
                from jarvis_relational import get_default_store
                l2 = get_default_store()
                for ub in l2.list_unfinished()[:5]:
                    last_touched = float(getattr(ub, 'last_referenced', 0) or
                                           getattr(ub, 'created_at', 0))
                    if last_touched <= 0:
                        continue
                    age_days = (time.time() - last_touched) / 86400
                    if age_days < 14:
                        continue
                    # 找 concern 关联此 ub.topic
                    topic_l = str(getattr(ub, 'topic', '')).lower()
                    for c in self.ledger.list_active():
                        cid = c.id.lower()
                        # 简单 substring match
                        if any(w in topic_l for w in cid.split('_') if len(w) >= 4):
                            if self._signal(c.id, 'unfinished_stale',
                                              f"unfinished business '{topic_l[:50]}' "
                                              f"untouched for {age_days:.0f}d", 0.03):
                                n += 1
                            break  # 一个 ub 喂一个 concern 就够
        except Exception:
            pass

        return n

    def _signal(self, concern_id: str, rule_id: str,
                  what: str, severity_delta: float) -> bool:
        if not self._can_signal(concern_id, rule_id):
            return False
        try:
            ok = bool(self.ledger.record_signal(concern_id, what, severity_delta))
        except Exception:
            return False
        # [β-3.2] event_bus publish 让 L4 reflector / WeeklyReflector 看到
        # 周末时 L4 看 sensor 派生频次, 自动调 severity 上下限
        if ok and self.nerve is not None:
            try:
                bus = getattr(self.nerve, 'event_bus', None)
                if bus is not None:
                    bus.publish(
                        etype='care_signal_derived',
                        description=f"{concern_id}: {what[:100]}",
                        source='ProactiveCareSensor',
                        metadata={
                            'concern_id': concern_id,
                            'rule_id': rule_id,
                            'severity_delta': severity_delta,
                        },
                    )
            except Exception:
                pass
        return ok


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

        # 9. [β-2 强化] Sir 深度工作中 → 只有高 urgency 才打扰
        try:
            if self._is_deep_work() and urgency < 0.75:
                return False, f'deep_work_focus (urgency={urgency:.2f} < 0.75 needed)'
        except Exception:
            pass

        return True, 'ok'

    def _is_deep_work(self) -> bool:
        """启发式判定 Sir 是否在深度工作.

        命中任意 2 条即视为 deep_work:
        - switch_frequency_5min < 3 (窗口切换少)
        - window_stay_seconds > 600 (10min 没换窗)
        - key_press_count_5min > 100 (高强度敲键)
        - work_category == Coding 且 session_duration > 25min
        """
        try:
            from jarvis_env_probe import PhysicalEnvironmentProbe as P
            snap = P.get_sensor_snapshot() or {}
        except Exception:
            return False
        if not snap:
            return False
        hits = 0
        if snap.get('switch_frequency_5min', 99) < 3:
            hits += 1
        if snap.get('window_stay_seconds', 0) > 600:
            hits += 1
        if snap.get('key_press_count_5min', 0) > 100:
            hits += 1
        if snap.get('work_category') == 'Coding' and \
                snap.get('session_duration_minutes', 0) > 25:
            hits += 1
        return hits >= 2


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
        evi.protocol_hints = self._find_relevant_protocols(concern)
        evi.related_unfinished = self._find_related_unfinished(concern) or ''
        evi.current_activity = self._snapshot_current_activity()
        return evi

    def _find_relevant_protocols(self, concern, max_n: int = 2) -> List[str]:
        """L2 unspoken_protocols: 找和此 concern 相关 + Jarvis 违规过的 protocol.
        让 LLM 谨慎不要重蹈覆辙."""
        if self.l2_store is None:
            return []
        try:
            protocols = self.l2_store.list_protocols()
        except Exception:
            return []
        if not protocols:
            return []
        kws = self._concern_keywords(concern)
        out = []
        for p in protocols:
            rule_l = str(getattr(p, 'rule', '')).lower()
            if not rule_l:
                continue
            relevant = any(k.lower() in rule_l for k in kws)
            has_violation = bool(getattr(p, 'violations', []) or [])
            if relevant or has_violation:
                out.append(str(p.rule)[:120])
            if len(out) >= max_n:
                break
        return out

    def _find_related_unfinished(self, concern) -> str:
        """L2 unfinished_business: 看是否有 unfinished 和此 concern 关联."""
        if self.l2_store is None:
            return ''
        try:
            ubs = self.l2_store.list_unfinished()
        except Exception:
            return ''
        if not ubs:
            return ''
        kws = self._concern_keywords(concern)
        for ub in ubs:
            topic_l = str(getattr(ub, 'topic', '')).lower()
            if any(k.lower() in topic_l for k in kws):
                return str(getattr(ub, 'topic', ''))[:100]
        return ''

    def _snapshot_current_activity(self) -> str:
        """从 PhysicalEnvironmentProbe 拿当下 1 行活动描述."""
        try:
            from jarvis_env_probe import PhysicalEnvironmentProbe as P
            cat = getattr(P, 'current_work_category', 'Unknown')
            dur = getattr(P, 'work_duration_minutes', 0)
            title = getattr(P, 'current_window_title', '') or ''
            if title:
                return f"{cat} for {dur:.0f}min: '{title[:60]}'"
            return f"{cat} for {dur:.0f}min"
        except Exception:
            return ''

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
        unfinished = evi.related_unfinished or '(no related unfinished business)'
        activity = evi.current_activity or '(activity unknown)'

        protocols_str = ''
        if evi.protocol_hints:
            lines = '\n'.join(f"  - {p}" for p in evi.protocol_hints)
            protocols_str = (
                "\n[OUR PROTOCOLS — respect these or Sir will push back]\n"
                f"{lines}\n"
            )

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
            f"  - Related unfinished business:      \"{unfinished}\"\n"
            f"  - Inside joke you may reference (sparingly): \"{joke}\"\n\n"
            f"[CURRENT ACTIVITY]\n  {activity}\n"
            f"{protocols_str}\n"
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
            "- If [CURRENT ACTIVITY] is concrete (e.g. 'Coding for 45min: cursor.exe'),\n"
            "  weave that into the remark to give it 'right now' feel.\n"
        )
        return directive

    def choose_channel(self, evi: CareEvidence,
                         silent_done_recently: bool) -> str:
        """β-3.1 动态 channel 选择: 不每次都吵.

        - 极高 urgency (>= 0.85): voice
        - 中高 urgency 第一次 (0.55-0.85, 没 silent 过): silent_text (字幕飘过)
        - 中高 urgency 已经 silent 过: voice (升级)
        """
        if evi.urgency_score >= 0.85:
            return 'voice'
        if silent_done_recently:
            return 'voice'
        return 'silent_text'

    def render_silent_text(self, evi: CareEvidence) -> str:
        """silent_text 档不调 LLM, 直接构 1 行中性话."""
        cid_human = evi.concern_id.replace('_', ' ').replace('sir ', 'Sir ').strip()
        sig = evi.last_signal_what or evi.what_i_watch
        return f"[I'm watching: {cid_human}] {sig[:80]}"

    def push(self, worker, evi: CareEvidence, dry_run: bool,
              channel: str = 'voice') -> bool:
        directive = self.build_directive(evi)
        nudge_ctx = {
            'type': 'proactive_care',
            'channel': channel,
            'nudge_directive': directive,
            'concern_id': evi.concern_id,
            'urgency_score': round(evi.urgency_score, 3),
            'source': 'ProactiveCareEngine',
            'urgency_breakdown': evi.breakdown,
        }
        if channel == 'silent_text':
            nudge_ctx['silent_text'] = self.render_silent_text(evi)
        if dry_run:
            # 🩹 [β.2.8.5 hotfix / 2026-05-17] Sir 22:30 反馈: dry-run 每 60s 重复刷
            # same concern same urgency 看着像系统坏了. 加 (cid, urgency_bucket) 30min 节流.
            if not hasattr(self, '_dry_log_throttle'):
                self._dry_log_throttle = {}
            urgency_bucket = int(evi.urgency_score * 10) / 10.0  # 0.1 粒度
            key = (evi.concern_id, urgency_bucket, channel)
            now_ts = time.time()
            last_log = self._dry_log_throttle.get(key, 0)
            if now_ts - last_log < 1800.0:  # 30min 内同 key 不重复 log
                return False
            self._dry_log_throttle[key] = now_ts
            bg_log(
                f"🤝 [ProactiveCare/DRY] would nudge concern={evi.concern_id} "
                f"urgency={evi.urgency_score:.2f} channel={channel} "
                f"quote='{evi.sir_recent_quote[:40]}' joke='{evi.inside_joke_ref[:40]}' "
                f"(node throttled 30min for same urgency bucket)"
            )
            return False
        try:
            payload = "__NUDGE__:" + json.dumps(nudge_ctx, ensure_ascii=False)
            worker.push_command(payload)
            bg_log(
                f"🤝 [ProactiveCare/LIVE] pushed concern={evi.concern_id} "
                f"urgency={evi.urgency_score:.2f} channel={channel}"
            )
            # 🩹 [β.2.8.5] 主动关心也算"言出必行"的兑现 -
            # 我 (Jarvis) 之前可能承诺"I'll keep an eye on hydration",
            # 这次主动 nudge 就是兑现. 配对 evidence.
            try:
                from jarvis_promise_log import try_pair_evidence
                try_pair_evidence(
                    evidence_kind='proactive_care_nudge',
                    evidence_what=f"actively raised concern {evi.concern_id}: {evi.what_i_watch[:80]}",
                )
            except Exception:
                pass
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
        # [β-3.1] concern_id → 上次 silent_text 推送时间. 用于决定下次升级 voice
        self.silent_history: dict = {}
        self.silent_decay_s: float = 3600.0  # 1h 内 silent 算"试探过", 该升级

        # 关键依赖 lazy resolved (start 时再拿)
        self.ledger = None
        self.l2_store = None
        self.anchor = None
        self.collector: Optional[CareSignalCollector] = None
        self.guard: Optional[CareWindowGuard] = None
        self.selector: Optional[CareSubjectSelector] = None
        self.sensor: Optional[CareConcernSensor] = None
        self.synth = CareSpeechSynth()

        # 🩹 [β.2.9.7 / 2026-05-18] dry_run 默认从 ON 改为 OFF (LIVE 默认):
        # β.2.8 阶段已并行跑 dry_run ≥ 1d 验证 urgency 算法稳定 + cooldown 不刷屏
        # + 准则 6 主体判定 + InconsistencyWatcher 三道防御 (β.2.9.7) 都到位.
        # Sir 可通过 JARVIS_PROACTIVE_CARE_DRY_RUN=1 临时 opt-in dry 模式调试.
        # 向后兼容: 旧 env JARVIS_PROACTIVE_CARE_LIVE=1 也强制 LIVE (Sir .env 可能设过).
        _live_env = os.environ.get('JARVIS_PROACTIVE_CARE_LIVE', '').strip()
        _dry_env = os.environ.get('JARVIS_PROACTIVE_CARE_DRY_RUN', '').strip()
        if _dry_env == '1':
            self.dry_run = True
        elif _live_env == '1':
            self.dry_run = False
        else:
            # 默认: LIVE (β.2.9.7 切换)
            self.dry_run = False
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
        if self.sensor is None:
            self.sensor = CareConcernSensor(self.ledger, self.nerve)
        return True

    def _tick(self) -> None:
        self._tick_count += 1
        now_ts = time.time()

        # 1. warm-up
        if now_ts - self.start_ts < WARMUP_SECONDS:
            return

        # 1.5. [β-2.5] 跑 sensor → 让 sensor 派生 signal 喂给 concern
        # 不依赖 Sir 主动开口才知道关心啥
        try:
            n_signals = self.sensor.tick()
            if n_signals > 0:
                bg_log(f"📡 [ProactiveCare/Sensor] tick fed {n_signals} signal(s)")
        except Exception as _sens_e:
            bg_log(f"⚠️ [ProactiveCare/Sensor] tick err: {_sens_e}")

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

        # 6. build evidence + 选 channel + push
        evi = self.selector.build_evidence(top_c, top_u, top_bd)
        # β-3.1 channel 升级: 先 silent 试探, 再 voice 升级
        with self._state_lock:
            last_silent_ts = self.silent_history.get(top_c.id, 0)
        silent_recent = (now_ts - last_silent_ts) < self.silent_decay_s
        channel = self.synth.choose_channel(evi, silent_recent)
        sent = self.synth.push(self.worker, evi, dry_run=self.dry_run, channel=channel)
        if sent:
            with self._state_lock:
                # voice 算"全局 nudge", silent_text 不占全局 cooldown 但占 per_concern
                if channel == 'voice':
                    self.last_any_nudge_ts = now_ts
                else:
                    self.silent_history[top_c.id] = now_ts
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
