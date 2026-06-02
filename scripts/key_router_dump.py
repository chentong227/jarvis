#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🆕 [P5-fix20-A2 / 2026-05-22] KeyRouter CLI — Sir 看/复活 API key 池.

Sir 14:32 真测痛点: OpenRouter 全挂 + Google 池 429 → 主脑能开口但
IntentResolver/Vision/Hippocampus 全降级 → "嘴上说没真做".

这个 CLI 让 Sir 不进 Python REPL / dashboard 也能:
  - 看哪个池挂了 (--show)
  - 强制复活某把 key (--reset-cooldown / --reset-permanent <label>)
  - 一键复活全部 (--reset-all)

设计:
  - 直接读 memory_pool/key_router_health.json (snapshot daemon 写, 15s 更新)
  - reset 通过写 memory_pool/key_router_reset_request.json
    主进程 KeyRouter daemon 每 5s poll → 执行 → 写 audit jsonl

Usage:
  python scripts/key_router_dump.py --show
  python scripts/key_router_dump.py --reset-cooldown google_1
  python scripts/key_router_dump.py --reset-permanent openrouter_3
  python scripts/key_router_dump.py --reset-all
  python scripts/key_router_dump.py --audit   # 看 reset 历史
  python scripts/key_router_dump.py --wait    # reset 后等主进程执行完
