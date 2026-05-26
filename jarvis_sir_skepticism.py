# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 20:14 真意 anchor 3] Sir Skepticism Learning Loop.

Sir 真意 (第三次细化):
  "我期待的是通过我跟他的对话他能动态调整, 比如一个很奇怪的 inside joke,
   我提出质疑的时候它会降低使用权重, 提出多次质疑甚至会考虑删除这种能力."

Sir 真意明确:
  1. 不是 main brain 听 Sir 说 "撤了" 然后调 tool
  2. 不是 thought 反思后自调 tool
  3. 是 Sir **自然对话** 中表达质疑 → 系统**自动**降权 / archive
  4. Sir 元否决: dashboard 看历史 + reactivate API (Sir 反悔)

设计 (准则 6 三维耦合 + 准则 8 优雅):

    ┌────────────────────────────────────────────────┐
    │  Sir reply: "这梗好奇怪" / "别再提了"             │
    └────────────────────────────────────────────────┘
                          ↓
    [1] SkepticismDetector  ← vocab JSON 持久化 (memory_pool/sir_skepticism_vocab.json)
        • check skepticism_keywords (zh + en)
        • check confusion_keywords (separate, no skepticism count)
        • check reactivation_keywords (Sir 反悔, skepticism_count -= 1)
        • publish SWM 'sir_skepticism' / 'sir_reactivation'
                          ↓
    [2] AttributionEngine
        • 查最近 30s 内 system 最后做的事:
          ▪ recent inside_joke usage (RelationalState last_used_at)
          ▪ recent nudge fire (SWM 'proactive_nudge_fired')
          ▪ recent concern injection (SWM 'concern_injected_layer1')
          ▪ recent reply 含 active joke phrase (substring match)
        • 找最 plausible attribution → target_item_id
                          ↓
    [3] DecayEngine
        • inside_joke.skepticism_count += 1
        • count=1 → use_weight *= 0.7 (减权)
        • count=2 → use_weight *= 0.5 + 'item_skepticism_warning' SWM
        • count=3 → 自动 archive + 'item_auto_archived' SWM + reactivation 可恢复
        • 同理 concern (severity *= 0.7), protocol (rejected_count += 1)

数据强耦合 (准则 6):
  - 全 publish SWM event (主脑下轮 prompt 看 evidence)
  - vocab 持久化 + CLI 可改 (scripts/sir_skepticism_dump.py)
  - skepticism_count field 加 RelationalState/Concerns dataclass (低风险扩展)

行为弱耦合 (准则 6):
  - SkepticismDetector 是 sensor (检 + publish), 不 hardcode behavior
  - DecayEngine 是 effector (read SWM event + apply 操作), 易 swap

决策集中 (准则 6):
  - 阈值 (count_1_weight=0.7, count_3_action=archive) 持久化 JSON 可调
  - 后期 L7 reflector daemon 可 LLM-propose 新 keyword

准则 7 Sir 元否决:
  - Sir reactivation: 可手动 dashboard 或对话 "继续提那个" 恢复
  - SkepticismDecay 阶段 publish SWM 让 Sir 看 history
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

try:
    from jarvis_utils import bg_log, get_event_bus
except Exception:
    def bg_log(msg: str) -> None:
        print(msg)
    def get_event_bus():
        return None


# ==========================================================================
# Path
# ==========================================================================
DEFAULT_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool',
    'sir_skepticism_vocab.json',
)

# 30s attribution window — Sir 质疑必紧跟 system 行为
ATTRIBUTION_WINDOW_S = 30.0

# Decay default thresholds (覆盖 JSON 缺失场景)
_DEFAULT_COUNT_1_WEIGHT = 0.7
_DEFAULT_COUNT_2_WEIGHT = 0.5
_DEFAULT_COUNT_3_ACTION = 'auto_archive'


