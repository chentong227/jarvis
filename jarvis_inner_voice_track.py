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
        entry = VoiceEntry(
            ts=ts if ts is not None else time.time(),
            source=str(source or 'noting'),
            content=str(content or '')[:300],
            intent=str(intent or 'noting'),
            urgency=max(0.0, min(1.0, float(urgency))),
            wants_voice=bool(wants_voice),
            meta=meta,
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
        self, max_chars: int = 2400, show_l3: bool = True
    ) -> str:
        """主脑 prompt 用 — 3 层叙事块.

        L1: 近 10min full entries (~600 token)
        L2: 10min-1h, 5min bucket digest (~150 token)
        L3: 1h-24h, 1h bucket digest (~250 token, 可关)

        Returns:
          多行字符串. 空 buffer 返一句 '(voice empty — just woke)'.
        """
        lines = []
        lines.append(
            "[YOUR INNER VOICE — past 24h, your continuous stream of consciousness]"
        )
        lines.append("")

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
