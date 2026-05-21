# -*- coding: utf-8 -*-
"""[Gap-Z3 / β.5.46-fix11 / 2026-05-22 00:25] Reflector Budget Controller.

8 个 Reflector (Concerns/Sleep/Profile/Soul/InsideJoke/ScreenTease/Struggle/etc)
各自调度 + 各自调 LLM. 没统一预算控制 → 周总 LLM 调用可能炸. 治法: 中央预算
tracker, 每个 reflector LLM 调用前 acquire(), 周预算用尽就 reject.

== 准则合规 ==

- 准则 1 (TTFT): 一行预算检查, ~1ms latency
- 准则 6.5: weekly_cap + usage 持久化, CLI dump

== 文件 ==

- config: memory_pool/reflector_budget_config.json
- state:  memory_pool/reflector_budget_state.json (rolling 周窗口)
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Optional


_THIS = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_THIS, 'memory_pool', 'reflector_budget_config.json')
_STATE_PATH = os.path.join(_THIS, 'memory_pool', 'reflector_budget_state.json')

_FALLBACK_CONFIG = {
    'enabled': True,
    'weekly_cap_total': 200,
    'per_reflector_cap': {},  # {name: cap}, 没指定走 weekly_cap_total / num_reflectors
    'reset_dow': 1,  # ISO weekday: Mon=1
}


def _load_config() -> Dict[str, Any]:
    try:
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                merged = dict(_FALLBACK_CONFIG)
                for k, v in cfg.items():
                    if not k.startswith('_'):
                        merged[k] = v
                return merged
    except Exception:
        pass
    return dict(_FALLBACK_CONFIG)


def _load_state() -> Dict[str, Any]:
    try:
        if os.path.exists(_STATE_PATH):
            with open(_STATE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {'window_start_ts': 0.0, 'usage_by_name': {}}


def _save_state(state: Dict[str, Any]) -> bool:
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        tmp = _STATE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _STATE_PATH)
        return True
    except Exception:
        return False


def _is_window_stale(state: Dict[str, Any]) -> bool:
    """Rolling 周窗口: > 7 天 reset usage."""
    win_start = float(state.get('window_start_ts', 0.0))
    if win_start <= 0:
        return True
    age_s = time.time() - win_start
    return age_s > 7 * 86400.0


class ReflectorBudget:
    """中央预算控制. Singleton.

    Usage:
        budget = ReflectorBudget()
        if budget.acquire('concerns_reflector', cost_units=1):
            # LLM call OK
            ...
        else:
            # 周预算用尽 / 单 reflector 上限到 → skip
            return
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.cfg = _load_config()
        self.state = _load_state()
        # 启动时检查窗口
        with self._lock:
            if _is_window_stale(self.state):
                self._reset_window_locked()

    def _reset_window_locked(self) -> None:
        self.state = {
            'window_start_ts': time.time(),
            'window_start_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'usage_by_name': {},
        }
        _save_state(self.state)

    def acquire(self, reflector_name: str, cost_units: int = 1) -> bool:
        """请求 LLM 调用预算. True = OK 调用, False = 拒绝.

        Args:
            reflector_name: e.g. 'concerns_reflector'
            cost_units: 1 = 一次 LLM call. 复杂 reflector 可传 2-3.

        Returns False 当:
            - config disabled (env force) - 反过来 returns True 兜底
            - weekly_cap_total 周总用量已到
            - per_reflector_cap[name] 单 reflector 用量已到
        """
        if not self.cfg.get('enabled', True):
            return True  # disabled = 不限制 = 全过

        with self._lock:
            if _is_window_stale(self.state):
                self._reset_window_locked()
            usage_map = self.state.get('usage_by_name', {})
            current = int(usage_map.get(reflector_name, 0))
            total_used = sum(usage_map.values())
            weekly_cap = int(self.cfg.get('weekly_cap_total', 200))
            per_caps = self.cfg.get('per_reflector_cap', {}) or {}
            per_cap = per_caps.get(reflector_name)

            # 检 weekly cap
            if total_used + cost_units > weekly_cap:
                return False
            # 检 per cap (如指定)
            if per_cap is not None:
                try:
                    per_cap_int = int(per_cap)
                    if current + cost_units > per_cap_int:
                        return False
                except Exception:
                    pass

            # OK 占预算
            usage_map[reflector_name] = current + cost_units
            self.state['usage_by_name'] = usage_map
            _save_state(self.state)
            return True

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            usage_map = dict(self.state.get('usage_by_name', {}))
            total_used = sum(usage_map.values())
            return {
                'window_start_iso': self.state.get('window_start_iso', ''),
                'weekly_cap_total': int(self.cfg.get('weekly_cap_total', 200)),
                'total_used': total_used,
                'remaining': max(0, int(self.cfg.get('weekly_cap_total', 200)) - total_used),
                'usage_by_name': usage_map,
                'per_reflector_cap': dict(self.cfg.get('per_reflector_cap', {}) or {}),
            }

    def reset_window(self) -> None:
        """Sir CLI 用 — 强制 reset 周窗口."""
        with self._lock:
            self._reset_window_locked()


# ============================================================
# Singleton
# ============================================================

_DEFAULT_BUDGET: Optional[ReflectorBudget] = None
_INIT_LOCK = threading.Lock()


def get_default_budget() -> ReflectorBudget:
    """Returns global singleton. 自动 init."""
    global _DEFAULT_BUDGET
    with _INIT_LOCK:
        if _DEFAULT_BUDGET is None:
            _DEFAULT_BUDGET = ReflectorBudget()
        return _DEFAULT_BUDGET


def reset_for_test() -> None:
    global _DEFAULT_BUDGET
    with _INIT_LOCK:
        _DEFAULT_BUDGET = None
