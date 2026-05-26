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

    # [P0+20-β.2.6 / 2026-05-17] Layer 5 alignment 统计
    aligned_count: int = 0          # SoulAlignmentEvaluator 判 aligned 累计
    missed_count: int = 0           # 同上 missed
    last_aligned_at: float = 0.0
    last_missed_at: float = 0.0

    # 🩹 [β.5.22-C / 2026-05-19] 动态语义反馈 (准则 6 核心修法).
    # Sir 01:34 痛点: "我说了喝了 6/7 杯, 那今天的喝水提醒只要再回应一次就该结束".
    # daily_progress: LLM 从 Sir 回应里抽出的"今天进度" — e.g. {"current": 6, "target": 8, "unit": "杯", "iso_date": "2026-05-19"}.
    # last_user_feedback: 最近一条 Sir 对此 concern 的回应 + LLM judgement.
    # optimal_timing: LLM 判的"合适提醒时机" — e.g. "before_sleep" / "morning" / "evening".
    # 影响 urgency 计算: 进度高 → urgency *= (1 - progress_ratio*0.7); optimal_timing 命中 → urgency *= 1.5.
    daily_progress: dict = field(default_factory=dict)
    last_user_feedback: dict = field(default_factory=dict)
    optimal_timing: str = ''        # 'before_sleep' / 'morning' / 'evening' / 'now' / ''

    # 🆕 [Sir 2026-05-26 20:14 真意 anchor 3] Skepticism Learning Loop field
    # ========================================================================
    # Sir 自然质疑某 concern (e.g. "为什么又提这个" 时 inject 命中此 concern) →
    # SirSkepticismDetector → AttributionEngine 匹到此 concern_id →
    # DecayEngine 累 skepticism_count + 降 severity. count=3 → auto dismiss.
    # 详 jarvis_sir_skepticism.py + docs/JARVIS_THINKING_TO_AGENCY_DESIGN.md §3.
    skepticism_count: int = 0

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

    def propose(self, concern: Concern) -> bool:
        """[P0+20-β.2.5 / 2026-05-17] WeeklyReflector 等自动来源 propose 新 concern。
        强制 state=STATE_REVIEW，等 Sir 拍板。返回是否新增。
        防 LLM 自作主张污染 Jarvis 的关心列表。详 docs/JARVIS_SOUL_DRIVE.md §5.2

        🩹 [β.2.8.13 / 2026-05-18] Sir 决定 WeeklyReflector 改 daily 触发, dedup 必加:
        - id 相同 → 拒
        - what_i_watch 字面 substring match → 拒 (主题相同换措辞 e.g.
          'Sir 熬夜' vs 'Sir 是否熬夜')
        - 与任何 state (active/review/archived) 的 concern 比较
        """
        concern.state = STATE_REVIEW
        # dedup
        try:
            new_id = concern.id
            new_watch_l = (concern.what_i_watch or '').lower().strip()
            for existing in self.concerns.values():
                if existing.id == new_id:
                    return False
                ex_watch_l = (existing.what_i_watch or '').lower().strip()
                if not new_watch_l or not ex_watch_l:
                    continue
                if new_watch_l == ex_watch_l:
                    return False
                # substring (one 包含 another) 且较短的 ≥ 15 字
                if (new_watch_l in ex_watch_l or ex_watch_l in new_watch_l):
                    if min(len(new_watch_l), len(ex_watch_l)) >= 15:
                        try:
                            from jarvis_utils import bg_log
                            bg_log(
                                f"🚫 [Concern/dedup] propose '{concern.id[:30]}' watch "
                                f"substring match vs '{existing.id[:30]}', skip"
                            )
                        except Exception:
                            pass
                        return False
        except Exception:
            pass
        return self.register(concern)

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

    def record_user_feedback(self, concern_id: str, raw_text: str,
                              judgement: dict) -> bool:
        """🩹 [β.5.22-C / 2026-05-19] 动态语义反馈 - Sir 主动说出关于某 concern 的进度/状态.

        Sir 01:34 痛点的核心修法: "我说了喝了 6/7 杯水了". LLM 判断后写回 ledger,
        urgency 计算时纳入 daily_progress → 当天不再重催, 但 optimal_timing 到了
        会反弹 (e.g. 睡前 30min 提醒喝最后一杯).

        judgement dict 应包含 (LLM 提取):
        - has_relevance: bool — 这条 Sir 回应是否真跟此 concern 相关
        - progress: dict | None — {"current": 6, "target": 8, "unit": "杯"} 或 None
        - severity_delta: float — 对 concern severity 的影响 (-1.0 to 1.0)
        - optimal_timing: str — "before_sleep" / "morning" / "" 等

        返 True 表示已写入, False = concern_id 不存在或 has_relevance=False.
        """
        if not judgement or not judgement.get('has_relevance'):
            return False
        with self._lock:
            c = self.concerns.get(concern_id)
            if c is None:
                return False
            now = time.time()
            today_iso = time.strftime('%Y-%m-%d', time.localtime(now))

            # 1. 更新 daily_progress (LLM 提取的进度)
            prog = judgement.get('progress') or None
            if prog and isinstance(prog, dict):
                # 跨天清零 — 新一天 progress 不沿用
                old_iso = (c.daily_progress or {}).get('iso_date', '')
                if old_iso != today_iso:
                    c.daily_progress = {}
                merged = dict(c.daily_progress or {})
                merged.update(prog)
                merged['iso_date'] = today_iso
                merged['last_updated'] = now
                c.daily_progress = merged

            # 2. last_user_feedback (调试 + L4 reflector 看)
            c.last_user_feedback = {
                'raw_text': str(raw_text or '')[:300],
                'judgement': judgement,
                'when': now,
                'when_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
            }

            # 3. optimal_timing 注入
            tm = judgement.get('optimal_timing') or ''
            if isinstance(tm, str) and tm:
                c.optimal_timing = tm[:32]

            # 4. severity 调整 (LLM 判断的 delta)
            sev_d = float(judgement.get('severity_delta', 0.0) or 0.0)
            if abs(sev_d) > 1e-3:
                c.severity = max(0.0, min(1.0, c.severity + sev_d))

            c.last_updated = now
            self._dirty = True

        # 🩹 [β.5.43-fix2-B / 2026-05-20 18:18] Sir 真理 — 统一 SWM evidence
        # ConcernFeedback 写 progress 后 publish 'sir_progress_evidence' SWM, 让
        # CommitmentWatcher / Memory Correction / ProfileCard 等 consumer 看同一
        # source, 避免多点 LLM 各自提取数据不一致.
        try:
            from jarvis_utils import get_event_bus as _geb
            _bus = _geb()
            if _bus is not None and prog and isinstance(prog, dict):
                _bus.publish(
                    etype='sir_progress_evidence',
                    description=(
                        f'Sir progress on {concern_id}: '
                        f'{prog.get("current", "?")} / {prog.get("target", "?")} '
                        f'{prog.get("unit", "")}'
                    ),
                    source='ConcernFeedback',
                    salience=0.65,
                    metadata={
                        'concern_id': concern_id,
                        'progress': prog,
                        'optimal_timing': judgement.get('optimal_timing', ''),
                        'severity_delta': sev_d,
                        'raw_text_excerpt': str(raw_text or '')[:200],
                    },
                    ttl=86400.0,  # 24h
                )
        except Exception:
            pass

        return True

    def record_alignment(self, concern_id: str, aligned: bool) -> bool:
        """[P0+20-β.2.6 / 2026-05-17] Layer 5 SoulAlignmentEvaluator 调。
        aligned=True → aligned_count++（Jarvis 本轮 honored 这条 concern）
        aligned=False → missed_count++（Jarvis 本轮 ignored 一条本应 reference 的 concern）
        统计用于未来 ConcernsReflector 优先级排序 & Sir 监控 alignment health。

        🩹 [P0+20-β.4.9 / 2026-05-19] aligned=True 时自动清 [pending_ack] tag.
        Sir 兑现承诺后 CommitmentWatcher 写 [pending_ack] 到 notes_for_self,
        主脑下次自然致意 → L5 评估 aligned → 此处清 tag, 防重复致意.
        通用化: 任何 concern 都走此 pipeline, 新 concern 0 改动.
        """
        with self._lock:
            c = self.concerns.get(concern_id)
            if c is None:
                return False
            now = time.time()
            if aligned:
                c.aligned_count += 1
                c.last_aligned_at = now
                # [β.4.9] 清 pending_ack tag (主脑已致意, 不再注入下轮)
                _notes = (c.notes_for_self or '')
                if '[pending_ack' in _notes:
                    import re as _re
                    _cleaned = _re.sub(
                        r'\s*\|?\s*\[pending_ack[^\]]*\][^\|]*',
                        '',
                        _notes,
                    ).strip(' |').strip()
                    c.notes_for_self = _cleaned[:600]
            else:
                c.missed_count += 1
                c.last_missed_at = now
            self._dirty = True
            return True

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

    # 🆕 [P5-fix24-concern-dismiss / 2026-05-22] Sir 18:42 痛点
    # =========================================================
    # Sir 真理: "我跟他说了很多次不要在意了, 他还是提, 感觉是我们没有
    # 语言控制长期关心的手段". concerns.json 没"主脑/Sir 显式 dismiss"路径,
    # 主脑嘴上说"I shall stop monitoring..." 但 state 仍 active, severity 仍 1.0.
    #
    # 设计 (准则 6 三维耦合):
    #   - 数据 publish SWM: concern_dismissed event 让 Reflector 看到 + 主脑下轮 prompt 知
    #   - 决策 LLM: 主脑听 Sir dismissal 类话 → emit FAST_CALL concern.dismiss
    #   - 持久化 + CLI: scripts/concerns_dump.py --dismiss / --reactivate
    #   - 正交: 软关闭 (triggers_proactive=False), 不动 state — Sir 问起仍可被动答
    # =========================================================
    def dismiss(self, concern_id: str, reason: str = '',
                  source: str = 'sir_voice',
                  source_turn_id: str = '',
                  severity_floor: float = 0.3) -> bool:
        """[P5-fix24-concern-dismiss / 2026-05-22] Sir 显式 dismiss.

        软关闭: triggers_proactive=False (不主动 nudge), severity 拉到 floor 以下
        (默认 0.3, 防止再被 SOUL inject 排 top), 写 signal + 持久化 + SWM publish.

        Args:
            concern_id: concern ID, 必须存在
            reason: Sir 原话 / dismiss 原因 (写进 signal + notes_for_self)
            source: 'sir_voice' (主脑 FAST_CALL) | 'cli' (Sir CLI 手动)
                   | 'reflector_auto' (后续 Phase 2: missed_count 自动 dismiss)
            source_turn_id: 主脑 turn_id (如 source='sir_voice')
            severity_floor: severity 上限封顶 (默认 0.3, 不再排 top concern)

        Returns:
            True if dismissed, False if concern_id 不存在.
        """
        with self._lock:
            c = self.concerns.get(concern_id)
            if c is None:
                return False
            c.triggers_proactive = False
            # severity 不归 0 (仍记录 Sir 关心程度), 但拉到 floor 以下不抢 top
            if c.severity > severity_floor:
                c.severity = severity_floor
            # signal 记一条 dismiss 事件 (Reflector / Sir CLI 可查)
            tag = f'[dismiss/{source}] '
            sig_what = (tag + (reason or 'no reason given'))[:200]
            c.recent_signals.append({
                'when': time.time(),
                'when_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                                time.localtime(time.time())),
                'what': sig_what,
                'severity_delta': 0,
                'turn_id': source_turn_id,
            })
            if len(c.recent_signals) > 10:
                c.recent_signals = c.recent_signals[-10:]
            # notes_for_self 记 (主脑下轮看)
            note_tag = f"[dismissed/{source}] {(reason or 'Sir dismissed')[:80]}"
            existing = c.notes_for_self or ''
            if note_tag not in existing:
                c.notes_for_self = (existing + ' | ' + note_tag).strip(' |')[:300]
            c.last_updated = time.time()
            self._dirty = True

        # SWM publish (Reflector + 主脑下轮 prompt 看)
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                bus.publish(
                    etype='concern_dismissed',
                    description=f"Sir dismissed concern {concern_id} via {source}",
                    source='concerns_ledger',
                    metadata={
                        'concern_id': concern_id,
                        'reason': (reason or '')[:200],
                        'source': source,
                        'turn_id': source_turn_id,
                        'ts': time.time(),
                    },
                    ttl=86400.0,  # 24h
                )
        except Exception:
            pass
        return True

    def reactivate(self, concern_id: str, reason: str = '',
                       source: str = 'sir_voice',
                       source_turn_id: str = '') -> bool:
        """[P5-fix24-concern-dismiss / 2026-05-22] Sir 撤销 dismiss, 重激活.

        triggers_proactive=True 复原, 写 signal, publish SWM event.
        severity 不动 (Sir 决定优先级, 由后续真实 signal 重 calibrate).
        """
        with self._lock:
            c = self.concerns.get(concern_id)
            if c is None:
                return False
            c.triggers_proactive = True
            tag = f'[reactivated/{source}] '
            sig_what = (tag + (reason or 'Sir asked to resume monitoring'))[:200]
            c.recent_signals.append({
                'when': time.time(),
                'when_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                                time.localtime(time.time())),
                'what': sig_what,
                'severity_delta': 0,
                'turn_id': source_turn_id,
            })
            if len(c.recent_signals) > 10:
                c.recent_signals = c.recent_signals[-10:]
            c.last_updated = time.time()
            self._dirty = True

        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                bus.publish(
                    etype='concern_reactivated',
                    description=f"Sir reactivated concern {concern_id} via {source}",
                    source='concerns_ledger',
                    metadata={
                        'concern_id': concern_id,
                        'reason': (reason or '')[:200],
                        'source': source,
                        'turn_id': source_turn_id,
                        'ts': time.time(),
                    },
                    ttl=86400.0,
                )
        except Exception:
            pass
        return True

    # =========================================================
    # 🆕 [P5-fix32-G / 2026-05-22] update_concern_field — 深度 update
    # =========================================================
    # Sir 21:55 mutation refactor Phase 2.1: Sir 想改 concern 的内容 (不只 dismiss).
    # 例:
    #   "睡眠 concern 别这么严肃, 我半夜画图也算工作" → 改 what_i_watch / why_i_care
    #   "把 cursor concern 严重度调低" → 改 severity
    #   "cursor concern 别 nudge" → 改 triggers_proactive=False (= dismiss 软关闭)
    # gateway 现在路由 'concerns.<cid>' → record_signal (改 severity_delta).
    # 加 'concerns.<cid>.<attr>' → update_concern_field (改字段).
    # 详 docs/JARVIS_MEMORY_AND_MUTATION_REFACTOR.md Part 6 Phase 2.1
    # =========================================================

    # 允许 update 的 Concern field 白名单 (防主脑乱改 schema).
    # 不含: id (改 id 会破 dedup), state (走 dismiss/reactivate), recent_signals
    # (signal 走 record_signal), last_updated (内部维护).
    _UPDATE_ALLOWED_FIELDS = frozenset({
        'what_i_watch', 'why_i_care', 'severity',
        'triggers_proactive', 'notes_for_self', 'optimal_timing',
        'ttl_days',
    })

    def update_concern_field(self, concern_id: str, field: str, new_value,
                                source: str = 'fast_call_mutation',
                                turn_id: str = '',
                                reason: str = '') -> tuple:
        """更新 concern 单个字段. 真改 + audit + SWM publish.

        Args:
          concern_id: target concern id
          field: top-level field name (must be in _UPDATE_ALLOWED_FIELDS)
          new_value: 新值
          source: caller 标识
          turn_id: trace id
          reason: Sir 原话 / 主脑解读

        Returns:
          (ok: bool, message: str, old_value: any)
        """
        if not concern_id:
            return False, 'empty concern_id', None
        if not field:
            return False, 'empty field', None
        if field not in self._UPDATE_ALLOWED_FIELDS:
            return (False,
                      f"field '{field}' not in allowed list "
                      f"(allowed: {sorted(self._UPDATE_ALLOWED_FIELDS)})",
                      None)

        with self._lock:
            c = self.concerns.get(concern_id)
            if c is None:
                return False, f'concern {concern_id} not found', None

            old_value = getattr(c, field, None)

            # No-op check
            if old_value == new_value:
                return True, f'no-op (concern.{field} already {str(new_value)[:40]})', old_value

            # Type coerce + validate
            try:
                if field == 'severity':
                    nv = max(0.0, min(1.0, float(new_value)))
                elif field == 'triggers_proactive':
                    if isinstance(new_value, str):
                        nv = new_value.strip().lower() in ('1', 'true', 'yes', 'on')
                    else:
                        nv = bool(new_value)
                elif field == 'ttl_days':
                    nv = max(1, min(3650, int(new_value)))
                elif field in ('what_i_watch', 'why_i_care'):
                    nv = str(new_value)[:500]
                elif field == 'notes_for_self':
                    nv = str(new_value)[:500]
                elif field == 'optimal_timing':
                    nv = str(new_value)[:32]
                else:
                    nv = new_value  # 不在 list 里 (不可达, 上面已 check)
            except (TypeError, ValueError) as _ve:
                return False, f'value coerce fail: {_ve}', old_value

            # 写入
            setattr(c, field, nv)
            # 加 signal 记录 (audit)
            tag = f'[update/{field}/{source}] '
            sig_what = (tag + (reason or f'changed to {str(nv)[:60]}'))[:200]
            c.recent_signals.append({
                'when': time.time(),
                'when_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                                time.localtime(time.time())),
                'what': sig_what,
                'severity_delta': 0,
                'turn_id': turn_id,
            })
            if len(c.recent_signals) > 10:
                c.recent_signals = c.recent_signals[-10:]
            c.last_updated = time.time()
            self._dirty = True

        # SWM publish (锁外)
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                bus.publish(
                    etype='concern_field_updated',
                    description=(
                        f"concern {concern_id}.{field} = "
                        f"'{str(nv)[:60]}' (was: '{str(old_value)[:40]}', "
                        f"src={source})"
                    ),
                    source='concerns_ledger',
                    salience=0.75,
                    metadata={
                        'concern_id': concern_id,
                        'field': field,
                        'old_value': str(old_value)[:200],
                        'new_value': str(nv)[:200],
                        'source': source,
                        'turn_id': turn_id,
                        'reason': reason[:200],
                    },
                    ttl=86400.0,
                )
        except Exception:
            pass

        return True, f"concern.{concern_id}.{field} updated", old_value

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
                        # [β.2.6] Layer 5 alignment 累计字段（旧 JSON 兼容默认 0）
                        aligned_count=int(data.get('aligned_count', 0)),
                        missed_count=int(data.get('missed_count', 0)),
                        last_aligned_at=float(data.get('last_aligned_at', 0.0)),
                        last_missed_at=float(data.get('last_missed_at', 0.0)),
                        # 🩹 [β.5.22-C / 2026-05-19] 动态语义反馈字段 (旧 JSON 兼容默认 空)
                        daily_progress=dict(data.get('daily_progress', {}) or {}),
                        last_user_feedback=dict(data.get('last_user_feedback', {}) or {}),
                        optimal_timing=str(data.get('optimal_timing', '') or ''),
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

        🩹 [P0+20-β.3.3 / 2026-05-17] 测试发现日期/数字（如 "22nd"）召回率仅 20%。
        改进：
        1. severity > 0.6 的 concern 用 [⚠ URGENT] 前缀
        2. concern 文本里的关键日期/数字用 「N」 显式高亮
        3. why_i_care 移到独立行（不挤一行）
        """
        import re as _re
        active = sorted(self.list_active(), key=lambda c: -c.severity)
        if not active:
            return ''
        top = active[:top_n]

        def _emphasize_facts(text: str) -> str:
            """关键日期/数字 → 「N」 形式高亮。"""
            # 月份+日 (May 22, May 12)
            text = _re.sub(r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2})\b',
                           r'「\1」', text)
            # 序数日 (22nd, 5th)
            text = _re.sub(r'\b(\d{1,2}(?:st|nd|rd|th))\b', r'「\1」', text)
            # 时间 (1:40 AM, 23:30)
            text = _re.sub(r'\b(\d{1,2}:\d{2}(?:\s*[AP]M)?)\b', r'「\1」', text)
            # N days running / N-day streak
            text = _re.sub(r'\b(\d+)\s+(days?|nights?|weeks?)\b', r'「\1 \2」', text)
            return text

        lines = ["=== MY SELF / SOUL ===",
                 "[CONCERNS I'M WATCHING — facts in 「」 are precise, do not paraphrase away]"]
        for c in top:
            urgent = " [⚠ URGENT]" if c.severity > 0.6 else ""
            severity_label = "high" if c.severity > 0.7 else "moderate" if c.severity > 0.4 else "low"
            watch = _emphasize_facts(c.what_i_watch[:120])
            lines.append(f"  - {c.id}{urgent} ({severity_label}, sev={c.severity:.2f}):"[:160])
            lines.append(f"      what I watch: {watch}"[:200])
            if c.why_i_care:
                why = _emphasize_facts(c.why_i_care[:80])
                lines.append(f"      why: {why}"[:160])
            # 🆕 [Sir 2026-05-25 20:23 真测 log 追根 BUG 治本] daily_progress 注入
            # =====================================================================
            # 源 BUG: Sir Turn 1 (concerns.progress_update sir_hydration_habit=1100) 后,
            # Turn 2 问"还差多少水", 主脑 prompt 看不到 current/target/unit → 去调
            # progress.status track_id='hydration_2026-05-25' (silo 错) → not found
            # → 迷茫输出 '---'. 真因: to_prompt_block 漏 daily_progress 注入.
            # 治本: 把 LLM 已写的 daily_progress (current/target/unit) 注入主脑 prompt,
            # 主脑直接答"还差 1900ml", 不需杀 tool. 准则 6 evidence-driven.
            # =====================================================================
            try:
                dp = getattr(c, 'daily_progress', {}) or {}
                if dp:
                    today_iso = time.strftime('%Y-%m-%d', time.localtime())
                    if dp.get('iso_date') == today_iso:
                        _cur = dp.get('current', '?')
                        _tgt = dp.get('target', '?')
                        _unit = dp.get('unit', '')
                        # remaining (主脑可直接答, 不用算) — current 是数才 derive
                        _rem_str = ''
                        try:
                            _rem = float(_tgt) - float(_cur)
                            if _rem > 0:
                                _rem_str = f", remaining 「{_rem:g} {_unit}」"
                        except (TypeError, ValueError):
                            pass
                        lines.append(
                            f"      today progress: 「{_cur}/{_tgt} {_unit}」{_rem_str}"
                            [:200]
                        )
            except Exception:
                pass
            if c.recent_signals:
                last = c.recent_signals[-1]
                what = _emphasize_facts(last.get('what', '')[:80])
                if what:
                    lines.append(f"      recent signal: {what}"[:160])
            # 🚨 [Sir 2026-05-26 12:28 真痛 CRITICAL] notes_for_self 主脑必须看见
            # =====================================================================
            # 源 BUG: ConcernsLedger.to_prompt_block 漏 inject notes_for_self,
            # → Sir 12:28 真痛 anchor: "保证贾维斯的思考是真能调整他的行为, 而不是
            # 一个展示在面板给我看的玩具".
            # Phase B (adjust_concern_notes) + dismiss + pending_ack + snooze 都写
            # notes_for_self, 设计意图就是主脑下轮看见自调行为, 但 prompt 完全
            # 不显示 → 全废. dismiss 注释 L458 写 "notes_for_self 记 (主脑下轮看)"
            # — 设计就该 inject, 但代码漏了.
            # 修: cap 200 char (够主脑读 "DO NOT volunteer this topic" 这类 guidance),
            # 用 ⚠ 前缀让主脑视觉抢眼. 准则 5 言出必行 + 6 evidence-driven.
            # =====================================================================
            try:
                _notes = (c.notes_for_self or '').strip()
                if _notes:
                    lines.append(
                        f"      ⚠ note to self: {_notes[:200]}"[:240]
                    )
            except Exception:
                pass
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
            lines.append(
                f"{'id':32}{'sev':>6}  {'src':<14}{'aligned/missed':<16}what_i_watch"
            )
            lines.append("-" * 100)
            for c in sorted(active, key=lambda x: -x.severity):
                # [β.2.6] aligned_count / missed_count (Layer 5 累计)
                ali_miss = f"{c.aligned_count}/{c.missed_count}"
                lines.append(
                    f"{c.id:32}{c.severity:>6.2f}  {c.source:<14}"
                    f"{ali_miss:<16}{c.what_i_watch[:40]}"
                )
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
