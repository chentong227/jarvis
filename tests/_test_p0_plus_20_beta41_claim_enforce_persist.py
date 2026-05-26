# -*- coding: utf-8 -*-
"""[P0+20-β.4.1 / 2026-05-18] INTEGRITY_STACK L4 enforce — ClaimTracer 升级

Session 1 任务: ClaimTracer 从 trace 升级 enforce.
  - jarvis_claim_tracer.write_audit_entry: 仅 unverified 入 memory_pool/integrity_audit.jsonl
  - jarvis_claim_tracer.read_recent_unverified: 读 tail + 过滤 found=false / exclude_turn_id
  - jarvis_claim_tracer.build_integrity_alert: 构造 [INTEGRITY ALERT] 串 (准则 5/6)
  - jarvis_central_nerve._assemble_prompt: 调 build_integrity_alert prepend 到 system_alert_text

设计准则 (testcase 守):
  - 准则 5 (言出必行): ALERT 必须 trace 上轮 claim 事实, 不能空头
  - 准则 6 (不硬编码): ALERT 不教主脑具体中文/英文句式, 不写"撤回时说 X"
  - 准则 6.5 (动态 schema): audit_path 可注入, jsonl append-only, mtime 不必 cache
"""
import json
import os
import sys
import tempfile
import time
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _FakeClaim:
    """模拟 jarvis_claim_tracer.Claim 的最小 duck-type."""

    def __init__(self, kind: str = 'past_action', text: str = '已打开 dashboard',
                 trace_to=None):
        self.kind = kind
        self.text = text
        self.trace_to = trace_to


def _new_tmp_jsonl() -> str:
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False,
                                      encoding='utf-8')
    f.close()
    return f.name


