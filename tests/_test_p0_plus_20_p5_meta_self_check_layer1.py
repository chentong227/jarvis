# -*- coding: utf-8 -*-
"""[P5-Layer1-fix19 / 2026-05-22] 主脑最小 thinking pass — META Self-Check

Sir 13:13 立: 给主脑加 1 行 thinking pass. 反 Sir 真测 fix16/17/18 类
"主脑被外部信号推着说错话" 痛点 (3/5 BUG).

设计:
  - jarvis_directives.meta_self_check_directive 教主脑 reply 末尾 emit
    [META] evidence=... reaction=... skip_alert=... note=...
  - jarvis_meta_self_check.parse_meta(reply) 抽 META + 裁 Sir-facing text
  - publish 'main_brain_meta' SWM event + audit jsonl 持久化
  - jarvis_claim_tracer.build_integrity_alert 看 META.skip_alert=yes 跳过 inject

Cover (12+ testcase):
  TestA: parse_meta 基本 — 单行 / 多行 / 缺失 / 损坏
  TestB: parse_meta 字段 — evidence list / reaction enum / skip_alert bool / note
  TestC: parse_meta 边界 — none / 大小写 / 多空格
  TestD: directive 注册到 registry, trigger WAKE_ONLY 跳, 其他 fire
  TestE: publish_meta + audit jsonl 端到端 (Sir 真测 case 反例)
  TestF: find_meta_for_turn — 按 turn_id 查
  TestG: build_integrity_alert 看 META.skip_alert=yes 跳过 inject
  TestH: marker / 文件存在
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_ParseMetaBasic(unittest.TestCase):
    """A: parse_meta 基本 — 单行 / 多行 / 缺失 / 损坏."""

    def test_parse_single_meta_line(self):
        from jarvis_meta_self_check import parse_meta
        reply = (
            "Yes, Sir.\n"
            "---ZH---\n"
            "好的, 先生.\n"
            "[META] evidence=stm:turn_xxx reaction=voice skip_alert=no note=ack"
        )
        sir_text, meta = parse_meta(reply)
        self.assertTrue(meta.parse_ok)
        self.assertEqual(meta.evidence, ['stm:turn_xxx'])
        self.assertEqual(meta.reaction, 'voice')
        self.assertFalse(meta.skip_alert)
        self.assertEqual(meta.note, 'ack')
        # [META] 行已裁
        self.assertNotIn('[META]', sir_text)

    def test_parse_no_meta_line(self):
        from jarvis_meta_self_check import parse_meta
        reply = "Yes, Sir.\n---ZH---\n好的, 先生."
        sir_text, meta = parse_meta(reply)
        self.assertFalse(meta.parse_ok)
        self.assertEqual(sir_text, reply)

    def test_parse_empty_reply(self):
        from jarvis_meta_self_check import parse_meta
        sir_text, meta = parse_meta('')
        self.assertEqual(sir_text, '')
        self.assertFalse(meta.parse_ok)

    def test_parse_multiple_meta_lines_takes_last(self):
        from jarvis_meta_self_check import parse_meta
        reply = (
            "Yes, Sir.\n"
            "[META] evidence=old reaction=voice skip_alert=no note=first\n"
            "(some text)\n"
            "[META] evidence=new reaction=silence skip_alert=yes note=final"
        )
        sir_text, meta = parse_meta(reply)
        self.assertTrue(meta.parse_ok)
        self.assertEqual(meta.evidence, ['new'])
        self.assertEqual(meta.reaction, 'silence')
        self.assertTrue(meta.skip_alert)
        # 所有 [META] 行都裁
        self.assertNotIn('[META]', sir_text)


class TestB_ParseMetaFields(unittest.TestCase):
    """B: parse_meta 字段 — evidence / reaction / skip_alert / note 各类型."""

    def test_evidence_comma_list(self):
        from jarvis_meta_self_check import parse_meta
        _, m = parse_meta(
            "[META] evidence=stm:turn_a,swm:cand_b,profile:loc reaction=voice skip_alert=no"
        )
        self.assertEqual(m.evidence, ['stm:turn_a', 'swm:cand_b', 'profile:loc'])
        self.assertTrue(m.has_evidence)

    def test_evidence_none_means_no_evidence(self):
        from jarvis_meta_self_check import parse_meta
        _, m = parse_meta("[META] evidence=none reaction=voice skip_alert=yes note=refusing")
        self.assertEqual(m.evidence, ['none'])
        self.assertFalse(m.has_evidence)
        self.assertTrue(m.skip_alert)

    def test_reaction_enum_validation(self):
        from jarvis_meta_self_check import parse_meta
        # 合法 enum 全部
        for r in ('voice', 'silent_text', 'silence'):
            _, m = parse_meta(f"[META] evidence=none reaction={r} skip_alert=no")
            self.assertEqual(m.reaction, r)
        # 非法 enum → fallback 'voice'
        _, m = parse_meta("[META] evidence=none reaction=garbage skip_alert=no")
        self.assertEqual(m.reaction, 'voice')

    def test_skip_alert_truthy(self):
        from jarvis_meta_self_check import parse_meta
        for v in ('yes', 'true', '1', 'YES', 'True'):
            _, m = parse_meta(f"[META] evidence=none reaction=voice skip_alert={v}")
            self.assertTrue(m.skip_alert, f'skip_alert={v} 应为 True')
        for v in ('no', 'false', '0', '', 'NO'):
            _, m = parse_meta(f"[META] evidence=none reaction=voice skip_alert={v}")
            self.assertFalse(m.skip_alert, f'skip_alert={v} 应为 False')

    def test_note_with_spaces(self):
        from jarvis_meta_self_check import parse_meta
        _, m = parse_meta(
            "[META] evidence=none reaction=voice skip_alert=no note=hold acknowledgment from Sir 5/22"
        )
        self.assertEqual(m.note, 'hold acknowledgment from Sir 5/22')

    def test_note_capped_60_chars(self):
        from jarvis_meta_self_check import parse_meta
        long_note = 'x' * 200
        _, m = parse_meta(f"[META] evidence=none reaction=voice skip_alert=no note={long_note}")
        self.assertLessEqual(len(m.note), 60)


class TestC_ParseMetaEdge(unittest.TestCase):
    """C: 边界 — 大小写 / 多空格 / [META] 在中间."""

    def test_meta_uppercase(self):
        from jarvis_meta_self_check import parse_meta
        _, m = parse_meta("[META] evidence=none reaction=voice skip_alert=no")
        self.assertTrue(m.parse_ok)
        # case-insensitive [META]
        _, m2 = parse_meta("[meta] evidence=none reaction=voice skip_alert=no")
        self.assertTrue(m2.parse_ok)

    def test_meta_extra_whitespace(self):
        from jarvis_meta_self_check import parse_meta
        _, m = parse_meta(
            "[META]   evidence=stm:t1   reaction=voice   skip_alert=no   note=trim"
        )
        self.assertTrue(m.parse_ok)
        self.assertEqual(m.evidence, ['stm:t1'])

    def test_corrupt_meta_no_eq(self):
        """[META] 后没 = 也不应 raise."""
        from jarvis_meta_self_check import parse_meta
        sir, m = parse_meta("[META] all garbage no equals here")
        # parse_ok 仍 True (parser 容错), 但字段空
        self.assertTrue(m.parse_ok)
        self.assertEqual(m.evidence, [])


class TestD_DirectiveRegistration(unittest.TestCase):
    """D: meta_self_check_directive 注册 + trigger 行为."""

    def _get_directive(self):
        """Bootstrap registry 拿 directive 实例 (不存在则 None)."""
        from jarvis_directives import DirectiveRegistry, bootstrap_default_registry
        reg = DirectiveRegistry(persist_path='/tmp/_test_dir_reg.json')
        bootstrap_default_registry(reg)
        return reg.directives.get('meta_self_check_directive')

    def test_directive_registered(self):
        d = self._get_directive()
        self.assertIsNotNone(d,
                              'meta_self_check_directive 应注册到 DirectiveRegistry')

    def test_directive_priority_10(self):
        d = self._get_directive()
        self.assertIsNotNone(d)
        self.assertEqual(d.priority, 10, 'priority 应为 10 (必触)')
        self.assertEqual(d.tier_whitelist, [], 'tier_whitelist 空 = 全 tier')

    def test_trigger_wake_only_skips(self):
        from jarvis_directives import _trigger_meta_self_check, DirectiveContext
        ctx = DirectiveContext(user_input='hello', stm=[], tier='WAKE_ONLY',
                                 has_active_plan=False)
        self.assertFalse(_trigger_meta_self_check(ctx),
                            'WAKE_ONLY tier 不应触发 (TTFT < 1s 硬约束)')

    def test_trigger_other_tiers_fire(self):
        from jarvis_directives import _trigger_meta_self_check, DirectiveContext
        for tier in ('SHORT_CHAT', 'DEEP_QUERY', 'TOOL_REQUEST', 'CRITICAL', 'FACTUAL_RECALL'):
            ctx = DirectiveContext(user_input='x', stm=[], tier=tier,
                                     has_active_plan=False)
            self.assertTrue(_trigger_meta_self_check(ctx),
                              f'tier={tier} 应触发')


class TestE_PublishAndAudit(unittest.TestCase):
    """E: publish_meta + audit jsonl 端到端 (Sir 真测 case 反例)."""

    def setUp(self):
        # 用 temp audit path
        self.tmp = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False)
        self.tmp.close()
        # 改 module path (monkey patch)
        import jarvis_meta_self_check as ms
        self._orig = ms._AUDIT_PATH
        ms._AUDIT_PATH = self.tmp.name

        class _MockBus:
            def __init__(self):
                self.events = []

            def publish(self, **kw):
                self.events.append(kw)
        self.bus = _MockBus()

    def tearDown(self):
        import jarvis_meta_self_check as ms
        ms._AUDIT_PATH = self._orig
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_publish_writes_audit_and_swm(self):
        from jarvis_meta_self_check import MetaSelfCheck, publish_meta
        m = MetaSelfCheck(
            evidence=['stm:turn_test'],
            reaction='voice',
            skip_alert=False,
            note='test',
            raw_line='[META] ...',
            parse_ok=True,
        )
        ok = publish_meta(m, turn_id='turn_test_123',
                            user_input='hello', event_bus=self.bus)
        self.assertTrue(ok)
        # SWM event published
        self.assertEqual(len(self.bus.events), 1)
        ev = self.bus.events[0]
        self.assertEqual(ev['etype'], 'main_brain_meta')
        self.assertIn('turn_test_123', ev['metadata']['turn_id'])
        # audit jsonl 写入
        with open(self.tmp.name, 'r', encoding='utf-8') as f:
            lines = [l for l in f if l.strip()]
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec['turn_id'], 'turn_test_123')

    def test_publish_failed_parse_ok_false_skipped(self):
        from jarvis_meta_self_check import MetaSelfCheck, publish_meta
        m = MetaSelfCheck(parse_ok=False)
        ok = publish_meta(m, turn_id='t1', event_bus=self.bus)
        self.assertFalse(ok)
        self.assertEqual(len(self.bus.events), 0)


class TestF_FindMetaForTurn(unittest.TestCase):
    """F: find_meta_for_turn — 按 turn_id 查."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False, mode='w', encoding='utf-8')
        # 写 3 条
        recs = [
            {'turn_id': 'turn_a', 'evidence': ['x'], 'reaction': 'voice',
             'skip_alert': False, 'note': 'a', 'ts': time.time()},
            {'turn_id': 'turn_b', 'evidence': ['y'], 'reaction': 'silence',
             'skip_alert': True, 'note': 'b', 'ts': time.time() + 1},
            {'turn_id': 'turn_a', 'evidence': ['z'], 'reaction': 'voice',
             'skip_alert': False, 'note': 'a2 (latest)', 'ts': time.time() + 2},
        ]
        for r in recs:
            self.tmp.write(json.dumps(r) + '\n')
        self.tmp.close()

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_find_returns_latest_for_turn(self):
        from jarvis_meta_self_check import find_meta_for_turn
        m = find_meta_for_turn('turn_a', audit_path=self.tmp.name)
        self.assertIsNotNone(m)
        self.assertEqual(m['note'], 'a2 (latest)')

    def test_find_skip_alert_true(self):
        from jarvis_meta_self_check import find_meta_for_turn
        m = find_meta_for_turn('turn_b', audit_path=self.tmp.name)
        self.assertIsNotNone(m)
        self.assertTrue(m['skip_alert'])

    def test_find_not_exists(self):
        from jarvis_meta_self_check import find_meta_for_turn
        m = find_meta_for_turn('turn_nope', audit_path=self.tmp.name)
        self.assertIsNone(m)

    def test_find_empty_turn_id(self):
        from jarvis_meta_self_check import find_meta_for_turn
        self.assertIsNone(find_meta_for_turn(''))


