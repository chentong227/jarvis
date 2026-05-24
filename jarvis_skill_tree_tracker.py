# -*- coding: utf-8 -*-
"""[Reshape M3.E / 2026-05-24] SkillTreeTracker — 拆自 jarvis_enhanced.py.

SQLite 持久化 Sir 的 coding 技能 (Python / CUDA / C++ / TS / SQL ...) 时长 + 等级.
通过 PhysicalEnvironmentProbe.current_work_category == 'Coding' 触发记录.

🆕 [Reshape M3.E] 单 class 独立 file. jarvis_enhanced.py re-export 兼容老 caller.
"""
import os
import re
import json
import time
import sqlite3

from jarvis_env_probe import PhysicalEnvironmentProbe


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
