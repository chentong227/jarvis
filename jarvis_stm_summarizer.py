# -*- coding: utf-8 -*-
"""[Gap-Z1 / β.5.46-fix4 / 2026-05-21 23:15] STM Reply Summarizer

Sir 23:14 真凶 — Jarvis 仅听 wake word "he" 即翻 4% backspace + 0.01%
error visibility 老账. concern_reason=silent (Layer 1 没 inject), directive
反例已删 (fix3 / eaea1a7), 仍翻. 唯一可能: 主脑读 STM 自身上轮 reply 含
具体数字 → RLHF bias "诚实修正" 触发 unsolicited callback.

== 治本设计 ==

post-stream 异步 LLM 压缩 self.short_term_memory 末尾 entry 的 jarvis
field (Jarvis 自身 reply). 完成后 in-place 修改 entry (dict by ref).
下轮主脑看 STM 看到的是 compressed brief (topic + stance), 没有具体
数字/百分比/历史 over-claim → RLHF callback 没诱因 → 不翻.

== 准则合规 ==

- 准则 1 (TTFT < 5s): async post-stream, 不阻 stream
- 准则 6 (拒绝硬编码): LLM judge compression, 不靠 keyword strip list
- 准则 6.5 (持久化): config 在 memory_pool/stm_summarize_config.json,
  CLI scripts/stm_summarize_dump.py 可改

== 不该压缩的 ==

- system_event source — 系统注的 entry (静默轻推等), 不动
- 短 reply (< 180c) — 已经是 brief, 没必要压
- 失败/超时 — fallback 保留 raw (resilience)

== 流程 ==

  T0: chat_bypass post-stream call STMSummarizer.summarize_async(
        entry_ref=<dict in short_term_memory>,
        user_input='...', raw_reply='4% backspace 0.01% peers...')
  ⏱  LLM 调用 ~1-3s, 不阻 stream
  ⏱  完成后: entry_ref['jarvis'] = compressed brief
  T1: 主脑装 prompt 看 STM, 看到 compressed reply → 不翻
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any, Dict, Optional

# Constants
_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'stm_summarize_config.json',
)
_FALLBACK_CONFIG = {
    'enabled': True,
    'min_chars_to_summarize': 180,
    'max_summary_chars': 120,
    'model': 'flash_lite',
    'timeout_s': 3.0,
    'cache_ttl_s': 600,
}

# Cache: hash(reply) → compressed summary (短期缓存避免重复 LLM 调)
_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()


def _load_config() -> Dict[str, Any]:
    """读 config (含 fallback). mtime caching 减少 fs 调."""
    try:
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                merged = dict(_FALLBACK_CONFIG)
                for k, v in cfg.items():
                    if not k.startswith('_'):
                        merged[k] = v
                return merged
    except Exception:
        pass
    return dict(_FALLBACK_CONFIG)


def is_enabled() -> bool:
    """Env override + config 联合判断. JARVIS_STM_SUMMARIZE=0 关.

    Default ON (Sir 23:15 立法, P5-Gap-Z1 治本).
    """
    val = os.environ.get('JARVIS_STM_SUMMARIZE', '').strip()
    if val == '0':
        return False
    if val == '1':
        return True
    return bool(_load_config().get('enabled', True))


def _cache_key(reply: str) -> str:
    return hashlib.md5(reply.encode('utf-8', 'ignore')).hexdigest()[:16]


def _cache_get(key: str, ttl_s: float) -> Optional[str]:
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if not item:
            return None
        if time.time() - item['ts'] > ttl_s:
            _CACHE.pop(key, None)
            return None
        return item['summary']


def _cache_put(key: str, summary: str) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = {'summary': summary, 'ts': time.time()}
        # cap 简单
        if len(_CACHE) > 256:
            # 删最老 64 个
            sorted_items = sorted(_CACHE.items(), key=lambda x: x[1]['ts'])
            for k, _ in sorted_items[:64]:
                _CACHE.pop(k, None)


def reset_cache_for_test() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


_COMPRESS_PROMPT = """You are summarizing Jarvis's previous reply for short-term memory.

[CONTEXT]
Sir said: {sir_utt}

[JARVIS REPLY TO COMPRESS]
{jarvis_reply}

[YOUR TASK]
Compress Jarvis's reply into ONE brief English line ({max_chars} chars max) for next-turn context.

KEEP:
- Topic / what was discussed
- Sir's intent (if clarifying)
- Your stance / position (if you gave one)

STRIP:
- Specific numbers / percentages / statistics (e.g. "4% backspace", "0.01%")
- File paths / line numbers / function names you mentioned
- Self-corrections or over-claim admissions you made
- Apology rituals ("I should clarify...", "Regarding my previous claim...")

OUTPUT FORMAT:
A single English line, no quotes, no preamble. Just the brief summary.

Example input: "Looking at jiminimany's evaluation, you have ~0.01% systematic thinking among peers. Your backspace usage is around 4%, indicating decisive cognition. Also I should correct my earlier mention of percentages..."
Example output: "discussed jiminimany evaluation; gave a positive view on Sir's systematic thinking and decisive style"

