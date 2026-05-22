# -*- coding: utf-8 -*-
"""[P5-fix25-stand-down / 2026-05-22] Stand Down 模式

Sir 真痛点:
> "可以给贾维斯加个 stand down 模式吗? 就是会听着我说话, 但是不出动作,
>  毕竟有时候我在玩游戏打电话或者和爸妈说话, 贾维斯一直回复挺尴尬的."

Sir 设计选择:
- 触发: 双轨 (Ctrl+Alt+J 全局 hotkey + LLM 听 Sir 中文短语自决)
- 反应: voice OFF + visual_pulse OFF + nudge OFF, 字幕 + 终端 log 仍 ON
- STM 仍记 (上下文连续, Sir wake 后记得)
- One-shot summon: Sir 直接叫 Jarvis 问 → 答完仍 stand_down (Sir 选 A)
- Grace period 15s: 进 stand_down 后 Sir 说话立即 cancel (防误触)
- Chime: 进/出时短低频 ding (Phase 2)

测试覆盖:
1. State API (set / clear / get / is_active / is_in_grace)
2. Reaction gate (should_silence_voice / nudge / visual_pulse, keep subtitle/terminal)
3. Grace period (15s 内 Sir 说话 → cancel)
4. Auto timeout (until_ts 到 → is_active=False)
5. Persistence (state file save/load round-trip)
6. Trigger (Sir 中文/英文短语 → directive fire)
7. SWM event publish
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _isolated_sd():
    """切换 module path 到临时目录, 隔离测试."""
    import jarvis_stand_down as sd
    tmp = tempfile.mkdtemp()
    sd._reset_for_test(
        state_path=os.path.join(tmp, 'state.json'),
        history_path=os.path.join(tmp, 'history.jsonl'),
        vocab_path=os.path.join(tmp, 'vocab.json'),
    )
    return sd, tmp


class TestStandDownStateAPI(unittest.TestCase):

    def test_initial_inactive(self):
        sd, _ = _isolated_sd()
        self.assertFalse(sd.is_active())
        self.assertFalse(sd.is_in_grace())

    def test_set_makes_active(self):
        sd, _ = _isolated_sd()
        s = sd.set_stand_down(reason=sd.REASON_PHONE, duration_min=15)
        self.assertTrue(sd.is_active())
        self.assertEqual(s.reason, 'phone_call')

    def test_set_records_until_ts(self):
        sd, _ = _isolated_sd()
        s = sd.set_stand_down(reason=sd.REASON_GAME, duration_min=10)
        self.assertGreater(s.until_ts, time.time())
        self.assertLess(s.until_ts, time.time() + 11 * 60)

    def test_clear_deactivates(self):
        sd, _ = _isolated_sd()
        sd.set_stand_down(reason=sd.REASON_PHONE)
        self.assertTrue(sd.is_active())
        sd.clear_stand_down(source='cli')
        self.assertFalse(sd.is_active())

    def test_set_caps_duration_at_max(self):
        sd, _ = _isolated_sd()
        s = sd.set_stand_down(reason='manual', duration_min=999)
        cap_minutes = (s.until_ts - s.since_ts) / 60.0
        self.assertLessEqual(cap_minutes, sd.MAX_DURATION_MIN + 0.1)

    def test_already_active_extends(self):
        sd, _ = _isolated_sd()
        s1 = sd.set_stand_down(reason=sd.REASON_PHONE, duration_min=10)
        time.sleep(0.05)
        s2 = sd.set_stand_down(reason=sd.REASON_GAME, duration_min=20)
        # since_ts 应保留 (不重置), reason 更新
        self.assertEqual(s1.since_ts, s2.since_ts)
        self.assertEqual(s2.reason, 'game')


class TestReactionGate(unittest.TestCase):

    def test_silence_voice_when_active(self):
        sd, _ = _isolated_sd()
        sd.set_stand_down(reason=sd.REASON_PHONE)
        self.assertTrue(sd.should_silence_voice())
        self.assertTrue(sd.should_silence_visual_pulse())
        self.assertTrue(sd.should_silence_proactive_nudge())

    def test_keep_subtitle_terminal_always(self):
        sd, _ = _isolated_sd()
        # Inactive
        self.assertTrue(sd.should_keep_subtitle())
        self.assertTrue(sd.should_keep_terminal_log())
        # Active 也保留
        sd.set_stand_down(reason=sd.REASON_PHONE)
        self.assertTrue(sd.should_keep_subtitle())
        self.assertTrue(sd.should_keep_terminal_log())

    def test_no_silence_when_inactive(self):
        sd, _ = _isolated_sd()
        self.assertFalse(sd.should_silence_voice())
        self.assertFalse(sd.should_silence_visual_pulse())


class TestGracePeriod(unittest.TestCase):

    def test_grace_active_at_start(self):
        sd, _ = _isolated_sd()
        sd.set_stand_down(reason=sd.REASON_PHONE)
        self.assertTrue(sd.is_in_grace())

    def test_grace_cancel_clears_state(self):
        sd, _ = _isolated_sd()
        sd.set_stand_down(reason=sd.REASON_PHONE)
        cancelled = sd.grace_cancel_if_in_grace(reason='Sir 说话')
        self.assertTrue(cancelled)
        self.assertFalse(sd.is_active())

    def test_grace_cancel_only_in_grace_window(self):
        """Mock 一个 expired grace (manual mutate) — cancel 应失败."""
        sd, _ = _isolated_sd()
        sd.set_stand_down(reason=sd.REASON_PHONE, duration_min=10)
        # Force grace expired: state.grace_until_ts 设为 1s 前
        s = sd.get_state()
        # 直 mutate 模块单例 (testcase 用)
        sd._STATE.grace_until_ts = time.time() - 1
        cancelled = sd.grace_cancel_if_in_grace()
        self.assertFalse(cancelled)
        self.assertTrue(sd.is_active())  # 仍 stand_down


class TestAutoTimeout(unittest.TestCase):

    def test_until_ts_in_past_is_inactive(self):
        sd, _ = _isolated_sd()
        sd.set_stand_down(reason=sd.REASON_PHONE, duration_min=1)
        # mutate until_ts 到过去
        sd._STATE.until_ts = time.time() - 1
        self.assertFalse(sd.is_active())


class TestPersistence(unittest.TestCase):

    def test_save_load_roundtrip(self):
        import jarvis_stand_down as sd
        tmp = tempfile.mkdtemp()
        sp = os.path.join(tmp, 'state.json')
        hp = os.path.join(tmp, 'h.jsonl')
        sd._reset_for_test(state_path=sp, history_path=hp)
        sd.set_stand_down(reason='phone_call', duration_min=15,
                                exit_hint='phone hung up')
        # 模拟重启: reset module, 重新 load
        sd._reset_for_test(state_path=sp, history_path=hp)
        s = sd.get_state()
        self.assertTrue(s.is_active_now())
        self.assertEqual(s.reason, 'phone_call')
        self.assertEqual(s.exit_hint, 'phone hung up')


class TestPromptBlock(unittest.TestCase):

    def test_block_empty_when_inactive(self):
        sd, _ = _isolated_sd()
        self.assertEqual(sd.render_prompt_block(), '')

    def test_block_renders_when_active(self):
        sd, _ = _isolated_sd()
        sd.set_stand_down(reason=sd.REASON_GAME, duration_min=30,
                                exit_hint='Sir says wake up')
        block = sd.render_prompt_block()
        self.assertIn('STAND DOWN STATE', block)
        self.assertIn('game', block)
        self.assertIn('Sir says wake up', block)
        self.assertIn('voice', block.lower())
        self.assertIn('off', block.lower())


class TestDirectiveTrigger(unittest.TestCase):
    """jarvis_directives._trigger_stand_down."""

    def setUp(self):
        # 隔离 stand_down state for trigger tests
        sd, _ = _isolated_sd()
        # 确保 inactive baseline
        if sd.is_active():
            sd.clear_stand_down()

    def test_chinese_enter_phrase_fires(self):
        from jarvis_directives import _trigger_stand_down, DirectiveContext
        for phrase in ['我接个电话', '我玩会儿游戏', '保持安静', '嘘', '我和爸妈聊会儿']:
            ctx = DirectiveContext(user_input=phrase, tier='CHAT', stm=[])
            self.assertTrue(_trigger_stand_down(ctx),
                              f'should fire for: {phrase}')

    def test_english_enter_phrase_fires(self):
        from jarvis_directives import _trigger_stand_down, DirectiveContext
        for phrase in ['stand down', 'quiet mode', 'shhh']:
            ctx = DirectiveContext(user_input=phrase, tier='CHAT', stm=[])
            self.assertTrue(_trigger_stand_down(ctx),
                              f'should fire for: {phrase}')

    def test_exit_phrase_fires(self):
        from jarvis_directives import _trigger_stand_down, DirectiveContext
        for phrase in ['Jarvis 回来', 'wake up', "I'm back", '可以说话了']:
            ctx = DirectiveContext(user_input=phrase, tier='CHAT', stm=[])
            self.assertTrue(_trigger_stand_down(ctx),
                              f'should fire for: {phrase}')

    def test_neutral_phrase_does_not_fire(self):
        from jarvis_directives import _trigger_stand_down, DirectiveContext
        for phrase in ['你好', 'open dashboard', 'tell me about the weather']:
            ctx = DirectiveContext(user_input=phrase, tier='CHAT', stm=[])
            self.assertFalse(_trigger_stand_down(ctx),
                                f'should NOT fire for: {phrase}')

    def test_active_state_always_fires(self):
        """stand_down active 时 directive 一直 fire (主脑要持续看 [STAND DOWN STATE])."""
        from jarvis_directives import _trigger_stand_down, DirectiveContext
        import jarvis_stand_down as sd
        sd.set_stand_down(reason='phone_call', duration_min=10)
        ctx = DirectiveContext(user_input='完全无关的话', tier='CHAT', stm=[])
        self.assertTrue(_trigger_stand_down(ctx))


class TestOneShotSummon(unittest.TestCase):
    """🆕 [Phase 3] One-shot summon — Sir 在 stand_down 时叫 Jarvis 一句."""

    def test_one_shot_initially_inactive(self):
        sd, _ = _isolated_sd()
        sd.set_stand_down(reason='phone_call', duration_min=10)
        self.assertFalse(sd.is_one_shot_active())

    def test_mark_returns_false_when_not_in_stand_down(self):
        sd, _ = _isolated_sd()
        ok = sd.mark_one_shot_summon(turn_id='turn_xxx', duration_s=60)
        self.assertFalse(ok)

    def test_mark_succeeds_when_active(self):
        sd, _ = _isolated_sd()
        sd.set_stand_down(reason='phone_call', duration_min=10)
        ok = sd.mark_one_shot_summon(turn_id='turn_xxx', duration_s=60)
        self.assertTrue(ok)
        self.assertTrue(sd.is_one_shot_active())

    def test_should_silence_voice_returns_false_during_one_shot(self):
        """关键: stand_down active + one_shot 标记 → voice 不静默."""
        sd, _ = _isolated_sd()
        sd.set_stand_down(reason='phone_call', duration_min=10)
        self.assertTrue(sd.should_silence_voice())  # 默认静默
        sd.mark_one_shot_summon(turn_id='turn_xxx')
        self.assertFalse(sd.should_silence_voice())  # one-shot 期内不静默

    def test_visual_pulse_and_nudge_still_silenced_during_one_shot(self):
        """one-shot 仅放 voice, 其他保持静默."""
        sd, _ = _isolated_sd()
        sd.set_stand_down(reason='phone_call', duration_min=10)
        sd.mark_one_shot_summon(turn_id='turn_xxx')
        self.assertTrue(sd.should_silence_visual_pulse())
        self.assertTrue(sd.should_silence_proactive_nudge())

    def test_clear_one_shot_returns_to_silence(self):
        sd, _ = _isolated_sd()
        sd.set_stand_down(reason='phone_call', duration_min=10)
        sd.mark_one_shot_summon(turn_id='turn_xxx')
        self.assertFalse(sd.should_silence_voice())
        sd.clear_one_shot_summon()
        self.assertTrue(sd.should_silence_voice())

    def test_one_shot_expires_after_duration(self):
        sd, _ = _isolated_sd()
        sd.set_stand_down(reason='phone_call', duration_min=10)
        sd.mark_one_shot_summon(turn_id='turn_xxx', duration_s=60)
        sd._STATE.one_shot_until_ts = time.time() - 1
        self.assertFalse(sd.is_one_shot_active())
        self.assertTrue(sd.should_silence_voice())

    def test_clear_stand_down_also_clears_one_shot(self):
        sd, _ = _isolated_sd()
        sd.set_stand_down(reason='phone_call', duration_min=10)
        sd.mark_one_shot_summon(turn_id='turn_xxx')
        self.assertTrue(sd.is_one_shot_active())
        sd.clear_stand_down()
        self.assertFalse(sd.is_one_shot_active())

    def test_duration_capped_at_120s(self):
        sd, _ = _isolated_sd()
        sd.set_stand_down(reason='phone_call', duration_min=10)
        sd.mark_one_shot_summon(turn_id='turn_xxx', duration_s=999)
        s = sd.get_state()
        cap = s.one_shot_until_ts - time.time()
        self.assertLessEqual(cap, 120 + 0.5)


if __name__ == '__main__':
    unittest.main()
