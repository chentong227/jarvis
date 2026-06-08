# -*- coding: utf-8 -*-
"""[P0+19-5 / 2026-05-16] Jarvis Memory Core — 记忆/纠错/睡意/幽默类（12 类）

从 jarvis_nerve.py 拆出 12 个类，分两组：

A. 幽默 / 个性化记忆（与 SmartNudge 配对）：
  - HumorMemory (~188 行) — Sir 的笑点 + 已用 nudge 重复防御

B. 主脑记忆基础设施（CentralNerve 直接持有）：
  - PromptLayer + PromptCache (TTL 缓存)
  - CorrectionEntry + CorrectionMemory + CorrectionLoop (纠错三件套)
  - MemoryFragment + UnifiedMemoryGateway (统一记忆访问)
  - FeedbackTracker (用户反馈追踪)
  - TaskWorkerPool + Anticipator (记忆预加载线程)
  - SleepIntentDetector (睡意意图)

依赖：
- 标准库：time / re / json / sqlite3 / threading / queue / hashlib / os
- dataclass / field
- jarvis_blood.MemoryFragment (但本文件也定义 MemoryFragment, 注意可能重复 — 后续清理)
- jarvis_hippocampus.Hippocampus (UnifiedMemoryGateway / Anticipator 内部用)

向后兼容：jarvis_nerve.py 转发垫层保证旧 `from jarvis_nerve import HumorMemory / PromptCache / ...` 0 改动。
"""

from __future__ import annotations

# [P0+20-α.1 / 2026-05-16] numpy 用于 embedding 向量化与余弦相似度（CorrectionMemory.search + UnifiedMemoryGateway / Anticipator 等 9 处 `np.*`）
# 拆分时 P0+19-5 漏掉 → 09:23 实测 `[KeyRouter] google_3 标记为不健康 (错误: name 'np' is not defined)` 被 KeyRouter 误归因到 key 上
import numpy as np

# [P0+19-final fix 4 / 2026-05-16] 一次性补全标准库 + 第三方常用 import（防 NameError 暴露）
import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import re  # noqa: F401
import time  # noqa: F401
import json  # noqa: F401
import math  # noqa: F401
import random  # noqa: F401
import queue  # noqa: F401
import sqlite3  # noqa: F401
import hashlib  # noqa: F401
import threading  # noqa: F401
import collections  # noqa: F401
import importlib  # noqa: F401
import concurrent.futures  # noqa: F401
import multiprocessing  # noqa: F401
from collections import defaultdict, deque  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from typing import List, Dict, Any, Optional, Tuple  # noqa: F401
try:
    from google.genai import types  # noqa: F401
except ImportError:
    pass


import os
import re
import json
import time
import sqlite3
import threading
import queue
import hashlib
import random  # noqa: F401
import collections  # noqa: F401
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional  # noqa: F401
# [P0+19-final fix 2]
from google.genai import types  # noqa: F401
import sys  # noqa: F401  # noqa: F401

__all__ = [
    'HumorMemory',
    'PromptLayer',
    'PromptCache',
    'CorrectionEntry',
    'CorrectionMemory',
    'MemoryFragment',
    'UnifiedMemoryGateway',
    'FeedbackTracker',
    'TaskWorkerPool',
    'Anticipator',
    'CorrectionLoop',
    'SleepIntentDetector',
]


# ============================================================================
# A. HumorMemory — Sir 笑点 + nudge 重复防御
# ============================================================================

