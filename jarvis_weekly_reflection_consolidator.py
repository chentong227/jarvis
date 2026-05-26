# -*- coding: utf-8 -*-
"""[WRC / Sir 2026-05-25 23:52 真问 "3 也做"] WeeklyReflectionConsolidator.

Sir 真意 (合并自之前对话):
  "明朝 03:xx daily reflection 自动 calibrate" + "B 类反思要不要存额外记忆" +
  "通过每日的思考迭代准确性" +
  "Step 3 周反思 → sir_profile.work_rhythms 演化"

灵魂工程 Layer 4.5 — 周反思合并器 (sit between InnerThought + LongTermMemory).

每周日 03:xx fire 一次 (low traffic 时段):
  1. 从 Hippocampus search 'self_reflection' (7d 内, top 10 by similarity)
  2. LLM (Flash-Lite, caller='inner_thought' LOW priority) 提 recurring pattern:
     "本周贾维斯 N 次反思 X 模式, 建议 long-term 调整 Y"
  3. propose 到 review queue (memory_pool/long_term_insights.jsonl)
  4. publish SWM 'weekly_insight_proposed' (salience 0.9 主脑下轮真看到)
  5. Sir 在 dashboard 看 + 一键 accept / reject

设计 (准则 6 evidence + 7 Sir 元否决 + 8 优雅):
  - 不直接 mutate sir_profile (Sir 元否决)
  - 只 propose, Sir 真决定升级
  - 失败/无 pattern → silent, 不刷屏

成本: 每周 1 次 LLM call ≈ $0.001/周 ≈ $0.004/月

参考:
  jarvis_inner_thought_daemon.py (daemon 模式参考)
  jarvis_auto_arbiter.py (Daily reflection 03:xx 模式参考)
  jarvis_hippocampus.py (Hippocampus.search_memory)
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, asdict
from typing import Any, List, Optional


@dataclass
class WeeklyInsight:
    """周反思合并后的长期 insight (待 Sir 升级到 sir_profile)."""
    id: str
    ts: float
    ts_iso: str
    week_range_iso: str           # "2026-05-19 → 2026-05-25"
    pattern_summary: str          # LLM 提的 pattern (≤200 char)
    suggested_action: str         # 建议升级 (e.g. 改 sir_profile.work_rhythms)
    evidence_count: int           # 7d 内 self_reflection event 数
    evidence_excerpts: List[str]  # top 3 reflection excerpt (≤80 char each)
    confidence: float             # 0.0-1.0
    state: str = 'review'         # 'review' / 'accepted' / 'rejected'
    sir_decision_at: float = 0.0
    sir_decision_reason: str = ''
    # 🆕 [Sir 2026-05-27 00:30 Phase 2B 后半] insight 类型区分两条 reflector path:
    #   'self_reflection_pattern' (老) — 从 Hippocampus self_reflection 提 pattern
    #   'inner_thought_vocab_tune' (新) — 从 inner_thoughts.jsonl 7d outcome 统计
    #                                     propose 调 surface_to_sir_vocab 阈值
    # 准则 7: Sir 元否决, accept 仍不 mutate vocab, Sir 手工改 JSON 升级
    insight_type: str = 'self_reflection_pattern'
    # 🆕 [Sir 2026-05-27 00:30] vocab_tune 专用: 具体改的 vocab field + old/new value
    # (self_reflection_pattern 时 = '', 老 record load 兼容)
    target_vocab_path: str = ''   # e.g. 'memory_pool/surface_to_sir_vocab.json'
    target_field: str = ''        # e.g. 'salience_threshold'
    proposed_old_value: Any = None
    proposed_new_value: Any = None


class WeeklyReflectionConsolidator:
    """Weekly consolidator. 周日 03:xx fire 一次."""

    PERSIST_PATH = 'memory_pool/long_term_insights.jsonl'

    # tick
    CHECK_INTERVAL_S = 600     # 10min 检查一次 hour/weekday
    STARTUP_DELAY_S = 120      # 2min 等系统稳定
    FIRE_WEEKDAY = 6           # Sunday (Python: Mon=0, Sun=6)
    FIRE_HOUR = 3              # 03:xx
    # 同一周不重 fire (用 ISO year-week key 防重)

    # evidence collection
    SEARCH_QUERY = 'self_reflection'  # 给 Hippocampus search
    SEARCH_TOP_K = 10
    SEARCH_TIME_LIMIT_DAYS = 7

    # 最少 evidence 阈值 (不够不 propose, 准则 6 evidence-driven)
    MIN_EVIDENCE_COUNT = 3

    def __init__(self, key_router=None, central_nerve=None):
        self.key_router = key_router
        self.nerve = central_nerve
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._insights: List[WeeklyInsight] = []
        self._last_fired_week_key = ''  # ISO year-week e.g. '2026-W21'
        self._load_persist()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._daemon_loop,
            name='WeeklyReflectionConsolidator',
            daemon=True,
        )
        self._thread.start()
        self._bg_log(
            "🪞 [WeeklyReflectionConsolidator] daemon started — 灵魂工程 "
            "Layer 4.5: 周日 03:xx 提 7d self_reflection pattern propose Sir"
        )

    def stop(self) -> None:
        self._stop.set()

    def _daemon_loop(self) -> None:
        self._stop.wait(timeout=self.STARTUP_DELAY_S)
        if self._stop.is_set():
            return
        while not self._stop.is_set():
            try:
                self._maybe_fire()
            except Exception as e:
                self._bg_log(
                    f"⚠️ [WeeklyConsolidator] tick exception: {e}"
                )
            self._stop.wait(timeout=self.CHECK_INTERVAL_S)

    def _maybe_fire(self) -> None:
        now_local = time.localtime()
        # 仅 Sunday 03:xx fire
        if now_local.tm_wday != self.FIRE_WEEKDAY:
            return
        if now_local.tm_hour != self.FIRE_HOUR:
            return
        # 防同周重 fire
        iso_year, iso_week, _ = time.strftime('%G %V %u',
                                                 now_local).split()
        week_key = f'{iso_year}-W{iso_week}'
        if week_key == self._last_fired_week_key:
            return
        self._last_fired_week_key = week_key
        # 🆕 [Sir 2026-05-27 00:30 Phase 2B 后半] 同周 fire 两条 reflector path:
        #   1. self_reflection_pattern (老) — Hippocampus 7d self_reflection
        #   2. inner_thought_vocab_tune (新) — inner_thoughts.jsonl 7d outcome
        # 准则 8 优雅: 并行 fire, 任一 fail 不阻另一条 (try/except each).
        try:
            self._do_weekly_consolidation(week_key)
        except Exception as e:
            self._bg_log(
                f"⚠️ [WeeklyConsolidator] self_reflection path fail: {e}"
            )
        try:
            self._do_inner_thought_outcome_consolidation(week_key)
        except Exception as e:
            self._bg_log(
                f"⚠️ [WeeklyConsolidator] thought_outcome path fail: {e}"
            )

    def _do_weekly_consolidation(self, week_key: str) -> None:
        # 1. evidence: 从 Hippocampus search 7d self_reflection
        evidence = self._collect_reflection_evidence()
        if len(evidence) < self.MIN_EVIDENCE_COUNT:
            self._bg_log(
                f"🪞 [WeeklyConsolidator] {week_key}: only "
                f"{len(evidence)} self_reflection events in 7d "
                f"(min {self.MIN_EVIDENCE_COUNT}), skip"
            )
            return

        # 2. LLM 提 pattern
        pattern, suggested_action, confidence = self._llm_extract_pattern(
            evidence
        )
        if not pattern:
            self._bg_log(
                f"🪞 [WeeklyConsolidator] {week_key}: LLM 没提出 pattern, skip"
            )
            return

        # 3. 建 WeeklyInsight
        now = time.time()
        # week range
        end_d = time.strftime('%Y-%m-%d', time.localtime(now))
        start_d = time.strftime(
            '%Y-%m-%d', time.localtime(now - 7 * 86400)
        )
        insight = WeeklyInsight(
            id=f'wi_{time.strftime("%Y%m%d_%H%M%S")}_'
                f'{int(now * 1000) % 10000:04x}',
            ts=now,
            ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S',
                                   time.localtime(now)),
            week_range_iso=f'{start_d} → {end_d}',
            pattern_summary=pattern[:200],
            suggested_action=suggested_action[:300],
            evidence_count=len(evidence),
            evidence_excerpts=[e['summary'][:80]
                                 for e in evidence[:3]],
            confidence=confidence,
        )

        # 4. persist + publish SWM
        with self._lock:
            self._insights.append(insight)
        self._persist_insight(insight)
        self._publish_swm(insight)

        self._bg_log(
            f"🪞 [WeeklyConsolidator] {week_key}: proposed insight "
            f"'{pattern[:80]}' (conf {confidence:.2f}, "
            f"evidence={len(evidence)})"
        )

    # ==========================================================
    # 🆕 [Sir 2026-05-27 00:30 Phase 2B 后半] thought_outcome 反思路径
    # =================================================================
    # 真痛 (design doc §2.B): thought 现已经写 outcome 字段 (M5 OutcomeTracker),
    # 但**没人看**. WRC 7d 反思 → LLM propose surface_to_sir_vocab 阈值调.
    # 准则 6 数据强耦合: 读 jsonl, publish review queue.
    # 准则 7 Sir 元否决: propose 不 mutate vocab, Sir 手工改.
    # 准则 8 优雅: 复用 long_term_insights.jsonl + WeeklyInsight schema,
    #            加 insight_type='inner_thought_vocab_tune' 区分.
    # =================================================================

    INNER_THOUGHT_PERSIST_PATH = 'memory_pool/inner_thoughts.jsonl'
    SURFACE_VOCAB_PATH = 'memory_pool/surface_to_sir_vocab.json'
    # 真反思最少 thought 数 (低于不 propose, 准则 6 evidence-driven)
    MIN_THOUGHT_COUNT_FOR_TUNE = 20
    # 至少多少 outcome != pending 才有信号 (low signal 噪音不调)
    MIN_OUTCOME_RESOLVED_RATE = 0.3

    def _do_inner_thought_outcome_consolidation(self, week_key: str) -> None:
        """周反思 inner_thoughts.jsonl 7d outcome → propose vocab tune."""
        stats = self._collect_thought_outcome_stats()
        n_total = stats.get('total', 0)
        n_resolved = (stats.get('outcomes', {}).get('sir_engaged', 0) +
                      stats.get('outcomes', {}).get('sir_silenced', 0) +
                      stats.get('outcomes', {}).get('sir_rejected', 0))
        if n_total < self.MIN_THOUGHT_COUNT_FOR_TUNE:
            self._bg_log(
                f"🪞 [WeeklyConsolidator/thought_outcome] {week_key}: "
                f"only {n_total} thoughts in 7d "
                f"(min {self.MIN_THOUGHT_COUNT_FOR_TUNE}), skip"
            )
            return
        resolved_rate = n_resolved / float(n_total) if n_total > 0 else 0.0
        if resolved_rate < self.MIN_OUTCOME_RESOLVED_RATE:
            self._bg_log(
                f"🪞 [WeeklyConsolidator/thought_outcome] {week_key}: "
                f"only {resolved_rate * 100:.0f}% outcomes resolved "
                f"(min {self.MIN_OUTCOME_RESOLVED_RATE * 100:.0f}%), "
                f"signal too low to tune, skip"
            )
            return
        # LLM propose tune
        cur_vocab = self._load_surface_vocab()
        tune = self._llm_propose_vocab_tune(stats, cur_vocab)
        if not tune or not tune.get('target_field'):
            self._bg_log(
                f"🪞 [WeeklyConsolidator/thought_outcome] {week_key}: "
                f"LLM 没 propose 有效 vocab tune, skip"
            )
            return
        # 建 WeeklyInsight (type=vocab_tune)
        now = time.time()
        end_d = time.strftime('%Y-%m-%d', time.localtime(now))
        start_d = time.strftime(
            '%Y-%m-%d', time.localtime(now - 7 * 86400)
        )
        # 准备 evidence excerpts (per-cat 简要 stats)
        ex = []
        for cat in 'ABCDE':
            cs = stats.get('by_category', {}).get(cat, {})
            if cs.get('total', 0) == 0:
                continue
            ex.append(
                f"{cat}: {cs['total']} thoughts, "
                f"engaged={cs.get('sir_engaged', 0)} "
                f"silenced={cs.get('sir_silenced', 0)} "
                f"rejected={cs.get('sir_rejected', 0)}"
            )
        insight = WeeklyInsight(
            id=f'wi_voc_{time.strftime("%Y%m%d_%H%M%S")}_'
                f'{int(now * 1000) % 10000:04x}',
            ts=now,
            ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S',
                                   time.localtime(now)),
            week_range_iso=f'{start_d} → {end_d}',
            pattern_summary=tune.get('pattern_summary', '')[:200],
            suggested_action=tune.get('suggested_action', '')[:300],
            evidence_count=n_total,
            evidence_excerpts=ex[:3],
            confidence=tune.get('confidence', 0.0),
            insight_type='inner_thought_vocab_tune',
            target_vocab_path=self.SURFACE_VOCAB_PATH,
            target_field=tune.get('target_field', ''),
            proposed_old_value=tune.get('old_value'),
            proposed_new_value=tune.get('new_value'),
        )
        with self._lock:
            self._insights.append(insight)
        self._persist_insight(insight)
        self._publish_swm(insight)
        self._bg_log(
            f"🪞 [WeeklyConsolidator/thought_outcome] {week_key}: "
            f"proposed vocab tune {tune.get('target_field')}: "
            f"{tune.get('old_value')} → {tune.get('new_value')} "
            f"(conf {insight.confidence:.2f}, "
            f"based on {n_total} thoughts, {n_resolved} resolved)"
        )

    def _collect_thought_outcome_stats(self) -> dict:
        """从 inner_thoughts.jsonl 读 7d thought, 统计 per-cat outcome."""
        path = self.INNER_THOUGHT_PERSIST_PATH
        if not os.path.exists(path):
            return {'total': 0}
        cutoff = time.time() - 7 * 86400
        outcomes = {'pending': 0, 'sir_engaged': 0,
                    'sir_silenced': 0, 'sir_rejected': 0}
        by_category = {}  # cat → {total, sir_engaged, sir_silenced, sir_rejected, pending, avg_sal}
        total = 0
        sal_sum = 0.0
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        t = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if float(t.get('ts', 0)) < cutoff:
                        continue
                    total += 1
                    sal_sum += float(t.get('salience', 0) or 0)
                    oc = t.get('outcome', 'pending')
                    outcomes[oc] = outcomes.get(oc, 0) + 1
                    cat = t.get('category', '?')
                    if cat not in by_category:
                        by_category[cat] = {
                            'total': 0, 'pending': 0,
                            'sir_engaged': 0, 'sir_silenced': 0,
                            'sir_rejected': 0, 'sal_sum': 0.0,
                        }
                    by_category[cat]['total'] += 1
                    by_category[cat][oc] = by_category[cat].get(oc, 0) + 1
                    by_category[cat]['sal_sum'] += float(
                        t.get('salience', 0) or 0
                    )
        except Exception as e:
            self._bg_log(
                f"⚠️ [WeeklyConsolidator/thought_outcome] read fail: {e}"
            )
            return {'total': 0}
        # avg_sal per cat
        for cat, cs in by_category.items():
            if cs['total'] > 0:
                cs['avg_sal'] = cs['sal_sum'] / cs['total']
            else:
                cs['avg_sal'] = 0.0
        return {
            'total': total,
            'avg_salience': sal_sum / total if total > 0 else 0.0,
            'outcomes': outcomes,
            'by_category': by_category,
        }

    def _load_surface_vocab(self) -> dict:
        """读 surface_to_sir_vocab.json (fail-safe)."""
        try:
            if not os.path.exists(self.SURFACE_VOCAB_PATH):
                return {}
            with open(self.SURFACE_VOCAB_PATH, 'r', encoding='utf-8') as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _llm_propose_vocab_tune(self, stats: dict, cur_vocab: dict
                                  ) -> dict:
        """LLM 看 outcome stats + 现 vocab → propose 1 个 tune (JSON dict).

        Returns dict: {
          'pattern_summary': str,  # 1-2 sentence 描述真现状
          'suggested_action': str, # 具体建议改什么
          'target_field': str,     # vocab key e.g. 'salience_threshold'
          'old_value': Any,
          'new_value': Any,
          'confidence': float,
        }
        空 dict (or 没 target_field) = 没 propose.
        """
        try:
            from jarvis_llm_reflector import LlmReflector
            from jarvis_key_router import KeyRouter
            reflector = LlmReflector(key_router=self.key_router)
        except Exception:
            return {}
        # 准备 stats summary (给 LLM 看)
        outcomes = stats.get('outcomes', {})
        total = stats.get('total', 0)
        by_cat = stats.get('by_category', {})
        cur_thr = cur_vocab.get('salience_threshold', 0.7)
        cur_max_h = cur_vocab.get('max_per_hour', 6)
        cur_cd_g = cur_vocab.get('cooldown_global_s', 120)
        # build stats block
        stats_lines = [
            f"[OUTCOME STATS — 7d, {total} thoughts]",
            f"  pending: {outcomes.get('pending', 0)}",
            f"  sir_engaged: {outcomes.get('sir_engaged', 0)}",
            f"  sir_silenced: {outcomes.get('sir_silenced', 0)}",
            f"  sir_rejected: {outcomes.get('sir_rejected', 0)}",
            "",
            "[PER-CATEGORY BREAKDOWN]",
        ]
        for cat in 'ABCDE':
            cs = by_cat.get(cat, {})
            if cs.get('total', 0) == 0:
                continue
            n = cs['total']
            eng = cs.get('sir_engaged', 0)
            sil = cs.get('sir_silenced', 0)
            rej = cs.get('sir_rejected', 0)
            avg_s = cs.get('avg_sal', 0.0)
            eng_rate = eng / float(n) if n > 0 else 0.0
            stats_lines.append(
                f"  {cat}: n={n} avg_sal={avg_s:.2f} "
                f"engaged={eng}({eng_rate*100:.0f}%) "
                f"silenced={sil} rejected={rej}"
            )
        stats_lines.append("")
        stats_lines.append(
            f"[CURRENT surface_to_sir_vocab]"
        )
        stats_lines.append(
            f"  salience_threshold: {cur_thr} "
            f"(thought must >= this to surface to Sir)"
        )
        stats_lines.append(
            f"  cooldown_global_s: {cur_cd_g} (anti-burst)"
        )
        stats_lines.append(
            f"  max_per_hour: {cur_max_h} (cap per hour)"
        )

        system = (
            "You are J.A.R.V.I.S., weekly reviewing your own inner-thought "
            "outcomes vs Sir's reactions, to propose a single tweak to your "
            "surface_to_sir vocabulary (your own threshold for speaking up).\n\n"
            "Read the stats and decide if ONE field needs adjustment. "
            "Examples of good logic:\n"
            "  - If engaged rate >= 50% across categories → Sir likes your "
            "thoughts, LOWER salience_threshold (more chatter welcomed).\n"
            "  - If silenced rate >= 60% → Sir tolerates but ignores, RAISE "
            "salience_threshold (be pickier).\n"
            "  - If rejected rate >= 30% → Sir actively dislikes, RAISE "
            "threshold significantly AND propose cooldown extension.\n"
            "  - If most outcomes still 'pending' (Sir hasn't reacted) → "
            "wait, output (no_tune).\n\n"
            "Output FORMAT (strict, 6 tags required):\n"
            "<PATTERN_SUMMARY>1-2 sentences describing the dominant outcome "
            "pattern observed (≤200 char).</PATTERN_SUMMARY>\n"
            "<SUGGESTED_ACTION>1-2 sentences explaining what to adjust and "
            "why (≤300 char). Be specific about WHICH field + WHY.</SUGGESTED_ACTION>\n"
            "<TARGET_FIELD>one of: salience_threshold | max_per_hour | "
            "cooldown_global_s | (no_tune)</TARGET_FIELD>\n"
            "<OLD_VALUE>current value (number)</OLD_VALUE>\n"
            "<NEW_VALUE>proposed new value (number). For salience_threshold "
            "stay in [0.5, 0.95]. For max_per_hour stay in [2, 20]. For "
            "cooldown_global_s stay in [60, 600].</NEW_VALUE>\n"
            "<CONFIDENCE>0.0-1.0 — how clear is the signal. ≥0.7 only if "
            "the dominant pattern is consistent across 3+ categories.</CONFIDENCE>\n\n"
            "Rules (准则 5 + 6 + 7 + 8):\n"
            "  - DO NOT invent. Only base on the stats shown.\n"
            "  - Propose at most ONE field change (Sir wants minimal "
            "perturbation per week).\n"
            "  - If signal is weak/ambiguous → output TARGET_FIELD=(no_tune) "
            "and CONFIDENCE=0.0.\n"
            "  - Sir has veto: even if you propose, Sir manually edits the "
            "JSON. You only suggest."
        )
        user_prompt = '\n'.join(stats_lines)
        try:
            res = reflector.reflect(
                model='flash_lite',
                system_prompt=system,
                user_prompt=user_prompt,
                force=True,
                caller=getattr(KeyRouter, 'CALLER_INNER_THOUGHT',
                                 'inner_thought'),
            )
            if not res.get('success'):
                return {}
            raw = res.get('raw_text', '') or ''
        except Exception as e:
            self._bg_log(
                f"⚠️ [WeeklyConsolidator/thought_outcome] LLM fail: {e}"
            )
            return {}
        # parse
        def _g(tag: str) -> str:
            m = re.search(
                rf'<{tag}>(.*?)</{tag}>', raw, re.DOTALL | re.IGNORECASE
            )
            return m.group(1).strip() if m else ''
        target = _g('TARGET_FIELD').lower()
        if not target or target == 'no_tune' or target == '(no_tune)':
            return {}
        if target not in (
            'salience_threshold', 'max_per_hour', 'cooldown_global_s'
        ):
            return {}
        try:
            old_v_str = _g('OLD_VALUE')
            new_v_str = _g('NEW_VALUE')
            conf_str = _g('CONFIDENCE')
            old_v = float(old_v_str) if old_v_str else None
            new_v = float(new_v_str) if new_v_str else None
            conf = max(0.0, min(1.0, float(conf_str))) if conf_str else 0.0
            # 整数 fields
            if target in ('max_per_hour', 'cooldown_global_s'):
                if new_v is not None:
                    new_v = int(round(new_v))
                if old_v is not None:
                    old_v = int(round(old_v))
            # clamp 安全范围
            if target == 'salience_threshold' and new_v is not None:
                new_v = max(0.5, min(0.95, new_v))
            elif target == 'max_per_hour' and new_v is not None:
                new_v = max(2, min(20, int(new_v)))
            elif target == 'cooldown_global_s' and new_v is not None:
                new_v = max(60, min(600, int(new_v)))
        except (ValueError, TypeError):
            return {}
        if conf < 0.4 or old_v == new_v or new_v is None:
            return {}
        return {
            'pattern_summary': _g('PATTERN_SUMMARY'),
            'suggested_action': _g('SUGGESTED_ACTION'),
            'target_field': target,
            'old_value': old_v,
            'new_value': new_v,
            'confidence': conf,
        }

    def _collect_reflection_evidence(self) -> List[dict]:
        """从 Hippocampus search self_reflection events (7d)."""
        if not self.nerve:
            return []
        hc = getattr(self.nerve, 'hippocampus', None)
        if hc is None or not hasattr(hc, 'search_memory'):
            return []
        try:
            time_limit = time.time() - self.SEARCH_TIME_LIMIT_DAYS * 86400
            results = hc.search_memory(
                query=self.SEARCH_QUERY,
                top_k=self.SEARCH_TOP_K,
                time_limit=time_limit,
                min_similarity=0.35,  # 中等阈值
            )
            return results or []
        except Exception as e:
            self._bg_log(f"⚠️ [WeeklyConsolidator] hippo search fail: {e}")
            return []

    def _llm_extract_pattern(self, evidence: List[dict]
                                ) -> tuple:
        """LLM (Flash-Lite) 看 evidence 提 pattern + action.

        Returns: (pattern, suggested_action, confidence)
        """
        if not evidence:
            return '', '', 0.0
        try:
            from jarvis_llm_reflector import LlmReflector
            from jarvis_key_router import KeyRouter
            reflector = LlmReflector(key_router=self.key_router)
        except Exception:
            return '', '', 0.0

        system = (
            "You are J.A.R.V.I.S., weekly consolidating your own "
            "self-reflections to extract recurring patterns. This becomes "
            "long-term self-knowledge proposed to Sir for approval.\n\n"
            "Output FORMAT (strict, 3 tags all required):\n"
            "<PATTERN>1-2 sentences naming the recurring pattern across "
            "the reflections below (≤200 char). e.g. 'I keep over-emphasizing "
            "Sir's stated priority projects in ambiguous queries'.</PATTERN>\n"
            "<SUGGESTED_ACTION>1-2 sentences naming what to add/change in "
            "long-term store (sir_profile / unspoken_protocols / etc) to "
            "embody this learning (≤300 char). e.g. 'Add protocol: ambiguous "
            "user queries (≤10 char like 你确定吗) → reply minimal, do not "
            "introduce active_projects context'.</SUGGESTED_ACTION>\n"
            "<CONFIDENCE>0.0-1.0 — how clear is this recurring pattern. "
            "0.8+ only when 3+ reflections clearly share theme.</CONFIDENCE>\n\n"
            "Rules (准则 5 + 6 + 8):\n"
            "  - DO NOT invent patterns not supported by evidence.\n"
            "  - If reflections are unrelated/sparse → output PATTERN=(no clear pattern) "
            "and CONFIDENCE=0.0. Sir 看到也无 action.\n"
            "  - Suggested action should be specific (which long-term field), "
            "not vague ('be more careful').\n"
            "  - Brief, factual, not flatter Sir."
        )

        user_lines = [
            f"[SELF-REFLECTIONS IN LAST 7 DAYS ({len(evidence)} events)]"
        ]
        for i, e in enumerate(evidence[:8]):
            user_lines.append(
                f"  {i+1}. {e.get('summary', '')[:200]}"
            )
        user_lines.append("")
        user_lines.append(
            "Now extract ONE recurring pattern (3 tags strict)."
        )
        user_prompt = '\n'.join(user_lines)

        try:
            res = reflector.reflect(
                model='flash_lite',
                system_prompt=system,
                user_prompt=user_prompt,
                force=True,
                caller=getattr(KeyRouter, 'CALLER_INNER_THOUGHT',
                                 'inner_thought'),
            )
            if not res.get('success'):
                return '', '', 0.0
            raw = res.get('raw_text', '') or ''
        except Exception as e:
            self._bg_log(
                f"⚠️ [WeeklyConsolidator] LLM call fail: {e}"
            )
            return '', '', 0.0

        pat_m = re.search(r'<PATTERN>(.*?)</PATTERN>', raw, re.DOTALL)
        act_m = re.search(
            r'<SUGGESTED_ACTION>(.*?)</SUGGESTED_ACTION>', raw, re.DOTALL
        )
        conf_m = re.search(r'<CONFIDENCE>\s*([0-9.]+)\s*</CONFIDENCE>', raw)
        pattern = pat_m.group(1).strip() if pat_m else ''
        action = act_m.group(1).strip() if act_m else ''
        try:
            conf = max(0.0, min(1.0, float(conf_m.group(1)))) \
                if conf_m else 0.0
        except (ValueError, TypeError):
            conf = 0.0
        # 'no clear pattern' filter
        if 'no clear pattern' in pattern.lower() or conf < 0.4:
            return '', '', 0.0
        return pattern, action, conf

    # ----------------------------------------------------------
    # Sir 操作 API
    # ----------------------------------------------------------
    def sir_accept(self, insight_id: str, reason: str = '') -> bool:
        """Sir accept 一条 insight → state=accepted (后续手工升级 sir_profile)."""
        return self._sir_decide(insight_id, 'accepted', reason)

    def sir_reject(self, insight_id: str, reason: str = '') -> bool:
        return self._sir_decide(insight_id, 'rejected', reason)

    def _sir_decide(self, insight_id: str, new_state: str,
                      reason: str) -> bool:
        with self._lock:
            for ins in self._insights:
                if ins.id == insight_id:
                    ins.state = new_state
                    ins.sir_decision_at = time.time()
                    ins.sir_decision_reason = reason[:200]
                    self._persist_insight(ins)
                    return True
        return False

    # ----------------------------------------------------------
    # Persistence
    # ----------------------------------------------------------
    def _persist_insight(self, ins: WeeklyInsight) -> None:
        try:
            os.makedirs(os.path.dirname(self.PERSIST_PATH), exist_ok=True)
            with open(self.PERSIST_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps(asdict(ins), ensure_ascii=False) + '\n')
            try:
                from jarvis_jsonl_rotator import maybe_rotate
                maybe_rotate(self.PERSIST_PATH, check_every_n_writes=10)
            except Exception:
                pass
        except Exception as e:
            self._bg_log(f"⚠️ [WeeklyConsolidator] persist fail: {e}")

    def _load_persist(self) -> None:
        if not os.path.exists(self.PERSIST_PATH):
            return
        try:
            cutoff = time.time() - 90 * 86400  # 90 天历史
            latest_by_id = {}
            with open(self.PERSIST_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        if d.get('ts', 0) < cutoff:
                            continue
                        latest_by_id[d.get('id')] = d
                    except (json.JSONDecodeError, ValueError):
                        continue
            for d in latest_by_id.values():
                try:
                    self._insights.append(WeeklyInsight(**d))
                except (TypeError, KeyError):
                    continue
        except Exception as e:
            self._bg_log(f"⚠️ [WeeklyConsolidator] load fail: {e}")

    def _publish_swm(self, ins: WeeklyInsight) -> None:
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            bus.publish(
                etype='weekly_insight_proposed',
                description=(
                    f"[Weekly self-insight] {ins.pattern_summary[:120]} "
                    f"(conf {ins.confidence:.2f}, evidence {ins.evidence_count})"
                ),
                source='weekly_reflection_consolidator',
                salience=max(0.85, ins.confidence),
                metadata={
                    'insight_id': ins.id,
                    'pattern': ins.pattern_summary[:200],
                    'suggested_action': ins.suggested_action[:300],
                    'evidence_count': ins.evidence_count,
                    'week_range': ins.week_range_iso,
                },
                ttl=86400.0 * 14,  # 14 天 (跨周保留, 让 Sir 有时间真看)
            )
        except Exception:
            pass

    # ----------------------------------------------------------
    # Stats (dashboard / CLI)
    # ----------------------------------------------------------
    def list_insights(self, state: Optional[str] = None) -> List[dict]:
        with self._lock:
            out = []
            for ins in sorted(self._insights, key=lambda i: -i.ts):
                if state and ins.state != state:
                    continue
                out.append(asdict(ins))
            return out

    def get_stats(self) -> dict:
        with self._lock:
            total = len(self._insights)
            by_state = {}
            for ins in self._insights:
                by_state[ins.state] = by_state.get(ins.state, 0) + 1
            return {
                'total_insights': total,
                'by_state': by_state,
                'last_fired_week_key': self._last_fired_week_key,
            }

    # ----------------------------------------------------------
    def _bg_log(self, msg: str) -> None:
        try:
            from jarvis_utils import bg_log
            bg_log(msg)
        except Exception:
            pass


# ==========================================================================
# Module-level singleton
# ==========================================================================
_DEFAULT_CONSOLIDATOR: Optional[WeeklyReflectionConsolidator] = None


def get_default_consolidator() -> Optional[WeeklyReflectionConsolidator]:
    return _DEFAULT_CONSOLIDATOR


def set_default_consolidator(c: WeeklyReflectionConsolidator) -> None:
    global _DEFAULT_CONSOLIDATOR
    _DEFAULT_CONSOLIDATOR = c
