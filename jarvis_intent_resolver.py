# -*- coding: utf-8 -*-
"""[β.5.44-C / 2026-05-20 19:00] IntentResolver — Sir 18:55 重构核心

Sir 真理: "我说一句话, Jarvis 会做什么真的太乱了. 应该和主动模块一样, 把所有都变成
LLM 决策-模块提供数据-大部分都是 push only".

设计 (β.5.0 三维耦合在被动 module 落地):
  Phase 1: 6 个 input module (Gatekeeper/ConcernFB/MemCorrect/CommitWatch/SelfPromise/
           ProfileCard) 退化为 publish-only — 仅 publish 'sir_intent_*_candidate' SWM
  Phase 2: IntentResolver 集中 LLM judge — 看 SWM candidate, 决定调哪些 tool
  Phase 3: 真调 tool, publish 'tool_called' + 'intent_resolved' SWM
  Phase 4: 主脑 prompt 看 [INTENT RESOLVED] block, reply 基于真实 mutation result

调用入口:
  resolver = IntentResolver(key_router, central_nerve, tool_registry)
  resolver.resolve_turn(turn_id, sir_utterance)  # turn 末尾调

doc: docs/JARVIS_INTENT_RESOLVER_REFACTOR.md
"""
from __future__ import annotations

import json
import os
import time
import threading
from typing import Any, Dict, List, Optional

try:
    from jarvis_utils import safe_openrouter_call  # noqa: F401
except Exception:
    safe_openrouter_call = None  # type: ignore


INTENT_RESOLVER_CONFIG = {
    'primary_model': 'google/gemini-2.5-flash-lite',
    'fallback_model': 'google/gemini-3.1-pro-preview',
    'temperature': 0.1,                    # 工具调度要稳, 不要随机
    'max_output_tokens': 800,
    'timeout_s': 12.0,
    'candidate_lookback_s': 30,            # 看 turn 内 30s candidate
    'confidence_threshold': 0.45,          # 低于此 IntentResolver 不调 tool
    'max_tool_calls_per_turn': 5,          # 单 turn 最多 5 个 tool (防 LLM 发散)
}


INTENT_RESOLVER_PROMPT = """[ROLE]
You are Jarvis's Intent Resolver. Sir just said something. 6 input modules (Gatekeeper,
ConcernFeedback, MemoryCorrection, CommitmentWatcher, SelfPromiseDetector, ProfileCard)
each pre-judged Sir's utterance and published "intent candidates" to SWM. Your job:
look at all candidates + Sir's raw utterance + current state, decide which TOOLS to call.

[CRITICAL]
1. DO NOT call a tool unless evidence is strong (confidence >= 0.45 in candidate).
2. DO NOT make up new tool names — only use names in [AVAILABLE TOOLS].
3. PREFER fewer tool_calls — Sir cares about precision, not coverage.
4. If candidates conflict (e.g. ConcernFB says "Sir confirms 8 cups" + MemCorrect says
   "Sir corrected 9 to 8"), call the MOST PRECISE tool, not both.
5. If no tool needed (Sir is just chatting / asking a question), output empty plan.

[SIR'S UTTERANCE THIS TURN]
"{sir_utterance}"

[INTENT CANDIDATES FROM MODULES]
{candidates_str}

[AVAILABLE TOOLS — ONLY USE THESE NAMES]
{tools_str}

[CURRENT STATE EVIDENCE]
{state_str}

[OUTPUT — JSON ONLY, no markdown]
{{"tool_calls": [
    {{"name": "<exact_tool_name_from_AVAILABLE_TOOLS>",
      "args": {{"<arg_name>": <value>, ...}},
      "reason": "<one short sentence why>"}}
]}}

If no tool needed: {{"tool_calls": []}}

REMEMBER: Output AT MOST {max_calls} tool_calls. JSON only. No markdown. No explanations
outside the JSON.
"""