class HumorMemory:
    """幽默去重引擎：持久化状态 + 动态权重 + 用户反馈学习 + 跨类型互斥"""
    def __init__(self, max_entries=30):
        self._used_topics = collections.deque(maxlen=max_entries)
        self._topic_cooldown = {}
        self._topic_weights = {}
        self._global_joke_cooldown = 0.0
        self._lock = threading.Lock()
        self._profile_joke_keywords = {}
        self._profile_last_load = 0
        self._state_file = os.path.join("jarvis_config", "humor_state.json")
        self._load_state()

    def _load_state(self):
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                with self._lock:
                    for entry in state.get("used_topics", []):
                        self._used_topics.append(entry)
                    self._topic_cooldown = state.get("topic_cooldown", {})
                    self._topic_weights = state.get("topic_weights", {})
                    self._global_joke_cooldown = state.get("global_joke_cooldown", 0.0)
        except:
            pass

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            with self._lock:
                state = {
                    "used_topics": list(self._used_topics),
                    "topic_cooldown": self._topic_cooldown,
                    "topic_weights": self._topic_weights,
                    "global_joke_cooldown": self._global_joke_cooldown,
                }
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
        except:
            pass

    def _load_profile_jokes(self):
        now = time.time()
        if now - self._profile_last_load < 300 and self._profile_joke_keywords:
            return
        self._profile_last_load = now
        try:
            # [P0+20-β.2.4.3 / 2026-05-16] 切走老数据源 sir_profile.our_inside_jokes
            # → 读 Layer 2 RelationalState 单源。详 docs/JARVIS_SOUL_DRIVE.md
            # 方案 A 老路径退役第 3 步（前置：跑 scripts/migrate_profile_to_relational.py
            # 把现有 our_inside_jokes 一次性迁过去）
            jokes = []
            try:
                from jarvis_relational import get_default_store
                store = get_default_store()
                jokes = [j.phrase for j in store.list_inside_jokes()]
            except Exception:
                jokes = []
            if jokes:
                new_keywords = {}
                for joke in jokes:
                    joke_lower = joke.lower()
                    if "racing" in joke_lower or "飞车" in joke_lower or "speed" in joke_lower:
                        new_keywords["racing_game"] = True
                    if "bilibili" in joke_lower or "youtube" in joke_lower or "视频" in joke_lower or "stream" in joke_lower:
                        new_keywords["video_platform"] = True
                    if "直播" in joke_lower or "live" in joke_lower or "斗鱼" in joke_lower or "douyu" in joke_lower:
                        new_keywords["live_stream"] = True
                    if "code" in joke_lower or "cursor" in joke_lower or "pycharm" in joke_lower or "coding" in joke_lower or "编程" in joke_lower:
                        new_keywords["coding_ide"] = True
                    if "error" in joke_lower or "exception" in joke_lower or "报错" in joke_lower or "bug" in joke_lower:
                        new_keywords["error_screen"] = True
                    if "driving" in joke_lower or "练车" in joke_lower or "驾照" in joke_lower or "驾驶" in joke_lower:
                        new_keywords["driving_practice"] = True
                    if "hydration" in joke_lower or "喝水" in joke_lower or "water" in joke_lower or "battery" in joke_lower:
                        new_keywords["health_hydration"] = True
                    if "sleep" in joke_lower or "睡觉" in joke_lower or "熬夜" in joke_lower or "late" in joke_lower:
                        new_keywords["sleep_deprivation"] = True
                    if "asr" in joke_lower or "phonetic" in joke_lower or "hallucination" in joke_lower or "空耳" in joke_lower or "语音识别" in joke_lower:
                        new_keywords["asr_glitch"] = True
                    if "keyboard" in joke_lower or "shortcut" in joke_lower or "快捷键" in joke_lower:
                        new_keywords["keyboard_war"] = True
                    if "hide" in joke_lower or "data wall" in joke_lower or "barrier" in joke_lower or "遮挡" in joke_lower:
                        new_keywords["hide_and_seek"] = True
                self._profile_joke_keywords = new_keywords
            else:
                # relational_state 暂无 jokes（迁移未跑 / 真空）— 清空匹配，
                # 不退回读 sir_profile（方案 A 单源）
                self._profile_joke_keywords = {}
        except:
            pass

    def _get_active_joke_topics(self):
        self._load_profile_jokes()
        return list(self._profile_joke_keywords.keys())

    def get_topic_weight(self, topic_key: str) -> float:
        with self._lock:
            base = self._topic_weights.get(topic_key, 1.0)
            last_used = self._topic_cooldown.get(topic_key, 0)
            elapsed_hours = (time.time() - last_used) / 3600.0
            decay = min(1.0, elapsed_hours / 4.0)
            return base * decay

    def lower_topic_weight(self, topic_key: str, amount: float = 0.4):
        with self._lock:
            current = self._topic_weights.get(topic_key, 1.0)
            self._topic_weights[topic_key] = max(0.05, current - amount)
        self._save_state()

    def can_joke_now(self, topic_key: str = None) -> bool:
        with self._lock:
            now = time.time()
            if now - self._global_joke_cooldown < 3600:
                return False
            if topic_key:
                weight = self.get_topic_weight(topic_key)
                if weight < 0.2:
                    return False
                last_used = self._topic_cooldown.get(topic_key, 0)
                if now - last_used < 7200:
                    return False
            return True

    def register_joke(self, topic_key: str, response_text: str):
        with self._lock:
            now = time.time()
            entry = {
                "topic": topic_key,
                "text": response_text[:200],
                "time": now
            }
            self._used_topics.append(entry)
            self._topic_cooldown[topic_key] = now
            self._global_joke_cooldown = now
        self._save_state()
        # 🆕 [Reshape M3.H / 2026-05-24] 准则 6 数据强耦合: publish SWM event
        # 让主脑下轮 SWM block 看到 "刚 register joke topic=X", 不用主脑猜.
        # salience=0.5 (中等, 不进 swm_history.jsonl 持久化, 仅 in-deque).
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                bus.publish(
                    etype='joke_fired',
                    description=(
                        f"HumorMemory.register_joke topic='{topic_key}' "
                        f"text='{response_text[:60]}'"
                    ),
                    source='HumorMemory',
                    salience=0.5,
                    metadata={
                        'topic_key': topic_key,
                        'global_cooldown_active': True,
                    },
                )
        except Exception:
            pass

    def get_recent_topics(self, max_age_seconds=7200):
        now = time.time()
        with self._lock:
            return [
                e["topic"] for e in self._used_topics
                if now - e["time"] < max_age_seconds
            ]

    def get_topic_freshness(self, topic_key: str) -> float:
        with self._lock:
            last_used = self._topic_cooldown.get(topic_key, 0)
            elapsed = time.time() - last_used
            if elapsed < 3600:
                return 0.0
            elif elapsed < 7200:
                return 0.2
            elif elapsed < 14400:
                return 0.5
            elif elapsed < 28800:
                return 0.8
            return 1.0

    def should_skip_topic(self, topic_key: str) -> bool:
        if not self.can_joke_now(topic_key):
            return True
        return self.get_topic_freshness(topic_key) < 0.2

    def get_state_snapshot(self) -> dict:
        """🆕 [Reshape M3.H / 2026-05-24] 准则 6 数据强耦合: 公开 inspect API.

        给 scripts/humor_state_dump.py / debug 用. 返当前 cooldown / weights / 笑点池.
        不影响主脑路径 (只读).
        """
        with self._lock:
            now = time.time()
            global_cd_remain = max(0.0, 3600 - (now - self._global_joke_cooldown))
            return {
                'used_topics_count': len(self._used_topics),
                'used_topics_recent5': list(self._used_topics)[-5:],
                'topic_cooldowns': {
                    k: {
                        'last_fired_at': v,
                        'cooldown_remain_s': max(0.0, 7200 - (now - v)),
                        'freshness': self.get_topic_freshness(k),
                    }
                    for k, v in self._topic_cooldown.items()
                },
                'topic_weights': dict(self._topic_weights),
                'global_cooldown_remain_s': global_cd_remain,
                'profile_keywords_active': list(self._profile_joke_keywords.keys()),
            }

    def extract_topic_key(self, window_title: str, nudge_type: str) -> str:
        title_lower = window_title.lower()

        self._load_profile_jokes()
        active_topics = self._get_active_joke_topics()

        if "racing_game" in active_topics and ("飞车" in title_lower or "racing" in title_lower or "speed" in title_lower):
            return "racing_game"
        if "live_stream" in active_topics and ("直播" in title_lower or "live" in title_lower or "斗鱼" in title_lower or "douyu" in title_lower):
            return "live_stream"
        if "video_platform" in active_topics and ("bilibili" in title_lower or "youtube" in title_lower or "视频" in title_lower):
            return "video_platform"
        if "coding_ide" in active_topics and ("code" in title_lower or "cursor" in title_lower or "pycharm" in title_lower):
            return "coding_ide"
        if "error_screen" in active_topics and ("error" in title_lower or "exception" in title_lower or "报错" in title_lower):
            return "error_screen"
        if "driving_practice" in active_topics and ("driving" in title_lower or "练车" in title_lower or "驾照" in title_lower):
            return "driving_practice"

        if "飞车" in title_lower or "racing" in title_lower or "speed" in title_lower:
            return "racing_game"
        if "bilibili" in title_lower or "youtube" in title_lower or "视频" in title_lower:
            return "video_platform"
        if "直播" in title_lower or "live" in title_lower or "斗鱼" in title_lower or "douyu" in title_lower:
            return "live_stream"
        if "code" in title_lower or "cursor" in title_lower or "pycharm" in title_lower:
            return "coding_ide"
        if "error" in title_lower or "exception" in title_lower or "报错" in title_lower:
            return "error_screen"
        if "driving" in title_lower or "练车" in title_lower or "驾照" in title_lower:
            return "driving_practice"
        return f"{nudge_type}:{title_lower[:30]}"




# ============================================================================
# B. 主脑记忆基础设施（11 类）
# ============================================================================

@dataclass
class PromptLayer:
    layer_id: str = ""
    content: str = ""
    ttl_seconds: float = 3600.0
    dependencies: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl_seconds


class PromptCache:
    def __init__(self):
        self._layers = {}
        self._lock = threading.Lock()

    def get_or_build(self, layer_id: str, builder_fn, ttl: float = 3600.0, dependencies: list = None) -> str:
        with self._lock:
            cached = self._layers.get(layer_id)
            if cached and not cached.is_expired():
                deps_valid = True
                if cached.dependencies:
                    for dep_id in cached.dependencies:
                        dep = self._layers.get(dep_id)
                        if not dep or dep.is_expired():
                            deps_valid = False
                            break
                if deps_valid:
                    return cached.content

        content = builder_fn()
        layer = PromptLayer(
            layer_id=layer_id,
            content=content,
            ttl_seconds=ttl,
            dependencies=dependencies or []
        )
        with self._lock:
            self._layers[layer_id] = layer
        return content

    def invalidate(self, layer_id: str):
        with self._lock:
            if layer_id in self._layers:
                del self._layers[layer_id]

    def invalidate_all(self):
        with self._lock:
            self._layers.clear()


