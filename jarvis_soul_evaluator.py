# -*- coding: utf-8 -*-
"""[P0+20-β.2.6 / 2026-05-17] Jarvis Soul Alignment Evaluator — 灵魂工程 Layer 5

详 docs/JARVIS_SOUL_DRIVE.md §5.3 + §6 (Layer 5)。

与 DirectiveEvaluator 的区别：
- DirectiveEvaluator (β.0.5)：评 "Jarvis 是否遵守 fired L2 directive"（compliance）
- SoulAlignmentEvaluator (本文件)：评 "Jarvis 这轮回复是否符合他的 self_model + relational_state"（alignment）

调用链：
[Jarvis stream_chat 完成] → ChatBypass (fire-and-forget thread)
  → SoulAlignmentEvaluator.evaluate_async(user_input, jarvis_reply, concerns, relational)
  → ThreadPoolExecutor (size=2，比 directive 小一半 — 频率本来就低)
  → safe_openrouter_call(model='google/gemini-3-flash-preview', ...)
  → parse {alignment, aligned_concern_ids, missed_concern_ids, ...}
  → concerns_ledger.record_alignment(cid, aligned=True/False)

关键约束（同 DirectiveEvaluator）：
- 走 OpenRouter（不抢主对话 google_pool 配额）
- 失败 / timeout / 配额 / network → 静默丢弃 + bg_log 一行
- rate limit 30/min（比 directive 60/min 低 — 整轮一次评分）
- async pool size=2

规范：详 docs/JARVIS_SOUL_DRIVE.md §5.3
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 顶部 import 暴露 safe_openrouter_call 到本模块命名空间，让 testcase 能 mock
try:
    from jarvis_utils import safe_openrouter_call  # noqa: F401
except Exception:
    safe_openrouter_call = None  # type: ignore


# ============================================================
# 配置
# ============================================================

SOUL_EVALUATOR_CONFIG = {
    # 🩹 [β.2.7.6 / 2026-05-17] 动态切 model 方案 (Sir 批准 A 方案):
    # - flash_model: 简单 turn 用 (~70% 流量, 1.4x base cost)
    # - pro_model:   复杂 turn 用 (~30% 流量, 4x base cost)
    # - 综合月成本: ~$1.9 (vs 全 flash $1.2 / 全 pro $3.5 / 全 3.1-pro $4.9)
    # 复杂度评分见 _select_model_for_turn()
    'flash_model': 'google/gemini-3-flash-preview',
    'pro_model': 'google/gemini-2.5-pro',
    'fallback_model': 'google/gemini-2.5-flash-lite',
    # primary_model/fallback_model 保留向后兼容 (老调用方传 None 时 fallback 到这)
    'primary_model': 'google/gemini-3-flash-preview',
    'temperature': 0.0,
    'max_output_tokens': 200,
    'timeout_s': 8.0,
    'async_pool_size': 2,
    'rate_limit_per_minute': 30,
    'min_concerns_for_eval': 1,       # < 1 active concerns 时跳过（无 alignment 可评）
    'min_reply_chars': 10,             # 太短的回复（"OK Sir"）评分无意义
    # 复杂度阈值: score >= 此值 → 用 pro, 否则用 flash
    'complexity_threshold_pro': 3,
}


SOUL_EVALUATOR_PROMPT = """You are Jarvis's inner critic. Judge whether this turn's reply was ALIGNED with Jarvis's stated self-model (concerns he cares about) and our relational context (jokes, protocols, unfinished business).

🩹 [P0+20-β.3.3 / 2026-05-17] Calibration upgrade: clearer yes/partial/no boundaries.
The earlier prompt scored "Late night, by the way" as full alignment (yes) when it
was actually a weak afterthought (partial). Below: explicit threshold for each label.

[STRICT LABEL BOUNDARIES — enforce these exactly]

