# -*- coding: utf-8 -*-
"""[P5-fix54 / 2026-05-23 15:48] PromptBuilder Phase 1 + META evidence 标准化.

Sir 15:39 战略指示: '优先重构现有模块, 维护现有框架, 让贾维斯获得更多能力'.
Sir 15:43 META 配合: '充分发挥 META 思维链 + 把每个模块清晰结构化'.

Phase 1 设计:
- jarvis_prompt_builder.py: PromptBuilder + BlockSpec class (不破坏现有 _assemble_prompt 入口)
- meta_self_check_directive: evidence 命名标准化 (sensor:/swm:/stm:/soul:/l2:/profile:/...)
- jarvis_meta_self_check.py: audit jsonl 加 evidence_resolved (按 prefix 分组, debug 神器)

测试覆盖:
A. PromptBuilder register + render + tier filter
B. BlockSpec render + truncate
C. compose() 完整 prompt 含 persona/blocks/meta_hint/user_input
D. factory make_sensor_block_spec / make_swm_block_spec
E. META directive 含 evidence 命名标准 (sensor:/swm:/stm:/...)
F. trace_main_brain_meta 写 evidence_resolved 分组
G. PromptBuilder 不破坏 (单测, 不依赖 _assemble_prompt)
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


class TestPromptBuilder(unittest.TestCase):

    def test_a_register_render(self):
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        b = PromptBuilder(tier='CHAT')
        b.register(BlockSpec(id='a', content='alpha', tiers=['CHAT']))
        b.register(BlockSpec(id='b', content='beta', tiers=['CHAT']))
        out = b.render_blocks()
        self.assertIn('alpha', out)
        self.assertIn('beta', out)

    def test_a_tier_filter(self):
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        b = PromptBuilder(tier='SHORT_CHAT')
        b.register(BlockSpec(id='a', content='alpha', tiers=['SHORT_CHAT', 'CHAT']))
        b.register(BlockSpec(id='b', content='beta', tiers=['DEEP_QUERY']))
        out = b.render_blocks()
        self.assertIn('alpha', out)
        self.assertNotIn('beta', out, 'DEEP_QUERY-only block 不该出现在 SHORT_CHAT')

    def test_b_blockspec_render_truncate(self):
        from jarvis_prompt_builder import BlockSpec
        spec = BlockSpec(id='t', content='X' * 500, max_chars=100)
        rendered = spec.render()
        self.assertLessEqual(len(rendered), 110)
        self.assertIn('truncated', rendered)

    def test_b_blockspec_no_truncate_under_limit(self):
        from jarvis_prompt_builder import BlockSpec
        spec = BlockSpec(id='t', content='short', max_chars=100)
        rendered = spec.render()
        self.assertEqual(rendered, 'short')

    def test_c_compose_full_prompt(self):
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        b = PromptBuilder(tier='CHAT')
        b.register(BlockSpec(id='sensor', content='[SENSOR]: x=42',
                              tiers=['CHAT'], hint='sensor:<field>'))
        out = b.compose(persona='You are Jarvis.',
                          user_input='Hello?',
                          footer='[BILINGUAL]')
        self.assertIn('You are Jarvis.', out)
        self.assertIn('[SENSOR]: x=42', out)
        self.assertIn('User: Hello?', out)
        self.assertIn('[BILINGUAL]', out)
        # META cheat sheet should be included
        self.assertIn('META EVIDENCE CHEAT SHEET', out)
        self.assertIn('sensor:<field>', out)

    def test_c_compose_no_meta_hint(self):
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        b = PromptBuilder(tier='CHAT')
        b.register(BlockSpec(id='x', content='content', tiers=['CHAT']))
        out = b.compose(persona='p', user_input='u', include_meta_hint=False)
        self.assertNotIn('CHEAT SHEET', out)

    def test_c_list_block_ids(self):
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        b = PromptBuilder(tier='CHAT')
        b.register(BlockSpec(id='a', content='X', tiers=['CHAT']))
        b.register(BlockSpec(id='b', content='Y', tiers=['DEEP_QUERY']))
        ids = b.list_block_ids()
        self.assertEqual(ids, ['a'])

    def test_d_factory_sensor_block(self):
        from jarvis_prompt_builder import make_sensor_block_spec
        spec = make_sensor_block_spec(tier='CHAT', max_chars=600)
        # 取决于 vocab 是否存在, 但应不 raise
        if spec is not None:
            self.assertEqual(spec.id, 'sensor')
            self.assertIn('sensor:', spec.hint)
            self.assertIn('CHAT', spec.tiers)

    def test_d_factory_swm_block_no_bus(self):
        from jarvis_prompt_builder import make_swm_block_spec
        spec = make_swm_block_spec(event_bus=None)
        self.assertIsNone(spec)

    def test_d_factory_swm_block_with_bus(self):
        from jarvis_prompt_builder import make_swm_block_spec
        from jarvis_utils import ConversationEventBus
        bus = ConversationEventBus()
        bus.publish(etype='test_event', description='hello world',
                    source='test', salience=0.5)
        spec = make_swm_block_spec(event_bus=bus)
        if spec is not None:
            self.assertEqual(spec.id, 'swm')
            self.assertIn('swm:', spec.hint)


class TestMetaDirective(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(ROOT / 'jarvis_directives.py', encoding='utf-8') as f:
            cls.src = f.read()

    def test_e_evidence_naming_convention(self):
        """META directive 含 evidence 命名标准 (sensor/swm/stm/soul/l2/profile/...)."""
        idx = self.src.find("id='meta_self_check_directive'")
        self.assertGreater(idx, 0)
        body = self.src[idx:idx + 5000]
        # 8 个 prefix 都应在 directive 文档
        for prefix in ('sensor:', 'swm:', 'stm:', 'soul:', 'l2:',
                          'profile:', 'commitment:', 'ledger:'):
            self.assertIn(prefix, body,
                              f'META directive 应教 evidence prefix "{prefix}"')

    def test_e_examples_use_new_convention(self):
        """META directive examples 使用新 prefix."""
        idx = self.src.find("id='meta_self_check_directive'")
        body = self.src[idx:idx + 5000]
        self.assertIn('sensor:current_window_stay_s', body,
                          'examples 应展示 sensor: 用法 (Sir 15:27 痛点)')


class TestMetaAuditEvidenceResolved(unittest.TestCase):

    def test_f_evidence_resolved_grouped(self):
        """publish_meta 写 audit 时, evidence 按 prefix 分组."""
        from jarvis_meta_self_check import MetaSelfCheck, publish_meta as trace_main_brain_meta
        meta = MetaSelfCheck(
            evidence=['sensor:current_window_stay_s', 'swm:concern_active',
                        'stm:turn_test', 'sensor:work_session_total_min',
                        'no_prefix_evidence'],
            reaction='voice', skip_alert=False, parse_ok=True,
        )
        import tempfile
        with tempfile.NamedTemporaryFile(
                suffix='.jsonl', delete=False, mode='w', encoding='utf-8') as f:
            audit_path = f.name
        # 临时改 audit path
        import jarvis_meta_self_check as m
        old_path = m._AUDIT_PATH
        m._AUDIT_PATH = audit_path
        try:
            ok = trace_main_brain_meta(
                meta, turn_id='turn_test_f', user_input='hello')
            self.assertTrue(ok)
            # 读 audit
            import json
            with open(audit_path, encoding='utf-8') as f:
                line = f.readline().strip()
            payload = json.loads(line)
            self.assertIn('evidence_resolved', payload)
            er = payload['evidence_resolved']
            self.assertIn('sensor', er)
            self.assertEqual(set(er['sensor']),
                              {'current_window_stay_s', 'work_session_total_min'})
            self.assertEqual(er['swm'], ['concern_active'])
            self.assertEqual(er['stm'], ['turn_test'])
            # 无 prefix 的 evidence 不进 resolved
            self.assertNotIn('no_prefix_evidence', str(er))
        finally:
            m._AUDIT_PATH = old_path
            try:
                os.unlink(audit_path)
            except Exception:
                pass


if __name__ == '__main__':
    unittest.main()