class IntentResolver:
    """集中 LLM judge — 看 SWM candidates 决定调 tool, publish intent_resolved.

    用法:
        resolver = IntentResolver(
            key_router=worker.key_router,
            central_nerve=nerve,
            tool_registry=TOOL_REGISTRY,
        )
        # turn 末尾调:
        resolver.resolve_turn(turn_id='turn_xxx', sir_utterance='记错了, 应该 8 杯')
    """

    def __init__(
        self,
        key_router=None,
        central_nerve=None,
        tool_registry: Optional[Dict[str, Any]] = None,
        config: Optional[Dict] = None,
    ):
        self.key_router = key_router
        self.nerve = central_nerve
        self.tools = dict(tool_registry or {})
        self.config = dict(INTENT_RESOLVER_CONFIG)
        if config:
            self.config.update(config)
        self._lock = threading.Lock()
        self._stats = {
            'turns_resolved': 0,
            'tools_called_total': 0,
            'tools_failed_total': 0,
            'last_resolve_ts': 0.0,
            'last_error': '',
        }

    def register_tool(self, name: str, fn: Any) -> None:
        """运行时注册 tool. fn 接 **args, 返 dict {'ok': bool, 'result': any, 'error': str}."""
        with self._lock:
            self.tools[name] = fn

    def stats(self) -> Dict:
        with self._lock:
            return dict(self._stats)

    # ---------------- evidence 收集 ----------------

    def _collect_candidates(self) -> List[Dict]:
        """从 SWM 拿 turn 内的 intent candidates."""
        if self.nerve is None:
            return []
        bus = getattr(self.nerve, 'event_bus', None)
        if bus is None:
            try:
                from jarvis_utils import get_event_bus
                bus = get_event_bus()
            except Exception:
                bus = None
        if bus is None:
            return []
        candidate_types = {
            'sir_intent_commit_candidate',
            'sir_intent_progress_candidate',
            'sir_intent_correction_candidate',
            'sir_intent_profile_update_candidate',
            'sir_intent_promise_candidate',
            'sir_intent_deadline_candidate',
        }
        try:
            events = bus.recent_events(
                within_seconds=self.config['candidate_lookback_s'],
                types=candidate_types,
            )
        except Exception:
            return []
        # filter confidence >= threshold
        filtered = []
        thresh = self.config['confidence_threshold']
        for ev in events:
            meta = ev.get('metadata') or {}
            conf = float(meta.get('confidence', 0.5))
            if conf >= thresh:
                filtered.append(ev)
        return filtered

    def _format_candidates_for_prompt(self, candidates: List[Dict]) -> str:
        if not candidates:
            return '(no intent candidates from any module)'
        lines = []
        for ev in candidates:
            meta = ev.get('metadata') or {}
            etype = ev.get('etype', '?')
            conf = meta.get('confidence', '?')
            src = ev.get('source', '?')
            desc = ev.get('description', '')[:200]
            judgement = meta.get('judgement', {})
            lines.append(
                f"  - etype={etype} (from {src}, conf={conf})\n"
                f"    desc: {desc}\n"
                f"    judgement: {json.dumps(judgement, ensure_ascii=False)[:300]}"
            )
        return '\n'.join(lines)

    def _format_tools_for_prompt(self) -> str:
        """🩹 [P1-Gap8 / 2026-05-20 23:35] Tool Schema Strict — 用 inspect 抽 signature,
        给 LLM 看每个 tool 的 args (名/类型/required/default), 不再凭 docstring 1 行猜.

        治 Sir 22:18-23:02 4 turn 反复 fail (e.g. concern_progress_update missing
        'current' — LLM 凭 docstring 'current=8/8' 误判 pass 'progress').
        """
        if not self.tools:
            return '(no tools registered)'
        import inspect as _ins
        lines = []
        for name, fn in self.tools.items():
            doc = (getattr(fn, '__doc__', '') or '').strip().split('\n')[0][:140]
            # 抽真实 signature
            try:
                # 走到 wrap 之下的真 function
                _real_fn = getattr(fn, '__wrapped__', None) or fn
                sig = _ins.signature(_real_fn)
                args_desc = []
                for pname, param in sig.parameters.items():
                    if pname in ('self', 'nerve', 'kw') or pname.startswith('**'):
                        continue
                    if param.kind == _ins.Parameter.VAR_KEYWORD:
                        continue
                    required = (param.default is _ins.Parameter.empty)
                    tname = ''
                    if param.annotation is not _ins.Parameter.empty:
                        tname = getattr(param.annotation, '__name__', '') or str(param.annotation)
                        tname = tname.replace('typing.', '').replace('Optional[', '').rstrip(']')[:20]
                    if required:
                        args_desc.append(f"{pname}<{tname or '?'}>*")
                    else:
                        _d = param.default
                        _d_str = ('=' + repr(_d))[:18] if _d not in (None, '', 0, 0.0) else ''
                        args_desc.append(f"{pname}<{tname or '?'}>{_d_str}")
                args_line = ', '.join(args_desc) if args_desc else '(no args)'
            except Exception:
                args_line = '(signature introspect failed)'
            lines.append(f"  - {name}:")
            lines.append(f"      doc: {doc}")
            lines.append(f"      args: {args_line}   ('*' = required)")
        lines.append('')
        lines.append('IMPORTANT: pass exact arg names from "args:" line above. '
                     'Required args (*) must be provided. Optional args have default.')
        return '\n'.join(lines)

    def _collect_state_evidence(self) -> str:
        """轻量当前 state evidence — 让 LLM 知道 hydration 当前 count 等."""
        if self.nerve is None:
            return '(no nerve)'
        lines = []
        # concerns ledger active concerns (with progress)
        try:
            ledger = getattr(self.nerve, 'concerns_ledger', None)
            if ledger is not None:
                today_iso = time.strftime('%Y-%m-%d', time.localtime())
                for c in ledger.list_active()[:8]:
                    dp = getattr(c, 'daily_progress', {}) or {}
                    if dp.get('iso_date') == today_iso:
                        lines.append(
                            f"  - concern {c.id}: progress {dp.get('current', '?')}"
                            f"/{dp.get('target', '?')} {dp.get('unit', '')}"
                        )
        except Exception:
            pass
        if not lines:
            return '(no relevant state)'
        return '\n'.join(lines)

    # ---------------- LLM call ----------------

    def _llm_judge(self, prompt: str) -> Dict:
        """调 LLM 拿 JSON tool_calls plan."""
        global safe_openrouter_call
        if safe_openrouter_call is None:
            try:
                from jarvis_utils import safe_openrouter_call as _sor
                safe_openrouter_call = _sor
            except Exception as e:
                return {'tool_calls': [], '_error': f'import fail: {e}'}

        if self.key_router is None:
            return {'tool_calls': [], '_error': 'no key_router'}
        try:
            okey, _label = self.key_router.get_openrouter_key(caller='intent_resolver')
        except Exception as e:
            return {'tool_calls': [], '_error': f'key error: {str(e)[:80]}'}

        response_text = ''
        try:
            response_text = safe_openrouter_call(
                openrouter_key=okey,
                model=self.config['primary_model'],
                prompt=prompt,
                max_tokens=self.config['max_output_tokens'],
                temperature=self.config['temperature'],
            )
        except Exception as e_primary:
            try:
                response_text = safe_openrouter_call(
                    openrouter_key=okey,
                    model=self.config['fallback_model'],
                    prompt=prompt,
                    max_tokens=self.config['max_output_tokens'],
                    temperature=self.config['temperature'],
                )
            except Exception as e_fb:
                return {
                    'tool_calls': [],
                    '_error': f'LLM both fail: {str(e_primary)[:50]} / {str(e_fb)[:50]}',
                }

        try:
            txt = response_text.strip()
            if txt.startswith('```'):
                lines = txt.split('\n')
                if len(lines) >= 3 and lines[-1].strip().startswith('```'):
                    txt = '\n'.join(lines[1:-1])
            parsed = json.loads(txt)
            if not isinstance(parsed, dict):
                return {'tool_calls': [], '_error': 'LLM returned non-dict'}
            tcs = parsed.get('tool_calls', [])
            if not isinstance(tcs, list):
                tcs = []
            return {'tool_calls': tcs[: self.config['max_tool_calls_per_turn']]}
        except Exception as e:
            return {
                'tool_calls': [],
                '_error': f'parse fail: {str(e)[:60]} resp={response_text[:120]}',
            }

    # ---------------- 主入口 ----------------

    def resolve_turn(self, turn_id: str, sir_utterance: str,
                     require_candidates: bool = False) -> Dict:
        """turn 末尾调. 收 SWM candidate + state evidence → LLM judge → 调 tool → publish intent_resolved.

        Args:
          turn_id: 本轮 ID
          sir_utterance: Sir 原话 (LLM 主要 evidence)
          require_candidates: True = 必须有 module candidate 才跑 (B 重构完后);
                              False (默认) = 无 candidate 也基于 utterance + state 直接 LLM judge.
                              过渡期 (B 没改完) 用 False; B 完成后改 True 节省 token.

        Returns: {'tool_calls': [...], 'executed': [...], 'reason': str}
        """
        result = {'tool_calls': [], 'executed': [], 'reason': ''}

        candidates = self._collect_candidates()
        if not candidates and require_candidates:
            result['reason'] = 'no candidates'
            return result

        # 短路: Sir utterance 太短 / 显然 chat-only → 不跑 LLM (省 token)
        utt = (sir_utterance or '').strip()
        if not utt or len(utt) < 4:
            result['reason'] = 'utterance too short'
            return result

        if not self.tools:
            result['reason'] = 'no tools registered'
            return result

        prompt = INTENT_RESOLVER_PROMPT.format(
            sir_utterance=str(sir_utterance or '')[:500],
            candidates_str=self._format_candidates_for_prompt(candidates),
            tools_str=self._format_tools_for_prompt(),
            state_str=self._collect_state_evidence(),
            max_calls=self.config['max_tool_calls_per_turn'],
        )

        plan = self._llm_judge(prompt)
        if plan.get('_error'):
            with self._lock:
                self._stats['last_error'] = plan['_error']
            result['reason'] = plan['_error']
            # 🩹 [β.5.43-F] LLM fail → ErrorBus 主动暴露
            try:
                from jarvis_error_bus import report_error, SEVERITY_MODERATE
                report_error(
                    module='intent_resolver',
                    kind='llm_judge_fail',
                    detail=plan['_error'][:200],
                    severity=SEVERITY_MODERATE,
                    recoverable=True,
                    suggested_action='check key_router quota or LLM model availability',
                )
            except Exception:
                pass
            return result

        tool_calls = plan.get('tool_calls', [])
        result['tool_calls'] = tool_calls

        # 执行 tools, publish tool_called
        bus = None
        if self.nerve is not None:
            bus = getattr(self.nerve, 'event_bus', None)
        if bus is None:
            try:
                from jarvis_utils import get_event_bus
                bus = get_event_bus()
            except Exception:
                bus = None

        for tc in tool_calls:
            name = (tc.get('name') or '').strip()
            args = tc.get('args') or {}
            reason = (tc.get('reason') or '')[:120]
            if not name or name not in self.tools:
                # tool 不存在 → 记 failed
                if bus is not None:
                    try:
                        bus.publish(
                            etype='tool_called',
                            description=f'tool {name} unknown (LLM 编了名字)',
                            source='IntentResolver',
                            salience=0.5,
                            metadata={
                                'turn_id': turn_id,
                                'name': name,
                                'args': args,
                                'ok': False,
                                'error': 'unknown_tool',
                                'reason': reason,
                            },
                        )
                    except Exception:
                        pass
                with self._lock:
                    self._stats['tools_failed_total'] += 1
                result['executed'].append({
                    'name': name, 'ok': False, 'error': 'unknown_tool',
                })
                continue

            fn = self.tools[name]
            ok = False
            err = ''
            tool_result = None
            try:
                tool_result = fn(**args)
                # tool fn 应返 {'ok': bool, 'result': any, 'error': str}
                if isinstance(tool_result, dict):
                    ok = bool(tool_result.get('ok', True))
                    err = str(tool_result.get('error', ''))[:200]
                else:
                    ok = True  # 没返 dict, 默认成功
            except Exception as e:
                ok = False
                err = str(e)[:200]

            # 🩹 [β.5.43-F / 2026-05-20] tool fail → ErrorBus 主动暴露
            if not ok:
                try:
                    from jarvis_error_bus import report_error, SEVERITY_MODERATE
                    report_error(
                        module='intent_resolver',
                        kind=f'tool_fail.{name}',
                        detail=f'{err} (args={json.dumps(args, ensure_ascii=False)[:100]})',
                        severity=SEVERITY_MODERATE,
                        recoverable=True,
                        suggested_action=f'check {name} preconditions or skip this turn',
                    )
                except Exception:
                    pass

            if bus is not None:
                try:
                    bus.publish(
                        etype='tool_called',
                        description=(
                            f'{"✓" if ok else "✗"} {name}'
                            f'({json.dumps(args, ensure_ascii=False)[:80]})'
                        ),
                        source='IntentResolver',
                        salience=0.85 if ok else 0.75,
                        metadata={
                            'turn_id': turn_id,
                            'name': name,
                            'args': args,
                            'ok': ok,
                            'error': err,
                            'reason': reason,
                            'result_summary': str(tool_result)[:200],
                        },
                    )
                except Exception:
                    pass

            with self._lock:
                if ok:
                    self._stats['tools_called_total'] += 1
                else:
                    self._stats['tools_failed_total'] += 1
            result['executed'].append({
                'name': name, 'ok': ok, 'error': err,
            })

        # publish intent_resolved (turn-level 报告, 主脑必看)
        if bus is not None:
            try:
                bus.publish(
                    etype='intent_resolved',
                    description=(
                        f"turn={turn_id[:20]}, "
                        f"calls={len(tool_calls)}, "
                        f"ok={sum(1 for e in result['executed'] if e.get('ok'))}/"
                        f"{len(result['executed'])}"
                    ),
                    source='IntentResolver',
                    salience=0.90,
                    metadata={
                        'turn_id': turn_id,
                        'sir_utterance_excerpt': str(sir_utterance or '')[:200],
                        'tool_calls': result['executed'],
                        'candidates_count': len(candidates),
                    },
                )
            except Exception:
                pass

        with self._lock:
            self._stats['turns_resolved'] += 1
            self._stats['last_resolve_ts'] = time.time()

        try:
            from jarvis_utils import bg_log
            ok_n = sum(1 for e in result['executed'] if e.get('ok'))
            bg_log(
                f"🧭 [IntentResolver] turn={turn_id[:20]} "
                f"candidates={len(candidates)} → "
                f"tools={ok_n}/{len(result['executed'])} ok"
            )
        except Exception:
            pass

        result['reason'] = f'resolved {len(candidates)} candidates → {len(tool_calls)} tool calls'
        return result


    def resolve_turn_async(self, turn_id: str, sir_utterance: str,
                            require_candidates: bool = False) -> threading.Thread:
        """fire-and-forget thread 入口, 主对话路径调这个 (零阻塞 TTFT)."""
        t = threading.Thread(
            target=self.resolve_turn,
            args=(turn_id, sir_utterance, require_candidates),
            name=f'IntentResolver-{turn_id[:12]}',
            daemon=True,
        )
        t.start()
        return t


# ---------------- 全局 singleton ----------------

_RESOLVER_INSTANCE: Optional[IntentResolver] = None


def get_intent_resolver() -> Optional[IntentResolver]:
    """全局 singleton getter, 没注册返 None."""
    return _RESOLVER_INSTANCE


def register_intent_resolver(resolver: IntentResolver) -> None:
    """central_nerve 创建后 register."""
    global _RESOLVER_INSTANCE
    _RESOLVER_INSTANCE = resolver
