# -*- coding: utf-8 -*-
"""
[P0+20-β.4.6 / 2026-05-18] L3 Directive vocab 半化 - text/metadata 提到 JSON

Sir Session 5 半化方案 (准则 6.5):
  - text/priority/state/tier_whitelist/ttl_days 全在 memory_pool/directives_vocab.json
  - trigger 函数仍在 jarvis_directives.py (Python lambda 不能 JSON)
  - bootstrap_default_registry 优先读 JSON + py trigger 组装 Directive
  - JSON 缺/损坏 → fallback 到 seed_defs (py 内嵌)
  - state='active' 才注册 (review/dormant/archived 跳过, Sir CLI --activate 才生效)

测试覆盖 (6 TestClass):
  1. TestVocabLoad — 读 JSON / mtime cache / reload
  2. TestBootstrap — JSON 路径注册 18 / seed fallback / state 过滤 (review skip)
  3. TestTriggerStillWorks — bilingual / nudge / search 等关键 trigger 仍 fire (text 来自 JSON)
  4. TestCLI — _cmd_show / _cmd_vocab_list / _cmd_edit_text / _cmd_archive
  5. TestFailSafe — JSON 损坏 / 缺失 / 全 skip 走 fallback
  6. TestRedLines — 准则 6.5 (vocab path / mtime cache / 状态 canonical) + 准则 7 (state default)
"""
import contextlib
import importlib
import io as _io
import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import jarvis_directives as jd  # noqa: E402


def _make_minimal_vocab(directives: list) -> dict:
    return {
        '_meta': {
            'schema_version': 1,
            'marker': 'test',
            'states_canonical': ['active', 'dormant', 'review', 'archived'],
        },
        'directives': directives,
    }


