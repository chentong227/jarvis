# -*- coding: utf-8 -*-
"""[audit] sir_sleep_streak concern 当前状态."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open('memory_pool/concerns.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

if isinstance(data, dict):
    items = data.items()
else:
    items = [(c.get('id', '?'), c) for c in data]

for cid, c in items:
    if not isinstance(c, dict):
        continue
    if any(t in cid.lower() for t in ('sleep', 'exam', 'medical', 'rest', 'cursor')):
        print('---')
        print(f'id           : {cid}')
        print(f'state        : {c.get("state")}')
        print(f'severity     : {c.get("severity")}')
        print(f'triggers_pro : {c.get("triggers_proactive")}')
        print(f'what_i_watch : {(c.get("what_i_watch") or "")[:100]}')
        print(f'why_i_care   : {(c.get("why_i_care") or "")[:100]}')
        print(f'last_triggered: {c.get("last_triggered")}')
