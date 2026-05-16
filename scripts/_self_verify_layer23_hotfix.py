# -*- coding: utf-8 -*-
"""[P0+20-β.2.3 / 2026-05-17] 自动验证 β.2.4 老路径退役 + β.2.3 Layer 3 + commitment hotfix

不需要 Sir 真机启动 Jarvis 主进程。覆盖所有"不靠主脑 LLM 的功能正确性"check。
跑完输出 PASS / FAIL 清单。

用法：
    python scripts/_self_verify_layer23_hotfix.py
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time


if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        os.system('chcp 65001 > nul 2>&1')
    except Exception:
        pass


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


CHECKS = []  # [(name, status, detail)]


def _check(name: str, fn):
    try:
        fn()
        CHECKS.append((name, 'PASS', ''))
    except AssertionError as e:
        CHECKS.append((name, 'FAIL', str(e)))
    except Exception as e:
        CHECKS.append((name, 'ERROR', f"{type(e).__name__}: {str(e)[:200]}"))


# ============================================================
# 1. nerve / soul / attention modules import 不破
# ============================================================
def _t1_module_imports():
    import jarvis_nerve  # noqa: F401
    import jarvis_attention  # noqa: F401
    import jarvis_relational  # noqa: F401
    import jarvis_concerns  # noqa: F401
    import jarvis_self_anchor  # noqa: F401
    import jarvis_commitment_watcher  # noqa: F401
    import jarvis_smart_nudge  # noqa: F401
    import jarvis_conductor  # noqa: F401
    import jarvis_sentinels  # noqa: F401


# ============================================================
# 2. resolve_worker_attr helper 工作正确（β.2.4 hotfix）
# ============================================================
def _t2_resolve_worker_attr():
    from jarvis_utils import resolve_worker_attr

    class _DirectNerve:
        hippocampus = 'DIRECT_HIPPO'

    class _WrappedNerve:
        hippocampus = 'WRAPPED_HIPPO'

    class _LegacyWorker:
        pass

    # 新路径优先
    n = _DirectNerve()
    n.jarvis = _WrappedNerve()
    assert resolve_worker_attr(n, 'hippocampus') == 'DIRECT_HIPPO'

    # 旧路径回退
    w = _LegacyWorker()
    w.jarvis = _WrappedNerve()
    assert resolve_worker_attr(w, 'hippocampus') == 'WRAPPED_HIPPO'

    # None worker
    assert resolve_worker_attr(None, 'hippocampus') is None

    # 双路径都无
    class _Empty: pass
    assert resolve_worker_attr(_Empty(), 'hippocampus') is None


# ============================================================
# 3. 静态扫无残留 self.worker.jarvis.X
# ============================================================
def _t3_no_residue():
    pattern = re.compile(r'self\.worker\.jarvis\.\w+')
    offenders = []
    for fname in os.listdir(REPO_ROOT):
        if not fname.startswith('jarvis_') or not fname.endswith('.py'):
            continue
        fpath = os.path.join(REPO_ROOT, fname)
        with open(fpath, encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                stripped = line.lstrip()
                if stripped.startswith('#') or '`self.worker.jarvis' in line:
                    continue
                if pattern.search(line):
                    offenders.append(f"{fname}:{i}")
    assert not offenders, f"残留 self.worker.jarvis.X: {offenders}"


# ============================================================
# 4. SoulRouter 只剩 projects / progression chapter
# ============================================================
def _t4_soul_router_chapters():
    from jarvis_routing import SoulRouter
    profile = {
        'active_projects': ['Project A'],
        'our_inside_jokes': ['joke 1', 'joke 2'],  # 应被忽略
        'significant_milestones': ['ms 1'],         # 应被忽略
        'skill_progression': [{'skill': 'rust'}],
    }
    router = SoulRouter(profile)
    assert 'inside_jokes' not in router.chapters, "SoulRouter 仍含 inside_jokes chapter"
    assert 'milestones' not in router.chapters, "SoulRouter 仍含 milestones chapter"
    assert 'projects' in router.chapters
    assert 'progression' in router.chapters


# ============================================================
# 5. memory_core._load_profile_jokes 改读 relational_state
# ============================================================
def _t5_humor_engine_source():
    """读源码静态检查 _load_profile_jokes 用了 jarvis_relational.get_default_store"""
    fpath = os.path.join(REPO_ROOT, 'jarvis_memory_core.py')
    with open(fpath, encoding='utf-8') as f:
        content = f.read()
    # 应不再 open sir_profile.json 读 our_inside_jokes
    bad_pattern = re.compile(
        r"_load_profile_jokes.*?open\(.*?sir_profile\.json",
        re.DOTALL,
    )
    assert not bad_pattern.search(content[:8000]), \
        "_load_profile_jokes 仍在读 sir_profile.json"
    # 应改读 relational_state
    assert 'from jarvis_relational import get_default_store' in content, \
        "_load_profile_jokes 未引入 jarvis_relational"


# ============================================================
# 6. SoulArchivistSentinel prompt 含 proposed_* 字段
# ============================================================
def _t6_sentinel_prompt():
    fpath = os.path.join(REPO_ROOT, 'jarvis_sentinels.py')
    with open(fpath, encoding='utf-8') as f:
        content = f.read()
    assert 'proposed_inside_jokes' in content, \
        "sentinel prompt 缺 proposed_inside_jokes 字段"
    assert 'proposed_shared_history_threads' in content, \
        "sentinel prompt 缺 proposed_shared_history_threads 字段"
    assert 'deprecated' in content, \
        "sentinel prompt 未明确告诉 LLM 老字段 deprecated"
    assert "new_profile.pop('our_inside_jokes'" in content, \
        "sentinel 未防御性 pop 老字段（兼容 LLM 旧习惯输出）"
    assert 'propose_inside_joke' in content, \
        "sentinel 未调 propose_inside_joke"
    assert 'write_review_queue' in content, \
        "sentinel 未调 write_review_queue"


# ============================================================
# 7. Layer 3 attention 不再含 PENDING FOLLOWUPS 段
# ============================================================
def _t7_attention_no_pending_followups():
    from jarvis_attention import build_attention_block
    from jarvis_relational import RelationalStateStore, UnfinishedBusiness
    s = RelationalStateStore(persist_path=tempfile.mktemp(suffix='.json'))
    s.add_unfinished(UnfinishedBusiness(
        id='u1', topic='study', next_touch_due=time.time() - 100
    ))
    block = build_attention_block(
        concerns_ledger=None, relational_state=s,
        user_input='some long enough input for current focus to show'
    )
    assert 'PENDING FOLLOWUPS' not in block, \
        "Layer 3 attention 仍含 PENDING FOLLOWUPS（与 Layer 2 重复）"
    assert 'study' not in block, \
        "Layer 3 attention 仍含 unfinished 内容 'study'"


# ============================================================
# 8. RelationalStateStore review queue 全套路径
# ============================================================
def _t8_review_queue():
    from jarvis_relational import (
        RelationalStateStore, InsideJoke, STATE_REVIEW, STATE_ACTIVE,
    )
    tmp = tempfile.mktemp(suffix='.json')
    review_tmp = tempfile.mktemp(suffix='.json')
    s = RelationalStateStore(persist_path=tmp, review_path=review_tmp)
    j = InsideJoke(id='j1', phrase='auto proposed phrase')
    assert s.propose_inside_joke(j)
    assert s.get_inside_joke('j1').state == STATE_REVIEW
    assert len(s.list_inside_jokes()) == 0  # 不入 active
    assert len(s.list_inside_jokes_review()) == 1
    assert s.to_prompt_block() == ''  # 不注入 prompt

    # write_review_queue 写盘
    assert s.write_review_queue()
    assert os.path.exists(review_tmp)
    with open(review_tmp, encoding='utf-8') as f:
        data = json.load(f)
    assert len(data['inside_jokes']) == 1
    assert data['inside_jokes'][0]['id'] == 'j1'

    # activate
    kind = s.activate_from_review('j1')
    assert kind == 'joke'
    assert s.get_inside_joke('j1').state == STATE_ACTIVE

    for p in (tmp, review_tmp):
        if os.path.exists(p):
            os.unlink(p)


# ============================================================
# 9. Migration script dry-run + apply
# ============================================================
def _t9_migration_script():
    script_path = os.path.join(REPO_ROOT, 'scripts', 'migrate_profile_to_relational.py')
    # 构造临时 profile + relational
    pf = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w', encoding='utf-8')
    json.dump({
        'core_philosophy': 'placeholder',
        'our_inside_jokes': ['test joke A', 'test joke B'],
        'significant_milestones': ['ms X'],
    }, pf, ensure_ascii=False)
    pf.close()
    rf = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w', encoding='utf-8')
    rf.close()
    os.unlink(rf.name)

    try:
        # dry-run
        r = subprocess.run(
            [sys.executable, script_path,
             '--profile-path', pf.name, '--relational-path', rf.name],
            capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=20,
        )
        assert r.returncode == 0, f"dry-run returncode={r.returncode} stderr={r.stderr}"
        assert 'DRY-RUN' in r.stdout
        assert not os.path.exists(rf.name), "dry-run 不应写盘但写了"

        # --apply
        r2 = subprocess.run(
            [sys.executable, script_path,
             '--profile-path', pf.name, '--relational-path', rf.name,
             '--apply'],
            capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=20,
        )
        assert r2.returncode == 0
        assert os.path.exists(rf.name)
        with open(rf.name, encoding='utf-8') as f:
            d = json.load(f)
        assert len(d['inside_jokes']) == 2, f"jokes count={len(d['inside_jokes'])}"
        assert len(d['shared_history_threads']) == 1, \
            f"threads count={len(d['shared_history_threads'])}"
    finally:
        for p in (pf.name, rf.name):
            if os.path.exists(p):
                os.unlink(p)
        d_dir = os.path.dirname(pf.name)
        for f in os.listdir(d_dir):
            if f.startswith(os.path.basename(pf.name)) and '.bak.' in f:
                try:
                    os.unlink(os.path.join(d_dir, f))
                except Exception:
                    pass


# ============================================================
# 10. Commitment 持久化 end-to-end：模拟 add_commitment 调用 → SQLite 有行
#     这是 Sir 23:38 BUG 的最关键验证（_get_hippo 必须能拿到 hippocampus）
# ============================================================
def _t10_commitment_e2e_sqlite_write():
    from jarvis_hippocampus import Hippocampus
    from jarvis_commitment_watcher import CommitmentWatcher

    # 临时 SQLite DB
    tmp_db_fd, tmp_db_path = tempfile.mkstemp(suffix='.db')
    os.close(tmp_db_fd)
    if os.path.exists(tmp_db_path):
        os.unlink(tmp_db_path)
    try:
        hippo = Hippocampus(db_path=tmp_db_path, key_router=None)

        # 模拟 P0+19 split 后的 worker：CentralNerve 直持 .hippocampus
        class _FakeNerve:
            short_term_memory = []
        fake_nerve = _FakeNerve()
        fake_nerve.hippocampus = hippo

        cw = CommitmentWatcher.__new__(CommitmentWatcher)
        cw.worker = fake_nerve
        cw.commitments = []
        cw._lock = __import__('threading').Lock()

        # 直接调 hippocampus.add_commitment_row（bypass extract 正则）
        new_id = hippo.add_commitment_row(
            description='go to bed',
            deadline_ts=time.time() + 3600,
            grace_minutes=10,
            source_text="I'll go to bed at 11pm",
            created_at=time.time(),
        )
        assert new_id >= 1, f"add_commitment_row returned {new_id} (expect >=1)"

        # 验 _get_hippo 找到 hippocampus（这是 BUG 修复的关键）
        hippo_via_cw = cw._get_hippo()
        assert hippo_via_cw is hippo, \
            f"_get_hippo 没找到 hippocampus (返回 {hippo_via_cw})"

        # sqlite3 查 row
        conn = sqlite3.connect(tmp_db_path)
        cur = conn.cursor()
        cur.execute('SELECT id, description FROM Commitments')
        rows = cur.fetchall()
        conn.close()
        assert len(rows) == 1, f"Commitments rows={len(rows)} expect 1"
        assert rows[0][0] == 1, f"id={rows[0][0]} expect 1"
        assert 'go to bed' in rows[0][1]
    finally:
        if os.path.exists(tmp_db_path):
            try:
                os.unlink(tmp_db_path)
            except Exception:
                pass


# ============================================================
# 11. CLI --review 在空 store 上不抛
# ============================================================
def _t11_cli_review_empty():
    script_path = os.path.join(REPO_ROOT, 'scripts', 'relational_dump.py')
    tmp = tempfile.mktemp(suffix='.json')
    try:
        r = subprocess.run(
            [sys.executable, script_path,
             '--persist-path', tmp, '--review'],
            capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=15,
        )
        assert r.returncode == 0, f"--review returncode={r.returncode}"
        assert 'REVIEW' in r.stdout.upper() or '空' in r.stdout
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ============================================================
# 12. CentralNerve __init__ banner 输出 4 个 Layer ready 字符串
#     不真启 Jarvis 主进程，只验证 module level imports 后 bg_log 调用链可达
# ============================================================
def _t12_layer_banners_in_source():
    """静态扫 jarvis_central_nerve.py 应含 4 个 Layer ready banner 字符串。"""
    fpath = os.path.join(REPO_ROOT, 'jarvis_central_nerve.py')
    with open(fpath, encoding='utf-8') as f:
        content = f.read()
    assert '🪞 [SelfAnchor] Layer 0 ready' in content
    assert '🌱 [ConcernsLedger]' in content
    assert '💞 [RelationalState]' in content
    assert '🎯 [Attention] Layer 3 ready' in content


# ============================================================
# 13. SOUL inject 诊断 log 存在
# ============================================================
def _t13_soul_inject_log():
    fpath = os.path.join(REPO_ROOT, 'jarvis_central_nerve.py')
    with open(fpath, encoding='utf-8') as f:
        content = f.read()
    assert '🪞 [SOUL inject]' in content, "缺 SOUL inject 诊断 log"
    assert 'L0={' in content
    assert 'L1={' in content
    assert 'L2={' in content
    assert 'L3={' in content


# ============================================================
# Main
# ============================================================

def main():
    checks = [
        ('1. 全模块 import (nerve/attention/relational/concerns/anchor/cw/sn/cond/sentinels)', _t1_module_imports),
        ('2. resolve_worker_attr helper (新路径优先 + 旧路径回退 + 容错)', _t2_resolve_worker_attr),
        ('3. 无 self.worker.jarvis.X 残留 (静态扫所有 jarvis_*.py)', _t3_no_residue),
        ('4. SoulRouter 只剩 projects/progression chapter (老 jokes/milestones 删)', _t4_soul_router_chapters),
        ('5. memory_core HumorEngine 改读 relational_state (不再读 sir_profile)', _t5_humor_engine_source),
        ('6. SoulArchivistSentinel prompt 改 proposed_* + pop 老字段 + 调 propose_*', _t6_sentinel_prompt),
        ('7. Layer 3 attention 不含 PENDING FOLLOWUPS 段 (Layer 2/3 内部去重)', _t7_attention_no_pending_followups),
        ('8. RelationalStateStore review queue 全套路径 (propose/activate/write_review)', _t8_review_queue),
        ('9. migration script dry-run + apply (端到端)', _t9_migration_script),
        ('10. Commitment SQLite 持久化端到端 (_get_hippo + add_commitment_row 写盘)', _t10_commitment_e2e_sqlite_write),
        ('11. CLI --review 空 store 不抛', _t11_cli_review_empty),
        ('12. CentralNerve 含 4 个 Layer ready banner (源码静态)', _t12_layer_banners_in_source),
        ('13. SOUL inject 诊断 log 存在 (源码静态)', _t13_soul_inject_log),
    ]

    for name, fn in checks:
        _check(name, fn)

    n_pass = sum(1 for _, s, _ in CHECKS if s == 'PASS')
    n_total = len(CHECKS)

    print()
    print('=' * 100)
    print(f'[SELF VERIFY] β.2.4 + β.2.3 + hotfix  result: {n_pass}/{n_total}')
    print('=' * 100)
    for name, status, msg in CHECKS:
        icon = {'PASS': '✓', 'FAIL': '✗', 'ERROR': '⛔'}.get(status, '?')
        line = f"  [{status:5}] {icon} {name}"
        if msg:
            line += f"\n          → {msg}"
        print(line)
    print()
    return 0 if n_pass == n_total else 1


if __name__ == '__main__':
    sys.exit(main())
