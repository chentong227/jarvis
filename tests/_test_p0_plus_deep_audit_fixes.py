# -*- coding: utf-8 -*-
"""
[P0+ / 2026-05-15] 深度体检 + 修复链路 — 测试套件

覆盖本轮 8 处修复（每条都对应 jarvis_nerve.py / jarvis_blood.py 的具体改动）：

  P0+9   ReturnSentinel "8:03 误触 + 没实现" 双修
         - 启动后 5min 内不允许 first_active_today 触发
         - idle_ms hysteresis（连续 5s 才算回归）
         - last_afk_start 初值改 time.time()
         - _on_return 加全链路 bg_log
         - LLM 路径成功后 first_active_today=False
         - __NUDGE__ stream_nudge 失败/为空打 bg_log + publish 'nudge_no_sound'
  P0+10  SmartNudge 拒绝期通用化（return_greeting 之外都挡）
  P0+11  soft_focus_fail 退出补 _publish_listening_done
  P0+12  _detect_sleep_intent 双语义 — 加清晰别名
         CentralNerve._detect_deep_sleep_request
         JarvisWorkerThread._detect_sleep_window_intent
  P0+13  FeedbackSignal 双定义合并 — nerve.py 改为 from jarvis_blood import
  P0+14  HumorMemory 共享单例 — CompanionCenter / SmartNudgeSentinel 接收外部注入

  C1-1   jarvis_nerve_backup.py 已删
  C1-3   task_pool 实例化已删
  C1-4   PromptCenter.habit_clock 实例化已删
  C1-5   _rule_decision companion_alert 死分支已删
  C1-7   重复 import 已清理 + difflib 已删

测试方法：源码契约（grep 关键 marker / 字符串）+ 关键路径单元测试。
"""
import os
import re
import sys
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(path):
    # [P0+19 / 2026-05-16] 拆分后 nerve.py 内容分散到多文件；自动用 corpus helper
    if 'jarvis_nerve.py' in str(path):
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        return read_nerve_corpus()
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


NERVE_PATH = os.path.join(ROOT, 'jarvis_nerve.py')
BLOOD_PATH = os.path.join(ROOT, 'jarvis_blood.py')


class TestP0Plus9ReturnSentinelStartupGuard(unittest.TestCase):
    """P0+9 / ReturnSentinel 启动 5min 护栏 + idle hysteresis + bg_log 链路"""

    def setUp(self):
        self.src = _read(NERVE_PATH)

    def test_startup_guard_field_initialized(self):
        self.assertIn(
            "self._startup_guard_until = time.time() + 300.0", self.src,
            "ReturnSentinel.__init__ 必须初始化 _startup_guard_until 为 now+300s"
        )

    def test_active_streak_field_initialized(self):
        self.assertIn(
            "self._active_streak_seconds = 0", self.src,
            "ReturnSentinel.__init__ 必须初始化 _active_streak_seconds = 0"
        )

    def test_last_afk_start_uses_time_not_zero(self):
        m = re.search(r"self\.last_afk_start\s*=\s*time\.time\(\)", self.src)
        self.assertIsNotNone(m, "ReturnSentinel.__init__ 必须用 time.time() 初值，避免 epoch 巨量秒误通过")

    def test_run_has_hysteresis_logic(self):
        self.assertIn(
            "self._active_streak_seconds += 1", self.src,
            "ReturnSentinel.run 必须包含 active_streak 累加逻辑（hysteresis）"
        )
        self.assertIn(
            "self._active_streak_seconds >= 5", self.src,
            "ReturnSentinel.run 必须用 active_streak >= 5 作为退出 AFK 条件"
        )

    def test_on_return_has_startup_guard_check(self):
        self.assertIn(
            "time.time() < self._startup_guard_until", self.src,
            "_on_return 必须检查 _startup_guard_until 启动护栏"
        )
        self.assertIn(
            "[ReturnSentinel/StartupGuard]", self.src,
            "_on_return 启动护栏触发时必须 bg_log"
        )

    def test_on_return_has_skip_logs(self):
        for tag in [
            "[ReturnSentinel/Skip]",
            "[ReturnSentinel/Blocked]",
            "[ReturnSentinel/Sent]",
        ]:
            self.assertIn(tag, self.src,
                          f"_on_return 必须打 {tag} bg_log 让 Sir 看见原因")

    def test_llm_path_resets_first_active_today(self):
        # 找 LLM 路径里的 self.first_active_today = False
        # 注意: 罐头模板路径已有，关键是 LLM 路径也必须有
        m = re.search(
            r"self\.gate\.mark_spoke\('guardian'\).*?self\._last_greeting_time\s*=\s*time\.time\(\).*?self\.first_active_today\s*=\s*False",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "LLM 路径成功推送 NUDGE 后必须置 self.first_active_today = False，防反复触发")

    def test_nudge_dispatch_logs_no_sound(self):
        # JarvisWorker.run 处理 __NUDGE__ 时 stream_nudge 为空/抛错都要 bg_log
        self.assertIn("[Nudge/NoSound]", self.src,
                      "__NUDGE__ 处理 stream_nudge 失败/为空时必须 bg_log [Nudge/NoSound]")
        self.assertIn("'nudge_no_sound'", self.src,
                      "未出声场景必须 publish 'nudge_no_sound' 事件到 event_bus")


