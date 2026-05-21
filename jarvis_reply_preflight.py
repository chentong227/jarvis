# -*- coding: utf-8 -*-
"""[Gap 2 / P5-PreFlight / 2026-05-21 00:00] Reply Pre-Flight — 主脑说之前先 self-check

Sir 22:04 / 22:19 / 23:02 / 23:43 / 23:49 反复 5 次 unsolicited apology callback.
P0+P1+P2+P3+P4 修了 signature / publish / SoftFocus / grace / SWM 等多层, 也加
always-on past_action_honesty directive — 但**主脑仍 callback 道歉** (Sir 简单
ack 时, directive cluster 太多被淹).

真治根: pre-flight self-check. 主脑生成 draft → Pass 2 极简 LLM call 看 draft +
Sir 当前 turn + Sir mental state → 3 self-question:
  Q1: Did Sir actually ask / need what my draft is saying?
      (检测 unsolicited callback / 主动翻老账)
  Q2: Does my draft tone match Sir's current state + our relational temp?
      (检测过度 self-flagellation / off-tone)
  Q3: Are all factual claims (past actions/timestamps/numbers/quotas) 
      backed by real evidence?
      (检测 hallucination — Sir 22:44/23:32/23:38 "trial quota"/"11:59 PM")

verdict: pass / edit / scrap → 输出 draft / edited / 重写

Design doc: docs/JARVIS_REPLY_PREFLIGHT.md
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Optional


# ============================================================
# Config
# ============================================================

_DEFAULT_CONFIG = {
    'model': 'flash_lite',                  # quick + cheap
    'timeout_s': 1.5,                        # max wait, fallback draft
    'cache_ttl_s': 30,                       # 同 (sir_input + draft) hash cache
    'max_scrap_retry': 1,                    # 1 retry, 2nd fail force output
    'stats_path': os.path.join('memory_pool', 'preflight_stats.jsonl'),
    'max_stats_keep': 1000,                  # rolling
}


_PREFLIGHT_PROMPT_TEMPLATE = """[ROLE] You are Jarvis's self-check before reply, separate from main brain.

[SIR JUST SAID THIS TURN]
"{sir_utterance}"

[YOUR DRAFT REPLY]
"{draft_reply}"

[CURRENT STATE]
{state_summary}

[CHECK - 3 questions]

Q1 (UNSOLICITED CALLBACK):
Did Sir actually ask about / need what your draft is saying?
- REJECT if draft brings up topics Sir didn't mention this turn (e.g. apologizing
  for "previous claim about hydration logs" when Sir just said "好的好的").
- REJECT if draft includes "I must correct myself / Regarding my previous claim..."
  unsolicited.

Q2 (TONE MISMATCH):
Does draft tone match Sir's current emotional state + our relational temp?
- REJECT if draft is too cold / too self-flagellating / over-formal when Sir is casual.

Q3 (FACTUAL HALLUCINATION):
Are all specific factual claims (past actions / timestamps / numbers / quotas)
backed by real evidence in state above OR explicitly marked uncertain?
- REJECT if draft invents specific facts (e.g. "trial quota reached" when no
  quota system exists, "11:59 PM" when actual deadline is 23:30).

[OUTPUT JSON ONLY, no markdown]
{{"verdict": "pass" | "edit" | "scrap",
  "issues": ["..."],
  "edited_reply": "..."}}

Rules:
- verdict=pass: draft is fine, output as-is. Leave edited_reply="".
- verdict=edit: output edited_reply (max 500 chars, keep core ack, drop offending part).
- verdict=scrap: force main brain regenerate. Set scrap_reason to issues[0].
- DEFAULT to pass unless clear Q1/Q2/Q3 violation. Don't be over-cautious.
- Empty/blank draft → "pass" (let it through, main brain may be intentionally silent).

