# -*- coding: utf-8 -*-
"""[P2-Gap7 / 2026-05-20 23:55] MemoryMutationGateway — 统一 mutation API

Sir 真痛点: 5 个 mutation silo, 互不知, 互相不一致:
  - worker.py:4416 memory_correction → ProfileCard.apply_correction (conf 0.04 不持久化)
  - IntentResolver tool_profile_field_update → ProfileCard (P0 fix 前 100% TypeError)
  - IntentResolver tool_memory_correction_apply → ProfileCard (同上)
  - Reflector propose → review queue → Sir CLI activate
  - Hippocampus.seal_chat_async → SQLite LTM
  - 任何 sir_profile.json 写路径: 根本不存在 (主档案 read-only)

→ Sir 跟 Jarvis 说 30 次 "我搬家了 / 改身高" 漂移, 主档案不动, Jarvis 撒谎.

修法 (Gap 7 设计目标):
  统一 `update_sir_field(field_path, new_value, source, confidence)` API:
    1. routing table 决定写哪个 layer:
       - 'biographic.*' / 'preferences.*' / 'traits.*' → ProfileCard
       - 'concerns.*' / 'sir_concern_*' → ConcernsLedger
       - 'relationships.*' / 'inside_joke.*' → RelationalStateStore
       - 'lifetime_anchor.*' / 'milestone.*' → Milestones
       - 'commitment.*' → CommitmentWatcher
       - 'promise.*' → PromiseLog
    2. 写 receipt 到 memory_pool/mutation_receipts.jsonl (audit trail)
    3. publish SWM 'sir_field_updated' (主脑下轮 prompt 看到)
    4. 返回 WriteReceipt {ok, layer, mutation_id, error}

P2 Minimum Viable Version 范围:
  - 只 cover 3 layer (ProfileCard / Concerns / Milestones) 完整路由
  - 老 caller 不强迫迁移 (后续单独 sprint)
  - CLI dump 看 receipts

Sir 准则 6 binding:
  ✅ 数据 publish SWM, receipt 持久化 jsonl
  ✅ 决策让 LLM 做 (路由是 path-based, 但内容 normalize 让 LLM 自决)
  ✅ 持久化 + CLI 可看 (scripts/mutation_receipts_dump.py)
  ✅ 跟现有 layer 正交 — 不替换, 收敛
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


_RECEIPT_PATH = os.path.join('memory_pool', 'mutation_receipts.jsonl')


@dataclass
class WriteReceipt:
    """单次 mutation 的 receipt — Sir 跟 Jarvis 都能 quote, 防撒谎."""
    mutation_id: str
    ts: float
    iso: str
    field_path: str
    new_value_excerpt: str
    old_value_excerpt: str
    source: str            # 'intent_resolver' / 'worker.memory_correction' / 'reflector' / 'sir_cli'
    confidence: float
    layer_targeted: str    # 'ProfileCard' / 'ConcernsLedger' / 'Milestones' / 'unknown'
    ok: bool
    error: str = ''
    turn_id: str = ''

    def to_dict(self) -> dict:
        return asdict(self)


def _detect_target_layer(field_path: str) -> str:
    """根据 field_path 前缀路由到正确 layer."""
    if not field_path:
        return 'unknown'
    fp = field_path.lower()
    if fp.startswith(('biographic.', 'preferences.', 'traits.', 'profile.',
                       'sir.', 'persona.')):
        return 'ProfileCard'
    if fp.startswith(('concern.', 'concerns.', 'sir_concern_')):
        return 'ConcernsLedger'
    if fp.startswith(('relationships.', 'inside_joke.', 'protocol.',
                       'unfinished.', 'thread.')):
        return 'RelationalStateStore'
    if fp.startswith(('lifetime.', 'lifetime_anchor.', 'milestone.', 'anchor.')):
        return 'Milestones'
    if fp.startswith(('commitment.',)):
        return 'CommitmentWatcher'
    if fp.startswith(('promise.',)):
        return 'PromiseLog'
    return 'unknown'


class MemoryMutationGateway:
    """统一 Sir-aware mutation 入口. 主脑 / IntentResolver / worker / reflector / 
    Sir CLI 全应该走这里, 不直接调底层 layer.

    线程安全. 单例.
    """

    def __init__(self, receipt_path: Optional[str] = None):
        self.receipt_path = receipt_path or _RECEIPT_PATH
        self._lock = threading.Lock()

    def _write_receipt(self, receipt: WriteReceipt) -> None:
        """append 到 jsonl. atomic per line."""
        try:
            os.makedirs(os.path.dirname(self.receipt_path), exist_ok=True)
            with self._lock:
                with open(self.receipt_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(receipt.to_dict(), ensure_ascii=False) + '\n')
            # 🩹 [P3-BUG#7 / 2026-05-20 23:38] rotation 防长期膨胀 (cheap check)
            try:
                from jarvis_jsonl_rotator import maybe_rotate as _mr
                _mr(self.receipt_path, size_mb_cap=10.0)
            except Exception:
                pass
        except Exception:
            pass

    def _publish_swm(self, receipt: WriteReceipt) -> None:
        """publish 'sir_field_updated' SWM event. 主脑下轮 prompt 看 [SIR FIELD UPDATES] block."""
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            bus.publish(
                etype='sir_field_updated',
                description=(
                    f"{receipt.layer_targeted}: {receipt.field_path} = "
                    f"'{receipt.new_value_excerpt}' "
                    f"(was: '{receipt.old_value_excerpt}', "
                    f"src={receipt.source}, ok={receipt.ok})"
                ),
                source='MemoryGateway',
                salience=0.80 if receipt.ok else 0.65,
                metadata={
                    'mutation_id': receipt.mutation_id,
                    'field_path': receipt.field_path,
                    'layer': receipt.layer_targeted,
                    'source': receipt.source,
                    'confidence': receipt.confidence,
                    'new_value': receipt.new_value_excerpt,
                    'old_value': receipt.old_value_excerpt,
                    'ok': receipt.ok,
                    'error': receipt.error,
                    'turn_id': receipt.turn_id,
                },
            )
        except Exception:
            pass

    def update_sir_field(self,
                          field_path: str,
                          new_value: Any,
                          source: str = 'unknown',
                          old_value: Any = '',
                          confidence: float = 0.7,
                          turn_id: str = '',
                          nerve=None) -> WriteReceipt:
        """统一 mutation 入口. 路由到正确 layer + receipt + SWM publish.

        Args:
          field_path: 'biographic.height' / 'concerns.sir_sleep_streak.severity' / ...
          new_value: 新值 (任意类型, 内部转 str excerpt 给 receipt)
          source: caller 标识 ('intent_resolver' / 'worker.memory_correction' / ...)
          old_value: 旧值 (可空, 用于 audit)
          confidence: 0.0-1.0
          turn_id: trace id
          nerve: CentralNerve ref (可空, fallback _GLOBAL_NERVE)

        Returns: WriteReceipt
        """
        mutation_id = f"mut_{uuid.uuid4().hex[:10]}"
        now = time.time()
        layer = _detect_target_layer(field_path)
        new_excerpt = str(new_value)[:100]
        old_excerpt = str(old_value or '')[:100]

        # fallback to global nerve
        if nerve is None:
            try:
                import jarvis_central_nerve as _cn
                nerve = getattr(_cn, '_GLOBAL_NERVE', None)
            except Exception:
                nerve = None

        ok = False
        err = ''
        try:
            if layer == 'ProfileCard':
                profile = getattr(nerve, 'profile_card', None) if nerve else None
                if profile is None:
                    err = 'ProfileCard not available'
                else:
                    # 🆕 [P5-fix32-B / 2026-05-22 22:20] 高置信走真覆写 sir_profile.json
                    # 低置信 / field 不在白名单 → fallback apply_correction (老路, 只 audit).
                    # field_path 转 top-level (取末段 — gateway 用 'biographic.X' / 'profile.X'
                    # 形式调, ProfileCard 只识 top-level field). e.g. 'profile.work_rhythms'
                    # → 'work_rhythms'. apply_correction 老路用全 field_path (含前缀).
                    _is_high_conf_fast_call = (
                        float(confidence) >= 0.8 and
                        (source.startswith('fast_call') or
                         source.startswith('sir_cli') or
                         source.startswith('intent_resolver_revise'))
                    )
                    if _is_high_conf_fast_call and hasattr(profile, 'overwrite_field'):
                        # 抽 top-level field (允许 'profile.X' / 'biographic.X' / 'sir.X' 前缀)
                        _top_field = field_path.split('.')[-1] if '.' in field_path else field_path
                        try:
                            ow_ok, ow_msg, ow_old = profile.overwrite_field(
                                field=_top_field,
                                new_value=new_value,
                                source=source,
                                turn_id=turn_id,
                            )
                            if ow_ok:
                                ok = True
                                if ow_old is not None:
                                    old_excerpt = str(ow_old)[:100]
                            else:
                                # field 不在白名单 / load fail / write fail → fallback 老路 audit
                                err = f'overwrite_field fail: {ow_msg}; falling back to apply_correction'
                                if hasattr(profile, 'apply_correction'):
                                    profile.apply_correction(
                                        source_module=source,
                                        field=field_path,
                                        old_value=old_excerpt,
                                        new_value=new_excerpt,
                                        confidence=float(confidence),
                                    )
                                    ok = True  # audit 成功
                        except Exception as _owe:
                            err = f'overwrite_field exception: {_owe}'
                    elif hasattr(profile, 'apply_correction'):
                        profile.apply_correction(
                            source_module=source,
                            field=field_path,
                            old_value=old_excerpt,
                            new_value=new_excerpt,
                            confidence=float(confidence),
                        )
                        ok = True
                    else:
                        err = 'ProfileCard has no apply_correction / overwrite_field'
            elif layer == 'Milestones':
                # 路由到 milestone_register tool
                try:
                    from jarvis_tool_registry import tool_milestone_register
                    r = tool_milestone_register(
                        text=str(new_value),
                        title=field_path,
                    )
                    ok = bool(r.get('ok'))
                    err = r.get('error', '')
                except Exception as e:
                    err = f'milestone_register fail: {e}'
            elif layer == 'ConcernsLedger':
                ledger = getattr(nerve, 'concerns_ledger', None) if nerve else None
                if ledger is None:
                    err = 'ConcernsLedger not available'
                else:
                    # field_path 形如:
                    #   'concerns.<cid>.<attr>'  → update_concern_field (P5-fix32-G 深度 update)
                    #   'concerns.<cid>'         → record_signal (老路, severity_delta)
                    parts = field_path.split('.')
                    cid = parts[1] if len(parts) >= 2 else ''
                    attr = parts[2] if len(parts) >= 3 else ''
                    if not cid:
                        err = 'invalid concern field_path (need concerns.<cid>[.<attr>])'
                    elif attr and hasattr(ledger, 'update_concern_field'):
                        # 🆕 [P5-fix32-G] 深度 update — 改 what_i_watch / severity / triggers_proactive 等
                        try:
                            uf_ok, uf_msg, uf_old = ledger.update_concern_field(
                                concern_id=cid,
                                field=attr,
                                new_value=new_value,
                                source=source,
                                turn_id=turn_id,
                            )
                            ok = uf_ok
                            if not uf_ok:
                                err = uf_msg
                            elif uf_old is not None:
                                old_excerpt = str(uf_old)[:100]
                        except Exception as _ue:
                            err = f'update_concern_field exception: {_ue}'
                    elif hasattr(ledger, 'record_signal'):
                        # 老路 (没 attr / ledger 不支持新 method): record_signal
                        ok = ledger.record_signal(
                            cid, str(new_value)[:200],
                            severity_delta=float(confidence) - 0.5,
                            source_turn_id=turn_id,
                        )
                        if not ok:
                            err = f'concern {cid} not found'
                    else:
                        err = 'ConcernsLedger has no record_signal / update_concern_field'
            # 🆕 [P5-fix32-C / 2026-05-22 22:25] PromiseLog routing
            # field_path 形如:
            #   'promise.fulfill.<id_or_keyword>'  → mark_fulfilled
            #   'promise.cancel.<id_or_keyword>'   → mark_cancelled
            elif layer == 'PromiseLog':
                try:
                    from jarvis_promise_log import get_default_log
                    plog = get_default_log()
                except Exception as _pe:
                    err = f'PromiseLog import fail: {_pe}'
                    plog = None
                if plog is not None:
                    parts = field_path.split('.', 2)
                    op = parts[1] if len(parts) >= 2 else ''
                    key = parts[2] if len(parts) >= 3 else str(new_value)
                    # Resolve key → promise_id (id 精确匹配 / keyword 模糊找)
                    target_pid = None
                    try:
                        # 1) 精确 id
                        if key in (plog.promises or {}):
                            target_pid = key
                        else:
                            # 2) keyword fuzzy on description
                            kl = key.lower()
                            for p in plog.list_pending():
                                if kl and kl in (p.description or '').lower():
                                    target_pid = p.id
                                    break
                    except Exception:
                        target_pid = None
                    if not target_pid:
                        err = f"no pending promise matching '{key}'"
                    elif op == 'fulfill':
                        try:
                            ok = plog.mark_fulfilled(target_pid,
                                                      evidence_kind='fast_call_mutation',
                                                      evidence_what=str(new_value)[:100])
                            if not ok:
                                err = f'mark_fulfilled fail (already settled?)'
                        except Exception as _fe:
                            err = f'mark_fulfilled exception: {_fe}'
                    elif op == 'cancel':
                        try:
                            ok = plog.mark_cancelled(target_pid, reason=str(new_value)[:100])
                            if not ok:
                                err = f'mark_cancelled fail (already settled?)'
                        except Exception as _ce:
                            err = f'mark_cancelled exception: {_ce}'
                    else:
                        err = f'unknown promise op: {op} (need fulfill/cancel)'
            # 🆕 [P5-fix32-C / 2026-05-22 22:25] CommitmentWatcher routing
            # field_path 形如:
            #   'commitment.cancel.<keyword>'  → cancel_by_keyword
            #   'commitment.update.<keyword>'  → update_by_keyword (new_value = new desc/deadline JSON)
            elif layer == 'CommitmentWatcher':
                cw = getattr(nerve, 'commitment_watcher', None) if nerve else None
                if cw is None:
                    err = 'CommitmentWatcher not available'
                else:
                    parts = field_path.split('.', 2)
                    op = parts[1] if len(parts) >= 2 else ''
                    keyword = parts[2] if len(parts) >= 3 else str(new_value)
                    if op == 'cancel':
                        try:
                            n_removed = cw.cancel_by_keyword(keyword)
                            ok = n_removed > 0
                            if not ok:
                                err = f'no commitment matching "{keyword}"'
                            else:
                                new_excerpt = f'cancelled {n_removed} commitment(s)'
                        except Exception as _cce:
                            err = f'cancel_by_keyword exception: {_cce}'
                    elif op == 'update':
                        # new_value 解读: dict {desc, deadline_str} 或 str (作为 new desc)
                        try:
                            if isinstance(new_value, dict):
                                _new_desc = new_value.get('description')
                                _new_dl = new_value.get('deadline_str')
                            else:
                                _new_desc = str(new_value)
                                _new_dl = None
                            n_updated = cw.update_by_keyword(
                                keyword,
                                new_description=_new_desc,
                                new_deadline_str=_new_dl,
                            )
                            ok = n_updated > 0
                            if not ok:
                                err = f'no commitment matching "{keyword}"'
                        except Exception as _cue:
                            err = f'update_by_keyword exception: {_cue}'
                    else:
                        err = f'unknown commitment op: {op} (need cancel/update)'
            # 🆕 [P5-fix32-C / 2026-05-22 22:25] RelationalStateStore routing
            # field_path 形如:
            #   'relationships.archive_joke.<jid>'   → archive_inside_joke
            #   'protocol.archive.<pid>'              → archive_protocol
            #   'unfinished.done.<uid>'               → mark_unfinished_done
            #   'thread.archive.<tid>'                → archive_thread
            elif layer == 'RelationalStateStore':
                rs = getattr(nerve, 'relational_state', None) if nerve else None
                if rs is None:
                    err = 'RelationalStateStore not available'
                else:
                    parts = field_path.split('.', 2)
                    kind = parts[0]  # relationships / protocol / unfinished / thread
                    op = parts[1] if len(parts) >= 2 else ''
                    item_id = parts[2] if len(parts) >= 3 else str(new_value)
                    try:
                        if kind in ('relationships', 'inside_joke') and op == 'archive':
                            ok = rs.archive_inside_joke(item_id)
                            if not ok:
                                err = f'inside_joke {item_id} not found'
                        elif kind == 'protocol' and op == 'archive':
                            ok = rs.archive_protocol(item_id)
                            if not ok:
                                err = f'protocol {item_id} not found'
                        elif kind == 'unfinished' and op == 'done':
                            ok = rs.mark_unfinished_done(item_id)
                            if not ok:
                                err = f'unfinished {item_id} not found'
                        elif kind == 'thread' and op == 'archive':
                            ok = rs.archive_thread(item_id)
                            if not ok:
                                err = f'thread {item_id} not found'
                        else:
                            err = (f'unknown relational op: kind={kind} op={op} '
                                      f'(need relationships.archive/protocol.archive/'
                                      f'unfinished.done/thread.archive)')
                    except Exception as _re:
                        err = f'relational mutation exception: {_re}'
            else:
                err = f'no router for layer={layer} (field={field_path})'
        except Exception as e:
            err = f'mutation exception: {e}'

        receipt = WriteReceipt(
            mutation_id=mutation_id,
            ts=now,
            iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
            field_path=field_path,
            new_value_excerpt=new_excerpt,
            old_value_excerpt=old_excerpt,
            source=source,
            confidence=float(confidence),
            layer_targeted=layer,
            ok=ok,
            error=err[:200],
            turn_id=turn_id,
        )
        self._write_receipt(receipt)
        self._publish_swm(receipt)
        return receipt

    def recent_receipts(self, max_n: int = 20,
                         within_seconds: Optional[float] = None) -> list:
        """读最近 N 条 receipts (jsonl tail)."""
        if not os.path.exists(self.receipt_path):
            return []
        try:
            with open(self.receipt_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception:
            return []
        out = []
        cutoff = time.time() - within_seconds if within_seconds else 0
        for ln in lines[-max_n * 2:]:  # tail buffer
            try:
                d = json.loads(ln.strip())
                if cutoff and float(d.get('ts', 0)) < cutoff:
                    continue
                out.append(d)
            except Exception:
                continue
        return out[-max_n:]

    def stats(self) -> dict:
        recents = self.recent_receipts(max_n=100)
        layers = {}
        sources = {}
        n_ok = 0
        for r in recents:
            layers[r.get('layer_targeted', '?')] = layers.get(r.get('layer_targeted', '?'), 0) + 1
            sources[r.get('source', '?')] = sources.get(r.get('source', '?'), 0) + 1
            if r.get('ok'):
                n_ok += 1
        return {
            'total_recent': len(recents),
            'ok_count': n_ok,
            'fail_count': len(recents) - n_ok,
            'by_layer': layers,
            'by_source': sources,
        }


# ============================================================
# 单例
# ============================================================

_DEFAULT_GATEWAY: Optional[MemoryMutationGateway] = None
_LOCK = threading.Lock()


def get_default_gateway() -> MemoryMutationGateway:
    global _DEFAULT_GATEWAY
    with _LOCK:
        if _DEFAULT_GATEWAY is None:
            _DEFAULT_GATEWAY = MemoryMutationGateway()
        return _DEFAULT_GATEWAY


def reset_default_gateway_for_test() -> None:
    global _DEFAULT_GATEWAY
    with _LOCK:
        _DEFAULT_GATEWAY = None


def update_sir_field(field_path: str, new_value: Any,
                      source: str = 'unknown',
                      old_value: Any = '',
                      confidence: float = 0.7,
                      turn_id: str = '',
                      nerve=None) -> WriteReceipt:
    """简化入口."""
    return get_default_gateway().update_sir_field(
        field_path=field_path,
        new_value=new_value,
        source=source,
        old_value=old_value,
        confidence=confidence,
        turn_id=turn_id,
        nerve=nerve,
    )