class TestG_IntegrityAlertSkipsOnSkipAlert(unittest.TestCase):
    """G: build_integrity_alert 看 META.skip_alert=yes 就跳过 inject.

    Sir 真测 fix17 case 主脑已自决拒道歉 → 本轮 ALERT 不再注入.
    """

    def setUp(self):
        # 写 audit (1 unverified claim) + meta (skip_alert=yes for that turn)
        self.audit_tmp = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False, mode='w', encoding='utf-8')
        rec = {
            'ts': time.time(),
            'iso': '2026-05-22T12:00:00',
            'turn_id': 'turn_skip_test',
            'claim': '95%',
            'kind': 'numeric',
            'found': False,
            'reason': 'no STM match',
        }
        self.audit_tmp.write(json.dumps(rec) + '\n')
        self.audit_tmp.close()

        self.meta_tmp = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False, mode='w', encoding='utf-8')
        meta_rec = {
            'turn_id': 'turn_skip_test',
            'evidence': ['none'],
            'reaction': 'voice',
            'skip_alert': True,  # 主脑明确 skip
            'note': 'integrity alert references empty turn, refuse',
            'ts': time.time(),
        }
        self.meta_tmp.write(json.dumps(meta_rec) + '\n')
        self.meta_tmp.close()

        # monkey patch META audit path
        import jarvis_meta_self_check as ms
        self._orig_meta = ms._AUDIT_PATH
        ms._AUDIT_PATH = self.meta_tmp.name

    def tearDown(self):
        import jarvis_meta_self_check as ms
        ms._AUDIT_PATH = self._orig_meta
        for p in [self.audit_tmp.name, self.meta_tmp.name]:
            try:
                os.unlink(p)
            except OSError:
                pass

    def test_skip_alert_yes_returns_empty_string(self):
        from jarvis_claim_tracer import build_integrity_alert
        result = build_integrity_alert(current_turn_id='turn_xyz_now',
                                          audit_path=self.audit_tmp.name)
        self.assertEqual(result, '',
                          '主脑 META.skip_alert=yes 时 build_integrity_alert 应返空')

    def test_no_meta_or_skip_alert_no_returns_alert(self):
        """对照: META.skip_alert=no (or no META) 时仍 inject ALERT."""
        # 把 skip_alert 改 no
        import jarvis_meta_self_check as ms
        with open(ms._AUDIT_PATH, 'w', encoding='utf-8') as f:
            f.write(json.dumps({
                'turn_id': 'turn_skip_test',
                'evidence': ['none'],
                'reaction': 'voice',
                'skip_alert': False,
                'note': '',
                'ts': time.time(),
            }) + '\n')
        from jarvis_claim_tracer import build_integrity_alert
        result = build_integrity_alert(current_turn_id='turn_xyz_now',
                                          audit_path=self.audit_tmp.name)
        self.assertIn('INTEGRITY ALERT', result,
                        'skip_alert=no 应正常 inject ALERT')
        self.assertIn('95%', result)


class TestH_MarkerCoverage(unittest.TestCase):
    """H: P5-Layer1-fix19 marker 在所有改动文件."""

    def test_markers(self):
        files = [
            'jarvis_directives.py',
            'jarvis_chat_bypass.py',
            'jarvis_claim_tracer.py',
            'jarvis_meta_self_check.py',
        ]
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for fname in files:
            path = os.path.join(base, fname)
            with open(path, 'r', encoding='utf-8') as f:
                src = f.read()
            self.assertIn('P5-Layer1', src,
                            f'P5-Layer1 marker 应在 {fname}')

    def test_meta_module_exists(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, 'jarvis_meta_self_check.py')
        self.assertTrue(os.path.exists(path))


if __name__ == '__main__':
    unittest.main()
