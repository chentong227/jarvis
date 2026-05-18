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
# 🩹 [β.2.9.7 / 2026-05-18] Sir 09:06 实测痛点: 反复提醒老旧 promise.
# 旧 1h 太宽 (新启动只要 < 1h 都 fire). 缩到 30min — 真正"刚说就反悔"才有意义,
# 跨 session 不再追老的"我会监督您".
MAX_PROMISE_AGE_S = 1800.0
COOLDOWN_PER_PROMISE_S = 1800.0   # 同 promise 30min 内最多 fire 1 次
# 🩹 [β.2.9.7] 全局节流: 任意 fire 5min 内不再 fire (即便不同 promise)
GLOBAL_COOLDOWN_S = 300.0
# 🩹 [β.2.9.7 / 2026-05-18] 双道兜底, 防 dedup / age 任一失效仍刷屏:
#   STARTUP_GUARD_S: daemon 启动后 5min 静默 — 进程刚起来 register dedup 还没生效,
#                    跨 session 老 promise 加载完不应立刻被 fire (Sir 实测痛点).
#   ABS_AGE_HARD_LIMIT_S: 任何 promise registered_at 早于 12h 一律拒查, 跨日残留绝缘.
#                          (即便 MAX_PROMISE_AGE_S 调宽, 这道仍是最终底线.)
STARTUP_GUARD_S = 300.0
ABS_AGE_HARD_LIMIT_S = 12 * 3600.0


