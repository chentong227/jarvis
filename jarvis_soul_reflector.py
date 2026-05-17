# -*- coding: utf-8 -*-
"""[P0+20-β.2.5 / 2026-05-17] Jarvis Soul Reflectors — 灵魂工程 Layer 4

详 docs/JARVIS_SOUL_DRIVE.md §6 (Layer 4 — Reflector daemons)。

两个反思器协同：

## 1. ConcernsReflector (同步 helper / 每轮对话末尾调用)
- 输入：本轮 user_input + jarvis_reply + turn_id
- 任务：启发式 keyword 匹配 → 给相关 concerns 加 signal
- 不走 LLM（保持 zero-cost）
- 例：Sir 说"明天早睡" → sir_sleep_streak.record_signal(...)；
      Sir 说"熬夜赶 cursor" → sir_cursor_payment + sir_sleep_streak 两条都加 signal

## 2. WeeklyReflector (daemon 线程 / 每 7 天 LLM 深度反思)
- daemon tick=60s / 实际反思 7 天一次（last_run_ts 记 ckpt）
- 取最近 50 条 STM + active concerns 列表 + Sir 画像关键字段
- 走 google/gemini-3-flash-preview via OpenRouter (safe_openrouter_call)
- 输出 JSON proposed_concerns: [{id, what_i_watch, why_i_care, severity}]
- 解析 → ledger.propose() 进 review 队列（不直接 active，等 Sir 拍板）
- 写 concerns_review.json
- 失败/超时静默丢弃；rate limit 兜底

设计原则：
- 默认所有 propose 进 review，Sir 是最终仲裁（防 LLM 自作主张污染关心列表）
- WeeklyReflector 不能跑得太勤（每 7 天一次 ~ $0.02/次 / 月 ~$0.08）
- ConcernsReflector 用 keyword 不走 LLM，免成本
- 任何 reflector 失败都不能影响主对话
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Dict, List, Optional

# [P0+20-β.2.5 / 2026-05-17] 顶部 import 暴露 safe_openrouter_call 到本模块命名空间，
# 让 testcase 能 mock。失败时占位 None，运行时 fallback 到 from jarvis_utils import。
try:
    from jarvis_utils import safe_openrouter_call  # noqa: F401
except Exception:
    safe_openrouter_call = None  # type: ignore


# ============================================================
# 启发式 keyword 表（中英双语）
# ============================================================

# 每条 concern_id → list of (lowercase keywords / regex pattern, severity_delta)
CONCERN_KEYWORDS: Dict[str, List[tuple]] = {
    'sir_sleep_streak': [
        # 睡眠相关
        ('sleep', 0.05), ('bed', 0.05), ('tired', 0.05), ('exhausted', 0.08),
        ('all-nighter', 0.10), ('late night', 0.05), ('熬夜', 0.10),
        ('睡', 0.05), ('困', 0.05), ('累', 0.04), ('凌晨', 0.05),
        ('点睡', 0.06), ('睡眠', 0.05), ('失眠', 0.10), ('几点起', 0.04),
    ],
    'sir_pomodoro_compliance': [
        ('break', 0.04), ('rest', 0.04), ('pomodoro', 0.06), ('stretch', 0.03),
        ('eyes hurt', 0.06), ('back hurt', 0.06), ('neck hurt', 0.08),
        ('休息', 0.04), ('久坐', 0.06), ('盯', 0.04), ('一直坐', 0.06),
        ('颈椎', 0.08), ('腰', 0.04), ('眼睛累', 0.06), ('番茄钟', 0.05),
    ],
    'sir_cursor_payment': [
        # 🩹 [P0+20-β.3.3 / 2026-05-17] 探索：单'cursor'关键字会误触
        # "帮我打开 cursor"，但移除会破 test_multi_concern_hits（"熬夜赶 cursor"
        # 期望同时触发）。这是单 keyword 匹配的固有歧义，不是 bug。
        # 保留 'cursor': 0.03 接受 1 个 FP，换 P/R 平衡。
        # 同时加复合词加大支付场景信号（叠加效果，不替代）。
        ('cursor pro', 0.05), ('cursor plan', 0.05), ('cursor subscription', 0.10),
        ('cursor renewal', 0.10), ('cursor billing', 0.08), ('cursor payment', 0.10),
        ('cursor 订阅', 0.10), ('cursor 续费', 0.10), ('cursor 付费', 0.08),
        ('cursor 账单', 0.08),
        ('cursor', 0.03), ('subscription', 0.05), ('payment failed', 0.10),
        ('billing', 0.04), ('订阅', 0.05), ('续费', 0.06), ('付费', 0.04),
        ('账单', 0.04), ('支付失败', 0.10),
    ],
    'unfinished_jiazhao_ke1': [
        ('driving', 0.04), ('license', 0.04), ('jiazhao', 0.08),
        ('科一', 0.10), ('驾照', 0.08), ('练车', 0.06), ('驾考', 0.08),
        ('考试', 0.03),
    ],
    'jarvis_keyrouter_health': [
        ('keyrouter', 0.05), ('permission_denied', 0.10), ('403', 0.06),
        ('quota', 0.05), ('rate limit', 0.05), ('api key', 0.04),
        ('配额', 0.05), ('权限', 0.04), ('挂', 0.03),
        # Jarvis 自己抱怨自己时（"my own keyrouter is..."）也算 signal
    ],
}


# ============================================================
# ConcernsReflector — 启发式 signal 采集
# ============================================================

class ConcernsReflector:
    """每轮对话结束后调一次 reflect_turn(...)，给相关 concerns 加 signal。
    纯启发式，不走 LLM，调用成本 ~50us。"""

    def __init__(self, concerns_ledger):
        self.ledger = concerns_ledger
        self._lock = threading.Lock()
        self._stats = {
            'turns_reflected': 0,
            'signals_recorded': 0,
            'last_turn_ts': 0.0,
        }

    def _scan_text(self, text: str) -> Dict[str, float]:
        """对一段文本扫所有 keyword，返回每个 concern_id 的累计 severity_delta。"""
        hits: Dict[str, float] = {}
        if not text:
            return hits
        t = text.lower()
        for concern_id, kw_list in CONCERN_KEYWORDS.items():
            total_delta = 0.0
            for kw, delta in kw_list:
                if kw in t:
                    total_delta += delta
            if total_delta > 0:
                # 单轮 cap：避免某条 concern 因为出现 5 个 keyword 涨太多
                hits[concern_id] = min(total_delta, 0.15)
        return hits

    def reflect_turn(self, user_input: str = '', jarvis_reply: str = '',
                     turn_id: str = '') -> Dict[str, float]:
        """主入口。返回本轮记的 signal dict (concern_id → severity_delta)。
        在 stream_chat 末尾被调（fire-and-forget thread 即可，但本函数本身
        是同步的，~50us）。"""
        if self.ledger is None:
            return {}
        # 双源扫：user + jarvis 都要看（jarvis 说的也算关系信号）
        combined = f"{user_input}\n{jarvis_reply}"
        hits = self._scan_text(combined)
        if not hits:
            return {}

        recorded = {}
        with self._lock:
            for cid, delta in hits.items():
                # 检查 concern 是否存在 + 是 active
                c = self.ledger.get(cid)
                if c is None:
                    continue
                # snippet：取触发关键字附近 ~60 字
                snippet = self._extract_snippet(combined, cid)[:80]
                evidence = f"[reflect/{turn_id or '?'}] 检测到话题: {snippet}"
                ok = self.ledger.record_signal(
                    cid, evidence,
                    severity_delta=delta,
                    source_turn_id=turn_id,
                )
                if ok:
                    recorded[cid] = delta
            self._stats['turns_reflected'] += 1
            self._stats['signals_recorded'] += len(recorded)
            self._stats['last_turn_ts'] = time.time()

        # 触发后台 persist（不阻塞）
        try:
            self.ledger.persist()
        except Exception:
            pass

        return recorded

    def _extract_snippet(self, text: str, concern_id: str) -> str:
        """从 text 取触发 keyword 附近的小片段，让 evidence 可读。"""
        kw_list = CONCERN_KEYWORDS.get(concern_id, [])
        t = text.lower()
        for kw, _ in kw_list:
            idx = t.find(kw)
            if idx >= 0:
                start = max(0, idx - 30)
                end = min(len(text), idx + len(kw) + 30)
                return text[start:end].replace('\n', ' ').strip()
        return text[:60]

    def get_stats(self) -> Dict:
        with self._lock:
            return dict(self._stats)


# ============================================================
# WeeklyReflector — LLM 深度反思
# ============================================================

WEEKLY_REFLECTOR_CONFIG = {
    # 🩹 [β.2.7.4 / 2026-05-17] Sir 决定升 gemini-3.1-pro-preview（治 LLM 误判 STM 间隔=失眠）
    # 频率：周 1 次 LLM 反思 / 重要性：决定 Jarvis 长期关心什么
    'primary_model': 'google/gemini-3.1-pro-preview',
    'fallback_model': 'google/gemini-2.5-flash-lite',
    'temperature': 0.2,        # 略放手让它创造
    'max_output_tokens': 600,
    'timeout_s': 10.0,
    'tick_seconds': 60.0,       # daemon tick 频率
    'min_interval_s': 7 * 86400,  # 实际反思间隔（每 7 天一次）
    'min_stm_for_reflection': 10,  # < 10 条 STM 不够反思
    'max_propose_per_run': 3,   # 每次最多 propose 3 条新 concern
}


WEEKLY_REFLECTOR_PROMPT = """[ROLE]
You are Jarvis's Inner Reflective Self. Once a week you look back at recent conversations and decide whether there's a NEW long-running concern that Jarvis should add to his "things I watch over for Sir" list.

