# -*- coding: utf-8 -*-
"""[P5-fix53 / 2026-05-23 15:30] sensor_state_block builder + 主对话 prompt 注入.

Sir 15:27 真痛点: 主脑被问 '我在 QQ 多久' hallucinate '19 minutes' (实际 work_duration).
Sir 15:29 深层痛点: '主脑必须知道我的一切信息才不 hallucinate'.
Sir 15:31 设计指示: '动态注入, 不是全量, 准则 6 持久化, 优雅高效可维护'.
Sir 15:34 真测复现 BUG: 主脑说 '面试文件 18 minutes' 实际 Sir 才打开.

设计 (准则 6 三维耦合):
  1. vocab JSON memory_pool/sensor_state_inject_vocab.json (13 字段 + tier filter)
  2. builder jarvis_sensor_state_block.build_sensor_state_block(tier, max_chars)
  3. CLI scripts/sensor_state_dump.py (--list / --activate / --reject / --preview)
  4. central_nerve.py _assemble_prompt 注入 6 个 template (紧跟 SYSTEM CLOCK 后)

测试覆盖:
A. vocab JSON 健康 (13 字段, 大部分 active)
B. build_sensor_state_block returns block 含 active fields
C. tier filter 工作 (SHORT_CHAT < CHAT < DEEP_QUERY 字段数递增)
D. inactive 字段不出现
E. max_chars 截断
F. central_nerve.py 6 个 prompt template 都注入 sensor_state_block
G. CLI list_active_fields 工作
H. 单字段 missing source 不 raise
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


class TestVocabHealth(unittest.TestCase):

    def test_a_vocab_exists_and_valid(self):
        path = ROOT / 'memory_pool' / 'sensor_state_inject_vocab.json'
        self.assertTrue(path.exists(), f'vocab not found: {path}')
        data = json.loads(path.read_text(encoding='utf-8'))
        self.assertIn('fields', data)
        self.assertGreaterEqual(len(data['fields']), 10,
                                  'should have >= 10 sensor fields')

    def test_a_required_core_fields(self):
        path = ROOT / 'memory_pool' / 'sensor_state_inject_vocab.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        ids = {f.get('id') for f in data.get('fields', [])}
        core = {'active_window', 'process', 'work_category',
                  'current_window_stay_s', 'work_session_total_min'}
        missing = core - ids
        self.assertEqual(missing, set(),
                          f'missing core fields: {missing}')


class TestBuilder(unittest.TestCase):

    def setUp(self):
        from jarvis_sensor_state_block import reload_vocab
        reload_vocab()

    def test_b_build_returns_block(self):
        from jarvis_sensor_state_block import build_sensor_state_block
        block = build_sensor_state_block(tier='CHAT', max_chars=1000)
        self.assertIn('SENSOR STATE', block)
        self.assertIn('active_window', block)
        self.assertIn('current_window_stay_s', block)
        self.assertIn('work_session_total_min', block)

    def test_c_tier_filter_short_chat(self):
        """SHORT_CHAT tier 只含核心字段 (4-6 个)."""
        from jarvis_sensor_state_block import list_active_fields
        short_fields = list_active_fields(tier='SHORT_CHAT')
        chat_fields = list_active_fields(tier='CHAT')
        deep_fields = list_active_fields(tier='DEEP_QUERY')
        self.assertGreater(len(short_fields), 0)
        self.assertGreater(len(chat_fields), len(short_fields),
                            'CHAT 应比 SHORT_CHAT 多字段')
        self.assertGreater(len(deep_fields), len(chat_fields),
                            'DEEP_QUERY 应比 CHAT 多字段')

    def test_c_short_chat_no_deep_fields(self):
        from jarvis_sensor_state_block import build_sensor_state_block
        block = build_sensor_state_block(tier='SHORT_CHAT', max_chars=1000)
        # DEEP_QUERY-only fields (switch_freq_5min / key_count_5min) 不该在 SHORT_CHAT
        self.assertNotIn('switch_freq_5min', block)
        self.assertNotIn('key_count_5min', block)
        # 但核心字段在
        self.assertIn('active_window', block)
        self.assertIn('current_window_stay_s', block)

    def test_d_inactive_field_not_in_block(self):
        """vocab 中 active=false 的 field 不出现在 block."""
        from jarvis_sensor_state_block import build_sensor_state_block
        # click_count_5min 在 vocab 是 active=false
        block = build_sensor_state_block(tier='DEEP_QUERY', max_chars=2000)
        # click_count_5min 不该出现 (vocab active=false)
        self.assertNotIn('click_count_5min', block,
                          'click_count_5min active=false 应被过滤')

    def test_e_max_chars_truncates(self):
        from jarvis_sensor_state_block import build_sensor_state_block
        block = build_sensor_state_block(tier='DEEP_QUERY', max_chars=200)
        self.assertLessEqual(len(block), 220)  # 允许 truncate marker
        if len(block) > 200:
            self.assertIn('truncated', block)


class TestCentralNervePromptInjection(unittest.TestCase):
    """central_nerve.py 6 个 prompt template 都注入 sensor_state_block."""

    @classmethod
    def setUpClass(cls):
        path = ROOT / 'jarvis_central_nerve.py'
        cls.src = path.read_text(encoding='utf-8')

    def test_f_sensor_state_block_defined(self):
        """sensor_state_block 变量在 _assemble_prompt 定义."""
        self.assertIn('sensor_state_block', self.src)
        self.assertIn('build_sensor_state_block', self.src)
        self.assertIn('jarvis_sensor_state_block', self.src)

    def test_f_six_prompt_templates_inject(self):
        """6 个 prompt template (含 SYSTEM CLOCK) 都注入 sensor_state_block."""
        # 简化测: 计 SYSTEM CLOCK 注入点 ≥ 6, sensor_state_block 注入点 ≥ 6
        n_clock = self.src.count('[SYSTEM CLOCK]: {current_time}')
        n_sensor = self.src.count('{sensor_state_block}')
        self.assertGreaterEqual(n_clock, 6,
                                  f'SYSTEM CLOCK 注入点应 >= 6, got {n_clock}')
        self.assertGreaterEqual(n_sensor, 6,
                                  f'sensor_state_block 注入点应 >= 6, got {n_sensor}')


class TestCLI(unittest.TestCase):

    def test_g_list_active_fields(self):
        from jarvis_sensor_state_block import list_active_fields
        for tier in ('SHORT_CHAT', 'CHAT', 'DEEP_QUERY'):
            fields = list_active_fields(tier=tier)
            self.assertIsInstance(fields, list)
            for fid in fields:
                self.assertIsInstance(fid, str)
                self.assertGreater(len(fid), 0)

    def test_h_missing_source_safe(self):
        """source attr 不存在不 raise."""
        from jarvis_sensor_state_block import _resolve_value
        # 不存在的 source → 返 None, 不 raise
        result = _resolve_value('NonExistentModule.nonexistent_attr')
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
