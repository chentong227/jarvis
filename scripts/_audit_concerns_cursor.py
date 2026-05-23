# -*- coding: utf-8 -*-
"""[temp audit] 查 Cursor subscription concern 现状 (Sir 18:42 痛点)."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

p = os.path.join('memory_pool', 'concerns.json')
with open(p, 'r', encoding='utf-8') as f:
    data = json.load(f)

items = data if isinstance(data, list) else data.get('concerns', [])
now = time.time()

print(f"Total concerns: {len(items)}")
active = [c for c in items if c.get('state') == 'active']
print(f"Active: {len(active)}")
print()

# 找 cursor / subscription / payment 相关
target = []
for c in items:
    cid = (c.get('id') or '').lower()
    summary = (c.get('summary') or '').lower()
    if 'cursor' in cid or 'cursor' in summary or 'subscription' in cid or \
       'subscription' in summary or 'payment' in cid or 'payment' in summary:
        target.append(c)

print(f"Cursor-related: {len(target)}")
for c in target:
    print(f"  ID         : {c.get('id')}")
    print(f"  state      : {c.get('state')}")
    print(f"  severity_d : {c.get('severity_dynamic', c.get('severity_d', 0))}")
    print(f"  nudge_count: {c.get('nudge_count', 0)}")
    last_nudge = c.get('last_nudge_at', 0)
    if last_nudge:
        age_min = int((now - last_nudge) / 60)
        print(f"  last_nudge : {age_min} min ago")
    dismissed_count = c.get('dismissed_count', 0)
    last_dismissed = c.get('last_dismissed_at', 0)
    print(f"  dismissed_count: {dismissed_count}")
    if last_dismissed:
        age_dismiss = int((now - last_dismissed) / 60)
        print(f"  last_dismissed: {age_dismiss} min ago")
    print(f"  summary    : {(c.get('summary') or '')[:200]}")
    print(f"  triggered_via: {c.get('triggered_via', '')}")
    print(f"  full keys  : {list(c.keys())}")
    print()
