#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[P5-fix35-AUDIT / 2026-05-23 11:42] System-wide audit — find BUGs / blindspots.

Sir 真意 (11:27): "排查排查还有没有BUG，边界盲点".

跑全模块 audit:
  1. publish-only 模块 fire frequency (查 'init 了但从没 publish' 类隐患)
  2. mutation receipts 真改了多少 (vs 主脑空头承诺)
  3. directive registry stats — 哪些 fired 0 次 (vocab miss)
  4. PreFlight stats — verdict 分布 (主脑 hallucinate 频率)
  5. ProgressTracker active tracks (是否真用上)
  6. CyclicTask active tasks (是否真用上)
  7. Concerns ledger health (active vs dismissed)
  8. Hippocampus DB stats (TaskMemories / Commitments / 大小)
  9. Vocab files schema check (准则 6 持久化 — 都在 memory_pool/?)
  10. Recent log analysis (latest log 跑模块 publish frequency)

用法:
  python scripts/system_audit.py               # 完整报告
  python scripts/system_audit.py --json        # 机读
  python scripts/system_audit.py --section <n> # 单 section (1-10)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time
import glob

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEM = os.path.join(ROOT, 'memory_pool')
LOGS_DIR = os.path.join(ROOT, 'docs', 'runtime_logs')
sys.path.insert(0, ROOT)


def _section_header(n: int, title: str):
    print("\n" + "=" * 78)
    print(f"  [{n}] {title}")
    print("=" * 78)


def _safe_count_in_logs(pattern: str, max_logs: int = 5) -> int:
    """count occurrences of pattern across most recent logs."""
    logs = sorted(glob.glob(os.path.join(LOGS_DIR, 'jarvis_*.log')),
                    key=os.path.getsize, reverse=True)[:max_logs]
    n = 0
    for lp in logs:
        try:
            with open(lp, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            n += content.count(pattern)
        except Exception:
            continue
    return n


def section_1_publish_modules():
    _section_header(1, "Publish-only modules — fire frequency (top 5 logs)")
    # Use ACTUAL bg_log markers (emoji prefixes), not just etype names.
    # publish to in-memory bus 不写 log; 各模块自带 bg_log marker 才能 grep.
    modules = {
        'AmbientSensor (publish)': '[AmbientSensor]',
        'AmbientSensor (stats)': '[AmbientSensor/Stats]',
        'PhysioProxy': '[PhysioProxy]',
        'CompanionRhythm': '[CompanionRhythm/publish]',
        'ProactiveCare tick': '[ProactiveCare/Health]',
        'ProactiveCare timing': '[ProactiveCare/timing]',
        'IntegrityWatcher report': '[INTEGRITY/Alert',
        'IntegrityWatcher vocab': '[IntegrityWatcher/vocab',
        'PreFlight verdict': '[PreFlight]',
        'CommitmentWatcher': '[CommitmentWatcher]',
        'MutationGateway': '[MemoryGateway]',
        'ScreenVision wake': '[ScreenVision/wake]',
        'ProgressTracker fire': '[ProgressTracker',
        'CyclicTask fire': '[cyclic_task',
        'IntentResolver': '[IntentResolver]',
        'StyleAdjust': '[StyleAdjust]',
        'Gatekeeper Commitment': '[Gatekeeper Commitment]',
        'SoulEvaluator': '[SoulEvaluator]',
        'ClaimTracer/Unverified': '[ClaimTracer/Unverified]',
        'L2 directive inject': '[L2 inject]',
        'STM Summarize': '[STMSummarize]',
        'Reminder fire': '[Reminder]',
    }
    for mod, kw in modules.items():
        n = _safe_count_in_logs(kw)
        flag = '+' if n > 10 else ('?' if n > 0 else '!')
        print(f"  [{flag}] {mod:30s} (marker {kw[:38]:38s}): {n:5d}")


def section_2_mutation_receipts():
    _section_header(2, "Mutation receipts — 主脑真改了多少")
    path = os.path.join(MEM, 'mutation_receipts.jsonl')
    if not os.path.exists(path):
        print("  (no mutation_receipts.jsonl yet)")
        return
    n = 0
    by_layer = {}
    by_source = {}
    cutoff_24h = time.time() - 86400
    n_24h = 0
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    n += 1
                    if r.get('ts', 0) >= cutoff_24h:
                        n_24h += 1
                    layer = r.get('layer_targeted', '?')
                    by_layer[layer] = by_layer.get(layer, 0) + 1
                    src = r.get('source', '?').split(':')[0]
                    by_source[src] = by_source.get(src, 0) + 1
                except Exception:
                    continue
    except Exception as e:
        print(f"  read error: {e}")
        return
    print(f"  total: {n}, last 24h: {n_24h}")
    print(f"  by layer: {dict(sorted(by_layer.items(), key=lambda x: -x[1])[:5])}")
    print(f"  by source: {dict(sorted(by_source.items(), key=lambda x: -x[1])[:5])}")


def section_3_directive_stats():
    _section_header(3, "Directive registry — fired counts (top + 0-fire)")
    path = os.path.join(MEM, 'directive_registry.json')
    if not os.path.exists(path):
        print("  (no directive_registry.json)")
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"  read error: {e}")
        return
    rows = []
    for did, d in data.items():
        if not isinstance(d, dict):
            continue
        rows.append((did, d.get('fired', 0), d.get('priority', 0),
                       d.get('state', '?')))
    rows.sort(key=lambda x: -x[1])
    print(f"  total directives: {len(rows)}")
    print(f"\n  top fired:")
    for did, fired, pri, state in rows[:8]:
        print(f"    {did:38s} fired={fired:6d} pri={pri:3d} state={state}")
    zero_fire = [(did, pri, state) for did, fired, pri, state in rows
                  if fired == 0 and state == 'active']
    if zero_fire:
        print(f"\n  ⚠️ active 但 0 fire ({len(zero_fire)}):")
        for did, pri, state in zero_fire[:8]:
            print(f"    {did:38s} pri={pri:3d}")


