# -*- coding: utf-8 -*-
"""[P0+20-β.5.23-B / 2026-05-19] ConcernFeedbackReflector — L7 LLM 周期分析 propose.

Sir 01:36 'B 不交手动 + 自动化为主' + Sir 准则 6 反思. 这个 daemon 是 Sir
不用手动改 cooldown 阈值的关键 — 它周期 (24h 1 次) 看:

  输入:
  - STM 最近 7 天
  - Concern.last_user_feedback (β.5.22-C 写入的 Sir 历史反馈)
  - ProactiveCare 推送频次 (last_any_nudge_ts / silent_history)
  - Sir explicit_reject 触发次数

  调 LLM propose:
  - 调 cooldown 阈值 (e.g. Sir 7 天里被 hydration 催 30 次拒 5 次 →
    propose PER_CONCERN_COOLDOWN_S: 1800 → 2700)
  - 新 optimal_timing pattern (e.g. Sir 喝水高峰在晚 11 点 → propose
    before_sleep timing)
  - 新 concern (delegate WeeklyReflector 做)

  写到 cooldown_vocab.json 的 review_queue. Sir 用 CLI `cooldown_vocab_dump.py
  review` 看; 同意就 `cooldown_vocab_dump.py set KEY VALUE` apply.

注: 这个 reflector 比 WeeklyReflector 更窄, 专门负责 cooldown / timing /
feedback pattern. 不替代 WeeklyReflector (后者管 concern lifecycle).
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Optional

try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(s: str) -> None:
        print(s)


REFLECT_INTERVAL_S_DEFAULT = 86400.0  # 24h
VOCAB_PATH = os.path.join('memory_pool', 'proactive_care_cooldown_vocab.json')


class ConcernFeedbackReflector:
    """L7 daemon — 周期看数据, LLM propose cooldown 阈值调整 + optimal_timing 模式.

    用法:
      reflector = ConcernFeedbackReflector(
          ledger=ledger, key_router=key_router, nerve=nerve)
      reflector.start_daemon(interval_s=86400)   # 后台跑
      reflector.reflect_once()                    # 手动跑一次 (debug)
    """

    def __init__(self, ledger, key_router=None, nerve=None,
                 vocab_path: str = VOCAB_PATH):
        self.ledger = ledger
        self.key_router = key_router
        self.nerve = nerve
        self.vocab_path = vocab_path
        self._stop = threading.Event()
        self._daemon_thread: Optional[threading.Thread] = None
        self._last_reflect_at: float = 0.0
        self._reflect_count: int = 0

    def start_daemon(self, interval_s: float = REFLECT_INTERVAL_S_DEFAULT) -> None:
        if self._daemon_thread is not None and self._daemon_thread.is_alive():
            return
        self._stop.clear()

        def _loop():
            # 启动 1h 后跑首次 (等系统稳定 + 有数据)
            time.sleep(3600)
            while not self._stop.is_set():
                try:
                    self.reflect_once()
                except Exception as e:
                    bg_log(f"⚠️ [ConcernFeedbackReflector] reflect err: {e}")
                # 等下一周期 (检查 stop 间隔 60s 防 join 阻塞)
                _waited = 0.0
                while not self._stop.is_set() and _waited < interval_s:
                    time.sleep(60.0)
                    _waited += 60.0

        self._daemon_thread = threading.Thread(
            target=_loop, daemon=True, name='ConcernFeedbackReflector')
        self._daemon_thread.start()
        bg_log(
            f"💫 [ConcernFeedbackReflector] daemon started "
            f"(interval={int(interval_s/3600)}h)"
        )

    def stop_daemon(self) -> None:
        self._stop.set()
        if self._daemon_thread is not None:
            self._daemon_thread.join(timeout=5.0)

    def reflect_once(self) -> dict:
        """跑一次反思. 返 {'proposals': [...], 'stats': {...}}."""
        self._reflect_count += 1
        self._last_reflect_at = time.time()
        stats = self._collect_stats()
        proposals = self._llm_propose(stats)
        # 写到 vocab review_queue
        if proposals:
            self._write_proposals(proposals)
        bg_log(
            f"💫 [ConcernFeedbackReflector] reflect #{self._reflect_count} "
            f"→ {len(proposals)} proposal(s) (stats: "
            f"nudges_7d={stats.get('nudges_total_7d', 0)}, "
            f"rejects_7d={stats.get('rejects_7d', 0)})"
        )
        return {'proposals': proposals, 'stats': stats}

    def _collect_stats(self) -> dict:
        """采集统计: 推送量 / 拒绝量 / 进度命中量 / 当前 cooldown."""
        stats = {
            'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'iso_date': time.strftime('%Y-%m-%d'),
        }
        try:
            actives = self.ledger.list_active() if self.ledger else []
        except Exception:
            actives = []
        stats['n_active_concerns'] = len(actives)

        # 7 天 cutoff
        cutoff_7d = time.time() - 7 * 86400

        # 统计 last_user_feedback 命中量 (β.5.22-C 写入)
        feedback_hits = 0
        progress_concerns = 0
        for c in actives:
            fb = getattr(c, 'last_user_feedback', {}) or {}
            if fb.get('when', 0) >= cutoff_7d:
                feedback_hits += 1
            dp = getattr(c, 'daily_progress', {}) or {}
            if dp.get('iso_date'):
                progress_concerns += 1
        stats['feedback_hits_7d'] = feedback_hits
        stats['concerns_with_progress'] = progress_concerns

        # 当前 cooldown vocab (从 json 读)
        try:
            with open(self.vocab_path, 'r', encoding='utf-8') as f:
                vocab = json.load(f)
            stats['current_cooldowns'] = vocab.get('current', {})
        except Exception:
            stats['current_cooldowns'] = {}

        # nudge 历史 (假设 nerve 上有 ProactiveCareEngine ref)
        # 简化版: 从 ledger 统计 last_triggered > cutoff_7d 的 concerns
        nudges_total = 0
        for c in actives:
            if getattr(c, 'last_triggered', 0) >= cutoff_7d:
                nudges_total += 1
        stats['nudges_total_7d'] = nudges_total

        # rejects (从 fatigue_map 估)
        rejects = 0
        try:
            pce = getattr(self.nerve, 'proactive_care_engine', None) \
                if self.nerve else None
            if pce is not None:
                fmap = getattr(pce, 'fatigue_map', {}) or {}
                rejects = sum(fmap.values())
        except Exception:
            pass
        stats['rejects_7d'] = rejects

        return stats

    def _llm_propose(self, stats: dict) -> list:
        """调 LLM 看 stats, propose cooldown / timing 调整. 失败 → []."""
        prompt = self._build_prompt(stats)
        # 优先 QuickClassifier (本地 ollama)
        try:
            from jarvis_utils import get_quick_classifier
            qc = get_quick_classifier()
            if qc and getattr(qc, 'is_available', False) \
                    and hasattr(qc, 'prompt_raw'):
                resp = qc.prompt_raw(prompt, max_tokens=1024,
                                       temperature=0.0, timeout=15.0)
                if resp:
                    parsed = self._parse_proposals(resp)
                    if parsed:
                        return parsed
        except Exception as e:
            bg_log(f"⚠️ [ConcernFeedbackReflector] qc fail: {e}")
        return []

    def _build_prompt(self, stats: dict) -> str:
        cur_cd = stats.get('current_cooldowns', {})
        return (
            "你是 Jarvis 内部的 L7 ConcernFeedbackReflector. 每天看 ProactiveCare "
            "数据, propose cooldown 阈值调整, 让 Sir 不被催太勤也不漏催.\n\n"
            f"[7 天统计]\n"
            f"  active concerns: {stats.get('n_active_concerns', 0)}\n"
            f"  nudges 推过: {stats.get('nudges_total_7d', 0)}\n"
            f"  Sir 反馈 hits: {stats.get('feedback_hits_7d', 0)}\n"
            f"  Sir 拒绝累计: {stats.get('rejects_7d', 0)}\n"
            f"  concerns 有进度: {stats.get('concerns_with_progress', 0)}\n\n"
            f"[当前 cooldown 阈值]\n"
            f"  {json.dumps(cur_cd, ensure_ascii=False, indent=2)}\n\n"
            "[判断规则]\n"
            "- 推 30+ 次 但 拒 10+: Sir 被催太勤, propose 全局 cooldown 升 50%\n"
            "- 推 < 5 次 但 0 拒: Sir 没烦, cooldown 不变 或 微降\n"
            "- feedback_hits 多 (Sir 主动报进度): 当 concern 衰减 OK, cooldown 不动\n"
            "- 不要无 stats 基础胡 propose (没数据就空 list)\n\n"
            "[输出 JSON]\n"
            '{"proposals": [\n'
            '  {\n'
            '    "key": "PER_CONCERN_COOLDOWN_S",\n'
            '    "current": 1800.0,\n'
            '    "proposed": 2700.0,\n'
            '    "rationale": "Sir 7 天内被 hydration 催 30 次拒了 5 次, 建议升 50%"\n'
            '  }\n'
            ']}\n\n'
            "严格 JSON, 无 markdown, 无解释.\n"
            "[输出]\n"
        )

    def _parse_proposals(self, resp: str) -> list:
        import re as _re
        s = resp.strip()
        s = _re.sub(r'^```(?:json)?\s*', '', s, flags=_re.MULTILINE)
        s = _re.sub(r'\s*```$', '', s, flags=_re.MULTILINE)
        i = s.find('{')
        j = s.rfind('}')
        if i < 0 or j < 0:
            return []
        try:
            obj = json.loads(s[i:j+1])
            return list(obj.get('proposals', []) or [])
        except Exception:
            return []

    def _write_proposals(self, proposals: list) -> None:
        """propose 写到 cooldown_vocab.json 的 review_queue, 等 Sir CLI 审."""
        try:
            with open(self.vocab_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            return
        rq = data.get('review_queue') or []
        now_iso = time.strftime('%Y-%m-%dT%H:%M:%S')
        for p in proposals:
            entry = {
                'when': now_iso,
                'source': 'ConcernFeedbackReflector',
                'key': p.get('key'),
                'current': p.get('current'),
                'proposed': p.get('proposed'),
                'rationale': str(p.get('rationale', ''))[:300],
            }
            rq.append(entry)
        # 防爆: 最多保 50 条
        data['review_queue'] = rq[-50:]
        try:
            with open(self.vocab_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            bg_log(f"⚠️ [ConcernFeedbackReflector] write fail: {e}")


# ============================================================
# 单例
# ============================================================

_DEFAULT_REFLECTOR: Optional[ConcernFeedbackReflector] = None
_REFLECTOR_LOCK = threading.Lock()


def get_or_create_reflector(ledger=None, key_router=None,
                             nerve=None) -> Optional[ConcernFeedbackReflector]:
    global _DEFAULT_REFLECTOR
    with _REFLECTOR_LOCK:
        if _DEFAULT_REFLECTOR is None and ledger is not None:
            _DEFAULT_REFLECTOR = ConcernFeedbackReflector(
                ledger=ledger, key_router=key_router, nerve=nerve)
        return _DEFAULT_REFLECTOR