def _seed_dict(did: str, **overrides) -> dict:
    """快速构造 directive entry (defaults match real seed)."""
    base = {
        'id': did,
        'text': f'[TEST {did}] dummy text',
        'priority': 5,
        'state': 'active',
        'tier_whitelist': [],
        'ttl_days': 30,
        'source_marker': 'test',
        'note': '',
        'source': 'seed',
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------
# 1. TestVocabLoad
# ---------------------------------------------------------------

class TestVocabLoad(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, 'directives_vocab.json')
        # reset cache
        jd._VOCAB_CACHE['mtime'] = 0.0
        jd._VOCAB_CACHE['data'] = None

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)
        jd._VOCAB_CACHE['mtime'] = 0.0
        jd._VOCAB_CACHE['data'] = None

    def test_load_returns_dict(self):
        vocab = _make_minimal_vocab([_seed_dict('foo')])
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(vocab, f)
        result = jd._load_directives_vocab(self.path)
        self.assertIsNotNone(result)
        self.assertEqual(len(result['directives']), 1)
        self.assertEqual(result['directives'][0]['id'], 'foo')

    def test_missing_file_returns_none(self):
        result = jd._load_directives_vocab('/nonexistent/path.json')
        self.assertIsNone(result)

    def test_corrupt_json_returns_none(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('not json at all')
        result = jd._load_directives_vocab(self.path)
        self.assertIsNone(result)

    def test_no_directives_field_returns_none(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump({'_meta': {}}, f)  # 缺 directives 字段
        result = jd._load_directives_vocab(self.path)
        self.assertIsNone(result)

    def test_mtime_cache_hits_on_unchanged_file(self):
        vocab = _make_minimal_vocab([_seed_dict('cache_test')])
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(vocab, f)
        r1 = jd._load_directives_vocab(self.path)
        # 缓存应填好
        self.assertIsNotNone(r1)
        self.assertGreater(jd._VOCAB_CACHE['mtime'], 0.0)
        # 再读一次 — 同一对象 (cache hit)
        r2 = jd._load_directives_vocab(self.path)
        self.assertIs(r1, r2)

    def test_reload_clears_cache(self):
        vocab = _make_minimal_vocab([_seed_dict('rel_test')])
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(vocab, f)
        jd._load_directives_vocab(self.path)
        self.assertIsNotNone(jd._VOCAB_CACHE['data'])
        jd.reload_directives_vocab()
        self.assertEqual(jd._VOCAB_CACHE['mtime'], 0.0)
        self.assertIsNone(jd._VOCAB_CACHE['data'])


# ---------------------------------------------------------------
# 2. TestBootstrap
# ---------------------------------------------------------------

class TestBootstrap(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vocab_path = os.path.join(self.tmpdir, 'directives_vocab.json')
        self.persist_path = os.path.join(self.tmpdir, '_persist.json')
        jd._VOCAB_CACHE['mtime'] = 0.0
        jd._VOCAB_CACHE['data'] = None
        jd._TRIGGER_BY_ID.clear()

    def tearDown(self):
        for p in (self.vocab_path, self.persist_path):
            if os.path.exists(p):
                os.unlink(p)
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)
        jd._VOCAB_CACHE['mtime'] = 0.0
        jd._VOCAB_CACHE['data'] = None

    def test_bootstrap_seed_only_registers_18(self):
        """seed fallback (强制路径) 应 18 个."""
        reg = jd.DirectiveRegistry(persist_path=self.persist_path)
        n = jd._bootstrap_seed_only(reg)
        self.assertEqual(n, 18)
        self.assertEqual(len(reg.directives), 18)

    def test_bootstrap_loads_real_vocab_18(self):
        """走真 memory_pool/directives_vocab.json (18 seed)."""
        reg = jd.DirectiveRegistry(persist_path=self.persist_path)
        n = jd.bootstrap_default_registry(reg)  # 默认路径
        self.assertEqual(n, 18, '应从 memory_pool/directives_vocab.json 读 18 directive')

    def test_bootstrap_filters_non_active_state(self):
        # 写 vocab: 1 active + 1 review + 1 archived
        # 用真 trigger id 才能注册 (其他 id 走 no-trigger skip)
        vocab = _make_minimal_vocab([
            _seed_dict('bilingual_directive', state='active'),
            _seed_dict('search_directive', state='review'),
            _seed_dict('image_context', state='archived'),
        ])
        with open(self.vocab_path, 'w', encoding='utf-8') as f:
            json.dump(vocab, f)
        # 先 bootstrap 一次填 _TRIGGER_BY_ID (用真 vocab)
        reg_seed = jd.DirectiveRegistry(persist_path=self.persist_path)
        jd._bootstrap_seed_only(reg_seed)
        # 现在 _TRIGGER_BY_ID 已填
        reg = jd.DirectiveRegistry(persist_path=self.persist_path + '.2')
        n = jd.bootstrap_default_registry(reg, vocab_path=self.vocab_path)
        # 1 active 注册, review + archived skip
        self.assertEqual(n, 1)
        self.assertIn('bilingual_directive', reg.directives)
        self.assertNotIn('search_directive', reg.directives)
        self.assertNotIn('image_context', reg.directives)

    def test_bootstrap_skips_unknown_id(self):
        """JSON 端 id 在 py 端无 trigger → skip."""
        vocab = _make_minimal_vocab([
            _seed_dict('completely_unknown_id_xyz', state='active'),
        ])
        with open(self.vocab_path, 'w', encoding='utf-8') as f:
            json.dump(vocab, f)
        # 先 bootstrap 一次填 _TRIGGER_BY_ID
        jd._bootstrap_seed_only(jd.DirectiveRegistry(
            persist_path=self.persist_path))
        reg = jd.DirectiveRegistry(persist_path=self.persist_path + '.b')
        n = jd.bootstrap_default_registry(reg, vocab_path=self.vocab_path)
        # JSON 全 skip → fallback seed 18
        self.assertEqual(n, 18)
        self.assertNotIn('completely_unknown_id_xyz', reg.directives)


# ---------------------------------------------------------------
# 3. TestTriggerStillWorks (text 来自 JSON, trigger 来自 py)
# ---------------------------------------------------------------

class TestTriggerStillWorks(unittest.TestCase):

    def setUp(self):
        self.tmp_persist = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8')
        self.tmp_persist.close()

    def tearDown(self):
        if os.path.exists(self.tmp_persist.name):
            os.unlink(self.tmp_persist.name)

    def test_bilingual_directive_fires_with_json_text(self):
        reg = jd.DirectiveRegistry(persist_path=self.tmp_persist.name)
        jd.bootstrap_default_registry(reg)  # 真 vocab
        ctx = jd.DirectiveContext(user_input='hi', tier='WAKE_ONLY')
        fired = reg.collect(ctx)
        ids = [d.id for d in fired]
        self.assertIn('bilingual_directive', ids)
        # text 来自 JSON, 内容应含 "BILINGUAL"
        d = reg.get('bilingual_directive')
        self.assertIn('BILINGUAL', d.text)

    def test_nudge_directive_fires_with_json_text(self):
        reg = jd.DirectiveRegistry(persist_path=self.tmp_persist.name)
        jd.bootstrap_default_registry(reg)
        ctx = jd.DirectiveContext(
            user_input='不用再提了好吗',
            last_jarvis_reply="I've struck it from the active agenda.",
            stm=[{'user': 'x', 'jarvis': 'y'}],
            tier='SHORT_CHAT',
        )
        fired = reg.collect(ctx)
        ids = [d.id for d in fired]
        self.assertIn('nudge_agenda_honesty', ids)


# ---------------------------------------------------------------
# 4. TestCLI (scripts/registry_dump.py β.4.6 命令)
# ---------------------------------------------------------------

class TestCLI(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, 'directives_vocab.json')
        # 写一个小 vocab (3 directives, 用真 id 让 _TRIGGER_BY_ID 命中)
        vocab = _make_minimal_vocab([
            _seed_dict('bilingual_directive', text='ORIGINAL TEXT', priority=10),
            _seed_dict('search_directive', text='SEARCH TEXT', priority=6),
            _seed_dict('image_context', text='IMAGE TEXT', priority=6,
                       state='review'),
        ])
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(vocab, f)
        # 重新 import scripts/registry_dump.py 以注入 VOCAB_PATH
        if 'registry_dump' in sys.modules:
            del sys.modules['registry_dump']
        import registry_dump
        self.rd = registry_dump
        self.rd.VOCAB_PATH = self.path

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def _quiet_call(self, fn, *args, **kwargs):
        """Helper: redirect CLI print output to buffer (防污染 unittest stdout)."""
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = fn(*args, **kwargs)
        return rc, buf.getvalue()

    def test_show_directive_returns_0_for_existing(self):
        rc, _ = self._quiet_call(self.rd._cmd_show_directive,
                                    'bilingual_directive')
        self.assertEqual(rc, 0)

    def test_show_directive_returns_1_for_missing(self):
        rc, _ = self._quiet_call(self.rd._cmd_show_directive, 'nonexistent_id')
        self.assertEqual(rc, 1)

    def test_vocab_list_returns_0(self):
        rc, _ = self._quiet_call(self.rd._cmd_vocab_list)
        self.assertEqual(rc, 0)

    def test_edit_text_replaces_text(self):
        text_file = os.path.join(self.tmpdir, 'new.txt')
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write('REPLACED TEXT FROM CLI')
        rc, _ = self._quiet_call(self.rd._cmd_edit_text,
                                    'bilingual_directive', text_file)
        self.assertEqual(rc, 0)
        # 验证写盘
        with open(self.path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        target = next(d for d in data['directives']
                       if d['id'] == 'bilingual_directive')
        self.assertEqual(target['text'], 'REPLACED TEXT FROM CLI')
        self.assertIn('Sir CLI edit', target['note'])
        os.unlink(text_file)

    def test_edit_text_rejects_empty_file(self):
        text_file = os.path.join(self.tmpdir, 'empty.txt')
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write('   \n  ')  # whitespace only
        rc, _ = self._quiet_call(self.rd._cmd_edit_text,
                                    'bilingual_directive', text_file)
        self.assertEqual(rc, 1)
        os.unlink(text_file)

    def test_archive_directive_changes_state(self):
        rc, _ = self._quiet_call(self.rd._cmd_archive_directive,
                                    'search_directive')
        self.assertEqual(rc, 0)
        with open(self.path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        target = next(d for d in data['directives']
                       if d['id'] == 'search_directive')
        self.assertEqual(target['state'], 'archived')

    def test_archive_unknown_returns_1(self):
        rc, _ = self._quiet_call(self.rd._cmd_archive_directive,
                                    'nonexistent_xyz')
        self.assertEqual(rc, 1)


# ---------------------------------------------------------------
# 5. TestFailSafe
# ---------------------------------------------------------------

class TestFailSafe(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vocab_path = os.path.join(self.tmpdir, 'directives_vocab.json')
        self.persist_path = os.path.join(self.tmpdir, '_persist.json')
        jd._VOCAB_CACHE['mtime'] = 0.0
        jd._VOCAB_CACHE['data'] = None

    def tearDown(self):
        for p in (self.vocab_path, self.persist_path):
            if os.path.exists(p):
                os.unlink(p)
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)
        jd._VOCAB_CACHE['mtime'] = 0.0
        jd._VOCAB_CACHE['data'] = None

    def test_corrupt_vocab_triggers_seed_fallback(self):
        with open(self.vocab_path, 'w', encoding='utf-8') as f:
            f.write('garbage non-json content')
        reg = jd.DirectiveRegistry(persist_path=self.persist_path)
        n = jd.bootstrap_default_registry(reg, vocab_path=self.vocab_path)
        # 损坏 → fallback seed 18
        self.assertEqual(n, 18)

    def test_empty_directives_array_triggers_seed_fallback(self):
        """vocab 存在但 directives=[], 全 skip → fallback seed 18."""
        with open(self.vocab_path, 'w', encoding='utf-8') as f:
            json.dump(_make_minimal_vocab([]), f)
        reg = jd.DirectiveRegistry(persist_path=self.persist_path)
        n = jd.bootstrap_default_registry(reg, vocab_path=self.vocab_path)
        self.assertEqual(n, 18)


# ---------------------------------------------------------------
# 6. TestRedLines (准则 6.5 + 准则 7)
# ---------------------------------------------------------------

class TestRedLines(unittest.TestCase):

    def test_real_vocab_file_exists_in_repo(self):
        """准则 6.5: vocab 必须在 memory_pool/."""
        path = os.path.join(ROOT, 'memory_pool', 'directives_vocab.json')
        self.assertTrue(os.path.exists(path),
                          'memory_pool/directives_vocab.json 必须存在 (β.4.6 seed)')

    def test_real_vocab_has_18_directives(self):
        """准则 6.5: 18 directive 全部 vocab 化."""
        path = os.path.join(ROOT, 'memory_pool', 'directives_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(len(data['directives']), 18)

    def test_real_vocab_meta_has_canonical_states(self):
        """准则 6.5: 状态 canonical 列表必须在 _meta."""
        path = os.path.join(ROOT, 'memory_pool', 'directives_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('states_canonical', data['_meta'])
        self.assertEqual(set(data['_meta']['states_canonical']),
                          {'active', 'dormant', 'review', 'archived'})

    def test_no_propose_writes_active_state(self):
        """准则 7: 任何 source != seed 的 entry, 默认 state 应 review (Sir 仲裁)."""
        # 模拟 IntegrityReflector / sir_added 加 directive
        # 现在 vocab 全 seed → 此红线在加 entry 时强制 (本测保护未来扩展)
        path = os.path.join(ROOT, 'memory_pool', 'directives_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for d in data['directives']:
            if d.get('source') in ('integrity_reflector', 'sir_added'):
                self.assertNotEqual(
                    d.get('state'), 'active',
                    f"{d['id']} source={d['source']} 默认 state 不应 active "
                    "(准则 7 Sir 仲裁): 必须 review/dormant/archived")

    def test_canonical_state_filter_in_bootstrap(self):
        """准则 7: state 不在 canonical 时强制改 review (代码层级)."""
        # 直接读 jarvis_directives.py 源码看 state 逻辑
        path = os.path.join(ROOT, 'jarvis_directives.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("state = 'review'", src,
                       "bootstrap 必须把非法 state → review 而非 active")

    def test_central_nerve_still_imports_get_default_registry(self):
        """central_nerve 入口点不变."""
        cn_path = os.path.join(ROOT, 'jarvis_central_nerve.py')
        with open(cn_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('get_default_registry', src,
                       'central_nerve 应仍调 get_default_registry()')


if __name__ == '__main__':
    unittest.main(verbosity=2)
