# -*- coding: utf-8 -*-
"""[β.5.43-fix3-㋭ / 2026-05-20 18:52] SirRequestReflector — L7 daemon

Sir 18:49 痛点: Sir 说 "下次卡住主动提醒我", Jarvis 答应了 — 但实际没机制
兑现 (PromiseLog 抓错文本, Gatekeeper 只存被动 memory, ConcernsLedger 没新 concern).

设计 (同 StruggleReflector / ScreenTeaseReflector L7 模式):
  1. 60s tick (短 interval 因 Sir 请求要快 propose, 不像 vocab 24h)
  2. 看 STM 最近 30 条 user_voice + jarvis_voice 对话
  3. LLM judge "Sir 是否要求 Jarvis long-watch / 主动 nudge 某 X"
  4. 命中 → propose 一条 concern 进 review_queue (state=review)
  5. Sir dashboard 一键激活 → ProactiveCare 真触发 nudge

config:
  primary_model: 'google/gemini-2.5-flash-lite'
  min_interval_s: 60          # 1min check 一次 (新对话来)
  min_stm_for_run: 6          # 至少 3 轮对话
  max_propose_per_run: 1      # 一次最多 propose 1 条
  stm_lookback: 30            # 看最近 30 条 STM (~10-15 轮)
  dedup_window_h: 24          # 24h 内同 topic 不重复 propose

doc: AGENTS.md 准则 6 (持久化 + CLI + L7 reflector)
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


SIR_REQUEST_REFLECTOR_CONFIG = {
    'primary_model': 'google/gemini-2.5-flash-lite',
    'fallback_model': 'google/gemini-3.1-pro-preview',
    'temperature': 0.2,
    'max_output_tokens': 500,
    'timeout_s': 15.0,
    'tick_seconds': 60.0,
    'min_interval_s': 60,           # 1min 1 跑 (短, Sir 请求要快)
    'min_stm_for_run': 6,
    'max_propose_per_run': 1,
    'stm_lookback': 30,
    'dedup_window_s': 86400,        # 24h 内同 topic 不重复
}


SIR_REQUEST_REFLECTOR_PROMPT = """[ROLE]
You are Jarvis's request-watcher reflector. Look at recent STM (Sir + Jarvis utterances) and decide if Sir has explicitly asked Jarvis to LONG-WATCH something and PROACTIVELY notify when a condition is met.

[CRITERIA — All Must Hold]
1. Sir's utterance contains a watch/proactive-notify request (e.g. "下次X的时候提醒我", "如果Y发生告诉我", "remind me when Z").
2. The request is LONG-LIVED, not one-shot ("提醒我 5min 后" = one-shot, 走 Time Hook, NOT here).
3. Jarvis acknowledged (no "无法做到" pushback in following turn).
4. Subject is CONCRETE and DETECTABLE by Jarvis sensors (windsurf 进程 / coding 时长 / 喝水 / 起床 / 睡觉 / 屏幕内容 / 鼠标键盘 / ambient 声音). NOT 抽象/不可测 (e.g. "提醒我开心").

[EXISTING CONCERNS — DO NOT DUPLICATE TOPIC]
{existing_concerns_str}

[RECENT STM (oldest first, {stm_count} entries)]
{stm_str}

[OUTPUT — JSON only, no markdown]
{{"proposed_concerns": [
    {{"id": "<snake_case_id_e.g.watch_windsurf_responsive>",
      "what_i_watch": "<one-line CONCRETE thing to watch>",
      "why_i_care": "<Sir's stated reason or inferred>",
      "trigger_evidence": "<what sensor signal would trigger this>",
      "source_utterance": "<the Sir utterance that triggered this>",
      "rationale": "<one sentence>"}}
]}}

If NO Sir long-watch request found, output: {{"proposed_concerns": []}}

