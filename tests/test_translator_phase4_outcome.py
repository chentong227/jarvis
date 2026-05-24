# -*- coding: utf-8 -*-
"""[Translator Phase 4.A / 2026-05-24 22:40] outcome metric (hit_count 闭环) test.

详 docs/JARVIS_TRANSLATOR_ARCHITECTURE.md §7.7 (Phase 4)

覆盖:
  A. Translator._lookup_vocab_alias 命中 active → bump in-memory hit buffer
  B. flush_hit_updates() atomic 落盘 → vocab.json hit_count 真增长
  C. flush 节流: 无 pending updates 返 0 / 不动 IO
  D. hit_count 跨多次 lookup 累加正确
  E. reflector dedupe 扩展: rejected (from, to) 也不再 propose
  F. reflector dedupe 扩展: review (from, to) 也不再 propose
  G. nerve 启动时含 _translator_flush_thread daemon (静态 grep)
  H. get_stats() 返 hit_buffer_pending_total
"""
import os
import json
import time
import tempfile
import shutil
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class _MockEventBus:
    def __init__(self):
        self.events = []
        self.published = []

    def publish(self, etype, description='', source='', salience=0.3,
                metadata=None, ttl=None):
        self.published.append({
            'etype': etype, 'metadata': metadata or {},
        })


def _make_active_alias(alias_id='alias_001', from_o='browser', to_o='web_search'):
    return {
        'id': alias_id, 'kind': 'organ',
        'from': from_o, 'to': to_o,
        'status': 'active', 'hit_count': 0,
        'last_hit_at': None, 'version': 1,
    }