@dataclass
class CorrectionEntry:
    trigger_context: str = ""
    wrong_response: str = ""
    correction: str = ""
    source_module: str = "chat"
    confidence: float = 1.0
    timestamp: float = field(default_factory=time.time)
    times_recalled: int = 0


class CorrectionMemory:
    def __init__(self, db_path="memory_pool/jarvis_memory.db"):
        self.db_path = db_path
        self._ensure_table()

    def _get_conn(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute('PRAGMA journal_mode=WAL;')
        return conn

    def _ensure_table(self):
        conn = self._get_conn()
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
        conn.commit()
        conn.close()

    def record_correction(self, entry: CorrectionEntry, key_router=None):
        conn = self._get_conn()
        cursor = conn.cursor()

        embedding_bytes = None
        if key_router and entry.trigger_context:
            _key_name = None
            try:
                _key, _key_name, _provider = key_router.get_key('hippocampus', 'flash_lite',
                                                       allow_openrouter_fallback=False)
                client = create_genai_client(api_key=_key)
                response = client.models.embed_content(
                    model='gemini-embedding-2',
                    contents=[f"correction context: {entry.trigger_context}"],
                    config=types.EmbedContentConfig(output_dimensionality=768)
                )
                embedding_bytes = np.array(response.embeddings[0].values, dtype=np.float32).tobytes()
                key_router.release(_key_name)
            except Exception as e:
                if _key_name:
                    key_router.report_error(_key_name, str(e))
                    key_router.release(_key_name)

        cursor.execute('''
            INSERT INTO CorrectionMemory
            (timestamp, trigger_context, wrong_response, correction, context_embedding, source_module, confidence, times_recalled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            entry.timestamp, entry.trigger_context, entry.wrong_response,
            entry.correction, embedding_bytes, entry.source_module,
            entry.confidence, entry.times_recalled
        ))
        conn.commit()
        conn.close()

    def find_similar_corrections(self, current_context: str, key_router=None, top_k: int = 3) -> list:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, timestamp, trigger_context, wrong_response, correction, context_embedding, confidence, times_recalled FROM CorrectionMemory WHERE context_embedding IS NOT NULL ORDER BY timestamp DESC LIMIT 100"
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return []

        if key_router and current_context:
            _key_name = None
            try:
                _key, _key_name, _provider = key_router.get_key('hippocampus', 'flash_lite',
                                                       allow_openrouter_fallback=False)
                client = create_genai_client(api_key=_key)
                response = client.models.embed_content(
                    model='gemini-embedding-2',
                    contents=[f"correction context: {current_context}"],
                    config=types.EmbedContentConfig(output_dimensionality=768)
                )
                query_vec = np.array(response.embeddings[0].values, dtype=np.float32)
                key_router.release(_key_name)

                results = []
                query_norm = np.linalg.norm(query_vec)
                for row in rows:
                    if row[5] is None:
                        continue
                    mem_vec = np.frombuffer(row[5], dtype=np.float32)
                    mem_norm = np.linalg.norm(mem_vec)
                    if query_norm == 0 or mem_norm == 0:
                        sim = 0.0
                    else:
                        sim = float(np.dot(query_vec, mem_vec) / (query_norm * mem_norm))
                    results.append({
                        'id': row[0], 'timestamp': row[1], 'trigger_context': row[2],
                        'wrong_response': row[3], 'correction': row[4],
                        'similarity': sim, 'confidence': row[6], 'times_recalled': row[7]
                    })
                results.sort(key=lambda x: x['similarity'], reverse=True)
                return results[:top_k]
            except Exception as e:
                if _key_name:
                    key_router.report_error(_key_name, str(e))
                    key_router.release(_key_name)

        return [{
            'id': r[0], 'timestamp': r[1], 'trigger_context': r[2],
            'wrong_response': r[3], 'correction': r[4],
            'similarity': 0.5, 'confidence': r[6], 'times_recalled': r[7]
        } for r in rows[:top_k]]

    def mark_recalled(self, correction_id: int):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE CorrectionMemory SET times_recalled = times_recalled + 1 WHERE id = ?", (correction_id,))
        conn.commit()
        conn.close()

    def get_correction_prompt_block(self, current_context: str, key_router=None, max_results: int = 3) -> str:
        corrections = self.find_similar_corrections(current_context, key_router, max_results)
        if not corrections:
            return ""

        lines = ["\n[LEARNED CORRECTIONS - Sir has previously corrected me in similar contexts. Apply these lessons:]"]
        for c in corrections:
            if c['similarity'] < 0.3:
                continue
            lines.append(f"- Context: {c['trigger_context'][:120]}")
            lines.append(f"  I said: \"{c['wrong_response'][:150]}\"")
            lines.append(f"  Sir corrected: \"{c['correction'][:150]}\"")
            self.mark_recalled(c['id'])
        return '\n'.join(lines) if len(lines) > 1 else ""


@dataclass
class MemoryFragment:
    source: str = ""
    content: str = ""
    relevance_score: float = 0.0
    freshness_hours: float = 0.0
    source_weight: float = 0.0
    timestamp: float = 0.0


class UnifiedMemoryGateway:
    """[DEPRECATED — Reshape M2.C / 2026-05-24] 已并入 MemoryHub (jarvis_memory_gateway).

    保留为 stub 让 20+ noqa F401 转发 import 不破 (兼容老 `from jarvis_memory_core
    import UnifiedMemoryGateway` 形式). 真实功能全在 `MemoryHub.query` +
    `MemoryHub.to_prompt_block` (M2.A 搬运).

    本 stub 是 delegate: 任何方法调用都转给 default hub. 真使用会发 warning.
    M2 完整完成后 (M5+) 可直接 `del` 此 class + 删 noqa import.

    Sir 准则 8 (优雅 > 简单): 删比改危险, stub delegate 是 0 破坏的 cleanup 第一步.
    """

    _warned = False

    def __init__(self, central_nerve):
        self.nerve = central_nerve
        if not type(self)._warned:
            type(self)._warned = True
            try:
                import warnings
                warnings.warn(
                    'UnifiedMemoryGateway is deprecated. '
                    'Use jarvis_memory_gateway.get_default_hub() instead '
                    '(MemoryHub.query / MemoryHub.to_prompt_block).',
                    DeprecationWarning, stacklevel=2,
                )
            except Exception:
                pass

    def _hub(self):
        try:
            from jarvis_memory_gateway import get_default_hub
            return get_default_hub()
        except Exception:
            return None

    def query(self, query_text: str, top_k: int = 5) -> list:
        h = self._hub()
        if h is None:
            return []
        return h.query(query_text, top_k=top_k, nerve=self.nerve)

    def to_prompt_block(self, query_text: str, top_k: int = 5) -> str:
        h = self._hub()
        if h is None:
            return ""
        return h.to_prompt_block(query_text, top_k=top_k, nerve=self.nerve)


# [P0+13 / 2026-05-15] FeedbackSignal 双定义合并 —— 复用 jarvis_blood.FeedbackSignal
# 之前 nerve.py 自带一份 dataclass，与 jarvis_blood 那份字段大同小异但独立维护，
# 形成"重复实现 + 状态可能不共享"。现统一从 blood 导入。
from jarvis_blood import FeedbackSignal  # noqa: E402

# [P0+19-final fix / 2026-05-16] 补全跨模块依赖（拆分后实例化时才暴露的缺失）
try:
    from jarvis_key_router import KeyRouter  # noqa: F401
except ImportError:
    pass
try:
    from jarvis_llm_reflector import LlmReflector  # noqa: F401
except ImportError:
    pass
try:
    from jarvis_hippocampus import Hippocampus  # noqa: F401
except ImportError:
    pass
try:
    from jarvis_blood import JarvisBlood, ExecutionResult, FeedbackSignal  # noqa: F401
except ImportError:
    pass
try:
    from jarvis_utils import (  # noqa: F401
        bg_log, set_conversation_active, is_conversation_active,
        register_jarvis_tts, is_recent_jarvis_echo, clear_jarvis_tts_ring,
        safe_gemini_call, safe_openrouter_call, create_genai_client,
        get_local_fallback, QuickClassifier, get_quick_classifier,
        ConversationEventBus, JarvisState, PlanLedger, WorkingMemoryFeed,
        SessionDigest, ToneSelector, AntiCommonPhraseTracker,
        VerbosityPreferenceTracker, ProjectContextProbe,
        ClipboardWatcher, PSHistoryWatcher, AttentionSlot,
        render_yesterday_block, render_open_threads_block,
        render_active_reminders_block, render_attention_block,
        render_silent_nudge_text, render_project_block,
        extract_open_threads, capture_attention_snapshot,
        resolve_nudge_channel, network_retry, get_rate_limiter,
        get_default_attention_slot, get_default_event_bus,
        get_default_phrase_tracker, get_default_plan_ledger,
        get_default_tone_selector, get_default_verbosity_tracker,
        get_default_working_feed,
    )
except ImportError:
    pass



# ============================================================
# 🩹 [P0+20-β.3.4-vocab6 / 2026-05-18] 准则 6.5 vocab 持久化
# 原 FeedbackTracker.__init__._correction_patterns (10 regex × signal_type)
# 迁 memory_pool/feedback_vocab.json + scripts/feedback_vocab_dump.py.
# 范式同 β.3.0-vocab1 但 entry 是 (compiled regex, signal_type), 不是 keyword.
# ============================================================

# Fallback seed — 与 json 完全一致, 仅 json 损坏/不存在时用. 顺序敏感 (first match wins).
_SEED_FEEDBACK_PATTERNS: List[Tuple[str, str]] = [
    (r"(?:不对|不是|错了|搞错|记错|出错|两码事|两个事|其实|"
     r"澄清|纠正|没那么|不是的|不要混淆|搞混)", "correction"),
    (r"\b(?:no|nope|not|don't|doesn't|isn't|actually|clarify|"
     r"correction|i meant|i'm not|you got it wrong|that's not)\b", "correction"),
    (r"\b(?:what\?|huh\?|pardon|excuse me\?)\b", "confusion"),
    (r"(?:啥|什么意思|没听明白|没明白)", "confusion"),
    (r"\b(?:thanks|thank you|perfect|exactly|great|good|nice)\b", "positive"),
    (r"(?:谢谢|对了|完美|不错|很好|挺好)", "positive"),
    (r"\b(?:go on|continue|and then|what else)\b", "follow_up"),
    (r"(?:然后|接着)", "follow_up"),
    (r"\b(?:ignore|skip|never mind)\b", "dismiss"),
    (r"(?:算了|不管|别管)", "dismiss"),
]

_FEEDBACK_VOCAB_PATH = os.path.join('memory_pool', 'feedback_vocab.json')
_FEEDBACK_PATTERNS_CACHE: Optional[List[Tuple[Any, str]]] = None
_FEEDBACK_PATTERNS_MTIME: float = 0.0


def _load_feedback_patterns_from_json() -> Optional[List[Tuple[Any, str]]]:
    """从 json 加载 active pattern (regex, signal_type). 顺序保留 (first match wins).
    失败返 None 走 fallback seed."""
    if not os.path.exists(_FEEDBACK_VOCAB_PATH):
        return None
    try:
        with open(_FEEDBACK_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        out: List[Tuple[Any, str]] = []
        for p in data.get('patterns', []):
            if not isinstance(p, dict):
                continue
            if p.get('state') != 'active':
                continue
            regex_str = p.get('regex')
            sig_type = p.get('signal_type')
            if not regex_str or not sig_type:
                continue
            try:
                compiled = re.compile(regex_str)
            except re.error:
                # 坏 regex 跳过, 不污染整体
                continue
            out.append((compiled, sig_type))
        return out if out else None
    except Exception:
        return None


def get_feedback_patterns() -> List[Tuple[Any, str]]:
    """🩹 [β.3.4-vocab6] mtime cache 自动 reload. 返 compiled regex 列表."""
    global _FEEDBACK_PATTERNS_CACHE, _FEEDBACK_PATTERNS_MTIME
    try:
        mtime = os.path.getmtime(_FEEDBACK_VOCAB_PATH) if os.path.exists(
            _FEEDBACK_VOCAB_PATH) else 0
    except OSError:
        mtime = 0
    if _FEEDBACK_PATTERNS_CACHE is None or mtime > _FEEDBACK_PATTERNS_MTIME:
        loaded = _load_feedback_patterns_from_json()
        if loaded is not None:
            _FEEDBACK_PATTERNS_CACHE = loaded
        else:
            # fallback: 用 seed (compile)
            _FEEDBACK_PATTERNS_CACHE = [
                (re.compile(rx), st) for rx, st in _SEED_FEEDBACK_PATTERNS
            ]
        _FEEDBACK_PATTERNS_MTIME = mtime
    return _FEEDBACK_PATTERNS_CACHE


class FeedbackTracker:
    # 🩹 [β.2.9.9 / 2026-05-18] Sir 10:51 诚信审计 — 中英 regex 修
    # 🩹 [β.3.4-vocab6 / 2026-05-18] 准则 6.5 vocab 迁 module-level:
    # 原 self._correction_patterns (10 regex × signal_type) → memory_pool/
    # feedback_vocab.json + scripts/feedback_vocab_dump.py.
    # analyze_interaction 改用 get_feedback_patterns() (module helper).
    def __init__(self):
        self.signals = collections.deque(maxlen=200)
        self._response_quality_scores = collections.deque(maxlen=100)

    def analyze_interaction(self, user_input: str, jarvis_response: str, stm_context: str = "") -> FeedbackSignal:
        signal_type = "neutral"
        input_lower = user_input.lower().strip()

        for pattern, sig_type in get_feedback_patterns():
            if pattern.search(input_lower):
                signal_type = sig_type
                break

        signal = FeedbackSignal(
            signal_type=signal_type,
            user_input=user_input,
            jarvis_response=jarvis_response,
            context_snapshot=stm_context[:500],
            metadata={
                'input_length': len(user_input),
                'response_length': len(jarvis_response),
                'hour': int(time.strftime('%H')),
            }
        )
        self.signals.append(signal)

        if signal_type in ("correction", "confusion"):
            self._response_quality_scores.append(('negative', time.time()))
        elif signal_type == "positive":
            self._response_quality_scores.append(('positive', time.time()))

        return signal

    def get_quality_trend(self, window_minutes: int = 60) -> dict:
        now = time.time()
        cutoff = now - window_minutes * 60
        recent = [s for s in self._response_quality_scores if s[1] > cutoff]
        if not recent:
            return {'positive_rate': 0.5, 'total': 0, 'trend': 'stable'}
        positive_count = sum(1 for s in recent if s[0] == 'positive')
        negative_count = sum(1 for s in recent if s[0] == 'negative')
        total = len(recent)
        rate = positive_count / total if total > 0 else 0.5
        trend = 'improving' if rate > 0.6 else ('declining' if rate < 0.3 else 'stable')
        return {'positive_rate': round(rate, 2), 'total': total, 'trend': trend}

    def get_recent_corrections(self, n: int = 3) -> list:
        corrections = [s for s in self.signals if s.signal_type == 'correction']
        return list(corrections)[-n:]

    def should_adjust_style(self) -> dict:
        trend = self.get_quality_trend(30)
        if trend['trend'] == 'declining' and trend['total'] >= 3:
            return {'adjust': True, 'suggestion': 'Be more concise and direct. Avoid elaboration.'}
        return {'adjust': False, 'suggestion': ''}


class TaskWorkerPool:
    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers
        self.task_queue = queue.Queue()
        self.active_tasks = {}
        self._task_counter = 0
        self._lock = threading.Lock()
        self._workers = []
        for _ in range(max_workers):
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self._workers.append(t)

    def _worker_loop(self):
        while True:
            try:
                task_id, task_fn, callback = self.task_queue.get(timeout=1.0)
                with self._lock:
                    self.active_tasks[task_id] = 'running'
                try:
                    result = task_fn()
                    with self._lock:
                        self.active_tasks[task_id] = 'done'
                    if callback:
                        callback(result)
                except Exception as e:
                    with self._lock:
                        self.active_tasks[task_id] = f'error: {e}'
                self.task_queue.task_done()
            except queue.Empty:
                pass

    def submit(self, task_fn, callback=None) -> str:
        with self._lock:
            self._task_counter += 1
            task_id = f"task_{self._task_counter}"
            self.active_tasks[task_id] = 'queued'
        self.task_queue.put((task_id, task_fn, callback))
        return task_id

    def get_status(self, task_id: str) -> str:
        with self._lock:
            return self.active_tasks.get(task_id, 'unknown')

    @property
    def pending_count(self) -> int:
        return self.task_queue.qsize()


class Anticipator(threading.Thread):
    def __init__(self, central_nerve):
        super().__init__(daemon=True)
        self.nerve = central_nerve
        self._last_prediction = None
        self._last_prediction_time = 0
        self._prediction_interval = 30
        self._preloaded_context = ""

    def run(self):
        time.sleep(15)
        print("[Anticipator] 预测预加载引擎就绪...")
        while True:
            try:
                now = time.time()
                if now - self._last_prediction_time < self._prediction_interval:
                    time.sleep(5)
                    continue
                self._last_prediction_time = now
                self._predict_and_preload()
            except Exception:
                pass
            time.sleep(5)

    def _predict_and_preload(self):
        hc = self.nerve.habit_clock
        if not hc:
            return

        prediction = hc.predict_current_state()
        work_cat = PhysicalEnvironmentProbe.current_work_category
        current_hour = int(time.strftime('%H'))
        proc_name = PhysicalEnvironmentProbe.current_process_name or ""

        predicted_need = self._infer_need(work_cat, current_hour, proc_name, prediction)

        if predicted_need == self._last_prediction:
            return
        self._last_prediction = predicted_need

        if predicted_need == "coding_context":
            self._preload_coding_context()
        elif predicted_need == "media_context":
            self._preload_media_context()
        elif predicted_need == "general_context":
            self._preload_general_context()

    def _infer_need(self, work_cat: str, hour: int, proc: str, prediction: dict) -> str:
        if work_cat == "Coding":
            return "coding_context"
        if work_cat == "Media":
            return "media_context"
        if prediction.get('focus_prediction') == 'high':
            return "coding_context"
        return "general_context"

    def _preload_coding_context(self):
        try:
            results = self.nerve.hippocampus.search_memory(
                self.nerve.gemini_key, "编程 代码 开发 项目 调试 bug", top_k=3
            )
            if results:
                now = time.time()
                ctx = "\n[ANTICIPATED CONTEXT - Preloaded based on your routine]:\n"
                for r in results:
                    age_hours = (now - r['timestamp']) / 3600
                    freshness = "RECENT" if age_hours < 24 else ("WEEK" if age_hours < 168 else "ARCHIVE")
                    ctx += f"- [{freshness}] {r['intent'][:100]} -> {r['summary'][:100]}\n"
                self._preloaded_context = ctx
                if hasattr(self.nerve, 'chat_bypass') and self.nerve.chat_bypass:
                    self.nerve.chat_bypass.last_ltm_context = (
                        getattr(self.nerve.chat_bypass, 'last_ltm_context', '') + ctx
                    )[-3000:]
        except Exception:
            pass

    def _preload_media_context(self):
        try:
            results = self.nerve.hippocampus.search_memory(
                self.nerve.gemini_key, "视频 音乐 娱乐 放松 休息", top_k=2
            )
            if results and hasattr(self.nerve, 'chat_bypass') and self.nerve.chat_bypass:
                ctx = "\n[ANTICIPATED]: " + "; ".join([r['summary'][:80] for r in results])
                self.nerve.chat_bypass.last_ltm_context = (
                    getattr(self.nerve.chat_bypass, 'last_ltm_context', '') + ctx
                )[-3000:]
        except Exception:
            pass

    def _preload_general_context(self):
        pass

    def get_preloaded_context(self) -> str:
        ctx = self._preloaded_context
        return ctx


class CorrectionLoop:
    def __init__(self, central_nerve):
        self.nerve = central_nerve
        self.correction_memory = CorrectionMemory()
        self.feedback_tracker = FeedbackTracker()
        self._last_user_input = ""
        self._last_jarvis_response = ""

    def on_user_input(self, user_input: str):
        if self._last_jarvis_response and self._last_user_input:
            signal = self.feedback_tracker.analyze_interaction(
                user_input, self._last_jarvis_response,
                stm_context="\n".join([
                    f"{m.get('user', '')} -> {m.get('jarvis', '')}"
                    for m in getattr(self.nerve, 'short_term_memory', [])[-6:]
                ])
            )

            if signal.signal_type == "correction":
                self._extract_and_store_correction(user_input)

        self._last_user_input = user_input

    def detect_and_learn(self, user_input: str, prev_response: str = "") -> dict:
        if not user_input:
            return None

        signal = self.feedback_tracker.analyze_interaction(
            user_input, prev_response or self._last_jarvis_response,
            stm_context="\n".join([
                f"{m.get('user', '')} -> {m.get('jarvis', '')}"
                for m in getattr(self.nerve, 'short_term_memory', [])[-6:]
            ])
        )

        result = None
        if signal.signal_type == "correction":
            self._extract_and_store_correction(user_input)
            result = {'type': 'correction', 'signal': signal.signal_type}
        elif signal.signal_type == "confusion":
            result = {'type': 'style', 'direction': 'more_clarity'}
        elif signal.signal_type == "positive":
            result = {'type': 'style', 'direction': 'maintain'}
        elif signal.signal_type == "follow_up":
            result = {'type': 'style', 'direction': 'more_detail'}

        # 🆕 [C3.1 tap / 2026-06-08] behavior-preserving: signal_type ∈
        # {correction, confusion} → 记一条 E_rel 债 (关系预测误差)。只新增记账,
        # 不改上面 result/signal 原逻辑/返回。ref = 当前 STM 末轮原文 hash (grounded:
        # 指回真实交互轮)。独立 try/except — 记账失败不影响 detect_and_learn。
        try:
            if signal.signal_type in ("correction", "confusion"):
                import hashlib as _hl
                _stm = getattr(self.nerve, 'short_term_memory', []) or []
                _last = _stm[-1] if _stm else {}
                _basis = (str(_last.get('user', '')) + '|' +
                          str(_last.get('jarvis', '')) + '|' +
                          str(_last.get('time', '')))
                _ref = _last.get('turn_id') or (
                    'stm_' + _hl.sha1(_basis.encode('utf-8')).hexdigest()[:12]
                    if _basis.strip('|') else '')
                if _ref:
                    from jarvis_coherence_debt import tap_correction
                    tap_correction(signal.signal_type, str(_ref),
                                   detail=user_input[:80])
        except Exception:
            pass

        return result

    def on_jarvis_response(self, response: str):
        self._last_jarvis_response = response

    def _extract_and_store_correction(self, correction_input: str):
        stm = getattr(self.nerve, 'short_term_memory', [])
        if len(stm) < 2:
            return

        trigger_context = stm[-2].get('user', '') if len(stm) >= 2 else ""
        wrong_response = stm[-2].get('jarvis', '') if len(stm) >= 2 else ""

        if not trigger_context or not wrong_response:
            return

        entry = CorrectionEntry(
            trigger_context=trigger_context,
            wrong_response=wrong_response,
            correction=correction_input,
            source_module="chat",
            confidence=0.8
        )
        self.correction_memory.record_correction(entry, self.nerve.key_router)

    def get_correction_context(self, current_input: str) -> str:
        return self.correction_memory.get_correction_prompt_block(
            current_input, self.nerve.key_router, max_results=3
        )

    def get_style_adjustment(self) -> str:
        adj = self.feedback_tracker.should_adjust_style()
        if adj['adjust']:
            return f"\n[STYLE ADJUSTMENT]: {adj['suggestion']}"
        return ""


class SleepIntentDetector:
    """多因子睡眠意图检测器：5因子评分 + 确认机制 + 睡后活动监督"""

    CONFIRM_THRESHOLD = 0.50
    SLEEP_THRESHOLD = 0.70
    COOLDOWN_SECONDS = 300
    POST_SLEEP_MONITOR_SECONDS = 600
    POST_SLEEP_CHECK_INTERVAL = 30

    def __init__(self, central_nerve):
        self.nerve = central_nerve
        self._last_detect_time = 0
        self._pending_confirmation = False
        self._sleep_confirmed_at = 0
        self._reminder_sent = False
        self._monitor_thread = None
        self._consecutive_short_inputs = 0

    def detect(self, user_input: str) -> str:
        """返回: 'sleep' (高置信直接睡), 'confirm' (中置信需确认), None (不触发)"""
        import re
        if not user_input:
            return None
        text = user_input.lower().strip()

        if len(text) < 4:
            self._consecutive_short_inputs += 1
            return None
        self._consecutive_short_inputs = 0

        active_patterns = [
            r'^(what|who|where|when|why|how|is|are|do|does|did|can|could|will|would|should|may|might|has|have|had)\s',
            r'^(你|我|他|她|它|这|那|什么|怎么|为什么|哪里|哪个|谁|多少|几|吗|呢|吧|啊|哦|哈|嗯|哎|喂)\s',
            r'^(so|please|ok|okay|yes|no|yeah|right|well|now|then|just|also|still|really|actually|maybe|perhaps)\s',
            r'^(对|是|好|行|可|不|没|有|要|想|会|能|让|给|帮|请|谢|麻|告|说|讲|问|查|找|搜|打|开|关|停|继|再|还|也|就|都|才|只|又|更|最|很|太|非|特|比|较|相|当|如|果|因|所|以|但|虽|然|而|且|或|与|和|跟|同|向|往|从|到|在|于|由|被|把|将|用|拿|按|照|按|根|据|关|关|于|对|对|于|为|为|了|除|除|了)\s',
            r'\[work_mode\]|\[wake_only\]|\[relax_mode\]',
        ]
        for pattern in active_patterns:
            if re.search(pattern, text):
                return None

        if time.time() - self._last_detect_time < self.COOLDOWN_SECONDS:
            return None

        scores = {}
        scores['semantic'] = self._factor_semantic(user_input)
        scores['keyword'] = self._factor_keyword(text)
        scores['time_of_day'] = self._factor_time_of_day()
        scores['activity_gap'] = self._factor_activity_gap()
        scores['input_trend'] = self._factor_input_trend()

        weights = {
            'semantic': 0.35,
            'keyword': 0.25,
            'time_of_day': 0.15,
            'activity_gap': 0.15,
            'input_trend': 0.10,
        }

        total = sum(scores[k] * weights[k] for k in scores)
        self._last_detect_time = time.time()

        print(f"[SleepDetector] Score={total:.2f} (sem={scores['semantic']:.2f} kw={scores['keyword']:.2f} "
              f"tod={scores['time_of_day']:.2f} gap={scores['activity_gap']:.2f} trend={scores['input_trend']:.2f})")

        # 🩹 [β.5.37-B / 2026-05-20] SleepDetector publish-only (Sir 14:39 校正 准则 6)
        # 不论 score 高/中/低, 都 publish 'sleep_intent_signal' 到 SWM 给主脑看自决.
        # 主脑看 SWM evidence 自决:
        #   - 高 score (>=0.70) 仍下行 hard 'sleep' 触发 _trigger_sleep_mode (Sir 真明确说了)
        #   - 中 score (0.50-0.70) 不再 set pending 状态, 主脑看到 signal 自决问不问 / 等不等
        #   - 低 score 也 publish 给主脑 awareness
        try:
            from jarvis_utils import get_event_bus as _geb
            _bus = _geb()
            if _bus is not None and total >= 0.3:
                _bus.publish(
                    etype='sleep_intent_signal',
                    description=(
                        f"score={total:.2f} sem={scores['semantic']:.2f} "
                        f"kw={scores['keyword']:.2f} tod={scores['time_of_day']:.2f}"
                    ),
                    source='SleepDetector',
                    salience=min(0.30 + total * 0.6, 0.95),
                    metadata={
                        'kind': 'sleep_intent',
                        'score': round(total, 2),
                        'breakdown': {k: round(v, 2) for k, v in scores.items()},
                        'user_input': user_input[:120],
                        'detected_at': self._last_detect_time,
                        'threshold_sleep': self.SLEEP_THRESHOLD,
                        'threshold_confirm': self.CONFIRM_THRESHOLD,
                    },
                )
        except Exception:
            pass

        if total >= self.SLEEP_THRESHOLD:
            return 'sleep'
        elif total >= self.CONFIRM_THRESHOLD:
            return 'confirm'
        return None

    def _factor_semantic(self, user_input: str) -> float:
        """因子1: 语义分类 (权重0.35) — 关键词前置过滤防止LLM幻觉"""
        import re
        text_lower = user_input.lower()
        sleep_keywords = [
            r'sleep', r'bed', r'tired', r'rest', r'nap', r'night', r'dream',
            r'睡', r'觉', r'困', r'累', r'休息', r'床', r'躺', r'眠',
            r'晚安', r'关灯', r'熄灯', r'明天见',
        ]
        has_any_keyword = any(re.search(kw, text_lower) for kw in sleep_keywords)
        if not has_any_keyword:
            return 0.0

        classifier = get_quick_classifier()
        if not classifier.is_available:
            return 0.0
        result = classifier.detect_sleep_intent(user_input)
        if result == 'sleep':
            return 1.0
        elif result == 'wake':
            return 0.0
        return 0.15

    def _factor_keyword(self, text: str) -> float:
        """因子2: 正则关键词匹配 (权重0.25) — 强/弱关键词分级"""
        import re
        strong_patterns = [
            r'(我去?睡(觉|了|啦|咯|吧|呀|哦|哈|喽))',
            r'(睡了|睡觉|晚安|good\s*night|night\s*night)',
            r'(上床|躺下|关灯|熄灯)',
            r'(i\'?m?\s*(going\s+to\s+)?(sleep|bed))',
            r'(i(\s+am)?\s+(need|want|have|got|gotta|should|must|will|gonna)(\s+to)?\s+(go\s+to\s+)?(sleep|bed|rest))',
            r'(我(需要|要|想|准备|打算|该|得|必须)(去)?(睡|休息|躺))',
        ]
        weak_patterns = [
            r'(困了|累了|休息了|去休息|要休息)',
            r'(明天见|明早|morning)',
            r'(i(\s+am|\'?m?)\s+tired)',
            r'(i\s+(need|want|have)\s+to\s+rest)',
        ]
        for p in strong_patterns:
            if re.search(p, text):
                return 1.0
        for p in weak_patterns:
            if re.search(p, text):
                return 0.6
        return 0.0

    def _factor_time_of_day(self) -> float:
        """因子3: 时间上下文 (权重0.15) — 凌晨/深夜加权"""
        hour = time.localtime().tm_hour
        if 0 <= hour < 6:
            return 0.9
        elif 22 <= hour < 24:
            return 0.7
        elif 6 <= hour < 8:
            return 0.3
        elif 21 <= hour < 22:
            return 0.3
        return 0.0

    def _factor_activity_gap(self) -> float:
        """因子4: 用户活跃度 (权重0.15) — 越久没动越像真要睡"""
        try:
            import win32api
            idle_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
            idle_sec = idle_ms / 1000.0
        except Exception:
            idle_sec = 0

        if idle_sec > 600:
            return 0.8
        elif idle_sec > 120:
            return 0.5
        elif idle_sec > 30:
            return 0.2
        return 0.0

    def _factor_input_trend(self) -> float:
        """因子5: 输入长度趋势 (权重0.10) — 连续短句可能是在敷衍/要睡了"""
        if self._consecutive_short_inputs >= 3:
            return 0.5
        return 0.0

    def handle_confirmation_response(self, user_input: str) -> bool:
        """处理用户对确认问题的回复, 返回 True 表示确认睡觉.
        
        ⚠️ [β.5.37-B / 2026-05-20 DEPRECATED] Sir 14:39 校正: 准则 6 publish-only 改造后
        本函数不再被 _detect_sleep_intent 调用. SleepDetector.detect publish 'sleep_intent_signal'
        到 SWM, 主脑看 evidence 自决问 Sir 或等待. 函数留作未来 backup, 当前 dead code.
        详 docs/JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md §4.1.
        """
        if not self._pending_confirmation:
            return False
        text = user_input.lower().strip()
        confirm_words = [
            'yes', 'yeah', 'yep', 'sure', 'ok', 'okay', 'right', 'go ahead',
            '对', '是', '好', '行', '嗯', '可以', '睡吧', '是的', '没错', '当然',
            'sleep', 'go to sleep', 'bed',
        ]
        deny_words = [
            'no', 'nope', 'not', 'wait', 'stop', 'cancel', 'never mind',
            '不', '别', '不要', '不用', '算了', '等等', '还没', '没有',
        ]
        for w in confirm_words:
            if w == text or text.startswith(w) or f' {w}' in text:
                self._pending_confirmation = False
                return True
        for w in deny_words:
            if w == text or text.startswith(w) or f' {w}' in text:
                self._pending_confirmation = False
                self._last_detect_time = time.time()
                print("[SleepDetector] 用户拒绝休眠模式，冷却时间重置")
                return False
        return False

    def request_confirmation(self):
        """中置信度时主动询问用户是否要进入睡眠模式"""
        self._pending_confirmation = True
        msg_en = "Sir, are you heading to rest? Shall I enter sleep mode?"
        msg_zh = "先生，您准备休息了吗？需要我进入睡眠模式吗？"
        print(f"\n║ 🌙 [SleepDetector] 休眠意图模糊，请求确认...")
        print(_box_newline(f"║ 🤖  [Jarvis] {msg_en}"))
        print(_box_newline(f"║ 📺  [Subtitle] {msg_zh}"))
        print("╚" + "═"*63 + "\n")

        try:
            if hasattr(self.nerve, 'chat_bypass') and hasattr(self.nerve.chat_bypass, 'subtitle_queue'):
                self.nerve.chat_bypass.subtitle_queue.put(("en", msg_en))
                self.nerve.chat_bypass.subtitle_queue.put(("zh", msg_zh))
            if hasattr(self.nerve, 'vocal'):
                import threading
                threading.Thread(target=self.nerve.vocal.say, args=(msg_en,), daemon=True).start()
        except Exception as e:
            print(f"[SleepDetector] 确认语音异常: {e}")

    def confirm_sleep(self):
        """确认进入睡眠后启动睡后活动监督"""
        self._sleep_confirmed_at = time.time()
        self._reminder_sent = False
        self._start_post_sleep_monitor()

    def _start_post_sleep_monitor(self):
        """启动后台线程监督睡后10分钟内是否有活动"""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        import threading
        self._monitor_thread = threading.Thread(target=self._post_sleep_monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _post_sleep_monitor_loop(self):
        """睡后监督循环: 每30秒检测一次用户活动, 2分钟后如果还在动就提醒.

        🆕 [β.5.46-fix13 Fix-1.2 / 2026-05-22] 起算点改 sleep_routine 真 fire.
        Sir 00:32 真测 (B9): "you said you were going to sleep 2 minutes ago, but
        I detect you are still active" — 但 Sir 根本没真睡, 是 dismissal 立刻进
        sleep_mode 后 2min 被这条假质疑打扰. 真凶: _sleep_confirmed_at = detect
        命中时, 不是 Sir 真睡时. 治本: 等 NudgeGate.is_sleep_routine_fired() 才算
        真睡, 用 fired_at 起算 elapsed.
        """
        print(f"[SleepDetector] 休眠后活动监控已启动 (将检查 {self.POST_SLEEP_MONITOR_SECONDS}秒)")
        start = time.time()
        while time.time() - start < self.POST_SLEEP_MONITOR_SECONDS:
            time.sleep(self.POST_SLEEP_CHECK_INTERVAL)
            if self._reminder_sent:
                return
            try:
                import win32api
                idle_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
            except Exception:
                continue
            if idle_ms < 5000:
                # 🆕 Fix-1.2: 看 NudgeGate routine fire evidence 决定起算
                _real_sleep_start = self._sleep_confirmed_at  # 默认 fallback
                try:
                    _gate_f12 = getattr(self.nerve, 'nudge_gate', None)
                    if _gate_f12 is not None and hasattr(_gate_f12, 'is_sleep_routine_fired'):
                        if not _gate_f12.is_sleep_routine_fired():
                            # routine 还没 fire = Sir 没真睡 = 不该 "你还在动" 质疑
                            try:
                                from jarvis_utils import bg_log as _bg_f12
                                _bg_f12(
                                    f"🛌 [PostSleepMonitor/Skip] routine 没 fire — "
                                    f"Sir 没真睡, 不质疑 'still active'"
                                )
                            except Exception:
                                pass
                            continue
                        # routine fire 后才算真睡 — 用 fired_at 起算
                        if hasattr(_gate_f12, 'sleep_routine_age_seconds'):
                            _age = _gate_f12.sleep_routine_age_seconds()
                            if _age > 0:
                                _real_sleep_start = time.time() - _age
                except Exception:
                    pass
                elapsed = time.time() - _real_sleep_start
                if elapsed > 120:
                    self._reminder_sent = True
                    self._dispatch_reminder(elapsed)
                    return
        print(f"[SleepDetector] 休眠后监控结束 (未检测到活动)")

    def _dispatch_reminder(self, elapsed_sec: float):
        """🩹 [β.2.9.1.4 / 2026-05-18] Sir 08:10 反馈: 主动质疑是 Jarvis 人设, 别删.
        撤回 β.2.9.1.3 的"改 bg_log only". 恢复 vocal.say. _reminder_sent 标志已经
        是单次保护 (line 1191), 但加 1h cooldown 防同一晚多次质疑."""
        minutes = int(elapsed_sec / 60)
        # 双保险: 1h 内只 fire 1 次
        if getattr(self, '_last_reminder_at', 0) > 0 and \
           (time.time() - self._last_reminder_at) < 3600:
            return
        self._last_reminder_at = time.time()

        msg_en = f"Sir, you said you were going to sleep {minutes} minutes ago, but I detect you are still active. Perhaps it is time to rest?"
        msg_zh = f"先生，{minutes}分钟前您说要睡觉了，但我检测到您还在活动。也许该休息了？"
        print(f"\n║ 🌙 [SleepDetector] 休眠后检测到活动，发送提醒...")
        print(_box_newline(f"║ 🤖  [Jarvis] {msg_en}"))
        print(_box_newline(f"║ 📺  [Subtitle] {msg_zh}"))
        print("╚" + "═"*63 + "\n")

        try:
            if hasattr(self.nerve, 'chat_bypass') and hasattr(self.nerve.chat_bypass, 'subtitle_queue'):
                self.nerve.chat_bypass.subtitle_queue.put(("en", msg_en))
                self.nerve.chat_bypass.subtitle_queue.put(("zh", msg_zh))
            if hasattr(self.nerve, 'vocal'):
                import threading
                threading.Thread(target=self.nerve.vocal.say, args=(msg_en,), daemon=True).start()
        except Exception as e:
            print(f"[SleepDetector] 提醒语音异常: {e}")

    @property
    def is_pending_confirmation(self) -> bool:
        return self._pending_confirmation


# [P0+19-final fix 5 / 2026-05-16] 全量跨模块类引用兜底（try/except 防循环依赖）
try:
    from jarvis_safety import *  # noqa: F401, F403
except Exception:
    pass
try:
    from jarvis_key_router import KeyRouter  # noqa: F401
except Exception:
    pass
try:
    from jarvis_llm_reflector import LlmReflector  # noqa: F401
except Exception:
    pass
try:
    from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401
except Exception:
    pass
try:
    from jarvis_sensors import (  # noqa: F401
        FunnelLogger, SensorFilter, HabitClock, CausalChain,
        ProjectTimeline, SubconsciousMailbox,
    )
except Exception:
    pass
try:
    from jarvis_routing import (  # noqa: F401
        SoulRouter, ContextRouter, ContentPreferenceTracker, ProfileCard,
        PromptCenter, GuardianCenter, CompanionCenter,
    )
except Exception:
    pass
try:
    from jarvis_memory_core import (  # noqa: F401
        PromptLayer, PromptCache, CorrectionEntry, CorrectionMemory,
        MemoryFragment, UnifiedMemoryGateway, FeedbackTracker,
        TaskWorkerPool, Anticipator, CorrectionLoop, SleepIntentDetector,
        HumorMemory,
    )
except Exception:
    pass
try:
    from jarvis_sentinels import (  # noqa: F401
        ChronosTick, ChronosSentinel, SystemSentinel, SoulArchivistSentinel,
        NudgeGate, UserStatusLedgerSentinel, ScreenshotSentinel,
        WellnessGuardian, ReflectionScheduler,
    )
except Exception:
    pass
try:
    from jarvis_conductor import Conductor  # noqa: F401
except Exception:
    pass
try:
    from jarvis_return_sentinel import ReturnSentinel  # noqa: F401
except Exception:
    pass
try:
    from jarvis_commitment_watcher import CommitmentWatcher  # noqa: F401
except Exception:
    pass
try:
    from jarvis_smart_nudge import SmartNudgeSentinel  # noqa: F401
except Exception:
    pass
try:
    from jarvis_chat_bypass import ChatBypass, _C3_ACTION_HAND_COMMANDS  # noqa: F401
except Exception:
    pass
try:
    from jarvis_blood import (  # noqa: F401
        JarvisBlood, ExecutionResult, FeedbackSignal, Action, PerceptionData, TaskSnapshot,
    )
except Exception:
    pass
try:
    from jarvis_hippocampus import Hippocampus  # noqa: F401
except Exception:
    pass
try:
    from jarvis_vocal_cord import VocalCord  # noqa: F401
except Exception:
    pass
try:
    from jarvis_enhanced import ProactiveShield, SkillTreeTracker, ProactiveCompanion  # noqa: F401
except Exception:
    pass
try:
    from jarvis_skill_registry import (  # noqa: F401
        SkillRegistry, SkillManifest, OfferGuard, PromiseExecutor, PromiseActivator,
        get_registry,
    )
except Exception:
    pass
try:
    from jarvis_utils import (  # noqa: F401
        bg_log, set_conversation_active, is_conversation_active,
        register_jarvis_tts, is_recent_jarvis_echo, clear_jarvis_tts_ring,
        safe_gemini_call, safe_openrouter_call, create_genai_client,
        get_local_fallback, QuickClassifier, get_quick_classifier,
        ConversationEventBus, JarvisState, PlanLedger, WorkingMemoryFeed,
        SessionDigest, ToneSelector, AntiCommonPhraseTracker,
        VerbosityPreferenceTracker, ProjectContextProbe,
        ClipboardWatcher, PSHistoryWatcher, AttentionSlot,
        render_yesterday_block, render_open_threads_block,
        render_active_reminders_block, render_attention_block,
        render_silent_nudge_text, render_project_block,
        extract_open_threads, capture_attention_snapshot,
        resolve_nudge_channel, network_retry, get_rate_limiter,
        get_default_attention_slot, get_default_event_bus,
        get_default_phrase_tracker, get_default_plan_ledger,
        get_default_tone_selector, get_default_verbosity_tracker,
        get_default_working_feed,
    )
except Exception:
    pass

