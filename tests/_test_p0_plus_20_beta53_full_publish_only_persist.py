# -*- coding: utf-8 -*-
"""
[P0+20-β.5.3 / 2026-05-19] 完全重构 push + SWM + 主脑 (Sir 拍板)

Sir 拍板第一性原理:
  "推进完全重构然后进行实际测试吧。毕竟目前有很多人机问题，我们把整体架构
   重构成 push+世界环境+主脑的架构对吧，先继续往下推进"

β.5.3 实施 (一次性完成所有, 让 Sir 真机测):
  A. vocab default: NudgeGate / OfferGuard hard → publish_only
  B. NudgeGate._can_speak_internal_v2 返 (result, block_reason, state_meta)
     state_meta 含 freeze_active / freeze_remaining_s / sleep_mode /
                   cooldown_remaining_s / last_nudge_age_s / last_nudge_center
     publish gate_advice 时 metadata 携带这些 state 给主脑看
  C. stream_nudge reaction_space prompt 强化:
     - 解释 publish_only 语义 (sentinel 不再 hard-block)
     - 列 7 类 priority-ordered silence triggers
     - bias-toward-silence: "When in doubt: prefer [SILENCE]"
  D. 老 _can_speak_internal 保留作向后兼容 wrapper

测试覆盖:
  1. vocab default publish_only 验
  2. _can_speak_internal_v2 三元组返回值 + state_meta 字段完整性
  3. publish_only 时 freeze + cooldown 不再 hard 拦
  4. SWM publish metadata 含 freeze_active / sleep_mode / cooldown_remaining_s
  5. reaction_space prompt 含 7 类 silence triggers + bias-toward-silence
  6. 向后兼容: _can_speak_internal (老 API) 仍返 bool
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================================
# A: vocab default publish_only
# ==========================================================================

class TestP0Plus20Beta53VocabDefaultPublishOnly(unittest.TestCase):
    def test_nudge_gate_default_publish_only(self):
        path = os.path.join(ROOT, 'memory_pool', 'gate_mode_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['current']['NudgeGate'], 'publish_only',
            'β.5.3: NudgeGate 默认 publish_only (Sir 拍板完全重构)')

    def test_offer_guard_default_publish_only(self):
        path = os.path.join(ROOT, 'memory_pool', 'gate_mode_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['current']['OfferGuard'], 'publish_only',
            'β.5.3: OfferGuard 默认 publish_only')

    def test_vocab_has_history_log(self):
        """vocab 含 history 记录切档变更 (含 β.5.3 节点)."""
        path = os.path.join(ROOT, 'memory_pool', 'gate_mode_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('history', data, 'vocab 应含 history 字段记录变更')
        history = data['history']
        self.assertGreater(len(history), 0)
        # β.5.3 节点应在任意 history 条目中 (β.5.5+ 会追加新条目)
        all_changes = ' | '.join(h.get('change', '') for h in history)
        self.assertIn('β.5.3', all_changes,
            'history 应至少有一条提及 β.5.3 节点')


# ==========================================================================
# B: _can_speak_internal_v2 返三元组 + state_meta 完整
# ==========================================================================

class TestP0Plus20Beta53InternalV2(unittest.TestCase):
    def setUp(self):
        from jarvis_sentinels import NudgeGate
        from jarvis_utils import reset_gate_mode_cache
        reset_gate_mode_cache()
        self.gate = NudgeGate(cooldown_seconds=60)

    def test_v2_returns_3_tuple(self):
        """_can_speak_internal_v2 必须返 (result, reason, state_meta)."""
        ret = self.gate._can_speak_internal_v2('test_center', False, '')
        self.assertEqual(len(ret), 3,
            '_can_speak_internal_v2 必须返 3 元组')
        result, reason, meta = ret
        self.assertIsInstance(result, bool)
        self.assertIsInstance(reason, str)
        self.assertIsInstance(meta, dict)

    def test_state_meta_has_required_fields(self):
        """state_meta 必须含核心 state 字段.
        [β.5.3-fix BUG-6] last_nudge_age_s 改 conditional (从未 nudge → 缺字段)."""
        _, _, meta = self.gate._can_speak_internal_v2('test_center', False, '')
        # 永远必填字段
        required = (
            'freeze_active', 'freeze_remaining_s',
            'sleep_mode', 'cooldown_remaining_s',
            'last_nudge_center',
        )
        for field in required:
            self.assertIn(field, meta,
                f'state_meta 必须含 {field} (β.5.3 给主脑看 state)')
        # 触发 nudge 后 last_nudge_age_s 应出现 (β.5.3-fix BUG-6)
        self.gate.mark_spoke('test_center')
        _, _, meta2 = self.gate._can_speak_internal_v2('other', False, '')
        self.assertIn('last_nudge_age_s', meta2,
            'state_meta after mark_spoke 必须含 last_nudge_age_s')

    def test_freeze_state_in_meta(self):
        """freeze 时 state_meta 应反映."""
        self.gate.freeze_for(60.0, source='test')
        _, reason, meta = self.gate._can_speak_internal_v2('test_center', False, '')
        self.assertTrue(meta['freeze_active'])
        self.assertGreater(meta['freeze_remaining_s'], 0)
        self.assertIn('hard_freeze', reason)

    def test_legacy_internal_still_returns_bool(self):
        """_can_speak_internal (老 API) 仍返 bool 兼容."""
        ret = self.gate._can_speak_internal('test_center', False, '')
        self.assertIsInstance(ret, bool, '_can_speak_internal 应返 bool (向后兼容)')


# ==========================================================================
# C: publish_only 时 freeze + cooldown 不再 hard 拦
# ==========================================================================

class TestP0Plus20Beta53PublishOnlyNoHardBlock(unittest.TestCase):
    def setUp(self):
        from jarvis_sentinels import NudgeGate
        from jarvis_utils import ConversationEventBus, reset_gate_mode_cache
        reset_gate_mode_cache()
        import jarvis_utils
        # mock publish_only mode
        jarvis_utils._GATE_MODE_CACHE = {'NudgeGate': 'publish_only'}
        jarvis_utils._GATE_MODE_CACHE_T = time.time()
        self.gate = NudgeGate(cooldown_seconds=60)
        self.bus = ConversationEventBus()
        ConversationEventBus.register_global(self.bus)

    def tearDown(self):
        from jarvis_utils import ConversationEventBus
        ConversationEventBus.register_global(None)

    def test_freeze_does_not_hard_block_in_publish_only(self):
        """β.5.18 升级: publish_only mode + freeze → 仍 hard 拦 (Sir 显式急停优先).

        🩹 [β.5.18 / 2026-05-19] 老 β.5.3 设计 "publish_only 永真包括 freeze"
        升级为 "publish_only 永真但 Sir 显式状态 (freeze/sleep) 例外". 因 freeze
        是 Sir 显式急停 / 拒绝 / 告别, 准则 5 言出必行 — 即便 publish_only 模式也
        不能让主脑 override. 主脑 SWM 仍能通过 gate_advice metadata 看 freeze_active
        状态 (test_freeze_published_to_swm_with_state_meta 验证 publish 仍发生).
        """
        self.gate.freeze_for(60.0, source='test_user_reject')
        result = self.gate.can_speak('guardian', is_urgent=False)
        self.assertFalse(result,
            'β.5.18: publish_only mode + freeze → 仍 hard 拦 (Sir 显式状态守)')

    def test_freeze_published_to_swm_with_state_meta(self):
        """publish_only mode + freeze → publish gate_advice 含 freeze_active=True."""
        self.gate.freeze_for(60.0, source='test_user_reject')
        self.gate.can_speak('guardian', is_urgent=False)
        snap = self.bus.snapshot()
        gate_events = [e for e in snap if e['type'] == 'gate_advice']
        self.assertGreater(len(gate_events), 0)
        latest = gate_events[-1]
        meta = latest['metadata']
        self.assertEqual(meta['decision'], 'block',
            'sentinel 仍建议 block (advisory), 但不 hard 拦')
        self.assertTrue(meta['freeze_active'])
        self.assertGreater(meta['freeze_remaining_s'], 0)
        self.assertEqual(meta['gate_mode'], 'publish_only')
        self.assertIn('hard_freeze', meta['block_reason'])

    def test_cooldown_state_in_meta(self):
        """cooldown 时 state_meta 含 cooldown_remaining_s."""
        # 触发 cooldown: 第 1 次 pass + mark, 第 2 次 (不同 center) 必 cooldown
        self.gate.can_speak('center_a', is_urgent=False)
        self.gate.mark_spoke('center_a')
        # 立刻第 2 次 different center → cooldown
        self.gate.can_speak('center_b', is_urgent=False)
        snap = self.bus.snapshot()
        gate_events = [e for e in snap if e['type'] == 'gate_advice']
        cooldown_events = [
            e for e in gate_events
            if e['metadata'].get('cooldown_remaining_s', 0) > 0
        ]
        self.assertGreater(len(cooldown_events), 0,
            'publish_only mode 下 cooldown 时 state_meta 应含 cooldown_remaining_s')


# ==========================================================================
# D: reaction_space prompt 强化
# ==========================================================================

class TestP0Plus20Beta53ReactionSpaceEnhanced(unittest.TestCase):
    def _get_src(self):
        path = os.path.join(ROOT, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_explains_publish_only_semantics(self):
        """reaction_space 必须教主脑读 sentinel directive + SWM evidence.
        [β.5.8-fix] β.5.3 旧 'publish_only sentinels' 说法被砍 (主脑不需知 vocab 模式),
        改成显式 evidence + sentinel directive 说法."""
        src = self._get_src()
        idx = src.find('[REACTION SPACE')
        block = src[idx:idx+5500]
        self.assertIn('directive', block,
            'reaction_space 必须解释 directive 概念')
        self.assertIn('sentinel', block,
            'reaction_space 应提及 sentinel')

    def test_lists_gate_advice_metadata_schema(self):
        """reaction_space 应列核心 gate_advice metadata 字段.
        [β.5.8-fix] 砍 block_reason (主脑不需细看), 只保 freeze_active/sleep_mode/cooldown_remaining_s 这三关键 state."""
        src = self._get_src()
        idx = src.find('[REACTION SPACE')
        block = src[idx:idx+5500]
        for field in ('decision', 'freeze_active',
                      'sleep_mode', 'cooldown_remaining_s'):
            self.assertIn(field, block,
                f'reaction_space 应列 {field} 字段说明')

    def test_has_priority_ordered_silence_triggers(self):
        """reaction_space 必须列 priority-ordered silence triggers.
        [β.5.8-fix] 改 7 → 4 trigger (narrow + explicit only)."""
        src = self._get_src()
        idx = src.find('[REACTION SPACE')
        block = src[idx:idx+5500]
        # β.5.8-fix: 至少 4 个 silence trigger
        for trigger_num in ('1.', '2.', '3.', '4.'):
            self.assertIn(trigger_num, block,
                f'reaction_space 应有 {trigger_num} silence trigger')

    def test_has_bias_toward_voice(self):
        """[β.5.8-fix] reaction_space 必须 bias-toward-voice (反 BUG-1 over-silence)."""
        src = self._get_src()
        idx = src.find('[REACTION SPACE')
        block = src[idx:idx+5500]
        # 新 bias: DEFAULT IS VOICE + SPEAK when in doubt
        self.assertIn('DEFAULT IS VOICE', block,
            'reaction_space 必须 DEFAULT IS VOICE (β.5.8-fix)')
        self.assertIn('When in doubt: SPEAK', block,
            'reaction_space 必须 "When in doubt: SPEAK" (β.5.8-fix)')


# ==========================================================================
# E: 端到端 — publish_only 时 NudgeGate + 主脑 [SILENCE] 协同
# ==========================================================================

class TestP0Plus20Beta53EndToEnd(unittest.TestCase):
    """验证 β.5.3 完整链路:
    NudgeGate publish_only → freeze publish 'gate_advice' → SWM evidence
    → 主脑 prompt 看到 (虽然 test 不能跑 LLM, 但能验 prompt 真含 evidence).
    """
    def test_swm_block_renders_gate_advice_block(self):
        """SWM to_swm_block 渲染 gate_advice 含 block decision 给主脑看."""
        from jarvis_utils import ConversationEventBus
        bus = ConversationEventBus()
        bus.publish(
            etype='gate_advice',
            description='NudgeGate would-block guardian/hydration: reason=hard_freeze_45s',
            source='NudgeGate',
            metadata={
                'decision': 'block',
                'block_reason': 'hard_freeze_45s',
                'freeze_active': True,
                'sleep_mode': False,
                'gate_mode': 'publish_only',
            },
            salience=0.75,
        )
        block = bus.to_swm_block(n=5)
        self.assertIn('gate_advice', block)
        self.assertIn('NudgeGate', block)
        self.assertIn('hard_freeze', block)


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print('='*60)
    if result.wasSuccessful():
        print('[OK] All β.5.3 full publish_only tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('='*60)
    sys.exit(0 if result.wasSuccessful() else 1)
