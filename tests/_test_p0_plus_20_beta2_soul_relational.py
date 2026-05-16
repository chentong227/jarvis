# -*- coding: utf-8 -*-
"""[P0+20-β.2.2 / 2026-05-16] 灵魂工程 Layer 2 测试

Layer 2 — RelationalState (jarvis_relational.py)
- InsideJoke / UnspokenProtocol / UnfinishedBusiness 三类
- Store CRUD + persist/load + apply_decay + to_prompt_block
- id 派生函数
- CLI 集成（scripts/relational_dump.py）

详 docs/JARVIS_SOUL_DRIVE.md §2.2 + §3.3
"""
import os
import sys
import time
import tempfile
import subprocess
import unittest
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_relational import (
    InsideJoke, UnspokenProtocol, UnfinishedBusiness, SharedHistoryThread,
    RelationalStateStore,
    get_default_store, reset_default_store_for_test,
    make_joke_id, make_protocol_id, make_ub_id, make_thread_id,
    STATE_ACTIVE, STATE_ARCHIVED, STATE_REVIEW,
    UB_OPEN, UB_PAUSED, UB_DONE,
    DEFAULT_TTL_DAYS, DEFAULT_UB_TTL_DAYS, DEFAULT_THREAD_TTL_DAYS,
)


# ============================================================
# A. Dataclass 基础
# ============================================================
class TestInsideJokeDataclass(unittest.TestCase):

    def test_defaults(self):
        j = InsideJoke(id='j1', phrase='hello')
        self.assertEqual(j.state, STATE_ACTIVE)
        self.assertEqual(j.use_count, 0)
        self.assertEqual(j.last_used, 0.0)
        self.assertEqual(j.source, 'sir_added')

    def test_mark_used_increments(self):
        j = InsideJoke(id='j1', phrase='hello')
        j.mark_used()
        j.mark_used()
        self.assertEqual(j.use_count, 2)
        self.assertGreater(j.last_used, 0)

    def test_is_expired_default_false(self):
        j = InsideJoke(id='j1', phrase='hello')
        self.assertFalse(j.is_expired())

    def test_is_expired_true_when_old(self):
        j = InsideJoke(id='j1', phrase='hello', ttl_days=1)
        j.created_at = time.time() - 2 * 86400
        j.last_used = 0.0
        self.assertTrue(j.is_expired())

    def test_to_dict_roundtrip_safe(self):
        j = InsideJoke(id='j1', phrase='hello', tone='wry', birth_context='ctx')
        d = j.to_dict()
        self.assertEqual(d['phrase'], 'hello')
        self.assertEqual(d['tone'], 'wry')
        self.assertEqual(d['state'], STATE_ACTIVE)


class TestUnspokenProtocolDataclass(unittest.TestCase):

    def test_defaults(self):
        p = UnspokenProtocol(id='p1', rule='I should X')
        self.assertEqual(p.state, STATE_ACTIVE)
        self.assertEqual(p.violations, [])

    def test_record_violation_caps_at_5(self):
        p = UnspokenProtocol(id='p1', rule='X')
        for i in range(10):
            p.record_violation(f'violation {i}', turn_id=f't{i}')
        self.assertEqual(len(p.violations), 5)
        self.assertEqual(p.violations[-1]['what'], 'violation 9')


class TestUnfinishedBusinessDataclass(unittest.TestCase):

    def test_defaults(self):
        u = UnfinishedBusiness(id='u1', topic='X')
        self.assertEqual(u.state, UB_OPEN)
        self.assertEqual(u.next_touch_due, 0.0)

    def test_is_overdue_false_no_due(self):
        u = UnfinishedBusiness(id='u1', topic='X')
        self.assertFalse(u.is_overdue())

    def test_is_overdue_true_when_past(self):
        u = UnfinishedBusiness(id='u1', topic='X', next_touch_due=time.time() - 100)
        self.assertTrue(u.is_overdue())

    def test_touch_updates_last_touched(self):
        u = UnfinishedBusiness(id='u1', topic='X')
        old = u.last_touched
        time.sleep(0.01)
        u.touch()
        self.assertGreater(u.last_touched, old)


