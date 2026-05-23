# -*- coding: utf-8 -*-
"""[Reshape M1.5 / 2026-05-24] Lineage Trace CLI — Sir 反向追溯主脑 reply / SWM event.

跟 scripts/mutation_dump.py / promise_dump.py 风格对齐 (准则 6.5).
读 memory_pool/lineage.jsonl + filter / trace / stats.

Usage:
    # 列最近 20 条 decision
    python scripts/lineage_dump.py --list-decisions
    # 列最近 1h
    python scripts/lineage_dump.py --list-decisions --within 3600
    # 反向追溯一条 decision (含 prompt evidence + actions + claims)
    python scripts/lineage_dump.py --reply-id bd_turn_xxx_1234
    python scripts/lineage_dump.py --reply-id bd_turn_xxx_1234 --depth 5
    # 看一条 evidence 详情
    python scripts/lineage_dump.py --evidence-id evt_20260524_010203_a1b2
    # 看某 turn 所有 decision
    python scripts/lineage_dump.py --turn-id turn_20260524_010203_abcd
    # 统计 (decision 数 / evidence 数 / broken chain 数)
    python scripts/lineage_dump.py --stats
    # 看最近 N 条 evidence
    python scripts/lineage_dump.py --list-evidence --limit 20

设计 (Reshape doc §5.5):
  反向追溯: reply token → brain_decision_id → prompt block → evidence_id → source row.
  Sir 一键看见主脑为什么这么说, evidence chain 完整.
"""
import argparse
import json
import os
import sys
import time


# Windows GBK 默认 console encoding 无法打 emoji. 强制 stdout utf-8.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def _setup_path():
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    if repo not in sys.path:
        sys.path.insert(0, repo)


_setup_path()


_LINEAGE_PATH = os.path.join('memory_pool', 'lineage.jsonl')


# ============================================================
# 读 jsonl
# ============================================================
def _load_all_records(path=_LINEAGE_PATH):
    """读全部 jsonl. 返回 list of dict."""
    if not os.path.exists(path):
        return []
    records = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        print(f'[lineage_dump] read fail: {e}', file=sys.stderr)
        return []
    return records


def _split_records(records):
    """split 成 (decisions, evidences) 两 dict."""
    decisions = {}
    evidences = {}
    for r in records:
        rt = r.get('record_type')
        if rt == 'decision':
            decisions[r.get('decision_id', '')] = r
        elif rt == 'evidence':
            evidences[r.get('evidence_id', '')] = r
    return decisions, evidences


# ============================================================
# Format helpers
# ============================================================
def _fmt_ts(ts):
    if not ts:
        return '?'
    try:
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(ts)))
    except Exception:
        return str(ts)


def _short(s, n=80):
    if s is None:
        return ''
    s = str(s)
    return s if len(s) <= n else s[:n - 3] + '...'


# ============================================================
# Commands
# ============================================================
def cmd_list_decisions(args):
    records = _load_all_records(args.path)
    decisions, _ = _split_records(records)

    now = time.time()
    items = list(decisions.values())
    items.sort(key=lambda r: r.get('timestamp', 0), reverse=True)

    if args.within:
        items = [r for r in items if now - r.get('timestamp', 0) <= args.within]

    items = items[:args.limit]
    if not items:
        print('(no decisions found)')
        return

    print(f'═══ Recent {len(items)} brain decisions ═══')
    for r in items:
        ts = _fmt_ts(r.get('timestamp'))
        did = r.get('decision_id', '?')
        tid = r.get('turn_id', '?')
        rep = _short(r.get('reply_text'), 80)
        n_blocks = len(r.get('prompt_evidence_log', {}))
        n_actions = len(r.get('actions_emitted', []))
        n_claims = len(r.get('claims_extracted', []))
        print(f'[{ts}] {did}')
        print(f'  turn={tid}  blocks={n_blocks}  actions={n_actions}  claims={n_claims}')
        print(f'  reply: {rep}')
        print('')


def cmd_list_evidence(args):
    records = _load_all_records(args.path)
    _, evidences = _split_records(records)

    items = list(evidences.values())
    items.sort(key=lambda r: r.get('timestamp', 0), reverse=True)

    if args.module:
        items = [r for r in items if r.get('source_module', '') == args.module]
    items = items[:args.limit]
    if not items:
        print('(no evidence found)')
        return

    print(f'═══ Recent {len(items)} evidence ═══')
    for r in items:
        ts = _fmt_ts(r.get('timestamp'))
        eid = r.get('evidence_id', '?')
        mod = r.get('source_module', '?')
        method = r.get('source_method', '?')
        data_id = r.get('source_data_id', '?')
        n_parents = len(r.get('parent_evidence_ids', []))
        snap = _short(json.dumps(r.get('raw_snapshot', {}), ensure_ascii=False), 100)
        print(f'[{ts}] {eid}  {mod}.{method}')
        print(f'  data={data_id}  parents={n_parents}')
        print(f'  snap: {snap}')
        print('')


