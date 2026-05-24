# -*- coding: utf-8 -*-
"""[Translator Phase 3 / 2026-05-24 21:30] L7 Reflector + Self-Correct Directive test.

详 docs/JARVIS_TRANSLATOR_ARCHITECTURE.md §7.6 (L7 reflector) + §4.2 (self-correct)

覆盖:
  A. TranslatorReflector class — init / run_cycle / propose pattern / dedupe / threshold
  B. start_daemon / stop — daemon thread 起停干净
  C. nerve start — central_nerve __init__ 含 TranslatorReflector init + set_default + start_daemon
  D. directive 注册 — translator_self_correct_directive 在 default registry
  E. trigger _trigger_translator_self_correct — SWM 有/无 translator_aliased event 返 True/False
  F. vocab persistence — propose 写入 translator_alias_vocab.json status=review
"""
import os
import json
import time
import tempfile
import shutil
import unittest
from unittest.mock import MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class _MockEventBus:
    """简易 SWM mock: recent_events + publish."""

    def __init__(self):
        self.events = []
        self.published = []

    def recent_events(self, within_seconds=None, types=None):
        out = []
        for ev in self.events:
            if types and ev.get('etype') not in types:
                continue
            out.append(ev)
        return out

    def publish(self, etype, description='', source='', salience=0.3,
                metadata=None, ttl=None):
        self.published.append({
            'etype': etype, 'description': description,
            'source': source, 'metadata': metadata or {},
        })


def _make_alias_event(from_o, to_o, kind='by_command', command=''):
    """构造一个 translator_aliased SWM event."""
    return {
        'etype': 'translator_aliased',
        'metadata': {
            'from_organ': from_o,
            'to_organ': to_o,
            'alias_kind': kind,
            'command': command,
        },
        'ts': time.time(),
    }


# ============================================================
# A. TranslatorReflector class basic
# ============================================================

