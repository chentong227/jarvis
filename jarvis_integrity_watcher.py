# -*- coding: utf-8 -*-
"""[P5-IntegrityWatcher / 2026-05-21 14:00] Jarvis 自检层 — 主动 verify + retry

Sir 13:50-14:00 真意:
> "我需要的是贾维斯有发现自己未遵守承诺或者撒谎的主动修正能力，这点尤其重要。
>  ...持续的 watcher，看看自己是不是真的成功了。触发，发现没成功，
>  主动的用轻推也好，别的方式也好，重新做一遍，真成功了，走主脑决策，
>  道歉+告诉我设上了/没成功，道歉加告知我这个事情..."

> "tool 调用本身会拖慢进程，我更在意的是贾维斯本身交互架构的能力，
>  tool 摘成独立架构...这个 watcher 也该是贾维斯自检的能力一部分"

> "至于 tool 调用失败，完全可以直接让主脑知道调用成功没有，毕竟我们 tool 的路径
>  是：主脑-工具-主脑"

## 架构定位

```
Jarvis 交互架构 (内部, fast path)
├── 内部 state mutation 层 (hippocampus/profile/commitment/promise/...)
│   └── nerve.<module>.<method>() 直接 call, 零 LLM dispatch
├── Self-检测层 (Sir 13:50: 贾维斯自检的能力一部分)
│   ├── ClaimTracer / SelfPromiseDetector (已有, 检 reply 含 claim)
│   ├── IntegrityReflector / PreFlight (已有, post-stream judge)
│   ├── ToMReflector (已有, 推 Sir mental state)
│   └── 🆕 IntegrityWatcher (本 module)
└── Tool 层 (操作 Sir 电脑, 独立, 主脑-工具-主脑 agentic loop)
    └── 失败本身让主脑知道, 不归 watcher
```

## 触发点 (跟言出必行一致)

主脑 reply 中含 "我已做 X" claim → ClaimDetector 提取 → IntegrityWatcher.watch_claim()
→ tick daemon (30s) 跑 verifier → 失败自动 retry (direct module call, max 3)
→ publish 'integrity_recovered' / 'integrity_failed' / 'integrity_verified' SWM
→ 主脑下轮 prompt [INTEGRITY WATCHER REPORT] block → 主脑自决 surface form

## Claim Types (Jarvis 内部能力 8 类)

| Claim Type | 主脑常说 | Verifier (直接 module call) | Retrier |
|------------|---------|---------------------------|---------|
| reminder | "set reminder for X" | hippocampus.list_reminders by intent+time | hippocampus.add_reminder |
| commitment | "Got it, Sir, 11pm" | commitment_watcher 找 description+deadline | register_commitment |
| promise | "I'll remind you" | promise_log 找 description | promise_log.register |
| memory | "I'll remember" | hippocampus.search by excerpt | (无 — 等 LLM rebuild) |
| milestone | "记到海马体了" | milestones.find by text | milestones.add |
| profile | "updated your profile" | profile_corrections.jsonl tail | profile.apply_correction |
| concern | "noted hydration" | concerns_ledger.find by topic | record_signal |
| relational | "I'll keep this joke" | relational_state find | add_inside_joke |

## 持久化

`memory_pool/integrity_watcher.json` — 状态 + 历史 (类 ClaimRevisionLog)

## Sir 准则 6 vocab persistence

claim detection vocab `memory_pool/integrity_claim_vocab.json` (CLI manage).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(msg: str) -> None:
        print(msg)


# ============================================================
# Constants
# ============================================================

# claim states (L4.5 IntegrityWatcher state machine)
STATUS_WATCHING = 'watching'           # 刚 capture, 等首次 verify
STATUS_VERIFIED = 'verified'           # verify 成功 (真有 state mutation)
STATUS_RETRYING = 'retrying'           # verify 失败, retry 中
STATUS_RECOVERED = 'recovered'         # retry 真成功
STATUS_HANDOFF_SIR = 'handoff_sir'     # Jarvis 真做不到, 移交 Sir 手动 (Sir 14:11 立)
STATUS_NO_TOOL = 'no_tool_claim'       # 主脑说做了但没对应 module call path
STATUS_REJECTED = 'rejected'           # Sir CLI 否决 (false positive)

DEFAULT_PERSIST_PATH = os.path.join('memory_pool', 'integrity_watcher.json')

# tick / retry policy (Sir 14:11 真意: 递归 retry 不限次, 直到 recovered OR cannot_recover)
DEFAULT_TICK_INTERVAL_S = 15.0          # 较短, watch 反应快 (Sir "快速检查")
DEFAULT_RETRY_BACKOFF_S = (5.0, 15.0, 45.0, 120.0, 300.0)  # 5s, 15s, 45s, 2min, 5min, 然后 5min 间隔
DEFAULT_FRESH_BUFFER_S = 3.0             # 给 IntentResolver / hands 跑完的时间, 避免假阴性
DEFAULT_HISTORY_KEEP = 200                # 内存 + 持久化最多保 200 条
DEFAULT_HANDOFF_AFTER_SAME_ERROR_N = 3   # 同 error 连续 3 次 → 判 cannot_recover, handoff
DEFAULT_HANDOFF_AFTER_AGE_S = 1800.0     # claim 30min 仍没 recovered → handoff (兜底)


# ============================================================
# Claim dataclass
# ============================================================

@dataclass
class Claim:
    """主脑 reply 中含的 mutation claim, IntegrityWatcher 监督."""
    id: str
    claim_type: str            # reminder / commitment / promise / memory / milestone / profile / concern / relational
    extracted_action: str      # 主脑原话片段 "I've set the reminder"
    extracted_target: str      # claim 内核 (intent / description / time / topic)
    extracted_meta: Dict[str, Any] = field(default_factory=dict)  # 时间 / 量值 / 字段路径 / ...
    captured_at: float = field(default_factory=time.time)
    captured_iso: str = field(default_factory=lambda: time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()))
    captured_turn_id: str = ''
    captured_reply_excerpt: str = ''  # full reply 前 300 char (debug)
    status: str = STATUS_WATCHING
    retries: int = 0
    last_verify_ts: float = 0.0
    last_retry_ts: float = 0.0
    next_retry_ts: float = 0.0
    verify_history: List[Dict[str, Any]] = field(default_factory=list)  # [{ts, ok, evidence}]
    final_evidence: Dict[str, Any] = field(default_factory=dict)
    final_error: str = ''
    notified_brain_at: float = 0.0  # 主脑下轮已 prompt 通知过的时间, 避免重复 surface

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'Claim':
        d = dict(d or {})
        d.setdefault('extracted_meta', {})
        d.setdefault('verify_history', [])
        d.setdefault('final_evidence', {})
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def age_s(self) -> float:
        return time.time() - self.captured_at

    def is_terminal(self) -> bool:
        return self.status in (STATUS_VERIFIED, STATUS_RECOVERED, STATUS_FAILED,
                                STATUS_NO_TOOL, STATUS_REJECTED)


# ============================================================
# Claim Detection (主脑 reply → claim_type + target)
# ============================================================

# 这些 pattern 跟 SelfPromiseDetector 不同 — 我们检 **已完成 action**, 不是 future promise.
# 设计原则: detect "我已做 X" / "I've done X" 类, 不 detect "I will do X" (那是 promise).

# reminder claim (已设)
_RE_REMINDER_EN = re.compile(
    r"(?:i(?:'ve|\s+have)|i)\s+(?:set|added|created|scheduled|saved|recorded|noted)\s+"
    r"(?:the\s+|a\s+|an\s+|that\s+|your\s+)?"
    r"(?P<target>reminder|alert|alarm)",
    re.IGNORECASE
)
_RE_REMINDER_ZH = re.compile(
    r"(?:已经|已|刚|刚刚|帮你|为您)?\s*"
    r"(?:设|设置|加|添加|记|创建)\s*"
    r"(?:好了|完了|了|完毕|妥了|完成|好|妥)?\s*"
    r"(?P<target>提醒|闹钟|日程)"
)

# commitment claim (Sir 的承诺, Jarvis confirm)
_RE_COMMITMENT_EN = re.compile(
    r"(?:got\s+it|noted|understood|locked\s+in|saved|recorded|will\s+hold\s+you)",
    re.IGNORECASE
)
_RE_COMMITMENT_ZH = re.compile(r"(?:记下了|记住了|收到|明白|这就|帮您记|记到|没问题)")

# self_promise claim (Jarvis 自己未来 action) — 复用 SelfPromiseDetector 信号 (后面 wire)

# memory remember claim
_RE_MEMORY_EN = re.compile(
    r"(?:i(?:'ll|\s+will)|i(?:'ve|\s+have))\s+(?:remember|memorize|keep\s+(?:that\s+)?in\s+mind|"
    r"committed?\s+(?:that\s+)?to\s+memory|saved\s+(?:that\s+)?to\s+memory)",
    re.IGNORECASE
)
_RE_MEMORY_ZH = re.compile(r"(?:已经|刚|帮你)?\s*(?:记住|记下|铭记|存(?:到|入)?海马体|刻在心里)")

# milestone claim (lifetime anchor)
_RE_MILESTONE_EN = re.compile(
    r"(?:i(?:'ll|\s+will))\s+(?:keep|hold|treasure|cherish)\s+"
    r"(?:this|that|it|this\s+moment)\s+(?:forever|always|for\s+life)",
    re.IGNORECASE
)
_RE_MILESTONE_ZH = re.compile(
    r"(?:这件事|这一刻|此刻|这个)?\s*"
    r"(?:永远(?:记得|铭记|不忘)|一辈子(?:记得|不忘)|刻进|铭刻)"
)

# profile claim
_RE_PROFILE_EN = re.compile(
    r"(?:i(?:'ve|\s+have))\s+(?:updated|saved|corrected|recorded|modified|noted)\s+"
    r"(?:your\s+|the\s+)?(?P<target>profile|preferences?|height|name|info|details|"
    r"settings?|档案|资料)",
    re.IGNORECASE
)
_RE_PROFILE_ZH = re.compile(r"(?:已经|刚|帮你)?\s*(?:更新|修改|纠正|改|存)\s*(?:了)?\s*(?:您的|你的)?\s*(?P<target>档案|资料|信息|偏好|profile)")

# concern claim
_RE_CONCERN_EN = re.compile(
    r"(?:i(?:'ve|\s+have))\s+(?:noted|added|tracked|recorded|updated|saved)\s+"
    r"(?:your\s+|the\s+|this\s+)?(?P<target>concern|count|progress|hydration|sleep|exercise)",
    re.IGNORECASE
)
_RE_CONCERN_ZH = re.compile(
    r"(?:已|刚|帮你)?\s*(?:更新|记录|记|加)\s*(?:了)?\s*"
    r"(?P<target>关注|count|进度|喝水|睡眠|运动|水量)"
)

# relational claim (inside joke / shared history)
_RE_RELATIONAL_EN = re.compile(
    r"(?:i(?:'ll|\s+will))\s+(?:remember|keep|hold)\s+"
    r"(?:this|that)\s+(?:joke|moment|memory|inside\s+joke)",
    re.IGNORECASE
)
_RE_RELATIONAL_ZH = re.compile(r"(?:这个|那个)?\s*(?:梗|笑话|内部梗)\s*(?:我会)?\s*(?:记住|记下|永远记得)")


# claim_type → (en_pattern, zh_pattern, target_field, claim_label)
# Hardcoded fallback (Sir 准则 6 — vocab json 损坏 / 首启时用)
_FALLBACK_DETECTORS: List[Tuple[str, re.Pattern, re.Pattern, str]] = [
    ('reminder',   _RE_REMINDER_EN,    _RE_REMINDER_ZH,    'reminder'),
    ('memory',     _RE_MEMORY_EN,      _RE_MEMORY_ZH,      'memory_remember'),
    ('milestone',  _RE_MILESTONE_EN,   _RE_MILESTONE_ZH,   'milestone'),
    ('profile',    _RE_PROFILE_EN,     _RE_PROFILE_ZH,     'profile_update'),
    ('concern',    _RE_CONCERN_EN,     _RE_CONCERN_ZH,     'concern_update'),
    ('relational', _RE_RELATIONAL_EN,  _RE_RELATIONAL_ZH,  'inside_joke'),
    ('commitment', _RE_COMMITMENT_EN,  _RE_COMMITMENT_ZH,  'commitment_register'),
]


# ============================================================
# Vocab loader (Sir 准则 6 — 持久化 + mtime cache)
# ============================================================

CLAIM_VOCAB_PATH = os.path.join('memory_pool', 'integrity_claim_vocab.json')
SUSPICIOUS_KW_PATH = os.path.join('memory_pool', 'integrity_suspicious_kw.json')

_vocab_lock = threading.Lock()
_vocab_mtime: float = 0.0
_compiled_detectors: Optional[List[Tuple[str, re.Pattern, re.Pattern, str]]] = None
_kw_mtime: float = 0.0
_compiled_kw_pattern_en: Optional[re.Pattern] = None
_compiled_kw_pattern_zh: Optional[re.Pattern] = None


def _load_claim_vocab() -> Optional[Dict[str, Any]]:
    """加载 integrity_claim_vocab.json. 失败 → None (走 fallback)."""
    if not os.path.exists(CLAIM_VOCAB_PATH):
        return None
    try:
        with open(CLAIM_VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _get_compiled_detectors() -> List[Tuple[str, List[re.Pattern], List[re.Pattern], str]]:
    """从 vocab json 加载 + compile, mtime cache.

    返 [(claim_type, [en_pats], [zh_pats], default_target), ...].
    每个 pattern 独立 compile (避免合 | 时 named group 冲突).
    Vocab 损坏 → fallback hardcoded.
    """
    global _vocab_mtime, _compiled_detectors
    if not os.path.exists(CLAIM_VOCAB_PATH):
        return _coerce_fallback_to_list_form()
    try:
        cur_mtime = os.path.getmtime(CLAIM_VOCAB_PATH)
    except Exception:
        return _coerce_fallback_to_list_form()
    with _vocab_lock:
        if cur_mtime == _vocab_mtime and _compiled_detectors is not None:
            return _compiled_detectors
        data = _load_claim_vocab()
        if data is None or not isinstance(data, dict):
            return _coerce_fallback_to_list_form()
        patterns = data.get('patterns') or {}
        if not patterns:
            return _coerce_fallback_to_list_form()
        out = []
        for claim_type, entry in patterns.items():
            if entry.get('state', 'active') != 'active':
                continue
            en_list = entry.get('en_patterns') or []
            zh_list = entry.get('zh_patterns') or []
            en_compiled = []
            zh_compiled = []
            for p in en_list:
                try:
                    en_compiled.append(re.compile(p, re.IGNORECASE))
                except re.error:
                    continue
            for p in zh_list:
                try:
                    zh_compiled.append(re.compile(p))
                except re.error:
                    continue
            if not en_compiled and not zh_compiled:
                continue
            default_target = entry.get('default_target', claim_type)
            out.append((claim_type, en_compiled, zh_compiled, default_target))
        if not out:
            return _coerce_fallback_to_list_form()
        _compiled_detectors = out
        _vocab_mtime = cur_mtime
        return out


def _coerce_fallback_to_list_form() -> List[Tuple[str, List[re.Pattern], List[re.Pattern], str]]:
    """_FALLBACK_DETECTORS 是 (str, Pattern, Pattern, str) 单 pattern 形式,
    转 (str, [Pattern], [Pattern], str) 跟 vocab loader 输出一致.
    """
    out = []
    for claim_type, en_pat, zh_pat, default_target in _FALLBACK_DETECTORS:
        out.append((claim_type, [en_pat], [zh_pat], default_target))
    return out


def _load_suspicious_kw() -> Tuple[List[str], List[str]]:
    """加载 suspicious keyword. 失败 → 内嵌 seed."""
    SEED_EN = [
        'set', 'added', 'saved', 'scheduled', 'remember', 'memorize',
        'noted', 'logged', 'tracked', 'updated', 'modified', 'applied',
        'registered', 'stored', 'recorded', 'marked', 'captured', 'confirmed',
        'got it', 'locked in',
    ]
    SEED_ZH = [
        '已', '记住', '记下', '设好', '设上', '更新', '存了', '改了',
        '存到', '记到', '保存', '添加', '登记', '注册', '锁定', '确认',
        '完成', '完毕', '妥了', '搞定',
    ]
    if not os.path.exists(SUSPICIOUS_KW_PATH):
        return (SEED_EN, SEED_ZH)
    try:
        with open(SUSPICIOUS_KW_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
        en = data.get('keywords_en') or SEED_EN
        zh = data.get('keywords_zh') or SEED_ZH
        return (en, zh)
    except Exception:
        return (SEED_EN, SEED_ZH)


def _get_compiled_kw_pattern() -> Tuple[re.Pattern, re.Pattern]:
    """compile suspicious kw → regex (mtime cache).

    Returns: (en_pat, zh_pat).
    """
    global _kw_mtime, _compiled_kw_pattern_en, _compiled_kw_pattern_zh
    if not os.path.exists(SUSPICIOUS_KW_PATH):
        cur_mtime = 0.0
    else:
        try:
            cur_mtime = os.path.getmtime(SUSPICIOUS_KW_PATH)
        except Exception:
            cur_mtime = 0.0
    with _vocab_lock:
        if cur_mtime == _kw_mtime and _compiled_kw_pattern_en is not None:
            return (_compiled_kw_pattern_en, _compiled_kw_pattern_zh)
        en_list, zh_list = _load_suspicious_kw()
        # 合 regex (word boundary 仅 EN)
        en_pat = re.compile(r'\b(?:' + '|'.join(re.escape(k) for k in en_list) + r')\b',
                              re.IGNORECASE)
        zh_pat = re.compile('(?:' + '|'.join(re.escape(k) for k in zh_list) + ')')
        _compiled_kw_pattern_en = en_pat
        _compiled_kw_pattern_zh = zh_pat
        _kw_mtime = cur_mtime
        return (en_pat, zh_pat)


def reset_vocab_cache() -> None:
    """force reload (testcase / Sir CLI 改 json 后)."""
    global _vocab_mtime, _compiled_detectors, _kw_mtime
    global _compiled_kw_pattern_en, _compiled_kw_pattern_zh
    with _vocab_lock:
        _vocab_mtime = 0.0
        _compiled_detectors = None
        _kw_mtime = 0.0
        _compiled_kw_pattern_en = None
        _compiled_kw_pattern_zh = None


# ============================================================
# Layer 1 — vocab fast-path
# ============================================================

def detect_claims_via_regex(reply_text: str) -> List[Dict[str, Any]]:
    """[Layer 1] vocab regex fast-path. 0.5-2ms. 主流 case 命中.

    Sir 14:30 设计原则: vocab + LLM 二维, 不是 LLM 替代 regex.
    """
    if not reply_text or len(reply_text.strip()) < 5:
        return []
    text = reply_text.strip()
    hits = []
    seen_keys = set()
    detectors = _get_compiled_detectors()
    for claim_type, en_pats, zh_pats, target_default in detectors:
        for pat_list, lang in ((en_pats, 'en'), (zh_pats, 'zh')):
            for pat in pat_list:
                try:
                    for m in pat.finditer(text):
                        gd = m.groupdict() if hasattr(m, 'groupdict') else {}
                        target = gd.get('target', '') or target_default
                        action_text = m.group(0)
                        pos = m.start()
                        key = (claim_type, action_text[:60].lower())
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        hits.append({
                            'claim_type': claim_type,
                            'action_text': action_text[:120],
                            'target': target[:80],
                            'lang': lang,
                            'pos': pos,
                            'source': 'vocab_layer1',
                        })
                except Exception:
                    continue
    return hits


def detect_claims_in_reply(reply_text: str) -> List[Dict[str, Any]]:
    """Sync 入口 — Layer 1 vocab. Async LLM 走 _LlmClaimJudge.

    跟 watcher.watch_claim 互通. testcase / 老 caller 用此 sync API.
    """
    return detect_claims_via_regex(reply_text)


# ============================================================
# Layer 2 — suspicious keyword gate
# ============================================================

def has_suspicious_keyword(reply_text: str) -> bool:
    """看 reply 是否含 suspicious mutation keyword. 触发 Layer 3 LLM judge."""
    if not reply_text or len(reply_text.strip()) < 5:
        return False
    en_pat, zh_pat = _get_compiled_kw_pattern()
    if en_pat.search(reply_text):
        return True
    if zh_pat.search(reply_text):
        return True
    return False


# ============================================================
# Time / target extraction helpers
# ============================================================

# trigger_time extraction (用于 reminder claim)
_RE_TIME_HHMM = re.compile(r'\b(\d{1,2}):(\d{2})\b')
_RE_TIME_ZH = re.compile(r'(\d{1,2})\s*点(?:\s*(\d{1,2})\s*分)?')
_RE_DURATION_EN = re.compile(r'in\s+(\d+)\s*(minute|min|hour|hr)s?\s+', re.IGNORECASE)
_RE_DURATION_ZH = re.compile(r'(\d+)\s*(分钟|小时)')


def extract_time_anchor(text: str) -> str:
    """从 reply 抽时间锚 (HH:MM / X 点 / in X minutes / X 分钟后).

    Returns: 标准化字符串 e.g. '12:00' / '15分钟后' or '' (无).
    """
    if not text:
        return ''
    m = _RE_TIME_HHMM.search(text)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = _RE_TIME_ZH.search(text)
    if m:
        h = int(m.group(1))
        mn = m.group(2)
        if mn:
            return f"{h:02d}:{int(mn):02d}"
        return f"{h:02d}:00"
    m = _RE_DURATION_EN.search(text)
    if m:
        n, u = int(m.group(1)), m.group(2).lower()
        if u.startswith('hour') or u == 'hr':
            return f"{n}小时后"
        return f"{n}分钟后"
    m = _RE_DURATION_ZH.search(text)
    if m:
        return f"{int(m.group(1))}{m.group(2)}后"
    return ''


def extract_intent_excerpt(reply_text: str, action_pos: int, max_chars: int = 60) -> str:
    """从 reply 中 action 之后 max_chars 字内提 intent (e.g. "to call mom" 类).

    用于 reminder/promise/commitment 内容描述.
    """
    if not reply_text or action_pos < 0:
        return ''
    rest = reply_text[action_pos:action_pos + 200]
    # 简单切句, 取第一句
    for sep in (' to ', '提醒', '为您', '记住', '关于', '——', '—', '. ', '。', ':', '：'):
        if sep in rest:
            tail = rest.split(sep, 1)[1][:max_chars]
            return tail.strip().rstrip('.,;。；')
    return rest[:max_chars].strip()


# ============================================================
# Store (持久化)
# ============================================================

class IntegrityWatcherStore:
    """持久化所有 watch 中和历史 claims."""

    def __init__(self, path: str = DEFAULT_PERSIST_PATH):
        self.path = path
        self._items: Dict[str, Claim] = {}  # claim_id -> Claim
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
            items_data = data.get('claims') or []
            for d in items_data:
                try:
                    c = Claim.from_dict(d)
                    self._items[c.id] = c
                except Exception:
                    continue
        except Exception:
            pass

    def _persist(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
            # keep 最多 DEFAULT_HISTORY_KEEP 条 (老 terminal 丢)
            items = list(self._items.values())
            if len(items) > DEFAULT_HISTORY_KEEP:
                items.sort(key=lambda c: (c.is_terminal(), c.captured_at))
                items = items[-DEFAULT_HISTORY_KEEP:]
                self._items = {c.id: c for c in items}
            data = {
                '_meta': {
                    'schema_version': '1.0',
                    'updated_at': time.time(),
                    'updated_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
                    'total': len(self._items),
                },
                'claims': [c.to_dict() for c in items],
            }
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def add(self, c: Claim) -> str:
        with self._lock:
            if not c.id:
                c.id = uuid.uuid4().hex[:12]
            self._items[c.id] = c
            self._persist()
            return c.id

    def update(self, c: Claim) -> None:
        with self._lock:
            self._items[c.id] = c
            self._persist()

    def get(self, claim_id: str) -> Optional[Claim]:
        with self._lock:
            return self._items.get(claim_id)

    def all_items(self, only_active: bool = False) -> List[Claim]:
        with self._lock:
            items = list(self._items.values())
        if only_active:
            items = [c for c in items if not c.is_terminal()]
        items.sort(key=lambda c: -c.captured_at)
        return items

    def reject(self, claim_id: str) -> bool:
        with self._lock:
            c = self._items.get(claim_id)
            if c is None:
                return False
            c.status = STATUS_REJECTED
            self._persist()
            return True


# ============================================================
# Default store singleton
# ============================================================

_DEFAULT_STORE: Optional[IntegrityWatcherStore] = None
_DEFAULT_STORE_LOCK = threading.Lock()


def get_default_store() -> IntegrityWatcherStore:
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = IntegrityWatcherStore()
        return _DEFAULT_STORE


def reset_default_store_for_tests(path: Optional[str] = None) -> None:
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        _DEFAULT_STORE = IntegrityWatcherStore(path=path or DEFAULT_PERSIST_PATH)


# ============================================================
# Verifier / Retrier protocol
# ============================================================
# verify_fn(claim, nerve) -> (ok: bool, evidence: dict, error: str)
# retry_fn(claim, nerve) -> (ok: bool, evidence: dict, error: str)

VerifyFn = Callable[[Claim, Any], Tuple[bool, Dict[str, Any], str]]
RetryFn = Callable[[Claim, Any], Tuple[bool, Dict[str, Any], str]]


# ============================================================
# Built-in Verifiers (直接 module call, 不通过 tool dispatch)
# ============================================================

def verify_reminder(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """看 hippocampus.commitments 是否真有这条 reminder.

    匹配条件: intent 含 target_excerpt 或 trigger_time 匹配.
    """
    try:
        hippo = getattr(nerve, 'hippocampus', None) if nerve else None
        if hippo is None:
            return (False, {}, 'no hippocampus')
        # find reminders by intent excerpt or time
        target_text = claim.extracted_target or claim.extracted_action
        time_anchor = claim.extracted_meta.get('time_anchor', '')
        try:
            if hasattr(hippo, 'list_recent_reminders'):
                recents = hippo.list_recent_reminders(within_minutes=10) or []
            elif hasattr(hippo, 'list_reminders'):
                recents = hippo.list_reminders() or []
            else:
                return (False, {}, 'hippo has no list_reminders')
        except Exception as e:
            return (False, {}, f'list_reminders fail: {e}')
        for r in recents[:50]:
            intent = (r.get('intent', '') if isinstance(r, dict) else getattr(r, 'intent', '')) or ''
            t = (r.get('trigger_time', '') if isinstance(r, dict) else getattr(r, 'trigger_time', '')) or ''
            if time_anchor and time_anchor in str(t):
                return (True, {'reminder_id': r.get('id') if isinstance(r, dict) else getattr(r, 'id', None),
                                'matched': 'time'}, '')
            if target_text and target_text.lower()[:20] in str(intent).lower():
                return (True, {'reminder_id': r.get('id') if isinstance(r, dict) else getattr(r, 'id', None),
                                'matched': 'intent'}, '')
        return (False, {'recents_n': len(recents)}, 'no matching reminder in last 10min')
    except Exception as e:
        return (False, {}, f'exception: {e}')


def verify_commitment(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """看 commitment_watcher.commitments 是否真有 description+deadline 匹配."""
    try:
        cw = getattr(nerve, 'commitment_watcher', None) if nerve else None
        if cw is None:
            return (False, {}, 'no commitment_watcher')
        target_text = claim.extracted_target or claim.extracted_action
        if not target_text:
            return (False, {}, 'no target excerpt')
        commits = getattr(cw, 'commitments', []) or []
        cutoff = time.time() - 600  # 10min 内 register 的
        for c in commits[-50:]:
            if c.get('created_at', 0) < cutoff:
                continue
            desc = (c.get('description') or '').lower()
            src = (c.get('source_text') or '').lower()
            if target_text.lower()[:20] in desc or target_text.lower()[:20] in src:
                return (True, {'db_id': c.get('db_id'), 'description': desc[:60],
                                'deadline_ts': c.get('deadline_ts')}, '')
        return (False, {'commits_n': len(commits)}, 'no matching commitment in last 10min')
    except Exception as e:
        return (False, {}, f'exception: {e}')


def verify_promise(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """看 PromiseLog 是否真有 description 匹配."""
    try:
        from jarvis_promise_log import get_default_log
        plog = getattr(nerve, 'promise_log', None) if nerve else None
        if plog is None:
            try:
                plog = get_default_log()
            except Exception as e:
                return (False, {}, f'no promise_log: {e}')
        target_text = claim.extracted_target or claim.extracted_action
        if not target_text:
            return (False, {}, 'no target excerpt')
        recents = []
        try:
            recents = plog.list_recent(limit=30) if hasattr(plog, 'list_recent') else []
        except Exception:
            recents = []
        cutoff = time.time() - 600
        for p in recents:
            if hasattr(p, 'registered_at') and p.registered_at < cutoff:
                continue
            desc = (getattr(p, 'description', '') or '').lower()
            if target_text.lower()[:20] in desc:
                return (True, {'promise_id': getattr(p, 'id', None),
                                'state': getattr(p, 'state', None)}, '')
        return (False, {'recents_n': len(recents)}, 'no matching promise in last 10min')
    except Exception as e:
        return (False, {}, f'exception: {e}')


def verify_memory(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """看 hippocampus 最近 memories 是否真有 excerpt 匹配.

    注: STM→LTM 是 daemon 后台异步 transfer, 短时窗 (<60s) 可能假阴性.
    给 60s grace.
    """
    try:
        hippo = getattr(nerve, 'hippocampus', None) if nerve else None
        if hippo is None:
            return (False, {}, 'no hippocampus')
        if claim.age_s() < 60:
            # grace period: STM→LTM daemon 还没跑
            return (False, {'grace_period': True}, 'within 60s grace (STM→LTM not yet)')
        excerpt = (claim.captured_reply_excerpt or '')[:50].lower()
        if not excerpt:
            return (False, {}, 'no excerpt')
        try:
            if hasattr(hippo, 'search_recent'):
                results = hippo.search_recent(excerpt, limit=5, within_minutes=30) or []
            elif hasattr(hippo, 'search'):
                results = hippo.search(excerpt, limit=5) or []
            else:
                return (False, {}, 'no search method')
        except Exception as e:
            return (False, {}, f'search fail: {e}')
        if results:
            return (True, {'matches_n': len(results)}, '')
        return (False, {'matches_n': 0}, 'no matching memory')
    except Exception as e:
        return (False, {}, f'exception: {e}')


def verify_milestone(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """看 milestones.json 是否真有最近 entry 匹配."""
    try:
        from jarvis_milestones import list_recent_milestones
        recents = list_recent_milestones(within_seconds=600) or []
        excerpt = (claim.captured_reply_excerpt or '')[:50].lower()
        if not recents:
            return (False, {}, 'no milestones in last 10min')
        if not excerpt:
            return (True if recents else False, {'recents_n': len(recents)}, '')
        for ms in recents:
            text = (ms.get('text', '') if isinstance(ms, dict) else '').lower()
            if any(w in text for w in excerpt.split()[:5] if len(w) > 3):
                return (True, {'milestone_id': ms.get('id') if isinstance(ms, dict) else None}, '')
        return (False, {'recents_n': len(recents)}, 'no matching milestone')
    except ImportError:
        return (False, {}, 'jarvis_milestones not importable')
    except Exception as e:
        return (False, {}, f'exception: {e}')


def verify_profile(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """看 profile_corrections.jsonl tail 是否最近 10min 有 entry."""
    try:
        path = os.path.join('memory_pool', 'profile_corrections.jsonl')
        if not os.path.exists(path):
            return (False, {}, 'no profile_corrections.jsonl')
        cutoff = time.time() - 600
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()[-30:]
        except Exception as e:
            return (False, {}, f'read fail: {e}')
        for ln in reversed(lines):
            try:
                d = json.loads(ln.strip())
                ts = float(d.get('ts') or d.get('timestamp') or 0)
                if ts < cutoff:
                    continue
                return (True, {'field': d.get('field'),
                                'new_value': str(d.get('new_value', ''))[:40]}, '')
            except Exception:
                continue
        return (False, {'lines_checked': len(lines)}, 'no entry in last 10min')
    except Exception as e:
        return (False, {}, f'exception: {e}')


def verify_concern(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """看 concerns_ledger 是否最近有 record_signal 或 daily_progress 更新."""
    try:
        ledger = getattr(nerve, 'concerns_ledger', None) if nerve else None
        if ledger is None:
            return (False, {}, 'no concerns_ledger')
        target = (claim.extracted_target or '').lower()
        cutoff = time.time() - 600
        try:
            actives = ledger.list_active() if hasattr(ledger, 'list_active') else []
        except Exception:
            return (False, {}, 'list_active fail')
        today_iso = time.strftime('%Y-%m-%d', time.localtime())
        for c in actives:
            cid = (getattr(c, 'id', '') or '').lower()
            topic = (getattr(c, 'topic', '') or '').lower()
            dp = getattr(c, 'daily_progress', {}) or {}
            last_update = float(dp.get('last_updated_ts') or 0)
            if dp.get('iso_date') == today_iso and last_update >= cutoff:
                if target and (target in cid or target in topic):
                    return (True, {'concern_id': cid,
                                    'progress': f"{dp.get('current')}/{dp.get('target')}"}, '')
                if not target:
                    return (True, {'concern_id': cid,
                                    'progress': f"{dp.get('current')}/{dp.get('target')}"}, '')
        return (False, {'concerns_n': len(actives)}, 'no concern updated in last 10min')
    except Exception as e:
        return (False, {}, f'exception: {e}')


def verify_relational(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """看 relational_state 是否最近 add inside_joke / shared_history."""
    try:
        rs = getattr(nerve, 'relational_state', None) if nerve else None
        if rs is None:
            return (False, {}, 'no relational_state')
        cutoff = time.time() - 600
        # check inside_jokes / shared_history_threads recent
        for attr in ('inside_jokes', 'shared_history_threads', 'unspoken_protocols'):
            items = getattr(rs, attr, []) or []
            for it in items[-20:]:
                added_at = float(getattr(it, 'created_at', 0) or 0)
                if added_at >= cutoff:
                    return (True, {'attr': attr, 'id': getattr(it, 'id', None)}, '')
        return (False, {}, 'no relational entry added in last 10min')
    except Exception as e:
        return (False, {}, f'exception: {e}')


# ============================================================
# Built-in Retriers
# ============================================================

def retry_reminder(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """直接 hippocampus.add_reminder. 不通过 tool dispatch."""
    try:
        hippo = getattr(nerve, 'hippocampus', None) if nerve else None
        if hippo is None or not hasattr(hippo, 'add_reminder'):
            return (False, {}, 'no hippocampus.add_reminder')
        intent = claim.extracted_meta.get('intent_excerpt') or claim.extracted_target or 'unknown'
        trigger_time = claim.extracted_meta.get('trigger_time') or claim.extracted_meta.get('time_anchor', '')
        if not trigger_time:
            return (False, {}, 'no trigger_time, cannot retry reminder')
        try:
            rid = hippo.add_reminder(intent=intent, trigger_time=trigger_time)
            return (True, {'reminder_id': rid}, '')
        except Exception as e:
            return (False, {}, f'add_reminder fail: {e}')
    except Exception as e:
        return (False, {}, f'exception: {e}')


def retry_commitment(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """直接 commitment_watcher.register_commitment."""
    try:
        cw = getattr(nerve, 'commitment_watcher', None) if nerve else None
        if cw is None or not hasattr(cw, 'register_commitment'):
            return (False, {}, 'no commitment_watcher.register_commitment')
        desc = claim.extracted_target or claim.extracted_action
        deadline_str = claim.extracted_meta.get('deadline_str') or claim.extracted_meta.get('time_anchor', '')
        cw.register_commitment(
            description=desc,
            deadline_str=deadline_str,
            raw_text=claim.extracted_action,
            author='sir',
        )
        return (True, {'description': desc, 'deadline_str': deadline_str}, '')
    except Exception as e:
        return (False, {}, f'exception: {e}')


def retry_promise(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """直接 promise_log.register."""
    try:
        from jarvis_promise_log import get_default_log
        plog = getattr(nerve, 'promise_log', None) if nerve else None
        if plog is None:
            try:
                plog = get_default_log()
            except Exception as e:
                return (False, {}, f'no promise_log: {e}')
        if not hasattr(plog, 'register'):
            return (False, {}, 'promise_log no register')
        desc = claim.extracted_target or claim.extracted_action
        deadline_str = claim.extracted_meta.get('deadline_str', '')
        kind = claim.extracted_meta.get('kind', 'soft')
        pid = plog.register(
            description=desc,
            kind=kind,
            deadline_str=deadline_str,
            jarvis_reply=claim.captured_reply_excerpt,
            author='jarvis',
        )
        return (True, {'promise_id': pid, 'kind': kind}, '')
    except Exception as e:
        return (False, {}, f'exception: {e}')


def retry_milestone(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """直接 milestones.add_milestone."""
    try:
        from jarvis_milestones import add_milestone
        text = claim.extracted_meta.get('milestone_text') or claim.captured_reply_excerpt[:200]
        if not text:
            return (False, {}, 'no text')
        new_id = add_milestone({
            'text': text,
            'speaker': 'sir',
            'type': 'declaration',
            'created_by': 'integrity_watcher_retry',
        })
        return (True, {'milestone_id': new_id}, '')
    except ImportError:
        return (False, {}, 'jarvis_milestones not importable')
    except Exception as e:
        return (False, {}, f'exception: {e}')


def retry_profile(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """直接 profile_card.apply_correction."""
    try:
        profile = getattr(nerve, 'profile_card', None) if nerve else None
        if profile is None or not hasattr(profile, 'apply_correction'):
            return (False, {}, 'no profile_card.apply_correction')
        field_path = claim.extracted_meta.get('field_path', 'general')
        new_value = claim.extracted_meta.get('new_value', '')
        old_value = claim.extracted_meta.get('old_value', '')
        if not new_value:
            return (False, {}, 'no new_value, cannot retry profile')
        profile.apply_correction(
            source_module='integrity_watcher_retry',
            field=field_path,
            old_value=str(old_value)[:100],
            new_value=str(new_value)[:100],
            confidence=0.9,
        )
        return (True, {'field_path': field_path}, '')
    except Exception as e:
        return (False, {}, f'exception: {e}')


def retry_concern(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """直接 concerns_ledger.record_signal 或 record_user_feedback."""
    try:
        ledger = getattr(nerve, 'concerns_ledger', None) if nerve else None
        if ledger is None:
            return (False, {}, 'no concerns_ledger')
        cid = claim.extracted_meta.get('concern_id', '')
        if not cid:
            return (False, {}, 'no concern_id')
        if hasattr(ledger, 'record_signal'):
            ok = ledger.record_signal(cid, claim.extracted_action[:200],
                                       severity_delta=0.05,
                                       source_turn_id=claim.captured_turn_id)
            return (ok, {'concern_id': cid}, '' if ok else 'concern not found')
        return (False, {}, 'ledger no record_signal')
    except Exception as e:
        return (False, {}, f'exception: {e}')


def retry_relational(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """直接 relational_state.add_inside_joke / add_shared_history."""
    try:
        rs = getattr(nerve, 'relational_state', None) if nerve else None
        if rs is None:
            return (False, {}, 'no relational_state')
        text = claim.extracted_meta.get('joke_text') or claim.extracted_action
        if hasattr(rs, 'add_inside_joke'):
            rs.add_inside_joke(text=text, source_turn_id=claim.captured_turn_id)
            return (True, {'kind': 'inside_joke'}, '')
        if hasattr(rs, 'add_shared_history'):
            rs.add_shared_history(text=text, source_turn_id=claim.captured_turn_id)
            return (True, {'kind': 'shared_history'}, '')
        return (False, {}, 'relational_state no add method')
    except Exception as e:
        return (False, {}, f'exception: {e}')


def retry_memory(claim: Claim, nerve: Any) -> Tuple[bool, Dict[str, Any], str]:
    """memory remember 没有直接 retry — Jarvis 不能"重新记一次".
    
    返 false (不算 retry), watcher 会 mark NO_TOOL_CLAIM 让主脑下轮 admit.
    """
    return (False, {}, 'memory remember has no retry path (主脑无法主动 store)')


# ============================================================
# Default verifier / retrier registry
# ============================================================

DEFAULT_VERIFIERS: Dict[str, VerifyFn] = {
    'reminder':   verify_reminder,
    'commitment': verify_commitment,
    'promise':    verify_promise,
    'memory':     verify_memory,
    'milestone':  verify_milestone,
    'profile':    verify_profile,
    'concern':    verify_concern,
    'relational': verify_relational,
}

DEFAULT_RETRIERS: Dict[str, RetryFn] = {
    'reminder':   retry_reminder,
    'commitment': retry_commitment,
    'promise':    retry_promise,
    'memory':     retry_memory,
    'milestone':  retry_milestone,
    'profile':    retry_profile,
    'concern':    retry_concern,
    'relational': retry_relational,
}


# ============================================================
# IntegrityWatcher — L4.5 Active Verify+Retry 子层
# Sir 14:11: "递归调用直到成功 OR Jarvis 真做不到, handoff Sir 手动"
# ============================================================

class IntegrityWatcher:
    """Jarvis 自检层 — 主动 verify Jarvis reply 中的 mutation claim 是否真完成,
    失败递归 retry, 最终 recovered 或 handoff Sir.

    Sir 14:11 真意:
      "wachter 负责贾维斯所有行为(除调用工具)是否成功的审查机构, 植入言出必行层级中"
      "主动重试, 轻推给主脑, 主动道歉+声明成功. 这是个递归调用, 如果还是没成功,
       wathcher 还能再试. 例外情况是 wathcher 发现贾维斯做不到, 那就说清楚这个事情,
       给我道歉, 并且提出让我手动解决的方案"

    定位: Integrity STACK L4.5 (post L4 audit, pre L5 reconciliation).
    跟 ClaimTracer (L4) 互补 — ClaimTracer 写 audit log, Watcher 主动 retry.
    """

    def __init__(
        self,
        nerve: Any = None,
        store: Optional[IntegrityWatcherStore] = None,
        verifiers: Optional[Dict[str, VerifyFn]] = None,
        retriers: Optional[Dict[str, RetryFn]] = None,
        tick_interval_s: float = DEFAULT_TICK_INTERVAL_S,
        retry_backoff_s: Tuple[float, ...] = DEFAULT_RETRY_BACKOFF_S,
        fresh_buffer_s: float = DEFAULT_FRESH_BUFFER_S,
        handoff_same_error_n: int = DEFAULT_HANDOFF_AFTER_SAME_ERROR_N,
        handoff_after_age_s: float = DEFAULT_HANDOFF_AFTER_AGE_S,
    ):
        self.nerve = nerve
        self.store = store or get_default_store()
        self.verifiers: Dict[str, VerifyFn] = dict(verifiers or DEFAULT_VERIFIERS)
        self.retriers: Dict[str, RetryFn] = dict(retriers or DEFAULT_RETRIERS)
        self.tick_interval_s = float(tick_interval_s)
        self.retry_backoff_s = tuple(retry_backoff_s)
        self.fresh_buffer_s = float(fresh_buffer_s)
        self.handoff_same_error_n = int(handoff_same_error_n)
        self.handoff_after_age_s = float(handoff_after_age_s)
        self._stop_event = threading.Event()
        self._daemon_thread: Optional[threading.Thread] = None
        self._stats = {
            'claims_watched': 0,
            'claims_verified_first_pass': 0,
            'claims_recovered': 0,
            'claims_handoff_sir': 0,
            'claims_no_tool': 0,
            'retries_total': 0,
            'last_tick_ts': 0.0,
            'last_error': '',
        }
        self._lock = threading.RLock()

    def register_verifier(self, claim_type: str, fn: VerifyFn) -> None:
        with self._lock:
            self.verifiers[claim_type] = fn

    def register_retrier(self, claim_type: str, fn: RetryFn) -> None:
        with self._lock:
            self.retriers[claim_type] = fn

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._stats)

    # ---------------- Watch / Capture API ----------------

    def watch_claim(
        self,
        reply_text: str,
        turn_id: str = '',
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """从 reply_text 抽 claim → 加入 watch. Returns: [claim_id...]

        Sir 14:30 设计 — 3 层 waterfall:
          Layer 1 vocab fast-path (0.5-2ms, 主路径)
          Layer 2 suspicious keyword gate (1ms, 决定是否跑 LLM)
          Layer 3 LLM async judge (1-2s, 后台跑, 不阻 TTFT)

        被 chat_bypass 在 stream 末调 (post-stream, fire-and-forget).
        Dedup: 同 turn_id + reply_hash 30s 内不重复 capture.
        """
        if not reply_text or len(reply_text.strip()) < 5:
            return []
        # Turn-level dedup (Sir 14:35 边界 bug — 防同轮多次 capture)
        if turn_id:
            with self._lock:
                _hash = (turn_id, hash(reply_text[:200]))
                now = time.time()
                # cleanup old entries (> 60s)
                if not hasattr(self, '_recent_watches'):
                    self._recent_watches = []
                self._recent_watches = [
                    (h, t) for (h, t) in self._recent_watches if now - t < 60
                ]
                if any(h == _hash for h, _ in self._recent_watches):
                    return []  # dedup, 不重复
                self._recent_watches.append((_hash, now))
                if len(self._recent_watches) > 50:
                    self._recent_watches = self._recent_watches[-30:]
        # Layer 1 — vocab fast-path
        hits = detect_claims_via_regex(reply_text)
        claim_ids = self._add_hits_to_store(hits, reply_text, turn_id, extra_meta)
        # Layer 2 — suspicious keyword gate (vocab miss + 含 kw → 触发 Layer 3)
        if not hits and has_suspicious_keyword(reply_text):
            # vocab miss but kw 命中 → 启 Layer 3 LLM judge async
            self._launch_layer3_async(reply_text, turn_id, extra_meta)
        return claim_ids

    def _add_hits_to_store(
        self,
        hits: List[Dict[str, Any]],
        reply_text: str,
        turn_id: str,
        extra_meta: Optional[Dict[str, Any]],
    ) -> List[str]:
        """把 hits 加入 store + log."""
        claim_ids = []
        if not hits:
            return claim_ids
        time_anchor = extract_time_anchor(reply_text)
        for h in hits:
            ctype = h['claim_type']
            action = h['action_text']
            target = h['target']
            pos = h.get('pos', 0)
            intent_excerpt = extract_intent_excerpt(reply_text, pos + len(action), 60)
            source = h.get('source', 'unknown')
            claim = Claim(
                id='',
                claim_type=ctype,
                extracted_action=action,
                extracted_target=target,
                extracted_meta={
                    'time_anchor': time_anchor,
                    'intent_excerpt': intent_excerpt,
                    'lang': h.get('lang', ''),
                    'detection_source': source,
                    **(extra_meta or {}),
                },
                captured_turn_id=turn_id,
                captured_reply_excerpt=reply_text[:300],
                status=STATUS_WATCHING,
            )
            cid = self.store.add(claim)
            claim_ids.append(cid)
            try:
                from jarvis_utils import bg_log as _bg
                _bg(
                    f"🔍 [IntegrityWatcher/{source}] capture {ctype} claim "
                    f"(id={cid[:8]}, action='{action[:40]}', "
                    f"target='{target[:30]}', time='{time_anchor}')"
                )
            except Exception:
                pass
        with self._lock:
            self._stats['claims_watched'] += len(claim_ids)
        return claim_ids

    def _launch_layer3_async(
        self,
        reply_text: str,
        turn_id: str,
        extra_meta: Optional[Dict[str, Any]],
    ) -> None:
        """[Layer 3] 启动 LLM async judge — vocab 没命中 + kw 命中 时.

        Sir 14:30 设计原则: LLM 仅在边界 case 跑, 估计 < 5% reply.
        完全后台 (daemon thread), 0 阻塞.
        """
        if _DEFAULT_LLM_JUDGE is None or not _DEFAULT_LLM_JUDGE.is_available():
            return
        t = threading.Thread(
            target=_DEFAULT_LLM_JUDGE.judge_and_capture,
            args=(self, reply_text, turn_id, extra_meta),
            daemon=True,
            name=f'IntegrityWatcher.L3-LLM/{turn_id[:12] if turn_id else "?"}',
        )
        t.start()

    def watch_claim_async(
        self,
        reply_text: str,
        turn_id: str = '',
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> threading.Thread:
        """fire-and-forget 入口."""
        t = threading.Thread(
            target=self.watch_claim,
            args=(reply_text, turn_id, extra_meta),
            daemon=True,
            name=f'IntegrityWatcher.watch/{turn_id[:12] if turn_id else "?"}',
        )
        t.start()
        return t

    # ---------------- Verify / Retry / Handoff ----------------

    def _is_in_backoff(self, claim: Claim) -> bool:
        """检查 claim 是否在 backoff 期间 (next_retry_ts 未到)."""
        if claim.next_retry_ts <= 0:
            return False
        return time.time() < claim.next_retry_ts

    def _set_backoff(self, claim: Claim) -> None:
        """根据 claim.retries 设 next_retry_ts."""
        idx = min(claim.retries, len(self.retry_backoff_s) - 1)
        backoff = self.retry_backoff_s[idx]
        claim.next_retry_ts = time.time() + backoff

    def _detect_cannot_recover(self, claim: Claim) -> Optional[str]:
        """判 claim 是否 'Jarvis 真做不到', 返 reason 或 None.

        条件:
          (a) verify_history 中最近 N 次 retry error 完全相同 → 判 cannot_recover
          (b) age > handoff_after_age_s → 兜底 handoff
          (c) error 含明确 cannot 关键词 (e.g. 'no method', 'no such field', 'no add_xxx')
        """
        if claim.age_s() > self.handoff_after_age_s:
            return f'age > {int(self.handoff_after_age_s/60)}min, 兜底 handoff'

        retry_errors = [h.get('error', '') for h in claim.verify_history
                        if h.get('phase') == 'retry'][-self.handoff_same_error_n:]
        if len(retry_errors) >= self.handoff_same_error_n and len(set(retry_errors)) == 1:
            return f"same retry error {self.handoff_same_error_n}× → cannot_recover: '{retry_errors[0][:80]}'"

        # 明确 cannot 关键词
        cannot_keywords = ('no method', 'no add_', 'no such field', 'has no register',
                           'no retry path', 'not importable')
        for h in claim.verify_history[-2:]:
            err = (h.get('error', '') or '').lower()
            for kw in cannot_keywords:
                if kw in err:
                    return f"clear cannot signal in error: '{kw}'"
        return None

    def _try_verify(self, claim: Claim) -> Tuple[bool, Dict[str, Any], str]:
        """跑 verifier."""
        fn = self.verifiers.get(claim.claim_type)
        if fn is None:
            return (False, {}, f'no verifier for claim_type={claim.claim_type}')
        try:
            return fn(claim, self.nerve)
        except Exception as e:
            return (False, {}, f'verifier exception: {e}')

    def _try_retry(self, claim: Claim) -> Tuple[bool, Dict[str, Any], str]:
        """跑 retrier."""
        fn = self.retriers.get(claim.claim_type)
        if fn is None:
            return (False, {}, f'no retrier for claim_type={claim.claim_type}')
        try:
            return fn(claim, self.nerve)
        except Exception as e:
            return (False, {}, f'retrier exception: {e}')

    def _publish_swm(self, etype: str, claim: Claim, **extra) -> None:
        """publish SWM event."""
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            salience = {
                'integrity_verified': 0.40,    # 验过, 不打扰
                'integrity_recovered': 0.75,    # 主脑该 inline acknowledge
                'integrity_handoff_sir': 0.85,  # 主脑该 actionable surface + 道歉
                'integrity_no_tool': 0.70,      # 主脑该 admit hallucination
                'integrity_retry_attempt': 0.30,  # 信息性
            }.get(etype, 0.50)
            bus.publish(
                etype=etype,
                description=f"{claim.claim_type} claim '{claim.extracted_target[:60]}' → {claim.status}",
                source='IntegrityWatcher',
                salience=salience,
                metadata={
                    'claim_id': claim.id,
                    'claim_type': claim.claim_type,
                    'extracted_action': claim.extracted_action[:120],
                    'extracted_target': claim.extracted_target[:80],
                    'status': claim.status,
                    'retries': claim.retries,
                    'final_error': claim.final_error[:160],
                    'final_evidence': claim.final_evidence,
                    'age_s': int(claim.age_s()),
                    'captured_turn_id': claim.captured_turn_id,
                    **extra,
                },
            )
        except Exception:
            pass

    def _process_one(self, claim: Claim) -> None:
        """单 claim 一次 tick 处理 (verify → 失败 retry → 失败 backoff or handoff)."""
        # 给 fresh buffer (避免 IntentResolver 还没跑完)
        if claim.age_s() < self.fresh_buffer_s:
            return

        # backoff 中, 跳过本 tick
        if self._is_in_backoff(claim):
            return

        # 1. 跑 verify
        ok, ev, err = self._try_verify(claim)
        claim.last_verify_ts = time.time()
        claim.verify_history.append({
            'ts': claim.last_verify_ts,
            'phase': 'verify',
            'ok': ok,
            'evidence': ev,
            'error': err,
        })

        if ok:
            # 真完成 - 第一次 verify 成功
            if claim.retries == 0:
                claim.status = STATUS_VERIFIED
                claim.final_evidence = ev
                with self._lock:
                    self._stats['claims_verified_first_pass'] += 1
                self.store.update(claim)
                self._publish_swm('integrity_verified', claim)
                return
            # retry 后 verify 通过 → recovered
            claim.status = STATUS_RECOVERED
            claim.final_evidence = ev
            with self._lock:
                self._stats['claims_recovered'] += 1
            self.store.update(claim)
            self._publish_swm('integrity_recovered', claim)
            try:
                from jarvis_utils import bg_log as _bg
                _bg(
                    f"✅ [IntegrityWatcher] {claim.claim_type} claim "
                    f"id={claim.id[:8]} RECOVERED after {claim.retries} retries"
                )
            except Exception:
                pass
            return

        # verify 失败 — 检 cannot_recover
        cannot_reason = self._detect_cannot_recover(claim)
        if cannot_reason:
            claim.status = STATUS_HANDOFF_SIR
            claim.final_error = cannot_reason
            with self._lock:
                self._stats['claims_handoff_sir'] += 1
            self.store.update(claim)
            self._publish_swm('integrity_handoff_sir', claim, cannot_reason=cannot_reason)
            try:
                from jarvis_utils import bg_log as _bg
                _bg(
                    f"❌ [IntegrityWatcher] {claim.claim_type} claim id={claim.id[:8]} "
                    f"HANDOFF SIR after {claim.retries} retries: {cannot_reason[:80]}"
                )
            except Exception:
                pass
            return

        # 跑 retry
        claim.status = STATUS_RETRYING
        claim.retries += 1
        claim.last_retry_ts = time.time()
        with self._lock:
            self._stats['retries_total'] += 1
        retry_ok, retry_ev, retry_err = self._try_retry(claim)
        claim.verify_history.append({
            'ts': claim.last_retry_ts,
            'phase': 'retry',
            'ok': retry_ok,
            'evidence': retry_ev,
            'error': retry_err,
        })
        self._publish_swm('integrity_retry_attempt', claim,
                          retry_ok=retry_ok, retry_error=retry_err[:120])

        if retry_ok:
            # retry 表面成功 — 但需要再 verify 才确认 (下个 tick)
            self._set_backoff(claim)  # 给新 mutation 时间落盘
            self.store.update(claim)
            try:
                from jarvis_utils import bg_log as _bg
                _bg(
                    f"🔄 [IntegrityWatcher] {claim.claim_type} claim id={claim.id[:8]} "
                    f"retry #{claim.retries} reported ok, will verify next tick"
                )
            except Exception:
                pass
            return

        # retry 也失败 — 检 cannot_recover
        cannot_reason = self._detect_cannot_recover(claim)
        if cannot_reason:
            claim.status = STATUS_HANDOFF_SIR
            claim.final_error = retry_err or cannot_reason
            with self._lock:
                self._stats['claims_handoff_sir'] += 1
            self.store.update(claim)
            self._publish_swm('integrity_handoff_sir', claim, cannot_reason=cannot_reason)
            try:
                from jarvis_utils import bg_log as _bg
                _bg(
                    f"❌ [IntegrityWatcher] {claim.claim_type} claim id={claim.id[:8]} "
                    f"HANDOFF SIR after retry #{claim.retries} fail: {cannot_reason[:80]}"
                )
            except Exception:
                pass
            return

        # 还有希望 — backoff 等下次 tick
        self._set_backoff(claim)
        self.store.update(claim)

    # ---------------- Daemon ----------------

    def _daemon_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    self._stats['last_tick_ts'] = time.time()
                items = self.store.all_items(only_active=True)
                for c in items:
                    if self._stop_event.is_set():
                        break
                    try:
                        self._process_one(c)
                    except Exception as e:
                        with self._lock:
                            self._stats['last_error'] = str(e)[:200]
            except Exception as e:
                with self._lock:
                    self._stats['last_error'] = f'tick exception: {e}'
            self._stop_event.wait(self.tick_interval_s)

    def start(self) -> None:
        """启动 daemon thread."""
        if self._daemon_thread is not None and self._daemon_thread.is_alive():
            return
        self._stop_event.clear()
        self._daemon_thread = threading.Thread(
            target=self._daemon_loop,
            daemon=True,
            name='IntegrityWatcher-daemon',
        )
        self._daemon_thread.start()
        try:
            from jarvis_utils import bg_log as _bg
            _bg(
                f"🛡️ [IntegrityWatcher] L4.5 daemon started "
                f"(tick={self.tick_interval_s}s, claim_types={len(self.verifiers)}). "
                f"Sir 14:11 真意 — 主动 verify + 递归 retry."
            )
        except Exception:
            pass

    def stop(self) -> None:
        self._stop_event.set()


# ============================================================
# Default singleton
# ============================================================

_DEFAULT_WATCHER: Optional[IntegrityWatcher] = None
_DEFAULT_WATCHER_LOCK = threading.Lock()


def get_default_watcher(nerve: Any = None) -> IntegrityWatcher:
    """central_nerve 启动时调, 之后传 nerve_ref."""
    global _DEFAULT_WATCHER
    with _DEFAULT_WATCHER_LOCK:
        if _DEFAULT_WATCHER is None:
            _DEFAULT_WATCHER = IntegrityWatcher(nerve=nerve)
        elif nerve is not None and _DEFAULT_WATCHER.nerve is None:
            _DEFAULT_WATCHER.nerve = nerve
        return _DEFAULT_WATCHER


def reset_default_watcher_for_tests() -> None:
    global _DEFAULT_WATCHER
    with _DEFAULT_WATCHER_LOCK:
        if _DEFAULT_WATCHER is not None:
            _DEFAULT_WATCHER.stop()
        _DEFAULT_WATCHER = None
        reset_default_store_for_tests()


# ============================================================
# Layer 3 — LLM async judge
# Sir 14:30: vocab miss + suspicious keyword → LLM 二次判
# Sir 14:25: 不阻塞 / 性价比. LLM 仅 < 5% reply 调.
# ============================================================

LLM_JUDGE_PROMPT = """You are Jarvis's IntegrityWatcher LLM judge. The reply below was emitted, but vocab fast-path missed it. We suspect it may contain a mutation claim (Jarvis claiming he did X). Identify mutation claims that need verification.