class TestWriteAuditEntry(unittest.TestCase):
    def setUp(self):
        from jarvis_claim_tracer import write_audit_entry
        self.write = write_audit_entry
        self.path = _new_tmp_jsonl()

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_write_unverified_appends_jsonl_line(self):
        c = _FakeClaim('past_action', '已打开 chrome')
        ok = self.write('turn_test_001', c, found=False,
                          reason='no ✅', audit_path=self.path)
        self.assertTrue(ok)
        with open(self.path, 'r', encoding='utf-8') as f:
            lines = [l for l in f.readlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        e = json.loads(lines[0])
        self.assertEqual(e['turn_id'], 'turn_test_001')
        self.assertEqual(e['claim'], '已打开 chrome')
        self.assertEqual(e['kind'], 'past_action')
        self.assertFalse(e['found'])
        self.assertEqual(e['reason'], 'no ✅')
        self.assertIn('ts', e)
        self.assertIn('iso', e)

    def test_write_verified_skips_jsonl(self):
        """准则 6.5: verified entry 不入表 (防文件膨胀, 只记 incident)."""
        c = _FakeClaim('time', '17:30')
        ok = self.write('turn_test_002', c, found=True, audit_path=self.path)
        self.assertFalse(ok)
        # 文件应仍为空
        with open(self.path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertEqual(content.strip(), '')

    def test_write_multiple_appends(self):
        # β.4.2-hotfix: time kind 已豁免 audit, 此 case 改用 state (普通 unverified kind) 测多写
        c1 = _FakeClaim('past_action', 'A')
        c2 = _FakeClaim('past_action', 'B')
        c3 = _FakeClaim('state', 'dashboard active')
        self.write('t1', c1, found=False, audit_path=self.path)
        self.write('t1', c2, found=False, audit_path=self.path)
        self.write('t1', c3, found=False, audit_path=self.path)
        with open(self.path, 'r', encoding='utf-8') as f:
            lines = [l for l in f.readlines() if l.strip()]
        self.assertEqual(len(lines), 3)

    def test_write_truncates_long_claim_text(self):
        long_text = 'x' * 500
        c = _FakeClaim('past_action', long_text)
        self.write('t1', c, found=False, audit_path=self.path)
        with open(self.path, 'r', encoding='utf-8') as f:
            e = json.loads(f.readline())
        self.assertLessEqual(len(e['claim']), 200)

    def test_write_missing_dir_creates_it(self):
        d = tempfile.mkdtemp()
        # 创新 subdir
        target = os.path.join(d, 'new_sub', 'audit.jsonl')
        c = _FakeClaim('past_action', 'X')
        ok = self.write('t', c, found=False, audit_path=target)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(target))
        try:
            os.remove(target)
            os.rmdir(os.path.dirname(target))
            os.rmdir(d)
        except OSError:
            pass


class TestReadRecentUnverified(unittest.TestCase):
    def setUp(self):
        from jarvis_claim_tracer import write_audit_entry, read_recent_unverified
        self.write = write_audit_entry
        self.read = read_recent_unverified
        self.path = _new_tmp_jsonl()

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_read_missing_file_returns_empty(self):
        bogus = '/nonexistent/audit_x.jsonl'
        self.assertEqual(self.read(audit_path=bogus), [])

    def test_read_empty_file_returns_empty(self):
        self.assertEqual(self.read(audit_path=self.path), [])

    def test_read_returns_only_unverified(self):
        # 全是 unverified (verified 本身不写)
        # β.4.2-hotfix: 'time' 改 'state' 避开 hotfix 豁免 (time kind 不进 audit)
        for i, kind in enumerate(['past_action', 'state', 'count']):
            self.write(f't{i}', _FakeClaim(kind, f'claim_{i}'),
                          found=False, audit_path=self.path)
        entries = self.read(audit_path=self.path)
        self.assertEqual(len(entries), 3)
        for e in entries:
            self.assertFalse(e['found'])

    def test_read_filters_exclude_turn_id(self):
        self.write('turn_curr', _FakeClaim(), found=False, audit_path=self.path)
        self.write('turn_prior', _FakeClaim(), found=False, audit_path=self.path)
        entries = self.read(exclude_turn_id='turn_curr', audit_path=self.path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['turn_id'], 'turn_prior')

    def test_read_respects_limit(self):
        for i in range(10):
            self.write(f't{i}', _FakeClaim(text=f'c{i}'),
                          found=False, audit_path=self.path)
        entries = self.read(limit=3, audit_path=self.path)
        self.assertEqual(len(entries), 3)
        # tail 3 应是 c7/c8/c9
        texts = [e['claim'] for e in entries]
        self.assertEqual(texts, ['c7', 'c8', 'c9'])

    def test_read_handles_corrupt_line(self):
        """坏 json 行应 skip 不 crash."""
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('{ this is not json [[\n')
            f.write(json.dumps({
                'ts': 1.0, 'iso': 'x', 'turn_id': 't_ok',
                'claim': 'ok', 'kind': 'past_action',
                'evidence_kind': '', 'found': False, 'reason': '',
            }) + '\n')
        entries = self.read(audit_path=self.path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['turn_id'], 't_ok')


class TestBuildIntegrityAlert(unittest.TestCase):
    def setUp(self):
        from jarvis_claim_tracer import build_integrity_alert, write_audit_entry
        self.build = build_integrity_alert
        self.write = write_audit_entry
        self.path = _new_tmp_jsonl()

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_no_audit_file_returns_empty(self):
        self.assertEqual(self.build(audit_path='/nonexistent.jsonl'), '')

    def test_empty_audit_returns_empty(self):
        self.assertEqual(self.build(audit_path=self.path), '')

    def test_current_turn_only_returns_empty(self):
        """当 audit 里只有 current_turn_id 的 entries → 不应 alert (排除自己)."""
        self.write('turn_curr', _FakeClaim(), found=False, audit_path=self.path)
        result = self.build(current_turn_id='turn_curr', audit_path=self.path)
        self.assertEqual(result, '')

    def test_alert_contains_prior_turn_id_and_count(self):
        self.write('turn_prior', _FakeClaim('past_action', '已打开 dashboard'),
                     found=False, audit_path=self.path)
        result = self.build(current_turn_id='turn_curr', audit_path=self.path)
        self.assertIn('[INTEGRITY ALERT]', result)
        self.assertIn('turn_prior', result)
        self.assertIn('1', result)  # n=1 unverified
        self.assertIn('past_action', result)
        self.assertIn('已打开 dashboard', result)

    def test_alert_picks_immediate_prior_turn_not_older(self):
        """多 prior turn → 应取 ts 最大的那个 (immediate prior)."""
        # 老 turn
        c1 = _FakeClaim('past_action', 'old_claim')
        self.write('turn_old', c1, found=False, audit_path=self.path)
        time.sleep(0.05)
        # 新 turn (immediate prior)
        c2 = _FakeClaim('past_action', 'recent_claim')
        self.write('turn_recent', c2, found=False, audit_path=self.path)
        result = self.build(current_turn_id='turn_curr', audit_path=self.path)
        self.assertIn('turn_recent', result)
        self.assertIn('recent_claim', result)
        self.assertNotIn('turn_old', result)
        self.assertNotIn('old_claim', result)

    def test_alert_aggregates_same_turn_multiple_claims(self):
        """同 prior turn 多 claim → 都列在 alert 里 (limit 3)."""
        for i, t in enumerate(['claim_a', 'claim_b', 'claim_c']):
            self.write('turn_prior', _FakeClaim('past_action', t),
                          found=False, audit_path=self.path)
        result = self.build(current_turn_id='turn_curr', audit_path=self.path)
        self.assertIn('3', result)  # n=3
        for t in ['claim_a', 'claim_b', 'claim_c']:
            self.assertIn(t, result)

    def test_alert_caps_examples_at_3_with_summary(self):
        """同 prior turn 超 3 claim → 列前 3 + '+N more'."""
        for i in range(5):
            self.write('turn_prior', _FakeClaim('past_action', f'c{i}'),
                          found=False, audit_path=self.path)
        result = self.build(current_turn_id='turn_curr', audit_path=self.path)
        self.assertIn('5', result)  # n=5
        self.assertIn('+2 more', result)
        # 前 3 都在
        for t in ['c0', 'c1', 'c2']:
            self.assertIn(t, result)

    def test_alert_offers_two_choices_withdraw_or_supply(self):
        """准则 5: ALERT 提两个选项 (撤回 OR 补 evidence), 不强制单一动作."""
        self.write('turn_prior', _FakeClaim(), found=False, audit_path=self.path)
        result = self.build(current_turn_id='turn_curr', audit_path=self.path)
        # 两个 keyword 都在
        self.assertIn('withdraw', result.lower())
        self.assertIn('evidence', result.lower())
        # 至少一个 'or' / 'either' 标示两选项
        self.assertTrue('or' in result.lower() or 'either' in result.lower())

    def test_alert_does_not_prescribe_chinese_phrasing(self):
        """准则 6: ALERT 不写 '说"其实"' / '用"On reflection"开头' 等句式锁."""
        self.write('turn_prior', _FakeClaim(), found=False, audit_path=self.path)
        result = self.build(current_turn_id='turn_curr', audit_path=self.path)
        # 反例: 这些禁词若出现 = 在教句式
        forbidden = [
            "On reflection",
            "I'm sorry",
            "其实",
            '说"',  # 教措辞
            "use the phrase",
            "begin with",
            "Sir~",
        ]
        for w in forbidden:
            self.assertNotIn(w, result,
                             f'ALERT 不该教具体措辞 (准则 6), 发现: {w}')


class TestTraceReplyWritesAudit(unittest.TestCase):
    """End-to-end: trace_reply 在 unverified 时调 write_audit_entry."""

    def setUp(self):
        self.path = _new_tmp_jsonl()
        # patch 默认 audit path 到临时
        import jarvis_claim_tracer as ct
        self._orig_path = ct._INTEGRITY_AUDIT_PATH
        ct._INTEGRITY_AUDIT_PATH = self.path

    def tearDown(self):
        import jarvis_claim_tracer as ct
        ct._INTEGRITY_AUDIT_PATH = self._orig_path
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_past_action_no_tool_writes_audit(self):
        from jarvis_claim_tracer import trace_reply
        # 🆕 [Sir 2026-05-26 22:35 fix] include_swm_tool_called=False 防老 SWM events 干扰
        result = trace_reply(
            jarvis_reply='已经打开 dashboard 了, Sir.',
            tool_results=[],  # 无 ✅ → past_action unverified
            stm_recent=[],
            turn_id='turn_pe_001',
            include_swm_tool_called=False,
        )
        self.assertGreater(result['n_unverified'], 0)
        # audit jsonl 应有 entry
        with open(self.path, 'r', encoding='utf-8') as f:
            lines = [l for l in f.readlines() if l.strip()]
        self.assertGreaterEqual(len(lines), 1)
        e = json.loads(lines[0])
        self.assertEqual(e['turn_id'], 'turn_pe_001')
        self.assertEqual(e['kind'], 'past_action')
        self.assertFalse(e['found'])

    def test_past_action_with_tool_success_no_audit(self):
        from jarvis_claim_tracer import trace_reply
        result = trace_reply(
            jarvis_reply='已打开 dashboard.',
            tool_results=['✅ dashboard opened'],  # ✅ → verified
            stm_recent=[],
            turn_id='turn_pe_002',
        )
        # past_action 应 verified
        self.assertEqual(result['n_unverified'], 0)
        # audit 不应记录 (verified 不入表)
        with open(self.path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertEqual(content.strip(), '')


class TestAssemblePromptIntegration(unittest.TestCase):
    """_assemble_prompt 集成: prepend [INTEGRITY ALERT] 到 system_alert_text."""

    def test_build_integrity_alert_importable_from_central_nerve(self):
        """central_nerve import path 应该通 (lazy import)."""
        # 验证 import chain (build_integrity_alert 在 jarvis_claim_tracer)
        from jarvis_claim_tracer import build_integrity_alert
        self.assertTrue(callable(build_integrity_alert))

    def test_central_nerve_calls_build_integrity_alert(self):
        """grep 验证 _assemble_prompt 调 build_integrity_alert + prepend system_alert_text"""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'jarvis_central_nerve.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        # 必须 import + 调
        self.assertIn('build_integrity_alert', src,
                      '_assemble_prompt 必须 import build_integrity_alert')
        # 必须 prepend 到 system_alert_text
        self.assertIn('system_alert_text', src)
        # 必须在 try/except 里 (保主路径)
        # 简单 sanity: 调用前后 50 字内有 try:
        idx = src.find('build_integrity_alert(current_turn_id=')
        self.assertGreater(idx, 0)
        # 找前 200 字内 'try:'
        before = src[max(0, idx - 300):idx]
        self.assertIn('try:', before,
                      'build_integrity_alert 调用必须包 try/except 保主路径')

    def test_alert_prepend_does_not_break_when_no_audit(self):
        """mock 一个 stub assemble: 无 audit → system_alert_text 不变."""
        from jarvis_claim_tracer import build_integrity_alert
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl',
                                            delete=False) as f:
            tmpname = f.name
        try:
            # 空 jsonl
            result = build_integrity_alert(current_turn_id='turn_x',
                                             audit_path=tmpname)
            self.assertEqual(result, '')
            # mock system_alert_text concat
            original = 'OLD ALERT'
            prepended = (
                result + '\n\n' + original
                if result and original
                else (result or original)
            )
            self.assertEqual(prepended, original)
        finally:
            os.remove(tmpname)

    def test_alert_prepend_prepends_when_unverified_exists(self):
        """有 unverified → 拼到 system_alert_text 前."""
        from jarvis_claim_tracer import (build_integrity_alert,
                                            write_audit_entry)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl',
                                            delete=False) as f:
            tmpname = f.name
        try:
            write_audit_entry('turn_prior',
                              _FakeClaim('past_action', '已发了'),
                              found=False, audit_path=tmpname)
            alert = build_integrity_alert(current_turn_id='turn_curr',
                                            audit_path=tmpname)
            self.assertTrue(alert)
            original = 'OLD ALERT'
            prepended = (
                alert + '\n\n' + original if alert else original
            )
            self.assertTrue(prepended.startswith('[INTEGRITY ALERT]'))
            self.assertIn('OLD ALERT', prepended)
            # ALERT 在前, 老 text 在后
            self.assertLess(prepended.find('[INTEGRITY ALERT]'),
                              prepended.find('OLD ALERT'))
        finally:
            os.remove(tmpname)


