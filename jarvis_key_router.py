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
    
    PROVIDER_GOOGLE = 'google'
    PROVIDER_OPENROUTER = 'openrouter'
    
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
    
    def get_openrouter_key(self, caller: str) -> tuple:
        """从 OpenRouter Key 池随机抽一个。返回 (key, key_name)。失败抛异常。"""
        self._reset_daily_counters()
        key, key_name = self._pick_from_pool(self._openrouter_pool, self.PROVIDER_OPENROUTER)
        if key:
            return key, key_name
        raise RuntimeError(f"[KeyRouter] 所有 OpenRouter Key 均不可用 (caller={caller})。")
    
    def get_key(self, caller: str, model_tier: str = 'flash_lite',
                allow_openrouter_fallback: bool = True) -> tuple:
        """兼容旧接口：主脑 → 锁死主脑Key；其他 → Google Key 池"""
        self._reset_daily_counters()
        
        if caller == self.CALLER_MAIN_BRAIN:
            if self._key_status[self._main_brain_key]['healthy']:
                if self._try_acquire(self._main_brain_key):
                    return self._main_brain_key, 'main_brain', self.PROVIDER_OPENROUTER
            raise RuntimeError(
                f"[KeyRouter] 主脑 Key 不可用 (caller={caller})。"
                f"healthy={self._key_status[self._main_brain_key]['healthy']}, "
                f"并发={self._active_calls[self._main_brain_key]}/{self._max_concurrent[self._main_brain_key]}"
            )
        
        key, key_name = self._pick_from_pool(self._google_pool, self.PROVIDER_GOOGLE)
        if key:
            return key, key_name, self.PROVIDER_GOOGLE
        raise RuntimeError(f"[KeyRouter] 所有 Google Key 均不可用 (caller={caller})。")
    
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
            if status['provider'] == self.PROVIDER_GOOGLE and not status['permanently_dead']:
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
        return {
            'openrouter_calls_today': self._openrouter_call_count_today,
            'key_status': {
                self._key_status[k]['label']: {
                    'healthy': v['healthy'], 'errors': v['error_count'],
                    'provider': v['provider']
                }
                for k, v in self._key_status.items()
            },
            'active_calls': {
                self._key_status[k]['label']: v
                for k, v in self._active_calls.items()
            },
        }

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

