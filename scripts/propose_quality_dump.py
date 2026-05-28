# -*- coding: utf-8 -*-
"""[Sir 2026-05-28 17:00 方案 B 治本] InnerThought propose quality vocab CLI.

Sir 真问 (dashboard 7-8 页 139 review 待办):
  "你认为 review 待办堆这么多 真因是什么? AutoArbiter 怎么会让 review
   待办堆这么多? 我担心他没有正确的反思评估自己 propose 的质量."

方案 B 治本: daemon 周期看 24h activate rate (auto_arbiter_log) 自适应升降
  sal_threshold — propose 类 (suggest_inside_joke / propose_protocol) sal <
  threshold 时 actionable 降级 none (thought 仍 persist, 不进 review).

准则 6 (vocab 持久化 + Sir CLI + L7 LLM-propose):
  - vocab: memory_pool/inner_thought_propose_quality_vocab.json
  - CLI: scripts/propose_quality_dump.py (本文件)
  - L7: TODO — reflector 看 review 7d 反馈 propose 新规则

用法:
  python scripts/propose_quality_dump.py list
  python scripts/propose_quality_dump.py enable
  python scripts/propose_quality_dump.py disable
  python scripts/propose_quality_dump.py enable-auto
  python scripts/propose_quality_dump.py disable-auto
  python scripts/propose_quality_dump.py set-threshold 0.65
  python scripts/propose_quality_dump.py set-cooldown 12   # 调 calibrate 间隔 (h)
  python scripts/propose_quality_dump.py set-min-samples 20
  python scripts/propose_quality_dump.py calibrate-now     # 清 last_ts 强 trigger
  python scripts/propose_quality_dump.py history           # 看 calibrate 历史
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

# 🆕 Windows GBK fix
import os as _cu_os
import sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
try:
    import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout
except Exception:
    pass

if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        os.system('chcp 65001 > nul 2>&1')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(
    ROOT, 'memory_pool', 'inner_thought_propose_quality_vocab.json'
)

# Default vocab (与 jarvis_inner_thought_daemon._PROPOSE_QUALITY_DEFAULT_VOCAB 一致)
DEFAULT_VOCAB = {
    '_doc': (
        'Inner thought daemon 自适应 propose 质量 gate. propose 类 '
        'actionable (suggest_inside_joke / propose_protocol) 受 '
        'salience >= sal_threshold gate. 周期反思 24h activate rate '
        '动态调阈值: rate 高 → 降阈 (放松); rate 低 → 升阈 (收紧). '
        'Sir CLI: scripts/propose_quality_dump.py.'
    ),
    'enabled': True,
    'sal_threshold': 0.60,
    'sal_threshold_floor': 0.40,
    'sal_threshold_ceiling': 0.85,
    'auto_calibrate_enabled': True,
    'calibrate_cooldown_h': 24,
    'calibrate_lookback_h': 24,
    'calibrate_min_samples': 10,
    'activate_rate_high': 0.70,
    'activate_rate_low': 0.30,
    'raise_step': 0.05,
    'lower_step': 0.02,
    'last_calibrated_at_ts': 0,
    'last_calibrated_at_iso': '',
    'history': [],
    'gated_actionable_prefixes': [
        'suggest_inside_joke:',
        'propose_protocol:',
    ],
}


def _load(path: str) -> dict:
    """加载 vocab, 不存在则返回 default (不报错, daemon 也走 fallback)."""
    if not os.path.exists(path):
        return dict(DEFAULT_VOCAB)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # merge default (新 key 补)
        cfg = dict(DEFAULT_VOCAB)
        for k, v in (data or {}).items():
            cfg[k] = v
        return cfg
    except Exception as e:
        print(f"⚠️  load failed: {e}, using default")
        return dict(DEFAULT_VOCAB)


def _save(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _add_history(data: dict, op: str, detail: str) -> None:
    hist = data.get('history') or []
    hist.append({
        'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'op': op,
        'detail': detail,
        'source': 'sir_cli',
    })
    data['history'] = hist[-50:]  # cap 50 (calibrate + cli ops 合用)


def cmd_list(args):
    data = _load(args.path)
    exists = "✅ exists" if os.path.exists(args.path) else "⚠️  using default (file not created yet)"
    print(f"📋 InnerThought propose quality vocab @ {args.path}")
    print(f"   ({exists})")
    print()
    print(f"[enabled] {'✅' if data.get('enabled') else '❌'} (整 gate)")
    print(f"[auto_calibrate_enabled] "
          f"{'✅' if data.get('auto_calibrate_enabled') else '❌'}")
    print()
    print(f"[sal_threshold] {data.get('sal_threshold'):.2f}")
    print(f"   floor: {data.get('sal_threshold_floor'):.2f}, "
          f"ceiling: {data.get('sal_threshold_ceiling'):.2f}")
    print()
    print(f"[calibrate]")
    print(f"   cooldown_h: {data.get('calibrate_cooldown_h')}")
    print(f"   lookback_h: {data.get('calibrate_lookback_h')}")
    print(f"   min_samples: {data.get('calibrate_min_samples')}")
    print(f"   activate_rate_high: {data.get('activate_rate_high'):.0%} "
          f"(>= → 降阈 -{data.get('lower_step'):.2f})")
    print(f"   activate_rate_low: {data.get('activate_rate_low'):.0%} "
          f"(<= → 升阈 +{data.get('raise_step'):.2f})")
    print()
    last_iso = data.get('last_calibrated_at_iso') or '(从未)'
    last_ts = float(data.get('last_calibrated_at_ts') or 0)
    if last_ts > 0:
        age_h = (time.time() - last_ts) / 3600
        print(f"[last_calibrated] {last_iso} ({age_h:.1f}h ago)")
    else:
        print(f"[last_calibrated] {last_iso}")
    print()
    prefixes = data.get('gated_actionable_prefixes') or []
    print(f"[gated_actionable_prefixes] ({len(prefixes)})")
    for p in prefixes:
        print(f"   - {p}")
    hist = data.get('history') or []
    print()
    print(f"[history] {len(hist)} entries "
          f"(use 'history' cmd to see latest)")


def cmd_enable(args):
    data = _load(args.path)
    data['enabled'] = True
    _add_history(data, 'enable', 'on')
    _save(args.path, data)
    print(f"✅ propose quality gate enabled")


def cmd_disable(args):
    data = _load(args.path)
    data['enabled'] = False
    _add_history(data, 'disable', 'off')
    _save(args.path, data)
    print(f"❌ propose quality gate disabled "
          f"(所有 propose 不 sal gate, 全 pass)")


def cmd_enable_auto(args):
    data = _load(args.path)
    data['auto_calibrate_enabled'] = True
    _add_history(data, 'enable_auto', 'on')
    _save(args.path, data)
    print(f"✅ auto calibrate enabled (24h 一次自动调阈)")


def cmd_disable_auto(args):
    data = _load(args.path)
    data['auto_calibrate_enabled'] = False
    _add_history(data, 'disable_auto', 'off')
    _save(args.path, data)
    print(f"❌ auto calibrate disabled (Sir 手动 set-threshold 控阈)")


def cmd_set_threshold(args):
    thr = float(args.value)
    if thr < 0.0 or thr > 1.0:
        print(f"❌ threshold must be 0.0-1.0, got {thr}")
        sys.exit(1)
    data = _load(args.path)
    old = float(data.get('sal_threshold', 0.60))
    floor = float(data.get('sal_threshold_floor', 0.40))
    ceil = float(data.get('sal_threshold_ceiling', 0.85))
    if thr < floor or thr > ceil:
        print(f"⚠️  warning: threshold {thr} out of [floor={floor}, "
              f"ceiling={ceil}] — set anyway (Sir 元否决)")
    data['sal_threshold'] = thr
    _add_history(data, 'set_threshold', f"{old:.2f} → {thr:.2f}")
    _save(args.path, data)
    print(f"✅ sal_threshold: {old:.2f} → {thr:.2f}")


def cmd_set_cooldown(args):
    h = float(args.hours)
    if h < 1 or h > 168:
        print(f"❌ cooldown_h must be 1-168 (1h-7d), got {h}")
        sys.exit(1)
    data = _load(args.path)
    old = data.get('calibrate_cooldown_h', 24)
    data['calibrate_cooldown_h'] = h
    _add_history(data, 'set_cooldown', f"{old}h → {h}h")
    _save(args.path, data)
    print(f"✅ calibrate_cooldown_h: {old}h → {h}h")


def cmd_set_min_samples(args):
    n = int(args.n)
    if n < 1 or n > 1000:
        print(f"❌ min_samples must be 1-1000, got {n}")
        sys.exit(1)
    data = _load(args.path)
    old = data.get('calibrate_min_samples', 10)
    data['calibrate_min_samples'] = n
    _add_history(data, 'set_min_samples', f"{old} → {n}")
    _save(args.path, data)
    print(f"✅ calibrate_min_samples: {old} → {n}")


def cmd_calibrate_now(args):
    """强 trigger — 清 last_calibrated_at_ts, daemon 下 tick 会跑 calibrate."""
    data = _load(args.path)
    old_ts = data.get('last_calibrated_at_ts', 0)
    data['last_calibrated_at_ts'] = 0
    data['last_calibrated_at_iso'] = ''
    _add_history(data, 'calibrate_now', f"cleared last_ts (was {old_ts})")
    _save(args.path, data)
    print(f"✅ last_calibrated_at_ts cleared — daemon 下次 tick 会立即 calibrate")
    print(f"   (默认 daemon tick 30-300s, 不必重启)")


def cmd_history(args):
    data = _load(args.path)
    hist = data.get('history') or []
    if not hist:
        print("(no history entries)")
        return
    print(f"📋 History ({len(hist)} entries, 最近 30):")
    for e in hist[-30:]:
        op = e.get('op', '?')
        src = e.get('source', 'auto')
        if op in ('calibrate', 'skip_calibrate'):
            # auto calibrate entry: 有 stats
            stats = e.get('stats') or {}
            old_thr = e.get('old_threshold', '?')
            new_thr = e.get('new_threshold', '?')
            reason = e.get('reason', '?')[:80]
            print(f"   [{e.get('ts_iso', '?')}] "
                  f"old={old_thr} → new={new_thr} | {reason}")
            if stats:
                print(f"      stats: act={stats.get('activate')} / "
                      f"rej={stats.get('reject')} / "
                      f"defer={stats.get('defer')} / "
                      f"rate={stats.get('activate_rate', 0):.0%}")
        else:
            print(f"   [{e.get('ts_iso', e.get('when', '?'))}] "
                  f"{op:20} {e.get('detail', '?')} ({src})")


def main():
    parser = argparse.ArgumentParser(
        description='InnerThought propose quality vocab CLI (Sir 17:00 方案 B)'
    )
    parser.add_argument('--path', default=DEFAULT_PATH)
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_list = sub.add_parser('list', help='列 vocab 全状态')
    p_list.set_defaults(func=cmd_list)

    p_en = sub.add_parser('enable', help='开整 gate')
    p_en.set_defaults(func=cmd_enable)
    p_di = sub.add_parser('disable', help='关整 gate (所有 propose pass)')
    p_di.set_defaults(func=cmd_disable)

    p_ena = sub.add_parser('enable-auto', help='开 auto calibrate (24h 自动调阈)')
    p_ena.set_defaults(func=cmd_enable_auto)
    p_dia = sub.add_parser('disable-auto', help='关 auto calibrate (Sir 手动控)')
    p_dia.set_defaults(func=cmd_disable_auto)

    p_st = sub.add_parser('set-threshold', help='手动设 sal_threshold (0.0-1.0)')
    p_st.add_argument('value', type=float)
    p_st.set_defaults(func=cmd_set_threshold)

    p_cd = sub.add_parser('set-cooldown', help='设 calibrate_cooldown_h (1-168)')
    p_cd.add_argument('hours', type=float)
    p_cd.set_defaults(func=cmd_set_cooldown)

    p_ms = sub.add_parser('set-min-samples',
                            help='设 calibrate_min_samples (1-1000)')
    p_ms.add_argument('n', type=int)
    p_ms.set_defaults(func=cmd_set_min_samples)

    p_cn = sub.add_parser('calibrate-now',
                            help='清 last_ts 让 daemon 下 tick 立即 calibrate')
    p_cn.set_defaults(func=cmd_calibrate_now)

    p_hist = sub.add_parser('history', help='看 calibrate + cli ops 历史 (最近 30)')
    p_hist.set_defaults(func=cmd_history)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
