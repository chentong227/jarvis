# -*- coding: utf-8 -*-
"""对比两次 strict ablation 结果"""
import json
import sys

old_path = sys.argv[1] if len(sys.argv) > 1 else 'docs/SOUL_STRICT_ABLATION_20260517_014822.json'
new_path = sys.argv[2] if len(sys.argv) > 2 else 'docs/SOUL_STRICT_ABLATION_20260517_021723.json'

old = json.load(open(old_path, encoding='utf-8'))
new = json.load(open(new_path, encoding='utf-8'))

print(f'OLD: {old_path}')
print(f'NEW: {new_path}')
print('=' * 80)
print(f'{"Layer":<10} {"OFF→":>8}{"OFF":>8} {"ON→":>8}{"ON":>8}  {"Δ→":>8}{"Δ":>8}')
print('-' * 80)
for k in ('L0', 'L1', 'L2', 'Holistic'):
    o = old.get(k, {}).get('aggregate', {})
    n = new.get(k, {}).get('aggregate', {})
    o_off = o.get('mean_off_recall', 0)
    n_off = n.get('mean_off_recall', 0)
    o_on = o.get('mean_on_recall', 0)
    n_on = n.get('mean_on_recall', 0)
    o_d = o.get('mean_delta', 0)
    n_d = n.get('mean_delta', 0)
    arrow_on = '↑' if n_on > o_on + 0.05 else ('↓' if n_on < o_on - 0.05 else '=')
    print(f'{k:<10} {o_off:>7.0%} {n_off:>7.0%}  {o_on:>7.0%} {n_on:>7.0%}{arrow_on}  {o_d:>+7.0%} {n_d:>+7.0%}')

print()
print('=== 各层细节 ===')
for k in ('L3', 'L4', 'L5'):
    print(f'\n--- {k} ---')
    o = old.get(k, {})
    n = new.get(k, {})
    keys_to_show = {
        'L3': ['classify_accuracy', 'top3_set_overlap', 'compression_ratio', 'has_user_echo'],
        'L4': ['tp', 'fp', 'tn', 'fn', 'precision', 'recall', 'f1'],
        'L5': ['strict_accuracy', 'binary_accuracy', 'correct', 'total'],
    }.get(k, [])
    for kk in keys_to_show:
        ov = o.get(kk)
        nv = n.get(kk)
        if ov is None and nv is None:
            continue
        marker = '' if ov == nv else (' [改进]' if (isinstance(ov, (int, float)) and isinstance(nv, (int, float)) and nv > ov) else ' [恶化]' if isinstance(ov, (int, float)) and isinstance(nv, (int, float)) else '')
        print(f'  {kk}: {ov} → {nv}{marker}')

print()
print('=== 各场景 SIGNATURE 召回率明细 ===')
for k in ('L0', 'L1', 'L2', 'Holistic'):
    o_tests = old.get(k, {}).get('tests', [])
    n_tests = new.get(k, {}).get('tests', [])
    if not o_tests or not n_tests:
        continue
    print(f'\n[{k}]')
    for ot, nt in zip(o_tests, n_tests):
        o_sigs = ot.get('signatures', {})
        n_sigs = nt.get('signatures', {})
        ui = ot.get('user_input', '')[:60]
        print(f'  scenario: {ui!r}')
        for sig_name in o_sigs:
            o_on = o_sigs[sig_name].get('on_recall', 0)
            n_on = n_sigs.get(sig_name, {}).get('on_recall', 0)
            arrow = '↑' if n_on > o_on else ('↓' if n_on < o_on else '=')
            mark = '' if o_on == n_on else f' [{arrow}{abs(n_on-o_on):.0%}]'
            print(f'    {sig_name:<25} ON: {o_on:.0%} → {n_on:.0%}{mark}')
