# -*- coding: utf-8 -*-
"""[β.5.35-D / 2026-05-20] StruggleReflector — L7 vocab propose daemon for sir_struggle_vocab

Sir 2026-05-20 10:46 实测 BUG 2: offer_help 触发源不对.
β.5.35-C 已修硬编码 → struggle vocab 持久化 + CLI + worker detector.
本 daemon (β.5.35-D) 补 L7 reflector:

设计 (同 jarvis_screen_tease_reflector.py 模式):
  1. 24h 1 跑 LLM, 看 STM 最近 100 条 [src=user_voice] entries
  2. propose 新 抱怨/困难 phrase pattern 进 review_queue
  3. Sir CLI struggle_vocab_dump.py --review-list / --activate / --reject 拍板
  4. 失败/超时/无 key 静默, 不阻塞主路径

config:
  primary_model: 'google/gemini-2.5-flash-lite'
  min_interval_s: 86400 (24h)
  min_stm_for_run: 30 ([src=user_voice] 数)
  max_propose_per_run: 3

doc: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

try:
    from jarvis_utils import safe_openrouter_call  # noqa: F401
except Exception:
    safe_openrouter_call = None  # type: ignore


STRUGGLE_REFLECTOR_CONFIG = {
    'primary_model': 'google/gemini-2.5-flash-lite',
    'fallback_model': 'google/gemini-3.1-pro-preview',
    'temperature': 0.2,
    'max_output_tokens': 600,
    'timeout_s': 15.0,
    'tick_seconds': 60.0,
    'min_interval_s': 86400,            # 24h 1 跑
    'min_stm_for_run': 30,              # < 30 user_voice 条不跑
    'max_propose_per_run': 3,
    'stm_lookback': 100,                # 看最近 100 条 user_voice STM
}


STRUGGLE_REFLECTOR_PROMPT = """[ROLE]
You are Jarvis's introspective reflector. You look at Sir's recent 100 voice utterances and decide if there's a NEW phrase pattern Jarvis should learn to recognize as "Sir struggling / asking for help".

[CRITICAL CONSTRAINTS]
1. APPEND ONLY — do NOT propose phrases that already exist (see [EXISTING PHRASES] below).
2. AT MOST 3 new phrase patterns per run.
3. Each proposed phrase MUST have at least 2 STM utterances as evidence (not 1-shot).
4. Severity rules:
   - high: explicit "stuck/blocked/can't do" / strong frustration / expletive
   - medium: "怎么办/how to" / mild confusion / asking for help
   - low: ambiguous noise (skip unless clearly Sir-asking-for-help context)
5. NEVER propose phrases that are normal casual chat (e.g. "what's the weather") — must be STRUGGLE-related.

[EXISTING PHRASES — DO NOT DUPLICATE]
{existing_phrases_str}

[RECENT 100 USER_VOICE STM (oldest first)]
{stm_str}

[OUTPUT]
Output ONLY a JSON object on a single line:
{{"proposed_phrases": [
    {{"id": "<snake_case_id_under_30_chars>",
      "patterns": ["pattern1", "pattern2"],
      "severity": "low|medium|high",
      "evidence_utterances": ["..."],
      "rationale": "<one sentence>"}}
]}}

Empty if nothing: {{"proposed_phrases": []}}

