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


# 🩹 [β.5.39 / 2026-05-20] Sir sleep pattern vocab (准则 6 mtime cache)
_SIR_SLEEP_PATTERN_PATH = os.path.join('memory_pool', 'sir_sleep_pattern_vocab.json')
_SIR_SLEEP_PATTERN_CACHE: dict = {}
_SIR_SLEEP_PATTERN_MTIME: float = 0.0


def _compute_concern_timing_evidence(concern, now_ts: float):
    """🩹 [β.5.40-fix / 2026-05-20 16:30] Sir 真理: 不硬 dampen, 让主脑看 evidence 自决.
    
    For concern with optimal_timing, compute timing evidence dict (None if no optimal_timing).
    主脑 directive `concern_timing_judge` 看此 evidence 决定是否该提 (远离 timing 别提).
    
    Returns dict 含:
      - optimal_timing: 'before_sleep' / 'morning' / 'evening' / 'now'
      - current_hour: 0-23
      - is_in_optimal_window: bool
      - hours_until_optimal: int (负=已过, 0=在窗口, 正=离窗口还有多久)
    """
    tm = getattr(concern, 'optimal_timing', '') or ''
    if not tm:
        return None
    hour = time.localtime(now_ts).tm_hour
    ev = {'optimal_timing': tm, 'current_hour': hour}
    if tm == 'before_sleep':
        # 22-1 (含)
        ev['is_in_optimal_window'] = (hour >= 22 or hour <= 1)
        if hour >= 22:
            ev['hours_until_optimal'] = 0
        elif hour <= 1:
            ev['hours_until_optimal'] = 0
        else:
            ev['hours_until_optimal'] = 22 - hour
    elif tm == 'morning':
        ev['is_in_optimal_window'] = (6 <= hour <= 10)
        if hour < 6:
            ev['hours_until_optimal'] = 6 - hour
        elif hour > 10:
            ev['hours_until_optimal'] = 24 - hour + 6
        else:
            ev['hours_until_optimal'] = 0
    elif tm == 'evening':
        ev['is_in_optimal_window'] = (18 <= hour <= 21)
        if hour < 18:
            ev['hours_until_optimal'] = 18 - hour
        elif hour > 21:
            ev['hours_until_optimal'] = 24 - hour + 18
        else:
            ev['hours_until_optimal'] = 0
    elif tm == 'now':
        ev['is_in_optimal_window'] = True
        ev['hours_until_optimal'] = 0
    else:
        return None
    return ev


