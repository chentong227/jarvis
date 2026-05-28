# -*- coding: utf-8 -*-
"""[Sir 2026-05-28 19:47 fix44 P1] sensor_thresholds_vocab CLI.

Sir 真意 (准则 6 vocab 持久化 + 准则 7 Sir 元否决):
  思考脑发现某 sensor 阈值不合 Sir 真习惯 → propose 入 review_queue
  Sir CLI 拍板 (approve / reject / 直接 apply / reset) — 不直 mutate current.
  现 hardcoded 阈值散在 .py source (e.g. 30s ghost_dampen) → 持久化 vocab.

用法:
  python scripts/sensor_thresholds_dump.py list
  python scripts/sensor_thresholds_dump.py proposals
  python scripts/sensor_thresholds_dump.py approve <review_id>
  python scripts/sensor_thresholds_dump.py reject <review_id> --reason "太激进"
  python scripts/sensor_thresholds_dump.py apply ghost_activity.idle_threshold_s 80
  python scripts/sensor_thresholds_dump.py reset proactive_shield.ghost_dampen_idle_real_s
  python scripts/sensor_thresholds_dump.py dry-run afk.idle_threshold_s 90
  python scripts/sensor_thresholds_dump.py history --path X --n 30
  python scripts/sensor_thresholds_dump.py gate on
  python scripts/sensor_thresholds_dump.py gate off

Sir 元否决 (准则 7): apply / reset 跳过 review queue, Sir 直接动 current.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# force utf-8 stdout (Windows GBK fix)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from jarvis_sensor_thresholds import (  # noqa: E402
    apply_adjustment,
    apply_direct,
    get_history,
    get_writable_paths,
    invalidate_cache,
    list_review_queue,
    reject_adjustment,
    reset_to_default,
    validate_value,
)


DEFAULT_PATH = os.path.join(
    ROOT, 'memory_pool', 'sensor_thresholds_vocab.json'
)


def _load_raw(path: str) -> dict:
    """直读 vocab JSON (CLI 看 enabled flag / 改 enabled / 改 raw)."""
    if not os.path.exists(path):
        print(f"WARN: {path} not found")
        sys.exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_raw(path: str, data: dict) -> None:
    """直写 vocab JSON (CLI 改 enabled gate)."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    invalidate_cache()


def _cast_value(value_str: str, vtype: str):
    """按 vocab spec.type 转 Sir 输的 str → typed value."""
    if vtype == 'int':
        return int(value_str)
    if vtype == 'float':
        return float(value_str)
    if vtype == 'bool':
        low = value_str.lower()
        if low in ('true', '1', 'yes', 'on'):
            return True
        if low in ('false', '0', 'no', 'off'):
            return False
        raise ValueError(
            f'bool parse fail: {value_str!r} (expected true/false/1/0)'
        )
    if vtype == 'list_str':
        v = json.loads(value_str)
        if not isinstance(v, list):
            raise ValueError(f'list_str not list: {type(v).__name__}')
        return v
    return value_str


def cmd_list(args):
    """列所有 writable_paths + current + default + spec."""
    data = _load_raw(args.path)
    writable = get_writable_paths()
    queue_n = len(data.get('review_queue') or [])
    print(f"[VOCAB] sensor_thresholds_vocab @ {args.path}")
    print(f"   schema_version: {data.get('schema_version', '?')}")
    print(f"   enabled: {data.get('enabled', 1)} "
          f"(0 = gate off, get_threshold returns default)")
    print(f"   last_modified: {data.get('last_modified_iso', '?')}")
    print(f"\n[WRITABLE PATHS] ({len(writable)})")
    for path in sorted(writable.keys()):
        spec = writable[path]
        cur = spec.get('current')
        dflt = spec.get('default')
        typ = spec.get('type', 'str')
        rng = ''
        if 'min' in spec and 'max' in spec:
            rng = f", range=[{spec['min']}, {spec['max']}]"
        elif 'max_items' in spec:
            rng = f", max_items={spec['max_items']}"
        owner = spec.get('owner', '?')
        flag = '*' if cur != dflt else ' '
        print(f"   {flag} {path}")
        print(f"       type={typ}{rng}, owner={owner}")
        print(f"       current={cur!r}")
        if cur != dflt:
            print(f"       default={dflt!r}")
        desc = spec.get('description')
        if desc:
            print(f"       {desc[:200]}")
    print(f"\n[REVIEW QUEUE] {queue_n} pending proposal(s)")
    if queue_n:
        print(f"   (use 'proposals' cmd to see details, "
              f"'approve <id>' / 'reject <id>' to act)")


