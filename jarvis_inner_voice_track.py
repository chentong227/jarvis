# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 18:44 真愿景 anchor] InnerVoiceTrack — Jarvis 的心声轨道

Sir 真愿景 (Sir 原话):
> "现象学等同人类 butler" — 让 Jarvis 借助 LLM (Gemini 3 Flash) + 设计架构,
> 在 Sir 体验上等同于一个 24/7 真在的 butler. 不是 LLM 模拟人格, 是给 LLM
> 充足真实 evidence, 让它每次开口都自然带着持续意识的氛围.

本模块 = Jarvis 24/7 的"意识流"载体. 所有思考脑产的 thought / sensor 重要事件 /
self reflection / care trigger 统一 append 进这条 ring buffer, 时序排.

主脑被召唤时, prompt 读 3 层视图 (防 Gemini 3 Flash 注意力稀释):
  L1 (近 10min full)         — 当 'I just been thinking about'    ~ 600 token
  L2 (10min-1h, 5min bucket) — 当 '1h 前我留意到'                  ~ 150 token
  L3 (1h-24h, 1h bucket)     — 当 '今天大致脉络'                   ~ 250 token

总 inner_voice block ~ 1000 token. Gemini 3 Flash 友好.

让主脑 reply 自然带"上下文连续", 不刻意 reference (butler comportment directive).

准则 6 三维耦合:
  数据强耦合: persist memory_pool/inner_voice_24h.jsonl
  行为弱耦合: append-only, 不强制主脑 reference, LLM 自决 weave
  决策集中主脑: 主脑读 voice block 自决 weave 进 reply

可回撤: env JARVIS_INNER_VOICE_ENABLED=0 → 主脑 prompt 不注入 voice 块,
        本 module 仍可 append (兼容).

Sir 2026-05-27 18:44 决策点:
  - 持久化窗口: 24h
  - 主脑 prompt 每次召唤都注入 (Sir 哲学: cost 不是问题, alive 先行)
  - 思考脑每 tick 必读 voice tail (近 5-10min) 当"我刚在想的事"
  - 主脑模型 Gemini 3 Flash, prompt 视图分 3 层 (~1000 token total)
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional


_PERSIST_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'inner_voice_24h.jsonl'
)
_RETENTION_SEC = 24 * 3600  # 24h
_RING_CAP = 2000  # 内存 ring buffer 上限 (远超 24h 实际量)


@dataclass
class VoiceEntry:
    """一条心声 entry. 第一人称叙事, 非报表."""
    ts: float
    source: str                 # 'inner_thought' / 'sensor' / 'care_trigger' /
                                # 'self_reflection' / 'noting' / 'sir_injected'
    content: str                # 一句话, 人话, 第一人称, ≤300 char
    intent: str = 'noting'      # 'observation' / 'care' / 'reflection' /
                                # 'reminder' / 'noting'
    urgency: float = 0.0        # 0-1, 越高越想开口
    wants_voice: bool = False   # 思考脑认为想开口提及 (主脑自决)
    meta: Optional[Dict] = None
    # 🆕 [Sir 2026-05-27 Phase 4 ageing + spotlight]
    entry_id: str = ''                 # uuid8, append 时生成 (backward-compat 默认空)
    surfaced_to_sir: bool = False      # 主脑 reply 后判定是否 reference 过
    surface_attempts: int = 0          # 出现在 prompt block 多少次
    last_surface_attempt_ts: float = 0.0  # 最后一次出现在 prompt 的 ts

    def to_dict(self) -> Dict:
        d = asdict(self)
        if d.get('meta') is None:
            d.pop('meta', None)
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> 'VoiceEntry':
        return cls(
            ts=float(d.get('ts', 0)),
            source=str(d.get('source', 'noting')),
            content=str(d.get('content', '')),
            intent=str(d.get('intent', 'noting')),
            urgency=float(d.get('urgency', 0.0)),
            wants_voice=bool(d.get('wants_voice', False)),
            meta=d.get('meta'),
            # 🆕 Phase 4 字段 backward-compat 默认
            entry_id=str(d.get('entry_id', '') or ''),
            surfaced_to_sir=bool(d.get('surfaced_to_sir', False)),
            surface_attempts=int(d.get('surface_attempts', 0) or 0),
            last_surface_attempt_ts=float(
                d.get('last_surface_attempt_ts', 0.0) or 0.0
            ),
        )


