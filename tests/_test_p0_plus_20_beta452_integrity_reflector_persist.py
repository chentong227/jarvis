# -*- coding: utf-8 -*-
"""
[P0+20-β.4.5.2 / 2026-05-18] INTEGRITY_STACK Session 4 sub-step 2:
IntegrityReflector L7 LLM-propose daemon — 7d audit 反思 → propose 进 review queue.

设计契约 (准则 7 Sir 元否决):
  - propose 只入 review state, 不自动 active
  - Sir 用 CLI --activate/--reject 仲裁
  - prompt 只约束 schema, 不教具体措辞 (准则 6 反硬编码)
  - 全持久化 + dedup + fail-safe (准则 6.5)

测试覆盖 (6 TestClass):
  1. TestReflectorInit — 初始化 / 默认配置 / 单例 factory
  2. TestShouldReflectNow — 触发条件: time-based 兜底 / audit-based + idle
  3. TestReflectIntegrityAudit — _reflect_once 主流程 (LLM mock)
  4. TestProposeWriters — 3 类 propose 写入 review queue (schema 正确 + dedup)
  5. TestFailSafe — LLM 失败 / 损坏 jsonl / 路径不可写 全 fail-safe
  6. TestRedLines — 准则 6 / 6.5 / 7 强制 + central_nerve 注册检查
"""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import jarvis_integrity_reflector as ir  # noqa: E402