class TestP0Plus10SmartNudgeRefusalGeneralization(unittest.TestCase):
    """P0+10 / SmartNudge 拒绝期通用化（不再只挡 offer_help）"""

    def setUp(self):
        self.src = _read(NERVE_PATH)

    def test_dispatch_uses_general_refusal_check(self):
        # 应该有 nudge_type != 'return_greeting' and time.time() < self._refused_help_until
        m = re.search(
            r"if\s+nudge_type\s*!=\s*['\"]return_greeting['\"]\s+and\s+time\.time\(\)\s*<\s*self\._refused_help_until",
            self.src,
        )
        self.assertIsNotNone(m,
            "SmartNudge._dispatch_nudge 必须对所有 nudge_type 尊重 _refused_help_until（return_greeting 例外）")

    def test_dispatch_logs_smartnudge_refusal_respect(self):
        self.assertIn("[SmartNudge/RefusalRespect]", self.src,
                      "SmartNudge 拒绝期挡截必须 bg_log")


class TestP0Plus11SoftFocusFailListeningDone(unittest.TestCase):
    """P0+11 / soft_focus_fail 退出补 _publish_listening_done"""

    def setUp(self):
        self.src = _read(NERVE_PATH)

    def test_soft_focus_fail_publishes_listening_done(self):
        # 找到 soft_focus 失败 continue 块附近
        m = re.search(
            r"self\.last_dismissal_reason\s*=\s*'false_alarm'\s*\n\s*self\.awake_signal\.emit\(False\)\s*\n\s*set_browser_ducking\(False\)\s*\n\s*#.*\n\s*#.*\n\s*#.*\n\s*self\._publish_listening_done\(\)",
            self.src,
        )
        if not m:
            # 如果注释长度变了，用宽松断言
            soft_focus_chunk = re.search(
                r"self\.last_dismissal_reason\s*=\s*'false_alarm'(.*?)continue",
                self.src, re.DOTALL,
            )
            self.assertIsNotNone(soft_focus_chunk,
                "未找到 soft_focus_fail 退出代码块")
            self.assertIn("self._publish_listening_done()", soft_focus_chunk.group(1),
                "soft_focus_fail 退出 continue 之前必须调 _publish_listening_done()")