ALL string values MUST be valid JSON. NO markdown, NO explanations.
"""


class StruggleReflector(threading.Thread):
    """L7 daemon: 24h 1 跑 LLM propose 新 struggle phrase 进 review_queue.

    用法:
        reflector = StruggleReflector(
            key_router=worker.key_router,
            stm_provider=lambda: nerve.get_recent_stm(),
            vocab_path='memory_pool/sir_struggle_vocab.json',
        )
        reflector.start()

    停止: reflector.stop()
    强制跑: reflector.force_run_now() -> dict
    """

    def __init__(
        self,
        key_router=None,
        stm_provider=None,
        vocab_path: Optional[str] = None,
        config: Optional[Dict] = None,
    ):
        super().__init__(daemon=True, name='StruggleReflector')
        self.key_router = key_router
        self.stm_provider = stm_provider  # callable() → list of STM dicts
        self.config = dict(STRUGGLE_REFLECTOR_CONFIG)
        if config:
            self.config.update(config)
        self.vocab_path = vocab_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'memory_pool', 'sir_struggle_vocab.json',
        )
        self._stop = threading.Event()
        self._last_run_ts = 0.0
        self._stats = {
            'runs_total': 0,
            'runs_proposed': 0,
            'proposals_total': 0,
            'last_run_ts': 0.0,
            'last_error': '',
        }

    def stop(self):
        self._stop.set()

    def force_run_now(self) -> Dict:
        try:
            return self._reflect_once(force=True)
        except Exception as e:
            return {'error': str(e)[:200]}

    def _load_existing_patterns(self) -> List[str]:
        """读 vocab 已有所有 patterns (lower) 用于 dedup."""
        try:
            if not os.path.exists(self.vocab_path):
                return []
            with open(self.vocab_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            all_pats = []
            for p in data.get('phrases', []):
                if p.get('state', 'active') == 'active':
                    all_pats.extend([pat.lower() for pat in p.get('patterns', [])])
            for p in data.get('review_queue', []):
                all_pats.extend([pat.lower() for pat in p.get('patterns', [])])
            return all_pats
        except Exception:
            return []

    def _build_existing_phrases_str(self) -> str:
        try:
            if not os.path.exists(self.vocab_path):
                return '(none yet)'
            with open(self.vocab_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            lines = []
            for p in data.get('phrases', []):
                if p.get('state', 'active') == 'active':
                    pats = ', '.join(p.get('patterns', [])[:6])
                    sev = p.get('severity', '?')
                    lines.append(f"  - {p.get('id')} [{sev}]: [{pats}]")
            return '\n'.join(lines) if lines else '(none yet)'
        except Exception:
            return '(failed to load)'

    def _get_user_voice_stm(self) -> List[Dict]:
        """从 stm_provider 拉最近 N 条 [src=user_voice] STM."""
        if self.stm_provider is None:
            return []
        try:
            stm = self.stm_provider() or []
        except Exception:
            return []
        # 过滤 user_voice (类 WeeklyReflector 风格)
        filtered = []
        for e in stm[-self.config['stm_lookback']:]:
            src = e.get('source', '') or e.get('src', '')
            if src == 'user_voice':
                filtered.append(e)
        return filtered

    def _format_stm_for_prompt(self, stm_list: List[Dict]) -> str:
        if not stm_list:
            return '(no user_voice STM)'
        lines = []
        for e in stm_list:
            text = (e.get('text', '') or e.get('content', '') or '').strip()
            if text:
                lines.append(f"  - {text[:160]}")
        return '\n'.join(lines) if lines else '(empty)'

    def _reflect_once(self, force: bool = False) -> Dict:
        result = {
            'ok': False,
            'reason': '',
            'proposed_n': 0,
            'stm_count': 0,
        }

        if not force:
            now = time.time()
            since = now - self._last_run_ts
            if since < self.config['min_interval_s']:
                result['reason'] = f'too soon: {since:.0f}s'
                return result

        stm = self._get_user_voice_stm()
        result['stm_count'] = len(stm)

        if not force and len(stm) < self.config['min_stm_for_run']:
            result['reason'] = f'not enough user_voice STM: {len(stm)} < {self.config["min_stm_for_run"]}'
            return result

        existing_str = self._build_existing_phrases_str()
        stm_str = self._format_stm_for_prompt(stm)

        prompt = STRUGGLE_REFLECTOR_PROMPT.format(
            existing_phrases_str=existing_str,
            stm_str=stm_str,
        )

        global safe_openrouter_call
        if safe_openrouter_call is None:
            try:
                from jarvis_utils import safe_openrouter_call as _sor
                safe_openrouter_call = _sor
            except Exception as e:
                result['reason'] = f'import safe_openrouter_call failed: {e}'
                return result

        if self.key_router is None:
            result['reason'] = 'no key_router'
            self._stats['last_error'] = result['reason']
            return result
        try:
            okey, _label = self.key_router.get_openrouter_key(caller='struggle_reflector')
        except Exception as e:
            result['reason'] = f'key_router error: {str(e)[:120]}'
            self._stats['last_error'] = result['reason']
            return result

        response_text = ''
        try:
            response_text = safe_openrouter_call(
                openrouter_key=okey,
                model=self.config['primary_model'],
                prompt=prompt,
                max_tokens=self.config['max_output_tokens'],
                temperature=self.config['temperature'],
                timeout_s=self.config['timeout_s'],
            )
        except Exception as e_primary:
            try:
                response_text = safe_openrouter_call(
                    openrouter_key=okey,
                    model=self.config['fallback_model'],
                    prompt=prompt,
                    max_tokens=self.config['max_output_tokens'],
                    temperature=self.config['temperature'],
                    timeout_s=self.config['timeout_s'],
                )
            except Exception as e_fallback:
                result['reason'] = (
                    f'LLM both failed: primary={str(e_primary)[:60]} '
                    f'fallback={str(e_fallback)[:60]}'
                )
                self._stats['last_error'] = result['reason']
                self._last_run_ts = time.time()
                self._stats['runs_total'] += 1
                return result

        try:
            txt = response_text.strip()
            if txt.startswith('```'):
                lines = txt.split('\n')
                if len(lines) >= 3 and lines[-1].strip().startswith('```'):
                    txt = '\n'.join(lines[1:-1])
            parsed = json.loads(txt)
            proposed = parsed.get('proposed_phrases', [])
            if not isinstance(proposed, list):
                proposed = []
            proposed = proposed[: self.config['max_propose_per_run']]
        except Exception as e:
            result['reason'] = f'parse fail: {str(e)[:80]} resp={response_text[:120]}'
            self._stats['last_error'] = result['reason']
            self._last_run_ts = time.time()
            self._stats['runs_total'] += 1
            return result

        added_n = 0
        if proposed:
            try:
                with open(self.vocab_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                existing_review_ids = {p.get('id') for p in data.get('review_queue', [])}
                existing_active_ids = {p.get('id') for p in data.get('phrases', [])}
                for p in proposed:
                    pid = (p.get('id') or '').strip()
                    if not pid or pid in existing_review_ids or pid in existing_active_ids:
                        continue
                    pats = p.get('patterns', [])
                    if not isinstance(pats, list) or not pats:
                        continue
                    sev = (p.get('severity', 'medium') or 'medium').lower()
                    if sev not in ('low', 'medium', 'high'):
                        sev = 'medium'
                    item = {
                        'id': pid,
                        'state': 'review',
                        'patterns': [str(pat).strip() for pat in pats if str(pat).strip()],
                        'severity': sev,
                        'rationale': str(p.get('rationale', '')),
                        'evidence_utterances': p.get('evidence_utterances', []),
                        'source': 'L7 reflector',
                        'proposed_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    }
                    data.setdefault('review_queue', []).append(item)
                    added_n += 1
                if added_n > 0:
                    data.setdefault('_meta', {})['last_l7_run_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
                    tmp = self.vocab_path + '.tmp'
                    with open(tmp, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                        f.write('\n')
                    os.replace(tmp, self.vocab_path)
            except Exception as e:
                result['reason'] = f'write vocab fail: {str(e)[:80]}'
                self._stats['last_error'] = result['reason']
                self._last_run_ts = time.time()
                self._stats['runs_total'] += 1
                return result

        self._last_run_ts = time.time()
        self._stats['runs_total'] += 1
        self._stats['last_run_ts'] = self._last_run_ts
        if added_n > 0:
            self._stats['runs_proposed'] += 1
            self._stats['proposals_total'] += added_n
        result.update({
            'ok': True,
            'proposed_n': added_n,
            'reason': f'proposed {added_n} new phrases from {len(stm)} user_voice STM',
        })
        try:
            from jarvis_utils import bg_log
            bg_log(
                f"🪞 [StruggleReflector] {result['reason']}"
            )
        except Exception:
            pass
        return result

    def run(self):
        try:
            from jarvis_utils import bg_log
            bg_log('[StruggleReflector] L7 vocab daemon ready (β.5.35-D)')
        except Exception:
            pass
        self._stop.wait(30.0)
        while not self._stop.is_set():
            try:
                self._reflect_once(force=False)
            except Exception as e:
                self._stats['last_error'] = f'reflect_once threw: {str(e)[:80]}'
            self._stop.wait(self.config['tick_seconds'])
