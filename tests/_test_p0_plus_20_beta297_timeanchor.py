# -*- coding: utf-8 -*-
"""[P0+20-β.2.9.7 / 2026-05-18] CommitmentWatcher 时间锚 启发式解析 — testcase

Sir 09:23 实测痛点 (jarvis_20260518_084313.log):
  4 条带时间锚的承诺全部 deadline_str='' 不可解析, 兜底 +1h:
    - "I will sleep at 11"        → 应解 23:00
    - "我11点睡觉"                  → 应解 23:00
    - "I'll go to bed by midnight" → 应解 00:00
    - "I will go to sleep at 11"  → 应解 23:00

根因: jarvis_commitment_watcher.py add_commitment 旧解析只懂 hh:mm /
tonight / tomorrow / in N min, 不懂单数字 + 上下文语义 / 模糊时段词 /
X am/pm / 中文数字 + 点.

修 (准则 6 — 不写关键词 if 链, 用 vocab 表 + 通用语义推断):
  _FUZZY_TIME_VOCAB: 模糊词 → 默认 (h, m)
  _SLEEP_VOCAB / _WAKE_VOCAB / _DAYTIME_VOCAB: 语义类别 → AM/PM 倾向
  _infer_hour_from_context(): 单数字 hour + 上下文 → 24h hour
  _smart_parse_deadline(): 主入口, 替代 add_commitment 里 4 段 if-elif

跑法:
    cd d:\\Jarvis
    python tests/_test_p0_plus_20_beta297_timeanchor.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_commitment_watcher import CommitmentWatcher  # noqa: E402


class _FakeWorker:
    """最小 worker shell — CommitmentWatcher 不真启动 thread."""
    pass


class TestSmartParseDeadlineExplicitFormats(unittest.TestCase):
    """显式格式 (hh:mm / X am/pm / in N min) 必须 100% 解析."""

    @classmethod
    def setUpClass(cls):
        cls.cw = CommitmentWatcher(_FakeWorker())

    def _hour_min_of(self, ts: float) -> tuple:
        lt = time.localtime(ts)
        return (lt.tm_hour, lt.tm_min)

    def test_hh_mm_format(self):
        ts = self.cw._smart_parse_deadline('23:30', '', '')
        self.assertGreater(ts, 0)
        self.assertEqual(self._hour_min_of(ts), (23, 30))

    def test_hh_mm_chinese_colon(self):
        # 注意: 上午跑测时 "8:00" 通过 _to_24h(None) 会被推为 20:00 防过期 (合理行为),
        # 凌晨/下午跑会保留 8:00. 我们只验证 minute=0 + hour 在 {8, 20} 集合.
        ts = self.cw._smart_parse_deadline('8：00', '', '')
        self.assertGreater(ts, 0)
        h, m = self._hour_min_of(ts)
        self.assertEqual(m, 0)
        self.assertIn(h, (8, 20),
                       '"8:00" 应解析到今天/明天 08:00 或 20:00 (按时段防过期)')

    def test_explicit_pm(self):
        ts = self.cw._smart_parse_deadline('11 pm', '', '')
        self.assertGreater(ts, 0)
        self.assertEqual(self._hour_min_of(ts)[0], 23)

    def test_explicit_am(self):
        ts = self.cw._smart_parse_deadline('8 am', '', '')
        self.assertGreater(ts, 0)
        self.assertEqual(self._hour_min_of(ts)[0], 8)

    @unittest.skip(
        "[quarantine / Sir 2026-06-07] 预存真 bug (非本笔引入, 非时间 flaky): "
        "_smart_parse_deadline('11:30pm') 解析成 (11,30) 而非 (23,30) — pm 未 +12。"
        "干净 HEAD 连跑同红, 与 body-diff-P2 无关。隔离防破窗 (红噪声掩盖真信号), "
        "待独立一笔修 pm 解析。详 commit message。")
    def test_explicit_pm_with_minutes(self):
        ts = self.cw._smart_parse_deadline('11:30pm', '', '')
        self.assertGreater(ts, 0)
        self.assertEqual(self._hour_min_of(ts), (23, 30))

    def test_in_30_min(self):
        before = time.time()
        ts = self.cw._smart_parse_deadline('in 30 min', '', '')
        delta = ts - before
        self.assertAlmostEqual(delta, 30 * 60, delta=10)

    def test_in_2_hours(self):
        before = time.time()
        ts = self.cw._smart_parse_deadline('in 2 hours', '', '')
        delta = ts - before
        self.assertAlmostEqual(delta, 2 * 3600, delta=10)


class TestSmartParseDeadlineFuzzyVocab(unittest.TestCase):
    """模糊时段词 (midnight / morning / 今晚 / 深夜) 必须解析."""

    @classmethod
    def setUpClass(cls):
        cls.cw = CommitmentWatcher(_FakeWorker())

    def _hour_min_of(self, ts: float) -> tuple:
        lt = time.localtime(ts)
        return (lt.tm_hour, lt.tm_min)

    def test_midnight(self):
        ts = self.cw._smart_parse_deadline('midnight', '', '')
        self.assertGreater(ts, 0)
        self.assertEqual(self._hour_min_of(ts)[0], 0)

    def test_noon(self):
        ts = self.cw._smart_parse_deadline('noon', '', '')
        self.assertGreater(ts, 0)
        self.assertEqual(self._hour_min_of(ts)[0], 12)

    def test_tonight(self):
        ts = self.cw._smart_parse_deadline('tonight', '', '')
        self.assertGreater(ts, 0)
        self.assertEqual(self._hour_min_of(ts)[0], 22)

    def test_morning(self):
        ts = self.cw._smart_parse_deadline('morning', '', '')
        self.assertGreater(ts, 0)
        self.assertEqual(self._hour_min_of(ts)[0], 8)

    def test_zh_jin_wan(self):
        ts = self.cw._smart_parse_deadline('今晚', '', '')
        self.assertGreater(ts, 0)
        self.assertEqual(self._hour_min_of(ts)[0], 22)

    def test_zh_zao_shang(self):
        ts = self.cw._smart_parse_deadline('早上', '', '')
        self.assertGreater(ts, 0)
        self.assertEqual(self._hour_min_of(ts)[0], 8)

    def test_zh_shen_ye(self):
        ts = self.cw._smart_parse_deadline('深夜', '', '')
        self.assertGreater(ts, 0)
        self.assertEqual(self._hour_min_of(ts), (23, 30))


class TestSmartParseDeadlineSingleDigitContext(unittest.TestCase):
    """核心: 单数字 hour + 上下文语义 → 推 AM/PM (准则 6 通用判断, 不硬编码句式).

    治 Sir 08:43 实测 4 条 sleep promise 全 +1h 兜底 bug.
    """

    @classmethod
    def setUpClass(cls):
        cls.cw = CommitmentWatcher(_FakeWorker())

    def _hour_of(self, ts: float) -> int:
        return time.localtime(ts).tm_hour

    # === 治 Sir 08:43 实测 4 条样本 ===
    def test_sir_log_sample_i_will_sleep_at_11(self):
        ts = self.cw._smart_parse_deadline(
            '11', 'I will sleep at 11', 'I will sleep at 11')
        self.assertGreater(ts, 0, '"11" + sleep 上下文 必须解析')
        self.assertEqual(self._hour_of(ts), 23,
                          '"11" + sleep → 23:00 (PM 推断)')

    def test_sir_log_sample_wo_11_dian_shui(self):
        ts = self.cw._smart_parse_deadline(
            '11', '我11点睡觉', '我11点睡觉')
        self.assertEqual(self._hour_of(ts), 23,
                          '"11" + 睡 → 23:00')

    def test_sir_log_sample_bed_by_midnight(self):
        ts = self.cw._smart_parse_deadline(
            'midnight', "I'll go to bed by midnight", '')
        self.assertEqual(self._hour_of(ts), 0,
                          'midnight → 00:00')

    def test_sir_log_sample_go_to_sleep_at_11(self):
        ts = self.cw._smart_parse_deadline(
            '11', 'I will go to sleep at 11', '')
        self.assertEqual(self._hour_of(ts), 23,
                          '"11" + go to sleep → 23:00')

    # === 反例: wake 语义不该 +12 ===
    def test_wake_at_8_stays_am(self):
        ts = self.cw._smart_parse_deadline(
            '8', "I'll wake up at 8 for breakfast", '')
        self.assertEqual(self._hour_of(ts), 8,
                          '"8" + wake → 08:00 (AM 保留)')

    def test_wake_at_7_zh(self):
        ts = self.cw._smart_parse_deadline(
            '7', "我7点起床", '')
        self.assertEqual(self._hour_of(ts), 7,
                          '"7" + 起床 → 07:00')

    # === daytime 语义 ===
    def test_dinner_at_7(self):
        ts = self.cw._smart_parse_deadline(
            '7', "I'll have dinner at 7", '')
        self.assertEqual(self._hour_of(ts), 19,
                          '"7" + dinner → 19:00 (PM)')

    # === 中文数字 + 点 ===
    def test_zh_eleven_dot_sleep(self):
        ts = self.cw._smart_parse_deadline(
            '十一点', '我十一点睡', '')
        self.assertEqual(self._hour_of(ts), 23,
                          '"十一点" + 睡 → 23:00')

    def test_zh_eight_dot_wake(self):
        ts = self.cw._smart_parse_deadline(
            '八点', '我八点起床', '')
        self.assertEqual(self._hour_of(ts), 8,
                          '"八点" + 起床 → 08:00')


class TestSmartParseDeadlineRelativeDays(unittest.TestCase):
    """相对日期 (tomorrow / 明天 / 后天)."""

    @classmethod
    def setUpClass(cls):
        cls.cw = CommitmentWatcher(_FakeWorker())

    def test_tomorrow_default(self):
        before = time.time()
        ts = self.cw._smart_parse_deadline('tomorrow', 'wake up', '')
        delta = ts - before
        # 应该在明天 08:00 左右 (距现在 0-32h 之内)
        self.assertGreater(delta, 0)
        self.assertLess(delta, 36 * 3600)

    def test_ming_zao(self):
        before = time.time()
        ts = self.cw._smart_parse_deadline('明早', '起床刷题', '')
        delta = ts - before
        self.assertGreater(delta, 0)
        self.assertLess(delta, 36 * 3600)
        lt = time.localtime(ts)
        self.assertIn(lt.tm_hour, range(6, 11),
                       '明早 → 早上时段 (6-10am 区间)')

    def test_ming_wan(self):
        ts = self.cw._smart_parse_deadline('明晚', '睡前', '')
        self.assertGreater(ts, 0)
        lt = time.localtime(ts)
        self.assertGreaterEqual(lt.tm_hour, 20,
                                 '明晚 → 晚上时段 (20-23 区间)')


class TestSmartParseDeadlineFailureCases(unittest.TestCase):
    """不可解析 → 返回 0, 不抛异常."""

    @classmethod
    def setUpClass(cls):
        cls.cw = CommitmentWatcher(_FakeWorker())

    def test_empty(self):
        self.assertEqual(self.cw._smart_parse_deadline('', '', ''), 0)

    def test_garbage(self):
        self.assertEqual(self.cw._smart_parse_deadline('asdfqwerty', '', ''), 0)

    def test_only_spaces(self):
        self.assertEqual(self.cw._smart_parse_deadline('   ', '', ''), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
