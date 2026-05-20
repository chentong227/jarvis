# -*- coding: utf-8 -*-
"""[β.5.41 / 2026-05-20] ActionableItems — 统一抽象 Sir 可操作项 (21 类).

Sir 16:43 真理:
  1. 所有 Sir 拍板的事全面出现在面板
  2. 交互设计要清晰明了
  3. 交互后状态要能实时看到
  4. 让我知道操作会影响什么
  5. 重构这部分能力和面板的 UI 设计

本模块: backend 抽象, 统一 21 个 vocab/state 源到 ActionableItem schema.

详: docs/JARVIS_DASHBOARD_REBUILD_AUDIT.md
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


ROOT = os.path.dirname(os.path.abspath(__file__))
MEM = os.path.join(ROOT, 'memory_pool')
CFG = os.path.join(ROOT, 'jarvis_config')


# ============================================================
# Schema
# ============================================================

@dataclass
class ActionableItem:
    """统一 schema 给 dashboard. 21 类源都映射到这."""

    id: str
    category: str                  # 'concern' / 'inside_joke' / 'thread' / 'screen_tease' / ...
    subcategory: str = ''          # 分组 (sidebar 用): 'review' / 'active' / 'archived' / 'system'
    state: str = 'active'          # 'review' / 'active' / 'archived' / 'rejected'
    preview: str = ''              # 显示文本 (1 行 ≤ 80 char)
    fields: Dict = field(default_factory=dict)  # 可修字段 (Sir 修正面板用)
    impact_if_modified: str = ''   # "改影响 X" tooltip
    impact_if_deleted: str = ''    # "删影响 X" tooltip
    source_file: str = ''          # 'memory_pool/concerns.json'
    source_path: str = ''          # JSON path 在文件中位置 (concerns.<id> / inside_jokes.<id>)
    created_at: float = 0.0
    last_used_at: float = 0.0
    use_count: int = 0
    auto_proposed: bool = False    # L7 reflector 提的还是 Sir 自加
    proposed_by: str = ''          # 'WeeklyReflector' / 'InsideJokeReflector' / ...
    sir_acked: bool = False        # Sir 看过没

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# 工具
# ============================================================

def _safe_read_json(path: str, default=None):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def _safe_read_jsonl(path: str) -> list:
    out = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass
    return out


def _truncate(s: str, n: int = 80) -> str:
    s = str(s or '').strip()
    return s[:n] if len(s) <= n else s[:n - 1] + '…'


def _ack_state_path() -> str:
    return os.path.join(MEM, 'sir_acked_state.json')


def _load_ack_state() -> dict:
    return _safe_read_json(_ack_state_path(), {})


def _is_acked(item_id: str, ack_state: dict = None) -> bool:
    if ack_state is None:
        ack_state = _load_ack_state()
    return item_id in (ack_state.get('item_acks') or {})


# ============================================================
# Category-specific extractors
# Each fn returns list of ActionableItem from one source
# ============================================================

def _extract_concerns(ack_state: dict) -> List[ActionableItem]:
    """Cat 1 + 12: concerns review + active."""
    items = []
    data = _safe_read_json(os.path.join(MEM, 'concerns.json'), {})
    for cid, c in (data.get('concerns') or {}).items():
        if not isinstance(c, dict):
            continue
        st = c.get('state', 'active')
        if st not in ('review', 'active'):
            continue
        items.append(ActionableItem(
            id=cid,
            category='concern',
            subcategory=st,
            state=st,
            preview=_truncate(f"{cid}: {c.get('what_i_watch', '')}", 100),
            fields={
                'what_i_watch': c.get('what_i_watch', ''),
                'why_i_care': c.get('why_i_care', ''),
                'severity': c.get('severity', 0.0),
                'optimal_timing': c.get('optimal_timing', ''),
                'notes_for_self': c.get('notes_for_self', ''),
            },
            impact_if_modified='Jarvis 下次 SOUL inject 看到的新文本/severity 影响主脑 nudge 倾向',
            impact_if_deleted='Jarvis 不再 watch 这个 concern, 不再 nudge',
            source_file='memory_pool/concerns.json',
            source_path=f'concerns.{cid}',
            created_at=float(c.get('created_at', 0) or 0),
            last_used_at=float(c.get('last_aligned_at', 0) or 0),
            use_count=int(c.get('aligned_count', 0) or 0) + int(c.get('missed_count', 0) or 0),
            auto_proposed=c.get('source', '') in ('weekly_reflector', 'auto_detected', 'L7'),
            proposed_by=c.get('source_marker', ''),
            sir_acked=_is_acked(cid, ack_state),
        ))
    return items


def _extract_relational(ack_state: dict) -> List[ActionableItem]:
    """Cat 2-4 + 13-16: inside_jokes / threads / protocols / unfinished."""
    items = []
    data = _safe_read_json(os.path.join(MEM, 'relational_state.json'), {})
    # inside_jokes
    for jid, j in (data.get('inside_jokes') or {}).items():
        if not isinstance(j, dict):
            continue
        st = j.get('state', 'active')
        if st not in ('review', 'active'):
            continue
        items.append(ActionableItem(
            id=jid,
            category='inside_joke',
            subcategory=st,
            state=st,
            preview=_truncate(f'"{j.get("phrase", "")}" ({j.get("tone", "")})', 100),
            fields={
                'phrase': j.get('phrase', ''),
                'birth_context': j.get('birth_context', ''),
                'tone': j.get('tone', ''),
            },
            impact_if_modified='Jarvis 下次引用此梗用新文本/tone',
            impact_if_deleted='Jarvis 永不再引用 (可恢复)',
            source_file='memory_pool/relational_state.json',
            source_path=f'inside_jokes.{jid}',
            created_at=float(j.get('created_at', 0) or 0),
            last_used_at=float(j.get('last_used', 0) or 0),
            use_count=int(j.get('use_count', 0) or 0),
            auto_proposed=j.get('source', '') == 'auto_detected',
            proposed_by=j.get('source_marker', ''),
            sir_acked=_is_acked(jid, ack_state),
        ))
    # shared_history_threads
    for tid, t in (data.get('shared_history_threads') or {}).items():
        if not isinstance(t, dict):
            continue
        st = t.get('state', 'active')
        if st not in ('review', 'active'):
            continue
        hl = t.get('highlights', []) or []
        items.append(ActionableItem(
            id=tid,
            category='thread',
            subcategory=st,
            state=st,
            preview=_truncate(f'{t.get("title", "?")} ({len(hl)} highlights)', 100),
            fields={
                'title': t.get('title', ''),
                'detail': t.get('detail', ''),
                'highlights': hl,
            },
            impact_if_modified='Jarvis 下次 SOUL inject 引用 thread 用新内容',
            impact_if_deleted='Jarvis 不再记忆此 thread (可恢复)',
            source_file='memory_pool/relational_state.json',
            source_path=f'shared_history_threads.{tid}',
            created_at=float(t.get('created_at', 0) or 0),
            last_used_at=float(t.get('last_milestone_at', 0) or 0),
            use_count=len(hl),
            auto_proposed=t.get('source', '') == 'auto_detected',
            proposed_by=t.get('source_marker', ''),
            sir_acked=_is_acked(tid, ack_state),
        ))
    # unspoken_protocols
    for pid, p in (data.get('unspoken_protocols') or {}).items():
        if not isinstance(p, dict):
            continue
        st = p.get('state', 'active')
        if st not in ('review', 'active'):
            continue
        items.append(ActionableItem(
            id=pid,
            category='protocol',
            subcategory=st,
            state=st,
            preview=_truncate(p.get('rule', ''), 100),
            fields={
                'rule': p.get('rule', ''),
                'examples': p.get('examples', []),
            },
            impact_if_modified='Jarvis 下次行为 SOUL inject 看到新 rule',
            impact_if_deleted='Jarvis 不再遵此默契',
            source_file='memory_pool/relational_state.json',
            source_path=f'unspoken_protocols.{pid}',
            created_at=float(p.get('created_at', 0) or 0),
            sir_acked=_is_acked(pid, ack_state),
        ))
    # unfinished_business
    for uid, u in (data.get('unfinished_business') or {}).items():
        if not isinstance(u, dict):
            continue
        st = u.get('state', 'open')
        if st in ('done',):
            continue
        items.append(ActionableItem(
            id=uid,
            category='unfinished',
            subcategory=st,
            state=st,
            preview=_truncate(u.get('topic', ''), 100),
            fields={
                'topic': u.get('topic', ''),
                'detail': u.get('detail', ''),
            },
            impact_if_modified='Jarvis 下次提醒文本变',
            impact_if_deleted='Jarvis 不再追这件事',
            source_file='memory_pool/relational_state.json',
            source_path=f'unfinished_business.{uid}',
            created_at=float(u.get('created_at', 0) or 0),
            sir_acked=_is_acked(uid, ack_state),
        ))
    return items


def _extract_vocab_review(vocab_name: str, category: str,
                           preview_fn, ack_state: dict,
                           list_key: str = 'review_queue') -> List[ActionableItem]:
    """通用 vocab review_queue / active list extractor."""
    items = []
    data = _safe_read_json(os.path.join(MEM, vocab_name), {})
    arr = data.get(list_key) or []
    if not isinstance(arr, list):
        return items
    for it in arr:
        if not isinstance(it, dict):
            continue
        iid = it.get('id', '?')
        st = it.get('state', 'review')
        items.append(ActionableItem(
            id=iid,
            category=category,
            subcategory=st,
            state=st,
            preview=_truncate(preview_fn(it), 100),
            fields={k: v for k, v in it.items()
                    if k not in ('id', 'state', 'proposed_at', 'created_at')},
            impact_if_modified=f'Jarvis {category} 行为下次用新参数',
            impact_if_deleted=f'Jarvis 不再触发此 {category} 规则',
            source_file=f'memory_pool/{vocab_name}',
            source_path=f'{list_key}.{iid}',
            created_at=float(it.get('proposed_at_epoch', 0) or 0),
            auto_proposed=True,
            proposed_by=it.get('source', 'L7 reflector'),
            sir_acked=_is_acked(iid, ack_state),
        ))
    return items


def _extract_screen_tease(ack_state: dict) -> List[ActionableItem]:
    """Cat 4 + 17: screen_tease review + active."""
    out = []
    out.extend(_extract_vocab_review(
        'screen_tease_vocab.json', 'screen_tease',
        lambda it: f"{it.get('id', '?')}: {', '.join(it.get('keywords', [])[:3])}",
        ack_state, list_key='review_queue',
    ))
    out.extend(_extract_vocab_review(
        'screen_tease_vocab.json', 'screen_tease',
        lambda it: f"{it.get('id', '?')}: {', '.join(it.get('keywords', [])[:3])}",
        ack_state, list_key='categories',
    ))
    return out


def _extract_struggle(ack_state: dict) -> List[ActionableItem]:
    """Cat 5 + 18: struggle vocab review + active."""
    out = []
    out.extend(_extract_vocab_review(
        'sir_struggle_vocab.json', 'struggle',
        lambda it: f"{it.get('id', '?')} [{it.get('severity', '?')}]: {', '.join(it.get('patterns', [])[:3])}",
        ack_state, list_key='review_queue',
    ))
    out.extend(_extract_vocab_review(
        'sir_struggle_vocab.json', 'struggle',
        lambda it: f"{it.get('id', '?')} [{it.get('severity', '?')}]: {', '.join(it.get('patterns', [])[:3])}",
        ack_state, list_key='phrases',
    ))
    return out


def _extract_directives(ack_state: dict) -> List[ActionableItem]:
    """Cat 6 + 20: directives review + active."""
    out = []
    data = _safe_read_json(os.path.join(MEM, 'directives_vocab.json'), {})
    arr = data.get('directives') or []
    for it in arr:
        if not isinstance(it, dict):
            continue
        iid = it.get('id', '?')
        st = it.get('state', 'active')
        out.append(ActionableItem(
            id=iid,
            category='directive',
            subcategory=st,
            state=st,
            preview=_truncate(f"{iid} [pri={it.get('priority', '?')}]: {it.get('note', '')[:50]}", 100),
            fields={
                'priority': it.get('priority', 5),
                'state': st,
                'tier_whitelist': it.get('tier_whitelist', []),
                'ttl_days': it.get('ttl_days', 120),
                'note': it.get('note', ''),
            },
            impact_if_modified='Jarvis 主脑 prompt 下次注入此 directive 改 priority/scope',
            impact_if_deleted='Jarvis 不再注入此 directive (主脑场景判断弱化)',
            source_file='memory_pool/directives_vocab.json',
            source_path=f'directives.{iid}',
            sir_acked=_is_acked(iid, ack_state),
        ))
    # review queue
    out.extend(_extract_vocab_review(
        'directives_vocab.json', 'directive',
        lambda it: f"{it.get('id', '?')}: {(it.get('text', '') or '')[:60]}",
        ack_state, list_key='review_queue',
    ))
    return out


def _extract_sleep_pattern(ack_state: dict) -> List[ActionableItem]:
    """Cat 7: sleep_pattern review."""
    return _extract_vocab_review(
        'sir_sleep_pattern_vocab.json', 'sleep_pattern',
        lambda it: f"{it.get('kind', '?')}: cur={it.get('current')} → prop={it.get('proposed')}",
        ack_state, list_key='review_queue',
    )


def _extract_behavior(ack_state: dict) -> List[ActionableItem]:
    """Cat 8: behavior_inference review."""
    return _extract_vocab_review(
        'behavior_inference_vocab.json', 'behavior_inference',
        lambda it: f"{it.get('id', '?')} [{it.get('kind', '?')}]: {', '.join(it.get('keywords', [])[:3])}",
        ack_state, list_key='review_queue',
    )


def _extract_callbacks(ack_state: dict) -> List[ActionableItem]:
    """Cat 9: cross_session callback review."""
    items = []
    data = _safe_read_json(os.path.join(MEM, 'cross_session_callback.json'), {})
    cbs = (data.get('callbacks') or {})
    for cid, cb in cbs.items():
        if not isinstance(cb, dict):
            continue
        st = cb.get('state', 'review')
        if st not in ('review', 'active'):
            continue
        items.append(ActionableItem(
            id=cid,
            category='callback',
            subcategory=st,
            state=st,
            preview=_truncate(
                f"{cb.get('when_natural', '?')}: {cb.get('action', '')[:60]}", 100),
            fields={
                'action': cb.get('action', ''),
                'when_iso': cb.get('when_iso', ''),
                'when_natural': cb.get('when_natural', ''),
                'source_utterance': cb.get('source_utterance', ''),
            },
            impact_if_modified='下次提醒时间/内容变',
            impact_if_deleted='Jarvis 不会再提醒这件事',
            source_file='memory_pool/cross_session_callback.json',
            source_path=f'callbacks.{cid}',
            created_at=float(cb.get('proposed_at', 0) or 0),
            auto_proposed=True,
            proposed_by='SoulArchivist',
            sir_acked=_is_acked(cid, ack_state),
        ))
    return items


def _extract_cooldown(ack_state: dict) -> List[ActionableItem]:
    """Cat 10: cooldown vocab review."""
    items = []
    data = _safe_read_json(os.path.join(MEM, 'proactive_care_cooldown_vocab.json'), {})
    arr = data.get('review_queue') or []
    for it in arr:
        if not isinstance(it, dict):
            continue
        key = it.get('key', '')
        iid = f"cooldown:{key}"
        items.append(ActionableItem(
            id=iid,
            category='cooldown',
            subcategory='review',
            state='review',
            preview=_truncate(f"{key}: {it.get('current')} → {it.get('proposed')}", 100),
            fields={
                'key': key,
                'current': it.get('current'),
                'proposed': it.get('proposed'),
                'rationale': it.get('rationale', ''),
            },
            impact_if_modified='ProactiveCare 阈值变, 主动 nudge 频率受影响',
            impact_if_deleted='跳过此 propose, 保留旧阈值',
            source_file='memory_pool/proactive_care_cooldown_vocab.json',
            source_path=f'review_queue.{key}',
            auto_proposed=True,
            proposed_by='ConcernFeedbackReflector',
            sir_acked=_is_acked(iid, ack_state),
        ))
    return items


def _extract_directive_review_json(ack_state: dict) -> List[ActionableItem]:
    """Cat 6': directive_review.json (priority drop / decay entries)."""
    items = []
    data = _safe_read_json(os.path.join(MEM, 'directive_review.json'), [])
    if not isinstance(data, list):
        return items
    for e in data:
        if not isinstance(e, dict):
            continue
        iid = f"dir_review:{e.get('id', '?')}_{e.get('enqueued_at', '')[:10]}"
        items.append(ActionableItem(
            id=iid,
            category='directive',
            subcategory='review_event',
            state='review',
            preview=_truncate(
                f"{e.get('id', '?')} {e.get('reason', '?')}: {e.get('note', '')[:40]}", 100),
            fields={k: v for k, v in e.items() if k not in ('enqueued_at',)},
            impact_if_modified='Jarvis 看到 Sir 拍板这条 propose',
            impact_if_deleted='跳过此 propose, 保留 directive 原状',
            source_file='memory_pool/directive_review.json',
            source_path=f'list.{iid}',
            auto_proposed=True,
            proposed_by='IntegrityReflector',
            sir_acked=_is_acked(iid, ack_state),
        ))
    return items


