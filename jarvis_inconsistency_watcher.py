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

import json
import os
import threading
import time
from typing import Dict, List, Optional, Tuple

try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(msg: str) -> None:
        print(msg)


# ============================================================
# 🩹 [P0+20-β.3.4-vocab4 / 2026-05-18] 准则 6.5 vocab 持久化
# 原 class attributes _SIR_SLEEP_VERBS / _SIR_BREAK_VERBS / _JARVIS_WRAPPER_MARKERS
# 迁 memory_pool/inconsistency_vocab.json + scripts/inconsistency_vocab_dump.py.
# 范式照搬 β.3.0-vocab1 (tool_intent) commit 63611f3.
# ============================================================

_SEED_SLEEP_COMMITMENT_VERBS: Tuple[str, ...] = (
    # EN
    'i will sleep', "i'll sleep", 'i shall sleep', 'i am going to bed',
    "i'm going to bed", 'i need to sleep', 'going to bed now',
    'i will rest', "i'll rest", 'i am off to bed', "i'm off to bed",
    'going to crash', 'turning in', 'time for bed',
    # ZH
    '我去睡', '我要睡', '我先睡', '我睡了', '睡觉去', '我上床',
    '我去休息', '我先休息', '休息一下', '准备睡', '该睡了',
)
_SEED_BREAK_COMMITMENT_VERBS: Tuple[str, ...] = (
    'i will take a break', "i'll take a break", 'i need a break',
    'i am going on break', "i'm taking a breather",
    '我去休息一下', '我先歇会', '我去走两步', '我先停一下',
)
_SEED_WRAPPER_EXCLUSION_MARKERS: Tuple[str, ...] = (
    '监督您', '监督你', '留意您', '留意你', '提醒您', '提醒你',
    '盯着您', '盯着你', '看着您', '看着你', '在此时叫', '到时叫',
    'i shall hold you', 'i will hold you', "i'll hold you",
    'i shall remind', 'i will remind', "i'll remind",
    'i shall watch', 'i will watch', "i'll watch",
    'i shall keep an eye', "i'll keep an eye", 'i will keep an eye',
    'i shall monitor', 'i will monitor', "i'll monitor",
)

_INCONSISTENCY_VOCAB_PATH = os.path.join(
    'memory_pool', 'inconsistency_vocab.json')
_INCONSISTENCY_CACHE: Optional[Dict[str, Tuple[str, ...]]] = None
_INCONSISTENCY_MTIME: float = 0.0


