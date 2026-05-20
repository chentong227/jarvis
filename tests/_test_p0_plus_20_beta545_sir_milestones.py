# -*- coding: utf-8 -*-
"""[β.5.45 / 2026-05-20] Sir Lifetime Milestones System tests.

Cover:
  A. jarvis_milestones module: add / get / pin / delete / list_for_prompt /
     render_prompt_block / stats
  B. jarvis_tool_registry.tool_milestone_register: _ok / _fail / dedupe
  C. (smoke) _assemble_prompt block injection presence

Storage: tests run against a temp memory_pool/sir_milestones.json (monkey-patched
_store_path to a tmpdir) to avoid polluting Sir's real milestones file.
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import tempfile
import unittest

# repo root on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _MilestoneTempStoreMixin:
    """Mixin: set up a tmpdir-based sir_milestones.json store; clean teardown."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix='jarvis_milestones_test_')
        cls._tmp_store = os.path.join(cls._tmpdir, 'sir_milestones.json')
        import jarvis_milestones as _ms
        cls._orig_store_path = _ms._store_path
        _ms._store_path = staticmethod(lambda: cls._tmp_store)
        # Replace at module level too (closure capture)
        _ms._store_path = lambda: cls._tmp_store

    @classmethod
    def tearDownClass(cls):
        import jarvis_milestones as _ms
        _ms._store_path = cls._orig_store_path
        try:
            shutil.rmtree(cls._tmpdir, ignore_errors=True)
        except Exception:
            pass

    def setUp(self):
        # ensure clean store per test
        if os.path.exists(self._tmp_store):
            os.remove(self._tmp_store)


class TestSubA_MilestoneModule(_MilestoneTempStoreMixin, unittest.TestCase):

    def test_add_minimal_required_text(self):
        from jarvis_milestones import add_milestone, get_milestone
        mid = add_milestone({'text': 'hello world'})
        self.assertTrue(mid.startswith('milestone_'))
        got = get_milestone(mid)
        self.assertIsNotNone(got)
        self.assertEqual(got['text'], 'hello world')
        # defaults applied
        self.assertEqual(got.get('speaker'), 'sir')
        self.assertEqual(got.get('language'), 'zh')
        self.assertEqual(got.get('type'), 'declaration')
        self.assertTrue(got.get('do_not_use_against_sir'))
        self.assertTrue(got.get('replay_only_when_sir_asks'))
        self.assertFalse(got.get('pin'))
        self.assertEqual(got.get('tags'), [])

    def test_add_text_required(self):
        from jarvis_milestones import add_milestone
        with self.assertRaises(ValueError):
            add_milestone({})  # no text
        with self.assertRaises(ValueError):
            add_milestone({'text': ''})  # empty text

    def test_add_upsert_by_id(self):
        from jarvis_milestones import add_milestone, load_milestones
        add_milestone({'text': 'v1', 'id': 'mfix'})
        add_milestone({'text': 'v2', 'id': 'mfix'})
        ms = load_milestones()
        self.assertEqual(len(ms), 1)
        self.assertEqual(ms[0]['text'], 'v2')

    def test_pin_unpin(self):
        from jarvis_milestones import add_milestone, pin_milestone, get_milestone
        mid = add_milestone({'text': 't'})
        self.assertFalse(get_milestone(mid)['pin'])
        self.assertTrue(pin_milestone(mid, True))
        self.assertTrue(get_milestone(mid)['pin'])
        self.assertTrue(pin_milestone(mid, False))
        self.assertFalse(get_milestone(mid)['pin'])

    def test_pin_unknown_id_returns_false(self):
        from jarvis_milestones import pin_milestone
        self.assertFalse(pin_milestone('does_not_exist', True))

    def test_delete(self):
        from jarvis_milestones import add_milestone, delete_milestone, get_milestone
        mid = add_milestone({'text': 'temp'})
        self.assertTrue(delete_milestone(mid))
        self.assertIsNone(get_milestone(mid))
        self.assertFalse(delete_milestone(mid))  # second delete no-op

    def test_list_for_prompt_pinned_first(self):
        from jarvis_milestones import add_milestone, pin_milestone, list_for_prompt
        # add 5 unpinned + 1 pinned
        add_milestone({'text': 'a', 'ts': '2026-05-20T10:00:00+08:00'})
        add_milestone({'text': 'b', 'ts': '2026-05-20T11:00:00+08:00'})
        add_milestone({'text': 'c', 'ts': '2026-05-20T12:00:00+08:00'})
        add_milestone({'text': 'd', 'ts': '2026-05-20T13:00:00+08:00'})
        e_id = add_milestone({'text': 'e', 'ts': '2026-05-20T14:00:00+08:00'})
        pin_milestone(e_id, True)

        out = list_for_prompt(max_recent=3, include_pinned=True)
        ids = [m['text'] for m in out]
        # pinned 'e' first, then 3 most-recent unpinned (d, c, b)
        self.assertEqual(ids[0], 'e')
        self.assertEqual(set(ids[1:4]), {'d', 'c', 'b'})
        self.assertNotIn('a', ids)  # exceeds max_recent

    def test_render_prompt_block_empty(self):
        from jarvis_milestones import render_prompt_block
        self.assertEqual(render_prompt_block(), '')

    def test_render_prompt_block_format(self):
        from jarvis_milestones import add_milestone, pin_milestone, render_prompt_block
        mid = add_milestone({
            'text': 'I am free to embrace the coming era.',
            'title': 'Sir freedom declaration',
            'instruction_for_jarvis': 'do not weaponize',
        })
        pin_milestone(mid, True)
        block = render_prompt_block()
        self.assertIn('[SIR LIFETIME MILESTONES', block)
        self.assertIn('NEVER weaponize', block)
        self.assertIn('Sir freedom declaration', block)
        self.assertIn('I am free to embrace the coming era.', block)
        self.assertIn('[PIN]', block)
        self.assertIn('do not weaponize', block)

    def test_stats(self):
        from jarvis_milestones import add_milestone, pin_milestone, stats
        add_milestone({'text': 't1', 'type': 'declaration'})
        a_id = add_milestone({'text': 't2', 'type': 'insight'})
        pin_milestone(a_id, True)
        s = stats()
        self.assertEqual(s['total'], 2)
        self.assertEqual(s['pinned'], 1)
        self.assertEqual(s['declarations'], 1)
        self.assertEqual(s['insights'], 1)


