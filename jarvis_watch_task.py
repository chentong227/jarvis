# -*- coding: utf-8 -*-
"""[P5-Gap3-WatchTask / β.5.46-fix13 Fix-3 / 2026-05-22] WatchTask 抽象

Sir 22:18 真测痛点 (前置 Gap 后续追问):
> Sir 说 "等他这个剩余时间，就是导出变成完成的时候提醒我，就是这个千寻VS省这个视频
  完成的时候叫我一下" — Jarvis 答 "I'll keep an eye on Adobe Media Encoder"
  但 **没有真兑现机制**:
    - Time Hook 注册了 trigger=空 (regex 解不出"导出完成"绝对时间)
    - SelfPromise soft 找不到匹配 concern → 仅 log
    - ScreenVisionEngine 默认开但只 describe 给主脑, 没 trigger nudge
    - SirRequestReflector 60s 后 propose 但需要 Sir 手动 activate (5 步链)

== 本 module 治本 ==

Sir 说 "等 X 完提醒" + Jarvis ack soft promise → 直接 register 一条 WatchTask:
  {
    id: 'wt_<uuid>',
    what_to_watch: 'Adobe Media Encoder export progress',
    trigger_evidence: 'progress reaches 100% / status "Done"',
    notify_msg_en/zh: 'Sir, "千寻VS省" export complete.',
    state: 'active',
    expires_at: now + 4h,
    poll_via_screen_vision: True,
  }

ScreenVisionEngine 每次 describe 后调 `judge_against_snapshot()`:
  - 遍历 active tasks
  - LLM batch judge: vision summary 是否命中任意 task trigger_evidence?
  - 命中 → state='fired' + push __NUDGE__ type=watch_task_fired

== 准则 6 4 问 ==

| # | 答 |
|---|---|
| 1 SWM publish | ✅ register/fire 都 publish event (watch_task_registered/fired) |
| 2 LLM 决策 | ✅ registrar LLM 提取 + judge LLM 判 trigger 命中 |
| 3 持久化 + CLI | ✅ memory_pool/watch_tasks.json + scripts/watch_task_dump.py |
| 4 正交 | ✅ vs SelfPromise (soft promise log) / TimeHook (绝对时间) / CommitmentWatcher (Sir 自己承诺) — 这是 "Sir 委托等事件" 独立通路 |

== TTFT 影响 ==

零阻塞. 注册是 fire-and-forget post-stream. judge 在 ScreenVision daemon 内.

doc: AGENTS.md 准则 6.5 vocab + L7 reflector 范式
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(msg: str) -> None:
        print(msg)


# ============================================================
# Constants & paths
# ============================================================

DEFAULT_CONFIG_PATH = os.path.join('memory_pool', 'watch_task_config.json')
DEFAULT_TASKS_PATH = os.path.join('memory_pool', 'watch_tasks.json')


# ============================================================
# WatchTask dataclass
# ============================================================

@dataclass
class WatchTask:
    """Sir 委托 Jarvis 等屏幕事件触发的任务."""
    id: str
    created_at: float
    sir_request: str          # Sir 原话 (truncated)
    jarvis_ack: str           # Jarvis ack reply (truncated)
    turn_id: str              # 注册时 turn_id

    # LLM 提取的语义字段
    what_to_watch: str        # "Adobe Media Encoder export progress"
    trigger_evidence: str     # "progress reaches 100% / 'Done' status"
    notify_msg_en: str
    notify_msg_zh: str

    # 状态机
    state: str = 'active'     # 'active' / 'fired' / 'expired' / 'cancelled'
    expires_at: float = 0.0   # 0 = no expiry, else abs ts
    fired_at: float = 0.0
    fired_evidence: str = ''  # 命中时的 vision summary

    # 统计
    judge_count: int = 0
    last_judge_at: float = 0.0
    last_judge_summary: str = ''   # 最近一次 judge 的 vision describe 摘要

    # 配置 override
    poll_via_screen_vision: bool = True

    def is_active(self) -> bool:
        return self.state == 'active'

    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'WatchTask':
        # tolerant — missing fields use default
        kwargs = {}
        for f in cls.__dataclass_fields__:  # type: ignore[attr-defined]
            if f in d:
                kwargs[f] = d[f]
        return cls(**kwargs)  # type: ignore[arg-type]


# ============================================================
# Store — load/save tasks JSON (thread-safe)
# ============================================================

_STORE_LOCK = threading.Lock()


def _load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """读 config JSON. 失败 fallback 默认.

    默 None → runtime resolve `DEFAULT_CONFIG_PATH` (让 monkeypatch 生效).
    """
    if path is None:
        path = DEFAULT_CONFIG_PATH
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {
            'enabled': True,
            'max_active_tasks': 10,
            'default_expires_in_s': 14400,
        }


def _load_tasks(path: Optional[str] = None) -> List[WatchTask]:
    """读 watch tasks. 失败返空 list.

    默 None → runtime resolve `DEFAULT_TASKS_PATH` (让 monkeypatch 生效).
    """
    if path is None:
        path = DEFAULT_TASKS_PATH
    with _STORE_LOCK:
        if not os.path.exists(path):
            return []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            return []
        tasks_raw = data.get('tasks', []) or []
        tasks = []
        for t in tasks_raw:
            try:
                tasks.append(WatchTask.from_dict(t))
            except Exception:
                continue
        return tasks


def _save_tasks(tasks: List[WatchTask],
                  path: Optional[str] = None) -> bool:
    """原子写 tasks JSON. 失败返 False.

    默 None → runtime resolve `DEFAULT_TASKS_PATH` (让 monkeypatch 生效).
    """
    if path is None:
        path = DEFAULT_TASKS_PATH
    with _STORE_LOCK:
        try:
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            tmp = path + '.tmp'
            payload = {
                '_doc': '[β.5.46-fix13 Fix-3] WatchTask state — Sir 委托等的事件',
                'version': 1,
                'tasks': [t.to_dict() for t in tasks],
            }
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return True
        except Exception as e:
            try:
                bg_log(f"⚠️ [WatchTask/Save] fail: {e}")
            except Exception:
                pass
            return False


def list_active_tasks() -> List[WatchTask]:
    """返当前 active 且未 expire 的 tasks."""
    tasks = _load_tasks()
    out = []
    for t in tasks:
        if t.state != 'active':
            continue
        if t.is_expired():
            continue
        out.append(t)
    return out


def list_all_tasks() -> List[WatchTask]:
    return _load_tasks()


def _sweep_expired() -> int:
    """sweep expired active tasks → state='expired'. 返修改条数."""
    tasks = _load_tasks()
    changed = 0
    for t in tasks:
        if t.state == 'active' and t.is_expired():
            t.state = 'expired'
            changed += 1
    if changed:
        _save_tasks(tasks)
    return changed


# ============================================================
# Registrar — Sir 说 + Jarvis ack 后从对话提取 WatchTask
# ============================================================

_REGISTRAR_PROMPT = """[ROLE]
Classify Sir's utterance for screen-watch intent. Output one of three verdicts:
  - "concrete": Sir said a CLEAR event with a DETECTABLE on-screen trigger
                (e.g. "build finishes", "导出完成", "download icon turns green",
                 "rate limit error appears in Windsurf")
  - "vague":    Sir asked Jarvis to watch SOMETHING but the trigger is unclear / unspecified
                (e.g. "盯一下这个直播" without saying what to look for, "看着 Cursor",
                 "keep an eye on this" without specifying the event)
  - "not_a_watch": no watch intent at all, OR fixed-time reminder (those go to Time Hook)

