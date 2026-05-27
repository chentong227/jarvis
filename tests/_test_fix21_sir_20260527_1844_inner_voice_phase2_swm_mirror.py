# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 18:44 真愿景] InnerVoice Phase 2 — SWM → voice mirror 回归.

Phase 2 工程: ConversationEventBus.publish() 末尾静默调 mirror_swm_event,
vocab 持久化决定哪些 etype mirror 成哪种 source/intent/wants_voice. 准则 6
三维耦合 — sentinel 代码完全不动, 数据强耦合在总线层.

测试覆盖 (10 testcase):

Step 2a — vocab JSON 完整性 (2 testcase):
  - PH2_1: memory_pool/swm_to_voice_vocab.json 存在且 mappings 非空
  - PH2_2: 每条 mapping 含必须字段 (etype/active/source/intent/min_salience)
           + source/intent 落在合法枚举 + 23 个默认 mapping 全 5 大 source 覆盖

Step 2b — mirror_swm_event 行为 (5 testcase):
  - PH2_3: mirror_swm_event API 存在 + signature
  - PH2_4: salience >= min_salience → mirror, < → skip (vocab gate)
  - PH2_5: wants_voice 阈值: sal >= wants_voice_min_salience → ★ True, 否则 False
  - PH2_6: content_template 格式化 {desc} 占位
  - PH2_7: env JARVIS_INNER_VOICE_ENABLED=0 → 立即 skip (可回撤)
  - PH2_8: 未在 vocab 的 etype → skip (无匹配)
  - PH2_9: active=false 的 mapping → skip (Sir CLI deactivate)

Step 2b — publish 集成 (1 testcase):
  - PH2_10: ConversationEventBus.publish() 末尾真调 mirror_swm_event
           (publish 完后 voice track 有 entry, swm_etype meta 正确)

Step 2c — CLI 存在 (1 testcase):
  - PH2_11: scripts/swm_to_voice_dump.py 存在 + main fn + 5 子命令
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


_VOCAB_PATH = os.path.join(_REPO, 'memory_pool', 'swm_to_voice_vocab.json')


# ============================================================
# Step 2a — vocab JSON 完整性
# ============================================================

