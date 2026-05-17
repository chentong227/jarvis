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
                       source: str = 'user_text'):
        """source='user_text' (Sir 承诺) | 'self_promise' (Jarvis 自承诺)
        🩹 [β.2.7.3 / 2026-05-17] 加 source — Jarvis 自承诺与 Sir 承诺平等持久化"""
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

        with self._lock:
            deadline_ts = time.time() + 3600
            if deadline_str:
                try:
                    dl_lower = deadline_str.lower().strip()
                    time_match = re.search(r'(\d{1,2})\s*:\s*(\d{2})', dl_lower)
                    if time_match:
                        h, m = int(time_match.group(1)), int(time_match.group(2))
                        deadline_ts = self._to_24h(h, m, None)
                    elif 'tonight' in dl_lower:
                        deadline_ts = self._to_24h(22, 0, None)
                    elif 'tomorrow' in dl_lower:
                        deadline_ts = time.time() + 86400
                    elif 'next week' in dl_lower:
                        deadline_ts = time.time() + 604800
                    elif 'in' in dl_lower:
                        num_match = re.search(r'in\s+(\d+)\s*(min|hour|minute)', dl_lower)
                        if num_match:
                            n = int(num_match.group(1))
                            unit = num_match.group(2)
                            deadline_ts = time.time() + (n * 60 if 'min' in unit else n * 3600)
                except:
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

            self.commitments.append({
                'db_id': _new_db_id,
                'deadline_ts': deadline_ts,
                'description': description,
                'grace_minutes': 10,
                'nudged': False,
                'source_text': f"[Commitment] {description}",
                'source': source,  # 🩹 β.2.7.3: 'user_text' | 'self_promise'
                'created_at': time.time()
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

    def _dispatch_commitment_nudge(self, commitment):
        overdue_minutes = int((time.time() - commitment['deadline_ts']) / 60)
        context = {
            "type": "commitment_check",
            "commitment_description": commitment['description'],
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