def cmd_proposals(args):
    """列 review_queue 待 Sir 拍板的 proposal."""
    queue = list_review_queue()
    if not queue:
        print("(no pending proposals)")
        return
    print(f"[PROPOSALS] {len(queue)} pending:")
    for p in queue:
        print(f"   {p.get('id', '?')}")
        print(f"       path: {p.get('path', '?')}")
        print(f"       proposed: {p.get('current_value')!r} "
              f"-> {p.get('proposed_value')!r}")
        print(f"       source: {p.get('source', '?')}")
        print(f"       created: {p.get('created_iso', '?')}")
        rationale = (p.get('rationale') or '')[:200]
        if rationale:
            print(f"       rationale: {rationale}")
    print(f"\n[SIR cmds]")
    print(f"   approve <id>            - apply 到 current")
    print(f"   reject <id> --reason X  - 否, 不 apply")


def cmd_approve(args):
    """Sir 拍板 proposal — apply 到 current (走 helper apply_adjustment)."""
    ok, msg = apply_adjustment(args.id)
    if ok:
        print(f"OK: {msg}")
    else:
        print(f"ERR: {msg}")
        sys.exit(1)


def cmd_reject(args):
    """Sir 否 proposal."""
    ok, msg = reject_adjustment(args.id, reason=args.reason or '')
    if ok:
        print(f"OK: {msg}")
    else:
        print(f"ERR: {msg}")
        sys.exit(1)


def cmd_apply(args):
    """Sir 元否决 (准则 7): 直接改 current 跳过 review queue."""
    writable = get_writable_paths()
    spec = writable.get(args.threshold_path)
    if spec is None:
        allowed = ', '.join(sorted(writable.keys())[:5])
        print(f"ERR: path '{args.threshold_path}' not in writable_paths")
        print(f"     (allowed e.g.: {allowed} ...)")
        sys.exit(1)
    vtype = spec.get('type', 'str')
    try:
        value = _cast_value(args.value, vtype)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"ERR: cast {vtype} fail: {e}")
        sys.exit(1)
    ok, msg = apply_direct(
        path=args.threshold_path,
        new_value=value,
        source='sir_cli',
        rationale=args.reason or 'Sir CLI apply (元否决)',
    )
    if ok:
        print(f"OK: {msg}")
    else:
        print(f"ERR: {msg}")
        sys.exit(1)


def cmd_reset(args):
    """Sir 撤改, 把某 path 的 current 还原成 default."""
    ok, msg = reset_to_default(args.threshold_path)
    if ok:
        print(f"OK: {msg}")
    else:
        print(f"ERR: {msg}")
        sys.exit(1)


def cmd_dry_run(args):
    """模拟 validate, 不真改 — 看 propose 会不会过."""
    writable = get_writable_paths()
    spec = writable.get(args.threshold_path)
    if spec is None:
        print(f"ERR: path '{args.threshold_path}' not in writable_paths")
        sys.exit(1)
    vtype = spec.get('type', 'str')
    try:
        value = _cast_value(args.value, vtype)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"ERR: cast {vtype} fail: {e}")
        sys.exit(1)
    ok, why = validate_value(args.threshold_path, value)
    if ok:
        print(f"OK: {args.threshold_path}={value!r} would pass validate")
    else:
        print(f"REJECT: {args.threshold_path}={value!r} -> {why}")


