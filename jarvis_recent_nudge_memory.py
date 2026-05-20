# -*- coding: utf-8 -*-
"""[P2-Gap12 / 2026-05-20 23:45] RecentNudgeMemory — 主动通道话题去重

Sir 22:38-22:44 真痛点:
  22:38 ReturnSentinel: "I trust the shower was refreshing"
  22:44 ProactiveCare:  "The shower was a wise choice"
  6 min 内两次 nudge 都 reference "shower" — 6 channel 互不知重复.

Root cause: ReturnSentinel / ProactiveCare / Conductor / Wellness / SmartNudge /
Curiosity 各自 fire stream_nudge, 主脑两次 prompt 都不知"我 6min 前刚说过 shower".

修法: persistent rolling log of recent Jarvis nudges + 注主脑 prompt
[RECENT JARVIS NUDGES] block, 主脑看自己刚说过啥 → 自决不重复.

设计原则:
1. 准则 6 — vocab + LLM 决策. 不写死"30min 内不重复" 硬规则. 让主脑自己看 history 判
2. 准则 1 高效 — 内存 list + jsonl persist (rolling 50 条), 无 LLM call
3. 准则 6.5 — Sir CLI 可看 + 删 (`scripts/recent_nudges_dump.py`)

数据格式 (memory_pool/recent_nudges.jsonl, append-only rolling 50):
  {"ts": 1234, "iso": "...", "channel": "ProactiveCare",
   "trigger": "concern=sir_sleep_streak", "content": "...",
   "topic_hint": "shower 23:30 sleep", "turn_id": "..."}
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import List, Optional


DEFAULT_PATH = os.path.join('memory_pool', 'recent_nudges.jsonl')
DEFAULT_MAX_KEEP = 50
DEFAULT_LOOKBACK_S = 1800.0  # 30min


@dataclass
class NudgeRecord:
    """单条 Jarvis 主动 nudge 记录."""
    ts: float
    iso: str
    channel: str             # 'ProactiveCare' / 'ReturnSentinel' / 'SmartNudge' / 'Conductor' / 'Wellness' / 'Curiosity'
    trigger: str = ''        # 'concern=X' / 'afk_return' / 'sleep_window' / ...
    content: str = ''        # nudge reply 全文 (max 300 chars)
    topic_hint: str = ''     # 简短关键词组 ('shower 23:30 sleep')
    turn_id: str = ''

    def to_dict(self) -> dict:
        return asdict(self)


def _extract_topic_hint(content: str, max_kw: int = 5) -> str:
    """启发式抽 content 关键词 (无 LLM 调用, 准则 1 高效)."""
    if not content:
        return ''
    # 去标点 + 小写
    text = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', content.lower())
    words = text.split()
    # 简单 stopword 过滤
    stop = {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'to', 'of', 'in', 'on', 'at', 'for', 'with', 'and', 'or', 'but',
        'i', 'you', 'sir', 'your', 'my', 'me', 'we', 'us', 'it', 'its',
        'this', 'that', 'these', 'those', 'will', 'shall', 'would', 'should',
        'may', 'might', 'can', 'could', 'have', 'has', 'had', 'do', 'does',
        '我', '你', '的', '了', '是', '在', '和', '与', '或', '也', '都', '就',
        '这', '那', '会', '要', '让', '把', '从', '到', '能', '可以', '已经',
        '请', '吗', '呢', '吧', '啊', '哦', '嗯', '好', '谢谢', '不',
    }
    keywords = [w for w in words if w and w not in stop and len(w) > 1]
    # dedup keep order
    seen = set()
    unique = []
    for w in keywords:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return ' '.join(unique[:max_kw])


class RecentNudgeMemoryStore:
    """Jarvis 最近主动 nudge log. 跨 channel 共享, 让主脑看自己刚说啥避免重复.

    持久化: jsonl rolling (memory_pool/recent_nudges.jsonl, max 50 条)
    线程安全: 所有 read/write 走 self._lock
    """

    def __init__(self, path: Optional[str] = None, max_keep: int = DEFAULT_MAX_KEEP):
        self.path = path or DEFAULT_PATH
        self.max_keep = max_keep
        self._records: List[NudgeRecord] = []
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """启动时读 jsonl 恢复. fail 容忍."""
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        r = NudgeRecord(
                            ts=float(d.get('ts', 0)),
                            iso=d.get('iso', ''),
                            channel=d.get('channel', '?'),
                            trigger=d.get('trigger', ''),
                            content=d.get('content', ''),
                            topic_hint=d.get('topic_hint', ''),
                            turn_id=d.get('turn_id', ''),
                        )
                        self._records.append(r)
                    except Exception:
                        continue
            # 启动时 trim
            if len(self._records) > self.max_keep:
                self._records = self._records[-self.max_keep:]
        except Exception:
            pass

    def _persist(self) -> None:
        """全量 rewrite jsonl (atomic). 因 max 50 条, rewrite 成本 < 5ms."""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                for r in self._records:
                    f.write(json.dumps(r.to_dict(), ensure_ascii=False) + '\n')
            os.replace(tmp, self.path)
        except Exception:
            pass

    def record_nudge(self, channel: str, content: str,
                     trigger: str = '', turn_id: str = '',
                     topic_hint: str = '') -> str:
        """记一次 Jarvis 主动 nudge. 返回 topic_hint."""
        if not channel or not content:
            return ''
        now = time.time()
        if not topic_hint:
            topic_hint = _extract_topic_hint(content)
        rec = NudgeRecord(
            ts=now,
            iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
            channel=channel,
            trigger=trigger[:80],
            content=content[:300],
            topic_hint=topic_hint[:120],
            turn_id=turn_id[:60],
        )
        with self._lock:
            self._records.append(rec)
            if len(self._records) > self.max_keep:
                self._records = self._records[-self.max_keep:]
            self._persist()
        return topic_hint

    def recent_nudges(self, within_seconds: float = DEFAULT_LOOKBACK_S) -> List[NudgeRecord]:
        """拿最近 within_seconds 秒的 nudge records, time desc 排序."""
        cutoff = time.time() - within_seconds
        with self._lock:
            return sorted(
                [r for r in self._records if r.ts >= cutoff],
                key=lambda r: -r.ts,
            )

    def to_prompt_block(self, within_seconds: float = DEFAULT_LOOKBACK_S,
                        max_show: int = 5) -> str:
        """渲 [RECENT JARVIS NUDGES] block 给 _assemble_prompt 注主脑 prompt.

        主脑看自己刚说过啥, 不重复主题 / 不重复 nudge 同一件事.
        准则 6: 不教硬规"30min 不重复", 让主脑看 evidence 自决.
        """
        recents = self.recent_nudges(within_seconds=within_seconds)
        if not recents:
            return ''
        lines = ['[RECENT JARVIS NUDGES — last 30min, you said these to Sir]']
        for r in recents[:max_show]:
            _age_min = int((time.time() - r.ts) / 60)
            _age_str = f'{_age_min}min ago' if _age_min < 60 else f'{_age_min // 60}h ago'
            _topic = f' [topic: {r.topic_hint}]' if r.topic_hint else ''
            _trig = f' (trigger: {r.trigger})' if r.trigger else ''
            lines.append(
                f'  - {_age_str} [{r.channel}]{_trig}{_topic}'
            )
            # show short content excerpt (50 chars)
            _excerpt = r.content[:80].replace('\n', ' ')
            lines.append(f'      "{_excerpt}..."')
        lines.append('[guidance: avoid re-nudging same topic. If Sir already heard '
                     'about X recently, vary angle or stay silent.]')
        return '\n'.join(lines)

    def stats(self) -> dict:
        with self._lock:
            n_total = len(self._records)
            channels = {}
            for r in self._records:
                channels[r.channel] = channels.get(r.channel, 0) + 1
            recent_30min = sum(1 for r in self._records
                               if (time.time() - r.ts) < 1800.0)
            return {
                'total': n_total,
                'recent_30min': recent_30min,
                'by_channel': channels,
            }

    def clear(self) -> int:
        """删全部 record (testcase 用 + Sir 紧急 reset)."""
        with self._lock:
            n = len(self._records)
            self._records.clear()
            self._persist()
            return n


# ============================================================
# 单例
# ============================================================

_DEFAULT_STORE: Optional[RecentNudgeMemoryStore] = None
_STORE_LOCK = threading.Lock()


def get_default_store() -> RecentNudgeMemoryStore:
    global _DEFAULT_STORE
    with _STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = RecentNudgeMemoryStore()
        return _DEFAULT_STORE


def reset_default_store_for_test() -> None:
    """testcase 隔离用."""
    global _DEFAULT_STORE
    with _STORE_LOCK:
        _DEFAULT_STORE = None


def record_nudge(channel: str, content: str,
                  trigger: str = '', turn_id: str = '') -> str:
    """简化入口给 stream_nudge 末尾调."""
    return get_default_store().record_nudge(
        channel=channel,
        content=content,
        trigger=trigger,
        turn_id=turn_id,
    )


def to_prompt_block(within_seconds: float = DEFAULT_LOOKBACK_S,
                     max_show: int = 5) -> str:
    """简化入口给 _assemble_prompt 注主脑."""
    return get_default_store().to_prompt_block(
        within_seconds=within_seconds,
        max_show=max_show,
    )