"""
import argparse
import json
import os
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEALTH_PATH = os.path.join(ROOT, 'memory_pool', 'key_router_health.json')
REQUEST_PATH = os.path.join(ROOT, 'memory_pool', 'key_router_reset_request.json')
AUDIT_PATH = os.path.join(ROOT, 'memory_pool', 'key_router_reset_audit.jsonl')


def _read_health() -> dict:
    if not os.path.exists(HEALTH_PATH):
        return {}
    try:
        with open(HEALTH_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERR] 读 health snapshot 失败: {e}")
        return {}


def cmd_show(args) -> int:
    """显示当前 key 池状态."""
    stats = _read_health()
    if not stats:
        print(f"❌ 未找到 key_router_health.json")
        print(f"   路径: {HEALTH_PATH}")
        print(f"   原因: Jarvis 未启动 / KeyRouter 未初始化 / snapshot daemon 未跑")
        return 1

    age_s = int(time.time() - stats.get('_snapshot_ts', 0)) if stats.get('_snapshot_ts') else None
    overall = stats.get('overall_health', '?')
    print(f"=== 🔑 KeyRouter Health Snapshot ===")
    print(f"Snapshot age: {age_s}s 前 ({stats.get('_snapshot_iso', '?')})")
    print(f"Overall: {overall.upper()}")
    print(f"OpenRouter calls today: {stats.get('openrouter_calls_today', 0)}")
    print()

    pools = stats.get('pools', {})
    if not pools:
        print(f"  (无 pool 数据)")
    for name, p in pools.items():
        emoji = '🟢' if p['healthy'] == p['total'] else ('🟡' if p['healthy'] > 0 else '🔴')
        print(f"  {emoji} {name:12s} {p['healthy']}/{p['total']}"
              + (f"  ⛔ 永久死 {p.get('permanent_dead', 0)}" if p.get('permanent_dead') else '')
              + (f"  ❄️ 冷却 {p.get('in_cooldown', 0)}" if p.get('in_cooldown') else '')
              )

    # detail
    key_status = stats.get('key_status', {})
    if key_status and args.detail:
        print()
        print(f"--- Detail ({len(key_status)} keys) ---")
        for label, st in key_status.items():
            mark = '🟢' if st.get('healthy') else ('⛔' if st.get('permanently_dead') else '❄️')
            extra = ''
            if st.get('in_cooldown'):
                extra += f" 冷却剩 {st.get('cooldown_remaining_s', 0)}s"
            if st.get('last_error'):
                extra += f" err={st['last_error'][:60]}"
            print(f"  {mark} {label:14s} {extra}")
    elif key_status:
        unhealthy = [(l, s) for l, s in key_status.items() if not s.get('healthy')]
        if unhealthy:
            print()
            print(f"--- {len(unhealthy)} key(s) 不健康 (--detail 看全部) ---")
            for label, st in unhealthy[:10]:
                mark = '⛔' if st.get('permanently_dead') else '❄️'
                err = (st.get('last_error') or '')[:80]
                print(f"  {mark} {label:14s} {err}")
            if len(unhealthy) > 10:
                print(f"  ... (+{len(unhealthy) - 10} more)")
    return 0


def _write_reset_request(action: str, label: str = '') -> dict:
    """写 reset_request.json, 主进程 daemon ≤5s 内执行."""
    req = {
        'action': action,
        'label': label,
        'source': 'cli',
        'requested_at': time.time(),
        'requested_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'consumed': False,
    }
    os.makedirs(os.path.dirname(REQUEST_PATH), exist_ok=True)
    tmp = REQUEST_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(req, f, ensure_ascii=False, indent=2)
    os.replace(tmp, REQUEST_PATH)
    return req


def _wait_for_consume(req: dict, timeout_s: int = 15) -> dict:
    """等主进程 KeyRouter 执行 reset 完成. 返回 result dict (或 None 超时)."""
    start = time.time()
    last_iso = req.get('requested_iso', '')
    while (time.time() - start) < timeout_s:
        try:
            with open(REQUEST_PATH, 'r', encoding='utf-8') as f:
                cur = json.load(f)
            if cur.get('consumed') and cur.get('requested_iso') == last_iso:
                return cur
        except Exception:
            pass
        time.sleep(0.5)
    return {}


def _do_reset(action: str, label: str, wait: bool) -> int:
    if not os.path.exists(HEALTH_PATH):
        print(f"⚠️  health snapshot 不存在 → Jarvis 可能未启动. reset 请求仍会写入,")
        print(f"   但主进程没起来不会被消费 (启动 Jarvis 后会被处理).")
    req = _write_reset_request(action, label)
    print(f"✅ Reset 请求已写入: action={action} label={label or '(none)'}")
    print(f"   路径: {REQUEST_PATH}")
    print(f"   主进程 KeyRouter ≤5s 内 poll 执行.")
    if wait:
        print(f"⏳ 等主进程执行... (timeout 15s)")
        consumed = _wait_for_consume(req)
        if not consumed:
            print(f"❌ 超时 — Jarvis 可能未运行或 KeyRouter snapshot daemon 未跑.")
            return 1
        result = consumed.get('result', {})
        print(f"✅ 已执行: {result.get('summary', '?')}")
        if result.get('reset_cooldown'):
            print(f"   冷却复活: {', '.join(result['reset_cooldown'])}")
        if result.get('reset_permanent'):
            print(f"   永久死复活: {', '.join(result['reset_permanent'])}")
    return 0


def cmd_reset_cooldown(args) -> int:
    return _do_reset('cooldown', args.reset_cooldown, args.wait)


def cmd_reset_permanent(args) -> int:
    return _do_reset('permanent', args.reset_permanent, args.wait)


def cmd_reset_all(args) -> int:
    return _do_reset('all', '', args.wait)


def cmd_ack_dead(args) -> int:
    """🆕 [放权-mask / Sir 2026-06-02] 屏蔽死 key 的自我焦虑 (不复活/不路由)."""
    label = 'all' if args.ack_all_dead else args.ack_dead
    return _do_reset('acknowledge', label, args.wait)


def cmd_audit(args) -> int:
    """看 reset 历史."""
    if not os.path.exists(AUDIT_PATH):
        print(f"(无 reset 历史 — 未做过任何 reset)")
        return 0
    lines = []
    try:
        with open(AUDIT_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    lines.append(json.loads(line))
                except Exception:
                    pass
    except Exception as e:
        print(f"[ERR] 读 audit 失败: {e}")
        return 1
    print(f"=== Reset 历史 ({len(lines)} 条) ===")
    # 倒序 (新的在上)
    n_show = args.limit or 20
    for entry in reversed(lines[-n_show:]):
        ts = entry.get('iso', '?')
        req = entry.get('request', {})
        res = entry.get('result', {})
        print(f"  {ts}  来源={req.get('source', '?'):8s} {res.get('summary', '?')}")
    if len(lines) > n_show:
        print(f"  ... (+{len(lines) - n_show} 条更老, --limit 调)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description='KeyRouter health + reset CLI (P5-fix20-A2)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  --show                          看池状态 (汇总)
  --show --detail                 看池状态 (含每把 key)
  --reset-cooldown google_1       清 google_1 冷却 (写请求, 主进程 poll)
  --reset-permanent openrouter_3  解 openrouter_3 永久死
  --reset-all                     一键全清 (cooldown + permanent_death)
  --reset-all --wait              一键全清 + 等执行完
  --ack-dead google_2             屏蔽 google_2 死 key 焦虑 (不复活, Sir 处理中)
  --ack-all-dead                  屏蔽全部死 key 焦虑 (等加新 key)
  --audit                         看 reset 历史
""",
    )
    p.add_argument('--show', action='store_true', help='显示当前 key 池状态')
    p.add_argument('--detail', action='store_true', help='--show 时显示每把 key 详情')
    p.add_argument('--reset-cooldown', metavar='LABEL', help='清某把 key 冷却')
    p.add_argument('--reset-permanent', metavar='LABEL', help='解某把 key 永久死亡')
    p.add_argument('--reset-all', action='store_true', help='一键复活全部')
    p.add_argument('--ack-dead', metavar='LABEL', help='屏蔽某把死 key 的自我焦虑 (不复活/不路由, Sir 处理中)')
    p.add_argument('--ack-all-dead', action='store_true', help='屏蔽全部死 key 的自我焦虑')
    p.add_argument('--wait', action='store_true', help='reset 后等待主进程执行完')
    p.add_argument('--audit', action='store_true', help='看 reset 历史')
    p.add_argument('--limit', type=int, default=20, help='--audit 显示最近 N 条')
    args = p.parse_args()

    # 至少一个 action
    actions = [args.show, args.reset_cooldown, args.reset_permanent, args.reset_all,
               args.ack_dead, args.ack_all_dead, args.audit]
    if not any(actions):
        # 默认行为: --show
        args.show = True

    if args.show:
        return cmd_show(args)
    if args.reset_cooldown:
        return cmd_reset_cooldown(args)
    if args.reset_permanent:
        return cmd_reset_permanent(args)
    if args.reset_all:
        return cmd_reset_all(args)
    if args.ack_dead or args.ack_all_dead:
        return cmd_ack_dead(args)
    if args.audit:
        return cmd_audit(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
