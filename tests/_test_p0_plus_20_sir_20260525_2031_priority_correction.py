# -*- coding: utf-8 -*-
"""[Sir 2026-05-25 20:31 真测追根 准则 6 学习机制] 4 路 regression test.

Sir 真理 (jarvis_20260525_200517.log Turn 3/4):
  '你忘记我们现在最重要的任务是什么了' / '其实是面试是我准备面试'.
  主脑 emit mutation.update profile.current_priority 但白名单不允许 → audit only.
  ConcernFeedback LLM 没识别这是 priority correction → sir_interview_prep_balance
  severity 没升, SOUL inject 仍排 keyrouter/水/番茄钟.

Sir 真理 = '我说一次, 你应该学会, 权重应该被我回应动态变化'. 准则 6 evidence-driven.

4 路治本:
  - v1: ZH 截断检测增强 (chat_bypass): ZH 末尾不完整 / ZH << EN 也算 truncate
  - v2: ConcernFeedback prompt 加 PRIORITY CORRECTION 判定规则 + vocab 注入
  - v3: priority_correction_vocab.json 持久化 (准则 6.5) + Sir CLI dump 脚本
  - v4: current_priority 加入 ProfileCard 白名单 (主脑 mutate 真持久化)
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(name: str) -> str:
    with open(os.path.join(ROOT, name), 'r', encoding='utf-8') as f:
        return f.read()


# ==========================================================================
# v1: ZH 截断检测增强 (chat_bypass)
# ==========================================================================
class TestV1ZHTruncateDetectionEnhanced(unittest.TestCase):

    def test_chat_bypass_checks_zh_endings(self):
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('_zh_endings', src,
                       '必须有 ZH 末尾标点 set 检测')
        self.assertIn('_zh_truncated', src,
                       '必须有 _zh_truncated flag')

    def test_chat_bypass_checks_zh_too_short_vs_en(self):
        src = _read('jarvis_chat_bypass.py')
        # 关键: ZH 长度 < EN × 0.4 也算 truncate
        idx = src.find('_zh_truncated')
        self.assertGreater(idx, 0)
        block = src[idx:idx + 1500]
        self.assertIn('len(_en_net) * 0.4', block,
                       'ZH 太短相对 EN 也算 truncate')

    def test_truncate_continuation_passes_zh_snippet(self):
        src = _read('jarvis_chat_bypass.py')
        # worker 接 zh_snippet 参数 (智能补)
        self.assertIn('def _truncate_continuation_worker(en_snippet: str, zh_snippet: str)', src,
                       'worker 必须接 en + zh 双参数')


# ==========================================================================
# v2: ConcernFeedback prompt 加 PRIORITY CORRECTION 判定
# ==========================================================================
class TestV2ConcernFeedbackPriorityCorrection(unittest.TestCase):

    def test_prompt_contains_priority_correction_block(self):
        src = _read('jarvis_concern_feedback.py')
        self.assertIn('PRIORITY CORRECTION', src,
                       'prompt 必须含 PRIORITY CORRECTION 判定段')
        self.assertIn('我说一次, 你应该学会', src,
                       'prompt 必须 anchor Sir 真理')

    def test_prompt_loads_vocab_dynamically(self):
        src = _read('jarvis_concern_feedback.py')
        self.assertIn('_load_priority_correction_vocab', src,
                       '必须有动态 vocab loader')
        self.assertIn('priority_correction_vocab.json', src,
                       'loader 必须读 JSON 持久化文件')

    def test_prompt_specifies_severity_delta_amounts(self):
        src = _read('jarvis_concern_feedback.py')
        # 强升 +0.6 + 降 -0.4
        idx = src.find('PRIORITY CORRECTION')
        self.assertGreater(idx, 0)
        block = src[idx:idx + 2000]
        self.assertIn('+0.6', block, '升权 amount')
        self.assertIn('-0.4', block, '降权 amount')

    def test_load_vocab_returns_phrases(self):
        """真 load vocab JSON 验证 active phrases 注入."""
        from jarvis_concern_feedback import ConcernFeedbackJudge
        # init 不需 ledger/key_router (我们只测 _load 静态方法)
        judge = ConcernFeedbackJudge.__new__(ConcernFeedbackJudge)
        block = judge._load_priority_correction_vocab()
        self.assertIsInstance(block, str)
        # vocab JSON 真存在 → block 非空 + 含 phrase
        if os.path.exists(os.path.join(ROOT, 'memory_pool',
                                          'priority_correction_vocab.json')):
            self.assertIn('最重要的是', block, 'ZH vocab 命中')


# ==========================================================================
# v3: priority_correction_vocab.json 持久化 + CLI 脚本
# ==========================================================================
class TestV3VocabPersistence(unittest.TestCase):

    def test_vocab_file_exists(self):
        path = os.path.join(ROOT, 'memory_pool', 'priority_correction_vocab.json')
        self.assertTrue(os.path.exists(path), 'vocab JSON 必须存在')

    def test_vocab_schema_valid(self):
        import json
        path = os.path.join(ROOT, 'memory_pool', 'priority_correction_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('_meta', data)
        self.assertIn('patterns', data)
        self.assertGreaterEqual(len(data['patterns']), 2,
                                  '至少 2 个 pattern (ZH + EN)')
        # 每个 pattern 必备字段
        for p in data['patterns']:
            self.assertIn('id', p)
            self.assertIn('phrases', p)
            self.assertIn('state', p)

    def test_vocab_contains_sir_real_phrases(self):
        """vocab 含 Sir 真用过的 phrase."""
        import json
        path = os.path.join(ROOT, 'memory_pool', 'priority_correction_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        all_phrases = []
        for p in data['patterns']:
            all_phrases.extend(p.get('phrases', []))
        # Sir 真说的 (Turn 3/4)
        self.assertTrue(
            any('最重要' in ph for ph in all_phrases),
            "vocab 必须含 '最重要' 类 phrase")
        self.assertTrue(
            any('其实是' in ph for ph in all_phrases),
            "vocab 必须含 '其实是' 类 phrase")
        self.assertTrue(
            any('你忘' in ph for ph in all_phrases),
            "vocab 必须含 '你忘' 类 phrase")

    def test_cli_dump_script_exists(self):
        path = os.path.join(ROOT, 'scripts', 'priority_correction_dump.py')
        self.assertTrue(os.path.exists(path),
                          'Sir CLI dump 脚本必须存在 (准则 6.5)')


# ==========================================================================
# v4: current_priority 加入 ProfileCard 白名单
# ==========================================================================
class TestV4ProfileCardCurrentPriorityAllowed(unittest.TestCase):

    def test_current_priority_in_overwrite_allowed(self):
        from jarvis_routing import ProfileCard
        self.assertIn('current_priority', ProfileCard._OVERWRITE_ALLOWED_FIELDS,
                       'current_priority 必须在白名单 (Sir 主脑 mutate 才真改)')

    def test_overwrite_field_accepts_current_priority(self):
        """真调 overwrite_field 验证不报 'not in allowed list'."""
        import tempfile, json as _json, shutil
        from unittest.mock import MagicMock
        from jarvis_routing import ProfileCard
        # 临时 sir_profile.json
        tmp_dir = tempfile.mkdtemp()
        cfg_dir = os.path.join(tmp_dir, 'jarvis_config')
        os.makedirs(cfg_dir, exist_ok=True)
        profile_path = os.path.join(cfg_dir, 'sir_profile.json')
        with open(profile_path, 'w', encoding='utf-8') as f:
            _json.dump({'professional_role': 'engineer'}, f)
        # change cwd
        old_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            pc = ProfileCard(central_nerve=MagicMock())
            ok, msg, old = pc.overwrite_field(
                field='current_priority',
                new_value='Interview prep',
                source='fast_call_mutation',
                turn_id='test_turn',
                reason='Sir said 其实是面试',
            )
            self.assertTrue(ok,
                f'current_priority overwrite_field 应成功, msg={msg}')
            # 验证 sir_profile.json 真改
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile = _json.load(f)
            self.assertEqual(profile.get('current_priority'), 'Interview prep')
        finally:
            os.chdir(old_cwd)
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
