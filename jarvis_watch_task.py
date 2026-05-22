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


def _load_config(path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """读 config JSON. 失败 fallback 默认."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {
            'enabled': True,
            'max_active_tasks': 10,
            'default_expires_in_s': 14400,
        }


def _load_tasks(path: str = DEFAULT_TASKS_PATH) -> List[WatchTask]:
    """读 watch tasks. 失败返空 list."""
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


def _save_tasks(tasks: List[WatchTask], path: str = DEFAULT_TASKS_PATH) -> bool:
    """原子写 tasks JSON. 失败返 False."""
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
Extract a WatchTask if Sir EXPLICITLY asked Jarvis to watch for an EVENT on screen and notify when it happens.

[CRITERIA — All must hold]
1. Sir's utterance contains EVENT-based watch request (e.g. "等导出完成提醒", "tell me when it's done", "when the build finishes ping me").
2. NOT a fixed-time reminder ("提醒我 5min 后" / "in 30 min" goes to Time Hook, NOT here).
3. The event is CONCRETE + DETECTABLE on screen (Adobe Media Encoder progress / build status / file download done / specific window appears / app exits).
4. Jarvis acknowledged (no pushback).

[SIR UTTERANCE]
{sir_text}

[JARVIS REPLY]
{jarvis_reply}

[OUTPUT — JSON only, no markdown fence]
If NO event-watch request found, output: {{"watch": null}}
Otherwise:
{{"watch": {{
  "what_to_watch": "<concrete thing being watched, e.g. 'Adobe Media Encoder export progress for 千寻vsshen.mp4'>",
  "trigger_evidence": "<what visual signal should fire the notify, e.g. 'export progress reaches 100% / status changes to Done'>",
  "notify_msg_en": "<one-line msg Jarvis will say when fired, in English>",
  "notify_msg_zh": "<one-line msg in Chinese>",
  "rationale": "<one sentence why this qualifies>"
}}}}
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

    def _register_blocking(self, sir_text: str, jarvis_reply: str,
                             turn_id: str, key_router: Any) -> None:
        """实际 LLM call + persist."""
        try:
            extracted = self._call_registrar_llm(sir_text, jarvis_reply,
                                                    key_router=key_router)
            if extracted is None:
                bg_log(f"📌 [WatchTask/Skip] LLM judged not event-watch: "
                       f"'{sir_text[:60]}'")
                return
            self._persist(extracted, sir_text, jarvis_reply, turn_id)
        except Exception as e:
            try:
                bg_log(f"⚠️ [WatchTask/Register] err: {e}")
            except Exception:
                pass

    def _call_registrar_llm(self, sir_text: str, jarvis_reply: str,
                              key_router: Any) -> Optional[Dict[str, str]]:
        """调 LLM 提取 schema. 失败 fallback 简单模板.

        Returns dict {what_to_watch, trigger_evidence, notify_msg_en/zh, rationale}
        or None if not a watch request.
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

        raw = ''
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

        return self._parse_llm_json(raw or '', sir_text, jarvis_reply)

    def _parse_llm_json(self, raw: str, sir_text: str,
                          jarvis_reply: str) -> Optional[Dict[str, str]]:
        """parse LLM JSON. 失败 fallback."""
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
        watch = data.get('watch')
        if not watch:
            return None
        # required fields
        what = watch.get('what_to_watch', '').strip()
        trig = watch.get('trigger_evidence', '').strip()
        if not what or not trig:
            return None
        return {
            'what_to_watch': what[:200],
            'trigger_evidence': trig[:300],
            'notify_msg_en': watch.get('notify_msg_en', '').strip()[:200]
                              or f"Sir, the event you were watching has occurred.",
            'notify_msg_zh': watch.get('notify_msg_zh', '').strip()[:200]
                              or '先生, 您让我等的事件已经发生.',
            'rationale': watch.get('rationale', '')[:200],
        }

    def _template_fallback(self, sir_text: str,
                              jarvis_reply: str) -> Optional[Dict[str, str]]:
        """LLM 不可用时 fallback. 用 sir_text 整段当 what_to_watch."""
        # 仅当含 trigger phrase 才 fallback
        if not self._has_trigger_phrase(sir_text):
            return None
        return {
            'what_to_watch': sir_text[:200],
            'trigger_evidence': 'an event Sir mentioned in his utterance',
            'notify_msg_en': 'Sir, the event you mentioned has occurred.',
            'notify_msg_zh': '先生, 您说的事件发生了.',
            'rationale': 'fallback template (LLM unavailable)',
        }

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
        raw = ''
        try:
            raw = safe_openrouter_call(
                openrouter_key=okey,
                model=cfg.get('primary_model', 'google/gemini-2.5-flash-lite'),
                prompt=prompt,
                max_tokens=int(cfg.get('max_output_tokens', 300)),
                temperature=float(cfg.get('temperature', 0.1)),
            )
        except Exception:
            try:
                raw = safe_openrouter_call(
                    openrouter_key=okey,
                    model=cfg.get('fallback_model', 'google/gemini-3-flash-preview'),
                    prompt=prompt,
                    max_tokens=int(cfg.get('max_output_tokens', 300)),
                    temperature=float(cfg.get('temperature', 0.1)),
                )
            except Exception:
                return []
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