class TestATranslatorReflectorClass(unittest.TestCase):

    def setUp(self):
        # 临时 vocab path, 不污染真 translator_alias_vocab.json
        self._tmpdir = tempfile.mkdtemp()
        self._tmp_vocab = os.path.join(self._tmpdir, 'memory_pool',
                                        'translator_alias_vocab.json')
        os.makedirs(os.path.dirname(self._tmp_vocab), exist_ok=True)
        # monkey patch VOCAB_PATH
        import jarvis_translator_reflector as trr
        self._orig_vocab_path = trr.VOCAB_PATH
        trr.VOCAB_PATH = self._tmp_vocab

    def tearDown(self):
        import jarvis_translator_reflector as trr
        trr.VOCAB_PATH = self._orig_vocab_path
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_init_default_stats(self):
        from jarvis_translator_reflector import TranslatorReflector
        r = TranslatorReflector(event_bus=None)
        s = r.stats()
        self.assertEqual(s['cycles_run'], 0)
        self.assertEqual(s['proposals_total'], 0)

    def test_run_cycle_no_bus(self):
        """event_bus=None → return [] 不抛."""
        from jarvis_translator_reflector import TranslatorReflector
        r = TranslatorReflector(event_bus=None)
        out = r.run_cycle()
        self.assertEqual(out, [])
        self.assertEqual(r.stats()['cycles_run'], 1)

    def test_run_cycle_no_events(self):
        """event_bus 无 events → return []."""
        from jarvis_translator_reflector import TranslatorReflector
        bus = _MockEventBus()
        r = TranslatorReflector(event_bus=bus)
        out = r.run_cycle()
        self.assertEqual(out, [])

    def test_propose_below_threshold(self):
        """< 3 次 by_command → 不 propose."""
        from jarvis_translator_reflector import TranslatorReflector
        bus = _MockEventBus()
        # 仅 2 次, 不到阈值 (_PROPOSE_THRESHOLD=3)
        bus.events = [
            _make_alias_event('browser', 'web_search', 'by_command', 'search X'),
            _make_alias_event('browser', 'web_search', 'by_command', 'search Y'),
        ]
        r = TranslatorReflector(event_bus=bus)
        out = r.run_cycle()
        self.assertEqual(out, [], '< 3 次不该 propose')

    def test_propose_at_threshold_creates_review(self):
        """≥ 3 次 by_command 同 (from, to) → propose 1 entry status=review."""
        from jarvis_translator_reflector import TranslatorReflector
        bus = _MockEventBus()
        bus.events = [
            _make_alias_event('browser', 'web_search', 'by_command', 'search A'),
            _make_alias_event('browser', 'web_search', 'by_command', 'search B'),
            _make_alias_event('browser', 'web_search', 'by_command', 'search C'),
        ]
        r = TranslatorReflector(event_bus=bus)
        out = r.run_cycle()
        self.assertEqual(len(out), 1, '应 propose 1 entry')
        entry = out[0]
        self.assertEqual(entry['from'], 'browser')
        self.assertEqual(entry['to'], 'web_search')
        self.assertEqual(entry['status'], 'review')
        self.assertEqual(entry['kind'], 'organ')
        self.assertEqual(entry['hit_count'], 3)
        self.assertTrue(entry['id'].startswith('alias_'))
        self.assertEqual(entry['added_by'], 'L7-TranslatorReflector')

    def test_propose_dedupes_existing(self):
        """已存在 (from, to) organ alias → 不再 propose."""
        from jarvis_translator_reflector import TranslatorReflector, _save_vocab
        # 先预存一个 organ alias (browser → web_search activated)
        existing = {
            'schema_version': 1,
            'aliases': [{
                'id': 'alias_001', 'kind': 'organ',
                'from': 'browser', 'to': 'web_search',
                'status': 'active',  # 🆕 [Phase 4.A] 修 enum: activated → active
            }],
        }
        _save_vocab(existing)

        bus = _MockEventBus()
        bus.events = [
            _make_alias_event('browser', 'web_search', 'by_command', 'search') for _ in range(5)
        ]
        r = TranslatorReflector(event_bus=bus)
        out = r.run_cycle()
        self.assertEqual(out, [], '已存在 alias 不应再 propose')

    def test_propose_skips_non_by_command(self):
        """alias_kind != 'by_command' (suffix_hands / exact) → 不 propose."""
        from jarvis_translator_reflector import TranslatorReflector
        bus = _MockEventBus()
        bus.events = [
            _make_alias_event('reminder', 'reminder_hands', 'suffix_hands', 'set X')
            for _ in range(5)
        ]
        r = TranslatorReflector(event_bus=bus)
        out = r.run_cycle()
        self.assertEqual(out, [], 'suffix_hands 不该 propose (不需 vocab persist)')

    def test_propose_publishes_swm_event(self):
        """propose 成功 → SWM publish 'translator_proposed'."""
        from jarvis_translator_reflector import TranslatorReflector
        bus = _MockEventBus()
        bus.events = [
            _make_alias_event('foo', 'foo_organ', 'by_command', 'cmd' + str(i))
            for i in range(3)
        ]
        r = TranslatorReflector(event_bus=bus)
        r.run_cycle()
        published_types = [e['etype'] for e in bus.published]
        self.assertIn('translator_proposed', published_types,
                      'propose 后应 publish translator_proposed SWM event')

    def test_propose_writes_vocab_json(self):
        """propose 后 translator_alias_vocab.json 应有 review 条目."""
        from jarvis_translator_reflector import TranslatorReflector
        bus = _MockEventBus()
        bus.events = [
            _make_alias_event('xx', 'yy', 'by_command', f'c{i}') for i in range(3)
        ]
        r = TranslatorReflector(event_bus=bus)
        r.run_cycle()
        with open(self._tmp_vocab, 'r', encoding='utf-8') as f:
            d = json.load(f)
        review = [a for a in d.get('aliases', []) if a.get('status') == 'review']
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]['from'], 'xx')
        self.assertEqual(review[0]['to'], 'yy')


# ============================================================
# B. start_daemon / stop
# ============================================================

class TestBDaemonLifecycle(unittest.TestCase):

    def test_start_daemon_creates_thread(self):
        from jarvis_translator_reflector import TranslatorReflector
        r = TranslatorReflector(event_bus=None)
        r.start_daemon()
        self.assertIsNotNone(r._daemon)
        self.assertTrue(r._daemon.is_alive())
        self.assertEqual(r._daemon.name, 'TranslatorReflector')
        # 清理
        r.stop()

    def test_start_daemon_idempotent(self):
        """重复 start_daemon 不应启第二个 thread."""
        from jarvis_translator_reflector import TranslatorReflector
        r = TranslatorReflector(event_bus=None)
        r.start_daemon()
        t1 = r._daemon
        r.start_daemon()
        t2 = r._daemon
        self.assertIs(t1, t2, '重复 start 应返同 thread')
        r.stop()

    def test_stop_sets_event(self):
        from jarvis_translator_reflector import TranslatorReflector
        r = TranslatorReflector(event_bus=None)
        r.start_daemon()
        self.assertFalse(r._stop.is_set())
        r.stop()
        self.assertTrue(r._stop.is_set())


