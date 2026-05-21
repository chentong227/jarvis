# -*- coding: utf-8 -*-
"""[P5-SirStatusTracker / 2026-05-21 15:25] Sir 声明状态跟踪

Sir 13:49 真实 case:
  Sir 12:06: "睡觉了睡觉了，下午见"
  Sir 13:49 回来 → ReturnSentinel return_greeting:
    "The Soul Drive documentation is still active in Windsurf, Sir.
     It has been over ninety minutes since your last entry."
  Sir: "话术也要优化, 难道不应该说我休息了九十分钟吗? 他应该要知道我是去睡觉了"

## 根因

AFK sensor 看 IDE 窗口 idle, 不看 Sir 声明状态. Sir 说"睡觉了" 系统没记 →
return_greeting 时 nudge_ctx 没有"sleep_context", LLM 主脑只能凭屏幕活动猜.

## 设计

Sir 每条 utterance → 扫 vocab → 命中 sleep/nap/lunch/dinner/out/afk_short/dnd/back
→ update SirStatus → publish SWM `sir_declared_status` → 持久化.

ReturnSentinel _on_return / SmartNudge / Conductor 看 SirStatus →
出对应话术 (sleep return → "Hope you rested well" / out return → "Welcome back").

## Sir 准则 6 落地

- vocab 持久化 `memory_pool/sir_status_vocab.json`
- mtime cache + atomic load (跟 promise_vocab / integrity_claim_vocab 一致)
- CLI `scripts/sir_status_dump.py`
- L7 reflector 后续 (TODO)

## 关系

跟现有:
  - inconsistency_watcher get_sir_sleep_verbs (复用) — 现仅判 sleep, 不广覆盖
  - ReturnSentinel _on_return — 改 nudge_ctx 加 declared_status
  - SmartNudge — sleep 期间静默 (cooldown 已自带 sleep mode 但靠 NudgeGate, 可 reinforce)
  - HabitClock — Sir 真实作息 vs 声明 (后续 cross-check)
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(msg: str) -> None:
        print(msg)


# ============================================================
# Constants
# ============================================================

VOCAB_PATH = os.path.join('memory_pool', 'sir_status_vocab.json')
PERSIST_PATH = os.path.join('memory_pool', 'sir_status.json')

# 状态码 (mutually exclusive)
STATUS_UNKNOWN = 'unknown'
STATUS_ACTIVE = 'active'        # Sir 在线工作 (默认)
STATUS_SLEEP = 'sleep'          # 睡觉 (长)
STATUS_NAP = 'nap'              # 小憩 (短)
STATUS_LUNCH = 'lunch'          # 午餐
STATUS_DINNER = 'dinner'        # 晚餐
STATUS_OUT = 'out'              # 出门 (中长)
STATUS_AFK_SHORT = 'afk_short'  # 短暂 AFK
STATUS_DND = 'dnd'              # 请勿打扰

# 状态优先级 (高优先级覆盖低优先级)
_STATUS_PRIORITY = {
    STATUS_SLEEP: 100,
    STATUS_DND: 90,
    STATUS_OUT: 80,
    STATUS_NAP: 70,
    STATUS_LUNCH: 65,
    STATUS_DINNER: 65,
    STATUS_AFK_SHORT: 50,
    STATUS_ACTIVE: 10,
    STATUS_UNKNOWN: 0,
}

# 默认期望返回时长 (秒) — 用于 cross-check
_STATUS_EXPECTED_DURATION_S = {
    STATUS_SLEEP: 8 * 3600,        # 8h
    STATUS_NAP: 60 * 60,            # 1h
    STATUS_LUNCH: 60 * 60,          # 1h
    STATUS_DINNER: 60 * 60,
    STATUS_OUT: 3 * 3600,           # 3h
    STATUS_AFK_SHORT: 30 * 60,      # 30min
    STATUS_DND: 2 * 3600,           # 2h
}


# ============================================================
# Vocab loader
# ============================================================

_vocab_lock = threading.Lock()
_vocab_mtime: float = 0.0
_compiled_vocab: Optional[Dict[str, List[Tuple[str, str]]]] = None  # status_key -> [(pattern, lang), ...]


def _load_vocab_atomic() -> Optional[Dict[str, Any]]:
    if not os.path.exists(VOCAB_PATH):
        return None
    try:
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _get_compiled_vocab() -> Dict[str, List[Tuple[str, str]]]:
    """Returns: {status_key: [(keyword_lower, lang), ...]}."""
    global _vocab_mtime, _compiled_vocab
    if not os.path.exists(VOCAB_PATH):
        return _seed_vocab_fallback()
    try:
        cur_mtime = os.path.getmtime(VOCAB_PATH)
    except Exception:
        return _seed_vocab_fallback()
    with _vocab_lock:
        if cur_mtime == _vocab_mtime and _compiled_vocab is not None:
            return _compiled_vocab
        data = _load_vocab_atomic()
        if not data or 'patterns' not in data:
            return _seed_vocab_fallback()
        out: Dict[str, List[Tuple[str, str]]] = {}
        for status_key, entry in (data.get('patterns') or {}).items():
            kws = []
            for w in entry.get('en') or []:
                kws.append((w.lower().strip(), 'en'))
            for w in entry.get('zh') or []:
                kws.append((w.strip(), 'zh'))
            if kws:
                out[status_key] = kws
        if not out:
            return _seed_vocab_fallback()
        _compiled_vocab = out
        _vocab_mtime = cur_mtime
        return out


def _seed_vocab_fallback() -> Dict[str, List[Tuple[str, str]]]:
    """Vocab json 缺失 / 损坏的 fallback (最小 seed)."""
    return {
        STATUS_SLEEP: [('睡觉了', 'zh'), ('晚安', 'zh'), ('going to bed', 'en'),
                       ('good night', 'en'), ('off to sleep', 'en')],
        STATUS_OUT: [('出去', 'zh'), ('我走了', 'zh'), ('下午见', 'zh'),
                      ('going out', 'en'), ('be back later', 'en')],
        STATUS_LUNCH: [('吃饭去', 'zh'), ('lunch break', 'en')],
        STATUS_NAP: [('午睡', 'zh'), ('睡一会', 'zh'), ('quick nap', 'en')],
        STATUS_AFK_SHORT: [('一会回', 'zh'), ('brb', 'en'), ('afk', 'en')],
        STATUS_DND: [('别打扰', 'zh'), ('do not disturb', 'en')],
        'back': [('我回来了', 'zh'), ('早', 'zh'), ("i'm back", 'en')],
    }


def reset_vocab_cache_for_tests() -> None:
    global _vocab_mtime, _compiled_vocab
    with _vocab_lock:
        _vocab_mtime = 0.0
        _compiled_vocab = None


# ============================================================
# Detection — Sir utterance → status
# ============================================================

def detect_status_from_utterance(text: str) -> Tuple[str, str]:
    """看 Sir utterance 是否含 status 关键词. Returns: (status_key, matched_keyword) or ('', '').

    'back' status 表示"重置回 active" (Sir 主动声明回来).
    """
    if not text or len(text.strip()) < 2:
        return ('', '')
    text_lower = text.lower().strip()
    vocab = _get_compiled_vocab()
    # 优先级: 看高优先级先 (sleep > out > nap > lunch > afk > dnd > back)
    for status_key in [STATUS_SLEEP, STATUS_DND, STATUS_OUT, STATUS_NAP,
                        STATUS_LUNCH, STATUS_DINNER, STATUS_AFK_SHORT, 'back']:
        kws = vocab.get(status_key, [])
        for kw, lang in kws:
            if not kw:
                continue
            if lang == 'en':
                # word-boundary 匹配
                if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
                    return (status_key, kw)
            else:
                if kw in text_lower or kw in text:
                    return (status_key, kw)
    return ('', '')


# ============================================================
# Status dataclass + Store
# ============================================================

@dataclass
class SirStatus:
    """Sir current status (mutually exclusive)."""
    status: str = STATUS_UNKNOWN
    since_ts: float = 0.0
    since_iso: str = ''
    expected_return_s: float = 0.0  # 预计 X 秒后回来
    last_keyword: str = ''
    last_utterance_excerpt: str = ''
    last_turn_id: str = ''
    history: List[Dict[str, Any]] = field(default_factory=list)  # last 20 transitions

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'SirStatus':
        d = dict(d or {})
        d.setdefault('history', [])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def status_age_s(self) -> float:
        if not self.since_ts:
            return 0.0
        return time.time() - self.since_ts

    def is_overdue(self) -> bool:
        """Sir 声明的状态时长已过 (e.g. 说 lunch 但 2h 没回)."""
        if not self.expected_return_s:
            return False
        return self.status_age_s() > self.expected_return_s * 2.0  # 2x 倍宽容


class SirStatusStore:
    """单例 store (持久化 sir_status.json)."""

    def __init__(self, path: str = PERSIST_PATH):
        self.path = path
        self._status: SirStatus = SirStatus()
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
            self._status = SirStatus.from_dict(data.get('current') or {})
        except Exception:
            pass

    def _persist(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
            data = {
                '_meta': {
                    'updated_at': time.time(),
                    'updated_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
                    'schema_version': '1.0',
                },
                'current': self._status.to_dict(),
            }
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def current(self) -> SirStatus:
        with self._lock:
            return self._status

    def update_status(self, new_status: str, keyword: str = '',
                       utterance: str = '', turn_id: str = '') -> bool:
        """Update status if new is higher-priority OR explicit 'back' transition.

        Returns: True if status changed.
        """
        with self._lock:
            old_status = self._status.status
            # 'back' = reset to active
            if new_status == 'back':
                if old_status == STATUS_ACTIVE:
                    return False  # already active
                self._status.history.append({
                    'from': old_status,
                    'to': STATUS_ACTIVE,
                    'reason': f'Sir said: "{keyword}"',
                    'at_ts': time.time(),
                    'duration_s': self._status.status_age_s(),
                    'turn_id': turn_id,
                })
                if len(self._status.history) > 20:
                    self._status.history = self._status.history[-20:]
                self._status = SirStatus(
                    status=STATUS_ACTIVE,
                    since_ts=time.time(),
                    since_iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
                    last_keyword=keyword,
                    last_utterance_excerpt=utterance[:100],
                    last_turn_id=turn_id,
                    history=self._status.history,
                )
                self._persist()
                return True
            # 看新 status 优先级
            new_pri = _STATUS_PRIORITY.get(new_status, 0)
            old_pri = _STATUS_PRIORITY.get(old_status, 0)
            # 同 status 不更新 (防 spam)
            if new_status == old_status:
                return False
            # 高优先级覆盖, 低优先级仅在 unknown/active 时覆盖
            if new_pri < old_pri and old_status not in (STATUS_UNKNOWN, STATUS_ACTIVE):
                return False
            self._status.history.append({
                'from': old_status,
                'to': new_status,
                'reason': f'Sir said: "{keyword}"',
                'at_ts': time.time(),
                'duration_s': self._status.status_age_s(),
                'turn_id': turn_id,
            })
            if len(self._status.history) > 20:
                self._status.history = self._status.history[-20:]
            self._status = SirStatus(
                status=new_status,
                since_ts=time.time(),
                since_iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
                expected_return_s=_STATUS_EXPECTED_DURATION_S.get(new_status, 0.0),
                last_keyword=keyword,
                last_utterance_excerpt=utterance[:100],
                last_turn_id=turn_id,
                history=self._status.history,
            )
            self._persist()
            return True


# ============================================================
# Default singleton
# ============================================================

_DEFAULT_STORE: Optional[SirStatusStore] = None
_DEFAULT_STORE_LOCK = threading.Lock()


def get_default_store() -> SirStatusStore:
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = SirStatusStore()
        return _DEFAULT_STORE


def reset_default_store_for_tests(path: Optional[str] = None) -> None:
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        _DEFAULT_STORE = SirStatusStore(path=path or PERSIST_PATH)


# ============================================================
# Public API
# ============================================================

def observe_sir_utterance(text: str, turn_id: str = '') -> Optional[Tuple[str, str]]:
    """主入口 — Sir 每条 utterance 调.

    Returns: (status_key, keyword) 或 None (no detect).
    """
    if not text or len(text.strip()) < 2:
        return None
    status_key, kw = detect_status_from_utterance(text)
    if not status_key:
        return None
    store = get_default_store()
    changed = store.update_status(
        new_status=status_key,
        keyword=kw,
        utterance=text,
        turn_id=turn_id,
    )
    if changed:
        # publish SWM
        try:
            from jarvis_utils import get_event_bus as _geb
            bus = _geb()
            if bus is not None:
                cur = store.current()
                bus.publish(
                    etype='sir_declared_status',
                    description=(
                        f"Sir declared {cur.status} ({kw or '?'}) — "
                        f"expected {int(cur.expected_return_s/60)}min back"
                    ),
                    source='SirStatusTracker',
                    salience=0.65,
                    metadata={
                        'status': cur.status,
                        'keyword': kw,
                        'utterance_excerpt': text[:100],
                        'expected_return_s': cur.expected_return_s,
                        'since_ts': cur.since_ts,
                        'turn_id': turn_id,
                    },
                )
        except Exception:
            pass
        try:
            cur = store.current()
            bg_log(
                f"💤 [SirStatusTracker] {status_key} captured "
                f"(kw='{kw[:30]}', turn={turn_id[:12] if turn_id else '?'}, "
                f"expected back in ~{int(cur.expected_return_s/60)}min)"
            )
        except Exception:
            pass
    return (status_key, kw)


def observe_sir_utterance_async(text: str, turn_id: str = '') -> threading.Thread:
    """fire-and-forget 入口."""
    t = threading.Thread(
        target=observe_sir_utterance,
        args=(text, turn_id),
        daemon=True,
        name=f'SirStatusTracker.observe/{turn_id[:12] if turn_id else "?"}',
    )
    t.start()
    return t


def current_status() -> Dict[str, Any]:
    """供外部查 (ReturnSentinel / SmartNudge / Conductor)."""
    store = get_default_store()
    cur = store.current()
    return {
        'status': cur.status,
        'since_ts': cur.since_ts,
        'since_iso': cur.since_iso,
        'expected_return_s': cur.expected_return_s,
        'age_s': cur.status_age_s(),
        'is_overdue': cur.is_overdue(),
        'last_keyword': cur.last_keyword,
        'last_utterance_excerpt': cur.last_utterance_excerpt,
        'last_turn_id': cur.last_turn_id,
    }


def render_status_block_for_prompt() -> str:
    """主脑 prompt 块 — 看 Sir current status, 调整话术."""
    cur = current_status()
    if cur['status'] in (STATUS_UNKNOWN, STATUS_ACTIVE):
        return ''
    age_min = int(cur['age_s'] / 60)
    expected_min = int(cur['expected_return_s'] / 60)
    overdue_note = ' (overdue!)' if cur['is_overdue'] else ''
    label_map = {
        STATUS_SLEEP: '睡觉中 (长)',
        STATUS_NAP: '小憩 (短)',
        STATUS_LUNCH: '吃午饭',
        STATUS_DINNER: '吃晚饭',
        STATUS_OUT: '出门',
        STATUS_AFK_SHORT: '短暂 AFK',
        STATUS_DND: '请勿打扰',
    }
    label = label_map.get(cur['status'], cur['status'])
    return (
        f"[SIR'S DECLARED STATUS]\n"
        f"  Sir 当前声明状态: {label} ({cur['status']})\n"
        f"  自 {cur['since_iso']} ({age_min}min ago){overdue_note}\n"
        f"  原话片段: \"{cur['last_utterance_excerpt'][:60]}\"\n"
        f"  预计 ~{expected_min}min 内回来\n"
        f"  → 不要 nudge 不重要的事 (除非紧急 / Sir 主动 query)\n"
        f"  → return 时话术应符合 status (e.g. sleep → 'Hope you rested well',\n"
        f"     out → 'Welcome back', lunch → 'Hope lunch was good')"
    )
