# -*- coding: utf-8 -*-
"""[P0+20-β.2.9.9 / 2026-05-18] CommitmentWatcher "时间确定性" 闸门 testcase

Sir 10:43 实测痛点:
  "我剪辑完这个视频就行" 被误注册为承诺 + 兜底 +1h (10:43 → 11:43 错闹).
  真问题: 这是个未来动作陈述, 但**没有具体时间 + 没有 predicate**.

修法 (准则 6 架构, 不硬编码"就行/完了"句式):
  add_commitment 加新闸门 — 必须有 EITHER:
    (a) 可解析的 deadline_str (走 _smart_parse_deadline 出非 0)
    (b) 不为空的 predicate (走 evaluate 路径)
  都没 → 拒绝注册 hard, 转 PromiseLog soft.

testcase 覆盖:
  - "我11点睡觉" + deadline_str='23:00' → 注册 (有时间锚)
  - "等我导出完视频" + predicate=ProcessExited → 注册 (有 predicate)
  - "我剪辑完就行" + deadline_str='' + predicate=None → 拒绝 + 转 soft
  - "我会去刷题" + deadline_str='' + predicate=None → 拒绝
  - Time Hook 已确认 → 信任跳过本闸门 (向后兼容)

跑法:
    cd d:\\Jarvis
    python tests/_test_p0_plus_20_beta299_commit_confidence.py
"""
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# 模块级隔离 prod promise_log (防本测试污染)
_ISO_PATH = None


def setUpModule():
    global _ISO_PATH
    _tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.json', delete=False, encoding='utf-8')
    _tmp.write('{}\n')
    _tmp.close()
    _ISO_PATH = _tmp.name
    from jarvis_promise_log import reset_default_log_for_test
    reset_default_log_for_test(persist_path=_ISO_PATH)


def tearDownModule():
    from jarvis_promise_log import reset_default_log_for_test
    reset_default_log_for_test()
    if _ISO_PATH and os.path.exists(_ISO_PATH):
        try:
            os.remove(_ISO_PATH)
        except Exception:
            pass


class _FakeHippo:
    """模拟 Hippocampus add_commitment_row, 让 CommitmentWatcher 注册 in-memory list."""
    def __init__(self):
        self.added = []
        self._next_id = 100

    def add_commitment_row(self, **kwargs):
        self._next_id += 1
        self.added.append({'id': self._next_id, **kwargs})
        return self._next_id


class _FakeWorker:
    pass


def _make_cw():
    """返 CommitmentWatcher + fake hippo (替换 _get_hippo)."""
    from jarvis_commitment_watcher import CommitmentWatcher
    cw = CommitmentWatcher(_FakeWorker())
    fake_hippo = _FakeHippo()
    cw._get_hippo = lambda: fake_hippo
    cw._fake_hippo = fake_hippo
    return cw


class TestTimeAnchorGate(unittest.TestCase):
    """🩹 时间确定性闸门 — 无 deadline + 无 predicate 必拒"""

    def setUp(self):
        self.cw = _make_cw()

    def test_no_anchor_no_predicate_rejected(self):
        """Sir 实测样本 — '我剪辑完这个视频就行' 必拒"""
        self.cw.add_commitment(
            description='我剪辑完这个视频就行',
            deadline_str='',
            user_text='我剪辑完这个视频就行',
            commit_type='sir_self_promise',
            predicate=None,
        )
        # in-memory list 应空
        self.assertEqual(len(self.cw.commitments), 0,
                          '"我剪辑完就行" 无时间锚无 predicate 不应注册')
        # SQLite 也不写
        self.assertEqual(len(self.cw._fake_hippo.added), 0)

    def test_no_anchor_zh_phrase_rejected(self):
        """类似样本 '我会去刷题' 也必拒"""
        self.cw.add_commitment(
            description='我会去刷题',
            deadline_str='',
            user_text='我会去刷题',
            commit_type='sir_self_promise',
            predicate=None,
        )
        self.assertEqual(len(self.cw.commitments), 0)

    def test_no_anchor_falls_to_promise_log_soft(self):
        """拒注册时, 转 PromiseLog soft 让 Sir 仍能看到"""
        from jarvis_promise_log import get_default_log
        log = get_default_log()
        before_n = len(log.promises)
        self.cw.add_commitment(
            description='我剪辑完这个视频就行',
            deadline_str='',
            user_text='我剪辑完这个视频就行',
            commit_type='sir_self_promise',
            predicate=None,
        )
        after_n = len(log.promises)
        self.assertEqual(after_n - before_n, 1,
                          '拒 hard 注册时应转 PromiseLog soft 记 1 笔')
        # 找到这条
        new_promises = [p for p in log.promises.values()
                        if '剪辑' in p.description]
        self.assertEqual(len(new_promises), 1)
        self.assertEqual(new_promises[0].kind, 'soft')

    def test_with_deadline_str_passes(self):
        """有时间锚 → 正常注册"""
        self.cw.add_commitment(
            description='我11点睡觉',
            deadline_str='23:00',
            user_text='我11点睡觉',
            commit_type='sir_self_promise',
            predicate=None,
        )
        self.assertEqual(len(self.cw.commitments), 1,
                          '有时间锚必须注册')

    def test_with_smart_parse_resolvable_passes(self):
        """deadline_str='11' + sleep 上下文 → _smart_parse 能解 23:00 → 注册"""
        self.cw.add_commitment(
            description='I will sleep at 11',
            deadline_str='11',
            user_text='I will sleep at 11',
            commit_type='sir_self_promise',
            predicate=None,
        )
        self.assertEqual(len(self.cw.commitments), 1)

    def test_with_predicate_passes(self):
        """有 predicate (conditional_reminder) → 正常注册"""
        # 用一个 mock predicate (假装是 ProcessExited)
        pred = MagicMock()
        pred.describe = lambda: 'ProcessExited(Premiere)'
        pred.evaluate = lambda ctx: False
        self.cw.add_commitment(
            description='等我导出完视频去喝水',
            deadline_str='',
            user_text='等我导出完视频去喝水, 提醒我',
            commit_type='conditional_reminder',
            predicate=pred,
        )
        self.assertEqual(len(self.cw.commitments), 1,
                          '有 predicate 必须注册')

    def test_is_future_task_confirmed_bypasses_gate(self):
        """Time Hook 已确认 → 信任上游, 跳过本闸门 (向后兼容)"""
        self.cw.add_commitment(
            description='明早起床刷题',
            deadline_str='',  # Time Hook 没传 deadline_str 但已 schedule
            user_text='明早起床刷题',
            commit_type='sir_self_promise',
            predicate=None,
            is_future_task_confirmed=True,
        )
        self.assertEqual(len(self.cw.commitments), 1,
                          'Time Hook 确认应信任注册 (向后兼容)')


class TestRegressionTimeAnchorStillWorks(unittest.TestCase):
    """回归: β.2.9.7 时间锚启发式仍生效 — 让闸门正确放行"""

    def setUp(self):
        self.cw = _make_cw()

    def test_sleep_at_11_zh(self):
        self.cw.add_commitment(
            description='我11点睡觉',
            deadline_str='11',
            user_text='我11点睡觉',
            commit_type='sir_self_promise',
        )
        self.assertEqual(len(self.cw.commitments), 1)
        # 验证 deadline 是 23:00 (晚上) 不是 11:00 (上午)
        t = time.localtime(self.cw.commitments[0]['deadline_ts'])
        self.assertEqual(t.tm_hour, 23,
                          '"11" + 睡 → 23:00 (β.2.9.7-α 时间锚启发式)')


if __name__ == '__main__':
    unittest.main(verbosity=2)
