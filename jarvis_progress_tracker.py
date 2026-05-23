#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[P5-fix35-D / 2026-05-23 11:30] Jarvis ProgressTracker — 通用数值进度跟踪.

# 设计原则 (Sir 11:29 真测痛点 + AGENTS 准则 6 三维耦合):
  Sir 真痛点: 主脑承诺"我会记到饮水记录上" — 实际系统**没有**饮水记录 store!
  ClaimTracer 抓到 'Noted' unverified 但没治本 (没数据结构可以验).

  - **通用** — 不只 hydration, kind 字段开放: hydration / running / writing /
    pomodoro / pushup / reading / screen_break / steps / ...
  - **持久化** — memory_pool/progress_logs.json (准则 6)
  - **CLI 可改** — scripts/progress_dump.py (准则 6 可调)
  - **数据强耦合** — publish SWM `progress_updated/completed`
  - **行为弱耦合** — tracker 只算 + 持久化, 决策让主脑
  - **决策集中主脑** — 主脑 emit FAST_CALL register/update/cancel/status
  - **联动 cyclic_task** — linked_cyclic_task 字段, fire 时附"余量"

# 主脑 FAST_CALL:
  register:
    <FAST_CALL>{"organ":"progress","command":"register","params":{
      "track_id":"hydration_2026-05-23",
      "kind":"hydration", "label":"今日饮水",
      "target":3000, "unit":"ml",
      "deadline":"2026-05-23 23:59",
      "linked_cyclic_task":"hydration_2026_05_23"  // optional
    }}</FAST_CALL>

  update (Sir 报告进度):
    <FAST_CALL>{"organ":"progress","command":"update","params":{
      "track_id":"hydration_2026-05-23",
      "amount":500, "note":"lunch"
    }}</FAST_CALL>

  status (主脑查):
    <FAST_CALL>{"organ":"progress","command":"status","params":{
      "track_id":"hydration_2026-05-23"
    }}</FAST_CALL>

  list / cancel: 同 cyclic_task 风格.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


_LOG_PATH = os.path.join('memory_pool', 'progress_logs.json')


@dataclass
class ProgressEntry:
    ts: float = 0.0
    amount: float = 0.0
    note: str = ''
    source: str = 'main_brain'

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProgressTrack:
    """单条 progress 记录. 持久化进 progress_logs.json."""
    track_id: str
    kind: str                           # hydration / running / writing / ...
    label: str = ''
    target: float = 0.0
    unit: str = ''
    current: float = 0.0
    deadline_iso: str = ''
    linked_cyclic_task: str = ''
    state: str = 'active'               # active / completed / cancelled
    started_at: float = 0.0
    completed_at: float = 0.0
    cancelled_at: float = 0.0
    cancelled_reason: str = ''
    history: List[ProgressEntry] = field(default_factory=list)
    created_by: str = 'main_brain'

    def to_dict(self) -> dict:
        d = asdict(self)
        # ProgressEntry list 用 dataclass asdict 自动转 — 已 OK
        return d

    @property
    def progress_ratio(self) -> float:
        if self.target <= 0:
            return 0.0
        return min(1.0, self.current / self.target)

    @property
    def remaining(self) -> float:
        return max(0.0, self.target - self.current)

    def render_brief(self) -> str:
        """简短渲染, 主脑可复用. 'X/Y unit (P%), 余 Z unit'."""
        if self.target > 0:
            ratio_pct = int(self.progress_ratio * 100)
            return (f"{self.current:g}/{self.target:g} {self.unit} "
                      f"({ratio_pct}%), 余 {self.remaining:g} {self.unit}")
        else:
            return f"{self.current:g} {self.unit} (无目标)"


# ============================================================
# Store
# ============================================================

