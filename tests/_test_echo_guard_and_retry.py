"""R5 防回声 + 不可重试错误 单元测试。

覆盖：
1. TTSEchoRing 基本注册 / 命中 / 时间窗外失效 / clear
2. is_recent_jarvis_echo 容忍 ASR 大小写/标点漂移 (As you wish. Muting audio. → as you wish, muting audio)
3. network_retry 装饰器对 403 / PERMISSION_DENIED / billing 立即抛出，不再无脑重试
4. network_retry 对常规异常仍然按指数退避重试

跑法：
    cd d:\\Jarvis
    python tests/_test_echo_guard_and_retry.py
"""
import sys
import os
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jarvis_utils import (
    register_jarvis_tts, is_recent_jarvis_echo, clear_jarvis_tts_ring,
    network_retry, _is_non_retryable_error,
)


class TestTTSEchoRing(unittest.TestCase):
    def setUp(self):
        clear_jarvis_tts_ring()

    def test_register_and_hit_exact(self):
        register_jarvis_tts("Done, Sir.")
        self.assertTrue(is_recent_jarvis_echo("Done, Sir."))

    def test_register_and_hit_case_punctuation(self):
        register_jarvis_tts("As you wish. Muting audio.")
        # ASR 经常把句号听成逗号 + 全小写 + 去掉标点
        self.assertTrue(is_recent_jarvis_echo("As you wish, muting audio"))
        self.assertTrue(is_recent_jarvis_echo("as you wish muting audio"))
        self.assertTrue(is_recent_jarvis_echo("As you wish , Muting audio ."))

    def test_no_hit_for_unrelated(self):
        register_jarvis_tts("Done, Sir.")
        self.assertFalse(is_recent_jarvis_echo("帮我把音量调到 30 percent"))
        self.assertFalse(is_recent_jarvis_echo("hello jarvis"))

    def test_substring_hit(self):
        register_jarvis_tts("Pylance seems rather displeased with an undefined variable.")
        # ASR 可能只听到一半
        self.assertTrue(is_recent_jarvis_echo("pylance seems rather displeased"))

    def test_empty_or_too_short_text(self):
        register_jarvis_tts("Done.")
        self.assertFalse(is_recent_jarvis_echo(""))
        self.assertFalse(is_recent_jarvis_echo("ok"))

    def test_clear_ring(self):
        register_jarvis_tts("Standing down, Sir.")
        self.assertTrue(is_recent_jarvis_echo("Standing down, Sir."))
        clear_jarvis_tts_ring()
        self.assertFalse(is_recent_jarvis_echo("Standing down, Sir."))

    def test_window_expiry(self):
        # 模拟 13s 前注册的句子（窗口 12s），应该 miss
        from jarvis_utils import _TTSEchoRing
        _TTSEchoRing._entries.append((time.time() - 13.0, _TTSEchoRing._normalize("old phrase here for test")))
        self.assertFalse(is_recent_jarvis_echo("old phrase here for test"))

    def test_chinese_tts_echo(self):
        register_jarvis_tts("如您所愿，已静音。")
        self.assertTrue(is_recent_jarvis_echo("如您所愿，已静音"))
        self.assertTrue(is_recent_jarvis_echo("如您所愿 已静音"))

    # 🩹 [β.2.7.7 / 2026-05-17] 短句宽容路径 — 治 Sir 实测 "What's sir" 漏过
    def test_short_sentence_with_jarvis_jargon_echo(self):
        """Jarvis 末尾 'Sir.' 被 ASR 切碎补全成 'What's sir' (3 token / 10 char) 也应识为 echo"""
        register_jarvis_tts(
            "Between your video editing suites and architectural refinements, "
            "the system is often juggling significant resource demands. Sir."
        )
        # 主诉 BUG case
        self.assertTrue(is_recent_jarvis_echo("What's sir"),
                        "短句含 jarvis 高频词 'sir' 应识为 echo")
        # 其他典型 Jarvis 余音
        self.assertTrue(is_recent_jarvis_echo("Sir."))
        self.assertTrue(is_recent_jarvis_echo("Yes sir"))

    def test_real_user_short_query_not_echo(self):
        """真用户短查询（不含 jarvis 高频词）不应误判为 echo"""
        register_jarvis_tts(
            "Sir, the system status is nominal across all subsystems."
        )
        # 真用户 query
        self.assertFalse(is_recent_jarvis_echo("Show me cursor"))
        self.assertFalse(is_recent_jarvis_echo("What time is it"))
        self.assertFalse(is_recent_jarvis_echo("I am tired"))

    def test_short_jarvis_jargon_no_jarvis_history_not_echo(self):
        """Jarvis 没说过 'Of course'，即便短句不应误判"""
        clear_jarvis_tts_ring()
        register_jarvis_tts("Sir, the weather looks pleasant today.")
        # "Of course" 含 jarvis 高频词但 ring 里没 Jarvis 答语含此词 → 不算 echo
        self.assertFalse(is_recent_jarvis_echo("Of course"))


class TestNonRetryableErrorGuard(unittest.TestCase):
    def test_403_detected(self):
        e = Exception("403 PERMISSION_DENIED. Your project has been denied access. Please contact support.")
        self.assertTrue(_is_non_retryable_error(e))

    def test_401_detected(self):
        e = Exception("401 unauthorized: API key not valid")
        self.assertTrue(_is_non_retryable_error(e))

    def test_billing_detected(self):
        e = Exception("Billing has been disabled for this project")
        self.assertTrue(_is_non_retryable_error(e))

    def test_503_is_retryable(self):
        e = Exception("503 service unavailable")
        self.assertFalse(_is_non_retryable_error(e))

    def test_network_timeout_is_retryable(self):
        e = Exception("Read timed out")
        self.assertFalse(_is_non_retryable_error(e))


class TestNetworkRetry(unittest.TestCase):
    def test_403_does_not_retry(self):
        counter = {'n': 0}

        @network_retry(max_retries=3, base_delay=0.01)
        def boom():
            counter['n'] += 1
            raise RuntimeError("403 PERMISSION_DENIED. Your project has been denied access.")

        with self.assertRaises(RuntimeError):
            boom()
        self.assertEqual(counter['n'], 1, "403 应该一次就 raise，绝不重试")

    def test_retryable_error_retries_until_success(self):
        counter = {'n': 0}

        @network_retry(max_retries=3, base_delay=0.01)
        def flaky():
            counter['n'] += 1
            if counter['n'] < 3:
                raise RuntimeError("503 service unavailable")
            return "ok"

        result = flaky()
        self.assertEqual(result, "ok")
        self.assertEqual(counter['n'], 3, "前 2 次 503 应该被重试，第 3 次成功")

    def test_retryable_error_exhausts_retries(self):
        counter = {'n': 0}

        @network_retry(max_retries=2, base_delay=0.01)
        def always_503():
            counter['n'] += 1
            raise RuntimeError("503 service unavailable")

        with self.assertRaises(RuntimeError):
            always_503()
        # max_retries=2 → 1 次原始 + 2 次重试 = 3 次调用
        self.assertEqual(counter['n'], 3)


def main():
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
    try:
        print("\n[OK] All R5 echo-guard + retry tests passed.")
    except UnicodeEncodeError:
        sys.stdout.write("\n[OK] All R5 echo-guard + retry tests passed.\n")


if __name__ == "__main__":
    main()
