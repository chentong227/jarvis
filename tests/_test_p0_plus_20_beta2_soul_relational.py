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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_relational import (
    InsideJoke, UnspokenProtocol, UnfinishedBusiness,
    RelationalStateStore,
    get_default_store, reset_default_store_for_test,
    make_joke_id, make_protocol_id, make_ub_id,
    STATE_ACTIVE, STATE_ARCHIVED,
    UB_OPEN, UB_PAUSED, UB_DONE,
    DEFAULT_TTL_DAYS, DEFAULT_UB_TTL_DAYS,
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
        self.assertEqual(result, {'jokes': 0, 'protocols': 0, 'ub': 0})


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
# F. ID 生成辅助
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
# H. CLI smoke test（scripts/relational_dump.py）
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
