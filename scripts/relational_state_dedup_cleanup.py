# -*- coding: utf-8 -*-
"""[fix44 / Sir 2026-05-28 19:47 P0.5] relational_state.json 一次性 LLM dedup cleanup.

复用 fix44 P0 的 `AutoArbiterDaemon._semantic_dedup_check` 跑现有 active
inside_jokes + active protocols 全 pairwise, LLM 判同义换皮组, archive
低 use_count + 后创建 + auto_proposed (优先级低) 那个.

使用:
  # 默认 dry-run (只输出 plan, 不改盘):
  python scripts/relational_state_dedup_cleanup.py

  # 真 apply:
  python scripts/relational_state_dedup_cleanup.py --apply

  # 只跑 inside_joke:
  python scripts/relational_state_dedup_cleanup.py --kind inside_joke

  # 跑 protocol + 真 apply:
  python scripts/relational_state_dedup_cleanup.py --kind protocol --apply

  # 自调阈值 (默认 LLM conf threshold = 0.70):
  python scripts/relational_state_dedup_cleanup.py --conf 0.75 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

REL_PATH = os.path.join(ROOT, 'memory_pool', 'relational_state.json')


def _safe_print(*args, **kwargs):
    """Windows console gbk 编码安全 print (fallback to ascii repr)."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        try:
            s = ' '.join(str(a) for a in args)
            print(s.encode('utf-8', errors='replace').decode('ascii',
                                                                errors='replace'),
                  **kwargs)
        except Exception:
            print('<print failed>', **kwargs)


def _source_priority(source: str) -> int:
    """source 优先级 (高 = 保留): sir_added > auto_proposed > inner_thought."""
    return {
        'sir_added': 100,
        'sir_cli': 100,
        'auto_proposed': 50,
        'inner_thought': 10,
    }.get((source or '').lower(), 30)


def _winner_loser(a: dict, b: dict) -> tuple:
    """二人 PK — 谁留谁删. Return (winner_id, loser_id, reason)."""
    a_score = (
        _source_priority(a.get('source', '')),
        int(a.get('use_count', 0)),
        -float(a.get('created_at', 0)),  # 早创建优先 (负号让小的赢)
    )
    b_score = (
        _source_priority(b.get('source', '')),
        int(b.get('use_count', 0)),
        -float(b.get('created_at', 0)),
    )
    if a_score >= b_score:
        return a['id'], b['id'], (
            f"a.source={a.get('source','?')[:12]}/use={a.get('use_count',0)} "
            f"> b.source={b.get('source','?')[:12]}/use={b.get('use_count',0)}"
        )
    return b['id'], a['id'], (
        f"b.source={b.get('source','?')[:12]}/use={b.get('use_count',0)} "
        f"> a.source={a.get('source','?')[:12]}/use={a.get('use_count',0)}"
    )


def _make_arbiter():
    """构造 minimal AutoArbiterDaemon 用 _semantic_dedup_check + 真 _call_llm."""
    from jarvis_auto_arbiter import AutoArbiterDaemon
    # 🆕 [Sir 2026-05-31 修 stale import] get_default_router 已从 jarvis_key_router
    # 移除; 改用 working CLI 的标准方式直接建 KeyRouter (load_keys + 三 key 池).
    from jarvis_config.keys import load_keys
    from jarvis_key_router import KeyRouter
    _keys = load_keys()
    kr = KeyRouter(
        main_brain_key=_keys.OPENROUTER_MAIN,
        google_keys=_keys.GOOGLE_LIST,
        openrouter_keys=_keys.OPENROUTER_LIST,
    )
    d = AutoArbiterDaemon.__new__(AutoArbiterDaemon)
    d.key_router = kr
    d._calibration = {}
    d._semantic_dedup_cache = OrderedDict()
    d._semantic_dedup_llm_calls = 0
    d._semantic_dedup_llm_hits = 0
    d._semantic_dedup_cache_hits = 0
    d._llm_call_count = 0
    d._llm_fail_count = 0
    d._last_monitor_warning_ts = {}
    d.relational = None
    return d