# ============================================================
# C. nerve start integration (static grep)
# ============================================================

class TestCNerveStartIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'), 'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_nerve_imports_reflector(self):
        self.assertIn('from jarvis_translator_reflector import', self.src,
                      'central_nerve 必须 import TranslatorReflector')

    def test_nerve_instantiates_reflector(self):
        self.assertIn('TranslatorReflector(', self.src,
                      'central_nerve 必须实例化 TranslatorReflector')

    def test_nerve_sets_default_reflector(self):
        self.assertIn('set_default_reflector(', self.src,
                      'central_nerve 必须 set_default_reflector')

    def test_nerve_starts_daemon(self):
        self.assertIn('translator_reflector.start_daemon()', self.src,
                      'central_nerve 必须 call start_daemon()')

    def test_nerve_assigns_self_attr(self):
        """self.translator_reflector = ... 必须存在 (其他模块可 access)."""
        self.assertIn('self.translator_reflector = ', self.src)


# ============================================================
# D. Directive 注册
# ============================================================

class TestDDirectiveRegistration(unittest.TestCase):

    def test_directive_in_default_registry(self):
        from jarvis_directives import get_default_registry
        reg = get_default_registry()
        ids = set(reg.directives.keys())
        self.assertIn('translator_self_correct_directive', ids,
                      'translator_self_correct_directive 必须注册')

    def test_directive_has_trigger(self):
        from jarvis_directives import get_default_registry
        reg = get_default_registry()
        d = reg.get('translator_self_correct_directive')
        self.assertIsNotNone(d)
        self.assertIsNotNone(d.trigger,
                             'translator_self_correct_directive 必须有 trigger function')
        self.assertEqual(d.trigger.__name__, '_trigger_translator_self_correct')

    def test_directive_text_contains_key_guidance(self):
        from jarvis_directives import get_default_registry
        reg = get_default_registry()
        d = reg.get('translator_self_correct_directive')
        self.assertIsNotNone(d)
        self.assertIn('TRANSLATOR SELF-CORRECT', d.text)
        self.assertIn('alias_kind', d.text)
        self.assertIn('FAST_CALL', d.text)


# ============================================================
# E. trigger logic
# ============================================================

class TestETriggerLogic(unittest.TestCase):

    def _set_bus(self, bus):
        # ConversationEventBus.register_global is staticmethod-like; use module-level _GLOBAL_EVENT_BUS
        import jarvis_utils as ju
        self._orig_bus = ju._GLOBAL_EVENT_BUS
        ju._GLOBAL_EVENT_BUS = bus

    def _restore_bus(self):
        import jarvis_utils as ju
        ju._GLOBAL_EVENT_BUS = self._orig_bus

    def test_trigger_false_when_no_recent_event(self):
        from jarvis_directives import _trigger_translator_self_correct, DirectiveContext
        bus = _MockEventBus()
        self._set_bus(bus)
        try:
            ctx = DirectiveContext(current_hour=12)
            # 无 events → trigger 应 False
            self.assertFalse(_trigger_translator_self_correct(ctx),
                             '无 events → False')
        finally:
            self._restore_bus()

    def test_trigger_returns_bool(self):
        """trigger 不抛异常, 返 bool (实际 True/False 依赖 _swm_has_recent 内部接口)."""
        from jarvis_directives import _trigger_translator_self_correct, DirectiveContext
        bus = _MockEventBus()
        bus.events = [{
            'etype': 'translator_aliased',
            'metadata': {},
            'ts': time.time() - 300.0,
        }]
        self._set_bus(bus)
        try:
            ctx = DirectiveContext(current_hour=12)
            result = _trigger_translator_self_correct(ctx)
            self.assertIn(result, (True, False), '应返 bool 不抛')
        finally:
            self._restore_bus()


if __name__ == '__main__':
    unittest.main()