class InnerVoiceTrack:
    """Singleton — Jarvis 心声轨道.

    所有 voice entry append 到 ring buffer (内存) + jsonl (持久).
    重启从 jsonl 恢复近 24h.
    """

    def __init__(self, persist_path: str = _PERSIST_PATH):
        self._lock = threading.RLock()
        self._buffer: deque = deque(maxlen=_RING_CAP)
        self._persist_path = persist_path
        self._load_from_disk()

    def _load_from_disk(self):
        """启动时从 jsonl 恢复近 24h. 静默 fail."""
        if not os.path.exists(self._persist_path):
            return
        now = time.time()
        cutoff = now - _RETENTION_SEC
        try:
            with open(self._persist_path, 'r', encoding='utf-8') as f:
                loaded = []
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        entry = VoiceEntry.from_dict(d)
                        if entry.ts >= cutoff:
                            loaded.append(entry)
                    except Exception:
                        continue
                # 按 ts asc 入 buffer
                loaded.sort(key=lambda e: e.ts)
                for e in loaded[-_RING_CAP:]:  # 只取最近 _RING_CAP
                    self._buffer.append(e)
        except Exception:
            pass

    def append(
        self,
        source: str,
        content: str,
        intent: str = 'noting',
        urgency: float = 0.0,
        wants_voice: bool = False,
        meta: Optional[Dict] = None,
        ts: Optional[float] = None,
    ) -> VoiceEntry:
        """Append 一条 entry. 任何 module 都能调.

        Args:
          source: 'inner_thought' / 'sensor' / 'care_trigger' /
                  'self_reflection' / 'noting' / 'sir_injected'
          content: 一句话, 人话, 第一人称 (e.g. 'Sir 工作 1h 没喝水, 心里挂着')
          intent: 'observation' / 'care' / 'reflection' / 'reminder' / 'noting'
          urgency: 0-1
          wants_voice: True 表示思考脑想开口提及, 主脑下次召唤可看到
          meta: 附加结构化数据 (raw thought, sensor snapshot, etc.)
          ts: 自定义 ts (testing用), 默认 now
        """
        # 🆕 [Phase 4] 自动 gen entry_id (uuid 前 12 字符即足 — 24h 内不冲突).
        # 用于 ageing/spotlight surface 追踪.
        import uuid as _uuid
        _eid = 'iv_' + _uuid.uuid4().hex[:12]
        entry = VoiceEntry(
            ts=ts if ts is not None else time.time(),
            source=str(source or 'noting'),
            content=str(content or '')[:300],
            intent=str(intent or 'noting'),
            urgency=max(0.0, min(1.0, float(urgency))),
            wants_voice=bool(wants_voice),
            meta=meta,
            entry_id=_eid,
        )
        with self._lock:
            self._buffer.append(entry)
            try:
                os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
                with open(self._persist_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + '\n')
            except Exception:
                pass
        return entry

    def recent(self, minutes: float = 10.0, max_n: int = 50) -> List[VoiceEntry]:
        """返回近 N 分钟 entries, 按 ts asc."""
        cutoff = time.time() - minutes * 60.0
        with self._lock:
            result = [e for e in self._buffer if e.ts >= cutoff]
        # buffer 已是 append 顺序 (asc), 直接 slice
        return result[-max_n:]

    def range(
        self, min_min_ago: float, max_min_ago: float, max_n: int = 500
    ) -> List[VoiceEntry]:
        """返回 [now - max_min_ago, now - min_min_ago) 时段 entries.

        Args:
          min_min_ago: 较新边界 (e.g. 10 = 10分钟前)
          max_min_ago: 较老边界 (e.g. 60 = 60分钟前)
        """
        now = time.time()
        upper = now - min_min_ago * 60.0  # 较新 (exclusive)
        lower = now - max_min_ago * 60.0  # 较老 (inclusive)
        with self._lock:
            result = [e for e in self._buffer if lower <= e.ts < upper]
        return result[-max_n:]

    def has_wants_voice_pending(self, within_min: float = 30.0) -> bool:
        """近 N 分钟内有 wants_voice=True 的 entry 吗?"""
        cutoff = time.time() - within_min * 60.0
        with self._lock:
            for e in self._buffer:
                if e.ts >= cutoff and e.wants_voice:
                    return True
        return False

    def build_prompt_block_for_brain(
        self, max_chars: int = 2400, show_l3: bool = True,
        show_spotlight: bool = True,
        daemon=None, prompt_tier: str = '',
    ) -> str:
        """主脑 prompt 用 — 3 层叙事块 + 🆕 [Phase 4] ★ spotlight 段
        + 🆕 [Sir 2026-05-28 17:20 β.6 Phase 2 治本] daemon 聚合
        (lifetime + thinking directive).

        Sir 真意 (2026-05-28 17:14): "除了归来招呼和我设置的定时提醒走强制性
        编码唤醒, 其他的所有模块都集成到思考链, 把思考链给主脑让主脑演的像
        他一直存在, 因为他知道他之前在想什么, 运行了多久, 什么的."

        架构 (β.6 Phase 2 — push 退化到 voice 聚合):
          主脑只调 Layer 1.6 → 本 method → 内部聚合 daemon (lifetime +
          should_speak), 不需 Layer 1.5/1.7 独立 push. daemon 仍是 source of
          truth, voice 是 view aggregator (准则 6 决策集中主脑; 准则 8 优雅).

        新 render 顺序 (top → bottom):
          [YOUR LIFETIME] (daemon.build_lifetime_block, 若 daemon 给)
          [THINKING BRAIN SUGGESTS] (daemon.build_should_speak_directive, 若 daemon 给)
          SPOTLIGHT (★ wants_voice pending)
          L1: 近 10min full
          L2: 10min-1h 5min bucket
          L3: 1h-24h 1h bucket

        参数:
          daemon: optional InnerThoughtDaemon. 不给 → 仅 voice (老行为, backward compat).
                  给 → 顶部聚合 lifetime + should_speak directive.

        Returns:
          多行字符串. 空 buffer 返一句 '(voice empty — just woke)'.
        """
        # 🆕 [Phase 4] 先 apply ageing (内存 mutate, 不动 jsonl)
        try:
            self.apply_ageing()
        except Exception:
            pass

        lines = []

        # 🆕 [β.6 Phase 2 / Sir 17:20] daemon 聚合 — lifetime + thinking directive
        # 主脑只读本 block 就懂 "我运行多久 / 之前想啥 / 思考脑现在建议啥".
        # daemon=None (backward compat for testcase / 老调用) → 跳过, 仅 voice.
        # prompt_tier (Layer 1.5 老 vocab 路径迁移过来): SHORT_CHAT→full,
        # FACTUAL_RECALL→mini, REMINDER_FIRING→off, default→full.
        if daemon is not None:
            try:
                if hasattr(daemon, 'build_lifetime_block'):
                    # tier-aware mode 解析: 复用 daemon vocab (准则 6 持久化)
                    _mode = 'full'
                    try:
                        if hasattr(daemon, '_load_lifetime_vocab'):
                            _vocab = daemon._load_lifetime_vocab() or {}
                            _tier_map = _vocab.get('tier_mode') or {}
                            _tier_key = str(prompt_tier or '').upper()
                            _mode = _tier_map.get(_tier_key, 'full')
                    except Exception:
                        _mode = 'full'
                    if _mode != 'off':
                        lt_block = daemon.build_lifetime_block(mode=_mode) or ''
                        if lt_block.strip():
                            lines.append(lt_block.rstrip())
                            lines.append("")
            except Exception:
                pass
            try:
                if hasattr(daemon, 'build_should_speak_directive'):
                    sd_block = daemon.build_should_speak_directive() or ''
                    if sd_block.strip():
                        lines.append(sd_block.rstrip())
                        lines.append("")
            except Exception:
                pass

        lines.append(
            "[YOUR INNER VOICE — past 24h, your continuous stream of consciousness]"
        )
        lines.append("")

        # 🆕 [Phase 4 SPOTLIGHT] 未 surface 的 ★ pending — 顶部突出, 也 mark attempt
        spotlight_entries: List[VoiceEntry] = []
        if show_spotlight:
            try:
                spotlight_entries = self.get_pending_wants_voice()
            except Exception:
                spotlight_entries = []
        if spotlight_entries:
            cfg = _load_aging_config()
            header = str(cfg.get('spotlight', {}).get(
                'spotlight_header',
                '★ pending to surface to Sir (you have not mentioned these yet)'
            ))
            lines.append(f"## {header}:")
            for e in spotlight_entries:
                lines.append(self._render_entry(e))
            lines.append(
                "  (these are pending in your awareness — weave naturally "
                "when context fits, do not announce 'i was thinking')"
            )
            lines.append("")
            # mark surface attempt (++ counter, ageing 一旦达 max_attempts 自动降级)
            try:
                self.mark_surface_attempt(spotlight_entries)
            except Exception:
                pass

        # L1: 近 10min full
        l1 = self.recent(minutes=10.0, max_n=40)
        if l1:
            lines.append("## past 10 min (full, ordered):")
            for e in l1:
                lines.append(self._render_entry(e))
            lines.append("")

        # L2: 10min - 1h, 5min bucket digest
        l2 = self.range(min_min_ago=10.0, max_min_ago=60.0, max_n=300)
        if l2:
            lines.append("## 10min — 1h (digest, 5min bucket):")
            for line in self._bucket_digest(l2, bucket_min=5):
                lines.append(line)
            lines.append("")

        # L3: 1h-24h, 1h bucket digest
        if show_l3:
            l3 = self.range(min_min_ago=60.0, max_min_ago=24 * 60.0, max_n=600)
            if l3:
                lines.append("## 1h — 24h (hourly digest):")
                for line in self._bucket_digest(l3, bucket_min=60):
                    lines.append(line)
                lines.append("")

        if len(lines) <= 2:
            lines.append(
                "  (voice empty — just woke or restored from sleep, "
                "no prior conscious stream yet)"
            )

        out = "\n".join(lines)
        if len(out) > max_chars:
            _suffix = "\n…[truncated for attention focus]"
            out = out[: max_chars - len(_suffix)].rstrip() + _suffix
        return out

    @staticmethod
    def _render_entry(e: VoiceEntry) -> str:
        """一条 entry 渲染成一行."""
        hhmm = time.strftime("%H:%M", time.localtime(e.ts))
        wv_tag = " ★" if e.wants_voice else ""
        urg_tag = f" u={e.urgency:.1f}" if e.urgency >= 0.3 else ""
        return f"  - {hhmm} ({e.source}/{e.intent}{urg_tag}){wv_tag} {e.content}"

    @staticmethod
    def _bucket_digest(
        entries: List[VoiceEntry], bucket_min: int
    ) -> List[str]:
        """按 N min bucket 聚合, 每 bucket 一行 digest.

        每行格式: '  - HH:MM (N entries: intent_a=2, intent_b=1) e.g. <highest urgency content>'
        """
        if not entries:
            return []
        buckets: Dict[int, List[VoiceEntry]] = {}
        for e in entries:
            bucket_key = int(e.ts // (bucket_min * 60))
            buckets.setdefault(bucket_key, []).append(e)
        out = []
        for k in sorted(buckets.keys()):
            es = buckets[k]
            bucket_start = time.strftime(
                "%H:%M", time.localtime(k * bucket_min * 60)
            )
            n = len(es)
            intent_counts: Dict[str, int] = {}
            highest_e: Optional[VoiceEntry] = None
            for e in es:
                intent_counts[e.intent] = intent_counts.get(e.intent, 0) + 1
                if highest_e is None or e.urgency > highest_e.urgency:
                    highest_e = e
            tag_str = ", ".join(
                f"{kk}={vv}" for kk, vv in sorted(intent_counts.items())
            )
            rep_text = highest_e.content if highest_e else ""
            if len(rep_text) > 80:
                rep_text = rep_text[:80] + "..."
            out.append(
                f"  - {bucket_start} ({n} entries: {tag_str}) e.g. {rep_text}"
            )
        return out

    def stats(self) -> Dict:
        """Dashboard / debug 用."""
        with self._lock:
            n = len(self._buffer)
            now = time.time()
            n_10min = sum(1 for e in self._buffer if now - e.ts < 600)
            n_1h = sum(1 for e in self._buffer if now - e.ts < 3600)
            n_24h = sum(1 for e in self._buffer if now - e.ts < 86400)
            n_wv = sum(
                1 for e in self._buffer
                if e.wants_voice and now - e.ts < 1800
            )
            oldest = min((e.ts for e in self._buffer), default=now)
            newest = max((e.ts for e in self._buffer), default=now)
        return {
            'total': n,
            'last_10min': n_10min,
            'last_1h': n_1h,
            'last_24h': n_24h,
            'wants_voice_pending_30min': n_wv,
            'oldest_age_min': int((now - oldest) / 60) if n else 0,
            'newest_age_sec': int(now - newest) if n else 0,
        }

    def all_recent(self, hours: float = 24.0) -> List[VoiceEntry]:
        """Dashboard 用 — 返近 N 小时全部 entries."""
        cutoff = time.time() - hours * 3600.0
        with self._lock:
            return [e for e in self._buffer if e.ts >= cutoff]

    # ============================================================
    # 🆕 [Sir 2026-05-27 Phase 4] ageing + spotlight + surface tracking
    # ============================================================

    def get_pending_wants_voice(
        self, max_age_min: Optional[float] = None,
        max_items: Optional[int] = None,
    ) -> List[VoiceEntry]:
        """返 wants_voice=True 且 surfaced_to_sir=False 的 entries (按 ts asc).

        Args:
          max_age_min: 仅返 age <= max_age_min 的 (None = 用 config spotlight.max_pending_min)
          max_items: 最多返多少条 (None = 用 config spotlight.max_items_in_spotlight)
        """
        cfg = _load_aging_config()
        if max_age_min is None:
            max_age_min = float(
                cfg.get('spotlight', {}).get('max_pending_min', 60.0)
            )
        if max_items is None:
            max_items = int(
                cfg.get('spotlight', {}).get('max_items_in_spotlight', 5)
            )
        cutoff = time.time() - max_age_min * 60.0
        with self._lock:
            pending = [
                e for e in self._buffer
                if e.wants_voice
                    and not e.surfaced_to_sir
                    and e.ts >= cutoff
            ]
        pending.sort(key=lambda e: e.ts)
        # 取最近的 max_items 个
        return pending[-max_items:]

    def apply_ageing(self) -> int:
        """应用 ageing: 超过 max_age_sec 或 max_attempts 的 ★ entry → wants_voice=False.
        jsonl 历史不动 (history 留痕), 只内存 mutate.

        Returns: 降级 entry 数.
        """
        cfg = _load_aging_config()
        ag = cfg.get('ageing', {})
        max_age_sec = float(ag.get('ageing_max_age_sec', 7200.0))
        max_attempts = int(ag.get('ageing_max_attempts', 6))
        now = time.time()
        n_aged = 0
        with self._lock:
            for e in self._buffer:
                if not e.wants_voice:
                    continue
                if e.surfaced_to_sir:
                    # 已 surface, 不必 ageing
                    continue
                aged_by_time = (now - e.ts) > max_age_sec
                aged_by_attempts = e.surface_attempts >= max_attempts
                if aged_by_time or aged_by_attempts:
                    e.wants_voice = False
                    n_aged += 1
        return n_aged

    def mark_surface_attempt(self, entries: List[VoiceEntry]) -> None:
        """主脑 prompt 用了这些 entry 后, 调本方法增 surface_attempts.

        不改 jsonl (运行时 counter, 重启不影响 ageing — 因为重启已 reload jsonl).
        """
        now = time.time()
        with self._lock:
            for e in entries:
                if e not in self._buffer:
                    # 也接受 by entry_id 匹配 (e 可能是 prompt 渲染时的 ref copy)
                    if not e.entry_id:
                        continue
                    for be in self._buffer:
                        if be.entry_id == e.entry_id:
                            be.surface_attempts += 1
                            be.last_surface_attempt_ts = now
                            break
                else:
                    e.surface_attempts += 1
                    e.last_surface_attempt_ts = now

    def mark_recent_surfaced_by_overlap(
        self,
        reply_text: str,
        within_min: float = 30.0,
    ) -> int:
        """主脑 reply 后调本 helper. token overlap 判 reply 是否 reference
        近 within_min min 的 ★ pending entry. 命中 → mark surfaced_to_sir=True.

        Returns: 标 surfaced 的 entry 数.

        准则 6: 不 hardcode keyword, 用通用 token overlap. 阈值持久化 config.
        """
        if not reply_text:
            return 0
        cfg = _load_aging_config()
        sd = cfg.get('surface_detection', {})
        min_overlap = int(sd.get('min_overlap_words', 3))
        prefix_chars = int(sd.get('content_prefix_chars', 60))
        min_tok_len = int(sd.get('min_token_len', 3))

        def _tokenize(s: str) -> set:
            # 简单 alnum tokenization, 小写, 长度 >= min_tok_len
            import re as _re
            return {
                w.lower() for w in _re.findall(r"[\w']+", s or '')
                if len(w) >= min_tok_len
            }

        reply_tokens = _tokenize(reply_text)
        if not reply_tokens:
            return 0
        cutoff = time.time() - within_min * 60.0
        n_marked = 0
        with self._lock:
            for e in self._buffer:
                if e.surfaced_to_sir or not e.wants_voice:
                    continue
                if e.ts < cutoff:
                    continue
                content_prefix = (e.content or '')[:prefix_chars]
                ent_tokens = _tokenize(content_prefix)
                # meta 里如果有 reply_excerpt / sir_excerpt 也排除
                # (自我感知 entry 永远 reference 自己, 不算 surface)
                if e.meta and (
                    e.meta.get('kind') in ('main_reply', 'nudge_reply')
                ):
                    # self_reflection self-append entry 不算 pending,
                    # 但万一被标 wants_voice (异常), 也不该被 overlap mark
                    continue
                if not ent_tokens:
                    continue
                overlap = reply_tokens & ent_tokens
                if len(overlap) >= min_overlap:
                    e.surfaced_to_sir = True
                    e.last_surface_attempt_ts = time.time()
                    n_marked += 1
        return n_marked


# ============================================================
# Singleton
# ============================================================

_DEFAULT: Optional[InnerVoiceTrack] = None
_DEFAULT_LOCK = threading.Lock()


def get_inner_voice_track() -> InnerVoiceTrack:
    """Singleton accessor. 任何 module 调本入口拿心声轨道."""
    global _DEFAULT
    if _DEFAULT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT is None:
                _DEFAULT = InnerVoiceTrack()
    return _DEFAULT


def reset_for_test():
    """测试用 — 重置 singleton (默认 jsonl 路径)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = None


def is_enabled() -> bool:
    """env JARVIS_INNER_VOICE_ENABLED=1 (default) / 0 关.

    可回撤旋钮: Sir 设 0 → 主脑 prompt 不注入 voice block, 思考脑改造也跳过.
    """
    return os.environ.get('JARVIS_INNER_VOICE_ENABLED', '1').strip() != '0'


# ============================================================
# 🆕 [Sir 2026-05-27 Phase 4] ageing config loader (mtime cache)
# ============================================================

_AGING_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'inner_voice_aging_config.json'
)
_AGING_CFG_CACHE: Optional[dict] = None
_AGING_CFG_CACHE_MTIME: float = 0.0
_AGING_CFG_LOCK = threading.Lock()
_AGING_CFG_DEFAULT = {
    'spotlight': {
        'max_pending_min': 60.0,
        'max_items_in_spotlight': 5,
        'spotlight_header': (
            '★ pending to surface to Sir (you have not mentioned these yet)'
        ),
    },
    'ageing': {
        'ageing_max_age_sec': 7200.0,
        'ageing_max_attempts': 6,
    },
    'surface_detection': {
        'min_overlap_words': 3,
        'content_prefix_chars': 60,
        'min_token_len': 3,
    },
}


def _load_aging_config() -> dict:
    """Lazy + mtime cache, default fallback."""
    global _AGING_CFG_CACHE, _AGING_CFG_CACHE_MTIME
    try:
        mtime = os.path.getmtime(_AGING_CONFIG_PATH)
    except OSError:
        return _AGING_CFG_DEFAULT
    with _AGING_CFG_LOCK:
        if _AGING_CFG_CACHE is not None and mtime == _AGING_CFG_CACHE_MTIME:
            return _AGING_CFG_CACHE
        try:
            with open(_AGING_CONFIG_PATH, 'r', encoding='utf-8') as f:
                loaded = json.load(f) or {}
            # merge with default (在 default 基础上覆盖)
            merged = {
                'spotlight': dict(_AGING_CFG_DEFAULT['spotlight']),
                'ageing': dict(_AGING_CFG_DEFAULT['ageing']),
                'surface_detection': dict(
                    _AGING_CFG_DEFAULT['surface_detection']
                ),
            }
            for section in ('spotlight', 'ageing', 'surface_detection'):
                for k, v in (loaded.get(section) or {}).items():
                    if k.endswith('_note'):
                        continue
                    merged[section][k] = v
            _AGING_CFG_CACHE = merged
            _AGING_CFG_CACHE_MTIME = mtime
        except Exception:
            _AGING_CFG_CACHE = _AGING_CFG_DEFAULT
        return _AGING_CFG_CACHE


# ============================================================
# 🆕 [Sir 2026-05-27 Phase 2 Step 2b] SWM event → voice mirror
# ============================================================
# 准则 6 三维耦合:
#   数据强耦合: mapping vocab 持久化 memory_pool/swm_to_voice_vocab.json
#   行为弱耦合: ConversationEventBus.publish() 末尾静默调 mirror,
#               sentinel 代码完全不动
#   决策集中: 哪些 etype mirror / source / intent / wants_voice 阈值
#             vocab 决定, 不写死 — CLI scripts/swm_to_voice_dump.py 可改
# 可回撤: env JARVIS_INNER_VOICE_ENABLED=0 → 跳过整个 mirror
# ============================================================

_SWM_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'swm_to_voice_vocab.json'
)
_SWM_VOCAB_CACHE: Optional[dict] = None
_SWM_VOCAB_CACHE_MTIME: float = 0.0
_SWM_VOCAB_LOCK = threading.Lock()


def _load_swm_vocab() -> dict:
    """Lazy + mtime cache, 防 hot path 每次 IO."""
    global _SWM_VOCAB_CACHE, _SWM_VOCAB_CACHE_MTIME
    try:
        mtime = os.path.getmtime(_SWM_VOCAB_PATH)
    except OSError:
        return {'mappings': []}
    with _SWM_VOCAB_LOCK:
        if _SWM_VOCAB_CACHE is not None and mtime == _SWM_VOCAB_CACHE_MTIME:
            return _SWM_VOCAB_CACHE
        try:
            with open(_SWM_VOCAB_PATH, 'r', encoding='utf-8') as f:
                _SWM_VOCAB_CACHE = json.load(f) or {'mappings': []}
            _SWM_VOCAB_CACHE_MTIME = mtime
        except Exception:
            _SWM_VOCAB_CACHE = {'mappings': []}
        return _SWM_VOCAB_CACHE


def mirror_swm_event(
    etype: str,
    description: str,
    salience: float = 0.5,
    source_module: str = 'unknown',
    metadata: Optional[Dict] = None,
) -> bool:
    """ConversationEventBus.publish() 末尾调本 helper, 静默 mirror SWM
    event → voice entry append. 返 True 真 mirror, False 跳过.

    Args:
        etype: SWM event type (e.g. 'sensor_change' / 'concern_active')
        description: event 描述 (≤300 char)
        salience: 0-1 publish 时传入的
        source_module: publish 时 source 参数 (用于 meta 追溯)
        metadata: publish 时 metadata (合并进 voice meta)

    任何错误静默 False (publish hot path 不能 raise).
    env JARVIS_INNER_VOICE_ENABLED=0 → 立即 False.
    """
    if not is_enabled():
        return False
    if not etype:
        return False
    try:
        vocab = _load_swm_vocab()
        mappings = vocab.get('mappings') or []
        # 找匹配的 active mapping
        m = None
        for entry in mappings:
            if entry.get('etype') == etype and entry.get('active', True):
                m = entry
                break
        if m is None:
            return False
        try:
            min_sal = float(m.get('min_salience', 0.3))
        except (TypeError, ValueError):
            min_sal = 0.3
        try:
            sal_f = float(salience)
        except (TypeError, ValueError):
            sal_f = 0.5
        if sal_f < min_sal:
            return False
        try:
            wv_min = float(m.get('wants_voice_min_salience', 1.1))
        except (TypeError, ValueError):
            wv_min = 1.1
        wants_voice = sal_f >= wv_min
        # content template
        tmpl = str(m.get('content_template') or '{desc}')
        try:
            content = tmpl.format(
                desc=description, salience=sal_f,
                source_module=source_module,
            )
        except Exception:
            content = str(description)
        # cap 300 char (voice_track append 内部也会 cap, 双保险)
        content = content[:300]
        # voice meta — 保留 SWM event 溯源
        voice_meta = {
            'swm_etype': etype,
            'swm_source_module': source_module,
            'swm_salience': sal_f,
        }
        if metadata:
            # 选择性 merge — 避免 voice meta 巨大. 只保 1-2 关键 key.
            for k in ('reason', 'evidence_id', 'commitment_id',
                        'tool', 'concern_id'):
                if k in metadata:
                    voice_meta[f'swm_{k}'] = metadata[k]
        track = get_inner_voice_track()
        track.append(
            source=str(m.get('source') or 'noting'),
            intent=str(m.get('intent') or 'noting'),
            content=content,
            urgency=sal_f,
            wants_voice=wants_voice,
            meta=voice_meta,
        )
        return True
    except Exception:
        return False
