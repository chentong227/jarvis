# -*- coding: utf-8 -*-
"""[Reshape M5.A / 2026-05-24] SWMTrigger — daemon 集中接管 sentinel push __NUDGE__.

# 治本目标 (Sir 准则 6 三维耦合)

老路径 (sentinel-driven):
    Sentinel (Conductor / SmartNudge / ProactiveCare / CommitmentWatcher) 决定 fire
        ↓
    sentinel 直接 worker.push_command("__NUDGE__:{json}")
        ↓
    主脑 stream_nudge → reaction

问题: sentinel **既感知又决策又 push**, 违反 §6 (sensor-only / 决策集中主脑).

新路径 (SWMTrigger-driven):
    Sensor / Sentinel 只 publish 'reminder_fired' / 'cyclic_task_due' / etc. 进 SWM
        ↓
    SWMTrigger daemon 1s tick scan SWM 找 unprocessed high-salience event
        ↓
    SWMTrigger 拼 nudge_context (event 数据 + SWM evidence chain) → push __NUDGE__
        ↓
    主脑 stream_nudge 看 SWM 全景 → 自决 reaction

# 当前阶段 (M5.A MVP, 不破老路径)

dual-mode 兼容 (env opt-in):
- 默认 disabled (env JARVIS_SWM_TRIGGER 未设 / =0): daemon 不处理 event, 老 sentinel
  push __NUDGE__ 路径不变.
- env JARVIS_SWM_TRIGGER=1: daemon 启用. 但仍只接管 metadata['fired_via']='swm_trigger'
  的 event — 给将来 sentinel publish-only 切换用.

# 监听 SWM etypes (M5.A 初版)

- 'reminder_fired'      (M4.4 CommitmentWatcher dual-emit)
- 'cyclic_task_due'     (M4.5 CyclicTaskStore 触发 trigger_time)
- 'watch_task_fired'    (WatchTaskJudge LLM judge match)
- 'proactive_nudge_required'  (将来通用 trigger event, 任意 sensor publish)

# 不监听 (避免双 push)

- 'proactive_nudge_fired'  — sentinel 已 push __NUDGE__, daemon 不再处理 (除非 fired_via='swm_trigger')

# 设计

- 1s tick 频率 (低开销)
- dedup by event timestamp + etype + key (避免重复 push 同一 event)
- 配置持久化: memory_pool/swm_trigger_config.json (准则 6.5 持久化)
- L7 reflector 后置 (M5.B+)

# 接口

- SWMTrigger(worker_ref) — daemon, start/stop
- get_default_trigger() — singleton
- publish_to_swm_trigger(etype, ...) — convenience (sentinel 用此 API publish event)
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set


# ============================================================
# Config
# ============================================================

DEFAULT_CONFIG_PATH = os.path.join('memory_pool', 'swm_trigger_config.json')

DEFAULT_CONFIG = {
    'enabled': False,                  # env opt-in 默认 False
    'tick_interval_s': 1.0,
    'min_salience': 0.6,               # 只看 salience >= 0.6 的 event
    'dedup_window_s': 60.0,             # 同 event_key 60s 内只处理 1 次
    'subscribed_etypes': [
        'reminder_fired',
        'cyclic_task_due',
        'watch_task_fired',
        'proactive_nudge_required',
    ],
    # 兼容老 'proactive_nudge_fired': 只处理 metadata.fired_via='swm_trigger' 的
    'process_only_swm_trigger_metadata': True,
}


def _load_config() -> Dict[str, Any]:
    """读 config 持久化, 缺则用 default."""
    cfg = dict(DEFAULT_CONFIG)
    try:
        if os.path.exists(DEFAULT_CONFIG_PATH):
            with open(DEFAULT_CONFIG_PATH, 'r', encoding='utf-8') as f:
                disk_cfg = json.load(f) or {}
            cfg.update(disk_cfg)
    except Exception:
        pass
    # env override
    env_enabled = os.environ.get('JARVIS_SWM_TRIGGER', '').strip()
    if env_enabled in ('1', 'true', 'True', 'yes', 'on'):
        cfg['enabled'] = True
    elif env_enabled in ('0', 'false', 'False', 'no', 'off'):
        cfg['enabled'] = False
    return cfg


def _save_config(cfg: Dict[str, Any]) -> bool:
    try:
        os.makedirs(os.path.dirname(DEFAULT_CONFIG_PATH), exist_ok=True)
        tmp = DEFAULT_CONFIG_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DEFAULT_CONFIG_PATH)
        return True
    except Exception:
        return False


# ============================================================
# Event-to-NudgeContext mapping
# ============================================================

@dataclass
class TriggerHandler:
    """一个 SWM etype 的 nudge_context 拼装规则."""
    etype: str
    nudge_type: str               # final __NUDGE__ context['type']
    extract_fn: Callable[[Dict], Dict]  # event_record → nudge_context dict


def _extract_reminder_fired(event: Dict) -> Dict:
    """commit_watcher publish 的 reminder_fired event → commitment_check nudge_context."""
    md = event.get('metadata', {}) or {}
    return {
        'type': 'commitment_check',
        'commitment_description': md.get('commitment_description', ''),
        'commitment_source_text': md.get('commitment_source_text', ''),
        'commitment_time': md.get('commitment_time', ''),
        'overdue_minutes': md.get('overdue_minutes', 0),
        'sleep_mode_active': md.get('sleep_mode_active', False),
        'sleep_duration_min': md.get('sleep_duration_min', 0),
        'recent_sleep_min': md.get('recent_sleep_min', 0),
        'promise_id': md.get('promise_id', ''),
        '_swm_trigger_origin': event.get('event_id', ''),
    }


def _extract_cyclic_task_due(event: Dict) -> Dict:
    """CyclicTaskStore publish 的 cyclic_task_due event → cyclic_task_fire context."""
    md = event.get('metadata', {}) or {}
    return {
        'type': 'cyclic_task_fire',
        'task_id': md.get('task_id', ''),
        'kind': md.get('kind', ''),
        'description': md.get('description', ''),
        'intent_template': md.get('intent_template', ''),
        'cycle_count': md.get('cycle_count', 0),
        '_swm_trigger_origin': event.get('event_id', ''),
    }


def _extract_watch_task_fired(event: Dict) -> Dict:
    """WatchTaskJudge publish 的 watch_task_fired event → watch_task_alert context."""
    md = event.get('metadata', {}) or {}
    return {
        'type': 'watch_task_alert',
        'task_id': md.get('task_id', ''),
        'what_to_watch': md.get('what_to_watch', ''),
        'trigger_evidence': md.get('trigger_evidence', ''),
        'notify_msg_en': md.get('notify_msg_en', ''),
        'notify_msg_zh': md.get('notify_msg_zh', ''),
        'rationale': md.get('rationale', ''),
        '_swm_trigger_origin': event.get('event_id', ''),
    }


def _extract_generic_proactive(event: Dict) -> Dict:
    """proactive_nudge_required: caller 在 metadata 里直接传 nudge_context."""
    md = event.get('metadata', {}) or {}
    nctx = md.get('nudge_context', {}) or {}
    if isinstance(nctx, dict) and 'type' in nctx:
        nctx['_swm_trigger_origin'] = event.get('event_id', '')
        return nctx
    # fallback: 简单 generic
    return {
        'type': md.get('nudge_type', 'proactive_observation'),
        'description': event.get('description', ''),
        '_swm_trigger_origin': event.get('event_id', ''),
    }


DEFAULT_HANDLERS: List[TriggerHandler] = [
    TriggerHandler('reminder_fired', 'commitment_check', _extract_reminder_fired),
    TriggerHandler('cyclic_task_due', 'cyclic_task_fire', _extract_cyclic_task_due),
    TriggerHandler('watch_task_fired', 'watch_task_alert', _extract_watch_task_fired),
    TriggerHandler('proactive_nudge_required', 'proactive_observation', _extract_generic_proactive),
]


# ============================================================
# SWMTrigger daemon
# ============================================================


class SWMTrigger(threading.Thread):
    """监 SWM event → 拼 nudge_context → push __NUDGE__ 到 worker.

    Sentinel 慢慢退化 publish-only 后, daemon 是统一 trigger 入口.
    """

    def __init__(self, worker_ref: Any = None,
                 config: Optional[Dict[str, Any]] = None,
                 handlers: Optional[List[TriggerHandler]] = None):
        super().__init__(daemon=True, name='SWMTrigger')
        self.worker_ref = worker_ref
        self.config = config or _load_config()
        self.handlers = handlers or list(DEFAULT_HANDLERS)
        self._handler_map = {h.etype: h for h in self.handlers}
        self._stop = threading.Event()
        self._processed_keys: Dict[str, float] = {}  # event_key → last_processed_ts
        self._lock = threading.Lock()
        self._tick_count = 0
        self._fired_count = 0

    def stop(self):
        self._stop.set()

    def _make_event_key(self, event: Dict) -> str:
        """event dedup key: event_id (lineage M1) > etype+ts."""
        eid = event.get('event_id') or ''
        if eid:
            return eid
        etype = event.get('etype') or event.get('type') or 'unknown'
        ts = event.get('ts') or event.get('fired_at') or 0
        return f'{etype}@{int(float(ts) * 1000)}'

    def _is_dedup_recent(self, key: str) -> bool:
        """是否最近 dedup_window_s 内已处理过."""
        now = time.time()
        last = self._processed_keys.get(key, 0.0)
        return (now - last) < float(self.config.get('dedup_window_s', 60.0))

    def _mark_processed(self, key: str) -> None:
        with self._lock:
            self._processed_keys[key] = time.time()
            # housekeep: 删 > 1h 的老 key
            cutoff = time.time() - 3600
            stale = [k for k, t in self._processed_keys.items() if t < cutoff]
            for k in stale:
                del self._processed_keys[k]

    def _should_process_event(self, event: Dict) -> bool:
        """筛: salience / etype / metadata 过滤."""
        # salience filter
        sal = float(event.get('salience') or 0.0)
        if sal < float(self.config.get('min_salience', 0.6)):
            return False
        # etype filter (subscribed)
        etype = event.get('etype') or event.get('type') or ''
        if etype not in self._handler_map:
            return False
        # metadata fired_via filter (避免双 push 老路径)
        if self.config.get('process_only_swm_trigger_metadata', True):
            md = event.get('metadata', {}) or {}
            fired_via = md.get('fired_via', '')
            # 'swm_trigger' = 新路径 (sentinel publish-only)
            # 'swm_trigger_acceptable' = handler 默认接受 (commit-watcher reminder_fired etc.)
            # '__NUDGE__' = 老 sentinel push 路径, daemon 跳过
            # '' = 老/未标记, 看 etype 判 (default safe behavior)
            if fired_via == '__NUDGE__':
                return False
            # reminder_fired / cyclic_task_due / watch_task_fired 默认接受
            # (M4.4/M4.5 sentinel 已 dual-emit, daemon 启用时单源 trigger)
            if etype in ('reminder_fired', 'cyclic_task_due', 'watch_task_fired'):
                return True
            # 新 etype proactive_nudge_required 必须 fired_via=swm_trigger
            if fired_via != 'swm_trigger':
                return False
        return True

    def _process_event(self, event: Dict) -> bool:
        """处理 1 个 event: 拼 nudge_context + push __NUDGE__."""
        try:
            etype = event.get('etype') or event.get('type') or ''
            handler = self._handler_map.get(etype)
            if handler is None:
                return False
            # 拼 nudge_context
            nctx = handler.extract_fn(event)
            if not nctx or not isinstance(nctx, dict):
                return False
            # push __NUDGE__
            cmd = f"__NUDGE__:{json.dumps(nctx, ensure_ascii=False)}"
            if self.worker_ref is not None and hasattr(self.worker_ref, 'push_command'):
                self.worker_ref.push_command(cmd)
                self._fired_count += 1
                # publish 'swm_trigger_fired' SWM event for observability
                try:
                    from jarvis_utils import get_event_bus as _geb
                    bus = _geb()
                    if bus is not None:
                        bus.publish(
                            etype='swm_trigger_fired',
                            description=f"SWMTrigger pushed {nctx.get('type','unknown')} from {etype}",
                            source='SWMTrigger',
                            salience=0.5,
                            metadata={
                                'origin_etype': etype,
                                'nudge_type': nctx.get('type', ''),
                                'origin_event_id': nctx.get('_swm_trigger_origin', ''),
                                'fired_count_total': self._fired_count,
                            },
                        )
                except Exception:
                    pass
                return True
            return False
        except Exception:
            return False

    def _scan_swm(self) -> int:
        """1 tick: scan SWM events, dedupe + process."""
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return 0
            # use recent_events to fetch (within 5min, salience-filtered)
            within_s = float(self.config.get('tick_interval_s', 1.0)) * 60  # ~1min
            events: List[Dict] = []
            try:
                events = bus.recent_events(
                    within_seconds=within_s,
                    types=set(self._handler_map.keys()),
                ) or []
            except Exception:
                # bus interface 老版本可能不支持 types kwarg
                try:
                    events = bus.recent_events(within_seconds=within_s) or []
                    events = [e for e in events
                              if (e.get('etype') or e.get('type') or '') in self._handler_map]
                except Exception:
                    events = []
            processed = 0
            for ev in events:
                if not self._should_process_event(ev):
                    continue
                key = self._make_event_key(ev)
                if self._is_dedup_recent(key):
                    continue
                ok = self._process_event(ev)
                if ok:
                    self._mark_processed(key)
                    processed += 1
            return processed
        except Exception:
            return 0

    def run(self):
        """daemon loop."""
        # 启动 banner
        try:
            from jarvis_utils import bg_log as _bg
            _bg(f"📡 [SWMTrigger] daemon 启动 (enabled={self.config.get('enabled')}, "
                f"subscribed={list(self._handler_map.keys())})")
        except Exception:
            pass
        # disabled 时 exit (但 thread 实例保留)
        if not self.config.get('enabled', False):
            try:
                from jarvis_utils import bg_log as _bg2
                _bg2(f"💤 [SWMTrigger] disabled, daemon idle (set JARVIS_SWM_TRIGGER=1 启用)")
            except Exception:
                pass
            return
        # 启动护栏 (worker boot 时不立刻 push)
        time.sleep(30)
        while not self._stop.is_set():
            try:
                self._tick_count += 1
                self._scan_swm()
            except Exception:
                pass
            self._stop.wait(self.config.get('tick_interval_s', 1.0))


# ============================================================
# Singleton
# ============================================================

_DEFAULT_TRIGGER: Optional[SWMTrigger] = None
_INIT_LOCK = threading.Lock()


def get_default_trigger(worker_ref: Any = None) -> SWMTrigger:
    """singleton getter. caller passes worker_ref on first call."""
    global _DEFAULT_TRIGGER
    with _INIT_LOCK:
        if _DEFAULT_TRIGGER is None:
            _DEFAULT_TRIGGER = SWMTrigger(worker_ref=worker_ref)
        elif worker_ref is not None and _DEFAULT_TRIGGER.worker_ref is None:
            _DEFAULT_TRIGGER.worker_ref = worker_ref
        return _DEFAULT_TRIGGER


def reset_default_trigger_for_test() -> None:
    global _DEFAULT_TRIGGER
    with _INIT_LOCK:
        if _DEFAULT_TRIGGER is not None:
            _DEFAULT_TRIGGER.stop()
        _DEFAULT_TRIGGER = None


def publish_to_swm_trigger(etype: str, description: str, source: str,
                           nudge_context: Optional[Dict] = None,
                           salience: float = 0.7,
                           extra_metadata: Optional[Dict] = None) -> Optional[str]:
    """便捷函数: sentinel publish event 时给 SWMTrigger handler 看的 metadata.

    Returns: event_id (lineage M1) or None.
    """
    try:
        from jarvis_utils import get_event_bus
        bus = get_event_bus()
        if bus is None:
            return None
        meta: Dict[str, Any] = dict(extra_metadata or {})
        meta['fired_via'] = 'swm_trigger'  # 让 SWMTrigger 接受
        if nudge_context:
            meta['nudge_context'] = nudge_context
        return bus.publish(
            etype=etype,
            description=description[:300],
            source=source,
            salience=salience,
            metadata=meta,
        )
    except Exception:
        return None


# ============================================================
# CLI 兼容 (Sir scripts/swm_trigger_dump.py 后续做)
# ============================================================


def get_status() -> Dict[str, Any]:
    """daemon 当前状态 dump."""
    if _DEFAULT_TRIGGER is None:
        return {'state': 'not_started'}
    t = _DEFAULT_TRIGGER
    return {
        'state': 'running' if t.is_alive() else 'stopped',
        'enabled': t.config.get('enabled'),
        'tick_count': t._tick_count,
        'fired_count': t._fired_count,
        'subscribed': list(t._handler_map.keys()),
        'processed_keys_size': len(t._processed_keys),
    }