[CRITICAL CONSTRAINTS]
1. APPEND ONLY — do NOT propose concerns that already exist (see [EXISTING CONCERNS] below).
2. AT MOST 3 new concerns per run. Quality over quantity.
3. Each proposed concern MUST have a clear rationale grounded in the conversation logs — no speculation.
4. NEVER propose meta concerns about "Sir using Jarvis" / "system reliability" / similar self-referential drivel.
5. Concerns should be about Sir's long-term wellbeing / unfinished projects / things he'd be grateful Jarvis noticed.
6. Output empty array if nothing legitimate emerges.

[INTERPRETATION RULES — STM 解读铁律]
🩹 [β.2.7.4 / 2026-05-17] 治 Sir 反馈：误把 "01:55 goodnight → 08:25 morning" 沉默 6.5h 判为 insomnia
1. 大间隔 (>= 4h) 在夜间/凌晨时段 → 默认假设 = 正常睡眠，不要 propose 失眠/作息类 concern
   - 例：01:55 'goodnight' → 08:25 'morning' = 6.5h 沉默 = 正常 6-8h 睡眠
   - 例：03:00 最后说话 → 07:00 第一次说话 = 4h 沉默 = 短睡眠（可能值得 note 但不是 insomnia 证据）
2. 失眠 (insomnia) 类 concern 必须有直接证据：Sir 说 "睡不着" / "insomnia" / "翻来覆去" / "失眠" / "alarm 都没用"
   - 单凭 STM 时间戳间隔本身永远不能 propose insomnia