class _BaseTranslatorTest(unittest.TestCase):
    """共用: 临时 vocab + 加假 hand_registry 让 lookup 通."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tmp_vocab = os.path.join(self._tmpdir, 'memory_pool',
                                        'translator_alias_vocab.json')
        os.makedirs(os.path.dirname(self._tmp_vocab), exist_ok=True)
        import jarvis_translator as t
        self._orig_path = t._ALIAS_VOCAB_PATH
        t._ALIAS_VOCAB_PATH = self._tmp_vocab

    def tearDown(self):
        import jarvis_translator as t
        t._ALIAS_VOCAB_PATH = self._orig_path
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_vocab(self, aliases):
        with open(self._tmp_vocab, 'w', encoding='utf-8') as f:
            json.dump({'schema_version': 1, 'aliases': aliases}, f,
                       ensure_ascii=False, indent=2)

    def _read_vocab(self):
        with open(self._tmp_vocab, 'r', encoding='utf-8') as f:
            return json.load(f)


# ============================================================
# A + B + C + D. Translator hit_count 闭环
# ============================================================

class TestAHitCountBumpInMemory(_BaseTranslatorTest):

    def test_lookup_active_bumps_buffer(self):
        """命中 active alias → buffer +1."""
        self._write_vocab([_make_active_alias('alias_001', 'browser', 'web_search')])
        from jarvis_translator import Translator
        tr = Translator(hand_registry={'web_search': object})
        # _lookup_vocab_alias 内部 bump
        result = tr._lookup_vocab_alias('organ', 'browser')
        self.assertEqual(result, 'web_search')
        with tr._hit_buffer_lock:
            self.assertEqual(tr._hit_buffer.get('alias_001'), 1)
            self.assertGreater(tr._hit_buffer_last_ts.get('alias_001', 0), 0)

    def test_lookup_no_match_does_not_bump(self):
        """无匹配 → 不 bump."""
        self._write_vocab([_make_active_alias('alias_001', 'browser', 'web_search')])
        from jarvis_translator import Translator
        tr = Translator(hand_registry={'web_search': object})
        result = tr._lookup_vocab_alias('organ', 'no_such_organ')
        self.assertIsNone(result)
        with tr._hit_buffer_lock:
            self.assertEqual(len(tr._hit_buffer), 0)

    def test_lookup_skip_review_does_not_bump(self):
        """status=review → 不命中, 不 bump."""
        review_alias = _make_active_alias('alias_001', 'browser', 'web_search')
        review_alias['status'] = 'review'
        self._write_vocab([review_alias])
        from jarvis_translator import Translator
        tr = Translator(hand_registry={'web_search': object})
        result = tr._lookup_vocab_alias('organ', 'browser')
        self.assertIsNone(result)


class TestBFlushHitUpdates(_BaseTranslatorTest):

    def test_flush_writes_hit_count_to_disk(self):
        """flush 后 vocab.json hit_count 真增长."""
        self._write_vocab([_make_active_alias('alias_001', 'browser', 'web_search')])
        from jarvis_translator import Translator
        tr = Translator(hand_registry={'web_search': object})
        # 命中 3 次
        for _ in range(3):
            tr._lookup_vocab_alias('organ', 'browser')
        # flush
        n = tr.flush_hit_updates()
        self.assertEqual(n, 1, 'merged alias count = 1')
        # 验 disk
        v = self._read_vocab()
        alias = v['aliases'][0]
        self.assertEqual(alias['hit_count'], 3)
        self.assertIsNotNone(alias['last_hit_at'])

    def test_flush_no_pending_returns_zero(self):
        """无 pending → 返 0, 不动 IO."""
        self._write_vocab([_make_active_alias()])
        from jarvis_translator import Translator
        tr = Translator(hand_registry={'web_search': object})
        n = tr.flush_hit_updates()
        self.assertEqual(n, 0)

    def test_flush_clears_buffer(self):
        """flush 后 in-memory buffer 清空."""
        self._write_vocab([_make_active_alias()])
        from jarvis_translator import Translator
        tr = Translator(hand_registry={'web_search': object})
        tr._lookup_vocab_alias('organ', 'browser')
        with tr._hit_buffer_lock:
            self.assertEqual(len(tr._hit_buffer), 1)
        tr.flush_hit_updates()
        with tr._hit_buffer_lock:
            self.assertEqual(len(tr._hit_buffer), 0)

    def test_flush_accumulates_across_calls(self):
        """跨多次 flush: hit_count 累加."""
        self._write_vocab([_make_active_alias()])
        from jarvis_translator import Translator
        tr = Translator(hand_registry={'web_search': object})
        for _ in range(2):
            tr._lookup_vocab_alias('organ', 'browser')
        tr.flush_hit_updates()
        for _ in range(5):
            tr._lookup_vocab_alias('organ', 'browser')
        tr.flush_hit_updates()
        v = self._read_vocab()
        self.assertEqual(v['aliases'][0]['hit_count'], 7, '2 + 5 = 7')


class TestCGetStatsBufferPending(_BaseTranslatorTest):

    def test_get_stats_returns_buffer_size(self):
        self._write_vocab([_make_active_alias()])
        from jarvis_translator import Translator
        tr = Translator(hand_registry={'web_search': object})
        for _ in range(3):
            tr._lookup_vocab_alias('organ', 'browser')
        s = tr.get_stats()
        self.assertIn('hit_buffer_pending_total', s)
        self.assertEqual(s['hit_buffer_pending_total'], 3)
        self.assertEqual(s['hit_buffer_aliases'], 1)


# ============================================================
# E + F. Reflector dedupe 扩展
# ============================================================

class TestEReflectorDedupesRejected(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tmp_vocab = os.path.join(self._tmpdir, 'memory_pool',
                                        'translator_alias_vocab.json')
        os.makedirs(os.path.dirname(self._tmp_vocab), exist_ok=True)
        import jarvis_translator_reflector as trr
        self._orig = trr.VOCAB_PATH
        trr.VOCAB_PATH = self._tmp_vocab

    def tearDown(self):
        import jarvis_translator_reflector as trr
        trr.VOCAB_PATH = self._orig
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _seed_vocab(self, aliases):
        with open(self._tmp_vocab, 'w', encoding='utf-8') as f:
            json.dump({'schema_version': 1, 'aliases': aliases}, f, ensure_ascii=False, indent=2)

    def _make_events(self, from_o, to_o, n=3):
        out = []
        for i in range(n):
            out.append({
                'etype': 'translator_aliased',
                'metadata': {
                    'from_organ': from_o, 'to_organ': to_o,
                    'alias_kind': 'by_command', 'command': f'c{i}',
                },
                'ts': time.time(),
            })
        return out

    def test_rejected_alias_not_reproposed(self):
        """Sir 已 reject 的 (from, to) → reflector 不再 propose."""
        self._seed_vocab([{
            'id': 'alias_001', 'kind': 'organ',
            'from': 'browser', 'to': 'web_search',
            'status': 'rejected',
        }])
        from jarvis_translator_reflector import TranslatorReflector

        class _Bus:
            def __init__(self): self.events = []
            def recent_events(self, within_seconds=None, types=None):
                return [e for e in self.events
                        if not types or e.get('etype') in types]
            def publish(self, **kw): pass

        bus = _Bus()
        bus.events = self._make_events('browser', 'web_search', n=5)
        r = TranslatorReflector(event_bus=bus)
        out = r.run_cycle()
        self.assertEqual(out, [], 'rejected (browser → web_search) 不应再 propose')

    def test_review_alias_not_reproposed(self):
        """已在 review queue 的 (from, to) → 不重复 propose."""
        self._seed_vocab([{
            'id': 'alias_001', 'kind': 'organ',
            'from': 'browser', 'to': 'web_search',
            'status': 'review',
        }])
        from jarvis_translator_reflector import TranslatorReflector

        class _Bus:
            def __init__(self): self.events = []
            def recent_events(self, within_seconds=None, types=None):
                return [e for e in self.events
                        if not types or e.get('etype') in types]
            def publish(self, **kw): pass

        bus = _Bus()
        bus.events = self._make_events('browser', 'web_search', n=5)
        r = TranslatorReflector(event_bus=bus)
        out = r.run_cycle()
        self.assertEqual(out, [], 'review (browser → web_search) 不应再 propose')


# ============================================================
# G. nerve flush daemon (静态 grep)
# ============================================================

class TestGNerveStartsFlushDaemon(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'),
                  'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_nerve_starts_translator_flush_thread(self):
        self.assertIn('TranslatorHitFlush', self.src,
                      'nerve 必须有 TranslatorHitFlush daemon thread')

    def test_nerve_calls_flush_hit_updates(self):
        self.assertIn('flush_hit_updates()', self.src,
                      'nerve 必须 call flush_hit_updates()')

    def test_nerve_flush_interval_60s(self):
        self.assertIn('wait(60.0)', self.src,
                      'flush 间隔应 60s')


if __name__ == '__main__':
    unittest.main()
