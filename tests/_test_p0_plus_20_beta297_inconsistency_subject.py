# -*- coding: utf-8 -*-
"""[P0+20-β.2.9.7 / 2026-05-18] InconsistencyWatcher 主体判定 + PromiseLog dedup

Sir 09:06 实测痛点 (jarvis_20260518_*.log):
  "proactive_care [InconsistencyWatcher] 一直提醒之前的事情"
根因链:
  1. PromiseExecutionLog.register 没 dedup → 每次 startup 同 desc+deadline 重复注册
  2. tests/_test_p0_plus_20_beta273_self_promise.py 不隔离 prod log → 30+ "我会监督您
     13:05" 测试残留累积进 prod
  3. InconsistencyWatcher._check_one_promise 看 desc + jarvis_reply 含 "休息" 字面
     就 fire, 不区分主体 — "Jarvis 监督 Sir" 也被当 "Sir 自承诺睡"

本套件覆盖三层防御:
  A. promise_log.register 同 desc+deadline 5min 内 → 返回老 ID (dedup)
  B. InconsistencyWatcher 准则 6 主体判定: 必须 first-person Sir-said-sleep
     verb, 排除 Jarvis wrapper ("监督您"/"hold you to"/"remind"/"watch")
  C. test_p0_plus_20_beta273_self_promise.py 已加 setUpModule / tearDownModule
     隔离 prod log (本套件验证不再污染默认路径)

跑法:
    cd d:\\Jarvis
    python -m unittest tests._test_p0_plus_20_beta297_inconsistency_subject -v
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# A. PromiseLog.register dedup
# ============================================================
class TestPromiseLogDedup(unittest.TestCase):
    def setUp(self):
        from jarvis_promise_log import PromiseExecutionLog, reset_default_log_for_test
        reset_default_log_for_test()
        self._tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8')
        self._tmp.close()
        os.remove(self._tmp.name)
        self.log = PromiseExecutionLog(persist_path=self._tmp.name)

    def tearDown(self):
        try:
            os.remove(self._tmp.name)
        except Exception:
            pass

    def test_same_desc_and_deadline_within_1h_returns_same_id(self):
        # 🩹 [β.2.9.7+] dedup 窗口从 5min 扩到 1h, 防 Sir 启动测试 18-30min 间隔
        # 重复注册同 promise. 真实 Sir 也不会 1h 内说两次"我11点睡".
        pid1 = self.log.register('我会监督您', kind='hard',
                                  deadline_str='13:05',
                                  jarvis_reply='我会监督您在 13:05 准时休息')
        pid2 = self.log.register('我会监督您', kind='hard',
                                  deadline_str='13:05',
                                  jarvis_reply='我会监督您在 13:05 准时休息')
        self.assertEqual(pid1, pid2,
                          'dedup hit 时应返回老 ID 不重复 register')
        self.assertEqual(len(self.log.promises), 1,
                          '内部只应保留 1 条')

    def test_different_deadline_no_dedup(self):
        pid1 = self.log.register('我会监督您', kind='hard', deadline_str='13:05')
        pid2 = self.log.register('我会监督您', kind='hard', deadline_str='14:00')
        self.assertNotEqual(pid1, pid2)
        self.assertEqual(len(self.log.promises), 2)

    def test_old_pending_outside_1h_and_different_reply_no_dedup(self):
        # 🩹 [β.2.9.7+] 验证 dedup 窗口扩到 1h 后, 真正超期 + reply 不同 才不复用.
        pid1 = self.log.register('我会监督您', kind='hard', deadline_str='13:05',
                                  jarvis_reply='reply v1 我会监督您在 13:05')
        # 手动把老的拉到 > 1h 前 + 给 pid2 不同 reply (防 reply_same 旁路)
        self.log.promises[pid1].registered_at = time.time() - 3700
        pid2 = self.log.register('我会监督您', kind='hard', deadline_str='13:05',
                                  jarvis_reply='reply v2 完全不同的回复内容')
        self.assertNotEqual(pid1, pid2,
                          '> 1h + reply 不同, 不再 dedup, 允许新 register')

    def test_same_reply_dedup_even_after_1h(self):
        # 🩹 [β.2.9.7+] reply 完全一致 → 几乎必然是测试/启动重放, 跨任何 age 都复用
        pid1 = self.log.register('我会监督您', kind='hard', deadline_str='13:05',
                                  jarvis_reply='我会监督您在 13:05 准时休息')
        self.log.promises[pid1].registered_at = time.time() - 7200  # 2h 前
        pid2 = self.log.register('我会监督您', kind='hard', deadline_str='13:05',
                                  jarvis_reply='我会监督您在 13:05 准时休息')
        self.assertEqual(pid1, pid2,
                          'reply 完全一致 (启动重放) 应复用, 即便 > 1h')

    def test_dedup_skips_fulfilled(self):
        pid1 = self.log.register('x', kind='soft')
        self.log.mark_fulfilled(pid1, 'k', 'w')
        pid2 = self.log.register('x', kind='soft')
        self.assertNotEqual(pid1, pid2,
                          'fulfilled 不算 pending, 新 register 不复用')


# ============================================================
# B. InconsistencyWatcher 准则 6 主体判定
# ============================================================
class _FakePromise:
    """简化 Promise 接口给 _check_one_promise 用."""
    def __init__(self, description='', jarvis_reply='', kind='hard',
                  registered_at=None, pid='p_fake'):
        self.id = pid
        self.description = description
        self.jarvis_reply = jarvis_reply
        self.kind = kind
        self.registered_at = registered_at or (time.time() - 300)  # 5min 前


class TestInconsistencyWatcherSubject(unittest.TestCase):
    """主体判定 — Sir 自承诺 sleep ✅, Jarvis 监督 wrapper ❌."""

    @classmethod
    def setUpClass(cls):
        from jarvis_inconsistency_watcher import InconsistencyWatcher
        cls.w_cls = InconsistencyWatcher

    def _make_watcher(self):
        class _FakeVT:
            in_active_conversation = True
        class _FakeWorker:
            voice_thread = _FakeVT()
        w = self.w_cls(worker=_FakeWorker())
        return w

    # --- 反例: Jarvis wrapper 不应 fire ---
    def test_jarvis_supervise_sir_NOT_sir_sleep(self):
        """治 Sir 09:06 实测: '我会监督您在 13:05 准时休息' 不是 Sir 承诺睡."""
        p = _FakePromise(description='我会监督您',
                          jarvis_reply='我会监督您在 13:05 准时休息')
        w = self._make_watcher()
        self.assertFalse(w._is_sir_sleep_commitment(p),
                          'Jarvis wrapper 不应被当 Sir 自承诺')

    def test_jarvis_hold_you_to_sleep_NOT_sir_sleep(self):
        p = _FakePromise(description='I shall hold you to that',
                          jarvis_reply='I shall hold you to that 13:05 sleep deadline')
        w = self._make_watcher()
        self.assertFalse(w._is_sir_sleep_commitment(p))

    def test_jarvis_remind_sir_to_sleep_NOT_sir_sleep(self):
        p = _FakePromise(description='I shall remind you at 23:00',
                          jarvis_reply='I shall remind you to sleep at 23:00')
        w = self._make_watcher()
        self.assertFalse(w._is_sir_sleep_commitment(p))

    def test_jarvis_watch_sir_sleep_NOT_sir_sleep(self):
        p = _FakePromise(description='I shall watch over your sleep tonight')
        w = self._make_watcher()
        self.assertFalse(w._is_sir_sleep_commitment(p))

    def test_jarvis_keep_eye_on_sir_NOT_sir_sleep(self):
        p = _FakePromise(description="I'll keep an eye on your bedtime")
        w = self._make_watcher()
        self.assertFalse(w._is_sir_sleep_commitment(p))

    def test_jarvis_monitor_sir_NOT_sir_sleep(self):
        p = _FakePromise(description="I will monitor your sleep at 23:00")
        w = self._make_watcher()
        self.assertFalse(w._is_sir_sleep_commitment(p))

    # --- 正例: Sir 自承诺 应 fire ---
    def test_sir_im_going_to_bed_IS_sleep(self):
        p = _FakePromise(description="I'm going to bed now")
        w = self._make_watcher()
        self.assertTrue(w._is_sir_sleep_commitment(p))

    def test_sir_will_sleep_at_11_IS_sleep(self):
        p = _FakePromise(description="I will sleep at 11")
        w = self._make_watcher()
        self.assertTrue(w._is_sir_sleep_commitment(p))

    def test_sir_zh_qu_shui_IS_sleep(self):
        p = _FakePromise(description="我去睡了")
        w = self._make_watcher()
        self.assertTrue(w._is_sir_sleep_commitment(p))

    def test_sir_zh_yao_shui_IS_sleep(self):
        p = _FakePromise(description="我要睡觉了")
        w = self._make_watcher()
        self.assertTrue(w._is_sir_sleep_commitment(p))

    def test_sir_im_off_to_bed_IS_sleep(self):
        p = _FakePromise(description="I'm off to bed, goodnight")
        w = self._make_watcher()
        self.assertTrue(w._is_sir_sleep_commitment(p))

    # --- _check_one_promise 综合: soft 不查 + age 窗口 ---
    def test_soft_promise_never_triggers(self):
        p = _FakePromise(description='I will sleep at 11', kind='soft')
        w = self._make_watcher()
        self.assertIsNone(w._check_one_promise(p),
                          'soft promise 没 deadline, 不应作 inconsistency 判定基础')

    def test_age_outside_window_returns_none(self):
        # 35min 前 (> MAX_PROMISE_AGE_S 30min)
        p = _FakePromise(description='I will sleep at 11', kind='hard',
                          registered_at=time.time() - 2100)
        w = self._make_watcher()
        self.assertIsNone(w._check_one_promise(p))

    def test_age_too_recent_returns_none(self):
        # 30s 前 (< MIN_PROMISE_AGE_S 60s)
        p = _FakePromise(description='I will sleep at 11', kind='hard',
                          registered_at=time.time() - 30)
        w = self._make_watcher()
        self.assertIsNone(w._check_one_promise(p))


# ============================================================
# C. testcase 隔离验证 (本测试本身就不该污染 prod path)
# ============================================================
class TestNoProdPollution(unittest.TestCase):
    """跑完本套件后, prod memory_pool/jarvis_promise_log.json 不该出现新内容."""

    def test_prod_path_untouched(self):
        prod = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'memory_pool', 'jarvis_promise_log.json')
        if not os.path.exists(prod):
            self.skipTest('prod path missing — first run, OK')
        import json
        with open(prod, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
        # 不允许本测试套件 (description 含 '我会监督您'+'13:05') 残留
        for pid, p in data.items():
            desc = (p.get('description') or '')[:120]
            self.assertNotIn(
                '我会监督您', desc + ' ' + (p.get('jarvis_reply', '') or ''),
                f"prod 残留 '{desc}' from earlier test pollution; "
                f"建议跑: python scripts/promise_log_reset.py --apply --keep-fulfilled")


if __name__ == '__main__':
    unittest.main(verbosity=2)