3. 上一条 utterance 含 'goodnight' / 'sleep' / '睡' / 'bed' 类词 + 长沉默 → 强烈暗示 Sir 真睡了
4. 时间戳是"Jarvis 收到 Sir 话的时刻"，不是"Sir 在干什么"。Sir 不说话 ≠ Sir 醒着

🩹 [β.2.7.5 / 2026-05-17] 治 Sir 反馈 "为什么会觉得我熬夜? 这些事我都不知道哪来的"
[SOURCE 歧义铁律 — STM 不全是 Sir 说的]
5. STM 里 user 字段 ≠ 一定是 Sir 自己说的。可能来源（按可信度排）：
   (a) user_voice — Sir 真说了（最可信）
   (b) ambient_pickup — 视频/音乐/旁人说话被 ASR 录入（不可信）
   (c) jarvis_self — Jarvis 之前的 reply 被错归用户字段（不可信）
   (d) system_event — 后台事件（Cursor 报错/commitment 触发 - 不是 Sir 行为）
6. STM 没标 source —— 你必须用 **conservative inference** 自己判：
   - utterance 像视频/电影/游戏台词 ("welcome to the desert" 类) → ambient
   - utterance 是技术系统消息 ("error in cursor" / "stack trace") → system_event 或 jarvis_self
   - utterance 含完整自然口语 + 涉及 Sir 个人生活/感受 ("我累了"/"我要睡了"/"明天有会") → user_voice