# ==========================================================================
# Vocab cache (singleton, 30s mtime throttle 类 runtime_log_markers)
# ==========================================================================
class _VocabCache:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._data: dict = {}
        self._mtime: float = 0.0
        self._last_check_ts: float = 0.0
        self._check_interval: float = 30.0
        self._skepticism_re_cache = None
        self._confusion_re_cache = None
        self._reactivation_re_cache = None

    def _load_from_disk(self, path: str) -> None:
        try:
            if not os.path.exists(path):
                self._data = {}
                return
            mtime = os.path.getmtime(path)
            if mtime == self._mtime and self._data:
                return
            with open(path, 'r', encoding='utf-8') as f:
                self._data = json.load(f)
            self._mtime = mtime
            self._skepticism_re_cache = None
            self._confusion_re_cache = None
            self._reactivation_re_cache = None
        except Exception:
            pass

    def ensure_loaded(self, path: str) -> None:
        now = time.time()
        if now - self._last_check_ts < self._check_interval and self._data:
            return
        self._last_check_ts = now
        self._load_from_disk(path)

    def _build_regex(self, key_zh: str, key_en: str):
        kws = list(self._data.get(key_zh) or []) + list(self._data.get(key_en) or [])
        if not kws:
            return None
        # case-insensitive + escape special chars
        escaped = [re.escape(k.lower()) for k in kws if k.strip()]
        if not escaped:
            return None
        return re.compile('|'.join(escaped), re.IGNORECASE)

    def get_skepticism_regex(self):
        if self._skepticism_re_cache is None:
            self._skepticism_re_cache = self._build_regex(
                'skepticism_keywords_zh', 'skepticism_keywords_en'
            )
        return self._skepticism_re_cache

    def get_confusion_regex(self):
        if self._confusion_re_cache is None:
            self._confusion_re_cache = self._build_regex(
                'confusion_keywords', 'confusion_keywords'
            )
        return self._confusion_re_cache

    def get_reactivation_regex(self):
        if self._reactivation_re_cache is None:
            self._reactivation_re_cache = self._build_regex(
                'reactivation_keywords_zh', 'reactivation_keywords_en'
            )
        return self._reactivation_re_cache

    def get_decay_thresholds(self) -> dict:
        meta = self._data.get('_meta') or {}
        return meta.get('decay_thresholds') or {
            'count_1_weight': _DEFAULT_COUNT_1_WEIGHT,
            'count_2_weight': _DEFAULT_COUNT_2_WEIGHT,
            'count_3_action': _DEFAULT_COUNT_3_ACTION,
        }


def _vocab() -> _VocabCache:
    """获取 vocab cache (lazy load)."""
    c = _VocabCache()
    c.ensure_loaded(DEFAULT_VOCAB_PATH)
    return c


# ==========================================================================
# Detector: Sir reply 检 skepticism / confusion / reactivation
# ==========================================================================
@dataclass
class SkepticismSignal:
    """质疑信号 (Detector → Attribution → Decay)."""
    kind: str            # 'skepticism' / 'confusion' / 'reactivation'
    matched_phrase: str
    sir_reply: str
    detected_at: float = field(default_factory=time.time)


def detect_skepticism(sir_reply: str) -> Optional[SkepticismSignal]:
    """Sir reply 检质疑 / 困惑 / 反悔.

    Returns SkepticismSignal | None.
    优先级: reactivation > skepticism > confusion (反悔最优先).
    """
    if not sir_reply or not isinstance(sir_reply, str):
        return None
    reply_lower = sir_reply.lower().strip()
    if not reply_lower:
        return None
    vc = _vocab()

    # 1. reactivation (Sir 反悔, 主动重提)
    re_react = vc.get_reactivation_regex()
    if re_react:
        m = re_react.search(reply_lower)
        if m:
            return SkepticismSignal(
                kind='reactivation',
                matched_phrase=m.group(0)[:80],
                sir_reply=sir_reply[:200],
            )

    # 2. skepticism (主路径 — 累积 count)
    re_skep = vc.get_skepticism_regex()
    if re_skep:
        m = re_skep.search(reply_lower)
        if m:
            return SkepticismSignal(
                kind='skepticism',
                matched_phrase=m.group(0)[:80],
                sir_reply=sir_reply[:200],
            )

    # 3. confusion (不累积, 只 publish 给 thought 反思看)
    re_conf = vc.get_confusion_regex()
    if re_conf:
        m = re_conf.search(reply_lower)
        if m:
            return SkepticismSignal(
                kind='confusion',
                matched_phrase=m.group(0)[:80],
                sir_reply=sir_reply[:200],
            )
    return None


# ==========================================================================
# Attribution: 找 30s 内最 plausible target item
# ==========================================================================
@dataclass
class AttributionResult:
    target_kind: str       # 'inside_joke' / 'protocol' / 'concern' / 'nudge' / 'unknown'
    target_id: str
    target_preview: str
    confidence: float      # 0.0-1.0
    reason: str            # 'last_joke_used' / 'last_nudge_fired' / etc


