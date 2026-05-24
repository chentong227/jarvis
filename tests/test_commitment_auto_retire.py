# -*- coding: utf-8 -*-
"""[Sir 真测 BUG-3 治本 / 2026-05-24] test_commitment_auto_retire — 过期承诺 retire 验证

测试覆盖:
  1. CLI scripts/commitment_retire_overdue.py: dry-run + 真 retire
  2. SWM TTL/salience 注册到位 (gaming_mode_* + commitment_retired)
"""
from __future__ import annotations
import os
import sys
import json
import time
import sqlite3
import subprocess
import tempfile
import shutil
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def tmp_db_and_plog(tmp_path, monkeypatch):
    """造临时 SQLite Commitments + PromiseLog json. 不影响真数据."""
    db_path = tmp_path / 'jarvis_memory.db'
    plog_path = tmp_path / 'jarvis_promise_log.json'

    # SQLite Commitments
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute('''CREATE TABLE Commitments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        description TEXT,
        deadline_ts REAL,
        grace_minutes INTEGER DEFAULT 2,
        source_text TEXT,
        created_at REAL,
        nudged INTEGER DEFAULT 0,
        is_deleted INTEGER DEFAULT 0
    )''')
    now = time.time()
    # 3 老条 (deadline 24h+ 前)
    for i, hours_ago in enumerate([72, 48, 24]):
        cur.execute(
            'INSERT INTO Commitments (description, deadline_ts, created_at, nudged, is_deleted) '
            'VALUES (?, ?, ?, ?, ?)',
            (f'old commitment {i}', now - hours_ago * 3600, now - hours_ago * 3600, 0, 0)
        )
    # 1 新条 (deadline 1h 后, 不该 retire)
    cur.execute(
        'INSERT INTO Commitments (description, deadline_ts, created_at, nudged, is_deleted) '
        'VALUES (?, ?, ?, ?, ?)',
        ('future commitment', now + 3600, now, 0, 0)
    )
    conn.commit()
    conn.close()

    # PromiseLog
    plog = {
        'p_old1': {
            'id': 'p_old1', 'description': 'sleep early', 'kind': 'commitment',
            'deadline_str': time.strftime('%Y-%m-%d %H:%M:%S',
                                              time.localtime(now - 48 * 3600)),
            'state': 'pending', 'evidence': [], 'registered_at': now - 48 * 3600,
            'fulfilled_at': 0.0,
        },
        'p_future': {
            'id': 'p_future', 'description': 'future task', 'kind': 'commitment',
            'deadline_str': time.strftime('%Y-%m-%d %H:%M:%S',
                                              time.localtime(now + 3600)),
            'state': 'pending', 'evidence': [], 'registered_at': now,
            'fulfilled_at': 0.0,
        },
    }
    with open(plog_path, 'w', encoding='utf-8') as f:
        json.dump(plog, f, indent=2, ensure_ascii=False)

    return {
        'db_path': str(db_path),
        'plog_path': str(plog_path),
        'tmp_path': str(tmp_path),
        'now': now,
    }


def _patch_paths_in_script(script_text: str, db_path: str, plog_path: str) -> str:
    """替换 script 里的硬编码路径为 tmp 路径."""
    db_path_p = db_path.replace('\\', '\\\\')
    plog_path_p = plog_path.replace('\\', '\\\\')
    s = script_text.replace(
        "os.path.join(here, 'memory_pool', 'jarvis_memory.db')",
        f"r'{db_path}'",
    )
    s = s.replace(
        "os.path.join(here, 'memory_pool', 'jarvis_promise_log.json')",
        f"r'{plog_path}'",
    )
    return s


