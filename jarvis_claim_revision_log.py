# -*- coding: utf-8 -*-
"""[P5-fixCB-revise / 2026-05-21 11:35] Claim Revision Log — 道歉是 functional revision 不是 ritual.

Sir 11:30 真意:
  > "贾维斯在我提出质疑的时候, 描述自己的能力边界, 或者在他自己发现自己的承诺没履行的时候,
  >  主动履行/承认边界. 道歉要有意义的道歉."

之前 P5-fixCB B+C 把所有 unsolicited callback 当 ritual ban 掉 — 砍 functional honesty 通道.
真治本 = redirect 不 ban:
  - 主脑想 backtrack 老 over-claim → 写 STM/SWM ClaimRevision pending state
  - **不在当前 reply 主动说**, 等以下 2 个合法 surface 触发:
    (a) Sir 召唤: Sir current utterance 含 capability 关键词 / 质疑句式
        → intent_resolver / keyword 命中 → publish 'sir_querying_capability'
        → 主脑下轮看 [PENDING CLAIM REVISIONS] block + 主动 surface 修正
    (b) 自检 due: Jarvis 自己发现 promise/claim 已 due 没履行
        → 跟 PromiseExecutor / SelfPromiseDetector 联动 (现有)
        → 主脑下轮看 [SELF-PROMISE OVERDUE] block 主动 admit

跟 P0+20-β.5.43-fix4 no_hallucinated_tool_use 互补:
  - 那条防"声称做了没做的 mutation"
  - 本模块防"主动 unsolicited backtrack 老 over-claim"
  - 同时保留 functional revision 通道 (Sir 召唤 / due 触发时主动 admit)

跟 jarvis_callback_guard 协作:
  - callback_guard 检测 reply 命中 forbidden_callback_vocab → 不再 publish 'violation'
  - 改 publish 'claim_revision_intent' + 写 ClaimRevisionLog (capability + reason)
  - 主脑下轮看 [PENDING CLAIM REVISIONS] block (合法 surface 触发时显)

持久化: memory_pool/claim_revisions.json (准则 6 合规)
CLI: scripts/claim_revision_dump.py (Sir list / surface / archive)
testcase: tests/_test_p0_plus_20_p5_claim_revision.py
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STORE_PATH = os.path.join(ROOT, 'memory_pool', 'claim_revisions.json')


# ============================================================
# Status enum (string)
# ============================================================
STATUS_PENDING = 'pending'      # 待 Sir 召唤 / 主脑自决 surface
STATUS_SURFACED = 'surfaced'    # 主脑已在某 turn 主动 admit
STATUS_ARCHIVED = 'archived'    # 长期没 surface (Sir 永远不问) → 归档
STATUS_REJECTED = 'rejected'    # Sir CLI 标记 "这条 revision 不需要" (false positive)


# ============================================================
# Dataclass
# ============================================================

@dataclass
class ClaimRevision:
    id: str                              # uuid4
    capability_keyword: str              # 主 capability 关键词 (e.g. 'reminder', 'quota', 'parameter')
    original_claim_excerpt: str          # 主脑想 backtrack 的原话节选 (< 200 chars)
    admitted_lacking_reason: str         # 修正原因 (< 200 chars), 解释为什么承认 over-claim
    captured_at: float                   # unix timestamp
    captured_iso: str                    # ISO 8601 (Sir 看)
    captured_turn_id: str                # 触发的 turn_id
    related_keywords: List[str] = field(default_factory=list)  # Sir 召唤匹配关键词
    status: str = STATUS_PENDING
    surfaced_at: Optional[float] = None
    surfaced_turn_id: str = ''
    archived_at: Optional[float] = None
    rejected_by_sir: bool = False
    source: str = 'callback_guard'       # 'callback_guard' / 'self_detect' / 'sir_cli'

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'ClaimRevision':
        # backward-compat: drop unknown fields
        valid = {k: d.get(k, '') for k in cls.__annotations__.keys()}
        # types
        valid['captured_at'] = float(valid.get('captured_at') or 0.0)
        valid['surfaced_at'] = (
            float(valid['surfaced_at']) if valid.get('surfaced_at') else None
        )
        valid['archived_at'] = (
            float(valid['archived_at']) if valid.get('archived_at') else None
        )
        valid['rejected_by_sir'] = bool(valid.get('rejected_by_sir', False))
        valid['related_keywords'] = list(valid.get('related_keywords') or [])
        return cls(**valid)


# ============================================================
# Store
# ============================================================

class ClaimRevisionStore:
    """Thread-safe 持久化 store. atomic write + mtime cache."""

    def __init__(self, path: Optional[str] = None):
        self._path = path or DEFAULT_STORE_PATH
        self._lock = threading.Lock()
        self._items: Dict[str, ClaimRevision] = {}
        self._mtime: float = 0.0
        self._loaded_once = False
        self._load()

    def _load(self) -> None:
        with self._lock:
            try:
                mtime = os.path.getmtime(self._path)
            except OSError:
                self._items = {}
                self._loaded_once = True
                return
            if self._loaded_once and mtime == self._mtime:
                return
            try:
                with open(self._path, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
            except Exception:
                if not self._loaded_once:
                    self._items = {}
                    self._loaded_once = True
                return
            items = {}
            for entry in data.get('revisions', []):
                try:
                    rev = ClaimRevision.from_dict(entry)
                    if rev.id:
                        items[rev.id] = rev
                except Exception:
                    continue
            self._items = items
            self._mtime = mtime
            self._loaded_once = True

    def _persist(self) -> None:
        """atomic write: tmp + replace."""
        tmp = self._path + '.tmp'
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        payload = {
            '_meta': {
                'schema_version': '1.0',
                'updated_at': time.time(),
                'updated_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
            },
            'revisions': [r.to_dict() for r in self._items.values()],
        }
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        try:
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.remove(self._path)
            except Exception:
                pass
            os.rename(tmp, self._path)
        try:
            self._mtime = os.path.getmtime(self._path)
        except Exception:
            pass

    # ---- public API ----

    def add(self, revision: ClaimRevision) -> str:
        """加新 revision. 自动生成 id (若空) 和 captured_iso."""
        with self._lock:
            if not revision.id:
                revision.id = uuid.uuid4().hex[:12]
            if not revision.captured_at:
                revision.captured_at = time.time()
            if not revision.captured_iso:
                revision.captured_iso = time.strftime(
                    '%Y-%m-%dT%H:%M:%S', time.localtime(revision.captured_at)
                )
            self._items[revision.id] = revision
            self._persist()
            return revision.id

    def get_pending(
        self,
        within_days: float = 7.0,
        related_to_keywords: Optional[List[str]] = None,
        limit: int = 5,
    ) -> List[ClaimRevision]:
        """取近 within_days 内 pending 的 revisions, 可选按 keyword 匹配."""
        self._load()  # mtime cache, cheap
        with self._lock:
            cutoff = time.time() - within_days * 86400.0
            out = [
                r for r in self._items.values()
                if r.status == STATUS_PENDING and r.captured_at >= cutoff
                and not r.rejected_by_sir
            ]
            if related_to_keywords:
                kws_lower = [k.lower() for k in related_to_keywords if k]
                def _match(rev: ClaimRevision) -> bool:
                    if not kws_lower:
                        return True
                    text = (
                        rev.capability_keyword + ' ' + ' '.join(rev.related_keywords)
                    ).lower()
                    return any(kw in text for kw in kws_lower)
                out = [r for r in out if _match(r)]
            out.sort(key=lambda r: r.captured_at, reverse=True)
            return out[:limit]

    def mark_surfaced(self, revision_id: str, turn_id: str = '') -> bool:
        with self._lock:
            rev = self._items.get(revision_id)
            if not rev:
                return False
            rev.status = STATUS_SURFACED
            rev.surfaced_at = time.time()
            rev.surfaced_turn_id = turn_id or ''
            self._persist()
            return True

    def archive_stale(self, days: float = 7.0) -> int:
        """超过 days 没 surface 的 pending → archive."""
        with self._lock:
            cutoff = time.time() - days * 86400.0
            n = 0
            for rev in self._items.values():
                if rev.status == STATUS_PENDING and rev.captured_at < cutoff:
                    rev.status = STATUS_ARCHIVED
                    rev.archived_at = time.time()
                    n += 1
            if n:
                self._persist()
            return n

    def reject(self, revision_id: str) -> bool:
        with self._lock:
            rev = self._items.get(revision_id)
            if not rev:
                return False
            rev.rejected_by_sir = True
            rev.status = STATUS_REJECTED
            self._persist()
            return True

    def all_items(self, include_archived: bool = False) -> List[ClaimRevision]:
        self._load()
        with self._lock:
            items = list(self._items.values())
            if not include_archived:
                items = [
                    r for r in items
                    if r.status not in (STATUS_ARCHIVED, STATUS_REJECTED)
                ]
            items.sort(key=lambda r: r.captured_at, reverse=True)
            return items


_DEFAULT_STORE: Optional[ClaimRevisionStore] = None
_STORE_LOCK = threading.Lock()


def get_default_store() -> ClaimRevisionStore:
    global _DEFAULT_STORE
    with _STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = ClaimRevisionStore()
        return _DEFAULT_STORE


def reset_default_store_for_tests(path: Optional[str] = None) -> None:
    global _DEFAULT_STORE
    with _STORE_LOCK:
        _DEFAULT_STORE = ClaimRevisionStore(path=path)


# ============================================================
# Capture API (callback_guard 调)
# ============================================================

def capture_revision_from_reply(
    reply_excerpt: str,
    capability_keyword: str,
    admitted_lacking_reason: str = '',
    turn_id: str = '',
    related_keywords: Optional[List[str]] = None,
    source: str = 'callback_guard',
) -> Optional[str]:
    """主脑想 backtrack 时, callback_guard / self-detect 调本 API:
    写 ClaimRevisionLog 不在 reply 主动说.

    Returns: revision_id 或 None (失败).
    """
    if not capability_keyword:
        return None
    try:
        rev = ClaimRevision(
            id='',
            capability_keyword=capability_keyword.strip()[:80],
            original_claim_excerpt=(reply_excerpt or '')[:200],
            admitted_lacking_reason=(admitted_lacking_reason or '')[:200],
            captured_at=0.0,
            captured_iso='',
            captured_turn_id=(turn_id or '')[:40],
            related_keywords=[k.strip()[:40] for k in (related_keywords or []) if k][:8],
            status=STATUS_PENDING,
            source=source[:40],
        )
        rid = get_default_store().add(rev)

        # publish SWM 'claim_revision_captured' (信息 event, 不是 violation)
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                bus.publish(
                    etype='claim_revision_captured',
                    description=(
                        f"主脑想 backtrack capability='{capability_keyword[:40]}' "
                        f"已 redirect 到 ClaimRevisionLog (id={rid}). "
                        f"等 Sir 召唤或主脑自决再 surface."
                    ),
                    source='ClaimRevisionLog',
                    salience=0.55,
                    metadata={
                        'revision_id': rid,
                        'capability_keyword': capability_keyword[:80],
                        'turn_id': turn_id[:40],
                        'source': source[:40],
                    },
                )
        except Exception:
            pass

        try:
            from jarvis_utils import bg_log
            bg_log(
                f"📝 [ClaimRevision] captured id={rid} cap='{capability_keyword[:30]}' "
                f"turn={turn_id[:16]} (redirect, 不在 reply 说)"
            )
        except Exception:
            pass
        return rid
    except Exception as e:
        try:
            from jarvis_utils import bg_log
            bg_log(f"⚠️ [ClaimRevision] capture failed: {e}")
        except Exception:
            pass
        return None


# ============================================================
# Sir 召唤 detect (合法 surface 触发 a)
# ============================================================

# Sir 质疑 / 询问 capability 句式
_SIR_QUERY_PATTERNS = [
    # 英文质疑
    re.compile(r'\bcan\s+you\s+(actually\s+)?(do|set|get|change|update)\b', re.IGNORECASE),
    re.compile(r'\bdid\s+you\s+(actually\s+)?(do|set|get|change|update|save)\b', re.IGNORECASE),
    re.compile(r'\bdo\s+you\s+(actually\s+)?have\s+(the\s+)?(ability|capability|access|permission)', re.IGNORECASE),
    re.compile(r'\bare\s+you\s+(actually\s+)?(able|capable)\s+to\b', re.IGNORECASE),
    re.compile(r'\bis\s+(it|that|this)\s+actually\s+(possible|done|set|saved)', re.IGNORECASE),
    re.compile(r'\bwhat\s+about\s+(the\s+)?', re.IGNORECASE),  # "what about the X"
    re.compile(r'\bhow\s+about\s+(the\s+)?', re.IGNORECASE),
    re.compile(r'\bdid\s+(it|that)\s+(work|go\s+through|succeed|happen)', re.IGNORECASE),
    # 英文 outright callout
    re.compile(r'\byou\s+(claimed|said|told\s+me|promised)\b', re.IGNORECASE),
    re.compile(r'\byou\s+(lied|made\s+(it\s+)?up|are\s+wrong|messed\s+up)\b', re.IGNORECASE),
    # 中文质疑
    re.compile(r'你能(吗|不能|不可以)'),
    re.compile(r'你(真的|真能)能?(做|设|改|更新|保存)'),
    re.compile(r'你(刚才|之前|刚刚)(说|做|讲|提)(过)?(的|了)?'),
    re.compile(r'(那|这)(个|件|条)?事(怎么样|做了吗|搞定了吗)'),
    re.compile(r'你(是不是|有没有)(真的|真)?(做|设|改|发|存|说|讲|提|答应)(了|到|过)'),
    re.compile(r'你(之前|刚才|刚刚).{0,6}(说|做|讲|提|答应|声称|claim)'),  # 兼容 '你之前是不是说过'
    re.compile(r'你(撒谎|骗|乱|说错|搞错|吹|没那个能力)'),
    re.compile(r'你能?不能(做|改|设|访问)'),
]


def detect_sir_querying_capability(sir_utterance: str) -> bool:
    """Sir current utterance 是否质疑 / 询问 capability → 合法 surface 触发 (a).

    Returns: True = Sir 在召唤老话题, 主脑应该看 [PENDING CLAIM REVISIONS] 主动 surface.
    """
    if not sir_utterance:
        return False
    text = sir_utterance.strip()
    if not text:
        return False
    for pat in _SIR_QUERY_PATTERNS:
        if pat.search(text):
            return True
    return False


def extract_keywords_from_sir(sir_utterance: str, max_n: int = 5) -> List[str]:
    """提取 Sir current utterance 关键词 (供 store.get_pending 匹配 capability)."""
    if not sir_utterance:
        return []
    # 简单 tokenize: 4+ char alnum 词 / 中文 2+ char
    text = sir_utterance.lower()
    words = re.findall(r'[a-z]{4,}|[\u4e00-\u9fff]{2,}', text)
    # de-dup, 保序
    seen = set()
    out = []
    for w in words:
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= max_n:
            break
    return out


# ============================================================
# Prompt block render (central_nerve 调)
# ============================================================

def render_pending_revisions_block(
    sir_utterance: str = '',
    within_days: float = 7.0,
    max_show: int = 3,
) -> str:
    """供 _assemble_prompt 调:
    若 Sir current utterance 含质疑 / 询问 capability → 显 PENDING CLAIM REVISIONS block
    教主脑用法 — 主动 surface 修正不带 ritual self-flagellation.

    Returns: 空字符串 (无相关 pending) 或 prompt block 文本.
    """
    if not sir_utterance:
        return ''

    sir_invited = detect_sir_querying_capability(sir_utterance)
    keywords = extract_keywords_from_sir(sir_utterance, max_n=8)

    if not (sir_invited or keywords):
        return ''

    try:
        store = get_default_store()
        # 只在 Sir 召唤 OR keywords 匹配时显示 (不主动 surface)
        match_kws = keywords if keywords else None
        # 若 Sir 显式质疑句式, 放宽 match (即使 keyword 不重) — 让主脑看到所有 pending
        if sir_invited:
            match_kws = None
        items = store.get_pending(
            within_days=within_days,
            related_to_keywords=match_kws,
            limit=max_show,
        )
        if not items:
            return ''
        lines = [
            '[PENDING CLAIM REVISIONS — 待你主动 surface (Sir 召唤了相关话题)]',
            '  你之前曾想 backtrack 这些 over-claim, 当时被 redirect (没在那 turn 说).',
            '  现在 Sir current turn 召唤了相关话题 → **机会到了**, 你可以主动 surface 修正:',
            '',
        ]
        for rev in items:
            age_h = max(0, int((time.time() - rev.captured_at) / 3600))
            lines.append(
                f"  - [{rev.capability_keyword}] (id={rev.id[:8]}, captured {age_h}h ago)"
            )
            if rev.original_claim_excerpt:
                lines.append(
                    f"      你曾说: \"{rev.original_claim_excerpt[:120]}\""
                )
            if rev.admitted_lacking_reason:
                lines.append(
                    f"      真相: {rev.admitted_lacking_reason[:160]}"
                )
        lines.append('')
        lines.append(
            '  **如何 surface 得有意义** (Sir 11:30 真理 "道歉要有意义"):'
        )
        lines.append(
            '    ✅ 自然 inline: "...其实我之前说能 X, 但实际 capability 边界在 Y. 想替你 ack 一下."'
        )
        lines.append(
            '    ❌ 不要 ritual: "I must apologize..." / "Regarding my previous claim..." (空 self-flagellation)'
        )
        lines.append(
            '    ✅ 后跟 actionable: "...你要不要让我换个 X 通道试试?" (修正 → 替代方案)'
        )
        lines.append(
            '    ❌ 不要 stack 多个老账 (一次最多 1-2 条, 别一口气倒陈年旧账)'
        )
        return '\n'.join(lines)
    except Exception:
        return ''


# ============================================================
# Stats / health
# ============================================================

def get_stats() -> dict:
    """Sir CLI / dashboard 用."""
    try:
        store = get_default_store()
        items = store.all_items(include_archived=True)
        n_pending = sum(1 for r in items if r.status == STATUS_PENDING)
        n_surfaced = sum(1 for r in items if r.status == STATUS_SURFACED)
        n_archived = sum(1 for r in items if r.status == STATUS_ARCHIVED)
        n_rejected = sum(1 for r in items if r.rejected_by_sir)
        return {
            'total': len(items),
            'pending': n_pending,
            'surfaced': n_surfaced,
            'archived': n_archived,
            'rejected_by_sir': n_rejected,
            'oldest_pending_iso': (
                min((r.captured_iso for r in items if r.status == STATUS_PENDING),
                    default='')
            ),
        }
    except Exception:
        return {}