def section_4_preflight():
    _section_header(4, "PreFlight stats — 主脑 hallucinate 频率")
    path = os.path.join(MEM, 'preflight_stats.jsonl')
    if not os.path.exists(path):
        print("  (no preflight_stats.jsonl)")
        return
    counts = {'pass': 0, 'edit': 0, 'scrap': 0, 'unknown': 0}
    issues_keywords = {}
    n = 0
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    n += 1
                    v = r.get('verdict', 'unknown')
                    counts[v] = counts.get(v, 0) + 1
                    for iss in r.get('issues', []):
                        if 'UNSOLICITED' in str(iss).upper():
                            issues_keywords['unsolicited'] = issues_keywords.get('unsolicited', 0) + 1
                        if 'HALLUCINATION' in str(iss).upper():
                            issues_keywords['hallucination'] = issues_keywords.get('hallucination', 0) + 1
                        if 'TONE' in str(iss).upper():
                            issues_keywords['tone'] = issues_keywords.get('tone', 0) + 1
                except Exception:
                    continue
    except Exception as e:
        print(f"  read error: {e}")
        return
    print(f"  total: {n}")
    print(f"  verdicts: {counts}")
    if n:
        edit_pct = (counts['edit'] + counts['scrap']) * 100 / n
        print(f"  edit/scrap rate: {edit_pct:.1f}%  (健康 < 15%)")
    if issues_keywords:
        print(f"  issue patterns: {issues_keywords}")


def section_5_progress_tracker():
    _section_header(5, "ProgressTracker — active tracks")
    path = os.path.join(MEM, 'progress_logs.json')
    if not os.path.exists(path):
        print("  (no progress_logs.json — 主脑还没用过)")
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"  read error: {e}")
        return
    tracks = data.get('tracks', {})
    active = [t for t in tracks.values()
                if isinstance(t, dict) and t.get('state') == 'active']
    print(f"  total: {len(tracks)}, active: {len(active)}")
    for t in active:
        cur = t.get('current', 0)
        tgt = t.get('target', 0)
        unit = t.get('unit', '')
        print(f"  - {t.get('track_id')}: {cur}/{tgt} {unit} "
                f"({t.get('kind')})")


def section_6_cyclic_tasks():
    _section_header(6, "CyclicTask — active cycles")
    path = os.path.join(MEM, 'cyclic_task_protocol.json')
    if not os.path.exists(path):
        print("  (no cyclic_task_protocol.json — 主脑还没用过)")
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"  read error: {e}")
        return
    tasks = data.get('tasks', [])
    active = [t for t in tasks
                if isinstance(t, dict) and t.get('state') == 'active']
    print(f"  total: {len(tasks)}, active: {len(active)}")
    for t in active:
        n_fires = len(t.get('fire_ids', []))
        print(f"  - {t.get('task_id')}: every {t.get('cycle_minutes')}min "
                f"{t.get('start_iso')} → {t.get('end_iso')} ({n_fires} fires)")


def section_7_concerns():
    _section_header(7, "Concerns ledger — health")
    path = os.path.join(MEM, 'concerns.json')
    if not os.path.exists(path):
        print("  (no concerns.json)")
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"  read error: {e}")
        return
    concerns = data.get('concerns', {}) or data
    if isinstance(concerns, list):
        items = concerns
    else:
        items = concerns.values() if isinstance(concerns, dict) else []
    n_total = len(list(items))
    items = (concerns if isinstance(concerns, list)
              else list(concerns.values())
              if isinstance(concerns, dict) else [])
    n_active = sum(1 for c in items
                     if isinstance(c, dict)
                     and c.get('triggers_proactive', False)
                     and c.get('severity', 0) > 0.3)
    n_dismissed = sum(1 for c in items
                        if isinstance(c, dict)
                        and not c.get('triggers_proactive', False))
    print(f"  total concerns: {n_total}")
    print(f"  active (severity > 0.3 + triggers_proactive): {n_active}")
    print(f"  dismissed (triggers=False): {n_dismissed}")


