# -*- coding: utf-8 -*-
"""[P5-Layer1-fix19 / 2026-05-22] main_brain_meta_audit.jsonl CLI dump

Sir 13:13 立 Layer 1 主脑 thinking pass 的 debug 神器配套.

每轮主脑 reply 后, jarvis_meta_self_check.publish_meta 会写一行 audit:
  {turn_id, evidence, reaction, skip_alert, note, ts, user_input_excerpt, ...}

本工具让 Sir 快速看主脑每轮"思考摘要", 反诘"贾维斯为什么这样说".

Usage:
  # 看最近 20 条
  python scripts/main_brain_meta_dump.py

  # 看最近 50 条
  python scripts/main_brain_meta_dump.py --limit 50

  # 看 specific turn_id
  python scripts/main_brain_meta_dump.py --turn turn_20260522_113908

  # 仅 skip_alert=yes 的 (主脑拒道歉的轮)
  python scripts/main_brain_meta_dump.py --skip-alert

  # 仅 reaction != voice 的 (主脑选 silent 的轮)
  python scripts/main_brain_meta_dump.py --silent

  # 统计概览 (parse_ok 比例 / skip_alert 占比 / reaction 分布)
  python scripts/main_brain_meta_dump.py --stats
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import List, Dict, Any

AUDIT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'memory_pool', 'main_brain_meta_audit.jsonl'
)


def _load(audit_path: str = AUDIT_PATH) -> List[Dict[str, Any]]:
    if not os.path.exists(audit_path):
        return []
    out: List[Dict[str, Any]] = []
    try:
        with open(audit_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except OSError:
        return []
    return out


def _format_iso(ts: float) -> str:
    if not ts:
        return '?'
    try:
        return time.strftime('%m-%d %H:%M:%S', time.localtime(float(ts)))
    except Exception:
        return '?'


def _print_record(rec: Dict[str, Any], idx: int = 0) -> None:
    iso = _format_iso(rec.get('ts', 0))
    turn = rec.get('turn_id', '?')[-30:]
    ev = rec.get('evidence', []) or []
    ev_str = ','.join(ev[:3]) + (f' (+{len(ev) - 3})' if len(ev) > 3 else '')
    if not ev_str:
        ev_str = '(none)'
    reaction = rec.get('reaction', '?')
    skip_alert = rec.get('skip_alert', False)
    skip_emoji = '🚫' if skip_alert else '✓'
    note = (rec.get('note', '') or '')[:50]
    user_inp = (rec.get('user_input_excerpt', '') or '')[:60]
    reaction_emoji = {
        'voice': '🔊',
        'silent_text': '📝',
        'silence': '🤐',
    }.get(reaction, '?')

    print(f"[{idx:>3}] {iso}  turn={turn}")
    print(f"      🗣️  Sir: {user_inp!r}")
    print(f"      📚 evidence: {ev_str}")
    print(f"      {reaction_emoji} reaction={reaction}  {skip_emoji} skip_alert={'YES' if skip_alert else 'no'}")
    if note:
        print(f"      💭 note: {note}")
    print()


def _stats(records: List[Dict[str, Any]]) -> int:
    if not records:
        print('(无 audit 记录, jarvis 还没跑过含 META 的对话)')
        return 0
    n = len(records)
    n_skip = sum(1 for r in records if r.get('skip_alert'))
    reactions = {}
    for r in records:
        rc = r.get('reaction', '?')
        reactions[rc] = reactions.get(rc, 0) + 1
    n_with_evidence = sum(1 for r in records if r.get('evidence') and r['evidence'] != ['none'])
    avg_ev_per_turn = sum(len(r.get('evidence', []) or []) for r in records) / max(1, n)

    earliest = _format_iso(min(r.get('ts', 0) for r in records))
    latest = _format_iso(max(r.get('ts', 0) for r in records))

    print(f"📊 main_brain_meta_audit 统计")
    print(f"━" * 60)
    print(f"  总轮数: {n}")
    print(f"  时间窗: {earliest} → {latest}")
    print(f"  skip_alert=yes: {n_skip} 轮 ({100 * n_skip / n:.1f}%)  ← 主脑拒道歉次数")
    print(f"  evidence 非空: {n_with_evidence} 轮 ({100 * n_with_evidence / n:.1f}%)  ← 主脑真用证据次数")
    print(f"  平均 evidence/轮: {avg_ev_per_turn:.2f}")
    print(f"  reaction 分布:")
    for rc, ct in sorted(reactions.items(), key=lambda x: -x[1]):
        emoji = {
            'voice': '🔊',
            'silent_text': '📝',
            'silence': '🤐',
        }.get(rc, '?')
        print(f"    {emoji} {rc:<14} {ct} 轮 ({100 * ct / n:.1f}%)")

    # 健康提示
    print()
    print(f"━" * 60)
    if n_skip / n > 0.5:
        print("⚠️ skip_alert=yes 占比 > 50% — 主脑频繁拒道歉, 可能 IntegrityAlert 误判过多, 看 audit jsonl root cause")
    elif n_skip == 0 and n > 20:
        print("ℹ️ 0 轮 skip_alert=yes — 没遇到 false ALERT (好事), 或主脑还没学会用 skip_alert")
    if n_with_evidence / n < 0.3:
        print("⚠️ evidence 非空 < 30% — 主脑很多轮说 'evidence=none', Layer 1 directive 可能被忽略")
    elif n_with_evidence / n > 0.7:
        print("✅ evidence 非空 > 70% — 主脑认真在用 SELF_CHECK, Layer 1 落地良好")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description='main_brain_meta_audit.jsonl CLI dump')
    p.add_argument('--limit', type=int, default=20, help='最近 N 条')
    p.add_argument('--turn', type=str, default='', help='只看 specific turn_id')
    p.add_argument('--skip-alert', action='store_true', help='仅 skip_alert=yes')
    p.add_argument('--silent', action='store_true', help='仅 reaction != voice')
    p.add_argument('--stats', action='store_true', help='统计概览')
    p.add_argument('--audit-path', type=str, default=AUDIT_PATH,
                    help='custom audit path')
    args = p.parse_args()

    records = _load(args.audit_path)
    if not records:
        print(f'(无记录) audit_path={args.audit_path}')
        print('提示: jarvis 跑过含 META directive 的对话才会有记录')
        return 0

    if args.stats:
        return _stats(records)

    # 过滤
    filtered = records
    if args.turn:
        filtered = [r for r in filtered if r.get('turn_id') == args.turn]
    if args.skip_alert:
        filtered = [r for r in filtered if r.get('skip_alert')]
    if args.silent:
        filtered = [r for r in filtered if r.get('reaction') in ('silent_text', 'silence')]

    # 取最近 N 条 (倒序最新先)
    if args.limit > 0 and len(filtered) > args.limit:
        filtered = filtered[-args.limit:]

    if not filtered:
        print('(无匹配记录)')
        return 0

    print(f"━" * 60)
    print(f"显示 {len(filtered)} / {len(records)} 条 main_brain_meta_audit")
    print(f"━" * 60)
    print()
    for i, rec in enumerate(filtered):
        _print_record(rec, i)

    return 0


if __name__ == '__main__':
    sys.exit(main())
