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


# ============================================================
# 🩹 [β.2.9.11 / 2026-05-18] 灵魂闭环 A — 通用 helper (准则 6 vocab 驱动)
# 🩹 [β.2.9.12 / 2026-05-18] Sir 12:53 反馈: vocab 不能硬编码 in py, 必须可加/改/删
# vocab 持久化到 memory_pool/behavior_inference_vocab.json:
#   - Sir 用 scripts/behavior_vocab_dump.py 看/加/改 (类 concerns_dump CLI 风格)
#   - INTEGRITY_STACK L7 (未来) WeeklyReflector 自动 propose 新 pattern 入 review
#   - py 里只留 _SEED_BEHAVIOR_PATTERNS 作 fallback (json 损坏 / 首次启动)
# ============================================================

# Fallback seed — 仅 json 不存在/损坏时用. 真正 vocab 在 json.
_SEED_BEHAVIOR_PATTERNS = [
    ({'睡', '上床', '关灯', '休息', '躺', '困', 'sleep', 'bed', 'rest', 'nap',
      'turn in', 'crash', 'goodnight'},
     {'kind': 'idle_min', 'threshold': 30}),
    ({'歇会', '走两步', '休息一下', 'break', 'pause', 'breather', 'stretch'},
     {'kind': 'idle_min', 'threshold': 5}),
    ({'刷题', '做题', '复习', '学习', '看完', '读完', '完成', '搞定',
      'finish', 'done', 'complete', 'wrap up'},
     {'kind': 'stm_contains',
      'kws': ['完成', '搞定', '做完了', '看完了', 'done', 'finished', 'wrapped']}),
]

_BEHAVIOR_VOCAB_PATH = os.path.join('memory_pool', 'behavior_inference_vocab.json')
_BEHAVIOR_PATTERNS_CACHE: Optional[List[Tuple[set, dict]]] = None
_BEHAVIOR_PATTERNS_MTIME: float = 0.0