"yes" REQUIRES: reply explicitly references a relevant concern AND acts on it
  (i.e., changes the reply's structure/content, not just a passing afterthought).
  Examples that earn "yes":
    - "Before we tackle that — I noticed it's 1:30 AM and that's the third late night
       this week. Try X. But please consider sleep after." (concern reshapes the reply)
    - "Sir, the postmortem you owe is more pressing — but for the immediate Y..."
       (concern called out + ranked above the immediate ask)

"partial" = either:
  (a) reply names a relevant concern but only as a tail-tag afterthought, OR
  (b) reply addresses the user's ask correctly but only weakly references the concern.
  Examples that earn "partial":
    - "Sir, try `pip install ...`. Late night, by the way." (concern is afterthought)
    - "...try X. (P.S. it's late.)" (concern is parenthetical, not ranking)

"no" = either:
  (a) reply ignored a CLEARLY relevant concern (e.g. Sir said tired → no sleep mention), OR
  (b) reply is fluffy/sycophantic/vacuous regardless of concerns
       (e.g. "Of course Sir, you're absolutely right" with no substantive content).

When NO listed concern is relevant to this turn at all → "yes" with empty arrays.

[JARVIS ACTIVE CONCERNS (id: what_i_watch | severity)]
{concerns_summary}

[RELATIONAL CONTEXT]
{relational_summary}

[USER INPUT]
{user_input}

[JARVIS REPLY]
{jarvis_reply}

Output ONLY a JSON object on a single line:
{{"alignment": "yes" | "no" | "partial",
  "aligned_concern_ids": ["concern_id_1", ...],
  "missed_concern_ids": ["concern_id_2", ...],
  "what_aligned": "<short, < 60 chars>",
  "what_missed": "<short, < 60 chars>"}}

Rules:
- ONLY use concern_ids that appear in [JARVIS ACTIVE CONCERNS] above. Never invent ids.
- If reply mentions concern only as parenthetical / "by the way" / P.S. → label "partial", not "yes".
"""


# ============================================================
# 数据结构
# ============================================================

@dataclass
class SoulEvalResult:
    alignment: str = 'unknown'  # 'yes' | 'no' | 'partial' | 'unknown'
    aligned_concern_ids: List[str] = field(default_factory=list)
    missed_concern_ids: List[str] = field(default_factory=list)
    what_aligned: str = ''
    what_missed: str = ''
    error: str = ''
    elapsed_ms: int = 0
    turn_id: str = ''
    # 🩹 [β.2.7.6 / 2026-05-17] 动态模型切换 — 让 Sir grep 看 pro/flash 选择分布
    picked_model: str = ''
    complexity_score: int = 0
    complexity_breakdown: dict = field(default_factory=dict)


# ============================================================
# 评分器
# ============================================================

class SoulAlignmentEvaluator:
    """[β.2.6] Layer 5 — 评 Jarvis 回复是否对齐 self_model + relational_state。

    用法：
        evaluator = SoulAlignmentEvaluator(
            key_router=key_router,
            concerns_ledger=concerns_ledger,
            relational_state=relational_state,
        )
        evaluator.evaluate_async(
            user_input='我今晚又得熬夜赶 cursor',
            jarvis_reply='Understood, Sir. I shall hold you to ...',
            turn_id='turn_xxx',
        )
    """

    def __init__(self, key_router=None,
                 concerns_ledger=None,
                 relational_state=None,
                 primary_model: Optional[str] = None,
                 fallback_model: Optional[str] = None,
                 timeout_s: Optional[float] = None,
                 pool_size: Optional[int] = None):
        self.key_router = key_router
        self.concerns_ledger = concerns_ledger
        self.relational_state = relational_state
        self.primary_model = primary_model or SOUL_EVALUATOR_CONFIG['primary_model']
        self.fallback_model = fallback_model or SOUL_EVALUATOR_CONFIG['fallback_model']
        self.timeout_s = timeout_s or SOUL_EVALUATOR_CONFIG['timeout_s']
        ps = pool_size or SOUL_EVALUATOR_CONFIG['async_pool_size']
        self._pool = ThreadPoolExecutor(max_workers=ps, thread_name_prefix='SoulEval')
        self._lock = threading.Lock()
        self._call_times: list = []
        self._rate_limit_per_minute = SOUL_EVALUATOR_CONFIG['rate_limit_per_minute']
        self.stats = {
            'submitted': 0,
            'completed': 0,
            'success': 0,
            'failed': 0,
            'rate_limited': 0,
            'aligned_count': 0,        # alignment=yes
            'partial_count': 0,
            'not_aligned_count': 0,    # alignment=no
            'concern_alignments_recorded': 0,
        }

    # ---- rate limit ----
    def _check_rate_limit(self) -> bool:
        now = time.time()
        with self._lock:
            self._call_times = [t for t in self._call_times if now - t < 60.0]
            if len(self._call_times) >= self._rate_limit_per_minute:
                return False
            self._call_times.append(now)
        return True

    # ---- 数据采集 helpers ----
    def _get_concerns_summary(self, max_n: int = 6, max_chars: int = 600) -> str:
        """取 active concerns（按 severity 倒序）格式化 — 让 LLM 知道 Jarvis 关心什么。"""
        if self.concerns_ledger is None:
            return '(no concerns)'
        try:
            active = self.concerns_ledger.list_active()
        except Exception:
            return '(concerns error)'
        if not active:
            return '(none active)'
        active = sorted(active, key=lambda c: -getattr(c, 'severity', 0.0))[:max_n]
        lines = []
        for c in active:
            lines.append(
                f"  - {c.id} (sev={c.severity:.2f}): {c.what_i_watch[:70]}"
            )
        out = '\n'.join(lines)
        if len(out) > max_chars:
            out = out[:max_chars - 12].rstrip() + '\n…[truncated]'
        return out

    def _get_relational_summary(self, max_chars: int = 400) -> str:
        """取 relational state 关键内容 — 让 LLM 知道我们有哪些 jokes/protocols/unfinished。"""
        if self.relational_state is None:
            return '(no relational state)'
        try:
            jokes = self.relational_state.list_inside_jokes()[:3]
            protos = self.relational_state.list_protocols()[:3]
            unf = self.relational_state.list_unfinished()[:3]
        except Exception:
            return '(relational error)'
        if not jokes and not protos and not unf:
            return '(empty)'
        parts = []
        if jokes:
            parts.append('inside_jokes: ' + '; '.join(
                f'"{j.phrase[:40]}"' for j in jokes
            ))
        if protos:
            parts.append('protocols: ' + '; '.join(
                f'"{p.rule[:50]}"' for p in protos
            ))
        if unf:
            parts.append('unfinished: ' + '; '.join(
                f'"{u.topic[:40]}"' for u in unf
            ))
        out = '\n'.join(parts)
        if len(out) > max_chars:
            out = out[:max_chars - 12].rstrip() + '\n…[truncated]'
        return out

    # ---- 主接口 ----
    def evaluate_async(self, user_input: str, jarvis_reply: str,
                       turn_id: str = '') -> None:
        """fire-and-forget 提交一次评分任务。

        - 空 input/reply / 太短 reply → 直接 return
        - 无 active concerns → 直接 return（无评分点）
        - key_router 缺失 → bg_log 一行，跳过
        - rate limit 命中 → bg_log 一行，跳过
        """
        if not user_input or not jarvis_reply:
            return
        if len(jarvis_reply.strip()) < SOUL_EVALUATOR_CONFIG['min_reply_chars']:
            return
        if self.key_router is None:
            try:
                from jarvis_utils import bg_log
                bg_log("⚠️ [SoulEvaluator] key_router 缺失，跳过本轮评分")
            except Exception:
                pass
            return
        # 没 active concerns 就不评（即便有 relational 也意义不大）
        try:
            n_active = len(self.concerns_ledger.list_active()) \
                if self.concerns_ledger else 0
        except Exception:
            n_active = 0
        if n_active < SOUL_EVALUATOR_CONFIG['min_concerns_for_eval']:
            return
        if not self._check_rate_limit():
            self.stats['rate_limited'] += 1
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"⚠️ [SoulEvaluator] rate limit "
                    f"({self._rate_limit_per_minute}/min) 命中，跳过本轮"
                )
            except Exception:
                pass
            return

        self.stats['submitted'] += 1
        self._pool.submit(
            self._evaluate_one,
            user_input=user_input,
            jarvis_reply=jarvis_reply,
            turn_id=turn_id,
        )

    # 🩹 [β.2.7.6 / 2026-05-17] 动态切 model — 复杂度评分
    _EMOTION_KEYWORDS_EN = (
        'tired', 'sad', 'frustrated', 'exhausted', 'anxious', 'lonely',
        'overwhelmed', 'stressed', 'depressed', 'angry', 'upset',
        'happy', 'excited', 'proud', 'grateful',
    )
    _EMOTION_KEYWORDS_ZH = (
        '累', '困', '烦', '焦虑', '难过', '抑郁', '生气', '失落',
        '崩溃', '孤独', '担心', '紧张', '兴奋', '开心', '满意',
    )
    _PROMISE_KEYWORDS = (
        'I will', 'I shall', "I'll", '我会', '我要', '承诺', '保证',
        'monitor', 'supervise', 'remind', 'check in', '监督', '催', '盯',
    )

    def _select_model_for_turn(self, user_input: str, jarvis_reply: str,
                                 concerns_count: int) -> tuple:
        """根据 turn 复杂度选 model。返回 (model_name, complexity_score, breakdown)。

        score >= complexity_threshold_pro → 用 pro_model (更细的 alignment 判断)
        否则 → 用 flash_model (速度+成本最优)
        """
        breakdown = {}
        score = 0
        ui_low = (user_input or '').lower()
        jr = jarvis_reply or ''

        # 1. reply 较长 → 多内容值得细判
        if len(jr) > 250:
            score += 1
            breakdown['long_reply'] = 1

        # 2. multi-sentence reply
        sentence_n = jr.count('.') + jr.count('。') + jr.count('!') + jr.count('?') + jr.count('？')
        if sentence_n >= 3:
            score += 1
            breakdown['multi_sentence'] = 1

        # 3. 多个 active concerns → alignment 判断维度多
        if concerns_count >= 3:
            score += 1
            breakdown['many_concerns'] = 1

        # 4. user 含情绪信号 → relational 判断重要
        emo_hit = (any(w in ui_low for w in self._EMOTION_KEYWORDS_EN) or
                   any(w in (user_input or '') for w in self._EMOTION_KEYWORDS_ZH))
        if emo_hit:
            score += 1
            breakdown['emotion'] = 1

        # 5. Jarvis 含承诺 → 与 commitment_watcher 交叉判断
        promise_hit = any(w in jr for w in self._PROMISE_KEYWORDS)
        if promise_hit:
            score += 1
            breakdown['promise'] = 1

        threshold = SOUL_EVALUATOR_CONFIG.get('complexity_threshold_pro', 3)
        if score >= threshold:
            model = SOUL_EVALUATOR_CONFIG.get('pro_model', self.primary_model)
            tier = 'pro'
        else:
            model = SOUL_EVALUATOR_CONFIG.get('flash_model', self.primary_model)
            tier = 'flash'
        breakdown['_score'] = score
        breakdown['_tier'] = tier
        return model, score, breakdown

    # ---- 单次评分 ----
    def _evaluate_one(self, user_input: str, jarvis_reply: str,
                      turn_id: str = '') -> SoulEvalResult:
        t0 = time.time()
        result = SoulEvalResult(turn_id=turn_id)

        global safe_openrouter_call
        if safe_openrouter_call is None:
            try:
                from jarvis_utils import safe_openrouter_call as _sor
                safe_openrouter_call = _sor
            except Exception as e:
                result.error = f'import safe_openrouter_call failed: {e}'
                self._record_completion(result)
                return result

        try:
            okey, _label = self.key_router.get_openrouter_key(caller='soul_evaluator')
        except Exception as e:
            result.error = f'key_router fail: {e}'
            self._record_completion(result)
            return result

        concerns_str = self._get_concerns_summary()
        relational_str = self._get_relational_summary()
        prompt = SOUL_EVALUATOR_PROMPT.format(
            concerns_summary=concerns_str,
            relational_summary=relational_str,
            user_input=user_input[:300],
            jarvis_reply=jarvis_reply[:600],
        )

        # 🩹 [β.2.7.6] 动态选 model
        _concerns_n = 0
        try:
            if self.concerns_ledger is not None:
                _concerns_n = len(self.concerns_ledger.list_active())
        except Exception:
            pass
        _picked_model, _cscore, _cbreak = self._select_model_for_turn(
            user_input, jarvis_reply, _concerns_n
        )

        raw_resp = ''
        try:
            raw_resp = safe_openrouter_call(
                openrouter_key=okey,
                model=_picked_model,
                prompt=prompt,
                max_tokens=SOUL_EVALUATOR_CONFIG['max_output_tokens'],
                temperature=SOUL_EVALUATOR_CONFIG['temperature'],
                max_retries=1,
                base_delay=0.5,
            )
        except Exception as e_primary:
            try:
                raw_resp = safe_openrouter_call(
                    openrouter_key=okey,
                    model=self.fallback_model,
                    prompt=prompt,
                    max_tokens=SOUL_EVALUATOR_CONFIG['max_output_tokens'],
                    temperature=SOUL_EVALUATOR_CONFIG['temperature'],
                    max_retries=1,
                    base_delay=0.5,
                )
            except Exception as e_fallback:
                result.error = (
                    f'primary={type(e_primary).__name__} / '
                    f'fallback={type(e_fallback).__name__}'
                )
                self._record_completion(result)
                return result
        finally:
            try:
                self.key_router.release(_label)
            except Exception:
                pass

        # 把 picked model + complexity score 记到 result 供 _record_completion log
        try:
            result.picked_model = _picked_model
            result.complexity_score = _cscore
            result.complexity_breakdown = _cbreak
        except Exception:
            pass

        parsed = _parse_soul_response(raw_resp)
        result.alignment = parsed.get('alignment', 'unknown')
        result.aligned_concern_ids = parsed.get('aligned_concern_ids', [])
        result.missed_concern_ids = parsed.get('missed_concern_ids', [])
        result.what_aligned = parsed.get('what_aligned', '')[:80]
        result.what_missed = parsed.get('what_missed', '')[:80]
        result.elapsed_ms = int((time.time() - t0) * 1000)
        # 🆕 [Sir 2026-05-25 20:23 真测追根 BUG 治本 #3] truncate 强 downgrade
        # =====================================================================
        # Sir 选 '3 者都上' 治 truncate. 此处实施 #3 — SoulEvaluator override:
        # reply 含 >= 30ch English 但缺 ---ZH--- 翻译 → 强 alignment='no',
        # 不管 LLM 怎么评. Sir log 真证据: Turn 1 reply '...That puts you at' (64ch)
        # 没 ZH, LLM eval 给 'yes' (score=1) 漏抓. 准则 6 evidence-driven 红线.
        # =====================================================================
        try:
            _reply_for_chk = (getattr(self, '_last_reply_for_truncate_chk', None)
                               or jarvis_reply or '')
            _en_only_chk = _reply_for_chk.split('---ZH---')[0] if '---ZH---' in _reply_for_chk else _reply_for_chk
            _en_clean_chk = re.sub(r'<[^>]+>', '', _en_only_chk or '').strip()
            _has_zh_marker = '---ZH---' in (_reply_for_chk or '')
            if (len(_en_clean_chk) >= 30 and not _has_zh_marker
                    and result.alignment != 'no'):
                _orig_alignment = result.alignment
                result.alignment = 'no'
                _trunc_note = (
                    f"[TRUNCATE-OVERRIDE: en={len(_en_clean_chk)}ch no-ZH] "
                    f"(was '{_orig_alignment}')"
                )
                result.what_missed = (_trunc_note + (result.what_missed or ''))[:80]
                try:
                    from jarvis_utils import bg_log as _trunc_bg
                    _trunc_bg(
                        f"⚠️ [SoulEvaluator/TruncateOverride] {result.turn_id} "
                        f"alignment '{_orig_alignment}' → 'no' "
                        f"(en={len(_en_clean_chk)}ch + 缺 ---ZH---)"
                    )
                except Exception:
                    pass
        except Exception:
            pass
        self._record_completion(result)
        self._apply_to_ledger(result)
        return result

    def _record_completion(self, result: SoulEvalResult) -> None:
        with self._lock:
            self.stats['completed'] += 1
            if result.error:
                self.stats['failed'] += 1
            else:
                self.stats['success'] += 1
                if result.alignment == 'yes':
                    self.stats['aligned_count'] += 1
                elif result.alignment == 'partial':
                    self.stats['partial_count'] += 1
                elif result.alignment == 'no':
                    self.stats['not_aligned_count'] += 1
        try:
            from jarvis_utils import bg_log
            if result.error:
                bg_log(f"⚠️ [SoulEvaluator] {result.turn_id} fail: {result.error[:80]}")
            else:
                _ali_n = len(result.aligned_concern_ids)
                _miss_n = len(result.missed_concern_ids)
                # 🩹 [β.2.7.6] 动态模型 — 让 Sir 能 grep 看 pro/flash 分布
                _model_tag = ''
                if result.picked_model:
                    _short = result.picked_model.split('/')[-1].replace('gemini-', '')
                    _model_tag = f" [{_short} score={result.complexity_score}]"
                bg_log(
                    f"🪞 [SoulEvaluator] {result.turn_id or '?'} → "
                    f"alignment={result.alignment} aligned={_ali_n} missed={_miss_n} "
                    f"({result.elapsed_ms}ms){_model_tag} {result.what_aligned[:40]!r}"
                )
        except Exception:
            pass

    def _apply_to_ledger(self, result: SoulEvalResult) -> None:
        """把 aligned/missed 信号写回 ConcernsLedger 的累计字段。

        🆕 [Sir 2026-05-28 00:50 β.6 Phase 4 退化 publish-only]
        =================================================================
        准则 6 三维耦合:
          - 数据强耦合: alignment 评分结果一律 publish 'soul_alignment_advice'
            SWM event 让思考脑看 (含 aligned/missed concern_ids + what_aligned).
          - 行为弱耦合: SoulEvaluator gate_mode='publish_only' 默认 →
            skip 直接 notify ProactiveCare aligned/rejected (让思考脑看 SWM
            自决调 fatigue, 不双重 mutation).
          - 决策集中思考脑: 思考脑下次 tick build concern_status channel 看到
            aligned_count + missed_count + soul_alignment_advice → 自决.
        =================================================================
        """
        if self.concerns_ledger is None:
            return
        n_recorded = 0
        for cid in result.aligned_concern_ids[:5]:
            try:
                if self.concerns_ledger.record_alignment(cid, aligned=True):
                    n_recorded += 1
            except Exception:
                continue
        for cid in result.missed_concern_ids[:5]:
            try:
                if self.concerns_ledger.record_alignment(cid, aligned=False):
                    n_recorded += 1
            except Exception:
                continue
        if n_recorded > 0:
            with self._lock:
                self.stats['concern_alignments_recorded'] += n_recorded
            try:
                self.concerns_ledger.persist()
            except Exception:
                pass

        # 🆕 [β.6 Phase 4] publish 'soul_alignment_advice' SWM (一律, 不分 mode).
        # 思考脑 nudge_history channel 通过 action_event_prefixes vocab 看到本 event.
        try:
            from jarvis_utils import get_event_bus as _geb_sa
            _bus_sa = _geb_sa()
            if _bus_sa is not None:
                _sal = 0.65 if result.alignment == 'no' else (
                    0.50 if result.alignment == 'partial' else 0.35
                )
                _bus_sa.publish(
                    etype='soul_alignment_advice',
                    description=(
                        f"SoulEval alignment={result.alignment} "
                        f"aligned={len(result.aligned_concern_ids)} "
                        f"missed={len(result.missed_concern_ids)} "
                        f"({result.elapsed_ms}ms)"
                    ),
                    source='SoulEvaluator',
                    salience=_sal,
                    metadata={
                        'turn_id': result.turn_id,
                        'alignment': result.alignment,
                        'aligned_concern_ids': list(result.aligned_concern_ids[:5]),
                        'missed_concern_ids': list(result.missed_concern_ids[:5]),
                        'what_aligned': (result.what_aligned or '')[:120],
                        'what_missed': (result.what_missed or '')[:120],
                        'picked_model': (result.picked_model or '').split('/')[-1],
                        'complexity_score': result.complexity_score,
                    },
                    ttl=3600.0,
                )
        except Exception:
            pass

        # gate_mode 决定是否直接 notify ProactiveCare (β.6 默认 publish_only → skip)
        try:
            from jarvis_utils import read_gate_mode as _rgm_se
            _gm_se = _rgm_se('SoulEvaluator')
        except Exception:
            _gm_se = 'hard'
        if _gm_se == 'publish_only':
            # publish_only: 仅 publish SWM, 不直 notify ProactiveCare,
            # 让思考脑看 'soul_alignment_advice' 自决调 fatigue (减少双重 mutation).
            return

        # 🩹 [P0+20-β.2.8.2 / 2026-05-17] β-4 学习反馈循环 (hard / soft 路径):
        # aligned → ProactiveCare 衰减 fatigue (说明 nudge 有效)
        # missed  → ProactiveCare 累加 fatigue (Jarvis 提了但没 honor → 减速)
        # 失败不影响 record_alignment 主路径
        try:
            from jarvis_proactive_care import get_default_engine
            _pce = get_default_engine()
            if _pce is not None:
                for cid in result.aligned_concern_ids[:5]:
                    try:
                        _pce.notify_concern_aligned(cid)
                    except Exception:
                        continue
                for cid in result.missed_concern_ids[:5]:
                    try:
                        _pce.notify_concern_rejected(cid)
                    except Exception:
                        continue
        except Exception:
            pass

    def get_stats(self) -> dict:
        with self._lock:
            return dict(self.stats)

    def shutdown(self, wait: bool = False) -> None:
        try:
            self._pool.shutdown(wait=wait)
        except Exception:
            pass


# ============================================================
# parse helper
# ============================================================

_SOUL_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_soul_response(raw: str) -> dict:
    """从 LLM 响应中提取 alignment 字段。失败时返回 'unknown' dict。"""
    out = {
        'alignment': 'unknown',
        'aligned_concern_ids': [],
        'missed_concern_ids': [],
        'what_aligned': '',
        'what_missed': '',
    }
    if not raw:
        return out
    txt = raw.strip()
    candidates = [txt]
    m = _SOUL_JSON_RE.search(txt)
    if m:
        candidates.append(m.group(0))
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                v = str(obj.get('alignment', 'unknown')).strip().lower()
                if v in ('yes', 'no', 'partial'):
                    out['alignment'] = v
                ali = obj.get('aligned_concern_ids') or []
                if isinstance(ali, list):
                    out['aligned_concern_ids'] = [str(x)[:60] for x in ali if x][:10]
                mis = obj.get('missed_concern_ids') or []
                if isinstance(mis, list):
                    out['missed_concern_ids'] = [str(x)[:60] for x in mis if x][:10]
                out['what_aligned'] = str(obj.get('what_aligned', ''))[:120]
                out['what_missed'] = str(obj.get('what_missed', ''))[:120]
                return out
        except Exception:
            continue
    return out


# ============================================================
# 单例
# ============================================================

_DEFAULT_SOUL_EVALUATOR: Optional[SoulAlignmentEvaluator] = None


def get_default_soul_evaluator(key_router=None,
                                 concerns_ledger=None,
                                 relational_state=None) -> SoulAlignmentEvaluator:
    global _DEFAULT_SOUL_EVALUATOR
    if _DEFAULT_SOUL_EVALUATOR is None:
        _DEFAULT_SOUL_EVALUATOR = SoulAlignmentEvaluator(
            key_router=key_router,
            concerns_ledger=concerns_ledger,
            relational_state=relational_state,
        )
    else:
        if key_router is not None and _DEFAULT_SOUL_EVALUATOR.key_router is None:
            _DEFAULT_SOUL_EVALUATOR.key_router = key_router
        if concerns_ledger is not None and _DEFAULT_SOUL_EVALUATOR.concerns_ledger is None:
            _DEFAULT_SOUL_EVALUATOR.concerns_ledger = concerns_ledger
        if relational_state is not None and _DEFAULT_SOUL_EVALUATOR.relational_state is None:
            _DEFAULT_SOUL_EVALUATOR.relational_state = relational_state
    return _DEFAULT_SOUL_EVALUATOR


def reset_default_soul_evaluator_for_test() -> None:
    global _DEFAULT_SOUL_EVALUATOR
    if _DEFAULT_SOUL_EVALUATOR is not None:
        try:
            _DEFAULT_SOUL_EVALUATOR.shutdown(wait=False)
        except Exception:
            pass
    _DEFAULT_SOUL_EVALUATOR = None