def _load_sir_sleep_pattern() -> dict:
    """读 memory_pool/sir_sleep_pattern_vocab.json typical_sleep_hour 段.
    返 {'weekday': float|None, 'weekend': float|None, 'tolerance_hours': float}.
    失败 fallback 全 None (caller 走老硬规则).
    """
    global _SIR_SLEEP_PATTERN_CACHE, _SIR_SLEEP_PATTERN_MTIME
    try:
        mt = os.path.getmtime(_SIR_SLEEP_PATTERN_PATH)
        if mt == _SIR_SLEEP_PATTERN_MTIME and _SIR_SLEEP_PATTERN_CACHE:
            return _SIR_SLEEP_PATTERN_CACHE
        with open(_SIR_SLEEP_PATTERN_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        typ = data.get('typical_sleep_hour', {}) or {}
        result = {
            'weekday': typ.get('weekday'),
            'weekend': typ.get('weekend'),
            'tolerance_hours': typ.get('tolerance_hours', 1.0),
        }
        _SIR_SLEEP_PATTERN_CACHE = result
        _SIR_SLEEP_PATTERN_MTIME = mt
        return result
    except Exception:
        return {'weekday': None, 'weekend': None, 'tolerance_hours': 1.0}


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

TICK_INTERVAL_S = 60.0                  # daemon tick — 系统级常量, 不 vocab 化

# 🩹 [β.5.23-A / 2026-05-19] cooldown / threshold 阈值 vocab 化 (Sir 准则 6).
# 老硬编码 .py 常量留作 fallback. source of truth = memory_pool/proactive_care_cooldown_vocab.json
# 由 ConcernFeedbackReflector L7 LLM-propose 自动调节, Sir 不用手动改.
HIGH_ACTIVITY_DAMPEN = 0.85             # Sir 高活跃降权 — 系统级 dampen, 不 vocab
UNHEALTHY_KEY_DAMPEN = 0.75             # KeyRouter 不健康降权 — 系统级 dampen, 不 vocab
SIGNAL_DENSITY_FULL_COUNT = 5           # 24h 内信号数 5 个算"密集" — 系统级 algo 参数

# vocab 化 fallback (json 不可用时用): 这些都是上一稳定版本数字
_FALLBACK_WARMUP_SECONDS = 300
_FALLBACK_NIGHT_CRITICAL_THRESHOLD = 0.85
_FALLBACK_SIGNAL_RECENCY_HALFLIFE_H = 24.0
_FALLBACK_SILENCE_PRESSURE_FULL_H = 12.0
_FALLBACK_FATIGUE_PENALTY_PER_REJECT = 0.15
_FALLBACK_FATIGUE_FLOOR = 0.2
_FALLBACK_GLOBAL_NUDGE_COOLDOWN_S = 300.0
_FALLBACK_SILENT_GLOBAL_COOLDOWN_S = 90.0
_FALLBACK_PER_CONCERN_COOLDOWN_S = 1800.0
_FALLBACK_EXPLICIT_REJECT_COOLDOWN_S = 1800.0

# vocab cache (module-level, mtime cache)
_COOLDOWN_VOCAB_CACHE: dict = {}
_COOLDOWN_VOCAB_MTIME: float = 0.0
_COOLDOWN_VOCAB_PATH = os.path.join('memory_pool', 'proactive_care_cooldown_vocab.json')


def _load_cooldown_vocab() -> dict:
    """🩹 [β.5.23-A] 读 proactive_care_cooldown_vocab.json with mtime cache.
    返 'current' dict (key → 阈值 float). 失败 → 用 fallback dict.
    """
    global _COOLDOWN_VOCAB_CACHE, _COOLDOWN_VOCAB_MTIME
    try:
        mt = os.path.getmtime(_COOLDOWN_VOCAB_PATH)
        if mt == _COOLDOWN_VOCAB_MTIME and _COOLDOWN_VOCAB_CACHE:
            return _COOLDOWN_VOCAB_CACHE
        import json as _j
        with open(_COOLDOWN_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = _j.load(f)
        cur = dict(data.get('current') or {})
        _COOLDOWN_VOCAB_CACHE = cur
        _COOLDOWN_VOCAB_MTIME = mt
        return cur
    except Exception:
        return {}


def _get_cd(key: str, fallback: float) -> float:
    """统一访问 vocab cooldown 阈值. key 缺失 / json 不可用 → fallback."""
    try:
        v = _load_cooldown_vocab().get(key)
        if v is not None:
            return float(v)
    except Exception:
        pass
    return float(fallback)


# 公共访问: 直接代理到 vocab. 老代码 GLOBAL_NUDGE_COOLDOWN_S 全部改成 _get_cd(...)
# 但为兼容 module-level 引用 (e.g. 其他文件 from jarvis_proactive_care import GLOBAL_NUDGE_COOLDOWN_S),
# 仍 expose 初始读出的值 (启动时一次性). 之后改值由 _get_cd 即时读 vocab.
WARMUP_SECONDS = int(_get_cd('WARMUP_SECONDS', _FALLBACK_WARMUP_SECONDS))
DEFAULT_URGENCY_THRESHOLD = float(_get_cd('DEFAULT_URGENCY_THRESHOLD', _LEVEL_CONF['threshold']))
NIGHT_CRITICAL_THRESHOLD = float(_get_cd('NIGHT_CRITICAL_THRESHOLD', _FALLBACK_NIGHT_CRITICAL_THRESHOLD))
SIGNAL_RECENCY_HALFLIFE_H = float(_get_cd('SIGNAL_RECENCY_HALFLIFE_H', _FALLBACK_SIGNAL_RECENCY_HALFLIFE_H))
SILENCE_PRESSURE_FULL_H = float(_get_cd('SILENCE_PRESSURE_FULL_H', _FALLBACK_SILENCE_PRESSURE_FULL_H))
FATIGUE_PENALTY_PER_REJECT = float(_get_cd('FATIGUE_PENALTY_PER_REJECT', _FALLBACK_FATIGUE_PENALTY_PER_REJECT))
FATIGUE_FLOOR = float(_get_cd('FATIGUE_FLOOR', _FALLBACK_FATIGUE_FLOOR))
GLOBAL_NUDGE_COOLDOWN_S = float(_get_cd('GLOBAL_NUDGE_COOLDOWN_S', _FALLBACK_GLOBAL_NUDGE_COOLDOWN_S))
SILENT_GLOBAL_COOLDOWN_S = float(_get_cd('SILENT_GLOBAL_COOLDOWN_S', _FALLBACK_SILENT_GLOBAL_COOLDOWN_S))
PER_CONCERN_COOLDOWN_S = float(_get_cd('PER_CONCERN_COOLDOWN_S', _FALLBACK_PER_CONCERN_COOLDOWN_S))
EXPLICIT_REJECT_COOLDOWN_S = float(_get_cd('EXPLICIT_REJECT_COOLDOWN_S', _FALLBACK_EXPLICIT_REJECT_COOLDOWN_S))


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
        # 🩹 [β.5.39 / 2026-05-20] Sir 15:18 真理: 不要硬编码 22:00 / 凌晨 1-5,
        # 看 sir_sleep_pattern_vocab 中 typical_sleep_hour, distance-based 自适应 urgency.
        # 仍保留老规则做 fallback (vocab 未填充时, 凌晨硬规则触低 severity)
        try:
            hour = time.localtime().tm_hour
            idle_s = snap.get('idle_seconds', 999)
            # 优先: vocab evidence-based 公式
            typical = _load_sir_sleep_pattern()
            now_local = time.localtime()
            is_weekday = now_local.tm_wday < 5
            typ_hour = typical.get('weekday') if is_weekday else typical.get('weekend')
            if typ_hour is not None and idle_s < 60:
                # 跨午夜: 当前 hour < 6 → +24 算前一晚延续
                current_h = hour + 24 if hour < 6 else hour
                distance = current_h - typ_hour  # 负 = 早于平时, 正 = 晚于平时
                if distance > 2:
                    severity = 0.0  # 远早, 不催
                elif distance > 1:
                    severity = 0.03  # 轻关心
                elif distance > 0:
                    severity = 0.06  # 适度
                elif distance > -1:
                    severity = 0.10  # 接近 (前 1h)
                else:
                    severity = 0.04  # 还很早 (距 typical > 1h, 不催)
                if severity > 0:
                    if self._signal('sir_sleep_streak', 'late_night_active',
                                      f"hour={hour}, typical={typ_hour}h, distance={distance:+.1f}h ({'weekday' if is_weekday else 'weekend'})",
                                      severity):
                        n += 1
                        # publish SWM signal (sir_sleep_pattern_distance) 让主脑看
                        try:
                            from jarvis_utils import get_event_bus as _geb
                            _bus = _geb()
                            if _bus is not None:
                                _bus.publish(
                                    etype='sir_sleep_pattern',
                                    description=f"current={hour}h typical={typ_hour}h dist={distance:+.1f}h ({'weekday' if is_weekday else 'weekend'})",
                                    source='ProactiveCare',
                                    salience=min(0.4 + abs(distance) * 0.1, 0.9),
                                    metadata={
                                        'kind': 'sleep_distance',
                                        'current_hour': hour,
                                        'typical_hour': typ_hour,
                                        'distance_h': round(distance, 2),
                                        'is_weekday': is_weekday,
                                        'urgency_severity': severity,
                                    },
                                )
                        except Exception:
                            pass
            # fallback: 老硬规则 (vocab 未填充时)
            elif typ_hour is None and 1 <= hour <= 5 and idle_s < 60:
                if self._signal('sir_sleep_streak', 'late_night_active',
                                  f"active at {hour}:00 (idle={idle_s}s) [vocab unfilled fallback]", 0.06):
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

        # 🩹 [β.5.40-A2 / 2026-05-20] Sir 方向 A.2 — physio_state publish.
        # 用 PhysicalEnvironmentProbe snap 已有 key/mouse fields 算 energy/focus/stress
        # publish 'physio_state' SWM 让主脑看 (stress 高时 tone 关切, focus 高时静默)
        # cooldown 60s 内不重复. 数据少 confidence < 0.1 不 publish.
        try:
            from jarvis_physio_proxy import get_physio_proxy
            if self.nerve is not None:
                bus = getattr(self.nerve, 'event_bus', None)
                if bus is not None:
                    pp = get_physio_proxy(event_bus=bus)
                    pp.compute_and_publish(snap)
        except Exception:
            pass

        # 🩹 [β.5.40-E1 / 2026-05-20] Sir 方向 E.1 — nudge_window_advice publish.
        # 每 tick 读 nudge_window_vocab.json 当前 hour 的 receptive score,
        # publish 'nudge_window_advice' 到 SWM 让主脑看. score < 0.3 时主脑应更克制.
        try:
            from jarvis_companion_rhythm_reflector import get_current_hour_receptive_score
            score = get_current_hour_receptive_score()
            if score is not None and self.nerve is not None:
                bus = getattr(self.nerve, 'event_bus', None)
                if bus is not None:
                    now_local = time.localtime()
                    is_weekday = now_local.tm_wday < 5
                    bus.publish(
                        etype='nudge_window_advice',
                        description=(
                            f"hour={now_local.tm_hour}h receptive_score={score:.2f} "
                            f"({'weekday' if is_weekday else 'weekend'})"
                        ),
                        source='CompanionRhythm',
                        salience=0.55 if score < 0.3 else 0.35,
                        metadata={
                            'kind': 'nudge_receptive_window',
                            'hour': now_local.tm_hour,
                            'is_weekday': is_weekday,
                            'receptive_score': round(score, 3),
                            'advice': (
                                'low_receptive_consider_silent' if score < 0.3
                                else 'normal_receptive' if score < 0.7
                                else 'high_receptive_engage_natural'
                            ),
                        },
                        ttl=3600.0,
                    )
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

        # 🩹 [β.5.22-C / 2026-05-19] 动态语义反馈纳入 urgency (准则 6 核心).
        # Sir 01:34 痛点: "我说喝了 6/7 杯水了" 后, hydration concern 当天应削权
        # 但睡前可反弹提醒最后一杯. 由 ConcernFeedbackJudge LLM 写 daily_progress 进来.
        # 1. progress_mul: 已完成比例越高 → urgency 越削
        # 2. timing_mul: optimal_timing 命中当下 → urgency 反弹 (但不超 1.0)
        progress_mul = 1.0
        timing_mul = 1.0
        try:
            dp = getattr(concern, 'daily_progress', {}) or {}
            today_iso = time.strftime('%Y-%m-%d', time.localtime(now_ts))
            # 仅当 daily_progress 是今天的才计入
            if dp.get('iso_date') == today_iso:
                cur = float(dp.get('current', 0) or 0)
                tgt = float(dp.get('target', 0) or 0)
                if tgt > 0 and cur > 0:
                    ratio = min(1.0, cur / tgt)
                    # 进度 100% → mul = 0.3 (削 70%), 进度 75% → mul = 0.475, 进度 50% → mul = 0.65
                    progress_mul = max(0.3, 1.0 - ratio * 0.7)
        except Exception:
            pass
        try:
            tm = (getattr(concern, 'optimal_timing', '') or '').lower()
            hour = time.localtime(now_ts).tm_hour
            # 简单 timing 命中规则 — LLM 之后可扩
            timing_hit = False
            if tm == 'before_sleep' and (hour >= 22 or hour <= 1):
                timing_hit = True
            elif tm == 'morning' and 6 <= hour <= 10:
                timing_hit = True
            elif tm == 'evening' and 18 <= hour <= 21:
                timing_hit = True
            elif tm == 'now':
                timing_hit = True
            if timing_hit:
                timing_mul = 1.5
        except Exception:
            pass
        breakdown['progress_mul'] = round(progress_mul, 3)
        breakdown['timing_mul'] = round(timing_mul, 3)

        urgency = urgency * progress_mul * timing_mul
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

        # 5. 全局 nudge 冷却 (β.5.23-A: 动态读 vocab)
        _gnc = _get_cd('GLOBAL_NUDGE_COOLDOWN_S', GLOBAL_NUDGE_COOLDOWN_S)
        if now_ts - last_any_nudge_ts < _gnc:
            return False, f'global_nudge_cooldown ({int(_gnc - (now_ts - last_any_nudge_ts))}s left)'

        # 6. 同 concern 冷却 (β.5.23-A: 动态读 vocab)
        last_trig = float(getattr(concern, 'last_triggered', 0) or 0)
        _pcc = _get_cd('PER_CONCERN_COOLDOWN_S', PER_CONCERN_COOLDOWN_S)
        if last_trig > 0 and now_ts - last_trig < _pcc:
            return False, f'per_concern_cooldown ({int(_pcc - (now_ts - last_trig))}s left)'

        # 7. 时段判断 (β.5.23-A: 动态读 vocab)
        _nct = _get_cd('NIGHT_CRITICAL_THRESHOLD', NIGHT_CRITICAL_THRESHOLD)
        hour = time.localtime(now_ts).tm_hour
        if 2 <= hour <= 5:
            if urgency < _nct:
                return False, f'night_quiet (hour={hour}, urgency={urgency:.2f} < {_nct})'

        # 8. Sir 在睡眠模式?
        try:
            gate = None
            if self.nerve is not None:
                gate = getattr(self.nerve, 'nudge_gate', None)
            if gate is not None and gate.is_sleep_mode():
                return False, 'sleep_mode'
        except Exception:
            pass

        # 🩹 [β.5.22-B / 2026-05-19] Sir 01:22 实测痛点: Sir 说"我去睡觉了" 后 10min
        # 仍被催 hydration. Root cause: ProactiveCare 不读 worker._sleep_intent_until
        # 软窗口 (Conductor / SmartNudge 都有这个 check, ProactiveCare 漏了). 修法:
        # sleep_intent 窗口内 (Sir 表态 X 分钟后睡) 全 silence ALL care nudge, 不只
        # late_night/suggest_break/bedtime. Sir 已在收尾, hydration 这种 nudge 也不该插.
        try:
            spi = float(getattr(self.worker, '_sleep_intent_until', 0.0) or 0.0)
            if spi > 0 and now_ts < spi:
                return False, f'sleep_intent_window ({int(spi - now_ts)}s left)'
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

        🩹 [β.5.13 / 2026-05-19] env JARVIS_NUDGE_LLM_ALL_CHANNELS=1 (默认) → 全走 voice
        意图: silent_text / visual_pulse 跳过主脑是 β.5 重构未覆盖的边界. 改后所有
        channel 都让主脑 stream_nudge 看 SWM 自己决策 (silent / voice / silent_text).
        env=0 走老逻辑 (实机出问题秒回, 不用 git revert).
        原 channel 提示通过 nudge_context['original_channel_hint'] 传给 stream_nudge,
        主脑可参考但能改 (例如 silent hint + 高 urgency 仍升级 voice).

        - env=1 (默认): 始终返 'voice' → 主脑接管
        - env=0 (旧):
          - 极高 urgency (>= 0.85): voice
          - 中高 urgency 第一次 (0.55-0.85, 没 silent 过): silent_text (字幕飘过)
          - 中高 urgency 已经 silent 过: voice (升级)
        """
        _llm_all = os.environ.get('JARVIS_NUDGE_LLM_ALL_CHANNELS', '1').strip()
        if _llm_all != '0':
            return 'voice'
        if evi.urgency_score >= 0.85:
            return 'voice'
        if silent_done_recently:
            return 'voice'
        return 'silent_text'

    def _legacy_channel_for_hint(self, evi: CareEvidence,
                                  silent_done_recently: bool) -> str:
        """β.5.13: 算"原来 channel 决策会走什么 channel", 给主脑作为 hint.
        若 env=1 走主脑路径, 仍想让主脑知道老规则会选 silent 还是 voice.
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
              channel: str = 'voice',
              original_channel_hint: str = None) -> bool:
        directive = self.build_directive(evi)
        # 🩹 [β.5.13 / 2026-05-19] original_channel_hint 注入 (env=1 时 channel='voice'
        # 主脑接管, 但仍想让主脑知道老规则会选啥 — silent_text hint 表示"轻量提醒,
        # 主脑可输出 [SILENCE] 表尊重 silent 本意, 也可升级 voice 视情况").
        nudge_ctx = {
            'type': 'proactive_care',
            'channel': channel,
            'nudge_directive': directive,
            'concern_id': evi.concern_id,
            'urgency_score': round(evi.urgency_score, 3),
            'source': 'ProactiveCareEngine',
            'urgency_breakdown': evi.breakdown,
            'original_channel_hint': original_channel_hint or channel,
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
# 🩹 [P0+20-β.3.4-vocab5 / 2026-05-18] 准则 6.5 vocab 持久化
# 原 ProactiveCareEngine class attrs _RESPONSE_POSITIVE / _RESPONSE_NEGATIVE
# 迁 memory_pool/response_classify_vocab.json + scripts/response_classify_dump.py.
# 范式照搬 β.3.0-vocab1 / β.3.4-vocab4.
# ============================================================

_SEED_RESPONSE_POSITIVE = (
    '好的', '好', '行', '可以', '会去', '我会', '会做', '去做', '马上',
    '现在去', '收到', '知道了', '了解', '明白', '听你的', '对的', '是的',
    "ok", "okay", "sure", "yes", "yeah", "yep", "i'll", "i will",
    "going to", "on it", "roger", "got it", "will do", "you're right",
)
_SEED_RESPONSE_NEGATIVE = (
    '别催', '不要催', '不用了', '算了', '不要提', '别提了', '我不',
    '不催了', '知道了别再说', '够了', '烦', '别管',
    'no', 'stop', "don't", 'leave it', 'not now', 'knock it off',
    'enough', 'shut up', 'stop pinging',
)

_RESPONSE_CLASSIFY_VOCAB_PATH = os.path.join(
    'memory_pool', 'response_classify_vocab.json')
_RESPONSE_CLASSIFY_CACHE: Optional[dict] = None
_RESPONSE_CLASSIFY_MTIME: float = 0.0


def _load_response_classify_from_json() -> Optional[dict]:
    """从 json 加载 active pattern 分类. 失败返 None (任一类空也走 fallback)."""
    if not os.path.exists(_RESPONSE_CLASSIFY_VOCAB_PATH):
        return None
    try:
        with open(_RESPONSE_CLASSIFY_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        by_cat = {'positive': [], 'negative': []}
        for p in data.get('patterns', []):
            if not isinstance(p, dict):
                continue
            if p.get('state') != 'active':
                continue
            cat = p.get('category', '')
            if cat not in by_cat:
                continue
            for kw in (p.get('keywords') or []):
                if isinstance(kw, str) and kw.strip():
                    by_cat[cat].append(kw.lower().strip())
        if not all(by_cat.values()):
            return None
        return {k: tuple(v) for k, v in by_cat.items()}
    except Exception:
        return None


def _get_response_classify_vocab() -> dict:
    """🩹 [β.3.4-vocab5] mtime cache. 文件变自动 reload."""
    global _RESPONSE_CLASSIFY_CACHE, _RESPONSE_CLASSIFY_MTIME
    try:
        mtime = os.path.getmtime(_RESPONSE_CLASSIFY_VOCAB_PATH) if os.path.exists(
            _RESPONSE_CLASSIFY_VOCAB_PATH) else 0
    except OSError:
        mtime = 0
    if _RESPONSE_CLASSIFY_CACHE is None or mtime > _RESPONSE_CLASSIFY_MTIME:
        loaded = _load_response_classify_from_json()
        if loaded is not None:
            _RESPONSE_CLASSIFY_CACHE = loaded
        else:
            _RESPONSE_CLASSIFY_CACHE = {
                'positive': _SEED_RESPONSE_POSITIVE,
                'negative': _SEED_RESPONSE_NEGATIVE,
            }
        _RESPONSE_CLASSIFY_MTIME = mtime
    return _RESPONSE_CLASSIFY_CACHE


def get_response_positive_vocab() -> tuple:
    return _get_response_classify_vocab().get('positive', _SEED_RESPONSE_POSITIVE)


def get_response_negative_vocab() -> tuple:
    return _get_response_classify_vocab().get('negative', _SEED_RESPONSE_NEGATIVE)


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
        # [β.4.10 / 2026-05-19] silent_text 独立全局冷却时间戳
        # voice 占用 last_any_nudge_ts, silent 占用 last_silent_global_ts, 两者独立 + 不重叠
        self.last_silent_global_ts: float = 0.0
        # 🩹 [β.2.9.9 / 2026-05-18] 反馈骨架: 记最后 nudge 的 concern_id 用于关联 Sir 回应
        self.last_nudge_concern_id: str = ''
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
        # β.5.23-A: 动态读 vocab cooldown
        _erc = _get_cd('EXPLICIT_REJECT_COOLDOWN_S', EXPLICIT_REJECT_COOLDOWN_S)
        with self._state_lock:
            self.explicit_reject_until = time.time() + _erc
        bg_log(
            f"🚫 [ProactiveCare] Sir 显式拒绝 → 静默 {int(_erc/60)} min"
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

    # 🩹 [β.2.9.11 / 2026-05-18] 闭环 — 暴露 last nudge 信息给 CommitmentWatcher
    # 关联自动 concern_link: Sir 在 nudge 后 120s 内说出的承诺自动归属该 concern.
    def get_last_nudge_info(self) -> Optional[tuple]:
        """返回 (concern_id, last_nudge_ts) 或 None."""
        with self._state_lock:
            cid = self.last_nudge_concern_id
            ts = self.last_any_nudge_ts
        if not cid or not ts:
            return None
        return (cid, ts)

    # 🩹 [β.2.9.9 / 2026-05-18] Sir 10:43 反馈: "贾维斯能不能通过后续承诺的执行
    # 来显式提高或降低这件事的关心度? 不仅睡眠, 后面贾维斯关心别的事情也会这样
    # 动态影响权重."
    # 通用机制 (准则 6 不针对特定 concern 硬编码):
    #   ProactiveCare 发 nudge 时记 last_nudge_concern_id
    #   Sir 在 120s 内回应 → notify_sir_response_post_nudge(text) →
    #     通用 vocab 判正面 → severity -= 0.1 + 衰减 fatigue
    #     通用 vocab 判负面 → severity 不动 + fatigue +1
    #     中性 → 不操作, 仅记 signal 让 L4 reflector 看
    # 🩹 [β.3.4-vocab5 / 2026-05-18] 准则 6.5 vocab 迁 module-level:
    # 原 class attrs _RESPONSE_POSITIVE / _RESPONSE_NEGATIVE → memory_pool/
    # response_classify_vocab.json. _classify_response 改用 module getter.
    @staticmethod
    def _classify_response(text: str) -> str:
        """通用正面/负面/中性判. vocab driven (Sir 准则 6 + 6.5).
        优先看负面 (因 '不会做' 含 '会做' 正面词应当判负).
        """
        if not text:
            return 'neutral'
        t = text.strip().lower()
        for w in get_response_negative_vocab():
            if w in t:
                return 'negative'
        for w in get_response_positive_vocab():
            if w in t:
                return 'positive'
        return 'neutral'

    def notify_sir_response_post_nudge(self, sir_text: str,
                                          now_ts: float = None) -> Optional[str]:
        """主对话路径调用: Sir 刚说了一段, 看是否在响应最近 nudge.

        返回 'positive' / 'negative' / 'neutral' / None (不算回应 nudge).
        自动调 ledger.record_signal + 调相应 notify_concern_* API.

        chat_bypass / worker 在 Sir 文本到达后调一次即可, 不阻塞主路径.
        """
        if now_ts is None:
            now_ts = time.time()
        with self._state_lock:
            cid = self.last_nudge_concern_id
            last_at = self.last_any_nudge_ts
        if not cid or not last_at:
            return None
        # Sir 必须在 nudge 后 2min 内回应才算 "关于这个 nudge"
        if now_ts - last_at > 120.0:
            return None

        verdict = self._classify_response(sir_text)
        try:
            if verdict == 'positive':
                # Sir 表态会做 → 信任先降 severity 0.1
                if self.ledger is not None:
                    self.ledger.record_signal(
                        cid,
                        f"Sir 听到 nudge 后正面回应: '{sir_text[:80]}'",
                        severity_delta=-0.1,
                    )
                self.notify_concern_aligned(cid)
            elif verdict == 'negative':
                # Sir 拒绝 → fatigue +1, severity 不变 (避免误降)
                if self.ledger is not None:
                    self.ledger.record_signal(
                        cid,
                        f"Sir 听到 nudge 后拒绝: '{sir_text[:80]}'",
                        severity_delta=0,
                    )
                self.notify_concern_rejected(cid)
            else:
                # 中性: 仅记 signal 让 L4 reflector 看, 不动 severity
                if self.ledger is not None:
                    self.ledger.record_signal(
                        cid,
                        f"Sir 听到 nudge 后中性回应: '{sir_text[:80]}'",
                        severity_delta=0,
                    )
        except Exception as _e:
            bg_log(f"⚠️ [ProactiveCare/PostNudge] record_signal fail: {_e}")
        bg_log(
            f"🎯 [ProactiveCare/PostNudge] concern={cid} verdict={verdict} "
            f"sir='{sir_text[:50]}'"
        )
        return verdict

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

        # 1. warm-up (β.5.23-A: 动态读 vocab)
        _wm = _get_cd('WARMUP_SECONDS', WARMUP_SECONDS)
        if now_ts - self.start_ts < _wm:
            return

        # 1.5. [β-2.5] 跑 sensor → 让 sensor 派生 signal 喂给 concern
        # 不依赖 Sir 主动开口才知道关心啥
        # 🩹 [β.5.27 / 2026-05-20] Sir 02:13 log: 'NoneType object has no attribute tick'.
        # Root cause: _resolve_deps partial-init 时 sensor 可能仍 None (race condition).
        # 修法: None guard + 真异常才 log (空 None 早返不噪音).
        if self.sensor is None:
            # 静默早返, 等下一 tick _resolve_deps 把 sensor 创出来
            pass
        else:
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

        # [β.5.0-A / 2026-05-19] 准则 6 数据强耦合: top concern publish 到 SWM
        # 让主脑下次 prompt 看到 "Sir 当下最受关心的事 = X, urgency=Y", 不依赖
        # ProactiveCare 自己 push __NUDGE__ 才让主脑知道.
        try:
            from jarvis_utils import get_event_bus
            _swm = get_event_bus()
            if _swm is not None:
                _cid = getattr(top_c, 'id', '?')
                _sev = getattr(top_c, 'severity', 0.0)
                _swm.publish(
                    etype='concern_active',
                    description=f"top_concern={_cid} urgency={top_u:.2f} severity={_sev:.2f}",
                    source='ProactiveCare',
                    metadata={
                        'concern_id': _cid,
                        'urgency': round(top_u, 3),
                        'severity': round(_sev, 3),
                        'breakdown': top_bd,
                    },
                    salience=min(0.95, 0.4 + top_u * 0.5),  # urgency 越高 salience 越高
                )

                # 🩹 [β.5.40-fix / 2026-05-20 16:30] Sir 真理: 16:07 sleep nudge BUG.
                # 准则 6 evidence-driven: 不动 compute_urgency 硬 dampen 公式, 改 publish
                # concern_timing_evidence 让主脑看 → 主脑 directive 自决是否提
                # 详 docs/JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md
                _timing_ev = _compute_concern_timing_evidence(top_c, now_ts)
                if _timing_ev:
                    _swm.publish(
                        etype='concern_timing_evidence',
                        description=(
                            f"concern={_cid} optimal={_timing_ev['optimal_timing']} "
                            f"current_h={_timing_ev['current_hour']} "
                            f"in_window={_timing_ev['is_in_optimal_window']} "
                            f"hours_until={_timing_ev['hours_until_optimal']:+d}"
                        ),
                        source='ProactiveCare',
                        salience=0.65 if not _timing_ev['is_in_optimal_window'] else 0.40,
                        metadata={
                            'concern_id': _cid,
                            **_timing_ev,
                        },
                        ttl=300.0,
                    )
        except Exception:
            pass

        # 5. guard 判定
        with self._state_lock:
            last_any = self.last_any_nudge_ts
            last_silent = self.last_silent_global_ts
            reject_until = self.explicit_reject_until
        ok, reason = self.guard.can_speak(top_c, top_u, now_ts, last_any, reject_until)
        # [β.4.10 / 2026-05-19] silent_text 独立全局 cooldown (90s):
        # voice gate 主用 last_any_nudge_ts (300s); silent 用独立 last_silent_global_ts (90s).
        # 治 Sir 凌晨 1 点 sleep silent → 立刻 hydration silent 连推 BUG.
        if ok and last_silent > 0:
            _silent_age = now_ts - last_silent
            _sgc = _get_cd('SILENT_GLOBAL_COOLDOWN_S', SILENT_GLOBAL_COOLDOWN_S)
            if _silent_age < _sgc:
                ok = False
                reason = f'silent_global_cooldown ({int(_sgc - _silent_age)}s left)'
        if not ok:
            # 🩹 [β.2.9.11 / 2026-05-18] Sir 12:30 痛点 "skip 刷屏":
            # 旧版每 60s tick 同 cid+reason 都 bg_log 一遍, 30min cooldown 刷 30 次.
            # 准则 6 通用节流: 同 (cid, reason_prefix) 5min 内只 log 1 次.
            try:
                if not hasattr(self, '_skip_log_throttle'):
                    self._skip_log_throttle = {}
                _cid = getattr(top_c, 'id', '?')
                _reason_prefix = reason.split('(')[0].strip()  # 去掉动态秒数
                _key = (_cid, _reason_prefix)
                _last_log = self._skip_log_throttle.get(_key, 0)
                if now_ts - _last_log >= 300.0:  # 5min 节流
                    bg_log(
                        f"🛑 [ProactiveCare] skip concern={_cid} "
                        f"urgency={top_u:.2f} reason={reason}"
                    )
                    self._skip_log_throttle[_key] = now_ts
                    # 清过期 entries 防内存泄漏
                    if len(self._skip_log_throttle) > 200:
                        _cutoff = now_ts - 1800
                        self._skip_log_throttle = {
                            k: ts for k, ts in self._skip_log_throttle.items()
                            if ts > _cutoff
                        }
            except Exception:
                pass
            return

        # 6. build evidence + 选 channel + push
        evi = self.selector.build_evidence(top_c, top_u, top_bd)
        # β-3.1 channel 升级: 先 silent 试探, 再 voice 升级
        with self._state_lock:
            last_silent_ts = self.silent_history.get(top_c.id, 0)
        silent_recent = (now_ts - last_silent_ts) < self.silent_decay_s
        channel = self.synth.choose_channel(evi, silent_recent)
        # 🩹 [β.5.13 / 2026-05-19] legacy_hint 给主脑作为 channel 参考
        # env=1 时 channel 已被 choose_channel 改为 'voice', legacy_hint 让主脑
        # 仍知道老规则会选 'silent_text' (轻量) 还是 'voice' (重要)
        legacy_hint = self.synth._legacy_channel_for_hint(evi, silent_recent)
        sent = self.synth.push(self.worker, evi, dry_run=self.dry_run,
                                 channel=channel,
                                 original_channel_hint=legacy_hint)
        if sent:
            with self._state_lock:
                # voice 算"全局 voice nudge" (300s 冷却), silent_text 占独立 silent 全局 (90s)
                if channel == 'voice':
                    self.last_any_nudge_ts = now_ts
                else:
                    self.silent_history[top_c.id] = now_ts
                    # [β.4.10 / 2026-05-19] silent 独立全局冷却 — 防 sleep silent → hydration silent 连推
                    self.last_silent_global_ts = now_ts
                # 🩹 [β.2.9.9] 记最后 nudge 的 concern_id, Sir 后续 2min 回应可关联
                self.last_nudge_concern_id = top_c.id
            try:
                self.ledger.record_triggered(top_c.id)
            except Exception:
                pass
            # 🩹 [β.2.9.9-D / 2026-05-18] Sir 10:43 痛点: nudge 后无焦点模式
            # → 开 60s soft focus, Sir 可直接口头回应 ("我中午会补觉") 不用喊 Jarvis
            if channel == 'voice':
                try:
                    rs = getattr(self.worker, 'return_sentinel', None)
                    if rs is not None and hasattr(rs, 'open_soft_focus'):
                        rs.open_soft_focus(
                            duration_s=60.0, reason='proactive_care')
                except Exception as _fce:
                    bg_log(f"⚠️ [ProactiveCare] open_soft_focus fail: {_fce}")

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
