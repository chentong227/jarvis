# -*- coding: utf-8 -*-
"""[β.5.40-B1 / 2026-05-20] InsideJokeReflector — L7 daemon propose inside_jokes

Sir 方向 B.1 (~2h):
  - 每日 03:30 扫近 7 天 STM
  - LLM 提取 Sir 重复用的口头梗/称呼/自创梗 (≥2 evidence + confidence ≥ 0.8)
  - propose 到 relational_state.inside_jokes review_queue (Sir 拍板 → active)
  - 主脑 prompt 看 active jokes 适时引用
  - Sir "他真懂我" 体感

设计 (沿用 StruggleReflector 模式):
  - 24h 1 跑, min STM 50, max 3 propose/run
  - cheap LLM (gemini-2.5-flash-lite)
  - 失败/超时/无 key 静默不阻塞
  - dedup: relational_state 已存 phrase 不重复

接 jarvis_relational.RelationalStateStore.propose_inside_joke (β.2.4.4 路径).

doc 参照 docs/JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md (Sir 方向 B.1).
test: tests/_test_p0_plus_20_beta540_inside_joke_reflector.py
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

try:
    from jarvis_utils import safe_openrouter_call  # noqa: F401
except Exception:
    safe_openrouter_call = None  # type: ignore


INSIDE_JOKE_REFLECTOR_CONFIG = {
    'primary_model': 'google/gemini-2.5-flash-lite',
    'fallback_model': 'google/gemini-3.1-pro-preview',
    'temperature': 0.2,
    'max_output_tokens': 800,
    'timeout_s': 20.0,
    'tick_seconds': 60.0,
    'min_interval_s': 86400,            # 24h 1 跑
    'min_stm_for_run': 50,              # < 50 entries 不跑 (Sir 精准要求, 数据足才提)
    'max_propose_per_run': 3,
    'stm_lookback': 300,                # 看最近 300 条 STM (覆盖 ~ 7天)
    'min_confidence': 0.8,              # ≥ 0.8 才 propose (Sir 精准要求)
    'preferred_run_hour_local': 3,      # 03:00 后跑 (idle 期不影响 Sir 用 LLM 配额)
}


INSIDE_JOKE_REFLECTOR_PROMPT = """[ROLE]
You are Jarvis's introspective reflector — you look at Sir's recent 300 STM entries (~ 7 days) and find PATTERNS that should become "inside jokes between us" (我们的共同梗).

[CRITICAL CONSTRAINTS]
1. APPEND ONLY — do NOT propose phrases that already exist (see [EXISTING INSIDE JOKES] below).
2. AT MOST 3 new inside jokes per run.
3. Each proposed joke MUST have AT LEAST 2 separate evidence utterances (different turns, not single repeat).
4. confidence MUST be ≥ 0.8 (Sir 精准要求 — 不确定的不要提).
5. tone valid values: wry / self-deprecating / playful / mock-formal / warm / sarcastic
6. NEVER propose:
   - Standard greetings / casual chitchat (我去/嗯/好的) — these are not jokes
   - Negative emotion expressions (这傻逼系统/烦死了) — these are stress, not bonding humor
   - Anything Sir said only once (no repeat = not joke)
7. PREFER:
   - 自创称呼 (Sir 给自己/朋友/Jarvis 起的特殊称呼)
   - 重复的 punchline / set-up (Sir 反复用的笑话模板)
   - Sir 反复用的自嘲表达 (e.g. "码农命" / "牛马打工人")
   - In-context 的小默契 (e.g. Sir 一说某话题就接某梗)

[EXISTING INSIDE JOKES — DO NOT DUPLICATE]
{existing_jokes_str}

[RECENT STM (oldest first, ~7 days)]
{stm_str}

[OUTPUT]
Output ONLY a JSON object on a single line:
{{"proposed_jokes": [
    {{"id": "<snake_case_id_under_30_chars>",
      "phrase": "<the joke phrase / call, ≤ 80 chars>",
      "birth_context": "<one sentence describing when Sir typically uses it>",
      "tone": "wry|playful|self-deprecating|mock-formal|warm|sarcastic",
      "evidence_utterances": ["...", "..."],
      "confidence": 0.85,
      "rationale": "<one sentence>"}}
]}}

Empty if nothing: {{"proposed_jokes": []}}