def _extract_sir_profile(ack_state: dict) -> List[ActionableItem]:
    """Cat 21: sir_profile."""
    items = []
    data = _safe_read_json(os.path.join(CFG, 'sir_profile.json'), {})
    if not isinstance(data, dict):
        return items
    # 每个 top-level field 一个 item (Sir 可单独看/改)
    for k, v in data.items():
        if k.startswith('_'):
            continue
        iid = f"profile:{k}"
        prev_v = v if isinstance(v, (str, int, float, bool)) else json.dumps(v)[:80]
        items.append(ActionableItem(
            id=iid,
            category='profile',
            subcategory='active',
            state='active',
            preview=_truncate(f"{k}: {prev_v}", 100),
            fields={k: v},
            impact_if_modified='Jarvis 下次 SOUL inject (L0 SelfAnchor) 看 Sir 新 profile',
            impact_if_deleted='清除此 field (Jarvis 不再知道这件事关于 Sir)',
            source_file='jarvis_config/sir_profile.json',
            source_path=f'{k}',
            sir_acked=_is_acked(iid, ack_state),
        ))
    return items


# ============================================================
# Main API
# ============================================================

_ALL_EXTRACTORS = [
    _extract_concerns,
    _extract_relational,
    _extract_screen_tease,
    _extract_struggle,
    _extract_directives,
    _extract_sleep_pattern,
    _extract_behavior,
    _extract_callbacks,
    _extract_cooldown,
    _extract_directive_review_json,
    _extract_sir_profile,
]


