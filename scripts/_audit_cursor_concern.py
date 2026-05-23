# -*- coding: utf-8 -*-
"""[temp] 看 sir_cursor_payment concern 详细 state."""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

p = os.path.join('memory_pool', 'concerns.json')
with open(p, 'r', encoding='utf-8') as f:
    data = json.load(f)

items = data if isinstance(data, list) else data.get('concerns', [])
now = time.time()

target = None
for c in items:
    if c.get('id') == 'sir_cursor_payment':
        target = c
        break

if target:
    print('=== sir_cursor_payment ===')
    for k, v in target.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            if isinstance(v, float) and 1700000000 < v < 2000000000:
                age_min = int((now - v) / 60)
                v_fmt = f'{v} ({age_min} min ago)'
            else:
                v_fmt = v
            print(f'  {k:30s}: {str(v_fmt)[:200]}')
        else:
            print(f'  {k:30s}: {type(v).__name__} len={len(v) if hasattr(v, "__len__") else "?"}')
            if isinstance(v, list) and len(v) <= 10:
                for item in v[:5]:
                    print(f'      - {str(item)[:150]}')
            elif isinstance(v, dict):
                for k2, v2 in list(v.items())[:5]:
                    print(f'      .{k2}: {str(v2)[:120]}')
else:
    print('sir_cursor_payment NOT FOUND')

print('\n=== Top 10 active concerns ===')
active = [c for c in items if c.get('state') == 'active']
active.sort(key=lambda c: c.get('severity_dynamic', c.get('severity_d', 0)), reverse=True)
for c in active[:10]:
    cid = c.get('id', '')
    sev = c.get('severity_dynamic', c.get('severity_d', 0))
    nudge_n = c.get('nudge_count', 0)
    last_nudge = c.get('last_nudge_at', 0)
    age = int((now - last_nudge) / 60) if last_nudge > 0 else -1
    print(f'  {cid:35s} sev={sev:.2f} nudges={nudge_n} last_nudge={age}min ago')
