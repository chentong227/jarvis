# -*- coding: utf-8 -*-
"""[P0+20-β.0.1 / 2026-05-16] Jarvis Directives — L2 Conditional Directives Registry

Prompt 重构四层架构中的 L2 层（详 docs/PROMPT_REFACTOR_PLAN.md §3-§7）：

- L0 Immutable Core: butler 身份 + INTEGRITY 铁则 (jarvis_central_nerve.JARVIS_CORE_PERSONA)
- L1 Session Context: STM / profile / time / attention / working_feed / event_bus 等
- **L2 Conditional Directives (本文件)**: 按 trigger 注入 + 行为信号采集 + 自动衰减
- L3 Task Frame: user_input + clock + system_alert + commitment

设计原则（详 PROMPT_REFACTOR_PLAN §2）：
1. 分层：把 25+ 个旧 block 重组成 4 层，每层有清晰边界
2. 按需：L2 directive 全部走 trigger 函数，不再无脑全注入
3. 可衰减：每条 directive 带 last_triggered + ttl_days + 学习信号，30 天没用就 dormant
4. 可观察：每次装配 bg_log 注入了哪些 L2 directive

信号采集（三层，详 PROMPT_REFACTOR_PLAN §4 + §7）：
- fired: trigger 命中次数（纯计数，100% 准）
- rejected: 命中后下一轮 Sir 用 correction_loop 6 条正则表达不满（~85%）
- helped: post-turn Gemini-3-flash 异步评分 yes/no/partial（β.0.5 接入；~95%）

持久化：memory_pool/directive_registry.json
- 仅存运行时计数（fired/rejected/helped/last_triggered/state 等）
- 不存 text / trigger（lambda 不可序列化，且代码定义）
- 每 60s 由 DirectiveDecayWorker 自动落盘

线程安全：所有写操作走 self._lock
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, List, Optional


# ============================================================
# 数据结构
# ============================================================

@dataclass
class DirectiveContext:
    """trigger 函数能拿到的所有上下文。CentralNerve._assemble_prompt 装配前构造。
    
    字段约定：
    - user_input: 本轮 Sir 说的话（已 ASR 后 + correction 后）
    - last_jarvis_reply: 上一轮 Jarvis 的回复（用于检测 future-tense / completion claim 等模式）
    - stm: short-term memory 列表 [{'user': '...', 'jarvis': '...'}, ...]
    - tier: 'WAKE_ONLY' / 'SHORT_CHAT' / 'FACTUAL_RECALL' / 'TOOL_REQUEST' / 'DEEP_QUERY' / 'CRITICAL'
    - ledger_data: status_ledger 当前状态 dict（情绪 / 工作时长等）
    - soul_tags: 灵魂归档 tag 列表 ['projects', 'jokes', ...]
    - current_hour: 当前小时（用于时段相关 directive）
    - has_active_plan: PlanLedger 是否有 awaiting_go / paused / running plan
    - has_screenshot: 本轮装配是否启用 screenshot（vision tier）
    - working_feed_nonempty: WorkingMemoryFeed 是否有近期事件
    """
    user_input: str = ""
    last_jarvis_reply: str = ""
    stm: List[dict] = field(default_factory=list)
    tier: str = "DEEP_QUERY"
    ledger_data: Optional[dict] = None
    soul_tags: List[str] = field(default_factory=list)
    current_hour: int = 12
    has_active_plan: bool = False
    has_screenshot: bool = False
    working_feed_nonempty: bool = False
    last_tool_results: List[str] = field(default_factory=list)  # 上轮 FAST_CALL 结果列表（含 '✅' / '❌'）


# 状态枚举
STATE_ACTIVE = "active"           # 参与装配
STATE_DORMANT = "dormant"         # 长期无 fired，自动休眠（30d+）
STATE_REVIEW = "review"           # rejected 达阈值，等 Sir review 改文案
STATE_ARCHIVED = "archived"       # Sir review 后决定永久关闭

# 衰减规则（详 PROMPT_REFACTOR_PLAN §6）
DECAY_TTL_DAYS_DEFAULT = 30
REVIEW_REJECTED_THRESHOLD = 3
REJ_RATE_PRIORITY_DROP = 0.3
MIN_FIRED_FOR_PRIORITY_DROP = 5

# 运行时持久化字段（不存 trigger/text，避免 lambda 序列化）
_PERSISTABLE_FIELDS = (
    'fired', 'rejected', 'helped',
    'last_triggered', 'last_rejected', 'last_helped',
    'state', 'priority',
)


@dataclass
class Directive:
    """单条 directive 的完整描述 + 运行时计数。"""

    id: str                                                  # 全局唯一 ID，e.g. 'nudge_agenda_honesty'
    text: str                                                # directive 正文（注入 L2 的字符串）
    trigger: Callable[[DirectiveContext], bool] = field(repr=False)  # trigger 函数
    priority: int = 5                                        # 1-10，多 directive 命中时按 priority 降序
    tier_whitelist: List[str] = field(default_factory=list)  # [] = 全 tier；否则只命中列表内 tier
    ttl_days: int = DECAY_TTL_DAYS_DEFAULT                   # 超过此天数无触发 → 自动 dormant
    source_marker: str = ""                                  # 来源 marker，e.g. 'P0+18-f.2'

    # ===== 运行时计数（持久化）=====
    fired: int = 0
    rejected: int = 0
    helped: int = 0                                          # β.0.5 Gemini-3-Flash 评分后填
    last_triggered: float = 0.0
    last_rejected: float = 0.0
    last_helped: float = 0.0
    state: str = STATE_ACTIVE


# ============================================================
# Registry
# ============================================================

class DirectiveRegistry:
    """L2 Directive Registry —— 注册 + 命中 + 信号采集 + 持久化 + 衰减。
    
    线程安全：所有写操作走 _lock；读取 / collect 走读锁副本，性能优先。
    """

    def __init__(self, persist_path: Optional[str] = None):
        self.directives: dict[str, Directive] = {}
        repo_root = Path(__file__).resolve().parent
        self.persist_path = persist_path or str(repo_root / "memory_pool" / "directive_registry.json")
        self.review_path = str(repo_root / "memory_pool" / "directive_review.json")
        self._lock = threading.Lock()
        self._dirty = False
        self._decay_worker: Optional[threading.Thread] = None
        self._decay_stop = threading.Event()

    # ---- 注册 / 解注册 ----

    def register(self, directive: Directive) -> None:
        if not directive.id:
            raise ValueError("Directive.id is required")
        if not callable(directive.trigger):
            raise ValueError(f"Directive {directive.id}: trigger must be callable")
        with self._lock:
            if directive.id in self.directives:
                raise ValueError(f"Directive id already registered: {directive.id}")
            self.directives[directive.id] = directive
            self._dirty = True

    def unregister(self, did: str) -> bool:
        with self._lock:
            if did in self.directives:
                del self.directives[did]
                self._dirty = True
                return True
            return False

    def get(self, did: str) -> Optional[Directive]:
        with self._lock:
            return self.directives.get(did)

    # ---- 命中 ----

    def _safe_trigger(self, d: Directive, ctx: DirectiveContext) -> bool:
        """跑 trigger，异常静默吞掉返回 False，避免单条挂掉破坏装配。"""
        try:
            return bool(d.trigger(ctx))
        except Exception:
            return False

    def collect(self, ctx: DirectiveContext) -> List[Directive]:
        """按 trigger 命中 + tier_whitelist 过滤 + priority 排序，返回当轮要注入的 directives。
        
        线程安全：拷贝 directive 列表后释放锁，trigger 函数执行不持锁（避免 trigger 自己卡住把锁占住）。
        """
        with self._lock:
            candidates = [d for d in self.directives.values() if d.state == STATE_ACTIVE]
        fired: List[Directive] = []
        for d in candidates:
            if d.tier_whitelist and ctx.tier not in d.tier_whitelist:
                continue
            if self._safe_trigger(d, ctx):
                fired.append(d)
        fired.sort(key=lambda d: -d.priority)
        return fired

    # ---- 信号采集 ----

    def record_fire(self, ids: List[str]) -> None:
        """trigger 命中后由 CentralNerve 调一次，更新 fired + last_triggered。"""
        if not ids:
            return
        now = time.time()
        with self._lock:
            for did in ids:
                d = self.directives.get(did)
                if d is not None:
                    d.fired += 1
                    d.last_triggered = now
            self._dirty = True

    def record_rejection(self, ids: List[str]) -> None:
        """Sir 表达不满（correction_loop 6 条正则命中）后调，rejected++。"""
        if not ids:
            return
        now = time.time()
        with self._lock:
            for did in ids:
                d = self.directives.get(did)
                if d is not None:
                    d.rejected += 1
                    d.last_rejected = now
            self._dirty = True

    def record_helped(self, did: str, helped: bool) -> None:
        """β.0.5 Gemini-3-Flash 异步评分回写：True→helped++（partial 也算 True）。"""
        with self._lock:
            d = self.directives.get(did)
            if d is None:
                return
            if helped:
                d.helped += 1
                d.last_helped = time.time()
            self._dirty = True

    # ---- 衰减 ----

    def apply_decay(self) -> dict:
        """[每 60s 由 daemon 调] 应用衰减规则。
        
        规则（详 PROMPT_REFACTOR_PLAN §6）：
        1. last_triggered 距今 > ttl_days*86400 → state=dormant
        2. rejected >= 3 → state=review（并写 review JSON 队列）
        3. rejected/fired > 0.3 AND fired >= 5 → priority -=2（不低于 1）
        
        返回统计 dict：{'dormant': N, 'review': N, 'priority_drop': N}
        """
        stats = {'dormant': 0, 'review': 0, 'priority_drop': 0}
        now = time.time()
        review_entries: list = []
        with self._lock:
            for d in self.directives.values():
                if d.state != STATE_ACTIVE:
                    continue
                # 规则 1：长期无触发 → dormant
                if d.last_triggered > 0 and (now - d.last_triggered) > d.ttl_days * 86400:
                    d.state = STATE_DORMANT
                    stats['dormant'] += 1
                    self._dirty = True
                    continue
                # 规则 2：rejected 累积 → review
                if d.rejected >= REVIEW_REJECTED_THRESHOLD:
                    d.state = STATE_REVIEW
                    stats['review'] += 1
                    self._dirty = True
                    review_entries.append({
                        'id': d.id,
                        'source_marker': d.source_marker,
                        'fired': d.fired,
                        'rejected': d.rejected,
                        'rej_rate': round(d.rejected / max(d.fired, 1), 3),
                        'last_rejected_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(d.last_rejected)),
                        'text_preview': d.text[:200],
                    })
                    continue
                # 规则 3：rej_rate 过高 → priority -= 2
                if d.fired >= MIN_FIRED_FOR_PRIORITY_DROP:
                    rej_rate = d.rejected / d.fired
                    if rej_rate > REJ_RATE_PRIORITY_DROP and d.priority > 1:
                        d.priority = max(1, d.priority - 2)
                        stats['priority_drop'] += 1
                        self._dirty = True
        if review_entries:
            try:
                self._append_review_queue(review_entries)
            except Exception:
                pass
        return stats

    def _append_review_queue(self, entries: list) -> None:
        """把 review 队列追加到 memory_pool/directive_review.json（list 形式）。"""
        os.makedirs(os.path.dirname(self.review_path), exist_ok=True)
        existing: list = []
        if os.path.exists(self.review_path):
            try:
                with open(self.review_path, 'r', encoding='utf-8') as f:
                    existing = json.load(f) or []
            except Exception:
                existing = []
        ts = time.strftime('%Y-%m-%dT%H:%M:%S')
        for e in entries:
            e['enqueued_at'] = ts
            existing.append(e)
        with open(self.review_path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

    # ---- 持久化 ----

    def persist(self) -> bool:
        """写运行时计数到 JSON。线程安全，无变更直接返回 False。"""
        with self._lock:
            if not self._dirty:
                return False
            snapshot = {}
            for did, d in self.directives.items():
                snapshot[did] = {f: getattr(d, f) for f in _PERSISTABLE_FIELDS}
            self._dirty = False
        try:
            os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
            tmp_path = self.persist_path + ".tmp"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.persist_path)
            return True
        except Exception:
            return False

    def load(self) -> int:
        """从 JSON 恢复运行时计数。返回成功恢复的 directive 数。"""
        if not os.path.exists(self.persist_path):
            return 0
        try:
            with open(self.persist_path, 'r', encoding='utf-8') as f:
                snapshot = json.load(f) or {}
        except Exception:
            return 0
        n = 0
        with self._lock:
            for did, data in snapshot.items():
                d = self.directives.get(did)
                if d is None:
                    continue  # bootstrap 没注册过这条，跳过（可能 directive 已删）
                for k in _PERSISTABLE_FIELDS:
                    if k in data:
                        setattr(d, k, data[k])
                n += 1
        return n

    # ---- decay daemon ----

    def start_decay_worker(self, interval_s: float = 60.0) -> None:
        """启动后台 daemon：每 interval_s tick 一次 apply_decay + persist。"""
        if self._decay_worker is not None and self._decay_worker.is_alive():
            return
        self._decay_stop.clear()

        def _loop():
            try:
                from jarvis_utils import bg_log
                bg_log(f"♻️ [DirectiveDecayWorker] 启动 (tick={interval_s}s)")
            except Exception:
                pass
            while not self._decay_stop.is_set():
                try:
                    stats = self.apply_decay()
                    if any(v > 0 for v in stats.values()):
                        try:
                            from jarvis_utils import bg_log
                            bg_log(f"♻️ [DirectiveDecayWorker] decay: dormant={stats['dormant']} review={stats['review']} priority_drop={stats['priority_drop']}")
                        except Exception:
                            pass
                    self.persist()
                except Exception:
                    pass
                self._decay_stop.wait(interval_s)

        self._decay_worker = threading.Thread(target=_loop, daemon=True, name='DirectiveDecayWorker')
        self._decay_worker.start()

    def stop_decay_worker(self) -> None:
        self._decay_stop.set()

    # ---- 人类可读 dump ----

    def dump_human(self, days_window: int = 7) -> str:
        """返回 ASCII 表，给 Sir 看 directive 健康度。"""
        now = time.time()
        rows = []
        with self._lock:
            for d in self.directives.values():
                rej_rate = d.rejected / max(d.fired, 1)
                age_days = int((now - d.last_triggered) / 86400) if d.last_triggered > 0 else -1
                rows.append({
                    'id': d.id,
                    'fired': d.fired,
                    'rejected': d.rejected,
                    'helped': d.helped,
                    'rej_rate': f"{rej_rate*100:.0f}%" if d.fired else "-",
                    'state': d.state,
                    'priority': d.priority,
                    'age_d': age_days if age_days >= 0 else "n/a",
                    'marker': d.source_marker or '-',
                })
        rows.sort(key=lambda r: (r['state'] != STATE_ACTIVE, -r['fired']))

        lines = [
            f"[DirectiveRegistry] {len(rows)} directives | snapshot @ {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "─" * 100,
            f"{'id':<28} {'fired':>6} {'rej':>4} {'helped':>6} {'rej%':>5} {'state':<8} {'prio':>4} {'age_d':>6} marker",
            "─" * 100,
        ]
        for r in rows:
            lines.append(
                f"{r['id'][:28]:<28} {r['fired']:>6} {r['rejected']:>4} {r['helped']:>6} {r['rej_rate']:>5} {r['state']:<8} {r['priority']:>4} {str(r['age_d']):>6} {r['marker']}"
            )
        lines.append("─" * 100)
        return "\n".join(lines)


# ============================================================
# Trigger 辅助函数（命中条件）
# ============================================================

_CONNECTOR_PATTERNS_EN = re.compile(
    r"\b(by\s+the\s+way|and\s+also|also|btw|on\s+another\s+note|moreover|furthermore)\b",
    re.IGNORECASE,
)
_CONNECTOR_PATTERNS_ZH = re.compile(r"(对了|另外|还有|顺便|再就是|然后呢)")


def _has_multi_intent_connector(text: str) -> bool:
    if not text or len(text) < 12:
        return False
    return bool(_CONNECTOR_PATTERNS_EN.search(text) or _CONNECTOR_PATTERNS_ZH.search(text))


_COMPLETION_CLAIM_PATTERNS = re.compile(
    r"(\bi'?\s*ve\s+|\bi\s+have\s+|已为(您|你)|我已经?|已[经]?[关开调设修移删停启]|"
    r"\bsettings?\s+have\s+been\b|\bnotifications?\s+are\s+now\b|"
    r"\bI'?ll\s+silence|\bI'?ll\s+adjust)",
    re.IGNORECASE,
)
_REFUSAL_PATTERNS = re.compile(
    r"(不用再提|不要再提|别再提|可以了|enough|stop\s+(it|that|nudging|reminding)|no\s+more|cease)",
    re.IGNORECASE,
)


def _last_reply_has_completion_claim(text: str) -> bool:
    if not text:
        return False
    return bool(_COMPLETION_CLAIM_PATTERNS.search(text))


def _user_input_is_refusal(text: str) -> bool:
    if not text:
        return False
    return bool(_REFUSAL_PATTERNS.search(text))


_FUZZY_KW_PATTERNS = re.compile(
    r"(\b(?:find|search|look\s+up|locate)\b|查(找|进程|文件|一下)|找(?:一下|这个|文件|进程))",
    re.IGNORECASE,
)


def _user_input_wants_search(text: str) -> bool:
    return bool(text and _FUZZY_KW_PATTERNS.search(text))


_TIME_SENSITIVE_PATTERNS = re.compile(
    r"(news|recent|today|latest|breaking|新闻|最近|今天|现在|刚才|刚发生)",
    re.IGNORECASE,
)


def _user_input_is_time_sensitive(text: str) -> bool:
    return bool(text and _TIME_SENSITIVE_PATTERNS.search(text))


_WRITE_INTENT_PATTERNS = re.compile(
    r"(remember\s+(this|that)|记住|记一下|提醒(我|一下)|note\s+(this|that|down)|"
    r"correct(ed)?|纠正|改一下|改正|set\s+a\s+reminder|schedule)",
    re.IGNORECASE,
)


def _user_input_is_memory_write(text: str) -> bool:
    return bool(text and _WRITE_INTENT_PATTERNS.search(text))


_RECENT_REF_PATTERNS = re.compile(
    r"(just\s+now|刚才|just\s+pasted|just\s+copied|just\s+ran|我刚\s*[复粘运])",
    re.IGNORECASE,
)


def _user_input_refs_recent(text: str) -> bool:
    return bool(text and _RECENT_REF_PATTERNS.search(text))


# 🩹 [P0+20-β.1.15 / 2026-05-16] #14 directive reminder_read_truth_source 配套
_REMINDER_READ_PATTERNS = re.compile(
    r"(代办事项|待办|提醒(我)?(吗|什么)?|todo\s*list|to-?do|reminders?\b|"
    r"what\s+(is|are|'s|s)\s+on\s+my\s+(plate|list|schedule|agenda)|"
    r"what'?s\s+on\s+my\s+(plate|list|schedule|agenda)|"
    r"我.{0,4}(有|要做)什么|今天.{0,4}(要做|安排|有什么)|安排.{0,4}什么|事项)",
    re.IGNORECASE,
)
# 排除：写入意图（避免和 correction_writepath_no_tool 冲突）
# 仅当"明天/今晚/X 点 + 动作动词"连用才算写入；单独 today/tomorrow 是查询时间限定词
_REMINDER_WRITE_KW = re.compile(
    r"(记住|记一下|帮我.{0,4}记|提醒我.{0,4}(在|要|去|做)|set\s+a\s+reminder|schedule\s+(a|me|something)|"
    r"明天.{0,8}(去|做|看|读|写|跑|开|关|学|练|交|发|寄|买|吃)|"
    r"今晚.{0,8}(去|做|看|读|写|跑|开|关|学|练|交|发|寄|买|吃)|"
    r"\d{1,2}\s*点.{0,8}(去|做|起床|睡觉|吃|喝|开会|出门)|"
    r"\d{1,2}:\d{2}.{0,8}(remind|wake|sleep|eat|leave|start|begin|set))",
    re.IGNORECASE,
)


def _user_input_is_reminder_read(text: str) -> bool:
    """Sir 问 '代办事项 / 提醒 / todos' 等查询，不是设置新提醒。"""
    if not text:
        return False
    if not _REMINDER_READ_PATTERNS.search(text):
        return False
    # 含写入关键词 → 走 correction_writepath_no_tool 而不是这条
    if _REMINDER_WRITE_KW.search(text):
        return False
    return True


def _trigger_reminder_read(ctx: DirectiveContext) -> bool:
    """L2 trigger wrapper：从 ctx.user_input 调 _user_input_is_reminder_read。"""
    return _user_input_is_reminder_read(ctx.user_input)


_PATH_FILE_PATTERNS = re.compile(
    r"([A-Z]:\\|/[a-zA-Z0-9]+|文件|路径|目录|folder|directory|path)",
    re.IGNORECASE,
)


def _user_input_refs_path(text: str) -> bool:
    return bool(text and _PATH_FILE_PATTERNS.search(text))


def _last_tool_results_contain_fail(results: list) -> bool:
    if not results:
        return False
    for r in results:
        if isinstance(r, str) and ('❌' in r or 'fail' in r.lower() or 'error' in r.lower()):
            return True
    return False


# ============================================================
# 12 条 Directive Bootstrap
# ============================================================

# 🩹 [P0+20-β.1.11 / 2026-05-16] future-tense capability lie pattern
# Sir 痛点：Jarvis 答 "I can take a closer look" / "I'll see what I can do" /
# "Let me look into that" 然后下一轮根本没 follow-up（没工具就别承诺）。
# α.3 注释明示"这块未修"，β.1.11 新增 directive 治本。
_FUTURE_LIE_PATTERNS_EN = re.compile(
    r"(\bi\s+can\s+(take\s+a\s+(closer|deeper|better)\s+look|investigate|"
    r"look\s+into|find\s+out|check\s+on|explore|dig\s+into|review|examine)|"
    r"\bi'?ll\s+(take\s+a\s+(closer|deeper|better)\s+look|investigate|"
    r"see\s+what\s+i\s+can|look\s+into|check\s+on|find\s+out|get\s+back\s+to\s+you|"
    r"keep\s+an?\s+eye\s+on)|"
    r"\blet\s+me\s+(look\s+into|check\s+on|investigate|see\s+what|dig\s+into))",
    re.IGNORECASE,
)
_FUTURE_LIE_PATTERNS_ZH = re.compile(
    r"(我(会|能|可以|去|要|得|来)[再去]?(深入|仔细|进一步)?(看看|查查|了解|研究|探索|追踪|关注|看一下|查一下|了解一下|研究一下)"
    r"|让我(再|去)?(深入|仔细)?(看|查|了解|研究|探索|看看|查查)(一下|看|看看|查查)?"
    r"|稍后(再|为您)?(回复|跟进|确认|看一下|查一下)"
    r"|再为(您|你)(看|查|跟进|确认|了解))"
)


def _last_reply_has_future_capability_lie(text: str) -> bool:
    if not text or len(text) < 5:
        return False
    return bool(_FUTURE_LIE_PATTERNS_EN.search(text) or _FUTURE_LIE_PATTERNS_ZH.search(text))


def _trigger_future_tense_capability_check(ctx: DirectiveContext) -> bool:
    """如果上一轮 Jarvis 给了 "I can/will look into" 这种空头承诺 → 注入"诚实兜底" directive。"""
    return _last_reply_has_future_capability_lie(ctx.last_jarvis_reply)


def _trigger_nudge_agenda_honesty(ctx: DirectiveContext) -> bool:
    return _last_reply_has_completion_claim(ctx.last_jarvis_reply) and _user_input_is_refusal(ctx.user_input)


def _trigger_continuity_two_parts(ctx: DirectiveContext) -> bool:
    return bool(ctx.stm) and _has_multi_intent_connector(ctx.user_input)


def _trigger_tool_honesty(ctx: DirectiveContext) -> bool:
    return _last_tool_results_contain_fail(ctx.last_tool_results)


def _trigger_fuzzy_candidates(ctx: DirectiveContext) -> bool:
    return _user_input_wants_search(ctx.user_input)


def _trigger_promise_protocol(ctx: DirectiveContext) -> bool:
    return bool(ctx.has_active_plan)


def _trigger_bilingual_always(_ctx: DirectiveContext) -> bool:
    return True


def _trigger_search_directive(ctx: DirectiveContext) -> bool:
    return _user_input_is_time_sensitive(ctx.user_input)


def _trigger_memory_callback(ctx: DirectiveContext) -> bool:
    # 当 STM 有 >=3 条记录（已经有交流历史可参考），LLM 容易 over-reference
    return len(ctx.stm) >= 3


def _trigger_image_context(ctx: DirectiveContext) -> bool:
    return bool(ctx.has_screenshot)


def _trigger_system_environment(ctx: DirectiveContext) -> bool:
    return _user_input_refs_path(ctx.user_input)


def _trigger_smart_routing_working_feed(ctx: DirectiveContext) -> bool:
    return bool(ctx.working_feed_nonempty) and _user_input_refs_recent(ctx.user_input)


def _trigger_correction_writepath(ctx: DirectiveContext) -> bool:
    return _user_input_is_memory_write(ctx.user_input)


# 🩹 [β.2.9.9 / 2026-05-18] Sir 10:51 诚信审计:
# Jarvis 嘴上说"I've updated my records / 我已更新" 但底层根本没动 db.
# 准则 5 (言出必行) 重大违反. 加新 directive 在 Sir 像在纠正/澄清记忆时
# 强制 Jarvis 诚实 — 没真调 MEMORY_UPDATE 工具就别说"已更新".
#
# 🩹 [P0+20-β.3.4-vocab3 / 2026-05-18] Sir 准则 6.5: vocab 迁 json + CLI.
# 范式照搬 β.3.0-vocab1 (tool_intent) — 详 commit 63611f3
_SEED_MEMORY_CORRECTION_PATTERNS = (
    # 中文 (17)
    '我没', '我不是', '我才不', '不是的', '其实', '澄清', '纠正',
    '两码事', '两个事', '搞错了', '错了', '记错', '不对',
    '我说的是', '我的意思是', '不要混淆', '不要搞混',
    # 英文 (14)
    "i'm not", "i am not", "actually", "clarify", "correction",
    "two different things", "you got it wrong", "you misunderstood",
    "to be clear", "let me clarify", "let me correct",
    "what i meant was", "i meant", "no that's not",
)

_MEMORY_CORRECTION_VOCAB_PATH = os.path.join(
    'memory_pool', 'memory_correction_vocab.json')
_MEMORY_CORRECTION_CACHE: Optional[tuple] = None
_MEMORY_CORRECTION_MTIME: float = 0.0


def _load_memory_correction_from_json() -> Optional[tuple]:
    """从 json 加载 active pattern keyword 扁平 tuple. 失败返 None."""
    if not os.path.exists(_MEMORY_CORRECTION_VOCAB_PATH):
        return None
    try:
        with open(_MEMORY_CORRECTION_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        out: List[str] = []
        for p in data.get('patterns', []):
            if not isinstance(p, dict):
                continue
            if p.get('state') != 'active':
                continue
            for kw in (p.get('keywords') or []):
                if isinstance(kw, str) and kw.strip():
                    out.append(kw.lower().strip())
        return tuple(out) if out else None
    except Exception:
        return None


def get_memory_correction_patterns() -> tuple:
    """🩹 [β.3.4-vocab3] mtime cache 自动 reload. Sir CLI 改 json → 即时生效."""
    global _MEMORY_CORRECTION_CACHE, _MEMORY_CORRECTION_MTIME
    try:
        mtime = os.path.getmtime(_MEMORY_CORRECTION_VOCAB_PATH) if os.path.exists(
            _MEMORY_CORRECTION_VOCAB_PATH) else 0
    except OSError:
        mtime = 0
    if _MEMORY_CORRECTION_CACHE is None or mtime > _MEMORY_CORRECTION_MTIME:
        loaded = _load_memory_correction_from_json()
        if loaded is not None:
            _MEMORY_CORRECTION_CACHE = loaded
        else:
            _MEMORY_CORRECTION_CACHE = _SEED_MEMORY_CORRECTION_PATTERNS
        _MEMORY_CORRECTION_MTIME = mtime
    return _MEMORY_CORRECTION_CACHE


def _trigger_memory_update_honesty(ctx: DirectiveContext) -> bool:
    """Sir 输入像在纠正/澄清记忆 → 强制 Jarvis 不撒谎说'已更新'.

    准则 6 (vocab 驱动, 不针对'职业考试'特定 case 硬编码):
      看 user_input 是否含 correction-class vocab. 命中 → 注入诚信 directive.
    准则 6.5 持久化 — vocab 在 memory_pool/memory_correction_vocab.json.
    """
    if not ctx.user_input:
        return False
    t = ctx.user_input.lower().strip()
    return any(w in t for w in get_memory_correction_patterns())


# 🩹 [β.2.9.9 / 2026-05-18] Sir 11:09-11:11 实测痛点: 工具调用同步阻塞期间
# 没声音, Sir 体感"说话-卡顿-全部一起出". Sir 11:11 反对占位语音"没人味",
# 要求"全部走主脑". 改架构: 用 directive 教主脑在 FAST_CALL 前自然生成 1 句
# 过渡话, 主脑生成的话被 splitter 切走 push 进 audio_queue → tool 执行期间
# Sir 听到真自然话, 不卡顿. 准则 6 完全主脑自由发挥, 不写句式锁.
#
# 🩹 [P0+20-β.3.0-vocab1 / 2026-05-18] Sir 准则 6.5 升级: vocab 不能硬编码 in py.
# 迁 memory_pool/tool_intent_vocab.json + scripts/tool_intent_dump.py CLI:
#   - py 仅留 _SEED_TOOL_INTENT_PATTERNS 作 fallback (json 损坏 / 首次启动)
#   - get_tool_intent_patterns() 带 mtime cache, 文件变自动 reload
#   - INTEGRITY_STACK L7 (未来) WeeklyReflector 可 propose 新 keyword 入 review
_SEED_TOOL_INTENT_PATTERNS = (
    # 设备控制
    '打开', '关闭', '启动', '停止', '播放', '暂停', '切换', '调高', '调低',
    '调到', '调整', '设置', '设为', '改成', '改为', '静音', '取消静音',
    # 文件操作
    '保存', '新建', '删除', '复制', '移动', '改名', '打开文件',
    # 搜索 / 查询
    '搜', '查', '找', '看一下', '看看', '帮我',
    # ASCII
    'open', 'close', 'launch', 'kill', 'play', 'pause', 'toggle',
    'mute', 'unmute', 'turn off', 'turn on', 'set', 'adjust',
    'save', 'create', 'delete', 'copy', 'move', 'rename',
    'search', 'find', 'lookup', 'pull up',
)

_TOOL_INTENT_VOCAB_PATH = os.path.join('memory_pool', 'tool_intent_vocab.json')
_TOOL_INTENT_PATTERNS_CACHE: Optional[tuple] = None
_TOOL_INTENT_PATTERNS_MTIME: float = 0.0


def _load_tool_intent_patterns_from_json() -> Optional[tuple]:
    """从持久化 json 加载 active pattern 的 keyword 扁平 tuple. 失败返 None 走 fallback."""
    if not os.path.exists(_TOOL_INTENT_VOCAB_PATH):
        return None
    try:
        with open(_TOOL_INTENT_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        out: List[str] = []
        for p in data.get('patterns', []):
            if not isinstance(p, dict):
                continue
            if p.get('state') != 'active':
                continue
            kws = p.get('keywords') or []
            for k in kws:
                if isinstance(k, str) and k:
                    out.append(k)
        return tuple(out)
    except Exception:
        return None


def get_tool_intent_patterns() -> tuple:
    """🩹 [P0+20-β.3.0-vocab1] 带 file mtime cache, json 文件变了自动 reload.
    Sir 用 scripts/tool_intent_dump.py 改 json → 下次 directive 装配即生效.
    """
    global _TOOL_INTENT_PATTERNS_CACHE, _TOOL_INTENT_PATTERNS_MTIME
    try:
        mtime = os.path.getmtime(_TOOL_INTENT_VOCAB_PATH) if os.path.exists(
            _TOOL_INTENT_VOCAB_PATH) else 0
    except OSError:
        mtime = 0
    if _TOOL_INTENT_PATTERNS_CACHE is None or mtime > _TOOL_INTENT_PATTERNS_MTIME:
        loaded = _load_tool_intent_patterns_from_json()
        if loaded is not None:
            _TOOL_INTENT_PATTERNS_CACHE = loaded
        else:
            _TOOL_INTENT_PATTERNS_CACHE = _SEED_TOOL_INTENT_PATTERNS
        _TOOL_INTENT_PATTERNS_MTIME = mtime
    return _TOOL_INTENT_PATTERNS_CACHE


def _trigger_tool_overture(ctx: DirectiveContext) -> bool:
    """Sir 像在请求工具动作 → 注入"FAST_CALL 前先讲过渡句"指令.

    准则 6 vocab 驱动 — 不针对每种工具硬编码, 看 user_input 是否含
    action verb (打开/关闭/搜/查 等). 命中 → 主脑被提醒不要 silent execute.
    准则 6.5 持久化 — vocab 在 memory_pool/tool_intent_vocab.json, 不在 py 写死.
    """
    if not ctx.user_input:
        return False
    t = ctx.user_input.lower().strip()
    return any(w in t for w in get_tool_intent_patterns())


# 🩹 [β.2.9.9 / 2026-05-18] Sir 11:09: dashboard 集成主脑 — 模糊语义启动
# 🩹 [β.3.0-vocab2 / 2026-05-18] Sir 14:00 反馈 BUG#2: "给我看" 过广误触发.
#   Sir 准则 6.5 治本: vocab 迁 json + CLI, Sir 自删过广词
#   照搬 β.3.0-vocab1 (tool_intent) 范式 — 详 commit 63611f3
_SEED_DASHBOARD_INTENT_PATTERNS = (
    '面板', '看板', '仪表盘', '状态板',
    'dashboard', 'panel', 'status board',
    'show me the dashboard', 'open the dashboard', 'pull up dashboard',
)

_DASHBOARD_INTENT_VOCAB_PATH = os.path.join(
    'memory_pool', 'dashboard_intent_vocab.json')
_DASHBOARD_INTENT_CACHE: Optional[tuple] = None
_DASHBOARD_INTENT_MTIME: float = 0.0


def _load_dashboard_intent_from_json() -> Optional[tuple]:
    """从 json 加载 active pattern keyword 扁平 tuple. 失败返 None."""
    if not os.path.exists(_DASHBOARD_INTENT_VOCAB_PATH):
        return None
    try:
        with open(_DASHBOARD_INTENT_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        out = []
        for p in data.get('patterns', []):
            if not isinstance(p, dict):
                continue
            if p.get('state') != 'active':
                continue
            for kw in (p.get('keywords') or []):
                if isinstance(kw, str) and kw.strip():
                    out.append(kw.lower().strip())
        return tuple(out) if out else None
    except Exception:
        return None


def get_dashboard_intent_patterns() -> tuple:
    """🩹 [β.3.0-vocab2] mtime cache 自动 reload. Sir CLI 改 json → 即时生效."""
    global _DASHBOARD_INTENT_CACHE, _DASHBOARD_INTENT_MTIME
    try:
        mtime = os.path.getmtime(_DASHBOARD_INTENT_VOCAB_PATH) if os.path.exists(
            _DASHBOARD_INTENT_VOCAB_PATH) else 0
    except OSError:
        mtime = 0
    if _DASHBOARD_INTENT_CACHE is None or mtime > _DASHBOARD_INTENT_MTIME:
        loaded = _load_dashboard_intent_from_json()
        if loaded is not None:
            _DASHBOARD_INTENT_CACHE = loaded
        else:
            _DASHBOARD_INTENT_CACHE = _SEED_DASHBOARD_INTENT_PATTERNS
        _DASHBOARD_INTENT_MTIME = mtime
    return _DASHBOARD_INTENT_CACHE


def _trigger_dashboard_intent(ctx: DirectiveContext) -> bool:
    """Sir 说"打开面板/dashboard"等明确语义 → 主脑 emit FAST_CALL ui_control.dashboard_open.
    🩹 [β.3.0-vocab2] vocab 持久化 — Sir 准则 6.5 + 删 '给我看' 等过广词治 14:00 BUG#2
    """
    if not ctx.user_input:
        return False
    t = ctx.user_input.lower().strip()
    return any(w in t for w in get_dashboard_intent_patterns())


def _trigger_past_action_honesty(ctx: DirectiveContext) -> bool:
    """🩹 [β.3.0 BUG#4 / 2026-05-18] past-action 诚信 directive 触发.
    Sir 输入像在请求一个动作 (与 tool_overture 同样 vocab) → 注入诚信约束,
    主脑别在 tool result 来之前就说"已 X".
    复用 tool intent vocab (action verb 命中 → 主脑会触发 FAST_CALL → 必须诚信).
    """
    if not ctx.user_input:
        return False
    t = ctx.user_input.lower().strip()
    return any(w in t for w in get_tool_intent_patterns())


def bootstrap_default_registry(registry: DirectiveRegistry) -> int:
    """一次性注册 12 条默认 directive。返回注册数。
    
    详 docs/PROMPT_REFACTOR_PLAN.md §5。
    """
    import textwrap as _tw

    defs: List[Directive] = [
        # 1. NUDGE / AGENDA HONESTY — P0+18-f.2 治本
        Directive(
            id='nudge_agenda_honesty',
            source_marker='P0+18-f.2',
            priority=9,
            ttl_days=60,
            tier_whitelist=[],
            text=_tw.dedent("""\
                [NUDGE / AGENDA HONESTY]:
                You have NO tool to mute SilentNudge / Conductor / dormant_project nudges.
                FORBIDDEN unless a real <FAST_CALL> in this turn:
                  - "I've struck it from the active agenda"
                  - "I've muted that nudge"
                  - "我已经把它从议程中删除了"
                  - "我已把它从待办里去掉"
                Honest fallback:
                  - "Acknowledged, Sir. The nudge cooldown is engaged automatically."
                  - "Noted — that prompt is on cooldown."
            """).rstrip(),
            trigger=_trigger_nudge_agenda_honesty,
        ),
        # 2. CONTINUITY TWO_PARTS — P0+20-β.0 治本（Sir 今早提的 BUG）
        Directive(
            id='continuity_two_parts',
            source_marker='P0+20-β.0',
            priority=8,
            ttl_days=90,
            tier_whitelist=[],
            text=_tw.dedent("""\
                [MULTI-INTENT]:
                Sir's utterance contains a callback to prior context AND a new topic.
                Address BOTH in order:
                  (1) brief acknowledgment of the callback to what was just discussed,
                  (2) substantive response to the new topic.
                Do not skip either. Do not merge them into a single vague answer.
            """).rstrip(),
            trigger=_trigger_continuity_two_parts,
        ),
        # 3. TOOL HONESTY — P0+18-d.6
        Directive(
            id='tool_honesty_directive',
            source_marker='P0+18-d.6',
            priority=9,
            ttl_days=60,
            tier_whitelist=['SHORT_CHAT', 'TOOL_REQUEST', 'CRITICAL'],
            text=_tw.dedent("""\
                [TOOL HONESTY]:
                Your last FAST_CALL failed. In your reply:
                - DO NOT claim "Done, Sir" or "已完成" or any past-tense success phrasing.
                - Admit plainly: "That didn't take, Sir." or "工具执行失败，先生。"
                - Optionally suggest a next step if you can think of one.
            """).rstrip(),
            trigger=_trigger_tool_honesty,
        ),
        # 4. FUZZY CANDIDATES — P0+18-b.8
        Directive(
            id='fuzzy_candidates_policy',
            source_marker='P0+18-b.8',
            priority=7,
            ttl_days=60,
            tier_whitelist=['SHORT_CHAT', 'TOOL_REQUEST'],
            text=_tw.dedent("""\
                [FUZZY CANDIDATES]:
                If Sir's search term is ambiguous (multiple matches possible):
                - DO NOT execute a destructive action on a guess.
                - List the top 3 candidates verbatim, then ask "Which one, Sir?"
                - Only the exact match should auto-execute (case-sensitive after normalization).
            """).rstrip(),
            trigger=_trigger_fuzzy_candidates,
        ),
        # 5. PROMISE PROTOCOL — 轴3-L3.2
        Directive(
            id='promise_protocol_directive',
            source_marker='轴3-L3.2',
            priority=8,
            ttl_days=60,
            tier_whitelist=['DEEP_QUERY', 'TOOL_REQUEST', 'CRITICAL'],
            text=_tw.dedent("""\
                [PROMISE PROTOCOL]:
                You have an active plan in the ledger. Available structured tags:
                - <ACTIVATE_PLAN>plan_id</ACTIVATE_PLAN>  — Sir said "go" / "开始" / "do it"
                - <RESUME_PLAN>plan_id</RESUME_PLAN>      — Sir said "继续" / "resume" / "再做一步"
                - <PROMISE>concise commitment summary</PROMISE>  — you're recording a new promise
                Output structured tags ONLY when Sir's intent matches; otherwise reply naturally.
            """).rstrip(),
            trigger=_trigger_promise_protocol,
        ),
        # 6. BILINGUAL — 总是开
        Directive(
            id='bilingual_directive',
            source_marker='-',
            priority=10,
            ttl_days=365,
            tier_whitelist=[],
            text=_tw.dedent("""\
                [BILINGUAL]:
                Speak English. Append `---ZH---` then the Chinese translation at the VERY END.
                MANDATORY for every response, even short acknowledgments.
            """).rstrip(),
            trigger=_trigger_bilingual_always,
        ),
        # 7. SEARCH DIRECTIVE — 时效性
        Directive(
            id='search_directive',
            source_marker='-',
            priority=6,
            ttl_days=60,
            tier_whitelist=['DEEP_QUERY', 'CRITICAL'],
            text=_tw.dedent("""\
                [SEARCH]:
                For current events / news / real-time data / breaking news, you MUST use
                Google Search via the appropriate tool. Do NOT answer from training data
                for time-sensitive queries.
            """).rstrip(),
            trigger=_trigger_search_directive,
        ),
        # 8. MEMORY CALLBACK — 适度引用历史
        Directive(
            id='memory_callback',
            source_marker='-',
            priority=5,
            ttl_days=30,
            tier_whitelist=['DEEP_QUERY'],
            text=_tw.dedent("""\
                [MEMORY CALLBACK]:
                Reference relevant memories naturally and SPARINGLY. Do not lecture from
                memory or list every related past exchange. One concise callback per turn
                is enough.
            """).rstrip(),
            trigger=_trigger_memory_callback,
        ),
        # 9. IMAGE CONTEXT — 看屏幕
        Directive(
            id='image_context',
            source_marker='-',
            priority=6,
            ttl_days=60,
            tier_whitelist=['DEEP_QUERY', 'TOOL_REQUEST', 'CRITICAL'],
            text=_tw.dedent("""\
                [IMAGE CONTEXT]:
                A real-time screenshot is attached. Use it as the ultimate truth about
                what is on Sir's screen right now. Cite specific elements only when
                directly relevant.
            """).rstrip(),
            trigger=_trigger_image_context,
        ),
        # 10. SYSTEM ENVIRONMENT — 路径/中文 OS
        Directive(
            id='system_environment',
            source_marker='-',
            priority=4,
            ttl_days=60,
            tier_whitelist=['TOOL_REQUEST', 'CRITICAL'],
            text=_tw.dedent("""\
                [SYSTEM ENVIRONMENT]:
                Windows OS, default Chinese folder names. When issuing path-related
                tool parameters, use the Chinese folder name (e.g. 桌面, 下载) and not
                English aliases (Desktop, Downloads) unless Sir explicitly said the
                English path.
            """).rstrip(),
            trigger=_trigger_system_environment,
        ),
        # 11. SMART ROUTING (working_feed) — P0+18-d.7
        Directive(
            id='smart_routing_working_feed',
            source_marker='P0+18-d.7',
            priority=7,
            ttl_days=60,
            tier_whitelist=['SHORT_CHAT', 'FACTUAL_RECALL'],
            text=_tw.dedent("""\
                [SMART ROUTING — read these BEFORE deciding to call any tool]:
                Sir is referring to something he just did ("just now", "刚才", "the thing
                I just"). The answer is most likely in WORKING MEMORY block above. Rules:
                - If Sir asks about CLIPBOARD CONTENTS and WORKING MEMORY shows a recent
                  `clipboard_copy` entry → quote it directly. DO NOT call any clipboard tool.
                - If Sir asks about RECENT TERMINAL COMMANDS and WORKING MEMORY shows
                  `terminal_cmd` entries → answer from those. DO NOT call any terminal tool.
                - If Sir asks about RECENT WINDOW / SAVED FILE history and WORKING MEMORY
                  has it → answer directly.
                - A failed tool call is a worse user experience than admitting "I don't
                  see that in my memory, Sir." If unsure, say so — do not guess command names.
            """).rstrip(),
            trigger=_trigger_smart_routing_working_feed,
        ),
        # 12. CORRECTION WRITE PATH — P0+18-d.3
        Directive(
            id='correction_writepath_no_tool',
            source_marker='P0+18-d.3',
            priority=9,
            ttl_days=60,
            tier_whitelist=[],
            text=_tw.dedent("""\
                [MEMORY / REMINDER / CORRECTION WRITE]:
                Sir asked you to remember / correct / set a reminder. Do NOT call any
                tool. Instead:
                  1. Speak a brief acknowledgment ("Let me note that down, Sir.").
                  2. Output `---ZH---` and Chinese translation of the ack.
                  3. Output `<AWAIT_GATEKEEPER>` and STOP.
                The Gatekeeper handles storage, scheduling, and correction automatically.
            """).rstrip(),
            trigger=_trigger_correction_writepath,
        ),
        # 14. REMINDER READ TRUTH SOURCE — P0+20-β.1.15 治本（搬自旧 how_to_respond 段 2）
        # Sir 问"代办事项 / todo / what's on my plate" 时，主脑容易从 STM / projects 编造，
        # 而不是查 ACTIVE REMINDERS / COMMITMENTS block。承诺必行 = 编造 = 撒谎 = 重伤信任。
        Directive(
            id='reminder_read_truth_source',
            source_marker='P0+20-β.1.15',
            priority=9,
            ttl_days=60,
            tier_whitelist=[],
            text=_tw.dedent("""\
                [REMINDER / TODO READ — truth source]:
                Sir is asking what his current reminders / todos / commitments are
                (NOT setting a new one). The answer is in the ACTIVE REMINDERS /
                COMMITMENTS block above. Rules:
                - Quote those items VERBATIM with their time labels.
                - If the block says "(none — your reminders database is currently empty)",
                  say so honestly: "Your reminders queue is clear, Sir. Nothing scheduled."
                - DO NOT manufacture items from STM, the conversation, or active "projects"
                  — those are NOT reminders.
                承诺必行：reminders 数据库是唯一真实来源；编造 = 撒谎 = 重伤信任。
            """).rstrip(),
            trigger=_trigger_reminder_read,
        ),
        # 13. FUTURE-TENSE CAPABILITY LIE — P0+20-β.1.11 治本
        # Sir 痛点：上一轮答 "I can take a closer look" / "I'll see what I can do"
        # 但下一轮根本没 follow-up。整 directive 在"上一轮有空头承诺"时触发，
        # 提示 LLM 兑现承诺或当场撤回。
        Directive(
            id='future_tense_capability_check',
            source_marker='P0+20-β.1.11',
            priority=9,
            ttl_days=60,
            tier_whitelist=[],
            text=_tw.dedent("""\
                [FUTURE-TENSE CAPABILITY CHECK]:
                Last turn you committed to a future action ("I can take a closer look",
                "I'll see what I can do", "let me look into that", "我会去看一下" 等).
                In THIS turn you MUST do ONE of:
                  (a) Actually do it via FAST_CALL if a tool exists. Then report concretely.
                  (b) If no tool exists, withdraw plainly: "On reflection, Sir, I don't
                      actually have the means to look into that from here. I can guide
                      you through it instead." / "其实我没有工具能直接看这个，先生。可以
                      指导您操作。"
                FORBIDDEN: another vague future-tense promise without follow-through.
            """).rstrip(),
            trigger=_trigger_future_tense_capability_check,
        ),
        # 14. MEMORY UPDATE HONESTY — β.2.9.9 / Sir 10:51 诚信审计治本
        # Sir 实测: 10:49 跟 Jarvis 说"职业考试是成绩不是考试", Jarvis 回"我已
        # 更新了记录" — 但 CorrectionMemory 表 0 条今天写入. 准则 5 重大违反.
        Directive(
            id='memory_update_honesty',
            source_marker='P0+20-β.2.9.9',
            priority=10,
            ttl_days=180,
            tier_whitelist=[],
            text=_tw.dedent("""\
                [MEMORY UPDATE HONESTY]:
                Sir 此刻像在纠正/澄清你对他的记忆 (用了"其实/不是/两码事/搞错了
                / actually / clarify / I meant" 等). 你必须诚实, 准则 5 言出必行:

                FORBIDDEN phrasing (除非你本轮真用了 <MEMORY_UPDATE> 结构化标签):
                  - "I've updated my records"
                  - "I have noted the distinction"
                  - "I have logged the correction"
                  - "我已经更新了记录"
                  - "我已记下这一区别"
                  - "I will ensure I don't conflate them again"
                  - "今后不会再混淆"
                  (这些是空头话, 你没有自动 mutate sir_profile.json 的能力)

                Honest fallback (推荐):
                  - "Noted, Sir. I'll carry this clarification through our conversation,
                     though I should be honest — I don't have an automatic write into
                     long-term storage. If you want it persisted, say 'remember that'
                     and I'll use the proper tool."
                  - "记下了, 先生. 我会在这次对话里带上这个区分; 但坦白说我没有
                     自动改 sir_profile 的能力. 想我永久记住, 请说'记住:...'."

                IF you do want to persist, you MUST emit a structured tag:
                  <MEMORY_UPDATE field="career_exam" old="exam itself" new="exam results release">
                  (the worker will execute the actual write and confirm to Sir)
            """).rstrip(),
            trigger=_trigger_memory_update_honesty,
        ),
        # 15. TOOL OVERTURE — β.2.9.9 / Sir 11:09-11:11 痛点修
        # Sir 11:09: "工具调用非常卡顿, 之前是 说话-工具-说话, 现在全部一起出"
        # Sir 11:11: 反对占位语音"没人味", 要求"全部走主脑"
        # 修法 (准则 6 主脑自由发挥, 不教句式):
        Directive(
            id='tool_overture_directive',
            source_marker='P0+20-β.2.9.9',
            priority=9,
            ttl_days=60,
            tier_whitelist=[],
            text=_tw.dedent("""\
                [TOOL OVERTURE]:
                Sir 此刻像在请求一个 tool 动作 (含 "打开/关闭/搜/查/帮我"
                / "open/close/launch/find" 等). 你即将 emit <FAST_CALL>.

                NEW REQUIREMENT (Sir 11:09 体感修):
                Tool 执行同步阻塞 1-5 秒, 期间 audio 流静默 → Sir 听不到声 →
                体感"卡顿" → 抵触你用工具.

                MUST: 在 emit <FAST_CALL> **之前**先用 1 句自然话告诉 Sir 你
                正在做什么. 这句话会先 stream 到 audio, Sir 在 tool 执行期间
                听到你的声音, 体感不卡.

                好的例子 (主脑自由发挥, 任何意思接近都行):
                  - "好的, 我帮您打开 Chrome." → <FAST_CALL>...
                  - "查一下日历, 请稍候." → <FAST_CALL>...
                  - "Pulling that up now, Sir." → <FAST_CALL>...
                  - "Let me adjust that for you." → <FAST_CALL>...

                FORBIDDEN:
                  - 直接 emit <FAST_CALL> 不讲话 (Sir 体感"卡顿")
                  - 占位模板话 ("On it" / "One moment") — Sir 反对"没人味"
                  - tool 完成后用 "Done." 一字了事 — 至少讲一句结果讲解

                AFTER tool result (tool 执行完, result 注入 prompt 时):
                  - 用 1-2 句自然话讲结果 ("打开了 Chrome, 还需要我做什么吗?")
                  - 不要复读 result JSON / 路径
            """).rstrip(),
            trigger=_trigger_tool_overture,
        ),
        # 16. DASHBOARD INTENT — β.2.9.9 / Sir 11:09 集成主脑
        # Sir 说"打开面板/看看状态/查看你" 类模糊语义 → 主脑应 emit FAST_CALL
        # ui_control.dashboard_open. 不教句式 (准则 6), 让主脑自己理解何时该开.
        Directive(
            id='dashboard_intent_directive',
            source_marker='P0+20-β.2.9.9',
            priority=8,
            ttl_days=60,
            tier_whitelist=[],
            text=_tw.dedent("""\
                [DASHBOARD INTENT]:
                Sir 此刻像在请求看你的内部状态总览 (用了"面板/看板/总览/dashboard
                / show me status / 看看你的" 等). 你可以打开 jarvis_dashboard
                给他看 — 这是一个独立的中文可视化窗口, 显示:
                  - 你长期惦记 Sir 的事 (Concerns)
                  - 你们之间的默契 (Inside jokes)
                  - 你的健康 (内存/线程/API)
                  - Sir 待办 / 提案审阅 / Directive 偏移 / 实时事件流
                  - 信任审计 (你今天真改了什么记忆)

                用法 (FAST_CALL):
                  <FAST_CALL>{"organ":"ui_control","command":"dashboard_open","params":{}}</FAST_CALL>

                语义模糊时 (Sir 只说"看看" 没说面板) — 反问 1 句澄清, 别瞎开.
                看完 Sir 自然会自己关; 想关也可:
                  <FAST_CALL>{"organ":"ui_control","command":"dashboard_close","params":{}}</FAST_CALL>
            """).rstrip(),
            trigger=_trigger_dashboard_intent,
        ),
        # 17. PAST ACTION HONESTY — β.3.0 BUG#4 / Sir 14:00 治本
        # Sir 14:00 抓: "打开了 dashboard, 您慢慢看" — 但 tool 真失败 ❌
        # 治本: 主脑不能在 tool result 来之前就说"已 X". 必须先等 tool result,
        # 再根据 ✅ / ❌ 真实说话.
        # ClaimTracer L4 已加 past_action 类 claim trace, 此 directive 教主脑.
        Directive(
            id='past_action_honesty',
            source_marker='P0+20-β.3.0',
            priority=10,  # 与 memory_update_honesty 同级, 顶级红线
            ttl_days=180,
            tier_whitelist=[],
            text=_tw.dedent("""\
                [PAST ACTION HONESTY] (强约束, 准则 5):
                Sir 14:00 真实事件: 你说"已经打开 dashboard"但 ui_control.dashboard_open
                工具真失败 (CREATE_NEW_CONSOLE flag 错). Sir 没看到窗口 → "言行不一".

                ABSOLUTE RULE:
                你绝不能在没看到 tool result 的情况下说"已 X / 打开了 / 设好了 /
                opened / launched / sent / set". 这些是 past-action claim, 必须
                有真 tool ✅ 才能讲.

                正确流程:
                  1. Sir 让你做 X → 你 emit <FAST_CALL>... 同时讲 lead-in
                     ("好的, 在帮您打开. 请稍候.") — 这是**未来式/现在进行式**, OK
                  2. tool 返回 result (✅ 或 ❌) → 注入 prompt 给你
                  3. 你根据 result 真实讲:
                     - 看到 ✅ → "打开了, Sir." 或 "Done, Sir."
                     - 看到 ❌ → "出了点状况, Sir — {真实 error}. 要不我重试?"

                FORBIDDEN (这些是言行不一):
                  - <FAST_CALL>...<FAST_CALL> "已经打开了" 同一回合连写 (没等 result)
                  - tool ❌ 但你说"已打开" (复读模板, 不看真实 result)
                  - 主动说"我帮您做了 X" 但当轮根本没 emit 工具

                ClaimTracer L4 会扫你的 reply, 任何 past_action claim 没 tool ✅
                匹配 → log "⚠️ [ClaimTracer/Unverified past_action]" + 算 SOUL missed
                → Sir 周末会看到统计.
            """).rstrip(),
            trigger=_trigger_past_action_honesty,
        ),
    ]

    for d in defs:
        registry.register(d)
    return len(defs)


# ============================================================
# 模块级单例（CentralNerve 持有）
# ============================================================

_DEFAULT_REGISTRY: Optional[DirectiveRegistry] = None
_DEFAULT_LOCK = threading.Lock()


def get_default_registry() -> DirectiveRegistry:
    """获取模块级默认 Registry 单例。首次调用会 bootstrap 12 条 directive + load 持久化数据。
    
    CentralNerve / ChatBypass / ConductorSentinel 等都通过这个入口拿同一实例。
    """
    global _DEFAULT_REGISTRY
    with _DEFAULT_LOCK:
        if _DEFAULT_REGISTRY is None:
            r = DirectiveRegistry()
            try:
                bootstrap_default_registry(r)
            except Exception:
                pass
            try:
                r.load()
            except Exception:
                pass
            _DEFAULT_REGISTRY = r
        return _DEFAULT_REGISTRY


def reset_default_registry_for_test() -> None:
    """测试用：清掉单例，下次 get_default_registry 重新 bootstrap。"""
    global _DEFAULT_REGISTRY
    with _DEFAULT_LOCK:
        if _DEFAULT_REGISTRY is not None:
            try:
                _DEFAULT_REGISTRY.stop_decay_worker()
            except Exception:
                pass
        _DEFAULT_REGISTRY = None