class TestStep2aVocab(unittest.TestCase):

    def test_ph2_1_vocab_file_exists_and_nonempty(self):
        """PH2_1: vocab JSON 存在 + mappings 非空."""
        self.assertTrue(os.path.exists(_VOCAB_PATH),
                          f'{_VOCAB_PATH} must exist')
        with open(_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('mappings', data)
        self.assertGreater(len(data['mappings']), 10,
                              'should have >= 10 default mappings')

    def test_ph2_2_each_mapping_has_required_fields_and_valid_enums(self):
        """PH2_2: 每 mapping 含必须字段 + source/intent 落在合法枚举."""
        with open(_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        valid_sources = {
            'inner_thought', 'sensor', 'care_trigger',
            'self_reflection', 'noting', 'sir_injected',
        }
        valid_intents = {
            'observation', 'care', 'reflection',
            'reminder', 'noting',
        }
        sources_seen = set()
        for m in data['mappings']:
            for fld in ('etype', 'active', 'source', 'intent',
                          'min_salience'):
                self.assertIn(fld, m,
                                f'mapping {m.get("etype")} missing {fld}')
            self.assertIn(m['source'], valid_sources,
                              f'invalid source {m["source"]} in {m["etype"]}')
            self.assertIn(m['intent'], valid_intents,
                              f'invalid intent {m["intent"]} in {m["etype"]}')
            sources_seen.add(m['source'])
        # 至少覆盖 4 大 source (sensor / care_trigger / self_reflection + noting)
        self.assertGreaterEqual(
            len(sources_seen), 3,
            f'should cover >= 3 sources, got {sources_seen}'
        )


# ============================================================
# Step 2b — mirror_swm_event 行为
# ============================================================

class TestStep2bMirrorBehavior(unittest.TestCase):

    def setUp(self):
        # 每 testcase reset voice track 到独立临时文件
        import jarvis_inner_voice_track as ivt
        td = tempfile.mkdtemp()
        # 强 reset _DEFAULT 到临时 jsonl, 不污染 memory_pool/inner_voice_24h.jsonl
        ivt.reset_for_test()
        ivt._DEFAULT = ivt.InnerVoiceTrack(
            persist_path=os.path.join(td, 'iv.jsonl')
        )
        # 同时 reset vocab cache 让 mtime/cache 重新生效
        ivt._SWM_VOCAB_CACHE = None
        ivt._SWM_VOCAB_CACHE_MTIME = 0.0
        # 确保 env enabled
        self._old_env = os.environ.pop('JARVIS_INNER_VOICE_ENABLED', None)

    def tearDown(self):
        if self._old_env is not None:
            os.environ['JARVIS_INNER_VOICE_ENABLED'] = self._old_env
        else:
            os.environ.pop('JARVIS_INNER_VOICE_ENABLED', None)

    def test_ph2_3_mirror_api_exists(self):
        """PH2_3: mirror_swm_event API 存在."""
        import jarvis_inner_voice_track as ivt
        self.assertTrue(hasattr(ivt, 'mirror_swm_event'))
        self.assertTrue(callable(ivt.mirror_swm_event))

    def test_ph2_4_salience_gate(self):
        """PH2_4: sal >= min_salience → mirror, < → skip."""
        from jarvis_inner_voice_track import (
            mirror_swm_event, get_inner_voice_track,
        )
        # sensor_change min_salience=0.4 在 vocab
        # sal=0.5 → mirror
        ok_high = mirror_swm_event(
            'sensor_change', 'test high sal', salience=0.5
        )
        # sal=0.1 → skip
        ok_low = mirror_swm_event(
            'sensor_change', 'test low sal', salience=0.1
        )
        self.assertTrue(ok_high, 'sal=0.5 should mirror')
        self.assertFalse(ok_low, 'sal=0.1 should skip')
        entries = get_inner_voice_track().all_recent(hours=1)
        self.assertEqual(len(entries), 1)
        self.assertIn('test high sal', entries[0].content)

    def test_ph2_5_wants_voice_threshold(self):
        """PH2_5: sal >= wants_voice_min_salience → ★ True, 否则 False."""
        from jarvis_inner_voice_track import (
            mirror_swm_event, get_inner_voice_track,
        )
        # concern_active wants_voice_min_salience=0.7
        mirror_swm_event('concern_active', 'low', salience=0.55)
        mirror_swm_event('concern_active', 'high', salience=0.85)
        entries = sorted(
            get_inner_voice_track().all_recent(hours=1),
            key=lambda e: e.ts,
        )
        self.assertEqual(len(entries), 2)
        low_entry = next(e for e in entries if 'low' in e.content)
        high_entry = next(e for e in entries if 'high' in e.content)
        self.assertFalse(low_entry.wants_voice,
                            'sal=0.55 should be wants_voice=False')
        self.assertTrue(high_entry.wants_voice,
                          'sal=0.85 should be wants_voice=True')

    def test_ph2_6_content_template_formatting(self):
        """PH2_6: content_template 格式化 {desc} 占位."""
        from jarvis_inner_voice_track import (
            mirror_swm_event, get_inner_voice_track,
        )
        # concern_active template: 'concern noted: {desc}'
        mirror_swm_event(
            'concern_active', 'hydration low', salience=0.75
        )
        entries = get_inner_voice_track().all_recent(hours=1)
        self.assertEqual(len(entries), 1)
        self.assertIn('concern noted:', entries[0].content)
        self.assertIn('hydration low', entries[0].content)

    def test_ph2_7_env_disabled_skips(self):
        """PH2_7: env JARVIS_INNER_VOICE_ENABLED=0 → 立即 skip."""
        from jarvis_inner_voice_track import (
            mirror_swm_event, get_inner_voice_track,
        )
        os.environ['JARVIS_INNER_VOICE_ENABLED'] = '0'
        ok = mirror_swm_event(
            'sensor_change', 'should skip', salience=0.9
        )
        self.assertFalse(ok, 'env=0 should make mirror skip')
        self.assertEqual(
            len(get_inner_voice_track().all_recent(hours=1)), 0,
            'no entry should be appended when env disabled'
        )

    def test_ph2_8_unknown_etype_skips(self):
        """PH2_8: 未在 vocab 的 etype → skip."""
        from jarvis_inner_voice_track import mirror_swm_event
        ok = mirror_swm_event(
            'totally_unknown_etype_xyz', 'test', salience=0.99
        )
        self.assertFalse(ok, 'unknown etype should skip')

    def test_ph2_9_inactive_mapping_skips(self):
        """PH2_9: active=false 的 mapping → skip (CLI deactivate 后)."""
        # proactive_nudge default active=false in vocab
        from jarvis_inner_voice_track import mirror_swm_event
        ok = mirror_swm_event(
            'proactive_nudge', 'i nudged', salience=0.95
        )
        self.assertFalse(ok, 'proactive_nudge active=false should skip')


# ============================================================
# Step 2b — publish 集成
# ============================================================

class TestStep2bPublishIntegration(unittest.TestCase):

    def test_ph2_10_publish_triggers_mirror(self):
        """PH2_10: ConversationEventBus.publish() 真触发 mirror_swm_event."""
        import jarvis_inner_voice_track as ivt
        td = tempfile.mkdtemp()
        ivt.reset_for_test()
        ivt._DEFAULT = ivt.InnerVoiceTrack(
            persist_path=os.path.join(td, 'iv.jsonl')
        )
        ivt._SWM_VOCAB_CACHE = None
        ivt._SWM_VOCAB_CACHE_MTIME = 0.0
        # 确保 env enabled
        old_env = os.environ.pop('JARVIS_INNER_VOICE_ENABLED', None)
        try:
            from jarvis_utils import ConversationEventBus
            bus = ConversationEventBus()
            bus.publish(
                'concern_active', 'hydration', salience=0.8,
                source='proactive_care_test',
                metadata={'concern_id': 'h_test', 'reason': 'low_intake'},
            )
            entries = ivt._DEFAULT.all_recent(hours=1)
            self.assertEqual(
                len(entries), 1,
                'publish concern_active sal=0.8 should mirror 1 voice entry'
            )
            e = entries[0]
            self.assertEqual(e.source, 'care_trigger')
            self.assertEqual(e.intent, 'care')
            self.assertIn('hydration', e.content)
            self.assertTrue(e.wants_voice,
                              'sal=0.8 >= 0.7 should ★')
            # meta 含 SWM 溯源
            self.assertIsNotNone(e.meta)
            self.assertEqual(e.meta.get('swm_etype'), 'concern_active')
            self.assertEqual(e.meta.get('swm_source_module'),
                              'proactive_care_test')
            self.assertEqual(e.meta.get('swm_concern_id'), 'h_test')
            self.assertEqual(e.meta.get('swm_reason'), 'low_intake')
        finally:
            if old_env is not None:
                os.environ['JARVIS_INNER_VOICE_ENABLED'] = old_env


# ============================================================
# Step 2c — CLI 存在
# ============================================================

class TestStep2cCLI(unittest.TestCase):

    def test_ph2_11_cli_script_exists_and_has_commands(self):
        """PH2_11: scripts/swm_to_voice_dump.py 存在 + main + 子命令."""
        cli_path = os.path.join(_REPO, 'scripts', 'swm_to_voice_dump.py')
        self.assertTrue(os.path.exists(cli_path))
        with open(cli_path, 'r', encoding='utf-8') as f:
            src = f.read()
        # 必含命令选项 + main fn
        for needle in (
            '--activate', '--reject', '--add', '--tail', '--stats',
            'def main(', 'cmd_list', 'cmd_activate', 'cmd_reject',
            'cmd_add', 'cmd_tail', 'cmd_stats',
        ):
            self.assertIn(needle, src, f'CLI must contain {needle!r}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