class TestP0Plus12SleepIntentSemanticAliases(unittest.TestCase):
    """P0+12 / 双 _detect_sleep_intent 语义清晰别名"""

    def setUp(self):
        self.src = _read(NERVE_PATH)

    def test_central_nerve_has_deep_sleep_alias(self):
        self.assertIn("def _detect_deep_sleep_request", self.src,
                      "CentralNerve 必须有 _detect_deep_sleep_request 别名（语义清晰）")

    def test_worker_has_sleep_window_alias(self):
        self.assertIn("def _detect_sleep_window_intent", self.src,
                      "JarvisWorkerThread 必须有 _detect_sleep_window_intent 别名（语义清晰）")

    def test_aliases_delegate_to_legacy_names(self):
        # 别名实际应该 return self._detect_sleep_intent(...)
        chunk_a = re.search(
            r"def _detect_deep_sleep_request\(self,\s*user_input.*?\):.*?return self\._detect_sleep_intent\(user_input\)",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(chunk_a, "_detect_deep_sleep_request 必须委托给历史名 _detect_sleep_intent")
        chunk_b = re.search(
            r"def _detect_sleep_window_intent\(self,\s*cmd.*?\):.*?return self\._detect_sleep_intent\(cmd\)",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(chunk_b, "_detect_sleep_window_intent 必须委托给历史名 _detect_sleep_intent")


class TestP0Plus13FeedbackSignalUnified(unittest.TestCase):
    """P0+13 / FeedbackSignal 双定义合并"""

    def setUp(self):
        self.nerve_src = _read(NERVE_PATH)
        self.blood_src = _read(BLOOD_PATH)

    def test_blood_has_dataclass(self):
        self.assertIn("class FeedbackSignal:", self.blood_src,
                      "jarvis_blood.py 必须保留 FeedbackSignal 定义")
        self.assertIn("@dataclass", self.blood_src.split("class FeedbackSignal:")[0][-50:],
                      "blood 的 FeedbackSignal 必须是 @dataclass")

    def test_blood_fields_have_defaults(self):
        chunk = self.blood_src[self.blood_src.index("class FeedbackSignal"):]
        chunk = chunk[:chunk.index("@dataclass\nclass MemoryFragment")]
        for field_name in ["signal_type", "user_input", "jarvis_response", "context_snapshot"]:
            self.assertIn(f"{field_name}:", chunk,
                          f"FeedbackSignal 应有字段 {field_name}")

    def test_nerve_imports_from_blood(self):
        self.assertIn("from jarvis_blood import FeedbackSignal", self.nerve_src,
                      "jarvis_nerve.py 必须 from jarvis_blood import FeedbackSignal")

    def test_nerve_no_longer_redefines_dataclass(self):
        # nerve 里不能再有 @dataclass + class FeedbackSignal: 紧贴
        m = re.search(
            r"@dataclass\s*\n\s*class\s+FeedbackSignal\b",
            self.nerve_src,
        )
        self.assertIsNone(m,
            "jarvis_nerve.py 不能再有自己的 @dataclass class FeedbackSignal 定义")

    def test_runtime_feedback_signal_is_blood_one(self):
        # 真 import 检查
        from jarvis_nerve import FeedbackSignal as nerve_fs
        from jarvis_blood import FeedbackSignal as blood_fs
        self.assertIs(nerve_fs, blood_fs,
                      "运行时 jarvis_nerve.FeedbackSignal 必须就是 jarvis_blood.FeedbackSignal")


class TestP0Plus14HumorMemorySingleton(unittest.TestCase):
    """P0+14 / HumorMemory 共享单例"""

    def setUp(self):
        self.src = _read(NERVE_PATH)

    def test_smart_nudge_init_accepts_humor_memory_param(self):
        # SmartNudgeSentinel.__init__ 应接受 humor_memory= 参数
        m = re.search(
            r"class SmartNudgeSentinel\(threading\.Thread\):.*?def __init__\(self,\s*jarvis_worker,\s*nudge_gate=None,\s*humor_memory=None\)",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "SmartNudgeSentinel.__init__ 必须接受 humor_memory=None 参数")

    def test_smart_nudge_uses_external_when_provided(self):
        # self.humor_memory = humor_memory if humor_memory is not None else HumorMemory()
        m = re.search(
            r"self\.humor_memory\s*=\s*humor_memory\s+if\s+humor_memory\s+is\s+not\s+None\s+else\s+HumorMemory\(\)",
            self.src,
        )
        self.assertIsNotNone(m,
            "SmartNudgeSentinel 应优先使用外部注入的 humor_memory")

    def test_companion_center_passes_humor_memory(self):
        m = re.search(
            r"def __init__\(self,\s*jarvis_worker,\s*nudge_gate:\s*NudgeGate,\s*humor_memory=None\)",
            self.src,
        )
        self.assertIsNotNone(m,
            "CompanionCenter.__init__ 必须接受 humor_memory=None 参数")
        self.assertIn(
            "humor_memory=self.humor_memory",
            self.src,
            "CompanionCenter.start_all 必须把 self.humor_memory 传给 SmartNudgeSentinel"
        )

    def test_central_nerve_creates_singleton(self):
        # CentralNerve 必须创建 self.humor_memory = HumorMemory()
        # 并把它传给 CompanionCenter
        m = re.search(
            r"self\.humor_memory\s*=\s*HumorMemory\(\)\s*\n\s*self\.companion_center\s*=\s*CompanionCenter\(\s*self,\s*nudge_gate=self\.nudge_gate,\s*humor_memory=self\.humor_memory",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "CentralNerve 必须创建 self.humor_memory 并立刻传给 CompanionCenter")

    def test_main_reuses_central_nerve_humor_memory(self):
        # main 段 humor_memory = jarvis_worker.jarvis.humor_memory
        self.assertIn(
            "humor_memory = jarvis_worker.jarvis.humor_memory",
            self.src,
            "main 段必须复用 jarvis_worker.jarvis.humor_memory，不再 new"
        )


class TestC1DeadCodeCleanupBatch1(unittest.TestCase):
    """死代码清扫批次 1 验证（C1-1, C1-3, C1-4, C1-5, C1-7）"""

    def setUp(self):
        self.src = _read(NERVE_PATH)

    def test_c1_1_backup_file_deleted(self):
        backup_path = os.path.join(ROOT, 'jarvis_nerve_backup.py')
        self.assertFalse(os.path.exists(backup_path),
                         "jarvis_nerve_backup.py 应已删除（C1-1）")

    def test_c1_3_task_pool_instance_removed(self):
        # 应该不再有 self.task_pool = TaskWorkerPool(...) 这一行
        self.assertNotIn(
            "self.task_pool = TaskWorkerPool",
            self.src,
            "self.task_pool = TaskWorkerPool(...) 实例化已删除（C1-3）"
        )

    def test_c1_4_prompt_center_habit_clock_removed(self):
        # PromptCenter.__init__ 中应该没有 self.habit_clock = HabitClock()
        # 但 CentralNerve.__init__ 仍然有 self.habit_clock = HabitClock()
        # 用上下文验证：搜 PromptCenter 类内的 habit_clock 赋值
        m = re.search(
            r"class PromptCenter:(.*?)class\s+CompanionCenter",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m, "未找到 PromptCenter 类")
        prompt_center_body = m.group(1)
        self.assertNotIn(
            "self.habit_clock = HabitClock()",
            prompt_center_body,
            "PromptCenter 不应再创建孤立的 self.habit_clock 实例（C1-4）"
        )
        # 顺便确认 CentralNerve 仍有
        m2 = re.search(
            r"class CentralNerve.*?self\.habit_clock\s*=\s*HabitClock\(\)",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m2,
            "CentralNerve.habit_clock 仍应保留（业务实际用的是这个）")

    def test_c1_5_companion_alert_dead_branch_removed(self):
        # _rule_decision 内不应再读 companion_alert
        m = re.search(
            r"def _rule_decision\(self.*?def\s+\w+\(",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m, "未找到 _rule_decision 方法")
        rule_decision_body = m.group(0)
        self.assertNotIn(
            "companion_alert.get('active')",
            rule_decision_body,
            "_rule_decision 不应再有 companion_alert 死分支（C1-5）"
        )

    def test_c1_7_difflib_import_removed(self):
        self.assertNotIn(
            "import difflib",
            self.src,
            "未使用的 difflib import 应已删除（C1-7）"
        )

    def test_c1_7_no_duplicate_threading_queue_pycaw_imports(self):
        # 顶部 (line 1-100) 不应有重复 import threading / queue / from pycaw
        head = '\n'.join(self.src.split('\n')[:100])
        # threading 出现一次
        self.assertEqual(
            head.count("\nimport threading"),
            1,
            "顶部 import threading 应只出现一次（C1-7）"
        )
        # queue 出现一次
        self.assertEqual(
            head.count("\nimport queue"),
            1,
            "顶部 import queue 应只出现一次（C1-7）"
        )
        # pycaw 出现一次（含 IAudioMeterInformation 那一行）
        self.assertEqual(
            head.count("from pycaw.pycaw import"),
            1,
            "顶部 from pycaw.pycaw import 应只出现一次（C1-7）"
        )


class TestRuntimeFeedbackSignalCompat(unittest.TestCase):
    """运行时验证 FeedbackSignal 合并后 FeedbackTracker 仍能正常工作"""

    def test_feedback_tracker_analyze_interaction_returns_blood_signal(self):
        from jarvis_nerve import FeedbackTracker
        from jarvis_blood import FeedbackSignal as BloodFS
        tracker = FeedbackTracker()
        sig = tracker.analyze_interaction(
            user_input="不对", jarvis_response="抱歉，我重新理解一下", stm_context=""
        )
        self.assertIsInstance(sig, BloodFS,
                              "FeedbackTracker.analyze_interaction 必须返回 jarvis_blood.FeedbackSignal")
        self.assertEqual(sig.signal_type, "correction",
                         "'不对' 应被识别为 correction")
        self.assertGreater(sig.timestamp, 0,
                           "blood 版的 FeedbackSignal.timestamp 应自动用 time.time()")


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("[OK] All P0+ deep audit fix tests passed.")
    else:
        print(f"[FAIL] {len(result.failures)} failures, {len(result.errors)} errors")
    print("=" * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