7. propose concern 必须基于**至少 2 条 user_voice 类证据**（同主题被 Sir 自己提到 ≥2 次），不能基于单条 ambient/system 推论
8. 凡 Sir 主体行为 propose ("Sir will do X" / "Sir is struggling with Y")，必须能从 STM **直接引用 Sir 第一人称话**作 evidence
9. 系统已发生事件 (cursor error / file 操作失败 / Jarvis 自检异常) 不要 propose 成 "Sir 在解决 X" — 那是 Jarvis 自己的事
10. 视频/电影/游戏类"梗"绝对不要变成 concern（"lighting was final piece for heaven" 是游戏台词 ≠ Sir 关心的"environment_lighting_logic"）

[EXISTING CONCERNS — DO NOT DUPLICATE]
{existing_concerns_str}

[RECENT STM (last 50 turns, oldest first)]
{stm_str}

[SIR PROFILE CONTEXT (relevant identity fields)]
{profile_summary}

[OUTPUT]
Output ONLY a JSON object on a single line:
{{"proposed_concerns": [
    {{"id": "<snake_case_id_under_30_chars>",
      "what_i_watch": "<one sentence Jarvis-perspective watch description, < 80 chars>",
      "why_i_care": "<one sentence rationale grounded in logs, < 80 chars>",
      "severity": <0.2-0.6 float>}}
]}}

Empty if nothing: {{"proposed_concerns": []}}

