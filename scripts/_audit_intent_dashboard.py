# -*- coding: utf-8 -*-
import json
import os

p = os.path.join('memory_pool', 'intent_to_tool_map.json')
if not os.path.exists(p):
    print('NOT FOUND:', p)
    raise SystemExit(0)

with open(p, 'r', encoding='utf-8') as f:
    data = json.load(f)

intents = data.get('intents', [])
print('Total intents:', len(intents))
print()
print('=== dashboard 相关 ===')
for it in intents:
    iid = it.get('id', '')
    tool = it.get('tool', '')
    state = it.get('state', '')
    if 'dashboard' in iid.lower() or 'dashboard' in (tool or '').lower():
        print(f'  id={iid} tool={tool} state={state}')
        triggers = it.get('triggers', [])
        if triggers:
            print(f'    triggers: {triggers[:5]}')

print()
print('=== 所有 active intents (前 20) ===')
n = 0
for it in intents:
    if it.get('state', 'active') == 'active':
        n += 1
        if n <= 20:
            print(f'  {it.get("id"):<35} → {it.get("tool")}')
print(f'(active total: {n})')