def test_retire_cli_dry_run(tmp_db_and_plog):
    """CLI --dry-run 不写文件, 只 preview."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_src = os.path.join(here, 'scripts', 'commitment_retire_overdue.py')
    with open(script_src, 'r', encoding='utf-8') as f:
        src = f.read()
    patched = _patch_paths_in_script(
        src, tmp_db_and_plog['db_path'], tmp_db_and_plog['plog_path']
    )
    tmp_script = os.path.join(tmp_db_and_plog['tmp_path'], 'cmd.py')
    with open(tmp_script, 'w', encoding='utf-8') as f:
        f.write(patched)
    res = subprocess.run(
        [sys.executable, tmp_script, '--hours', '6', '--dry-run'],
        capture_output=True, text=True, encoding='utf-8',
    )
    assert res.returncode == 0
    assert 'overdue: 3' in res.stdout
    assert 'DRY-RUN' in res.stdout

    # 验 SQLite + PromiseLog 没动
    conn = sqlite3.connect(tmp_db_and_plog['db_path'])
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM Commitments WHERE is_deleted=0")
    assert cur.fetchone()[0] == 4  # 3 old + 1 future, 全 active
    conn.close()
    with open(tmp_db_and_plog['plog_path'], 'r', encoding='utf-8') as f:
        plog = json.load(f)
    assert plog['p_old1']['state'] == 'pending'  # 未 retire


def test_retire_cli_real(tmp_db_and_plog):
    """CLI 真 retire: SQLite mark is_deleted + PromiseLog mark fulfilled."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_src = os.path.join(here, 'scripts', 'commitment_retire_overdue.py')
    with open(script_src, 'r', encoding='utf-8') as f:
        src = f.read()
    patched = _patch_paths_in_script(
        src, tmp_db_and_plog['db_path'], tmp_db_and_plog['plog_path']
    )
    tmp_script = os.path.join(tmp_db_and_plog['tmp_path'], 'cmd.py')
    with open(tmp_script, 'w', encoding='utf-8') as f:
        f.write(patched)
    res = subprocess.run(
        [sys.executable, tmp_script, '--hours', '6'],
        capture_output=True, text=True, encoding='utf-8',
    )
    assert res.returncode == 0
    assert 'mark is_deleted: 3' in res.stdout
    assert 'mark fulfilled: 1' in res.stdout

    # 验 SQLite: 3 old → is_deleted=1, future 不变
    conn = sqlite3.connect(tmp_db_and_plog['db_path'])
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM Commitments WHERE is_deleted=0")
    assert cur.fetchone()[0] == 1  # 仅 future 还 active
    cur.execute("SELECT description FROM Commitments WHERE is_deleted=0")
    assert cur.fetchone()[0] == 'future commitment'
    conn.close()

    # 验 PromiseLog: p_old1 fulfilled, p_future pending
    with open(tmp_db_and_plog['plog_path'], 'r', encoding='utf-8') as f:
        plog = json.load(f)
    assert plog['p_old1']['state'] == 'fulfilled'
    assert plog['p_old1']['fulfilled_at'] > 0
    # 验 evidence 加了 retire reason
    evidence = plog['p_old1'].get('evidence', [])
    assert any(e.get('kind') == 'auto_retire_overdue' for e in evidence)
    # future 不动
    assert plog['p_future']['state'] == 'pending'


def test_retire_cli_no_overdue(tmp_db_and_plog):
    """CLI --hours 1000 → 没过期 1000h 的, retire 0 条."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_src = os.path.join(here, 'scripts', 'commitment_retire_overdue.py')
    with open(script_src, 'r', encoding='utf-8') as f:
        src = f.read()
    patched = _patch_paths_in_script(
        src, tmp_db_and_plog['db_path'], tmp_db_and_plog['plog_path']
    )
    tmp_script = os.path.join(tmp_db_and_plog['tmp_path'], 'cmd.py')
    with open(tmp_script, 'w', encoding='utf-8') as f:
        f.write(patched)
    res = subprocess.run(
        [sys.executable, tmp_script, '--hours', '1000'],
        capture_output=True, text=True, encoding='utf-8',
    )
    assert res.returncode == 0
    assert '无过期承诺' in res.stdout or 'overdue: 0' in res.stdout


def test_swm_etype_registered():
    """gaming_mode_activated / gaming_mode_ended / commitment_retired 注册了 TTL + salience."""
    from jarvis_utils import _GLOBAL_EVENT_BUS, ConversationEventBus
    bus = ConversationEventBus()
    # 调 publish 不 raise (= etype 已注册 TTL/salience)
    for etype in ('gaming_mode_activated', 'gaming_mode_ended', 'commitment_retired'):
        bus.publish(
            etype=etype,
            description=f'test {etype}',
            source='test',
        )
    # 看 events 真进了 bus
    events = bus.recent_events(within_seconds=60)
    etypes_seen = [e['type'] for e in events]
    assert 'gaming_mode_activated' in etypes_seen
    assert 'gaming_mode_ended' in etypes_seen
    assert 'commitment_retired' in etypes_seen


def test_gaming_swm_salience_high_for_activated():
    """gaming_mode_activated salience >= 0.7 (主脑必看)."""
    from jarvis_utils import ConversationEventBus
    bus = ConversationEventBus()
    bus.publish(etype='gaming_mode_activated', description='test', source='test')
    events = bus.recent_events(within_seconds=60)
    e = next(e for e in events if e['type'] == 'gaming_mode_activated')
    assert e['salience'] >= 0.7
