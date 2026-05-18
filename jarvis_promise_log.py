# -*- coding: utf-8 -*-
"""
[P0+20-β.2.8.5 / 2026-05-17] PromiseExecutionLog — Jarvis 承诺生命周期可观察账本

Sir 22:25 反馈痛点:
> "贾维斯说话能不能和行为一致这个事情让我很困扰. 她说她会更新相应的状态,
>  更新了吗? 要不把贾维斯每次出现承诺的时候的承诺行为日志放出来让我知道?
>  任何一个他表态的事情都要有对应的日志."

设计:
- 每条 Jarvis 自承诺 (SelfPromiseDetector 识别) → register → 拿 promise_id
- 后续 N 分钟监听 fast_call 完成 / state 变更 / 主动 nudge / commitment_watcher 触发
  → mark_fulfilled(promise_id, evidence)
- 超过 deadline 仍 pending → mark_overdue
- N 小时无任何 evidence 关联 → mark_untracked (诚实标记: "我说了但没监控到执行")
- 终端可见 + scripts/promise_tail.py 可读 + JSON 持久化

承诺状态机:
    pending → fulfilled (有 evidence)
    pending → overdue (deadline 过)
    pending → untracked (24h 无 evidence + 也无 deadline → 我们无法验证)
    pending → cancelled (Sir 显式撤销)
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict

try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(msg: str) -> None:
        print(msg)


STATE_PENDING = 'pending'
STATE_FULFILLED = 'fulfilled'
STATE_OVERDUE = 'overdue'
STATE_UNTRACKED = 'untracked'
STATE_CANCELLED = 'cancelled'

DEFAULT_LOG_PATH = os.path.join('memory_pool', 'jarvis_promise_log.json')
UNTRACKED_AFTER_HOURS = 24.0    # 无 evidence 24h → untracked
MAX_KEEP_PROMISES = 500          # 内存最多保 500 条 (老的归档/丢弃)


@dataclass
class Promise:
    id: str
    description: str
    kind: str = 'soft'                # hard/soft
    deadline_str: str = ''
    jarvis_reply: str = ''
    turn_id: str = ''
    lang: str = ''
    state: str = STATE_PENDING
    registered_at: float = field(default_factory=time.time)
    fulfilled_at: float = 0.0
    evidence: List[Dict] = field(default_factory=list)   # [{when, kind, what}]

    def add_evidence(self, kind: str, what: str) -> None:
        self.evidence.append({
            'when': time.time(),
            'when_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
            'kind': kind,
            'what': what[:200],
        })

    def to_dict(self) -> dict:
        return asdict(self)


class PromiseExecutionLog:
    """所有 Jarvis 承诺的生命周期账本. 线程安全."""

    def __init__(self, persist_path: Optional[str] = None):
        self.persist_path = persist_path or DEFAULT_LOG_PATH
        self.promises: Dict[str, Promise] = {}
        self._lock = threading.Lock()
        self._load()

    def _new_id(self) -> str:
        return 'p_' + uuid.uuid4().hex[:8]

    def register(self, description: str, kind: str = 'soft',
                  deadline_str: str = '', jarvis_reply: str = '',
                  turn_id: str = '', lang: str = '') -> str:
        # 🩹 [β.2.9.7 / 2026-05-18] Sir 09:06 实测痛点: InconsistencyWatcher 反复
        # 提醒同一旧承诺. 根因之一: register 没 dedup, 每次 startup / 测试 / 同
        # session 内同 desc + deadline_str 重复 register 新 ID, 老的也仍 pending.
        # 修: 同 (description, deadline_str) 在 1h 内已 pending → 返回老 ID, 不
        # 重复 register. 准则 6 — 不写"特定关键词忽略", 用通用语义.
        # 5min → 3600s: Sir 08:24/08:42/09:00 三次启动间隔 18-30min 超 5min 窗口,
        # 真生产场景 Sir 也不会 1h 内重复说"我11点睡", 1h 是安全裕度.
        # 同时加 jarvis_reply hash 旁路: 即便超 1h, 但 desc+deadline+reply 完全一致
        # → 几乎必然是测试/启动重放, 也复用. 真实 Sir 重新表态 reply 不会逐字相同.
        with self._lock:
            try:
                _now = time.time()
                _desc_key = (description or '')[:300].strip().lower()
                _dl_key = (deadline_str or '').strip().lower()
                _reply_key = (jarvis_reply or '')[:200].strip().lower()
                for _existing in self.promises.values():
                    if _existing.state != STATE_PENDING:
                        continue
                    if (_existing.description or '').strip().lower() != _desc_key:
                        continue
                    if (_existing.deadline_str or '').strip().lower() != _dl_key:
                        continue
                    _age = _now - _existing.registered_at
                    _reply_same = (
                        _reply_key and
                        (_existing.jarvis_reply or '')[:200].strip().lower() == _reply_key
                    )
                    # 1h 内同 desc+deadline OR 任何 age 下 desc+deadline+reply 完全一致
                    if _age < 3600.0 or _reply_same:
                        bg_log(
                            f"♻️ [PromiseLog] dedup reuse {_existing.id} "
                            f"age={int(_age)}s reply_same={_reply_same} "
                            f"'{description[:50]}'"
                        )
                        return _existing.id
            except Exception:
                pass
            pid = self._new_id()
            # 🩹 [β.2.8.6 / 2026-05-17] Sir 实测发现 jarvis_reply 200 截断让
            # context 匹配漏关键词. 扩到 1200 (大约 200 英文 word, 涵盖大多数 reply).
            p = Promise(
                id=pid, description=description[:300], kind=kind,
                deadline_str=deadline_str, jarvis_reply=jarvis_reply[:1200],
                turn_id=turn_id, lang=lang,
            )
            self.promises[pid] = p
            self._evict_old_locked()
            self._dirty = True
        try:
            self._persist()
        except Exception:
            pass
        bg_log(f"📝 [PromiseLog] register {pid} kind={kind} '{description[:60]}'")
        return pid

    def mark_fulfilled(self, promise_id: str, evidence_kind: str,
                        evidence_what: str) -> bool:
        with self._lock:
            p = self.promises.get(promise_id)
            if p is None or p.state != STATE_PENDING:
                return False
            p.state = STATE_FULFILLED
            p.fulfilled_at = time.time()
            p.add_evidence(evidence_kind, evidence_what)
        try:
            self._persist()
        except Exception:
            pass
        elapsed = int(time.time() - p.registered_at)
        line = (
            f"✅ [Jarvis Promise FULFILLED] {promise_id} '{p.description[:60]}' "
            f"by {evidence_kind} ({evidence_what[:60]}) — {elapsed}s after promise"
        )
        print(line)
        bg_log(line)
        return True

    def add_evidence_only(self, promise_id: str, evidence_kind: str,
                            evidence_what: str) -> bool:
        """记 evidence 但不变 state. 给"半完成"行为用 (例: 提到 keyrouter 但没真 check)."""
        with self._lock:
            p = self.promises.get(promise_id)
            if p is None:
                return False
            p.add_evidence(evidence_kind, evidence_what)
        try:
            self._persist()
        except Exception:
            pass
        return True

    def mark_overdue(self, promise_id: str) -> bool:
        with self._lock:
            p = self.promises.get(promise_id)
            if p is None or p.state != STATE_PENDING:
                return False
            p.state = STATE_OVERDUE
        try:
            self._persist()
        except Exception:
            pass
        line = f"⏰ [Jarvis Promise OVERDUE] {promise_id} '{p.description[:60]}'"
        print(line)
        bg_log(line)
        return True

    def mark_untracked(self, promise_id: str) -> bool:
        with self._lock:
            p = self.promises.get(promise_id)
            if p is None or p.state != STATE_PENDING:
                return False
            p.state = STATE_UNTRACKED
        try:
            self._persist()
        except Exception:
            pass
        line = f"❓ [Jarvis Promise UNTRACKED] {promise_id} '{p.description[:60]}' (24h 无 evidence, 我说了但无法验证执行)"
        print(line)
        bg_log(line)
        return True

    def mark_cancelled(self, promise_id: str, reason: str = '') -> bool:
        with self._lock:
            p = self.promises.get(promise_id)
            if p is None or p.state != STATE_PENDING:
                return False
            p.state = STATE_CANCELLED
            p.add_evidence('cancelled', reason)
        try:
            self._persist()
        except Exception:
            pass
        line = f"🚫 [Jarvis Promise CANCELLED] {promise_id} '{p.description[:60]}' reason={reason}"
        print(line)
        bg_log(line)
        return True

    def list_pending(self) -> List[Promise]:
        with self._lock:
            return [p for p in self.promises.values() if p.state == STATE_PENDING]

    def list_recent(self, limit: int = 20) -> List[Promise]:
        with self._lock:
            arr = sorted(self.promises.values(),
                          key=lambda p: -p.registered_at)
            return arr[:limit]

    def get(self, pid: str) -> Optional[Promise]:
        return self.promises.get(pid)

    def find_pending_matching(self, description_keywords: List[str],
                                max_age_s: float = 600.0) -> Optional[Promise]:
        """找 pending 的 promise 含 keyword 匹配 description **或** jarvis_reply 整段.

        🩹 [β.2.8.5 hotfix / 2026-05-17] Sir 22:39 实测痛点:
        promise.description='I shall adjust my monitoring accordingly' 字面没含
        'sleep' / 'streak', 但同一回复整段提了 sleep/curfew/cervical. 改 scan
        jarvis_reply 让 evidence 能命中"上下文相关 promise".
        """
        if not description_keywords:
            return None
        kws_l = [k.lower() for k in description_keywords if k and len(k) >= 3]
        if not kws_l:
            return None
        now = time.time()
        with self._lock:
            cands = []
            for p in self.promises.values():
                if p.state != STATE_PENDING:
                    continue
                if now - p.registered_at > max_age_s:
                    continue
                blob_l = (p.description + ' ' + p.jarvis_reply).lower()
                hits = sum(1 for k in kws_l if k in blob_l)
                if hits >= 1:
                    cands.append((hits, p))
        if not cands:
            return None
        # 优先 hits 多的, 再按时间最新
        cands.sort(key=lambda x: (-x[0], -x[1].registered_at))
        return cands[0][1]

    def stats(self) -> dict:
        with self._lock:
            total = len(self.promises)
            states = {'pending': 0, 'fulfilled': 0, 'overdue': 0,
                      'untracked': 0, 'cancelled': 0}
            kinds = {'hard': 0, 'soft': 0}
            for p in self.promises.values():
                states[p.state] = states.get(p.state, 0) + 1
                kinds[p.kind] = kinds.get(p.kind, 0) + 1
            return {'total': total, 'states': states, 'kinds': kinds}

    def sweep_untracked(self) -> int:
        """定期跑: 把 24h 无 evidence 的 pending → untracked. 返回扫到数."""
        n = 0
        cutoff = time.time() - UNTRACKED_AFTER_HOURS * 3600
        with self._lock:
            for p in list(self.promises.values()):
                if p.state != STATE_PENDING:
                    continue
                if p.registered_at > cutoff:
                    continue
                if p.evidence:
                    continue
                p.state = STATE_UNTRACKED
                n += 1
        if n > 0:
            try:
                self._persist()
            except Exception:
                pass
            line = f"❓ [Jarvis Promise] sweep_untracked: {n} pending → untracked (24h no evidence)"
            print(line)
            bg_log(line)
        return n

    # ---- 持久化 ----

    def _evict_old_locked(self) -> None:
        """超容量按 registered_at 老的丢, 但保留 pending."""
        if len(self.promises) <= MAX_KEEP_PROMISES:
            return
        finished = [p for p in self.promises.values()
                     if p.state != STATE_PENDING]
        finished.sort(key=lambda p: p.registered_at)
        excess = len(self.promises) - MAX_KEEP_PROMISES
        for p in finished[:excess]:
            self.promises.pop(p.id, None)

    def _persist(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.persist_path) or '.', exist_ok=True)
            with open(self.persist_path, 'w', encoding='utf-8') as f:
                snapshot = {pid: p.to_dict() for pid, p in self.promises.items()}
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load(self) -> None:
        if not os.path.exists(self.persist_path):
            return
        try:
            with open(self.persist_path, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
            for pid, pd in data.items():
                try:
                    p = Promise(**pd)
                    self.promises[pid] = p
                except Exception:
                    continue
        except Exception:
            pass


# ============================================================
# 单例 + 便捷 API
# ============================================================

_DEFAULT_LOG: Optional[PromiseExecutionLog] = None
_LOCK = threading.Lock()


def get_default_log() -> PromiseExecutionLog:
    global _DEFAULT_LOG
    with _LOCK:
        if _DEFAULT_LOG is None:
            _DEFAULT_LOG = PromiseExecutionLog()
        return _DEFAULT_LOG


def reset_default_log_for_test(persist_path: Optional[str] = None) -> None:
    """重置单例. 可指定 persist_path 让单测彻底隔离 (默认 magic 'NO_PERSIST' 用 /dev/null 等价)."""
    global _DEFAULT_LOG
    with _LOCK:
        _DEFAULT_LOG = None
        if persist_path is not None:
            # 立刻预创单例使 get_default_log 返这个隔离实例
            _DEFAULT_LOG = PromiseExecutionLog(persist_path=persist_path)


# ============================================================
# Sweep daemon: 每 1h 跑 sweep_untracked
# ============================================================

class PromiseSweepDaemon(threading.Thread):
    """每 1h 跑 sweep_untracked 让超过 24h 无 evidence 的 pending → untracked.
    Sir 一打开 promise_tail.py 不再看到一堆永远 pending 的'诚信赤字'."""

    def __init__(self, interval_s: float = 3600.0):
        super().__init__(daemon=True, name='PromiseSweepDaemon')
        self.interval = interval_s
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        time.sleep(60)
        while not self._stop.is_set():
            try:
                log = get_default_log()
                log.sweep_untracked()
            except Exception as e:
                bg_log(f"⚠️ [PromiseSweep] err: {e}")
            self._stop.wait(self.interval)


_SWEEP_DAEMON: Optional[PromiseSweepDaemon] = None


def ensure_sweep_daemon_started() -> None:
    global _SWEEP_DAEMON
    with _LOCK:
        if _SWEEP_DAEMON is None:
            _SWEEP_DAEMON = PromiseSweepDaemon()
            _SWEEP_DAEMON.start()


def evidence_keywords_from_text(text: str) -> List[str]:
    """从一段 Jarvis 自言文本抽 keyword (粗略, 用于匹配 promise.description)."""
    if not text:
        return []
    import re
    words = re.findall(r'[a-zA-Z\u4e00-\u9fff]{3,}', text.lower())
    stop = {'the', 'and', 'for', 'with', 'that', 'this', 'sir', 'jarvis',
            'will', 'shall', 'should', 'about'}
    return [w for w in words if w not in stop][:20]


def try_pair_evidence(evidence_kind: str, evidence_what: str,
                       max_match_age_s: float = 600.0) -> Optional[str]:
    """便捷: 给一段 evidence (e.g. fast_call done / state update),
    自动找最近 pending promise 含相关 keyword → mark_fulfilled.
    返回匹配到的 promise_id (没匹配返回 None).
    """
    log = get_default_log()
    kws = evidence_keywords_from_text(evidence_what)
    if not kws:
        return None
    p = log.find_pending_matching(kws, max_age_s=max_match_age_s)
    if p is None:
        return None
    log.mark_fulfilled(p.id, evidence_kind, evidence_what)
    return p.id
