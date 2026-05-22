# -*- coding: utf-8 -*-
"""[P5-fix20-B2 / 2026-05-22] META.commitments + commitment mismatch 检查测试.

Sir 14:32 真测痛点: 主脑嘴上说"我已记下" 但 IntentResolver 0 tool_called → 嘴上说没真做.

测试覆盖 (~10 条):
  A: parse_meta 解析 commitments=a;b;c (分号) / a,b,c (逗号)
  B: parse_meta commitments=none → 空 list
  C: MetaSelfCheck.to_dict 含 commitments
  D: check_commitments_vs_mutations — ok/partial/mismatch/no_commitments
  E: render_commitment_mismatch_block — 输出格式 + mismatch=False 不渲染
  F: directive 含 commitments 字段教学
  G: central_nerve prompt 注入 [COMMITMENT MISMATCH] block (静态检查)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestA_ParseCommitments(unittest.TestCase):
    """A: parse_meta 解析 commitments 字段."""

    def test_semicolon_list(self):
        from jarvis_meta_self_check import parse_meta
        reply = ("Hello Sir.\n"
                 "[META] evidence=stm:x reaction=voice skip_alert=no "
                 "commitments=hold dashboard 72h;noted Sir's correction;"
                 "register reminder 8pm note=ok")
        _, m = parse_meta(reply)
        self.assertTrue(m.parse_ok)
        self.assertEqual(len(m.commitments), 3)
        self.assertEqual(m.commitments[0], 'hold dashboard 72h')
        self.assertIn("noted Sir's correction", m.commitments[1])
        self.assertIn('register reminder 8pm', m.commitments[2])

    def test_comma_list_when_no_semicolon(self):
        from jarvis_meta_self_check import parse_meta
        reply = ("[META] evidence=stm:x reaction=voice skip_alert=no "
                 "commitments=noteA,noteB,noteC note=ok")
        _, m = parse_meta(reply)
        self.assertEqual(m.commitments, ['noteA', 'noteB', 'noteC'])

    def test_none_literal(self):
        from jarvis_meta_self_check import parse_meta
        reply = ("[META] evidence=stm:x reaction=voice skip_alert=no "
                 "commitments=none note=just chatting")
        _, m = parse_meta(reply)
        self.assertEqual(m.commitments, [])

    def test_missing_field_default_empty(self):
        from jarvis_meta_self_check import parse_meta
        # 没 commitments 字段
        reply = ("[META] evidence=stm:x reaction=voice skip_alert=no note=ok")
        _, m = parse_meta(reply)
        self.assertEqual(m.commitments, [])

    def test_to_dict_has_commitments(self):
        from jarvis_meta_self_check import MetaSelfCheck
        m = MetaSelfCheck(commitments=['x', 'y'], parse_ok=True)
        d = m.to_dict()
        self.assertEqual(d['commitments'], ['x', 'y'])


class TestB_CheckCommitments(unittest.TestCase):
    """B: check_commitments_vs_mutations — 各种 status."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False,
                                                  mode='w', encoding='utf-8')
        self.tmp.close()
        self.turn = 'turn_test_abc'

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _seed_meta(self, commitments):
        rec = {
            'turn_id': self.turn,
            'commitments': commitments,
            'evidence': ['stm:x'],
            'reaction': 'voice',
            'skip_alert': False,
            'note': '',
            'ts': time.time(),
            'iso': '2026-05-22',
        }
        with open(self.tmp.name, 'w', encoding='utf-8') as f:
            f.write(json.dumps(rec) + '\n')

    def _mock_bus(self, tool_called_events):
        bus = mock.MagicMock()
        bus.recent_events.return_value = tool_called_events
        return bus

    def test_no_meta(self):
        from jarvis_meta_self_check import check_commitments_vs_mutations
        # tmp 文件空
        r = check_commitments_vs_mutations(self.turn, audit_path=self.tmp.name)
        self.assertEqual(r['status'], 'no_meta')
        self.assertFalse(r['mismatch'])

    def test_no_commitments(self):
        from jarvis_meta_self_check import check_commitments_vs_mutations
        self._seed_meta([])
        bus = self._mock_bus([])
        r = check_commitments_vs_mutations(self.turn, event_bus=bus,
                                              audit_path=self.tmp.name)
        self.assertEqual(r['status'], 'no_commitments')
        self.assertFalse(r['mismatch'])

    def test_ok_all_mutations_succeeded(self):
        from jarvis_meta_self_check import check_commitments_vs_mutations
        self._seed_meta(['hold X', 'noted'])
        evs = [
            {'metadata': {'turn_id': self.turn, 'ok': True, 'via': 'fast_path'}},
            {'metadata': {'turn_id': self.turn, 'ok': True, 'via': 'llm'}},
        ]
        bus = self._mock_bus(evs)
        r = check_commitments_vs_mutations(self.turn, event_bus=bus,
                                              audit_path=self.tmp.name)
        self.assertEqual(r['status'], 'ok')
        self.assertFalse(r['mismatch'])
        self.assertEqual(r['mutations_ok'], 2)

    def test_partial_mismatch(self):
        from jarvis_meta_self_check import check_commitments_vs_mutations
        self._seed_meta(['hold X', 'noted', 'remember Y'])
        evs = [
            {'metadata': {'turn_id': self.turn, 'ok': True}},
            {'metadata': {'turn_id': self.turn, 'ok': False}},
        ]
        bus = self._mock_bus(evs)
        r = check_commitments_vs_mutations(self.turn, event_bus=bus,
                                              audit_path=self.tmp.name)
        self.assertEqual(r['status'], 'partial')
        self.assertTrue(r['mismatch'])
        self.assertEqual(r['mutations_ok'], 1)
        self.assertEqual(r['mutations_fail'], 1)

    def test_full_mismatch_0_tool_called(self):
        """Sir 14:32 真测场景: 主脑 commitments=3 但 IntentResolver 0 mutation."""
        from jarvis_meta_self_check import check_commitments_vs_mutations
        self._seed_meta(['hold X', 'noted', 'remember Y'])
        bus = self._mock_bus([])  # 0 tool_called
        r = check_commitments_vs_mutations(self.turn, event_bus=bus,
                                              audit_path=self.tmp.name)
        self.assertEqual(r['status'], 'mismatch')
        self.assertTrue(r['mismatch'])
        self.assertEqual(r['mutations_ok'], 0)

    def test_filters_by_turn_id(self):
        from jarvis_meta_self_check import check_commitments_vs_mutations
        self._seed_meta(['hold X'])
        # 其他 turn 的 tool_called 不算
        evs = [
            {'metadata': {'turn_id': 'other_turn', 'ok': True}},
        ]
        bus = self._mock_bus(evs)
        r = check_commitments_vs_mutations(self.turn, event_bus=bus,
                                              audit_path=self.tmp.name)
        self.assertEqual(r['mutations_ok'], 0)
        self.assertTrue(r['mismatch'])