class InconsistencyWatcher(threading.Thread):
    """主动性 B — 检测 Sir 表态-行为反差, 给 ProactiveCare 注入 signal."""

    def __init__(self, worker, central_nerve=None,
                  tick_interval_s: float = TICK_INTERVAL_S):
        super().__init__(daemon=True, name='InconsistencyWatcher')
        self.worker = worker
        self.nerve = central_nerve
        self.tick = tick_interval_s
        self._stop = threading.Event()
        # 🩹 [β.2.9.7] key 从 promise.id 改成 (desc+deadline+reply)[:160] hash:
        # 跨 session register 同主题不同 id 也共用 cooldown, 不再 "新 id 重新计时".
        self._fired_promises: dict = {}      # cooldown_key (str) → last_fire_ts
        self._last_any_fire_ts: float = 0.0  # 全局节流
        self._daemon_start_ts: float = time.time()  # 🩹 startup guard 基准

    @staticmethod
    def _cooldown_key(p) -> str:
        """跨 session 等价 promise 共用 cooldown. desc[:120]+deadline+reply[:60]."""
        import hashlib
        desc = (getattr(p, 'description', '') or '')[:120].strip().lower()
        dl = (getattr(p, 'deadline_str', '') or '').strip().lower()
        rep = (getattr(p, 'jarvis_reply', '') or '')[:60].strip().lower()
        return hashlib.md5(
            f"{desc}|{dl}|{rep}".encode('utf-8', errors='replace')
        ).hexdigest()[:16]

    def stop(self) -> None:
        self._stop.set()

    # 🩹 [β.2.9.7 / 2026-05-18] 准则 6 主体判定 — 正向 first-person + sleep verb,
    # 排除 wrapper. 治 Sir 09:06 实测痛点: "我会监督您在 13:05 准时休息" (Jarvis
    # 监督 Sir, 不是 Sir 承诺睡) 被误判 is_sleep=True 反复 fire.
    #
    # 反例 wrapper (Jarvis 代理人称, 不是 Sir 自承诺):
    #   "我会监督您..." / "I shall hold you to..." / "I'll remind you..." /
    #   "I shall watch over your sleep" / "我会留意您..."
    # 正例 (Sir 自承诺 sleep):
    #   "I'm going to bed" / "我去睡了" / "I'll sleep at 11" / "I'm about to rest"
    _SIR_SLEEP_VERBS = (
        'i will sleep', "i'll sleep", 'i shall sleep', 'i am going to bed',
        "i'm going to bed", 'i need to sleep', 'going to bed now',
        'i will rest', "i'll rest", 'i am off to bed', "i'm off to bed",
        'going to crash', 'turning in', 'time for bed',
        '我去睡', '我要睡', '我先睡', '我睡了', '睡觉去', '我上床',
        '我去休息', '我先休息', '休息一下', '准备睡', '该睡了',
    )
    _JARVIS_WRAPPER_MARKERS = (
        '监督您', '监督你', '留意您', '留意你', '提醒您', '提醒你', '盯着您', '盯着你',
        '看着您', '看着你', '在此时叫', '到时叫',
        'i shall hold you', 'i will hold you', "i'll hold you",
        'i shall remind', 'i will remind', "i'll remind",
        'i shall watch', 'i will watch', "i'll watch",
        'i shall keep an eye', "i'll keep an eye", 'i will keep an eye',
        'i shall monitor', 'i will monitor', "i'll monitor",
    )

    def _is_sir_sleep_commitment(self, p) -> bool:
        """准则 6: 主体是 Sir + 动词是 sleep, 排除 Jarvis wrapper.
        看 description (优先 Sir 原话). 不看 jarvis_reply 整段, 那是 Jarvis 包装话."""
        desc_l = (p.description or '').lower().strip()
        if not desc_l:
            return False
        if any(w in desc_l for w in self._JARVIS_WRAPPER_MARKERS):
            return False
        return any(v in desc_l for v in self._SIR_SLEEP_VERBS)

    _SIR_BREAK_VERBS = (
        'i will take a break', "i'll take a break", 'i need a break',
        'i am going on break', "i'm taking a breather",
        '我去休息一下', '我先歇会', '我去走两步', '我先停一下',
    )

    def _is_sir_break_commitment(self, p) -> bool:
        desc_l = (p.description or '').lower().strip()
        if not desc_l:
            return False
        if any(w in desc_l for w in self._JARVIS_WRAPPER_MARKERS):
            return False
        return any(v in desc_l for v in self._SIR_BREAK_VERBS)

    def _check_one_promise(self, p) -> Optional[str]:
        """检查一条 pending promise 是否和当前 Sir 状态反差.
        返回 inconsistency 描述 (str) 或 None.
        """
        # 0. 🩹 [β.2.9.7] ABS 硬上限 — 12h 前的 promise 绝不查 (跨日残留兜底)
        age = time.time() - p.registered_at
        if age > ABS_AGE_HARD_LIMIT_S:
            return None
        # 1. age 窗口
        if age < MIN_PROMISE_AGE_S or age > MAX_PROMISE_AGE_S:
            return None
        # 2. 🩹 [β.2.9.7] cooldown 升级 — key 改用 (desc+deadline+reply)[:160] hash,
        #    跨 session 同主题不同 pid 都视为同条 cooldown, 不再 "新 id 重新计时"
        ckey = self._cooldown_key(p)
        last_fired_ts = self._fired_promises.get(ckey, 0)
        if last_fired_ts > 0 and (time.time() - last_fired_ts) < COOLDOWN_PER_PROMISE_S:
            return None
        # 🩹 [β.2.9.7] kind 必须 hard — soft 没有 deadline, 不应作"反差"判定基础
        if getattr(p, 'kind', 'soft') != 'hard':
            return None
        # 3. 内容判定 — 准则 6: 主体判定 (Sir 自承诺 sleep), 不只看 keyword
        is_sleep = self._is_sir_sleep_commitment(p)
        is_break = self._is_sir_break_commitment(p)
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
            # 🩹 [β.2.9.7] cooldown key 用主题 hash (跨 id 同主题等价), 同时记
            # 全局 last_any_fire_ts 触发 GLOBAL_COOLDOWN_S 节流.
            self._fired_promises[self._cooldown_key(p)] = time.time()
            self._last_any_fire_ts = time.time()
        except Exception as e:
            bg_log(f"⚠️ [InconsistencyWatcher] dispatch err: {e}")

    def _tick(self) -> None:
        # 🩹 [β.2.9.7] 启动 guard — 进程刚起来 5min 内只观察, 不发声.
        # 防"跨 session 残留 promise 在启动瞬间被一次 fire 完". 现实 wake-time
        # callback 由 ReturnSentinel 接管, InconsistencyWatcher 只管"刚承诺转头反悔".
        if time.time() - self._daemon_start_ts < STARTUP_GUARD_S:
            return
        # 🩹 [β.2.9.6 audit] 清理过期 _fired_promises (cooldown 2 倍后清除, 防内存泄漏)
        try:
            now = time.time()
            cutoff = now - COOLDOWN_PER_PROMISE_S * 2
            self._fired_promises = {
                k: ts for k, ts in self._fired_promises.items()
                if ts > cutoff
            }
        except Exception:
            pass
        # 🩹 [β.2.9.7] 全局节流: 任意 fire 5min 内不再 fire
        if time.time() - self._last_any_fire_ts < GLOBAL_COOLDOWN_S:
            return
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
                self._last_any_fire_ts = time.time()
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
