# -*- coding: utf-8 -*-
"""[P0+19-2 / 2026-05-16] LlmReflector — 共享 LLM 反思引擎

从 jarvis_nerve.py 拆出。设计原则：
- 单例（_instance 模式）
- 规则引擎实时检测 + LLM 定期语义反思
- 缓存确保相同数据不重复调用（200 entry，超过 LRU 淘汰）
- 模型分层：flash_lite (便宜) / flash (中等)
- 跨模块反思结果存储（reflection_store）

依赖：
- 标准库：hashlib / time / re / json
- jarvis_utils.safe_gemini_call
- jarvis_key_router.KeyRouter（用 CALLER_REFLECTOR 常量 + key release）

向后兼容：jarvis_nerve.py 用 `from jarvis_llm_reflector import LlmReflector` 转发。
"""

from __future__ import annotations

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


import hashlib
import time
import re
import json

from jarvis_utils import safe_gemini_call
from jarvis_key_router import KeyRouter


class LlmReflector:
    """共享 LLM 反思引擎：缓存、成本追踪、多模型分层
    
    设计原则：
    - 规则引擎做实时检测（快、免费）
    - LLM 做定期语义反思（慢、便宜、深刻）
    - 缓存确保相同数据不重复调用
    """
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, key_router=None):
        if self._initialized:
            return
        self._initialized = True
        
        self.key_router = key_router
        
        self._cache = {}
        self._cache_max_size = 200
        
        self._call_counts = {
            'flash_lite': 0,
            'flash': 0,
        }
        self._daily_reset_day = time.strftime('%Y-%m-%d')
        
        self._cost_per_1k = {
            'flash_lite': 0.00001875,
            'flash': 0.000075,
        }
        
        self._reflection_store = {}
    
    def set_key_router(self, key_router):
        self.key_router = key_router
    
    def _reset_daily_counts(self):
        current_day = time.strftime('%Y-%m-%d')
        if current_day != self._daily_reset_day:
            self._call_counts = {'flash_lite': 0, 'flash': 0}
            self._daily_reset_day = current_day
    
    def _cache_key(self, model: str, prompt: str) -> str:
        raw = f"{model}:{prompt}"
        return hashlib.md5(raw.encode('utf-8')).hexdigest()
    
    def reflect(self, model: str, system_prompt: str, user_prompt: str,
                force: bool = False, cache_ttl: int = 1800) -> dict:
        """统一 LLM 反思接口
        
        Args:
            model: 'flash_lite' | 'flash'
            system_prompt: 系统指令
            user_prompt: 用户数据
            force: 是否强制忽略缓存
            cache_ttl: 缓存有效期（秒）
        
        Returns:
            {'success': bool, 'result': dict|None, 'raw_text': str, 'cached': bool}
        """
        self._reset_daily_counts()
        
        cache_key = self._cache_key(model, system_prompt + user_prompt)
        
        if not force and cache_key in self._cache:
            entry = self._cache[cache_key]
            if time.time() - entry['time'] < cache_ttl:
                return {'success': True, 'result': entry['result'], 'raw_text': entry['raw_text'], 'cached': True}
        
        model_map = {
            'flash_lite': 'gemini-3.1-flash-lite',
            'flash': 'gemini-3-flash-preview',
        }
        model_name = model_map.get(model, 'gemini-3.1-flash-lite')
        
        try:
            def _call(client):
                return client.models.generate_content(
                    model=model_name,
                    contents=f"{system_prompt}\n\n{user_prompt}"
                )
            
            res, _key_name, _client = safe_gemini_call(
                self.key_router, KeyRouter.CALLER_REFLECTOR, model, _call,
                max_retries=3, base_delay=1.5,
                model_name=model_name, contents_text=f"{system_prompt}\n\n{user_prompt}"
            )
            self.key_router.release(_key_name)
            
            raw_text = res.text.strip()
            self._call_counts[model] = self._call_counts.get(model, 0) + 1
            
            match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            result = None
            if match:
                try:
                    result = json.loads(match.group(0))
                except json.JSONDecodeError:
                    result = None
            
            self._cache[cache_key] = {
                'time': time.time(),
                'result': result,
                'raw_text': raw_text
            }
            
            if len(self._cache) > self._cache_max_size:
                oldest = sorted(self._cache.items(), key=lambda x: x[1]['time'])[:50]
                for k, _ in oldest:
                    del self._cache[k]
            
            return {'success': True, 'result': result, 'raw_text': raw_text, 'cached': False}
            
        except Exception as e:
            print(f"[LlmReflector] {model} 调用失败: {e}")
            return {'success': False, 'result': None, 'raw_text': '', 'cached': False}
    
    def store_reflection(self, module: str, reflection_id: str, data: dict):
        """持久化存储反思结果，供跨会话引用"""
        if module not in self._reflection_store:
            self._reflection_store[module] = {}
        self._reflection_store[module][reflection_id] = {
            'data': data,
            'timestamp': time.time()
        }
        if len(self._reflection_store[module]) > 50:
            oldest = sorted(self._reflection_store[module].items(),
                          key=lambda x: x[1]['timestamp'])[:10]
            for k, _ in oldest:
                del self._reflection_store[module][k]
    
    def get_reflection(self, module: str, reflection_id: str) -> dict:
        return self._reflection_store.get(module, {}).get(reflection_id, {}).get('data')
    
    def get_daily_stats(self) -> dict:
        self._reset_daily_counts()
        total_cost = sum(
            self._call_counts.get(m, 0) * self._cost_per_1k.get(m, 0)
            for m in self._call_counts
        )
        return {
            'calls': dict(self._call_counts),
            'estimated_cost_usd': round(total_cost, 6),
            'cache_hits': len(self._cache),
        }


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
    from l1_right_brain import RightBrain  # noqa: F401
except Exception:
    pass
try:
    from l3_left_brain import LeftBrain  # noqa: F401
except Exception:
    pass
try:
    from l5_reflection_brain import ReflectionBrain  # noqa: F401
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