def attribute_skepticism(
    sir_reply: str = '',
    window_s: float = ATTRIBUTION_WINDOW_S,
) -> Optional[AttributionResult]:
    """30s 内查 system 最后做的事, 找最 plausible target.

    优先级:
      1. 最近被 inject 的 inside_joke (Sir 质疑 inject 这条最 plausible)
      2. 最近 fire 的 nudge (含 concern_id / kind → concern)
      3. 最近 active concern (Layer 1 SOUL inject)
    """
    bus = get_event_bus()
    if bus is None:
        return None

    candidates: List[AttributionResult] = []

    try:
        # 拿最近 50 events. ConversationEventBus.top_n 给每个 event add '_age_s' 字段.
        # 不用 'ts' (字段名错), 也不用 'timestamp' 直接算 age — 用 '_age_s' 准.
        top = bus.top_n(n=50) or []
        for ev in top:
            # 🔧 [Sir 2026-05-26 20:39 真痛 BUG 治本] 不用 `or 999999` 兜底:
            # _age_s=0 (刚 publish) 是合法 int falsy, `or` 会兜底到 999999 →
            # event 永远被当成超窗口 skip → attribution 永远 None.
            _age_raw = ev.get('_age_s')
            age = float(_age_raw if _age_raw is not None else 999999)
            if age > window_s:
                continue
            etype = ev.get('type', '')

            # 1. inside_joke 被 inject (含 phrase metadata)
            if etype == 'inside_joke_injected':
                meta = ev.get('metadata') or {}
                jid = meta.get('joke_id', '')
                phrase = meta.get('phrase', '')[:60]
                if jid:
                    confidence = max(0.5, 1.0 - age / window_s)  # 越近越准
                    candidates.append(AttributionResult(
                        target_kind='inside_joke',
                        target_id=jid,
                        target_preview=phrase,
                        confidence=confidence,
                        reason=f'inside_joke_injected {int(age)}s ago',
                    ))

            # 2. proactive_nudge_fired (含 concern_id 可二级 attribute concern)
            elif etype == 'proactive_nudge_fired':
                meta = ev.get('metadata') or {}
                concern_id = meta.get('concern_id', '')
                kind = meta.get('kind', '')
                sentinel = meta.get('sentinel', '')
                confidence = max(0.4, 0.8 - age / window_s)
                if concern_id:
                    candidates.append(AttributionResult(
                        target_kind='concern',
                        target_id=concern_id,
                        target_preview=f'{sentinel}/{kind}',
                        confidence=confidence,
                        reason=f'nudge_fired with concern {int(age)}s ago',
                    ))
                # nudge 本身也 candidate (即使没 concern)
                candidates.append(AttributionResult(
                    target_kind='nudge',
                    target_id=f'{sentinel}_{kind}',
                    target_preview=f'{sentinel}/{kind}',
                    confidence=confidence * 0.8,
                    reason=f'nudge fired {int(age)}s ago',
                ))

            # 3. concern_injected_layer1
            elif etype == 'concern_injected_layer1':
                meta = ev.get('metadata') or {}
                concern_id = meta.get('concern_id', '')
                what = meta.get('what', '')[:60]
                if concern_id:
                    confidence = max(0.3, 0.6 - age / window_s)
                    candidates.append(AttributionResult(
                        target_kind='concern',
                        target_id=concern_id,
                        target_preview=what,
                        confidence=confidence,
                        reason=f'concern injected {int(age)}s ago',
                    ))
    except Exception:
        return None

    # 4. fallback: 看 Sir reply 是否含 active inside_joke phrase (substring)
    if sir_reply and not candidates:
        try:
            from jarvis_relational import get_default_store
            store = get_default_store()
            reply_lower = sir_reply.lower()
            for joke in store.inside_jokes.values():
                if getattr(joke, 'state', '') != 'active':
                    continue
                phrase = (getattr(joke, 'phrase', '') or '').lower()
                if phrase and len(phrase) >= 4 and phrase in reply_lower:
                    candidates.append(AttributionResult(
                        target_kind='inside_joke',
                        target_id=joke.id,
                        target_preview=joke.phrase[:60],
                        confidence=0.4,
                        reason='reply 含 joke phrase',
                    ))
        except Exception:
            pass

    if not candidates:
        return None
    # 按 confidence 选最高
    candidates.sort(key=lambda c: -c.confidence)
    return candidates[0]


# ==========================================================================
# Decay: 给 target item 加 skepticism_count + 阈值触发
# ==========================================================================
@dataclass
class DecayAction:
    target_kind: str
    target_id: str
    old_skepticism_count: int
    new_skepticism_count: int
    old_weight: float
    new_weight: float
    action: str           # 'weight_lowered' / 'archived' / 'reactivated' / 'noop'
    reason: str


