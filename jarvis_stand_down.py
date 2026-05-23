# -*- coding: utf-8 -*-
"""[P5-fix25-stand-down / 2026-05-22] Stand Down 模式 — 听着但不出动作

Sir 真痛点: "我玩游戏 / 接电话 / 和爸妈说话时, 贾维斯一直回复挺尴尬的."
但又不能完全 mute (要保留上下文 / Sir 想 wake 时立即响应).

设计 (准则 6 三维耦合 + 4 问):
  1. 数据 publish SWM: stand_down_set / stand_down_clear event 进 ConversationEventBus
  2. 决策 LLM: 主脑听 Sir "stand down/嘘/接个电话/玩会儿游戏" 等, LLM 自决 emit
     FAST_CALL stand_down.set / clear (or 全局 hotkey Ctrl+Alt+J 直接调)
  3. 配置持久化 + CLI: memory_pool/stand_down_state.json + scripts/stand_down_dump.py
  4. 正交: 不和现有 sentinel 重复 — 这是新维度 (用户意图档位, 全局)

Reaction gate 规则 (Sir 选 A: 字幕和终端保留):
  - TTS voice         : OFF (强制 silence)
  - 字幕窗口          : ON (Sir 仍能看 Jarvis 内部 thinking)
  - 终端 log          : ON (始终保留)
  - Visual pulse 灯光 : OFF
  - Sensor (STT/screen): ON (要听 Sir 说话)
  - STM 写入          : ON (Sir 选 A — 上下文连续, 不丢真话)
  - Nudge 主动        : OFF (强制 silence)

Wake 路径:
  - 全局 hotkey Ctrl+Alt+J 再按一次 (toggle)
  - Sir 显式 'Jarvis 回来 / wake up' (主脑 LLM 自决 emit FAST_CALL clear)
  - One-shot summon: Sir 直接叫 Jarvis 问问题 → 答完自动回 stand_down (Sir 选 A)
  - Auto exit: 默认 30min, 最长 60min 防忘
  - Dashboard '立即 Wake' 按钮

Grace period (Sir 选 A):
  - 进 stand_down 后 15s 试探期, Sir 说话立即 cancel (防误触)

文件:
  - memory_pool/stand_down_state.json — current state (active/since/until/reason)
  - memory_pool/stand_down_history.jsonl — append-only 历史 (Reflector 学习习惯)
  - memory_pool/stand_down_trigger_vocab.json — Sir CLI 可改的触发短语 (准则 6.5)
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, List


# ============================================================
# 路径常量
# ============================================================
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_STATE_PATH = os.path.join(_REPO_ROOT, 'memory_pool', 'stand_down_state.json')
_HISTORY_PATH = os.path.join(_REPO_ROOT, 'memory_pool', 'stand_down_history.jsonl')
_VOCAB_PATH = os.path.join(_REPO_ROOT, 'memory_pool',
                                'stand_down_trigger_vocab.json')

# 默认值
DEFAULT_DURATION_MIN = 30
MAX_DURATION_MIN = 60
GRACE_PERIOD_S = 15.0


# ============================================================
# Reasons (semantic, 不是 enum 限制 — Sir 自由)
# ============================================================
REASON_PHONE = 'phone_call'
REASON_GAME = 'game'
REASON_FAMILY = 'family_chat'
REASON_FOCUS = 'deep_focus'
REASON_MANUAL = 'manual'  # Sir 直接按 hotkey, 没说原因


# ============================================================
# State dataclass
# ============================================================
@dataclass
class StandDownState:
    """当前 stand_down 状态. 序列化到 stand_down_state.json."""
    active: bool = False
    since_ts: float = 0.0          # 进入时间
    until_ts: float = 0.0          # 自动退出时间 (max 60min)
    reason: str = ''               # 'phone_call' / 'game' / 'family_chat' / 'manual' / ...
    exit_hint: str = ''            # LLM 自由文本, 主脑下轮看
    set_by_turn: str = ''          # 进入时 turn_id (LLM emit) 或 'cli' / 'hotkey'
    set_by_source: str = ''        # 'sir_voice' / 'cli' / 'hotkey'
    grace_until_ts: float = 0.0    # 试探期截止 (since + 15s)
    cleared_at_ts: float = 0.0     # 上次 clear 时间 (only meaningful when active=False)
    cleared_by_source: str = ''
    cleared_by_turn: str = ''
    # 🆕 [P5-fix25-phase3-one-shot / 2026-05-22] one-shot summon
    # Sir 在 stand_down 时叫 "Jarvis ..." → 当前轮 voice 不静默 (听 reply)
    # 答完 60s 后自动回全静默. Sir 选 A: 答完仍 stand_down (until_ts 不变).
    one_shot_until_ts: float = 0.0  # 当前轮 one-shot voice 窗口
    one_shot_turn: str = ''         # mark 时的 turn_id (debug)

    def is_active_now(self) -> bool:
        """是否当前 active (未到 until_ts)."""
        if not self.active:
            return False
        if self.until_ts > 0 and time.time() >= self.until_ts:
            return False
        return True

    def is_in_grace(self) -> bool:
        """是否在 15s 试探期内."""
        if not self.is_active_now():
            return False
        return time.time() < self.grace_until_ts

    def is_one_shot_active(self) -> bool:
        """是否在 one-shot summon 窗口期 (voice 临时不静默)."""
        if not self.is_active_now():
            return False
        if self.one_shot_until_ts <= 0:
            return False
        return time.time() < self.one_shot_until_ts

    def remaining_s(self) -> float:
        if not self.is_active_now():
            return 0.0
        if self.until_ts <= 0:
            return -1.0  # 永久 (理论上不应发生, max 60min)
        return max(0.0, self.until_ts - time.time())

    def elapsed_s(self) -> float:
        if self.since_ts <= 0:
            return 0.0
        return max(0.0, time.time() - self.since_ts)

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# 全局单例 + 锁 (主进程 + hotkey daemon + LLM 路径都共用)
# ============================================================
_LOCK = threading.RLock()
_STATE: Optional[StandDownState] = None
_AUTO_LOAD_DONE = False


def _ensure_loaded() -> StandDownState:
    """lazy init from disk (idempotent)."""
    global _STATE, _AUTO_LOAD_DONE
    with _LOCK:
        if _STATE is not None:
            return _STATE
        _STATE = _load_state_from_disk()
        _AUTO_LOAD_DONE = True
        return _STATE


def _load_state_from_disk() -> StandDownState:
    if not os.path.exists(_STATE_PATH):
        return StandDownState()
    try:
        with open(_STATE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return StandDownState()
        # 兼容字段缺失 (用 dataclass default)
        s = StandDownState()
        for k in s.__dataclass_fields__:
            if k in data:
                try:
                    setattr(s, k, data[k])
                except Exception:
                    pass
        # Disk reload: 校验是否过期 (Sir 可能停 Jarvis 后又开)
        if s.active and s.until_ts > 0 and time.time() >= s.until_ts:
            # 自动 timeout, 视为已 cleared
            s.active = False
            s.cleared_at_ts = s.until_ts
            s.cleared_by_source = 'auto_timeout_on_load'
        return s
    except Exception:
        return StandDownState()


def _save_state_to_disk(s: StandDownState) -> bool:
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        tmp = _STATE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(s.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, _STATE_PATH)
        return True
    except Exception:
        return False


def _append_history(record: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(_HISTORY_PATH), exist_ok=True)
        with open(_HISTORY_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
        return True
    except Exception:
        return False


def _publish_swm(etype: str, metadata: dict) -> None:
    try:
        from jarvis_utils import get_event_bus
        bus = get_event_bus()
        if bus is not None:
            desc = f"Stand Down: {etype} — {metadata.get('reason', '')}"
            bus.publish(
                etype=etype,
                description=desc,
                source='stand_down',
                metadata=metadata,
                ttl=3600.0 * 4,  # 4h (主脑下轮prompt 一般看不到 4h 前的)
            )
    except Exception:
        pass


def _bg_log(msg: str) -> None:
    try:
        from jarvis_utils import bg_log
        bg_log(msg)
    except Exception:
        pass


# ============================================================
# 🆕 [P5-fix25-stand-down-chime / 2026-05-22] Chime 进/出反馈 (默认 OFF)
# ============================================================
# Sir 20:07 真测反馈: "是你在放声音吗?! 好突兀的声音" — winsound.Beep 是
# PC speaker 硬件方波, 极刺耳. 改默认 OFF, 仅终端 + 字幕 + dashboard 反馈.
# 后续 Phase 2 可换 wav 文件 (柔和 ding) 或系统 message beep (Asterisk).
# 想试: 设 env JARVIS_STAND_DOWN_CHIME=1 临时打开.
# ============================================================
_CHIME_ENABLED = (os.environ.get('JARVIS_STAND_DOWN_CHIME', '0') == '1')


def _play_chime(direction: str) -> None:
    """Play short chime. direction='enter' | 'exit'. 默认 OFF.

    Sir 20:07 真测反馈 winsound.Beep 太突兀, 默认关. 仅 env=1 时开.

    改用 MessageBeep — 系统通知声, 比 Beep 柔和很多 (Windows 自带 wav, 跟
    Sir 平时听到的"消息提示音"一致, 不会突兀).
      enter (沉默): MB_ICONHAND (低沉系统通知)
      exit (回来):  MB_ICONASTERISK (轻快系统通知)

    Non-blocking — daemon thread 跑. 失败静默.
    """
    if not _CHIME_ENABLED:
        return
    try:
        import winsound
    except Exception:
        return

    def _worker():
        try:
            if direction == 'enter':
                # 进入沉默 — 系统询问音 (短低)
                winsound.MessageBeep(winsound.MB_ICONQUESTION)
            else:
                # 出沉默 — 系统通知音 (短亮)
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True,
                       name=f'StandDownChime/{direction}').start()


# ============================================================
# Public API — set / clear / get / is_active
# ============================================================
def set_stand_down(reason: str = REASON_MANUAL,
                       duration_min: float = DEFAULT_DURATION_MIN,
                       exit_hint: str = '',
                       source: str = 'sir_voice',
                       source_turn_id: str = '') -> StandDownState:
    """Sir 进入 stand_down 模式.

    Args:
        reason: 'phone_call' / 'game' / 'family_chat' / 'deep_focus' / 'manual' / ...
        duration_min: 自动 timeout 分钟 (默认 30, max 60)
        exit_hint: LLM 自由文本告诉自己 wake 条件 (e.g. "phone app loses focus
                  OR Sir says wake up")
        source: 'sir_voice' (主脑 LLM emit FAST_CALL) | 'cli' | 'hotkey'
        source_turn_id: 主脑 turn_id (如 source='sir_voice')

    Returns:
        新 StandDownState. 调用者可 inspect.
    """
    duration_min = max(1.0, min(float(duration_min), float(MAX_DURATION_MIN)))
    now = time.time()

    with _LOCK:
        s = _ensure_loaded()
        # 如果已经 active, 视为延期 (新 reason 覆盖, until_ts 重算)
        already_active = s.is_active_now()
        s.active = True
        s.since_ts = s.since_ts if already_active else now
        s.until_ts = now + duration_min * 60.0
        s.reason = reason or REASON_MANUAL
        s.exit_hint = exit_hint or ''
        s.set_by_turn = source_turn_id or source
        s.set_by_source = source
        # 重置 grace period (新 enter 都重置, 防止已经过的 grace 被沿用)
        s.grace_until_ts = now + GRACE_PERIOD_S
        # 清掉旧 cleared 字段 (新一轮 active)
        s.cleared_at_ts = 0.0
        s.cleared_by_source = ''
        s.cleared_by_turn = ''

        _save_state_to_disk(s)
        snapshot = StandDownState(**s.to_dict())  # copy for outer

    # SWM publish (锁外, 防止死锁)
    _publish_swm('stand_down_set', {
        'reason': snapshot.reason,
        'until_ts': snapshot.until_ts,
        'duration_min': duration_min,
        'source': source,
        'turn_id': source_turn_id,
        'exit_hint': snapshot.exit_hint,
        'already_active': already_active,
        'ts': now,
    })

    # History
    _append_history({
        'event': 'set' if not already_active else 'extend',
        'ts': now,
        'iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
        'reason': snapshot.reason,
        'duration_min': duration_min,
        'source': source,
        'turn_id': source_turn_id,
        'exit_hint': snapshot.exit_hint,
    })

    # 终端反馈
    eta = time.strftime('%H:%M', time.localtime(snapshot.until_ts))
    _bg_log(f"🌙 [StandDown] 进入沉默 reason={snapshot.reason} "
              f"until={eta} (~{int(duration_min)}min) "
              f"source={source} grace_until={int(GRACE_PERIOD_S)}s")

    # Chime (仅当真"进入" — 已 active 时延期不响, 防止刷屏)
    if not already_active:
        _play_chime('enter')

    return snapshot


def clear_stand_down(reason: str = '',
                          source: str = 'sir_voice',
                          source_turn_id: str = '') -> StandDownState:
    """Sir 退出 stand_down (wake up).

    Args:
        reason: 自由文本 (主脑或 Sir 解释)
        source: 'sir_voice' / 'cli' / 'hotkey' / 'auto_timeout' / 'grace_cancel'
        source_turn_id: turn_id

    Returns:
        新 StandDownState (active=False).
    """
    now = time.time()
    with _LOCK:
        s = _ensure_loaded()
        was_active = s.active
        prev_reason = s.reason
        prev_since = s.since_ts
        s.active = False
        s.cleared_at_ts = now
        s.cleared_by_source = source
        s.cleared_by_turn = source_turn_id or source
        # since/until/reason 字段保留 (history 信息), 不清

        _save_state_to_disk(s)
        snapshot = StandDownState(**s.to_dict())

    if was_active:
        _publish_swm('stand_down_clear', {
            'prev_reason': prev_reason,
            'duration_held_s': now - prev_since,
            'source': source,
            'turn_id': source_turn_id,
            'ts': now,
            'cleared_reason': reason,
        })
        _append_history({
            'event': 'clear',
            'ts': now,
            'iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
            'prev_reason': prev_reason,
            'duration_held_s': round(now - prev_since, 1),
            'source': source,
            'turn_id': source_turn_id,
            'cleared_reason': reason,
        })
        _bg_log(f"☀️ [StandDown] wake up source={source} "
                  f"(was {prev_reason}, held "
                  f"{int(now - prev_since)}s)")
        # Chime — 出 stand_down (明亮升序). grace_cancel 也响, Sir 想要反馈.
        _play_chime('exit')

    return snapshot


# ============================================================
# Query API — 各处 Reaction gate / prompt block 用
# ============================================================
def get_state() -> StandDownState:
    """快照. 不持续锁 (调用者后续 mutate state 自己保证 thread-safe)."""
    with _LOCK:
        s = _ensure_loaded()
        return StandDownState(**s.to_dict())


def is_active() -> bool:
    """当前是否处于 stand_down (考虑 timeout)."""
    with _LOCK:
        s = _ensure_loaded()
        return s.is_active_now()


def is_in_grace() -> bool:
    """是否在 15s 试探期内."""
    with _LOCK:
        s = _ensure_loaded()
        return s.is_in_grace()


def is_one_shot_active() -> bool:
    """🆕 [Phase 3] one-shot summon 窗口期内 (voice 临时不静默)."""
    with _LOCK:
        s = _ensure_loaded()
        return s.is_one_shot_active()


def mark_one_shot_summon(turn_id: str = '', duration_s: float = 60.0) -> bool:
    """🆕 [Phase 3] Sir 在 stand_down 时喊"Jarvis ..." → mark 当前轮 voice 不静默.

    Args:
        turn_id: 当前 turn_id (debug, 不强制)
        duration_s: one-shot 窗口期 (默认 60s, 主脑 reply 大概 5-30s 够)

    Returns:
        True if marked, False if 当前未在 stand_down (不需要 mark).
    """
    with _LOCK:
        s = _ensure_loaded()
        if not s.is_active_now():
            return False
        s.one_shot_until_ts = time.time() + max(5.0, min(duration_s, 120.0))
        s.one_shot_turn = (turn_id or '')[:60]
        _save_state_to_disk(s)

    _bg_log(f"🔉 [StandDown/OneShot] mark — Sir 叫 Jarvis 一轮, voice 临时开 "
              f"{int(duration_s)}s turn={turn_id[:20] if turn_id else 'unknown'}")
    return True


def clear_one_shot_summon() -> bool:
    """🆕 [Phase 3] turn 完后清 one-shot (back to 全静默)."""
    with _LOCK:
        s = _ensure_loaded()
        if s.one_shot_until_ts <= 0:
            return False
        s.one_shot_until_ts = 0.0
        s.one_shot_turn = ''
        _save_state_to_disk(s)
    return True


def should_silence_voice() -> bool:
    """[Reaction Gate] TTS voice 是否要静默. Stand Down active → True.

    🆕 [Phase 3] EXCEPT 在 one-shot summon 窗口期 (Sir 叫"Jarvis ..." 那一轮).
    """
    with _LOCK:
        s = _ensure_loaded()
        if not s.is_active_now():
            return False
        # active 但在 one-shot 窗口 → 不静默 (Sir 听 reply)
        if s.is_one_shot_active():
            return False
        return True


def should_silence_visual_pulse() -> bool:
    """[Reaction Gate] Visual pulse (灯光) 是否要静默. Stand Down active → True."""
    return is_active()


def should_silence_proactive_nudge() -> bool:
    """[Reaction Gate] Smart Nudge 是否要静默. Stand Down active → True."""
    return is_active()


def should_keep_subtitle() -> bool:
    """[Reaction Gate] 字幕是否仍显. Sir 选: 始终 ON (即使 stand_down 也保留).

    主脑可继续生成 silent_text 让 Sir 看到内部 thinking, 只是不出声.
    """
    return True  # 永远 ON (即使非 stand_down)


def should_keep_terminal_log() -> bool:
    """[Reaction Gate] 终端 log 是否保留. Sir 选: 始终 ON."""
    return True


# ============================================================
# Grace period 试探期 — Sir 说话取消
# ============================================================
def grace_cancel_if_in_grace(reason: str = 'Sir 说话, grace cancel') -> bool:
    """Voice listen 检测到 Sir 说话时调.

    如果当前在 grace_until_ts 内 (15s) → 自动 clear (视为误触发).
    返回是否真的 cancel 了.
    """
    with _LOCK:
        s = _ensure_loaded()
        if not s.is_active_now():
            return False
        if not s.is_in_grace():
            return False
    # 在 grace 内, cancel
    clear_stand_down(reason=reason, source='grace_cancel')
    return True


# ============================================================
# Prompt block — 给主脑 prompt 注入
# ============================================================
def render_prompt_block() -> str:
    """[STAND DOWN STATE] 主脑 prompt block. Sir 选: 字幕 + 终端 ON.

    主脑看到这个 block 自决: 不出 voice, 可出 silent_text (字幕),
    不出 visual_pulse, nudge 全 silenced.

    Returns:
        '' if not active, 否则返 multi-line block string (注入 prompt L2).
    """
    with _LOCK:
        s = _ensure_loaded()
        if not s.is_active_now():
            return ''
        snapshot = StandDownState(**s.to_dict())

    elapsed_min = int(snapshot.elapsed_s() / 60)
    remain_min = int(snapshot.remaining_s() / 60)
    in_grace = snapshot.is_in_grace()

    lines = [
        '[STAND DOWN STATE]',
        f'  Active     : true (since {time.strftime("%H:%M", time.localtime(snapshot.since_ts))}, '
        f'{elapsed_min}min ago)',
        f'  Reason     : {snapshot.reason or "manual"}',
        f'  Until      : {time.strftime("%H:%M", time.localtime(snapshot.until_ts))} '
        f'(in {remain_min}min) — auto wake at this time',
    ]
    if snapshot.exit_hint:
        lines.append(f'  Exit hint  : {snapshot.exit_hint[:200]}')
    if in_grace:
        grace_left_s = int(snapshot.grace_until_ts - time.time())
        lines.append(
            f'  Grace      : 试探期内 ({grace_left_s}s 剩) — Sir 任何说话会立即 cancel'
        )
    lines.extend([
        '',
        '  Reaction policy (Sir 选 A 字幕+终端保留):',
        '    - voice (TTS)         : OFF — 不要出声, 即使主脑想说',
        '    - 字幕 (silent_text)  : ON  — 仍可生成字幕给 Sir 看 (内部 thinking)',
        '    - visual pulse (灯光) : OFF — 不要点亮 orb',
        '    - 主动 nudge          : OFF — 不要主动开新话题',
        '',
        '  Wake 策略:',
        '    - Sir 显式 "Jarvis 回来 / wake up / 贾维斯醒醒" → emit FAST_CALL',
        '      <FAST_CALL>{"organ":"stand_down","command":"clear","params":{"reason":"Sir 说回来"}}</FAST_CALL>',
        '    - Sir one-shot summon (直接叫 Jarvis 问问题) → 答完仍保留 stand_down',
        '      (Sir 选 A: 一句问完不破坏全场沉默, until_ts 不变)',
        '    - 主脑可主动 propose clear if sensor 显电话挂断 + ~30s 静默, 但需明确 evidence',
    ]),
    return '\n'.join(lines)


# ============================================================
# Hotkey daemon — Ctrl+Alt+J global toggle
# ============================================================
# 用 GetAsyncKeyState polling (50ms tick), 已在 jarvis_env_probe 用
# 不需要新依赖 (跟 jarvis_env_probe 同源).
# 50ms × 20Hz, CPU 几乎 0.
# Rising edge detection (上一 tick 没按, 这 tick 按下 → toggle).
# ============================================================
_HOTKEY_THREAD: Optional[threading.Thread] = None
_HOTKEY_STOP = threading.Event()
_HOTKEY_RUNNING = False


def _hotkey_loop() -> None:
    """polling thread. Ctrl+Alt+J rising edge → toggle stand_down."""
    try:
        import ctypes
    except Exception:
        return

    user32 = ctypes.windll.user32
    VK_CONTROL = 0x11
    VK_MENU = 0x12  # Alt
    VK_J = 0x4A

    prev_pressed = False
    _bg_log("🎹 [StandDown/Hotkey] Ctrl+Alt+J listener 启动 (polling 50ms)")
    try:
        while not _HOTKEY_STOP.is_set():
            try:
                ctrl = user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
                alt = user32.GetAsyncKeyState(VK_MENU) & 0x8000
                j = user32.GetAsyncKeyState(VK_J) & 0x8000
                cur = bool(ctrl and alt and j)
                if cur and not prev_pressed:
                    # rising edge → toggle
                    # 🆕 [P5-fix68 / 2026-05-23 16:48] Sir 16:41 痛点 BUG-D:
                    # "C+B+J 静默模式唤醒没生效或没提示". Sir 真按错 hotkey (真是 Ctrl+Alt+J)
                    # 但即使按对也**没反馈** → Sir 不知道生效. 加显式 ack.
                    if is_active():
                        clear_stand_down(reason='hotkey toggle', source='hotkey')
                        try:
                            print("\n🌅 [StandDown/Hotkey] Sir 唤醒 (Ctrl+Alt+J)")
                            _bg_log("🌅 [StandDown/Hotkey] cleared via hotkey (Ctrl+Alt+J)")
                        except Exception:
                            pass
                    else:
                        set_stand_down(reason=REASON_MANUAL,
                                            duration_min=DEFAULT_DURATION_MIN,
                                            exit_hint='hotkey toggle (Sir 按 Ctrl+Alt+J)',
                                            source='hotkey')
                        try:
                            print("\n🌙 [StandDown/Hotkey] Sir 静默 (Ctrl+Alt+J), {0}min 自动唤醒".format(int(DEFAULT_DURATION_MIN)))
                            _bg_log(f"🌙 [StandDown/Hotkey] set via hotkey (Ctrl+Alt+J, {int(DEFAULT_DURATION_MIN)}min)")
                        except Exception:
                            pass
                prev_pressed = cur
            except Exception:
                pass
            _HOTKEY_STOP.wait(0.05)
    finally:
        _bg_log("🎹 [StandDown/Hotkey] listener 停止")


def start_hotkey_daemon() -> bool:
    """主进程启动时调. Idempotent."""
    global _HOTKEY_THREAD, _HOTKEY_RUNNING
    with _LOCK:
        if _HOTKEY_RUNNING and _HOTKEY_THREAD is not None and _HOTKEY_THREAD.is_alive():
            return True
        _HOTKEY_STOP.clear()
        _HOTKEY_THREAD = threading.Thread(target=_hotkey_loop,
                                                 daemon=True,
                                                 name='StandDownHotkey')
        _HOTKEY_THREAD.start()
        _HOTKEY_RUNNING = True
        return True


def stop_hotkey_daemon() -> bool:
    global _HOTKEY_RUNNING
    with _LOCK:
        _HOTKEY_STOP.set()
        _HOTKEY_RUNNING = False
        return True


# ============================================================
# Test helpers (testcase 用 — reset module state)
# ============================================================
def _reset_for_test(state_path: Optional[str] = None,
                       history_path: Optional[str] = None,
                       vocab_path: Optional[str] = None) -> None:
    """重置模块全局 + 切换 path (testcase 隔离用). NOT for production."""
    global _STATE, _AUTO_LOAD_DONE, _STATE_PATH, _HISTORY_PATH, _VOCAB_PATH
    with _LOCK:
        _STATE = None
        _AUTO_LOAD_DONE = False
        if state_path is not None:
            _STATE_PATH = state_path
        if history_path is not None:
            _HISTORY_PATH = history_path
        if vocab_path is not None:
            _VOCAB_PATH = vocab_path
