# -*- coding: utf-8 -*-
"""[β.5.40-A2 / 2026-05-20] Physio proxy — 键鼠节奏 → energy/focus/stress 评分

Sir 方向 A.2 (~3h):
  - 读 PhysicalEnvironmentProbe 已有 key/mouse 5min fields
  - 算 energy (活跃度) / focus (专注度) / stress (压力指数) 评分 (0-1)
  - publish 'physio_state' 到 SWM (TTL 180s, salience 0.45)
  - ProactiveCare 在 stress 高时减 nudge severity
  - 主脑 directive 看 physio_state evidence 调 tone

算法 (Sir 精准要求, 保守):
  - energy: norm(key_5min) * 0.6 + norm(mouse_dist_5min) * 0.4
  - focus: (1 - backspace_ratio) * 0.5 + (1 - switch_freq_norm) * 0.3 + (1 - undo_norm) * 0.2
  - stress: backspace_ratio_above_baseline * 0.4 + erratic_burst * 0.3 + undo_above_baseline * 0.3

baseline 来自 7d 移动平均 (memory_pool/physio_baseline.json), 数据少 fallback hardcoded.

需 baseline 校准 ≥ 1 周 才生效 (data points ≥ 50).
ENV JARVIS_PHYSIO_DISABLE=1 关闭.

test: tests/_test_p0_plus_20_beta540_physio_proxy.py
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# ============================================================
# Constants & baselines
# ============================================================

# Hardcoded defaults if no baseline collected yet
DEFAULT_BASELINE = {
    'key_5min_p50': 200,       # 5min 内 200 击键算 "正常"
    'key_5min_p90': 500,
    'mouse_5min_p50': 5000,    # 5min 鼠标移动 5000px
    'mouse_5min_p90': 15000,
    'backspace_ratio_p50': 0.08,
    'backspace_ratio_p90': 0.18,
    'switch_5min_p50': 5,
    'switch_5min_p90': 15,
    'undo_5min_p50': 1,
    'undo_5min_p90': 5,
}

# publish 限频
PUBLISH_COOLDOWN_S = 60.0

# Sir 精准要求: 数据采样 ≥ 30s session 才生效 (启动初期不可信)
MIN_SESSION_AGE_S = 30.0


@dataclass
class PhysioState:
    energy: float = 0.0      # 0-1
    focus: float = 0.0       # 0-1
    stress: float = 0.0      # 0-1
    confidence: float = 0.0  # 0-1, 0=数据不足
    timestamp: float = 0.0
    metadata: dict = field(default_factory=dict)


def _norm_clip(value: float, baseline_p50: float, baseline_p90: float) -> float:
    """正规化 value → 0-1, p50→0.5, p90→0.9."""
    if baseline_p90 <= baseline_p50:
        return 0.5
    if value <= 0:
        return 0.0
    if value <= baseline_p50:
        # 0 → 0, p50 → 0.5 linear
        return max(0.0, 0.5 * value / baseline_p50)
    # > p50: linear to 0.9 at p90, clip 1.0
    extra = (value - baseline_p50) / (baseline_p90 - baseline_p50)
    return min(1.0, 0.5 + 0.4 * extra)


def compute_physio_state(
    key_5min: int = 0,
    mouse_dist_5min: float = 0.0,
    click_5min: int = 0,
    backspace_ratio: float = 0.0,
    burst_pause_ratio: float = 0.0,
    switch_freq_5min: int = 0,
    shortcut_undo_5min: int = 0,
    session_age_s: float = 0.0,
    baseline: Optional[Dict] = None,
) -> PhysioState:
    """算 energy/focus/stress (0-1). 不抛异常."""
    bl = dict(DEFAULT_BASELINE)
    if baseline:
        bl.update(baseline)

    state = PhysioState(timestamp=time.time())

    # Sir 精准: session 太短 confidence 0
    if session_age_s < MIN_SESSION_AGE_S:
        return state

    # energy = key_norm * 0.6 + mouse_norm * 0.4
    key_n = _norm_clip(key_5min, bl['key_5min_p50'], bl['key_5min_p90'])
    mouse_n = _norm_clip(mouse_dist_5min, bl['mouse_5min_p50'], bl['mouse_5min_p90'])
    energy = round(key_n * 0.6 + mouse_n * 0.4, 3)

    # focus = (1 - backspace_ratio) * 0.5 + (1 - switch_freq_n) * 0.3 + (1 - undo_n) * 0.2
    # backspace_ratio 高 = 反复改 → focus 低
    bsr_n = min(1.0, backspace_ratio / max(bl['backspace_ratio_p90'], 0.01))
    switch_n = _norm_clip(switch_freq_5min, bl['switch_5min_p50'], bl['switch_5min_p90'])
    undo_n = _norm_clip(shortcut_undo_5min, bl['undo_5min_p50'], bl['undo_5min_p90'])
    focus = round(
        (1.0 - bsr_n) * 0.5 + (1.0 - switch_n) * 0.3 + (1.0 - undo_n) * 0.2, 3
    )
    focus = max(0.0, min(1.0, focus))

    # stress = bsr_above * 0.4 + burst_erratic * 0.3 + undo_above * 0.3
    # bsr 超 p90 → stress 拉满; burst_pause_ratio < 0.3 = 节奏 erratic (不流畅)
    bsr_above = max(0.0, (backspace_ratio - bl['backspace_ratio_p50']) /
                    max(bl['backspace_ratio_p90'] - bl['backspace_ratio_p50'], 0.01))
    bsr_above = min(1.0, bsr_above)
    # burst_pause_ratio 范围 0-1, 0.5-0.8 = 流畅, 接近 0 或 1 = erratic (要么全 burst 要么全 pause)
    # 简化: < 0.3 = erratic
    erratic = 1.0 if (burst_pause_ratio > 0 and burst_pause_ratio < 0.3) else 0.0
    undo_above = max(0.0, (shortcut_undo_5min - bl['undo_5min_p50']) /
                     max(bl['undo_5min_p90'] - bl['undo_5min_p50'], 1.0))
    undo_above = min(1.0, undo_above)
    stress = round(bsr_above * 0.4 + erratic * 0.3 + undo_above * 0.3, 3)
    stress = max(0.0, min(1.0, stress))

    # confidence: session 越长越可靠 + 数据多
    conf_session = min(1.0, session_age_s / 300.0)  # 5 min session = 1.0
    conf_data = min(1.0, key_5min / 50.0)  # ≥ 50 击键 = 1.0
    state.confidence = round(0.5 * conf_session + 0.5 * conf_data, 3)
    state.energy = energy
    state.focus = focus
    state.stress = stress
    state.metadata = {
        'key_5min': key_5min,
        'mouse_dist': mouse_dist_5min,
        'backspace_ratio': backspace_ratio,
        'switch_freq': switch_freq_5min,
        'undo_5min': shortcut_undo_5min,
        'session_age_s': round(session_age_s, 1),
    }
    return state


# ============================================================
# PhysioProxy publish (singleton, hook 到 sensor tick)
# ============================================================

class PhysioProxy:
    """Hook 到 PhysicalEnvironmentProbe._publish_loop / ProactiveCare.tick
    定期算 PhysioState + publish 'physio_state' 到 SWM.
    """

    def __init__(self, event_bus: Any = None, enabled: bool = True,
                  baseline_path: Optional[str] = None):
        self._lock = threading.Lock()
        self._enabled = enabled
        self._event_bus = event_bus
        self._last_publish_at = 0.0
        self._baseline_path = baseline_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'memory_pool', 'physio_baseline.json',
        )
        self._baseline_cache = None
        self._baseline_mtime = 0.0
        self._n_published = 0

    def is_enabled(self) -> bool:
        return self._enabled and self._event_bus is not None

    def attach_event_bus(self, bus: Any) -> None:
        with self._lock:
            self._event_bus = bus

    def _load_baseline(self) -> Optional[Dict]:
        try:
            if not os.path.exists(self._baseline_path):
                return None
            mt = os.path.getmtime(self._baseline_path)
            if mt == self._baseline_mtime and self._baseline_cache:
                return self._baseline_cache
            with open(self._baseline_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._baseline_cache = data.get('baseline', None)
            self._baseline_mtime = mt
            return self._baseline_cache
        except Exception:
            return None

    def compute_and_publish(self, snap: Dict) -> Optional[PhysioState]:
        """从 sensor snap 读 fields, 算 physio, publish SWM.
        
        snap: PhysicalEnvironmentProbe.get_snapshot() 返的 dict.
        
        Returns: PhysioState (or None if not enough data / cooldown).
        """
        if not self._enabled or self._event_bus is None:
            return None

        with self._lock:
            now = time.time()
            if now - self._last_publish_at < PUBLISH_COOLDOWN_S:
                return None

        try:
            state = compute_physio_state(
                key_5min=int(snap.get('key_press_count_5min', 0) or 0),
                mouse_dist_5min=float(snap.get('mouse_distance_5min', 0.0) or 0.0),
                click_5min=int(snap.get('click_count_5min', 0) or 0),
                backspace_ratio=float(snap.get('backspace_ratio', 0.0) or 0.0),
                burst_pause_ratio=float(snap.get('burst_pause_ratio', 0.0) or 0.0),
                switch_freq_5min=int(snap.get('switch_frequency_5min', 0) or 0),
                shortcut_undo_5min=int(snap.get('shortcut_undo_5min', 0) or 0),
                session_age_s=float(snap.get('session_duration_minutes', 0.0) or 0.0) * 60.0,
                baseline=self._load_baseline(),
            )
        except Exception:
            return None

        if state.confidence < 0.1:
            return None  # 数据太少, 不 publish (避免噪声)

        # publish
        try:
            self._event_bus.publish(
                etype='physio_state',
                description=(
                    f"energy={state.energy:.2f} focus={state.focus:.2f} "
                    f"stress={state.stress:.2f} conf={state.confidence:.2f}"
                ),
                source='PhysioProxy',
                metadata={
                    'energy': state.energy,
                    'focus': state.focus,
                    'stress': state.stress,
                    'confidence': state.confidence,
                    'raw': state.metadata,
                },
                salience=0.55 if state.stress > 0.6 else 0.35,
                ttl=180.0,
            )
            self._last_publish_at = time.time()
            self._n_published += 1
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"💪 [PhysioProxy] energy={state.energy:.2f} focus={state.focus:.2f} "
                    f"stress={state.stress:.2f} conf={state.confidence:.2f}"
                )
            except Exception:
                pass
        except Exception:
            pass

        return state

    def get_stats(self) -> Dict:
        return {
            'enabled': self._enabled,
            'bus_attached': self._event_bus is not None,
            'n_published': self._n_published,
            'last_publish_at': self._last_publish_at,
        }


# Register etype + salience to ConversationEventBus (idempotent)
def _register_etype_defaults():
    try:
        from jarvis_utils import ConversationEventBus
        if 'physio_state' not in ConversationEventBus.DEFAULT_TTL:
            ConversationEventBus.DEFAULT_TTL['physio_state'] = 180
        if 'physio_state' not in ConversationEventBus.DEFAULT_SALIENCE:
            ConversationEventBus.DEFAULT_SALIENCE['physio_state'] = 0.45
    except Exception:
        pass


_register_etype_defaults()


# Singleton
_GLOBAL_PROXY: Optional[PhysioProxy] = None
_SINGLETON_LOCK = threading.Lock()


def get_physio_proxy(event_bus: Any = None) -> PhysioProxy:
    """获取全局 PhysioProxy 单例."""
    global _GLOBAL_PROXY
    with _SINGLETON_LOCK:
        if _GLOBAL_PROXY is None:
            enabled = os.environ.get('JARVIS_PHYSIO_DISABLE', '0') != '1'
            _GLOBAL_PROXY = PhysioProxy(event_bus=event_bus, enabled=enabled)
        elif event_bus is not None and _GLOBAL_PROXY._event_bus is None:
            _GLOBAL_PROXY.attach_event_bus(event_bus)
        return _GLOBAL_PROXY