def apply_decay(
    attribution: AttributionResult,
    signal: SkepticismSignal,
) -> Optional[DecayAction]:
    """对 attribution.target_item 加 skepticism_count + 触发阈值动作.

    skepticism action:
      count=1 → use_weight *= 0.7
      count=2 → use_weight *= 0.5 + publish 'item_skepticism_warning'
      count=3+ → auto_archive

    reactivation action:
      count -= 1 (cap 0) + restore weight to min(1.0, weight / 0.7)
    """
    try:
        return _apply_decay_inside_joke(attribution, signal) if attribution.target_kind == 'inside_joke' \
            else _apply_decay_concern(attribution, signal) if attribution.target_kind == 'concern' \
            else _apply_decay_protocol(attribution, signal) if attribution.target_kind == 'protocol' \
            else None
    except Exception as e:
        bg_log(f"⚠️ [Skepticism/Decay] exception: {e}")
        return None


def _apply_decay_inside_joke(attribution: AttributionResult,
                                signal: SkepticismSignal) -> Optional[DecayAction]:
    try:
        from jarvis_relational import get_default_store
        store = get_default_store()
        joke = store.inside_jokes.get(attribution.target_id)
        if joke is None:
            return None
        thresholds = _vocab().get_decay_thresholds()
        old_count = int(getattr(joke, 'skepticism_count', 0) or 0)
        old_weight = float(getattr(joke, 'use_weight', 1.0) or 1.0)

        if signal.kind == 'reactivation':
            new_count = max(0, old_count - 1)
            joke.skepticism_count = new_count
            new_weight = min(1.0, old_weight / float(thresholds.get('count_1_weight', 0.7)))
            joke.use_weight = round(new_weight, 3)
            store._dirty = True
            store.persist()
            _publish_skepticism_event(
                'item_reactivated', attribution, signal,
                {'old_count': old_count, 'new_count': new_count,
                 'old_weight': old_weight, 'new_weight': new_weight}
            )
            return DecayAction(
                target_kind='inside_joke',
                target_id=attribution.target_id,
                old_skepticism_count=old_count,
                new_skepticism_count=new_count,
                old_weight=old_weight,
                new_weight=new_weight,
                action='reactivated',
                reason=f'Sir reactivation: "{signal.matched_phrase}"',
            )

        # skepticism (默认路径)
        new_count = old_count + 1
        joke.skepticism_count = new_count

        if new_count >= 3 and thresholds.get('count_3_action') == 'auto_archive':
            # archive
            joke.state = 'archived'
            joke.use_weight = 0.0
            store._dirty = True
            store.persist()
            _publish_skepticism_event(
                'item_auto_archived', attribution, signal,
                {'count': new_count, 'reason': 'skepticism_count >= 3'}
            )
            bg_log(
                f"🚫 [Skepticism/Decay] auto_archive inside_joke "
                f"'{joke.phrase[:40]}' (count={new_count})"
            )
            return DecayAction(
                target_kind='inside_joke',
                target_id=attribution.target_id,
                old_skepticism_count=old_count,
                new_skepticism_count=new_count,
                old_weight=old_weight,
                new_weight=0.0,
                action='archived',
                reason=f'skepticism_count={new_count} >= 3 auto',
            )

        # weight decay
        if new_count == 1:
            new_weight = old_weight * float(thresholds.get('count_1_weight', 0.7))
        elif new_count == 2:
            new_weight = old_weight * float(thresholds.get('count_2_weight', 0.5))
        else:
            new_weight = old_weight  # 等 next tick 自然到 3
        joke.use_weight = round(max(0.0, new_weight), 3)
        store._dirty = True
        store.persist()

        evt_name = 'item_skepticism_warning' if new_count == 2 else 'item_skepticism_decay'
        _publish_skepticism_event(
            evt_name, attribution, signal,
            {'count': new_count, 'old_weight': old_weight,
             'new_weight': joke.use_weight}
        )
        bg_log(
            f"⚠️ [Skepticism/Decay] inside_joke '{joke.phrase[:40]}' "
            f"count {old_count}→{new_count}, weight {old_weight:.2f}→{joke.use_weight:.2f}"
        )
        return DecayAction(
            target_kind='inside_joke',
            target_id=attribution.target_id,
            old_skepticism_count=old_count,
            new_skepticism_count=new_count,
            old_weight=old_weight,
            new_weight=joke.use_weight,
            action='weight_lowered',
            reason=f'Sir skepticism: "{signal.matched_phrase}"',
        )
    except Exception as e:
        bg_log(f"⚠️ [Skepticism/Decay/joke] exception: {e}")
        return None


