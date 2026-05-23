# -*- coding: utf-8 -*-
"""[audit] grep '血压咨询' / 'blood pressure' across all memory stores."""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KW = ['\u8840\u538b', 'blood pressure', 'bp consult', 'consultation']


def _has_kw(s):
    s = str(s).lower()
    for k in KW:
        if k.lower() in s:
            return True
    return False


print('=== STM (last 30 turns) ===')
try:
    p = 'memory_pool/stm_recent.jsonl'
    with open(p, 'r', encoding='utf-8') as f:
        for ln in f.readlines()[-30:]:
            if _has_kw(ln):
                print(ln.strip()[:200])
except Exception as e:
    print(f'stm err: {e}')

print()
print('=== concerns ===')
try:
    with open('memory_pool/concerns.json', 'r', encoding='utf-8') as f:
        d = json.load(f)
    for c in (d.get('concerns') or []):
        if _has_kw(c):
            print(f"  {c.get('id', '?')}: sev={c.get('severity', 0)} watch={c.get('what_i_watch', '')[:80]}")
except Exception as e:
    print(f'concerns err: {e}')

print()
print('=== commitments db ===')
try:
    db = sqlite3.connect('memory_pool/jarvis_memory.db')
    cur = db.cursor()
    cur.execute('SELECT name FROM sqlite_master WHERE type="table"')
    tables = [r[0] for r in cur.fetchall()]
    print(f'tables: {tables[:15]}')
    if 'commitments' in tables:
        cur.execute('SELECT id, description, deadline, completed FROM commitments ORDER BY id DESC LIMIT 30')
        for r in cur.fetchall():
            if _has_kw(r[1]):
                print(f"  id={r[0]} desc={r[1][:80]!r} deadline={r[2]} completed={r[3]}")
    if 'reminders' in tables:
        cur.execute('SELECT * FROM reminders ORDER BY id DESC LIMIT 30')
        for r in cur.fetchall():
            if _has_kw(str(r)):
                print(f"  reminder: {r}")
except Exception as e:
    print(f'db err: {e}')

print()
print('=== mutation_receipts (last 50) ===')
try:
    p = 'memory_pool/mutation_receipts.jsonl'
    with open(p, 'r', encoding='utf-8') as f:
        for ln in f.readlines()[-50:]:
            if _has_kw(ln):
                d = json.loads(ln)
                print(f"  {d.get('ts_iso', '?')} field={d.get('field_path', '?')} new={str(d.get('new_value', ''))[:80]}")
except Exception as e:
    print(f'mr err: {e}')

print()
print('=== promise_log ===')
try:
    with open('memory_pool/jarvis_promise_log.json', 'r', encoding='utf-8') as f:
        d = json.load(f)
    for p in (d.get('promises') or []):
        if _has_kw(p):
            print(f"  {p}")
except Exception as e:
    print(f'promise err: {e}')

print()
print('=== sir_milestones ===')
try:
    with open('memory_pool/sir_milestones.json', 'r', encoding='utf-8') as f:
        d = json.load(f)
    for m in (d.get('milestones') or []):
        if _has_kw(m):
            print(f"  {m}")
except Exception as e:
    print(f'milestone err: {e}')
