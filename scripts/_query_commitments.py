import sqlite3, time, os, sys

# 找 hippo db
candidates = [
    'memory_pool/jarvis_memory.db',
    'memory_pool/jarvis_hippocampus.db',
    'memory_pool/hippocampus.db',
    'memory_pool/jarvis_brain.db',
]
db_path = None
for p in candidates:
    if os.path.exists(p):
        db_path = p
        break

if not db_path:
    print("hippo db not found, listing memory_pool/")
    for f in os.listdir('memory_pool'):
        print(" ", f)
    sys.exit(1)

print(f"=== using db: {db_path} ===")
conn = sqlite3.connect(db_path)
c = conn.cursor()

# 表存在?
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print(f"tables: {tables}")

if 'Commitments' not in tables:
    print("!! Commitments table 不存在 !!")
    conn.close()
    sys.exit(2)

# 列出全部
c.execute("SELECT id, description, deadline_ts, nudged, is_deleted, created_at FROM Commitments ORDER BY id DESC LIMIT 30")
rows = c.fetchall()
print(f"\n=== Commitments 表共 {len(rows)} 条最近记录 ===")
for r in rows:
    rid, desc, dl, nudged, deleted, ct = r
    dl_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(dl)) if dl else 'NULL'
    ct_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ct)) if ct else 'NULL'
    print(f"id={rid} desc={desc!r:50} deadline={dl_str} nudged={nudged} del={deleted} created={ct_str}")

# 重点：今天 21:12 前后的记录
print("\n=== 今天 21:00-21:30 之间的记录 ===")
since = time.mktime(time.strptime('2026-05-16 20:00:00', '%Y-%m-%d %H:%M:%S'))
until = time.mktime(time.strptime('2026-05-16 22:30:00', '%Y-%m-%d %H:%M:%S'))
c.execute("SELECT id, description, deadline_ts, nudged, is_deleted, created_at FROM Commitments WHERE created_at > ? AND created_at < ? ORDER BY created_at",
          (since, until))
recent = c.fetchall()
print(f"   {len(recent)} 条")
for r in recent:
    rid, desc, dl, nudged, deleted, ct = r
    dl_str = time.strftime('%H:%M:%S', time.localtime(dl)) if dl else 'NULL'
    ct_str = time.strftime('%H:%M:%S', time.localtime(ct)) if ct else 'NULL'
    print(f"  id={rid} created@{ct_str} -> deadline@{dl_str} nudged={nudged} del={deleted} desc={desc!r}")

conn.close()
