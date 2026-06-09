# -*- coding: utf-8 -*-
"""[fixG3b-prune-proactive-care-dead-topic / Sir 2026-06-09] proactive_care _topics 清死名.

proactive_care.py:1136 区 _topics 是 lifecycle events 纯过滤 (etype in _topics).
死名 'memory_corrected' 零 producer (全仓 grep 实证, 与 fixG3 同源历史遗留) → 永不命中.
移除逐字节 behavior-preserving. 余 3 名 (promise_fulfilled/promise_cancelled/
concern_dismissed) 均有 producer, 保留.

T1 _topics 不再含死名 memory_corrected, 仍含 3 活名.
T2 死名 event 不被 _topics 过滤命中 (源码层断言: memory_corrected 不在 tuple).
"""
from __future__ import annotations

import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

SRC_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'jarvis_proactive_care.py')


def _read_topics_tuple():
    """从源码抽 _topics = (...) 的成员 (该行后续多行 tuple)."""
    src = io.open(SRC_PATH, encoding='utf-8').read()
    # 匹配 _topics = ( ... ) 直到第一个右括号
    m = re.search(r"_topics\s*=\s*\(([^)]*)\)", src, re.DOTALL)
    assert m, "未找到 _topics 定义"
    body = m.group(1)
    return set(re.findall(r"'([a-z_]+)'", body))


class TestFixG3bProactiveCareDeadTopic(unittest.TestCase):

    def test_t1_dead_name_removed_live_names_kept(self):
        topics = _read_topics_tuple()
        # 死名已清
        self.assertNotIn('memory_corrected', topics,
                         "死名 memory_corrected 应已从 _topics 移除")
        # 3 活名仍在
        for live in ('promise_fulfilled', 'promise_cancelled', 'concern_dismissed'):
            self.assertIn(live, topics, f"活名 {live} 应保留")
        # 精确剩 3 名
        self.assertEqual(topics, {'promise_fulfilled', 'promise_cancelled',
                                  'concern_dismissed'})

    def test_t2_dead_name_never_matches_filter(self):
        """_topics 是纯过滤; memory_corrected 不在 tuple → 该 etype 的 event 永不命中.
        逐字节 BP: 删前死名本就不命中 (零 producer), 删后仍不命中 (不在 tuple)."""
        topics = _read_topics_tuple()
        # 模拟过滤逻辑: etype in _topics
        self.assertFalse('memory_corrected' in topics,
                         "memory_corrected event 不会被 _topics 过滤命中 (行为同删除前)")


if __name__ == '__main__':
    unittest.main()
