# -*- coding: utf-8 -*-
"""[temp] grep latest log for cursor / Smart Nudge / proactive_care."""
import glob
import io
import os
import sys

# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

logs = sorted(glob.glob('docs/runtime_logs/jarvis_*.log'), reverse=True)[:5]

KEYWORDS = ['cursor', 'subscription', '订阅', 'payment', 'Smart Nudge',
              'proactive_care', 'ProactiveCare', '18:42', 'Cursor']

for L in logs:
    print(f'\n=== {L} (size: {os.path.getsize(L)}) ===')
    matches = 0
    with open(L, 'r', encoding='utf-8', errors='ignore') as f:
        for i, line in enumerate(f, 1):
            ll = line.lower()
            if any(k.lower() in ll for k in KEYWORDS):
                print(f'[L{i}] {line.rstrip()[:300]}')
                matches += 1
                if matches >= 30:
                    print('... (truncated 30+)')
                    break
    if matches == 0:
        print('  (no matches)')
