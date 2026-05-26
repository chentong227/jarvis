# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 18:54 真意 anchor FIX C] Runtime Log Marker Vocab Loader.

Sir 真意:
  "反思要看真日志, 终端省略了很多输出". InnerThought daemon 反思时拉
  docs/runtime_logs/latest.txt → resolve → tail → regex marker filter.

准则 6 vocab 驱动 (硬规):
  - 持久化: memory_pool/runtime_log_marker_vocab.json
  - CLI: scripts/runtime_log_marker_dump.py (Sir add/remove/propose/show)
  - TODO L7 reflector: jarvis_log_marker_reflector (Sir 拒过的 marker 自动学)

复用方:
  - jarvis_inner_thought_daemon._collect_runtime_log_tail (拉 log tail)
  - jarvis_inner_thought_daemon._ACTION_EVENT_PREFIXES (SWM filter)

设计 (准则 8 优雅):
  - 懒加载 + 单例 cache (避免每 tick read JSON)
  - vocab 改了 — _reload_if_changed() 监 mtime, 30s 间隔 throttle
  - JSON 缺失 / 损坏 → fallback 内置 DEFAULT_MARKERS (preserve daemon 可用)
  - 任何 IO error → silent return defaults
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import List, Tuple


# ==========================================================================
# Path
# ==========================================================================
DEFAULT_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool',
    'runtime_log_marker_vocab.json',
)


# ==========================================================================
# Fallback defaults (JSON 缺/损坏时用 - preserve daemon 可用)
# ==========================================================================
_DEFAULT_ACTION_EVENT_PREFIXES = (
    'proactive_nudge_',
    'inner_thought_',
    'concern_severity_changed',
    'concern_notes_appended',
    'promise_',
    'commitment_',
    'reminder_',
    'wake_',
    'sir_intent_',
    'stand_down_',
    'utterance_appended',
)

_DEFAULT_LOG_LINE_MARKERS = (
    '[Human]', '[Jarvis]', '[State]', '[JarvisState]',
    '__NUDGE__', '[Spinal Reflex]', '[ConcernFeedback',
    '[SOUL inject]', '[Prompt Tier]', '[L2 inject]', '[Tone]',
    '[ReturnSentinel', '[SmartNudge', '[Conductor',
    '[CommitmentWatcher', '[InnerThought', '[AutoArbiter',
    'fired', 'rejected', 'published', 'skipped', 'blocked',
    'Yield', 'commitment_check', 'reminder_fired',
)


