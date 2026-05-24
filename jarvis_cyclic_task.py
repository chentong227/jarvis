#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[P5-fix35-C / 2026-05-23 11:08] Jarvis CyclicTaskStore — 通用循环任务协议.

# 设计原则 (Sir 11:09 真意 + AGENTS 准则 6 三维耦合):

  - **通用** — 不只 reminder, kind 字段开放给主脑: reminder / check / habit_log
    / standup / writing_chunk / stretch / pomodoro / focus_block / ...
  - **持久化** — memory_pool/cyclic_task_protocol.json (准则 6 持久化, 不在 .py)
  - **CLI 可改** — scripts/cyclic_task_dump.py 让 Sir list/cancel/inspect
  - **数据强耦合** — publish SWM cyclic_task_registered/fired/completed 给主脑看
  - **行为弱耦合** — store 只管展开 + 调度, 不决定要不要展开 (主脑决定)
  - **决策集中主脑** — 主脑 emit cyclic_task FAST_CALL organ → store 执行

# 主脑 FAST_CALL 用法:
  <FAST_CALL>{"organ":"cyclic_task","command":"register","params":{
    "task_id": "hydration_2026-05-23",
    "kind": "reminder",
    "description": "每 90 分钟提醒喝 300ml 水",
    "cycle_minutes": 90,
    "start_at": "2026-05-23 14:30",
    "end_at": "2026-05-23 22:00",
    "intent_template": "💧 该喝 ~300ml 水了, Sir"
  }}</FAST_CALL>

  command 支持: register / list / cancel / status

# 内部展开:
  start_at + cycle_minutes 步进到 end_at → N 个 trigger_time → 批量 insert
  TaskMemories (复用 reminder 机制, ChronosSentinel 自动 fire).

# CLI:
  python scripts/cyclic_task_dump.py --list
  python scripts/cyclic_task_dump.py --cancel hydration_2026-05-23
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# ============================================================
# Data
# ============================================================

_PROTOCOL_PATH = os.path.join('memory_pool', 'cyclic_task_protocol.json')


@dataclass
class CyclicTask:
    """单条循环任务定义. 持久化进 cyclic_task_protocol.json."""
    task_id: str
    kind: str                       # reminder / check / habit_log / standup / ...
    description: str
    cycle_minutes: float
    start_iso: str
    end_iso: str
    intent_template: str
    state: str = 'active'           # active / cancelled / completed
    created_ts: float = 0.0
    created_by: str = 'main_brain'  # main_brain / sir_cli / reflector
    fire_ids: List[int] = field(default_factory=list)  # TaskMemories.id 数组
    fire_count: int = 0
    last_fired_at: float = 0.0
    cancelled_at: float = 0.0
    cancelled_reason: str = ''

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# Store
# ============================================================

