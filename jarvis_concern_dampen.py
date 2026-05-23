# -*- coding: utf-8 -*-
"""[P5-fix45 / 2026-05-23 14:55] CONCERN_DAMPEN tag parser — 主脑自决调 concern severity.

Sir 14:51 真测痛点 ('链路是否实现?'):
  Sir 说 '我中午睡了 1 小时' → mutation organ ✅ 写 ProfileCard.daily_logs.
  但 sir_sleep_streak severity 没削 → ProactiveCare 仍 fire concern. Sir: '链路没实现'.

Sir 真意 (β.5.0 三维耦合 / 准则 8):
  '不要堆 LLM, 不要 hot-fix cooldown, 让主脑看 SWM evidence 自决调 severity'

设计 (准则 6 决策集中主脑):
  数据强耦合: mutation organ 已 publish 'sir_field_updated' 进 SWM ✅
  行为弱耦合: 加 <CONCERN_DAMPEN cid="..." delta="-0.X" reason="..."/> tag (主脑可 emit)
  决策集中主脑: directive 教主脑看 SWM 'sir_field_updated' + active concerns severity
              → 自决 emit dampen tag
  
  chat_bypass 后处理: parse tag → ledger.record_signal(cid, reason, severity_delta) +
              publish 'concern_dampen_applied' SWM (主脑下轮可见 — closure)

Tag schema (主脑可 emit):
  <CONCERN_DAMPEN cid="sir_sleep_streak" delta="-0.3" reason="Sir reported 1h nap"/>
  
  cid    — concern id (must match concerns.json key)
  delta  — float, range [-1.0, 1.0]. 负 = 削权, 正 = 升权
  reason — short text, evidence anchor (Sir 原话 / mutation result)

API:
  parse_dampen_tags(text) → List[ParsedDampen]   — 解析 reply 含的 dampen tag
  apply_dampen(parsed, ledger) → bool           — 调 ledger.record_signal + publish SWM
  process_reply(text, ledger, turn_id)          — 一站式 (parse + apply, 主路径调)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

try:
    from jarvis_utils import bg_log, get_event_bus
except Exception:
    def bg_log(s: str) -> None:
        print(s)
    def get_event_bus():
        return None


# Tag schema:
# <CONCERN_DAMPEN cid="X" delta="-0.3" reason="Y"/>
# 或 <CONCERN_DAMPEN cid="X" delta="-0.3" reason="Y"></CONCERN_DAMPEN>
_PAT_DAMPEN = re.compile(
    r'<CONCERN_DAMPEN\s+'
    r'cid\s*=\s*[\'"]([^\'"]+)[\'"]\s+'
    r'delta\s*=\s*[\'"]([+\-]?\d*\.?\d+)[\'"]\s+'
    r'reason\s*=\s*[\'"]([^\'"]*)[\'"]\s*'
    r'/?>(?:\s*</CONCERN_DAMPEN>)?',
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class ParsedDampen:
    cid: str
    delta: float
    reason: str
    raw_match: str

    def is_valid(self) -> bool:
        if not self.cid or not isinstance(self.cid, str):
            return False
        if abs(self.delta) > 1.0:
            return False
        if abs(self.delta) < 0.01:
            return False
        return True


def parse_dampen_tags(text: str) -> List[ParsedDampen]:
    """从 reply text 抽 <CONCERN_DAMPEN> tag 列表. 空/无返 []."""
    if not text or '<CONCERN_DAMPEN' not in text:
        return []
    out: List[ParsedDampen] = []
    try:
        for m in _PAT_DAMPEN.finditer(text):
            try:
                cid = (m.group(1) or '').strip()
                delta = float(m.group(2) or 0.0)
                reason = (m.group(3) or '').strip()[:200]
                pd = ParsedDampen(
                    cid=cid, delta=delta, reason=reason, raw_match=m.group(0))
                if pd.is_valid():
                    out.append(pd)
            except Exception:
                continue
    except Exception:
        pass
    return out


def apply_dampen(pd: ParsedDampen, ledger, turn_id: str = '') -> bool:
    """对单个 ParsedDampen 调 ledger.record_signal + publish SWM."""
    if not pd or not pd.is_valid():
        return False
    if ledger is None:
        return False
    try:
        what = (
            f"[ConcernDampen/turn={turn_id[:20]}] {pd.reason}"
            if pd.reason else
            f"[ConcernDampen/turn={turn_id[:20]}] (no reason)"
        )
        ok = ledger.record_signal(
            pd.cid, what, severity_delta=pd.delta, source_turn_id=turn_id)
        if ok:
            try:
                bg_log(
                    f"📉 [ConcernDampen] cid={pd.cid} delta={pd.delta:+.2f} "
                    f"reason='{pd.reason[:60]}' (主脑自决)"
                )
            except Exception:
                pass
            # publish SWM closure event — 主脑下轮 prompt 看到 dampen 已落地
            try:
                bus = get_event_bus()
                if bus is not None:
                    bus.publish(
                        etype='concern_dampen_applied',
                        description=(
                            f"concern {pd.cid} severity {pd.delta:+.2f} applied "
                            f"({pd.reason[:60]})"
                        ),
                        source='ConcernDampenParser',
                        salience=0.65,
                        metadata={
                            'concern_id': pd.cid,
                            'delta': pd.delta,
                            'reason': pd.reason[:120],
                            'turn_id': turn_id,
                        },
                    )
            except Exception:
                pass
            return True
        else:
            try:
                bg_log(
                    f"⚠️ [ConcernDampen/Reject] cid={pd.cid} ledger.record_signal "
                    f"返 False (concern_id 不存在?)"
                )
            except Exception:
                pass
            return False
    except Exception as e:
        try:
            bg_log(f"⚠️ [ConcernDampen/Exception] cid={pd.cid}: {e}")
        except Exception:
            pass
        return False


def process_reply(text: str, ledger, turn_id: str = '') -> int:
    """一站式 — 主路径调. 返 success count."""
    parsed = parse_dampen_tags(text)
    if not parsed:
        return 0
    n = 0
    for pd in parsed:
        if apply_dampen(pd, ledger, turn_id=turn_id):
            n += 1
    return n
