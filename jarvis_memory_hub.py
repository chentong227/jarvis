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
    # 🆕 [P5-fix34 / 2026-05-23] 主脑 model 标签 — A/B 跑模型时按 model 分组 audit.
    # 空字符串 = 不知道 / 调用方没传. fast_call_mutation 路径会传当前 chat_bypass.main_brain_model.
    model: str = ''

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
                          nerve=None,
                          model: str = '') -> WriteReceipt:
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
                        # 🆕 [P5-fix81 / 2026-05-23 22:05] BUG-X: 嵌套 path 不丢中间层
                        # 老 split('.')[-1] 把 'profile.preferences.cup_ml' → 'cup_ml'
                        # 丢了 'preferences' 中间层 → 不在 allowed → fallback audit only
                        # → sir_profile.json 不真改. Sir 21:59 真测痛点根因.
                        # 修法: 剥前缀 'profile.' / 'biographic.' / 'sir.' 后保留剩下 dot
                        # path. e.g. 'profile.unit_preferences.cup_ml' → 'unit_preferences.cup_ml'.
                        # overwrite_field 现支持嵌套写 (fix81).
                        _path = field_path
                        for _pfx in ('profile.', 'biographic.', 'sir.'):
                            if _path.startswith(_pfx):
                                _path = _path[len(_pfx):]
                                break
                        try:
                            ow_ok, ow_msg, ow_old = profile.overwrite_field(
                                field=_path,
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
            # 🆕 [P5-fix32-C+I / 2026-05-22] RelationalStateStore routing
            # field_path 形如:
            #   'relationships.archive_joke.<jid>'   → archive_inside_joke
            #   'protocol.archive.<pid>'              → archive_protocol
            #   'unfinished.done.<uid>'               → mark_unfinished_done
            #   'thread.archive.<tid>'                → archive_thread
            #   🆕 [P5-fix32-I / Phase 2.2] depth update:
            #   '<kind>.update.<item_id>.<field>'     → update_field
            #   e.g. 'inside_joke.update.j1.phrase'
            elif layer == 'RelationalStateStore':
                rs = getattr(nerve, 'relational_state', None) if nerve else None
                if rs is None:
                    err = 'RelationalStateStore not available'
                else:
                    parts = field_path.split('.', 3)  # 允许 4 段
                    kind = parts[0]  # relationships / protocol / unfinished / thread / inside_joke
                    op = parts[1] if len(parts) >= 2 else ''
                    item_id = parts[2] if len(parts) >= 3 else str(new_value)
                    sub_field = parts[3] if len(parts) >= 4 else ''
                    try:
                        # 🆕 [P5-fix32-I] update.<item_id>.<field> 深度 update
                        if op == 'update' and sub_field and hasattr(rs, 'update_field'):
                            # 'relationships' 是 alias for 'inside_joke'
                            kind_norm = ('inside_joke' if kind == 'relationships'
                                            else kind)
                            uf_ok, uf_msg, uf_old = rs.update_field(
                                kind=kind_norm,
                                item_id=item_id,
                                field=sub_field,
                                new_value=new_value,
                                source=source,
                                turn_id=turn_id,
                            )
                            ok = uf_ok
                            if not uf_ok:
                                err = uf_msg
                            elif uf_old is not None:
                                old_excerpt = str(uf_old)[:100]
                        elif kind in ('relationships', 'inside_joke') and op == 'archive':
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
                                      f'unfinished.done/thread.archive/'
                                      f'<kind>.update.<id>.<field>)')
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
            model=model or '',
        )
        self._write_receipt(receipt)
        self._publish_swm(receipt)

        # 🆕 [P5-fix82-X / 2026-05-23 22:22] Sir 真意 "教一次, 多处同步"
        # 治本 Sir 22:06 真测痛点: Sir 教 "今天血压咨询完成" → MemoryGateway 写
        # ProfileCard.preferences.user_correction (audit), 但**Commitments table
        # 老 id=20 description '明天血压咨询' deadline=今天 22:00 没改** → 22:00
        # commitment_check fire → 主脑读老 description 又重复. 链路断在: 改 1 处
        # source 没联动其他.
        # 修法: ok 且 new_value 含完成语义 (vocab persisted) → 抽 keyword(s) →
        # CommitmentWatcher.cancel_by_keyword (max_age 24h). 多处同步真治本.
        if ok:
            try:
                self._maybe_cascade_completion(
                    field_path, new_value, source, turn_id, nerve)
            except Exception:
                pass

        return receipt

    def _maybe_cascade_completion(self, field_path, new_value, source, turn_id, nerve):
        """🆕 [fix82-X] Sir 教 "X 完成" → 联动 Commitments cancel.

        判定: new_value 含完成语义 (load vocab from completion_event_vocab.json,
        seed defaults if missing). 抽 noun keyword → cw.cancel_by_keyword.

        准则 6 三维耦合:
        - 数据 publish SWM: publish 'completion_cascaded' event (主脑下轮 prompt 看)
        - 决策让 LLM 做: 仅 cancel active commitments (不删 Hippocampus, 那是 LLM 抽)
        - 配置持久化 + CLI: vocab 在 memory_pool/completion_event_vocab.json (准则 6)
        """
        nv_str = str(new_value or '').strip()
        if not nv_str or len(nv_str) < 4:
            return

        # Load completion vocab (准则 6 持久化)
        vocab = self._load_completion_vocab()
        completion_kws = vocab.get('completion_keywords') or []
        noun_extract_kws = vocab.get('noun_extract_keywords') or []

        # 判定 new_value 含完成语义
        nv_low = nv_str.lower()
        has_completion = False
        for ck in completion_kws:
            if ck.lower() in nv_low:
                has_completion = True
                break
        if not has_completion:
            return

        # 抽 noun keywords (从 vocab 找 noun + 邻近字符)
        kws_found = set()
        for nk in noun_extract_kws:
            if nk.lower() in nv_low:
                kws_found.add(nk)
        if not kws_found:
            return

        # 调 CommitmentWatcher.cancel_by_keyword
        cw = getattr(nerve, 'commitment_watcher', None) if nerve else None
        if cw is None or not hasattr(cw, 'cancel_by_keyword'):
            return
        cancelled_total = 0
        cancelled_details = []
        for kw in list(kws_found)[:5]:  # cap 5 keywords
            try:
                n = cw.cancel_by_keyword(kw, max_age_seconds=86400.0)  # 24h
                if n > 0:
                    cancelled_total += n
                    cancelled_details.append(f"'{kw}'×{n}")
            except Exception:
                continue

        # 🆕 [fix82-X cascade step 2] 写 TaskMemories 'Completed: X' (Hippocampus)
        # 让 list_recent_completed_events 能 hit → 主脑下轮 prompt [RECENT COMPLETED]
        # 看到 evidence. 即便没 cancel commitment 也写 (Sir 可能没用具体 cmd 注册).
        try:
            hippo_ce = getattr(nerve, 'hippocampus', None) if nerve else None
            if hippo_ce is not None and hasattr(hippo_ce, 'add_completed_event'):
                hippo_ce.add_completed_event(
                    summary=nv_str[:200],
                    keywords=list(kws_found),
                    source=f'cascade_completion:{source}',
                    turn_id=turn_id,
                )
        except Exception:
            pass

        if cancelled_total > 0:
            # bg_log + publish SWM 'completion_cascaded'
            try:
                from jarvis_utils import bg_log as _x_bg
                _x_bg(
                    f"🔗 [fix82-X Completion Cascade] "
                    f"'{nv_str[:60]}' → cancelled {cancelled_total} commitment(s): "
                    f"{', '.join(cancelled_details)}"
                )
            except Exception:
                pass
            try:
                from jarvis_utils import get_event_bus as _x_geb
                _bus = _x_geb()
                if _bus is not None:
                    _bus.publish(
                        etype='completion_cascaded',
                        description=(
                            f"Sir 教完成 '{nv_str[:50]}' → 联动 cancel "
                            f"{cancelled_total} commitment(s)"
                        ),
                        source='MemoryGateway.cascade_completion',
                        salience=0.75,
                        metadata={
                            'new_value': nv_str[:200],
                            'keywords': list(kws_found),
                            'cancelled_n': cancelled_total,
                            'turn_id': turn_id,
                            'mutation_source': source,
                        },
                    )
            except Exception:
                pass

    def _load_completion_vocab(self):
        """🆕 [fix82-X] Load completion vocab. Seed defaults if missing.

        准则 6: 持久化到 memory_pool/completion_event_vocab.json, CLI 可改.
        """
        vocab_path = os.path.join('memory_pool', 'completion_event_vocab.json')
        if os.path.exists(vocab_path):
            try:
                with open(vocab_path, 'r', encoding='utf-8') as f:
                    return json.load(f) or {}
            except Exception:
                pass
        # Seed defaults
        seed = {
            '_meta': {
                'description': 'fix82-X completion event vocab — Sir 教 "X 已完成 / 今天去过了 / done" 触发 Commitments cancel',
                'created_at': time.time(),
                'created_by': 'fix82-X seed',
            },
            'completion_keywords': [
                # 中文
                '已完成', '完成了', '去过了', '已去', '做完了', '搞定',
                '弄完', '已经做', '已经去', '已经完成', '今天去过',
                'completed', 'done', 'finished', 'taken care of',
                'already did', 'already done', 'already went',
            ],
            'noun_extract_keywords': [
                # 常见 noun (Sir 实测 / Hippocampus user_intent 抽过的)
                '血压', '血压咨询', '咨询', '体检', '吃药', '复诊', '挂号',
                '面试', 'KTV', '聚会', '理发', '驾照', '科目一', '科目二',
                '快递', '取件', '健身', '游泳', '跑步', '锻炼',
                'blood pressure', 'consultation', 'appointment', 'checkup',
                'medication', 'interview', 'haircut',
            ],
        }
        try:
            os.makedirs(os.path.dirname(vocab_path), exist_ok=True)
            tmp = vocab_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(seed, f, ensure_ascii=False, indent=2)
            os.replace(tmp, vocab_path)
        except Exception:
            pass
        return seed

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
# [Reshape M2.A / 2026-05-24] 6 write_* 方法 — 按 6 source of truth 分写
# ============================================================
# 设计: 老 update_sir_field 是 routing-by-field_path 单入口 (内部识 layer);
# 新 6 write_* 是 caller 显式选 layer (更清晰 + 各自 contract). 老接口保留,
# 新接口推荐. 内部都走同一 _do_mutation, 保证一致性.
#
# 6 source of truth (GRAND_ARCHITECTURE_RESHAPE §3 设计):
#   1. write_identity   → ProfileCard (sir_profile.json)
#   2. write_event      → Hippocampus (long_term_memory.db)
#   3. write_commitment → CommitmentWatcher (commitments.db)
#   4. write_concern    → ConcernsLedger (concerns.json)
#   5. write_state      → status_ledger / state files
#   6. write_relation   → RelationalStateStore (relational_state.json)