ALL string values MUST be valid JSON. NO markdown, NO explanations.
"""


class InsideJokeReflector(threading.Thread):
    """L7 daemon: 每日 03:30 LLM 提取 inside_jokes propose 到 review queue.
    
    用法:
        reflector = InsideJokeReflector(
            key_router=worker.key_router,
            stm_provider=lambda: nerve.get_recent_stm(),
            relational_store=nerve.relational_state,
        )
        reflector.start()
    
    停止: reflector.stop()
    强制跑: reflector.force_run_now() -> dict
    """

    def __init__(
        self,
        key_router=None,
        stm_provider=None,
        relational_store=None,
        config: Optional[Dict] = None,
    ):
        super().__init__(daemon=True, name='InsideJokeReflector')
        self.key_router = key_router
        self.stm_provider = stm_provider
        self.relational_store = relational_store
        self.config = dict(INSIDE_JOKE_REFLECTOR_CONFIG)
        if config:
            self.config.update(config)
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
            return {'error': str(e)[:200], 'ok': False}

    def _build_existing_jokes_str(self) -> str:
        """Dump 当前 relational_state 已有 jokes (active + review + archived)."""
        if self.relational_store is None:
            return '(none yet)'
        try:
            lines = []
            for jid, j in (self.relational_store.inside_jokes or {}).items():
                phrase = getattr(j, 'phrase', '')[:80] if not isinstance(j, dict) else str(j.get('phrase', ''))[:80]
                state = getattr(j, 'state', 'active') if not isinstance(j, dict) else j.get('state', 'active')
                lines.append(f"  - [{state}] {phrase!r}")
            return '\n'.join(lines) if lines else '(none yet)'
        except Exception:
            return '(failed to load)'

    def _get_recent_stm(self) -> List[Dict]:
        if self.stm_provider is None:
            return []
        try:
            stm = self.stm_provider() or []
        except Exception:
            return []
        # 取最近 N (Sir + Jarvis 两边都看 — 笑点是互动产物)
        return stm[-self.config['stm_lookback']:]

    def _format_stm_for_prompt(self, stm_list: List[Dict]) -> str:
        if not stm_list:
            return '(no STM)'
        lines = []
        for e in stm_list:
            role = e.get('role', 'unknown')
            text = (e.get('text', '') or e.get('content', '') or '').strip()
            if text and len(text) > 2:
                lines.append(f"  [{role}] {text[:160]}")
        return '\n'.join(lines) if lines else '(empty)'

    def _should_run_by_hour(self, force: bool = False) -> bool:
        """检查当前 local hour 是否在 preferred 窗口 (03:00 后允许跑)."""
        if force:
            return True
        try:
            hour = time.localtime().tm_hour
            # 允许 03:00-05:59 跑 (idle 期)
            return 3 <= hour < 6
        except Exception:
            return True  # 出错宽松放行

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
                result['reason'] = f'too soon: {since:.0f}s < {self.config["min_interval_s"]}s'
                return result
            if not self._should_run_by_hour(force=False):
                result['reason'] = 'outside preferred hour (3-6 AM only)'
                return result

        if self.relational_store is None:
            result['reason'] = 'no relational_store'
            self._stats['last_error'] = result['reason']
            return result

        stm = self._get_recent_stm()
        result['stm_count'] = len(stm)

        if not force and len(stm) < self.config['min_stm_for_run']:
            result['reason'] = f'not enough STM: {len(stm)} < {self.config["min_stm_for_run"]}'
            return result

        existing_str = self._build_existing_jokes_str()
        stm_str = self._format_stm_for_prompt(stm)

        prompt = INSIDE_JOKE_REFLECTOR_PROMPT.format(
            existing_jokes_str=existing_str,
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
            okey, _label = self.key_router.get_openrouter_key(caller='inside_joke_reflector')
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
            txt = (response_text or '').strip()
            if txt.startswith('```'):
                lines = txt.split('\n')
                if len(lines) >= 3 and lines[-1].strip().startswith('```'):
                    txt = '\n'.join(lines[1:-1])
            parsed = json.loads(txt)
            proposed = parsed.get('proposed_jokes', [])
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
                from jarvis_relational import InsideJoke
            except Exception as e:
                result['reason'] = f'import InsideJoke failed: {e}'
                self._stats['last_error'] = result['reason']
                self._last_run_ts = time.time()
                self._stats['runs_total'] += 1
                return result

            for p in proposed:
                try:
                    conf = float(p.get('confidence', 0.0))
                except (TypeError, ValueError):
                    conf = 0.0
                if conf < self.config['min_confidence']:
                    continue
                evidence = p.get('evidence_utterances', [])
                if not isinstance(evidence, list) or len(evidence) < 2:
                    continue  # Sir 精准要求 ≥ 2 evidence
                phrase = str(p.get('phrase', '') or '').strip()[:80]
                if not phrase:
                    continue
                pid = (p.get('id') or '').strip() or f"joke_{uuid.uuid4().hex[:8]}"
                tone = (p.get('tone', '') or 'playful').strip().lower()
                if tone not in (
                    'wry', 'playful', 'self-deprecating', 'mock-formal', 'warm', 'sarcastic'
                ):
                    tone = 'playful'

                joke = InsideJoke(
                    id=pid,
                    phrase=phrase,
                    birth_context=str(p.get('birth_context', ''))[:200],
                    tone=tone,
                    source='auto_detected',
                    source_marker='P0+20-β.5.40-B1',
                )
                try:
                    added = self.relational_store.propose_inside_joke(joke)
                    if added:
                        added_n += 1
                except Exception as e:
                    try:
                        from jarvis_utils import bg_log
                        bg_log(f"⚠️ [InsideJokeReflector] propose 失败: {e}")
                    except Exception:
                        pass

            # 持久化 + 写 review queue
            if added_n > 0:
                try:
                    if hasattr(self.relational_store, 'persist'):
                        self.relational_store.persist()
                    if hasattr(self.relational_store, 'write_review_queue'):
                        self.relational_store.write_review_queue()
                except Exception:
                    pass

        self._last_run_ts = time.time()
        self._stats['runs_total'] += 1
        self._stats['last_run_ts'] = self._last_run_ts
        if added_n > 0:
            self._stats['runs_proposed'] += 1
            self._stats['proposals_total'] += added_n
        result.update({
            'ok': True,
            'proposed_n': added_n,
            'reason': f'proposed {added_n} new jokes from {len(stm)} STM',
        })
        try:
            from jarvis_utils import bg_log
            bg_log(f"😄 [InsideJokeReflector] {result['reason']}")
        except Exception:
            pass
        return result

    def get_stats(self) -> Dict:
        return dict(self._stats)

    def run(self):
        try:
            from jarvis_utils import bg_log
            bg_log('[InsideJokeReflector] L7 daemon ready (β.5.40-B1)')
        except Exception:
            pass
        self._stop.wait(60.0)  # 启动 60s 后才开始
        while not self._stop.is_set():
            try:
                self._reflect_once(force=False)
            except Exception as e:
                self._stats['last_error'] = f'reflect_once threw: {str(e)[:80]}'
            self._stop.wait(self.config['tick_seconds'])
