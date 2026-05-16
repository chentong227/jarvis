# -*- coding: utf-8 -*-
"""[P0+20-β.0.5 / 2026-05-16] DirectiveEvaluator — Gemini-3-Flash 异步评分链

L2 directive 三层学习信号的第三层（详 docs/PROMPT_REFACTOR_PLAN.md §7）：
- fired: trigger 命中（100% 准）
- rejected: 行为信号采集（~85% 准 / 6 条 correction_loop 正则）
- helped: post-turn LLM 评分（~95% 准 / 本文件）

调用链（详 plan §7.2）：
[Jarvis stream_chat 完成] → ChatBypass.gatekeeper_async()
  → DirectiveEvaluator.evaluate_async(directives_fired, jarvis_reply, user_input)
  → ThreadPoolExecutor (size=4)
  → safe_openrouter_call(model='google/gemini-3-flash-preview', ...)
  → parse {is_followed: yes/no/partial, reason: str}
  → registry.record_helped(directive_id, helped=True/False)

关键约束：
- 评分调用走 OpenRouter（不抢主对话 google_pool 配额）
- 失败时（timeout / 配额 / network）静默丢弃，bg_log 一行，不影响 registry
- async pool size=4 + 60 calls/min rate limit 防刷爆

规范：详 docs/PROMPT_REFACTOR_PLAN.md §7
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import List, Optional

# 顶部 import 暴露 safe_openrouter_call 在本模块命名空间，让 testcase 能 mock。
# 失败时占位 None，运行时再 fallback 到 from jarvis_utils import。
try:
    from jarvis_utils import safe_openrouter_call  # noqa: F401
except Exception:
    safe_openrouter_call = None  # type: ignore


# ============================================================
# 配置
# ============================================================

EVALUATOR_CONFIG = {
    'primary_model': 'google/gemini-2.5-flash-preview-09-2025',
    'fallback_model': 'google/gemini-2.5-flash-lite-preview-09-2025',
    'temperature': 0.0,
    'max_output_tokens': 80,
    'timeout_s': 6.0,
    'async_pool_size': 4,
    'rate_limit_per_minute': 60,
}


EVALUATOR_PROMPT = """You are a directive compliance auditor. Given a directive and Jarvis's reply, judge whether the reply followed the directive.

[DIRECTIVE]:
{directive_text}

[USER INPUT]:
{user_input}

[JARVIS REPLY]:
{jarvis_reply}

Output ONLY a JSON object on a single line:
{{"is_followed": "yes" | "no" | "partial", "reason": "short reason ≤ 30 chars"}}

