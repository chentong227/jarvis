# -*- coding: utf-8 -*-
"""[fix4 / Sir 2026-05-26 00:25 真痛"地基没打牢"] InnerThought evidence linking.

Sir 真痛 (真机 log evidence):
  💭 [InnerThought] [C/sal=0.80/state=active/tick=60s]
    I've noticed Sir toggling between general tasks and coding quite rapidly
    over the last thirty second
    | actionable=update_concern_severity:sir_interview_pr → sev 0.20→0.30 (+0.10)
  Sir: "为什么这加面试重要性呢? 地基都没打牢吧?"

真因: prompt 没强制 LLM 证明 "thought 内容能 trace 到 actionable", LLM 拍脑袋
  选 sir_interview_pr (虽然 thought 内容跟面试完全无关).

治本 (双层 gate, 准则 6 evidence-driven):
  L1: LLM 必须 cite THOUGHT 中真实出现的 1-5 词 → Python 校验 cite 在 thought 里
      (防 hallucinate cite)
  L2: 对 update_concern_severity, cite 词跟 concern (id+what_i_watch) 至少 1
      meaningful token 重合 (防 wrong concern, 治 Sir 真痛 anchor)

测试覆盖:
  L1 dataclass evidence_link field
  L2 parser 解析 <EVIDENCE_LINK> + 缺失不 crash
  L3 _validate_evidence_link (6 case: none/empty/cite-in/cite-out/case-insensitive/multi-word-50%)
  L4 _evidence_links_to_concern (4 case: overlap/no-overlap/stopword-排/empty)
  L5 _execute_actionable 端到端 (rejected_no_evidence_link / evidence_link_wrong_concern / pass)
  L6 Sir 真痛 anchor 端到端 (toggling + interview_pr → reject)
  L7 正例端到端 (without rest + pomodoro → pass)
  L8 actionable=none 不需要 link (no-op)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _empty_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    tmp = os.path.join(tempfile.gettempdir(),
                          f'fix4_{time.time()}.jsonl')
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp
    try:
        d = InnerThoughtDaemon(key_router=None)
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp
    return d


def _mk_thought(thought_text: str, actionable: str = 'none',
                  evidence_link: str = '', category: str = 'C',
                  salience: float = 0.7):
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id=f't_{time.time()}',
        ts=time.time(),
        ts_iso='?',
        category=category,
        thought=thought_text,
        salience=salience,
        actionable=actionable,
        evidence_link=evidence_link,
    )


# ==========================================================================
# L1: dataclass
# ==========================================================================
class TestL1Dataclass(unittest.TestCase):
    def test_evidence_link_field_default_empty(self):
        from jarvis_inner_thought_daemon import InnerThought
        t = InnerThought(
            id='t', ts=time.time(), ts_iso='?', category='C',
            thought='x', salience=0.5, actionable='none',
        )
        self.assertEqual(t.evidence_link, '',
            'evidence_link 默认 "" (老 jsonl reload 兼容)')

    def test_evidence_link_field_settable(self):
        from jarvis_inner_thought_daemon import InnerThought
        t = InnerThought(
            id='t', ts=time.time(), ts_iso='?', category='C',
            thought='x', salience=0.5, actionable='none',
            evidence_link='some cite',
        )
        self.assertEqual(t.evidence_link, 'some cite')


# ==========================================================================
# L2: parser
# ==========================================================================
class TestL2Parser(unittest.TestCase):
    def test_parse_all_5_tags(self):
        d = _empty_daemon()
        raw = (
            '<CATEGORY>C</CATEGORY>\n'
            '<THOUGHT>Sir is toggling without rest between tasks.</THOUGHT>\n'
            '<SALIENCE>0.7</SALIENCE>\n'
            '<ACTIONABLE>update_concern_severity:sir_pomodoro:+0.1</ACTIONABLE>\n'
            '<EVIDENCE_LINK>without rest</EVIDENCE_LINK>'
        )
        t = d._parse_thought(raw, 'active', 60)
        self.assertIsNotNone(t)
        self.assertEqual(t.category, 'C')
        self.assertEqual(t.evidence_link, 'without rest',
            'parser 必须真解析 EVIDENCE_LINK tag')

    def test_parse_missing_evidence_link_no_crash(self):
        """缺 EVIDENCE_LINK tag (老 LLM 输出) → evidence_link='' 不 crash."""
        d = _empty_daemon()
        raw = (
            '<CATEGORY>A</CATEGORY>\n'
            '<THOUGHT>quiet observation</THOUGHT>\n'
            '<SALIENCE>0.3</SALIENCE>\n'
            '<ACTIONABLE>none</ACTIONABLE>'
            # 缺 EVIDENCE_LINK tag
        )
        t = d._parse_thought(raw, 'active', 60)
        self.assertIsNotNone(t)
        self.assertEqual(t.evidence_link, '')

    def test_parse_evidence_link_truncated(self):
        """超长 cite 截到 120 char (防 LLM 输出 prompt 注入)."""
        d = _empty_daemon()
        long_cite = 'a' * 300
        raw = (
            '<CATEGORY>A</CATEGORY>\n'
            '<THOUGHT>test</THOUGHT>\n'
            '<SALIENCE>0.3</SALIENCE>\n'
            '<ACTIONABLE>none</ACTIONABLE>\n'
            f'<EVIDENCE_LINK>{long_cite}</EVIDENCE_LINK>'
        )
        t = d._parse_thought(raw, 'active', 60)
        self.assertIsNotNone(t)
        self.assertLessEqual(len(t.evidence_link), 120)


# ==========================================================================
# L3: _validate_evidence_link (第一层 gate)
# ==========================================================================
class TestL3ValidateEvidenceLink(unittest.TestCase):
    def setUp(self):
        self.d = _empty_daemon()

    def test_empty_cite_fail(self):
        t = _mk_thought('Sir is coding', evidence_link='')
        ok, reason = self.d._validate_evidence_link(t)
        self.assertFalse(ok)
        self.assertIn('no_cite', reason)

    def test_none_cite_fail(self):
        t = _mk_thought('Sir is coding', evidence_link='none')
        ok, reason = self.d._validate_evidence_link(t)
        self.assertFalse(ok)
        self.assertIn('no_cite', reason)

    def test_cite_in_thought_pass(self):
        t = _mk_thought(
            'Sir is toggling without rest between tasks',
            evidence_link='without rest',
        )
        ok, _ = self.d._validate_evidence_link(t)
        self.assertTrue(ok, 'cite "without rest" 真在 thought → 通过')

    def test_cite_not_in_thought_fail(self):
        """治本 anchor: LLM 编 cite — 字串不在 thought 里 → reject."""
        t = _mk_thought(
            'Sir is coding rapidly',
            evidence_link='drinking water',  # 编的 cite, 不在 thought
        )
        ok, reason = self.d._validate_evidence_link(t)
        self.assertFalse(ok)
        self.assertIn('cite_not_in_thought', reason)

    def test_case_insensitive_and_punctuation_strip(self):
        """大小写 + 标点不影响匹配."""
        t = _mk_thought(
            'Sir is Coding! Quite focused.',
            evidence_link='quite focused',  # 大小写不同
        )
        ok, _ = self.d._validate_evidence_link(t)
        self.assertTrue(ok)

    def test_multi_word_50pct_fallback(self):
        """LLM cite 多词 — 即使顺序/连续不一致, 50% 词命中也算 (兜底)."""
        t = _mk_thought(
            'Sir is toggling rapidly without much rest at all',
            evidence_link='without rest',  # 不连续, 但 2/2 词都在
        )
        ok, _ = self.d._validate_evidence_link(t)
        self.assertTrue(ok)


# ==========================================================================
# L4: _evidence_links_to_concern (第二层 gate, Sir 真痛 anchor)
# ==========================================================================
class TestL4EvidenceLinksToConcern(unittest.TestCase):
    def setUp(self):
        self.d = _empty_daemon()

    def _mk_concern(self, cid: str, what: str):
        c = MagicMock()
        c.id = cid
        c.what_i_watch = what
        c.severity = 0.5
        return c

    def test_overlap_pass(self):
        """cite "without rest" + concern "work-rest pomodoro" → overlap=rest."""
        c = self._mk_concern(
            'sir_pomodoro_compliance',
            'Sir work-rest cycle pomodoro 25 minute intervals',
        )
        ok, reason = self.d._evidence_links_to_concern('without rest', c)
        self.assertTrue(ok)
        self.assertIn('rest', reason.lower())

    def test_no_overlap_fail_sir_real_pain(self):
        """🎯 Sir 真痛 anchor 治本:
        cite "toggling general coding" + concern sir_interview_pr → no overlap → reject.
        """
        c = self._mk_concern(
            'sir_interview_pr',
            'Sir interview preparation balance and progress',
        )
        ok, reason = self.d._evidence_links_to_concern(
            'toggling general coding', c
        )
        self.assertFalse(ok,
            'Sir 真痛 anchor: toggling/general/coding 跟 interview/preparation 无 overlap → 必须 reject')
        self.assertIn('no_token_overlap', reason)

    def test_stopword_not_count(self):
        """全 stopword cite → no meaningful cite tokens → 信任 LLM (pass).

        "sir/me/my/i" 在 stopword list (所有 concern/thought 都有这些通用词,
        不能算 meaningful link). 这种情况兜底信任 LLM (准则 6).
        """
        c = self._mk_concern('sir_hydration_habit', 'Sir drinks water regularly')
        ok, reason = self.d._evidence_links_to_concern('Sir me my', c)
        # "sir/me/my" 全 stopword → cite_tokens 空 → trust LLM (pass)
        self.assertTrue(ok,
            f'全 stopword cite 应 trust LLM, got reason: {reason}')
        self.assertIn('trust LLM', reason)

    def test_meaningful_cite_no_overlap_fails(self):
        """补丁: cite 有 meaningful 词但跟 concern 无 overlap → fail (区分 stopword case).

        cite "here" 不是 stopword, 跟 concern "hydration/drinks/water" 无 overlap → fail.
        """
        c = self._mk_concern('sir_hydration_habit', 'Sir drinks water regularly')
        ok, reason = self.d._evidence_links_to_concern('here', c)
        self.assertFalse(ok,
            'meaningful cite 但跟 concern 无 overlap → 应 reject (非 trust case)')
        self.assertIn('no_token_overlap', reason)

    def test_concern_id_underscore_split(self):
        """concern id 拆 underscore 也算 token 源."""
        c = self._mk_concern(
            'sir_pomodoro_compliance',
            '',  # what 空, 只看 id
        )
        ok, reason = self.d._evidence_links_to_concern(
            'pomodoro break needed', c
        )
        self.assertTrue(ok)
        self.assertIn('pomodoro', reason.lower())


# ==========================================================================
# L5: _execute_actionable 端到端 双层 gate
# ==========================================================================
class TestL5ExecuteActionable(unittest.TestCase):
    def setUp(self):
        self.d = _empty_daemon()

    def test_actionable_none_no_link_needed(self):
        """actionable=none 不需要 evidence_link."""
        t = _mk_thought('quiet moment', actionable='none', evidence_link='')
        ok, result = self.d._execute_actionable(t)
        self.assertTrue(ok)
        self.assertEqual(result, 'none')

    def test_rejected_no_evidence_link_first_gate(self):
        """第一层 gate: actionable != none + 无 cite → 降级."""
        t = _mk_thought(
            'Sir seems tired',
            actionable='update_concern_severity:sir_sleep_streak:+0.1',
            evidence_link='',
        )
        ok, result = self.d._execute_actionable(t)
        self.assertFalse(ok)
        self.assertIn('rejected_no_evidence_link', result)
        # 降级: thought.actionable 改 none (SOUL inject 不误导)
        self.assertEqual(t.actionable, 'none')

    def test_rejected_cite_not_in_thought(self):
        """第一层 gate: cite 不在 thought → 降级."""
        t = _mk_thought(
            'Sir is coding',
            actionable='update_concern_severity:sir_sleep:+0.1',
            evidence_link='drinking water',  # 编的
        )
        ok, result = self.d._execute_actionable(t)
        self.assertFalse(ok)
        self.assertIn('rejected_no_evidence_link', result)
        self.assertEqual(t.actionable, 'none')


# ==========================================================================
# L6: Sir 真痛 anchor 端到端
# ==========================================================================
class TestL6SirRealPainAnchor(unittest.TestCase):
    def setUp(self):
        self.d = _empty_daemon()
        # mock concerns_ledger 含 sir_interview_pr concern
        self.ledger = MagicMock()
        interview_concern = MagicMock()
        interview_concern.id = 'sir_interview_pr'
        interview_concern.what_i_watch = (
            'Sir interview preparation balance and progress'
        )
        interview_concern.severity = 0.2
        self.ledger.get = MagicMock(return_value=interview_concern)
        # update_concern_field 返回 success (但不应被调到)
        self.ledger.update_concern_field = MagicMock(
            return_value=(True, '', 0.2)
        )
        self.d.concerns_ledger = self.ledger

    def test_sir_real_pain_toggling_to_interview_rejected(self):
        """🎯 Sir 真机 evidence 端到端测试:
        thought: "Sir toggling between general tasks and coding quite rapidly"
        actionable: update_concern_severity:sir_interview_pr:+0.1
        cite: "toggling" (cite 真在 thought, 第一层 pass)
        expected: 第二层 fail (toggling/general/coding 跟 interview/preparation 无 overlap)
                  → actionable 降级 none
                  → severity NOT 真改 (update_concern_field 不被调)
        """
        t = _mk_thought(
            'Sir is toggling between general tasks and coding quite rapidly',
            actionable='update_concern_severity:sir_interview_pr:+0.1',
            evidence_link='toggling',  # cite 真在 thought, 防第一层
        )
        ok, result = self.d._execute_actionable(t)
        self.assertFalse(ok,
            'Sir 真痛 anchor: 必须 reject (cite 在 thought 但 wrong concern)')
        self.assertIn('evidence_link_wrong_concern', result)
        self.assertIn('sir_interview_pr', result)
        # actionable 降级 (SOUL inject 不误导)
        self.assertEqual(t.actionable, 'none')
        # severity 真没被改
        self.ledger.update_concern_field.assert_not_called()


# ==========================================================================
# L7: 正例端到端
# ==========================================================================
class TestL7CorrectActionableFires(unittest.TestCase):
    def setUp(self):
        self.d = _empty_daemon()
        self.ledger = MagicMock()
        pomodoro_concern = MagicMock()
        pomodoro_concern.id = 'sir_pomodoro_compliance'
        pomodoro_concern.what_i_watch = (
            'Sir work-rest cycle compliance with pomodoro 25min intervals'
        )
        pomodoro_concern.severity = 0.5
        self.ledger.get = MagicMock(return_value=pomodoro_concern)
        self.ledger.update_concern_field = MagicMock(
            return_value=(True, '', 0.5)
        )
        self.d.concerns_ledger = self.ledger

    def test_correct_concern_with_grounded_cite_fires(self):
        """正例: cite 真在 thought + cite ↔ concern overlap → 真 execute.

        thought: "Sir is toggling rapidly without rest" (有"without rest")
        cite: "without rest" (第一层 pass)
        target: sir_pomodoro_compliance (what 含 "rest" → overlap)
        expected: severity 真改, update_concern_field 真调
        """
        t = _mk_thought(
            'Sir is toggling rapidly without rest between coding sessions',
            actionable='update_concern_severity:sir_pomodoro_compliance:+0.1',
            evidence_link='without rest',
        )
        ok, result = self.d._execute_actionable(t)
        self.assertTrue(ok,
            f'正例必须 pass, got result: {result}')
        self.assertIn('sev', result)
        # update_concern_field 真被调
        self.ledger.update_concern_field.assert_called_once()


# ==========================================================================
# L8: prompt 含 grounding rule (anchor)
# ==========================================================================
class TestL8PromptHasGroundingRule(unittest.TestCase):
    def test_prompt_has_evidence_link_tag(self):
        """prompt 必须含 EVIDENCE_LINK tag + grounding example."""
        d = _empty_daemon()
        sys_p, _ = d._build_prompt('active', {'sir_state': 'active'},
                                       free_categories=['A', 'B', 'C'])
        self.assertIn('EVIDENCE_LINK', sys_p,
            'prompt 必须含 EVIDENCE_LINK tag 教 LLM 输出')
        self.assertIn('verify the cite', sys_p,
            'prompt 必须明示 Python 会校验 cite (强约束 LLM)')
        # 含 ❌/✅ example (Sir 真痛 anchor 教学)
        self.assertIn('interview_pr', sys_p.lower(),
            'prompt 必须含 Sir 真痛 anchor BAD example (toggling → interview_pr 是 wrong)')
        self.assertIn('pomodoro', sys_p.lower(),
            'prompt 必须含 GOOD example (without rest → pomodoro 是 correct)')


if __name__ == '__main__':
    unittest.main()