def _load_inconsistency_vocab_from_json() -> Optional[Dict[str, Tuple[str, ...]]]:
    """从 json 加载 active pattern 分类 → keyword tuple. 失败返 None."""
    if not os.path.exists(_INCONSISTENCY_VOCAB_PATH):
        return None
    try:
        with open(_INCONSISTENCY_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        by_cat: Dict[str, List[str]] = {
            'sleep_commitment': [],
            'break_commitment': [],
            'wrapper_exclusion': [],
        }
        for p in data.get('patterns', []):
            if not isinstance(p, dict):
                continue
            if p.get('state') != 'active':
                continue
            cat = p.get('category', '')
            if cat not in by_cat:
                continue
            for kw in (p.get('keywords') or []):
                if isinstance(kw, str) and kw.strip():
                    by_cat[cat].append(kw.lower().strip())
        # 任一类空就走 fallback (避免 json 只配了部分时 broken)
        if not all(by_cat.values()):
            return None
        return {k: tuple(v) for k, v in by_cat.items()}
    except Exception:
        return None


def _get_inconsistency_vocab() -> Dict[str, Tuple[str, ...]]:
    """🩹 [β.3.4-vocab4] mtime cache. 文件变自动 reload."""
    global _INCONSISTENCY_CACHE, _INCONSISTENCY_MTIME
    try:
        mtime = os.path.getmtime(_INCONSISTENCY_VOCAB_PATH) if os.path.exists(
            _INCONSISTENCY_VOCAB_PATH) else 0
    except OSError:
        mtime = 0
    if _INCONSISTENCY_CACHE is None or mtime > _INCONSISTENCY_MTIME:
        loaded = _load_inconsistency_vocab_from_json()
        if loaded is not None:
            _INCONSISTENCY_CACHE = loaded
        else:
            _INCONSISTENCY_CACHE = {
                'sleep_commitment': _SEED_SLEEP_COMMITMENT_VERBS,
                'break_commitment': _SEED_BREAK_COMMITMENT_VERBS,
                'wrapper_exclusion': _SEED_WRAPPER_EXCLUSION_MARKERS,
            }
        _INCONSISTENCY_MTIME = mtime
    return _INCONSISTENCY_CACHE


def get_sir_sleep_verbs() -> Tuple[str, ...]:
    return _get_inconsistency_vocab().get('sleep_commitment',
                                            _SEED_SLEEP_COMMITMENT_VERBS)


def get_sir_break_verbs() -> Tuple[str, ...]:
    return _get_inconsistency_vocab().get('break_commitment',
                                            _SEED_BREAK_COMMITMENT_VERBS)


def get_jarvis_wrapper_markers() -> Tuple[str, ...]:
    return _get_inconsistency_vocab().get('wrapper_exclusion',
                                            _SEED_WRAPPER_EXCLUSION_MARKERS)


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
    """主动性 B — 检测 Sir 表态-行为反差, 给 ProactiveCare 注入 signal.

    🩹 [β.5.15 / 2026-05-19] β.5 重构收尾 - 准则 6 数据强耦合:
      1. 加 nudge_gate 引用 (publish_only 模式下永真, 但跨源 cooldown 统一)
      2. 所有 skip 路径 (startup_guard / global_cooldown / per_promise_cooldown) publish
         'gate_advice' source='InconsistencyWatcher' 到 SWM. sal=0.15 不污染默认 evidence.
      3. _dispatch 前调 gate.can_speak (跟 CommitmentWatcher 一致) 让 NudgeGate 知道.
    """

    def __init__(self, worker, central_nerve=None,
                  tick_interval_s: float = TICK_INTERVAL_S,
                  nudge_gate=None):
        super().__init__(daemon=True, name='InconsistencyWatcher')
        self.worker = worker
        self.nerve = central_nerve
        self.gate = nudge_gate  # [β.5.15] NudgeGate 引用 (publish_only 永真)
        self.tick = tick_interval_s
        self._stop = threading.Event()
        # 🩹 [β.2.9.7] key 从 promise.id 改成 (desc+deadline+reply)[:160] hash:
        # 跨 session register 同主题不同 id 也共用 cooldown, 不再 "新 id 重新计时".
        self._fired_promises: dict = {}      # cooldown_key (str) → last_fire_ts
        self._last_any_fire_ts: float = 0.0  # 全局节流
        self._daemon_start_ts: float = time.time()  # 🩹 startup guard 基准
        # [β.5.15] skip publish dedupe (60s 内同 reason 1 次)
        self._skip_publish_last_t: dict = {}

    def _publish_skip(self, skip_reason: str, extra_meta: dict = None):
        """[β.5.15] skip 时 publish 'gate_advice' 到 SWM (跟 WellnessGuardian 同设计).

        sal=0.15 < 0.3 SWM render floor: 写历史不污染主脑 evidence. dedupe 60s.
        """
        try:
            _now = time.time()
            _last = self._skip_publish_last_t.get(skip_reason, 0)
            if _now - _last < 60.0:
                return
            self._skip_publish_last_t[skip_reason] = _now
            # GC 5min 以前
            self._skip_publish_last_t = {
                k: v for k, v in self._skip_publish_last_t.items()
                if _now - v < 300
            }
            from jarvis_utils import get_event_bus
            _bus = get_event_bus()
            if _bus is None:
                return
            meta = {
                'decision': 'block',
                'block_reason': skip_reason,
            }
            if extra_meta:
                meta.update(extra_meta)
            _bus.publish(
                etype='gate_advice',
                description=f"InconsistencyWatcher skipped tick: {skip_reason}",
                source='InconsistencyWatcher',
                metadata=meta,
                salience=0.15,
            )
        except Exception:
            pass

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
    # 监督 Sir, 不是 Sir 自承诺) 被误判 is_sleep=True 反复 fire.
    #
    # 🩹 [β.3.4-vocab4 / 2026-05-18] 准则 6.5 vocab 迁 module-level:
    # 原 class attributes _SIR_SLEEP_VERBS / _SIR_BREAK_VERBS /
    # _JARVIS_WRAPPER_MARKERS → memory_pool/inconsistency_vocab.json.
    # 改用 get_sir_sleep_verbs() / get_sir_break_verbs() / get_jarvis_wrapper_markers().
    def _is_sir_sleep_commitment(self, p) -> bool:
        """准则 6: 主体是 Sir + 动词是 sleep, 排除 Jarvis wrapper.
        看 description (优先 Sir 原话). 不看 jarvis_reply 整段, 那是 Jarvis 包装话."""
        desc_l = (p.description or '').lower().strip()
        if not desc_l:
            return False
        if any(w in desc_l for w in get_jarvis_wrapper_markers()):
            return False
        return any(v in desc_l for v in get_sir_sleep_verbs())

    def _is_sir_break_commitment(self, p) -> bool:
        desc_l = (p.description or '').lower().strip()
        if not desc_l:
            return False
        if any(w in desc_l for w in get_jarvis_wrapper_markers()):
            return False
        return any(v in desc_l for v in get_sir_break_verbs())

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

        🩹 [β.5.15 / 2026-05-19] 前置 NudgeGate.can_speak (跟 CommitmentWatcher 一致):
        publish_only 模式下永真但跨源 cooldown 统一. NudgeGate 标 last_nudge_time
        让 Conductor/SmartNudge inter_source_cooldown 知道刚 fire 过 inconsistency.
        """
        # [β.5.15] gate check: 让 NudgeGate 看到这次 nudge (publish_only 永真)
        if self.gate is not None and not self.gate.can_speak('companion',
                is_urgent=False, nudge_type='proactive_care'):
            self._publish_skip('nudge_gate_block_proactive_care',
                                {'promise_id': getattr(p, 'id', '?')[:40]})
            return
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
            # 🆕 [C3.1 tap / 2026-06-08] behavior-preserving: 记一条 E_commit 债
            # (承诺完整性误差)。只新增记账调用, 不改上面 fire/cooldown 原逻辑。
            # ref=promise_id (grounded)。独立 try/except — 记账失败不影响 fire。
            try:
                from jarvis_coherence_debt import tap_inconsistency
                tap_inconsistency(str(getattr(p, 'id', '') or ''),
                                  detail=inconsistency_desc[:80])
            except Exception:
                pass
        except Exception as e:
            bg_log(f"⚠️ [InconsistencyWatcher] dispatch err: {e}")

    def _tick(self) -> None:
        # 🩹 [β.2.9.7] 启动 guard — 进程刚起来 5min 内只观察, 不发声.
        # 防"跨 session 残留 promise 在启动瞬间被一次 fire 完". 现实 wake-time
        # callback 由 ReturnSentinel 接管, InconsistencyWatcher 只管"刚承诺转头反悔".
        _now = time.time()
        if _now - self._daemon_start_ts < STARTUP_GUARD_S:
            # [β.5.15] startup_guard skip → publish 到 SWM
            _remain = int(STARTUP_GUARD_S - (_now - self._daemon_start_ts))
            self._publish_skip(f'startup_guard_{_remain}s_remaining',
                                {'startup_guard_remaining_s': _remain})
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
        if _now - self._last_any_fire_ts < GLOBAL_COOLDOWN_S:
            # [β.5.15] global_cooldown skip → publish 到 SWM
            _gap = int(_now - self._last_any_fire_ts)
            _remain = int(GLOBAL_COOLDOWN_S - _gap)
            self._publish_skip(f'global_cooldown_{_remain}s_remaining',
                                {'global_cooldown_remaining_s': _remain,
                                 'last_fire_age_s': _gap})
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


def ensure_inconsistency_watcher_started(worker, central_nerve=None,
                                            nudge_gate=None) -> None:
    """[β.5.15] 加 nudge_gate 参数让 InconsistencyWatcher 也走 NudgeGate."""
    global _DEFAULT_WATCHER
    with _LOCK:
        if _DEFAULT_WATCHER is None and worker is not None:
            _DEFAULT_WATCHER = InconsistencyWatcher(worker, central_nerve,
                                                      nudge_gate=nudge_gate)
            _DEFAULT_WATCHER.start()


def get_default_watcher() -> Optional[InconsistencyWatcher]:
    return _DEFAULT_WATCHER
