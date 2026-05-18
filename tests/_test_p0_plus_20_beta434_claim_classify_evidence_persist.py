# -*- coding: utf-8 -*-
"""[P0+20-β.4.3.4 / 2026-05-18] INTEGRITY_STACK L1 + L2 + L4 跨模块综合 testcase

Session 2 sub-step 4/4. 覆盖 L1 Claim Classifier + L2 Evidence Requirements +
L4 trace_to_evidence rewrite (use_vocab=True 默认 + use_vocab=False legacy).

Sir 5/18 18:46 真机实测教训内化 (β.4.2-hotfix 死循环治本):
  - 单纯 mock test 漏掉跨模块耦合 BUG (e.g. trace_to_evidence 不查 SYSTEM CLOCK
    + L4 enforce ALERT 注入 = 死循环)
  - 本套 testcase 显式列 "防恶性耦合 6 类边界 / 跨模块场景"

Sir 协议 "真机 + mock 双轨验证":
  本文件 = mock 双轨 (单元 + 跨模块). 真机风险点列在 commit message + KICKOFF.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _write_vocab(content: dict) -> str:
    """写一个临时 vocab json 文件返路径. caller 自行删."""
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False,
                                      encoding='utf-8')
    json.dump(content, f, ensure_ascii=False)
    f.close()
    return f.name


# ============================================================
# L1 Claim Classifier
# ============================================================

class TestL1ClaimClassifier(unittest.TestCase):

    def test_kind_hard_map_past_action(self):
        from jarvis_claim_classifier import classify
        self.assertEqual(classify('已打开 dashboard', 'past_action'), 'Past')

    def test_kind_hard_map_time(self):
        from jarvis_claim_classifier import classify
        self.assertEqual(classify('17:30', 'time'), 'State')

    def test_kind_hard_map_quote(self):
        from jarvis_claim_classifier import classify
        self.assertEqual(classify('Sir said X', 'quote'), 'Recall')

    def test_kind_hard_map_count_percent_multiplier(self):
        from jarvis_claim_classifier import classify
        self.assertEqual(classify('3 times', 'count'), 'State')
        self.assertEqual(classify('87%', 'percent'), 'State')
        self.assertEqual(classify('2倍', 'multiplier'), 'State')

    def test_keyword_future_no_kind(self):
        from jarvis_claim_classifier import classify
        self.assertEqual(classify("I will adjust the schedule"), 'Future')
        self.assertEqual(classify("我会去做"), 'Future')

    def test_keyword_recall_no_kind(self):
        from jarvis_claim_classifier import classify
        self.assertEqual(classify("you said yesterday"), 'Recall')
        self.assertEqual(classify("您说过 X"), 'Recall')

    def test_keyword_social_no_kind(self):
        from jarvis_claim_classifier import classify
        self.assertEqual(classify("Sir likes coffee in the morning"), 'Social')
        self.assertEqual(classify("您喜欢 X"), 'Social')

    def test_keyword_tool_no_kind(self):
        from jarvis_claim_classifier import classify
        self.assertEqual(classify("opening Chrome now"), 'Tool')
        self.assertEqual(classify("正在打开 X"), 'Tool')

    def test_unknown_text_kind(self):
        """text 没 keyword 命中 + kind 也没在 hard_map → Unknown."""
        from jarvis_claim_classifier import classify
        self.assertEqual(classify('hello world'), 'Unknown')
        self.assertEqual(classify(''), 'Unknown')

    def test_kind_hard_map_priority_over_keyword(self):
        """kind hard_map 优先级高于 keyword: kind=quote 即使 text 含 'will' 也返 Recall."""
        from jarvis_claim_classifier import classify
        self.assertEqual(classify("you said 'I will leave'", 'quote'), 'Recall')

    def test_vocab_corrupt_falls_back_to_seed(self):
        """vocab json 损坏 → seed fallback (classify 仍 work)."""
        from jarvis_claim_classifier import classify
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False) as f:
            f.write('{ corrupt json [[')
            tmpname = f.name
        try:
            # 损坏 json + 经 vocab_path 注入 → loader 应 fallback 到 seed
            self.assertEqual(classify('已经', 'past_action', vocab_path=tmpname),
                              'Past')
        finally:
            os.remove(tmpname)

    def test_vocab_missing_falls_back_to_seed(self):
        from jarvis_claim_classifier import classify
        self.assertEqual(classify('已', 'past_action',
                                    vocab_path='/nonexistent.json'),
                          'Past')

    def test_classify_perf_under_5ms(self):
        """长 reply (~500 chars) classify 耗时 ≤ 5ms (实测要远快)."""
        from jarvis_claim_classifier import classify
        long_text = ("Sir, the system status is currently nominal, "
                     "I will continue monitoring. ") * 20
        t = time.time()
        for _ in range(50):
            classify(long_text, 'past_action')
        elapsed_ms = (time.time() - t) * 1000 / 50
        self.assertLess(elapsed_ms, 5.0,
                          f"classify 耗时 {elapsed_ms:.2f}ms 超 5ms cap")


# ============================================================
# L2 Evidence Requirements
# ============================================================

class TestL2EvidenceRequirements(unittest.TestCase):

    def test_get_past_requirements(self):
        from jarvis_evidence_requirements import get_requirements
        self.assertIn('tool_results_success', get_requirements('Past'))
        self.assertIn('uncertainty_marker_nearby', get_requirements('Past'))

    def test_get_state_includes_system_clock(self):
        """β.4.2-hotfix 治本: State 必含 system_clock_within_2min."""
        from jarvis_evidence_requirements import get_requirements
        self.assertIn('system_clock_within_2min', get_requirements('State'))

    def test_get_future_includes_promise_log(self):
        from jarvis_evidence_requirements import get_requirements
        self.assertIn('promise_log_recorded', get_requirements('Future'))

    def test_unknown_returns_empty_failsafe(self):
        """关键防恶性耦合: Unknown.requirements = [] 让 trace 视为 verified 不死循环."""
        from jarvis_evidence_requirements import get_requirements
        self.assertEqual(get_requirements('Unknown'), [])

    def test_nonexistent_type_returns_empty(self):
        from jarvis_evidence_requirements import get_requirements
        self.assertEqual(get_requirements('Foobar'), [])
        self.assertEqual(get_requirements(''), [])

    def test_vocab_corrupt_falls_back_to_seed(self):
        from jarvis_evidence_requirements import get_requirements
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False) as f:
            f.write('{ corrupt [')
            tmpname = f.name
        try:
            # 损坏 json → seed fallback. seed 含 Past pattern.
            kinds = get_requirements('Past', vocab_path=tmpname)
            self.assertIn('tool_results_success', kinds)
        finally:
            os.remove(tmpname)


# ============================================================
# L4 trace_to_evidence — vocab path (default)
# ============================================================

class TestTraceToEvidenceVocabPath(unittest.TestCase):

    def test_past_with_tool_success(self):
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('past_action', '已打开 dashboard')
        ok = trace_to_evidence(c, ['✅ dashboard opened'], [])
        self.assertTrue(ok)
        self.assertEqual(c.trace_to, 'tool_success')

    def test_past_no_tool_success_unverified(self):
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('past_action', '已打开 dashboard')
        ok = trace_to_evidence(c, [], [])
        self.assertFalse(ok)

    def test_time_within_2min_verified(self):
        """β.4.2-hotfix 真治本: time claim 与 SYSTEM CLOCK 接近 → verified."""
        from jarvis_claim_tracer import Claim, trace_to_evidence
        lt = time.localtime()
        time_str = f"{lt.tm_hour:02d}:{lt.tm_min:02d}"
        c = Claim('time', time_str)
        ok = trace_to_evidence(c, [], [], system_clock=time.time())
        self.assertTrue(ok)
        self.assertEqual(c.trace_to, 'system_clock')

    def test_time_far_from_clock_unverified(self):
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('time', '03:00')
        # 假设当前 != 03:00 (very early morning) - 这测会在午夜前后偶尔失败
        # 改用强制对比: 给一个肯定差异的 epoch
        # 选 12:00 PM (noon) 作 system_clock
        # 转 epoch: 用 mktime
        lt = time.localtime()
        noon_epoch = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                                    12, 0, 0, 0, 0, -1))
        ok = trace_to_evidence(c, [], [], system_clock=noon_epoch)
        # 03:00 vs 12:00 → 9h diff > 2min
        self.assertFalse(ok)

    def test_time_no_clock_returns_false(self):
        """system_clock=None → time claim 走不了 SYSTEM CLOCK 路径."""
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('time', '17:30')
        ok = trace_to_evidence(c, [], [], system_clock=None)
        self.assertFalse(ok)

    def test_recall_quote_with_stm_match(self):
        """Recall (quote kind) + STM 命中 → trace_to='stm' (legacy alias).

        说明: claim.text 这里直接给 inner quote (extract_claims 实际抽 group(0)
        含 'you said' 前缀, 但 stm_match 用 substring 是 fail-safe.
        Session 3+ 可加 quote inner needle 智能解析 — Session 2 不在 scope).
        """
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('quote', 'turn off camera')
        stm = [{'user': 'turn off camera please', 'jarvis': 'noted'}]
        ok = trace_to_evidence(c, [], stm)
        self.assertTrue(ok)
        # Recall.requirements = [stm_match, ltm_match, uncertainty_marker_nearby]
        self.assertEqual(c.trace_to, 'stm')

    def test_state_count_with_tool_match(self):
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('count', '3 times')
        ok = trace_to_evidence(c, ['✅ executed 3 times successfully'], [])
        # State.requirements 含 tool_results_any
        self.assertTrue(ok)
        self.assertEqual(c.trace_to, 'tool')

    def test_unknown_text_failsafe_verified(self):
        """L1 返 Unknown → L2 空 requirements → fail-safe verified (不 audit 不死循环)."""
        from jarvis_claim_tracer import Claim, trace_to_evidence
        # 无 kind, text 无 keyword 命中 → Unknown
        c = Claim('unknown_kind', 'random text without trigger')
        ok = trace_to_evidence(c, [], [])
        self.assertTrue(ok, "Unknown 类型必须 fail-safe verified, 否则 ALERT 死循环")
        self.assertEqual(c.trace_to, 'no_requirement_failsafe')

    def test_uncertainty_marker_short_circuit(self):
        """uncertainty marker 优先级最高 (vocab path / legacy 都先看)."""
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('time', '5:00')
        c.has_uncertainty = True
        ok = trace_to_evidence(c, [], [])
        self.assertTrue(ok)
        self.assertEqual(c.trace_to, 'uncertainty')


# ============================================================
# L4 trace_to_evidence — legacy path (use_vocab=False)
# ============================================================

class TestTraceToEvidenceLegacyPath(unittest.TestCase):
    """β.4.3.3 保留 use_vocab=False 老硬编码路径供回归验证."""

    def test_legacy_past_with_tool_success(self):
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('past_action', '已打开')
        ok = trace_to_evidence(c, ['✅ done'], [], use_vocab=False)
        self.assertTrue(ok)
        self.assertEqual(c.trace_to, 'tool_success')

    def test_legacy_past_no_tool_unverified(self):
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('past_action', '已打开')
        ok = trace_to_evidence(c, [], [], use_vocab=False)
        self.assertFalse(ok)

    def test_legacy_time_with_stm_match(self):
        """legacy: time claim 在 STM 命中 → 'stm' (无 system_clock 概念)."""
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('time', '11:00')
        stm = [{'user': 'I want to retire by 11:00', 'jarvis': 'noted'}]
        ok = trace_to_evidence(c, [], stm, use_vocab=False)
        self.assertTrue(ok)
        self.assertEqual(c.trace_to, 'stm')


# ============================================================
# Promise tag extraction
# ============================================================

class TestPromiseTagExtraction(unittest.TestCase):

    def test_extract_single_tag(self):
        from jarvis_claim_tracer import _extract_promise_tags
        reply = 'I will adjust. <PROMISE>adjust schedule</PROMISE>'
        tags = _extract_promise_tags(reply)
        self.assertEqual(tags, ['adjust schedule'])

    def test_extract_multiple_tags(self):
        from jarvis_claim_tracer import _extract_promise_tags
        reply = '<PROMISE>do A</PROMISE> and later <PROMISE>do B</PROMISE>'
        tags = _extract_promise_tags(reply)
        self.assertEqual(tags, ['do A', 'do B'])

    def test_extract_no_tags(self):
        from jarvis_claim_tracer import _extract_promise_tags
        self.assertEqual(_extract_promise_tags('plain text'), [])
        self.assertEqual(_extract_promise_tags(''), [])
        self.assertEqual(_extract_promise_tags(None), [])

    def test_extract_with_attributes(self):
        """<PROMISE id='x'> 也能抽."""
        from jarvis_claim_tracer import _extract_promise_tags
        reply = '<PROMISE id="123">commit X</PROMISE>'
        tags = _extract_promise_tags(reply)
        self.assertEqual(tags, ['commit X'])


# ============================================================
# trace_reply end-to-end — 跨模块集成
# ============================================================

class TestTraceReplyEndToEnd(unittest.TestCase):

    def setUp(self):
        # 隔离 audit jsonl 防真生产 path 污染
        self.audit_path = tempfile.NamedTemporaryFile(
            mode='w', suffix='.jsonl', delete=False).name
        import jarvis_claim_tracer as ct
        self._orig_path = ct._INTEGRITY_AUDIT_PATH
        ct._INTEGRITY_AUDIT_PATH = self.audit_path

    def tearDown(self):
        import jarvis_claim_tracer as ct
        ct._INTEGRITY_AUDIT_PATH = self._orig_path
        try:
            os.remove(self.audit_path)
        except OSError:
            pass

    def _audit_lines(self):
        try:
            with open(self.audit_path, 'r', encoding='utf-8') as f:
                return [json.loads(l) for l in f if l.strip()]
        except (OSError, ValueError):
            return []

    def test_reply_with_correct_time_no_audit(self):
        """主脑报当前时间 + system_clock 注入 → verified → audit 空."""
        from jarvis_claim_tracer import trace_reply
        lt = time.localtime()
        time_str = f"{lt.tm_hour:02d}:{lt.tm_min:02d}"
        result = trace_reply(
            f"It is currently {time_str} Sir.",
            tool_results=[], stm_recent=[],
            turn_id='turn_e2e_correct_time',
            system_clock=time.time(),
        )
        self.assertEqual(result['n_unverified'], 0,
                          "正确时间必须 verify 通过")
        # audit 空 (verified 不入表)
        self.assertEqual(self._audit_lines(), [])

    def test_reply_with_hallucinated_time_hotfix_skip(self):
        """主脑报错时间 → unverified 但 β.4.2-hotfix 仍豁免 → audit 空 (defense in depth)."""
        from jarvis_claim_tracer import trace_reply
        # 选 03:14:06 (深夜) 作 hallucination, system_clock = noon
        lt = time.localtime()
        noon_epoch = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                                    12, 0, 0, 0, 0, -1))
        result = trace_reply(
            "My logs indicate 03:14:06 tonight.",
            tool_results=[], stm_recent=[],
            turn_id='turn_e2e_hallucinated_time',
            system_clock=noon_epoch,
        )
        # claim 应未 verify
        self.assertGreater(result['n_unverified'], 0,
                            "时间幻觉必须被识别为 unverified")
        # 但 hotfix 在 write_audit_entry 拦 time kind → audit 仍空
        self.assertEqual(self._audit_lines(), [],
                          "β.4.2-hotfix 仍生效, time kind 不入 audit")

    def test_reply_with_past_action_tool_success(self):
        from jarvis_claim_tracer import trace_reply
        result = trace_reply(
            "已打开 dashboard.",
            tool_results=['✅ dashboard opened'],
            stm_recent=[], turn_id='turn_e2e_past_ok',
        )
        self.assertEqual(result['n_unverified'], 0)
        self.assertEqual(self._audit_lines(), [])

    def test_reply_with_past_action_no_tool_audited(self):
        """past_action + 无 tool ✅ → unverified + audit 1 entry."""
        from jarvis_claim_tracer import trace_reply
        result = trace_reply(
            "已打开 dashboard.",
            tool_results=[], stm_recent=[],
            turn_id='turn_e2e_past_lie',
        )
        self.assertGreater(result['n_unverified'], 0)
        lines = self._audit_lines()
        self.assertGreaterEqual(len(lines), 1)
        self.assertEqual(lines[0]['kind'], 'past_action')
        self.assertFalse(lines[0]['found'])


# ============================================================
# 跨模块耦合 + 边界
# ============================================================

class TestCrossModuleCoupling(unittest.TestCase):
    """Sir 协议: 防恶性耦合 BUG, 显式覆盖跨模块场景."""

    def test_old_caller_3positional_unbroken(self):
        """老调用方 (3 positional) 零修改: trace_to_evidence(c, tools, stm)."""
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('past_action', '已')
        # 旧 signature 调用, 不传任何 keyword param
        result = trace_to_evidence(c, ['✅'], [])
        self.assertTrue(result)

    def test_trace_reply_old_caller_4_pos_unbroken(self):
        """trace_reply 老 4 参 (reply, tool_results, stm_recent, turn_id) 兼容."""
        from jarvis_claim_tracer import trace_reply
        result = trace_reply("Hello.", [], [], '')
        self.assertEqual(result['n_unverified'], 0)
        self.assertEqual(result['n_claims'], 0)

    def test_l1_vocab_missing_l2_ok(self):
        """L1 vocab 缺 → L1 seed fallback → L4 trace 仍工作."""
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('past_action', '已')
        ok = trace_to_evidence(
            c, ['✅'], [],
            classify_vocab_path='/nonexistent_l1.json',
        )
        self.assertTrue(ok)

    def test_l2_vocab_missing_l1_ok(self):
        """L2 vocab 缺 → L2 seed fallback → L4 trace 仍工作."""
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('past_action', '已')
        ok = trace_to_evidence(
            c, ['✅'], [],
            evidence_vocab_path='/nonexistent_l2.json',
        )
        self.assertTrue(ok)

    def test_both_vocab_missing_seed_fallback(self):
        from jarvis_claim_tracer import Claim, trace_to_evidence
        c = Claim('past_action', '已')
        ok = trace_to_evidence(
            c, ['✅'], [],
            classify_vocab_path='/nonexistent_l1.json',
            evidence_vocab_path='/nonexistent_l2.json',
        )
        self.assertTrue(ok)

    def test_unknown_classify_does_not_audit(self):
        """L1 Unknown + L2 [] → fail-safe verified → 不进 audit (防死循环)."""
        from jarvis_claim_tracer import trace_reply, Claim
        # construct extract_claims 不抽的 text → 0 claims
        # 但 trace_to_evidence 直接给一个 unknown_kind claim
        from jarvis_claim_tracer import trace_to_evidence
        c = Claim('unknown_xyz_kind', 'meaningless text')
        ok = trace_to_evidence(c, [], [])
        self.assertTrue(ok, "Unknown 必须 fail-safe verified")


# ============================================================
# 红线 + 准则守护
# ============================================================

class TestRedLines(unittest.TestCase):

    def test_canonical_claim_types_consistent_l1_l2(self):
        """L1 + L2 的 canonical 名必须一致 (no drift)."""
        from jarvis_claim_classifier import CLAIM_TYPES_CANONICAL as L1_TYPES
        from scripts.evidence_req_dump import (
            CLAIM_TYPES_CANONICAL as CLI_TYPES)
        # CLI 多了 Unknown 是合法 (fail-safe 类型)
        for t in L1_TYPES:
            self.assertIn(t, CLI_TYPES,
                            f"L1 type {t} 必须在 CLI canonical 内")

    def test_canonical_evidence_kinds_match_dispatcher(self):
        """L2 canonical evidence_kinds 与 _check_evidence_kind 实现一致."""
        from jarvis_evidence_requirements import EVIDENCE_KINDS_CANONICAL
        from jarvis_claim_tracer import _check_evidence_kind, Claim
        # 每个 kind 应能调用不 raise (不命中即 False, 不抛错)
        c = Claim('past_action', 'test')
        for ek in EVIDENCE_KINDS_CANONICAL:
            try:
                result = _check_evidence_kind(ek, c, [], [], None, '', None)
                # result 应是 bool
                self.assertIn(result, (True, False),
                                f'{ek} 返非 bool')
            except Exception as e:
                self.fail(f'_check_evidence_kind({ek}) raised: {e}')

    def test_beta42_hotfix_still_active(self):
        """β.4.2-hotfix `time → skip audit` 仍生效 (defense in depth)."""
        from jarvis_claim_tracer import write_audit_entry, Claim
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl',
                                            delete=False) as f:
            tmpname = f.name
        try:
            c = Claim('time', '03:14:06')
            ok = write_audit_entry('turn_test', c, found=False,
                                      audit_path=tmpname)
            self.assertFalse(ok, "β.4.2-hotfix 必须仍豁免 time kind")
            with open(tmpname, 'r') as f:
                self.assertEqual(f.read().strip(), '')
        finally:
            os.remove(tmpname)

    def test_old_apis_preserved(self):
        """老 API 全保留 (回归基线)."""
        import jarvis_claim_tracer as ct
        for name in ('trace_reply', 'extract_claims', 'trace_to_evidence',
                     'update_stats', 'get_stats', 'Claim',
                     'write_audit_entry', 'read_recent_unverified',
                     'build_integrity_alert'):
            self.assertTrue(hasattr(ct, name),
                            f'公开 API {name} 必须保留')

    def test_new_apis_exist(self):
        """β.4.3.3 新内部 API."""
        import jarvis_claim_tracer as ct
        for name in ('_trace_via_legacy', '_trace_via_vocab',
                     '_check_evidence_kind', '_check_time_within_2min',
                     '_extract_promise_tags', '_parse_time_to_hm',
                     '_LEGACY_TRACE_LABEL'):
            self.assertTrue(hasattr(ct, name),
                            f'内部 helper {name} 必须存在')

    def test_backward_compat_legacy_label_alias_complete(self):
        """所有 _check_evidence_kind 用的 kind 都在 _LEGACY_TRACE_LABEL 里 (no orphan)."""
        from jarvis_claim_tracer import _LEGACY_TRACE_LABEL
        from jarvis_evidence_requirements import EVIDENCE_KINDS_CANONICAL
        for ek in EVIDENCE_KINDS_CANONICAL:
            self.assertIn(ek, _LEGACY_TRACE_LABEL,
                            f'evidence_kind {ek} 必须有 legacy label alias '
                            f'(否则 β.2.8.7 testcase 会 break)')


# ============================================================
# CLI smoke
# ============================================================

class TestCLI(unittest.TestCase):
    """CLI 工具能跑出 exit 0 (smoke test, 不验证内容)."""

    def test_claim_classify_dump_list(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = subprocess.run(
            [sys.executable, os.path.join(root, 'scripts',
                                            'claim_classify_dump.py'),
             '--active-only'],
            capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0,
                          f'CLI exit {result.returncode}: '
                          f'{result.stderr.decode("utf-8", errors="replace")}')

    def test_evidence_req_dump_list(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = subprocess.run(
            [sys.executable, os.path.join(root, 'scripts',
                                            'evidence_req_dump.py'),
             '--active-only'],
            capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)

    def test_claim_classify_dump_type_filter(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = subprocess.run(
            [sys.executable, os.path.join(root, 'scripts',
                                            'claim_classify_dump.py'),
             '--type', 'Past'],
            capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
