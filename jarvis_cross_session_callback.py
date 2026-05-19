# -*- coding: utf-8 -*-
"""
🩹 [β.5.33 / 2026-05-20] Cross-session memory callback (PROACTIVITY_NEXT §E).

Sir 痛点: Sir 周一说"周三去刷题" → 周三主动提醒. 现有 commitment_watcher 只处理
explicit 时间 ("9:00 提醒我 X"). 软提议 ("过两天试试"/"周三看一下") 漏掉.

设计 (准则 6 服从):
1. SoulArchivistSentinel 反思 STM 时, 用 LLM 提取 "Sir 提到的未来动作 + 时间"
2. 写 memory_pool/cross_session_callback.json review queue (state=review)
3. Dashboard 显 → Sir 拍板 (通过/拒)
4. 通过 → 转 commitment_watcher hard commitment (到点 nudge)
5. 拒 → state=archived (不再 propose 同 desc)

数据格式:
{
  "callbacks": {
    "cb_<hash>": {
      "id": "cb_xxx",
      "action": "驾照科一刷题",
      "when_iso": "2026-05-22T09:00",
      "when_natural": "周三上午",
      "source_utterance": "明天我打算去刷一下科一",
      "source_turn_id": "turn_...",
      "proposed_at": <ts>,
      "state": "review"  # review/active/archived
    }
  }
}
"""
from __future__ import annotations
import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


_PATH = os.path.join('memory_pool', 'cross_session_callback.json')
STATE_REVIEW = 'review'
STATE_ACTIVE = 'active'
STATE_ARCHIVED = 'archived'


@dataclass
class Callback:
    id: str
    action: str
    when_iso: str = ''
    when_natural: str = ''
    source_utterance: str = ''
    source_turn_id: str = ''
    proposed_at: float = field(default_factory=time.time)
    state: str = STATE_REVIEW
    # 兑现追踪
    fired_at: float = 0.0
    fired_evidence: str = ''


class CrossSessionCallbackStore:
    """Cross-session callback store. 线程安全."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or _PATH
        self.callbacks: Dict[str, Callback] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
            for cb_id, cd in (data.get('callbacks') or {}).items():
                try:
                    self.callbacks[cb_id] = Callback(**cd)
                except Exception:
                    continue
        except Exception:
            pass

    def _persist(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({
                    'callbacks': {cid: asdict(c) for cid, c in self.callbacks.items()},
                }, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def propose(self, action: str, when_iso: str = '', when_natural: str = '',
                 source_utterance: str = '', source_turn_id: str = '') -> Optional[str]:
        """propose 新 callback. dedup: 同 action 已存在 → 跳过."""
        if not action:
            return None
        action = action[:200].strip()
        with self._lock:
            # dedup: action 高度相似 → 跳过
            action_l = action.lower()
            for ex in self.callbacks.values():
                if ex.state == STATE_ARCHIVED:
                    continue
                if (ex.action or '').lower() == action_l:
                    return ex.id  # 已 propose 过, 复用
                # token jaccard ≥ 0.7 也 dedup
                tk_new = set(action_l.split())
                tk_ex = set((ex.action or '').lower().split())
                if tk_new and tk_ex:
                    inter = len(tk_new & tk_ex)
                    union = len(tk_new | tk_ex)
                    if union > 0 and inter / union >= 0.7:
                        return ex.id
            cb_id = 'cb_' + uuid.uuid4().hex[:8]
            cb = Callback(
                id=cb_id,
                action=action,
                when_iso=when_iso[:30],
                when_natural=when_natural[:60],
                source_utterance=source_utterance[:200],
                source_turn_id=source_turn_id[:60],
            )
            self.callbacks[cb_id] = cb
            self._persist()
        return cb_id

    def list_review(self) -> List[Callback]:
        with self._lock:
            return [c for c in self.callbacks.values() if c.state == STATE_REVIEW]

    def list_active(self) -> List[Callback]:
        with self._lock:
            return [c for c in self.callbacks.values() if c.state == STATE_ACTIVE]

    def activate(self, cb_id: str) -> Optional[Callback]:
        """Sir 通过 → state=active. 同时返回 cb 让调方注册到 commitment_watcher."""
        with self._lock:
            cb = self.callbacks.get(cb_id)
            if not cb or cb.state != STATE_REVIEW:
                return None
            cb.state = STATE_ACTIVE
            self._persist()
            return cb

    def reject(self, cb_id: str) -> bool:
        """Sir 拒 → state=archived (不再 propose 同 action)."""
        with self._lock:
            cb = self.callbacks.get(cb_id)
            if not cb:
                return False
            cb.state = STATE_ARCHIVED
            self._persist()
        return True

    def mark_fired(self, cb_id: str, evidence: str = '') -> bool:
        with self._lock:
            cb = self.callbacks.get(cb_id)
            if not cb:
                return False
            cb.fired_at = time.time()
            cb.fired_evidence = evidence[:200]
            cb.state = STATE_ARCHIVED
            self._persist()
        return True


# ============================================================
# 单例
# ============================================================
_DEFAULT_STORE: Optional[CrossSessionCallbackStore] = None
_LOCK = threading.Lock()


def get_default_store() -> CrossSessionCallbackStore:
    global _DEFAULT_STORE
    with _LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = CrossSessionCallbackStore()
        return _DEFAULT_STORE


# ============================================================
# 简易时间解析 (LLM 给 when_natural, 这里转 ISO)
# ============================================================

_WEEKDAY_MAP = {
    '周一': 0, '周二': 1, '周三': 2, '周四': 3, '周五': 4, '周六': 5, '周日': 6, '周天': 6,
    '星期一': 0, '星期二': 1, '星期三': 2, '星期四': 3, '星期五': 4, '星期六': 5, '星期日': 6, '星期天': 6,
    'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6,
}


def parse_natural_time_to_iso(when_natural: str, base_ts: Optional[float] = None) -> str:
    """简易自然语言时间 → ISO. 失败返 ''.
    支持: 明天/后天/大后天 + 周X + 几号 + HH:MM (可选).
    """
    if not when_natural:
        return ''
    text = when_natural.lower().strip()
    base_ts = base_ts or time.time()
    base_local = time.localtime(base_ts)
    target_ts = None

    # 明天 / 后天
    if '明天' in text or 'tomorrow' in text:
        target_ts = base_ts + 86400
    elif '后天' in text:
        target_ts = base_ts + 86400 * 2
    elif '大后天' in text:
        target_ts = base_ts + 86400 * 3

    # 周X / 星期X
    if target_ts is None:
        for kw, target_wd in _WEEKDAY_MAP.items():
            if kw in text:
                cur_wd = base_local.tm_wday
                days_ahead = (target_wd - cur_wd) % 7
                if days_ahead == 0:
                    days_ahead = 7  # 如说"周三"且今天就是周三, 指下周三
                target_ts = base_ts + days_ahead * 86400
                break

    if target_ts is None:
        return ''

    # 默认 09:00
    target_local = time.localtime(target_ts)
    hour, minute = 9, 0
    m_time = re.search(r'(\d{1,2})\s*[:点]\s*(\d{2})?', text)
    if m_time:
        hour = int(m_time.group(1))
        if m_time.group(2):
            minute = int(m_time.group(2))

    target_struct = (target_local.tm_year, target_local.tm_mon, target_local.tm_mday,
                     hour, minute, 0, 0, 0, -1)
    target_iso_ts = time.mktime(target_struct)
    return time.strftime('%Y-%m-%dT%H:%M', time.localtime(target_iso_ts))
