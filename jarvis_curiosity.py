# -*- coding: utf-8 -*-
"""
[P0+20-β.2.9.4 / 2026-05-18] Curiosity Ping — 主动性 D

Sir 长时间一种活动 (同一进程 > 60min + 单一窗口标题) → Jarvis 主动问一个开放
问题让 Sir 短暂跳出工作模式. 1-2 天 1 次低频, 不烦.

设计原则 (准则 6 拒硬编码):
- 不写"Sir, what are you trying to crack?" 这种固定句子
- 给主脑 context (sir 在 X process Y min, window title) + 让主脑自己生成开放问题
- daily cap 严格 (24h 内 ≤ 1 次)
"""

from __future__ import annotations

import json
import threading
import time
from typing import Optional

try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(msg: str) -> None:
        print(msg)


TICK_INTERVAL_S = 300.0           # 5min tick (低频, 不忙)
MIN_DEEP_FOCUS_MIN = 60.0         # ≥60min 同 process 才触发
MAX_SWITCHES_5MIN = 4              # 5min 切窗 ≤4 = 真专注
DAILY_CAP = 1                      # 24h 内 ≤ 1 次
COOLDOWN_AFTER_FIRE_S = 24 * 3600  # 24h


class CuriosityDaemon(threading.Thread):
    """主动性 D — Sir 长时间专注时偶尔问开放问题."""

    def __init__(self, worker, central_nerve=None,
                  tick_interval_s: float = TICK_INTERVAL_S):
        super().__init__(daemon=True, name='CuriosityDaemon')
        self.worker = worker
        self.nerve = central_nerve
        self.tick = tick_interval_s
        self._stop = threading.Event()
        self._last_fire_ts: float = 0.0

    def stop(self) -> None:
        self._stop.set()

    def _should_fire(self) -> Optional[dict]:
        """看 Sir 是否符合 deep_focus 条件. 返回 ctx 或 None."""
        # daily cap
        if time.time() - self._last_fire_ts < COOLDOWN_AFTER_FIRE_S:
            return None
        # 不在 active_conv 时不主动 (避免插话)
        try:
            vt = getattr(self.worker, 'voice_thread', None)
            if vt is not None and getattr(vt, 'in_active_conversation', False):
                return None
            if vt is not None and getattr(vt, '_bypass_speech_count', 0) >= 2:
                return None
        except Exception:
            pass
        # sensor
        try:
            from jarvis_env_probe import PhysicalEnvironmentProbe as P
            snap = P.get_sensor_snapshot() or {}
        except Exception:
            return None
        sess_min = float(snap.get('session_duration_minutes', 0) or 0)
        sw5 = int(snap.get('switch_frequency_5min', 0) or 0)
        cat = snap.get('work_category', '')
        if sess_min < MIN_DEEP_FOCUS_MIN:
            return None
        if sw5 > MAX_SWITCHES_5MIN:
            return None
        if cat in ('AFK', 'Idle'):
            return None
        # 命中
        return {
            'session_min': sess_min,
            'switch_5min': sw5,
            'work_category': cat,
            'window_title': snap.get('window_title', ''),
            'process_name': snap.get('process_name', ''),
        }

    def _dispatch(self, ctx: dict) -> None:
        """走 proactive_care channel 让主脑自己生成开放问题."""
        try:
            directive = (
                f"You are about to make a brief curiosity-driven remark to Sir.\n"
                f"Sir has been deeply focused for {ctx['session_min']:.0f} min in "
                f"{ctx['work_category']} ('{ctx['window_title'][:60]}'), "
                f"with only {ctx['switch_5min']} window switches in last 5 min.\n\n"
                "[STYLE]\n"
                "- Ask ONE genuinely curious open question that invites Sir to step\n"
                "  back from the immediate task (准则 6 — speak in your own voice,\n"
                "  no fixed phrasing).\n"
                "- NOT a check-in ('how's it going?'), NOT a nudge to stop ('take a\n"
                "  break?'). A real question about what he's tackling / why it\n"
                "  matters / what would 'done' look like.\n"
                "- ≤ 20 English words + ZH translation.\n"
                "- If you can't form a genuine question for the specific situation,\n"
                "  output silence_text directive and skip — better silent than fake."
            )
            nudge_ctx = {
                'type': 'proactive_care',
                'channel': 'voice',
                'nudge_directive': directive,
                'concern_id': 'curiosity_ping',
                'source': 'CuriosityDaemon',
                'session_min': ctx['session_min'],
            }
            payload = "__NUDGE__:" + json.dumps(nudge_ctx, ensure_ascii=False)
            self.worker.push_command(payload)
            bg_log(
                f"🤔 [Curiosity] FIRE session={ctx['session_min']:.0f}min "
                f"window='{ctx['window_title'][:50]}'"
            )
            self._last_fire_ts = time.time()
        except Exception as e:
            bg_log(f"⚠️ [Curiosity] dispatch err: {e}")

    def run(self) -> None:
        time.sleep(60)
        bg_log(f"🤔 [CuriosityDaemon] started (tick={self.tick}s, daily cap=1)")
        while not self._stop.is_set():
            try:
                ctx = self._should_fire()
                if ctx:
                    self._dispatch(ctx)
            except Exception as e:
                bg_log(f"⚠️ [CuriosityDaemon] tick err: {e}")
            self._stop.wait(self.tick)


_DEFAULT_DAEMON: Optional[CuriosityDaemon] = None
_LOCK = threading.Lock()


def ensure_curiosity_daemon_started(worker, central_nerve=None) -> None:
    global _DEFAULT_DAEMON
    with _LOCK:
        if _DEFAULT_DAEMON is None and worker is not None:
            _DEFAULT_DAEMON = CuriosityDaemon(worker, central_nerve)
            _DEFAULT_DAEMON.start()