# ============================================================
# B. Store CRUD
# ============================================================
class TestStoreCRUD(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = RelationalStateStore(persist_path=self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_add_and_get_inside_joke(self):
        j = InsideJoke(id='j1', phrase='hello', tone='wry')
        self.assertTrue(self.store.add_inside_joke(j))
        self.assertIs(self.store.get_inside_joke('j1'), j)

    def test_add_duplicate_returns_false(self):
        j1 = InsideJoke(id='dup', phrase='one')
        j2 = InsideJoke(id='dup', phrase='two')
        self.assertTrue(self.store.add_inside_joke(j1))
        self.assertFalse(self.store.add_inside_joke(j2))

    def test_list_filters_archived(self):
        a = InsideJoke(id='a', phrase='alive')
        b = InsideJoke(id='b', phrase='dead', state=STATE_ARCHIVED)
        self.store.add_inside_joke(a)
        self.store.add_inside_joke(b)
        active = self.store.list_inside_jokes(include_archived=False)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].id, 'a')
        full = self.store.list_inside_jokes(include_archived=True)
        self.assertEqual(len(full), 2)

    def test_archive_inside_joke(self):
        j = InsideJoke(id='j1', phrase='hello')
        self.store.add_inside_joke(j)
        self.assertTrue(self.store.archive_inside_joke('j1'))
        self.assertEqual(j.state, STATE_ARCHIVED)
        self.assertFalse(self.store.archive_inside_joke('nonexistent'))

    def test_mark_inside_joke_used_increments(self):
        j = InsideJoke(id='j1', phrase='hello')
        self.store.add_inside_joke(j)
        self.assertTrue(self.store.mark_inside_joke_used('j1'))
        self.assertEqual(j.use_count, 1)

    def test_protocol_violation_records(self):
        p = UnspokenProtocol(id='p1', rule='I should X')
        self.store.add_protocol(p)
        self.assertTrue(self.store.record_protocol_violation(
            'p1', 'I did Y instead', turn_id='turn1'
        ))
        self.assertEqual(len(p.violations), 1)

    def test_unfinished_lifecycle(self):
        u = UnfinishedBusiness(id='u1', topic='study')
        self.store.add_unfinished(u)
        self.assertTrue(self.store.pause_unfinished('u1'))
        self.assertEqual(u.state, UB_PAUSED)
        self.assertTrue(self.store.resume_unfinished('u1'))
        self.assertEqual(u.state, UB_OPEN)
        self.assertTrue(self.store.mark_unfinished_done('u1'))
        self.assertEqual(u.state, UB_DONE)


