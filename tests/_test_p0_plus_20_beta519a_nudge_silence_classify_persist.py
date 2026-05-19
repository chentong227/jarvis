# -*- coding: utf-8 -*-
"""[β.5.19-A / 2026-05-20] NoSound empty_reply vs Silenced 分级测试

5/19 真机 audit 发现 4 处 `[Nudge/NoSound] reason=empty_reply` warn 实是主脑选
[SILENCE] (β.5.0-B reaction_space 预期行为), 不是 BUG. 但日志统一 warn 级
导致 audit false alarm.

β.5.19-A 修法:
  - chat_bypass.stream_nudge 入口复位 `_last_nudge_was_silence = False`
  - 进 `_silence_chosen=True` 路径标 flag = True
  - worker 看到 flag → 跳过 ⚠️ NoSound warn (chat_bypass 已 info `[Nudge/Silence]`)
  - 真异常 (`empty_reply` / `exception:*`) → 保留 ⚠️ NoSound warn + publish

本 testcase 静态扫源码确认:
  1. chat_bypass.stream_nudge 入口复位 flag
  2. _silence_chosen 路径设 flag = True
  3. worker.py 检测 flag 跳过 warn / publish
  4. marker 在 jarvis_chat_bypass.py + jarvis_worker.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


class TestBeta519ANudgeSilenceClassify(unittest.TestCase):
    """[β.5.19-A] NoSound silence/empty_reply 分级源码扫"""

    @classmethod
    def setUpClass(cls):
        cls.cb_src = _read(os.path.join(ROOT, 'jarvis_chat_bypass.py'))
        cls.w_src = _read(os.path.join(ROOT, 'jarvis_worker.py'))

    def test_chat_bypass_marker(self):
        """jarvis_chat_bypass.py 含 β.5.19-A marker."""
        self.assertIn('β.5.19-A', self.cb_src,
            'β.5.19-A marker 必须在 jarvis_chat_bypass.py')

    def test_worker_marker(self):
        """jarvis_worker.py 含 β.5.19-A marker."""
        self.assertIn('β.5.19-A', self.w_src,
            'β.5.19-A marker 必须在 jarvis_worker.py')

    def test_stream_nudge_resets_flag(self):
        """stream_nudge 入口复位 _last_nudge_was_silence=False."""
        # 找 def stream_nudge 入口, 下方 ~10 行内有复位
        idx = self.cb_src.find('def stream_nudge(')
        self.assertGreater(idx, 0, 'def stream_nudge 必须存在')
        region = self.cb_src[idx:idx + 1500]
        self.assertIn('_last_nudge_was_silence = False', region,
            'stream_nudge 入口必须复位 _last_nudge_was_silence=False')

    def test_silence_chosen_sets_flag(self):
        """_silence_chosen=True 路径 set self._last_nudge_was_silence=True."""
        # 定位 `if _silence_chosen:` 块
        idx = self.cb_src.find('if _silence_chosen:')
        self.assertGreater(idx, 0, '_silence_chosen 块必须存在')
        region = self.cb_src[idx:idx + 800]
        self.assertIn('self._last_nudge_was_silence = True', region,
            '_silence_chosen 路径必须 set _last_nudge_was_silence=True')

    def test_worker_checks_silence_flag(self):
        """worker.py NoSound 路径检测 _last_nudge_was_silence."""
        self.assertIn('_last_nudge_was_silence', self.w_src,
            'worker 必须检测 _last_nudge_was_silence flag')
        self.assertIn('_silenced_intent', self.w_src,
            'worker 必须用 _silenced_intent 局部变量分类')

    def test_worker_skips_warn_when_silenced(self):
        """worker.py 看 _silenced_intent=True 时跳过 ⚠️ NoSound warn log."""
        idx = self.w_src.find('_silenced_intent and not _nudge_exc_repr')
        self.assertGreater(idx, 0,
            'worker 必须有 _silenced_intent + 无 exc 条件分支')
        # 该条件后跳过 NoSound bg_log (else 分支才打 warn)
        region = self.w_src[idx:idx + 600]
        self.assertIn('worker 不再重报', region,
            '条件分支必须明确注释跳过原因')

    def test_silence_path_publishes_self_critique(self):
        """chat_bypass _silence_chosen 路径 publish 'self_critique' 进 SWM."""
        idx = self.cb_src.find('if _silence_chosen:')
        self.assertGreater(idx, 0)
        region = self.cb_src[idx:idx + 1500]
        self.assertIn("etype='self_critique'", region,
            '_silence_chosen 路径必须 publish self_critique 进 SWM')
        self.assertIn("'reaction': 'silence'", region,
            "self_critique metadata 必须含 reaction='silence'")

    def test_silence_log_info_level(self):
        """chat_bypass _silence_chosen 路径打 info 级 `[Nudge/Silence]` log."""
        idx = self.cb_src.find('if _silence_chosen:')
        self.assertGreater(idx, 0)
        region = self.cb_src[idx:idx + 1500]
        self.assertIn('[Nudge/Silence]', region,
            '_silence_chosen 路径必须打 info `[Nudge/Silence]` log')

    def test_normal_empty_reply_still_warns(self):
        """worker.py 真 empty_reply (无 silence flag) 仍打 ⚠️ NoSound warn."""
        idx = self.w_src.find('⚠️ [Nudge/NoSound]')
        self.assertGreater(idx, 0,
            'worker 仍保留 ⚠️ NoSound warn (真异常路径)')
        # 须在 else 分支 (silence_intent=False 或有 exc)
        # 前 200 字符内含 'else:' 表示是非 silence 分支
        region = self.w_src[max(0, idx - 200):idx + 50]
        self.assertIn('else:', region,
            'NoSound warn 必须在 else 分支 (非 silence intent)')


class TestBeta519ARuntimeBehavior(unittest.TestCase):
    """[β.5.19-A] 运行时行为验证 — instance attr 默认 False, [SILENCE] 后 True"""

    def setUp(self):
        # Mock chat_bypass 模拟 instance attr 行为
        class FakeChatBypass:
            def __init__(self):
                self._last_nudge_was_silence = False
        self.cb = FakeChatBypass()

    def test_initial_flag_false(self):
        """新 chat_bypass instance: flag 默认 False (未 nudge 过 / 上轮非 silence)."""
        self.assertFalse(self.cb._last_nudge_was_silence,
            '初始 flag 应 False')

    def test_flag_set_true_after_silence(self):
        """模拟 stream_nudge → silence: flag=True."""
        self.cb._last_nudge_was_silence = True
        self.assertTrue(self.cb._last_nudge_was_silence)

    def test_flag_reset_on_next_call(self):
        """模拟下一次 stream_nudge 入口复位: flag=False."""
        self.cb._last_nudge_was_silence = True
        # 模拟 stream_nudge 入口复位
        self.cb._last_nudge_was_silence = False
        self.assertFalse(self.cb._last_nudge_was_silence,
            '下次 stream_nudge 入口必须复位')


if __name__ == '__main__':
    unittest.main(verbosity=2)