class ProgressTrackerStore:
    """进度跟踪. 线程安全, 单例 (get_default_store)."""

    def __init__(self, log_path: Optional[str] = None):
        self.log_path = log_path or _LOG_PATH
        self._lock = threading.Lock()
        self.tracks: Dict[str, ProgressTrack] = {}
        self._load()

    # ---- persistence ----

    def _load(self) -> None:
        if not os.path.exists(self.log_path):
            return
        try:
            with open(self.log_path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
        except Exception:
            return
        tracks_data = raw.get('tracks', {}) if isinstance(raw, dict) else {}
        with self._lock:
            for tid, t in tracks_data.items():
                try:
                    history_raw = t.pop('history', []) if isinstance(t, dict) else []
                    pt = ProgressTrack(**{k: v for k, v in t.items()
                                              if k in ProgressTrack.__dataclass_fields__})
                    for h in history_raw:
                        if isinstance(h, dict):
                            pt.history.append(ProgressEntry(
                                ts=float(h.get('ts', 0)),
                                amount=float(h.get('amount', 0)),
                                note=str(h.get('note', '')),
                                source=str(h.get('source', '')),
                            ))
                    self.tracks[pt.track_id] = pt
                except Exception:
                    continue

    def _save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            snapshot = {
                '_comment': '[P5-fix35-D / 2026-05-23] 通用 progress 持久化. 主脑 emit '
                              'FAST_CALL progress organ → store 累加 + 持久化. 准则 6.',
                'tracks': {tid: t.to_dict()
                              for tid, t in self.tracks.items()},
            }
            tmp = self.log_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.log_path)
            return True
        except Exception:
            return False

    # ---- API ----

    def register(self, *,
                  track_id: str,
                  kind: str,
                  label: str = '',
                  target: float = 0.0,
                  unit: str = '',
                  deadline: str = '',
                  linked_cyclic_task: str = '',
                  created_by: str = 'main_brain') -> Dict[str, Any]:
        if not track_id:
            return {'ok': False, 'error': 'track_id required'}
        try:
            target = float(target) if target else 0.0
        except Exception:
            target = 0.0

        with self._lock:
            existing = self.tracks.get(track_id)
            if existing and existing.state == 'active':
                return {'ok': False,
                          'error': f"track_id '{track_id}' 已 active. cancel 先 OR 改 id."}

        pt = ProgressTrack(
            track_id=track_id, kind=kind, label=label,
            target=target, unit=unit,
            deadline_iso=deadline,
            linked_cyclic_task=linked_cyclic_task,
            state='active',
            started_at=time.time(),
            created_by=created_by,
        )
        with self._lock:
            self.tracks[track_id] = pt
        self._save()
        self._publish_swm(
            etype='progress_registered',
            description=(f"{kind}: target {target}{unit} "
                          f"deadline={deadline or 'none'}"),
            metadata={'track_id': track_id, 'kind': kind,
                       'target': target, 'unit': unit,
                       'linked_cyclic_task': linked_cyclic_task},
        )
        return {'ok': True, 'track_id': track_id,
                  'state': pt.state, 'target': target}

    def update(self, *, track_id: str, amount: float,
                note: str = '', source: str = 'main_brain') -> Dict[str, Any]:
        try:
            amount = float(amount)
        except Exception:
            return {'ok': False, 'error': f'amount 非法: {amount!r}'}

        with self._lock:
            pt = self.tracks.get(track_id)
            if pt is None:
                return {'ok': False, 'error': f"track_id '{track_id}' 不存在 (先 register)"}
            if pt.state != 'active':
                return {'ok': False, 'error': f"track '{track_id}' state={pt.state} (非 active)"}
            old_current = pt.current
            pt.current = max(0.0, pt.current + amount)
            pt.history.append(ProgressEntry(
                ts=time.time(), amount=amount, note=note[:200], source=source,
            ))
            # 自动 completed
            became_complete = False
            if pt.target > 0 and pt.current >= pt.target and pt.state == 'active':
                pt.state = 'completed'
                pt.completed_at = time.time()
                became_complete = True

        self._save()
        self._publish_swm(
            etype='progress_updated',
            description=(f"{pt.kind}: +{amount}{pt.unit} → {pt.render_brief()}"),
            metadata={'track_id': track_id, 'kind': pt.kind,
                       'old_current': old_current, 'new_current': pt.current,
                       'target': pt.target, 'unit': pt.unit,
                       'amount': amount, 'note': note[:200],
                       'progress_ratio': pt.progress_ratio,
                       'remaining': pt.remaining,
                       'became_complete': became_complete},
            salience=0.55 if not became_complete else 0.75,
        )
        # 自动联动 — 完成时 cancel cyclic_task
        cancelled_cycle = ''
        if became_complete and pt.linked_cyclic_task:
            try:
                from jarvis_cyclic_task import get_default_store as _get_ct_store
                ct_store = _get_ct_store()
                r = ct_store.cancel(
                    pt.linked_cyclic_task,
                    reason=f"linked progress {track_id} completed")
                if r.get('ok'):
                    cancelled_cycle = pt.linked_cyclic_task
            except Exception:
                pass

        if became_complete:
            self._publish_swm(
                etype='progress_completed',
                description=(f"🎯 {pt.kind} 完成! {pt.render_brief()}"),
                metadata={'track_id': track_id, 'kind': pt.kind,
                           'cancelled_linked_cycle': cancelled_cycle},
                salience=0.80,
            )

        return {
            'ok': True,
            'track_id': track_id,
            'current': pt.current,
            'target': pt.target,
            'unit': pt.unit,
            'progress_ratio': pt.progress_ratio,
            'remaining': pt.remaining,
            'state': pt.state,
            'became_complete': became_complete,
            'cancelled_linked_cycle': cancelled_cycle,
            'brief': pt.render_brief(),
        }

    def cancel(self, track_id: str, reason: str = '') -> Dict[str, Any]:
        with self._lock:
            pt = self.tracks.get(track_id)
            if pt is None:
                return {'ok': False, 'error': f"track_id '{track_id}' not found"}
            if pt.state != 'active':
                return {'ok': False, 'error': f"track '{track_id}' state={pt.state}, not active"}
            pt.state = 'cancelled'
            pt.cancelled_at = time.time()
            pt.cancelled_reason = reason[:200]

        self._save()
        self._publish_swm(
            etype='progress_cancelled',
            description=f"{pt.kind} '{track_id}' cancelled",
            metadata={'track_id': track_id, 'reason': reason[:200]},
            salience=0.50,
        )
        return {'ok': True, 'track_id': track_id}

    def status(self, track_id: str) -> Dict[str, Any]:
        with self._lock:
            pt = self.tracks.get(track_id)
        if pt is None:
            return {'ok': False, 'error': f"track_id '{track_id}' not found"}
        return {'ok': True,
                  'track_id': track_id,
                  'kind': pt.kind, 'label': pt.label,
                  'target': pt.target, 'unit': pt.unit,
                  'current': pt.current,
                  'progress_ratio': pt.progress_ratio,
                  'remaining': pt.remaining,
                  'state': pt.state,
                  'deadline_iso': pt.deadline_iso,
                  'linked_cyclic_task': pt.linked_cyclic_task,
                  'history_n': len(pt.history),
                  'last_n_entries': [h.to_dict() for h in pt.history[-3:]],
                  'brief': pt.render_brief()}

    def list_active(self) -> List[ProgressTrack]:
        with self._lock:
            return [t for t in self.tracks.values() if t.state == 'active']

    def list_all(self) -> List[ProgressTrack]:
        with self._lock:
            return list(self.tracks.values())

    def get(self, track_id: str) -> Optional[ProgressTrack]:
        with self._lock:
            return self.tracks.get(track_id)

    # ---- helpers ----

    def _publish_swm(self, etype: str, description: str,
                       metadata: Optional[dict] = None,
                       salience: float = 0.55) -> None:
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                bus.publish(
                    etype=etype, description=description,
                    source='ProgressTrackerStore',
                    metadata=metadata or {},
                    salience=salience,
                )
        except Exception:
            pass


# ============================================================
# Singleton
# ============================================================

_DEFAULT_STORE: Optional[ProgressTrackerStore] = None
_INIT_LOCK = threading.Lock()


def get_default_store() -> ProgressTrackerStore:
    global _DEFAULT_STORE
    with _INIT_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = ProgressTrackerStore()
        return _DEFAULT_STORE


def register_default_store(store: ProgressTrackerStore) -> None:
    global _DEFAULT_STORE
    with _INIT_LOCK:
        _DEFAULT_STORE = store


def reset_default_store_for_test() -> None:
    global _DEFAULT_STORE
    with _INIT_LOCK:
        _DEFAULT_STORE = None
