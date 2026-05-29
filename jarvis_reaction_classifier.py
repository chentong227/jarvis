# -*- coding: utf-8 -*-
"""[Sir 2026-05-29 Option A] ReactionClassifier — Sir 反应分类器 (#2)

docs/JARVIS_CLOSURE_AND_RELATIONAL_UPLIFT_DESIGN.md §3 #2.

两层:
- classify_fast(text): 纯 vocab, O(1), 热路径用. 出 'engaged'/'rejected'
  (喂 V6 meta_feedback_loop). 'ignored' 来自静默 sweep, 非本函数.
- judge_behavioral_reject_async(...): 异步 LLM (仿 DirectiveEvaluator), 仅当
  classify_fast 命中 negative_candidates 才提交 (预筛闸, 不每轮调). LLM 判 Sir
  是否在"纠正 Jarvis 行为"(behavioral_reject) vs 泛泛不满/外部情绪 → yes 才
  registry.record_rejection(prev_fired_ids) (= #1 精准归因, 接通生产从未接线的
  rejected 强闭环).

准则:
- §1 TTFT: fast 在热路径 O(1); LLM 异步 fire-and-forget + 预筛闸 → 不阻 stream.
- §6: vocab 持久化 memory_pool/reaction_vocab.json + CLI scripts/reaction_vocab_dump.py
       + L7 reflector (TODO). JSON 缺/损坏 → fallback DEFAULTS (preserve 可用).
- §5: behavioral_reject=yes 才衰减, 不假装; 失败静默丢弃.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Optional, Tuple

# 顶部 import 暴露 safe_openrouter_call 在本模块命名空间，让 testcase 能 mock。
try:
    from jarvis_utils import safe_openrouter_call  # noqa: F401
except Exception:
    safe_openrouter_call = None  # type: ignore


# ==========================================================================
# Path + fallback defaults (JSON 缺/损坏时用)
# ==========================================================================
DEFAULT_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool',
    'reaction_vocab.json',
)

_DEFAULT_NEGATIVE_CANDIDATES = (
    '别提', '别说', '不要', '别再', '烦死', '够了', '别了',
    '不对', '错了', '不用', '醒醒', 'stop', 'enough', "don't",
    '不是这个', '不是我想要', '不太对', '不太行', '答非所问', '跑题',
    '听错', '误会', '重说', '重新说', '搞错', '你错了', '别闹', '说错',
)
_DEFAULT_SOFT = ('算了', '无所谓', '随便')
_DEFAULT_IGNORED_AFTER_MIN = 8.0


# ==========================================================================
# Config + Prompt (异步 LLM)
# ==========================================================================
CLASSIFIER_CONFIG = {
    'primary_model': 'google/gemini-3-flash-preview',
    'fallback_model': 'google/gemini-2.5-flash-lite',
    'temperature': 0.0,
    'max_output_tokens': 60,
    'timeout_s': 6.0,
    'async_pool_size': 2,
    'rate_limit_per_minute': 30,
}

CLASSIFIER_PROMPT = """You are an auditor judging Sir's reaction to Jarvis's previous reply.
Decide if Sir's NEW message is a BEHAVIORAL correction of Jarvis — i.e. Jarvis did something wrong in HOW it responded (wrong/off-topic content, ignored an instruction, hallucinated, bad tone, too pushy) — as opposed to Sir merely venting about something external, a neutral acknowledgement, or simply changing topic.

[JARVIS PREVIOUS REPLY]:
{prev_reply}

[SIR NEW MESSAGE]:
{sir_input}

Output ONLY a JSON object on a single line:
{{"behavioral_reject": "yes" | "no", "reason": "short reason <= 30 chars"}}

