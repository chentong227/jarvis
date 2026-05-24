# -*- coding: utf-8 -*-
"""[Translator Phase 1 / 2026-05-24 20:30] L4.6 LLM → schema 翻译层测试.

详 docs/JARVIS_TRANSLATOR_ARCHITECTURE.md
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _MockBus:
    """Mock event_bus 收 publish."""
    def __init__(self):
        self.events = []

    def publish(self, etype, description, source=None, salience=None,
                metadata=None, ttl=None):
        self.events.append({
            'etype': etype, 'desc': description, 'source': source,
            'salience': salience, 'metadata': metadata, 'ttl': ttl,
        })
        return True


class _FakeHandClass:
    """模拟 hand class. 提供 get_instruction_dict()."""
    def __init__(self, *args, **kwargs):
        pass

    def get_instruction_dict(self):
        return '''
        【fake_hand】测试用器官:
        1. "fake_command": {"q": "v"} <- 测试命令
        2. "another_cmd": {"x": "y"} <- 第二命令
        '''


class TestTranslatorImport(unittest.TestCase):
    def test_module_imports(self):
        import jarvis_translator
        self.assertTrue(hasattr(jarvis_translator, 'Translator'))
        self.assertTrue(hasattr(jarvis_translator, 'TranslationResult'))
        self.assertTrue(hasattr(jarvis_translator, 'get_default_translator'))
        self.assertTrue(hasattr(jarvis_translator, 'set_default_translator'))


class TestExactMatchPath(unittest.TestCase):
    def setUp(self):
        from jarvis_translator import Translator
        self.tr = Translator(
            hand_registry={'memory_hands': _FakeHandClass},
            hand_manifests={'memory_hands': {}},
        )

    def test_exact_organ_command(self):
        r = self.tr.translate('memory_hands', 'list_reminders', {})
        self.assertTrue(r.success)
        self.assertEqual(r.organ_name, 'memory_hands')
        self.assertEqual(r.alias_kind, 'exact')


class TestSuffixHandsAlias(unittest.TestCase):
    def setUp(self):
        from jarvis_translator import Translator
        self.tr = Translator(
            hand_registry={'memory_hands': _FakeHandClass},
            hand_manifests={'memory_hands': {}},
        )

    def test_short_name_aliases_to_full(self):
        # 'memory' → 'memory_hands' 走 vocab_alias 路径 (vocab.json 有 active alias_002)
        r = self.tr.translate('memory', 'list_reminders', {})
        self.assertTrue(r.success)
        self.assertEqual(r.organ_name, 'memory_hands')
        # 可能是 'vocab_alias' (vocab.json hit) 或 'suffix_hands' (fallback). 都 OK.
        self.assertIn(r.alias_kind, ('vocab_alias', 'suffix_hands'))

    def test_unknown_short_name_tries_suffix_hands(self):
        # 'random_xyz' (vocab 没) → +'_hands' 也没 → 反向 lookup → 找到 _FakeHandClass
        # 但 fake_command 在 _FakeHandClass 才反向 lookup
        r = self.tr.translate('random_xyz', 'fake_command', {})
        self.assertTrue(r.success)
        self.assertEqual(r.organ_name, 'memory_hands')
        self.assertEqual(r.alias_kind, 'by_command')


class TestVocabAlias(unittest.TestCase):
    """vocab.json 持久化 alias 测试 (memory_pool/translator_alias_vocab.json)."""

    def setUp(self):
        from jarvis_translator import Translator
        self.tr = Translator(
            hand_registry={'memory_hands': _FakeHandClass},
            hand_manifests={'memory_hands': {}},
        )

    def test_reminder_hands_alias_active(self):
        """alias_001: reminder_hands → memory_hands status=active."""
        r = self.tr.translate('reminder_hands', 'list_reminders', {})
        self.assertTrue(r.success)
        self.assertEqual(r.organ_name, 'memory_hands')

    def test_review_status_not_aliased(self):
        """alias_004: todo → memory_hands status=review (不 active 不生效)."""
        r = self.tr.translate('todo', 'list_reminders', {})
        # status=review 不应 alias, 但 todo 不是 valid organ → 走反向 cmd lookup
        # list_reminders 在 _FakeHandClass 没有 → 总体 fail unknown_organ
        # (除非反向 lookup 命中其他 organ)
        # 这个 test 验 status=review 不被 vocab_alias 路径 alias
        # 通过 alias_kind 判断: 不应是 'vocab_alias'
        if r.success:
            self.assertNotEqual(r.alias_kind, 'vocab_alias')


class TestSchemaValidation(unittest.TestCase):
    """Lv2 schema 验证 (translator_schema_vocab.json)."""

    def setUp(self):
        from jarvis_translator import Translator
        # 真用 memory_hands class (l4_memory_hands.py) 让 schema 路径生效
        try:
            from l4_hands_pool.l4_memory_hands import Hands as MemHands
        except Exception:
            MemHands = _FakeHandClass
        self.tr = Translator(
            hand_registry={'memory_hands': MemHands},
            hand_manifests={'memory_hands': {}},
        )

    def test_add_reminder_missing_intent_fails(self):
        """add_reminder 缺 intent → schema fail + actionable msg."""
        r = self.tr.translate('memory_hands', 'add_reminder',
                              {'trigger_time': '2026-05-25 08:00:00'})
        self.assertFalse(r.success)
        self.assertEqual(r.error_kind, 'missing_param')
        self.assertIn('intent', r.actionable_msg)
        self.assertIn('Sir', r.actionable_msg)

    def test_add_reminder_missing_trigger_time_fails(self):
        r = self.tr.translate('memory_hands', 'add_reminder', {'intent': 'X'})
        self.assertFalse(r.success)
        self.assertEqual(r.error_kind, 'missing_param')
        self.assertIn('trigger_time', r.actionable_msg)

    def test_add_reminder_full_params_succeeds(self):
        r = self.tr.translate('memory_hands', 'add_reminder',
                              {'intent': 'X', 'trigger_time': '2026-05-25 08:00:00'})
        self.assertTrue(r.success)
        self.assertTrue(r.schema_validated)


class TestMalformedGuard(unittest.TestCase):
    def setUp(self):
        from jarvis_translator import Translator
        self.tr = Translator(hand_registry={}, hand_manifests={})

    def test_none_organ_returns_malformed(self):
        r = self.tr.translate(None, 'cmd', {})
        self.assertFalse(r.success)
        self.assertEqual(r.error_kind, 'malformed')
        self.assertIn('FAST_CALL malformed', r.actionable_msg)

    def test_none_command_returns_malformed(self):
        r = self.tr.translate('organ', None, {})
        self.assertFalse(r.success)
        self.assertEqual(r.error_kind, 'malformed')

    def test_empty_string_returns_malformed(self):
        r = self.tr.translate('  ', 'cmd', {})
        self.assertFalse(r.success)
        self.assertEqual(r.error_kind, 'malformed')


class TestUnknownOrganActionable(unittest.TestCase):
    def setUp(self):
        from jarvis_translator import Translator
        self.tr = Translator(
            hand_registry={'memory_hands': _FakeHandClass, 'system_hands': _FakeHandClass},
            hand_manifests={},
        )

    def test_unknown_organ_lists_registered(self):
        r = self.tr.translate('xyz_unknown', 'do_something', {})
        self.assertFalse(r.success)
        self.assertEqual(r.error_kind, 'unknown_organ')
        self.assertIn('memory_hands', r.actionable_msg)


class TestSWMPublish(unittest.TestCase):
    def setUp(self):
        from jarvis_translator import Translator
        self.bus = _MockBus()
        self.tr = Translator(
            hand_registry={'memory_hands': _FakeHandClass},
            hand_manifests={},
            event_bus=self.bus,
        )

    def test_aliased_publishes_event(self):
        # vocab.json 有 reminder_hands → memory_hands active
        self.tr.translate('reminder_hands', 'list_reminders', {})
        types_pubd = [e['etype'] for e in self.bus.events]
        self.assertIn('translator_aliased', types_pubd)

    def test_rejected_publishes_event(self):
        self.tr.translate('xyz_unknown', 'cmd', {})
        types_pubd = [e['etype'] for e in self.bus.events]
        self.assertIn('translator_rejected', types_pubd)

    def test_exact_no_aliased_publish(self):
        # exact 命中不该 publish translator_aliased (节省 SWM 量)
        self.tr.translate('memory_hands', 'list_reminders', {})
        types_pubd = [e['etype'] for e in self.bus.events]
        self.assertNotIn('translator_aliased', types_pubd)


class TestStatsAPI(unittest.TestCase):
    def setUp(self):
        from jarvis_translator import Translator
        self.tr = Translator(
            hand_registry={'memory_hands': _FakeHandClass},
            hand_manifests={},
        )

    def test_stats_returns_dict(self):
        stats = self.tr.get_stats()
        self.assertIn('alias_total', stats)
        self.assertIn('alias_active', stats)
        self.assertIn('hand_registry_size', stats)
        # vocab.json seed 有 4 alias (3 active + 1 review)
        self.assertGreaterEqual(stats['alias_total'], 4)
        self.assertGreaterEqual(stats['alias_active'], 3)
        self.assertEqual(stats['hand_registry_size'], 1)


class TestVocabSchemaFiles(unittest.TestCase):
    def test_alias_vocab_file_exists(self):
        path = os.path.join(ROOT, 'memory_pool', 'translator_alias_vocab.json')
        self.assertTrue(os.path.exists(path), 'vocab.json 必须存在')

    def test_schema_vocab_file_exists(self):
        path = os.path.join(ROOT, 'memory_pool', 'translator_schema_vocab.json')
        self.assertTrue(os.path.exists(path), 'schema_vocab.json 必须存在')

    def test_alias_vocab_has_seed(self):
        import json
        path = os.path.join(ROOT, 'memory_pool', 'translator_alias_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        aliases = data.get('aliases', [])
        self.assertGreaterEqual(len(aliases), 4)
        # alias_001 必为 reminder_hands → memory_hands
        first = aliases[0]
        self.assertEqual(first.get('from'), 'reminder_hands')
        self.assertEqual(first.get('to'), 'memory_hands')
        self.assertEqual(first.get('status'), 'active')


class TestSWMEtypeRegistered(unittest.TestCase):
    """jarvis_utils.py DEFAULT_TTL + DEFAULT_SALIENCE 必须含 4 个 translator etype."""

    def test_etypes_in_default_ttl(self):
        with open(os.path.join(ROOT, 'jarvis_utils.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        for etype in ('translator_aliased', 'translator_rejected',
                      'translator_schema_matched', 'translator_proposed'):
            self.assertIn(f"'{etype}'", src, f'etype {etype} 必须在 jarvis_utils.py 注册')


class TestFEATUREFlag(unittest.TestCase):
    """chat_bypass 灰度切: JARVIS_FEATURE_TRANSLATOR=1 才启用."""

    def test_feature_flag_present(self):
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('JARVIS_FEATURE_TRANSLATOR', src,
                      '灰度 flag 必须在 chat_bypass 检 env')
        self.assertIn('Translator Phase 1', src,
                      'Phase 1 标识注释必须在 chat_bypass')


class TestCLIScript(unittest.TestCase):
    def test_cli_script_exists(self):
        path = os.path.join(ROOT, 'scripts', 'translator_alias_dump.py')
        self.assertTrue(os.path.exists(path), 'CLI 必须存在')


if __name__ == '__main__':
    unittest.main()