def get_all_sir_actionable_items(
    filter_category: Optional[str] = None,
    filter_state: Optional[str] = None,
) -> List[ActionableItem]:
    """主 API: 返回所有 Sir 可操作 item, 统一 schema.

    Args:
        filter_category: 仅返回特定 category (e.g. 'inside_joke')
        filter_state: 仅返回特定 state (e.g. 'review')

    Returns:
        list[ActionableItem]
    """
    ack_state = _load_ack_state()
    out = []
    for extractor in _ALL_EXTRACTORS:
        try:
            out.extend(extractor(ack_state))
        except Exception:
            pass  # 单个 extractor 失败不影响其他
    if filter_category:
        out = [i for i in out if i.category == filter_category]
    if filter_state:
        out = [i for i in out if i.state == filter_state]
    return out


def get_category_counts() -> Dict[str, Dict[str, int]]:
    """返 {category: {review: N, active: M, ...}} 给 sidebar 用."""
    counts = {}
    for item in get_all_sir_actionable_items():
        cat = item.category
        st = item.state
        counts.setdefault(cat, {}).setdefault(st, 0)
        counts[cat][st] += 1
    return counts


def find_item_by_id(item_id: str) -> Optional[ActionableItem]:
    """根据 id 找 item (用于 modify/delete)."""
    for item in get_all_sir_actionable_items():
        if item.id == item_id:
            return item
    return None