Mutation claim types (Jarvis internal capabilities ONLY — NOT tool calls):
  - reminder: "I've set/added/scheduled X reminder/alarm"
  - commitment: "Got it / noted / understood / I'll hold you to X"
  - promise: "I'll do X by Y" (future timed action)
  - memory: "I'll remember / I've remembered X"
  - milestone: "I'll keep X forever / treasure / cherish / 永远记住"
  - profile: "I've updated/modified your profile/preferences/info"
  - concern: "I've noted/tracked your concern about X"
  - relational: "I'll remember this joke / inside joke"

What is NOT a claim (DON'T return):
  - Future tense without specifics ("I'll help" — too vague)
  - Polite social ("Of course, Sir" / "Yes, Sir")
  - Tool calls (those handle themselves via 主脑→工具→主脑 loop)
  - Greetings / closings

Reply text:
\"\"\"
{reply_text}
\"\"\"

Output JSON only, no markdown:
{{
  "claims": [
    {{
      "claim_type": "<type>",
      "action_text": "<verbatim short phrase from reply>",
      "target": "<what mutation about, e.g. 'reminder for 7am' / 'sir height'>",
      "lang": "en|zh"
    }}
  ]
}}

If no real mutation claim, return {{"claims": []}}.
"""


class _LlmClaimJudge:
    """Layer 3 LLM judge (gemini-flash via OpenRouter). Async, 不阻 TTFT.

    跟 ToMReflector / IntegrityReflector 同范式. key_router 没配 → 直接 unavailable.
    """

    def __init__(self, key_router=None):
        self.key_router = key_router
        self._lock = threading.Lock()
        self._stats = {
            'judges_called': 0,
            'judges_succeeded': 0,
            'claims_extracted': 0,
            'last_error': '',
        }

    def attach_key_router(self, key_router) -> None:
        with self._lock:
            self.key_router = key_router

    def is_available(self) -> bool:
        return self.key_router is not None

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._stats)

    def judge_and_capture(
        self,
        watcher: 'IntegrityWatcher',
        reply_text: str,
        turn_id: str,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """LLM judge → 命中 claim → 加入 watcher store. fire-and-forget thread 目标."""
        if not self.is_available() or not reply_text:
            return
        with self._lock:
            self._stats['judges_called'] += 1
        try:
            from jarvis_utils import safe_openrouter_call
        except Exception:
            with self._lock:
                self._stats['last_error'] = 'safe_openrouter_call import fail'
            return
        try:
            okey, _label = self.key_router.get_openrouter_key(caller='integrity_watcher_l3')
        except Exception as e:
            with self._lock:
                self._stats['last_error'] = f'key error: {e}'
            return
        prompt = LLM_JUDGE_PROMPT.format(reply_text=reply_text[:1500])
        try:
            response_text = safe_openrouter_call(
                openrouter_key=okey,
                model='google/gemini-2.5-flash-preview-09-2025',
                prompt=prompt,
                max_tokens=400,
                temperature=0.1,
            )
        except Exception as e:
            with self._lock:
                self._stats['last_error'] = f'LLM call fail: {str(e)[:80]}'
            return
        # parse JSON
        txt = (response_text or '').strip()
        if txt.startswith('```'):
            lines = txt.split('\n')
            if len(lines) >= 3 and lines[-1].strip().startswith('```'):
                txt = '\n'.join(lines[1:-1])
        try:
            parsed = json.loads(txt)
        except Exception as e:
            with self._lock:
                self._stats['last_error'] = f'parse fail: {str(e)[:60]}'
            return
        claims_data = parsed.get('claims', []) if isinstance(parsed, dict) else []
        if not isinstance(claims_data, list) or not claims_data:
            with self._lock:
                self._stats['judges_succeeded'] += 1
            return
        # 转 hits 格式
        hits = []
        for c in claims_data[:5]:  # max 5 防 LLM 爆
            try:
                ctype = (c.get('claim_type') or '').strip().lower()
                action = (c.get('action_text') or '').strip()[:120]
                target = (c.get('target') or '').strip()[:80]
                lang = (c.get('lang') or 'en').strip().lower()
                if not ctype or not action:
                    continue
                # find pos in reply
                pos = reply_text.find(action)
                if pos < 0:
                    pos = 0
                hits.append({
                    'claim_type': ctype,
                    'action_text': action,
                    'target': target,
                    'lang': lang,
                    'pos': pos,
                    'source': 'llm_layer3',
                })
            except Exception:
                continue
        if hits:
            watcher._add_hits_to_store(hits, reply_text, turn_id, extra_meta)
            with self._lock:
                self._stats['judges_succeeded'] += 1
                self._stats['claims_extracted'] += len(hits)
            try:
                from jarvis_utils import bg_log as _bg
                _bg(
                    f"🤖 [IntegrityWatcher/L3-LLM] extracted {len(hits)} claim(s) "
                    f"from reply (turn={turn_id[:12]}) — vocab missed but LLM caught"
                )
            except Exception:
                pass


_DEFAULT_LLM_JUDGE: Optional[_LlmClaimJudge] = None
_DEFAULT_LLM_JUDGE_LOCK = threading.Lock()


def get_default_llm_judge() -> _LlmClaimJudge:
    global _DEFAULT_LLM_JUDGE
    with _DEFAULT_LLM_JUDGE_LOCK:
        if _DEFAULT_LLM_JUDGE is None:
            _DEFAULT_LLM_JUDGE = _LlmClaimJudge()
        return _DEFAULT_LLM_JUDGE


def attach_llm_judge_key_router(key_router) -> None:
    """central_nerve 启动时调, 注入 key_router."""
    judge = get_default_llm_judge()
    judge.attach_key_router(key_router)


# ============================================================
# Render block for prompt (主脑下轮看 [INTEGRITY WATCHER REPORT])
# ============================================================

def render_report_block(within_seconds: float = 1800.0,
                          max_show: int = 3) -> str:
    """看 SWM 最近 events, 渲染 [INTEGRITY WATCHER REPORT] block 给主脑.

    显:
      - integrity_recovered: 主脑应主动 inline acknowledge "刚补上了"
      - integrity_handoff_sir: 主脑应道歉 + 提议 Sir 手动
      - integrity_no_tool: 主脑应 admit hallucination
    不显: integrity_verified (无需打扰 / 默认行为)
    """
    try:
        from jarvis_utils import get_event_bus
        bus = get_event_bus()
        if bus is None:
            return ''
        types = {'integrity_recovered', 'integrity_handoff_sir', 'integrity_no_tool'}
        events = bus.recent_events(within_seconds=within_seconds, types=types) or []
        if not events:
            return ''

        # de-dup by claim_id
        seen = set()
        recovered: List[Dict] = []
        handoff: List[Dict] = []
        no_tool: List[Dict] = []
        for e in events:
            meta = e.get('metadata') or {}
            cid = meta.get('claim_id', '')
            if not cid or cid in seen:
                continue
            seen.add(cid)
            etype = e.get('type', e.get('etype', ''))
            entry = {
                'claim_id': cid,
                'claim_type': meta.get('claim_type', '?'),
                'action': (meta.get('extracted_action', '') or '')[:80],
                'target': (meta.get('extracted_target', '') or '')[:60],
                'final_evidence': meta.get('final_evidence', {}),
                'final_error': (meta.get('final_error', '') or '')[:120],
                'cannot_reason': (meta.get('cannot_reason', '') or '')[:120],
                'retries': meta.get('retries', 0),
                'age_s': meta.get('age_s', 0),
            }
            if etype == 'integrity_recovered':
                recovered.append(entry)
            elif etype == 'integrity_handoff_sir':
                handoff.append(entry)
            elif etype == 'integrity_no_tool':
                no_tool.append(entry)

        if not (recovered or handoff or no_tool):
            return ''

        lines = [
            '[INTEGRITY WATCHER REPORT — L4.5 自检层 / Sir 14:11 真意]',
            '  你之前 reply 中声称完成的 mutation, IntegrityWatcher 验证 + retry 后:',
            '',
        ]
        if recovered:
            lines.append('  ✅ 已自动补救 (你之前 claim 没真完成, watcher 重补成功 — '
                          '主脑请 inline acknowledge):')
            for r in recovered[:max_show]:
                lines.append(
                    f"    - {r['claim_type']}: \"{r['target']}\" "
                    f"(retried {r['retries']}× → 现已 OK, evidence={str(r['final_evidence'])[:60]})"
                )
            lines.append(
                '    💡 建议 inline 句式: "顺便 Sir, 之前那 X 没设上, 我刚补了, 现在 OK 了."'
            )
            lines.append('')
        if handoff:
            lines.append('  ❌ Jarvis 做不到 (watcher retry 多次仍失败 — '
                          '主脑请道歉 + 给 Sir 手动方案):')
            for h in handoff[:max_show]:
                reason = h['cannot_reason'] or h['final_error']
                lines.append(
                    f"    - {h['claim_type']}: \"{h['target']}\" "
                    f"(retries={h['retries']}, age={h['age_s']}s, reason: {reason[:80]})"
                )
            lines.append(
                '    💡 建议 actionable 句式: "Sir 我那 X 没设上, retry 了 N 次仍失败 '
                '(原因 Y). 您要不要手动 Z / 我换其他方式 / 跳过这个?"'
            )
            lines.append('')
        if no_tool:
            # 🩹 [P5-fixCB-final / 2026-05-21 17:30 Sir 18:25 真意"澄清类"] no_tool 升级
            # Sir 真意: "澄清自己说做了, 但是其实超出能力边界, 自然在下一轮对话提及并且
            # 道歉, 自然的语言, 甚至可以提高主动性, 表明自己做什么事需要什么能力, 希望获得"
            # 老句式只 "admit 没真做 + 询问要不要现在做" — Sir 要更主动: 表能力边界 + 求 capability.
            lines.append('  ⚠️ 你之前说做了 X 但其实超出 Jarvis 当前能力边界 (无对应 module/tool):')
            for n in no_tool[:max_show]:
                lines.append(
                    f"    - {n['claim_type']}: \"{n['target']}\" "
                    f"(action='{n['action']}')"
                )
            lines.append(
                '    💡 建议主动澄清句式 (Sir 18:25 真意, 提高主动性 / 表能力诉求):'
            )
            lines.append(
                '       "Sir, 关于刚才说的 X — 我其实超出了能力边界, 没有 Y tool/path 真做这事."'
            )
            lines.append(
                '       "如果您希望我能 X, 我需要 Z 能力. 您要不要让我 (跳过 / 用其他方式 / 添加 Z 通道)?"'
            )
            lines.append(
                '       (自然语言, 不要 ritual "I must apologize"; 只在你说做了那件事的下轮 surface 1 次)'
            )

        return '\n'.join(lines)
    except Exception:
        return ''


# ============================================================
# Stats
# ============================================================

def get_stats() -> Dict[str, Any]:
    """全局 watcher stats (CLI 调)."""
    try:
        watcher = _DEFAULT_WATCHER
        store = get_default_store()
        items = store.all_items()
        st = watcher.stats() if watcher else {}
        st['total_claims'] = len(items)
        st['active'] = sum(1 for c in items if not c.is_terminal())
        st['recovered'] = sum(1 for c in items if c.status == STATUS_RECOVERED)
        st['handoff_sir'] = sum(1 for c in items if c.status == STATUS_HANDOFF_SIR)
        st['verified_first_pass'] = sum(1 for c in items if c.status == STATUS_VERIFIED)
        st['no_tool'] = sum(1 for c in items if c.status == STATUS_NO_TOOL)
        return st
    except Exception:
        return {}