def _add_write_methods(_cls):
    """attach 6 write_* helpers to MemoryMutationGateway. 不破老 update_sir_field."""

    def write_identity(self, field_path: str, value, source: str = 'unknown',
                        confidence: float = 0.7, old_value='', turn_id: str = '',
                        nerve=None) -> WriteReceipt:
        """写 ProfileCard (sir_profile.json). field_path 自动加 'profile.' 前缀如缺失."""
        if not field_path.startswith(('profile.', 'biographic.', 'sir.', 'preferences.', 'traits.')):
            field_path = f'profile.{field_path}'
        return self.update_sir_field(field_path=field_path, new_value=value,
                                       source=source, old_value=old_value,
                                       confidence=confidence, turn_id=turn_id, nerve=nerve)

    def write_event(self, summary: str, kind: str = 'event', entities=None,
                     embedding=None, source: str = 'unknown', turn_id: str = '',
                     nerve=None) -> WriteReceipt:
        """写 Hippocampus event. 直接调 hippocampus.add_memory + receipt."""
        mutation_id = f"mut_{uuid.uuid4().hex[:10]}"
        if nerve is None:
            try:
                import jarvis_central_nerve as _cn
                nerve = getattr(_cn, '_GLOBAL_NERVE', None)
            except Exception:
                nerve = None
        ok, err = False, ''
        try:
            hc = getattr(nerve, 'hippocampus', None) if nerve else None
            if hc is None:
                err = 'Hippocampus not available'
            elif hasattr(hc, 'add_memory'):
                # add_memory 签名: (intent, summary, entities, ...) — 现有
                hc.add_memory(intent=kind, summary=summary,
                              entities=entities or [], gemini_key='')
                ok = True
            else:
                err = 'hippocampus.add_memory not available'
        except Exception as e:
            err = f'write_event exception: {e}'
        _now = time.time()
        receipt = WriteReceipt(
            mutation_id=mutation_id, ts=_now,
            iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(_now)),
            field_path=f'hippocampus.{kind}', new_value_excerpt=summary[:100],
            old_value_excerpt='', source=source, confidence=1.0,
            layer_targeted='Hippocampus', ok=ok, error=err, turn_id=turn_id,
        )
        self._write_receipt(receipt)
        self._publish_swm(receipt)
        return receipt

    def write_commitment(self, description: str, kind: str = 'commitment',
                          who_promised: str = 'jarvis', deadline=None,
                          source: str = 'unknown', turn_id: str = '',
                          nerve=None, **kwargs) -> WriteReceipt:
        """写 CommitmentWatcher. 直接调 commitment_watcher.register_commitment."""
        mutation_id = f"mut_{uuid.uuid4().hex[:10]}"
        if nerve is None:
            try:
                import jarvis_central_nerve as _cn
                nerve = getattr(_cn, '_GLOBAL_NERVE', None)
            except Exception:
                nerve = None
        ok, err, new_excerpt = False, '', description[:100]
        try:
            cw = getattr(nerve, 'commitment_watcher', None) if nerve else None
            if cw is None:
                err = 'CommitmentWatcher not available'
            elif hasattr(cw, 'register_commitment'):
                cid = cw.register_commitment(
                    description=description, kind=kind,
                    who_promised=who_promised, deadline=deadline,
                    source=source, turn_id=turn_id, **kwargs)
                ok = bool(cid)
                if cid:
                    new_excerpt = f'cid={cid}: {description[:80]}'
            else:
                err = 'commitment_watcher.register_commitment not available'
        except Exception as e:
            err = f'write_commitment exception: {e}'
        _now = time.time()
        receipt = WriteReceipt(
            mutation_id=mutation_id, ts=_now,
            iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(_now)),
            field_path=f'commitment.{kind}', new_value_excerpt=new_excerpt,
            old_value_excerpt='', source=source, confidence=1.0,
            layer_targeted='CommitmentWatcher', ok=ok, error=err, turn_id=turn_id,
        )
        self._write_receipt(receipt)
        self._publish_swm(receipt)
        return receipt

    def write_concern(self, concern_id: str, field: str, new_value,
                       source: str = 'unknown', old_value='', confidence: float = 0.7,
                       turn_id: str = '', nerve=None) -> WriteReceipt:
        """写 ConcernsLedger. 委托给 update_sir_field with 'concerns.<cid>.<field>' path."""
        return self.update_sir_field(
            field_path=f'concerns.{concern_id}.{field}',
            new_value=new_value, source=source, old_value=old_value,
            confidence=confidence, turn_id=turn_id, nerve=nerve)

    def write_state(self, field_path: str, value, source: str = 'unknown',
                     old_value='', confidence: float = 0.7, turn_id: str = '',
                     nerve=None) -> WriteReceipt:
        """写 status_ledger / state files. 占位接口 - 现 status_ledger 没统一 mutate API,
        暂走 update_sir_field (routing 命中 'state.*' → unknown layer → audit only).
        M2+ 跟 status_ledger 重构一起做真实现."""
        if not field_path.startswith('state.'):
            field_path = f'state.{field_path}'
        return self.update_sir_field(field_path=field_path, new_value=value,
                                       source=source, old_value=old_value,
                                       confidence=confidence, turn_id=turn_id, nerve=nerve)

    def write_relation(self, kind: str, item_id: str, field: str, new_value,
                        source: str = 'unknown', old_value='', confidence: float = 0.7,
                        turn_id: str = '', nerve=None) -> WriteReceipt:
        """写 RelationalStateStore. 委托给 update_sir_field with 路径式 'inside_joke.update.<id>.<field>'."""
        # 沿用现有 routing 表 (在 _detect_target_layer 中):
        # 'inside_joke.update.<id>.phrase' → RelationalStateStore.update_field
        return self.update_sir_field(
            field_path=f'{kind}.update.{item_id}.{field}',
            new_value=new_value, source=source, old_value=old_value,
            confidence=confidence, turn_id=turn_id, nerve=nerve)

    _cls.write_identity = write_identity
    _cls.write_event = write_event
    _cls.write_commitment = write_commitment
    _cls.write_concern = write_concern
    _cls.write_state = write_state
    _cls.write_relation = write_relation
    return _cls


