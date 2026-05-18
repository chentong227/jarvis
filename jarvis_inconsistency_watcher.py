# -*- coding: utf-8 -*-
"""
[P0+20-β.2.9.3 / 2026-05-18] Commitment Inconsistency Watcher — 主动性 B

Sir 例子 (00:55 → 01:04 reactivate):
  Sir 说 "去睡了" → PromiseLog 注册 hard promise
  → 9 min 内 wake_word "Jarvis"
  → Jarvis 应该主动 callback "您不是说去睡了吗?"

扩展方向 B 设计:
- daemon 每 60s 跑 inconsistency check
- 对每条 pending hard promise, 看是否有 evidence Sir 行为反差
- 命中 → push __NUDGE__ proactive_care nudge (走 ProactiveCare 通道, 复用现有 channel)

类型枚举:
- 'sir_said_sleep_but_active': Sir 说睡了但 < 30min 又 wake_word / 键鼠活跃
- 'sir_said_break_but_alt_tab': Sir 说休息但还在频繁切窗
- 'sir_said_X_but_did_Y' (LLM-driven, 未来)

设计原则 (Sir 准则 6 拒绝硬编码):
- 不为每个 inconsistency type 写硬规则
- 给 ProactiveCare 一个 signal source — 让 ProactiveCare 看 promise 描述 +
  当前 sensor + STM, 自己判 inconsistency 是否真存在
- 复用 ProactiveCareEngine 的 dry_run / cooldown / channel 升级机制
"""

from __future__ import annotations

import threading
import time
from typing import List, Optional

try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(msg: str) -> None:
        print(msg)


TICK_INTERVAL_S = 60.0           # 每 60s 跑一次 check
MIN_PROMISE_AGE_S = 60.0          # promise 注册 < 60s 不检查 (Sir 还没真行动)
MAX_PROMISE_AGE_S = 3600.0        # promise > 1h 太老不查
COOLDOWN_PER_PROMISE_S = 1800.0   # 同 promise 30min 内最多 fire 1 次


