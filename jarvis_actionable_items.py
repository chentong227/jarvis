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
    """统一 schema 给 dashboard. 21 类源都映射到这.

    🩹 [P5-fix-items-i18n / 2026-05-21 09:58] Sir 09:55 截图反馈:
      ①卡片只显 vocab id / tag 没人话翻译
      ②没 👍/👎 评价按钮
    schema 加 `description_zh` (人话 1 句 "这条干啥用") + `category_zh` (中文类别名).
    extractor 各自填充. dashboard card 额外渲染这两字段.
    """

    id: str
    category: str                  # 'concern' / 'inside_joke' / 'thread' / 'screen_tease' / ...
    subcategory: str = ''          # 分组 (sidebar 用): 'review' / 'active' / 'archived' / 'system'
    state: str = 'active'          # 'review' / 'active' / 'archived' / 'rejected'
    preview: str = ''              # 显示文本 (1 行 ≤ 80 char)
    description_zh: str = ''       # 🩹 [P5-fix-items-i18n] 人话 1 句解释"这条干啥/触发时 Jarvis 做啥"
    category_zh: str = ''          # 🩹 [P5-fix-items-i18n] 中文 category 名 (e.g. 'Sir 困境词')
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
    sir_feedback: str = ''         # 🩹 [P5-fix-items-i18n] 'up' / 'down' / '' (空 = 未评)

    def to_dict(self) -> dict:
        return asdict(self)


