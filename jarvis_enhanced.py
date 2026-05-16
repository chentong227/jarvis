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

# =========================================================================
# 1. PromptCache — 分层 Prompt 缓存引擎
# =========================================================================
class PromptCache:
    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()

    def get_or_build(self, key: str, builder, ttl: float = 3600.0) -> str:
        with self._lock:
            entry = self._cache.get(key)
            if entry and time.time() - entry['time'] < ttl:
                return entry['value']
        value = builder()
        with self._lock:
            self._cache[key] = {'value': value, 'time': time.time()}
            if len(self._cache) > 50:
                oldest = sorted(self._cache.items(), key=lambda x: x[1]['time'])[:10]
                for k, _ in oldest:
                    del self._cache[k]
        return value

    def invalidate(self, key: str = None):
        with self._lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()


# =========================================================================
# 2. CorrectionLoop — 纠错闭环学习引擎
# =========================================================================
class CorrectionLoop:
    def __init__(self, central_nerve):
        self.jarvis = central_nerve
        self.db_path = os.path.join("memory_pool", "correction_memory.db")
        self._pending_user_input = None
        self._pending_jarvis_response = None
        self._correction_patterns = [
            (r'\b(no[,.\s]*i\s+meant?|not\s+that|not\s+what\s+i\s+meant?|that\'?s\s+not\s+right|that\'?s\s+wrong)\b', 0.9),
            (r'\b(不对|不是|错了|搞错了|不是这个|不是这样|你理解错了|你没听懂|不是这个意思)\b', 0.9),
            (r'\b(correct|actually|i\s+said|i\s+asked|i\s+wanted|what\s+i\s+meant?)\b', 0.7),
            (r'\b(应该是|我是说|我要的是|我要查|我是想问|重新|再来)\b', 0.7),
            (r'\b(wrong|incorrect|mistake|error|misunderstanding)\b', 0.6),
            (r'\b(错了|不对|不是|重新|再查|再搜)\b', 0.6),
        ]
        self._style_signals = [
            (r'\b(too\s+formal|too\s+stiff|too\s+ robotic|be\s+more\s+natural|be\s+more\s+casual|relax)\b', 'more_casual'),
            (r'\b(too\s+casual|too\s+informal|be\s+more\s+professional|be\s+more\s+formal)\b', 'more_formal'),
            (r'\b(too\s+long|too\s+verbose|too\s+wordy|shorter|brief|concise|get\s+to\s+the\s+point)\b', 'shorter'),
            (r'\b(too\s+short|more\s+detail|elaborate|explain\s+more|go\s+deeper)\b', 'more_detail'),
            (r'\b(太正式|太僵硬|太啰嗦|太长了|简短|简洁|直接|别废话)\b', 'shorter'),
            (r'\b(太随便|太短了|详细|多说|展开)\b', 'more_detail'),
        ]
        self._style_adjustments = defaultdict(float)
        self._style_decay = 0.95
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS CorrectionMemory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                trigger_context TEXT NOT NULL,
                wrong_response TEXT NOT NULL,
                correction TEXT NOT NULL,
                context_embedding BLOB,
                source_module TEXT DEFAULT 'chat',
                confidence REAL DEFAULT 1.0,
                times_recalled INTEGER DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS StyleFeedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                style_direction TEXT NOT NULL,
                trigger_context TEXT,
                weight REAL DEFAULT 1.0
            )
        ''')
        conn.commit()
        conn.close()

    def on_user_input(self, user_text: str):
        self._pending_user_input = user_text

    def on_jarvis_response(self, jarvis_text: str):
        self._pending_jarvis_response = jarvis_text

    def detect_and_learn(self, user_text: str, jarvis_text: str = None) -> Optional[dict]:
        if not user_text:
            return None

        user_lower = user_text.lower()

        for pattern, confidence in self._correction_patterns:
            if re.search(pattern, user_lower):
                correction_data = self._extract_correction(user_text, jarvis_text, confidence)
                if correction_data:
                    self._store_correction(correction_data)
                    return correction_data

        for pattern, direction in self._style_signals:
            if re.search(pattern, user_lower):
                self._style_adjustments[direction] += 0.3
                self._store_style_feedback(direction, user_text)
                self._decay_styles()
                return {'type': 'style', 'direction': direction}

        return None

    def _extract_correction(self, user_text: str, jarvis_text: str, confidence: float) -> Optional[dict]:
        stm = getattr(self.jarvis, 'short_term_memory', [])
        trigger_context = ""
        if stm:
            recent = stm[-3:]
            trigger_context = " | ".join([f"Q: {m.get('user', '')} A: {m.get('jarvis', '')}" for m in recent])

        wrong_response = jarvis_text or (stm[-1].get('jarvis', '') if stm else "")

        return {
            'trigger_context': trigger_context[:500],
            'wrong_response': wrong_response[:500],
            'correction': user_text[:500],
            'confidence': confidence,
            'source_module': 'chat'
        }

    def _store_correction(self, data: dict):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO CorrectionMemory
                (timestamp, trigger_context, wrong_response, correction, source_module, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                time.time(),
                data['trigger_context'],
                data['wrong_response'],
                data['correction'],
                data.get('source_module', 'chat'),
                data.get('confidence', 1.0)
            ))
            conn.commit()
            conn.close()
            print(f"   📝 [CorrectionLoop] Correction case recorded (confidence: {data.get('confidence', 1.0):.0%})")
        except Exception as e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"   ⚠️ [CorrectionLoop] Storage error: {e}")
            except Exception:
                pass

    def _store_style_feedback(self, direction: str, context: str):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO StyleFeedback (timestamp, style_direction, trigger_context)
                VALUES (?, ?, ?)
            ''', (time.time(), direction, context[:200]))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _decay_styles(self):
        for k in list(self._style_adjustments.keys()):
            self._style_adjustments[k] *= self._style_decay
            if self._style_adjustments[k] < 0.05:
                del self._style_adjustments[k]

    def get_correction_context(self, current_input: str) -> str:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT trigger_context, wrong_response, correction, confidence, times_recalled
                FROM CorrectionMemory
                ORDER BY timestamp DESC LIMIT 10
            ''')
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return ""

            relevant = []
            for row in rows:
                trigger, wrong, correction, conf, recalled = row
                if any(kw in (trigger or "").lower() for kw in current_input.lower().split()[:5]):
                    relevant.append(row)
                elif any(kw in current_input.lower() for kw in (correction or "").lower().split()[:3]):
                    relevant.append(row)

            if not relevant:
                relevant = rows[:3]

            parts = ["[LEARNED CORRECTIONS - Sir has corrected similar situations before]:"]
            for trigger, wrong, correction, conf, recalled in relevant[:3]:
                parts.append(f"  - When Jarvis said: \"{wrong[:80]}\"")
                parts.append(f"    Sir corrected: \"{correction[:80]}\"")
                parts.append(f"    Context: {trigger[:100]}")

            cursor = conn.cursor()
            for row in relevant[:3]:
                cursor.execute(
                    "UPDATE CorrectionMemory SET times_recalled = times_recalled + 1 WHERE trigger_context = ?",
                    (row[0],)
                )
            conn.commit()
            conn.close()

            return "\n".join(parts)
        except Exception:
            return ""

    def get_style_adjustment(self) -> str:
        self._decay_styles()
        if not self._style_adjustments:
            return ""

        dominant = max(self._style_adjustments, key=self._style_adjustments.get)
        strength = self._style_adjustments[dominant]

        if strength < 0.15:
            return ""

        adjustments = {
            'more_casual': "Sir has indicated he prefers a more natural, conversational tone. Relax the formality slightly.",
            'more_formal': "Sir has indicated he prefers a more professional tone. Be more formal and precise.",
            'shorter': "Sir has indicated he prefers shorter responses. Be concise — get to the point quickly.",
            'more_detail': "Sir has indicated he wants more detailed responses. Elaborate when appropriate.",
        }

        return f"[STYLE ADJUSTMENT (confidence: {strength:.0%})]: {adjustments.get(dominant, '')}"

    def get_stats(self) -> dict:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM CorrectionMemory")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM CorrectionMemory WHERE timestamp > ?", (time.time() - 86400,))
            today = cursor.fetchone()[0]
            conn.close()
            return {'total_corrections': total, 'corrections_today': today, 'active_styles': dict(self._style_adjustments)}
        except Exception:
            return {'total_corrections': 0, 'corrections_today': 0, 'active_styles': {}}


# =========================================================================
# 3. UnifiedMemoryGateway — 统一记忆网关
# =========================================================================
class UnifiedMemoryGateway:
    def __init__(self, central_nerve):
        self.jarvis = central_nerve

    def query(self, text: str, current_context: dict = None, top_k: int = 5) -> list:
        results = []

        results += self._query_stm(text, weight=0.30)
        results += self._query_ltm(text, weight=0.25)
        results += self._query_profile(text, weight=0.15)
        results += self._query_ledger(text, weight=0.15)
        results += self._query_causal(text, weight=0.15)

        results = self._deduplicate(results)
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:top_k]

    def _query_stm(self, text: str, weight: float) -> list:
        results = []
        stm = getattr(self.jarvis, 'short_term_memory', [])
        if not stm:
            return results

        query_lower = text.lower()
        query_words = set(query_lower.split())

        for i, entry in enumerate(stm):
            user_text = (entry.get('user', '') or '').lower()
            jarvis_text = (entry.get('jarvis', '') or '').lower()
            combined = user_text + " " + jarvis_text

            word_overlap = len(query_words & set(combined.split()))
            recency = (i + 1) / len(stm)
            importance = getattr(self.jarvis, '_stm_importance_scores', {}).get(i, 0.5)

            score = (word_overlap * 0.4 + recency * 0.3 + importance * 0.3) * weight

            if score > 0.05:
                results.append({
                    'source': 'stm',
                    'content': f"Q: {entry.get('user', '')} → A: {entry.get('jarvis', '')}",
                    'score': score,
                    'timestamp': time.time() - (len(stm) - i) * 60,
                    'metadata': {'index': i}
                })

        return results

    def _query_ltm(self, text: str, weight: float) -> list:
        results = []
        try:
            hippocampus = getattr(self.jarvis, 'hippocampus', None)
            if not hippocampus:
                return results

            memories = hippocampus.search_memory(
                getattr(self.jarvis, 'gemini_key', None),
                text,
                top_k=5
            )

            for mem in memories:
                score = mem.get('similarity', 0.3) * weight
                results.append({
                    'source': 'ltm',
                    'content': f"[{mem.get('environment', '')}] {mem.get('intent', '')} → {mem.get('summary', '')}",
                    'score': score,
                    'timestamp': mem.get('timestamp', 0),
                    'metadata': {'id': mem.get('id'), 'similarity': mem.get('similarity', 0)}
                })
        except Exception:
            pass

        return results

    def _query_profile(self, text: str, weight: float) -> list:
        results = []
        try:
            profile_file = os.path.join("jarvis_config", "sir_profile.json")
            if not os.path.exists(profile_file):
                return results

            with open(profile_file, 'r', encoding='utf-8') as f:
                profile = json.load(f)

            query_lower = text.lower()

            for key in ['active_projects', 'skill_domains', 'significant_milestones']:
                items = profile.get(key, [])
                if isinstance(items, list):
                    for item in items:
                        item_str = str(item).lower()
                        overlap = len(set(query_lower.split()) & set(item_str.split()))
                        if overlap > 0:
                            score = (overlap / max(len(query_lower.split()), 1)) * weight
                            results.append({
                                'source': 'profile',
                                'content': f"[{key}] {item}",
                                'score': score,
                                'timestamp': time.time(),
                                'metadata': {'profile_key': key}
                            })
        except Exception:
            pass

        return results

    def _query_ledger(self, text: str, weight: float) -> list:
        results = []
        try:
            status_ledger = getattr(self.jarvis, 'status_ledger', None)
            if not status_ledger:
                return results

            ledger = status_ledger.get_instant_ledger()
            query_lower = text.lower()

            relevant_fields = ['software_and_content', 'recent_dialogue_topic', 'human_cognitive_load']
            for field in relevant_fields:
                value = str(ledger.get(field, '')).lower()
                if value and any(w in value for w in query_lower.split()[:3]):
                    results.append({
                        'source': 'ledger',
                        'content': f"[{field}] {ledger.get(field, '')}",
                        'score': 0.3 * weight,
                        'timestamp': time.time(),
                        'metadata': {'field': field}
                    })
        except Exception:
            pass

        return results

    def _query_causal(self, text: str, weight: float) -> list:
        results = []
        try:
            causal_chain = getattr(self.jarvis, 'causal_chain', None)
            if not causal_chain:
                return results

            patterns = causal_chain.detect_patterns()
            query_lower = text.lower()

            for pattern in patterns:
                pattern_lower = pattern.lower()
                overlap = len(set(query_lower.split()) & set(pattern_lower.split()))
                if overlap > 0:
                    results.append({
                        'source': 'causal',
                        'content': pattern,
                        'score': 0.2 * weight,
                        'timestamp': time.time(),
                        'metadata': {}
                    })
        except Exception:
            pass

        return results

    def _deduplicate(self, results: list) -> list:
        seen = set()
        deduped = []
        for r in sorted(results, key=lambda x: x['score'], reverse=True):
            key = hashlib.md5(r['content'][:100].encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        return deduped

    def to_prompt_block(self, query_text: str, top_k: int = 3) -> str:
        results = self.query(query_text, top_k=top_k)
        if not results:
            return ""

        parts = ["[UNIFIED MEMORY - Cross-source relevant context]:"]
        for r in results:
            source_label = {'stm': '📝 Recent', 'ltm': '📦 Archive', 'profile': '👤 Profile',
                          'ledger': '📊 Status', 'causal': '🔗 Pattern'}.get(r['source'], r['source'])
            parts.append(f"  {source_label}: {r['content'][:150]}")

        return "\n".join(parts)


# =========================================================================
# 4. TaskWorkerPool — 并发任务执行池
# =========================================================================
class TaskWorkerPool:
    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers
        self._active_tasks = {}
        self._task_counter = 0
        self._lock = threading.Lock()
        self._result_queue = queue.Queue()
        self._semaphore = threading.BoundedSemaphore(max_workers)

    def submit(self, task_id: str, func, *args, **kwargs) -> str:
        with self._lock:
            self._task_counter += 1
            internal_id = f"{task_id}_{self._task_counter}"

        thread = threading.Thread(
            target=self._worker,
            args=(internal_id, func, args, kwargs),
            daemon=True
        )

        with self._lock:
            self._active_tasks[internal_id] = {
                'status': 'pending',
                'thread': thread,
                'start_time': time.time()
            }

        thread.start()
        return internal_id

    def _worker(self, task_id: str, func, args, kwargs):
        acquired = self._semaphore.acquire(timeout=30)
        if not acquired:
            with self._lock:
                if task_id in self._active_tasks:
                    self._active_tasks[task_id]['status'] = 'timeout'
            return

        try:
            with self._lock:
                if task_id in self._active_tasks:
                    self._active_tasks[task_id]['status'] = 'running'

            result = func(*args, **kwargs)

            with self._lock:
                if task_id in self._active_tasks:
                    self._active_tasks[task_id]['status'] = 'completed'
                    self._active_tasks[task_id]['result'] = result
                    self._active_tasks[task_id]['end_time'] = time.time()

            self._result_queue.put((task_id, result))
        except Exception as e:
            with self._lock:
                if task_id in self._active_tasks:
                    self._active_tasks[task_id]['status'] = 'failed'
                    self._active_tasks[task_id]['error'] = str(e)
        finally:
            self._semaphore.release()

    def get_result(self, task_id: str, timeout: float = 0) -> Optional[Any]:
        try:
            tid, result = self._result_queue.get(timeout=timeout if timeout > 0 else 0.1)
            if tid == task_id:
                return result
            self._result_queue.put((tid, result))
        except queue.Empty:
            pass
        return None

    def get_status(self, task_id: str) -> dict:
        with self._lock:
            if task_id in self._active_tasks:
                return dict(self._active_tasks[task_id])
        return {'status': 'unknown'}

    def get_active_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._active_tasks.values() if t['status'] in ('pending', 'running'))

    def cleanup(self, max_age: float = 3600):
        now = time.time()
        with self._lock:
            expired = [tid for tid, t in self._active_tasks.items()
                      if t['status'] in ('completed', 'failed', 'timeout')
                      and now - t.get('end_time', t['start_time']) > max_age]
            for tid in expired:
                del self._active_tasks[tid]


# =========================================================================
# 5. Anticipator (JarvisAnticipator) — 预见者引擎
# =========================================================================
class Anticipator(threading.Thread):
    def __init__(self, central_nerve):
        super().__init__(daemon=True)
        self.jarvis = central_nerve
        self._habit_patterns = {}
        self._last_scan_time = 0
        self._scan_interval = 30
        self._preloaded_context = ""
        self._last_preload_time = 0
        self._preload_cooldown = 120
        self._llm_last_check = 0
        self._llm_check_interval = 1800

    def run(self):
        time.sleep(30)
        print("🔮 [Anticipator] Predictive engine ready — proactive preemption mode active...")
        while True:
            try:
                self._tick()
            except Exception as e:
                try:
                    from jarvis_utils import bg_log as _bg
                    _bg(f"⚠️ [Anticipator] Scan error: {e}")
                except Exception:
                    pass
            time.sleep(self._scan_interval)

    def _tick(self):
        now = time.time()
        current_hour = int(time.strftime('%H'))
        current_weekday = time.strftime('%A')
        work_category = getattr(
            getattr(self.jarvis, 'PhysicalEnvironmentProbe', None),
            'current_work_category', 'Unknown'
        )
        try:
            work_category = PhysicalEnvironmentProbe.current_work_category
            window_title = PhysicalEnvironmentProbe.current_window_title
        except Exception:
            window_title = ""

        pattern_key = f"{current_weekday}_{current_hour}"
        if pattern_key not in self._habit_patterns:
            self._habit_patterns[pattern_key] = {'count': 0, 'categories': {}}

        self._habit_patterns[pattern_key]['count'] += 1
        self._habit_patterns[pattern_key]['categories'][work_category] = \
            self._habit_patterns[pattern_key]['categories'].get(work_category, 0) + 1

        dominant_category = max(
            self._habit_patterns[pattern_key]['categories'],
            key=self._habit_patterns[pattern_key]['categories'].get
        ) if self._habit_patterns[pattern_key]['categories'] else 'Unknown'

        if self._habit_patterns[pattern_key]['count'] >= 3 and dominant_category != 'Unknown':
            if now - self._last_preload_time > self._preload_cooldown:
                self._preload_for_category(dominant_category, window_title)
                self._last_preload_time = now

        if now - self._llm_last_check > self._llm_check_interval:
            self._llm_last_check = now
            self._llm_pattern_reflect()

    def _preload_for_category(self, category: str, window_title: str):
        try:
            hippocampus = getattr(self.jarvis, 'hippocampus', None)
            if not hippocampus:
                return

            query_map = {
                'Coding': '编程 代码 开发 bug fix',
                'Media': '视频 音乐 娱乐 直播',
                'Communication': '聊天 消息 邮件',
                'Browsing': '搜索 浏览 研究 文章',
            }
            query = query_map.get(category, '最近 任务 工作')

            results = hippocampus.search_memory(
                getattr(self.jarvis, 'gemini_key', None),
                query,
                top_k=3
            )

            if results:
                context_parts = ["[ANTICIPATOR - Preloaded context based on habitual patterns]:"]
                now = time.time()
                for r in results:
                    time_str = time.strftime('%m/%d %H:%M', time.localtime(r['timestamp']))
                    age_hours = (now - r['timestamp']) / 3600
                    freshness = "🔥" if age_hours < 24 else ("📅" if age_hours < 168 else "📦")
                    context_parts.append(
                        f"  {freshness} [{time_str}] {r.get('intent', '')[:80]} → {r.get('summary', '')[:80]}"
                    )
                context_parts.append("[DIRECTIVE]: This context is preloaded. Reference naturally if relevant.")

                self._preloaded_context = "\n".join(context_parts)

                if hasattr(self.jarvis, 'chat_bypass'):
                    self.jarvis.chat_bypass.last_ltm_context = self._preloaded_context

                if self._habit_patterns.get(f"{time.strftime('%A')}_{int(time.strftime('%H'))}", {}).get('count', 0) <= 5:
                    print(f"🔮 [Anticipator] Preloaded {category} related memories ({len(results)} items)")
        except Exception as e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"⚠️ [Anticipator] Preload error: {e}")
            except Exception:
                pass

    def _llm_pattern_reflect(self):
        try:
            if len(self._habit_patterns) < 5:
                return

            reflector = getattr(self.jarvis, 'reflector', None)
            if not reflector:
                return

            pattern_summary = {}
            for key, data in sorted(self._habit_patterns.items()):
                if data['count'] >= 3:
                    pattern_summary[key] = {
                        'count': data['count'],
                        'dominant': max(data['categories'], key=data['categories'].get) if data['categories'] else 'Unknown'
                    }

            if len(pattern_summary) < 3:
                return

            system_prompt = """You are a pattern recognition engine. Identify Sir's habitual patterns from time-slot data.
Output ONLY valid JSON."""

            user_prompt = f"""Analyze these time-slot activity patterns:

{json.dumps(pattern_summary, ensure_ascii=False, indent=2)}

Output this JSON:
{{
    "identified_routines": [
        {{"time_slot": "weekday_hour", "activity": "description", "confidence": 0.0-1.0, "frequency": "daily/weekly/occasional"}}
    ],
    "most_consistent_pattern": "The single most reliable pattern observed",
    "prediction_for_now": "What Sir is most likely doing right now"
}}"""

            result = reflector.reflect('flash_lite', system_prompt, user_prompt, cache_ttl=3600)
            if result.get('success') and result.get('result'):
                routines = result['result'].get('identified_routines', [])
                high_conf = [r for r in routines if r.get('confidence', 0) >= 0.7]
                if high_conf:
                    print(f"🔮 [Anticipator LLM] Identified {len(high_conf)} high-confidence habit patterns")
        except Exception:
            pass

    def get_preloaded_context(self) -> str:
        return self._preloaded_context

    def get_pattern_summary(self) -> str:
        if len(self._habit_patterns) < 3:
            return ""

        parts = ["[HABIT PATTERNS - Learned from observation]:"]
        for key, data in sorted(self._habit_patterns.items(), key=lambda x: x[1]['count'], reverse=True)[:5]:
            if data['count'] >= 3:
                dominant = max(data['categories'], key=data['categories'].get) if data['categories'] else 'Unknown'
                parts.append(f"  - {key}: usually '{dominant}' ({data['count']} observations)")

        return "\n".join(parts) if len(parts) > 1 else ""


# =========================================================================
# 6. ContextRouter — 上下文路由器
# =========================================================================
class ContextRouter:
    def __init__(self, central_nerve):
        self.jarvis = central_nerve

    def assemble(self, current_hour: int) -> str:
        parts = []

        try:
            phys = PhysicalEnvironmentProbe.current_physical_state
            cat = PhysicalEnvironmentProbe.current_work_category
            dur = PhysicalEnvironmentProbe.work_duration_minutes
            parts.append(f"[PHYSICAL STATE]: {phys}")
            parts.append(f"[WORK CATEGORY]: {cat} (Session: {dur} min)")
        except Exception:
            pass

        if hasattr(self.jarvis, 'habit_clock'):
            parts.append(self.jarvis.habit_clock.get_llm_enhanced_summary())

        if hasattr(self.jarvis, 'causal_chain'):
            causal = self.jarvis.causal_chain.get_llm_enhanced_summary()
            if causal:
                parts.append(causal)

        if hasattr(self.jarvis, 'project_timeline'):
            proj = self.jarvis.project_timeline.get_summary()
            if proj:
                parts.append(proj)

        if hasattr(self.jarvis, 'anticipator'):
            pattern = self.jarvis.anticipator.get_pattern_summary()
            if pattern:
                parts.append(pattern)

        return "\n".join(parts)


# =========================================================================
# 7. ProfileCard — 用户画像卡片
# =========================================================================
class ProfileCard:
    def __init__(self, central_nerve):
        self.jarvis = central_nerve
        self._cache_time = 0
        self._cache_ttl = 300
        self._cached_prompt = ""
        self._corrections = []

    def apply_correction(self, source: str, field: str, old_value: str, new_value: str, confidence: float):
        self._corrections.append({
            'source': source,
            'field': field,
            'old': old_value,
            'new': new_value,
            'confidence': confidence,
            'timestamp': time.time()
        })
        if len(self._corrections) > 50:
            self._corrections = self._corrections[-50:]
        self._cache_time = 0

    def to_prompt_block(self) -> str:
        now = time.time()
        if self._cached_prompt and now - self._cache_time < self._cache_ttl:
            return self._cached_prompt

        parts = ["=== SIR'S PROFILE (continuously refined) ==="]

        try:
            profile_file = os.path.join("jarvis_config", "sir_profile.json")
            if os.path.exists(profile_file):
                with open(profile_file, 'r', encoding='utf-8') as f:
                    profile = json.load(f)

                philosophy = profile.get('core_philosophy', '')
                if philosophy:
                    parts.append(f"Core: {philosophy}")

                idiosyncrasies = profile.get('idiosyncrasies', '')
                if idiosyncrasies:
                    parts.append(f"Habits: {idiosyncrasies}")

                boundaries = profile.get('conversational_boundaries', '')
                if boundaries:
                    parts.append(f"Boundaries: {boundaries}")

                projects = profile.get('active_projects', [])
                if projects:
                    parts.append(f"Projects: {', '.join(projects[-5:])}")

                skills = profile.get('skill_domains', [])
                if skills:
                    parts.append(f"Skills: {', '.join(skills[-5:])}")

                jokes = profile.get('our_inside_jokes', [])
                if jokes:
                    parts.append(f"Inside jokes ({len(jokes)} stored)")

                progression = profile.get('skill_progression', [])
                if progression:
                    prog_lines = []
                    for s in progression[-3:]:
                        prog_lines.append(f"  - {s.get('skill', '?')} (confidence: {s.get('confidence', '?')})")
                    parts.append("Skill Progression:\n" + "\n".join(prog_lines))
        except Exception:
            pass

        recent_corrections = [c for c in self._corrections if now - c['timestamp'] < 86400]
        if recent_corrections:
            parts.append(f"[Recent refinements ({len(recent_corrections)} today)]")

        self._cached_prompt = "\n".join(parts)
        self._cache_time = now
        return self._cached_prompt


# =========================================================================
# 8. ContentPreferenceTracker — 响应质量隐式反馈追踪
# =========================================================================
class ContentPreferenceTracker:
    def __init__(self):
        self._response_history = deque(maxlen=50)
        self._feedback_signals = deque(maxlen=100)
        self._style_scores = defaultdict(lambda: {'positive': 0, 'negative': 0, 'total': 0})
        self._topic_engagement = defaultdict(lambda: {'follow_ups': 0, 'corrections': 0, 'ignores': 0})
        self._last_user_input = ""
        self._last_jarvis_response = ""
        self._conversation_turn = 0
        self._window_switch_count = 0
        self._last_window_title = ""

    def tick(self):
        try:
            current_title = PhysicalEnvironmentProbe.current_window_title
            if current_title != self._last_window_title and self._last_window_title:
                self._window_switch_count += 1
            self._last_window_title = current_title
        except Exception:
            pass

    def record_interaction(self, user_input: str, jarvis_response: str):
        self._last_user_input = user_input
        self._last_jarvis_response = jarvis_response
        self._conversation_turn += 1

        entry = {
            'timestamp': time.time(),
            'user_input': user_input[:200],
            'jarvis_response': jarvis_response[:200],
            'response_length': len(jarvis_response),
            'turn': self._conversation_turn
        }
        self._response_history.append(entry)

    def record_feedback(self, signal_type: str, user_input: str = "", jarvis_response: str = ""):
        signal = {
            'timestamp': time.time(),
            'type': signal_type,
            'user_input': user_input[:200],
            'jarvis_response': jarvis_response[:200]
        }
        self._feedback_signals.append(signal)

        if jarvis_response:
            length = len(jarvis_response)
            if length < 50:
                style = 'concise'
            elif length < 200:
                style = 'moderate'
            else:
                style = 'verbose'

            if signal_type in ('correction', 'repeat_question', 'frustration'):
                self._style_scores[style]['negative'] += 1
            elif signal_type in ('follow_up', 'positive_ack', 'natural_continue'):
                self._style_scores[style]['positive'] += 1
            self._style_scores[style]['total'] += 1

    def detect_implicit_feedback(self, current_input: str, previous_input: str,
                                  previous_response: str) -> Optional[str]:
        current_lower = current_input.lower().strip()
        prev_lower = previous_input.lower().strip()

        correction_signals = [
            r'\b(no[,.\s]*i\s+meant?|not\s+that|that\'?s\s+not\s+right|that\'?s\s+wrong)\b',
            r'\b(不对|不是|错了|搞错了|不是这个|你理解错了)\b',
            r'\b(correct|actually|i\s+said|i\s+asked|what\s+i\s+meant?)\b',
            r'\b(应该是|我是说|我要的是|我是想问)\b',
        ]
        for pattern in correction_signals:
            if re.search(pattern, current_lower):
                return 'correction'

        if previous_input and len(previous_input) > 5:
            prev_words = set(prev_lower.split())
            curr_words = set(current_lower.split())
            overlap = len(prev_words & curr_words) / max(len(prev_words), 1)
            if overlap > 0.5 and len(current_lower) > 10:
                return 'repeat_question'

        frustration_signals = [
            r'\b(sigh|ugh|argh|ffs|wtf|omg|seriously|again\?|still\?)\b',
            r'\b(唉|哎|啧|怎么又|还是|又是)\b',
        ]
        for pattern in frustration_signals:
            if re.search(pattern, current_lower):
                return 'frustration'

        positive_signals = [
            r'\b(thanks|thank\s+you|perfect|exactly|great|good|nice|awesome)\b',
            r'\b(谢谢|好的|完美|没错|对|很好|不错)\b',
        ]
        for pattern in positive_signals:
            if re.search(pattern, current_lower):
                return 'positive_ack'

        if previous_response and len(previous_response) > 50:
            resp_words = set(previous_response.lower().split())
            curr_words = set(current_lower.split())
            overlap = len(resp_words & curr_words) / max(len(resp_words), 1)
            if overlap > 0.3:
                return 'follow_up'

        return None

    def get_preferred_style(self) -> str:
        if not self._style_scores:
            return ""

        best_style = None
        best_score = -1
        for style, scores in self._style_scores.items():
            if scores['total'] >= 3:
                ratio = (scores['positive'] + 1) / (scores['negative'] + 1)
                if ratio > best_score:
                    best_score = ratio
                    best_style = style

        if best_style and best_score > 1.5:
            return f"[PREFERRED STYLE]: Sir tends to respond better to '{best_style}' responses (positive ratio: {best_score:.1f}:1)."
        return ""

    def get_stats(self) -> dict:
        return {
            'total_interactions': self._conversation_turn,
            'feedback_count': len(self._feedback_signals),
            'style_scores': dict(self._style_scores),
            'topic_engagement': dict(self._topic_engagement)
        }


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