def _load_behavior_patterns_from_json() -> Optional[List[Tuple[set, dict]]]:
    """从持久化 json 加载 active pattern. 失败返 None 走 fallback."""
    if not os.path.exists(_BEHAVIOR_VOCAB_PATH):
        return None
    try:
        with open(_BEHAVIOR_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        out: List[Tuple[set, dict]] = []
        for p in data.get('patterns', []):
            if not isinstance(p, dict):
                continue
            if p.get('state') != 'active':
                continue
            kws = p.get('keywords') or []
            eb = p.get('expected_behavior') or {}
            if not kws or not eb or not eb.get('kind'):
                continue
            out.append((set(kws), dict(eb)))
        return out
    except Exception:
        return None


def get_behavior_patterns() -> List[Tuple[set, dict]]:
    """🩹 [β.2.9.12] 带 file mtime cache, json 文件变了自动 reload, 不必重启 Jarvis.
    Sir 用 scripts/behavior_vocab_dump.py 改 json → 下次 add_commitment 即生效.
    """
    global _BEHAVIOR_PATTERNS_CACHE, _BEHAVIOR_PATTERNS_MTIME
    try:
        mtime = os.path.getmtime(_BEHAVIOR_VOCAB_PATH) if os.path.exists(
            _BEHAVIOR_VOCAB_PATH) else 0
    except OSError:
        mtime = 0
    if _BEHAVIOR_PATTERNS_CACHE is None or mtime > _BEHAVIOR_PATTERNS_MTIME:
        loaded = _load_behavior_patterns_from_json()
        if loaded is not None:
            _BEHAVIOR_PATTERNS_CACHE = loaded
        else:
            _BEHAVIOR_PATTERNS_CACHE = _SEED_BEHAVIOR_PATTERNS
        _BEHAVIOR_PATTERNS_MTIME = mtime
    return _BEHAVIOR_PATTERNS_CACHE


def infer_concern_link(description: str) -> Optional[str]:
    """通用 — 复用 ConcernsReflector 的 concern_keywords vocab 反查 concern_link.

    准则 6: 不写 concern → keyword 硬编码 if 链, 用 reflector vocab 反查.
    任何新 concern 在 reflector 加 keyword → 此函数自动支持, 0 改动.
    🩹 [β.3.4-vocab7] 改用 get_concern_keywords() 享 mtime reload (Sir CLI 改 json 即生效).
    """
    if not description:
        return None
    try:
        from jarvis_soul_reflector import get_concern_keywords
    except Exception:
        return None
    t = description.lower()
    best_cid = None
    best_score = 0
    for cid, kw_list in get_concern_keywords().items():
        score = 0
        for kw, delta in kw_list:
            if kw in t:
                score += abs(float(delta))
        if score > best_score:
            best_score = score
            best_cid = cid
    return best_cid


def infer_expected_behavior(description: str) -> Optional[dict]:
    """通用 — 从 description vocab 推 fulfillment 验证方式.

    准则 6: vocab 表驱动, 不针对 sleep/break 写专门 if 分支.
    🩹 [β.2.9.12] vocab 来源动态: memory_pool/behavior_inference_vocab.json,
    Sir 改 json 后下次调本函数即生效 (mtime cache 自动 reload).
    🩹 [β.5.39-fix / 2026-05-20] Sir 15:22 真理: vocab 默认 30min threshold 对
    Sir 真说 "休息 5 分钟" 来说太严. 修法: 优先 parse description 显式时间
    (user evidence > vocab default), 用真时间覆盖 idle_min threshold.
    """
    if not description:
        return None
    t = description.lower()
    behavior = None
    for kws, b in get_behavior_patterns():
        if any(k in t for k in kws):
            behavior = dict(b)  # 返副本防意外 mutate
            break
    if behavior is None:
        return None
    # 优先 parse description 显式时间 (user evidence > vocab default)
    if behavior.get('kind') == 'idle_min':
        import re as _re
        # 中文: X 分钟 / X 分 / X 小时
        m_zh = _re.search(r'(\d+)\s*(?:分钟|分(?!\w)|min(?:ute)?s?)', t)
        if m_zh:
            try:
                behavior['threshold'] = max(1, int(m_zh.group(1)))
                behavior['_threshold_source'] = 'description_explicit'
                return behavior
            except Exception:
                pass
        m_hr = _re.search(r'(\d+)\s*(?:小时|hours?|hrs?|h)', t)
        if m_hr:
            try:
                behavior['threshold'] = max(1, int(m_hr.group(1)) * 60)
                behavior['_threshold_source'] = 'description_explicit'
                return behavior
            except Exception:
                pass
        # 中文数字 (半小时 / 一小时)
        if '半小时' in t or 'half hour' in t or 'half an hour' in t:
            behavior['threshold'] = 30
            behavior['_threshold_source'] = 'description_explicit'
            return behavior
        if '一小时' in t or 'one hour' in t or 'an hour' in t:
            behavior['threshold'] = 60
            behavior['_threshold_source'] = 'description_explicit'
            return behavior
    return behavior

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
                        'grace_minutes': row.get('grace_minutes', 2),  # 🩹 [P4-Case1 / 2026-05-20 23:55] default 10→2 (Sir 期待 commitment 准点 fire)
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

        # 🆕 [Reshape M4.5.2 / 2026-05-24] 启动也从 PromiseLog 拉 active commitment.
        # M4.5.1 dual-write 让 add_commitment 同时进 PromiseLog. 这里 daemon 启动
        # 时也从 PromiseLog 拉 pending kind=commitment 进 self.commitments, 让
        # M4.5.3 安全停 SQLite 写后 daemon 仍能从 PromiseLog 单源工作.
        # dedup: 已在 self.commitments (来自 SQLite) 的 desc 不重加.
        try:
            self._load_from_promise_log_locked(max_age_hours=48.0)
        except Exception as _e:
            try:
                from jarvis_utils import bg_log as _cw_load_bg
                _cw_load_bg(f"⚠️ [CommitmentWatcher/PromiseLog] load 失败: {str(_e)[:80]}")
            except Exception:
                pass

    def _load_from_promise_log_locked(self, max_age_hours: float = 48.0) -> int:
        """[M4.5.2] 从 PromiseLog 拉 pending kind=commitment 进 self.commitments.

        dedup: 同 description (lowercase strip) 已在 list 中 → 跳过.
        年龄过滤: deadline_ts 比 now - max_age_hours 老 → 跳过 (过期不补 nudge).
        返回真新加的条数.
        """
        try:
            from jarvis_promise_log import get_default_log
            plog = get_default_log()
        except Exception:
            return 0
        if not hasattr(plog, 'list_pending'):
            return 0
        existing_descs = set()
        for c in self.commitments:
            d = (c.get('description') or '').strip().lower()
            if d:
                existing_descs.add(d)
        added = 0
        cutoff_ts = time.time() - max_age_hours * 3600
        for p in plog.list_pending():
            if getattr(p, 'kind', '') not in ('commitment', 'cyclic'):
                continue
            desc_l = (p.description or '').strip().lower()
            if not desc_l or desc_l in existing_descs:
                continue
            # 尝试 parse deadline_str → ts. 失败 fallback registered_at + 1h
            dl_ts = self._try_parse_deadline_str(p.deadline_str)
            if dl_ts <= 0:
                # 没法 parse 就 skip (避免错 nudge)
                continue
            if dl_ts < cutoff_ts:
                continue
            self.commitments.append({
                'db_id': 0,  # PromiseLog 来源, 没 SQLite db_id
                'promise_id': p.id,  # 反向引用 (M4.5.3+ daemon 直接走 PromiseLog 标 fulfilled 用)
                'deadline_ts': dl_ts,
                'description': p.description,
                'grace_minutes': 2,
                'nudged': False,
                'source_text': (p.jarvis_reply or '')[:240],
                'created_at': p.registered_at,
                'source': 'promise_log',  # 区别 SQLite 来源
            })
            existing_descs.add(desc_l)
            added += 1
        if added > 0:
            try:
                from jarvis_utils import bg_log as _pl_bg
                _pl_bg(f"📥 [CommitmentWatcher/PromiseLog] 从 PromiseLog 恢复 {added} 条 pending commitment")
            except Exception:
                pass
        return added

    def _dual_mark_fired(self, c: dict) -> None:
        """[Reshape M4.5.3 / 2026-05-24] daemon 触发 nudge 后, 同步标 SQLite + PromiseLog.

        SQLite mark_commitment_nudged 是老路径 (避免重启重发). PromiseLog 加
        evidence_only (kind=cw_nudge_fired) 让 trace 看 daemon 真触发了哪条.
        Sir 真用一段后, 看 PromiseLog evidence 充足 → M5+ 可停 SQLite mark
        (cleanup checklist #3 兑现).

        失败静默不破老流 (准则 1 高效). 注: 不调 mark_fulfilled — fired 不等于
        Sir 完成, 完成 evidence 主脑下轮 fast_call.complete 才填.
        """
        # 1. 老 SQLite mark (兼容老 daemon load_active_commitments 过滤)
        try:
            db_id = c.get('db_id', 0)
            if db_id and db_id > 0:
                hippo = self._get_hippo()
                if hippo is not None:
                    hippo.mark_commitment_nudged(db_id)
        except Exception:
            pass
        # 2. 新 PromiseLog evidence (M5+ 真停老路径前要先 dual-write)
        try:
            _pid = c.get('promise_id', '') or ''
            if _pid:
                from jarvis_promise_log import get_default_log
                _plog = get_default_log()
                _plog.add_evidence_only(
                    promise_id=_pid,
                    evidence_kind='cw_nudge_fired',
                    evidence_what=(
                        f"CW daemon fired nudge: {c.get('description','')[:80]} "
                        f"@ deadline_ts={c.get('deadline_ts',0):.0f}"
                    ),
                )
        except Exception:
            pass

    def _try_parse_deadline_str(self, deadline_str: str) -> float:
        """parse 'HH:MM' / 'YYYY-MM-DD HH:MM:SS' → epoch ts. 失败返 0.0."""
        if not deadline_str:
            return 0.0
        s = deadline_str.strip()
        # try 'YYYY-MM-DD HH:MM:SS' 长格式
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
            try:
                return time.mktime(time.strptime(s, fmt))
            except Exception:
                pass
        # try 'HH:MM' 短格式 — 今天该时间, 已过则推明天
        try:
            hh, mm = s.split(':')[:2]
            hh, mm = int(hh), int(mm)
            # 严格范围 hh 0-23 mm 0-59 (避免 '25:99' 这种无效输入 time.mktime
            # auto-normalize 后被当成有效 ts)
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                return 0.0
            now = time.localtime()
            cand = time.mktime((now.tm_year, now.tm_mon, now.tm_mday,
                                  hh, mm, 0, 0, 0, -1))
            if cand < time.time() - 60:
                cand += 86400
            return cand
        except Exception:
            return 0.0

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
                                    grace_minutes=2,  # 🩹 [P4-Case1 / 2026-05-20 23:55] default 10→2
                                    source_text=user_text[:200] if user_text else '',
                                    created_at=time.time(),
                                )
                        except Exception:
                            pass
                        self.commitments.append({
                            'db_id': _new_db_id,
                            'deadline_ts': deadline_ts,
                            'description': description,
                            'grace_minutes': 2,  # 🩹 [P4-Case1] default 10→2
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
                       action_target: str = 'sir',
                       concern_link: str = None,
                       expected_behavior: dict = None):
        """🩹 [β.2.9.11 / 2026-05-18] 灵魂闭环 A — Sir 10:43 + 12:35 要求:
          'Jarvis 关心 → 我承诺 → 履约/违约 → 动态影响关心值'

        新参数 (准则 6 通用):
          concern_link: 关联到哪个 concern (如 'sir_sleep_streak') — 履约后
                        调 ledger.record_signal + notify_concern_aligned/rejected
          expected_behavior: 怎么验证履约 (dict, kind 驱动):
            {'kind': 'idle_min', 'threshold': 30}   # idle X min = 履约 (sleep/rest)
            {'kind': 'process_exit', 'name': 'X'}   # 进程退出 = 履约 (剪完视频)
            {'kind': 'stm_contains', 'kws': [...]}  # STM 含完成词 = 履约 (任务类)
            None → 不检测履约 (老路径, 兼容)

          调用方可手动传, 也可走 infer_concern_link / infer_expected_behavior
          自动推断 (见 jarvis_commitment_watcher.py 模块级函数).
        """
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

        # 🛡️ [β.4.11 / 2026-05-19] Conditional / status-description vocab gate
        # Sir 01:07 原话: "呃呃，现在先不睡，今晚有重要工作，模块推进完成了再睡觉。今晚稍微熬一下"
        # → Gatekeeper LLM 误抓成 commitment + 幻觉 deadline=08:00 (Sir 完全没说 8 点) → 险些 8:00 闹 Sir.
        # 修法 (准则 6.5 vocab 持久化 + L7 reflector 明日做):
        #   memory_pool/commitment_conditional_vocab.json 含 3 类 markers:
        #   - markers_conditional: "完成…再睡" / "做完…再睡" / "等…完…睡" — 条件性, 没 deadline
        #   - markers_intent_vague: "今晚熬" / "稍微熬" / "晚点睡" — 模糊意图, LLM 易猜时间
        #   - markers_negation_status: "先不睡" / "暂时不睡" — 状态否定, 不是承诺
        #   命中任一 → 转 PromiseLog soft (Sir 仍知道发生了, 不到点闹), 不注册 hard.
        # 对照 user_text 原话 + description (Gatekeeper 抽象后) 双查.
        try:
            import json as _cw_json
            import os as _cw_os
            _vocab_path = _cw_os.path.join('memory_pool', 'commitment_conditional_vocab.json')
            if _cw_os.path.exists(_vocab_path):
                with open(_vocab_path, 'r', encoding='utf-8') as _vf:
                    _vocab = _cw_json.load(_vf)
                _all_markers = (
                    list(_vocab.get('markers_conditional', [])) +
                    list(_vocab.get('markers_intent_vague', [])) +
                    list(_vocab.get('markers_negation_status', []))
                )
                _check_text = (user_text or '') + ' || ' + (description or '')
                _hit_marker = None
                for _mp in _all_markers:
                    try:
                        if re.search(_mp, _check_text):
                            _hit_marker = _mp
                            break
                    except re.error:
                        continue
                if _hit_marker and not is_future_task_confirmed:
                    # 转 PromiseLog soft (Sir 知道发生了, 不闹)
                    # 🩹 [β.5.30 / 2026-05-20] author='sir' (这是 Sir 自己 cmd 表态, 不是 Jarvis 承诺)
                    try:
                        from jarvis_promise_log import get_default_log as _gpl
                        _log = _gpl()
                        _log.register(
                            description=description,
                            kind='soft',
                            deadline_str=deadline_str or '',
                            jarvis_reply='',
                            turn_id='',
                            lang='zh' if re.search(r'[\u4e00-\u9fa5]', description) else 'en',
                            author='sir',
                        )
                    except Exception:
                        pass
                    try:
                        from jarvis_utils import bg_log as _cw_bg_log
                        _cw_bg_log(
                            f"📝 [CommitmentWatcher] 🛡️ Conditional vocab 命中 (marker='{_hit_marker}'): "
                            f"'{description[:60]}' → 转 PromiseLog soft (不到点闹). "
                            f"原话: '{(user_text or '')[:60]}'"
                        )
                    except Exception:
                        pass
                    return
        except Exception:
            pass

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
                # 🩹 [β.5.30 / 2026-05-20] author='sir' (这个路径是 Sir cmd 推进来, 不是 Jarvis reply 承诺)
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
                        author='sir',
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
                        grace_minutes=2,  # 🩹 [P4-Case1] default 10→2
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
                'grace_minutes': 2,  # 🩹 [P4-Case1] default 10→2
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
                # 🩹 β.2.9.11: 灵魂闭环 A — 关联 concern + 验证方式
                # 优先级: caller 传 > ProactiveCare nudge backfill (tick 时) >
                #         infer_concern_link 反查 reflector CONCERN_KEYWORDS
                'concern_link': concern_link or infer_concern_link(description),
                'expected_behavior': expected_behavior or infer_expected_behavior(description),
                'fulfillment_checked': False,  # 防重复检测
                'concern_link_inferred_at': 0.0,  # 自动 backfill 时间戳
            })
            dl_str = time.strftime("%H:%M", time.localtime(deadline_ts))
            # [P0+18-c.8 / 2026-05-15] 改 bg_log 不漏到对话框
            try:
                from jarvis_utils import bg_log as _cw_bg_log
                _src_tag = '/SelfPromise' if source == 'self_promise' else ''
                _cw_bg_log(f"📝 [CommitmentWatcher{_src_tag}] 已注册: {description} @ {dl_str} (DB#{_new_db_id})")
            except Exception:
                pass

            # 🆕 [Reshape M4.5.1 / 2026-05-24] DUAL-WRITE to PromiseLog (单源准备)
            # 老 SQLite 仍写 (CW daemon 老路径不破), 新 PromiseLog 也写一份, 让 M4.5.2
            # daemon 切到 PromiseLog 时 0 数据丢失. 失败静默不破老路径 (准则 1 高效).
            try:
                from jarvis_memory_hub import get_default_hub
                _hub = get_default_hub()
                _iso_dl = time.strftime('%Y-%m-%d %H:%M:%S',
                                          time.localtime(deadline_ts))
                _who = 'jarvis' if source == 'self_promise' else 'sir'
                _hub.write_commitment(
                    description=description,
                    kind='commitment',
                    who_promised=_who,
                    deadline=_iso_dl,
                    source=f'cw.add_commitment.dual_write/{source}',
                    jarvis_reply='',
                    bound_to_concern_id=(concern_link or ''),
                )
            except Exception:
                pass
            # 🩹 [β.5.44-B / 2026-05-20 19:07] publish_intent (β.5.0 三维耦合)
            # 让 IntentResolver 看 deadline candidate, 主脑下轮知道有承诺已注册.
            try:
                from jarvis_utils import get_event_bus as _b544_geb
                _b544_bus = _b544_geb()
                if _b544_bus is not None:
                    _b544_bus.publish(
                        etype='sir_intent_deadline_candidate',
                        description=f'commitment registered: {str(description)[:60]} @ {dl_str}',
                        source=f'CommitmentWatcher.{source}',
                        salience=0.65,
                        metadata={
                            'confidence': 0.90,  # add_commitment 已成功
                            'judgement': {
                                'description': str(description)[:200],
                                'deadline_str': dl_str,
                                'deadline_ts': float(deadline_ts),
                                'source': source,
                                'db_id': _new_db_id,
                                'mutated_already': True,
                            },
                        },
                    )
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

    def _consume_pending_callbacks(self) -> int:
        """🩹 [β.5.33 / 2026-05-20] 消费 dashboard activate 写入的 pending_callbacks.jsonl.

        每条 → add_commitment (cross_session=True 不走 conditional vocab).
        truncate 后 jsonl 清空, 避免重复消费.
        """
        path = os.path.join('memory_pool', 'pending_callbacks.jsonl')
        if not os.path.exists(path):
            return 0
        try:
            lines = []
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        lines.append(line)
            if not lines:
                return 0
            consumed = 0
            for line in lines:
                try:
                    cb = json.loads(line)
                    action = (cb.get('action') or '').strip()
                    when_iso = (cb.get('when_iso') or '').strip()
                    if not action:
                        continue
                    self.add_commitment(
                        description=action,
                        deadline_str=when_iso,
                        user_text=cb.get('source_utterance', ''),
                        is_future_task_confirmed=True,
                        source='cross_session_callback',
                    )
                    consumed += 1
                except Exception as e:
                    try:
                        from jarvis_utils import bg_log
                        bg_log(f"⚠️ [CommitmentWatcher] consume callback 失败: {e}")
                    except Exception:
                        pass
            # truncate 文件 (全部消费)
            with open(path, 'w', encoding='utf-8') as f:
                f.write('')
            if consumed > 0:
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"📅 [CommitmentWatcher β.5.33] 消费 {consumed} 条跨 session callback → commitment")
                except Exception:
                    pass
            return consumed
        except Exception as e:
            try:
                from jarvis_utils import bg_log
                bg_log(f"⚠️ [CommitmentWatcher] _consume_pending_callbacks IO 失败: {e}")
            except Exception:
                pass
            return 0

    def run(self):
        time.sleep(30)
        print("[CommitmentWatcher] 承诺看门狗就绪...", file=sys.stderr)
        # 🩹 [β.5.33 / 2026-05-20] 启动时立刻消费 pending_callbacks (Sir 之前 activate 的)
        self._consume_pending_callbacks()
        _last_callback_check = time.time()
        # 🆕 [Reshape M4.4 / 2026-05-24] daemon 周期 reload from PromiseLog (单源真理)
        # 每 5min 拉一次 pending kind=commitment, 让 SQLite/PromiseLog 不一致时 (e.g.
        # main brain FAST_CALL.complete 标 fulfilled, 但 SQLite 还显示 active) daemon
        # 不会 stale fire. M4.5.1 dual-write 保证两源数据等价, 这里 reload 只是 catchup.
        _last_plog_reload = time.time()
        _PLOG_RELOAD_INTERVAL = 300.0  # 5min
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
                                # [M4.5.3] dual-mark SQLite + PromiseLog evidence
                                self._dual_mark_fired(c)
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

                        # 🆕 [Sir 真测 BUG-3 治本 / 2026-05-24 16:15] 自动 retire 过期承诺
                        # Sir 痛点: "过期的 commit 就不要存在 commit 了, 存在长期的记忆那边,
                        # 我不需要他一直拿过期的 commit 骚扰我". 真治本 (准则 6 + 8):
                        #   deadline 过 _AUTO_RETIRE_HOURS (default 6h) 还没 fulfilled → 自动 retire.
                        #   - SQLite mark is_deleted=1 (CommitmentWatcher 重启后不再读)
                        #   - PromiseLog mark state=fulfilled + evidence kind=auto_retire_overdue
                        #     (历史 evidence 保留, 主脑通过 PromiseLog 看历史)
                        #   - SWM publish commitment_retired event (主脑下轮看到)
                        #   - skip nudge (这次不催)
                        # 这条放在 fulfillment pre-check 前: 6h+ 过期的不需要再 check
                        # fulfillment, 直接 retire (减 LLM 调用).
                        _AUTO_RETIRE_HOURS = 6.0
                        _retire_threshold = c['deadline_ts'] + _AUTO_RETIRE_HOURS * 3600
                        if now > _retire_threshold and not c.get('nudged') and not c.get('auto_retired'):
                            c['nudged'] = True
                            c['auto_retired'] = True
                            try:
                                # 1) SQLite mark is_deleted=1
                                _hippo = self._get_hippo()
                                _db_id = c.get('db_id', 0)
                                if _hippo is not None and _db_id and _db_id > 0:
                                    if hasattr(_hippo, 'soft_delete_commitment'):
                                        _hippo.soft_delete_commitment(_db_id)
                                # 2) PromiseLog mark state=fulfilled + evidence
                                try:
                                    from jarvis_promise_log import get_default_log
                                    _plog = get_default_log()
                                    _pid = c.get('promise_id', '')
                                    _retire_what = (
                                        f"Auto-retired by CommitmentWatcher: "
                                        f"deadline_ts={c['deadline_ts']:.0f}, "
                                        f"overdue_hours={(now - c['deadline_ts'])/3600:.1f}, "
                                        f"never fulfilled. 历史 evidence 保留."
                                    )
                                    if _pid and hasattr(_plog, 'mark_fulfilled'):
                                        _plog.mark_fulfilled(
                                            _pid,
                                            evidence_kind='auto_retire_overdue',
                                            evidence_what=_retire_what,
                                        )
                                    elif _pid and hasattr(_plog, 'add_evidence_only'):
                                        _plog.add_evidence_only(
                                            promise_id=_pid,
                                            evidence_kind='auto_retire_overdue',
                                            evidence_what=_retire_what,
                                        )
                                except Exception:
                                    pass
                                # 3) SWM publish commitment_retired
                                try:
                                    from jarvis_utils import get_event_bus
                                    _bus = get_event_bus()
                                    if _bus is not None:
                                        _overdue_h = (now - c['deadline_ts']) / 3600
                                        _bus.publish(
                                            etype='commitment_retired',
                                            description=(
                                                f"Sir 承诺 '{c.get('description','')[:60]}' "
                                                f"过期 {_overdue_h:.1f}h 未 fulfilled, 自动 retire 不再骚扰. "
                                                f"历史在 PromiseLog kind=auto_retire_overdue."
                                            ),
                                            source='CommitmentWatcher.auto_retire',
                                            salience=0.55,
                                            metadata={
                                                'description': c.get('description', '')[:200],
                                                'deadline_ts': c['deadline_ts'],
                                                'overdue_hours': round(_overdue_h, 2),
                                                'db_id': c.get('db_id', 0),
                                                'promise_id': c.get('promise_id', ''),
                                            },
                                        )
                                except Exception:
                                    pass
                                # 4) bg_log
                                try:
                                    from jarvis_utils import bg_log as _retire_bg
                                    _retire_bg(
                                        f"⏳ [CommitmentWatcher/AutoRetire] "
                                        f"'{c.get('description','')[:50]}' overdue "
                                        f"{(now - c['deadline_ts'])/3600:.1f}h "
                                        f"(>{_AUTO_RETIRE_HOURS}h threshold) → retired (no nudge)"
                                    )
                                except Exception:
                                    pass
                            except Exception as _ar_e:
                                try:
                                    from jarvis_utils import bg_log as _ar_bg
                                    _ar_bg(f"⚠️ [CommitmentWatcher/AutoRetire] {_ar_e}")
                                except Exception:
                                    pass
                            continue  # skip nudge / fulfillment check 路径

                        # 🩹 [β.5.39-fix2 / 2026-05-20 15:38] Sir 实测真理:
                        # commitment_check nudge 在 fulfillment 检测**之前** 触发 → Sir 真履行了也催!
                        # 修法: deadline-based nudge 之前先 check fulfillment, fulfilled → skip nudge
                        # 走 pending_ack 路径 (Sir 下次开口主脑致意).
                        # 这是 Sir 14:39 三层架构思想延伸: 先看 sensor evidence, 不见 evidence 才 sentinel hard action.
                        _fulfillment_done_pre_check = False
                        try:
                            if (not c.get('fulfillment_checked') and
                                    now > c['deadline_ts'] + self._FULFILLMENT_GRACE_S):
                                self._backfill_concern_link(c, now)
                                _pre_verdict = self._check_fulfillment(c, now)
                                if _pre_verdict == 'fulfilled':
                                    # Sir 真履行了, mark nudged=True 不催 + 走 fulfillment 反馈
                                    c['nudged'] = True
                                    # [M4.5.3] dual-mark SQLite + PromiseLog evidence
                                    self._dual_mark_fired(c)
                                    if c.get('concern_link'):
                                        self._on_fulfillment(c, _pre_verdict)
                                    c['fulfillment_checked'] = True
                                    _fulfillment_done_pre_check = True
                                    try:
                                        from jarvis_utils import bg_log as _ff_bg
                                        _ff_bg(
                                            f"✅ [CommitmentWatcher/PreCheckFulfilled] '{c.get('description', '?')[:60]}' "
                                            f"Sir 已履行 → skip nudge (β.5.39-fix2)"
                                        )
                                    except Exception:
                                        pass
                        except Exception as _pre_e:
                            try:
                                from jarvis_utils import bg_log as _pre_bg
                                _pre_bg(f"⚠️ [CommitmentWatcher/PreCheck] {_pre_e}")
                            except Exception:
                                pass

                        if not _fulfillment_done_pre_check and now > c['deadline_ts'] + c['grace_minutes'] * 60:
                            try:
                                idle_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
                                if idle_ms < 120000:
                                    c['nudged'] = True
                                    # [P0+18-e.3] 同步到 SQLite，重启后避免再 nudge
                                    # [M4.5.3] dual-mark SQLite + PromiseLog evidence
                                    self._dual_mark_fired(c)
                                    self._dispatch_commitment_nudge(c)
                            except:
                                pass

                        # 🩹 [β.2.9.11 / 2026-05-18] 灵魂闭环 A — 履约检测
                        # 1. 自动 backfill concern_link (若 ProactiveCare nudge 后 120s 内创建)
                        # 2. deadline + grace 5min 后看 sensor → fulfilled/broken
                        # 3. 反馈调 ledger.record_signal + notify_concern_aligned/rejected
                        # 🩹 [β.5.39-fix2] 此 block 已在 PreCheck 处理过 fulfilled, 这里走 broken/unknown
                        try:
                            self._backfill_concern_link(c, now)
                            if (c.get('concern_link') and
                                    not c.get('fulfillment_checked') and
                                    now > c['deadline_ts'] + self._FULFILLMENT_GRACE_S):
                                verdict = self._check_fulfillment(c, now)
                                if verdict != 'unknown':
                                    self._on_fulfillment(c, verdict)
                                    c['fulfillment_checked'] = True
                        except Exception as _fce:
                            try:
                                from jarvis_utils import bg_log
                                bg_log(f"⚠️ [Closure/tick] {_fce}")
                            except Exception:
                                pass

                # 🩹 [β.5.33 / 2026-05-20] 周期消费 pending_callbacks (Sir 拍板后 < 5min 落地)
                if time.time() - _last_callback_check > 300:
                    _last_callback_check = time.time()
                    self._consume_pending_callbacks()

                # 🆕 [Reshape M4.4 / 2026-05-24] 周期 reload from PromiseLog (单源真理)
                if time.time() - _last_plog_reload > _PLOG_RELOAD_INTERVAL:
                    _last_plog_reload = time.time()
                    try:
                        with self._lock:
                            _added = self._load_from_promise_log_locked(max_age_hours=48.0)
                        if _added > 0:
                            from jarvis_utils import bg_log as _m44_bg
                            _m44_bg(f"📥 [CommitmentWatcher/M4.4] 周期 reload: +{_added} 条 from PromiseLog")
                    except Exception:
                        pass

                time.sleep(30)
            except Exception:
                time.sleep(30)

    # ============================================================
    # 🩹 [β.2.9.11 / 2026-05-18] 灵魂闭环 A — 履约/违约检测 + 反馈 concern
    # Sir 10:43+12:35 要求: 'Jarvis 关心 → 我承诺 → 履约/违约 → 动态影响关心值'
    # 通用化 (准则 6): 不针对 sleep 硬编码, expected_behavior 类型驱动.
    # ============================================================

    _FULFILLMENT_GRACE_S = 300.0  # deadline 后 5min 才检测 (Sir 真有时间去做)

    def _check_fulfillment(self, c: dict, now_ts: float) -> Optional[str]:
        """看 Sir 是否真兑现了 commitment. 返 'fulfilled' / 'broken' / 'unknown'.

        准则 6: expected_behavior['kind'] 驱动, 不针对 sleep 硬编码:
          idle_min       : Sir idle > threshold 分钟 = 履约 (适合 sleep/rest)
          process_exit   : 指定进程已退 = 履约 (适合 '剪完视频后...')
          stm_contains   : STM 最近含完成关键词 = 履约 (适合任务)
          其他           : 'unknown' (不调反馈, 避免误判)
        """
        eb = c.get('expected_behavior')
        if not eb or not isinstance(eb, dict):
            return 'unknown'

        kind = eb.get('kind', '')
        try:
            if kind == 'idle_min':
                threshold = float(eb.get('threshold', 30))
                # 看 sensor idle
                if 'win32api' in globals() and win32api is not None:
                    idle_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
                else:
                    return 'unknown'
                idle_min = idle_ms / 1000 / 60
                return 'fulfilled' if idle_min >= threshold else 'broken'

            elif kind == 'process_exit':
                exe = eb.get('name', '').lower()
                if not exe:
                    return 'unknown'
                try:
                    from jarvis_env_probe import PhysicalEnvironmentProbe as P
                    events = getattr(P, 'process_died_events', []) or []
                except Exception:
                    events = []
                # 最近 30min 内 exe 退过 = 履约
                cutoff = now_ts - 1800
                for ev in events:
                    if ev.get('exe', '').lower() == exe and ev.get('when', 0) >= cutoff:
                        return 'fulfilled'
                return 'broken'

            elif kind == 'stm_contains':
                kws = eb.get('kws', []) or []
                if not kws:
                    return 'unknown'
                try:
                    stm = getattr(self.worker, 'short_term_memory', []) or []
                except Exception:
                    stm = []
                # 最近 5 条 STM 看 user/jarvis 是否含 keyword
                for entry in stm[-5:]:
                    blob = f"{entry.get('user', '')} {entry.get('jarvis', '')}".lower()
                    if any(k.lower() in blob for k in kws):
                        return 'fulfilled'
                return 'broken'
        except Exception:
            return 'unknown'
        return 'unknown'

    def _on_fulfillment(self, c: dict, verdict: str) -> None:
        """履约 / 违约 → 反馈 concern severity + notify_aligned/rejected.

        通用化: 任何 concern_link 都通过 ledger.record_signal 调.
        """
        cid = c.get('concern_link', '')
        if not cid:
            return
        desc = (c.get('description') or '')[:80]

        if verdict == 'fulfilled':
            evidence_what = f"Sir 兑现承诺: '{desc}'"
        elif verdict == 'broken':
            evidence_what = f"Sir 违约: '{desc}'"
        else:
            return  # unknown 不调

        # [β.4.9] severity_delta 从 vocab 读 (准则 6.5)
        # per_concern 覆盖优先, 没则 default (-0.20/+0.10)
        try:
            from jarvis_safety import _load_severity_delta
            severity_delta = _load_severity_delta(cid, verdict)
        except Exception:
            severity_delta = -0.2 if verdict == 'fulfilled' else 0.1

        # 1. 写 concern signal
        try:
            from jarvis_concerns import get_default_ledger
            ledger = get_default_ledger()
            if ledger is not None:
                ledger.record_signal(cid, evidence_what,
                                       severity_delta=severity_delta)
        except Exception as e:
            try:
                from jarvis_utils import bg_log
                bg_log(f"⚠️ [Closure/ledger] {e}")
            except Exception:
                pass

        # 2. 通知 ProactiveCare 调 fatigue map
        try:
            from jarvis_proactive_care import get_default_engine
            pce = get_default_engine()
            if pce is not None:
                if verdict == 'fulfilled':
                    pce.notify_concern_aligned(cid)
                else:
                    pce.notify_concern_rejected(cid)
        except Exception:
            pass

        # 3. PromiseLog 配对 evidence (Sir 兑现也是 Jarvis 言出必行的证据)
        try:
            from jarvis_promise_log import try_pair_evidence
            try_pair_evidence(
                evidence_kind='commitment_' + verdict,
                evidence_what=evidence_what,
            )
        except Exception:
            pass

        # 4. [P0+20-β.4.9 / 2026-05-19] pending_ack 注入 concern.notes_for_self
        # Sir 重设计 (2026-05-19): 不立刻 push (会吵醒 Sir / 多数 concern 没 sensor 验),
        # 改写一条 [pending_ack] 标记到 notes_for_self → Sir 下次主动开口时主脑读到 →
        # 自然致意 (反硬编码: 不写死句子, 信任主脑根据 evidence 涌现回答).
        # L5 SoulAlignmentEvaluator 后续清 [pending_ack] (reply 引用了 → 已致意).
        # 通用化: 任何 concern 都走同一管道, 新 concern 0 改动.
        try:
            from jarvis_concerns import get_default_ledger as _gdl
            _ledger2 = _gdl()
            if _ledger2 is not None:
                _c_obj = _ledger2.get(cid) if hasattr(_ledger2, 'get') else None
                if _c_obj is None and hasattr(_ledger2, 'concerns'):
                    _c_obj = _ledger2.concerns.get(cid)
                if _c_obj is not None:
                    _existing = (getattr(_c_obj, 'notes_for_self', '') or '').strip()
                    # 已含 [pending_ack ...] 不重复堆 (避免 N 次兑现 spam)
                    if '[pending_ack' not in _existing:
                        _hms = time.strftime('%H:%M', time.localtime(time.time()))
                        if verdict == 'fulfilled':
                            _ack_note = (
                                f"[pending_ack {_hms} fulfilled] Sir 真兑现了 "
                                f"'{desc[:60]}'. Sir 下次开口时, 自然致意一次 "
                                f"(短句, 不说教不重复关心), 致意后此 tag 清除."
                            )
                        else:
                            _ack_note = (
                                f"[pending_ack {_hms} broken] Sir 未兑现 "
                                f"'{desc[:60]}'. Sir 下次开口时, 温和提及一次 "
                                f"(不指责不催促, 关心而非压力), 致意后清除."
                            )
                        _new_notes = (_existing + " | " + _ack_note) if _existing else _ack_note
                        _c_obj.notes_for_self = _new_notes[:600]
                        _c_obj.last_updated = time.time()
                        try:
                            _ledger2.persist()
                        except Exception:
                            pass
                        try:
                            from jarvis_utils import bg_log as _ack_bg
                            _ack_bg(
                                f"📝 [pending_ack/{verdict}] concern={cid} 写入 notes_for_self "
                                f"(主脑下次自然致意)"
                            )
                        except Exception:
                            pass
        except Exception as _ack_e:
            try:
                from jarvis_utils import bg_log as _ack_err_bg
                _ack_err_bg(f"⚠️ [pending_ack] 写 notes_for_self 失败 (容忍): {_ack_e}")
            except Exception:
                pass

        try:
            from jarvis_utils import bg_log
            bg_log(
                f"🎯 [Closure/{verdict}] concern={cid} severity_delta={severity_delta:+.2f} "
                f"'{desc}'"
            )
        except Exception:
            pass

    def _backfill_concern_link(self, c: dict, now_ts: float) -> None:
        """自动 backfill: 若 commitment 在 ProactiveCare nudge 后 120s 内 register
        且无 concern_link → 自动关联到 last_nudge_concern_id.
        """
        if c.get('concern_link') or c.get('concern_link_inferred_at'):
            return  # 已有或已尝试
        c['concern_link_inferred_at'] = now_ts
        try:
            from jarvis_proactive_care import get_default_engine
            pce = get_default_engine()
            if pce is None:
                return
            info = pce.get_last_nudge_info()
            if info is None:
                return
            cid, last_ts = info
            created = float(c.get('created_at', 0) or 0)
            if abs(created - last_ts) > 120:
                return  # commitment 不在 nudge 后 120s 内
            c['concern_link'] = cid
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"🔗 [Closure] auto-link commitment '{c['description'][:50]}' "
                    f"→ concern={cid} (nudge 后 {int(created - last_ts)}s 内 register)"
                )
            except Exception:
                pass
            # 同时 infer expected_behavior (若没传)
            if not c.get('expected_behavior'):
                eb = infer_expected_behavior(c.get('description', ''))
                if eb:
                    c['expected_behavior'] = eb
        except Exception:
            pass

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
        # 🆕 [P5-fix72 / 2026-05-23 17:11] BUG-F: Sir 17:01 ack reminder 后,
        # 17:03 commitment_check 又 fire "stand up and stretch" (同事). 根因:
        # commitment_watcher 不知 reminder_acknowledged. 修法 (准则 6 数据强耦合):
        # 检 SWM 近 30min reminder_acknowledged event 含同 keyword → skip nudge.
        try:
            _desc_lower = (commitment.get('description', '') or '').lower()
            if _desc_lower:
                from jarvis_utils import get_event_bus as _geb_ra
                _bus_ra = _geb_ra()
                if _bus_ra is not None:
                    _recent_acks = _bus_ra.recent_events(
                        within_seconds=1800.0,  # 30min
                        types={'reminder_acknowledged'},
                    )
                    for _ev in _recent_acks:
                        _ack_intent = (_ev.get('metadata', {}) or {}).get('intent', '')
                        if _ack_intent:
                            _ack_lower = _ack_intent.lower()
                            # fingerprint: 2 sides share >= 5 char overlap on key noun
                            # 简单: commitment desc 含 ack intent (or vice versa)
                            if (_ack_lower[:30] in _desc_lower
                                or _desc_lower[:30] in _ack_lower):
                                try:
                                    from jarvis_utils import bg_log as _skip_bg
                                    _skip_bg(
                                        f"🛡️ [CommitmentWatcher] skip nudge — "
                                        f"reminder 已 ack 30min 内 "
                                        f"(ack='{_ack_intent[:50]}' vs "
                                        f"commit='{commitment.get('description', '')[:50]}')"
                                    )
                                except Exception:
                                    pass
                                return  # skip, 不 dispatch
        except Exception:
            pass

        overdue_minutes = int((time.time() - commitment['deadline_ts']) / 60)
        # 🆕 [P5-fix42 / 2026-05-23 14:34] inject sleep evidence — 主脑 evidence-based
        # 自决, 不再直觉断言 'still working'. Sir 14:32 真痛点: NudgeGate 显示 sleep
        # 132min 但主脑三连"您没睡". 让 directive 看 NudgeGate 真状态.
        sleep_mode_active = False
        sleep_duration_min = 0
        recent_sleep_min = 0
        try:
            if self.gate and hasattr(self.gate, 'is_sleep_mode'):
                sleep_mode_active = bool(self.gate.is_sleep_mode())
                if sleep_mode_active and hasattr(self.gate, 'sleep_duration_seconds'):
                    sleep_duration_min = int(self.gate.sleep_duration_seconds() / 60)
        except Exception:
            pass
        # recent_sleep_min: 过去 1h 内 ReturnSentinel afk 累计 (代理量, 简单 proxy:
        # 当前 sleep_duration_min 也算入). 主脑读 evidence 判断.
        try:
            recent_sleep_min = sleep_duration_min  # 简版: sleep_mode 是主信号
            # 若已退出 sleep mode, 看 jarvis._last_user_active 距 commitment_time 是否
            # 有 > 30min gap (Sir 真睡过纳).
            if not sleep_mode_active and self.jarvis is not None:
                last_active = getattr(self.jarvis, '_last_user_active', 0) or 0
                # ReturnSentinel afk 时长 (近 1h)
                rs = getattr(self.jarvis, 'return_sentinel', None)
                if rs is not None and hasattr(rs, '_last_afk_seconds'):
                    afk_s = float(getattr(rs, '_last_afk_seconds', 0) or 0)
                    if afk_s > 1800:  # 30min+ AFK = 真休息过
                        recent_sleep_min = max(recent_sleep_min, int(afk_s / 60))
        except Exception:
            pass
        context = {
            "type": "commitment_check",
            "commitment_description": commitment['description'],
            # 🩹 [β.2.7.8] 传原话给 nudge prompt, LLM 必须引用原话而不是幻觉细节
            "commitment_source_text": commitment.get('source_text', '')[:200],
            "commitment_time": time.strftime("%H:%M", time.localtime(commitment['deadline_ts'])),
            "source_text": commitment['source_text'],
            "overdue_minutes": overdue_minutes,
            # 🆕 [P5-fix42] sleep evidence
            "sleep_mode_active": sleep_mode_active,
            "sleep_duration_min": sleep_duration_min,
            "recent_sleep_min": recent_sleep_min,
        }
        if self.gate and not self.gate.can_speak('guardian', is_urgent=True, nudge_type='commitment_check'):
            return

        # 🩹 [P5-fixC / 2026-05-21 09:55] β.5.0 行为弱耦合 — 看 SWM 让位最近 proactive nudge.
        # Sir 09:05/06 真测: ReturnSentinel return_greeting fire 后 55s commitment_check 又 fire,
        # Sir 还没回复 morning 问候. 这条 commitment 不是新的, deadline 是昨晚 23:30, 跟 morning
        # warmth 冲突. 让位 → 退化 publish-only, 不抢话筒.
        try:
            from jarvis_nudge_coordination import (
                should_yield_to_recent_proactive_nudge as _yield_check,
                publish_proactive_nudge_skipped as _pub_skip,
            )
            _should_yield, _yield_reason = _yield_check(
                within_s=600.0,
                current_kind='commitment_check',
                current_sentinel='SmartNudge',
            )
            if _should_yield:
                _pub_skip(
                    kind='commitment_check',
                    sentinel='SmartNudge',
                    reason=_yield_reason,
                    extra_metadata={
                        'commitment_description': commitment.get('description', '')[:60],
                        'overdue_minutes': overdue_minutes,
                    },
                )
                try:
                    from jarvis_utils import bg_log as _yld_bg
                    _yld_bg(
                        f"🤝 [CommitmentWatcher/Yield] commitment_check publish-only "
                        f"(让位 {_yield_reason})"
                    )
                except Exception:
                    pass
                return  # publish-only, 不 push __NUDGE__
        except Exception:
            pass  # 协调失败时走原 path (向后兼容)

        cmd = f"__NUDGE__:{json.dumps(context, ensure_ascii=False)}"
        self.worker.push_command(cmd)
        if self.gate:
            self.gate.mark_spoke('guardian')

        # 🆕 [Reshape M4.4 / 2026-05-24] dual-emit 'reminder_fired' SWM event.
        # M5.A SWM-trigger daemon 启用后, 此处 push __NUDGE__ 路径将退化为 publish-only.
        # 当前两路径并行 (push + publish), 数据强耦合保证主脑看见 evidence.
        try:
            from jarvis_utils import get_event_bus as _m44_geb
            _m44_bus = _m44_geb()
            if _m44_bus is not None:
                _m44_bus.publish(
                    etype='reminder_fired',
                    description=(
                        f"commitment overdue by {overdue_minutes}min: "
                        f"{commitment.get('description','')[:80]}"
                    ),
                    source='CommitmentWatcher._dispatch_commitment_nudge',
                    salience=0.85,
                    metadata={
                        'commitment_description': commitment.get('description', '')[:200],
                        'commitment_source_text': commitment.get('source_text', '')[:200],
                        'commitment_time': time.strftime("%H:%M", time.localtime(commitment['deadline_ts'])),
                        'overdue_minutes': overdue_minutes,
                        'sleep_mode_active': sleep_mode_active,
                        'sleep_duration_min': sleep_duration_min,
                        'recent_sleep_min': recent_sleep_min,
                        'promise_id': commitment.get('promise_id', ''),
                        'db_id': commitment.get('db_id', 0),
                        'fired_via': '__NUDGE__',  # current path; M5.A → 'swm_trigger'
                        'milestone': 'M4.4',
                    },
                )
        except Exception:
            pass

        # 🩹 [P5-fixC] commitment_check 真 fire → publish 让别的 sentinel 让位.
        try:
            from jarvis_nudge_coordination import publish_proactive_nudge_fired as _pn_pub
            _pn_pub(
                kind='commitment_check',
                sentinel='SmartNudge',
                extra_metadata={
                    'commitment_description': commitment.get('description', '')[:60],
                    'overdue_minutes': overdue_minutes,
                },
            )
        except Exception:
            pass

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

