# -*- coding: utf-8 -*-
"""[governor F8 / Sir 2026-06-02] 语义 thread 归并 — emergent×F3/F4 张力治本回归.

根因 (真机 jarvis_20260602_074737 实测):
  emergent 模式下主脑对同一语义主题 (keyrouter) 反复声明 <CONTINUITY>new_topic →
  23 条同义 thought 散在 11 个 thread_id, 单 thread max=3 occurrences < F3/F4 阈值
  (即便降到 6) → let_go 元能力永不触发 → 反刍治理对 emergent 失效。

治本 (准则 8 根因非糖衣, 准则 6 信任 LLM + 准则 7 可关):
  _parse_thought 在 LLM 声明 new_topic 时, 若 thought 文本与近窗某 thread jaccard >=
  阈值 → 归并入该既有 thread (continuity='semantic_merge')。thread_id 从此追踪
  '语义现实', F3/F4/let_go 全部自动复活。

覆盖:
  F8_1  config helper seed 默认 (vocab 缺失 fallback)
  F8_2  config helper 读 live vocab + sanity cap
  F8_3  new_topic + 语义相似近窗 thread → 归并 (thread_id 复用, continuity=semantic_merge)
  F8_4  new_topic + 语义不相似 → 不归并 (新 thread_id)
  F8_5  same_thread LLM 声明 → 不走归并 (LLM 主判优先)
  F8_6  enabled=False → 关归并, new_topic 永远新 thread (准则 7 Sir 可关)
  F8_7  lookback 窗口外的相似 thread 不归并 (只看近窗)
  F8_8  归并让 keyrouter 反刍场景下单 thread 计数破阈值 (端到端: F3 aged_flag 复活)
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    with patch.object(
        InnerThoughtDaemon, '_append_cold_start_record', return_value=None,
    ):
        return InnerThoughtDaemon(key_router=MagicMock())


def _mk_thought(thread_id, text, age_s=60):
    from jarvis_inner_thought_daemon import InnerThought
    ts = time.time() - age_s
    return InnerThought(
        id=thread_id, ts=ts,
        ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(ts)),
        category='C', thought=text, salience=0.9, actionable='none',
        evidence_link='none', thread_id=thread_id, continuity='new_topic',
    )


def _raw(thought_text, continuity='new_topic'):
    """构造一条 LLM raw 输出 (emergent 兼容: 不强制 CATEGORY)."""
    return (
        f"<CATEGORY>C</CATEGORY>\n"
        f"<THOUGHT>{thought_text}</THOUGHT>\n"
        f"<SALIENCE>0.9</SALIENCE>\n"
        f"<ACTIONABLE>none</ACTIONABLE>\n"
        f"<CONTINUITY>{continuity}</CONTINUITY>\n"
    )


_KR_A = ("Sir's keyrouter instability remains critical and is impacting "
         "workspace stability; I must prioritize addressing this hardware issue.")
_KR_B = ("The critical keyrouter instability persists and remains my primary "
         "concern impacting Sir's workspace stability right now.")
_UNRELATED = ("Sir mentioned wanting Italian food for dinner later tonight, "
              "I should remember his pasta preference for future suggestions.")


class TestF8ConfigHelper(unittest.TestCase):
    def setUp(self):
        from jarvis_inner_thought_daemon import _PACING_VOCAB_CACHE
        _PACING_VOCAB_CACHE['data'] = None
        _PACING_VOCAB_CACHE['mtime'] = 0.0
        _PACING_VOCAB_CACHE['checked_at'] = 0.0

    def test_F8_1_seed_default(self):
        import jarvis_inner_thought_daemon as m
        with patch.object(m, '_PACING_VOCAB_PATH',
                          '/nonexistent/_seed_only.json'):
            m._PACING_VOCAB_CACHE['data'] = None
            m._PACING_VOCAB_CACHE['mtime'] = 0.0
            m._PACING_VOCAB_CACHE['checked_at'] = 0.0
            enabled, thr, lookback, max_c = m._get_semantic_thread_merge_config()
        self.assertTrue(enabled)
        self.assertAlmostEqual(thr, 0.5)
        self.assertEqual(lookback, 60)
        self.assertEqual(max_c, 12)

    def test_F8_2_live_vocab_and_sanity(self):
        from jarvis_inner_thought_daemon import _get_semantic_thread_merge_config
        enabled, thr, lookback, max_c = _get_semantic_thread_merge_config()
        # live vocab 应有该段 (本 fix 已加)
        self.assertIsInstance(enabled, bool)
        self.assertGreaterEqual(thr, 0.0)
        self.assertLessEqual(thr, 1.0)
        self.assertGreaterEqual(lookback, 1)


class TestF8MergeBehavior(unittest.TestCase):
    def setUp(self):
        from jarvis_inner_thought_daemon import _PACING_VOCAB_CACHE
        _PACING_VOCAB_CACHE['data'] = None
        _PACING_VOCAB_CACHE['mtime'] = 0.0
        _PACING_VOCAB_CACHE['checked_at'] = 0.0
        self.daemon = _make_daemon()

    def _force_cfg(self, enabled=True, thr=0.5, lookback=60, max_c=12):
        import jarvis_inner_thought_daemon as m
        return patch.object(
            m, '_get_semantic_thread_merge_config',
            return_value=(enabled, thr, lookback, max_c),
        )

    def test_F8_3_merge_when_semantically_similar(self):
        """new_topic 但与近窗 keyrouter thread 高 jaccard → 归并."""
        existing = _mk_thought('thought_kr_origin', _KR_A, age_s=120)
        with self.daemon._lock:
            self.daemon._thoughts = [existing]
        with self._force_cfg(enabled=True, thr=0.3):
            t = self.daemon._parse_thought(_raw(_KR_B), 'active', 60)
        self.assertIsNotNone(t)
        self.assertEqual(t.thread_id, 'thought_kr_origin',
                         "F8_3 同义 thought 应归并入既有 keyrouter thread")
        self.assertEqual(t.continuity, 'semantic_merge')

    def test_F8_4_no_merge_when_unrelated(self):
        """new_topic + 语义不相似 → 新 thread."""
        existing = _mk_thought('thought_kr_origin', _KR_A, age_s=120)
        with self.daemon._lock:
            self.daemon._thoughts = [existing]
        with self._force_cfg(enabled=True, thr=0.5):
            t = self.daemon._parse_thought(_raw(_UNRELATED), 'active', 60)
        self.assertIsNotNone(t)
        self.assertNotEqual(t.thread_id, 'thought_kr_origin')
        self.assertEqual(t.continuity, 'new_topic')

    def test_F8_5_same_thread_llm_claim_not_overridden(self):
        """LLM 声明 same_thread → 不走语义归并 (LLM 主判优先)."""
        existing = _mk_thought('thought_kr_origin', _KR_A, age_s=120)
        with self.daemon._lock:
            self.daemon._thoughts = [existing]
        with self._force_cfg(enabled=True, thr=0.3):
            t = self.daemon._parse_thought(
                _raw(_KR_B, continuity='same_thread:thought_kr_origin'),
                'active', 60,
            )
        self.assertIsNotNone(t)
        self.assertEqual(t.thread_id, 'thought_kr_origin')
        self.assertEqual(t.continuity, 'same_thread')

    def test_F8_6_disabled_never_merges(self):
        """enabled=False → 关归并 (准则 7 Sir 可关), new_topic 永远新 thread."""
        existing = _mk_thought('thought_kr_origin', _KR_A, age_s=120)
        with self.daemon._lock:
            self.daemon._thoughts = [existing]
        with self._force_cfg(enabled=False, thr=0.3):
            t = self.daemon._parse_thought(_raw(_KR_B), 'active', 60)
        self.assertIsNotNone(t)
        self.assertNotEqual(t.thread_id, 'thought_kr_origin')
        self.assertEqual(t.continuity, 'new_topic')

    def test_F8_7_outside_lookback_not_merged(self):
        """近窗外 (lookback_min) 的相似 thread 不归并."""
        # existing thought 2h 前, lookback 仅 60min → 不在窗内
        existing = _mk_thought('thought_kr_origin', _KR_A, age_s=7200)
        with self.daemon._lock:
            self.daemon._thoughts = [existing]
        with self._force_cfg(enabled=True, thr=0.3, lookback=60):
            t = self.daemon._parse_thought(_raw(_KR_B), 'active', 60)
        self.assertIsNotNone(t)
        self.assertNotEqual(t.thread_id, 'thought_kr_origin',
                            "F8_7 窗口外 thread 不应被归并")

    def test_F8_8_merge_restores_topic_count(self):
        """端到端: 多条 new_topic keyrouter thought 归并后单 thread 计数破阈值."""
        with self.daemon._lock:
            self.daemon._thoughts = []
        # 模拟 emergent: 连续 5 条同义 keyrouter thought, 全声明 new_topic
        variants = [
            "keyrouter instability remains critical impacting workspace stability now",
            "the critical keyrouter instability persists impacting Sir workspace",
            "keyrouter health critical, I must prioritize this instability impacting stability",
            "critical keyrouter instability remains my primary concern for workspace stability",
            "Sir keyrouter instability is critical and impacting his workspace stability",
        ]
        with self._force_cfg(enabled=True, thr=0.3):
            for v in variants:
                t = self.daemon._parse_thought(_raw(v), 'active', 60)
                self.assertIsNotNone(t)
                with self.daemon._lock:
                    self.daemon._thoughts.append(t)
        # 归并后: 所有 5 条应共享同一 thread_id (第 1 条的)
        with self.daemon._lock:
            tids = set(t.thread_id for t in self.daemon._thoughts)
        self.assertEqual(len(tids), 1,
                         f"F8_8 5 条同义 keyrouter thought 应归并为 1 thread, got {len(tids)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