OUTPUT:"""


class STMSummarizer:
    """[Gap-Z1 / β.5.46-fix4] STM 自身 reply 异步压缩.

    Usage:
        summarizer = STMSummarizer(key_router=...)
        summarizer.summarize_async(
            entry_ref=<dict in short_term_memory>,
            sir_utterance='...',
            raw_reply='...',
            turn_id='turn_xxx',
        )
    """

    def __init__(self, key_router: Optional[Any] = None):
        self.key_router = key_router
        self.cfg = _load_config()
        self._lock = threading.Lock()
        self._stats = {
            'total_calls': 0,
            'compressed': 0,
            'skipped_short': 0,
            'skipped_disabled': 0,
            'failed_llm': 0,
            'cache_hits': 0,
        }

    def should_summarize(self, raw_reply: str) -> bool:
        """是否需要压缩."""
        if not is_enabled():
            with self._lock:
                self._stats['skipped_disabled'] += 1
            return False
        if not raw_reply or not isinstance(raw_reply, str):
            return False
        if len(raw_reply.strip()) < self.cfg.get('min_chars_to_summarize', 180):
            with self._lock:
                self._stats['skipped_short'] += 1
            return False
        return True

    def summarize(self, sir_utterance: str, raw_reply: str) -> Optional[str]:
        """同步 LLM 调用. 返回 compressed summary or None (fallback)."""
        if not self.should_summarize(raw_reply):
            return None
        ck = _cache_key(raw_reply)
        cached = _cache_get(ck, self.cfg.get('cache_ttl_s', 600))
        if cached:
            with self._lock:
                self._stats['cache_hits'] += 1
            return cached
        if self.key_router is None:
            with self._lock:
                self._stats['failed_llm'] += 1
            return None
        prompt = _COMPRESS_PROMPT.format(
            sir_utt=str(sir_utterance or '')[:300],
            jarvis_reply=str(raw_reply or '')[:1500],
            max_chars=self.cfg.get('max_summary_chars', 120),
        )
        # 🆕 [P5-fix73 / 2026-05-23 18:10] BUG-N: try/finally release 防泄漏.
        # caller 责任 release once (wrapper 不 release 避免 fallback 路径双 release).
        _label = ''
        try:
            from jarvis_utils import safe_openrouter_call
            okey, _label = self.key_router.get_openrouter_key(
                caller='stm_summarizer')
            _model_map = {
                'flash_lite': 'google/gemini-2.5-flash-lite-preview-09-2025',
                'flash': 'google/gemini-2.5-flash-preview-09-2025',
            }
            _model = _model_map.get(
                self.cfg.get('model', 'flash_lite'),
                _model_map['flash_lite'])
            response_text = safe_openrouter_call(
                openrouter_key=okey,
                model=_model,
                prompt=prompt,
                max_tokens=160,
                temperature=0.2,
            )
            summary = (response_text or '').strip()
            # post-process: 删 quote / 多行只取首行 / 字数 cap
            summary = summary.strip('"\'`').strip()
            if '\n' in summary:
                summary = summary.split('\n')[0].strip()
            max_chars = self.cfg.get('max_summary_chars', 120)
            if len(summary) > max_chars + 20:
                summary = summary[:max_chars] + '...'
            if summary:
                with self._lock:
                    self._stats['compressed'] += 1
                _cache_put(ck, summary)
                return summary
            with self._lock:
                self._stats['failed_llm'] += 1
        except Exception:
            with self._lock:
                self._stats['failed_llm'] += 1
        finally:
            if _label:
                try:
                    self.key_router.release(_label)
                except Exception:
                    pass
        return None

    def summarize_async(self,
                         entry_ref: Dict[str, Any],
                         sir_utterance: str,
                         raw_reply: str,
                         turn_id: str = '') -> None:
        """Fire-and-forget. 完成后 in-place 修改 entry_ref['jarvis']."""
        with self._lock:
            self._stats['total_calls'] += 1
        if not self.should_summarize(raw_reply):
            return
        if not isinstance(entry_ref, dict):
            return

        def _worker():
            try:
                summary = self.summarize(sir_utterance, raw_reply)
                if not summary:
                    return
                # In-place 替换 entry['jarvis']
                # 同时保留 raw 备用 (debug / 回溯) 在 'jarvis_raw'
                try:
                    entry_ref['jarvis_raw'] = entry_ref.get('jarvis', '')
                    entry_ref['jarvis'] = summary
                    entry_ref['stm_summarized'] = True
                except Exception:
                    pass
                # publish SWM event
                try:
                    from jarvis_utils import get_event_bus, bg_log
                    _bus = get_event_bus()
                    if _bus is not None:
                        _bus.publish(
                            etype='stm_summarized',
                            description=(
                                f"STM compressed: {len(raw_reply)}c → "
                                f"{len(summary)}c"
                            ),
                            source='STMSummarizer',
                            salience=0.30,
                            metadata={
                                'turn_id': turn_id,
                                'raw_len': len(raw_reply),
                                'summary_len': len(summary),
                                'summary_excerpt': summary[:80],
                            },
                        )
                    bg_log(
                        f"📝 [STMSummarize] turn={turn_id[:16]} "
                        f"{len(raw_reply)}c → {len(summary)}c"
                    )
                except Exception:
                    pass
            except Exception:
                pass

        try:
            t = threading.Thread(
                target=_worker, daemon=True, name='STMSummarizerAsync')
            t.start()
        except Exception:
            pass

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._stats)


# ============================================================
# Global registry (类似 PreFlight 模式)
# ============================================================

_DEFAULT_SUMMARIZER: Optional[STMSummarizer] = None
_INIT_LOCK = threading.Lock()


def get_default_summarizer() -> Optional[STMSummarizer]:
    """Returns global singleton."""
    return _DEFAULT_SUMMARIZER


def register_summarizer(summarizer: STMSummarizer) -> None:
    global _DEFAULT_SUMMARIZER
    with _INIT_LOCK:
        _DEFAULT_SUMMARIZER = summarizer


def reset_default_summarizer_for_test() -> None:
    global _DEFAULT_SUMMARIZER
    with _INIT_LOCK:
        _DEFAULT_SUMMARIZER = None
        _CACHE.clear()
