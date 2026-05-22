# -*- coding: utf-8 -*-
"""[P5-fix32-H / 2026-05-22] Mutation Receipts CLI — Sir 查 mutation 真发生过没.

跟 scripts/promise_dump.py / scripts/concerns_dump.py 风格对齐 (准则 6.5).
读 memory_pool/mutation_receipts.jsonl + filter / stats / inspect.

Usage:
    # 列最近 20 条 mutation
    python scripts/mutation_dump.py --list
    # 列最近 1h
    python scripts/mutation_dump.py --list --within 3600
    # 按 layer filter
    python scripts/mutation_dump.py --list --layer ProfileCard
    # 按 source filter
    python scripts/mutation_dump.py --list --source fast_call_mutation:revise
    # 只看失败
    python scripts/mutation_dump.py --list --only-fail
    # 看 stats (by layer / by source / fail rate)
    python scripts/mutation_dump.py --stats
    # 看一条详情
    python scripts/mutation_dump.py --show mut_xxxxxxxx
    # 看 24h 总 mutation 数
    python scripts/mutation_dump.py --count --within 86400
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


_RECEIPT_PATH = os.path.join('memory_pool', 'mutation_receipts.jsonl')


def _fmt_ts(ts: float) -> str:
    if not ts or ts <= 0:
        return '-'
    return time.strftime('%m-%d %H:%M:%S', time.localtime(ts))


def _read_all() -> list:
    """读全部 receipts. 反向时序排列 (最新先)."""
    if not os.path.exists(_RECEIPT_PATH):
        return []
    out = []
    try:
        with open(_RECEIPT_PATH, 'r', encoding='utf-8') as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except Exception:
                    continue
    except Exception:
        pass
    return out[::-1]  # newest first


def _filter(receipts, layer=None, source=None, within=None, only_fail=False):
    """按条件 filter."""
    now = time.time()
    cutoff = now - within if within else 0
    out = []
    for r in receipts:
        ts = float(r.get('ts', 0))
        if cutoff and ts < cutoff:
            continue
        if layer and r.get('layer_targeted') != layer:
            continue
        if source and source not in (r.get('source') or ''):
            continue
        if only_fail and r.get('ok'):
            continue
        out.append(r)
    return out


def cmd_list(args):
    receipts = _read_all()
    receipts = _filter(receipts,
                          layer=args.layer,
                          source=args.source,
                          within=args.within,
                          only_fail=args.only_fail)
    receipts = receipts[:args.limit]
    if not receipts:
        print('(no mutation receipts match filter)')
        return

    print(f"{'='*78}")
    print(f"  Mutation Receipts ({len(receipts)} 条, newest first)")
    if args.within:
        print(f"  within: {args.within}s")
    if args.layer:
        print(f"  layer: {args.layer}")
    if args.source:
        print(f"  source~ '{args.source}'")
    if args.only_fail:
        print(f"  only_fail")
    print(f"{'='*78}")

    for r in receipts:
        ok = r.get('ok')
        mark = '✅' if ok else '❌'
        mid = r.get('mutation_id', '?')
        layer = r.get('layer_targeted', '?')
        fp = r.get('field_path', '?')
        new_v = (r.get('new_value_excerpt', '') or '')[:50]
        old_v = (r.get('old_value_excerpt', '') or '')[:30]
        src = r.get('source', '?')
        ts = _fmt_ts(r.get('ts', 0))
        line = f"{mark} [{ts}] {mid}  layer={layer}  {fp}"
        print(line)
        print(f"     new='{new_v}'  was='{old_v}'  src={src}")
        if not ok:
            err = (r.get('error', '') or '')[:120]
            if err:
                print(f"     err: {err}")
        turn = r.get('turn_id', '')
        if turn:
            print(f"     turn={turn}")


def cmd_show(args):
    receipts = _read_all()
    mid = args.show
    for r in receipts:
        if r.get('mutation_id') == mid:
            print(json.dumps(r, ensure_ascii=False, indent=2))
            return
    print(f"❌ mutation_id={mid} not found")
    sys.exit(1)


def cmd_stats(args):
    receipts = _read_all()
    if args.within:
        receipts = _filter(receipts, within=args.within)
    if not receipts:
        print('(no mutation receipts)')
        return

    by_layer = {}
    by_source = {}
    by_field_prefix = {}
    n_ok = 0
    n_fail = 0
    for r in receipts:
        layer = r.get('layer_targeted', 'unknown')
        by_layer[layer] = by_layer.get(layer, 0) + 1
        src = (r.get('source', '') or '').split(':')[0] or 'unknown'
        by_source[src] = by_source.get(src, 0) + 1
        fp = r.get('field_path', '')
        prefix = fp.split('.')[0] if fp else 'unknown'
        by_field_prefix[prefix] = by_field_prefix.get(prefix, 0) + 1
        if r.get('ok'):
            n_ok += 1
        else:
            n_fail += 1

    print(f"{'='*60}")
    print(f"  Mutation Receipts Stats ({len(receipts)} total)")
    if args.within:
        print(f"  within: {args.within}s")
    print(f"{'='*60}")
    print(f"\n  Overall: {n_ok} ✅ / {n_fail} ❌  "
            f"(fail rate: {n_fail/max(len(receipts),1)*100:.1f}%)\n")

    print(f"  By layer:")
    for k, v in sorted(by_layer.items(), key=lambda x: -x[1]):
        print(f"    {k:<26s} {v}")

    print(f"\n  By source (first colon-prefix):")
    for k, v in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"    {k:<26s} {v}")

    print(f"\n  By field_path prefix:")
    for k, v in sorted(by_field_prefix.items(), key=lambda x: -x[1]):
        print(f"    {k:<26s} {v}")


def cmd_count(args):
    receipts = _read_all()
    if args.within:
        receipts = _filter(receipts, within=args.within)
    n_ok = sum(1 for r in receipts if r.get('ok'))
    n_fail = len(receipts) - n_ok
    print(f"{len(receipts)} ({n_ok} ✅ / {n_fail} ❌)")


def main():
    parser = argparse.ArgumentParser(
        description='Mutation receipts CLI (P5-fix32-H)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('Usage:')[1] if 'Usage:' in __doc__ else '',
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument('--list', action='store_true', help='list recent receipts')
    grp.add_argument('--stats', action='store_true', help='show stats summary')
    grp.add_argument('--show', metavar='MUTATION_ID',
                       help='show one receipt detail')
    grp.add_argument('--count', action='store_true',
                       help='show count only (good for piping)')

    parser.add_argument('--limit', type=int, default=20,
                          help='max rows (default 20)')
    parser.add_argument('--within', type=float, default=None,
                          help='only within N seconds (e.g. 3600 for 1h)')
    parser.add_argument('--layer', default=None,
                          help='filter by layer (ProfileCard / ConcernsLedger / '
                               'PromiseLog / CommitmentWatcher / RelationalStateStore / '
                               'Milestones)')
    parser.add_argument('--source', default=None,
                          help='filter by source substring '
                               '(e.g. fast_call_mutation:revise / sir_cli)')
    parser.add_argument('--only-fail', action='store_true',
                          help='only show ❌ mutations')

    args = parser.parse_args()

    if args.list:
        cmd_list(args)
    elif args.stats:
        cmd_stats(args)
    elif args.show:
        cmd_show(args)
    elif args.count:
        cmd_count(args)


if __name__ == '__main__':
    main()