def _apply_decay_concern(attribution: AttributionResult,
                            signal: SkepticismSignal) -> Optional[DecayAction]:
    try:
        from jarvis_concerns import get_default_ledger
        ledger = get_default_ledger()
        if ledger is None:
            return None
        concern = ledger.concerns.get(attribution.target_id)
        if concern is None:
            return None
        thresholds = _vocab().get_decay_thresholds()
        old_count = int(getattr(concern, 'skepticism_count', 0) or 0)
        old_severity = float(getattr(concern, 'severity', 0.5) or 0.5)

        if signal.kind == 'reactivation':
            new_count = max(0, old_count - 1)
            concern.skepticism_count = new_count
            ledger._dirty = True
            _publish_skepticism_event(
                'item_reactivated', attribution, signal,
                {'old_count': old_count, 'new_count': new_count}
            )
            return DecayAction(
                target_kind='concern',
                target_id=attribution.target_id,
                old_skepticism_count=old_count,
                new_skepticism_count=new_count,
                old_weight=old_severity,
                new_weight=old_severity,
                action='reactivated',
                reason=f'reactivation: "{signal.matched_phrase}"',
            )

        new_count = old_count + 1
        concern.skepticism_count = new_count

        if new_count >= 3:
            # concern 不 archive (Sir 准则 6 可能仍 passively 关心), 改 dismiss
            ok = ledger.dismiss(
                attribution.target_id,
                reason=f"skepticism_count={new_count} (auto via SirSkepticism)",
                source='sir_skepticism_auto',
            )
            _publish_skepticism_event(
                'item_auto_dismissed', attribution, signal,
                {'count': new_count, 'reason': 'skepticism >= 3 → dismiss'}
            )
            bg_log(
                f"🚫 [Skepticism/Decay] auto_dismiss concern "
                f"'{concern.id}' (count={new_count})"
            )
            return DecayAction(
                target_kind='concern',
                target_id=attribution.target_id,
                old_skepticism_count=old_count,
                new_skepticism_count=new_count,
                old_weight=old_severity,
                new_weight=0.3,  # dismiss 把 severity 拉到 0.3
                action='dismissed',
                reason=f'skepticism_count={new_count} auto-dismissed',
            )

        # severity decay
        if new_count == 1:
            new_sev = old_severity * float(thresholds.get('count_1_weight', 0.7))
        elif new_count == 2:
            new_sev = old_severity * float(thresholds.get('count_2_weight', 0.5))
        else:
            new_sev = old_severity
        concern.severity = round(max(0.0, new_sev), 3)
        ledger._dirty = True
        evt_name = 'item_skepticism_warning' if new_count == 2 else 'item_skepticism_decay'
        _publish_skepticism_event(
            evt_name, attribution, signal,
            {'count': new_count, 'old_severity': old_severity,
             'new_severity': concern.severity}
        )
        bg_log(
            f"⚠️ [Skepticism/Decay] concern '{concern.id}' "
            f"count {old_count}→{new_count}, sev {old_severity:.2f}→{concern.severity:.2f}"
        )
        return DecayAction(
            target_kind='concern',
            target_id=attribution.target_id,
            old_skepticism_count=old_count,
            new_skepticism_count=new_count,
            old_weight=old_severity,
            new_weight=concern.severity,
            action='weight_lowered',
            reason=f'concern skepticism count={new_count}',
        )
    except Exception as e:
        bg_log(f"⚠️ [Skepticism/Decay/concern] exception: {e}")
        return None