[IMPORTANT — judge BY SIR'S INTENT ONLY]
- Use [SIR UTTERANCE] as the SOLE basis for verdict.
- [JARVIS REPLY] is shown as background context (e.g. to extract a phrasing Jarvis
  already committed to), NOT as a gate. DO NOT downgrade to "not_a_watch" just
  because Jarvis pushed back ("That is outside my reach" / "I do not have a tool"
  / "I cannot monitor that"). The system DOES have ScreenVisionEngine + WatchTask
  + Mirror infrastructure that can monitor screen events regardless of what
  Jarvis's reply LLM claimed; Jarvis's prompt simply may not have surfaced these
  capabilities. Your job: register the watch task on Sir's behalf so the daemon
  can fire when the screen event occurs.

[GUIDANCE]
- "等 X 完提醒我" → concrete (event = X completes)
- "盯一下直播" → vague (盯啥? 主播动作 / 礼物 / 弹幕?)
- "盯下直播主播开始唱歌就喊我" → concrete (event = 主播唱歌, 有字幕/口型/弹幕 evidence)
- "看着 Windsurf 出 rate limit 提醒" → concrete (event = 'rate limit' text appears)
- "提醒我 5min 后吃药" → not_a_watch (fixed time → Time Hook)

[SIR UTTERANCE]
{sir_text}

[JARVIS REPLY — context only, do not use as gate]
{jarvis_reply}

[OUTPUT — JSON only, no markdown fence]
{{
  "verdict": "concrete" | "vague" | "not_a_watch",
  "watch": null OR {{
    "what_to_watch": "<concrete thing, e.g. 'Adobe Media Encoder export of 千寻vsshen.mp4'>",
    "trigger_evidence": "<visual signal that fires notify, e.g. 'export progress reaches 100% / status Done'>",
    "notify_msg_en": "<one-line English msg when fired>",
    "notify_msg_zh": "<one-line Chinese msg>",
    "rationale": "<one sentence>"
  }},
  "vague_topic": "<rough topic if verdict=vague, e.g. '直播间' / 'Cursor 编辑器'>",
  "clarify_question": "<one-line ask Sir for spec if verdict=vague, e.g. '盯主播啥具体动作 — 开播 / 唱歌 / 礼物 / 弹幕关键词?'>"
}}

If verdict="concrete", watch dict MUST be filled. If verdict="vague", vague_topic + clarify_question MUST be filled.
If verdict="not_a_watch", set watch=null, vague_topic="", clarify_question="".
"""


class WatchTaskRegistrar:
    """Sir 说 + Jarvis ack 后, post-stream fire-and-forget 提取 WatchTask.

    用法 (chat_bypass post-stream):
        from jarvis_watch_task import get_default_registrar
        get_default_registrar().register_async(
            sir_text=cmd, jarvis_reply=full_text, turn_id=tid,
            key_router=worker.key_router,
        )
    """

    DEDUP_WINDOW_SEC = 30.0

    def __init__(self):
        self._lock = threading.Lock()
        self._recent: List[tuple] = []  # [(hash, ts), ...]
        self._config = _load_config()

    def register_async(self, sir_text: str, jarvis_reply: str,
                         turn_id: str = '', key_router: Any = None) -> None:
        """fire-and-forget 异步 register. 主对话不等."""
        if not self._config.get('enabled', True):
            return
        if not sir_text or not jarvis_reply:
            return
        min_chars = int(self._config.get('registrar', {}).get('min_sir_chars', 8))
        if len(sir_text.strip()) < min_chars:
            return
        # quick phrase pre-filter — 命中 trigger phrases 才调 LLM (省 token)
        if not self._has_trigger_phrase(sir_text):
            return
        # dedup
        _hash = hash(sir_text[:200])
        now = time.time()
        with self._lock:
            self._recent = [(h, t) for h, t in self._recent
                              if now - t < self.DEDUP_WINDOW_SEC]
            if any(h == _hash for h, _ in self._recent):
                return
            self._recent.append((_hash, now))
        threading.Thread(
            target=self._register_blocking,
            args=(sir_text, jarvis_reply, turn_id, key_router),
            daemon=True, name='WatchTaskRegister',
        ).start()

    def _has_trigger_phrase(self, sir_text: str) -> bool:
        """快速 phrase pre-filter (Sir 说 + 'remind me when' / '等 X 完' 类)."""
        t = sir_text.lower()
        phrases_zh = self._config.get('registrar_trigger_phrases_zh') or []
        phrases_en = self._config.get('registrar_trigger_phrases_en') or []
        for p in phrases_en:
            if p.lower() in t:
                return True
        # zh phrase 用原文不 lower
        for p in phrases_zh:
            if p in sir_text:
                return True
        return False

    def _has_vague_phrase(self, sir_text: str) -> bool:
        """[fix50 / 2026-05-28] 快速 vague phrase pre-filter (Sir 说 '盯一下' / 'keep an eye on' 类).

        命中 vague phrase 但 Registrar LLM 也判 not_a_watch → 兜底走 vague_clarify
        (准则 6 三维耦合: LLM 决策为主, vocab phrase 兜底防 LLM 漏判).
        """
        t = sir_text.lower()
        phrases_zh = self._config.get('vague_trigger_phrases_zh') or []
        phrases_en = self._config.get('vague_trigger_phrases_en') or []
        for p in phrases_en:
            if p.lower() in t:
                return True
        for p in phrases_zh:
            if p in sir_text:
                return True
        return False

    def _register_blocking(self, sir_text: str, jarvis_reply: str,
                             turn_id: str, key_router: Any) -> None:
        """实际 LLM call + persist (or vague clarify, or fail)."""
        try:
            extracted = self._call_registrar_llm(sir_text, jarvis_reply,
                                                    key_router=key_router)
            if extracted is None:
                # 🆕 [P5-fix21-c / 2026-05-22] 区分多种 None:
                # 1. LLM 判 not_a_watch (Sir 没真要 watch) — 不需 SWM event
                # 2. LLM call fail / parse fail (无法判) — publish 'watch_task_register_fail'
                # 3. [fix50] vague phrase 命中但 LLM 漏判 → 兜底 vague_clarify
                phrase_hit = self._has_trigger_phrase(sir_text)
                vague_hit = self._has_vague_phrase(sir_text)
                if phrase_hit:
                    bg_log(f"⚠️ [WatchTask/RegisterFail] phrase hit but LLM 没出 schema "
                           f"(LLM 挂或返垃圾) → 拒注册 + publish SWM. sir='{sir_text[:60]}'")
                    self._publish_register_fail(sir_text, jarvis_reply, turn_id,
                                                    reason='llm_unavailable_or_parse_fail')
                elif vague_hit:
                    bg_log(f"📌 [WatchTask/VagueFallback] vague phrase hit but LLM 漏判 "
                           f"→ 兜底 vague_clarify. sir='{sir_text[:60]}'")
                    self._publish_vague_clarify(
                        sir_text, jarvis_reply, turn_id,
                        vague_topic='', clarify_question='',
                        source_reason='vague_phrase_fallback',
                    )
                else:
                    bg_log(f"📌 [WatchTask/Skip] no trigger phrase / LLM judged not event-watch: "
                           f"'{sir_text[:60]}'")
                return

            # 🆕 [fix50 / 2026-05-28] verdict 字段分流
            verdict = str(extracted.get('_verdict', '') or '').lower()
            if verdict == 'vague':
                self._publish_vague_clarify(
                    sir_text, jarvis_reply, turn_id,
                    vague_topic=extracted.get('_vague_topic', ''),
                    clarify_question=extracted.get('_clarify_question', ''),
                    source_reason='llm_verdict_vague',
                )
                return
            # concrete (verdict='concrete' 或老 LLM 无 verdict 但有 watch dict)
            self._persist(extracted, sir_text, jarvis_reply, turn_id)
        except Exception as e:
            try:
                bg_log(f"⚠️ [WatchTask/Register] err: {e}")
                self._publish_register_fail(sir_text, jarvis_reply, turn_id,
                                                reason=f'exception: {type(e).__name__}: {str(e)[:80]}')
            except Exception:
                pass

    def _publish_register_fail(self, sir_text: str, jarvis_reply: str,
                                  turn_id: str, reason: str) -> None:
        """🆕 [P5-fix21-c] publish 'watch_task_register_fail' SWM event.

        主脑下轮 prompt 看 [WATCH TASK REGISTER FAIL] block, 自然承认
        "Sir 我答应'盯着 X' 但其实 LLM 挂没真注册成功, 要不要换说法或我手动加".
        准则 5 言出必行 — 没成功也要说清楚.
        """
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                bus.publish(
                    etype='watch_task_register_fail',
                    description=f"WatchTask register fail (Sir asked to watch but LLM failed): "
                                  f"{sir_text[:100]}",
                    source='WatchTaskRegistrar',
                    salience=0.9,  # 高 salience — 主脑必看必说
                    ttl=600.0,  # 10min — 给主脑 1-2 轮承认
                    metadata={
                        'sir_text': sir_text[:300],
                        'jarvis_reply_excerpt': jarvis_reply[:300],
                        'turn_id': turn_id,
                        'reason': reason[:200],
                        'ts': time.time(),
                    },
                )
        except Exception:
            pass

    def _publish_vague_clarify(self, sir_text: str, jarvis_reply: str,
                                  turn_id: str, vague_topic: str = '',
                                  clarify_question: str = '',
                                  source_reason: str = 'llm_verdict_vague') -> None:
        """🆕 [fix50 / 2026-05-28] publish 'watch_task_vague_clarify' SWM event.

        Sir 说 'vague watch req' (e.g. '盯一下这个直播') — Registrar LLM 判 vague
        (或 vague phrase 兜底命中). 不真注册 (没空壳 task), 而是 publish 让主脑下轮
        prompt 看到 [WATCH TASK VAGUE CLARIFY] block, 自然问 Sir 具体盯啥事件.

        准则 5 言出必行 — 不假装答应 'I'll keep an eye on' 但其实没注册. 主脑主动问.
        准则 6 三维耦合 — 数据 publish SWM, 决策让主脑下轮自由组织反问句.
        """
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            cfg = (self._config.get('vague_clarify') or {})
            ttl = float(cfg.get('prompt_block_age_s', 600.0))
            bus.publish(
                etype='watch_task_vague_clarify',
                description=(
                    f"Sir vague watch req — needs clarification: "
                    f"{(vague_topic or sir_text)[:80]}"
                ),
                source='WatchTaskRegistrar',
                salience=0.85,  # 高 salience, 主脑下轮必看
                ttl=ttl,
                metadata={
                    'sir_text': sir_text[:300],
                    'jarvis_reply_excerpt': jarvis_reply[:300],
                    'turn_id': turn_id,
                    'vague_topic': (vague_topic or '')[:200],
                    'clarify_question': (clarify_question or '')[:200],
                    'source_reason': source_reason[:50],
                    'ts': time.time(),
                },
            )
            bg_log(
                f"📌 [WatchTask/VagueClarify] published SWM "
                f"(reason={source_reason}, topic='{(vague_topic or '?')[:40]}'): "
                f"'{sir_text[:60]}'"
            )
        except Exception:
            pass

    def _call_registrar_llm(self, sir_text: str, jarvis_reply: str,
                              key_router: Any) -> Optional[Dict[str, Any]]:
        """调 LLM 提取 schema. 失败 fallback 简单模板.

        Returns dict with '_verdict' ∈ {'concrete', 'vague'} 加其他字段,
        or None if not a watch request / LLM fail.
        """
        cfg = self._config.get('registrar') or {}
        if key_router is None:
            return self._template_fallback(sir_text, jarvis_reply)

        try:
            from jarvis_utils import safe_openrouter_call
        except Exception:
            return self._template_fallback(sir_text, jarvis_reply)

        try:
            okey, _label = key_router.get_openrouter_key(caller='watch_task_registrar')
        except Exception:
            return self._template_fallback(sir_text, jarvis_reply)

        prompt = _REGISTRAR_PROMPT.format(
            sir_text=sir_text[:500],
            jarvis_reply=jarvis_reply[:500],
        )

        # 🆕 [P5-fix73 / 2026-05-23 18:10] BUG-N: try/finally release 防泄漏.
        raw = ''
        try:
            try:
                raw = safe_openrouter_call(
                    openrouter_key=okey,
                    model=cfg.get('primary_model', 'google/gemini-2.5-flash-lite'),
                    prompt=prompt,
                    max_tokens=int(cfg.get('max_output_tokens', 400)),
                    temperature=float(cfg.get('temperature', 0.2)),
                )
            except Exception:
                try:
                    raw = safe_openrouter_call(
                        openrouter_key=okey,
                        model=cfg.get('fallback_model', 'google/gemini-3-flash-preview'),
                        prompt=prompt,
                        max_tokens=int(cfg.get('max_output_tokens', 400)),
                        temperature=float(cfg.get('temperature', 0.2)),
                    )
                except Exception:
                    return self._template_fallback(sir_text, jarvis_reply)
        finally:
            try:
                key_router.release(_label)
            except Exception:
                pass

        return self._parse_llm_json(raw or '', sir_text, jarvis_reply)

    def _parse_llm_json(self, raw: str, sir_text: str,
                          jarvis_reply: str) -> Optional[Dict[str, Any]]:
        """parse LLM JSON. 失败 fallback.

        🆕 [fix50 / 2026-05-28] verdict 字段三分类:
          - 'concrete' (新): 老路径 → 返 dict with _verdict='concrete' + watch fields
          - 'vague'    (新): 新路径 → 返 dict with _verdict='vague' + _vague_topic + _clarify_question
          - 'not_a_watch' (新): 返 None (caller 走 skip)
          - 老 LLM 无 verdict 字段: watch=null → None, watch 完整 → 当 concrete (向后兼容)
        """
        t = (raw or '').strip()
        if t.startswith('```'):
            t = t.split('\n', 1)[-1] if '\n' in t else t
            if t.endswith('```'):
                t = t[:t.rfind('```')]
        t = t.strip()
        try:
            data = json.loads(t)
        except Exception:
            return self._template_fallback(sir_text, jarvis_reply)

        verdict = str(data.get('verdict', '') or '').strip().lower()
        watch = data.get('watch')

        # vague branch
        if verdict == 'vague':
            return {
                '_verdict': 'vague',
                '_vague_topic': str(data.get('vague_topic', '') or '')[:200],
                '_clarify_question': str(data.get('clarify_question', '') or '')[:200],
            }

        # explicit not_a_watch → None
        if verdict == 'not_a_watch':
            return None

        # concrete (verdict='concrete' 或老 LLM 无 verdict)
        if not watch:
            return None
        what = (watch.get('what_to_watch', '') or '').strip()
        trig = (watch.get('trigger_evidence', '') or '').strip()
        if not what or not trig:
            return None
        return {
            '_verdict': 'concrete',
            'what_to_watch': what[:200],
            'trigger_evidence': trig[:300],
            'notify_msg_en': (watch.get('notify_msg_en', '') or '').strip()[:200]
                              or "Sir, the event you were watching has occurred.",
            'notify_msg_zh': (watch.get('notify_msg_zh', '') or '').strip()[:200]
                              or '先生, 您让我等的事件已经发生.',
            'rationale': (watch.get('rationale', '') or '')[:200],
        }

    def _template_fallback(self, sir_text: str,
                              jarvis_reply: str) -> Optional[Dict[str, str]]:
        """🆕 [P5-fix21-c / 2026-05-22] LLM 不可用 → 拒绝注册 (返 None).

        Sir 14:50 真测痛点: 老 fallback 写"trigger_evidence='an event Sir mentioned'"
        空壳 task → judge LLM 永远判不出"命中" → fired_at 永远 0 → Jarvis 嘴上说
        "I shall keep an eye on" 但其实没真盯. 准则 5 言出必行被破坏.

        修法: LLM fail → 直接 return None (拒绝注册) + caller 端 publish
        'watch_task_register_fail' SWM event 让主脑下轮 prompt 看到, 自然承认
        "Sir 我答应了但其实没真注册成功 (LLM 挂), 您要不要换说法或我手动加".
        """
        # 不再 fallback 写空壳 task. caller 在 _register_blocking 里看到 None
        # 会 publish 'watch_task_register_fail' SWM (见 _persist 调用前判断).
        return None

    def _persist(self, extracted: Dict[str, str], sir_text: str,
                   jarvis_reply: str, turn_id: str) -> None:
        """写入 watch_tasks.json + publish SWM."""
        # 先 sweep expired (顺手 housekeeping)
        _sweep_expired()
        tasks = _load_tasks()
        # 数量上限
        active = [t for t in tasks if t.state == 'active' and not t.is_expired()]
        max_n = int(self._config.get('max_active_tasks', 10))
        if len(active) >= max_n:
            bg_log(f"⚠️ [WatchTask/Reject] active >= {max_n}, "
                   f"skip new (cancel old first via CLI)")
            return
        # 创建 task
        ttl = int(self._config.get('default_expires_in_s', 14400))
        task = WatchTask(
            id=f"wt_{uuid.uuid4().hex[:10]}",
            created_at=time.time(),
            sir_request=sir_text[:300],
            jarvis_ack=jarvis_reply[:300],
            turn_id=turn_id,
            what_to_watch=extracted['what_to_watch'],
            trigger_evidence=extracted['trigger_evidence'],
            notify_msg_en=extracted['notify_msg_en'],
            notify_msg_zh=extracted['notify_msg_zh'],
            state='active',
            expires_at=time.time() + ttl,
            poll_via_screen_vision=bool(self._config.get(
                'default_poll_via_screen_vision', True)),
        )
        tasks.append(task)
        ok = _save_tasks(tasks)
        if not ok:
            return
        bg_log(f"📌 [WatchTask/Register] {task.id} "
               f"watch='{task.what_to_watch[:60]}' "
               f"trig='{task.trigger_evidence[:60]}' "
               f"ttl={ttl // 60}min")

        # 🆕 [Reshape M4.5 / 2026-05-24] DUAL-WRITE to PromiseLog (单源准备)
        # 老 watch_tasks.json 仍写, 新 PromiseLog kind='watch' 也写一份.
        try:
            from jarvis_memory_hub import get_default_hub
            _hub = get_default_hub()
            _hub.write_commitment(
                description=task.what_to_watch[:300],
                kind='watch',
                who_promised='jarvis',
                deadline=time.strftime('%Y-%m-%d %H:%M:%S',
                                         time.localtime(task.expires_at)),
                trigger_pattern={
                    'kind': 'screen_vision',
                    'evidence': task.trigger_evidence[:200],
                    'task_id': task.id,
                    'notify_msg_en': task.notify_msg_en[:200],
                    'notify_msg_zh': task.notify_msg_zh[:200],
                    'turn_id': turn_id,
                },
                source=f'watch_task.register/{turn_id or "no_turn"}',
                jarvis_reply=jarvis_reply[:300],
            )
        except Exception:
            pass

        # publish SWM 'watch_task_registered'
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                bus.publish(
                    etype='watch_task_registered',
                    description=f"WatchTask registered: {task.what_to_watch[:80]}",
                    source='WatchTaskRegistrar',
                    salience=0.5,
                    metadata={
                        'task_id': task.id,
                        'what_to_watch': task.what_to_watch,
                        'trigger_evidence': task.trigger_evidence,
                        'expires_at': task.expires_at,
                        'turn_id': turn_id,
                    },
                )
        except Exception:
            pass


# ============================================================
# Judge — ScreenVision describe 后, batch judge active tasks
# ============================================================

_JUDGE_PROMPT = """[ROLE]
Judge: did any of Jarvis's active WatchTasks just trigger based on what is on screen RIGHT NOW?

[SCREEN VISION SUMMARY]
{vision_summary}

[ACTIVE WATCH TASKS]
{tasks_str}

[CRITERIA]
A task fires ONLY if the screen evidence CLEARLY shows the trigger_evidence has met. Be conservative — false fires annoy Sir. If unsure, say no.

[OUTPUT — JSON only, no markdown]
{{"fired_task_ids": ["wt_xxx", ...], "rationale_per_task": {{"wt_xxx": "<why>"}}}}
If nothing fires, output: {{"fired_task_ids": [], "rationale_per_task": {{}}}}
"""


class WatchTaskJudge:
    """ScreenVision describe 后, LLM judge active tasks 是否命中."""

    def __init__(self):
        self._lock = threading.Lock()
        self._last_judge_at = 0.0
        self._config = _load_config()

    def judge_against_snapshot(self, snapshot: Any,
                                 key_router: Any = None) -> List[Dict[str, Any]]:
        """ScreenVision._do_describe 完后调.

        Args:
            snapshot: jarvis_screen_vision.ScreenSnapshot 实例 (含 screen_summary)
            key_router: KeyRouter for LLM call

        Returns: list of fired task dicts [{task_id, evidence, msg_en, msg_zh}, ...]
        """
        if not self._config.get('enabled', True):
            return []
        # min judge interval (省 LLM call)
        min_iv = float(self._config.get('min_judge_interval_s', 30.0))
        with self._lock:
            if time.time() - self._last_judge_at < min_iv:
                return []
        # load active tasks
        active = list_active_tasks()
        active = [t for t in active if t.poll_via_screen_vision]
        if not active:
            return []
        # extract vision summary
        summary = self._extract_vision_summary(snapshot)
        if not summary:
            return []
        # call judge LLM
        fired_ids = self._call_judge_llm(summary, active, key_router)
        if not fired_ids:
            # update last_judge_at + judge_count even if 0 fired
            self._update_judge_stats(active, summary, fired_ids=[])
            with self._lock:
                self._last_judge_at = time.time()
            return []
        # mark fired
        fired_tasks = self._mark_fired_and_persist(active, fired_ids, summary)
        # publish + push __NUDGE__
        for ft in fired_tasks:
            self._publish_fired(ft)
        with self._lock:
            self._last_judge_at = time.time()
        return fired_tasks

    def _extract_vision_summary(self, snapshot: Any) -> str:
        """从 ScreenSnapshot 抽 summary."""
        try:
            parts = []
            app = getattr(snapshot, 'active_app', '') or ''
            sumr = getattr(snapshot, 'screen_summary', '') or ''
            fileurl = getattr(snapshot, 'file_or_url_visible', '') or ''
            errors = getattr(snapshot, 'errors_visible', None) or []
            build = getattr(snapshot, 'build_output_status', '') or ''
            kws = getattr(snapshot, 'recent_visible_keywords', None) or []
            if app:
                parts.append(f"App: {app}")
            if fileurl:
                parts.append(f"File/URL: {fileurl}")
            if sumr:
                parts.append(f"Summary: {sumr}")
            if build:
                parts.append(f"Build: {build}")
            if errors:
                parts.append(f"Errors: {', '.join(str(e) for e in errors[:3])}")
            if kws:
                parts.append(f"Keywords: {', '.join(str(k) for k in kws[:6])}")
            return ' | '.join(parts)
        except Exception:
            return ''

    def _call_judge_llm(self, vision_summary: str,
                          active_tasks: List[WatchTask],
                          key_router: Any) -> List[str]:
        """调 LLM batch judge. Returns fired task ids."""
        cfg = self._config.get('judge') or {}
        if key_router is None:
            return []
        try:
            from jarvis_utils import safe_openrouter_call
        except Exception:
            return []
        try:
            okey, _label = key_router.get_openrouter_key(caller='watch_task_judge')
        except Exception:
            return []
        # format tasks
        tasks_lines = []
        for t in active_tasks:
            tasks_lines.append(
                f"- id={t.id} | watch={t.what_to_watch[:80]} | "
                f"trigger={t.trigger_evidence[:100]}"
            )
        prompt = _JUDGE_PROMPT.format(
            vision_summary=vision_summary[:600],
            tasks_str='\n'.join(tasks_lines),
        )
        # 🆕 [P5-fix73 / 2026-05-23 18:10] BUG-N: try/finally release 防泄漏.
        raw = ''
        primary_err = ''
        try:
            try:
                raw = safe_openrouter_call(
                    openrouter_key=okey,
                    model=cfg.get('primary_model', 'google/gemini-2.5-flash-lite'),
                    prompt=prompt,
                    max_tokens=int(cfg.get('max_output_tokens', 300)),
                    temperature=float(cfg.get('temperature', 0.1)),
                )
            except Exception as e_p:
                primary_err = str(e_p)[:120]
                try:
                    raw = safe_openrouter_call(
                        openrouter_key=okey,
                        model=cfg.get('fallback_model', 'google/gemini-3-flash-preview'),
                        prompt=prompt,
                        max_tokens=int(cfg.get('max_output_tokens', 300)),
                        temperature=float(cfg.get('temperature', 0.1)),
                    )
                except Exception as e_f:
                    # 🆕 [P5-fix21-c2 / 2026-05-22] judge LLM 双 fallback 失败 → ErrorBus
                    # Sir 14:50 真意: judge daemon 一直 polling 但 LLM 全挂时主脑不知道.
                    # publish ErrorBus + 不报为 critical (高频可能刷屏, 用 LOW 静默)
                    try:
                        from jarvis_error_bus import report_error as _eb_report, SEVERITY_LOW
                        _eb_report(
                            module='watch_task_judge',
                            kind='llm_judge_fail',
                            detail=f'primary={primary_err[:60]} fallback={str(e_f)[:60]}',
                            severity=SEVERITY_LOW,
                            recoverable=True,
                        )
                    except Exception:
                        pass
                    return []
        finally:
            try:
                key_router.release(_label)
            except Exception:
                pass
        # parse
        t = (raw or '').strip()
        if t.startswith('```'):
            t = t.split('\n', 1)[-1] if '\n' in t else t
            if t.endswith('```'):
                t = t[:t.rfind('```')]
        t = t.strip()
        try:
            data = json.loads(t)
        except Exception:
            # 🆕 [P5-fix21-c2 / 2026-05-22] LLM 返垃圾 JSON → ErrorBus LOW
            try:
                from jarvis_error_bus import report_error as _eb_report, SEVERITY_LOW
                _eb_report(
                    module='watch_task_judge',
                    kind='llm_parse_fail',
                    detail=f'parse fail: {(raw or "")[:60]}',
                    severity=SEVERITY_LOW,
                    recoverable=True,
                )
            except Exception:
                pass
            return []
        return [str(x) for x in (data.get('fired_task_ids') or []) if x]

    def _update_judge_stats(self, judged: List[WatchTask],
                              summary: str, fired_ids: List[str]) -> None:
        """update judge_count + last_judge_at + last_judge_summary."""
        tasks = _load_tasks()
        changed = False
        judged_ids = {t.id for t in judged}
        for t in tasks:
            if t.id in judged_ids:
                t.judge_count += 1
                t.last_judge_at = time.time()
                t.last_judge_summary = summary[:200]
                changed = True
        if changed:
            _save_tasks(tasks)

    def _mark_fired_and_persist(self, active_tasks: List[WatchTask],
                                  fired_ids: List[str],
                                  vision_summary: str) -> List[Dict[str, Any]]:
        """active_tasks 中 id ∈ fired_ids 标 state='fired'. 返 fired task dicts."""
        if not fired_ids:
            return []
        tasks = _load_tasks()
        fired_set = set(fired_ids)
        fired_out = []
        for t in tasks:
            if t.id in fired_set and t.state == 'active':
                t.state = 'fired'
                t.fired_at = time.time()
                t.fired_evidence = vision_summary[:300]
                fired_out.append({
                    'task_id': t.id,
                    'what_to_watch': t.what_to_watch,
                    'trigger_evidence': t.trigger_evidence,
                    'fired_evidence': vision_summary[:200],
                    'notify_msg_en': t.notify_msg_en,
                    'notify_msg_zh': t.notify_msg_zh,
                })
        if fired_out:
            _save_tasks(tasks)
        return fired_out

    def _publish_fired(self, ft: Dict[str, Any]) -> None:
        """publish 'watch_task_fired' SWM + push __NUDGE__."""
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                bus.publish(
                    etype='watch_task_fired',
                    description=f"WatchTask fired: {ft['what_to_watch'][:80]} "
                                  f"— evidence: {ft['fired_evidence'][:80]}",
                    source='WatchTaskJudge',
                    salience=0.95,  # 高 salience, 主脑必看必说
                    ttl=600.0,
                    metadata=ft,
                )
        except Exception:
            pass
        try:
            bg_log(f"🔥 [WatchTask/Fired] {ft['task_id']} "
                   f"watch='{ft['what_to_watch'][:60]}' "
                   f"evidence='{ft['fired_evidence'][:60]}'")
        except Exception:
            pass


# ============================================================
# Singleton helpers
# ============================================================

_DEFAULT_REGISTRAR: Optional[WatchTaskRegistrar] = None
_DEFAULT_JUDGE: Optional[WatchTaskJudge] = None


def get_default_registrar() -> WatchTaskRegistrar:
    global _DEFAULT_REGISTRAR
    if _DEFAULT_REGISTRAR is None:
        _DEFAULT_REGISTRAR = WatchTaskRegistrar()
    return _DEFAULT_REGISTRAR


def get_default_judge() -> WatchTaskJudge:
    global _DEFAULT_JUDGE
    if _DEFAULT_JUDGE is None:
        _DEFAULT_JUDGE = WatchTaskJudge()
    return _DEFAULT_JUDGE


def judge_against_snapshot(snapshot: Any,
                              key_router: Any = None) -> List[Dict[str, Any]]:
    """Module-level convenience for ScreenVisionEngine to call."""
    return get_default_judge().judge_against_snapshot(snapshot, key_router=key_router)


def register_async(sir_text: str, jarvis_reply: str,
                     turn_id: str = '', key_router: Any = None) -> None:
    """Module-level convenience for chat_bypass post-stream to call."""
    get_default_registrar().register_async(
        sir_text=sir_text, jarvis_reply=jarvis_reply,
        turn_id=turn_id, key_router=key_router,
    )


# ============================================================
# 🆕 [P5-fix21-c / 2026-05-22] Prompt block renders 给主脑下轮看
# ============================================================

def render_register_fail_block(within_seconds: float = 600.0,
                                  max_show: int = 2) -> str:
    """渲染 [WATCH TASK REGISTER FAIL] block 给主脑下轮 prompt.

    Sir 14:50 真意 — 主脑答应"盯着 X" 但 LLM 挂没真注册成功 → 下轮主脑必须
    自然承认 + 提议 (重说/手动加/换说法). 准则 5 言出必行 — 没成功也要说清楚.
    """
    try:
        from jarvis_utils import get_event_bus
        bus = get_event_bus()
        if bus is None:
            return ''
        events = bus.recent_events(within_seconds=within_seconds,
                                       types={'watch_task_register_fail'}) or []
        if not events:
            return ''
        # de-dup by sir_text head
        seen = set()
        items = []
        for e in events:
            meta = e.get('metadata') or {}
            sir_h = (meta.get('sir_text') or '')[:80]
            if sir_h in seen:
                continue
            seen.add(sir_h)
            items.append({
                'sir_text': (meta.get('sir_text') or '')[:200],
                'reason': (meta.get('reason') or '')[:80],
                'turn_id': (meta.get('turn_id') or '')[:30],
                'age_s': int(time.time() - float(meta.get('ts', 0) or 0)),
            })
        if not items:
            return ''
        items = items[:max_show]
        lines = [
            '[WATCH TASK REGISTER FAIL — P5-fix21-c / Sir 14:50 痛点: 嘴上盯着但没真盯]',
            '  你之前 reply 答应"keep an eye on / 提醒您"等, 但 LLM 没真出 schema, '
            '系统拒绝了空壳注册:',
        ]
        for it in items:
            lines.append(
                f"    - turn={it['turn_id']} ({it['age_s']}s ago): "
                f"\"{it['sir_text'][:80]}...\" reason={it['reason']}"
            )
        lines.append('')
        lines.append('  你本轮自然承认 (准则 5 言出必行):')
        lines.append('    - "Sir, 关于刚说要盯着 X — 我答应了但其实没真注册成功 '
                       '(LLM 挂或时机不好). 您要不要重说一遍, 或我换其他方式 (手动加 / 跳过)?"')
        lines.append('  ❌ 错误反应: 装没说过 / 再次空答应 "I\'ll keep an eye on" 但仍不真注册.')
        return '\n'.join(lines)
    except Exception:
        return ''


def render_active_tasks_block(max_show: int = 5) -> str:
    """渲染 [ACTIVE WATCH TASKS] block — 主脑知道当前正在盯哪些事.

    Sir 真意: 主脑下轮看自己正在 watch 哪些, 避免重复答应 / 跨 turn 一致性.
    """
    try:
        active = list_active_tasks()
        if not active:
            return ''
        lines = [
            '[ACTIVE WATCH TASKS — 你正在盯着的事 (ScreenVision daemon judge 中)]',
        ]
        for t in active[:max_show]:
            age_min = int((time.time() - t.created_at) / 60)
            ttl_left = int((t.expires_at - time.time()) / 60) if t.expires_at > 0 else -1
            lines.append(
                f"    - {t.id}: watch=\"{t.what_to_watch[:80]}\" "
                f"trig=\"{t.trigger_evidence[:80]}\" "
                f"(age={age_min}min, ttl={ttl_left}min, judges={t.judge_count})"
            )
        if len(active) > max_show:
            lines.append(f"    ... +{len(active) - max_show} more")
        return '\n'.join(lines)
    except Exception:
        return ''


def render_vague_clarify_block(within_seconds: Optional[float] = None,
                                  max_show: Optional[int] = None) -> str:
    """🆕 [fix50 / 2026-05-28] 渲染 [WATCH TASK VAGUE CLARIFY] block — Sir vague req.

    Sir 说 '盯一下这个直播' / '看着 Cursor' 这种 vague request → Registrar LLM 判 vague
    (或 vague phrase 兜底) → publish 'watch_task_vague_clarify' SWM.
    主脑下轮 prompt 看本 block → 自然问 Sir 具体盯啥事件 → Sir 答清楚 →
    轮 Registrar concrete 路径真注册为 WatchTask.

    准则 5 言出必行 — 不假装注册成功. 准则 6 三维耦合 — 数据进 SWM 让主脑决策.
    """
    try:
        from jarvis_utils import get_event_bus
        bus = get_event_bus()
        if bus is None:
            return ''

        cfg = (_load_config().get('vague_clarify') or {})
        if not cfg.get('enabled', True):
            return ''
        ws = float(within_seconds if within_seconds is not None
                    else cfg.get('prompt_block_age_s', 600.0))
        cap = int(max_show if max_show is not None
                   else cfg.get('max_recent_show', 2))

        events = bus.recent_events(within_seconds=ws,
                                       types={'watch_task_vague_clarify'}) or []
        if not events:
            return ''
        # de-dup by sir_text head
        seen = set()
        items = []
        for e in events:
            meta = e.get('metadata') or {}
            sir_h = (meta.get('sir_text') or '')[:80]
            if sir_h in seen:
                continue
            seen.add(sir_h)
            items.append({
                'sir_text': (meta.get('sir_text') or '')[:200],
                'vague_topic': (meta.get('vague_topic') or '')[:150],
                'clarify_question': (meta.get('clarify_question') or '')[:200],
                'source_reason': (meta.get('source_reason') or '')[:40],
                'turn_id': (meta.get('turn_id') or '')[:30],
                'age_s': int(time.time() - float(meta.get('ts', 0) or 0)),
            })
        if not items:
            return ''
        items = items[:cap]
        lines = [
            '[WATCH TASK VAGUE CLARIFY — fix50: Sir 说了 vague watch 请求, 你要主动问清]',
            '  Sir 刚说了模糊的 watch 请求, 系统未注册 (没空壳 task), 你本轮自然问 Sir 澄清:',
        ]
        for it in items:
            lines.append(
                f"    - turn={it['turn_id']} ({it['age_s']}s ago, reason={it['source_reason']})"
            )
            lines.append(f"      Sir said: \"{it['sir_text'][:120]}\"")
            if it['vague_topic']:
                lines.append(f"      topic: {it['vague_topic']}")
            if it['clarify_question']:
                lines.append(f"      建议问: {it['clarify_question']}")
        lines.append('')
        lines.append('  你本轮 reply (准则 5 言出必行):')
        lines.append(
            '    - 用一句反问 Sir 具体盯啥事件, 提议几种可能 trigger (从 vague_topic 推).'
        )
        lines.append(
            '    - 例: Sir 说 "盯下这个直播" → '
            '"Sir, 您想我盯主播啥具体动作? 开播 / 唱歌 / 礼物超 X / 弹幕关键词?"'
        )
        lines.append(
            '    - 例: Sir 说 "看着 Windsurf" → '
            '"您想我看 Cascade 出什么? rate limit / 错误弹窗 / 长时间 spinner?"'
        )
        lines.append(
            '  ❌ 错误: 装答应 ("收到, 我盯着") 但其实没注册 → 准则 5 违反.'
        )
        return '\n'.join(lines)
    except Exception:
        return ''


# ============================================================
# CLI helpers (used by scripts/watch_task_dump.py)
# ============================================================

def cancel_task(task_id: str) -> bool:
    """CLI: cancel an active task."""
    tasks = _load_tasks()
    for t in tasks:
        if t.id == task_id and t.state == 'active':
            t.state = 'cancelled'
            _save_tasks(tasks)
            return True
    return False


def expire_task(task_id: str) -> bool:
    """CLI: expire a task (force state='expired')."""
    tasks = _load_tasks()
    for t in tasks:
        if t.id == task_id and t.state == 'active':
            t.state = 'expired'
            _save_tasks(tasks)
            return True
    return False