# ============================================================
# Mutation API (modify / delete / restore / ack)
# β.5.41-D: 写 sir_corrections.jsonl 留痕
# ============================================================

def _log_correction(action: str, item: ActionableItem, **kwargs):
    """append-only log."""
    log_path = os.path.join(MEM, 'sir_corrections.jsonl')
    entry = {
        'ts': time.time(),
        'iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'action': action,
        'category': item.category,
        'item_id': item.id,
        'source_file': item.source_file,
        'source_path': item.source_path,
    }
    entry.update(kwargs)
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass


def mark_sir_acked(item_id: str) -> bool:
    """Sir 看过 item 30s 后调. 写 sir_acked_state.json."""
    path = _ack_state_path()
    data = _safe_read_json(path, {})
    if 'item_acks' not in data:
        data['item_acks'] = {}
    data['item_acks'][item_id] = time.time()
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def get_recent_corrections(hours: float = 24.0, limit: int = 50) -> list:
    """主脑 prompt assembler 用. 返最近 hours 内的 corrections."""
    log_path = os.path.join(MEM, 'sir_corrections.jsonl')
    entries = _safe_read_jsonl(log_path)
    cutoff = time.time() - hours * 3600
    recent = [e for e in entries if float(e.get('ts', 0)) >= cutoff]
    return recent[-limit:]
