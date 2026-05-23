# -*- coding: utf-8 -*-
"""[audit] 找主脑 18:07 '血压明天' 信息来源."""
import sqlite3
import json

db = sqlite3.connect('memory_pool/jarvis_memory.db')
cur = db.cursor()
cur.execute('SELECT name FROM sqlite_master WHERE type="table"')
tables = [r[0] for r in cur.fetchall()]
print('tables:', tables)
print()

for tbl in ('TaskMemories', 'ProjectTimeline', 'CorrectionMemory', 'Commitments'):
    try:
        cur.execute(f'PRAGMA table_info({tbl})')
        cols = [r[1] for r in cur.fetchall()]
        cur.execute(f'SELECT count(*) FROM {tbl}')
        n = cur.fetchone()[0]
        print(f'-- {tbl} ({n} rows) cols: {cols}')
    except Exception as e:
        print(f'{tbl}: err {e}')
print()

# Commitments 血压
try:
    cur.execute("SELECT * FROM Commitments WHERE description LIKE '%血压%' OR description LIKE '%blood%' ORDER BY id DESC LIMIT 10")
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f'== Commitments 血压 ({len(rows)} hits) ==')
    for r in rows:
        d = dict(zip(cols, r))
        print(' ', d)
except Exception as e:
    print('Commit err:', e)
print()

# TaskMemories 血压
try:
    cur.execute("SELECT * FROM TaskMemories WHERE task_description LIKE '%血压%' OR task_description LIKE '%blood%' OR notes LIKE '%血压%' OR notes LIKE '%blood%' ORDER BY id DESC LIMIT 10")
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f'== TaskMemories 血压 ({len(rows)} hits) ==')
    for r in rows:
        d = dict(zip(cols, r))
        print(' ', {k: str(v)[:150] for k, v in d.items()})
except Exception as e:
    print('Task err:', e)
print()

# ProjectTimeline
try:
    cur.execute("SELECT * FROM ProjectTimeline WHERE event LIKE '%血压%' OR event LIKE '%blood%' ORDER BY id DESC LIMIT 10")
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f'== ProjectTimeline 血压 ({len(rows)} hits) ==')
    for r in rows:
        d = dict(zip(cols, r))
        print(' ', d)
except Exception as e:
    print('Timeline err:', e)

# 全文 grep all tables
print()
print('=== full-text search all tables ===')
for tbl in tables:
    if tbl.startswith('sqlite'):
        continue
    try:
        cur.execute(f'PRAGMA table_info({tbl})')
        cols = [r[1] for r in cur.fetchall()]
        text_cols = [c for c in cols if 'TEXT' in str(c) or c in ('description', 'task_description', 'notes', 'event', 'content')]
        for col in cols:
            try:
                cur.execute(f"SELECT id, {col} FROM {tbl} WHERE {col} LIKE '%血压%' OR {col} LIKE '%blood pressure%' OR {col} LIKE '%pressure%' LIMIT 3")
                rows = cur.fetchall()
                if rows:
                    print(f"  {tbl}.{col} ({len(rows)} hits):")
                    for r in rows:
                        print(f"    id={r[0]} val={str(r[1])[:150]}")
            except Exception:
                pass
    except Exception:
        pass
