import time
import json
import os
import re
import hashlib
import threading
import queue
import sqlite3
import numpy as np
import ctypes
from collections import deque, defaultdict
from jarvis_env_probe import PhysicalEnvironmentProbe   # [P0+19-2] 顶部 import, 旧延迟 import 已移除



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
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple


# ============================================================
# [P0+20-beta.1.10 / 2026-05-16] DEAD CODE REMOVED
# ----------------------------------------------------------
# Original line 32-994 contained 9 orphaned class duplicates
# left over from P0+19 split (PromptCache / CorrectionLoop /
# UnifiedMemoryGateway / TaskWorkerPool / Anticipator /
# ContextRouter / ProfileCard / ContentPreferenceTracker /
# SoulRouter). Real implementations live in:
#   - jarvis_memory_core.py (5 classes)
#   - jarvis_routing.py     (4 classes)
# Verified: zero references to jarvis_enhanced.<class> across
# all jarvis_*.py + tests/ + scripts/. Safe to remove.
# Surviving classes below: ProactiveShield, ProactiveCompanion,
# SkillTreeTracker (used by central_nerve.py:97).
# ============================================================

# =========================================================================
# 9. ProactiveShield (JarvisProactiveShield) — 主动守护盾
# =========================================================================
class ProactiveShield(threading.Thread):
    FRUSTRATION_SIGNALS = {
        'rapid_alt_tab': {'window_switches': 12, 'time_window': 300},
        'error_loop': {'same_page_minutes': 5},
        'repeated_edits': {'edit_count': 10, 'time_window': 600},
        'search_spiral': {'similar_searches': 4, 'time_window': 600},
    }

    def __init__(self, central_nerve):
        super().__init__(daemon=True)
        self.jarvis = central_nerve
        self._window_switch_times = deque(maxlen=100)
        self._error_page_times = {}
        self._search_history = deque(maxlen=50)
        self._last_nudge_time = 0
        self._nudge_cooldown = 900
        self._daily_nudge_count = 0
        self._last_reset_day = ""
        self._last_diag_print_time = 0
        self._diag_print_interval = 30

    def run(self):
        time.sleep(15)
        print("🛡️ [ProactiveShield] Shield ready (alt-tab≥12/5min or error≥5min, cooldown=15min, max 4/day)")
        while True:
            try:
                self._scan()
            except Exception as e:
                try:
                    from jarvis_utils import bg_log as _bg
                    _bg(f"[ProactiveShield] scan error: {e}")
                except Exception:
                    pass
            time.sleep(10)

    def _scan(self):
        current_day = time.strftime('%Y-%m-%d')
        if current_day != self._last_reset_day:
            self._daily_nudge_count = 0
            self._last_reset_day = current_day

        now = time.time()
        if now - self._last_nudge_time < self._nudge_cooldown:
            return
        if self._daily_nudge_count >= 4:
            return

        try:
            history = list(PhysicalEnvironmentProbe.window_history)
            if len(history) < 10:
                return

            recent = [e for e in history if now - e['time'] < 300]
            switches = 0
            last_title = None
            for e in sorted(recent, key=lambda x: x['time']):
                if last_title is not None and e.get('title', '') != last_title and e.get('title', ''):
                    switches += 1
                last_title = e.get('title', '')

            error_keywords = ['error', 'exception', 'traceback', 'stack trace', '报错', '错误',
                            'stackoverflow', 'stack overflow', 'stack_over', 'failed', 'failure']
            error_titles = []
            for e in recent:
                title = (e.get('title', '') or '').lower()
                if any(kw in title for kw in error_keywords):
                    error_titles.append(e)

            frustration_detected = False
            frustration_type = ""

            switch_threshold = self.FRUSTRATION_SIGNALS['rapid_alt_tab']['window_switches']
            if switches >= switch_threshold:
                frustration_detected = True
                frustration_type = "rapid_context_switching"

            error_duration_min = 0.0
            if error_titles:
                earliest_error = min(error_titles, key=lambda x: x['time'])
                error_duration_min = (now - earliest_error['time']) / 60
                if error_duration_min >= self.FRUSTRATION_SIGNALS['error_loop']['same_page_minutes']:
                    frustration_detected = True
                    frustration_type = "extended_error_loop"

            # 接近阈值时打印诊断（限频 30s，避免刷屏）
            is_near_switch = switches >= switch_threshold * 0.65
            is_near_error = error_titles and error_duration_min >= 2.0
            if (is_near_switch or is_near_error) and not frustration_detected:
                if now - self._last_diag_print_time > self._diag_print_interval:
                    self._last_diag_print_time = now
                    if is_near_switch:
                        print(f"🛡️ [Shield watching] alt-tab switches={switches}/5min (threshold {switch_threshold})")
                    if is_near_error:
                        try:
                            from jarvis_utils import bg_log as _bg
                            _bg(f"🛡️ [Shield watching] error window for {error_duration_min:.1f}min (threshold 5min)")
                        except Exception:
                            pass

            if frustration_detected:
                self._send_shield_nudge(frustration_type, switches, error_titles)
                self._last_nudge_time = now
                self._daily_nudge_count += 1

        except Exception as e:
            if 'PhysicalEnvironmentProbe' not in str(e):
                print(f"[ProactiveShield] _scan exception: {e}")

    def _send_shield_nudge(self, frustration_type: str, switch_count: int, error_titles: list):
        try:
            PhysicalEnvironmentProbe._shield_alert = {
                'active': True,
                'type': frustration_type,
                'switch_count': switch_count,
                'error_titles': [e.get('title', '')[:80] for e in (error_titles or [])],
                'timestamp': time.time(),
            }
            print(f"\n🛡️ [ProactiveShield] Productivity cliff detected ({frustration_type}), reported to Conductor")
        except Exception:
            pass


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