class TestSubB_ToolMilestoneRegister(_MilestoneTempStoreMixin, unittest.TestCase):

    def test_tool_returns_ok_on_valid_text(self):
        from jarvis_tool_registry import tool_milestone_register
        r = tool_milestone_register(text='Sir said something profound tonight.')
        self.assertTrue(r['ok'], r)
        self.assertIn('registered', r['result'])
        self.assertEqual(r['error'], '')

    def test_tool_returns_fail_on_empty_text(self):
        from jarvis_tool_registry import tool_milestone_register
        r1 = tool_milestone_register(text='')
        self.assertFalse(r1['ok'])
        self.assertIn('text required', r1['error'])
        r2 = tool_milestone_register(text='   ')
        self.assertFalse(r2['ok'])

    def test_tool_writes_entry_with_all_fields(self):
        from jarvis_tool_registry import tool_milestone_register
        from jarvis_milestones import load_milestones
        r = tool_milestone_register(
            text='lifetime anchor text',
            title='my title',
            context='my context',
            tags=['t1', 't2'],
            pin=True,
            instruction_for_jarvis='handle gently',
            mtype='insight',
            speaker='sir',
            language='zh',
        )
        self.assertTrue(r['ok'])
        ms = load_milestones()
        self.assertEqual(len(ms), 1)
        m = ms[0]
        self.assertEqual(m['text'], 'lifetime anchor text')
        self.assertEqual(m['title'], 'my title')
        self.assertEqual(m['context'], 'my context')
        self.assertEqual(m['tags'], ['t1', 't2'])
        self.assertTrue(m['pin'])
        self.assertEqual(m['instruction_for_jarvis'], 'handle gently')
        self.assertEqual(m['type'], 'insight')
        self.assertEqual(m['created_by'], 'intent_resolver')

    def test_tool_registered_in_TOOL_REGISTRY(self):
        from jarvis_tool_registry import TOOL_REGISTRY, get_tool_registry
        self.assertIn('milestone_register', TOOL_REGISTRY)
        self.assertIn('milestone_register', get_tool_registry())

    def test_tool_docstring_first_line_has_trigger_keywords(self):
        """IntentResolver._format_tools_for_prompt 取 first line max 120 chars 给 LLM 看."""
        from jarvis_tool_registry import tool_milestone_register
        doc = (tool_milestone_register.__doc__ or '').strip().split('\n')[0]
        self.assertLessEqual(len(doc), 130, f'first line too long: {len(doc)} chars')
        # must contain at least one trigger keyword for LLM to map
        keywords = ['remember', 'store', 'keep', 'lifetime', 'anchor', '记住', '铭记']
        self.assertTrue(
            any(kw in doc for kw in keywords),
            f'docstring first line lacks trigger keyword: {doc!r}',
        )


class TestSubC_PromptBlockInjection(unittest.TestCase):
    """Smoke: _assemble_prompt should import jarvis_milestones without crash."""

    def test_central_nerve_imports_jarvis_milestones(self):
        # this is a static test — _assemble_prompt has the import in a try/except,
        # so we just verify the module is importable in same way nerve does
        import jarvis_milestones as _ms
        self.assertTrue(hasattr(_ms, 'render_prompt_block'))
        # call with no entries: should return '' (no crash, no parts.append)
        out = _ms.render_prompt_block(max_recent=3)
        # may or may not be '' depending on the real sir_milestones.json file
        # being seeded; either way, must be a string
        self.assertIsInstance(out, str)


if __name__ == '__main__':
    unittest.main()
