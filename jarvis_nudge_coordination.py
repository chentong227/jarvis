# -*- coding: utf-8 -*-
"""[P5-fixC / 2026-05-21 09:50] β.5.0 行为弱耦合 — 多 sentinel proactive nudge 协调.

Sir 09:05/06/12 真测痛点: ReturnSentinel return_greeting fire 后 55s SmartNudge
commitment_check 又 fire, 7min 内 Conductor offer_help 第三次 fire — 3 个 sentinel
各自 hard fire 不知道彼此, Sir 醒来收 3 连数落.

不加硬编码 cooldown 数字 — 改 evidence-driven:
- 任一 sentinel fire __NUDGE__ → publish SWM 'proactive_nudge_fired' (含 kind + sentinel)
- 别的 sentinel 在 fire 前调 should_yield_to_recent_proactive_nudge() 看 SWM 自决
- 命中 → publish 'proactive_nudge_skipped_due_to_recent' + 退化 publish-only (不 push __NUDGE__)
- Sir 一旦回应 (主对话路径), 不会 publish proactive_nudge_fired, gate 自然释放

数字 600s 是 "single morning conversation block" 物理时长边界 (跟 nudge_window /
afk_return cooldown 同档物理边界), 不是行为 cooldown 硬编码.

跟 NudgeGate (跨 center 硬 cooldown) 互补不替: NudgeGate 防 spam, 此 module 防
multi-sentinel 同时段抢话筒.

详 docs/JARVIS_SOUL_DRIVE.md §4.3 "每条路径都受益".
"""

from typing import Tuple, Optional


def should_yield_to_recent_proactive_nudge(
    within_s: float = 600.0,
    current_kind: str = '',
    current_sentinel: str = '',
    exempt_kinds: Optional[set] = None,
) -> Tuple[bool, str]:
    """检查是否该退化为 publish-only 让位最近一个 proactive nudge.

    Args:
        within_s: 看 SWM 多久内的 proactive_nudge_fired event (默认 600s = 10min,
                  跟 nudge_window 同物理边界, 不是硬 cooldown).
        current_kind: 当前要 fire 的 nudge kind (e.g. 'commitment_check', 'offer_help').
        current_sentinel: 当前 sentinel 名 (e.g. 'SmartNudge', 'Conductor').
        exempt_kinds: 这些 kind 不退化 (e.g. 自己 vs 自己, 真紧急绕过). 默认空.

    Returns:
        (should_yield, reason): 
          - should_yield=True: 让位, caller 应 publish skip event + 不 push __NUDGE__
          - reason: 字符串解释 (log + skip event metadata)
    """
    exempt_kinds = exempt_kinds or set()

    try:
        from jarvis_utils import get_event_bus as _geb
        bus = _geb()
        if bus is None:
            return False, 'no_event_bus'
        top = bus.top_n(n=20)
        for e in top:
            if e.get('type') != 'proactive_nudge_fired':
                continue
            age = e.get('_age_s', 9999)
            if age > within_s:
                continue
            meta = e.get('metadata') or {}
            other_kind = meta.get('kind', '')
            other_sentinel = meta.get('sentinel', '')

            # 自己的 fire 不算让位 (e.g. SmartNudge 不应让位自己上一个 SmartNudge)
            if other_sentinel == current_sentinel and other_kind == current_kind:
                continue

            # exempt: 调用方明确说"这种 kind 不让位"
            if other_kind in exempt_kinds:
                continue

            return True, (
                f'recent_nudge:{other_sentinel}/{other_kind} fired {int(age)}s ago'
            )
        return False, 'no_recent_proactive_nudge'
    except Exception as e:
        return False, f'exception:{type(e).__name__}'


def publish_proactive_nudge_fired(
    kind: str,
    sentinel: str,
    salience: float = 0.6,
    extra_metadata: Optional[dict] = None,
) -> bool:
    """fire __NUDGE__ 后调此 publish SWM event 让别人能让位.

    🆕 [Sir 2026-05-24 23:31 真测追根 + 准则 6 优雅治本]
    Sir 真测: SmartNudge 12s 内 commitment_check 连推 2 次.
    根因: 第 2 次 fire 时 SWM 中 12s 前 fired evidence salience=0.6, 主脑权重平等
          看到但不当回事 — 仍 voice.
    优雅修法 (零硬 cooldown, 符合准则 6): 自检最近 60s 同 kind 已 fire N 次 → 当前
          salience boost 到 critical (0.92+). evidence 显眼, 主脑 SWM 自决 [SILENCE].
    """
    try:
        import time
        from jarvis_utils import get_event_bus as _geb
        bus = _geb()
        if bus is None:
            return False

        # 🆕 自检: 60s 内同 kind 已 fire N 次 → salience boost
        # N=1 (本次是 60s 内第 2 次) → 0.85
        # N=2 (本次是 60s 内第 3 次) → 0.92 critical
        # N>=3 (60s 内第 4+ 次) → 0.98 极高
        boost_count = 0
        boost_note = ''
        try:
            top = bus.top_n(n=30)
            for e in top:
                if e.get('type') != 'proactive_nudge_fired':
                    continue
                if e.get('_age_s', 9999) > 60:
                    continue
                m = e.get('metadata') or {}
                if m.get('kind') == kind:
                    boost_count += 1
            if boost_count >= 3:
                salience = max(salience, 0.98)
                boost_note = f' [{boost_count + 1}th fire in 60s — DEFAULT [SILENCE]]'
            elif boost_count >= 2:
                salience = max(salience, 0.92)
                boost_note = f' [{boost_count + 1}rd fire in 60s — reconsider [SILENCE]]'
            elif boost_count >= 1:
                salience = max(salience, 0.85)
                boost_note = f' [{boost_count + 1}nd fire in 60s]'
        except Exception:
            pass

        meta = {
            'kind': kind,
            'sentinel': sentinel,
            'fired_at': time.time(),
            'same_kind_fires_60s': boost_count + 1,
        }
        if extra_metadata:
            meta.update(extra_metadata)
        bus.publish(
            etype='proactive_nudge_fired',
            description=f"{kind} fired by {sentinel}{boost_note}",
            source=sentinel,
            salience=salience,
            metadata=meta,
        )
        return True
    except Exception:
        return False


def publish_proactive_nudge_skipped(
    kind: str,
    sentinel: str,
    reason: str,
    extra_metadata: Optional[dict] = None,
) -> bool:
    """让位时调此 publish SWM trace event."""
    try:
        import time
        from jarvis_utils import get_event_bus as _geb
        bus = _geb()
        if bus is None:
            return False
        meta = {
            'kind': kind,
            'sentinel': sentinel,
            'reason': reason,
            'skipped_at': time.time(),
        }
        if extra_metadata:
            meta.update(extra_metadata)
        bus.publish(
            etype='proactive_nudge_skipped_due_to_recent',
            description=f"{kind} skipped by {sentinel}: {reason}",
            source=sentinel,
            salience=0.3,  # 比 fired 低, 不抢主脑注意力
            metadata=meta,
        )
        return True
    except Exception:
        return False
