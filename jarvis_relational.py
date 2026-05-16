# -*- coding: utf-8 -*-
"""[P0+20-β.2.2 / 2026-05-16] Jarvis Relational State — 灵魂工程 Layer 2

详 docs/JARVIS_SOUL_DRIVE.md §2.2 + §3.3。

核心：Jarvis 和 Sir "之间"的持续状态。Layer 0 是"我是谁"，Layer 1 是"我关心什么"，
Layer 2 是"我们之间"——笑点、默契、未竟之事。这是关系成为"老友"而不是"客户/服务"
的关键。

三类数据（按场景独立但同一个 store 持久化）：

1. InsideJoke — 我们的笑点
   - 例：Sir 反讽 "overly meddlesome" → Jarvis 用 "becoming... overbearing" 省略号自嘲
   - phrase: 笑点本身（短语 / 1 句话）
   - birth_context: 诞生时的情境（让 Jarvis 知道何时引用合适）
   - tone: wry / self-deprecating / playful / mock-formal …
   - last_used + use_count: 用于注入 prompt 时反 spam（最近用过的不重复）

2. UnspokenProtocol — 我们的默契
   - 例："Sir 反驳后我不再坚持"
   - rule: 一句话规则
   - learned_from: turn_id（哪一轮学到的）
   - violations: 我违反这个 protocol 的记录（让 LLM 自我纠正）

3. UnfinishedBusiness — 未竟之事
   - 例："驾照科一周三复习暂停"
   - topic: 短描述
   - last_touched: 上次碰到这件事的 ts
   - next_touch_due: 应该再 follow up 的 ts（none = 自然提及）
   - status: open / paused / done

注入路径：core_persona 之后（在 Layer 0/1 之后），影响所有 prompt branch。
不主动 nudge —— 让 LLM 在自然对话里"想起来"使用。

持久化：memory_pool/relational_state.json（单文件三类合一）
线程安全：所有写操作走 self._lock
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, List, Optional


# ============================================================
# 状态常量
# ============================================================
STATE_ACTIVE = 'active'
STATE_ARCHIVED = 'archived'

# UnfinishedBusiness 状态
UB_OPEN = 'open'
UB_PAUSED = 'paused'
UB_DONE = 'done'

# 默认参数
DEFAULT_TTL_DAYS = 90              # inside jokes / protocols 90d 没用过 → archived
DEFAULT_UB_TTL_DAYS = 60           # unfinished_business 60d 没动 → archived
PROMPT_BLOCK_DEFAULT_MAX = 700     # 注入 prompt 的 Layer 2 块上限
INSIDE_JOKES_RECENT_COOLDOWN_S = 1800.0  # 30min 内用过的 joke 注入时降排序


# ============================================================
# 数据结构
# ============================================================

@dataclass
class InsideJoke:
    """我们的笑点。

    设计原则：
    - phrase 最长 80 字（一个 punchline 应当短）
    - birth_context 给 LLM 看"什么时候引用合适"的依据
    - tone 是 wry / self-deprecating / playful / mock-formal 这类形容词，给 LLM 调性提示
    - use_count + last_used 让注入时按"新鲜未滥用"优先
    """
    id: str
    phrase: str
    birth_context: str = ''
    tone: str = ''
    state: str = STATE_ACTIVE

    # 时间
    created_at: float = field(default_factory=time.time)
    last_used: float = 0.0
    use_count: int = 0

    # 来源
    source: str = 'sir_added'       # sir_added / auto_detected / seeded
    source_marker: str = ''
    birth_turn_id: str = ''

    # 配置
    ttl_days: int = DEFAULT_TTL_DAYS

    def mark_used(self) -> None:
        self.last_used = time.time()
        self.use_count += 1

    def is_expired(self) -> bool:
        ref = max(self.last_used, self.created_at)
        return (time.time() - ref) > self.ttl_days * 86400

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class UnspokenProtocol:
    """我们的默契。

    例："Sir 反驳后我不再坚持自己的看法"
    设计原则：
    - rule 写成 Jarvis 视角的第一人称命令（"I should X" / "I should not Y"）
    - violations 是我违反这个 protocol 的最近 evidence（最多 5 条）
    """
    id: str
    rule: str
    state: str = STATE_ACTIVE

    # 来源
    source: str = 'sir_added'
    source_marker: str = ''
    learned_from_turn_id: str = ''
    examples: List[str] = field(default_factory=list)   # 正例

    # 违规记录
    violations: List[dict] = field(default_factory=list)

    # 时间
    created_at: float = field(default_factory=time.time)
    last_referenced: float = 0.0
    ttl_days: int = DEFAULT_TTL_DAYS

    def record_violation(self, what: str, turn_id: str = '') -> None:
        now = time.time()
        self.violations.append({
            'when': now,
            'when_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
            'what': what[:200],
            'turn_id': turn_id,
        })
        if len(self.violations) > 5:
            self.violations = self.violations[-5:]

    def is_expired(self) -> bool:
        ref = max(self.last_referenced, self.created_at)
        return (time.time() - ref) > self.ttl_days * 86400

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class UnfinishedBusiness:
    """未竟之事。

    例："驾照科一周三复习暂停"
    设计原则：
    - topic 短描述 (≤ 80 字)
    - next_touch_due > 0 时表示有明确 follow-up 时间，达到时 Jarvis 应当主动提
    - last_touched 是上次任何形式碰到（不必正面 follow up）
    """
    id: str
    topic: str
    state: str = UB_OPEN              # open / paused / done
    detail: str = ''

    # 来源
    source: str = 'sir_added'
    source_marker: str = ''
    origin_turn_id: str = ''

    # 时间
    created_at: float = field(default_factory=time.time)
    last_touched: float = field(default_factory=time.time)
    next_touch_due: float = 0.0       # 0 = 没有截止，自然提及
    ttl_days: int = DEFAULT_UB_TTL_DAYS

    def touch(self) -> None:
        self.last_touched = time.time()

    def is_overdue(self) -> bool:
        return self.next_touch_due > 0 and time.time() > self.next_touch_due

    def is_expired(self) -> bool:
        return self.state != UB_OPEN and (time.time() - self.last_touched) > self.ttl_days * 86400

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# Store
# ============================================================

class RelationalStateStore:
    """Layer 2 总聚合存储 + 持久化 + prompt 注入。线程安全。

    单 JSON 文件持久化所有三类：
        {
          "inside_jokes": {id: {...}, ...},
          "unspoken_protocols": {id: {...}, ...},
          "unfinished_business": {id: {...}, ...},
        }
    """

    DEFAULT_PERSIST_PATH = os.path.join('memory_pool', 'relational_state.json')

    def __init__(self, persist_path: Optional[str] = None):
        self.persist_path = persist_path or self.DEFAULT_PERSIST_PATH
        self.inside_jokes: dict[str, InsideJoke] = {}
        self.unspoken_protocols: dict[str, UnspokenProtocol] = {}
        self.unfinished_business: dict[str, UnfinishedBusiness] = {}
        self._lock = threading.Lock()
        self._dirty = False

    # ---------------------------------------------------------
    # Inside Jokes
    # ---------------------------------------------------------

    def add_inside_joke(self, joke: InsideJoke) -> bool:
        with self._lock:
            if joke.id in self.inside_jokes:
                return False
            self.inside_jokes[joke.id] = joke
            self._dirty = True
            return True

    def get_inside_joke(self, jid: str) -> Optional[InsideJoke]:
        return self.inside_jokes.get(jid)

    def list_inside_jokes(self, include_archived: bool = False) -> List[InsideJoke]:
        out = []
        for j in self.inside_jokes.values():
            if not include_archived and j.state != STATE_ACTIVE:
                continue
            out.append(j)
        return out

    def mark_inside_joke_used(self, jid: str) -> bool:
        with self._lock:
            j = self.inside_jokes.get(jid)
            if j is None:
                return False
            j.mark_used()
            self._dirty = True
            return True

    def archive_inside_joke(self, jid: str) -> bool:
        with self._lock:
            j = self.inside_jokes.get(jid)
            if j is None:
                return False
            j.state = STATE_ARCHIVED
            self._dirty = True
            return True

    # ---------------------------------------------------------
    # Unspoken Protocols
    # ---------------------------------------------------------

    def add_protocol(self, protocol: UnspokenProtocol) -> bool:
        with self._lock:
            if protocol.id in self.unspoken_protocols:
                return False
            self.unspoken_protocols[protocol.id] = protocol
            self._dirty = True
            return True

    def get_protocol(self, pid: str) -> Optional[UnspokenProtocol]:
        return self.unspoken_protocols.get(pid)

    def list_protocols(self, include_archived: bool = False) -> List[UnspokenProtocol]:
        out = []
        for p in self.unspoken_protocols.values():
            if not include_archived and p.state != STATE_ACTIVE:
                continue
            out.append(p)
        return out

    def record_protocol_violation(self, pid: str, what: str, turn_id: str = '') -> bool:
        with self._lock:
            p = self.unspoken_protocols.get(pid)
            if p is None:
                return False
            p.record_violation(what, turn_id)
            self._dirty = True
            return True

    def archive_protocol(self, pid: str) -> bool:
        with self._lock:
            p = self.unspoken_protocols.get(pid)
            if p is None:
                return False
            p.state = STATE_ARCHIVED
            self._dirty = True
            return True

    # ---------------------------------------------------------
    # Unfinished Business
    # ---------------------------------------------------------

    def add_unfinished(self, ub: UnfinishedBusiness) -> bool:
        with self._lock:
            if ub.id in self.unfinished_business:
                return False
            self.unfinished_business[ub.id] = ub
            self._dirty = True
            return True

    def get_unfinished(self, uid: str) -> Optional[UnfinishedBusiness]:
        return self.unfinished_business.get(uid)

    def list_unfinished(self, include_done: bool = False) -> List[UnfinishedBusiness]:
        out = []
        for u in self.unfinished_business.values():
            if not include_done and u.state == UB_DONE:
                continue
            out.append(u)
        return out

    def touch_unfinished(self, uid: str) -> bool:
        with self._lock:
            u = self.unfinished_business.get(uid)
            if u is None:
                return False
            u.touch()
            self._dirty = True
            return True

    def mark_unfinished_done(self, uid: str) -> bool:
        with self._lock:
            u = self.unfinished_business.get(uid)
            if u is None:
                return False
            u.state = UB_DONE
            u.touch()
            self._dirty = True
            return True

    def pause_unfinished(self, uid: str) -> bool:
        with self._lock:
            u = self.unfinished_business.get(uid)
            if u is None:
                return False
            u.state = UB_PAUSED
            self._dirty = True
            return True

    def resume_unfinished(self, uid: str) -> bool:
        with self._lock:
            u = self.unfinished_business.get(uid)
            if u is None:
                return False
            u.state = UB_OPEN
            u.touch()
            self._dirty = True
            return True

    # ---------------------------------------------------------
    # Decay / Cleanup
    # ---------------------------------------------------------

    def apply_decay(self) -> dict:
        """过期项 → archived/done。返回统计。"""
        stats = {'jokes_archived': 0, 'protocols_archived': 0, 'ub_archived': 0}
        with self._lock:
            for j in self.inside_jokes.values():
                if j.state == STATE_ACTIVE and j.is_expired():
                    j.state = STATE_ARCHIVED
                    stats['jokes_archived'] += 1
                    self._dirty = True
            for p in self.unspoken_protocols.values():
                if p.state == STATE_ACTIVE and p.is_expired():
                    p.state = STATE_ARCHIVED
                    stats['protocols_archived'] += 1
                    self._dirty = True
            for u in self.unfinished_business.values():
                if u.state != UB_OPEN and u.is_expired():
                    u.state = UB_DONE
                    stats['ub_archived'] += 1
                    self._dirty = True
        return stats

    # ---------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------

    def persist(self) -> bool:
        with self._lock:
            if not self._dirty:
                return False
            snapshot = {
                'inside_jokes': {jid: j.to_dict() for jid, j in self.inside_jokes.items()},
                'unspoken_protocols': {
                    pid: p.to_dict() for pid, p in self.unspoken_protocols.items()
                },
                'unfinished_business': {
                    uid: u.to_dict() for uid, u in self.unfinished_business.items()
                },
                '_meta': {
                    'persisted_at': time.time(),
                    'persisted_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
                    'schema_version': 1,
                },
            }
            self._dirty = False
        try:
            os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
            tmp = self.persist_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.persist_path)
            return True
        except Exception:
            return False

    def load(self) -> dict:
        """从 disk 恢复。返回 {'jokes': N, 'protocols': N, 'ub': N}。"""
        result = {'jokes': 0, 'protocols': 0, 'ub': 0}
        if not os.path.exists(self.persist_path):
            return result
        try:
            with open(self.persist_path, 'r', encoding='utf-8') as f:
                snapshot = json.load(f) or {}
        except Exception:
            return result

        with self._lock:
            for jid, d in (snapshot.get('inside_jokes') or {}).items():
                try:
                    j = InsideJoke(
                        id=d.get('id', jid),
                        phrase=d.get('phrase', '')[:120],
                        birth_context=d.get('birth_context', '')[:400],
                        tone=d.get('tone', '')[:60],
                        state=d.get('state', STATE_ACTIVE),
                        created_at=float(d.get('created_at', time.time())),
                        last_used=float(d.get('last_used', 0.0)),
                        use_count=int(d.get('use_count', 0)),
                        source=d.get('source', 'sir_added'),
                        source_marker=d.get('source_marker', ''),
                        birth_turn_id=d.get('birth_turn_id', ''),
                        ttl_days=int(d.get('ttl_days', DEFAULT_TTL_DAYS)),
                    )
                    self.inside_jokes[j.id] = j
                    result['jokes'] += 1
                except Exception:
                    continue

            for pid, d in (snapshot.get('unspoken_protocols') or {}).items():
                try:
                    p = UnspokenProtocol(
                        id=d.get('id', pid),
                        rule=d.get('rule', '')[:300],
                        state=d.get('state', STATE_ACTIVE),
                        source=d.get('source', 'sir_added'),
                        source_marker=d.get('source_marker', ''),
                        learned_from_turn_id=d.get('learned_from_turn_id', ''),
                        examples=list(d.get('examples') or []),
                        violations=list(d.get('violations') or []),
                        created_at=float(d.get('created_at', time.time())),
                        last_referenced=float(d.get('last_referenced', 0.0)),
                        ttl_days=int(d.get('ttl_days', DEFAULT_TTL_DAYS)),
                    )
                    self.unspoken_protocols[p.id] = p
                    result['protocols'] += 1
                except Exception:
                    continue

            for uid, d in (snapshot.get('unfinished_business') or {}).items():
                try:
                    u = UnfinishedBusiness(
                        id=d.get('id', uid),
                        topic=d.get('topic', '')[:120],
                        state=d.get('state', UB_OPEN),
                        detail=d.get('detail', '')[:300],
                        source=d.get('source', 'sir_added'),
                        source_marker=d.get('source_marker', ''),
                        origin_turn_id=d.get('origin_turn_id', ''),
                        created_at=float(d.get('created_at', time.time())),
                        last_touched=float(d.get('last_touched', time.time())),
                        next_touch_due=float(d.get('next_touch_due', 0.0)),
                        ttl_days=int(d.get('ttl_days', DEFAULT_UB_TTL_DAYS)),
                    )
                    self.unfinished_business[u.id] = u
                    result['ub'] += 1
                except Exception:
                    continue

        return result

    # ---------------------------------------------------------
    # Prompt 注入
    # ---------------------------------------------------------

    def _rank_inside_jokes(self, top_n: int) -> List[InsideJoke]:
        """按"未滥用 + 新鲜"排序，结果中靠前的最优先注入 prompt。

        排序规则（tuple ascending，越小越靠前）：
        1. 最近 30min 用过的 → 排后（避免立刻重复使用）
        2. use_count 小的 → 排前（少用的优先）
        3. created_at 大的（新生）→ 排前
        """
        active = [j for j in self.inside_jokes.values() if j.state == STATE_ACTIVE]
        now = time.time()

        def _score(j: InsideJoke):
            in_cooldown = (
                j.last_used > 0
                and (now - j.last_used) < INSIDE_JOKES_RECENT_COOLDOWN_S
            )
            return (
                1 if in_cooldown else 0,
                j.use_count,
                -max(j.last_used, j.created_at),
            )

        active.sort(key=_score)
        return active[:top_n]

    def _rank_unfinished(self, top_n: int) -> List[UnfinishedBusiness]:
        """优先 overdue → 然后按 last_touched 最久没碰排前。"""
        opens = [u for u in self.unfinished_business.values() if u.state == UB_OPEN]
        now = time.time()

        def _score(u: UnfinishedBusiness) -> float:
            overdue_bonus = -1e9 if u.is_overdue() else 0.0
            return overdue_bonus + u.last_touched

        opens.sort(key=_score)
        return opens[:top_n]

    def to_prompt_block(self, top_jokes: int = 3, top_unfinished: int = 2,
                        max_chars: int = PROMPT_BLOCK_DEFAULT_MAX) -> str:
        """构造注入 prompt 的 [BETWEEN US] 块。

        结构（参考 Layer 0/1 风格）：

        === BETWEEN US — OUR RELATIONAL CONTEXT ===
        [OUR INSIDE JOKES]
          - phrase | tone | birth: ...
          - phrase | tone | birth: ...
        [OUR UNSPOKEN PROTOCOLS]
          - rule (refed N times)
        [UNFINISHED BUSINESS WE BOTH KNOW]
          - topic — last touched <human time> ago
        """
        jokes = self._rank_inside_jokes(top_jokes)
        protocols = self.list_protocols()
        unfinished = self._rank_unfinished(top_unfinished)

        if not jokes and not protocols and not unfinished:
            return ''

        lines: List[str] = ["=== BETWEEN US — OUR RELATIONAL CONTEXT ==="]

        if jokes:
            lines.append("[OUR INSIDE JOKES — references between you and me]")
            for j in jokes:
                seg = f"  - \"{j.phrase[:80]}\""
                meta = []
                if j.tone:
                    meta.append(f"tone: {j.tone[:30]}")
                if j.birth_context:
                    meta.append(f"born when: {j.birth_context[:80]}")
                if meta:
                    seg += f" | {' | '.join(meta)}"
                lines.append(seg[:200])
            lines.append("  (use sparingly — referencing too often kills the spark)")

        if protocols:
            lines.append("[OUR UNSPOKEN PROTOCOLS — how we operate]")
            for p in protocols[:3]:
                refed = ''
                if p.last_referenced > 0:
                    refed = f" (last honored: {time.strftime('%m-%d %H:%M', time.localtime(p.last_referenced))})"
                lines.append(f"  - {p.rule[:140]}{refed}"[:200])

        if unfinished:
            lines.append("[UNFINISHED BUSINESS — things we both know aren't done]")
            now = time.time()
            for u in unfinished:
                age_days = (now - u.last_touched) / 86400
                if age_days < 1:
                    age_str = f"{int((now - u.last_touched) / 3600)}h ago"
                else:
                    age_str = f"{int(age_days)}d ago"
                overdue_tag = " [OVERDUE]" if u.is_overdue() else ""
                lines.append(f"  - {u.topic[:80]} — last touched {age_str}{overdue_tag}"[:200])

        out = "\n".join(lines)
        if len(out) > max_chars:
            _suffix = "\n…[truncated]"
            out = out[:max_chars - len(_suffix)].rstrip() + _suffix
        return out

    # ---------------------------------------------------------
    # 人类可读 dump
    # ---------------------------------------------------------

    def dump_human(self, show_archived: bool = False) -> str:
        """ASCII 表给 Sir 看。"""
        jokes = self.list_inside_jokes(include_archived=show_archived)
        protos = self.list_protocols(include_archived=show_archived)
        ubs = self.list_unfinished(include_done=show_archived)

        lines = []
        lines.append("=" * 100)
        lines.append(
            f"[RelationalState] jokes={len(jokes)} protocols={len(protos)} "
            f"unfinished={len(ubs)} (path={self.persist_path})"
        )
        lines.append("=" * 100)

        # Inside Jokes
        lines.append("")
        lines.append("[INSIDE JOKES]")
        if jokes:
            lines.append(f"  {'id':28}{'use':>5} {'tone':<22}phrase")
            lines.append("  " + "-" * 96)
            for j in sorted(jokes, key=lambda x: -x.created_at):
                lines.append(
                    f"  {j.id:28}{j.use_count:>5} {(j.tone or '-')[:20]:<22}"
                    f"\"{j.phrase[:46]}\""
                )
                if j.birth_context:
                    lines.append(f"      born: {j.birth_context[:80]}")
        else:
            lines.append("  (none)")

        # Protocols
        lines.append("")
        lines.append("[UNSPOKEN PROTOCOLS]")
        if protos:
            for p in protos:
                v = len(p.violations)
                lines.append(f"  - {p.id} (violations: {v}): {p.rule[:80]}")
        else:
            lines.append("  (none)")

        # Unfinished
        lines.append("")
        lines.append("[UNFINISHED BUSINESS]")
        if ubs:
            now = time.time()
            for u in sorted(ubs, key=lambda x: x.last_touched):
                age_days = (now - u.last_touched) / 86400
                overdue = " [OVERDUE]" if u.is_overdue() else ""
                lines.append(
                    f"  - {u.id} [{u.state}] — {u.topic[:60]} "
                    f"(last touched {age_days:.1f}d ago){overdue}"
                )
        else:
            lines.append("  (none)")

        lines.append("=" * 100)
        return "\n".join(lines)


# ============================================================
# 单例
# ============================================================

_DEFAULT_STORE: Optional[RelationalStateStore] = None


def get_default_store() -> RelationalStateStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = RelationalStateStore()
        _DEFAULT_STORE.load()
    return _DEFAULT_STORE


def reset_default_store_for_test() -> None:
    global _DEFAULT_STORE
    _DEFAULT_STORE = None


# ============================================================
# ID 生成辅助
# ============================================================

def make_joke_id(phrase: str) -> str:
    """从 phrase 生成短可读 id：joke_<slug>_<6hex>。"""
    import hashlib
    import re as _re
    slug = _re.sub(r'[^a-z0-9]+', '_', phrase.lower())[:24].strip('_') or 'joke'
    h = hashlib.md5(phrase.encode('utf-8', errors='ignore')).hexdigest()[:6]
    return f"joke_{slug}_{h}"


def make_protocol_id(rule: str) -> str:
    """从 rule 生成短可读 id：proto_<slug>_<6hex>。"""
    import hashlib
    import re as _re
    slug = _re.sub(r'[^a-z0-9]+', '_', rule.lower())[:24].strip('_') or 'rule'
    h = hashlib.md5(rule.encode('utf-8', errors='ignore')).hexdigest()[:6]
    return f"proto_{slug}_{h}"


def make_ub_id(topic: str) -> str:
    """从 topic 生成短可读 id：ub_<slug>_<6hex>。"""
    import hashlib
    import re as _re
    slug = _re.sub(r'[^a-z0-9]+', '_', topic.lower())[:24].strip('_') or 'topic'
    h = hashlib.md5(topic.encode('utf-8', errors='ignore')).hexdigest()[:6]
    return f"ub_{slug}_{h}"