def cmd_history(args):
    """看 history (apply / approve / reject / reset / direct)."""
    hist = get_history(path=args.path, limit=args.n if args.n > 0 else 50)
    if not hist:
        if args.path:
            print(f"(no history for path={args.path})")
        else:
            print("(no history entries)")
        return
    print(f"[HISTORY] {len(hist)} entries:")
    for e in hist:
        act = e.get('action', '?')
        ts = (e.get('applied_iso') or e.get('rejected_iso')
              or e.get('reset_iso') or '?')
        path = e.get('path', '?')
        src = e.get('source', '?')
        print(f"   [{ts}] {act:18} {path}", end='')
        ov = e.get('old_value')
        nv = e.get('new_value')
        if ov is not None or nv is not None:
            print(f" {ov!r} -> {nv!r}", end='')
        print(f"  ({src})")
        ra = (e.get('rationale') or '')[:120]
        if ra:
            print(f"       rationale: {ra}")


def cmd_gate(args):
    """开关整个 vocab — gate off 时 get_threshold 返 default 不读 current."""
    data = _load_raw(args.path)
    state = args.state.lower()
    if state not in ('on', 'off'):
        print("ERR: state must be 'on' or 'off'")
        sys.exit(1)
    new_enabled = 1 if state == 'on' else 0
    old_enabled = data.get('enabled', 1)
    data['enabled'] = new_enabled

    # 记 history (sentinel-like 走自己的 history list)
    import time as _t
    hist = data.setdefault('history', [])
    hist.append({
        'action': 'gate_toggle',
        'old_value': old_enabled,
        'new_value': new_enabled,
        'source': 'sir_cli',
        'rationale': args.reason or '',
        'applied_at': _t.time(),
        'applied_iso': _t.strftime('%Y-%m-%dT%H:%M:%S', _t.localtime()),
    })
    _save_raw(args.path, data)
    print(f"OK: gate enabled {old_enabled} -> {new_enabled}")


def main():
    parser = argparse.ArgumentParser(
        description='sensor_thresholds_vocab CLI (Sir fix44 P1)'
    )
    parser.add_argument('--path', default=DEFAULT_PATH)
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_list = sub.add_parser('list', help='列所有 writable_paths + current')
    p_list.set_defaults(func=cmd_list)

    p_props = sub.add_parser('proposals', help='列待拍板 proposal')
    p_props.set_defaults(func=cmd_proposals)

    p_app = sub.add_parser('approve', help='Sir 拍板 apply proposal')
    p_app.add_argument('id')
    p_app.set_defaults(func=cmd_approve)

    p_rej = sub.add_parser('reject', help='Sir 否 proposal')
    p_rej.add_argument('id')
    p_rej.add_argument('--reason', default='')
    p_rej.set_defaults(func=cmd_reject)

    p_apl = sub.add_parser(
        'apply', help='Sir 元否决: 直接改 current (跳过 review queue)')
    p_apl.add_argument('threshold_path')
    p_apl.add_argument('value')
    p_apl.add_argument('--reason', default='')
    p_apl.set_defaults(func=cmd_apply)

    p_rev = sub.add_parser('reset', help='Sir 撤改, 回 default')
    p_rev.add_argument('threshold_path')
    p_rev.set_defaults(func=cmd_reset)

    p_dry = sub.add_parser(
        'dry-run', help='模拟 validate (不真改, 不入 queue)')
    p_dry.add_argument('threshold_path')
    p_dry.add_argument('value')
    p_dry.set_defaults(func=cmd_dry_run)

    p_hist = sub.add_parser('history', help='ops history')
    p_hist.add_argument('--path', default=None,
                       help='过滤指定 path; 默认全看')
    p_hist.add_argument('--n', type=int, default=30)
    p_hist.set_defaults(func=cmd_history)

    p_gate = sub.add_parser('gate', help='整个 vocab 开关 (on/off)')
    p_gate.add_argument('state', choices=['on', 'off'])
    p_gate.add_argument('--reason', default='')
    p_gate.set_defaults(func=cmd_gate)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