def section_8_hippocampus():
    _section_header(8, "Hippocampus DB stats")
    db_path = os.path.join(MEM, 'jarvis_memory.db')
    if not os.path.exists(db_path):
        print("  (no jarvis_memory.db)")
        return
    try:
        import sqlite3
        size_mb = os.path.getsize(db_path) / 1024 / 1024
        print(f"  size: {size_mb:.1f} MB")
        conn = sqlite3.connect(db_path, timeout=5.0)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM TaskMemories")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM TaskMemories WHERE is_deleted=0")
        active = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM TaskMemories WHERE is_future_task=1 AND is_deleted=0")
        future = cur.fetchone()[0]
        try:
            cur.execute("SELECT COUNT(*) FROM Commitments WHERE is_deleted=0")
            commitments = cur.fetchone()[0]
        except Exception:
            commitments = '?'
        print(f"  TaskMemories: {total} total / {active} active / {future} future")
        print(f"  Commitments: {commitments}")
        conn.close()
    except Exception as e:
        print(f"  error: {e}")


def section_9_vocab_persistence():
    _section_header(9, "Vocab persistence (准则 6 — 都在 memory_pool/?)")
    files = sorted(glob.glob(os.path.join(MEM, '*_vocab.json')))
    base_files = [f for f in files
                    if os.path.basename(f).startswith('_base_')]
    spec_files = [f for f in files
                    if not os.path.basename(f).startswith('_base_')]
    print(f"  total vocab files: {len(files)}")
    print(f"  _base_*: {len(base_files)} (P5-fix35-BUG#6 抽出)")
    print(f"  specific: {len(spec_files)}")
    for f in spec_files[:15]:
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            patterns = data.get('patterns', [])
            if patterns and isinstance(patterns[0], dict):
                kws = []
                for p in patterns:
                    kws.extend(p.get('keywords', []))
                n = len(kws)
            else:
                n = len(patterns) if isinstance(patterns, list) else 0
            print(f"  - {os.path.basename(f):44s}: {n} keywords")
        except Exception as e:
            print(f"  - {os.path.basename(f):44s}: read error {e}")


def section_10_recent_log_summary():
    _section_header(10, "Latest log summary")
    logs = sorted(glob.glob(os.path.join(LOGS_DIR, 'jarvis_*.log')),
                    key=os.path.getmtime, reverse=True)
    if not logs:
        print("  (no logs)")
        return
    biggest_recent = None
    for lp in logs[:10]:
        if os.path.getsize(lp) > 50 * 1024:
            biggest_recent = lp
            break
    if not biggest_recent:
        print("  (no recent log > 50KB)")
        return
    sz = os.path.getsize(biggest_recent) / 1024
    print(f"  log: {os.path.basename(biggest_recent)} ({sz:.0f} KB)")
    try:
        with open(biggest_recent, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception as e:
        print(f"  read error: {e}")
        return
    # Markers to track
    markers = {
        'L2 inject (directive fire)': '🧭 [L2 inject]',
        'PreFlight verdict=edit': 'verdict=edit',
        'PreFlight verdict=scrap': 'verdict=scrap',
        'INTEGRITY/Alert inject': '🩹 [INTEGRITY/Alert inject]',
        'INTEGRITY/Alert skip': '🛑 [INTEGRITY/Alert skip]',
        'ClaimTracer/Unverified': 'ClaimTracer/Unverified',
        'WatchTask/RegisterFail': 'WatchTask/RegisterFail',
        'Malformed FAST_CALL': 'Malformed FAST_CALL',
        'AmbientSensor publish': '🎵 [AmbientSensor]',
        'AmbientSensor stats': '🎵 [AmbientSensor/Stats]',
    }
    for label, marker in markers.items():
        n = content.count(marker)
        flag = '+' if n > 0 else '-'
        print(f"  [{flag}] {label:40s}: {n}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--section', type=int, default=0,
                     help='Run only one section (1-10)')
    p.add_argument('--json', action='store_true',
                     help='Output as JSON (TODO)')
    args = p.parse_args()

    print()
    print("█" * 78)
    print("█" + " " * 76 + "█")
    print("█" + "  JARVIS SYSTEM AUDIT REPORT".center(76) + "█")
    print("█" + f"  generated {time.strftime('%Y-%m-%d %H:%M:%S')}".center(76) + "█")
    print("█" + " " * 76 + "█")
    print("█" * 78)

    sections = [
        section_1_publish_modules,
        section_2_mutation_receipts,
        section_3_directive_stats,
        section_4_preflight,
        section_5_progress_tracker,
        section_6_cyclic_tasks,
        section_7_concerns,
        section_8_hippocampus,
        section_9_vocab_persistence,
        section_10_recent_log_summary,
    ]
    if args.section > 0 and args.section <= len(sections):
        sections[args.section - 1]()
    else:
        for s in sections:
            try:
                s()
            except Exception as e:
                print(f"  section error: {e}")
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
