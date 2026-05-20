# -*- coding: utf-8 -*-
"""[β.5.36-G / 2026-05-20] jarvis_intent_router.py — Intent → Tool 后端路由

Sir 2026-05-20 10:46 实测 BUG 3: 工具名泄漏 ("I can run process_hands.get_top_cpu...").
β.5.36-E 持久化 intent_to_tool_map.json, β.5.36-F 改 skill_registry.to_prompt_block
为 SEMANTIC CAPABILITIES (intent-based). 本模块 (β.5.36-G) 加后端解析 + 路由:

1. **IntentParser**: 从 LLM 输出 stream 提取 `<TOOL_CALL>{"intent":"X", "args":{...}}</TOOL_CALL>`
2. **IntentRouter**: 查 intent_to_tool_map 翻成 tool 名 → 调 fast_call_executor 执行
3. **结果回流**: 写 event_bus + plan_ledger evidence 给主脑下一轮 prompt 看到

设计原则 (准则 6):
- intent_to_tool_map 持久化 (vocab + CLI), 不在源码硬编码
- 失败/未知 intent 静默 + log (主路径不阻塞)
- dangerous intent 需 Sir 显式确认 (复用 PromiseExecutor 已有路径) — β.5.36-G v1 仅支持 safe/risky
  自动执行, dangerous → 不执行 + log warning (PromiseExecutor 走 PROMISE tag 路径)
- 主脑同时说 human language ('let me check CPU') + emit <TOOL_CALL>{intent='check_top_cpu'} —
  对 Sir 听感无变化, 但工具名不再被 TTS 说出来

doc: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md §C
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


# 默认 intent_to_tool_map 路径 (与 scripts/intent_map_dump.py + skill_registry._render_intent_block 一致)
DEFAULT_INTENT_MAP_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'intent_to_tool_map.json',
)

# <TOOL_CALL> tag regex (case-insensitive 兼容 LLM 不一致输出)
_TOOL_CALL_TAG_RE = re.compile(
    r'<TOOL_CALL>(.*?)</TOOL_CALL>',
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class IntentCall:
    """单次解析的 intent call (LLM 输出的一个 <TOOL_CALL> tag)."""
    intent_id: str
    args: Dict[str, Any] = field(default_factory=dict)
    raw_json: str = ''  # 原始 JSON 字符串 (debug 用)


class IntentParser:
    """从 LLM 输出文本抽 <TOOL_CALL>{...}</TOOL_CALL> tag → IntentCall list."""

    @classmethod
    def has_tool_call_tag(cls, text: Optional[str]) -> bool:
        if not text:
            return False
        return bool(_TOOL_CALL_TAG_RE.search(text))

    @classmethod
    def extract_all(cls, text: Optional[str]) -> List[IntentCall]:
        """提取所有 <TOOL_CALL>...</TOOL_CALL> 的 IntentCall.

        损坏的 JSON 跳过, 不抛. intent_id 必填; args 可选 (默认 {}).
        """
        if not text:
            return []
        calls: List[IntentCall] = []
        for m in _TOOL_CALL_TAG_RE.finditer(text):
            raw = (m.group(1) or '').strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            intent_id = (data.get('intent') or '').strip()
            if not intent_id:
                continue
            args = data.get('args', {}) or {}
            if not isinstance(args, dict):
                args = {}
            calls.append(IntentCall(
                intent_id=intent_id,
                args=args,
                raw_json=raw[:240],
            ))
        return calls

    @classmethod
    def strip_tags(cls, text: Optional[str]) -> str:
        """从 LLM 输出剥掉 <TOOL_CALL> tag, 返 cleaned 文本 (TTS / subtitle 用).

        即便 LLM 同时说人话 + 发 tag, TTS 不应该读出 tag 内容.
        """
        if not text:
            return ''
        return _TOOL_CALL_TAG_RE.sub('', text)


class IntentRouter:
    """Intent → Tool 路由器. 查 intent_to_tool_map 翻 tool 名 + 调 fast_call_executor.

    用法:
        router = IntentRouter(
            fast_call_executor=chat_bypass._execute_fast_call,
            event_bus=nerve.event_bus,
        )
        # LLM 输出文本含 <TOOL_CALL>{"intent":"check_top_cpu"}</TOOL_CALL>
        results = router.route_and_invoke_all(llm_text)
        # results = [{'intent_id':'check_top_cpu', 'tool':'process_hands.get_top_cpu',
        #             'success': True, 'msg':'...', 'latency_ms': 180}]
    """

    def __init__(
        self,
        fast_call_executor: Optional[Callable[[str, str, dict], str]] = None,
        event_bus: Any = None,
        intent_map_path: Optional[str] = None,
        skip_dangerous: bool = True,
    ):
        self.fast_call_executor = fast_call_executor
        self.event_bus = event_bus
        self.intent_map_path = intent_map_path or DEFAULT_INTENT_MAP_PATH
        self.skip_dangerous = skip_dangerous
        self._intent_map_cache: Optional[Dict[str, Dict]] = None
        self._intent_map_mtime: float = 0.0

    def _load_intent_map(self) -> Dict[str, Dict]:
        """mtime cache 读 intent_to_tool_map.json. 返 {intent_id: intent_entry}."""
        try:
            if not os.path.exists(self.intent_map_path):
                return {}
            mtime = os.path.getmtime(self.intent_map_path)
            if mtime == self._intent_map_mtime and self._intent_map_cache is not None:
                return self._intent_map_cache
            with open(self.intent_map_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            mapping = {}
            for c in data.get('intents', []):
                if c.get('state', 'active') == 'active' and c.get('id'):
                    mapping[c['id']] = c
            self._intent_map_cache = mapping
            self._intent_map_mtime = mtime
            return mapping
        except Exception:
            return self._intent_map_cache or {}

    def resolve_intent(self, intent_id: str) -> Optional[Dict]:
        """查 intent → entry. 未注册 / archived 返 None."""
        return self._load_intent_map().get(intent_id)

    def route_and_invoke(self, call: IntentCall) -> Dict[str, Any]:
        """单 intent → tool 调用. 返结果 dict."""
        result = {
            'intent_id': call.intent_id,
            'tool': None,
            'success': False,
            'msg': '',
            'latency_ms': 0,
            'reason': '',
        }

        entry = self.resolve_intent(call.intent_id)
        if entry is None:
            result['reason'] = 'unknown_intent'
            self._publish_event(call, result)
            return result

        tool_full = entry.get('tool', '')
        result['tool'] = tool_full
        if not tool_full or '.' not in tool_full:
            result['reason'] = 'invalid_tool_format'
            self._publish_event(call, result)
            return result

        # dangerous intent — β.5.36-G v1 不自动执行 (走 PromiseExecutor)
        danger = entry.get('dangerous_flag', 'safe')
        if self.skip_dangerous and danger == 'dangerous':
            result['reason'] = 'dangerous_requires_promise_path'
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"⚠️ [IntentRouter] dangerous intent={call.intent_id} "
                    f"tool={tool_full} skipped (need PROMISE path + Sir confirm)"
                )
            except Exception:
                pass
            self._publish_event(call, result)
            return result

        # 调 fast_call_executor
        if self.fast_call_executor is None:
            result['reason'] = 'no_fast_call_executor'
            self._publish_event(call, result)
            return result

        organ_name, command = tool_full.split('.', 1)
        start_ts = time.time()
        try:
            msg = self.fast_call_executor(organ_name, command, call.args or {})
            msg_str = str(msg) if msg is not None else ''
            result['msg'] = msg_str[:400]
            # 约定: msg 前缀 ✅/Done/OK 视为成功
            ok = (
                msg_str.startswith('✅') or
                msg_str.lower().startswith('done') or
                msg_str.lower().startswith('ok')
            )
            result['success'] = ok
            if not ok and not result['reason']:
                result['reason'] = 'tool_returned_non_success'
        except Exception as e:
            result['msg'] = f"Exception: {type(e).__name__}: {str(e)[:200]}"
            result['reason'] = 'tool_threw_exception'
            result['success'] = False
        finally:
            result['latency_ms'] = int((time.time() - start_ts) * 1000)

        # 更新 skill_registry KPI (复用 PromiseExecutor 同款机制)
        try:
            from jarvis_skill_registry import get_registry
            reg = get_registry()
            if reg is not None:
                reg.record_invocation(
                    tool_full,
                    success=result['success'],
                    latency_ms=result['latency_ms'],
                    error=None if result['success'] else result['msg'][:200],
                )
        except Exception:
            pass

        self._publish_event(call, result)
        try:
            from jarvis_utils import bg_log
            bg_log(
                f"🔧 [IntentRouter] intent={call.intent_id} → {tool_full} "
                f"success={result['success']} latency={result['latency_ms']}ms "
                f"msg='{result['msg'][:60]}'"
            )
        except Exception:
            pass
        return result

    def route_and_invoke_all(self, llm_text: Optional[str]) -> List[Dict[str, Any]]:
        """从 LLM 输出文本扫所有 <TOOL_CALL> tag 并执行. 返结果 list.

        失败/未知 intent 不抛, 进结果列表 (Sir 可调 dashboard 看哪些 intent 漏 register).
        """
        calls = IntentParser.extract_all(llm_text)
        results = []
        for call in calls:
            try:
                results.append(self.route_and_invoke(call))
            except Exception as e:
                # paranoia: route_and_invoke 内部 try 覆盖, 这里再加一层
                results.append({
                    'intent_id': call.intent_id,
                    'tool': None,
                    'success': False,
                    'msg': f'router fatal: {type(e).__name__}',
                    'latency_ms': 0,
                    'reason': 'router_exception',
                })
        return results

    def _publish_event(self, call: IntentCall, result: Dict) -> None:
        """把 intent 执行结果 publish 给 event_bus, 主脑下一轮 prompt 可读."""
        bus = self.event_bus
        if bus is None:
            return
        try:
            description = (
                f"intent={call.intent_id} → tool={result.get('tool') or '?'} "
                f"success={result.get('success')} "
                f"msg='{(result.get('msg') or '')[:80]}'"
            )
            bus.publish(
                etype='intent_call_result',
                description=description,
                source='IntentRouter',
                metadata={
                    'intent_id': call.intent_id,
                    'tool': result.get('tool'),
                    'success': result.get('success'),
                    'reason': result.get('reason'),
                    'latency_ms': result.get('latency_ms'),
                    'args_keys': list((call.args or {}).keys()),
                },
            )
        except Exception:
            pass


# 单例 helper (类似 get_registry / get_event_bus 模式)
_DEFAULT_ROUTER: Optional[IntentRouter] = None


def get_default_intent_router() -> Optional[IntentRouter]:
    """返 默认 IntentRouter 实例 (无 fast_call_executor — 调用方需注入).

    主路径不直接用此 helper. central_nerve 启动时构造 + 注入 fast_call_executor.
    """
    global _DEFAULT_ROUTER
    if _DEFAULT_ROUTER is None:
        _DEFAULT_ROUTER = IntentRouter()
    return _DEFAULT_ROUTER


def init_default_intent_router(
    fast_call_executor: Optional[Callable] = None,
    event_bus: Any = None,
) -> IntentRouter:
    """central_nerve 启动时初始化 default router 并注入回调."""
    global _DEFAULT_ROUTER
    _DEFAULT_ROUTER = IntentRouter(
        fast_call_executor=fast_call_executor,
        event_bus=event_bus,
    )
    return _DEFAULT_ROUTER
