# -*- coding: utf-8 -*-
"""[轴3-L3.1 / 2026-05-15] PromiseParser + PROMISE_PROTOCOL_DIRECTIVE — 测试套件

覆盖：
  TestPromiseParserExtract       — 标签抽取 + 多 PROMISE / 容错
  TestPromiseParserSchema        — JSON schema 校验
  TestPromiseDraftClassify       — has_dangerous_skill / get_unknown_skills
  TestPromiseParserDraftToLedger — 集成 PlanLedger 真 draft
  TestPromiseProtocolDirective   — directive 字符串关键内容

跑法：
    cd d:\\Jarvis
    python tests/_test_r8_axis3_l3_1_promise_parser.py
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_skill_registry import (
    SkillRegistry,
    SkillManifest,
    DANGER_SAFE,
    DANGER_RISKY,
    DANGER_DANGEROUS,
    PromiseParser,
    PromiseDraft,
    PromiseParseError,
    PROMISE_PROTOCOL_DIRECTIVE,
    PROMISE_TAG_RE,
    get_registry,
)
from jarvis_utils import PlanLedger


def _make(command='audio.list', danger=DANGER_SAFE, **k):
    base = dict(command=command, module='m', callable_name='c',
                description='d', dangerous_flag=danger)
    base.update(k)
    return SkillManifest(**base)


# ==========================================================================
# 标签抽取
# ==========================================================================

class TestPromiseParserExtract(unittest.TestCase):

    def test_single_promise_extracted(self):
        text = '''
Some response text.
<PROMISE>
{"goal": "diagnose 403", "steps": [{"description": "查 KeyRouter", "skill": "key_health.report"}]}
</PROMISE>
Shall I proceed, Sir?
'''
        drafts = PromiseParser.extract_all(text)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].goal, 'diagnose 403')
        self.assertEqual(len(drafts[0].steps), 1)
        self.assertEqual(drafts[0].steps[0]['skill'], 'key_health.report')

    def test_multiple_promises_extracted(self):
        text = '''
<PROMISE>{"goal": "G1", "steps": [{"description": "step1"}]}</PROMISE>
some chat
<PROMISE>{"goal": "G2", "steps": [{"description": "step2"}]}</PROMISE>
'''
        drafts = PromiseParser.extract_all(text)
        self.assertEqual(len(drafts), 2)
        self.assertEqual(drafts[0].goal, 'G1')
        self.assertEqual(drafts[1].goal, 'G2')

    def test_no_promise_returns_empty(self):
        self.assertEqual(PromiseParser.extract_all("Hello Sir"), [])
        self.assertEqual(PromiseParser.extract_all(""), [])
        self.assertEqual(PromiseParser.extract_all(None), [])

    def test_corrupt_promise_skipped_not_aborted(self):
        """损坏的 PROMISE 不应阻塞其他正确 PROMISE 的解析"""
        text = '''
<PROMISE>NOT JSON AT ALL</PROMISE>
<PROMISE>{"goal": "valid", "steps": [{"description": "step"}]}</PROMISE>
'''
        drafts = PromiseParser.extract_all(text)
        self.assertEqual(len(drafts), 1, '损坏的应跳过，正确的应通过')
        self.assertEqual(drafts[0].goal, 'valid')

    def test_has_promise_tag_detection(self):
        self.assertTrue(PromiseParser.has_promise_tag('hi <PROMISE>x</PROMISE> bye'))
        self.assertFalse(PromiseParser.has_promise_tag('no tag here'))
        self.assertFalse(PromiseParser.has_promise_tag(''))

    def test_case_insensitive_tag(self):
        text = '<promise>{"goal": "g", "steps": [{"description": "s"}]}</promise>'
        drafts = PromiseParser.extract_all(text)
        self.assertEqual(len(drafts), 1)


# ==========================================================================
# JSON schema 校验
# ==========================================================================

class TestPromiseParserSchema(unittest.TestCase):

    def _wrap(self, json_str):
        return f'<PROMISE>{json_str}</PROMISE>'

    def test_missing_goal_skipped(self):
        text = self._wrap('{"steps": [{"description": "x"}]}')
        self.assertEqual(len(PromiseParser.extract_all(text)), 0)

    def test_empty_goal_skipped(self):
        text = self._wrap('{"goal": "", "steps": [{"description": "x"}]}')
        self.assertEqual(len(PromiseParser.extract_all(text)), 0)

    def test_steps_not_list_skipped(self):
        text = self._wrap('{"goal": "g", "steps": "not a list"}')
        self.assertEqual(len(PromiseParser.extract_all(text)), 0)

    def test_step_missing_description_skipped(self):
        text = self._wrap('{"goal": "g", "steps": [{"skill": "x"}]}')
        self.assertEqual(len(PromiseParser.extract_all(text)), 0)

    def test_no_steps_field_uses_empty_list(self):
        """{"goal": "g"} 没 steps → 视为空步骤承诺"""
        text = self._wrap('{"goal": "just a thought"}')
        drafts = PromiseParser.extract_all(text)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].steps, [])

    def test_root_not_dict_skipped(self):
        text = self._wrap('["g", []]')
        self.assertEqual(len(PromiseParser.extract_all(text)), 0)

    def test_goal_truncated_at_300(self):
        long = 'x' * 500
        text = self._wrap(json.dumps({'goal': long, 'steps': []}))
        drafts = PromiseParser.extract_all(text)
        self.assertEqual(len(drafts[0].goal), 300)


# ==========================================================================
# PromiseDraft 分类（dangerous / unknown skills）
# ==========================================================================

class TestPromiseDraftClassify(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = get_registry()
        self.reg.register(_make('audio.list', danger=DANGER_SAFE))
        self.reg.register(_make('file.delete', danger=DANGER_DANGEROUS))

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_no_dangerous_when_only_safe_skills(self):
        d = PromiseDraft(goal='g', steps=[
            {'description': 's', 'skill': 'audio.list'},
        ])
        self.assertFalse(d.has_dangerous_skill())

    def test_dangerous_detected(self):
        d = PromiseDraft(goal='g', steps=[
            {'description': 's1', 'skill': 'audio.list'},
            {'description': 's2', 'skill': 'file.delete'},
        ])
        self.assertTrue(d.has_dangerous_skill())
        self.assertEqual(d.get_dangerous_skills(), ['file.delete'])

    def test_unknown_skills_detected(self):
        d = PromiseDraft(goal='g', steps=[
            {'description': 's1', 'skill': 'audio.list'},
            {'description': 's2', 'skill': 'totally_made_up.skill'},
        ])
        unknown = d.get_unknown_skills()
        self.assertEqual(unknown, ['totally_made_up.skill'])

    def test_required_skills_auto_extracted_from_steps(self):
        d = PromiseDraft(goal='g', steps=[
            {'description': 's1', 'skill': 'audio.list'},
            {'description': 's2', 'skill': None},
            {'description': 's3', 'skill': 'file.delete'},
        ])
        self.assertEqual(d.required_skills, ['audio.list', 'file.delete'])


# ==========================================================================
# 集成 PlanLedger 真 draft
# ==========================================================================

class TestPromiseParserDraftToLedger(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = get_registry()
        self.reg.register(_make('audio.list', danger=DANGER_SAFE))
        self.reg.register(_make('file.delete', danger=DANGER_DANGEROUS))
        self.tmpdir = tempfile.mkdtemp()
        self.ledger_path = os.path.join(self.tmpdir, 'plans.json')
        self.ledger = PlanLedger(persist_path=self.ledger_path, autosave=False)

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_draft_to_ledger_creates_plan_in_awaiting_go(self):
        text = '''
<PROMISE>
{"goal": "diagnose 403", "steps": [{"description": "查 keys", "skill": "audio.list"}]}
</PROMISE>
'''
        drafts = PromiseParser.extract_all(text)
        plan_ids = PromiseParser.draft_to_ledger(drafts, self.ledger)
        self.assertEqual(len(plan_ids), 1)
        plan = self.ledger.get(plan_ids[0])
        self.assertIsNotNone(plan)
        self.assertEqual(plan['state'], 'awaiting_go',
            'PromiseParser draft 应自动流转到 awaiting_go')
        self.assertEqual(plan['goal'], 'diagnose 403')
        self.assertEqual(len(plan['steps']), 1)

    def test_metadata_carries_dangerous_flag(self):
        text = '<PROMISE>{"goal": "delete stuff", "steps": [{"description": "rm", "skill": "file.delete"}]}</PROMISE>'
        drafts = PromiseParser.extract_all(text)
        plan_ids = PromiseParser.draft_to_ledger(drafts, self.ledger)
        plan = self.ledger.get(plan_ids[0])
        self.assertIn('file.delete', plan['metadata'].get('dangerous_skills', []),
            'metadata 必须标 dangerous_skills 让 PromiseLedger L3.3 决定不自动跑')

    def test_metadata_carries_unknown_skills(self):
        text = '<PROMISE>{"goal": "g", "steps": [{"description": "s", "skill": "fake.skill"}]}</PROMISE>'
        drafts = PromiseParser.extract_all(text)
        plan_ids = PromiseParser.draft_to_ledger(drafts, self.ledger)
        plan = self.ledger.get(plan_ids[0])
        self.assertIn('fake.skill', plan['metadata'].get('unknown_skills', []),
            'LLM 编造的 skill 名必须被标 unknown_skills (Integrity Check 用)')

    def test_no_drafts_yields_no_plans(self):
        plan_ids = PromiseParser.draft_to_ledger([], self.ledger)
        self.assertEqual(plan_ids, [])

    def test_none_ledger_returns_empty(self):
        plan_ids = PromiseParser.draft_to_ledger([
            PromiseDraft('g', [{'description': 's'}]),
        ], None)
        self.assertEqual(plan_ids, [])


# ==========================================================================
# PROMISE_PROTOCOL_DIRECTIVE 字符串
# ==========================================================================

class TestPromiseProtocolDirective(unittest.TestCase):

    def test_directive_marker_present(self):
        self.assertIn('PROMISE PROTOCOL', PROMISE_PROTOCOL_DIRECTIVE)
        self.assertIn('言出必行', PROMISE_PROTOCOL_DIRECTIVE)

    def test_directive_explains_tag_format(self):
        self.assertIn('<PROMISE>', PROMISE_PROTOCOL_DIRECTIVE)
        self.assertIn('</PROMISE>', PROMISE_PROTOCOL_DIRECTIVE)
        self.assertIn('"goal"', PROMISE_PROTOCOL_DIRECTIVE)
        self.assertIn('"steps"', PROMISE_PROTOCOL_DIRECTIVE)
        self.assertIn('"skill"', PROMISE_PROTOCOL_DIRECTIVE)

    def test_directive_warns_against_invented_skills(self):
        self.assertIn('Do NOT invent skill names', PROMISE_PROTOCOL_DIRECTIVE)

    def test_directive_explains_go_yes_protocol(self):
        for kw in ['go', 'yes']:
            self.assertIn(kw, PROMISE_PROTOCOL_DIRECTIVE)

    def test_directive_says_when_to_use_promise(self):
        self.assertIn('multi-step', PROMISE_PROTOCOL_DIRECTIVE.lower())


# ==========================================================================
# nerve.py 集成接入源码契约
# ==========================================================================

class TestNerveIntegrationContract(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_marker_present(self):
        self.assertIn('[轴3-L3.1 / 2026-05-15]', self.src,
            'jarvis_nerve.py 必须有 [轴3-L3.1] marker')

    def test_assemble_prompt_computes_promise_directive(self):
        """_assemble_prompt 顶部必须计算 promise_protocol_directive"""
        import re
        m = re.search(
            r'def _assemble_prompt.*?promise_protocol_directive\s*=\s*""\s*\n.*?'
            r'from jarvis_skill_registry import PROMISE_PROTOCOL_DIRECTIVE',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            '_assemble_prompt 必须计算 promise_protocol_directive')

    def test_full_mode_injects_promise_directive(self):
        """full mode 必须注入 promise_protocol_directive"""
        self.assertIn('{promise_protocol_directive}', self.src,
            'full mode prompt 必须含 {promise_protocol_directive} 占位')

    def test_stream_chat_parses_promise_tag(self):
        """stream_chat 末尾必须解析 PROMISE → draft 到 ledger
        允许 ledger 参数用任意 ref 名（plan_ledger_ref / self.jarvis.plan_ledger）。
        """
        import re
        m = re.search(
            r'PromiseParser\.has_promise_tag\(full_text\).*?'
            r'PromiseParser\.extract_all\(full_text\).*?'
            r'PromiseParser\.draft_to_ledger\(drafts,\s*[\w\.]+\)',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            'stream_chat 必须 has_promise_tag → extract_all → draft_to_ledger 链路')

    def test_promise_log_marker(self):
        self.assertIn('[PromiseLedger]', self.src,
            'draft 成功必须 bg_log [PromiseLedger]')


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("[OK] All R8 axis3 L3.1 PromiseParser tests passed.")
    else:
        print(f"[FAIL] {len(result.failures)} failures, {len(result.errors)} errors")
    print("=" * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