ALL string values MUST be in English. NO markdown, NO explanations.
"""


class WeeklyReflector(threading.Thread):
    """每 7 天 LLM 反思 daemon。propose 新 concerns 进 review 队列。"""

    def __init__(self, concerns_ledger, key_router=None,
                 stm_provider=None, profile_provider=None,
                 config: Optional[Dict] = None):
        super().__init__(daemon=True, name='WeeklyReflector')
        self.ledger = concerns_ledger
        self.key_router = key_router
        self.stm_provider = stm_provider          # callable() → list of STM dicts
        self.profile_provider = profile_provider  # callable() → dict
        self.config = dict(WEEKLY_REFLECTOR_CONFIG)
        if config:
            self.config.update(config)
        self._stop = threading.Event()
        self._last_run_ts = 0.0
        self._stats = {
            'runs_total': 0,
            'runs_proposed': 0,
            'proposals_total': 0,
            'last_run_ts': 0.0,
            'last_error': '',
        }

    def stop(self):
        self._stop.set()

    def force_run_now(self) -> Dict:
        """立刻强制反思一次（CLI / 测试用）。返回 stats 摘要。"""
        try:
            return self._reflect_once(force=True)
        except Exception as e:
            return {'error': str(e)[:200]}

    def run(self):
        """daemon loop：每 tick_seconds 检查是否到了 min_interval_s。"""
        try:
            from jarvis_utils import bg_log
            bg_log(f"🌙 [WeeklyReflector] 启动（tick={self.config['tick_seconds']}s, "
                   f"interval={self.config['min_interval_s']/86400:.1f}d, "
                   f"灵魂工程 Layer 4 已激活）")
        except Exception:
            pass

        # 启动后 sleep 20s 让其他模块就绪
        if self._stop.wait(20.0):
            return

        while not self._stop.is_set():
            try:
                # 是否到了反思周期？
                if (time.time() - self._last_run_ts) >= self.config['min_interval_s']:
                    self._reflect_once(force=False)
            except Exception as e:
                self._stats['last_error'] = str(e)[:200]
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"⚠️ [WeeklyReflector] 反思失败（非致命）：{str(e)[:120]}")
                except Exception:
                    pass
            # 等下一个 tick
            if self._stop.wait(self.config['tick_seconds']):
                return

    def _gather_stm_str(self, max_n: int = 50) -> str:
        if self.stm_provider is None:
            return '(no STM provider)'
        try:
            stm = self.stm_provider() or []
        except Exception:
            return '(STM error)'
        if not stm:
            return '(empty)'
        lines = []
        for m in (stm[-max_n:] if len(stm) > max_n else stm):
            u = (m.get('user') or '')[:200]
            j = (m.get('jarvis') or '')[:200]
            ts = m.get('time', '') or ''
            if u or j:
                lines.append(f"[{ts}] U: {u} | J: {j}")
        return '\n'.join(lines)[:5000]

    def _gather_profile_summary(self) -> str:
        if self.profile_provider is None:
            return '(no profile provider)'
        try:
            p = self.profile_provider() or {}
        except Exception:
            return '(profile error)'
        # 只取 identity 类字段（β.2.4 后 sir_profile 只剩这些）
        parts = []
        for k in ('core_philosophy', 'idiosyncrasies', 'work_rhythms',
                  'conversational_boundaries'):
            v = p.get(k, '')
            if v:
                parts.append(f"{k}: {str(v)[:300]}")
        for k in ('active_projects', 'skill_domains'):
            v = p.get(k, [])
            if v:
                parts.append(f"{k}: {', '.join(str(x)[:40] for x in v[:5])}")
        return '\n'.join(parts)[:1500] or '(empty)'

    def _gather_existing_concerns_str(self) -> str:
        if self.ledger is None:
            return '(none)'
        try:
            all_c = self.ledger.list_all() if hasattr(self.ledger, 'list_all') else []
        except Exception:
            return '(error)'
        if not all_c:
            return '(none)'
        lines = []
        for c in all_c:
            lines.append(
                f"  - {c.id} (state={c.state}): {c.what_i_watch[:80]}"
            )
        return '\n'.join(lines)[:2000]

    def _reflect_once(self, force: bool = False) -> Dict:
        """跑一轮反思。返回 {'proposed_n', 'reason'}。"""
        result = {'proposed_n': 0, 'reason': ''}

        # 取数据
        stm_str = self._gather_stm_str()
        profile_str = self._gather_profile_summary()
        existing_str = self._gather_existing_concerns_str()

        # 检查 STM 足够吗（force 不检查）
        if not force:
            try:
                stm = self.stm_provider() if self.stm_provider else []
            except Exception:
                stm = []
            if len(stm) < self.config['min_stm_for_reflection']:
                result['reason'] = (
                    f'STM only {len(stm)} turns '
                    f'(need {self.config["min_stm_for_reflection"]})'
                )
                self._last_run_ts = time.time()  # 也算跑过，下周再来
                return result

        # 调 LLM
        prompt = WEEKLY_REFLECTOR_PROMPT.format(
            existing_concerns_str=existing_str,
            stm_str=stm_str,
            profile_summary=profile_str,
        )

        # 模块级 safe_openrouter_call（顶部 import）；mock 时 testcase 走这条路径
        global safe_openrouter_call
        if safe_openrouter_call is None:
            try:
                from jarvis_utils import safe_openrouter_call as _sor
                safe_openrouter_call = _sor
            except Exception as e:
                result['reason'] = f'import safe_openrouter_call failed: {e}'
                return result

        if self.key_router is None:
            result['reason'] = 'no key_router'
            self._stats['last_error'] = result['reason']
            return result
        try:
            okey, _label = self.key_router.get_openrouter_key(caller='soul_reflector')
        except Exception as e:
            result['reason'] = f'key_router error: {str(e)[:120]}'
            self._stats['last_error'] = result['reason']
            return result

        response_text = ''
        try:
            response_text = safe_openrouter_call(
                openrouter_key=okey,
                model=self.config['primary_model'],
                prompt=prompt,
                max_tokens=self.config['max_output_tokens'],
                temperature=self.config['temperature'],
                max_retries=1,
            )
        except Exception as e_primary:
            # primary 失败 → 走 fallback model
            try:
                response_text = safe_openrouter_call(
                    openrouter_key=okey,
                    model=self.config['fallback_model'],
                    prompt=prompt,
                    max_tokens=self.config['max_output_tokens'],
                    temperature=self.config['temperature'],
                    max_retries=1,
                )
            except Exception as e_fallback:
                result['reason'] = (
                    f'LLM both failed: primary={str(e_primary)[:60]} '
                    f'fallback={str(e_fallback)[:60]}'
                )
                self._stats['last_error'] = result['reason']
                return result

        if not response_text or not response_text.strip():
            result['reason'] = 'empty response'
            return result

        # 解析 JSON
        match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if not match:
            result['reason'] = 'no JSON in response'
            return result
        try:
            data = json.loads(match.group(0))
        except Exception as e:
            result['reason'] = f'JSON parse error: {str(e)[:60]}'
            return result

        proposed = data.get('proposed_concerns') or []
        if not isinstance(proposed, list):
            proposed = []

        # 应用 propose
        from jarvis_concerns import Concern
        n_added = 0
        for entry in proposed[:self.config['max_propose_per_run']]:
            if not isinstance(entry, dict):
                continue
            cid = str(entry.get('id') or '').strip()
            watch = str(entry.get('what_i_watch') or '').strip()
            why = str(entry.get('why_i_care') or '').strip()
            sev = float(entry.get('severity') or 0.3)
            if not cid or not watch or not why:
                continue
            # cap severity
            sev = max(0.1, min(0.8, sev))
            c = Concern(
                id=cid[:60],
                what_i_watch=watch[:120],
                why_i_care=why[:120],
                severity=sev,
                source='weekly_reflector',
                source_marker='P0+20-β.2.5',
            )
            try:
                ok_added = self.ledger.propose(c) if hasattr(self.ledger, 'propose') \
                    else self._propose_fallback(c)
                if ok_added:
                    n_added += 1
            except Exception:
                continue

        if n_added > 0:
            try:
                self.ledger.persist()
                if hasattr(self.ledger, 'write_review_queue'):
                    self.ledger.write_review_queue()
            except Exception:
                pass
            self._stats['runs_proposed'] += 1
            self._stats['proposals_total'] += n_added
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"🌙 [WeeklyReflector] propose {n_added} new concerns → review queue "
                    f"(用 scripts/concerns_dump.py --review 看)"
                )
            except Exception:
                pass

        self._stats['runs_total'] += 1
        self._stats['last_run_ts'] = time.time()
        self._last_run_ts = time.time()
        result['proposed_n'] = n_added
        return result

    def _propose_fallback(self, concern):
        """如果 ledger 没有 propose 方法（旧版本），fallback：用 register 但
        强制 state=review。"""
        try:
            from jarvis_concerns import STATE_REVIEW
            concern.state = STATE_REVIEW
            return self.ledger.register(concern)
        except Exception:
            return False

    def get_stats(self) -> Dict:
        return dict(self._stats)


# ============================================================
# 单例（central_nerve.__init__ 启动）
# ============================================================

_DEFAULT_CONCERNS_REFLECTOR: Optional[ConcernsReflector] = None
_DEFAULT_WEEKLY_REFLECTOR: Optional[WeeklyReflector] = None


def get_default_concerns_reflector(concerns_ledger=None) -> Optional[ConcernsReflector]:
    global _DEFAULT_CONCERNS_REFLECTOR
    if _DEFAULT_CONCERNS_REFLECTOR is None and concerns_ledger is not None:
        _DEFAULT_CONCERNS_REFLECTOR = ConcernsReflector(concerns_ledger)
    return _DEFAULT_CONCERNS_REFLECTOR


def get_default_weekly_reflector(concerns_ledger=None, key_router=None,
                                  stm_provider=None,
                                  profile_provider=None) -> Optional[WeeklyReflector]:
    global _DEFAULT_WEEKLY_REFLECTOR
    if _DEFAULT_WEEKLY_REFLECTOR is None and concerns_ledger is not None:
        _DEFAULT_WEEKLY_REFLECTOR = WeeklyReflector(
            concerns_ledger=concerns_ledger,
            key_router=key_router,
            stm_provider=stm_provider,
            profile_provider=profile_provider,
        )
    return _DEFAULT_WEEKLY_REFLECTOR


def reset_default_reflectors_for_test():
    global _DEFAULT_CONCERNS_REFLECTOR, _DEFAULT_WEEKLY_REFLECTOR
    if _DEFAULT_WEEKLY_REFLECTOR is not None:
        try:
            _DEFAULT_WEEKLY_REFLECTOR.stop()
        except Exception:
            pass
    _DEFAULT_CONCERNS_REFLECTOR = None
    _DEFAULT_WEEKLY_REFLECTOR = None
