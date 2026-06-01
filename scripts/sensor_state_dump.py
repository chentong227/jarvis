# -*- coding: utf-8 -*-
"""[P5-fix53 / 2026-05-23 15:30] sensor_state_inject_vocab.json CLI tool.

Sir 准则 6 #2: vocab 必须有 CLI 让 Sir list/add/activate/reject/delete.

用法:
  python scripts/sensor_state_dump.py --list                  # 看所有 field
  python scripts/sensor_state_dump.py --list --tier CHAT      # 看 tier 激活的
  python scripts/sensor_state_dump.py --activate <field_id>   # 激活
  python scripts/sensor_state_dump.py --reject <field_id>     # 拒
  python scripts/sensor_state_dump.py --preview --tier CHAT   # 预览 prompt 注入效果
"""
from __future__ import annotations

import argparse
import json
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

VOCAB_PATH = ROOT / 'memory_pool' / 'sensor_state_inject_vocab.json'


def cmd_list(args):
    if not VOCAB_PATH.exists():
        print(f'❌ vocab not found: {VOCAB_PATH}')
        return 1
    v = json.loads(VOCAB_PATH.read_text(encoding='utf-8'))
    fields = v.get('fields', [])
    tier = args.tier or ''
    print(f'Vocab: {VOCAB_PATH}')
    print(f'Total fields: {len(fields)}\n')
    print(f'{"ID":<30} {"Active":<8} {"Tiers":<35} Annotation')
    print('-' * 100)
    for f in fields:
        if not isinstance(f, dict):
            continue
        fid = f.get('id', '?')
        active = '✅' if f.get('active', True) else '⛔'
        tiers = ','.join(f.get('tiers', []))
        if tier and tier not in f.get('tiers', []):
            continue
        annot = (f.get('annotation', '') or '')[:50]
        print(f'{fid:<30} {active:<8} {tiers:<35} {annot}')


def cmd_set_active(args, target_active: bool):
    if not VOCAB_PATH.exists():
        print(f'❌ vocab not found: {VOCAB_PATH}')
        return 1
    v = json.loads(VOCAB_PATH.read_text(encoding='utf-8'))
    target_id = args.field
    if not target_id:
        print('❌ --field required')
        return 1
    found = False
    for f in v.get('fields', []):
        if isinstance(f, dict) and f.get('id') == target_id:
            old = f.get('active', True)
            f['active'] = target_active
            print(f"✅ {target_id}: active {old} → {target_active}")
            found = True
            break
    if not found:
        print(f'❌ field "{target_id}" not in vocab')
        return 1
    # backup + write
    import shutil
    backup = str(VOCAB_PATH) + '.bak'
    shutil.copy2(VOCAB_PATH, backup)
    VOCAB_PATH.write_text(
        json.dumps(v, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'✅ done. backup: {backup}')
    return 0


def cmd_preview(args):
    """Preview what main brain will see (run live with current sensors)."""
    from jarvis_sensor_state_block import build_sensor_state_block, reload_vocab
    reload_vocab()
    tier = args.tier or 'CHAT'
    block = build_sensor_state_block(tier=tier, max_chars=2000)
    print(f'=== Preview (tier={tier}) ===\n')
    print(block or '(empty — vocab miss / 全 inactive)')
    print()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--list', action='store_true', help='List all fields')
    p.add_argument('--activate', dest='field', help='Activate field')
    p.add_argument('--reject', dest='reject_field', help='Reject field')
    p.add_argument('--preview', action='store_true', help='Preview block')
    p.add_argument('--tier', default='', help='Filter by tier')
    args = p.parse_args()

    if args.list:
        return cmd_list(args)
    if args.field:
        return cmd_set_active(args, True)
    if args.reject_field:
        args.field = args.reject_field
        return cmd_set_active(args, False)
    if args.preview:
        return cmd_preview(args)
    p.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
