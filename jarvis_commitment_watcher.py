# -*- coding: utf-8 -*-
"""[P0+19-6.d / 2026-05-16] 承诺守望者 CommitmentWatcher — 用户承诺监督 + SQLite 持久化（P0+18-e.3）

从 jarvis_nerve.py 拆出 1 个大类（>500 行）。
向后兼容：jarvis_nerve.py 用 `from jarvis_commitment_watcher import CommitmentWatcher` 转发，
旧 `from jarvis_nerve import CommitmentWatcher` 0 改动。
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


import os
import re
import json
import time
import threading
import queue
import random
import collections
import sqlite3  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from typing import List, Dict, Any, Optional  # noqa: F401

# 🩹 [P0+20-β.1.7 / 2026-05-16] P0+19-6.d 拆分留尾：win32api 没 import →
# line 607 NameError → 承诺过期+grace 分支静默丢失。修法：try-import 容错。
try:
    import win32api  # noqa: F401
    import win32gui  # noqa: F401
    import win32con  # noqa: F401
except Exception:
    win32api = None  # type: ignore
    win32gui = None  # type: ignore
    win32con = None  # type: ignore

# 跨文件依赖（上游已拆完）
from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401
# [P0+19-final fix 2]
from google.genai import types  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401  # noqa: F401
from jarvis_sensors import (  # noqa: F401
    SubconsciousMailbox, CausalChain, HabitClock,
    FunnelLogger, SensorFilter, ProjectTimeline,
)
from jarvis_sentinels import NudgeGate  # noqa: F401

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




class CommitmentWatcher(threading.Thread):
    """承诺守望者：用户说了1点睡觉但1:20还在工作 → 主动关怀
    
    [P0+18-e.3 / 2026-05-15] 持久化升级：commitments 镜像到 SQLite Commitments 表。
    重启后能从 DB 反查未到期未 nudge 的承诺。
    """
    def __init__(self, jarvis_worker, nudge_gate=None):
        super().__init__(daemon=True)
        self.worker = jarvis_worker
        self.gate = nudge_gate
        self.commitments = []
        self._lock = threading.Lock()
        # [P0+18-e.3] 重启反查：从 SQLite Commitments 表加载未 nudge 的承诺
        try:
            hippo = self._get_hippo()
            if hippo is not None:
                rows = hippo.load_active_commitments(max_age_hours=48.0)
                for row in rows:
                    self.commitments.append({
                        'db_id': row.get('id', 0),
                        'deadline_ts': row.get('deadline_ts', 0.0),
                        'description': row.get('description', ''),
                        'grace_minutes': row.get('grace_minutes', 10),
                        'nudged': row.get('nudged', False),
                        'source_text': row.get('source_text', ''),
                        'created_at': row.get('created_at', time.time()),
                    })
                if rows:
                    try:
                        from jarvis_utils import bg_log as _cw_load_bg
                        _cw_load_bg(f"📥 [CommitmentWatcher/Persist] 从 SQLite 恢复 {len(rows)} 条未触发承诺")
                    except Exception:
                        pass
        except Exception as _e:
            try:
                from jarvis_utils import bg_log as _cw_load_bg
                _cw_load_bg(f"⚠️ [CommitmentWatcher/Persist] load 失败: {str(_e)[:80]}")
            except Exception:
                pass

    def _get_hippo(self):
        """安全获取 hippocampus 引用，便于持久化 CRUD。

        [P0+20-β.2.4 hotfix / 2026-05-16] Sir 23:38 报告 P0 BUG：
        P0+19 split 后 worker 参数从 JarvisWorkerThread (.jarvis = nerve) 改成
        直接传 CentralNerve（.hippocampus 直持）。原代码只走 .jarvis.hippocampus
        路径 → 永远 None → add_commitment_row 从未调 → SQLite Commitments 表
        自 P0+18-e.3 起一直空（commitment 持久化伪失效）。
        修法：先 worker.hippocampus 直接拿，回退 worker.jarvis.hippocampus 兼容
        旧路径。走公共 helper resolve_worker_attr。
        """
        try:
            from jarvis_utils import resolve_worker_attr
            return resolve_worker_attr(self.worker, 'hippocampus')
        except Exception:
            return None

    def extract_from_input(self, user_text):
        import re
        if not user_text:
            return
        text_lower = user_text.lower()

        rest_verbs = r'(sleep|rest|nap|go\s+to\s+bed|go\s+to\s+sleep|take\s+a\s+break|take\s+a\s+nap|lie\s+down|call\s+it\s+a\s+day|wrap\s+up|finish\s+up|stop\s+working)'
        intent_prefix = r'(i\s+(will|am\s+going\s+to|.ll|plan\s+to|gonna|need\s+to|have\s+to|should|must|want\s+to))'

        time_patterns = [
            (r'at\s+(\d{1,2})\s*:\s*(\d{2})\s*(pm|am|p\.m\.|a\.m\.)?', lambda h, m, ap: self._to_24h(int(h), int(m), ap)),
            (r'at\s+(\d{1,2})\s*(pm|am|p\.m\.|a\.m\.|o.?clock)', lambda h, ap: self._to_24h(int(h), 0, ap if ap not in ("o'clock", "oclock") else None)),
            (r'at\s+(\d{1,2})\s*:\s*(\d{2})', lambda h, m: self._to_24h(int(h), int(m), None)),
            (r'at\s+(\d{1,2})(?!\s*:\s*\d)', lambda h: self._to_24h(int(h), 0, None)),
            (r'in\s+(\d+)\s*minutes?', lambda m: time.time() + int(m) * 60),
            (r'in\s+(\d+)\s*hours?', lambda h: time.time() + int(h) * 3600),
            (r'in\s+an\s+hour', lambda: time.time() + 3600),
            (r'in\s+half\s+an\s+hour', lambda: time.time() + 1800),
        ]

        for tp_regex, tp_func in time_patterns:
            time_match = re.search(tp_regex, text_lower)
            if time_match:
                try:
                    if tp_regex.startswith(r'in\s+an'):
                        deadline_ts = tp_func()
                    elif tp_regex.startswith(r'in\s+half'):
                        deadline_ts = tp_func()
                    elif tp_regex.startswith(r'in\s+(\d+)\s*minutes?'):
                        deadline_ts = tp_func(time_match.group(1))
                    elif tp_regex.startswith(r'in\s+(\d+)\s*hours?'):
                        deadline_ts = tp_func(time_match.group(1))
                    else:
                        groups = time_match.groups()
                        deadline_ts = tp_func(*groups)
                except:
                    continue

                rest_match = re.search(rest_verbs, text_lower)
                if rest_match:
                    verb = rest_match.group(1).replace('\\s+', ' ')

                    if deadline_ts < time.time() - 3600:
                        return

                    past_tense_markers = [r'\b(slept|napped|rested|went\s+to\s+bed|went\s+to\s+sleep|took\s+a\s+break|took\s+a\s+nap)\b',
                                          r'\b(last\s+night|yesterday|earlier|before|already|just\s+(slept|napped|rested))\b']
                    if any(re.search(m, text_lower) for m in past_tense_markers):
                        return

                    description = f"用户计划{verb}"

                    with self._lock:
                        existing = [c for c in self.commitments if not c['nudged']]
                        for c in existing:
                            if abs(c['deadline_ts'] - deadline_ts) < 300:
                                return
                        if len(self.commitments) > 5:
                            self.commitments = self.commitments[-4:]

                        # [P0+18-e.3 / 2026-05-15] 先持久化到 SQLite，再回填 db_id
                        _new_db_id = 0
                        try:
                            hippo = self._get_hippo()
                            if hippo is not None:
                                _new_db_id = hippo.add_commitment_row(
                                    description=description,
                                    deadline_ts=deadline_ts,
                                    grace_minutes=10,
                                    source_text=user_text[:200] if user_text else '',
                                    created_at=time.time(),
                                )
                        except Exception:
                            pass
                        self.commitments.append({
                            'db_id': _new_db_id,
                            'deadline_ts': deadline_ts,
                            'description': description,
                            'grace_minutes': 10,
                            'nudged': False,
                            'source_text': user_text[:200],
                            'created_at': time.time()
                        })
                        deadline_str = time.strftime("%H:%M", time.localtime(deadline_ts))
                        # [P0+18-c.8 / 2026-05-15] 改 bg_log 不漏到对话框
                        try:
                            from jarvis_utils import bg_log as _cw_bg_log
                            _cw_bg_log(f"📝 [CommitmentWatcher] 已注册: {description} @ {deadline_str} (DB#{_new_db_id})")
                        except Exception:
                            pass
                    return

    # 🩹 [β.2.9.7 / 2026-05-18] Sir 08:43 实测痛点 (jarvis_20260518_084313.log):
    # 4 条 "I will sleep at 11" / "我11点睡觉" / "I'll go to bed by midnight" /
    # "I will go to sleep at 11" 全部 deadline_str='' 不可解析 → 兜底 +1h.
    # 根因: 旧 _parse 只懂 hh:mm / tonight / tomorrow / in N min, 不懂:
    #   - 单数字 + 上下文语义 ("11" + sleep → 23:00)
    #   - 模糊时段词 ("midnight" / "noon" / "深夜" / "早上")
    #   - "X pm" / "X am" 显式 AM/PM
    # 修 (准则 6 — 不写关键词 if 链, 用 vocab 表 + 通用语义推断):
    #   _FUZZY_TIME_VOCAB: 模糊词 → 默认 (h, m)
    #   _SLEEP_VOCAB / _WAKE_VOCAB / _DAYTIME_VOCAB: 语义类别 → AM/PM 倾向
    #   _infer_hour_from_context(): 单数字 hour + 上下文 → 24h hour
    #   _smart_parse_deadline(): 主入口, 替代 add_commitment 里 4 段 if-elif

    _FUZZY_TIME_VOCAB = {
        'midnight': (0, 0), 'noon': (12, 0),
        'tonight': (22, 0), 'late night': (23, 30),
        'morning': (8, 0), 'afternoon': (15, 0),
        'evening': (19, 0), 'night': (22, 0),
        '半夜': (0, 0), '凌晨': (1, 30),
        '中午': (12, 0), '今晚': (22, 0), '今夜': (22, 0),
        '早上': (8, 0), '清晨': (6, 30), '一早': (7, 0),
        '上午': (9, 0), '下午': (15, 0),
        '傍晚': (18, 0), '黄昏': (18, 30),
        '晚上': (20, 0), '深夜': (23, 30), '夜里': (22, 0),
    }
    _SLEEP_VOCAB = ('sleep', 'bed', 'bedtime', 'nap', 'rest', 'turn in',
                    'crash', 'goodnight', 'tired',
                    '睡', '上床', '关灯', '休息', '躺', '困', '歇会')
    _WAKE_VOCAB = ('wake', 'up', 'morning', 'breakfast', 'rise', 'alarm',
                   '起床', '早上', '早餐', '醒', '起来')
    _DAYTIME_VOCAB = ('dinner', 'lunch', 'supper', 'meeting',
                      '晚饭', '晚餐', '午饭', '午餐', '会议', '下午茶')

    def _infer_hour_from_context(self, hour: int, ctx: str, now_ts: float) -> int:
        """单数字 hour (0-23) + 上下文 → 24h hour. 准则 6: vocab 驱动, 不硬编码 if 链.

        逻辑: 含 sleep 词 + hour 1-11 → +12 (晚 PM); 含 wake 词 → 保留 AM;
        含 daytime 词 + hour 5-11 → +12 (下午饭); 默认看当前时段推断.
        """
        if hour < 0 or hour > 23:
            return max(0, min(23, hour))
        ctx_l = ctx.lower()
        in_sleep = any(w in ctx_l for w in self._SLEEP_VOCAB)
        in_wake = any(w in ctx_l for w in self._WAKE_VOCAB)
        in_daytime = any(w in ctx_l for w in self._DAYTIME_VOCAB)

        if in_sleep:
            # sleep 语义: 1-11 → PM (晚上); 12 → 00:00; 13+ 已是 PM 24h
            if 1 <= hour <= 11:
                return hour + 12
            if hour == 12:
                return 0
            return hour
        if in_wake:
            # wake 语义: 5-11 → AM 保留; 0-4 → AM (凌晨醒); 12 → 12 noon; 13+ 罕见保留
            return hour
        if in_daytime:
            # 晚饭/下午茶语义: 5-11 → PM 下午; 12 → noon 12; 0-4 → AM (早餐?)
            if 5 <= hour <= 11:
                return hour + 12
            return hour
        # 默认: 看当前时段 — 白天 (6-18) 说小数字 (1-7) 倾向 PM
        now_h = time.localtime(now_ts).tm_hour
        if 6 <= now_h <= 18 and 1 <= hour <= 7:
            return hour + 12
        return hour

    def _smart_parse_deadline(self, deadline_str: str,
                                description: str = '', user_text: str = '') -> float:
        """主入口: 把 LLM 给的 deadline_str (任意自然语言时间) 解析成 deadline_ts.

        失败返回 0 (调用方走兜底). ctx = description + user_text 用于上下文推断.
        """
        if not deadline_str:
            return 0
        dl = str(deadline_str).lower().strip()
        if not dl:
            return 0
        ctx = f"{description} {user_text}"
        now_ts = time.time()

        # 1. 显式 hh:mm (最强信号, 优先) — 旧 _to_24h 还有 AM/PM 推断, 给最大宽容
        m = re.search(r'(\d{1,2})\s*[:：]\s*(\d{2})', dl)
        if m:
            return self._to_24h(int(m.group(1)), int(m.group(2)), None)

        # 2. "in N min/hour" 相对时间
        m = re.search(r'\bin\s+(\d+)\s*(min|minute|hour|hr)', dl)
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            return now_ts + (n * 60 if 'min' in unit else n * 3600)

        # 3. "X am / X pm / X a.m. / X p.m." 显式 AM/PM (含可选分钟)
        m = re.search(r'(\d{1,2})(?:\s*[:：]\s*(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)\b', dl)
        if m:
            h = int(m.group(1))
            minute = int(m.group(2)) if m.group(2) else 0
            tail = m.group(3).replace('.', '')
            return self._to_24h(h, minute, tail)

        # 4. 模糊时段词 (midnight / 早上 等) — 直接 24h, 跳过 _to_24h AM/PM 推断
        # 否则 'midnight' (0, 0) 在上午会被推成 12:00 (因 _to_24h 看 hour<12 +12)
        for kw, (h, mi) in self._FUZZY_TIME_VOCAB.items():
            if kw in dl:
                return self._build_deadline_from_24h(h, mi, now_ts)

        # 5. tomorrow / next week / day after 等粗粒度相对日期
        if 'next week' in dl:
            return now_ts + 604800
        if 'day after tomorrow' in dl or '后天' in dl:
            return now_ts + 86400 * 2
        if 'tomorrow' in dl or '明天' in dl or '明早' in dl or '明晚' in dl:
            # tomorrow 必须是次日, 不能用 _build_deadline_from_24h (它会做"过 1h
            # 推次日"逻辑导致双重 +86400). 直接构今天日期 + 86400.
            if '晚' in dl or 'night' in dl or 'evening' in dl:
                base_h = 22
            else:
                base_h = 8
            now_local = time.localtime(now_ts)
            today_ts = time.mktime((now_local.tm_year, now_local.tm_mon,
                                      now_local.tm_mday, base_h, 0, 0,
                                      now_local.tm_wday, now_local.tm_yday,
                                      now_local.tm_isdst))
            return today_ts + 86400

        # 6. 单数字 + 语义 (准则 6 核心 — 治 "I will sleep at 11" 类 4 条样本)
        m = re.search(r'(?:^|\s|at\s+)(\d{1,2})(?!\d)', dl)
        if m:
            h = int(m.group(1))
            if 0 <= h <= 23:
                inferred = self._infer_hour_from_context(h, ctx, now_ts)
                return self._build_deadline_from_24h(inferred, 0, now_ts)

        # 7. 中文数字 (一二三..十一十二) — 简单 lookup
        _ZH_DIGITS = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3,
                      '四': 4, '五': 5, '六': 6, '七': 7, '八': 8,
                      '九': 9, '十': 10, '十一': 11, '十二': 12}
        for zh, n in sorted(_ZH_DIGITS.items(), key=lambda x: -len(x[0])):
            if zh + '点' in dl:
                inferred = self._infer_hour_from_context(n, ctx, now_ts)
                return self._build_deadline_from_24h(inferred, 0, now_ts)

        return 0  # 解析失败

    def _build_deadline_from_24h(self, hour_24: int, minute: int,
                                    now_ts: float) -> float:
        """已知 24h hour + minute, 直接构 timestamp. 跳过 _to_24h 的 AM/PM 推断.

        逻辑: 今天该时间已过 1h+ → 推到明天. 防 "8 am 推 23:00" → 已过 18h, 推次日.
        """
        h = max(0, min(23, int(hour_24)))
        m = max(0, min(59, int(minute)))
        now_local = time.localtime(now_ts)
        ts = time.mktime((now_local.tm_year, now_local.tm_mon, now_local.tm_mday,
                           h, m, 0, now_local.tm_wday, now_local.tm_yday,
                           now_local.tm_isdst))
        if ts < now_ts - 3600:  # 今天该时间已过 1h+ → 推到明天
            ts += 86400
        return ts

    def _to_24h(self, hour, minute, am_pm):
        # [P0-1 / 2026-05-15] 凌晨上下文修复：
        # 实测发现 Sir 在凌晨 1:24 说"两点睡觉"，此函数把 2 → 14（下午2点），
        # 因为旧逻辑没看 now.tm_hour，统一把小数字假设成下午。
        # 修法：把"当前几点"作为基准；凌晨/清晨说小数字优先保留为凌晨值。
        now = time.localtime()
        if am_pm:
            am_pm = am_pm.lower().replace('.', '')
            if am_pm == 'pm' and hour != 12:
                hour += 12
            elif am_pm == 'am' and hour == 12:
                hour = 0
        else:
            # 无 am/pm 标记 → 按当前时段推断
            if now.tm_hour < 6:
                # 凌晨 [0,6)：Sir 说"两点"几乎一定是凌晨；不加 12
                # 但若 hour > now.tm_hour + 16 这种夸张差，保留原值由下方 +86400 兜底到明天
                pass
            elif 6 <= now.tm_hour < 12:
                # 早晨 [6,12)：Sir 说"两点" 通常指下午；hour < 6 一律 +12（避免回到今天清晨过期）
                if hour < 12:
                    hour += 12
            else:
                # 下午/晚上 [12,24)：小数字（<8）默认补 12 → 当天傍晚/晚上；
                # 7-11 这一段说"九点"通常指当晚 21:00 → 也 +12
                if hour < 12:
                    hour += 12
        if hour >= 24:
            hour -= 24
        deadline = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, hour, minute, 0, now.tm_wday, now.tm_yday, now.tm_isdst))
        if deadline < time.time() - 3600:
            deadline += 86400
        return deadline

    def add_commitment(self, description: str, deadline_str: str,
                       user_text: str = None,
                       is_future_task_confirmed: bool = False,
                       source: str = 'user_text',
                       commit_type: str = 'sir_self_promise',
                       predicate: 'Predicate' = None,
                       ttl_s: float = 86400.0,
                       action_executor: str = 'voice_nudge',
                       action_target: str = 'sir'):
        """
        🩹 [β.2.8.7 / 2026-05-17] Sir 23:28 反馈承诺三角接口预留:
          action_executor: 谁执行 action 'voice_nudge' (默认, 走 stream_nudge 出声)
                          | 'tool_call' (将来扩展: 直接执行 organ.command, 例如
                                          自动暂停 chrome, kill premiere 后真喝水提醒+开播)
                          | 'silent_log' (只记 PromiseLog, 不打扰)
          action_target: 谁是被影响者 'sir' (默认提醒 Sir) | 'jarvis' (自我状态变更, 调 tool)
                          | 'system' (改全局 state)
          当前实现只支持 voice_nudge → sir, 字段存进 commitment dict 等 β.2.9 接通其他通道.
        """
        """source='user_text' (Sir 承诺) | 'self_promise' (Jarvis 自承诺)
        🩹 [β.2.7.3 / 2026-05-17] 加 source — Jarvis 自承诺与 Sir 承诺平等持久化
        🩹 [β.2.8.6 / 2026-05-17] Predicate-driven commitment + 承诺三角 (Sir 22:48 澄清):
          - commit_type='sir_self_promise' (老兼容): Sir 承诺自己做某事 → 走 first_person 检查
          - commit_type='conditional_reminder': Sir 托付 Jarvis 监视 predicate + 满足时提醒
                                                 跳过 first_person, 必须有 predicate
          - commit_type='jarvis_self_promise': Jarvis 自承诺 (source='self_promise')
          - predicate: 可选, 满足时立刻 fire 不走 deadline_ts
          - ttl_s: predicate 路径的过期时间 (default 24h)
        """
        """注册一条用户承诺。

        [P0+18-c.9/c.10 / 2026-05-15] 修 Sir 实测 BUG：
        Sir 原话 "我...不如**明天早上起来刷**怎么样" 明显是承诺，但 CW 用 Gatekeeper
        extracted desc ("明天早上起来刷科目一的题"，没"我") 做 first_person 检测 → 拒绝。
        与此同时 Time Hook 已 schedule。两路径数据不一致。

        修复方案：
        - user_text: 用户原话（cmd），first_person 检查优先看它
        - is_future_task_confirmed: Time Hook 已确认 future_task → CW 信任，跳过 first_person/rest 检查
        - 作息词典扩展：'学习/做题/复习/刷题/工作/编程/视频/会议/锻炼' 等
        - 不一致时 bg_log warn
        """
        import re
        if not description:
            return

        # 🛡️ 反误判守门（Bug A 修复）：用户对 Jarvis 下指令 ≠ 用户自己承诺
        # Gate LLM 偶尔会把"帮我把音量调到 30%"识别成承诺，这里做硬过滤兜底
        desc_lower = description.lower().strip()
        instruction_to_jarvis_patterns = [
            r'^帮我',              # 帮我把音量调到 30%
            r'^给我',              # 给我调一下
            r'^把.+?(调|设|改|关|开|降|升|提|减|增)',  # 把屏幕亮度调整到 50%
            r'^请你',              # 请你打开...
            r'^请\s',              # 请把
            r'^让你',
            r'^叫你',
            r'^麻烦你',
            r'^jarvis\b',
            r'^j\.a\.r\.v\.i\.s',
            r'^你帮',
            r'^你能',
            r'^(打开|关闭|启动|停止|播放|暂停|切换|调高|调低|调到|调整|设置|设为|改成|改为)',
            r'^(turn|set|adjust|change|open|close|play|pause|toggle|switch|increase|decrease|raise|lower|mute)\b',
            r'^(扮演|假装|模拟|演一下|演个)',
            r'^(pretend|act\s+as|role[- ]?play|simulate)\b',
        ]
        for pat in instruction_to_jarvis_patterns:
            if re.search(pat, desc_lower):
                # [P0+18-c.8 / 2026-05-15] 改 bg_log 不漏到对话框
                try:
                    from jarvis_utils import bg_log as _cw_bg_log
                    _cw_bg_log(f"📝 [CommitmentWatcher] 🛡️ 拒绝注册：'{description[:60]}' — 这是给 Jarvis 的指令，不是用户的承诺")
                except Exception:
                    pass
                return

        # 🩹 [β.2.8.6 / 2026-05-17] conditional_reminder 类型跳过 first_person 检查
        # Sir 澄清: "等我导出完视频提醒我喝水" — Sir 没承诺自己做啥, 是托付 Jarvis
        # 监视 predicate. 这种 commit 必须有 predicate 字段才允许 (兜底安全).
        if commit_type == 'conditional_reminder':
            if predicate is None:
                try:
                    from jarvis_utils import bg_log as _cw_bg_log
                    _cw_bg_log(f"📝 [CommitmentWatcher] 🛡️ conditional_reminder 必须带 predicate, "
                               f"拒绝注册 '{description[:60]}'")
                except Exception:
                    pass
                return
            # 跳过 first_person 检查, 直接进 lock 块注册
            try:
                from jarvis_utils import bg_log as _cw_bg_log
                _cw_bg_log(f"📝 [CommitmentWatcher/CondReminder] 接受 '{description[:60]}' "
                           f"predicate={predicate.describe()[:80]}")
            except Exception:
                pass
            has_first_person = True   # 标记让后续 logic 不再阻拦
            has_rest_intent = True

        # 描述要么出现第一人称（"我"/"I"），要么是和作息相关的强关键词，
        # 否则视为可疑（设备控制、外部事件、家务等都不应被当成用户对自己的承诺）
        # [P0+18-c.10 / 2026-05-15] 扩词典 + 检查 user_text（原话）+ 信任 Time Hook 已确认
        first_person_markers = [r'\bi\b', r'\bi\'?ll\b', r'\bi\'?m\b', r'\bmy\b',
                                r'\bmyself\b', r'我[要会想得该需必去打准]', r'我[\s,，]', r'^我',
                                r'不如', r'打算', r'准备', r'计划']  # 新增意图词
        # 作息 + 学习 + 工作 + 锻炼 等"用户自我承诺动作"通用词典
        rest_intent_markers = [
            r'\b(sleep|bed|nap|rest|study|work|exercise|practice|review|code)\b',
            r'(睡|休息|躺下|上床|关灯)',
            r'(学习|做题|刷题|复习|预习|做作业)',           # 学习类
            r'(工作|加班|开会|写代码|编程)',                # 工作类
            r'(剪辑|剪视频|录视频|做视频)',                  # 视频创作类
            r'(锻炼|健身|跑步|运动|拉伸)',                   # 锻炼类
            r'(吃药|吃饭|喝水|早餐|午餐|晚餐|宵夜)',         # 生活类
        ]
        # 优先看用户原话（user_text）的 first_person —— extracted desc 经常丢"我"
        # 注意: conditional_reminder 在上面已 short-circuit 设了 has_first_person=True
        if commit_type != 'conditional_reminder':
            first_person_source = user_text.lower() if user_text else desc_lower
            has_first_person = any(re.search(p, first_person_source) for p in first_person_markers) or \
                               any(re.search(p, desc_lower) for p in first_person_markers)
            has_rest_intent = any(re.search(p, desc_lower) for p in rest_intent_markers) or \
                              (user_text and any(re.search(p, user_text.lower()) for p in rest_intent_markers))

        # Time Hook 已确认 future_task → CW 信任,跳过第一人称/作息检查
        if is_future_task_confirmed:
            if not (has_first_person or has_rest_intent):
                # 两路径不一致 → bg_log warn（让 Sir 实测时一眼看到）
                try:
                    from jarvis_utils import bg_log as _cw_bg_log
                    _cw_bg_log(f"⚠️ [CommitmentWatcher/Inconsistency] Time Hook 已 schedule '{description[:40]}' "
                               f"但 CW 第一人称/作息检查均未命中（信任 Time Hook 继续注册）")
                except Exception:
                    pass
        elif not has_first_person and not has_rest_intent:
            try:
                from jarvis_utils import bg_log as _cw_bg_log
                _cw_bg_log(f"📝 [CommitmentWatcher] 🛡️ 拒绝注册：'{description[:60]}' — 既无第一人称也无作息关键词，不像用户承诺")
            except Exception:
                pass
            return

        # 🩹 [β.2.9.9 / 2026-05-18] Sir 10:43 实测痛点: "我剪辑完这个视频就行"
        # 被注册成承诺 + 兜底 +1h (10:43 + 1h = 11:43 错误闹钟). 真问题: 这是个
        # 未来动作陈述, 但**没有具体时间 + 没有 predicate**, 不应该走 hard
        # Commitments DB (会到点真出声扰民).
        # 准则 6 架构修 (不针对"就行/完了"这种关键词硬编码):
        #   加 "时间确定性" 闸门 — 任何承诺必须有 EITHER:
        #     (a) 可解析的 deadline_str (走 _smart_parse_deadline 出非 0)
        #     (b) 不为空的 predicate (走 evaluate 路径)
        #   都没 → 拒绝注册 hard, 转 PromiseLog soft 记一笔 (Sir 仍能看到, 不闹).
        # 例外:
        #   conditional_reminder 必带 predicate (上面已强校), 此处不重复.
        #   is_future_task_confirmed = True 时信任上游 Time Hook (已解析过).
        if commit_type != 'conditional_reminder' and not is_future_task_confirmed:
            _has_time_anchor = False
            if deadline_str:
                try:
                    _test_ts = self._smart_parse_deadline(
                        deadline_str, description, user_text or '')
                    _has_time_anchor = bool(_test_ts and _test_ts > 0)
                except Exception:
                    _has_time_anchor = False
            _has_predicate = predicate is not None

            if not _has_time_anchor and not _has_predicate:
                # 转 PromiseLog soft (Sir 仍知道发生了, 不到点出声)
                try:
                    from jarvis_promise_log import get_default_log
                    _log = get_default_log()
                    _log.register(
                        description=description,
                        kind='soft',
                        deadline_str='',
                        jarvis_reply='',
                        turn_id='',
                        lang='zh' if re.search(r'[\u4e00-\u9fa5]', description) else 'en',
                    )
                except Exception:
                    pass
                try:
                    from jarvis_utils import bg_log as _cw_bg_log
                    _cw_bg_log(
                        f"📝 [CommitmentWatcher] 🛡️ 时间确定性闸门: "
                        f"'{description[:60]}' 无具体时间/predicate → "
                        f"跳过 hard 注册, 转 PromiseLog soft (不到点闹)"
                    )
                except Exception:
                    pass
                return

        with self._lock:
            # 🩹 [β.2.9.1.1 / 2026-05-18] Sir 01:14 反馈: deadline='now' 被默认 +3600 注册.
            # 准则 6 (拒绝硬编码) 反例 — 默认 +1h 是凭空猜测.
            # 修: deadline='now' / 'right now' / 'immediately' / '现在' / '马上' →
            #     这不是未来承诺, 是 present-tense status, mark 已 nudged 跳过 deadline 路径.
            #     deadline 不可解析时也 mark nudged (不强行 +1h 闹钟扰 Sir).
            if deadline_str:
                _dl_l = deadline_str.lower().strip()
                _present_tense_markers = ('now', 'right now', 'immediately',
                                            'at the moment', '现在', '马上',
                                            '立刻', '正在', '此刻')
                if _dl_l in _present_tense_markers or any(m == _dl_l for m in _present_tense_markers):
                    try:
                        from jarvis_utils import bg_log as _now_bg
                        _now_bg(
                            f"📝 [CommitmentWatcher] deadline='{deadline_str}' = present-tense, "
                            f"not a future commitment — skipping registration ('{description[:60]}')"
                        )
                    except Exception:
                        pass
                    return

            deadline_ts = 0  # 用 0 标记"未解析", 后面看是否真有效解析
            if deadline_str:
                try:
                    deadline_ts = self._smart_parse_deadline(
                        deadline_str, description or '', user_text or ''
                    )
                except Exception:
                    pass
            # 🩹 [β.2.9.4 hotfix / 2026-05-18] 解析失败时:
            # - conditional_reminder + predicate → predicate 主导 (deadline 设 30 天)
            # - 其他 → 兜底 +1h (legacy 行为保留; present-tense 已在上面 return 拦)
            if deadline_ts <= 0:
                if commit_type == 'conditional_reminder' and predicate is not None:
                    deadline_ts = time.time() + 86400 * 30
                else:
                    deadline_ts = time.time() + 3600
                    try:
                        from jarvis_utils import bg_log as _fb_bg
                        _fb_bg(
                            f"📝 [CommitmentWatcher] deadline_str='{deadline_str}' 不可解析, "
                            f"兜底 +1h. desc='{description[:60]}'"
                        )
                    except Exception:
                        pass

            # [P0-1 bottom-guard / 2026-05-15] 凌晨上下文兜底：
            # 即便 LLM 把"两点"算成 14:00:00（凌晨 1 点说），这里再做一次 sanity check。
            # 规则：若 now.tm_hour < 6（凌晨）+ description 含睡眠关键词 + 解析出的 deadline
            # 在未来 8 小时以外（即不在"接下来这个凌晨"的窗口），强制把目标小时回到凌晨段。
            try:
                now_local = time.localtime()
                gap_hours = (deadline_ts - time.time()) / 3600.0
                desc_lower = description.lower()
                rest_keywords = ('sleep', 'bed', 'nap', 'rest', '睡', '休息', '躺', '上床')
                has_rest_kw = any(kw in desc_lower for kw in rest_keywords)
                if now_local.tm_hour < 6 and has_rest_kw and gap_hours > 8:
                    deadline_struct = time.localtime(deadline_ts)
                    pm_hour = deadline_struct.tm_hour
                    if pm_hour >= 12:
                        am_hour = pm_hour - 12
                        corrected = time.mktime((now_local.tm_year, now_local.tm_mon, now_local.tm_mday,
                                                  am_hour, deadline_struct.tm_min, 0,
                                                  now_local.tm_wday, now_local.tm_yday, now_local.tm_isdst))
                        if corrected < time.time() - 600:
                            corrected += 86400
                        try:
                            from jarvis_utils import bg_log
                            bg_log(f"🌙 [Commitment Sanity] 凌晨 {now_local.tm_hour}:xx 说'{description[:30]}' 含睡眠词，"
                                   f"原 deadline {time.strftime('%H:%M', deadline_struct)} → 修正为 "
                                   f"{time.strftime('%H:%M', time.localtime(corrected))}")
                        except Exception:
                            pass
                        deadline_ts = corrected
            except Exception:
                pass

            existing = [c for c in self.commitments if not c['nudged']]
            for c in existing:
                if c['description'][:30] == description[:30]:
                    return

            # [P0+18-e.3 / 2026-05-15] 持久化到 SQLite
            _new_db_id = 0
            try:
                hippo = self._get_hippo()
                if hippo is not None:
                    _new_db_id = hippo.add_commitment_row(
                        description=description,
                        deadline_ts=deadline_ts,
                        grace_minutes=10,
                        source_text=(user_text or f"[Commitment] {description}")[:200],
                        created_at=time.time(),
                    )
            except Exception:
                pass

            # 🩹 [β.2.7.8 / 2026-05-17] source_text 必须存 user 原话, 不是 [Commitment]
            # prefix. 治 Sir 实测 "dinner 幻觉": commitment_check nudge 没有原话引用 →
            # LLM 看到 abstract description 自己脑补具体细节 (urinate → dinner)。
            # 修: 优先存 user_text (cmd 原话), 缺失时才 fallback prefix。
            _sxt = (user_text or '').strip()[:240]
            if not _sxt:
                _sxt = f"[Commitment] {description}"
            self.commitments.append({
                'db_id': _new_db_id,
                'deadline_ts': deadline_ts,
                'description': description,
                'grace_minutes': 10,
                'nudged': False,
                'source_text': _sxt,
                'source': source,  # 🩹 β.2.7.3: 'user_text' | 'self_promise'
                'created_at': time.time(),
                # 🩹 β.2.8.6: predicate-driven 字段 (None 时走老 deadline_ts 路径)
                'commit_type': commit_type,
                'predicate': predicate,
                'ttl_s': float(ttl_s),
                # 🩹 β.2.8.7: 承诺三角接口预留 (Sir 23:28)
                'action_executor': action_executor,
                'action_target': action_target,
            })
            dl_str = time.strftime("%H:%M", time.localtime(deadline_ts))
            # [P0+18-c.8 / 2026-05-15] 改 bg_log 不漏到对话框
            try:
                from jarvis_utils import bg_log as _cw_bg_log
                _src_tag = '/SelfPromise' if source == 'self_promise' else ''
                _cw_bg_log(f"📝 [CommitmentWatcher{_src_tag}] 已注册: {description} @ {dl_str} (DB#{_new_db_id})")
            except Exception:
                pass

    # [P0-3 / 2026-05-15] 新增：更新/取消 commitment 的接口，让 Memory Correction 能联动。
    # 旧代码 self.commitments 是 in-memory list，只有 append/remove(已 nudged) 两种操作，
    # 没有"按描述/关键词找到并修改"的接口，导致 Sir 纠正记忆时实际 commitment 不会更新。
    def cancel_by_keyword(self, keyword: str, max_age_seconds: float = 1800) -> int:
        """按关键词（在 description 或 source_text 里）取消近期注册的 commitment。
        返回取消数量。仅取消尚未 nudged 的；max_age_seconds 内创建的。"""
        if not keyword or len(keyword) < 2:
            return 0
        kw_lower = keyword.lower().strip()
        removed = 0
        now_ts = time.time()
        with self._lock:
            kept = []
            for c in self.commitments:
                age_ok = (now_ts - c.get('created_at', 0)) <= max_age_seconds
                desc_lower = c.get('description', '').lower()
                src_lower = c.get('source_text', '').lower()
                hit = (kw_lower in desc_lower) or (kw_lower in src_lower)
                if hit and (not c.get('nudged')) and age_ok:
                    removed += 1
                    # [P0+18-e.3] 同步 SQLite soft delete
                    try:
                        db_id = c.get('db_id', 0)
                        if db_id and db_id > 0:
                            hippo = self._get_hippo()
                            if hippo is not None:
                                hippo.soft_delete_commitment(db_id)
                    except Exception:
                        pass
                    try:
                        from jarvis_utils import bg_log
                        dl_str = time.strftime("%H:%M", time.localtime(c.get('deadline_ts', 0)))
                        bg_log(f"🗑️ [Commitment Cancel] '{c.get('description', '')[:40]}' @ {dl_str} 被关键词 '{keyword}' 撤销")
                    except Exception:
                        pass
                else:
                    kept.append(c)
            self.commitments = kept
        return removed

    def update_by_keyword(self, keyword: str, new_description: str = None,
                          new_deadline_str: str = None, max_age_seconds: float = 1800) -> int:
        """按关键词找到近期 commitment，更新描述和/或 deadline。返回更新数量。"""
        if not keyword or len(keyword) < 2:
            return 0
        kw_lower = keyword.lower().strip()
        updated = 0
        now_ts = time.time()
        with self._lock:
            for c in self.commitments:
                if c.get('nudged'):
                    continue
                age_ok = (now_ts - c.get('created_at', 0)) <= max_age_seconds
                if not age_ok:
                    continue
                desc_lower = c.get('description', '').lower()
                src_lower = c.get('source_text', '').lower()
                if (kw_lower not in desc_lower) and (kw_lower not in src_lower):
                    continue

                if new_deadline_str:
                    try:
                        dl_lower = new_deadline_str.lower().strip()
                        import re as _re
                        time_match = _re.search(r'(\d{1,2})\s*:\s*(\d{2})', dl_lower)
                        if time_match:
                            h, m = int(time_match.group(1)), int(time_match.group(2))
                            c['deadline_ts'] = self._to_24h(h, m, None)
                        elif 'tonight' in dl_lower:
                            c['deadline_ts'] = self._to_24h(22, 0, None)
                    except Exception:
                        pass
                if new_description and len(new_description) >= 2:
                    c['description'] = new_description
                    c['source_text'] = f"[Commitment-Updated] {new_description}"
                # [P0+18-e.3] 同步到 SQLite
                try:
                    db_id = c.get('db_id', 0)
                    if db_id and db_id > 0:
                        hippo = self._get_hippo()
                        if hippo is not None:
                            hippo.update_commitment_row(
                                rowid=db_id,
                                new_description=new_description if (new_description and len(new_description) >= 2) else None,
                                new_deadline_ts=c.get('deadline_ts') if new_deadline_str else None,
                            )
                except Exception:
                    pass
                updated += 1
                try:
                    from jarvis_utils import bg_log
                    dl_str = time.strftime("%H:%M", time.localtime(c.get('deadline_ts', 0)))
                    bg_log(f"🔄 [Commitment Update] '{c.get('description', '')[:40]}' → {dl_str}")
                except Exception:
                    pass
        return updated

    def run(self):
        time.sleep(30)
        print("[CommitmentWatcher] 承诺看门狗就绪...", file=sys.stderr)
        while True:
            try:
                if hasattr(self.worker, 'voice_thread') and self.worker.voice_thread.in_active_conversation:
                    time.sleep(10)
                    continue

                # [P0+17 / 2026-05-15] 启动护栏：复用 ReturnSentinel._startup_guard_until。
                # 09:22 实测发现 P0+9 的 5min 启动护栏只挡住了 ReturnSentinel.first_active_today
                # 路径，但 commit 的 trigger 路径完全独立 → 08:03 仍然触发了一次"纠正记忆"流程
                # （ID 685/686 全是这次的产物）。这里同样接入护栏：启动期内不允许 commit 触发主动
                # 提醒，等护栏过期再让正常逻辑接管。grace_minutes 不会丢，护栏过期后下一轮 tick
                # 自然会触发提醒。
                rs = getattr(self.worker, 'return_sentinel', None)
                if rs is not None:
                    guard_until = getattr(rs, '_startup_guard_until', 0.0)
                    if time.time() < guard_until:
                        # 仍在 5min 启动护栏内 → 这一轮不主动触发任何 commit nudge
                        try:
                            from jarvis_utils import bg_log
                            remaining = int(guard_until - time.time())
                            # 限频：每 60s 才打一次，避免日志刷屏（tick 是 30s 一次）
                            if not hasattr(self, '_last_startup_guard_log') or \
                               time.time() - getattr(self, '_last_startup_guard_log', 0) > 55:
                                bg_log(f"🛡️ [CommitmentWatcher/StartupGuard] 启动护栏内 ({remaining}s 剩余)，本轮不触发 commit 提醒")
                                self._last_startup_guard_log = time.time()
                        except Exception:
                            pass
                        time.sleep(30)
                        continue

                now = time.time()
                with self._lock:
                    for c in self.commitments[:]:
                        if c['nudged']:
                            if now - c['deadline_ts'] > 7200:
                                self.commitments.remove(c)
                            continue

                        # 🩹 [β.2.8.6 / 2026-05-17] Predicate-driven trigger:
                        # commitment 若含 predicate (β-3 LLM 解析 / β-2 heuristic 自动绑定)
                        # → 每 tick evaluate(ctx), True 则 fire. 时间锚仅保底 (老路径并存).
                        # 详 docs/JARVIS_PREDICATE_COMMITMENT.md
                        _pred = c.get('predicate', None)
                        if _pred is not None:
                            try:
                                _ctx = self._build_predicate_ctx(now)
                                _fire = bool(_pred.evaluate(_ctx))
                            except Exception as _eve:
                                try:
                                    from jarvis_utils import bg_log as _wb
                                    _wb(f"⚠️ [PredicateEval] {c.get('description', '?')[:40]}: {_eve}")
                                except Exception:
                                    pass
                                _fire = False
                            if _fire:
                                c['nudged'] = True
                                try:
                                    from jarvis_utils import bg_log as _wb
                                    _wb(f"✨ [CommitmentWatcher/Predicate] FIRE "
                                        f"'{c['description'][:50]}' by {_pred.describe()[:80]}")
                                except Exception:
                                    pass
                                try:
                                    db_id = c.get('db_id', 0)
                                    if db_id and db_id > 0:
                                        hippo = self._get_hippo()
                                        if hippo is not None:
                                            hippo.mark_commitment_nudged(db_id)
                                except Exception:
                                    pass
                                self._dispatch_commitment_nudge(c)
                                continue
                            # 未 fire: ttl 检查 (默认 24h)
                            _ttl_s = float(c.get('ttl_s', 86400))
                            _age = now - float(c.get('created_at', now))
                            if _age > _ttl_s:
                                c['nudged'] = True
                                try:
                                    from jarvis_utils import bg_log as _wb
                                    _wb(f"⏰ [CommitmentWatcher/Predicate] EXPIRED ({_ttl_s/3600:.0f}h) "
                                        f"never fired: '{c['description'][:50]}'")
                                except Exception:
                                    pass
                            continue

                        if now > c['deadline_ts'] + c['grace_minutes'] * 60:
                            try:
                                idle_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
                                if idle_ms < 120000:
                                    c['nudged'] = True
                                    # [P0+18-e.3] 同步到 SQLite，重启后避免再 nudge
                                    try:
                                        db_id = c.get('db_id', 0)
                                        if db_id and db_id > 0:
                                            hippo = self._get_hippo()
                                            if hippo is not None:
                                                hippo.mark_commitment_nudged(db_id)
                                    except Exception:
                                        pass
                                    self._dispatch_commitment_nudge(c)
                            except:
                                pass

                time.sleep(30)
            except Exception:
                time.sleep(30)

    def _build_predicate_ctx(self, now_ts: float) -> dict:
        """β.2.8.6: 每 tick 构造 predicate evaluation context.
        含 idle_ms / sensor_snap / window_title / recent_stm / process events 等.
        失败的字段静默落空 (predicate evaluate 时自己处理 None / default).

        🩹 [β.2.8.13 / 2026-05-18] 加 was_afk_recently_minutes 给 AfterAfk predicate.
        启发式: ReturnSentinel._last_afk_minutes 暴露最近 AFK 时长.
        """
        ctx = {'now_ts': now_ts}
        try:
            ctx['idle_ms'] = win32api.GetTickCount() - win32api.GetLastInputInfo()
        except Exception:
            ctx['idle_ms'] = 0
        try:
            from jarvis_env_probe import PhysicalEnvironmentProbe as P
            snap = P.get_sensor_snapshot() or {}
            ctx['sensor_snap'] = snap
            ctx['window_title'] = snap.get('window_title', '') or getattr(P, 'current_window_title', '')
            ctx['first_active_today'] = bool(snap.get('is_first_active_today', False))
            ctx['process_died_events'] = getattr(P, 'process_died_events', []) or []
            ctx['running_processes'] = getattr(P, 'running_processes_cache', []) or []
        except Exception:
            ctx['sensor_snap'] = {}
            ctx['window_title'] = ''
            ctx['first_active_today'] = False
            ctx['process_died_events'] = []
            ctx['running_processes'] = []
        # was_afk_recently_minutes — 从 ReturnSentinel 拿最近 AFK 时长 (β.2.8.13)
        try:
            rs = getattr(self.worker, 'return_sentinel', None)
            if rs is not None:
                ctx['was_afk_recently_minutes'] = float(
                    getattr(rs, '_last_afk_minutes', 0) or 0
                )
            else:
                ctx['was_afk_recently_minutes'] = 0
        except Exception:
            ctx['was_afk_recently_minutes'] = 0
        try:
            stm = getattr(self.worker.jarvis, 'short_term_memory', None) \
                  if hasattr(self.worker, 'jarvis') else None
            ctx['recent_stm'] = list(stm) if stm else []
        except Exception:
            ctx['recent_stm'] = []
        return ctx

    def _dispatch_commitment_nudge(self, commitment):
        overdue_minutes = int((time.time() - commitment['deadline_ts']) / 60)
        context = {
            "type": "commitment_check",
            "commitment_description": commitment['description'],
            # 🩹 [β.2.7.8] 传原话给 nudge prompt, LLM 必须引用原话而不是幻觉细节
            "commitment_source_text": commitment.get('source_text', '')[:200],
            "commitment_time": time.strftime("%H:%M", time.localtime(commitment['deadline_ts'])),
            "source_text": commitment['source_text'],
            "overdue_minutes": overdue_minutes
        }
        if self.gate and not self.gate.can_speak('guardian', is_urgent=True, nudge_type='commitment_check'):
            return
        cmd = f"__NUDGE__:{json.dumps(context, ensure_ascii=False)}"
        self.worker.push_command(cmd)
        if self.gate:
            self.gate.mark_spoke('guardian')

        try:
            if hasattr(self.worker, 'causal_chain'):
                self.worker.causal_chain.record(
                    "commitment_breach",
                    f"Committed to {commitment['description']} by {time.strftime('%H:%M', time.localtime(commitment['deadline_ts']))}, overdue by {overdue_minutes}min"
                )
        except:
            pass


# ==========================================
# 🎭 [P0+19-5 / 2026-05-16] HumorMemory 已拆到 jarvis_memory_core.py
# ==========================================
from jarvis_memory_core import HumorMemory


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

