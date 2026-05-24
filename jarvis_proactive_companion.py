# -*- coding: utf-8 -*-
"""[Reshape M3.E / 2026-05-24] ProactiveCompanion 主动伴随 — 拆自 jarvis_enhanced.py.

morning_briefing / breath_check / work_switch_nudge 三类时间分布事件源头.
通过 PhysicalEnvironmentProbe._companion_alert dict 下发给 Conductor 处理.

🆕 [Reshape M3.E] 单 class 独立 file. jarvis_enhanced.py re-export 兼容老 caller.
"""
import time
import ctypes
import threading

from jarvis_env_probe import PhysicalEnvironmentProbe


def get_user_idle_seconds() -> float:
    """Windows API: 返回用户最后一次键鼠操作距今的秒数"""
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return millis / 1000.0
    except Exception:
        pass
    return 0.0


class ProactiveCompanion(threading.Thread):
    def __init__(self, central_nerve):
        super().__init__(daemon=True)
        self.jarvis = central_nerve
        self._last_breath_time = 0
        self._breath_interval = 10800
        self._morning_done_today = False
        self._morning_reset_day = ""
        self._last_work_category = "Idle"
        self._last_switch_nudge = 0
        self._switch_cooldown = 3600
        self._last_user_interaction = 0

    def run(self):
        time.sleep(60)
        print("💫 [ProactiveCompanion] Companion engine ready — breath light/morning brief/switch detection active...")
        while True:
            try:
                self._tick()
            except Exception as e:
                try:
                    from jarvis_utils import bg_log as _bg
                    _bg(f"⚠️ [ProactiveCompanion] Scan error: {e}")
                except Exception:
                    pass
            time.sleep(60)

    def _tick(self):
        now = time.time()
        current_hour = int(time.strftime('%H'))
        current_day = time.strftime('%Y-%m-%d')

        if hasattr(self.jarvis, 'voice_thread'):
            self._last_user_interaction = self.jarvis.voice_thread.last_user_speech_time

        if current_day != self._morning_reset_day:
            self._morning_done_today = False
            self._morning_reset_day = current_day

        user_away = get_user_idle_seconds() > 120

        if not self._morning_done_today and 6 <= current_hour < 11:
            if not user_away:
                idle_minutes = (now - self._last_user_interaction) / 60
                if idle_minutes < 5:
                    self._send_morning_briefing()
                    self._morning_done_today = True

        if 9 <= current_hour < 23:
            time_since_breath = now - self._last_breath_time
            if time_since_breath > self._breath_interval:
                if not user_away:
                    idle_minutes = (now - self._last_user_interaction) / 60
                    if idle_minutes > 30:
                        self._send_breath_check()
                        self._last_breath_time = now
                        import random
                        self._breath_interval = 10800 + random.randint(-1800, 1800)

        try:
            current_category = PhysicalEnvironmentProbe.current_work_category
        except Exception:
            current_category = "Idle"

        if current_category != self._last_work_category:
            prev = self._last_work_category
            self._last_work_category = current_category

            if prev in ('Coding', 'General') and current_category in ('Media',):
                if now - self._last_switch_nudge > self._switch_cooldown:
                    if not user_away:
                        self._send_switch_nudge(prev, current_category)
                        self._last_switch_nudge = now

    def _send_morning_briefing(self):
        try:
            current_hour = int(time.strftime('%H'))
            PhysicalEnvironmentProbe._companion_alert = {
                'active': True,
                'type': 'morning_greeting',
                'hour': current_hour,
                'timestamp': time.time(),
            }
            print(f"\n🌅 [ProactiveCompanion] Morning event reported to Conductor")
        except Exception as e:
            print(f"⚠️ [MorningBrief] Report failed: {e}")

    def _send_breath_check(self):
        try:
            current_hour = int(time.strftime('%H'))
            try:
                work_cat = PhysicalEnvironmentProbe.current_work_category
            except Exception:
                work_cat = "General"
            PhysicalEnvironmentProbe._companion_alert = {
                'active': True,
                'type': 'breath_check',
                'hour': current_hour,
                'work_category': work_cat,
                'timestamp': time.time(),
            }
            print(f"\n🫁 [ProactiveCompanion] Breath light event reported to Conductor")
        except Exception as e:
            print(f"⚠️ [BreathLight] Report failed: {e}")

    def _send_switch_nudge(self, from_cat: str, to_cat: str):
        try:
            PhysicalEnvironmentProbe._companion_alert = {
                'active': True,
                'type': 'work_switch',
                'from_category': from_cat,
                'to_category': to_cat,
                'timestamp': time.time(),
            }
            print(f"\n🔄 [ProactiveCompanion] Work switch event reported to Conductor ({from_cat} → {to_cat})")
        except Exception as e:
            print(f"⚠️ [WorkSwitch] Report failed: {e}")