class CyclicTaskStore:
    """循环任务存储 + 调度. 线程安全, 单例 (get_default_store)."""

    def __init__(self, protocol_path: Optional[str] = None,
                  hippocampus=None):
        self.protocol_path = protocol_path or _PROTOCOL_PATH
        self.hippocampus = hippocampus  # 调 hippocampus 真插 TaskMemories
        self._lock = threading.Lock()
        self.tasks: Dict[str, CyclicTask] = {}
        self._load()

    # ---- persistence ----

    def _load(self) -> None:
        if not os.path.exists(self.protocol_path):
            return
        try:
            with open(self.protocol_path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
        except Exception:
            return
        tasks_data = raw.get('tasks', []) if isinstance(raw, dict) else []
        with self._lock:
            for t in tasks_data:
                try:
                    ct = CyclicTask(**{k: v for k, v in t.items()
                                          if k in CyclicTask.__dataclass_fields__})
                    self.tasks[ct.task_id] = ct
                except Exception:
                    continue

    def _save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.protocol_path), exist_ok=True)
            snapshot = {
                '_comment': '[P5-fix35-C / 2026-05-23] 通用 cyclic_task '
                              '持久化. 主脑 emit FAST_CALL cyclic_task '
                              '→ store 展开成 N 个 reminders. 准则 6 持久化.',
                'tasks': [t.to_dict() for t in self.tasks.values()],
            }
            tmp = self.protocol_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.protocol_path)
            return True
        except Exception:
            return False

    # ---- API ----

    def register(self,
                  task_id: str,
                  kind: str,
                  description: str,
                  cycle_minutes: float,
                  start_at: str,
                  end_at: str,
                  intent_template: str,
                  created_by: str = 'main_brain') -> Dict[str, Any]:
        """注册 + 展开. Returns dict with ok/n_fires/fire_ids/error."""
        # parse times
        try:
            start_dt = _parse_dt(start_at)
            end_dt = _parse_dt(end_at)
        except Exception as e:
            return {'ok': False, 'error': f'time parse fail: {e}'}

        if not start_dt or not end_dt:
            return {'ok': False, 'error': 'invalid start_at/end_at'}
        if end_dt <= start_dt:
            return {'ok': False, 'error': 'end_at must be after start_at'}
        if cycle_minutes <= 0:
            return {'ok': False, 'error': 'cycle_minutes must be > 0'}
        if cycle_minutes < 1:
            return {'ok': False, 'error': 'cycle_minutes < 1 too tight, reject'}

        # 防止 task_id 冲突
        with self._lock:
            existing = self.tasks.get(task_id)
            if existing and existing.state == 'active':
                return {'ok': False, 'error': f"task_id '{task_id}' already active. "
                          f"cancel first or use different id."}

        # expand into individual trigger times
        triggers = []
        cur = start_dt
        delta = timedelta(minutes=float(cycle_minutes))
        # 防 explosion (e.g. 1 分钟 cycle 24 小时 = 1440 个), cap at 50
        max_fires = 50
        while cur <= end_dt and len(triggers) < max_fires:
            triggers.append(cur)
            cur = cur + delta

        if not triggers:
            return {'ok': False, 'error': 'no triggers expanded (start_at past end_at?)'}

        # insert into Hippocampus TaskMemories
        fire_ids: List[int] = []
        if self.hippocampus is not None:
            for trig_dt in triggers:
                rid = self._insert_reminder(
                    intent_template=intent_template,
                    trigger_dt=trig_dt,
                    task_id=task_id,
                    kind=kind,
                )
                if rid:
                    fire_ids.append(rid)

        # persist CyclicTask
        ct = CyclicTask(
            task_id=task_id,
            kind=kind,
            description=description,
            cycle_minutes=float(cycle_minutes),
            start_iso=start_dt.strftime('%Y-%m-%d %H:%M'),
            end_iso=end_dt.strftime('%Y-%m-%d %H:%M'),
            intent_template=intent_template,
            state='active',
            created_ts=time.time(),
            created_by=created_by,
            fire_ids=fire_ids,
        )
        with self._lock:
            self.tasks[task_id] = ct
        self._save()

        # 🆕 [Reshape M4.5 / 2026-05-24] DUAL-WRITE to PromiseLog (单源准备)
        # 老 cyclic_task_protocol.json 仍写, 新 PromiseLog kind='cyclic' 也写一份.
        # M5.A SWM-trigger daemon 切到 PromiseLog 时 0 数据丢失. 失败静默不破老路径.
        try:
            from jarvis_memory_hub import get_default_hub
            _hub = get_default_hub()
            _hub.write_commitment(
                description=description[:300],
                kind='cyclic',
                who_promised='jarvis',
                deadline=end_dt.strftime('%Y-%m-%d %H:%M:%S'),
                trigger_pattern={
                    'kind': 'cycle_minutes',
                    'value': float(cycle_minutes),
                    'start_at': start_dt.strftime('%Y-%m-%d %H:%M'),
                    'end_at': end_dt.strftime('%Y-%m-%d %H:%M'),
                    'intent_template': intent_template[:200],
                    'task_id': task_id,
                    'kind_inner': kind,
                    'created_by': created_by,
                    'n_fires': len(triggers),
                },
                source=f'cyclic_task.register/{kind}',
                jarvis_reply='',
            )
        except Exception:
            pass

        # publish SWM (best effort)
        self._publish_swm(
            etype='cyclic_task_registered',
            description=(
                f"{kind}: {description} | every {cycle_minutes}min from "
                f"{start_dt.strftime('%H:%M')} to {end_dt.strftime('%H:%M')} "
                f"({len(triggers)} fires)"
            ),
            metadata={
                'task_id': task_id, 'kind': kind,
                'n_fires': len(triggers), 'cycle_minutes': cycle_minutes,
                'fire_ids': fire_ids,
            },
        )

        return {
            'ok': True,
            'task_id': task_id,
            'n_fires': len(triggers),
            'fire_ids': fire_ids,
            'first_at': triggers[0].strftime('%Y-%m-%d %H:%M') if triggers else '',
            'last_at': triggers[-1].strftime('%Y-%m-%d %H:%M') if triggers else '',
        }

    def cancel(self, task_id: str, reason: str = '') -> Dict[str, Any]:
        """取消任务 + 删除所有未来 reminder."""
        with self._lock:
            ct = self.tasks.get(task_id)
            if not ct:
                return {'ok': False, 'error': f"task_id '{task_id}' not found"}
            if ct.state != 'active':
                return {'ok': False, 'error': f"task '{task_id}' is {ct.state}, not active"}

        # 删 hippocampus 的 future reminders (用 ID 数组精准删)
        n_removed = 0
        if self.hippocampus is not None and ct.fire_ids:
            for rid in ct.fire_ids:
                if self._consume_or_delete_reminder(rid):
                    n_removed += 1

        with self._lock:
            ct.state = 'cancelled'
            ct.cancelled_at = time.time()
            ct.cancelled_reason = reason[:200]
        self._save()

        self._publish_swm(
            etype='cyclic_task_cancelled',
            description=f"{ct.kind} '{task_id}' cancelled (removed {n_removed} pending fires)",
            metadata={'task_id': task_id, 'n_removed': n_removed, 'reason': reason[:200]},
        )

        return {'ok': True, 'task_id': task_id, 'n_removed': n_removed}

    def list_active(self) -> List[CyclicTask]:
        with self._lock:
            return [t for t in self.tasks.values() if t.state == 'active']

    def list_all(self) -> List[CyclicTask]:
        with self._lock:
            return list(self.tasks.values())

    def get(self, task_id: str) -> Optional[CyclicTask]:
        with self._lock:
            return self.tasks.get(task_id)

    # ---- helpers ----

    def _insert_reminder(self, intent_template: str, trigger_dt: datetime,
                          task_id: str, kind: str) -> Optional[int]:
        """直接 SQL insert TaskMemories. 走 hippocampus 句柄但避免 embedding 调用."""
        try:
            conn = self.hippocampus._get_conn()
            cur = conn.cursor()
            trigger_ts = trigger_dt.timestamp()
            iso_time = trigger_dt.strftime('%H:%M')
            intent = f"{intent_template} [cyclic:{task_id}:{iso_time}]"
            cur.execute('''
                INSERT INTO TaskMemories
                (timestamp, environment, user_intent, macro_goal, execution_summary,
                 raw_actions, semantic_embedding, memory_type, entities_json,
                 is_future_task, trigger_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                time.time(), 'CHAT', intent,
                f"cyclic_{kind}_{task_id}",
                f"cyclic_task fire ({kind}, task_id={task_id})",
                '[]', None, 'REMINDER', '{}',
                1, trigger_ts,
            ))
            rid = cur.lastrowid
            conn.commit()
            conn.close()
            return rid
        except Exception:
            return None

    def _consume_or_delete_reminder(self, reminder_id: int) -> bool:
        try:
            self.hippocampus.consume_reminder(reminder_id)
            return True
        except Exception:
            try:
                conn = self.hippocampus._get_conn()
                cur = conn.cursor()
                cur.execute(
                    "UPDATE TaskMemories SET is_future_task=0 WHERE id=?",
                    (reminder_id,))
                conn.commit()
                conn.close()
                return True
            except Exception:
                return False

    def _publish_swm(self, etype: str, description: str,
                       metadata: Optional[dict] = None) -> None:
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                bus.publish(
                    etype=etype,
                    description=description,
                    source='CyclicTaskStore',
                    salience=0.65,
                    metadata=metadata or {},
                )
        except Exception:
            pass


# ============================================================
# Helpers
# ============================================================

_DT_FORMATS = (
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%d %H:%M',
    '%Y-%m-%dT%H:%M:%S',
    '%Y-%m-%dT%H:%M',
    '%H:%M',  # today HH:MM
)


def _parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    for fmt in _DT_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            # 'HH:MM' → today's date
            if fmt == '%H:%M':
                today = datetime.now().date()
                dt = datetime(today.year, today.month, today.day, dt.hour, dt.minute)
            return dt
        except ValueError:
            continue
    return None


# ============================================================
# Singleton
# ============================================================

_DEFAULT_STORE: Optional[CyclicTaskStore] = None
_INIT_LOCK = threading.Lock()


def get_default_store(hippocampus=None) -> CyclicTaskStore:
    global _DEFAULT_STORE
    with _INIT_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = CyclicTaskStore(hippocampus=hippocampus)
        elif hippocampus is not None and _DEFAULT_STORE.hippocampus is None:
            # lazy bind hippocampus on first availability
            _DEFAULT_STORE.hippocampus = hippocampus
        return _DEFAULT_STORE


def register_default_store(store: CyclicTaskStore) -> None:
    global _DEFAULT_STORE
    with _INIT_LOCK:
        _DEFAULT_STORE = store


def reset_default_store_for_test() -> None:
    global _DEFAULT_STORE
    with _INIT_LOCK:
        _DEFAULT_STORE = None
