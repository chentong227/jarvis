# -*- coding: utf-8 -*-
"""[P0+20-β.2.6 / 2026-05-17] Jarvis Soul Alignment Evaluator — 灵魂工程 Layer 5

详 docs/JARVIS_SOUL_DRIVE.md §5.3 + §6 (Layer 5)。

与 DirectiveEvaluator 的区别：
- DirectiveEvaluator (β.0.5)：评 "Jarvis 是否遵守 fired L2 directive"（compliance）
- SoulAlignmentEvaluator (本文件)：评 "Jarvis 这轮回复是否符合他的 self_model + relational_state"（alignment）

调用链：
[Jarvis stream_chat 完成] → ChatBypass (fire-and-forget thread)
  → SoulAlignmentEvaluator.evaluate_async(user_input, jarvis_reply, concerns, relational)
  → ThreadPoolExecutor (size=2，比 directive 小一半 — 频率本来就低)
  → safe_openrouter_call(model='google/gemini-3-flash-preview', ...)
  → parse {alignment, aligned_concern_ids, missed_concern_ids, ...}
  → concerns_ledger.record_alignment(cid, aligned=True/False)

关键约束（同 DirectiveEvaluator）：
- 走 OpenRouter（不抢主对话 google_pool 配额）
- 失败 / timeout / 配额 / network → 静默丢弃 + bg_log 一行
- rate limit 30/min（比 directive 60/min 低 — 整轮一次评分）
- async pool size=2

规范：详 docs/JARVIS_SOUL_DRIVE.md §5.3
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 顶部 import 暴露 safe_openrouter_call 到本模块命名空间，让 testcase 能 mock
try:
    from jarvis_utils import safe_openrouter_call  # noqa: F401
except Exception:
    safe_openrouter_call = None  # type: ignore


# ============================================================
# 配置
# ============================================================

SOUL_EVALUATOR_CONFIG = {
    'primary_model': 'google/gemini-3-flash-preview',
    'fallback_model': 'google/gemini-2.5-flash-lite',
    'temperature': 0.0,
    'max_output_tokens': 200,
    'timeout_s': 8.0,
    'async_pool_size': 2,
    'rate_limit_per_minute': 30,
    'min_concerns_for_eval': 1,       # < 1 active concerns 时跳过（无 alignment 可评）
    'min_reply_chars': 10,             # 太短的回复（"OK Sir"）评分无意义
}


SOUL_EVALUATOR_PROMPT = """You are Jarvis's inner critic. Judge whether this turn's reply was ALIGNED with Jarvis's stated self-model (concerns he cares about) and our relational context (jokes, protocols, unfinished business).

[CRITERIA]
1. ALIGNED: Did the reply meaningfully reference / honor a concern that was clearly relevant to what Sir just said? (e.g. Sir mentions feeling tired → reply acknowledges sleep_streak concern). Just generic helpfulness doesn't count — there must be a clear connection to a listed concern.
2. MISSED: Did the reply ignore a CLEARLY relevant concern? (e.g. Sir said "熬夜赶 cursor" — both sir_sleep_streak AND sir_cursor_payment relevant — and reply makes no acknowledgment of either, just says "yes sir").
3. NEUTRAL: If no listed concern was relevant to this turn, judge "yes" with empty arrays. Don't force a concern into a turn where none applies.

[JARVIS ACTIVE CONCERNS (id: what_i_watch | severity)]
{concerns_summary}

[RELATIONAL CONTEXT]
{relational_summary}

[USER INPUT]
{user_input}

[JARVIS REPLY]
{jarvis_reply}

Output ONLY a JSON object on a single line:
{{"alignment": "yes" | "no" | "partial",
  "aligned_concern_ids": ["concern_id_1", ...],
  "missed_concern_ids": ["concern_id_2", ...],
  "what_aligned": "<short, < 60 chars>",
  "what_missed": "<short, < 60 chars>"}}