Rules:
- "yes" = reply clearly follows the directive instructions
- "no"  = reply ignores or violates the directive
- "partial" = reply addresses some but not all of the directive
"""


# ============================================================
# 数据结构
# ============================================================

@dataclass
class EvalResult:
    directive_id: str
    is_followed: str  # 'yes' | 'no' | 'partial' | 'unknown'
    reason: str = ''
    error: str = ''
    elapsed_ms: int = 0


# ============================================================
# 评分器
# ============================================================

class DirectiveEvaluator:
    """L2 directive 异步评分器 (β.0.5 / Gemini-3-Flash via OpenRouter)。
    
    用法：
        evaluator = DirectiveEvaluator(key_router=key_router, registry=registry)
        evaluator.evaluate_async(
            fired_directive_ids=['bilingual_directive', 'tool_honesty_directive'],
            user_input='set the volume to 30%',
            jarvis_reply='Done, Sir. ---ZH--- 已为您调整音量。'
        )
        # 评分异步跑，主路径不阻塞
    """

    def __init__(self, key_router=None, registry=None,
                 primary_model: Optional[str] = None,
                 fallback_model: Optional[str] = None,
                 timeout_s: Optional[float] = None,
                 pool_size: int = 4):
        self.key_router = key_router
        self.registry = registry
        self.primary_model = primary_model or EVALUATOR_CONFIG['primary_model']
        self.fallback_model = fallback_model or EVALUATOR_CONFIG['fallback_model']
        self.timeout_s = timeout_s or EVALUATOR_CONFIG['timeout_s']
        self._pool = ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix='DirEval')
        self._lock = threading.Lock()
        # rate limit 滑动窗口（unix ts list，最近 60s）
        self._call_times: list = []
        self._rate_limit_per_minute = EVALUATOR_CONFIG['rate_limit_per_minute']
        # 统计
        self.stats = {
            'submitted': 0,
            'completed': 0,
            'success': 0,
            'failed': 0,
            'rate_limited': 0,
            'helped_count': 0,
            'partial_count': 0,
            'not_helped_count': 0,
        }

    # ---- rate limit ----
    def _check_rate_limit(self) -> bool:
        """True = 可以发，False = 命中 rate limit 应跳过本次评分。"""
        now = time.time()
        with self._lock:
            self._call_times = [t for t in self._call_times if now - t < 60.0]
            if len(self._call_times) >= self._rate_limit_per_minute:
                return False
            self._call_times.append(now)
        return True

    # ---- 主接口 ----
    def evaluate_async(self, fired_directive_ids: List[str],
                       user_input: str,
                       jarvis_reply: str) -> None:
        """提交一批 directive 的评分任务到后台 pool。fire-and-forget，不返回 future。
        
        - 空 directive 列表 → 直接 return
        - 空 reply / user_input → 直接 return（评分需要内容）
        - rate limit 命中 → bg_log 一行，跳过本批
        - registry / key_router 缺失 → bg_log 一行，跳过
        """
        if not fired_directive_ids:
            return
        if not jarvis_reply or len(jarvis_reply.strip()) < 5:
            return
        if not user_input or len(user_input.strip()) < 1:
            return
        if self.registry is None or self.key_router is None:
            try:
                from jarvis_utils import bg_log
                bg_log("⚠️ [Evaluator] registry / key_router 缺失，跳过本批评分")
            except Exception:
                pass
            return
        if not self._check_rate_limit():
            self.stats['rate_limited'] += 1
            try:
                from jarvis_utils import bg_log
                bg_log(f"⚠️ [Evaluator] rate limit ({self._rate_limit_per_minute}/min) 命中，跳过本批 {len(fired_directive_ids)} 评分")
            except Exception:
                pass
            return

        for did in fired_directive_ids:
            d = self.registry.get(did) if hasattr(self.registry, 'get') else None
            if d is None:
                continue
            self.stats['submitted'] += 1
            self._pool.submit(
                self._evaluate_one,
                directive_id=did,
                directive_text=d.text,
                user_input=user_input,
                jarvis_reply=jarvis_reply,
            )

    # ---- 单条评分 ----
    def _evaluate_one(self, directive_id: str, directive_text: str,
                      user_input: str, jarvis_reply: str) -> EvalResult:
        t0 = time.time()
        result = EvalResult(directive_id=directive_id, is_followed='unknown')

        # 用模块级 safe_openrouter_call（顶部 import）；mock 时 testcase 走这条路径
        global safe_openrouter_call
        if safe_openrouter_call is None:
            try:
                from jarvis_utils import safe_openrouter_call as _sor
                safe_openrouter_call = _sor
            except Exception as e:
                result.error = f"import safe_openrouter_call failed: {e}"
                self._record_completion(result)
                return result

        try:
            okey, _label = self.key_router.get_openrouter_key(caller='evaluator')
        except Exception as e:
            result.error = f"key_router fail: {e}"
            self._record_completion(result)
            return result

        prompt = EVALUATOR_PROMPT.format(
            directive_text=directive_text[:600],
            user_input=user_input[:300],
            jarvis_reply=jarvis_reply[:600],
        )

        raw_resp = ""
        try:
            raw_resp = safe_openrouter_call(
                openrouter_key=okey,
                model=self.primary_model,
                prompt=prompt,
                max_tokens=EVALUATOR_CONFIG['max_output_tokens'],
                temperature=EVALUATOR_CONFIG['temperature'],
                max_retries=1,
                base_delay=0.5,
            )
        except Exception as e_primary:
            try:
                raw_resp = safe_openrouter_call(
                    openrouter_key=okey,
                    model=self.fallback_model,
                    prompt=prompt,
                    max_tokens=EVALUATOR_CONFIG['max_output_tokens'],
                    temperature=EVALUATOR_CONFIG['temperature'],
                    max_retries=1,
                    base_delay=0.5,
                )
            except Exception as e_fallback:
                result.error = f"primary={type(e_primary).__name__} / fallback={type(e_fallback).__name__}"
                self._record_completion(result)
                return result
        finally:
            try:
                self.key_router.release(_label)
            except Exception:
                pass

        result.is_followed, result.reason = _parse_eval_response(raw_resp)
        result.elapsed_ms = int((time.time() - t0) * 1000)
        self._record_completion(result)
        self._apply_to_registry(result)
        return result

    def _record_completion(self, result: EvalResult) -> None:
        with self._lock:
            self.stats['completed'] += 1
            if result.error:
                self.stats['failed'] += 1
            else:
                self.stats['success'] += 1
                if result.is_followed == 'yes':
                    self.stats['helped_count'] += 1
                elif result.is_followed == 'partial':
                    self.stats['partial_count'] += 1
                elif result.is_followed == 'no':
                    self.stats['not_helped_count'] += 1
        try:
            from jarvis_utils import bg_log
            if result.error:
                bg_log(f"⚠️ [Evaluator] {result.directive_id} fail: {result.error[:80]}")
            else:
                bg_log(
                    f"🎯 [Evaluator] {result.directive_id} → "
                    f"helped={result.is_followed} ({result.elapsed_ms}ms) reason={result.reason[:40]!r}"
                )
        except Exception:
            pass

    def _apply_to_registry(self, result: EvalResult) -> None:
        if self.registry is None:
            return
        if result.is_followed == 'yes':
            try:
                self.registry.record_helped(result.directive_id, helped=True)
            except Exception:
                pass
        elif result.is_followed == 'no':
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

_JSON_OBJECT_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _parse_eval_response(raw: str) -> tuple:
    """从 LLM 响应中提取 (is_followed, reason)。失败时返回 ('unknown', '')。"""
    if not raw:
        return ('unknown', '')
    txt = raw.strip()
    # 尝试整段直接 parse
    candidates = [txt]
    # 再加 regex 抓第一个 {...}
    m = _JSON_OBJECT_RE.search(txt)
    if m:
        candidates.append(m.group(0))
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                v = str(obj.get('is_followed', 'unknown')).strip().lower()
                r = str(obj.get('reason', ''))[:80]
                if v not in ('yes', 'no', 'partial'):
                    v = 'unknown'
                return (v, r)
        except Exception:
            continue
    txt_lower = txt.lower()
    for kw in ('"yes"', "'yes'", 'is_followed: yes', 'followed: yes'):
        if kw in txt_lower:
            return ('yes', '')
    for kw in ('"no"', "'no'", 'is_followed: no', 'followed: no', 'is_followed":"no"'):
        if kw in txt_lower:
            return ('no', '')
    for kw in ('"partial"', "'partial'", 'is_followed: partial', 'partially'):
        if kw in txt_lower:
            return ('partial', '')
    return ('unknown', '')


# ============================================================
# 单例 + 默认接入点
# ============================================================

_DEFAULT_EVALUATOR: Optional[DirectiveEvaluator] = None


def get_default_evaluator(key_router=None, registry=None) -> DirectiveEvaluator:
    """单例 evaluator。第一次调用时从 jarvis_directives 拿 default registry。"""
    global _DEFAULT_EVALUATOR
    if _DEFAULT_EVALUATOR is None:
        if registry is None:
            try:
                from jarvis_directives import get_default_registry
                registry = get_default_registry()
            except Exception:
                pass
        _DEFAULT_EVALUATOR = DirectiveEvaluator(key_router=key_router, registry=registry)
    elif registry is not None and _DEFAULT_EVALUATOR.registry is None:
        _DEFAULT_EVALUATOR.registry = registry
    if key_router is not None and _DEFAULT_EVALUATOR.key_router is None:
        _DEFAULT_EVALUATOR.key_router = key_router
    return _DEFAULT_EVALUATOR


def reset_default_evaluator_for_test() -> None:
    global _DEFAULT_EVALUATOR
    if _DEFAULT_EVALUATOR is not None:
        try:
            _DEFAULT_EVALUATOR.shutdown(wait=False)
        except Exception:
            pass
    _DEFAULT_EVALUATOR = None