# ============================================================
# C. 持久化
# ============================================================
class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.tmp.close()
        os.unlink(self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_persist_and_load_roundtrip(self):
        s1 = RelationalStateStore(persist_path=self.tmp.name)
        s1.add_inside_joke(InsideJoke(id='j1', phrase='hello', tone='wry',
                                      birth_context='context'))
        s1.add_protocol(UnspokenProtocol(id='p1', rule='I should X'))
        s1.add_unfinished(UnfinishedBusiness(id='u1', topic='study',
                                             detail='daily'))
        self.assertTrue(s1.persist())

        s2 = RelationalStateStore(persist_path=self.tmp.name)
        result = s2.load()
        self.assertEqual(result['jokes'], 1)
        self.assertEqual(result['protocols'], 1)
        self.assertEqual(result['ub'], 1)

        j = s2.get_inside_joke('j1')
        self.assertIsNotNone(j)
        self.assertEqual(j.phrase, 'hello')
        self.assertEqual(j.tone, 'wry')

        p = s2.get_protocol('p1')
        self.assertIsNotNone(p)
        self.assertEqual(p.rule, 'I should X')

        u = s2.get_unfinished('u1')
        self.assertIsNotNone(u)
        self.assertEqual(u.topic, 'study')

    def test_persist_no_changes_returns_false(self):
        s = RelationalStateStore(persist_path=self.tmp.name)
        self.assertFalse(s.persist())

    def test_load_missing_file_returns_zeros(self):
        s = RelationalStateStore(persist_path=self.tmp.name)
        result = s.load()
        self.assertEqual(result, {'jokes': 0, 'protocols': 0, 'ub': 0, 'threads': 0})


# ============================================================
# D. to_prompt_block
# ============================================================
class TestPromptBlock(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = RelationalStateStore(persist_path=self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_empty_store_returns_empty_block(self):
        self.assertEqual(self.store.to_prompt_block(), '')

    def test_jokes_only_has_jokes_section(self):
        self.store.add_inside_joke(InsideJoke(
            id='j1', phrase='becoming... overbearing',
            tone='wry, self-deprecating',
            birth_context='Sir 21:57 sarcasm callback',
        ))
        block = self.store.to_prompt_block()
        self.assertIn('BETWEEN US', block)
        self.assertIn('OUR INSIDE JOKES', block)
        self.assertIn('becoming... overbearing', block)
        self.assertIn('wry, self-deprecating', block)
        self.assertNotIn('UNSPOKEN PROTOCOLS', block)
        self.assertNotIn('UNFINISHED BUSINESS', block)

    def test_all_three_classes_appear(self):
        self.store.add_inside_joke(InsideJoke(
            id='j1', phrase='joke phrase', tone='dry',
            birth_context='born somewhere',
        ))
        self.store.add_protocol(UnspokenProtocol(
            id='p1', rule='I should never repeat myself'
        ))
        self.store.add_unfinished(UnfinishedBusiness(
            id='u1', topic='driver license review'
        ))
        block = self.store.to_prompt_block()
        self.assertIn('OUR INSIDE JOKES', block)
        self.assertIn('UNSPOKEN PROTOCOLS', block)
        self.assertIn('UNFINISHED BUSINESS', block)
        self.assertIn('joke phrase', block)
        self.assertIn('repeat myself', block)
        self.assertIn('driver license', block)

    def test_max_chars_truncates(self):
        for i in range(20):
            self.store.add_inside_joke(InsideJoke(
                id=f'j{i}',
                phrase=f'phrase number {i} which is moderately long for testing',
                tone='tone'
            ))
        block = self.store.to_prompt_block(top_jokes=10, max_chars=300)
        self.assertLessEqual(len(block), 300)
        self.assertIn('truncated', block)

    def test_recent_used_joke_demoted(self):
        """最近 30min 用过的 joke 应当排在没用过的后面（避免立刻重复使用）。"""
        fresh = InsideJoke(id='fresh', phrase='fresh punch', tone='dry')
        used = InsideJoke(id='used', phrase='just used punch', tone='dry')
        used.last_used = time.time()
        used.use_count = 1
        self.store.add_inside_joke(fresh)
        self.store.add_inside_joke(used)
        ranked = self.store._rank_inside_jokes(top_n=2)
        self.assertEqual(ranked[0].id, 'fresh')
        self.assertEqual(ranked[1].id, 'used')

    def test_overdue_unfinished_ranks_first(self):
        normal = UnfinishedBusiness(id='n', topic='normal')
        overdue = UnfinishedBusiness(id='o', topic='overdue',
                                     next_touch_due=time.time() - 100)
        self.store.add_unfinished(normal)
        self.store.add_unfinished(overdue)
        ranked = self.store._rank_unfinished(top_n=2)
        self.assertEqual(ranked[0].id, 'o')

    def test_block_contains_anti_spam_hint(self):
        """注入块应当带"少用、过度引用会失去新鲜感"的提示。"""
        self.store.add_inside_joke(InsideJoke(
            id='j1', phrase='something', tone='dry',
        ))
        block = self.store.to_prompt_block()
        self.assertIn('sparingly', block.lower())


# ============================================================
# E. Decay
# ============================================================
class TestDecay(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = RelationalStateStore(persist_path=self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_expired_joke_archived(self):
        old = InsideJoke(id='old', phrase='old', ttl_days=1)
        old.created_at = time.time() - 5 * 86400
        old.last_used = 0.0
        self.store.add_inside_joke(old)
        self.store.add_inside_joke(InsideJoke(id='new', phrase='new'))
        stats = self.store.apply_decay()
        self.assertEqual(stats['jokes_archived'], 1)
        self.assertEqual(self.store.get_inside_joke('old').state, STATE_ARCHIVED)
        self.assertEqual(self.store.get_inside_joke('new').state, STATE_ACTIVE)


# ============================================================
# F. SharedHistoryThread (β.2.4.1 新增)
# ============================================================
class TestSharedHistoryThreadDataclass(unittest.TestCase):

    def test_defaults(self):
        t = SharedHistoryThread(id='t1', title='Built Jarvis')
        self.assertEqual(t.state, STATE_ACTIVE)
        self.assertEqual(t.highlights, [])
        self.assertEqual(t.ttl_days, DEFAULT_THREAD_TTL_DAYS)
        self.assertEqual(t.source, 'sir_added')

    def test_add_highlight_caps_at_20(self):
        t = SharedHistoryThread(id='t1', title='X')
        for i in range(25):
            t.add_highlight(f'event {i}')
        self.assertEqual(len(t.highlights), 20)
        self.assertEqual(t.highlights[-1]['what'], 'event 24')

    def test_is_expired_default_false(self):
        t = SharedHistoryThread(id='t1', title='X')
        self.assertFalse(t.is_expired())

    def test_is_expired_true_when_old(self):
        t = SharedHistoryThread(id='t1', title='X', ttl_days=1)
        t.last_milestone_at = time.time() - 2 * 86400
        self.assertTrue(t.is_expired())


class TestSharedHistoryThreadStore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = RelationalStateStore(persist_path=self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_add_get_list_thread(self):
        t = SharedHistoryThread(id='t1', title='Built Jarvis')
        self.assertTrue(self.store.add_thread(t))
        self.assertIs(self.store.get_thread('t1'), t)
        self.assertEqual(len(self.store.list_threads()), 1)
        self.assertFalse(self.store.add_thread(t))

    def test_record_highlight_persists(self):
        t = SharedHistoryThread(id='t1', title='X')
        self.store.add_thread(t)
        self.assertTrue(self.store.record_thread_highlight(
            't1', 'P0+19 nerve split done'
        ))
        self.assertEqual(len(t.highlights), 1)
        self.assertIn('P0+19', t.highlights[0]['what'])

    def test_archive_thread(self):
        self.store.add_thread(SharedHistoryThread(id='t1', title='X'))
        self.assertTrue(self.store.archive_thread('t1'))
        self.assertEqual(self.store.get_thread('t1').state, STATE_ARCHIVED)
        self.assertEqual(len(self.store.list_threads()), 0)
        self.assertEqual(len(self.store.list_threads(include_archived=True)), 1)

    def test_persist_load_roundtrip_with_thread(self):
        s1 = self.store
        s1.add_thread(SharedHistoryThread(
            id='t1', title='Built Jarvis', detail='from 2025'
        ))
        s1.record_thread_highlight('t1', 'wake word OK')
        self.assertTrue(s1.persist())

        s2 = RelationalStateStore(persist_path=self.tmp.name)
        result = s2.load()
        self.assertEqual(result['threads'], 1)
        t = s2.get_thread('t1')
        self.assertEqual(t.title, 'Built Jarvis')
        self.assertEqual(len(t.highlights), 1)

    def test_threads_appear_in_prompt_block(self):
        self.store.add_thread(SharedHistoryThread(
            id='t1', title='Built Jarvis system'
        ))
        self.store.record_thread_highlight('t1', 'P0+20 soul layer 2 done')
        block = self.store.to_prompt_block()
        self.assertIn('SHARED HISTORY THREADS', block)
        self.assertIn('Built Jarvis', block)
        self.assertIn('soul layer 2', block)

    def test_decay_archives_expired_thread(self):
        old = SharedHistoryThread(id='old', title='X', ttl_days=1)
        old.last_milestone_at = time.time() - 5 * 86400
        self.store.add_thread(old)
        self.store.add_thread(SharedHistoryThread(id='new', title='Y'))
        stats = self.store.apply_decay()
        self.assertEqual(stats['threads_archived'], 1)
        self.assertEqual(self.store.get_thread('old').state, STATE_ARCHIVED)
        self.assertEqual(self.store.get_thread('new').state, STATE_ACTIVE)


# ============================================================
# G. ID 生成辅助
# ============================================================
class TestIdHelpers(unittest.TestCase):

    def test_joke_id_deterministic(self):
        self.assertEqual(
            make_joke_id('becoming... overbearing'),
            make_joke_id('becoming... overbearing')
        )

    def test_joke_id_different_for_different_phrases(self):
        self.assertNotEqual(
            make_joke_id('phrase A'),
            make_joke_id('phrase B')
        )

    def test_joke_id_starts_with_joke_prefix(self):
        self.assertTrue(make_joke_id('hello').startswith('joke_'))
        self.assertTrue(make_protocol_id('rule').startswith('proto_'))
        self.assertTrue(make_ub_id('topic').startswith('ub_'))
        self.assertTrue(make_thread_id('Built Jarvis').startswith('thread_'))

    def test_thread_id_deterministic(self):
        self.assertEqual(
            make_thread_id('Built Jarvis'),
            make_thread_id('Built Jarvis')
        )

    def test_joke_id_safe_for_filenames(self):
        jid = make_joke_id('becoming... overbearing!@#$')
        for ch in jid:
            self.assertTrue(ch.isalnum() or ch == '_',
                            f"id contains unsafe char: {ch!r}")


# ============================================================
# G. Singleton
# ============================================================
class TestSingleton(unittest.TestCase):

    def setUp(self):
        reset_default_store_for_test()

    def tearDown(self):
        reset_default_store_for_test()

    def test_get_default_store_returns_same_instance(self):
        s1 = get_default_store()
        s2 = get_default_store()
        self.assertIs(s1, s2)


# ============================================================
# H. Review Queue (β.2.4.4): SoulArchivistSentinel propose 流程
# ============================================================
class TestReviewQueue(unittest.TestCase):

    def setUp(self):
        self.tmp_persist = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.tmp_persist.close()
        os.unlink(self.tmp_persist.name)
        self.tmp_review = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.tmp_review.close()
        os.unlink(self.tmp_review.name)
        self.store = RelationalStateStore(
            persist_path=self.tmp_persist.name,
            review_path=self.tmp_review.name,
        )

    def tearDown(self):
        for p in (self.tmp_persist.name, self.tmp_review.name):
            if os.path.exists(p):
                os.unlink(p)

    def test_propose_inside_joke_state_is_review(self):
        joke = InsideJoke(id='j1', phrase='auto proposed phrase')
        self.assertTrue(self.store.propose_inside_joke(joke))
        self.assertEqual(self.store.get_inside_joke('j1').state, STATE_REVIEW)

    def test_propose_inside_joke_not_in_default_list(self):
        joke = InsideJoke(id='j1', phrase='auto proposed')
        self.store.propose_inside_joke(joke)
        self.assertEqual(len(self.store.list_inside_jokes()), 0)
        self.assertEqual(len(self.store.list_inside_jokes_review()), 1)

    def test_propose_inside_joke_not_in_prompt_block(self):
        """Review 状态的 joke 不应被 to_prompt_block 注入。"""
        joke = InsideJoke(id='j1', phrase='unreviewed proposed phrase')
        self.store.propose_inside_joke(joke)
        # 没有 active 条目 → block 为空
        self.assertEqual(self.store.to_prompt_block(), '')

    def test_propose_thread_state_is_review(self):
        t = SharedHistoryThread(id='t1', title='auto proposed thread')
        self.assertTrue(self.store.propose_thread(t))
        self.assertEqual(self.store.get_thread('t1').state, STATE_REVIEW)
        self.assertEqual(len(self.store.list_threads()), 0)
        self.assertEqual(len(self.store.list_threads_review()), 1)

    def test_activate_from_review_changes_state(self):
        self.store.propose_inside_joke(InsideJoke(id='j1', phrase='x'))
        kind = self.store.activate_from_review('j1')
        self.assertEqual(kind, 'joke')
        self.assertEqual(self.store.get_inside_joke('j1').state, STATE_ACTIVE)
        self.assertEqual(len(self.store.list_inside_jokes_review()), 0)

    def test_reject_from_review_archives(self):
        self.store.propose_inside_joke(InsideJoke(id='j1', phrase='x'))
        kind = self.store.reject_from_review('j1')
        self.assertEqual(kind, 'joke')
        self.assertEqual(self.store.get_inside_joke('j1').state, STATE_ARCHIVED)

    def test_activate_thread_from_review(self):
        self.store.propose_thread(SharedHistoryThread(id='t1', title='X'))
        kind = self.store.activate_from_review('t1')
        self.assertEqual(kind, 'thread')
        self.assertEqual(self.store.get_thread('t1').state, STATE_ACTIVE)

    def test_activate_unknown_id_returns_empty(self):
        kind = self.store.activate_from_review('nonexistent')
        self.assertEqual(kind, '')

    def test_activate_already_active_returns_empty(self):
        """只能 activate review 状态的，已 active 的不会被影响。"""
        self.store.add_inside_joke(InsideJoke(id='j1', phrase='x', state=STATE_ACTIVE))
        kind = self.store.activate_from_review('j1')
        self.assertEqual(kind, '')

    def test_write_review_queue_creates_file(self):
        self.store.propose_inside_joke(InsideJoke(id='j1', phrase='x'))
        self.assertTrue(self.store.write_review_queue())
        self.assertTrue(os.path.exists(self.tmp_review.name))
        with open(self.tmp_review.name, encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(len(data['inside_jokes']), 1)
        self.assertEqual(data['inside_jokes'][0]['id'], 'j1')


# ============================================================
# I. CLI smoke test（scripts/relational_dump.py）
# ============================================================
class TestRelationalCLI(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'relational_dump.py'
        )

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def _run(self, *args, timeout: float = 15.0):
        cmd = [sys.executable, self.script_path,
               '--persist-path', self.tmp.name] + list(args)
        # [β.2.2.1 / 2026-05-16] CLI 输出 UTF-8（reconfigure + chcp 65001），
        # subprocess.run 父进程默认 GBK 解码 Windows locale → 遇 emdash/中文报
        # UnicodeDecodeError 让 stdout=None。显式 encoding='utf-8' 修复。
        return subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout
        )

    def test_cli_add_inside_joke_writes_persist(self):
        r = self._run(
            '--add-inside-joke',
            '--phrase', 'becoming... overbearing',
            '--birth-context', 'Sir 21:57 ironic callback',
            '--tone', 'wry, self-deprecating',
        )
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        self.assertTrue(os.path.exists(self.tmp.name),
                        f"persist file not created: {self.tmp.name}")

        s = RelationalStateStore(persist_path=self.tmp.name)
        s.load()
        jokes = s.list_inside_jokes()
        self.assertEqual(len(jokes), 1)
        self.assertEqual(jokes[0].phrase, 'becoming... overbearing')
        self.assertEqual(jokes[0].tone, 'wry, self-deprecating')

    def test_cli_show_prompt_returns_block_after_add(self):
        self._run(
            '--add-inside-joke', '--phrase', 'phrase one', '--tone', 'dry'
        )
        r = self._run('--show-prompt')
        self.assertEqual(r.returncode, 0)
        self.assertIn('BETWEEN US', r.stdout)
        self.assertIn('phrase one', r.stdout)

    def test_cli_add_thread_writes_persist(self):
        r = self._run(
            '--add-thread', '--title', 'Built Jarvis personal butler system',
            '--detail', 'multi-year project'
        )
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")
        self.assertTrue(os.path.exists(self.tmp.name))
        s = RelationalStateStore(persist_path=self.tmp.name)
        s.load()
        threads = s.list_threads()
        self.assertEqual(len(threads), 1)
        self.assertIn('Jarvis', threads[0].title)


if __name__ == '__main__':
    unittest.main(verbosity=2)
