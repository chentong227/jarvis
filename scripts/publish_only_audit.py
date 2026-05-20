# -*- coding: utf-8 -*-
"""[P2-Gap10 / 2026-05-21 00:00] Publish-Only Audit Script

Scans all sentinel / daemon modules for gate_mode and hard-gate patterns.
Reports current state so Sir can decide which sentinels should retire to
publish-only mode per β.5.0 三维耦合 design.

Usage:
    python scripts/publish_only_audit.py            # text report
    python scripts/publish_only_audit.py --json     # machine-readable

The 6 sentinels Sir is tracking:
  - ProactiveCareEngine (collected: central, scoring-based)
  - SmartNudge (legacy)
  - Conductor (event-funnel scheduler)
  - Wellness (sleep/break monitoring)
  - ReturnSentinel (AFK return greeting)
  - Curiosity (random open-ended pings)
  - NudgeGate (cooldown enforcement)
  - OfferGuard (offer help politeness)

Per β.5.0, target state:
  - ProactiveCareEngine: CENTRAL (集中决策)
  - All others: publish_only (publish candidate, ProactiveCare scores + decides)

This script does not modify sentinels. It only audits and recommends.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys


SENTINEL_FILES = [
    'jarvis_proactive_care.py',
    'jarvis_sentinels.py',
    'jarvis_conductor.py',
    'jarvis_smart_nudge.py',
    'jarvis_return_sentinel.py',
    'jarvis_curiosity.py',
    'jarvis_silence_intel.py',
    'jarvis_routing.py',
]


HARD_GATE_PATTERNS = [
    (r'\bgate_mode\s*=\s*[\'"]hard[\'"]', 'gate_mode=hard'),
    (r'\bif\s+\w+\.fire\(\)', 'direct fire()'),
    (r'\bself\._fire_nudge', 'self._fire_nudge'),
    (r'\b_send_nudge\b', '_send_nudge'),
    (r'\bnudge_gate\s*\.\s*should_fire', 'nudge_gate.should_fire'),
    (r'\bstream_nudge\s*\(', 'direct stream_nudge'),
]

PUBLISH_ONLY_PATTERNS = [
    (r'\bgate_mode\s*=\s*[\'"]publish_only[\'"]', 'gate_mode=publish_only'),
    (r'\bpublish\s*\(.*sir_intent_', 'publish_intent'),
    (r'\bevent_bus\.publish\b', 'bus.publish'),
]


def audit_file(path: str) -> dict:
    if not os.path.exists(path):
        return {'path': path, 'exists': False}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
    except Exception as e:
        return {'path': path, 'exists': True, 'error': str(e)[:100]}

    hard_hits = []
    for pat, label in HARD_GATE_PATTERNS:
        matches = re.findall(pat, src)
        if matches:
            hard_hits.append({'pattern': label, 'count': len(matches)})

    pub_hits = []
    for pat, label in PUBLISH_ONLY_PATTERNS:
        matches = re.findall(pat, src)
        if matches:
            pub_hits.append({'pattern': label, 'count': len(matches)})

    # heuristic 评估 mode
    n_hard = sum(h['count'] for h in hard_hits)
    n_pub = sum(p['count'] for p in pub_hits)
    if n_pub > n_hard * 2:
        mode_estimate = 'mostly_publish_only'
    elif n_hard > n_pub * 2:
        mode_estimate = 'mostly_hard_gate'
    else:
        mode_estimate = 'mixed'

    # recommend
    fname = os.path.basename(path)
    if 'proactive_care' in fname:
        recommended = 'CENTRAL (集中决策, 保持)'
    elif fname in ('jarvis_smart_nudge.py', 'jarvis_conductor.py',
                    'jarvis_curiosity.py', 'jarvis_return_sentinel.py'):
        recommended = 'publish_only (退化为 publish, 由 ProactiveCare 决定)'
    else:
        recommended = 'mixed OK'

    return {
        'path': path,
        'exists': True,
        'hard_gate_hits': hard_hits,
        'publish_only_hits': pub_hits,
        'mode_estimate': mode_estimate,
        'recommended': recommended,
        'file_loc': len(src.splitlines()),
    }


def main():
    p = argparse.ArgumentParser(description='Publish-Only audit for Jarvis sentinels')
    p.add_argument('--json', action='store_true', help='machine-readable JSON')
    args = p.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    results = []
    for fname in SENTINEL_FILES:
        fpath = os.path.join(repo_root, fname)
        results.append(audit_file(fpath))

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    print('=' * 78)
    print('[Publish-Only Audit] β.5.0 三维耦合 — sentinel gate_mode 当前现状')
    print('=' * 78)
    for r in results:
        print()
        if not r.get('exists'):
            print(f"  {os.path.basename(r['path']):35s} : NOT FOUND")
            continue
        print(f"  {os.path.basename(r['path']):35s} : {r['mode_estimate']}")
        print(f"    file LoC: {r['file_loc']}")
        if r['hard_gate_hits']:
            print(f"    hard_gate hits ({sum(h['count'] for h in r['hard_gate_hits'])}):")
            for h in r['hard_gate_hits']:
                print(f"       - {h['pattern']}: {h['count']}x")
        if r['publish_only_hits']:
            print(f"    publish hits ({sum(p['count'] for p in r['publish_only_hits'])}):")
            for ph in r['publish_only_hits']:
                print(f"       - {ph['pattern']}: {ph['count']}x")
        print(f"    \u2192 recommended: {r['recommended']}")

    print()
    print('=' * 78)
    print('Summary:')
    central = [r for r in results if 'CENTRAL' in r.get('recommended', '')]
    should_pub = [r for r in results if 'publish_only' in r.get('recommended', '')]
    print(f"  CENTRAL (collect + decide): {len(central)} sentinel")
    print(f"  Should be publish_only:    {len(should_pub)} sentinel")
    print(f"  Total audited:             {len(results)}")
    print()
    print('Action items (Sir decides):')
    for r in should_pub:
        if 'mostly_hard_gate' in r.get('mode_estimate', ''):
            _name = os.path.basename(r['path'])
            print(f"  [!] {_name}: still mostly hard-gate, "
                  "consider adding publish_intent + retiring gate_mode")


if __name__ == '__main__':
    main()