# =========================================================================
# 10. SkillTreeTracker (JarvisSkillTree) — 技能树追踪
# =========================================================================
class SkillTreeTracker:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.path.join("memory_pool", "skill_tree.db")
        self._skill_cache = {}
        self._last_scan_time = 0
        self._scan_interval = 600
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS SkillNodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_name TEXT NOT NULL UNIQUE,
                category TEXT DEFAULT 'general',
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                total_hours REAL DEFAULT 0,
                streak_days INTEGER DEFAULT 0,
                longest_streak INTEGER DEFAULT 0,
                session_count INTEGER DEFAULT 0,
                level TEXT DEFAULT 'beginner',
                confidence REAL DEFAULT 0.3,
                sources TEXT DEFAULT '[]'
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS SkillSessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_name TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL,
                duration_minutes REAL DEFAULT 0,
                source_window TEXT,
                project_name TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS WeeklySnapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start TEXT NOT NULL,
                snapshot_data TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        ''')
        conn.commit()
        conn.close()

    def tick(self, window_title: str = "", process_name: str = "", project_name: str = ""):
        now = time.time()
        if now - self._last_scan_time < self._scan_interval:
            return
        self._last_scan_time = now

        try:
            window_title = PhysicalEnvironmentProbe.current_window_title
            process_name = PhysicalEnvironmentProbe.current_process_name
            work_category = PhysicalEnvironmentProbe.current_work_category
        except Exception:
            work_category = "General"

        if work_category != "Coding" or not window_title:
            return

        skills = self._extract_skills(window_title, process_name)
        for skill in skills:
            self._record_skill_activity(skill, window_title, project_name)

    def _extract_skills(self, window_title: str, process_name: str) -> list:
        skills = []
        title_lower = window_title.lower()

        skill_patterns = {
            'Python': [r'\bpython\b', r'\.py\b', r'pytorch', r'tensorflow', r'flask', r'django', r'fastapi'],
            'CUDA/GPU': [r'\bcuda\b', r'\bgpu\b', r'\bnvidia\b', r'\bcudnn\b', r'\btensorrt\b'],
            'C++': [r'\bc\+\+\b', r'\.cpp\b', r'\.h\b', r'\.hpp\b', r'\bcmake\b'],
            'JavaScript/TS': [r'\bjavascript\b', r'\btypescript\b', r'\.js\b', r'\.ts\b', r'\bnode\b', r'\breact\b', r'\bvue\b'],
            'SQL/Database': [r'\bsql\b', r'\bdatabase\b', r'\bpostgres\b', r'\bmysql\b', r'\bsqlite\b', r'\bmongodb\b'],
            'Docker/DevOps': [r'\bdocker\b', r'\bkubernetes\b', r'\bk8s\b', r'\bdevops\b', r'\bci/cd\b', r'\bjenkins\b'],
            'Git': [r'\bgit\b', r'\bgithub\b', r'\bgitlab\b', r'\bcommit\b', r'\bbranch\b', r'\bmerge\b'],
            'PyQt/GUI': [r'\bpyqt\b', r'\bqt\b', r'\bgui\b', r'\bpyqt5\b', r'\bqwidget\b', r'\bqpainter\b'],
            'OpenCV/CV': [r'\bopencv\b', r'\bcv2\b', r'\bemgucv\b', r'\bcomputer.vision\b', r'\bimage.process'],
            'Machine Learning': [r'\bml\b', r'\bmachine.learning\b', r'\bdeep.learning\b', r'\bneural\b', r'\btransformer\b'],
            'ASR/Speech': [r'\basr\b', r'\bspeech\b', r'\bvoice\b', r'\btts\b', r'\bstt\b', r'\bfunasr\b', r'\bsensevoice\b'],
            'Audio Processing': [r'\baudio\b', r'\bpyaudio\b', r'\bsoundfile\b', r'\bwav\b', r'\bsound\b'],
            'Windows API': [r'\bwin32\b', r'\bwin32gui\b', r'\bwin32api\b', r'\bwin32con\b', r'\bpycaw\b'],
            'Multithreading': [r'\bthreading\b', r'\bmultithread', r'\bconcurrent\b', r'\bthread\b', r'\basync\b'],
            'LLM/GenAI': [r'\bllm\b', r'\bgemini\b', r'\bgpt\b', r'\bopenai\b', r'\bgenai\b', r'\bprompt\b'],
            'Embedded/Hardware': [r'\bembedded\b', r'\bhardware\b', r'\bmicroscope\b', r'\bscan\b', r'\bcamera\b'],
        }

        for skill_name, patterns in skill_patterns.items():
            for pattern in patterns:
                if re.search(pattern, title_lower):
                    skills.append(skill_name)
                    break

        process_skill_map = {
            'code.exe': ['VS Code', 'Coding'],
            'devenv.exe': ['Visual Studio', 'Coding'],
            'pycharm64.exe': ['PyCharm', 'Python'],
            'idea64.exe': ['IntelliJ', 'Java'],
            'terminal.exe': ['Terminal', 'CLI'],
            'powershell.exe': ['PowerShell', 'Scripting'],
            'cmd.exe': ['Command Prompt', 'CLI'],
        }
        proc_lower = (process_name or '').lower()
        for proc, skills_list in process_skill_map.items():
            if proc in proc_lower:
                for s in skills_list:
                    if s not in skills:
                        skills.append(s)

        return list(set(skills))

    def _record_skill_activity(self, skill_name: str, window_title: str, project_name: str):
        now = time.time()
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                "SELECT id, first_seen, last_seen, total_hours, streak_days, longest_streak, session_count, level, confidence FROM SkillNodes WHERE skill_name = ?",
                (skill_name,)
            )
            row = cursor.fetchone()

            if row:
                skill_id, first_seen, last_seen, total_hours, streak_days, longest_streak, session_count, level, confidence = row

                days_since_last = (now - last_seen) / 86400
                if days_since_last < 1.5:
                    streak_days += 1
                elif days_since_last > 2:
                    streak_days = 1

                longest_streak = max(longest_streak, streak_days)
                session_count += 1
                total_hours += 0.17
                confidence = min(1.0, confidence + 0.01)

                if total_hours > 100:
                    level = 'master'
                elif total_hours > 50:
                    level = 'expert'
                elif total_hours > 20:
                    level = 'advanced'
                elif total_hours > 5:
                    level = 'intermediate'
                elif total_hours > 1:
                    level = 'beginner'

                cursor.execute('''
                    UPDATE SkillNodes SET last_seen = ?, total_hours = ?, streak_days = ?,
                    longest_streak = ?, session_count = ?, level = ?, confidence = ?
                    WHERE id = ?
                ''', (now, round(total_hours, 2), streak_days, longest_streak, session_count, level, confidence, skill_id))
            else:
                cursor.execute('''
                    INSERT INTO SkillNodes (skill_name, category, first_seen, last_seen, total_hours,
                    streak_days, longest_streak, session_count, level, confidence, sources)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (skill_name, 'coding', now, now, 0.17, 1, 1, 1, 'beginner', 0.3, json.dumps([window_title[:100]])))

            cursor.execute('''
                INSERT INTO SkillSessions (skill_name, start_time, duration_minutes, source_window, project_name)
                VALUES (?, ?, ?, ?, ?)
            ''', (skill_name, now, 10, window_title[:200], project_name or ''))

            conn.commit()
            conn.close()
        except Exception:
            pass

    def get_skill_report(self, days: int = 14) -> dict:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cutoff = time.time() - days * 86400
            cursor.execute('''
                SELECT skill_name, total_hours, level, streak_days, session_count, confidence,
                       first_seen, last_seen
                FROM SkillNodes
                WHERE last_seen >= ?
                ORDER BY total_hours DESC
            ''', (cutoff,))
            active_skills = []
            for row in cursor.fetchall():
                name, hours, level, streak, sessions, conf, first, last = row
                active_skills.append({
                    'name': name,
                    'total_hours': round(hours, 1),
                    'level': level,
                    'current_streak_days': streak,
                    'total_sessions': sessions,
                    'confidence': round(conf, 2),
                    'first_seen': time.strftime('%Y-%m-%d', time.localtime(first)),
                    'last_seen': time.strftime('%Y-%m-%d', time.localtime(last)),
                })

            cursor.execute('''
                SELECT skill_name, SUM(duration_minutes) as total_min, COUNT(*) as sessions
                FROM SkillSessions
                WHERE start_time >= ?
                GROUP BY skill_name
                ORDER BY total_min DESC
            ''', (cutoff,))
            recent_activity = []
            for row in cursor.fetchall():
                recent_activity.append({
                    'name': row[0],
                    'minutes': round(row[1], 1),
                    'sessions': row[2]
                })

            conn.close()
            return {
                'active_skills': active_skills,
                'recent_activity': recent_activity,
                'period_days': days,
                'generated_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
        except Exception as e:
            return {'error': str(e), 'active_skills': [], 'recent_activity': []}

    def get_skill_summary_for_prompt(self) -> str:
        report = self.get_skill_report(days=14)
        skills = report.get('active_skills', [])
        if not skills:
            return ""

        parts = ["[SKILL TREE - Sir's recent technical activities]:"]
        for s in skills[:5]:
            trend = "📈" if s.get('current_streak_days', 0) >= 3 else "📊"
            parts.append(
                f"  {trend} {s['name']}: {s['total_hours']}h total, "
                f"Level: {s['level']}, Streak: {s['current_streak_days']} days"
            )

        rising = [s for s in skills if s.get('current_streak_days', 0) >= 5]
        if rising:
            parts.append(f"  🔥 Rising skills: {', '.join(s['name'] for s in rising[:3])}")

        return "\n".join(parts)

    def generate_weekly_snapshot(self):
        try:
            week_start = time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400 * 7))
            report = self.get_skill_report(days=7)

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO WeeklySnapshots (week_start, snapshot_data, created_at)
                VALUES (?, ?, ?)
            ''', (week_start, json.dumps(report, ensure_ascii=False), time.time()))
            conn.commit()
            conn.close()
        except Exception:
            pass


# =========================================================================
# 11. SoulRouter — 灵魂路由器 (轻量级)
# =========================================================================
class SoulRouter:
    def __init__(self, profile: dict = None):
        self.profile = profile or {}
        self._tag_index = {}

    def route(self, user_input: str) -> list:
        tags = []
        input_lower = (user_input or '').lower()

        if any(kw in input_lower for kw in ['project', '项目', 'working on', 'code', '编程']):
            tags.append('projects')

        if any(kw in input_lower for kw in ['joke', 'funny', 'remember', '笑话', '记得', '上次']):
            tags.append('inside_jokes')

        if any(kw in input_lower for kw in ['achievement', 'milestone', '里程碑', '完成', 'built']):
            tags.append('milestones')

        if any(kw in input_lower for kw in ['skill', 'learning', 'progress', '技能', '学习', '进步']):
            tags.append('progression')

        return tags if tags else ['general']