class TestRedLines(unittest.TestCase):
    """准则红线: API 不破 / schema 稳定 / 准则 5/6/6.5 守护."""

    def test_claim_tracer_api_unchanged(self):
        """老 API (trace_reply / extract_claims / trace_to_evidence) 仍存在."""
        import jarvis_claim_tracer as ct
        for name in ('trace_reply', 'extract_claims', 'trace_to_evidence',
                     'update_stats', 'get_stats', 'Claim'):
            self.assertTrue(hasattr(ct, name),
                            f'公开 API {name} 必须保留 (老调用方不破)')

    def test_new_api_exists(self):
        """新 API (write_audit_entry / read_recent_unverified / build_integrity_alert)"""
        import jarvis_claim_tracer as ct
        for name in ('write_audit_entry', 'read_recent_unverified',
                     'build_integrity_alert', '_INTEGRITY_AUDIT_PATH'):
            self.assertTrue(hasattr(ct, name),
                            f'新 API/常量 {name} 必须存在')

    def test_audit_jsonl_path_under_memory_pool(self):
        """准则 6.5: vocab/audit 都在 memory_pool/, 不散在 py 里"""
        import jarvis_claim_tracer as ct
        self.assertIn('memory_pool', ct._INTEGRITY_AUDIT_PATH)
        self.assertTrue(ct._INTEGRITY_AUDIT_PATH.endswith('.jsonl'))

    def test_gitignore_covers_integrity_audit(self):
        """memory_pool/*.jsonl 已在 .gitignore (防 audit 进 git)"""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            '.gitignore')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('memory_pool/*.jsonl', content,
                      '.gitignore 必须 cover memory_pool/*.jsonl')


if __name__ == '__main__':
    unittest.main(verbosity=2)