# ==========================================================================
# Singleton cache + mtime throttle
# ==========================================================================
class _Cache:
    """Singleton cache for vocab data + mtime check."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._data: dict = {}
        self._mtime: float = 0.0
        self._last_check_ts: float = 0.0
        self._check_interval: float = 30.0
        self._marker_regex_cache = None  # compiled regex
        self._action_prefixes_cache: Tuple[str, ...] = ()

    def _load_from_disk(self, path: str) -> None:
        try:
            if not os.path.exists(path):
                self._data = {}
                return
            mtime = os.path.getmtime(path)
            if mtime == self._mtime and self._data:
                return
            with open(path, 'r', encoding='utf-8') as f:
                self._data = json.load(f)
            self._mtime = mtime
            # 清 regex cache (markers 可能改了)
            self._marker_regex_cache = None
            self._action_prefixes_cache = ()
        except Exception:
            # 损坏文件 → 不更新 data, 继续用上次 / fallback
            pass

    def ensure_loaded(self, path: str) -> None:
        """Throttled reload — 30s 一次 mtime check."""
        now = time.time()
        if now - self._last_check_ts < self._check_interval and self._data:
            return
        self._last_check_ts = now
        self._load_from_disk(path)

    def get_action_event_prefixes(self) -> Tuple[str, ...]:
        if self._action_prefixes_cache:
            return self._action_prefixes_cache
        prefixes = self._data.get('action_event_prefixes')
        if isinstance(prefixes, list) and prefixes:
            tup = tuple(str(p) for p in prefixes if p)
            self._action_prefixes_cache = tup
            return tup
        return _DEFAULT_ACTION_EVENT_PREFIXES

    def get_log_line_markers(self) -> Tuple[str, ...]:
        markers = self._data.get('log_line_markers')
        if isinstance(markers, list) and markers:
            return tuple(str(m) for m in markers if m)
        return _DEFAULT_LOG_LINE_MARKERS

    def get_marker_regex(self) -> re.Pattern:
        if self._marker_regex_cache is not None:
            return self._marker_regex_cache
        markers = self.get_log_line_markers()
        # 拼成 (m1|m2|m3) — escape 防 regex 元字符
        escaped = [re.escape(m) for m in markers]
        pattern = '(' + '|'.join(escaped) + ')'
        self._marker_regex_cache = re.compile(pattern)
        return self._marker_regex_cache


# ==========================================================================
# Public API
# ==========================================================================
def load_action_event_prefixes(path: str = DEFAULT_VOCAB_PATH) -> Tuple[str, ...]:
    """SWM event_bus filter 用 prefix 列 (jarvis 真行为 etype prefix)."""
    cache = _Cache()
    cache.ensure_loaded(path)
    return cache.get_action_event_prefixes()


def load_log_line_markers(path: str = DEFAULT_VOCAB_PATH) -> Tuple[str, ...]:
    """runtime_log tail filter 用 marker 列 (含 emoji tag / [Tag] / verb)."""
    cache = _Cache()
    cache.ensure_loaded(path)
    return cache.get_log_line_markers()


def load_marker_regex(path: str = DEFAULT_VOCAB_PATH) -> re.Pattern:
    """编译后的 marker regex (含全 markers OR 拼接), filter log lines 用."""
    cache = _Cache()
    cache.ensure_loaded(path)
    return cache.get_marker_regex()


def add_marker(marker: str, kind: str = 'log_line',
                path: str = DEFAULT_VOCAB_PATH,
                source: str = 'cli') -> bool:
    """CLI add — 加 marker (kind='log_line' / 'action_event_prefix').

    Returns True if added, False if dup or invalid.
    """
    if not marker or not marker.strip():
        return False
    marker = marker.strip()
    if kind not in ('log_line', 'action_event_prefix'):
        return False
    key = 'log_line_markers' if kind == 'log_line' else 'action_event_prefixes'
    try:
        if not os.path.exists(path):
            return False
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        lst = data.get(key) or []
        if marker in lst:
            return False
        lst.append(marker)
        data[key] = lst
        hist = data.get('history') or []
        hist.append({
            'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'op': 'add',
            'kind': kind,
            'marker': marker,
            'source': source,
        })
        data['history'] = hist
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # 让 cache 下次 ensure_loaded 强制重读 (reset throttle + mtime + regex cache)
        _c = _Cache()
        _c._mtime = 0.0
        _c._last_check_ts = 0.0
        _c._marker_regex_cache = None
        _c._action_prefixes_cache = ()
        return True
    except Exception:
        return False


def remove_marker(marker: str, kind: str = 'log_line',
                     path: str = DEFAULT_VOCAB_PATH,
                     source: str = 'cli') -> bool:
    """CLI remove — 删 marker."""
    if not marker or not marker.strip():
        return False
    marker = marker.strip()
    if kind not in ('log_line', 'action_event_prefix'):
        return False
    key = 'log_line_markers' if kind == 'log_line' else 'action_event_prefixes'
    try:
        if not os.path.exists(path):
            return False
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        lst = data.get(key) or []
        if marker not in lst:
            return False
        lst.remove(marker)
        data[key] = lst
        hist = data.get('history') or []
        hist.append({
            'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'op': 'remove',
            'kind': kind,
            'marker': marker,
            'source': source,
        })
        data['history'] = hist
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # 强制重读 (reset throttle + mtime + regex cache) — 同 add_marker
        _c = _Cache()
        _c._mtime = 0.0
        _c._last_check_ts = 0.0
        _c._marker_regex_cache = None
        _c._action_prefixes_cache = ()
        return True
    except Exception:
        return False


def list_all(path: str = DEFAULT_VOCAB_PATH) -> dict:
    """CLI list — 返完整 vocab data (含 history + review_queue)."""
    try:
        if not os.path.exists(path):
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}
