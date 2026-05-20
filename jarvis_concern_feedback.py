# -*- coding: utf-8 -*-
"""[P0+20-β.5.22-C / 2026-05-19] ConcernFeedbackJudge — LLM 语义反馈引擎.

Sir 01:34 痛点修法的 LLM 判断层. 准则 6 核心: 拒绝硬编码 -0.2 衰减,
信任 LLM 语义.

Flow:
  Sir 主动说一句话 (e.g. "我喝了 6/7 杯水了") →
  post_chat hook 调 ConcernFeedbackJudge.judge_async(user_input, ledger) →
  LLM 输出 JSON list per concern: {cid, has_relevance, progress, severity_delta, optimal_timing} →
  ledger.record_user_feedback() 写回 daily_progress + last_user_feedback.

设计原则:
- 异步, 不阻塞 turn (准则 1: TTFT < 5s)
- 调轻档 LLM (优先 quick_classifier 1.5B local, fallback KeyRouter pool)
- 失败静默 — 不破坏主流程
- JSON 解析容错 (LLM 可能返非 strict JSON)

todo (下轮):
- L7 ConcernFeedbackReflector: 周期回看历史 judgement, propose 新 concern / 调 optimal_timing
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Optional

try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(s: str) -> None:
        print(s)


class ConcernFeedbackJudge:
    """LLM 语义判 Sir 回应 vs active concerns.

    用法:
      judge = ConcernFeedbackJudge(ledger=ledger, key_router=key_router)
      judge.judge_async(user_input="我喝了 6/7 杯了", turn_id="turn_xxx")
      # → 异步 spawn 线程跑 LLM judge, 写回 ledger.record_user_feedback()
    """

    # JSON schema (LLM 输出格式):
    # {
    #   "concerns": [
    #     {
    #       "cid": "sir_hydration_habit",
    #       "has_relevance": true,
    #       "progress": {"current": 6, "target": 8, "unit": "杯"},
    #       "severity_delta": -0.4,
    #       "optimal_timing": "before_sleep"
    #     }
    #   ]
    # }

    def __init__(self, ledger, key_router=None, nerve=None):
        self.ledger = ledger
        self.key_router = key_router
        self.nerve = nerve
        self._judge_thread_count = 0
        self._max_concurrent = 2

    def judge_async(self, user_input: str, turn_id: str = '') -> None:
        """spawn 后台线程跑 judge, 不阻塞."""
        if not user_input or len(user_input.strip()) < 4:
            return
        if self._judge_thread_count >= self._max_concurrent:
            bg_log(
                f"⏭️  [ConcernFeedback] skip {turn_id[:20]} (busy "
                f"{self._judge_thread_count}/{self._max_concurrent})"
            )
            return
        t = threading.Thread(
            target=self._judge_worker,
            args=(user_input, turn_id),
            daemon=True,
            name=f"ConcernFeedback-{turn_id[:12]}",
        )
        t.start()
        self._judge_thread_count += 1

    def _judge_worker(self, user_input: str, turn_id: str) -> None:
        try:
            actives = self.ledger.list_active()
            if not actives:
                return
            judgement = self._call_llm_judge(user_input, actives)
            if not judgement:
                return
            for entry in judgement.get('concerns', []) or []:
                cid = entry.get('cid')
                if not cid:
                    continue
                if not entry.get('has_relevance'):
                    continue
                ok = self.ledger.record_user_feedback(cid, user_input, entry)
                if ok:
                    _sev_d = entry.get('severity_delta') or 0.0
                    try:
                        _sev_d = float(_sev_d)
                    except Exception:
                        _sev_d = 0.0
                    bg_log(
                        f"🔄 [ConcernFeedback/RECORD] cid={cid} "
                        f"progress={entry.get('progress')} "
                        f"sev_d={_sev_d:+.2f} "
                        f"timing='{entry.get('optimal_timing', '')}' "
                        f"turn={turn_id[:20]}"
                    )
                    # 🩹 [β.5.44-B / 2026-05-20 19:05] publish_intent (β.5.0 三维耦合)
                    # Sir 18:55 真理: IntentResolver 看 progress candidate 知道 ledger 已 mutate.
                    # 主脑下轮 prompt [INTENT RESOLVED] block 看到 → 不再撒谎 "I've corrected".
                    try:
                        from jarvis_utils import get_event_bus as _b544_geb
                        _b544_bus = _b544_geb()
                        if _b544_bus is not None:
                            _prog = entry.get('progress') or {}
                            _b544_bus.publish(
                                etype='sir_intent_progress_candidate',
                                description=(
                                    f'concern {cid} progress updated: '
                                    f'{_prog.get("current", "?")}/{_prog.get("target", "?")}'
                                ),
                                source='ConcernFeedback',
                                salience=0.65,
                                metadata={
                                    'confidence': 0.80,  # LLM 已 judge has_relevance
                                    'turn_id': turn_id,
                                    'judgement': {
                                        'concern_id': cid,
                                        'progress': _prog,
                                        'severity_delta': _sev_d,
                                        'optimal_timing': entry.get('optimal_timing', ''),
                                        'mutated_already': True,
                                    },
                                },
                            )
                    except Exception:
                        pass
        except Exception as e:
            bg_log(f"⚠️ [ConcernFeedback] judge err: {e}")
        finally:
            self._judge_thread_count = max(0, self._judge_thread_count - 1)

    def _call_llm_judge(self, user_input: str, actives: list) -> Optional[dict]:
        """构 prompt 调 LLM. fail → 返 None.

        用 QuickClassifier.prompt_raw (本地 ollama qwen2.5:1.5b). 准则 1 高效:
        本地 ~1-3s 不烧 API quota. ollama 不可用 → skip 该 turn, 等下次.
        准则 5: 不胡判, 宁可 skip 不写错 daily_progress.
        """
        # 构 concerns brief (cid + what_i_watch + 当前 daily_progress)
        actives_brief = []
        for c in actives[:10]:  # max 10 防 prompt 爆炸
            actives_brief.append({
                'cid': c.id,
                'what_i_watch': (c.what_i_watch or '')[:80],
                'current_progress': c.daily_progress or {},
            })
        prompt = self._build_prompt(user_input, actives_brief)

        # 调 QuickClassifier.prompt_raw (新 generic API β.5.22-C)
        try:
            from jarvis_utils import get_quick_classifier
            qc = get_quick_classifier()
            if qc and getattr(qc, 'is_available', False) and hasattr(qc, 'prompt_raw'):
                resp = qc.prompt_raw(prompt, max_tokens=512,
                                       temperature=0.0, timeout=8.0)
                if resp:
                    parsed = self._parse_json(resp)
                    if parsed:
                        return parsed
        except Exception:
            pass

        return None

    def _build_prompt(self, user_input: str, actives_brief: list) -> str:
        now_iso = time.strftime('%Y-%m-%d %H:%M', time.localtime())
        actives_json = json.dumps(actives_brief, ensure_ascii=False, indent=2)
        return (
            "你是 Jarvis 内部的 concern feedback judge. Sir 刚说了一句话, "
            "判断这句话是否反映了任一 active concern 的进度, 输出 JSON.\n\n"
            f"[当前时间] {now_iso}\n\n"
            f"[Sir 原话] '{user_input}'\n\n"
            f"[Active Concerns]\n{actives_json}\n\n"
            "[输出 JSON schema]\n"
            '{"concerns": [\n'
            '  {\n'
            '    "cid": "<concern_id>",\n'
            '    "has_relevance": true|false,\n'
            '    "progress": {"current": <int>, "target": <int>, "unit": "<杯|分钟|杯水|...>"} 或 null,\n'
            '    "severity_delta": <float -1.0 ~ 1.0>,\n'
            '    "optimal_timing": "before_sleep" | "morning" | "evening" | "now" | ""\n'
            '  }, ...\n'
            ']}\n\n'
            "[判定规则]\n"
            "- has_relevance=false 的 concern 不必包含 progress/severity_delta/timing (但 cid 仍要给)\n"
            "- 进度高 (e.g. Sir 说喝了 6/8 杯) → severity_delta 负 (e.g. -0.4 削权), 但 optimal_timing='before_sleep' 表示"
            "睡前还该提醒最后一杯\n"
            "- Sir 说 '今天还没做' / '没时间' → severity_delta 正 (升权)\n"
            "- 不要 hallucinate progress (Sir 没明说数字就 progress=null)\n"
            "- 严格 JSON, 不要 markdown code fence, 不要解释\n\n"
            "[输出]\n"
        )

    def _parse_json(self, resp: str) -> Optional[dict]:
        """容错 JSON 解析 - 去 markdown fence, 找首 { 到末 }."""
        if not resp:
            return None
        s = resp.strip()
        # 去 markdown code fence
        s = re.sub(r'^```(?:json)?\s*', '', s, flags=re.MULTILINE)
        s = re.sub(r'\s*```$', '', s, flags=re.MULTILINE)
        # 找首 { 末 }
        i = s.find('{')
        j = s.rfind('}')
        if i < 0 or j < 0:
            return None
        try:
            return json.loads(s[i:j+1])
        except Exception:
            return None

# ============================================================
# 单例
# ============================================================

_DEFAULT_JUDGE: Optional[ConcernFeedbackJudge] = None
_JUDGE_LOCK = threading.Lock()


def get_or_create_judge(ledger=None, key_router=None, nerve=None) -> Optional[ConcernFeedbackJudge]:
    """单例工厂. 第一次调时初始化, 后续返复用."""
    global _DEFAULT_JUDGE
    with _JUDGE_LOCK:
        if _DEFAULT_JUDGE is None and ledger is not None:
            _DEFAULT_JUDGE = ConcernFeedbackJudge(
                ledger=ledger, key_router=key_router, nerve=nerve)
        return _DEFAULT_JUDGE