_add_write_methods(MemoryMutationGateway)


# ============================================================
# [Reshape M2.A / 2026-05-24] query + to_prompt_block — 搬运自
# jarvis_memory_core.UnifiedMemoryGateway. 把 READ 入口收回 Hub 里 (R+W 单入口).
# 老 UnifiedMemoryGateway 仍存在 (向后兼容), M2.C 阶段标 deprecated.
# ============================================================

_SOURCE_WEIGHTS = {
    'stm': 0.30, 'ltm': 0.25, 'profile': 0.15,
    'ledger': 0.15, 'causal': 0.15,
}


def _add_query_methods(_cls):
    """attach READ helpers (query / to_prompt_block) to Hub."""

    def _bind_nerve(self, nerve=None):
        if nerve is not None:
            return nerve
        try:
            import jarvis_central_nerve as _cn
            return getattr(_cn, '_GLOBAL_NERVE', None)
        except Exception:
            return None

    def _fuzzy_match(self, query: str, text: str) -> float:
        if not query or not text:
            return 0.3
        q = set(query.lower().split())
        t = set(text.lower().split())
        if not q:
            return 0.3
        return min(1.0, len(q & t) / len(q) * 1.5)

    def query(self, query_text: str, top_k: int = 5, nerve=None) -> list:
        """跨 source 模糊查 (STM + LTM + Profile + Ledger + CausalChain). 返 fragment list."""
        nerve = self._bind_nerve(nerve)
        if nerve is None:
            return []
        # lazy import 防 circular
        try:
            from jarvis_memory_core import MemoryFragment
        except Exception:
            return []
        fragments = []
        now = time.time()

        stm = getattr(nerve, 'short_term_memory', [])
        if stm:
            for m in stm[-20:]:
                content = f"[{m.get('time', '')}] User: {m.get('user', '')} | Jarvis: {m.get('jarvis', '')}"
                fragments.append(MemoryFragment(
                    source='stm', content=content,
                    relevance_score=self._fuzzy_match(query_text, content),
                    freshness_hours=0.01, source_weight=_SOURCE_WEIGHTS['stm']))

        try:
            hc = getattr(nerve, 'hippocampus', None)
            gk = getattr(nerve, 'gemini_key', '')
            if hc is not None and hasattr(hc, 'search_memory'):
                ltm_results = hc.search_memory(gk, query_text, top_k=5)
                for r in ltm_results or []:
                    age_hours = (now - r['timestamp']) / 3600
                    fragments.append(MemoryFragment(
                        source='ltm',
                        content=f"[{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['timestamp']))}] {r['intent']} -> {r['summary']}",
                        timestamp=r['timestamp'],
                        relevance_score=r.get('similarity', 0.5),
                        freshness_hours=age_hours,
                        source_weight=_SOURCE_WEIGHTS['ltm']))
        except Exception:
            pass

        try:
            pc = getattr(nerve, 'profile_card', None)
            if pc is not None and hasattr(pc, 'snapshot'):
                profile = pc.snapshot() or {}
                if profile:
                    profile_text = json.dumps(profile, ensure_ascii=False)[:500]
                    fragments.append(MemoryFragment(
                        source='profile', content=profile_text,
                        relevance_score=self._fuzzy_match(query_text, profile_text),
                        freshness_hours=0.5, source_weight=_SOURCE_WEIGHTS['profile']))
        except Exception:
            pass

        try:
            sl = getattr(nerve, 'status_ledger', None)
            if sl is not None and hasattr(sl, 'get_recent_daily_summaries'):
                ledger_text = sl.get_recent_daily_summaries(days=2)
                if ledger_text:
                    fragments.append(MemoryFragment(
                        source='ledger', content=ledger_text[:500],
                        relevance_score=self._fuzzy_match(query_text, ledger_text),
                        freshness_hours=12, source_weight=_SOURCE_WEIGHTS['ledger']))
        except Exception:
            pass

        try:
            cc = getattr(nerve, 'causal_chain', None)
            if cc is not None and hasattr(cc, 'get_llm_enhanced_summary'):
                causal_text = cc.get_llm_enhanced_summary()
                if causal_text:
                    fragments.append(MemoryFragment(
                        source='causal', content=causal_text[:300],
                        relevance_score=self._fuzzy_match(query_text, causal_text),
                        freshness_hours=1, source_weight=_SOURCE_WEIGHTS['causal']))
        except Exception:
            pass

        # 时间衰减 + 排序 + dedup
        for f in fragments:
            freshness_bonus = max(0, 1.0 - f.freshness_hours / 168)
            f.relevance_score = f.relevance_score * 0.6 + freshness_bonus * 0.4
        fragments.sort(key=lambda x: x.relevance_score * x.source_weight, reverse=True)
        seen, out = set(), []
        for f in fragments:
            key = f.content[:80]
            if key not in seen:
                seen.add(key)
                out.append(f)
        return out[:top_k]

    def to_prompt_block(self, query_text: str, top_k: int = 5, nerve=None) -> str:
        """render 跨 source recall block 给主脑 prompt."""
        results = self.query(query_text, top_k, nerve=nerve)
        if not results:
            return ""
        lines = ["\n[UNIFIED MEMORY - Cross-source recall]:"]
        for r in results:
            lines.append(f"[{r.source.upper()}] {r.content[:200]}")
        return '\n'.join(lines)

    _cls._bind_nerve = _bind_nerve
    _cls._fuzzy_match = _fuzzy_match
    _cls.query = query
    _cls.to_prompt_block = to_prompt_block
    return _cls


_add_query_methods(MemoryMutationGateway)


# ============================================================
# [Reshape M2.A / 2026-05-24] MemoryHub 命名别名 — 新代码用 Hub, 老代码 Gateway 仍 work
# Q3 决议: MemoryMutationGateway 改名 MemoryHub. M2.C 阶段 git mv file, 现先双名 alias.
# ============================================================

MemoryHub = MemoryMutationGateway


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


# [Reshape M2.A] 新名 alias
get_default_hub = get_default_gateway
reset_default_hub_for_test = reset_default_gateway_for_test


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
