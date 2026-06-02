# -*- coding: utf-8 -*-
"""[governor F9 / Sir 2026-06-02] 语义聚类反刍检测 — 治 B 类"反省自己反省".

真机 jarvis_20260602_184250 暴露 (dismiss Cursor 后):
  思考脑转 B 类 "I have been over-attending to hydration/cursor" 反复换词转
  (sal 0.95→0.99, kind=empty), 但全 same_thread, 单 thread 计数 < F3/F4 阈值 →
  let_go 抓不到。F8 只治 new_topic 发散; 这是 same_thread 内语义堆积。

F9 治本: topic_distribution 除 count-by-thread_id 外, 加跨 thread 的 jaccard
语义聚类 — 某语义簇 count >= 阈值 → 标 aged, LLM 看 [semantic clusters] →
自决 let_go (对簇内任一 thread)。准则6 python 只 count, LLM 决。

覆盖:
  T1  跨 thread 同语义 thought → semantic_clusters 聚出 1 簇 count=N
  T2  簇 count >= aged 阈值 → aged_flag=True
  T3  语义不同的 thought → 不聚成同簇
  T4  单条 thought 不算簇 (count>=2 才暴露)
  T5  prompt 渲染含 [semantic clusters] 段
  T6  disabled (semantic_thread_merge.enabled=False) → 不聚类 (准则7)
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


def _mk(thread_id, text, age_s=60):
    from jarvis_inner_thought_daemon import InnerThought
    ts = time.time() - age_s
    return InnerThought(
        id=thread_id, ts=ts,
        ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(ts)),
        category='B', thought=text, salience=0.95, actionable='none',
        evidence_link='none', thread_id=thread_id, continuity='same_thread',
    )


# B 类反省反刍变体 (真机标本: over-attending) — 同语义, 不同 thread_id
_RUM_SPECS = [
    ("thr_b1", "I have been over-attending to Sir's hydration and cursor subscription."),
    ("thr_b2", "I have been persistently over-attending to Sir's hydration and cursor."),
    ("thr_b3", "I am persistently over-attending to Sir's cursor and hydration concerns."),
    ("thr_b4", "I have been overly persistent over-attending to hydration and cursor."),
    ("thr_b5", "I keep over-attending to Sir's hydration and his cursor subscription."),
    ("thr_b6", "I have been over-attending to Sir's cursor and hydration repeatedly."),
]
_DIFFERENT = ("thr_x", "Sir mentioned wanting pasta for dinner; I should note his preference.")


def _rum_thoughts():
    return [_mk(tid, txt) for tid, txt in _RUM_SPECS]


class TestF9SemanticCluster(unittest.TestCase):
    def setUp(self):
        from jarvis_inner_thought_daemon import _PACING_VOCAB_CACHE
        _PACING_VOCAB_CACHE['data'] = None
        _PACING_VOCAB_CACHE['mtime'] = 0.0
        _PACING_VOCAB_CACHE['checked_at'] = 0.0
        self.daemon = _make_daemon()

    def _collect(self, thoughts, sm_cfg=None, tr_max_occ=6):
        import jarvis_inner_thought_daemon as m
        with self.daemon._lock:
            self.daemon._thoughts = list(thoughts)
        patches = []
        if sm_cfg is not None:
            patches.append(patch.object(
                m, '_get_semantic_thread_merge_config', return_value=sm_cfg))
        # 固定 topic_repeat aged 阈值 + topic_distribution config (隔离 live vocab)
        patches.append(patch.object(
            m, '_get_topic_repeat_config', return_value=(tr_max_occ, 60, 30)))
        patches.append(patch.object(
            m, '_get_topic_distribution_config', return_value=(60, 6, 10)))
        for p in patches:
            p.start()
        try:
            ev = self.daemon._collect_evidence(sir_state='active', within_seconds=3600)
        finally:
            for p in patches:
                p.stop()
        return ev

    def test_t1_cross_thread_same_meaning_clusters(self):
        ev = self._collect(_rum_thoughts(), sm_cfg=(True, 0.4, 60, 12))
        clusters = ev.get('topic_distribution', {}).get('semantic_clusters', [])
        self.assertTrue(clusters, "F9: 跨 thread 同语义应聚出簇")
        top = clusters[0]
        self.assertGreaterEqual(top['count'], 4,
                                f"F9: over-attending 簇应聚 >=4 条, got {top['count']}")
        self.assertGreaterEqual(top['n_threads'], 4,
                                "F9: 簇应跨多个 thread_id")

    def test_t2_cluster_aged_flag_when_over_threshold(self):
        # 6 条 >= aged 阈值 6 → aged_flag
        ev = self._collect(_rum_thoughts(), sm_cfg=(True, 0.4, 60, 12), tr_max_occ=6)
        clusters = ev.get('topic_distribution', {}).get('semantic_clusters', [])
        self.assertTrue(any(c['aged_flag'] for c in clusters),
                        "F9: 簇 count>=6 应 aged_flag=True")

    def test_t3_different_meaning_not_clustered(self):
        mixed = _rum_thoughts()[:2] + [_mk(*_DIFFERENT)]
        ev = self._collect(mixed, sm_cfg=(True, 0.4, 60, 12))
        clusters = ev.get('topic_distribution', {}).get('semantic_clusters', [])
        # pasta 那条不应混进 over-attending 簇
        for c in clusters:
            self.assertNotIn('pasta', c['sample'].lower(),
                             "F9: 语义不同不应聚同簇")

    def test_t4_single_thought_not_a_cluster(self):
        ev = self._collect([_mk(*_DIFFERENT)], sm_cfg=(True, 0.4, 60, 12))
        clusters = ev.get('topic_distribution', {}).get('semantic_clusters', [])
        self.assertEqual(clusters, [], "F9: 单条 thought 不算反刍簇 (count>=2 才暴露)")

    def test_t5_prompt_renders_semantic_clusters(self):
        import jarvis_inner_thought_daemon as m
        thoughts = _rum_thoughts()
        with self.daemon._lock:
            self.daemon._thoughts = list(thoughts)
        with patch.object(m, '_get_semantic_thread_merge_config',
                          return_value=(True, 0.4, 60, 12)), \
             patch.object(m, '_get_topic_repeat_config',
                          return_value=(6, 60, 30)), \
             patch.object(m, '_get_topic_distribution_config',
                          return_value=(60, 6, 10)):
            ev = self.daemon._collect_evidence(sir_state='active', within_seconds=3600)
            # sanity: cluster 数据在 ev 里
            self.assertTrue(
                ev.get('topic_distribution', {}).get('semantic_clusters'),
                "F9 前置: ev 应含 semantic_clusters")
            sys_p, user_p = self.daemon._build_prompt('active', ev)
        combined = sys_p + "\n" + user_p
        self.assertIn('semantic clusters', combined,
                      "F9: prompt 应渲染 [semantic clusters] 段")

    def test_t6_disabled_no_clusters(self):
        ev = self._collect(_rum_thoughts(), sm_cfg=(False, 0.4, 60, 12))
        clusters = ev.get('topic_distribution', {}).get('semantic_clusters', [])
        self.assertEqual(clusters, [],
                         "F9: semantic_thread_merge.enabled=False → 不聚类 (准则7)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