class TestC_RenderBlock(unittest.TestCase):
    """C: render_commitment_mismatch_block 输出."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False,
                                                  mode='w', encoding='utf-8')
        self.tmp.close()
        self.turn = 'turn_render_test'

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _seed_meta(self, commitments):
        rec = {
            'turn_id': self.turn,
            'commitments': commitments,
            'evidence': ['stm:x'],
            'reaction': 'voice',
            'skip_alert': False,
            'note': '',
            'ts': time.time(),
        }
        with open(self.tmp.name, 'w', encoding='utf-8') as f:
            f.write(json.dumps(rec) + '\n')

    def test_render_empty_when_no_mismatch(self):
        """mismatch=False (commitments OK) → 返空."""
        from jarvis_meta_self_check import render_commitment_mismatch_block
        self._seed_meta([])  # no commitments
        block = render_commitment_mismatch_block(self.turn,
                                                     audit_path=self.tmp.name)
        self.assertEqual(block, '')

    def test_render_mismatch_block_content(self):
        from jarvis_meta_self_check import render_commitment_mismatch_block
        self._seed_meta(['hold X', 'noted'])
        # 不 mock bus → bus 是 None → mismatch=True
        block = render_commitment_mismatch_block(self.turn,
                                                     audit_path=self.tmp.name)
        self.assertIn('COMMITMENT MISMATCH', block)
        self.assertIn('P5-fix20-B2', block)
        self.assertIn('hold X', block)
        self.assertIn('准则 5', block)


class TestD_DirectiveCommitments(unittest.TestCase):
    """D: directive 含 commitments 教学."""

    def test_directive_has_commitments_field(self):
        from jarvis_directives import get_default_registry
        reg = get_default_registry()
        target = reg.directives.get('meta_self_check_directive')
        self.assertIsNotNone(target)
        # directive 模板含 commitments
        self.assertIn('commitments=', target.text)
        # 含 P5-fix20-B2 marker
        self.assertIn('P5-fix20-B2', target.text)
        # 含反"嘴上说没真做"硬规
        self.assertIn('do NOT list a commitment', target.text)


class TestE_NerveIntegration(unittest.TestCase):
    """E: central_nerve 注入 [COMMITMENT MISMATCH] block (静态源码检查)."""

    def test_nerve_imports_render(self):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'),
                  'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('render_commitment_mismatch_block', src)
        self.assertIn('COMMITMENT MISMATCH', src)
        self.assertIn('P5-fix20-B2', src)


class TestF_Marker(unittest.TestCase):
    """F: marker P5-fix20-B2 出现在所有相关源码."""

    def test_marker_in_meta_self_check(self):
        with open(os.path.join(ROOT, 'jarvis_meta_self_check.py'),
                  'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('P5-fix20-B2', src)
        self.assertIn('check_commitments_vs_mutations', src)
        self.assertIn('render_commitment_mismatch_block', src)

    def test_marker_in_directives(self):
        with open(os.path.join(ROOT, 'jarvis_directives.py'),
                  'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('P5-fix20-B2', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
