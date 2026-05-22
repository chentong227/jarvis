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
    # 🆕 [β.5.46-fix14 / 2026-05-22] Gemini 3.5 Flash A/B (Sir 拍板副链 A/B)
    # 调研: gemini-3.5-flash GA 2026-05-19, 强 agentic/工具调用 (Terminal-Bench 76.2%
    # MCP Atlas 83.6%, beats 3.1 Pro), $1.50/$9 per 1M, 1M ctx, 4x faster.
    # IntentResolver 是 mutation tool 调度核心 (LLM judge 调哪些 tool), agentic 强项
    # 真适用. 切换 primary 试 1-2 周看 fact tool call 准确率 vs 老 lite. 主对话不动.
    # fallback 降级老 lite (3.5 rate limit / 挂时至少能跑), 不用 pro-preview (timeout 风险高 + 贵).
    'primary_model': 'google/gemini-3.5-flash',
    'fallback_model': 'google/gemini-2.5-flash-lite',
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
            # 🆕 [β.5.46-fix14 / 2026-05-22] A/B telemetry — 看 3.5-flash vs 老 lite
            'llm_primary_calls': 0,
            'llm_primary_ok': 0,
            'llm_primary_fail': 0,
            'llm_primary_latency_sum_ms': 0.0,
            'llm_fallback_calls': 0,
            'llm_fallback_ok': 0,
            'llm_fallback_fail': 0,
            'llm_fallback_latency_sum_ms': 0.0,
            'llm_parse_fail': 0,
            # 🆕 [P5-fix20-B1 / 2026-05-22] vocab fast-path telemetry
            'fast_path_hits': 0,
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
            # 🆕 [β.5.46-fix18 / 2026-05-22] Sir 真测 BUG: project hold persistence.
            # ProjectHoldDetector publish 此 candidate, 主脑看 evidence 调 tool_project_hold.
            'sir_intent_project_hold_candidate',
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
        # 🆕 [β.5.46-fix14] A/B telemetry — 记录 primary/fallback 真实成功率 + latency
        _t0 = time.time()
        try:
            with self._lock:
                self._stats['llm_primary_calls'] += 1
            response_text = safe_openrouter_call(
                openrouter_key=okey,
                model=self.config['primary_model'],
                prompt=prompt,
                max_tokens=self.config['max_output_tokens'],
                temperature=self.config['temperature'],
            )
            with self._lock:
                self._stats['llm_primary_ok'] += 1
                self._stats['llm_primary_latency_sum_ms'] += \
                    (time.time() - _t0) * 1000.0
        except Exception as e_primary:
            with self._lock:
                self._stats['llm_primary_fail'] += 1
                self._stats['llm_primary_latency_sum_ms'] += \
                    (time.time() - _t0) * 1000.0
            _t1 = time.time()
            try:
                with self._lock:
                    self._stats['llm_fallback_calls'] += 1
                response_text = safe_openrouter_call(
                    openrouter_key=okey,
                    model=self.config['fallback_model'],
                    prompt=prompt,
                    max_tokens=self.config['max_output_tokens'],
                    temperature=self.config['temperature'],
                )
                with self._lock:
                    self._stats['llm_fallback_ok'] += 1
                    self._stats['llm_fallback_latency_sum_ms'] += \
                        (time.time() - _t1) * 1000.0
            except Exception as e_fb:
                with self._lock:
                    self._stats['llm_fallback_fail'] += 1
                    self._stats['llm_fallback_latency_sum_ms'] += \
                        (time.time() - _t1) * 1000.0
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
            # 🆕 [P5-fix28+30 / 2026-05-22] Sir 20:40 + 21:01 真测 LLM 返:
            #   - {"t...           (truncate, fix28 rfind(']') rescue)
            #   - 你可以看下你的记忆"  (plain text, fix30 detect 无 '{' 早返 empty)
            #   - " Precision is preferred (markdown 起头, fix30 同上)
            # 治本三档:
            #  (1) 不以 '{' 开头 → 主脑没听 system 指令返 JSON, 直接 empty + 不噪音
            #  (2) 以 '{' 开头但 truncated → rfind(']') 试补 '}'
            #  (3) 都不行 → empty + 静默
            try:
                parsed = json.loads(txt)
            except json.JSONDecodeError:
                # (1) plain text 没 '{' 起首 → 主脑该返 JSON 但说人话了
                _stripped = txt.lstrip()
                if not _stripped.startswith('{'):
                    with self._lock:
                        self._stats['llm_parse_fail'] += 1
                    return {'tool_calls': [],
                              '_error': f'non-JSON response ({len(txt)}c) — '
                                          f'LLM didn\'t follow JSON-only rule, '
                                          f'recoverable, treating as no-tool'}
                # (2) JSON-like 但 truncate
                _idx = txt.rfind(']')
                if _idx > 0:
                    rescue_txt = txt[: _idx + 1] + '}'
                    try:
                        parsed = json.loads(rescue_txt)
                    except Exception:
                        with self._lock:
                            self._stats['llm_parse_fail'] += 1
                        return {'tool_calls': [],
                                  '_error': f'truncated JSON ({len(txt)}c) — '
                                              f'recoverable, treating as no-tool'}
                else:
                    # (3) JSON-like 但根本没 ] → 几乎肯定 truncate, 静默
                    with self._lock:
                        self._stats['llm_parse_fail'] += 1
                    return {'tool_calls': [],
                              '_error': f'unparseable JSON ({len(txt)}c) — '
                                          f'recoverable, treating as no-tool'}
            if not isinstance(parsed, dict):
                with self._lock:
                    self._stats['llm_parse_fail'] += 1
                return {'tool_calls': [], '_error': 'LLM returned non-dict'}
            tcs = parsed.get('tool_calls', [])
            if not isinstance(tcs, list):
                tcs = []
            return {'tool_calls': tcs[: self.config['max_tool_calls_per_turn']]}
        except Exception as e:
            with self._lock:
                self._stats['llm_parse_fail'] += 1
            return {
                'tool_calls': [],
                '_error': f'parse fail: {str(e)[:60]} resp={response_text[:120]}',
            }

    # ---------------- vocab fast-path (P5-fix20-B1) ----------------

    _VOCAB_PATH = 'memory_pool/intent_fast_path_vocab.json'

    def _load_fast_path_vocab(self) -> List[Dict]:
        """🆕 [P5-fix20-B1 / 2026-05-22] 读 fast-path vocab.

        Sir 14:32 真测痛点: OpenRouter 全挂 → IntentResolver LLM 全 fail → 0 mutation.
        fast-path 在 LLM 之前 keyword 匹配, 高确定性场景直达 tool, LLM 挂兜底.
        准则 6 vocab 持久化 — 数据在 memory_pool/intent_fast_path_vocab.json,
        Sir 通过 scripts/intent_fast_path_dump.py CLI 改, 不动源码.
        """
        try:
            with open(self._VOCAB_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return [v for v in data.get('vocab', []) if v.get('active')]
        except Exception:
            return []

    def _render_template_value(self, value: Any, sir_utterance: str,
                                  phrase: str) -> Any:
        """🆕 [P5-fix20-B1] template render — 支持 {sir_utterance} / {after_phrase}.

        - {sir_utterance}: 替换 Sir 原话
        - {after_phrase}:  替换 phrase 之后的子串 (lowercase utterance), trim 首尾空白
                           e.g. utterance='我想暂停 dashboard 项目', phrase='暂停'
                           → after_phrase='dashboard 项目'
        - {before_phrase}: 替换 phrase 之前的子串
        非 str 原样返.
        """
        if not isinstance(value, str):
            return value
        out = value
        if '{sir_utterance}' in out:
            out = out.replace('{sir_utterance}', sir_utterance or '')
        if '{after_phrase}' in out or '{before_phrase}' in out:
            utt_lower = (sir_utterance or '').strip().lower()
            p_lower = (phrase or '').lower()
            if p_lower and p_lower in utt_lower:
                idx = utt_lower.index(p_lower)
                # 用 lower 找位, 但取原 case 子串
                before = (sir_utterance or '')[:idx].strip()
                after = (sir_utterance or '')[idx + len(p_lower):].strip()
                # trim 标点 (中英常见)
                for c in ('.,。,!?！？:;:；'):
                    before = before.strip(c).strip()
                    after = after.strip(c).strip()
                out = out.replace('{after_phrase}', after)
                out = out.replace('{before_phrase}', before)
            else:
                out = out.replace('{after_phrase}', '')
                out = out.replace('{before_phrase}', '')
        return out

    def _check_vocab_fast_path(self, sir_utterance: str) -> List[Dict]:
        """匹配 vocab → 返 tool_calls list (LLM 前的短路).

        Returns: list of {'name', 'args', 'reason', '_via': 'fast_path', '_phrase': '...'}
                 多条 vocab 命中 → 多条 tool_call (同一 tool 仅取首条 vocab, 防重复调).

        skip 条件:
          - vocab 抽 args 后含 None/空必填 → 跳过 (避免 tool 调用 fail)
          - tool 不存在
          - phrase len/utt len 不匹配
        """
        utt = (sir_utterance or '').strip().lower()
        if not utt:
            return []
        vocab = self._load_fast_path_vocab()
        if not vocab:
            return []
        matched = []
        seen_tools: set = set()
        for v in vocab:
            phrase = (v.get('phrase') or '').lower().strip()
            if not phrase:
                continue
            min_len = v.get('min_utterance_len', 0)
            max_len = v.get('max_utterance_len', 0)
            if len(utt) < min_len:
                continue
            if max_len > 0 and len(utt) > max_len:
                continue
            if phrase not in utt:
                continue
            tool_name = v.get('tool_name', '')
            if not tool_name or tool_name not in self.tools:
                continue
            if tool_name in seen_tools:
                continue  # 同一 tool 已命中过 (vocab list order = priority)
            # render args template
            args_t = dict(v.get('tool_args_template') or {})
            args = {}
            skip = False
            required_args = v.get('required_args', [])  # vocab 可声明 必填字段
            for ak, av in args_t.items():
                rendered = self._render_template_value(av, sir_utterance, phrase)
                if ak in required_args and not rendered:
                    skip = True
                    break  # 必填空 → 跳过这条 vocab (防 tool 调用 fail)
                args[ak] = rendered
            if skip:
                continue
            matched.append({
                'name': tool_name,
                'args': args,
                'reason': f"fast-path: '{phrase}' (conf={v.get('confidence', '?')})",
                '_via': 'fast_path',
                '_phrase': phrase,
            })
            seen_tools.add(tool_name)
        return matched

    # ---------------- 主入口 ----------------

    def resolve_turn(self, turn_id: str, sir_utterance: str,
                     require_candidates: bool = False) -> Dict:
        """turn 末尾调. 收 SWM candidate + state evidence → LLM judge → 调 tool → publish intent_resolved.

        🆕 [P5-fix20-B1 / 2026-05-22] LLM 之前先跑 _check_vocab_fast_path —
        高确定性 vocab (e.g. "暂停 X") 命中即直达 tool, 不耗 LLM token.
        LLM judge fail 时 fast-path 命中也兜底.

        Args:
          turn_id: 本轮 ID
          sir_utterance: Sir 原话 (LLM 主要 evidence)
          require_candidates: True = 必须有 module candidate 才跑 (B 重构完后);
                              False (默认) = 无 candidate 也基于 utterance + state 直接 LLM judge.
                              过渡期 (B 没改完) 用 False; B 完成后改 True 节省 token.

        Returns: {'tool_calls': [...], 'executed': [...], 'reason': str,
                   'fast_path_matched': bool}
        """
        result = {'tool_calls': [], 'executed': [], 'reason': '',
                    'fast_path_matched': False}

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

        # 🆕 [P5-fix20-B1] vocab fast-path 先跑 (高确定性场景 skip LLM)
        fast_path_calls = self._check_vocab_fast_path(sir_utterance)
        if fast_path_calls:
            result['fast_path_matched'] = True
            try:
                from jarvis_utils import bg_log
                phrases = [c.get('_phrase') for c in fast_path_calls]
                bg_log(
                    f"⚡ [IntentResolver/FastPath] turn={turn_id[:20]} "
                    f"matched {len(fast_path_calls)} vocab → "
                    f"{[c['name'] for c in fast_path_calls]} "
                    f"(phrases={phrases}) — skip LLM judge"
                )
            except Exception:
                pass
            # fast-path 直接走 tool 执行路径, 不调 LLM
            return self._execute_tool_calls(
                turn_id=turn_id,
                sir_utterance=sir_utterance,
                candidates=candidates,
                tool_calls=fast_path_calls,
                via='fast_path',
                result=result,
            )

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
            # 🩹 [β.5.43-F + P5-fix30] LLM fail → ErrorBus.
            # fix30: '_error' 含 'recoverable, treating as no-tool' (parse rescue)
            # 不报 ErrorBus — 这是常见 case, 主路径已 graceful 处理. 报会刷噪.
            _err = plan['_error']
            _silent = 'treating as no-tool' in _err
            if not _silent:
                try:
                    from jarvis_error_bus import report_error, SEVERITY_MODERATE
                    report_error(
                        module='intent_resolver',
                        kind='llm_judge_fail',
                        detail=_err[:200],
                        severity=SEVERITY_MODERATE,
                        recoverable=True,
                        suggested_action='check key_router quota or LLM model availability',
                    )
                except Exception:
                    pass
            return result

        tool_calls = plan.get('tool_calls', [])
        return self._execute_tool_calls(
            turn_id=turn_id,
            sir_utterance=sir_utterance,
            candidates=candidates,
            tool_calls=tool_calls,
            via='llm',
            result=result,
        )

    def _execute_tool_calls(self, turn_id: str, sir_utterance: str,
                             candidates: List[Dict],
                             tool_calls: List[Dict],
                             via: str,
                             result: Dict) -> Dict:
        """🆕 [P5-fix20-B1 / 2026-05-22] 执行 tool_calls + publish — 抽出来让
        LLM 路径和 fast-path 共用 (复用所有 publish / ErrorBus / stats / log).

        Args:
          turn_id, sir_utterance, candidates: turn 上下文 (publish 元信息)
          tool_calls: list of {name, args, reason, [_via, _phrase]}
          via: 'llm' / 'fast_path' (publish 时 metadata 标识)
          result: 已部分填充的 result dict (会就地更新 + 返)
        """
        result['tool_calls'] = tool_calls

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
            tc_via = tc.get('_via', via)
            tc_phrase = tc.get('_phrase', '')
            if not name or name not in self.tools:
                # tool 不存在 → 记 failed
                if bus is not None:
                    try:
                        bus.publish(
                            etype='tool_called',
                            description=f'tool {name} unknown ({tc_via} 编了名字)',
                            source='IntentResolver',
                            salience=0.5,
                            metadata={
                                'turn_id': turn_id,
                                'name': name,
                                'args': args,
                                'ok': False,
                                'error': 'unknown_tool',
                                'reason': reason,
                                'via': tc_via,
                            },
                        )
                    except Exception:
                        pass
                with self._lock:
                    self._stats['tools_failed_total'] += 1
                result['executed'].append({
                    'name': name, 'ok': False, 'error': 'unknown_tool', 'via': tc_via,
                })
                continue

            fn = self.tools[name]
            ok = False
            err = ''
            tool_result = None
            try:
                tool_result = fn(**args)
                if isinstance(tool_result, dict):
                    ok = bool(tool_result.get('ok', True))
                    err = str(tool_result.get('error', ''))[:200]
                else:
                    ok = True
            except Exception as e:
                ok = False
                err = str(e)[:200]

            if not ok:
                try:
                    from jarvis_error_bus import report_error, SEVERITY_MODERATE
                    report_error(
                        module='intent_resolver',
                        kind=f'tool_fail.{name}',
                        detail=f'{err} (via={tc_via} args={json.dumps(args, ensure_ascii=False)[:100]})',
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
                            + (f' [via={tc_via}]' if tc_via != 'llm' else '')
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
                            'via': tc_via,
                            'phrase': tc_phrase,
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
                'name': name, 'ok': ok, 'error': err, 'via': tc_via,
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
                        + (f" [via={via}]" if via != 'llm' else '')
                    ),
                    source='IntentResolver',
                    salience=0.90,
                    metadata={
                        'turn_id': turn_id,
                        'sir_utterance_excerpt': str(sir_utterance or '')[:200],
                        'tool_calls': result['executed'],
                        'candidates_count': len(candidates),
                        'via': via,
                    },
                )
            except Exception:
                pass

        with self._lock:
            self._stats['turns_resolved'] += 1
            self._stats['last_resolve_ts'] = time.time()
            # 🆕 [P5-fix20-B1] fast-path 命中计数 (telemetry)
            if via == 'fast_path':
                self._stats['fast_path_hits'] = self._stats.get('fast_path_hits', 0) + 1

        try:
            from jarvis_utils import bg_log
            ok_n = sum(1 for e in result['executed'] if e.get('ok'))
            bg_log(
                f"🧭 [IntentResolver] turn={turn_id[:20]} "
                f"candidates={len(candidates)} via={via} → "
                f"tools={ok_n}/{len(result['executed'])} ok"
            )
        except Exception:
            pass

        try:
            self._persist_telemetry()
        except Exception:
            pass

        result['reason'] = (f'resolved {len(candidates)} candidates → '
                              f'{len(tool_calls)} tool calls (via={via})')
        return result

    def _persist_telemetry(self) -> None:
        """🆕 [β.5.46-fix14] 把 stats 写到 memory_pool/intent_resolver_telemetry.json.

        Sir CLI `scripts/intent_resolver_telemetry_dump.py` 跨进程看. 防止 process
        重启丢 stats. atomic write (tmp + replace).
        """
        try:
            import json
            import os
            path = os.path.join('memory_pool', 'intent_resolver_telemetry.json')
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            with self._lock:
                payload = {
                    '_doc': '[β.5.46-fix14] IntentResolver A/B telemetry — '
                            '3.5-flash primary vs 2.5-flash-lite fallback',
                    'primary_model': self.config['primary_model'],
                    'fallback_model': self.config['fallback_model'],
                    'updated_at': time.time(),
                    'stats': dict(self._stats),
                }
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            pass


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
