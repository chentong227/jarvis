# -*- coding: utf-8 -*-
"""[β.5.43-A / 2026-05-20] Jarvis State Tracker — HUD 状态条 + SWM publish.

Sir 17:10 真理: "人机交互的顶尖地基" — Sir 不知 Jarvis 在 idle / thinking / speaking
/ listening / focused 哪种状态. Iron Man HUD 类型状态可视化.

设计:
  - 单例 JarvisStateTracker
  - 6 状态: ready / thinking / speaking / listening / focused / error
  - state change 立刻 publish 'jarvis_state' 到 SWM (让主脑也知自己状态)
  - UI subscribe (subtitle_queue 加 ('jarvis_state', state) 消息) 渲染顶 badge
  - 不影响 TTFT (state change ms 级 + 异步 publish)

state semantics:
  - ready: idle, 等 Sir wake
  - thinking: LLM streaming 中, 还没出 TTS token
  - speaking: TTS 播放中 (含未播完的 audio frame)
  - listening: Sir 声波 detected, ASR 累积中
  - focused: focus_lock 30s 内 (Sir 短回应不用 wake)
  - error: 某 sensor / daemon 异常 (β.5.43-F selfheal 配合)

主脑用法: SWM 'jarvis_state' 让主脑感知自己当前在啥状态 — e.g. 主脑 reply 时
若 state=speaking (老 reply 没说完) → 主脑可决定是否抢话.

test: tests/_test_p0_plus_20_beta543_state_tracker.py
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional


# 6 个有效状态
STATE_READY = 'ready'
STATE_THINKING = 'thinking'
STATE_SPEAKING = 'speaking'
STATE_LISTENING = 'listening'
STATE_FOCUSED = 'focused'
STATE_ERROR = 'error'

ALL_STATES = (STATE_READY, STATE_THINKING, STATE_SPEAKING,
              STATE_LISTENING, STATE_FOCUSED, STATE_ERROR)

# 状态优先级 (重要度) — 同时多个 transition 时按 max 取
STATE_PRIORITY = {
    STATE_ERROR: 100,
    STATE_THINKING: 60,
    STATE_SPEAKING: 50,
    STATE_LISTENING: 40,
    STATE_FOCUSED: 30,
    STATE_READY: 10,
}

# emoji + 颜色 (UI 渲染用)
STATE_DISPLAY = {
    STATE_READY:     {'emoji': '🟢', 'color': 'green', 'label_en': 'Ready', 'label_zh': '待命'},
    STATE_THINKING:  {'emoji': '🔵', 'color': 'blue', 'label_en': 'Thinking', 'label_zh': '思考中'},
    STATE_SPEAKING:  {'emoji': '🟡', 'color': 'yellow', 'label_en': 'Speaking', 'label_zh': '回应中'},
    STATE_LISTENING: {'emoji': '🟠', 'color': 'orange', 'label_en': 'Listening', 'label_zh': '聆听中'},
    STATE_FOCUSED:   {'emoji': '🟣', 'color': 'purple', 'label_en': 'Focused', 'label_zh': '专注锁'},
    STATE_ERROR:     {'emoji': '🔴', 'color': 'red', 'label_en': 'Error', 'label_zh': '异常'},
}


class JarvisStateTracker:
    """单例 — 跟踪 Jarvis 全局 state, publish SWM + UI.

    用法:
        tracker = get_state_tracker()
        tracker.set_state(STATE_THINKING, reason='llm_stream_started')
        # ... LLM done ...
        tracker.set_state(STATE_SPEAKING, reason='tts_started')
        # ... TTS done ...
        tracker.set_state(STATE_READY, reason='turn_complete')
    """

    def __init__(self, event_bus: Any = None, subtitle_queue: Any = None):
        self._lock = threading.Lock()
        self._state = STATE_READY
        self._reason = 'init'
        self._since_ts = time.time()
        self._event_bus = event_bus
        self._subtitle_queue = subtitle_queue
        self._n_transitions = 0
        self._history: list = []  # 最近 20 次 transition

    def attach_event_bus(self, bus: Any) -> None:
        with self._lock:
            self._event_bus = bus

    def attach_subtitle_queue(self, q: Any) -> None:
        with self._lock:
            self._subtitle_queue = q

    def get_state(self) -> str:
        return self._state

    def get_age_seconds(self) -> float:
        return time.time() - self._since_ts

    def get_snapshot(self) -> dict:
        with self._lock:
            return {
                'state': self._state,
                'reason': self._reason,
                'since_ts': self._since_ts,
                'age_seconds': time.time() - self._since_ts,
                'n_transitions': self._n_transitions,
                'display': STATE_DISPLAY.get(self._state, STATE_DISPLAY[STATE_READY]),
            }

    def set_state(self, new_state: str, reason: str = '') -> bool:
        """切换状态. 同状态重复 set 不做事. Returns: 是否实际 transition."""
        if new_state not in ALL_STATES:
            return False
        with self._lock:
            if new_state == self._state:
                # 同 state, 更新 reason 但不 publish
                self._reason = reason or self._reason
                return False
            old_state = self._state
            self._state = new_state
            self._reason = reason
            self._since_ts = time.time()
            self._n_transitions += 1
            self._history.append({
                'ts': self._since_ts,
                'from': old_state,
                'to': new_state,
                'reason': reason,
            })
            if len(self._history) > 20:
                self._history = self._history[-20:]

        # publish 到 SWM (在 lock 外, 避免 deadlock)
        self._publish_swm(old_state, new_state, reason)
        # emit 到 subtitle_queue (UI 渲染状态条)
        self._emit_to_ui(new_state, reason)
        return True

    def _publish_swm(self, old_state: str, new_state: str, reason: str) -> None:
        # bg_log (Sir 在终端能看到 state 变化)
        try:
            from jarvis_utils import bg_log
            display = STATE_DISPLAY.get(new_state, STATE_DISPLAY[STATE_READY])
            bg_log(
                f"{display['emoji']} [JarvisState] {old_state} → {new_state} "
                f"({reason}) | {display['label_en']}"
            )
        except Exception:
            pass

        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(
                etype='jarvis_state',
                description=f"{old_state} → {new_state} ({reason})",
                source='JarvisStateTracker',
                metadata={
                    'old_state': old_state,
                    'new_state': new_state,
                    'reason': reason,
                    'ts': time.time(),
                },
                salience=0.45 if new_state == STATE_ERROR else 0.30,
                ttl=120.0,
            )
        except Exception:
            pass

    def _emit_to_ui(self, new_state: str, reason: str) -> None:
        if self._subtitle_queue is None:
            return
        try:
            display = STATE_DISPLAY.get(new_state, STATE_DISPLAY[STATE_READY])
            payload = {
                'state': new_state,
                'reason': reason,
                **display,
            }
            self._subtitle_queue.put(('jarvis_state', payload))
        except Exception:
            pass

    def get_recent_history(self, n: int = 10) -> list:
        with self._lock:
            return list(self._history[-n:])


# Singleton
_TRACKER: Optional[JarvisStateTracker] = None
_LOCK = threading.Lock()


def get_state_tracker(event_bus: Any = None,
                       subtitle_queue: Any = None) -> JarvisStateTracker:
    """获取全局 tracker. 第一次调用 attach bus + queue."""
    global _TRACKER
    with _LOCK:
        if _TRACKER is None:
            _TRACKER = JarvisStateTracker(event_bus, subtitle_queue)
        else:
            if event_bus is not None and _TRACKER._event_bus is None:
                _TRACKER.attach_event_bus(event_bus)
            if subtitle_queue is not None and _TRACKER._subtitle_queue is None:
                _TRACKER.attach_subtitle_queue(subtitle_queue)
        return _TRACKER


# Convenience module-level setters (for hot paths who don't want to call get_state_tracker each time)
def set_state(new_state: str, reason: str = '') -> bool:
    t = get_state_tracker()
    return t.set_state(new_state, reason)


def get_state() -> str:
    t = get_state_tracker()
    return t.get_state()


# Register etype + salience defaults to ConversationEventBus
def _register_etype_defaults():
    try:
        from jarvis_utils import ConversationEventBus
        if 'jarvis_state' not in ConversationEventBus.DEFAULT_TTL:
            ConversationEventBus.DEFAULT_TTL['jarvis_state'] = 120
        if 'jarvis_state' not in ConversationEventBus.DEFAULT_SALIENCE:
            ConversationEventBus.DEFAULT_SALIENCE['jarvis_state'] = 0.30
    except Exception:
        pass


_register_etype_defaults()
