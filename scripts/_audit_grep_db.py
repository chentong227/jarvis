# -*- coding: utf-8 -*-
"""[Audit / 2026-05-21 09:35] Grep memory.db / hippocampus / STM 找 23:59 / medical 字符串污染.

Sir 09:05 / 09:06 主脑回复带 "23:59 sleep commitment" + "medical examination" — 排查这两字符串
真来源 (是 hallucination 还是真数据).
"""
import sqlite3
import json
from pathlib import Path

DB = Path(__file__).parent.parent / 'memory_pool' / 'jarvis_memory.db'

NEEDLES = ['23:59', '11:59 PM', 'medical', 'examination', '体检', 'fasting', '禁食']


def main():
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print(f"=== Tables: {tables} ===\n")

    for t in tables:
        try:
            cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})").fetchall()]
        except Exception:
            continue
        text_cols = [c for c in cols if c.lower() in ('content', 'description', 'desc', 'text', 'reply', 'utterance', 'action', 'evidence', 'value')]
        if not text_cols:
            continue
        for col in text_cols:
            for needle in NEEDLES:
                try:
                    rows = cur.execute(
                        f"SELECT * FROM {t} WHERE {col} LIKE ? LIMIT 10",
                        (f'%{needle}%',),
                    ).fetchall()
                except Exception:
                    continue
                if rows:
                    print(f"--- [{t}.{col}] '{needle}' → {len(rows)} hits ---")
                    for r in rows:
                        snippet = str(r)[:300]
                        print(f"  {snippet}")
                    print()
    con.close()


if __name__ == '__main__':
    main()
