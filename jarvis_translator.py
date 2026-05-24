# -*- coding: utf-8 -*-
"""JARVIS L4.6 Translator — LLM emit → 架构 schema 翻译层.

设计 doc: docs/JARVIS_TRANSLATOR_ARCHITECTURE.md
起源: Sir 2026-05-24 19:49 "LLM 没办法把我说的话翻译成现有架构可理解的语言"

职责:
- Lv1 词汇 alias: organ / command 同义名 → 精确名 (vocab.json)
- Lv2 schema 验证: 必填参数 (manifest schema_vocab.json)
- 失败 → actionable msg 教 LLM 下轮 self-correct
- SWM publish: translator_aliased / translator_rejected / translator_schema_matched

不职责:
- Lv3 意图翻译 (主脑做)
- 真正执行 hand / mutation (Tool Execution Layer 做)
- Cross-organ 同名消歧 (准则 5 不猜, 拒绝 + actionable)
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ----- 持久化文件路径 -----
_HERE = os.path.dirname(os.path.abspath(__file__))
_ALIAS_VOCAB_PATH = os.path.join(_HERE, 'memory_pool', 'translator_alias_vocab.json')
_SCHEMA_VOCAB_PATH = os.path.join(_HERE, 'memory_pool', 'translator_schema_vocab.json')

# ----- param key 排除集 (反向 command lookup 时忽略, 避免误将 param 名当 command) -----
_PARAM_KEY_BLACKLIST = frozenset({
    'intent', 'query', 'id', 'trigger_time', 'time_range_hours',
    'new_intent', 'new_time', 'max_age_hours', 'description', 'name',
    'path', 'value', 'reason', 'turn_id', 'source', 'field_path',
    'new_value', 'old_value', 'kind', 'severity', 'metadata',
})


@dataclass
class TranslationResult:
    """Translator 翻译结果. 不抛 exception, 失败时 success=False."""
    success: bool
    organ_name: Optional[str] = None
    command: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)

    # 失败时:
    error_kind: Optional[str] = None
    actionable_msg: Optional[str] = None

    # 元数据 (审计 / SWM publish 用):
    aliased_from: Dict[str, Any] = field(default_factory=dict)
    schema_validated: bool = False
    alias_kind: Optional[str] = None  # suffix_hands / vocab_alias / by_command / exact
    translated_at: float = field(default_factory=time.time)


class Translator:
    """L4.6 LLM → 架构 schema 翻译层. 纯 python + vocab. 关键路径 < 1ms.

    使用:
        translator = Translator(hand_registry, hand_manifests, event_bus=bus)
        result = translator.translate(organ_name, command, params)
        if result.success:
            # 用 result.organ_name / result.command / result.params 调 hand
        else:
            # 用 result.actionable_msg 作 tool_result 给主脑 self-correct
    """

    def __init__(self, hand_registry: Optional[Dict[str, Any]] = None,
                 hand_manifests: Optional[Dict[str, Any]] = None,
                 event_bus: Any = None,
                 gemini_key: Optional[str] = None):
        self.hand_registry = hand_registry or {}
        self.hand_manifests = hand_manifests or {}
        self.event_bus = event_bus
        self.gemini_key = gemini_key

        # lazy 加载 (mtime cache 重载)
        self._alias_vocab_cache: Optional[Dict[str, Any]] = None
        self._alias_vocab_mtime: float = 0.0
        self._schema_vocab_cache: Optional[Dict[str, Any]] = None
        self._schema_vocab_mtime: float = 0.0

        # 反向 command index (lazy build, 首次使用时构)
        self._command_index: Optional[Dict[str, str]] = None
        self._lock = threading.Lock()

        # 🆕 [Translator Phase 4.A / 2026-05-24 22:40] hit_count 闭环
        # 每次 _lookup_vocab_alias 命中 active alias → bump in-memory (alias_id → +1).
        # nerve daemon 每 60s 调 flush_hit_updates() 落盘 (节流防过频写 IO).
        # 让 reflector / dashboard 看 真实 hit_count, 不止 propose 时的初始值.
        # Sir CLI: scripts/translator_alias_dump.py list 看 hit_count 知道哪个 alias 真常用.
        self._hit_buffer: Dict[str, int] = {}      # alias_id → pending +N
        self._hit_buffer_last_ts: Dict[str, float] = {}  # alias_id → last_hit_at
        self._hit_buffer_lock = threading.Lock()

    # ========== 主入口 ==========
    def translate(self, organ_name: Any, command: Any,
                   params: Optional[Dict[str, Any]] = None) -> TranslationResult:
        """主入口. 不抛 exception, 失败时返不 success 让调用方兜底."""
        params = params or {}

        # 1. None / 空 guard (BUG #3 同型)
        if not organ_name or not command or \
           not isinstance(organ_name, str) or not isinstance(command, str) or \
           not organ_name.strip() or not command.strip():
            return TranslationResult(
                success=False,
                error_kind='malformed',
                actionable_msg=(
                    "FAST_CALL malformed — organ_name 或 command 为空 / 非 str. "
                    "请用完整 organ.command 格式. 若不确定 organ, 改问 Sir, 不发 FAST_CALL."
                ),
                aliased_from={'organ': organ_name, 'cmd': command},
            )

        organ_name = organ_name.strip()
        command = command.strip()

        # 2. Lv1 organ resolve (3 层 waterfall)
        resolved_organ, alias_kind = self._resolve_organ(organ_name, command)
        if resolved_organ is None:
            return self._make_unknown_organ_result(organ_name, command, params)

        # 3. Lv1 command resolve (organ scope 内)
        resolved_cmd = self._resolve_command(resolved_organ, command)
        # command 不在 vocab 时不算 fail (hand 自己处理), 仅传透

        # 4. Lv1 param 归一化 (Phase 1 简化: 仅 trim string)
        normalized_params = self._normalize_params(resolved_organ, resolved_cmd, params)

        # 5. Lv2 schema 验证 (manifest required_params)
        ok, err_kind, err_msg = self._validate_schema(resolved_organ, resolved_cmd, normalized_params)
        if not ok:
            self._publish_rejected(organ_name, command, resolved_organ, resolved_cmd, err_kind)
            return TranslationResult(
                success=False,
                organ_name=resolved_organ,
                command=resolved_cmd,
                params=normalized_params,
                error_kind=err_kind,
                actionable_msg=err_msg,
                aliased_from={'organ': organ_name, 'cmd': command, 'params': dict(params)},
                alias_kind=alias_kind,
            )

        # 6. 成功 publish SWM
        if alias_kind and alias_kind != 'exact':
            self._publish_aliased(organ_name, resolved_organ, alias_kind, command)
        self._publish_schema_matched(resolved_organ, resolved_cmd)

        return TranslationResult(
            success=True,
            organ_name=resolved_organ,
            command=resolved_cmd,
            params=normalized_params,
            aliased_from={'organ': organ_name, 'cmd': command, 'params': dict(params)},
            schema_validated=True,
            alias_kind=alias_kind,
        )

    # ========== Lv1 organ resolve (3 层 waterfall) ==========
    def _resolve_organ(self, organ_name: str, command: str) -> Tuple[Optional[str], Optional[str]]:
        """返 (resolved_organ, alias_kind). 找不到返 (None, None).

        waterfall: 精确 → +_hands → vocab alias → 反向 command lookup
        """
        # 1. 精确命中
        if organ_name in self.hand_registry:
            return organ_name, 'exact'

        # 2. + '_hands' 兜底
        if not organ_name.endswith('_hands'):
            aliased = organ_name + '_hands'
            if aliased in self.hand_registry:
                return aliased, 'suffix_hands'

        # 3. vocab.json alias 查 (持久化 alias)
        vocab_to = self._lookup_vocab_alias('organ', organ_name)
        if vocab_to and vocab_to in self.hand_registry:
            return vocab_to, 'vocab_alias'

        # 4. 反向 command lookup (主脑 emit 不存在 organ 但 command 在哪个 hand)
        by_cmd = self._lookup_organ_by_command(command)
        if by_cmd:
            return by_cmd, 'by_command'

        return None, None

    # ========== Lv1 command resolve ==========
    def _resolve_command(self, organ_name: str, command: str) -> str:
        """看 vocab.json 是否有 command alias. 没有返原 command (hand 自己 fallback)."""
        vocab_to = self._lookup_vocab_alias('command', command, scope_organ=organ_name)
        if vocab_to:
            return vocab_to
        return command

    # ========== Lv1 param 归一化 (Phase 1 简化, 仅 trim) ==========
    def _normalize_params(self, organ: str, command: str,
                          params: Dict[str, Any]) -> Dict[str, Any]:
        """Phase 1 仅 trim string. Phase 2+ 加 trigger_time '明天 8 点' → ISO 等."""
        out = {}
        for k, v in (params or {}).items():
            if isinstance(v, str):
                out[k] = v.strip()
            else:
                out[k] = v
        return out

    # ========== Lv2 schema 验证 ==========
    def _validate_schema(self, organ: str, command: str,
                         params: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[str]]:
        """看 schema_vocab.json 是否有 required_params. 缺则失败."""
        schema = self._lookup_schema_hint(organ, command)
        if not schema:
            return True, None, None  # 没 schema 定义就放过

        for req in schema.get('required_params', []) or []:
            if req not in params or params[req] in (None, '', [], {}):
                actionable = self._build_missing_param_msg(organ, command, req, schema)
                return False, 'missing_param', actionable

        return True, None, None

    # ========== actionable msg 生成 ==========
    def _build_missing_param_msg(self, organ: str, command: str,
                                 missing_param: str, schema: Dict[str, Any]) -> str:
        examples = schema.get('examples', []) or []
        common_mistakes = schema.get('common_mistakes', []) or []

        lines = [
            f"{organ}.{command} 缺 {missing_param} 参数.",
            "下一轮: 先用自然语言问 Sir, Sir 答了再 emit FAST_CALL. 不抢发.",
        ]
        if examples:
            ex = examples[0]
            lines.append(f"正确示例: {ex.get('fast_call', '')}")
        if common_mistakes:
            lines.append(f"常见错: {common_mistakes[0]}")
        return ' '.join(lines)

    def _make_unknown_organ_result(self, organ_name: str, command: str,
                                    params: Dict[str, Any]) -> TranslationResult:
        registered = sorted(self.hand_registry.keys())[:10]
        msg = (
            f"organ '{organ_name}' 未在 hand_registry 注册. "
            f"已挂载 organ 示例: {', '.join(registered)} ... "
            f"请用完整 organ.command, 若不确定改问 Sir."
        )
        self._publish_rejected(organ_name, command, None, None, 'unknown_organ')
        return TranslationResult(
            success=False,
            error_kind='unknown_organ',
            actionable_msg=msg,
            aliased_from={'organ': organ_name, 'cmd': command, 'params': dict(params)},
        )

    # ========== vocab.json 读取 (mtime cache) ==========
    def _load_alias_vocab(self) -> Dict[str, Any]:
        """加载 translator_alias_vocab.json, mtime cache."""
        try:
            mtime = os.path.getmtime(_ALIAS_VOCAB_PATH)
        except OSError:
            return {'aliases': []}

        if self._alias_vocab_cache is not None and mtime == self._alias_vocab_mtime:
            return self._alias_vocab_cache

        try:
            with open(_ALIAS_VOCAB_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._alias_vocab_cache = data
            self._alias_vocab_mtime = mtime
            return data
        except Exception:
            return {'aliases': []}

    def _load_schema_vocab(self) -> Dict[str, Any]:
        try:
            mtime = os.path.getmtime(_SCHEMA_VOCAB_PATH)
        except OSError:
            return {'schema_hints': []}

        if self._schema_vocab_cache is not None and mtime == self._schema_vocab_mtime:
            return self._schema_vocab_cache

        try:
            with open(_SCHEMA_VOCAB_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._schema_vocab_cache = data
            self._schema_vocab_mtime = mtime
            return data
        except Exception:
            return {'schema_hints': []}

    def _lookup_vocab_alias(self, kind: str, from_name: str,
                            scope_organ: Optional[str] = None) -> Optional[str]:
        """查 vocab 找 active 状态的 alias.

        kind: 'organ' 或 'command'
        scope_organ: command alias 时, 限定 organ scope
        """
        vocab = self._load_alias_vocab()
        candidates = []
        for entry in vocab.get('aliases', []) or []:
            if entry.get('kind') != kind:
                continue
            if entry.get('status') != 'active':
                continue
            if entry.get('from') != from_name:
                continue
            if kind == 'command' and scope_organ:
                if entry.get('scope_organ') and entry.get('scope_organ') != scope_organ:
                    continue
            candidates.append(entry)

        if not candidates:
            return None
        # 多 active 时, 取 version 最大的
        candidates.sort(key=lambda e: e.get('version', 1), reverse=True)
        winner = candidates[0]
        # 🆕 [Phase 4.A] 命中 → bump in-memory hit (节流 60s daemon flush 落盘)
        alias_id = winner.get('id')
        if alias_id:
            now = time.time()
            with self._hit_buffer_lock:
                self._hit_buffer[alias_id] = self._hit_buffer.get(alias_id, 0) + 1
                self._hit_buffer_last_ts[alias_id] = now
        return winner.get('to')

    def _lookup_schema_hint(self, organ: str, command: str) -> Optional[Dict[str, Any]]:
        vocab = self._load_schema_vocab()
        for hint in vocab.get('schema_hints', []) or []:
            if hint.get('organ') == organ and hint.get('command') == command:
                return hint
        return None

    # ========== 反向 command lookup (lazy build) ==========
    def _lookup_organ_by_command(self, command: str) -> Optional[str]:
        if not command:
            return None
        with self._lock:
            if self._command_index is None:
                self._command_index = self._build_command_index()
        return self._command_index.get(command)

    def _build_command_index(self) -> Dict[str, str]:
        """扫所有 hand_registry 的 get_instruction_dict() 提 command."""
        cache: Dict[str, str] = {}
        for organ_name, hand_class in self.hand_registry.items():
            inst = None
            for ctor in (
                lambda: hand_class(self.gemini_key) if self.gemini_key else hand_class(),
                lambda: hand_class(),
            ):
                try:
                    inst = ctor()
                    break
                except Exception:
                    continue
            if inst is None or not hasattr(inst, 'get_instruction_dict'):
                continue
            try:
                doc = inst.get_instruction_dict()
            except Exception:
                continue
            # regex 提 "command_name": { 模式 (匹配 manifest 风格)
            for m in re.finditer(r'["\'](\w+)["\']\s*:\s*\{', doc or ''):
                cmd = m.group(1)
                if cmd in _PARAM_KEY_BLACKLIST:
                    continue
                if cmd not in cache:
                    cache[cmd] = organ_name
        return cache

    # ========== SWM publish ==========
    def _publish_aliased(self, from_organ: str, to_organ: str,
                         alias_kind: str, command: str) -> None:
        if self.event_bus is None:
            return
        try:
            self.event_bus.publish(
                etype='translator_aliased',
                description=(
                    f"Translator alias '{from_organ}.{command}' → "
                    f"'{to_organ}.{command}' ({alias_kind})"
                ),
                source='Translator',
                salience=0.55,
                metadata={
                    'from_organ': from_organ,
                    'to_organ': to_organ,
                    'alias_kind': alias_kind,
                    'command': command,
                },
                ttl=600.0,
            )
        except Exception:
            pass

    def _publish_rejected(self, from_organ: str, command: str,
                           to_organ: Optional[str], to_cmd: Optional[str],
                           err_kind: str) -> None:
        if self.event_bus is None:
            return
        try:
            self.event_bus.publish(
                etype='translator_rejected',
                description=(
                    f"Translator reject '{from_organ}.{command}' "
                    f"({err_kind})"
                ),
                source='Translator',
                salience=0.75,
                metadata={
                    'from_organ': from_organ,
                    'command': command,
                    'to_organ': to_organ,
                    'to_command': to_cmd,
                    'error_kind': err_kind,
                },
                ttl=1800.0,
            )
        except Exception:
            pass

    def _publish_schema_matched(self, organ: str, command: str) -> None:
        if self.event_bus is None:
            return
        try:
            self.event_bus.publish(
                etype='translator_schema_matched',
                description=f"Translator schema OK for {organ}.{command}",
                source='Translator',
                salience=0.20,
                metadata={'organ': organ, 'command': command},
                ttl=60.0,
            )
        except Exception:
            pass

    # ========== 主脑 prompt 注入 helper (Phase 2) ==========
    def render_prompt_block(self, max_chars: int = 1200) -> str:
        """🆕 [Translator Phase 2 / 2026-05-24 20:50] 主脑 prompt 注入.

        从 schema_vocab.json 读 examples + common_mistakes, 渲染成 prompt block.
        返回 < max_chars. 让主脑 emit FAST_CALL 时少犯 BUG (减翻译层 BUG).
        """
        vocab = self._load_schema_vocab()
        hints = vocab.get('schema_hints', []) or []
        if not hints:
            return ''

        lines = ['[HAND SCHEMA EXAMPLES - emit FAST_CALL 参考]']
        for hint in hints:
            organ = hint.get('organ', '')
            cmd = hint.get('command', '')
            req = hint.get('required_params', []) or []
            examples = hint.get('examples', []) or []
            mistakes = hint.get('common_mistakes', []) or []

            req_str = ' + '.join(req) if req else '无必填'
            line = f"- {organ}.{cmd}: 必填 {req_str}."
            if examples:
                ex = examples[0].get('fast_call', '')
                if ex:
                    line += f" 例: {ex}"
            lines.append(line)
            # 仅 priority hand 加 mistake (省 chars)
            if mistakes and organ in ('memory_hands', 'progress'):
                lines.append(f"  ⚠️ {mistakes[0]}")

        block = '\n'.join(lines)
        if len(block) > max_chars:
            block = block[:max_chars - 4] + '...'
        return block

    # ========== Phase 4.A: hit_count 闭环 flush ==========
    def flush_hit_updates(self) -> int:
        """落盘 in-memory hit_buffer 到 translator_alias_vocab.json.

        🆕 [Translator Phase 4.A / 2026-05-24 22:40] hit_count 闭环回写.
        被 nerve daemon 每 60s 调一次. 也可在退出时调.
        无 pending updates 直接返 0, 不动 IO. atomic write (tmp + os.replace).

        Returns:
            int: 实际 merged 的 alias 数 (含命中的 active alias 数)
        """
        # 1. 快照 + 清 buffer (持锁短)
        with self._hit_buffer_lock:
            if not self._hit_buffer:
                return 0
            pending_counts = dict(self._hit_buffer)
            pending_ts = dict(self._hit_buffer_last_ts)
            self._hit_buffer.clear()
            self._hit_buffer_last_ts.clear()

        # 2. load 当前 vocab (绕 mtime cache, 拿最新 disk 内容)
        try:
            if not os.path.exists(_ALIAS_VOCAB_PATH):
                return 0
            with open(_ALIAS_VOCAB_PATH, 'r', encoding='utf-8') as f:
                vocab = json.load(f)
        except Exception:
            # load fail → 退回 buffer (下次 retry)
            with self._hit_buffer_lock:
                for aid, cnt in pending_counts.items():
                    self._hit_buffer[aid] = self._hit_buffer.get(aid, 0) + cnt
                    if aid in pending_ts:
                        self._hit_buffer_last_ts[aid] = max(
                            self._hit_buffer_last_ts.get(aid, 0.0),
                            pending_ts[aid]
                        )
            return 0

        # 3. merge pending → vocab.aliases
        merged = 0
        for entry in vocab.get('aliases', []) or []:
            aid = entry.get('id')
            if aid in pending_counts:
                old_hit = int(entry.get('hit_count', 0) or 0)
                entry['hit_count'] = old_hit + pending_counts[aid]
                entry['last_hit_at'] = pending_ts.get(aid, time.time())
                merged += 1

        # 4. atomic write
        try:
            from datetime import datetime as _dt
            vocab['last_modified'] = _dt.utcnow().isoformat() + 'Z'
            tmp = _ALIAS_VOCAB_PATH + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(vocab, f, indent=2, ensure_ascii=False)
            os.replace(tmp, _ALIAS_VOCAB_PATH)
            # invalidate cache (强制下次 _lookup reload)
            self._alias_vocab_cache = None
            self._alias_vocab_mtime = 0.0
            return merged
        except Exception:
            return 0

    # ========== 调试 / stats API ==========
    def get_stats(self) -> Dict[str, Any]:
        """返当前 Translator 状态 (供 dashboard / CLI 用)."""
        vocab = self._load_alias_vocab()
        aliases = vocab.get('aliases', []) or []
        with self._lock:
            cmd_idx_size = len(self._command_index or {})
        with self._hit_buffer_lock:
            hit_buffer_size = len(self._hit_buffer)
            hit_buffer_pending = sum(self._hit_buffer.values())
        return {
            'alias_total': len(aliases),
            'alias_active': len([a for a in aliases if a.get('status') == 'active']),
            'alias_review': len([a for a in aliases if a.get('status') == 'review']),
            'alias_rejected': len([a for a in aliases if a.get('status') == 'rejected']),
            'command_index_size': cmd_idx_size,
            'hand_registry_size': len(self.hand_registry),
            # 🆕 [Phase 4.A] hit buffer 状态
            'hit_buffer_aliases': hit_buffer_size,
            'hit_buffer_pending_total': hit_buffer_pending,
        }


# ========== singleton (供 nerve / chat_bypass 共用) ==========
_default_translator: Optional[Translator] = None


def get_default_translator() -> Optional[Translator]:
    return _default_translator


def set_default_translator(t: Translator) -> None:
    global _default_translator
    _default_translator = t