class InconsistencyWatcher(threading.Thread):
    """主动性 B — 检测 Sir 表态-行为反差, 给 ProactiveCare 注入 signal."""

    def __init__(self, worker, central_nerve=None,
                  tick_interval_s: float = TICK_INTERVAL_S):
        super().__init__(daemon=True, name='InconsistencyWatcher')
        self.worker = worker
        self.nerve = central_nerve
        self.tick = tick_interval_s
        self._stop = threading.Event()
        self._fired_promises: dict = {}  # promise_id → last_fire_ts

    def stop(self) -> None:
        self._stop.set()

    def _check_one_promise(self, p) -> Optional[str]:
        """检查一条 pending promise 是否和当前 Sir 状态反差.
        返回 inconsistency 描述 (str) 或 None.
        """
        # 1. age 窗口
        age = time.time() - p.registered_at
        if age < MIN_PROMISE_AGE_S or age > MAX_PROMISE_AGE_S:
            return None
        # 2. cooldown 防重复
        if self._fired_promises.get(p.id, 0) > 0 and \
                (time.time() - self._fired_promises[p.id]) < COOLDOWN_PER_PROMISE_S:
            return None
        # 3. 内容判定 — 启发式: promise 含 'sleep/睡/rest/休息' 时, 看 Sir 是否真去睡了
        desc_l = (p.description + ' ' + p.jarvis_reply).lower()
        is_sleep = any(kw in desc_l for kw in
                        ('sleep', 'bed', 'rest', '睡', '休息', '上床'))
        is_break = any(kw in desc_l for kw in
                        ('break', 'pause', '休息一下', 'take a break'))
        if not (is_sleep or is_break):
            return None
        # 4. 看当前 Sir 状态
        try:
            import win32api
            idle_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
        except Exception:
            idle_ms = 0
        # Sir 在 30s 内有键鼠活动 + active_conversation → 反差
        try:
            vt = getattr(self.worker, 'voice_thread', None)
            in_conv = vt is not None and getattr(vt, 'in_active_conversation', False)
        except Exception:
            in_conv = False

        if is_sleep:
            # sleep promise: idle < 30s + active_conv = 没真睡
            if idle_ms < 30000 and in_conv:
                return (
                    f"Sir said he'd sleep {int(age/60)} min ago "
                    f"('{p.description[:60]}') but is active and chatting again"
                )
            # idle < 60s (碰了下键鼠) + 不在对话 = 边缘 inconsistency (轻)
            if idle_ms < 60000 and age > 300:
                return (
                    f"Sir said he'd sleep {int(age/60)} min ago "
                    f"but keyboard/mouse just stirred"
                )
        if is_break:
            # break promise: 还在 alt-tab 频繁
            try:
                from jarvis_env_probe import PhysicalEnvironmentProbe as P
                snap = P.get_sensor_snapshot() or {}
                sw5 = snap.get('switch_frequency_5min', 0)
                if sw5 >= 10:
                    return (
                        f"Sir said he'd break {int(age/60)} min ago but is "
                        f"alt-tabbing rapidly ({sw5}/5min)"
                    )
            except Exception:
                pass
        return None

    def _dispatch(self, p, inconsistency_desc: str) -> None:
        """把 inconsistency 信号转成 __NUDGE__ proactive_care channel.

        复用 ProactiveCareEngine 现有发送通道, 让主脑自己决定 callback 话术
        (准则 6 不教句式). 复用 ProactiveCare cooldown / channel 升级.
        """
        try:
            import json
            directive = (
                "You are about to make a brief proactive remark to Sir based on a\n"
                "behavioral inconsistency you noticed.\n\n"
                f"[INCONSISTENCY DETECTED]\n"
                f"  {inconsistency_desc}\n"
                f"  Sir's original words: \"{p.jarvis_reply[:120]}\"\n\n"
                "[STYLE]\n"
                "- Speak in your own voice (准则 6 — no fixed phrasing).\n"
                "- Mild, playful callback acceptable if it fits — not preachy.\n"
                "- Reference the gap honestly (e.g. 'you said sleep 9 min ago')\n"
                "  but don't lecture. Sir is an adult.\n"
                "- ONE sentence, ≤ 20 words English + ZH translation.\n"
            )
            nudge_ctx = {
                'type': 'proactive_care',
                'channel': 'voice',
                'nudge_directive': directive,
                'concern_id': 'inconsistency_callback',
                'source': 'InconsistencyWatcher',
                'inconsistency_kind': inconsistency_desc[:60],
            }
            payload = "__NUDGE__:" + json.dumps(nudge_ctx, ensure_ascii=False)
            self.worker.push_command(payload)
            bg_log(
                f"⚖️ [InconsistencyWatcher] FIRE promise={p.id} "
                f"inconsistency='{inconsistency_desc[:80]}'"
            )
            self._fired_promises[p.id] = time.time()
        except Exception as e:
            bg_log(f"⚠️ [InconsistencyWatcher] dispatch err: {e}")

    def _tick(self) -> None:
        # 🩹 [β.2.9.6 audit] 清理过期 _fired_promises (cooldown 2 倍后清除, 防内存泄漏)
        try:
            now = time.time()
            cutoff = now - COOLDOWN_PER_PROMISE_S * 2
            self._fired_promises = {
                pid: ts for pid, ts in self._fired_promises.items()
                if ts > cutoff
            }
        except Exception:
            pass
        try:
            from jarvis_promise_log import get_default_log
            log = get_default_log()
            pendings = log.list_pending()
        except Exception:
            return
        if not pendings:
            return
        for p in pendings:
            desc = self._check_one_promise(p)
            if desc:
                self._dispatch(p, desc)
                break  # 一次 tick 只 fire 1 个, 防 spam

    def run(self) -> None:
        time.sleep(20)
        bg_log(f"⚖️ [InconsistencyWatcher] started (tick={self.tick}s)")
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                bg_log(f"⚠️ [InconsistencyWatcher] tick err: {e}")
            self._stop.wait(self.tick)


_DEFAULT_WATCHER: Optional[InconsistencyWatcher] = None
_LOCK = threading.Lock()


def ensure_inconsistency_watcher_started(worker, central_nerve=None) -> None:
    global _DEFAULT_WATCHER
    with _LOCK:
        if _DEFAULT_WATCHER is None and worker is not None:
            _DEFAULT_WATCHER = InconsistencyWatcher(worker, central_nerve)
            _DEFAULT_WATCHER.start()


def get_default_watcher() -> Optional[InconsistencyWatcher]:
    return _DEFAULT_WATCHER