# 🩹 [P5-fix-items-i18n / 2026-05-21 09:58] category → 中文 + 描述模板
CATEGORY_ZH_MAP = {
    'concern': '🎯 我在关心的事',
    'inside_joke': '💭 我们的梗',
    'thread': '📜 共同经历',
    'protocol': '🤝 默契规则',
    'unfinished': '⏱️ 未完结的事',
    'screen_tease': '🪞 屏幕调侃词',
    'struggle': '🆘 Sir 困境词',
    'directive': '📡 主脑 directive',
    'sleep_pattern': '💤 Sir 睡眠习惯',
    'behavior_inference': '⏱️ 行为推断词',
    'callback': '📞 跨会话提醒',
    'cooldown': '⏰ 冷却时段',
    'profile': '👤 Sir 资料',
}


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
    """Cat 1 + 12: concerns review + active.
    
    🩹 [β.5.43-fix2-C / 2026-05-20 18:18] Sir 真理 — dashboard 显示真实 nudge 概率.
    raw severity 反复涨 (sensor rule 累加), 但 urgency = severity * progress_mul * timing_mul
    才是真实 nudge 阈值. 显示 urgency 给 Sir 体感对 (不再看 raw severity 一直 100).
    """
    items = []
    data = _safe_read_json(os.path.join(MEM, 'concerns.json'), {})
    for cid, c in (data.get('concerns') or {}).items():
        if not isinstance(c, dict):
            continue
        st = c.get('state', 'active')
        if st not in ('review', 'active'):
            continue
        sev_raw = float(c.get('severity', 0.0) or 0.0)
        # 算 progress_mul (跟 ProactiveCare.compute_urgency 同公式)
        prog_mul = 1.0
        prog_pct = ''
        dp = c.get('daily_progress', {}) or {}
        try:
            today_iso = time.strftime('%Y-%m-%d', time.localtime())
            if dp.get('iso_date') == today_iso:
                cur = float(dp.get('current', 0) or 0)
                tgt = float(dp.get('target', 0) or 0)
                if tgt > 0 and cur > 0:
                    ratio = min(1.0, cur / tgt)
                    prog_mul = max(0.3, 1.0 - ratio * 0.7)
                    prog_pct = f' (progress {cur:.0f}/{tgt:.0f})'
        except Exception:
            pass
        urgency = max(0.0, min(1.0, sev_raw * prog_mul))
        items.append(ActionableItem(
            id=cid,
            category='concern',
            subcategory=st,
            state=st,
            preview=_truncate(
                f"{cid}: {c.get('what_i_watch', '')} "
                f"[urg={urgency*100:.0f}, sev_raw={sev_raw*100:.0f}{prog_pct}]",
                140,
            ),
            fields={
                'what_i_watch': c.get('what_i_watch', ''),
                'why_i_care': c.get('why_i_care', ''),
                'severity': sev_raw,           # raw severity (sensor 累加)
                'urgency': round(urgency, 3),  # 真实 nudge 阈值 (削 progress 后)
                'progress_mul': round(prog_mul, 3),
                'daily_progress': dp,
                'optimal_timing': c.get('optimal_timing', ''),
                'notes_for_self': c.get('notes_for_self', ''),
            },
            impact_if_modified=(
                'Jarvis 下次 SOUL inject 看到新文本/severity 影响主脑 nudge 倾向. '
                'urgency = severity × progress_mul × timing_mul 才是真实 nudge 概率'
            ),
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
                           list_key: str = 'review_queue',
                           describe_fn=None) -> List[ActionableItem]:
    """通用 vocab review_queue / active list extractor.

    🩹 [P5-fix-items-i18n / 2026-05-21 09:58] 加 describe_fn → description_zh.
    describe_fn(item_dict) → str: 人话 1 句"这条触发时 Jarvis 做啥".
    fallback: 默认 = "{category_zh} vocab — 触发时影响 Jarvis 反应".
    """
    items = []
    data = _safe_read_json(os.path.join(MEM, vocab_name), {})
    arr = data.get(list_key) or []
    if not isinstance(arr, list):
        return items
    feedback_state = _load_feedback_state()
    cat_zh = CATEGORY_ZH_MAP.get(category, category)
    for it in arr:
        if not isinstance(it, dict):
            continue
        iid = it.get('id', '?')
        st = it.get('state', 'review')
        desc_zh = ''
        if describe_fn is not None:
            try:
                desc_zh = describe_fn(it) or ''
            except Exception:
                desc_zh = ''
        items.append(ActionableItem(
            id=iid,
            category=category,
            subcategory=st,
            state=st,
            preview=_truncate(preview_fn(it), 100),
            description_zh=desc_zh,
            category_zh=cat_zh,
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
            sir_feedback=_get_feedback(iid, feedback_state),
        ))
    return items


# 🩹 [P5-fix-items-i18n / 2026-05-21 10:05] Sir item-level feedback state
def _feedback_state_path() -> str:
    return os.path.join(MEM, 'item_feedback_state.json')


def _load_feedback_state() -> dict:
    return _safe_read_json(_feedback_state_path(), {})


def _get_feedback(item_id: str, feedback_state: dict = None) -> str:
    """返 'up' / 'down' / '' (空 = 未评)."""
    if feedback_state is None:
        feedback_state = _load_feedback_state()
    fb_map = feedback_state.get('item_feedback') or {}
    entry = fb_map.get(item_id) or {}
    return entry.get('verdict', '') if isinstance(entry, dict) else ''


def save_item_feedback(item_id: str, verdict: str,
                         sir_note: str = '') -> bool:
    """Sir dashboard 评 item: 写 item_feedback_state.json + jsonl audit.

    verdict ∈ ('up', 'down', '') — '' = 撤销.
    """
    if verdict not in ('up', 'down', ''):
        return False
    try:
        state = _load_feedback_state()
        fb_map = state.get('item_feedback') or {}
        if verdict == '':
            fb_map.pop(item_id, None)
        else:
            fb_map[item_id] = {
                'verdict': verdict,
                'sir_note': sir_note[:200],
                'ts': time.time(),
            }
        state['item_feedback'] = fb_map
        os.makedirs(os.path.dirname(_feedback_state_path()), exist_ok=True)
        with open(_feedback_state_path(), 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        # audit jsonl
        audit_path = os.path.join(MEM, 'item_feedback.jsonl')
        with open(audit_path, 'a', encoding='utf-8') as f:
            json.dump({
                'item_id': item_id,
                'verdict': verdict,
                'sir_note': sir_note[:200],
                'ts': time.time(),
                'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
            }, f, ensure_ascii=False)
            f.write('\n')
        return True
    except Exception:
        return False


def _extract_screen_tease(ack_state: dict) -> List[ActionableItem]:
    """Cat 4 + 17: screen_tease review + active."""
    def _describe(it):
        cat = it.get('category', '?')
        kws = it.get('keywords', [])[:3]
        return (
            f"窗口标题/进程含 {kws} → Jarvis 把 Sir 当下场景归为 "
            f"'{cat}', 后续 nudge/调侃 围绕这个 context."
        )

    def _preview(it):
        return f"{it.get('category', '?')}: {', '.join(it.get('keywords', [])[:3])}"

    out = []
    out.extend(_extract_vocab_review(
        'screen_tease_vocab.json', 'screen_tease',
        _preview, ack_state, list_key='review_queue',
        describe_fn=_describe,
    ))
    out.extend(_extract_vocab_review(
        'screen_tease_vocab.json', 'screen_tease',
        _preview, ack_state, list_key='categories',
        describe_fn=_describe,
    ))
    return out


def _extract_struggle(ack_state: dict) -> List[ActionableItem]:
    """Cat 5 + 18: struggle vocab review + active."""
    _sev_zh = {'high': '高强度', 'medium': '中等', 'low': '轻度', '': '?'}
    _lang_hint_zh = {'_zh': '中文', '_en': '英文'}

    def _describe(it):
        sev = it.get('severity', '')
        sev_zh = _sev_zh.get(sev, sev or '?')
        iid = it.get('id', '?')
        # 从 id 后缀猜语种
        lang_hint = ''
        for suffix, zh in _lang_hint_zh.items():
            if iid.endswith(suffix):
                lang_hint = f'{zh}/'
                break
        patterns = it.get('patterns', [])[:3]
        return (
            f"Sir 说出{lang_hint}{sev_zh}困境词 (如 {patterns}) → "
            f"Conductor 把 last_struggle_at 设为 fresh, 90s 内触发 offer_help 主动关心 Sir 是否需要帮忙."
        )

    def _preview(it):
        return f"{it.get('id', '?')} [{it.get('severity', '?')}]: {', '.join(it.get('patterns', [])[:3])}"

    out = []
    out.extend(_extract_vocab_review(
        'sir_struggle_vocab.json', 'struggle',
        _preview, ack_state, list_key='review_queue',
        describe_fn=_describe,
    ))
    out.extend(_extract_vocab_review(
        'sir_struggle_vocab.json', 'struggle',
        _preview, ack_state, list_key='phrases',
        describe_fn=_describe,
    ))
    return out


def _extract_directives(ack_state: dict) -> List[ActionableItem]:
    """Cat 6 + 20: directives review + active."""
    out = []
    data = _safe_read_json(os.path.join(MEM, 'directives_vocab.json'), {})
    arr = data.get('directives') or []
    feedback_state = _load_feedback_state()
    cat_zh_dir = CATEGORY_ZH_MAP.get('directive', 'directive')
    for it in arr:
        if not isinstance(it, dict):
            continue
        iid = it.get('id', '?')
        st = it.get('state', 'active')
        # 🩹 [P5-fix-items-i18n] 人话 description
        _pri = it.get('priority', 5)
        _note = (it.get('note', '') or '')[:80]
        _text_first_line = ((it.get('text', '') or '').split('\n')[0] or '')[:80]
        # priority 含义: ≥10 = 顶级红线 / 7-9 = 高 / ≤6 = 普通
        if _pri >= 10:
            _pri_zh = '🔴顶级红线 always-on'
        elif _pri >= 7:
            _pri_zh = '🟠高优先 (主脑通常会看)'
        else:
            _pri_zh = '🟡普通 (排队后入)'
        _desc_zh = (
            f"{_pri_zh}, 触发时往主脑 prompt 注入此规则. "
            f"内容: {_text_first_line or _note or '(无描述)'}"
        )
        out.append(ActionableItem(
            id=iid,
            category='directive',
            subcategory=st,
            state=st,
            preview=_truncate(f"{iid} [pri={_pri}]: {_note}", 100),
            description_zh=_desc_zh,
            category_zh=cat_zh_dir,
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
            sir_feedback=_get_feedback(iid, feedback_state),
        ))
    # review queue
    out.extend(_extract_vocab_review(
        'directives_vocab.json', 'directive',
        lambda it: f"{it.get('id', '?')}: {(it.get('text', '') or '')[:60]}",
        ack_state, list_key='review_queue',
        describe_fn=lambda it: (
            f"L7 reflector 提议新 directive (待审). 拍板 active → 主脑下次能看到此规则. "
            f"内容: {((it.get('text', '') or '').split(chr(10))[0] or '')[:80]}"
        ),
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
    # 🩹 [P5-fix-items-i18n / 2026-05-21 10:08] post-process — 兜底填 category_zh
    # + sir_feedback (老 extractor 没填的也得有 — Sir 看到完整中文 + 👍/👎 状态).
    feedback_state = _load_feedback_state()
    for item in out:
        if not item.category_zh:
            item.category_zh = CATEGORY_ZH_MAP.get(item.category, item.category)
        if not item.sir_feedback:
            item.sir_feedback = _get_feedback(item.id, feedback_state)
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


# ============================================================
# Mutation Handlers (per-source-file)
# ============================================================

def _save_json(path: str, data: Any) -> bool:
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def _mutate_relational_state(item: ActionableItem, action: str, new_fields: dict = None) -> tuple:
    """处理 relational_state.json 中的 inside_jokes / threads / protocols / unfinished."""
    path = os.path.join(MEM, 'relational_state.json')
    data = _safe_read_json(path, {})
    parts = item.source_path.split('.')
    if len(parts) != 2:
        return False, f'bad source_path: {item.source_path}'
    section, sid = parts
    if section not in data:
        return False, f'section {section} not in relational_state'
    if sid not in data[section]:
        return False, f'id {sid} not found in {section}'
    target = data[section][sid]
    old_snapshot = {k: target.get(k) for k in (new_fields or {})}

    if action == 'modify':
        if not new_fields:
            return False, 'modify needs new_fields'
        for k, v in new_fields.items():
            target[k] = v
    elif action == 'delete':
        target['state'] = 'archived'
    elif action == 'restore':
        target['state'] = 'active'
    elif action == 'activate':
        if target.get('state') == 'review':
            target['state'] = 'active'
        else:
            return False, f'not in review state (is {target.get("state")})'
    elif action == 'reject':
        if target.get('state') == 'review':
            target['state'] = 'archived'
        else:
            return False, f'not in review state'
    else:
        return False, f'unknown action {action}'

    if not _save_json(path, data):
        return False, 'save failed'
    return True, {'old': old_snapshot, 'new': new_fields or {}}


def _mutate_concerns(item: ActionableItem, action: str, new_fields: dict = None) -> tuple:
    """处理 concerns.json."""
    path = os.path.join(MEM, 'concerns.json')
    data = _safe_read_json(path, {})
    parts = item.source_path.split('.', 1)
    if len(parts) != 2:
        return False, f'bad source_path: {item.source_path}'
    cid = parts[1]
    concerns = data.get('concerns') or {}
    if cid not in concerns:
        return False, f'concern {cid} not found'
    target = concerns[cid]
    old_snapshot = {k: target.get(k) for k in (new_fields or {})}

    if action == 'modify':
        if not new_fields:
            return False, 'modify needs new_fields'
        for k, v in new_fields.items():
            target[k] = v
    elif action == 'delete':
        target['state'] = 'archived'
    elif action == 'restore':
        target['state'] = 'active'
    elif action == 'activate':
        if target.get('state') == 'review':
            target['state'] = 'active'
    elif action == 'reject':
        if target.get('state') == 'review':
            target['state'] = 'archived'
    else:
        return False, f'unknown action {action}'

    if not _save_json(path, data):
        return False, 'save failed'
    return True, {'old': old_snapshot, 'new': new_fields or {}}


def _mutate_vocab_list(vocab_name: str, item: ActionableItem, action: str,
                        new_fields: dict = None) -> tuple:
    """通用 vocab list (review_queue / phrases / categories / directives)."""
    path = os.path.join(MEM, vocab_name)
    data = _safe_read_json(path, {})
    parts = item.source_path.split('.', 1)
    if len(parts) != 2:
        return False, f'bad source_path: {item.source_path}'
    list_key, target_id = parts
    arr = data.get(list_key) or []
    if not isinstance(arr, list):
        return False, f'{list_key} not a list'
    target = None
    target_idx = None
    for i, it in enumerate(arr):
        if isinstance(it, dict) and it.get('id') == target_id:
            target = it
            target_idx = i
            break
    if target is None:
        return False, f'id {target_id} not in {list_key}'
    old_snapshot = {k: target.get(k) for k in (new_fields or {})}

    if action == 'modify':
        if not new_fields:
            return False, 'modify needs new_fields'
        for k, v in new_fields.items():
            target[k] = v
    elif action == 'delete':
        target['state'] = 'archived'
        if list_key == 'review_queue':
            # 从 review_queue 拿出放 rejected_history (legacy 兼容)
            arr.pop(target_idx)
            data.setdefault('rejected_history', []).append(target)
    elif action == 'restore':
        target['state'] = 'active'
        # 从 rejected_history 回去 phrases / categories / etc 不实现 (复杂); 仅改 state
    elif action == 'activate':
        if list_key == 'review_queue' and target.get('state') == 'review':
            target['state'] = 'active'
            arr.pop(target_idx)
            # 决定放到哪个 active list (basics: phrases / categories / directives / etc)
            for active_key in ('phrases', 'categories', 'directives'):
                if active_key in data and isinstance(data[active_key], list):
                    data[active_key].append(target)
                    break
            else:
                data.setdefault('phrases', []).append(target)  # fallback
        else:
            return False, f'not in review state'
    elif action == 'reject':
        if list_key == 'review_queue' and target.get('state') == 'review':
            target['state'] = 'rejected'
            arr.pop(target_idx)
            data.setdefault('rejected_history', []).append(target)
        else:
            return False, f'not in review state'
    else:
        return False, f'unknown action {action}'

    if not _save_json(path, data):
        return False, 'save failed'
    return True, {'old': old_snapshot, 'new': new_fields or {}}


def _mutate_callback(item: ActionableItem, action: str, new_fields: dict = None) -> tuple:
    """处理 cross_session_callback.json."""
    path = os.path.join(MEM, 'cross_session_callback.json')
    data = _safe_read_json(path, {})
    cbs = data.get('callbacks') or {}
    cid = item.id
    if cid not in cbs:
        return False, f'callback {cid} not found'
    target = cbs[cid]
    old_snapshot = {k: target.get(k) for k in (new_fields or {})}

    if action == 'modify':
        for k, v in (new_fields or {}).items():
            target[k] = v
    elif action == 'delete':
        target['state'] = 'archived'
    elif action == 'restore':
        target['state'] = 'active'
    elif action == 'activate':
        if target.get('state') == 'review':
            target['state'] = 'active'
    elif action == 'reject':
        if target.get('state') == 'review':
            target['state'] = 'archived'
    else:
        return False, f'unknown action {action}'

    if not _save_json(path, data):
        return False, 'save failed'
    return True, {'old': old_snapshot, 'new': new_fields or {}}


def _mutate_sir_profile(item: ActionableItem, action: str, new_fields: dict = None) -> tuple:
    """处理 sir_profile.json. Only modify supported, no delete (太危险)."""
    path = os.path.join(CFG, 'sir_profile.json')
    data = _safe_read_json(path, {})
    field_name = item.source_path  # top-level field
    old_value = data.get(field_name)

    if action == 'modify':
        if not new_fields or field_name not in new_fields:
            return False, f'modify needs new_fields[{field_name}]'
        data[field_name] = new_fields[field_name]
    elif action == 'delete':
        # Sir 删 profile field — 不真删, 设 null (避免 schema 破坏)
        data[field_name] = None
    else:
        return False, f'action {action} not supported on sir_profile (only modify/delete)'

    if not _save_json(path, data):
        return False, 'save failed'
    return True, {'old': {field_name: old_value}, 'new': new_fields or {field_name: None}}


def _mutate_directive_review_event(item: ActionableItem, action: str, new_fields: dict = None) -> tuple:
    """处理 directive_review.json 中的事件 (priority drop / etc)."""
    path = os.path.join(MEM, 'directive_review.json')
    arr = _safe_read_json(path, [])
    if not isinstance(arr, list):
        return False, 'directive_review not a list'
    # item.id 形如 'dir_review:<id>_<enq_at[:10]>'
    raw_id = item.id.split(':', 1)[1] if ':' in item.id else item.id
    target = None
    target_idx = None
    for i, e in enumerate(arr):
        eid_concat = f"{e.get('id', '?')}_{e.get('enqueued_at', '')[:10]}"
        if eid_concat == raw_id:
            target = e
            target_idx = i
            break
    if target is None:
        return False, f'event {raw_id} not found'

    if action in ('delete', 'reject', 'activate'):
        arr.pop(target_idx)  # 单一动作: 移除事件
    else:
        return False, f'action {action} not supported on directive_review event'

    if not _save_json(path, arr):
        return False, 'save failed'
    return True, {'removed_entry': target}


def _mutate_cooldown_review(item: ActionableItem, action: str, new_fields: dict = None) -> tuple:
    """处理 proactive_care_cooldown_vocab.json review_queue."""
    path = os.path.join(MEM, 'proactive_care_cooldown_vocab.json')
    data = _safe_read_json(path, {})
    arr = data.get('review_queue') or []
    # item.id 形如 'cooldown:<key>'
    key = item.id.split(':', 1)[1] if ':' in item.id else item.id
    target_idx = None
    target = None
    for i, e in enumerate(arr):
        if e.get('key') == key:
            target = e
            target_idx = i
            break
    if target is None:
        return False, f'cooldown review for {key} not found'

    if action == 'activate':
        # apply proposed value to current
        cur = data.setdefault('current', {})
        cur[key] = target.get('proposed')
        # archive event
        arr.pop(target_idx)
        data.setdefault('history', []).append({
            'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'key': key,
            'old': target.get('current'),
            'new': target.get('proposed'),
            'source': 'sir_activate',
        })
    elif action in ('delete', 'reject'):
        arr.pop(target_idx)
    else:
        return False, f'action {action} not supported on cooldown review'

    if not _save_json(path, data):
        return False, 'save failed'
    return True, {'cooldown_action': action}


# Source file → mutation handler
_MUTATION_DISPATCH = {
    'memory_pool/concerns.json': _mutate_concerns,
    'memory_pool/relational_state.json': _mutate_relational_state,
    'memory_pool/screen_tease_vocab.json': lambda i, a, n: _mutate_vocab_list('screen_tease_vocab.json', i, a, n),
    'memory_pool/sir_struggle_vocab.json': lambda i, a, n: _mutate_vocab_list('sir_struggle_vocab.json', i, a, n),
    'memory_pool/directives_vocab.json': lambda i, a, n: _mutate_vocab_list('directives_vocab.json', i, a, n),
    'memory_pool/sir_sleep_pattern_vocab.json': lambda i, a, n: _mutate_vocab_list('sir_sleep_pattern_vocab.json', i, a, n),
    'memory_pool/behavior_inference_vocab.json': lambda i, a, n: _mutate_vocab_list('behavior_inference_vocab.json', i, a, n),
    'memory_pool/cross_session_callback.json': _mutate_callback,
    'memory_pool/proactive_care_cooldown_vocab.json': _mutate_cooldown_review,
    'memory_pool/directive_review.json': _mutate_directive_review_event,
    'jarvis_config/sir_profile.json': _mutate_sir_profile,
}


def mutate_actionable_item(item_id: str, action: str,
                            new_fields: dict = None,
                            sir_note: str = '') -> dict:
    """主 mutation API. Sir 改/删/恢复/激活/拒绝 一条 actionable item.

    Args:
        item_id: ActionableItem.id
        action: 'modify' / 'delete' / 'restore' / 'activate' / 'reject'
        new_fields: dict (action='modify' 必填; 其他可省)
        sir_note: Sir 的备注 (写入 corrections.jsonl)

    Returns:
        {'ok': True, 'detail': '...', 'changes': {...}} or {'ok': False, 'error': '...'}
    """
    item = find_item_by_id(item_id)
    if item is None:
        return {'ok': False, 'error': f'item {item_id} not found'}

    handler = _MUTATION_DISPATCH.get(item.source_file)
    if handler is None:
        return {'ok': False, 'error': f'no mutation handler for {item.source_file}'}

    try:
        ok, detail = handler(item, action, new_fields)
    except Exception as e:
        return {'ok': False, 'error': f'mutation exception: {type(e).__name__}: {e}'}

    if not ok:
        return {'ok': False, 'error': str(detail)}

    # 写 corrections log
    _log_correction(
        action, item,
        old=detail.get('old', {}) if isinstance(detail, dict) else {},
        new=new_fields or {},
        sir_note=sir_note,
    )

    return {
        'ok': True,
        'detail': f'{action} succeeded',
        'changes': detail,
        'item_id': item_id,
        'category': item.category,
    }