Rules:
- "yes" = Sir is correcting / rejecting Jarvis's behavior or reply itself
- "no"  = Sir venting about external things / neutral / new topic / mild dissatisfaction not aimed at Jarvis
"""


# ==========================================================================
# Vocab cache (mtime throttle, 仿 jarvis_runtime_log_markers._Cache)
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
        self._neg_cache: Tuple[str, ...] = ()
        self._gate_cache: Tuple[str, ...] = ()

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
            self._neg_cache = ()
            self._gate_cache = ()
        except Exception:
            pass

    def ensure_loaded(self, path: str) -> None:
        now = time.time()
        if now - self._last_check_ts < self._check_interval and self._data:
            return
        self._last_check_ts = now
        self._load_from_disk(path)

    def get_negative_candidates(self) -> Tuple[str, ...]:
        if self._neg_cache:
            return self._neg_cache
        lst = self._data.get('negative_candidates')
        if isinstance(lst, list) and lst:
            tup = tuple(str(x) for x in lst if x)
            self._neg_cache = tup
            return tup
        return _DEFAULT_NEGATIVE_CANDIDATES

    def get_soft_terms(self) -> Tuple[str, ...]:
        lst = self._data.get('soft')
        if isinstance(lst, list) and lst:
            return tuple(str(x) for x in lst if x)
        return _DEFAULT_SOFT

    def get_gate_terms(self) -> Tuple[str, ...]:
        """预筛闸词 (宽): negative_candidates ∪ soft — 让 LLM 判边界."""
        if self._gate_cache:
            return self._gate_cache
        tup = tuple(dict.fromkeys(
            self.get_negative_candidates() + self.get_soft_terms()))
        self._gate_cache = tup
        return tup

    def get_ignored_after_min(self) -> float:
        v = self._data.get('ignored_after_min')
        try:
            if v is not None:
                return float(v)
        except Exception:
            pass
        return _DEFAULT_IGNORED_AFTER_MIN

    def invalidate(self) -> None:
        self._mtime = 0.0
        self._last_check_ts = 0.0
        self._neg_cache = ()
        self._gate_cache = ()


# ==========================================================================
# Public vocab API
# ==========================================================================
def load_negative_candidates(path: str = DEFAULT_VOCAB_PATH) -> Tuple[str, ...]:
    cache = _VocabCache()
    cache.ensure_loaded(path)
    return cache.get_negative_candidates()


def load_ignored_after_min(path: str = DEFAULT_VOCAB_PATH) -> float:
    cache = _VocabCache()
    cache.ensure_loaded(path)
    return cache.get_ignored_after_min()


def has_negative_candidate(text: str, path: str = DEFAULT_VOCAB_PATH) -> bool:
    """预筛闸 (宽) — text 含 negative_candidates ∪ soft 任一 → 提交 behavioral_reject LLM.

    闸宽是为了不漏边界 (如 '算了/无所谓'), 交 LLM 精判; 不宽会让 #1 漏拍.
    """
    if not text or not text.strip():
        return False
    low = ' ' + text.lower() + ' '
    cache = _VocabCache()
    cache.ensure_loaded(path)
    return any(kw and kw.lower() in low for kw in cache.get_gate_terms())


def classify_fast(text: str, path: str = DEFAULT_VOCAB_PATH) -> str:
    """纯 vocab O(1) → 'rejected' (命中 negative_candidates, 窄) / 'engaged'.

    soft 词 (算了/无所谓) 不在此判 rejected (避免 meta loop 误标); 仅进 LLM 闸.
    'ignored' 来自静默 sweep (jarvis_inner_thought_daemon), 非本函数.
    喂 V6 meta_feedback_loop (热路径用).
    """
    if not text or not text.strip():
        return 'engaged'
    low = ' ' + text.lower() + ' '
    return ('rejected' if any(kw and kw.lower() in low
                              for kw in load_negative_candidates(path))
            else 'engaged')


# ---- CLI helpers (准则 6) ----
_VALID_KINDS = ('negative_candidates', 'strong_correction', 'soft')


def add_term(term: str, kind: str = 'negative_candidates',
             path: str = DEFAULT_VOCAB_PATH, source: str = 'cli') -> bool:
    if not term or not term.strip() or kind not in _VALID_KINDS:
        return False
    term = term.strip()
    try:
        if not os.path.exists(path):
            return False
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        lst = data.get(kind) or []
        if term in lst:
            return False
        lst.append(term)
        data[kind] = lst
        hist = data.get('history') or []
        hist.append({'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
                     'op': 'add', 'kind': kind, 'term': term, 'source': source})
        data['history'] = hist
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _VocabCache().invalidate()
        return True
    except Exception:
        return False


def remove_term(term: str, kind: str = 'negative_candidates',
                path: str = DEFAULT_VOCAB_PATH, source: str = 'cli') -> bool:
    if not term or not term.strip() or kind not in _VALID_KINDS:
        return False
    term = term.strip()
    try:
        if not os.path.exists(path):
            return False
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        lst = data.get(kind) or []
        if term not in lst:
            return False
        lst.remove(term)
        data[kind] = lst
        hist = data.get('history') or []
        hist.append({'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
                     'op': 'remove', 'kind': kind, 'term': term,
                     'source': source})
        data['history'] = hist
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _VocabCache().invalidate()
        return True
    except Exception:
        return False


def list_all(path: str = DEFAULT_VOCAB_PATH) -> dict:
    try:
        if not os.path.exists(path):
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


# ==========================================================================
# 异步 behavioral_reject 判定 (仿 DirectiveEvaluator)
# ==========================================================================
@dataclass
class ReactionResult:
    behavioral_reject: str = 'unknown'  # 'yes' | 'no' | 'unknown'
    reason: str = ''
    error: str = ''
    n_fired: int = 0
    elapsed_ms: int = 0


class ReactionClassifier:
    """Sir 反应异步 LLM 判定器 — behavioral_reject=yes → record_rejection(fired)."""

    def __init__(self, key_router=None, registry=None,
                 primary_model: Optional[str] = None,
                 fallback_model: Optional[str] = None,
                 timeout_s: Optional[float] = None,
                 pool_size: Optional[int] = None):
        self.key_router = key_router
        self.registry = registry
        self.primary_model = primary_model or CLASSIFIER_CONFIG['primary_model']
        self.fallback_model = fallback_model or CLASSIFIER_CONFIG['fallback_model']
        self.timeout_s = timeout_s or CLASSIFIER_CONFIG['timeout_s']
        self._pool = ThreadPoolExecutor(
            max_workers=pool_size or CLASSIFIER_CONFIG['async_pool_size'],
            thread_name_prefix='ReactCls')
        self._lock = threading.Lock()
        self._call_times: list = []
        self._rate_limit_per_minute = CLASSIFIER_CONFIG['rate_limit_per_minute']
        self.stats = {
            'submitted': 0, 'completed': 0, 'success': 0, 'failed': 0,
            'rate_limited': 0, 'behavioral_reject_yes': 0,
            'behavioral_reject_no': 0, 'recorded_rejection': 0,
        }

    def _check_rate_limit(self) -> bool:
        now = time.time()
        with self._lock:
            self._call_times = [t for t in self._call_times if now - t < 60.0]
            if len(self._call_times) >= self._rate_limit_per_minute:
                return False
            self._call_times.append(now)
        return True

    def judge_behavioral_reject_async(self, sir_input: str, prev_reply: str,
                                      prev_fired_ids: List[str]) -> None:
        """fire-and-forget. 仅当预筛闸命中才提交 (不每轮调 LLM).

        - prev_fired_ids 空 → return (无可归因 directive)
        - sir_input 非疑似负面 (预筛闸) → return (省 LLM)
        - registry / key_router 缺失 → return
        - rate limit → return
        """
        if not prev_fired_ids:
            return
        if not sir_input or not has_negative_candidate(sir_input):
            return
        if self.registry is None or self.key_router is None:
            return
        if not self._check_rate_limit():
            self.stats['rate_limited'] += 1
            return
        self.stats['submitted'] += 1
        self._pool.submit(
            self._judge_one,
            sir_input=str(sir_input),
            prev_reply=str(prev_reply or ''),
            prev_fired_ids=list(prev_fired_ids),
        )

    def _judge_one(self, sir_input: str, prev_reply: str,
                   prev_fired_ids: List[str]) -> ReactionResult:
        t0 = time.time()
        result = ReactionResult(n_fired=len(prev_fired_ids))

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
            okey, _label = self.key_router.get_openrouter_key(
                caller='reaction_classifier')
        except Exception as e:
            result.error = f"key_router fail: {e}"
            self._record_completion(result)
            return result

        prompt = CLASSIFIER_PROMPT.format(
            prev_reply=prev_reply[:600],
            sir_input=sir_input[:300],
        )
        raw_resp = ""
        try:
            raw_resp = safe_openrouter_call(
                openrouter_key=okey, model=self.primary_model, prompt=prompt,
                max_tokens=CLASSIFIER_CONFIG['max_output_tokens'],
                temperature=CLASSIFIER_CONFIG['temperature'],
                max_retries=1, base_delay=0.5,
            )
        except Exception as e_primary:
            try:
                raw_resp = safe_openrouter_call(
                    openrouter_key=okey, model=self.fallback_model,
                    prompt=prompt,
                    max_tokens=CLASSIFIER_CONFIG['max_output_tokens'],
                    temperature=CLASSIFIER_CONFIG['temperature'],
                    max_retries=1, base_delay=0.5,
                )
            except Exception as e_fb:
                result.error = (f"primary={type(e_primary).__name__} / "
                                f"fallback={type(e_fb).__name__}")
                self._record_completion(result)
                return result
        finally:
            try:
                self.key_router.release(_label)
            except Exception:
                pass

        result.behavioral_reject, result.reason = _parse_reaction_response(
            raw_resp)
        result.elapsed_ms = int((time.time() - t0) * 1000)
        self._record_completion(result)
        self._apply_to_registry(result, prev_fired_ids)
        return result

    def _record_completion(self, result: ReactionResult) -> None:
        with self._lock:
            self.stats['completed'] += 1
            if result.error:
                self.stats['failed'] += 1
            else:
                self.stats['success'] += 1
                if result.behavioral_reject == 'yes':
                    self.stats['behavioral_reject_yes'] += 1
                elif result.behavioral_reject == 'no':
                    self.stats['behavioral_reject_no'] += 1
        try:
            from jarvis_utils import bg_log
            if result.error:
                bg_log(f"⚠️ [ReactCls] fail: {result.error[:80]}")
            else:
                bg_log(
                    f"🎯 [ReactCls] behavioral_reject={result.behavioral_reject} "
                    f"n_fired={result.n_fired} ({result.elapsed_ms}ms) "
                    f"reason={result.reason[:40]!r}"
                )
        except Exception:
            pass

    def _apply_to_registry(self, result: ReactionResult,
                           prev_fired_ids: List[str]) -> None:
        """behavioral_reject=yes → record_rejection(fired). = #1 精准归因.

        priority>=10 红线 directive 由 apply_decay:293 既有保护, 不在此处特判.
        """
        if result.behavioral_reject != 'yes' or self.registry is None:
            return
        try:
            self.registry.record_rejection(prev_fired_ids)
            with self._lock:
                self.stats['recorded_rejection'] += 1
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


# ==========================================================================
# parse helper
# ==========================================================================
_JSON_OBJECT_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _parse_reaction_response(raw: str) -> Tuple[str, str]:
    """提取 (behavioral_reject, reason). 失败 → ('unknown', '')."""
    if not raw:
        return ('unknown', '')
    txt = raw.strip()
    candidates = [txt]
    m = _JSON_OBJECT_RE.search(txt)
    if m:
        candidates.append(m.group(0))
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                v = str(obj.get('behavioral_reject', 'unknown')).strip().lower()
                r = str(obj.get('reason', ''))[:80]
                if v not in ('yes', 'no'):
                    v = 'unknown'
                return (v, r)
        except Exception:
            continue
    low = txt.lower()
    for kw in ('"yes"', "'yes'", 'behavioral_reject: yes', 'reject":"yes"'):
        if kw in low:
            return ('yes', '')
    for kw in ('"no"', "'no'", 'behavioral_reject: no', 'reject":"no"'):
        if kw in low:
            return ('no', '')
    return ('unknown', '')


# ==========================================================================
# 单例 + 默认接入点
# ==========================================================================
_DEFAULT_CLASSIFIER: Optional[ReactionClassifier] = None


def get_default_reaction_classifier(key_router=None,
                                    registry=None) -> ReactionClassifier:
    global _DEFAULT_CLASSIFIER
    if _DEFAULT_CLASSIFIER is None:
        if registry is None:
            try:
                from jarvis_directives import get_default_registry
                registry = get_default_registry()
            except Exception:
                pass
        _DEFAULT_CLASSIFIER = ReactionClassifier(
            key_router=key_router, registry=registry)
    else:
        if registry is not None and _DEFAULT_CLASSIFIER.registry is None:
            _DEFAULT_CLASSIFIER.registry = registry
        if key_router is not None and _DEFAULT_CLASSIFIER.key_router is None:
            _DEFAULT_CLASSIFIER.key_router = key_router
    return _DEFAULT_CLASSIFIER


def reset_default_classifier_for_test() -> None:
    global _DEFAULT_CLASSIFIER
    if _DEFAULT_CLASSIFIER is not None:
        try:
            _DEFAULT_CLASSIFIER.shutdown(wait=False)
        except Exception:
            pass
    _DEFAULT_CLASSIFIER = None