def cmd_trace_back(args):
    """反向追溯一条 decision → 展开 evidence DAG."""
    records = _load_all_records(args.path)
    decisions, evidences = _split_records(records)

    target = decisions.get(args.reply_id)
    if target is None:
        print(f'(decision {args.reply_id} not found)')
        return

    print(f'═══ Reverse trace: {args.reply_id} ═══')
    print(f'turn_id : {target.get("turn_id", "?")}')
    print(f'ts      : {_fmt_ts(target.get("timestamp"))}')
    print(f'reply   : {target.get("reply_text", "")}')
    print('')

    # prompt evidence by block
    print('── prompt evidence (by block) ──')
    pel = target.get('prompt_evidence_log', {})
    if not pel:
        print('  (no prompt_evidence_log recorded)')
    else:
        for block_name, eid_list in pel.items():
            print(f'  [{block_name}]  ({len(eid_list)} evidence)')
            for eid in eid_list:
                ev = evidences.get(eid)
                if ev is None:
                    print(f'    └─ {eid}  ❌ (BROKEN CHAIN, evidence not found)')
                else:
                    mod = ev.get('source_module', '?')
                    method = ev.get('source_method', '?')
                    data_id = ev.get('source_data_id', '?')
                    print(f'    └─ {eid}  {mod}.{method}  → {data_id}')
                    # 上溯 parent (深度 args.depth)
                    if args.depth > 1:
                        _print_parents(ev, evidences, depth=args.depth - 1, indent=6)
    print('')

    # actions emitted
    print('── actions emitted ──')
    actions = target.get('actions_emitted', [])
    if not actions:
        print('  (none)')
    else:
        for act in actions:
            print(f'  • {act}')
    print('')

    # claims extracted
    print('── claims extracted ──')
    claims = target.get('claims_extracted', [])
    if not claims:
        print('  (none)')
    else:
        for c in claims:
            txt = _short(c.get('text', ''), 60)
            ver = '✓' if c.get('verified') else '✗'
            print(f'  {ver} {txt}')


def _print_parents(ev, evidences, depth, indent):
    """递归打 parent evidence (上溯 DAG)."""
    pad = ' ' * indent
    for pid in ev.get('parent_evidence_ids', []):
        pev = evidences.get(pid)
        if pev is None:
            print(f'{pad}↑ {pid}  ❌ (parent missing)')
        else:
            mod = pev.get('source_module', '?')
            method = pev.get('source_method', '?')
            data_id = pev.get('source_data_id', '?')
            print(f'{pad}↑ {pid}  {mod}.{method}  → {data_id}')
            if depth > 1:
                _print_parents(pev, evidences, depth=depth - 1, indent=indent + 2)


def cmd_show_evidence(args):
    records = _load_all_records(args.path)
    _, evidences = _split_records(records)

    ev = evidences.get(args.evidence_id)
    if ev is None:
        print(f'(evidence {args.evidence_id} not found)')
        return

    print(f'═══ Evidence: {args.evidence_id} ═══')
    print(json.dumps(ev, indent=2, ensure_ascii=False))


def cmd_show_turn(args):
    records = _load_all_records(args.path)
    decisions, _ = _split_records(records)

    items = [r for r in decisions.values() if r.get('turn_id') == args.turn_id]
    if not items:
        print(f'(no decisions found for turn {args.turn_id})')
        return

    print(f'═══ Decisions for turn {args.turn_id} ═══')
    items.sort(key=lambda r: r.get('timestamp', 0))
    for r in items:
        ts = _fmt_ts(r.get('timestamp'))
        did = r.get('decision_id', '?')
        rep = _short(r.get('reply_text'), 100)
        print(f'[{ts}] {did}')
        print(f'  reply: {rep}')
        print('')


def cmd_stats(args):
    records = _load_all_records(args.path)
    decisions, evidences = _split_records(records)

    # broken chain check
    broken_decisions = 0
    for d in decisions.values():
        for eid_list in d.get('prompt_evidence_log', {}).values():
            for eid in eid_list:
                if eid not in evidences:
                    broken_decisions += 1
                    break
            else:
                continue
            break

    # by source_module
    by_module = {}
    for ev in evidences.values():
        mod = ev.get('source_module', '?')
        by_module[mod] = by_module.get(mod, 0) + 1

    print('═══ Lineage Stats ═══')
    print(f'total decisions: {len(decisions)}')
    print(f'total evidence : {len(evidences)}')
    print(f'broken chain   : {broken_decisions} decisions ({broken_decisions/max(1,len(decisions))*100:.1f}%)')
    print('')
    print('── evidence by source_module ──')
    for mod, n in sorted(by_module.items(), key=lambda x: -x[1])[:20]:
        print(f'  {n:5d}  {mod}')
    print('')

    # file size
    try:
        size_mb = os.path.getsize(args.path) / (1024 * 1024)
        print(f'jsonl file size: {size_mb:.2f} MB')
    except Exception:
        pass


# ============================================================
# Main
# ============================================================
def main():
    p = argparse.ArgumentParser(description='Lineage Trace CLI (Reshape M1)')
    p.add_argument('--path', default=_LINEAGE_PATH, help='lineage.jsonl path')
    p.add_argument('--list-decisions', action='store_true', help='list recent brain decisions')
    p.add_argument('--list-evidence', action='store_true', help='list recent evidence')
    p.add_argument('--reply-id', help='reverse trace a brain_decision_id')
    p.add_argument('--evidence-id', help='show one evidence detail')
    p.add_argument('--turn-id', help='show all decisions for a turn')
    p.add_argument('--stats', action='store_true', help='show overall stats')
    p.add_argument('--within', type=float, help='filter to last N seconds')
    p.add_argument('--limit', type=int, default=20, help='max records to print')
    p.add_argument('--module', help='filter evidence by source_module')
    p.add_argument('--depth', type=int, default=3, help='trace_back parent DAG depth (default 3)')
    args = p.parse_args()

    if args.list_decisions:
        cmd_list_decisions(args)
    elif args.list_evidence:
        cmd_list_evidence(args)
    elif args.reply_id:
        cmd_trace_back(args)
    elif args.evidence_id:
        cmd_show_evidence(args)
    elif args.turn_id:
        cmd_show_turn(args)
    elif args.stats:
        cmd_stats(args)
    else:
        p.print_help()


if __name__ == '__main__':
    main()