ABSOLUTE: output VALID JSON only. No markdown fence. No prose.
"""


# ============================================================
# Cache
# ============================================================

_VERDICT_CACHE: Dict[str, dict] = {}
_VERDICT_CACHE_LOCK = threading.Lock()


def _cache_key(sir_utterance: str, draft_reply: str) -> str:
    """Hash (sir+draft) for cache lookup."""
    import hashlib
    raw = (sir_utterance or '')[:200] + '|' + (draft_reply or '')[:300]
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def _cache_get(key: str, ttl_s: float) -> Optional[dict]:
    with _VERDICT_CACHE_LOCK:
        entry = _VERDICT_CACHE.get(key)
        if not entry:
            return None
        if time.time() - entry.get('ts', 0) > ttl_s:
            return None
        return entry.get('verdict')


def _cache_put(key: str, verdict: dict) -> None:
    with _VERDICT_CACHE_LOCK:
        _VERDICT_CACHE[key] = {'ts': time.time(), 'verdict': verdict}
        # rolling cap 200
        if len(_VERDICT_CACHE) > 200:
            sorted_keys = sorted(_VERDICT_CACHE.items(), key=lambda kv: kv[1]['ts'])
            for k, _ in sorted_keys[:50]:
                _VERDICT_CACHE.pop(k, None)


# ============================================================
# Stats persistence
# ============================================================

_STATS_LOCK = threading.Lock()


def _record_stats(verdict_data: dict, latency_ms: float, sir_utt: str,
                   draft_len: int) -> None:
    """Append verdict to preflight_stats.jsonl (rolling)."""
    try:
        path = _DEFAULT_CONFIG['stats_path']
        os.makedirs(os.path.dirname(path), exist_ok=True)
        entry = {
            'ts': time.time(),
            'iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
            'verdict': verdict_data.get('verdict', 'unknown'),
            'issues': verdict_data.get('issues', [])[:3],
            'latency_ms': round(latency_ms, 1),
            'sir_utterance_excerpt': (sir_utt or '')[:80],
            'draft_len': draft_len,
            'edited': bool(verdict_data.get('edited_reply')),
        }
        with _STATS_LOCK:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        # rotation cheap (every 50 writes)
        try:
            from jarvis_jsonl_rotator import maybe_rotate as _mr
            _mr(path, size_mb_cap=5.0)
        except Exception:
            pass
    except Exception:
        pass


# ============================================================
# Main API
# ============================================================

class ReplyPreFlight:
    """Pre-flight check on main brain draft before output.

    Usage:
        preflight = ReplyPreFlight(key_router=...)
        verdict = preflight.check(
            sir_utterance="好的好的",
            draft_reply="I must correct myself...",
            state_summary="Sir is casual mode, relational warm",
        )
        if verdict['verdict'] == 'pass':
            output(draft_reply)
        elif verdict['verdict'] == 'edit':
            output(verdict['edited_reply'])
        elif verdict['verdict'] == 'scrap':
            regenerate(scrap_reason=verdict['scrap_reason'])
    """

    def __init__(self, key_router=None, config: Optional[Dict] = None):
        self.key_router = key_router
        self.config = dict(_DEFAULT_CONFIG)
        if config:
            self.config.update(config)
        self._lock = threading.Lock()
        self._stats = {
            'total_checks': 0,
            'pass_count': 0,
            'edit_count': 0,
            'scrap_count': 0,
            'llm_fail_count': 0,
            'cache_hit_count': 0,
        }

    def check(self,
              sir_utterance: str,
              draft_reply: str,
              state_summary: str = '',
              turn_id: str = '') -> Dict[str, Any]:
        """Pre-flight check. Returns verdict dict.

        Returns:
          {
            'verdict': 'pass' | 'edit' | 'scrap',
            'issues': ['...'],
            'edited_reply': '...' (if verdict=edit),
            'scrap_reason': '...' (if verdict=scrap),
            'latency_ms': float,
            '_cached': bool,
            '_fallback': bool,  # True if LLM failed and we default-pass
          }

        Default pass on:
          - empty draft (silence)
          - LLM fail / timeout
          - JSON parse fail
        """
        _t_start = time.time()

        # short-circuit: empty draft → pass (silence is OK)
        if not draft_reply or not draft_reply.strip():
            return self._make_result('pass', latency_ms=0, fallback=False,
                                       reason='empty_draft')

        # cache check
        ckey = _cache_key(sir_utterance, draft_reply)
        cached = _cache_get(ckey, self.config['cache_ttl_s'])
        if cached:
            with self._lock:
                self._stats['cache_hit_count'] += 1
            cached = dict(cached)
            cached['_cached'] = True
            cached['latency_ms'] = 0
            return cached

        # short-circuit: no key router → fallback pass
        if self.key_router is None:
            with self._lock:
                self._stats['llm_fail_count'] += 1
            return self._make_result('pass', latency_ms=0, fallback=True,
                                       reason='no_key_router')

        # LLM call
        prompt = _PREFLIGHT_PROMPT_TEMPLATE.format(
            sir_utterance=str(sir_utterance or '')[:300],
            draft_reply=str(draft_reply or '')[:500],
            state_summary=str(state_summary or '(no state evidence)')[:400],
        )
        verdict_dict = self._llm_call(prompt)
        _latency_ms = (time.time() - _t_start) * 1000

        if verdict_dict.get('_fallback'):
            with self._lock:
                self._stats['llm_fail_count'] += 1
            result = self._make_result('pass', latency_ms=_latency_ms,
                                         fallback=True,
                                         reason=verdict_dict.get('_error', 'llm_fail'))
        else:
            result = {
                'verdict': verdict_dict.get('verdict', 'pass'),
                'issues': verdict_dict.get('issues', []),
                'edited_reply': verdict_dict.get('edited_reply', ''),
                'scrap_reason': verdict_dict.get('scrap_reason', ''),
                'latency_ms': _latency_ms,
                '_cached': False,
                '_fallback': False,
            }
            with self._lock:
                self._stats['total_checks'] += 1
                _v = result['verdict']
                if _v == 'pass':
                    self._stats['pass_count'] += 1
                elif _v == 'edit':
                    self._stats['edit_count'] += 1
                elif _v == 'scrap':
                    self._stats['scrap_count'] += 1

        # cache
        _cache_put(ckey, result)
        # stats persist (best effort)
        try:
            _record_stats(result, _latency_ms, sir_utterance, len(draft_reply))
        except Exception:
            pass

        return result

    def _llm_call(self, prompt: str) -> dict:
        """Call LLM, parse JSON verdict. Returns dict with verdict OR _fallback."""
        try:
            from jarvis_utils import safe_openrouter_call
        except Exception as e:
            return {'_fallback': True, '_error': f'import fail: {e}'}

        try:
            okey, _label = self.key_router.get_openrouter_key(caller='reply_preflight')
        except Exception as e:
            return {'_fallback': True, '_error': f'key err: {str(e)[:60]}'}

        try:
            # flash_lite for cheap + fast
            _model_map = {
                'flash_lite': 'google/gemini-2.5-flash-lite-preview-09-2025',
                'flash': 'google/gemini-2.5-flash-preview-09-2025',
            }
            _model = _model_map.get(self.config['model'], _model_map['flash_lite'])
            response_text = safe_openrouter_call(
                openrouter_key=okey,
                model=_model,
                prompt=prompt,
                max_tokens=400,
                temperature=0.1,
            )
        except Exception as e:
            return {'_fallback': True, '_error': f'LLM fail: {str(e)[:80]}'}

        try:
            txt = (response_text or '').strip()
            if txt.startswith('```'):
                lines = txt.split('\n')
                if len(lines) >= 3:
                    txt = '\n'.join(lines[1:-1])
            parsed = json.loads(txt)
            if not isinstance(parsed, dict):
                return {'_fallback': True, '_error': 'non-dict json'}
            # validate verdict
            v = parsed.get('verdict', 'pass')
            if v not in ('pass', 'edit', 'scrap'):
                v = 'pass'  # default
            parsed['verdict'] = v
            return parsed
        except Exception as e:
            return {'_fallback': True, '_error': f'parse fail: {str(e)[:60]}'}

    def _make_result(self, verdict: str, latency_ms: float = 0,
                     fallback: bool = False, reason: str = '') -> dict:
        return {
            'verdict': verdict,
            'issues': [reason] if reason else [],
            'edited_reply': '',
            'scrap_reason': reason if verdict == 'scrap' else '',
            'latency_ms': latency_ms,
            '_cached': False,
            '_fallback': fallback,
        }

    def stats(self) -> dict:
        with self._lock:
            return dict(self._stats)


# ============================================================
# Singleton
# ============================================================

_DEFAULT_PREFLIGHT: Optional[ReplyPreFlight] = None
_INIT_LOCK = threading.Lock()


def get_default_preflight() -> Optional[ReplyPreFlight]:
    """Returns global singleton (None if not registered)."""
    return _DEFAULT_PREFLIGHT


def register_preflight(preflight: ReplyPreFlight) -> None:
    global _DEFAULT_PREFLIGHT
    with _INIT_LOCK:
        _DEFAULT_PREFLIGHT = preflight


def reset_default_preflight_for_test() -> None:
    global _DEFAULT_PREFLIGHT
    with _INIT_LOCK:
        _DEFAULT_PREFLIGHT = None
        _VERDICT_CACHE.clear()


def is_enabled() -> bool:
    """env JARVIS_PREFLIGHT 控制. Default ON (P5-fixD / 2026-05-21 10:00).

    Sir 09:05/06/12 真测痛点: 23:59 / "medical examination overlooked" / Windsurf
    trial quota — 都是主脑混合真数据涌现 hallucination, [PENDING COMMITMENTS] block
    主脑无视. P5-fixD: PreFlight 默认开, 让主脑 reply 后 LLM 自审, 不通过 → publish
    SWM verdict, 主脑下轮 [PREFLIGHT FEEDBACK] 看自纠.

    Sir 关掉: 设 JARVIS_PREFLIGHT=0 (其他任何值都视为 ON, 跟 fix3 默认开同 pattern).
    代价: 每轮多 ~500ms LLM (async post-stream, 不阻 TTFT).
    """
    val = os.environ.get('JARVIS_PREFLIGHT', '1').strip()
    return val != '0'
