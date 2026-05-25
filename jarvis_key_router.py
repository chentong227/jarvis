# -*- coding: utf-8 -*-
"""[P0+19-2 / 2026-05-16] KeyRouter — API Key 智能路由器

从 jarvis_nerve.py 拆出。设计原则：
- 主脑发声 (CALLER_MAIN_BRAIN) → 锁死 MAIN_BRAIN_KEY，绝不共享
- Google 通道：3 个 Google Key 随机抽，挂了换下一个
- OpenRouter 通道：N 个 Key 随机抽，挂了换下一个
- 同 Key 并发熔断：同一 Key 同时最多 N 个请求
- 启动诊断探针 (P0+18-b.5): probe_google_keys_at_startup 探测 3 Key 是否同 Project

依赖：
- 标准库：time / random / threading / hashlib
- 延迟 import：jarvis_utils.bg_log / create_genai_client
- 延迟 import：google.genai.types

向后兼容：jarvis_nerve.py 用 `from jarvis_key_router import KeyRouter` 转发，
旧 `from jarvis_nerve import KeyRouter` 0 改动。
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


import time
import random
import threading
import hashlib  # noqa: F401 — 内部函数 _cache_key 用


# 🆕 [P2 / Sir 2026-05-25 21:47] Token bucket — LOW priority 限速保护
class _TokenBucket:
    """简易 token bucket. capacity 个 token 容量, refill_per_sec 速率补 token.
    acquire(wait_max_s) 尝试取 1 token, 成功 True / timeout False.
    用于 KeyRouter LOW priority caller 限速, 防 daemon 失控压主流量.
    """

    def __init__(self, capacity: int, refill_per_sec: float):
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.refill_per_sec = float(refill_per_sec)
        self.last_refill = time.time()
        self._lock = threading.Lock()

    def acquire(self, wait_max_s: float = 5.0) -> bool:
        deadline = time.time() + max(0.0, wait_max_s)
        while True:
            with self._lock:
                now = time.time()
                elapsed = now - self.last_refill
                if elapsed > 0:
                    self.tokens = min(self.capacity,
                                       self.tokens + elapsed * self.refill_per_sec)
                    self.last_refill = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return True
            if time.time() >= deadline:
                return False
            time.sleep(0.1)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                'tokens': round(self.tokens, 2),
                'capacity': self.capacity,
                'refill_per_sec': self.refill_per_sec,
            }


class KeyRouter:
    """API Key 智能路由器：主脑隔离 + Google/OpenRouter 双通道独立随机池
    
    路由规则：
    1. 主脑发声 (CALLER_MAIN_BRAIN) → 锁死 MAIN_BRAIN_KEY，绝不共享
    2. Google 通道 → 3个Google Key随机抽 → 挂了换下一个
    3. OpenRouter 通道 → 3个OpenRouter Key随机抽 → 挂了换下一个
    4. safe_gemini_call 随机选通道 → 失败立刻切另一通道
    5. 同 Key 并发熔断：同一 Key 同时最多 N 个请求
    """
    
    CALLER_MAIN_BRAIN = 'main_brain'
    CALLER_SENTINEL = 'sentinel'
    CALLER_REFLECTOR = 'reflector'
    CALLER_HIPPOCAMPUS = 'hippocampus'
    CALLER_HANDS = 'hands'
    CALLER_GATEKEEPER = 'gatekeeper'
    # 🆕 [P1 / Sir 2026-05-25 22:10 数字生命基础] InnerThoughtDaemon caller
    # 不在 HIGH/MEDIUM 列表 → 自动 LOW priority + 30/min 限速 (P2 保护).
    CALLER_INNER_THOUGHT = 'inner_thought'
    # 🆕 [AA / Sir 2026-05-25 22:58 自决] AutoArbiterDaemon caller
    # 同 LOW priority + 30/min 限速 (后台 daemon, 不挤主流量).
    CALLER_AUTO_ARBITER = 'auto_arbiter'

    PROVIDER_GOOGLE = 'google'
    PROVIDER_OPENROUTER = 'openrouter'

    # 🆕 [P2 / Sir 2026-05-25 21:47 真测追根] Priority + OpenRouter Fallback + 限速
    # Sir 真痛点 (jarvis_20260525_*.log): google_1 SSL EOF (代理流量超) +
    # OpenRouter pool 4 key 闲置. 后台 daemon 失控可能压垮主对话 TTFT.
    # P2 治本: priority 分级 + 真 fallback + token bucket 限速 (准则 6/8).
    # 路线: P2 → P1 inner_thought daemon (Sir 数字生命 5min tick 真陪伴感).
    PRIORITY_HIGH = 'high'      # 主脑 / turn-time critical, 不限速, 优先 fallback
    PRIORITY_MEDIUM = 'medium'  # turn-time but tolerable, 不限速, 后置 fallback
    PRIORITY_LOW = 'low'        # 后台 daemon, 限速 30/min default, 不挤主流量

    # caller → 默认 priority 映射. 老 caller 不传 priority 即按此映射.
    # 不在表里的 caller 默认 LOW (后台 daemon / reflector 全 LOW).
    _PRIORITY_HIGH_CALLERS = frozenset({
        'main_brain',
        'gatekeeper',
        'reply_preflight',
    })
    _PRIORITY_MEDIUM_CALLERS = frozenset({
        'sentinel',
        'hippocampus',
        'predicate_parser',
        'soul_evaluator',
    })

    # LOW priority token bucket — 30 calls/min default. inner_thought 5min tick
    # 远低于这个 cap. ProactiveCare / L4-L7 reflector 周期 tick 加起来也不会超.
    _LOW_PRIORITY_RATE_PER_MIN = 30
    _LOW_PRIORITY_WAIT_TIMEOUT_S = 5.0
    
    def __init__(self, main_brain_key: str, google_keys: list, openrouter_keys: list):
        self._main_brain_key = main_brain_key
        
        self._google_pool = []
        for i, k in enumerate(google_keys):
            self._google_pool.append({'key': k, 'label': f'google_{i+1}'})
        
        self._openrouter_pool = []
        for i, k in enumerate(openrouter_keys):
            self._openrouter_pool.append({'key': k, 'label': f'openrouter_{i+1}'})
        
        self._active_calls = {}
        self._max_concurrent = {}
        self._key_status = {}
        
        self._init_key(main_brain_key, 'main_brain', self.PROVIDER_OPENROUTER, max_concurrent=5)
        for entry in self._google_pool:
            self._init_key(entry['key'], entry['label'], self.PROVIDER_GOOGLE, max_concurrent=3)
        for entry in self._openrouter_pool:
            self._init_key(entry['key'], entry['label'], self.PROVIDER_OPENROUTER, max_concurrent=10)
        
        self._lock = threading.Lock()
        self._error_cooldown = 300
        
        self._openrouter_alerted_today = False
        self._openrouter_alert_acknowledged = False
        self._openrouter_alert_date = ''
        self._openrouter_call_count_today = 0
        self._daily_reset_day = time.strftime('%Y-%m-%d')

        # 🆕 [P2 / Sir 2026-05-25 21:47] LOW priority token bucket — 30 calls/min
        # refill_per_sec = 30/60 = 0.5. capacity = 30 burst (短时允许 30 个并发后限速)
        self._low_priority_bucket = _TokenBucket(
            capacity=self._LOW_PRIORITY_RATE_PER_MIN,
            refill_per_sec=self._LOW_PRIORITY_RATE_PER_MIN / 60.0,
        )

        # 🆕 [P2 / Sir 2026-05-25 21:47] Fallback 统计 — Sir dashboard 看 fallback 真实生效情况
        self._fallback_stats = {
            'google_to_openrouter': 0,
            'openrouter_to_google': 0,
            'low_priority_rate_limited': 0,
            'low_priority_acquired': 0,
        }

        # 🩹 [P0+20-β.1.5 / 2026-05-16] 永久剔除持久化（治 B7）：
        # 旧版 α.2 只在内存里标 permanently_dead → 进程重启后又开始尝试 google_1，
        # 第一次 PROJECT_DENIED 又触发"标记不健康 + cooldown 5min"，每次启动都浪费一轮请求。
        # 新版：启动时从 memory_pool/key_router_state.json 载入；触发永久剔除时立即写盘。
        # 提供 reset_permanent_death(label) 让 Sir rotate key 后主动清除。
        try:
            self._load_permanent_death_state()
        except Exception as _e:
            try:
                from jarvis_utils import bg_log as _kr_bg
                _kr_bg(f"⚠️ [KeyRouter] 永久剔除状态载入失败（首次运行正常）: {_e}")
            except Exception:
                pass

        # 🆕 [P5-fix20-A1 / 2026-05-22] Sir 14:32 真测痛点修.
        # 启动 health snapshot daemon — 每 15s 把 get_stats() 写到 disk
        # (memory_pool/key_router_health.json), dashboard 进程读该文件即可
        # 实时显示 key 池状态. 进程隔离不让 dashboard 直接持 KeyRouter.
        try:
            self._snapshot_stop = threading.Event()
            self._snapshot_thread = threading.Thread(
                target=self._snapshot_daemon_loop,
                name='KeyRouterSnapshot',
                daemon=True,
            )
            self._snapshot_thread.start()
        except Exception:
            pass
    
    def _init_key(self, key: str, label: str, provider: str, max_concurrent: int):
        self._active_calls[key] = 0
        self._max_concurrent[key] = max_concurrent
        self._key_status[key] = {
            'healthy': True, 'error_count': 0, 'last_error': '', 'last_error_time': 0,
            'label': label, 'provider': provider,
            # [P0+20-α.2 / 2026-05-16] 永久剔除：连续 3 次 PROJECT_DENIED / 项目级不可恢复错误
            # → permanently_dead=True，不再 _auto_recover，下次启动还需 rotate key 才能恢复
            'permanently_dead': False,
            'permanent_death_count': 0,    # 累计 PROJECT_DENIED 次数（达到 3 触发永久剔除）
            'permanent_death_reason': '',
            'permanent_death_announced': False,  # 一次性提示：避免每次 _auto_recover 重复刷屏
        }
    
    def _reset_daily_counters(self):
        current_day = time.strftime('%Y-%m-%d')
        if current_day != self._daily_reset_day:
            self._daily_reset_day = current_day
            self._openrouter_alerted_today = False
            self._openrouter_alert_acknowledged = False
            self._openrouter_alert_date = ''
            self._openrouter_call_count_today = 0
    
    def _pick_from_pool(self, pool: list, provider: str) -> tuple:
        healthy = [e for e in pool if self._key_status[e['key']]['healthy']]
        if not healthy:
            return None, None
        random.shuffle(healthy)
        for entry in healthy:
            key = entry['key']
            if self._try_acquire(key):
                if provider == self.PROVIDER_OPENROUTER:
                    self._openrouter_call_count_today += 1
                return key, entry['label']
            for _ in range(3):
                time.sleep(0.1)
                if self._try_acquire(key):
                    if provider == self.PROVIDER_OPENROUTER:
                        self._openrouter_call_count_today += 1
                    return key, entry['label']
        return None, None
    
    def get_google_key(self, caller: str) -> tuple:
        """从 Google Key 池随机抽一个。返回 (key, key_name)。失败抛异常。"""
        self._reset_daily_counters()
        key, key_name = self._pick_from_pool(self._google_pool, self.PROVIDER_GOOGLE)
        if key:
            return key, key_name
        raise RuntimeError(f"[KeyRouter] 所有 Google Key 均不可用 (caller={caller})。")
    
    def get_openrouter_key(self, caller: str,
                            priority: Optional[str] = None) -> tuple:
        """从 OpenRouter Key 池随机抽一个。返回 (key, key_name)。失败抛异常。

        🆕 [P2 / Sir 2026-05-25 21:47] LOW priority 限速 (默认按 caller 推断).
        后台 daemon (reflector / inner_thought) 走此路径也限速 30/min, 不挤主流量.
        显式传 priority=PRIORITY_HIGH 可跳过限速.
        """
        self._reset_daily_counters()

        if priority is None:
            priority = self._default_priority(caller)

        # LOW priority 限速 — 后台 daemon 不挤主流量
        if priority == self.PRIORITY_LOW:
            if not self._low_priority_bucket.acquire(
                    wait_max_s=self._LOW_PRIORITY_WAIT_TIMEOUT_S):
                self._fallback_stats['low_priority_rate_limited'] += 1
                raise RuntimeError(
                    f"[KeyRouter] LOW priority 限速命中 (caller={caller}, "
                    f"{self._LOW_PRIORITY_RATE_PER_MIN}/min 上限)."
                )
            self._fallback_stats['low_priority_acquired'] += 1

        key, key_name = self._pick_from_pool(self._openrouter_pool, self.PROVIDER_OPENROUTER)
        if key:
            return key, key_name
        raise RuntimeError(f"[KeyRouter] 所有 OpenRouter Key 均不可用 (caller={caller})。")
    
    def _default_priority(self, caller: str) -> str:
        """🆕 [P2 / Sir 2026-05-25 21:47] caller → 默认 priority 推断.

        老 caller 不传 priority 即按此函数推断 (向后兼容, 不破现有调用).
        - 主脑 / Gatekeeper / reply_preflight → HIGH
        - Sentinel / Hippocampus / predicate / soul_evaluator → MEDIUM
        - 其他 (后台 reflector / inner_thought 等) → LOW (默认限速 30/min)
        """
        c = (caller or '').strip()
        if c in self._PRIORITY_HIGH_CALLERS:
            return self.PRIORITY_HIGH
        if c in self._PRIORITY_MEDIUM_CALLERS:
            return self.PRIORITY_MEDIUM
        return self.PRIORITY_LOW

    def get_key(self, caller: str, model_tier: str = 'flash_lite',
                allow_openrouter_fallback: bool = True,
                priority: Optional[str] = None) -> tuple:
        """🆕 [P2 / Sir 2026-05-25 21:47] 路由 + Priority + OpenRouter Fallback + 限速.

        参数:
          caller: 调用方标识 (e.g. CALLER_MAIN_BRAIN / CALLER_GATEKEEPER / 'reply_preflight').
          model_tier: 模型档 ('flash_lite' / 'flash' / 'pro').
          allow_openrouter_fallback: Google pool 全不可用时是否 fallback OpenRouter (P2 真启用).
          priority: 显式覆盖 priority. None 时按 caller 自动推断.
            - HIGH:  不限速, google → openrouter fallback 立即.
            - MEDIUM: 不限速, fallback 但后置.
            - LOW:   限速 30/min token bucket. 超 → wait 5s 仍无 token raise.

        返回 (key, key_name, provider). 失败抛 RuntimeError.

        ⚠️ 主脑 (CALLER_MAIN_BRAIN) 永远锁死 main_brain_key, 不受 priority 影响.
        """
        self._reset_daily_counters()

        # 推断 priority (老 caller 不传时)
        if priority is None:
            priority = self._default_priority(caller)

        # 主脑路径 — 锁死 main_brain_key, priority 永远 HIGH 不限速
        if caller == self.CALLER_MAIN_BRAIN:
            if self._key_status[self._main_brain_key]['healthy']:
                if self._try_acquire(self._main_brain_key):
                    return self._main_brain_key, 'main_brain', self.PROVIDER_OPENROUTER
            raise RuntimeError(
                f"[KeyRouter] 主脑 Key 不可用 (caller={caller})。"
                f"healthy={self._key_status[self._main_brain_key]['healthy']}, "
                f"并发={self._active_calls[self._main_brain_key]}/{self._max_concurrent[self._main_brain_key]}"
            )

        # LOW priority 限速 — 后台 daemon 不挤主流量
        if priority == self.PRIORITY_LOW:
            if not self._low_priority_bucket.acquire(
                    wait_max_s=self._LOW_PRIORITY_WAIT_TIMEOUT_S):
                self._fallback_stats['low_priority_rate_limited'] += 1
                raise RuntimeError(
                    f"[KeyRouter] LOW priority 限速命中 (caller={caller}, "
                    f"{self._LOW_PRIORITY_RATE_PER_MIN}/min 上限). "
                    f"等 {self._LOW_PRIORITY_WAIT_TIMEOUT_S}s 仍无 token. "
                    f"后台 daemon 频率过高?"
                )
            self._fallback_stats['low_priority_acquired'] += 1

        # 优先池: Google
        key, key_name = self._pick_from_pool(self._google_pool, self.PROVIDER_GOOGLE)
        if key:
            return key, key_name, self.PROVIDER_GOOGLE

        # 🆕 [P2] Fallback OpenRouter pool (真启用! 老逻辑 allow_openrouter_fallback 参数没真用)
        if allow_openrouter_fallback and self._openrouter_pool:
            key, key_name = self._pick_from_pool(
                self._openrouter_pool, self.PROVIDER_OPENROUTER)
            if key:
                self._fallback_stats['google_to_openrouter'] += 1
                try:
                    from jarvis_utils import bg_log as _kr_bg
                    _kr_bg(
                        f"♻️ [KeyRouter/Fallback] {caller} (priority={priority}) "
                        f"Google 全挂 → OpenRouter {key_name}"
                    )
                except Exception:
                    pass
                return key, key_name, self.PROVIDER_OPENROUTER

        raise RuntimeError(
            f"[KeyRouter] 所有 key 池均不可用 (caller={caller}, priority={priority}, "
            f"allow_or_fallback={allow_openrouter_fallback})."
        )
    
    def _try_acquire(self, key: str) -> bool:
        with self._lock:
            if self._active_calls[key] < self._max_concurrent[key]:
                self._active_calls[key] += 1
                return True
            return False
    
    def release(self, key_name: str):
        key = self._resolve_key(key_name)
        if key:
            with self._lock:
                if self._active_calls[key] > 0:
                    self._active_calls[key] -= 1
    
    def _resolve_key(self, key_name: str):
        if key_name == 'main_brain':
            return self._main_brain_key
        for entry in self._google_pool + self._openrouter_pool:
            if entry['label'] == key_name:
                return entry['key']
        if key_name in self._key_status:
            return key_name
        return None
    
    def report_error(self, key_name: str, error_msg: str):
        # [P0+18-c.5 / 2026-05-15] 修 b.4 没修透的回归：
        # 旧版 PROJECT_DENIED / 403 / permission_denied 这种"立刻不可恢复"的错误
        # 不在 is_billing_error 关键词集 → 需要累计 3 次才标 unhealthy → google_1 第一次
        # 失败后仍 healthy=True → KeyRouter random 池里仍把 google_1 当候选 → hippocampus
        # _embed_with_rotation 第二轮又抽到 google_1 → tried_labels 命中 break → "只试 1/3
        # 就熔断" 假象。
        # 修法：把"权限/项目级不可恢复"错误归到"立即标不健康"类（不需要重试 3 次）。
        key = self._resolve_key(key_name)
        if not key:
            return

        # 🆕 [P5-fix21-a / 2026-05-22] label vs error provider 一致性 check
        # Sir 14:50 真测痛点: log 里 "[KeyRouter] google_1 标记为不健康
        # (错误: [OpenRouter] API Key 无效或已过期 (401))" — Google pool 的 key
        # 被 OpenRouter 的错误污染, 导致健康 Google key 误标 unhealthy.
        # caller 报错时若 label 在 google pool 但 error_msg 头含 "[OpenRouter]"
        # → 这是 caller 报错归类 BUG, 我们 defensive: log warn + skip 标记,
        # 真正的 OpenRouter key 由它自己的 caller 路径报.
        try:
            err_head = error_msg[:80].lower()
            label_lower = (key_name or '').lower()
            in_google_pool = label_lower.startswith('google_')
            in_openrouter_pool = label_lower.startswith('openrouter_')
            error_says_openrouter = '[openrouter]' in err_head or 'openrouter' in err_head[:30]
            error_says_google_only = ('project_denied' in err_head or
                                          'project has been denied' in err_head or
                                          'aistudio' in err_head)
            mismatch = False
            mismatch_reason = ''
            if in_google_pool and error_says_openrouter:
                mismatch = True
                mismatch_reason = (f'caller report google label but error msg cites '
                                       f'[OpenRouter] — likely caller mis-routed')
            elif in_openrouter_pool and error_says_google_only:
                mismatch = True
                mismatch_reason = (f'caller report openrouter label but error msg cites '
                                       f'Google project_denied/aistudio — likely mis-routed')
            if mismatch:
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"⚠️ [KeyRouter/MisroutedError] skip mark unhealthy: "
                           f"label={key_name} but error head='{error_msg[:60]}'. "
                           f"{mismatch_reason}. caller bug — fix upstream report_error()")
                except Exception:
                    pass
                # publish ErrorBus 让 Sir Dashboard 看到 caller bug
                try:
                    from jarvis_error_bus import report_error as _eb_report, SEVERITY_LOW
                    _eb_report(
                        module='key_router',
                        kind='misrouted_error_skip',
                        detail=f'label={key_name} err_head={error_msg[:80]}',
                        severity=SEVERITY_LOW,
                        recoverable=True,
                    )
                except Exception:
                    pass
                return  # 不标 unhealthy
        except Exception:
            pass  # defensive 失败别破坏 report_error 主路径
        now = time.time()
        status = self._key_status[key]
        status['error_count'] += 1
        status['last_error'] = error_msg[:200]
        status['last_error_time'] = now
        
        err_lower = error_msg.lower()
        is_billing_error = any(kw in err_lower for kw in [
            'billing', 'quota', 'exceeded', '429', 'resource_exhausted',
            'payment', 'insufficient', 'disabled', 'deactivated',
            'limit', 'rate', 'capacity', '400', 'invalid_argument',
            'api key not valid', 'api_key_invalid'
        ])
        # [P0+18-c.5] 权限/项目级错误：一次失败就标不健康
        is_permission_error = any(kw in err_lower for kw in [
            'permission_denied', 'permission denied',
            'project has been denied', 'project_denied',
            '403', '401', 'unauthorized', 'forbidden',
        ])
        # 🆕 [Sir 2026-05-25 19:57 真测追根 BUG 治本] 网络层 vs key 级错误隔离
        # =====================================================================
        # 源 BUG: Sir 真测 'EOF occurred in violation of protocol (_ssl.c:1129)'
        # 不是 key 失效, 是网络层 TLS 错误 (Sir 后确认: 代理流量超). 老逻辑
        # error_count >= 3 即标 unhealthy → 网络抖动 3 次冤枉 key. Sir 真问
        # 'key 全炸是 Sir 问题还是代码问题' — 答 = Sir 代理 + 代码也该区分.
        # 治本: 识别网络层错误, 不计入 unhealthy 阈值, 短期 cooldown 重试即可.
        # 准则 6 evidence-driven: key 级 (401/403/billing) vs 网络级独立计数.
        # =====================================================================
        is_network_error = any(kw in err_lower for kw in [
            'eof occurred in violation of protocol',  # SSL handshake 中断
            '_ssl.c:',                                 # OpenSSL 错误层
            'ssl: ',                                   # 通用 SSL 错误前缀
            'connection reset', 'connection aborted',  # TCP RST/abort
            'connection refused', 'connection error',  # TCP 拒绝 / 通用
            'broken pipe', 'remote end closed',        # socket EPIPE / 远端断
            'read timed out', 'write timed out',       # socket 读写超时
            'apitimeouterror', 'request timed out',    # OpenAI/Anthropic SDK
            'temporary failure in name resolution',    # DNS 临时失败
            'name or service not known',               # DNS 解析失败
            'getaddrinfo failed',                      # DNS 解析失败 (Windows)
            'network is unreachable',                  # 网络不可达
            'no route to host',                        # 无路由
            'max retries exceeded',                    # urllib3 重试耗尽
            'proxyerror', 'proxy error',               # 代理错误 (Sir 真因)
            'tunnel connection failed',                # 代理隧道失败
        ])

        # [P0+20-α.2 / 2026-05-16] 永久死亡判定：项目级错误累计 3 次 → 不再 auto_recover
        # 解决 jarvis_20260516_092307.log 中 google_1 PROJECT_DENIED 每轮对话刷屏问题：
        # 旧版每 5min auto_recover 一次，然后下次请求又失败又标 unhealthy → 死循环。
        # 永久死亡后：① 不再 spawn _auto_recover；② Hippocampus 等下游静默跳过；
        # ③ Sir 一次性提示（rotate key 后重启才能恢复）。
        if is_permission_error:
            status['permanent_death_count'] += 1
            if status['permanent_death_count'] >= 3 and not status['permanently_dead']:
                status['permanently_dead'] = True
                status['permanent_death_reason'] = error_msg[:200]
                label = status['label']
                # 一次性提示：醒目格式 + 写日志（不污染对话框）
                if not status['permanent_death_announced']:
                    status['permanent_death_announced'] = True
                    msg = (
                        f"⛔ [KeyRouter PERMANENT] {label} 已永久剔除（累计 3 次 PROJECT_DENIED / 403）。"
                        f" 下次启动前请 rotate key (https://aistudio.google.com/apikey) 并填 .env。"
                        f" 当前剩余健康 key 数 = {sum(1 for s in self._key_status.values() if s.get('healthy', False))}/{len(self._key_status)}。"
                    )
                    try:
                        from jarvis_utils import bg_log
                        bg_log(msg)
                    except Exception:
                        print(msg)
                # 🩹 [P0+20-β.1.5 / 2026-05-16] 立即写盘（治 B7）
                try:
                    self._save_permanent_death_state()
                except Exception:
                    pass

        # 🆕 [Sir 2026-05-25 19:57] 网络层错误回退 error_count, 不冤枉 key
        # 网络抖动 (SSL EOF / proxy / DNS / timeout) 不该累计为"key 失效"证据.
        # 仍 spawn short cooldown 短期重试 (60s), 但 healthy=True 不变, key 不退役.
        if is_network_error and not is_billing_error and not is_permission_error:
            # 网络错误回退本次 +1, 让 error_count 净增 0
            status['error_count'] = max(0, status['error_count'] - 1)
            try:
                from jarvis_utils import bg_log
                bg_log(f"🌐 [KeyRouter/Network] {status['label']} 网络层错误 "
                       f"(error_count 不累加 unhealthy): {error_msg[:80]}")
            except Exception:
                pass
            # 🆕 [P2 / Sir 2026-05-25 21:47] 仍 spawn _auto_recover 让 short cooldown
            # 走一遍, 但 healthy=True 不变. P2 修法: OpenRouter pool 也走 auto_recover
            # (老逻辑仅 google, OpenRouter SSL EOF 后没 cooldown 重试 → fallback 路径
            # 反复 retry 同一坏 key 浪费 quota).
            threading.Thread(target=self._auto_recover, args=(key,), daemon=True).start()
            return

        if is_billing_error or is_permission_error or status['error_count'] >= 3:
            status['healthy'] = False
            label = status['label']
            # [P0+20-α.2 / 2026-05-16] 标 unhealthy 的日志降级：
            # 永久死亡的不再每次刷"标记为不健康"（已经一次性提示过），减少日志噪音；
            # 暂时不健康的仍打一行 bg_log（方便 grep 调试）。
            if not status['permanently_dead']:
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"[KeyRouter] {label} 标记为不健康 (错误: {error_msg[:80]})")
                except Exception:
                    pass  # 不再 print 污染对话框

            # 永久死亡的 key 不 spawn _auto_recover（避免死循环）
            # 🆕 [P2 / Sir 2026-05-25 21:47] OpenRouter pool 也走 auto_recover
            # (老逻辑仅 google, OpenRouter 标 unhealthy 后永远不恢复).
            if not status['permanently_dead']:
                threading.Thread(target=self._auto_recover, args=(key,), daemon=True).start()
    
    def _auto_recover(self, key: str):
        time.sleep(self._error_cooldown)
        status = self._key_status[key]
        # [P0+20-α.2 / 2026-05-16] 永久死亡的 key 不参与恢复（双保险，spawn 时已经 skip 过一次）
        if status.get('permanently_dead', False):
            return
        status['healthy'] = True
        status['error_count'] = 0
        label = status['label']
        try:
            from jarvis_utils import bg_log
            bg_log(f"[KeyRouter] {label} 冷却结束，已自动恢复")
        except Exception:
            pass  # 不再 print 污染对话框

    def is_permanently_dead(self, key_or_label) -> bool:
        """[P0+20-α.2 / 2026-05-16] 下游模块（Hippocampus 等）查询某 key 是否永久死亡。
        
        参数可以是 key 字符串本身或 label（'google_1' 等）。
        """
        key = self._resolve_key(key_or_label) if not key_or_label.startswith('sk-') and not key_or_label.startswith('AIzaSy') else key_or_label
        if not key or key not in self._key_status:
            return False
        return self._key_status[key].get('permanently_dead', False)

    # ============================================================
    # 🩹 [P0+20-β.1.5 / 2026-05-16] 永久剔除持久化
    # ============================================================
    _STATE_FILE_PATH = 'memory_pool/key_router_state.json'

    def _load_permanent_death_state(self):
        """启动时从 disk 载入永久死亡 key list，恢复 _key_status 标记。"""
        import os as _os
        import json as _json
        if not _os.path.exists(self._STATE_FILE_PATH):
            return
        try:
            with open(self._STATE_FILE_PATH, 'r', encoding='utf-8') as f:
                payload = _json.load(f) or {}
        except Exception:
            return
        dead_dict = payload.get('permanently_dead') or {}
        if not isinstance(dead_dict, dict) or not dead_dict:
            return
        restored = []
        for label, info in dead_dict.items():
            if not isinstance(label, str) or not isinstance(info, dict):
                continue
            key = self._resolve_key(label)
            if not key or key not in self._key_status:
                continue
            status = self._key_status[key]
            status['permanently_dead'] = True
            status['permanent_death_count'] = max(int(info.get('count', 3)), 3)
            status['permanent_death_reason'] = str(info.get('reason', ''))[:200]
            status['permanent_death_announced'] = True
            status['healthy'] = False
            restored.append(label)
        if restored:
            try:
                from jarvis_utils import bg_log as _kr_bg
                _kr_bg(
                    f"⛔ [KeyRouter PERMANENT/Restored] 从 disk 恢复永久剔除 keys: {restored}。"
                    f" rotate key + 调 reset_permanent_death() 可清除。"
                )
            except Exception:
                pass

    def _save_permanent_death_state(self):
        """把当前永久死亡 key list 写到 disk（atomic write）。"""
        import os as _os
        import json as _json
        try:
            _os.makedirs(_os.path.dirname(self._STATE_FILE_PATH), exist_ok=True)
        except Exception:
            pass
        dead_dict = {}
        for key, status in self._key_status.items():
            if status.get('permanently_dead', False):
                dead_dict[status['label']] = {
                    'reason': status.get('permanent_death_reason', ''),
                    'count': status.get('permanent_death_count', 3),
                    'since_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
                }
        payload = {'permanently_dead': dead_dict}
        try:
            tmp_path = self._STATE_FILE_PATH + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as f:
                _json.dump(payload, f, ensure_ascii=False, indent=2)
            _os.replace(tmp_path, self._STATE_FILE_PATH)
        except Exception as _e:
            try:
                from jarvis_utils import bg_log as _kr_bg
                _kr_bg(f"⚠️ [KeyRouter] 永久剔除状态写盘失败: {_e}")
            except Exception:
                pass

    def reset_permanent_death(self, label: str) -> bool:
        """Sir rotate key 后主动调用清除某 label 的永久死亡标记。

        返回 True 表示成功清除并重写 disk。
        """
        key = self._resolve_key(label)
        if not key or key not in self._key_status:
            return False
        with self._lock:
            status = self._key_status[key]
            if not status.get('permanently_dead', False):
                return False
            status['permanently_dead'] = False
            status['permanent_death_count'] = 0
            status['permanent_death_reason'] = ''
            status['permanent_death_announced'] = False
            status['healthy'] = True
            status['error_count'] = 0
        self._save_permanent_death_state()
        try:
            from jarvis_utils import bg_log as _kr_bg
            _kr_bg(f"✅ [KeyRouter] {label} 永久剔除标记已清除（Sir rotate 后调用）。")
        except Exception:
            pass
        return True
    
    def is_openrouter_active(self) -> bool:
        return self._openrouter_call_count_today > 0
    
    def get_openrouter_alert(self) -> str:
        self._reset_daily_counters()
        if not self.is_openrouter_active():
            return ''
        if self._openrouter_alert_acknowledged:
            return ''
        if self._openrouter_alerted_today:
            return ''
        self._openrouter_alerted_today = True
        return (
            f"[SYSTEM ALERT] Jarvis 正在使用 OpenRouter 作为 API 后端 "
            f"(今日 {self._openrouter_call_count_today} 次调用)。 "
            f"部分 Google API Key 可能存在配额问题。 "
            f"回复 '我知道了' 来关闭今日提醒。"
        )
    
    def acknowledge_openrouter_alert(self):
        self._openrouter_alert_acknowledged = True
        self._openrouter_alert_date = time.strftime('%Y-%m-%d')
    
    def get_stats(self) -> dict:
        self._reset_daily_counters()
        # 🆕 [P5-fix20-A1 / 2026-05-22] Sir 14:32 真测发现 root cause:
        # OpenRouter 全挂 + Google 池 429 → IntentResolver/Vision/Hippocampus 全降级,
        # 主脑能开口但子系统 0 mutation → "嘴上说没真做". get_stats 扩展加 cooldown /
        # permanent_death / last_error / pool_summary, 让 dashboard 一眼看 key 池状态.
        now = time.time()
        key_status = {}
        for k, v in self._key_status.items():
            label = v['label']
            # cooldown 还剩几秒 (only for unhealthy + auto_recover-able + not permanent)
            cooldown_remaining = 0
            if (not v['healthy'] and not v.get('permanently_dead', False)
                    and v['provider'] == self.PROVIDER_GOOGLE):
                last_err_t = v.get('last_error_time', 0) or 0
                if last_err_t > 0:
                    elapsed = now - last_err_t
                    cooldown_remaining = max(0, int(self._error_cooldown - elapsed))
            key_status[label] = {
                'healthy': v['healthy'],
                'errors': v['error_count'],
                'provider': v['provider'],
                'permanently_dead': v.get('permanently_dead', False),
                'permanent_death_count': v.get('permanent_death_count', 0),
                'permanent_death_reason': v.get('permanent_death_reason', '')[:120],
                'last_error': v.get('last_error', '')[:200],
                'last_error_time': v.get('last_error_time', 0),
                'cooldown_remaining_s': cooldown_remaining,
                'in_cooldown': cooldown_remaining > 0,
            }

        # 池级 summary — Sir 一眼看哪个池挂了
        pools = {
            'main_brain': {'total': 1, 'healthy': 0, 'unhealthy': 0,
                            'permanent_dead': 0, 'in_cooldown': 0},
            'google': {'total': len(self._google_pool), 'healthy': 0,
                        'unhealthy': 0, 'permanent_dead': 0, 'in_cooldown': 0},
            'openrouter': {'total': len(self._openrouter_pool), 'healthy': 0,
                            'unhealthy': 0, 'permanent_dead': 0, 'in_cooldown': 0},
        }
        for label, st in key_status.items():
            if label == 'main_brain':
                bucket = 'main_brain'
            elif label.startswith('google_'):
                bucket = 'google'
            elif label.startswith('openrouter_'):
                bucket = 'openrouter'
            else:
                continue
            if st['healthy']:
                pools[bucket]['healthy'] += 1
            else:
                pools[bucket]['unhealthy'] += 1
            if st['permanently_dead']:
                pools[bucket]['permanent_dead'] += 1
            if st['in_cooldown']:
                pools[bucket]['in_cooldown'] += 1

        # 整体健康度 (worst pool 决定整体)
        any_total_dead = any(
            p['total'] > 0 and p['healthy'] == 0
            for p in pools.values()
        )
        any_partial = any(
            p['total'] > 0 and 0 < p['healthy'] < p['total']
            for p in pools.values()
        )
        overall = 'crit' if any_total_dead else ('warn' if any_partial else 'ok')

        return {
            'openrouter_calls_today': self._openrouter_call_count_today,
            'key_status': key_status,
            'active_calls': {
                self._key_status[k]['label']: v
                for k, v in self._active_calls.items()
            },
            'pools': pools,
            'overall_health': overall,
            # 🆕 [P2 / Sir 2026-05-25 21:47] Priority + Fallback 真实生效统计
            'priority_stats': dict(self._fallback_stats),
            'low_priority_bucket': self._low_priority_bucket.snapshot(),
        }

    def reset_cooldown(self, label: str) -> bool:
        """🆕 [P5-fix20-A2 / 2026-05-22] Sir 一键强制结束 cooldown.

        把 last_error_time 清零 → cooldown 立刻视为结束 → 下次 _pick_from_pool
        会跳过 (因为 healthy=False), 但 _auto_recover thread 仍会按时执行.
        Sir 想立刻复活 → reset_cooldown 后调 _force_healthy.

        Returns: True 成功, False 不存在 / 永久死亡 (要 reset_permanent_death).
        """
        key = self._resolve_key(label)
        if not key or key not in self._key_status:
            return False
        with self._lock:
            status = self._key_status[key]
            if status.get('permanently_dead', False):
                return False  # permanent dead 要走 reset_permanent_death
            status['healthy'] = True
            status['error_count'] = 0
            status['last_error'] = ''
            status['last_error_time'] = 0
        try:
            from jarvis_utils import bg_log as _kr_bg
            _kr_bg(f"✅ [KeyRouter] {label} cooldown 已强制结束 (Sir 手动 reset)")
        except Exception:
            pass
        return True

    # 🆕 [P5-fix20-A1 / 2026-05-22] health snapshot daemon
    _HEALTH_SNAPSHOT_PATH = 'memory_pool/key_router_health.json'
    _RESET_REQUEST_PATH = 'memory_pool/key_router_reset_request.json'
    _RESET_AUDIT_PATH = 'memory_pool/key_router_reset_audit.jsonl'
    _HEALTH_SNAPSHOT_INTERVAL_S = 15.0
    _RESET_POLL_INTERVAL_S = 5.0  # reset 比 snapshot 快, 让 Sir 一键能 ≤5s 看到结果

    def _snapshot_daemon_loop(self):
        """每 15s 写 health snapshot + 每 5s poll reset_request.

        合并到同一 thread 省资源. snapshot 间隔较大 (state 变化慢),
        reset 必须响应快 (Sir 等结果). 用 _snapshot_stop.wait 做 interruptible sleep.
        """
        last_snapshot_ts = 0.0
        while not self._snapshot_stop.is_set():
            now = time.time()
            # poll reset request (高频)
            try:
                self._poll_reset_request()
            except Exception:
                pass
            # snapshot (低频)
            if (now - last_snapshot_ts) >= self._HEALTH_SNAPSHOT_INTERVAL_S:
                try:
                    self._write_health_snapshot()
                    last_snapshot_ts = now
                except Exception:
                    pass
            # interruptible sleep
            self._snapshot_stop.wait(self._RESET_POLL_INTERVAL_S)

    def _write_health_snapshot(self):
        """写 health snapshot 到 disk (子函数, 让 _snapshot_daemon_loop 干净)."""
        import os as _os
        import json as _json
        path = self._HEALTH_SNAPSHOT_PATH
        stats = self.get_stats()
        stats['_snapshot_ts'] = time.time()
        stats['_snapshot_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        try:
            _os.makedirs(_os.path.dirname(path), exist_ok=True)
        except Exception:
            pass
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            _json.dump(stats, f, ensure_ascii=False, indent=2)
        _os.replace(tmp, path)

    def _poll_reset_request(self):
        """🆕 [P5-fix20-A2 / 2026-05-22] poll reset_request.json, 主进程执行 reset.

        Dashboard / CLI 写 reset_request.json (action/label/consumed=false).
        本 loop 读 → 执行对应 reset_* → 标记 consumed=true → 写 audit jsonl.
        让 Sir 一键复活的请求在 ≤5s 内被主进程执行.
        """
        import os as _os
        import json as _json
        path = self._RESET_REQUEST_PATH
        if not _os.path.exists(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                req = _json.load(f)
        except Exception:
            return
        if not isinstance(req, dict) or req.get('consumed'):
            return  # 已被处理过
        action = (req.get('action', '') or '').strip().lower()
        label = (req.get('label', '') or '').strip()
        source = (req.get('source', '') or 'unknown').strip()
        result: Dict[str, Any] = {'action': action, 'label': label, 'source': source}

        if action == 'all':
            r = self.reset_all()
            result['outcome'] = 'ok'
            result['reset_cooldown'] = r.get('reset_cooldown', [])
            result['reset_permanent'] = r.get('reset_permanent', [])
            n_total = len(result['reset_cooldown']) + len(result['reset_permanent'])
            result['summary'] = f"复活 {n_total} 把 key (冷却 {len(result['reset_cooldown'])} + 永久死 {len(result['reset_permanent'])})"
        elif action == 'cooldown':
            ok = self.reset_cooldown(label) if label else False
            result['outcome'] = 'ok' if ok else 'fail'
            result['summary'] = f"reset_cooldown({label})={'ok' if ok else 'fail'}"
        elif action == 'permanent':
            ok = self.reset_permanent_death(label) if label else False
            result['outcome'] = 'ok' if ok else 'fail'
            result['summary'] = f"reset_permanent_death({label})={'ok' if ok else 'fail'}"
        else:
            result['outcome'] = 'unknown_action'
            result['summary'] = f"unknown action: {action}"

        # 标 consumed (写回 request 文件)
        req['consumed'] = True
        req['consumed_at'] = time.time()
        req['result'] = result
        try:
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                _json.dump(req, f, ensure_ascii=False, indent=2)
            _os.replace(tmp, path)
        except Exception:
            pass

        # 写 audit jsonl (debug + Sir 看历史)
        try:
            audit_path = self._RESET_AUDIT_PATH
            _os.makedirs(_os.path.dirname(audit_path), exist_ok=True)
            audit_line = {
                'ts': time.time(),
                'iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'request': {k: v for k, v in req.items() if k not in ('result',)},
                'result': result,
            }
            with open(audit_path, 'a', encoding='utf-8') as f:
                f.write(_json.dumps(audit_line, ensure_ascii=False) + '\n')
        except Exception:
            pass

        # bg_log 让 Sir 一眼看到
        try:
            from jarvis_utils import bg_log as _kr_bg
            _kr_bg(
                f"⚡ [KeyRouter/Reset] 源={source} {result.get('summary', '')} "
                f"(P5-fix20-A2 file-IPC)"
            )
        except Exception:
            pass

        # 立刻刷新 snapshot, 让 dashboard 在 5s 内看到新状态
        try:
            self._write_health_snapshot()
        except Exception:
            pass

    def reset_all(self) -> dict:
        """🆕 [P5-fix20-A2 / 2026-05-22] Sir 一键全清 — cooldown + permanent_death 一次性.

        Returns: {reset_cooldown: [labels], reset_permanent: [labels]}
        """
        out = {'reset_cooldown': [], 'reset_permanent': []}
        # 先 permanent
        for key, status in list(self._key_status.items()):
            if status.get('permanently_dead', False):
                if self.reset_permanent_death(status['label']):
                    out['reset_permanent'].append(status['label'])
        # 再 cooldown
        for key, status in list(self._key_status.items()):
            if not status['healthy'] and not status.get('permanently_dead', False):
                if self.reset_cooldown(status['label']):
                    out['reset_cooldown'].append(status['label'])
        return out

    # ====================================================================
    # [P0+18-b.5 / 2026-05-15] 启动诊断探针
    # ----------------------------------------------------------------
    # 问题：日志反复显示 `google_1 标记为不健康 (错误: ... 'Your project h')`，
    # 用户怀疑"三个 Key 轮换不工作"，但实际上：
    # 1) 海马体 BUG（b.4 已修）：之前所有 hippocampus.* embed 调用都死锁在
    #    google_1，根本不切 key —— 这是"轮换没工作"的根因。
    # 2) "Your project has been denied" 是 GCP 项目级错误：如果 3 个 Key
    #    都来自同一个 Google Cloud Project，那它们共享 quota / billing，
    #    一个被封三个全 403。
    #
    # 探针在启动时给 3 个 google key 各做一次轻量 embed_content（1 token），
    # 任一失败时把错误归类（auth/quota/project-denied/network）。如果
    # 3 个全失败、且错误模式相同 → 提示 Sir "三 Key 等效于一 Key"。
    # ====================================================================
    def probe_google_keys_at_startup(self, async_mode: bool = True):
        """启动时探针：检查 3 个 google key 是否都可用 + 是否同一 GCP Project。

        async_mode=True：后台跑，不阻塞主程序启动；探针结果用 bg_log 输出。
        """
        def _probe():
            try:
                time.sleep(2.0)  # 让 jarvis_utils 的 runtime log + bg_log 系统就绪
                from jarvis_utils import bg_log, create_genai_client
                from google.genai import types as _types

                results = []
                for entry in self._google_pool:
                    label = entry['label']
                    key = entry['key']
                    try:
                        client = create_genai_client(api_key=key)
                        _ = client.models.embed_content(
                            model='gemini-embedding-2',
                            contents=['probe'],
                            config=_types.EmbedContentConfig(output_dimensionality=768)
                        )
                        results.append((label, 'OK', ''))
                    except Exception as e:
                        msg = str(e)
                        if 'project has been denied' in msg.lower() or 'project_denied' in msg.lower():
                            cat = 'PROJECT_DENIED'
                        elif '403' in msg or 'permission' in msg.lower() or 'forbidden' in msg.lower():
                            cat = 'AUTH_403'
                        elif '401' in msg or 'unauthorized' in msg.lower():
                            cat = 'AUTH_401'
                        elif '429' in msg or 'quota' in msg.lower() or 'rate' in msg.lower():
                            cat = 'QUOTA'
                        elif 'billing' in msg.lower():
                            cat = 'BILLING'
                        else:
                            cat = 'NETWORK_OR_OTHER'
                        results.append((label, cat, msg[:150]))
                        # 标记不健康，避免后续 hippocampus 路径再撞
                        self.report_error(label, msg)

                lines = [f"  {label:12} → {cat}" for (label, cat, _) in results]
                bg_log("🔍 [KeyRouter Probe] 启动时探针结果：\n" + "\n".join(lines))

                ok_count = sum(1 for (_, c, _) in results if c == 'OK')
                bad_categories = {c for (_, c, _) in results if c != 'OK'}

                if ok_count == 0 and bad_categories == {'PROJECT_DENIED'}:
                    bg_log(
                        "🚨 [KeyRouter Diagnosis] 3 个 Google Key 全部 PROJECT_DENIED！\n"
                        "    → 极可能：3 个 Key 来自同一个 GCP Project（共享 quota/billing），\n"
                        "      该 Project 已被禁用 → 三 Key 等价于一 Key。\n"
                        "    建议：(1) 检查 https://console.cloud.google.com/billing；\n"
                        "         (2) 用 3 个不同 GCP Project 各生成一份 Key，才有真正的"
                        "三 Key 容量"
                    )
                elif ok_count == 0:
                    bg_log(
                        f"🚨 [KeyRouter Diagnosis] 3 个 Google Key 全部失败，类别={bad_categories}。\n"
                        "    所有 hippocampus embedding / 反思链路将走 fuzzy 兜底。"
                    )
                elif ok_count < len(results):
                    bg_log(
                        f"⚠️ [KeyRouter Diagnosis] {ok_count}/{len(results)} 个 Key 可用，"
                        f"其余失败类别={bad_categories}。"
                    )
                else:
                    bg_log(f"✅ [KeyRouter Diagnosis] 3 个 Google Key 全部 OK，轮换池就绪。")
            except Exception as e:
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"⚠️ [KeyRouter Probe] 探针异常（不影响主程序）: {e}")
                except Exception:
                    pass

        if async_mode:
            threading.Thread(target=_probe, daemon=True, name='KeyRouterProbe').start()
        else:
            _probe()


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