def _write_jsonl(path: str, records: list) -> None:
    """helper: 写测试 jsonl audit."""
    with open(path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def _make_audit_record(turn_id: str = 'turn_test',
                        kind: str = 'past_action',
                        claim: str = 'I checked it',
                        ts: float = None) -> dict:
    return {
        'turn_id': turn_id,
        'ts': ts or time.time(),
        'kind': kind,
        'claim': claim,
        'verified': False,
    }


class _BaseFixture(unittest.TestCase):
    """共享 fixture: 临时目录 + 3 个 review path 注入."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.audit_path = os.path.join(self.tmpdir, 'integrity_audit.jsonl')
        self.classify_path = os.path.join(self.tmpdir, 'claim_classify_vocab.json')
        self.evreq_path = os.path.join(self.tmpdir, 'evidence_requirements.json')
        self.directive_path = os.path.join(self.tmpdir, 'directive_review.json')
        # 重置单例 (上一个 test 可能留 _DEFAULT_INTEGRITY_REFLECTOR)
        ir._DEFAULT_INTEGRITY_REFLECTOR = None

    def tearDown(self):
        ir._DEFAULT_INTEGRITY_REFLECTOR = None
        for p in (self.audit_path, self.classify_path, self.evreq_path,
                   self.directive_path):
            if os.path.exists(p):
                os.unlink(p)
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def _reflector(self, key_router=None, config: dict = None):
        return ir.IntegrityReflector(
            key_router=key_router,
            audit_path=self.audit_path,
            classify_vocab_path=self.classify_path,
            evreq_vocab_path=self.evreq_path,
            directive_review_path=self.directive_path,
            config=config or {},
        )


# ---------------------------------------------------------------
# 1. TestReflectorInit
# ---------------------------------------------------------------

class TestReflectorInit(_BaseFixture):

    def test_init_defaults(self):
        r = self._reflector()
        self.assertEqual(r.name, 'IntegrityReflector')
        self.assertTrue(r.daemon)
        self.assertEqual(r.audit_path, self.audit_path)
        self.assertIn('min_audit_for_trigger', r.config)
        self.assertEqual(r.config['min_audit_for_trigger'], 50)

    def test_init_config_override(self):
        r = self._reflector(config={'min_audit_for_trigger': 10,
                                       'window_days': 3})
        self.assertEqual(r.config['min_audit_for_trigger'], 10)
        self.assertEqual(r.config['window_days'], 3)
        # 其他默认仍在
        self.assertEqual(r.config['max_propose_per_run'], 5)

    def test_singleton_factory(self):
        r1 = ir.get_default_integrity_reflector()
        r2 = ir.get_default_integrity_reflector()
        self.assertIs(r1, r2)


# ---------------------------------------------------------------
# 2. TestShouldReflectNow
# ---------------------------------------------------------------

class TestShouldReflectNow(_BaseFixture):

    def test_trigger_time_based_when_never_run(self):
        # _last_run_ts=0 → elapsed > min_interval_s → 触发
        r = self._reflector()
        # 但 audit < min_audit_for_trigger, 怎么也走不到 audit-based
        # 不过 time-based 已经先 return True (_last_run_ts=0 → elapsed=now)
        self.assertTrue(r._should_reflect_now())

    def test_no_trigger_time_recent_run(self):
        r = self._reflector(config={'min_audit_for_trigger': 1000})
        r._last_run_ts = time.time() - 60  # 60s ago, 远小于 3d 兜底
        # audit 文件也不存在 → 0 条
        self.assertFalse(r._should_reflect_now())

    def test_trigger_audit_based(self):
        # audit jsonl 有 ≥ min_audit_for_trigger 条 + idle 模拟过关
        records = [_make_audit_record(claim=f'claim {i}') for i in range(10)]
        _write_jsonl(self.audit_path, records)

        r = self._reflector(config={
            'min_audit_for_trigger': 5,
            'min_idle_hours_for_trigger': 0.0,  # 不要求 idle
        })
        r._last_run_ts = time.time() - 60  # 不靠 time-based 兜底
        with patch.object(r, '_sir_idle_hours', return_value=10.0):
            self.assertTrue(r._should_reflect_now())

    def test_no_trigger_audit_below_threshold(self):
        records = [_make_audit_record(claim=f'c{i}') for i in range(3)]
        _write_jsonl(self.audit_path, records)

        r = self._reflector(config={
            'min_audit_for_trigger': 50,
        })
        r._last_run_ts = time.time() - 60
        self.assertFalse(r._should_reflect_now())


# ---------------------------------------------------------------
# 3. TestReflectIntegrityAudit (LLM mock)
# ---------------------------------------------------------------

class TestReflectIntegrityAudit(_BaseFixture):

    def test_reflect_empty_audit_returns_no_proposals(self):
        r = self._reflector()
        result = r._reflect_once(force=True)
        self.assertEqual(result['proposed_n'], 0)
        self.assertIn('audit empty', result['reason'])

    def test_reflect_audit_below_min_returns_skip(self):
        # 非 force 时, < min_audit_for_trigger 应 skip
        records = [_make_audit_record(claim=f'c{i}') for i in range(5)]
        _write_jsonl(self.audit_path, records)
        r = self._reflector(config={'min_audit_for_trigger': 50})
        result = r._reflect_once(force=False)
        self.assertEqual(result['proposed_n'], 0)
        self.assertIn('audit only 5', result['reason'])

    def test_reflect_with_llm_mock_propose_classify(self):
        records = [_make_audit_record(claim=f'I shall do {i}', kind='future_intent')
                    for i in range(10)]
        _write_jsonl(self.audit_path, records)
        r = self._reflector(config={'min_audit_for_trigger': 5})

        mock_response = json.dumps({
            'claim_classify_proposals': [{
                'id': 'mock_future_kw',
                'claim_type': 'Future',
                'keywords': ['I shall', "I'll go"],
                'rationale': 'Future tense missed by current vocab',
            }],
            'evidence_req_proposals': [],
            'directive_proposals': [],
        })
        with patch.object(r, '_call_llm', return_value=mock_response):
            result = r._reflect_once(force=True)

        self.assertGreaterEqual(result['proposed_n'], 1)
        # 验证 classify_vocab 真写入
        with open(self.classify_path, 'r', encoding='utf-8') as f:
            vocab = json.load(f)
        ids = [p.get('id') for p in vocab.get('patterns', [])]
        self.assertIn('mock_future_kw', ids)
        # 验证 state=review
        added = [p for p in vocab['patterns'] if p['id'] == 'mock_future_kw'][0]
        self.assertEqual(added['state'], 'review')
        self.assertEqual(added['source'], 'integrity_reflector')

    def test_reflect_llm_returns_invalid_json(self):
        records = [_make_audit_record(claim=f'c{i}') for i in range(5)]
        _write_jsonl(self.audit_path, records)
        r = self._reflector(config={'min_audit_for_trigger': 5})
        with patch.object(r, '_call_llm', return_value='not json at all'):
            result = r._reflect_once(force=True)
        self.assertEqual(result['proposed_n'], 0)
        self.assertIn('no JSON', result['reason'])

    def test_reflect_llm_returns_empty(self):
        records = [_make_audit_record(claim=f'c{i}') for i in range(5)]
        _write_jsonl(self.audit_path, records)
        r = self._reflector(config={'min_audit_for_trigger': 5})
        with patch.object(r, '_call_llm', return_value=''):
            result = r._reflect_once(force=True)
        self.assertEqual(result['proposed_n'], 0)


# ---------------------------------------------------------------
# 4. TestProposeWriters (直接调 _propose_*, 不走 LLM)
# ---------------------------------------------------------------

class TestProposeWriters(_BaseFixture):

    def test_propose_classify_writes_review_state(self):
        r = self._reflector()
        ok = r._propose_claim_classify({
            'id': 'kw_test_a',
            'claim_type': 'Past',
            'keywords': ['I emailed', 'I dispatched'],
            'rationale': 'past actions missed',
        })
        self.assertTrue(ok)
        with open(self.classify_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        added = next(p for p in data['patterns'] if p['id'] == 'kw_test_a')
        self.assertEqual(added['state'], 'review')
        self.assertEqual(added['claim_type'], 'Past')
        self.assertEqual(set(added['keywords']), {'i emailed', 'i dispatched'})

    def test_propose_classify_dedup_same_id(self):
        r = self._reflector()
        ok1 = r._propose_claim_classify({
            'id': 'kw_dup', 'claim_type': 'Past', 'keywords': ['x']
        })
        ok2 = r._propose_claim_classify({
            'id': 'kw_dup', 'claim_type': 'Past', 'keywords': ['y']
        })
        self.assertTrue(ok1)
        self.assertFalse(ok2, '同 id 应 dedup skip')

    def test_propose_classify_invalid_claim_type(self):
        r = self._reflector()
        ok = r._propose_claim_classify({
            'id': 'kw_bad',
            'claim_type': 'BogusType',
            'keywords': ['x'],
        })
        self.assertFalse(ok)

    def test_propose_evreq_writes_review_state(self):
        r = self._reflector()
        ok = r._propose_evidence_req({
            'claim_type': 'Past',
            'evidence_kind': 'ltm_match',
            'rationale': 'past should also accept LTM',
        })
        self.assertTrue(ok)
        with open(self.evreq_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        added = next(p for p in data['patterns']
                      if p.get('source') == 'integrity_reflector')
        self.assertEqual(added['state'], 'review')
        self.assertEqual(added['claim_type'], 'Past')
        self.assertEqual(added['accepted_evidence_kinds'], ['ltm_match'])

    def test_propose_evreq_invalid_kind(self):
        r = self._reflector()
        ok = r._propose_evidence_req({
            'claim_type': 'Past', 'evidence_kind': 'bogus_kind'
        })
        self.assertFalse(ok)

    def test_propose_directive_writes_review_state(self):
        r = self._reflector()
        ok = r._propose_directive({
            'id': 'dir_verify_first',
            'trigger_pattern': r'I checked',
            'rule_summary': 'verify before claiming I checked X',
            'rationale': 'frequent unverified pattern',
        })
        self.assertTrue(ok)
        with open(self.directive_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        added = next(d for d in data if d.get('id') == 'dir_verify_first')
        self.assertEqual(added['state'], 'review')
        self.assertEqual(added['source'], 'integrity_reflector')

    def test_propose_directive_dedup(self):
        r = self._reflector()
        e = {'id': 'dir_d', 'trigger_pattern': 'X', 'rule_summary': 'do Y'}
        ok1 = r._propose_directive(e)
        ok2 = r._propose_directive(e)
        self.assertTrue(ok1)
        self.assertFalse(ok2)


# ---------------------------------------------------------------
# 5. TestFailSafe
# ---------------------------------------------------------------

class TestFailSafe(_BaseFixture):

    def test_corrupt_audit_jsonl_does_not_crash(self):
        # 写损坏 jsonl (一些行非 json)
        with open(self.audit_path, 'w', encoding='utf-8') as f:
            f.write('{"valid": 1}\n')
            f.write('this is not json\n')
            f.write('{"ts": 1234, "claim": "ok"}\n')
            f.write('\n')
        r = self._reflector()
        recs = r._gather_audit_window()
        # 只剩 2 条 valid (虽然第 1 条 ts=0 < cutoff, 实际过滤掉)
        # 关键是不 raise
        self.assertIsInstance(recs, list)

    def test_no_audit_file_returns_empty(self):
        # 文件根本不存在
        r = self._reflector()
        recs = r._gather_audit_window()
        self.assertEqual(recs, [])
        n = r._count_recent_audit()
        self.assertEqual(n, 0)

    def test_call_llm_no_key_router_returns_empty(self):
        r = self._reflector(key_router=None)
        text = r._call_llm('any prompt')
        self.assertEqual(text, '')
        self.assertIn('no key_router', r._stats['last_error'])

    def test_call_llm_key_router_raises(self):
        kr = MagicMock()
        kr.get_openrouter_key.side_effect = RuntimeError('no key available')
        r = self._reflector(key_router=kr)
        text = r._call_llm('prompt')
        self.assertEqual(text, '')
        self.assertIn('key_router', r._stats['last_error'])

    def test_propose_classify_corrupt_vocab_recovers(self):
        # vocab 文件损坏 (非 json)
        with open(self.classify_path, 'w', encoding='utf-8') as f:
            f.write('not json at all')
        r = self._reflector()
        # _load_vocab_atomic fail-safe 返 {'patterns': []}, propose 仍能加
        ok = r._propose_claim_classify({
            'id': 'recover_kw',
            'claim_type': 'Future',
            'keywords': ['will'],
        })
        self.assertTrue(ok)


# ---------------------------------------------------------------
# 6. TestRedLines (准则 6/6.5/7 + central_nerve)
# ---------------------------------------------------------------

class TestRedLines(_BaseFixture):

    def test_propose_state_is_always_review(self):
        # 准则 7 Sir 元否决: propose 必须 state=review
        r = self._reflector()
        r._propose_claim_classify({
            'id': 'rl_kw', 'claim_type': 'Tool', 'keywords': ['x']
        })
        with open(self.classify_path, 'r', encoding='utf-8') as f:
            v = json.load(f)
        self.assertTrue(all(p['state'] == 'review'
                              for p in v['patterns']
                              if p.get('source') == 'integrity_reflector'),
                          'integrity_reflector source 全须 state=review')

    def test_canonical_evidence_kinds_only(self):
        # 准则 6.5: evidence_kind 必须在 canonical 列表内
        r = self._reflector()
        # invalid kind 拒绝
        self.assertFalse(r._propose_evidence_req({
            'claim_type': 'Past', 'evidence_kind': 'random_kind'
        }))
        # canonical 接受
        self.assertTrue(r._propose_evidence_req({
            'claim_type': 'Past', 'evidence_kind': 'tool_results_any'
        }))

    def test_canonical_claim_types_only(self):
        # 准则 6.5: claim_type 必须 6 类之一
        r = self._reflector()
        for valid in ('Past', 'Future', 'State', 'Recall', 'Social', 'Tool'):
            ok = r._propose_claim_classify({
                'id': f'rl_{valid.lower()}_v',
                'claim_type': valid,
                'keywords': ['x'],
            })
            self.assertTrue(ok, f'{valid} 应被接受')
        # invalid
        self.assertFalse(r._propose_claim_classify({
            'id': 'rl_bad', 'claim_type': 'NotAType',
            'keywords': ['x'],
        }))

    def test_central_nerve_imports_reflector(self):
        # central_nerve 注册检查
        cn_path = os.path.join(ROOT, 'jarvis_central_nerve.py')
        with open(cn_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn(
            'from jarvis_integrity_reflector import get_default_integrity_reflector',
            src,
            'central_nerve must import get_default_integrity_reflector')
        self.assertIn('IntegrityReflector', src)

    def test_thread_uses_stop_event_not_stop(self):
        # β.4.5.1 教训: 不能用 self._stop (与 Python 3.9 Thread._stop 冲突)
        r = self._reflector()
        self.assertTrue(hasattr(r, '_stop_event'))
        # _stop 仍 callable (基类 method, 不是 Event)
        self.assertTrue(callable(r._stop))

    def test_prompt_does_not_prescribe_chinese_phrasing(self):
        # 准则 6: prompt 不能教具体中文措辞 (例如直接给"已经/完成了"这类词)
        # 验证 prompt 本身不含具体中文词汇预设 (除了"反硬编码"自指 + 章节标签)
        prompt = ir.INTEGRITY_REFLECTOR_PROMPT
        # prompt 应只含 schema 定义的英文 + 占位符, 不应预设具体 keyword 列表
        self.assertNotIn('已经', prompt, 'prompt 不应预设"已经"等具体措辞')
        self.assertNotIn('完成了', prompt, 'prompt 不应预设"完成了"等具体措辞')


if __name__ == '__main__':
    unittest.main(verbosity=2)