def _load_relational() -> dict:
    with open(REL_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_relational(v: dict) -> None:
    backup = REL_PATH + f'.bk_dedup_{time.strftime("%Y%m%d_%H%M%S")}'
    with open(backup, 'w', encoding='utf-8') as f:
        json.dump(v, f, ensure_ascii=False, indent=2)
    _safe_print(f'[OK] backup -> {backup}')
    with open(REL_PATH, 'w', encoding='utf-8') as f:
        json.dump(v, f, ensure_ascii=False, indent=2)
    _safe_print(f'[OK] saved -> {REL_PATH}')


def _scan_kind(d, kind: str, items: list, conf_thr: float) -> list:
    """全 pairwise LLM 扫一个 kind, 返 [(winner, loser, jac, conf, reason), ...].

    items: [{'id': str, 'text': str, 'use_count': int, 'source': str,
              'created_at': float, '__raw': dict}, ...]
    """
    import re as _re
    pairs_to_archive = []
    seen_losers = set()  # 一个 loser 只 archive 一次
    n = len(items)
    _safe_print(f'\n=== Scanning {kind} ({n} active items, '
                 f'{n*(n-1)//2} pairs) ===')
    pair_n = 0
    for i in range(n):
        if items[i]['id'] in seen_losers:
            continue
        tokens_i = set(_re.findall(r'\w+', items[i]['text'].lower()))
        for j in range(i + 1, n):
            if items[j]['id'] in seen_losers:
                continue
            tokens_j = set(_re.findall(r'\w+', items[j]['text'].lower()))
            inter = len(tokens_i & tokens_j)
            union = len(tokens_i | tokens_j) or 1
            jac = inter / union
            # cleanup script: 比 pre-activate 更宽松 — jac > 0.05 都试 (尽量找漏网)
            if jac < 0.05:
                continue
            pair_n += 1
            if pair_n % 10 == 0:
                _safe_print(f'  ... checked {pair_n} pairs '
                             f'(llm_calls={d._semantic_dedup_llm_calls}, '
                             f'cache_hits={d._semantic_dedup_cache_hits})')
            # 强行 enable + 阈值 override
            d._calibration['runtime'] = {
                'semantic_dedup_enabled': 1,
                'semantic_dedup_conf_threshold': conf_thr,
                'semantic_dedup_cache_max': 500,
            }
            is_dup, conf, reason = d._semantic_dedup_check(
                kind, items[i]['text'], items[j]['text']
            )
            if is_dup:
                winner_id, loser_id, pk_reason = _winner_loser(
                    items[i]['__raw'], items[j]['__raw']
                )
                pairs_to_archive.append({
                    'winner_id': winner_id,
                    'loser_id': loser_id,
                    'winner_text': (items[i]['text']
                                     if items[i]['id'] == winner_id
                                     else items[j]['text']),
                    'loser_text': (items[i]['text']
                                    if items[i]['id'] == loser_id
                                    else items[j]['text']),
                    'jaccard': round(jac, 3),
                    'conf': round(conf, 2),
                    'llm_reason': reason[:80],
                    'pk_reason': pk_reason,
                })
                seen_losers.add(loser_id)
    _safe_print(f'  scan done: {pair_n} pairs checked, '
                 f'{len(pairs_to_archive)} DUP found '
                 f'({d._semantic_dedup_llm_calls} LLM calls).')
    return pairs_to_archive


def _print_plan(kind: str, plan: list) -> None:
    if not plan:
        _safe_print(f'\n>>> {kind}: no dup found, nothing to do.')
        return
    _safe_print(f'\n>>> {kind}: {len(plan)} archive action(s):')
    for i, p in enumerate(plan, 1):
        _safe_print(f'  [{i}] KEEP {p["winner_id"][:30]!r}')
        _safe_print(f'      ARCHIVE {p["loser_id"][:30]!r}')
        _safe_print(f'      winner: {p["winner_text"][:60]!r}')
        _safe_print(f'      loser:  {p["loser_text"][:60]!r}')
        _safe_print(f'      jac={p["jaccard"]:.2f} conf={p["conf"]:.2f} '
                     f'pk: {p["pk_reason"][:60]}')


def _apply_archive(kind: str, plan: list, relational: dict) -> int:
    """archive losers in plan. Return n archived."""
    if kind == 'inside_joke':
        store = relational['inside_jokes']
    else:
        store = relational['unspoken_protocols']
    archived = 0
    for p in plan:
        loser_id = p['loser_id']
        if loser_id in store and store[loser_id].get('state') == 'active':
            store[loser_id]['state'] = 'archived'
            store[loser_id]['archived_at'] = time.time()
            store[loser_id]['archived_reason'] = (
                f'fix44_dedup: dup of {p["winner_id"][:25]} '
                f'(conf={p["conf"]:.2f})'
            )
            archived += 1
    return archived


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true',
                         help='真 apply (默认 dry-run)')
    parser.add_argument('--kind', choices=['inside_joke', 'protocol', 'both'],
                         default='both')
    parser.add_argument('--conf', type=float, default=0.70,
                         help='LLM conf threshold (default 0.70)')
    args = parser.parse_args()

    _safe_print(f'[Cleanup] dry_run={not args.apply} kind={args.kind} '
                 f'conf={args.conf}')

    relational = _load_relational()

    plans = {}
    arbiter = _make_arbiter()

    if args.kind in ('inside_joke', 'both'):
        ij = relational.get('inside_jokes', {})
        items = [
            {
                'id': v['id'],
                'text': v.get('phrase', ''),
                'use_count': v.get('use_count', 0),
                'source': v.get('source', ''),
                'created_at': v.get('created_at', 0),
                '__raw': v,
            }
            for v in ij.values()
            if v.get('state') == 'active' and v.get('phrase')
        ]
        plans['inside_joke'] = _scan_kind(arbiter, 'inside_joke', items,
                                           args.conf)
        _print_plan('inside_joke', plans['inside_joke'])

    if args.kind in ('protocol', 'both'):
        pr = relational.get('unspoken_protocols', {})
        items = [
            {
                'id': v['id'],
                'text': v.get('rule', ''),
                'use_count': v.get('use_count', 0),
                'source': v.get('source', ''),
                'created_at': v.get('created_at', 0),
                '__raw': v,
            }
            for v in pr.values()
            if v.get('state') == 'active' and v.get('rule')
        ]
        plans['protocol'] = _scan_kind(arbiter, 'protocol', items, args.conf)
        _print_plan('protocol', plans['protocol'])

    if args.apply:
        _safe_print('\n=== APPLY MODE ===')
        total_archived = 0
        for kind, plan in plans.items():
            n = _apply_archive(kind, plan, relational)
            total_archived += n
            _safe_print(f'  {kind}: {n} archived')
        if total_archived > 0:
            _save_relational(relational)
            _safe_print(f'\n[DONE] total archived: {total_archived}')
        else:
            _safe_print('\n[DONE] nothing to archive (no DUP found).')
    else:
        total_plan = sum(len(p) for p in plans.values())
        _safe_print(f'\n[DRY-RUN] would archive {total_plan} items. '
                     f'Use --apply to commit.')


if __name__ == '__main__':
    main()
