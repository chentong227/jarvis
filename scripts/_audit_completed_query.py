# -*- coding: utf-8 -*-
"""[audit] Check why list_recent_completed_events returns 0."""
import sqlite3

conn = sqlite3.connect('memory_pool/jarvis_memory.db')
cur = conn.cursor()

# raw query
cur.execute("SELECT id, user_intent, timestamp, is_deleted FROM TaskMemories "
            "WHERE user_intent LIKE 'Completed:%' OR user_intent LIKE 'completed:%' "
            "ORDER BY id DESC LIMIT 10")
print('=== rows matching Completed: ===')
for r in cur.fetchall():
    print(f"  id={r[0]} intent={r[1][:50]!r} ts={r[2]!r} is_deleted={r[3]}")

print()
cur.execute("SELECT typeof(timestamp), typeof(is_deleted) FROM TaskMemories LIMIT 1")
print('types:', cur.fetchone())

cur.execute("SELECT timestamp FROM TaskMemories ORDER BY id DESC LIMIT 3")
print('sample timestamps (recent):', cur.fetchall())

cur.execute("SELECT MIN(timestamp), MAX(timestamp) FROM TaskMemories")
print('ts range:', cur.fetchone())
