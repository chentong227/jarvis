# -*- coding: utf-8 -*-
"""[P0+20-β.2.1 / 2026-05-16] Jarvis Concerns — 内部牵挂系统（灵魂工程 Layer 1）

详 docs/JARVIS_SOUL_DRIVE.md。

核心：Jarvis 跨对话持续的"我"。每条 Concern 是 Jarvis 自己关心的事，
持续 evolve，注入到每一次 prompt 装配（不只是 nudge 路径），让主脑无论
回答什么问题都能"考虑 Sir 的全貌"。

数据结构：
- Concern: 单条牵挂（what_i_watch / why_i_care / severity / recent_signals / ...）
- ConcernsLedger: 增删查改 + 持久化 + decay + Sir review queue

5 个种子（启动时 bootstrap）：
- sir_sleep_streak / sir_pomodoro / sir_cursor_payment
- unfinished_jiazhao / jarvis_keyrouter（这条是 Jarvis 对自己的关心）

持久化：memory_pool/concerns.json
Sir review 队列：memory_pool/concerns_review.json

线程安全：所有写操作走 self._lock。
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, List, Optional


# ============================================================
# 状态常量
# ============================================================
STATE_ACTIVE = 'active'
STATE_SNOOZED = 'snoozed'      # Sir 暂时压制 N 小时
STATE_REVIEW = 'review'        # 新 propose 等 Sir 审
STATE_ARCHIVED = 'archived'    # 长期无信号 / Sir 拒绝

# 默认参数
DEFAULT_TTL_DAYS = 30
DEFAULT_DECAY_INTERVAL_S = 86400.0  # 24h tick


# ============================================================
# 数据结构
# ============================================================

@dataclass
class Concern:
    """Jarvis 内部牵挂。

    设计原则：
    - what_i_watch 是 Jarvis 视角的"我在关心什么"（不是 Sir 视角的"Sir 是什么"）
    - why_i_care 必须有 rationale（防止凭空 propose）
    - severity 0-1 浮点，影响注入 prompt 时的排序
    - recent_signals 是滑动窗口，最多保留 10 条最近 evidence
    """
    id: str
    what_i_watch: str
    why_i_care: str
    severity: float = 0.3
    state: str = STATE_ACTIVE

    # 数据信号（最近 N 条 evidence）
    recent_signals: List[dict] = field(default_factory=list)

    # 时间
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    last_triggered: float = 0.0  # 上次因为这个 concern 真的触发主动行为

    # 来源
    source: str = 'seeded'          # seeded / discovered / sir_added / sir_confirmed
    source_marker: str = ''         # P0+20-β.X.Y / sir_2026_05_16

    # 配置
    ttl_days: int = DEFAULT_TTL_DAYS
    triggers_proactive: bool = True
    notes_for_self: str = ''        # Jarvis 给自己的便条（"上次 Sir 反驳了，下次温和点"）

    def record_signal(self, what: str, severity_delta: float = 0.0,
                      source_turn_id: str = '') -> None:
        """记一条 evidence。recent_signals 最多保 10 条。"""
        now = time.time()
        self.recent_signals.append({
            'when': now,
            'when_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
            'what': what[:200],
            'severity_delta': severity_delta,
            'turn_id': source_turn_id,
        })
        if len(self.recent_signals) > 10:
            self.recent_signals = self.recent_signals[-10:]
        self.severity = max(0.0, min(1.0, self.severity + severity_delta))
        self.last_updated = now

    def is_expired(self) -> bool:
        """ttl_days 内没 signal 且 severity 低 → 视为过期。"""
        if self.severity > 0.5:
            return False  # 重要的不过期
        if not self.recent_signals and self.last_updated > 0:
            age = time.time() - self.last_updated
            return age > self.ttl_days * 86400
        if self.recent_signals:
            last_sig = max(s.get('when', 0) for s in self.recent_signals)
            return (time.time() - last_sig) > self.ttl_days * 86400
        return False

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# Ledger
# ============================================================

class ConcernsLedger:
    """Concerns 注册 + 查询 + 持久化 + decay。线程安全。"""

    DEFAULT_PERSIST_PATH = os.path.join('memory_pool', 'concerns.json')
    DEFAULT_REVIEW_PATH = os.path.join('memory_pool', 'concerns_review.json')

    def __init__(self, persist_path: Optional[str] = None,
                 review_path: Optional[str] = None):
        self.persist_path = persist_path or self.DEFAULT_PERSIST_PATH
        self.review_path = review_path or self.DEFAULT_REVIEW_PATH
        self.concerns: dict[str, Concern] = {}
        self._lock = threading.Lock()
        self._dirty = False
        self._decay_worker: Optional[threading.Thread] = None
        self._decay_stop = threading.Event()

    # ---- CRUD ----

    def register(self, concern: Concern) -> bool:
        """注册新 concern。已存在则返回 False。"""
        with self._lock:
            if concern.id in self.concerns:
                return False
            self.concerns[concern.id] = concern
            self._dirty = True
            return True

    def update(self, concern: Concern) -> bool:
        """覆盖更新（按 id）。不存在返回 False。"""
        with self._lock:
            if concern.id not in self.concerns:
                return False
            self.concerns[concern.id] = concern
            self._dirty = True
            return True

    def get(self, concern_id: str) -> Optional[Concern]:
        return self.concerns.get(concern_id)

    def list_all(self) -> List[Concern]:
        return list(self.concerns.values())

    def list_active(self) -> List[Concern]:
        return [c for c in self.concerns.values() if c.state == STATE_ACTIVE]

    def list_review(self) -> List[Concern]:
        return [c for c in self.concerns.values() if c.state == STATE_REVIEW]

    # ---- 信号采集 ----

    def record_signal(self, concern_id: str, what: str,
                      severity_delta: float = 0.0,
                      source_turn_id: str = '') -> bool:
        """给某个 concern 加一条 evidence。"""
        with self._lock:
            c = self.concerns.get(concern_id)
            if c is None:
                return False
            c.record_signal(what, severity_delta, source_turn_id)
            self._dirty = True
            return True

    def record_triggered(self, concern_id: str) -> None:
        """标记 concern 触发了主动行为（用于 cooldown）。"""
        with self._lock:
            c = self.concerns.get(concern_id)
            if c is not None:
                c.last_triggered = time.time()
                self._dirty = True

    # ---- 状态管理 ----

    def activate(self, concern_id: str) -> bool:
        """Sir review 后激活。"""
        with self._lock:
            c = self.concerns.get(concern_id)
            if c is None:
                return False
            c.state = STATE_ACTIVE
            c.last_updated = time.time()
            self._dirty = True
        return True

    def reject(self, concern_id: str) -> bool:
        """Sir 拒绝（→ archived）。"""
        with self._lock:
            c = self.concerns.get(concern_id)
            if c is None:
                return False
            c.state = STATE_ARCHIVED
            c.last_updated = time.time()
            self._dirty = True
        return True

    def snooze(self, concern_id: str, hours: float = 24.0) -> bool:
        with self._lock:
            c = self.concerns.get(concern_id)
            if c is None:
                return False
            c.state = STATE_SNOOZED
            c.notes_for_self = f"snoozed until {time.strftime('%Y-%m-%d %H:%M', time.localtime(time.time() + hours * 3600))}"
            c.last_updated = time.time()
            self._dirty = True
        return True

    # ---- decay ----

    def apply_decay(self) -> dict:
        """24h tick：过期 concern → archived；snoozed 到期 → active。"""
        stats = {'archived': 0, 'unsnoozed': 0}
        now = time.time()
        with self._lock:
            for c in self.concerns.values():
                if c.state == STATE_ACTIVE and c.is_expired():
                    c.state = STATE_ARCHIVED
                    stats['archived'] += 1
                    self._dirty = True
                elif c.state == STATE_SNOOZED:
                    # 简单判断：notes_for_self 含 "until YYYY-MM-DD HH:MM"，过期则唤回
                    note = c.notes_for_self or ''
                    if 'snoozed until' in note:
                        try:
                            _, until_str = note.split('until', 1)
                            until_ts = time.mktime(time.strptime(until_str.strip(), '%Y-%m-%d %H:%M'))
                            if now > until_ts:
                                c.state = STATE_ACTIVE
                                c.notes_for_self = ''
                                stats['unsnoozed'] += 1
                                self._dirty = True
                        except Exception:
                            pass
        return stats

    # ---- 持久化 ----

    def persist(self) -> bool:
        with self._lock:
            if not self._dirty:
                return False
            snapshot = {cid: c.to_dict() for cid, c in self.concerns.items()}
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

    def load(self) -> int:
        """从 disk 恢复。返回成功恢复的 concerns 数。"""
        if not os.path.exists(self.persist_path):
            return 0
        try:
            with open(self.persist_path, 'r', encoding='utf-8') as f:
                snapshot = json.load(f) or {}
        except Exception:
            return 0
        n = 0
        with self._lock:
            for cid, data in snapshot.items():
                try:
                    # 兼容字段缺失（旧版本）
                    c = Concern(
                        id=data.get('id', cid),
                        what_i_watch=data.get('what_i_watch', ''),
                        why_i_care=data.get('why_i_care', ''),
                        severity=float(data.get('severity', 0.3)),
                        state=data.get('state', STATE_ACTIVE),
                        recent_signals=list(data.get('recent_signals', []) or []),
                        created_at=float(data.get('created_at', time.time())),
                        last_updated=float(data.get('last_updated', time.time())),
                        last_triggered=float(data.get('last_triggered', 0.0)),
                        source=data.get('source', 'seeded'),
                        source_marker=data.get('source_marker', ''),
                        ttl_days=int(data.get('ttl_days', DEFAULT_TTL_DAYS)),
                        triggers_proactive=bool(data.get('triggers_proactive', True)),
                        notes_for_self=data.get('notes_for_self', ''),
                    )
                    self.concerns[c.id] = c
                    n += 1
                except Exception:
                    continue
        return n

    # ---- Sir review queue ----

    def write_review_queue(self) -> bool:
        """写 review state 的 concerns 到 review JSON。"""
        review = [c.to_dict() for c in self.list_review()]
        try:
            os.makedirs(os.path.dirname(self.review_path), exist_ok=True)
            tmp = self.review_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(review, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.review_path)
            return True
        except Exception:
            return False

    # ---- prompt 注入 ----

    def to_prompt_block(self, top_n: int = 3, max_chars: int = 800) -> str:
        """构造注入 prompt 的 [MY SELF / SOUL] 块。

        - 取 top_n active concerns，按 severity 降序
        - 每条 ≤ 150 chars
        - 总长度硬上限 max_chars
        """
        active = sorted(self.list_active(), key=lambda c: -c.severity)
        if not active:
            return ''
        top = active[:top_n]
        lines = ["=== MY SELF / SOUL ===",
                 "[CONCERNS I'M WATCHING NOW]"]
        for c in top:
            severity_label = "high" if c.severity > 0.7 else "moderate" if c.severity > 0.4 else "low"
            line = (f"  - {c.id} ({severity_label}, sev={c.severity:.2f}): "
                    f"{c.what_i_watch[:60]}")
            if c.why_i_care:
                line += f" | why: {c.why_i_care[:50]}"
            lines.append(line[:150])
            if c.recent_signals:
                last = c.recent_signals[-1]
                what = last.get('what', '')[:60]
                if what:
                    lines.append(f"    recent: {what}"[:150])
        out = '\n'.join(lines)
        if len(out) > max_chars:
            _suffix = '\n…[truncated]'
            out = out[:max_chars - len(_suffix)].rstrip() + _suffix
        return out

    # ---- decay daemon ----

    def start_decay_worker(self, interval_s: float = DEFAULT_DECAY_INTERVAL_S) -> None:
        if self._decay_worker is not None and self._decay_worker.is_alive():
            return
        self._decay_stop.clear()

        def _loop():
            try:
                from jarvis_utils import bg_log
                bg_log(f"♻️ [ConcernsDecayWorker] 启动 (tick={interval_s/3600:.1f}h)")
            except Exception:
                pass
            while not self._decay_stop.is_set():
                try:
                    stats = self.apply_decay()
                    if any(v > 0 for v in stats.values()):
                        try:
                            from jarvis_utils import bg_log
                            bg_log(f"♻️ [ConcernsDecayWorker] archived={stats['archived']} unsnoozed={stats['unsnoozed']}")
                        except Exception:
                            pass
                    self.persist()
                    self.write_review_queue()
                except Exception:
                    pass
                self._decay_stop.wait(interval_s)

        self._decay_worker = threading.Thread(target=_loop, daemon=True, name='ConcernsDecayWorker')
        self._decay_worker.start()

    def stop_decay_worker(self) -> None:
        self._decay_stop.set()

    # ---- 人类可读 dump ----

    def dump_human(self) -> str:
        """ASCII 表给 Sir 看。"""
        active = self.list_active()
        review = self.list_review()
        snoozed = [c for c in self.concerns.values() if c.state == STATE_SNOOZED]
        archived = [c for c in self.concerns.values() if c.state == STATE_ARCHIVED]

        lines = []
        lines.append("=" * 100)
        lines.append(f"[ConcernsLedger] active={len(active)} review={len(review)} "
                     f"snoozed={len(snoozed)} archived={len(archived)}")
        lines.append("=" * 100)
        if active:
            lines.append(f"{'id':32}{'sev':>6}  {'src':<14}{'last_signal':<22}what_i_watch")
            lines.append("-" * 100)
            for c in sorted(active, key=lambda x: -x.severity):
                last_sig = ''
                if c.recent_signals:
                    last_sig = c.recent_signals[-1].get('when_iso', '')[:19]
                lines.append(f"{c.id:32}{c.severity:>6.2f}  {c.source:<14}{last_sig:<22}"
                             f"{c.what_i_watch[:40]}")
        else:
            lines.append("(no active concerns)")
        if review:
            lines.append("")
            lines.append(f"[REVIEW QUEUE] {len(review)} concerns 等 Sir 审")
            for c in review:
                lines.append(f"  - {c.id}: {c.what_i_watch[:60]}")
        lines.append("=" * 100)
        return '\n'.join(lines)


# ============================================================
# 种子 concerns（启动时 bootstrap）
# ============================================================

def bootstrap_default_concerns(ledger: ConcernsLedger) -> int:
    """注册 5 个种子 concerns。返回新注册数。

    设计原则：
    - 每条都有真实 rationale（why_i_care 不能空）
    - severity 起点 0.2-0.4，让信号驱动它涨/降
    - 第 5 条是 Jarvis 对自己的关心（不只是关心 Sir）
    """
    seeds = [
        Concern(
            id='sir_sleep_streak',
            what_i_watch="Sir 是否连续熬夜（4+ 天 deep night）",
            why_i_care="Sir 18 个月颈椎病史 / profile 标记慢性疲劳风险",
            severity=0.3,
            source='seeded',
            source_marker='P0+20-β.2.1',
            ttl_days=60,
        ),
        Concern(
            id='sir_pomodoro_compliance',
            what_i_watch="Sir 是否按节奏休息（90 min+ 无 break = 信号）",
            why_i_care="Sir 工作时倾向 flow 锁死，自己不会主动停",
            severity=0.2,
            source='seeded',
            source_marker='P0+20-β.2.1',
        ),
        Concern(
            id='sir_cursor_payment',
            what_i_watch="Sir 的 Cursor 订阅状态（log 看到 Payment Failed）",
            why_i_care="Cursor 是 Sir 主要工作工具，订阅停 = 工作流断",
            severity=0.4,
            source='seeded',
            source_marker='P0+20-β.2.1',
            ttl_days=14,
        ),
        Concern(
            id='unfinished_jiazhao_ke1',
            what_i_watch="驾照科一复习进度（STM 多次提到，最近一周没碰）",
            why_i_care="Sir 自己定的承诺，半途而废会自责",
            severity=0.3,
            source='seeded',
            source_marker='P0+20-β.2.1',
        ),
        Concern(
            id='jarvis_keyrouter_health',
            what_i_watch="我自己的 google_1 永久死了 / 剩余 key 配额",
            why_i_care="我是 Sir 的工具，自己掉线就帮不了他了",
            severity=0.5,
            source='seeded',
            source_marker='P0+20-β.2.1',
            triggers_proactive=False,  # 这条只影响主对话语气，不主动 nudge
        ),
    ]

    count = 0
    for c in seeds:
        if ledger.register(c):
            count += 1
    return count


# ============================================================
# 单例
# ============================================================

_DEFAULT_LEDGER: Optional[ConcernsLedger] = None


def get_default_ledger() -> ConcernsLedger:
    global _DEFAULT_LEDGER
    if _DEFAULT_LEDGER is None:
        _DEFAULT_LEDGER = ConcernsLedger()
        bootstrap_default_concerns(_DEFAULT_LEDGER)
        _DEFAULT_LEDGER.load()
    return _DEFAULT_LEDGER


def reset_default_ledger_for_test() -> None:
    global _DEFAULT_LEDGER
    if _DEFAULT_LEDGER is not None:
        try:
            _DEFAULT_LEDGER.stop_decay_worker()
        except Exception:
            pass
    _DEFAULT_LEDGER = None