CRITICAL: Output AT MOST 1 concern per run. Empty list if nothing clearly matches all 4 criteria.
"""


class SirRequestReflector(threading.Thread):
    """L7 daemon: 60s tick, LLM propose 新 watch-concern 进 review_queue.

    用法:
        reflector = SirRequestReflector(
            key_router=worker.key_router,
            stm_provider=lambda: nerve.get_recent_stm(),
            concerns_ledger=nerve.concerns_ledger,
        )
        reflector.start()
    """

    def __init__(
        self,
        key_router=None,
        stm_provider=None,
        concerns_ledger=None,
        config: Optional[Dict] = None,
    ):
        super().__init__(daemon=True, name='SirRequestReflector')
        self.key_router = key_router
        self.stm_provider = stm_provider
        self.concerns_ledger = concerns_ledger
        self.config = dict(SIR_REQUEST_REFLECTOR_CONFIG)
        if config:
            self.config.update(config)
        self._stop = threading.Event()
        self._last_run_ts = 0.0
        # 防 60s 内同一 stm 重复跑 LLM
        self._last_stm_fingerprint = ''
        # dedup: topic_keyword → last_propose_ts (24h 内不重复)
        self._recent_topic_proposed: Dict[str, float] = {}
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

    def _get_recent_stm(self) -> List[Dict]:
        if self.stm_provider is None:
            return []
        try:
            stm = self.stm_provider() or []
        except Exception:
            return []
        # 取最近 N 条 user_voice + jarvis_voice
        filtered = []
        for e in stm[-self.config['stm_lookback']:]:
            src = e.get('source', '') or e.get('src', '')
            if src in ('user_voice', 'jarvis_voice', 'user', 'jarvis'):
                filtered.append(e)
        return filtered

    def _format_stm_for_prompt(self, stm_list: List[Dict]) -> str:
        if not stm_list:
            return '(no recent STM)'
        lines = []
        for e in stm_list:
            src = e.get('source', '') or e.get('src', '')
            speaker = 'Sir' if src in ('user_voice', 'user') else 'Jarvis'
            text = (e.get('text', '') or e.get('content', '') or '').strip()
            if text:
                lines.append(f"  [{speaker}] {text[:200]}")
        return '\n'.join(lines) if lines else '(empty)'

    def _build_existing_concerns_str(self) -> str:
        if self.concerns_ledger is None:
            return '(no ledger)'
        try:
            active = self.concerns_ledger.list_active()
            review = self.concerns_ledger.list_review()
            lines = []
            for c in (active + review)[:20]:
                lines.append(f"  - {c.id}: {(c.what_i_watch or '')[:100]}")
            return '\n'.join(lines) if lines else '(none)'
        except Exception:
            return '(failed to load)'

    def _stm_fingerprint(self, stm_list: List[Dict]) -> str:
        """简易 fingerprint, 60s 内 STM 没变就不重跑 LLM."""
        if not stm_list:
            return ''
        last = stm_list[-1]
        text = (last.get('text', '') or last.get('content', '') or '')[:80]
        return f"{len(stm_list)}::{text}"

    def _topic_already_proposed_recently(self, concern_id: str) -> bool:
        """24h dedup: 同 concern_id 24h 内 propose 过就 skip."""
        now = time.time()
        # 清过期
        cutoff = now - self.config['dedup_window_s']
        self._recent_topic_proposed = {
            k: v for k, v in self._recent_topic_proposed.items() if v > cutoff
        }
        return concern_id in self._recent_topic_proposed

    def _reflect_once(self, force: bool = False) -> Dict:
        result = {'ok': False, 'reason': '', 'proposed_n': 0, 'stm_count': 0}

        if not force:
            now = time.time()
            since = now - self._last_run_ts
            if since < self.config['min_interval_s']:
                result['reason'] = f'too soon: {since:.0f}s'
                return result

        stm = self._get_recent_stm()
        result['stm_count'] = len(stm)

        if not force and len(stm) < self.config['min_stm_for_run']:
            result['reason'] = f'not enough STM: {len(stm)}'
            return result

        # fingerprint dedup
        fp = self._stm_fingerprint(stm)
        if not force and fp == self._last_stm_fingerprint:
            result['reason'] = 'stm unchanged since last run'
            return result

        global safe_openrouter_call
        if safe_openrouter_call is None:
            try:
                from jarvis_utils import safe_openrouter_call as _sor
                safe_openrouter_call = _sor
            except Exception as e:
                result['reason'] = f'import fail: {e}'
                return result

        if self.key_router is None:
            result['reason'] = 'no key_router'
            self._stats['last_error'] = result['reason']
            return result

        try:
            okey, _label = self.key_router.get_openrouter_key(caller='sir_request_reflector')
        except Exception as e:
            result['reason'] = f'key error: {str(e)[:120]}'
            self._stats['last_error'] = result['reason']
            return result

        existing_str = self._build_existing_concerns_str()
        stm_str = self._format_stm_for_prompt(stm)
        prompt = SIR_REQUEST_REFLECTOR_PROMPT.format(
            existing_concerns_str=existing_str,
            stm_str=stm_str,
            stm_count=len(stm),
        )

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
            except Exception as e_fb:
                result['reason'] = f'LLM fail: p={str(e_primary)[:50]} f={str(e_fb)[:50]}'
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
            proposed = parsed.get('proposed_concerns', [])
            if not isinstance(proposed, list):
                proposed = []
            proposed = proposed[: self.config['max_propose_per_run']]
        except Exception as e:
            result['reason'] = f'parse fail: {str(e)[:80]} resp={response_text[:100]}'
            self._stats['last_error'] = result['reason']
            self._last_run_ts = time.time()
            self._stats['runs_total'] += 1
            return result

        added_n = 0
        if proposed and self.concerns_ledger is not None:
            try:
                from jarvis_concerns import Concern
                for p in proposed:
                    pid = (p.get('id') or '').strip()
                    if not pid or len(pid) > 60:
                        continue
                    if self._topic_already_proposed_recently(pid):
                        continue
                    what = (p.get('what_i_watch') or '').strip()[:200]
                    why = (p.get('why_i_care') or '').strip()[:200]
                    if not what or not why:
                        continue
                    trig = (p.get('trigger_evidence') or '').strip()[:200]
                    src_utt = (p.get('source_utterance') or '').strip()[:300]
                    rationale = (p.get('rationale') or '').strip()[:200]
                    c = Concern(
                        id=pid,
                        what_i_watch=what,
                        why_i_care=why,
                        severity=0.5,
                        state='review',
                        notes_for_self=(
                            f'[β.5.43-fix3-㋭ SirRequestReflector] '
                            f'src: "{src_utt[:100]}" | trigger: {trig[:80]}'
                        )[:400],
                    )
                    ok = self.concerns_ledger.propose(c)
                    if ok:
                        added_n += 1
                        self._recent_topic_proposed[pid] = time.time()
                if added_n > 0:
                    try:
                        self.concerns_ledger.write_review_queue()
                        self.concerns_ledger.persist()
                    except Exception:
                        pass
                    # SWM publish 通知主脑有新 watch request
                    try:
                        from jarvis_utils import get_event_bus
                        _bus = get_event_bus()
                        if _bus is not None:
                            _bus.publish(
                                etype='sir_watch_request_proposed',
                                description=f'Sir 请求 watch {added_n} 项, dashboard 一键激活',
                                source='SirRequestReflector',
                                salience=0.7,
                                metadata={'proposed_ids': [p.get('id') for p in proposed[:added_n]]},
                                ttl=3600.0,
                            )
                    except Exception:
                        pass
            except Exception as e:
                result['reason'] = f'propose fail: {str(e)[:80]}'
                self._stats['last_error'] = result['reason']

        self._last_run_ts = time.time()
        self._last_stm_fingerprint = fp
        self._stats['runs_total'] += 1
        self._stats['last_run_ts'] = self._last_run_ts
        if added_n > 0:
            self._stats['runs_proposed'] += 1
            self._stats['proposals_total'] += added_n

        result.update({
            'ok': True,
            'proposed_n': added_n,
            'reason': f'proposed {added_n} new watch-concerns from {len(stm)} STM',
        })

        if added_n > 0:
            try:
                from jarvis_utils import bg_log
                bg_log(f'🪞 [SirRequestReflector] propose {added_n} watch concerns (review queue)')
            except Exception:
                pass

        return result

    def run(self):
        try:
            from jarvis_utils import bg_log
            bg_log('[SirRequestReflector] L7 watch-request daemon ready (β.5.43-fix3)')
        except Exception:
            pass
        self._stop.wait(45.0)  # 启动后 45s 才开始 (等 STM 积累)
        while not self._stop.is_set():
            try:
                self._reflect_once(force=False)
            except Exception as e:
                self._stats['last_error'] = f'reflect_once threw: {str(e)[:80]}'
            self._stop.wait(self.config['tick_seconds'])