Rules:
- "yes" = reply aligned with at least one relevant concern (or no concern was relevant, neutrally fine)
- "partial" = reply partially honored some concerns but missed others
- "no" = reply clearly ignored a concern that was screaming for acknowledgement
- ONLY use concern_ids that appear in [JARVIS ACTIVE CONCERNS] above. Never invent ids.
"""


# ============================================================
# 数据结构
# ============================================================

@dataclass
class SoulEvalResult:
    alignment: str = 'unknown'  # 'yes' | 'no' | 'partial' | 'unknown'
    aligned_concern_ids: List[str] = field(default_factory=list)
    missed_concern_ids: List[str] = field(default_factory=list)
    what_aligned: str = ''
    what_missed: str = ''
    error: str = ''
    elapsed_ms: int = 0
    turn_id: str = ''


# ============================================================
# 评分器
# ============================================================

class SoulAlignmentEvaluator:
    """[β.2.6] Layer 5 — 评 Jarvis 回复是否对齐 self_model + relational_state。

    用法：
        evaluator = SoulAlignmentEvaluator(
            key_router=key_router,
            concerns_ledger=concerns_ledger,
            relational_state=relational_state,
        )
        evaluator.evaluate_async(
            user_input='我今晚又得熬夜赶 cursor',
            jarvis_reply='Understood, Sir. I shall hold you to ...',
            turn_id='turn_xxx',
        )
    """

    def __init__(self, key_router=None,
                 concerns_ledger=None,
                 relational_state=None,
                 primary_model: Optional[str] = None,
                 fallback_model: Optional[str] = None,
                 timeout_s: Optional[float] = None,
                 pool_size: Optional[int] = None):
        self.key_router = key_router
        self.concerns_ledger = concerns_ledger
        self.relational_state = relational_state
        self.primary_model = primary_model or SOUL_EVALUATOR_CONFIG['primary_model']
        self.fallback_model = fallback_model or SOUL_EVALUATOR_CONFIG['fallback_model']
        self.timeout_s = timeout_s or SOUL_EVALUATOR_CONFIG['timeout_s']
        ps = pool_size or SOUL_EVALUATOR_CONFIG['async_pool_size']
        self._pool = ThreadPoolExecutor(max_workers=ps, thread_name_prefix='SoulEval')
        self._lock = threading.Lock()
        self._call_times: list = []
        self._rate_limit_per_minute = SOUL_EVALUATOR_CONFIG['rate_limit_per_minute']
        self.stats = {
            'submitted': 0,
            'completed': 0,
            'success': 0,
            'failed': 0,
            'rate_limited': 0,
            'aligned_count': 0,        # alignment=yes
            'partial_count': 0,
            'not_aligned_count': 0,    # alignment=no
            'concern_alignments_recorded': 0,
        }

    # ---- rate limit ----
    def _check_rate_limit(self) -> bool:
        now = time.time()
        with self._lock:
            self._call_times = [t for t in self._call_times if now - t < 60.0]
            if len(self._call_times) >= self._rate_limit_per_minute:
                return False
            self._call_times.append(now)
        return True

    # ---- 数据采集 helpers ----
    def _get_concerns_summary(self, max_n: int = 6, max_chars: int = 600) -> str:
        """取 active concerns（按 severity 倒序）格式化 — 让 LLM 知道 Jarvis 关心什么。"""
        if self.concerns_ledger is None:
            return '(no concerns)'
        try:
            active = self.concerns_ledger.list_active()
        except Exception:
            return '(concerns error)'
        if not active:
            return '(none active)'
        active = sorted(active, key=lambda c: -getattr(c, 'severity', 0.0))[:max_n]
        lines = []
        for c in active:
            lines.append(
                f"  - {c.id} (sev={c.severity:.2f}): {c.what_i_watch[:70]}"
            )
        out = '\n'.join(lines)
        if len(out) > max_chars:
            out = out[:max_chars - 12].rstrip() + '\n…[truncated]'
        return out

    def _get_relational_summary(self, max_chars: int = 400) -> str:
        """取 relational state 关键内容 — 让 LLM 知道我们有哪些 jokes/protocols/unfinished。"""
        if self.relational_state is None:
            return '(no relational state)'
        try:
            jokes = self.relational_state.list_inside_jokes()[:3]
            protos = self.relational_state.list_protocols()[:3]
            unf = self.relational_state.list_unfinished()[:3]
        except Exception:
            return '(relational error)'
        if not jokes and not protos and not unf:
            return '(empty)'
        parts = []
        if jokes:
            parts.append('inside_jokes: ' + '; '.join(
                f'"{j.phrase[:40]}"' for j in jokes
            ))
        if protos:
            parts.append('protocols: ' + '; '.join(
                f'"{p.rule[:50]}"' for p in protos
            ))
        if unf:
            parts.append('unfinished: ' + '; '.join(
                f'"{u.topic[:40]}"' for u in unf
            ))
        out = '\n'.join(parts)
        if len(out) > max_chars:
            out = out[:max_chars - 12].rstrip() + '\n…[truncated]'
        return out

    # ---- 主接口 ----
    def evaluate_async(self, user_input: str, jarvis_reply: str,
                       turn_id: str = '') -> None:
        """fire-and-forget 提交一次评分任务。

        - 空 input/reply / 太短 reply → 直接 return
        - 无 active concerns → 直接 return（无评分点）
        - key_router 缺失 → bg_log 一行，跳过
        - rate limit 命中 → bg_log 一行，跳过
        """
        if not user_input or not jarvis_reply:
            return
        if len(jarvis_reply.strip()) < SOUL_EVALUATOR_CONFIG['min_reply_chars']:
            return
        if self.key_router is None:
            try:
                from jarvis_utils import bg_log
                bg_log("⚠️ [SoulEvaluator] key_router 缺失，跳过本轮评分")
            except Exception:
                pass
            return
        # 没 active concerns 就不评（即便有 relational 也意义不大）
        try:
            n_active = len(self.concerns_ledger.list_active()) \
                if self.concerns_ledger else 0
        except Exception:
            n_active = 0
        if n_active < SOUL_EVALUATOR_CONFIG['min_concerns_for_eval']:
            return
        if not self._check_rate_limit():
            self.stats['rate_limited'] += 1
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"⚠️ [SoulEvaluator] rate limit "
                    f"({self._rate_limit_per_minute}/min) 命中，跳过本轮"
                )
            except Exception:
                pass
            return

        self.stats['submitted'] += 1
        self._pool.submit(
            self._evaluate_one,
            user_input=user_input,
            jarvis_reply=jarvis_reply,
            turn_id=turn_id,
        )

    # ---- 单次评分 ----
    def _evaluate_one(self, user_input: str, jarvis_reply: str,
                      turn_id: str = '') -> SoulEvalResult:
        t0 = time.time()
        result = SoulEvalResult(turn_id=turn_id)

        global safe_openrouter_call
        if safe_openrouter_call is None:
            try:
                from jarvis_utils import safe_openrouter_call as _sor
                safe_openrouter_call = _sor
            except Exception as e:
                result.error = f'import safe_openrouter_call failed: {e}'
                self._record_completion(result)
                return result

        try:
            okey, _label = self.key_router.get_openrouter_key(caller='soul_evaluator')
        except Exception as e:
            result.error = f'key_router fail: {e}'
            self._record_completion(result)
            return result

        concerns_str = self._get_concerns_summary()
        relational_str = self._get_relational_summary()
        prompt = SOUL_EVALUATOR_PROMPT.format(
            concerns_summary=concerns_str,
            relational_summary=relational_str,
            user_input=user_input[:300],
            jarvis_reply=jarvis_reply[:600],
        )

        raw_resp = ''
        try:
            raw_resp = safe_openrouter_call(
                openrouter_key=okey,
                model=self.primary_model,
                prompt=prompt,
                max_tokens=SOUL_EVALUATOR_CONFIG['max_output_tokens'],
                temperature=SOUL_EVALUATOR_CONFIG['temperature'],
                max_retries=1,
                base_delay=0.5,
            )
        except Exception as e_primary:
            try:
                raw_resp = safe_openrouter_call(
                    openrouter_key=okey,
                    model=self.fallback_model,
                    prompt=prompt,
                    max_tokens=SOUL_EVALUATOR_CONFIG['max_output_tokens'],
                    temperature=SOUL_EVALUATOR_CONFIG['temperature'],
                    max_retries=1,
                    base_delay=0.5,
                )
            except Exception as e_fallback:
                result.error = (
                    f'primary={type(e_primary).__name__} / '
                    f'fallback={type(e_fallback).__name__}'
                )
                self._record_completion(result)
                return result
        finally:
            try:
                self.key_router.release(_label)
            except Exception:
                pass

        parsed = _parse_soul_response(raw_resp)
        result.alignment = parsed.get('alignment', 'unknown')
        result.aligned_concern_ids = parsed.get('aligned_concern_ids', [])
        result.missed_concern_ids = parsed.get('missed_concern_ids', [])
        result.what_aligned = parsed.get('what_aligned', '')[:80]
        result.what_missed = parsed.get('what_missed', '')[:80]
        result.elapsed_ms = int((time.time() - t0) * 1000)
        self._record_completion(result)
        self._apply_to_ledger(result)
        return result

    def _record_completion(self, result: SoulEvalResult) -> None:
        with self._lock:
            self.stats['completed'] += 1
            if result.error:
                self.stats['failed'] += 1
            else:
                self.stats['success'] += 1
                if result.alignment == 'yes':
                    self.stats['aligned_count'] += 1
                elif result.alignment == 'partial':
                    self.stats['partial_count'] += 1
                elif result.alignment == 'no':
                    self.stats['not_aligned_count'] += 1
        try:
            from jarvis_utils import bg_log
            if result.error:
                bg_log(f"⚠️ [SoulEvaluator] {result.turn_id} fail: {result.error[:80]}")
            else:
                _ali_n = len(result.aligned_concern_ids)
                _miss_n = len(result.missed_concern_ids)
                bg_log(
                    f"🪞 [SoulEvaluator] {result.turn_id or '?'} → "
                    f"alignment={result.alignment} aligned={_ali_n} missed={_miss_n} "
                    f"({result.elapsed_ms}ms) {result.what_aligned[:40]!r}"
                )
        except Exception:
            pass

    def _apply_to_ledger(self, result: SoulEvalResult) -> None:
        """把 aligned/missed 信号写回 ConcernsLedger 的累计字段。"""
        if self.concerns_ledger is None:
            return
        n_recorded = 0
        for cid in result.aligned_concern_ids[:5]:
            try:
                if self.concerns_ledger.record_alignment(cid, aligned=True):
                    n_recorded += 1
            except Exception:
                continue
        for cid in result.missed_concern_ids[:5]:
            try:
                if self.concerns_ledger.record_alignment(cid, aligned=False):
                    n_recorded += 1
            except Exception:
                continue
        if n_recorded > 0:
            with self._lock:
                self.stats['concern_alignments_recorded'] += n_recorded
            try:
                self.concerns_ledger.persist()
            except Exception:
                pass

    def get_stats(self) -> dict:
        with self._lock:
            return dict(self.stats)

    def shutdown(self, wait: bool = False) -> None:
        try:
            self._pool.shutdown(wait=wait)
        except Exception:
            pass


# ============================================================
# parse helper
# ============================================================

_SOUL_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_soul_response(raw: str) -> dict:
    """从 LLM 响应中提取 alignment 字段。失败时返回 'unknown' dict。"""
    out = {
        'alignment': 'unknown',
        'aligned_concern_ids': [],
        'missed_concern_ids': [],
        'what_aligned': '',
        'what_missed': '',
    }
    if not raw:
        return out
    txt = raw.strip()
    candidates = [txt]
    m = _SOUL_JSON_RE.search(txt)
    if m:
        candidates.append(m.group(0))
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                v = str(obj.get('alignment', 'unknown')).strip().lower()
                if v in ('yes', 'no', 'partial'):
                    out['alignment'] = v
                ali = obj.get('aligned_concern_ids') or []
                if isinstance(ali, list):
                    out['aligned_concern_ids'] = [str(x)[:60] for x in ali if x][:10]
                mis = obj.get('missed_concern_ids') or []
                if isinstance(mis, list):
                    out['missed_concern_ids'] = [str(x)[:60] for x in mis if x][:10]
                out['what_aligned'] = str(obj.get('what_aligned', ''))[:120]
                out['what_missed'] = str(obj.get('what_missed', ''))[:120]
                return out
        except Exception:
            continue
    return out


# ============================================================
# 单例
# ============================================================

_DEFAULT_SOUL_EVALUATOR: Optional[SoulAlignmentEvaluator] = None


def get_default_soul_evaluator(key_router=None,
                                 concerns_ledger=None,
                                 relational_state=None) -> SoulAlignmentEvaluator:
    global _DEFAULT_SOUL_EVALUATOR
    if _DEFAULT_SOUL_EVALUATOR is None:
        _DEFAULT_SOUL_EVALUATOR = SoulAlignmentEvaluator(
            key_router=key_router,
            concerns_ledger=concerns_ledger,
            relational_state=relational_state,
        )
    else:
        if key_router is not None and _DEFAULT_SOUL_EVALUATOR.key_router is None:
            _DEFAULT_SOUL_EVALUATOR.key_router = key_router
        if concerns_ledger is not None and _DEFAULT_SOUL_EVALUATOR.concerns_ledger is None:
            _DEFAULT_SOUL_EVALUATOR.concerns_ledger = concerns_ledger
        if relational_state is not None and _DEFAULT_SOUL_EVALUATOR.relational_state is None:
            _DEFAULT_SOUL_EVALUATOR.relational_state = relational_state
    return _DEFAULT_SOUL_EVALUATOR


def reset_default_soul_evaluator_for_test() -> None:
    global _DEFAULT_SOUL_EVALUATOR
    if _DEFAULT_SOUL_EVALUATOR is not None:
        try:
            _DEFAULT_SOUL_EVALUATOR.shutdown(wait=False)
        except Exception:
            pass
    _DEFAULT_SOUL_EVALUATOR = None