def _apply_decay_protocol(attribution: AttributionResult,
                             signal: SkepticismSignal) -> Optional[DecayAction]:
    try:
        from jarvis_relational import get_default_store
        store = get_default_store()
        proto = store.unspoken_protocols.get(attribution.target_id)
        if proto is None:
            return None
        old_count = int(getattr(proto, 'skepticism_count', 0) or 0)
        old_rejected = int(getattr(proto, 'rejected', 0) or 0)

        if signal.kind == 'reactivation':
            new_count = max(0, old_count - 1)
            proto.skepticism_count = new_count
            store._dirty = True
            store.persist()
            return DecayAction(
                target_kind='protocol',
                target_id=attribution.target_id,
                old_skepticism_count=old_count,
                new_skepticism_count=new_count,
                old_weight=float(old_rejected),
                new_weight=float(old_rejected),
                action='reactivated',
                reason=f'reactivation: "{signal.matched_phrase}"',
            )

        new_count = old_count + 1
        proto.skepticism_count = new_count
        proto.rejected = old_rejected + 1

        if new_count >= 3:
            proto.state = 'archived'
            store._dirty = True
            store.persist()
            _publish_skepticism_event(
                'item_auto_archived', attribution, signal,
                {'count': new_count, 'reason': 'protocol skepticism >= 3'}
            )
            return DecayAction(
                target_kind='protocol',
                target_id=attribution.target_id,
                old_skepticism_count=old_count,
                new_skepticism_count=new_count,
                old_weight=float(old_rejected),
                new_weight=float(old_rejected + 1),
                action='archived',
                reason=f'skepticism_count={new_count} auto-archived',
            )
        store._dirty = True
        store.persist()
        return DecayAction(
            target_kind='protocol',
            target_id=attribution.target_id,
            old_skepticism_count=old_count,
            new_skepticism_count=new_count,
            old_weight=float(old_rejected),
            new_weight=float(old_rejected + 1),
            action='weight_lowered',
            reason='protocol skepticism count incremented',
        )
    except Exception as e:
        bg_log(f"⚠️ [Skepticism/Decay/protocol] exception: {e}")
        return None


def _publish_skepticism_event(
    etype: str,
    attribution: AttributionResult,
    signal: SkepticismSignal,
    extra: Optional[dict] = None,
) -> None:
    """Publish SWM event 让主脑 / thought 下次 prompt 看到 evidence."""
    try:
        bus = get_event_bus()
        if bus is None:
            return
        meta = {
            'kind': signal.kind,
            'matched_phrase': signal.matched_phrase,
            'target_kind': attribution.target_kind,
            'target_id': attribution.target_id,
            'target_preview': attribution.target_preview,
            'confidence': round(attribution.confidence, 2),
            'attribution_reason': attribution.reason,
        }
        if extra:
            meta.update(extra)
        bus.publish(
            etype=etype,
            description=(
                f"Sir skepticism→{attribution.target_kind}/"
                f"{attribution.target_id} '{attribution.target_preview[:30]}': "
                f"{signal.matched_phrase} (count→{extra.get('count', '?') if extra else '?'})"
            ),
            source='sir_skepticism',
            salience=0.8,
            metadata=meta,
            ttl=86400.0,  # 24h 让 thought 反思看
        )
    except Exception as e:
        bg_log(f"⚠️ [Skepticism/publish] exception: {e}")


# ==========================================================================
# Top-level: process_sir_reply (chat_bypass hook 调)
# ==========================================================================
def process_sir_reply(sir_reply: str) -> Optional[DecayAction]:
    """主入口 — Sir reply 后 chat_bypass 调.

    流程: Detector → publish 'sir_skepticism' SWM → Attribution → Decay.
    返 DecayAction (Sir 元否决可看), None 表示无 skepticism.
    """
    signal = detect_skepticism(sir_reply)
    if signal is None:
        return None

    # publish skepticism signal (无 attribution 也 publish, 让 thought 看)
    try:
        bus = get_event_bus()
        if bus is not None:
            bus.publish(
                etype='sir_skepticism' if signal.kind == 'skepticism'
                       else f'sir_{signal.kind}',
                description=(
                    f"Sir {signal.kind}: \"{signal.matched_phrase}\""
                ),
                source='sir_skepticism_detector',
                salience=0.7,
                metadata={
                    'kind': signal.kind,
                    'matched_phrase': signal.matched_phrase,
                    'sir_reply': signal.sir_reply[:200],
                },
                ttl=86400.0,
            )
    except Exception:
        pass

    # confusion 不 trigger decay, 只 publish 让 thought 反思
    if signal.kind == 'confusion':
        bg_log(f"❓ [Skepticism] Sir confusion: '{signal.matched_phrase}'")
        return None

    # attribution
    attribution = attribute_skepticism(sir_reply=sir_reply)
    if attribution is None:
        bg_log(
            f"⚠️ [Skepticism] {signal.kind} '{signal.matched_phrase}' "
            f"but no attribution found in last {int(ATTRIBUTION_WINDOW_S)}s"
        )
        return None

    # decay
    action = apply_decay(attribution, signal)
    if action:
        bg_log(
            f"✅ [Skepticism] '{signal.matched_phrase}' → "
            f"{action.target_kind}/{action.target_id} → {action.action}"
        )
    return action
