# -*- coding: utf-8 -*-
"""
[P0+20-β.2.8.6 / 2026-05-17] Predicate-Driven Commitment — 抽象语义承诺谓词层

Sir 22:42 反馈痛点:
> "加某个类型, 是不是有点类似硬编码? 如果不是睡觉的情况呢? 是我'导出完视频
>  就去喝水'之类的抽象承诺呢? 我们能不能设计一套这种抽象语义的承诺系统?"

设计参见 docs/JARVIS_PREDICATE_COMMITMENT.md

核心抽象:
    Commitment = (description, predicate, action, ttl)
    Predicate.evaluate(ctx) -> bool
    ctx = {now_ts, idle_ms, sensor_snap, recent_stm, window_title, ...}

阶段:
- β-1 (本): Predicate base + 7 内置 library + Composite (AND/OR/NOT) + 持久化
- β-2: CommitmentWatcher 每 tick evaluate
- β-3: Gatekeeper LLM parser 翻译自然语言 → predicate JSON
- β-4: scripts/predicate_tail.py Sir 可观察
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


# ============================================================
# Base
# ============================================================


class Predicate(ABC):
    """抽象谓词. 子类必须实现 evaluate(ctx) 和 _to_args / from_args.

    🩹 [β.2.8.7 / 2026-05-17] Sir 23:28 反馈: 留 observer / executor 接口
      - subject: 谁的状态被观察? 'sir' (默认, 现有所有 predicate 都看 Sir) |
                  'jarvis' (未来扩展, 让 Jarvis 也能看自己: 'jarvis 备份完了就...')
      - 当前所有 predicate 默认 subject='sir'. 添加 jarvis-subject 时 ctx 加
        ctx['jarvis_state'] / ctx['jarvis_running_tasks'] 等字段, predicate
        实现自己处理 (向后兼容: 不读 jarvis 字段就和现在一样).
    """

    name: str = 'base'         # 类标识 (= type 字段)
    subject: str = 'sir'        # 'sir' | 'jarvis' (β.2.8.7 接口预留)

    @abstractmethod
    def evaluate(self, ctx: Dict[str, Any]) -> bool:
        raise NotImplementedError

    @abstractmethod
    def describe(self) -> str:
        """给 LLM / Sir 看的可读说明."""
        raise NotImplementedError

    def to_dict(self) -> dict:
        """序列化 (持久化 + LLM parse 输出)."""
        d = {'type': self.name, **self._to_args()}
        if self.subject != 'sir':
            d['subject'] = self.subject
        return d

    def _to_args(self) -> dict:
        return {}

    @classmethod
    def from_dict(cls, d: dict) -> 'Predicate':
        """工厂: 从 dict 还原 Predicate 实例 (递归处理 Composite)."""
        t = d.get('type', '')
        impl = PREDICATE_REGISTRY.get(t)
        if impl is None:
            raise ValueError(f"unknown predicate type: {t}")
        return impl.from_args(d)

    @classmethod
    def from_args(cls, d: dict) -> 'Predicate':
        """默认实现: 用 d 减去 type/subject 字段当 kwargs, subject 单独 set."""
        subject = d.get('subject', 'sir')
        kw = {k: v for k, v in d.items() if k not in ('type', 'subject')}
        inst = cls(**kw)
        inst.subject = subject
        return inst


# ============================================================
# Composites — AND / OR / NOT
# ============================================================


class AndPredicate(Predicate):
    name = 'AND'

    def __init__(self, *children: Predicate):
        self.children = list(children)

    def evaluate(self, ctx):
        return all(c.evaluate(ctx) for c in self.children)

    def describe(self):
        return ' AND '.join(c.describe() for c in self.children)

    def _to_args(self):
        return {'args': [c.to_dict() for c in self.children]}

    @classmethod
    def from_args(cls, d):
        return cls(*[Predicate.from_dict(a) for a in d.get('args', [])])


class OrPredicate(Predicate):
    name = 'OR'

    def __init__(self, *children: Predicate):
        self.children = list(children)

    def evaluate(self, ctx):
        return any(c.evaluate(ctx) for c in self.children)

    def describe(self):
        return ' OR '.join(c.describe() for c in self.children)

    def _to_args(self):
        return {'args': [c.to_dict() for c in self.children]}

    @classmethod
    def from_args(cls, d):
        return cls(*[Predicate.from_dict(a) for a in d.get('args', [])])


class NotPredicate(Predicate):
    name = 'NOT'

    def __init__(self, child: Predicate):
        self.child = child

    def evaluate(self, ctx):
        return not self.child.evaluate(ctx)

    def describe(self):
        return f"NOT ({self.child.describe()})"

    def _to_args(self):
        return {'arg': self.child.to_dict()}

    @classmethod
    def from_args(cls, d):
        return cls(Predicate.from_dict(d['arg']))


# ============================================================
# Built-in Library
# ============================================================


class WakeFirstActive(Predicate):
    """Sir 今天首次活跃 — first_active_today + 真醒 (idle<60s).
    用于 "醒了之后 / 早起 / 一起床" 类承诺.
    """
    name = 'wake_first_active'

    def __init__(self, max_idle_ms: int = 60_000):
        self.max_idle_ms = max_idle_ms

    def evaluate(self, ctx):
        if not ctx.get('first_active_today', False):
            return False
        return ctx.get('idle_ms', 9999_999) <= self.max_idle_ms

    def describe(self):
        return f"Sir today's first active (idle ≤ {self.max_idle_ms}ms)"

    def _to_args(self):
        return {'max_idle_ms': self.max_idle_ms}


class TimeAfter(Predicate):
    """当下时间 ≥ HH:MM (today only).

    例: TimeAfter("09:00") — 9 点以后 fire (不指日期, 每天 9:00 后都满足).
    """
    name = 'time_after'

    def __init__(self, hh_mm: str):
        self.hh_mm = hh_mm
        h, m = hh_mm.split(':')
        self.h = int(h)
        self.m = int(m)

    def evaluate(self, ctx):
        now_ts = ctx.get('now_ts', time.time())
        lt = time.localtime(now_ts)
        return (lt.tm_hour, lt.tm_min) >= (self.h, self.m)

    def describe(self):
        return f"time ≥ {self.hh_mm}"

    def _to_args(self):
        return {'hh_mm': self.hh_mm}


class TimeBefore(Predicate):
    name = 'time_before'

    def __init__(self, hh_mm: str):
        self.hh_mm = hh_mm
        h, m = hh_mm.split(':')
        self.h = int(h)
        self.m = int(m)

    def evaluate(self, ctx):
        now_ts = ctx.get('now_ts', time.time())
        lt = time.localtime(now_ts)
        return (lt.tm_hour, lt.tm_min) < (self.h, self.m)

    def describe(self):
        return f"time < {self.hh_mm}"

    def _to_args(self):
        return {'hh_mm': self.hh_mm}


class ProcessExited(Predicate):
    """指定 process 在最近 max_recent_s 内 alive→dead.
    ctx['process_died_events'] 由 PhysicalEnvironmentProbe 提供 (β-2 接通).
    """
    name = 'process_exit'

    def __init__(self, name: str, max_recent_s: int = 600):
        self.exe_name = name.lower()
        self.max_recent_s = max_recent_s

    def evaluate(self, ctx):
        events = ctx.get('process_died_events', []) or []
        now = ctx.get('now_ts', time.time())
        for e in events:
            exe = str(e.get('exe', '')).lower()
            when = float(e.get('when', 0))
            if not exe or not when:
                continue
            if (self.exe_name in exe or exe in self.exe_name) and \
                    (now - when) < self.max_recent_s:
                return True
        return False

    def describe(self):
        return f"process '{self.exe_name}' exited within {self.max_recent_s}s"

    def _to_args(self):
        return {'name': self.exe_name, 'max_recent_s': self.max_recent_s}


class ProcessRunning(Predicate):
    """指定进程当前在运行 (ctx['running_processes'] list)."""
    name = 'process_running'

    def __init__(self, name: str):
        self.exe_name = name.lower()

    def evaluate(self, ctx):
        procs = ctx.get('running_processes', []) or []
        return any(self.exe_name in str(p).lower() for p in procs)

    def describe(self):
        return f"process '{self.exe_name}' is running"

    def _to_args(self):
        return {'name': self.exe_name}


class WindowTitleContains(Predicate):
    """当前活跃窗口标题含 keyword (大小写不敏感)."""
    name = 'window_title_contains'

    def __init__(self, keyword: str):
        self.keyword = keyword
        self._k_l = keyword.lower()

    def evaluate(self, ctx):
        title = str(ctx.get('window_title', '') or '').lower()
        return self._k_l in title

    def describe(self):
        return f"active window title contains '{self.keyword}'"

    def _to_args(self):
        return {'keyword': self.keyword}


class IdleFor(Predicate):
    """Sir 键鼠 idle ≥ seconds (e.g. 30s 没动)."""
    name = 'idle_for'

    def __init__(self, seconds: int):
        self.seconds = int(seconds)

    def evaluate(self, ctx):
        return ctx.get('idle_ms', 0) >= self.seconds * 1000

    def describe(self):
        return f"idle ≥ {self.seconds}s"

    def _to_args(self):
        return {'seconds': self.seconds}


class ActiveFor(Predicate):
    """Sir 在当前活动持续 ≥ minutes."""
    name = 'active_for'

    def __init__(self, minutes: int):
        self.minutes = int(minutes)

    def evaluate(self, ctx):
        snap = ctx.get('sensor_snap', {}) or {}
        return snap.get('session_duration_minutes', 0) >= self.minutes

    def describe(self):
        return f"session duration ≥ {self.minutes}min"

    def _to_args(self):
        return {'minutes': self.minutes}


class AfterAfk(Predicate):
    """β.2.8.13: Sir AFK ≥ min_afk_minutes 后刚回到电脑 (idle 短).

    经典场景: Sir 23:45 说"洗完澡就睡觉" — 洗澡 = AFK 15-30min, 回来 idle 短.
    predicate fire 条件: 历史曾出现长时段 idle (≥ min_afk_minutes) + 当前 idle < 60s.

    用 PhysicalEnvironmentProbe._last_long_idle_ts (β-2 接通) 判断.
    暂时用 ctx['was_afk_recently_minutes'] (上游算好传入) + idle_ms.
    """
    name = 'after_afk'

    def __init__(self, min_afk_minutes: int = 10):
        self.min_afk_minutes = int(min_afk_minutes)

    def evaluate(self, ctx):
        # 当前要 active (idle < 60s)
        if ctx.get('idle_ms', 9999_999) >= 60_000:
            return False
        # 历史曾长 idle ≥ min_afk_minutes
        was_afk = float(ctx.get('was_afk_recently_minutes', 0) or 0)
        return was_afk >= self.min_afk_minutes

    def describe(self):
        return f"Sir just returned from AFK (≥{self.min_afk_minutes}min) and is active now"

    def _to_args(self):
        return {'min_afk_minutes': self.min_afk_minutes}


class StmContains(Predicate):
    """最近 N 轮 STM Sir 主动提过 keyword (任意一个)."""
    name = 'stm_contains'

    def __init__(self, keywords: List[str], lookback_turns: int = 5):
        self.keywords = list(keywords)
        self.lookback = int(lookback_turns)
        self._k_l = [k.lower() for k in keywords]

    def evaluate(self, ctx):
        stm = ctx.get('recent_stm', []) or []
        recent = stm[-self.lookback:] if self.lookback > 0 else stm
        for e in recent:
            user_txt = str(e.get('user', '') or '').lower()
            if any(k in user_txt for k in self._k_l):
                return True
        return False

    def describe(self):
        return f"recent STM ({self.lookback} turns) contains any of {self.keywords}"

    def _to_args(self):
        return {'keywords': self.keywords, 'lookback_turns': self.lookback}


# ============================================================
# Registry — type 字段 → 实现类
# ============================================================

PREDICATE_REGISTRY: Dict[str, type] = {
    'AND': AndPredicate,
    'OR': OrPredicate,
    'NOT': NotPredicate,
    'wake_first_active': WakeFirstActive,
    'time_after': TimeAfter,
    'time_before': TimeBefore,
    'process_exit': ProcessExited,
    'process_running': ProcessRunning,
    'window_title_contains': WindowTitleContains,
    'idle_for': IdleFor,
    'active_for': ActiveFor,
    'stm_contains': StmContains,
    'after_afk': AfterAfk,
}


def register_predicate(impl_cls: type) -> None:
    """对外扩展点: 第三方加新 predicate."""
    PREDICATE_REGISTRY[impl_cls.name] = impl_cls


def parse_predicate(d: dict) -> Optional[Predicate]:
    """安全解析: 返回 Predicate 或 None (LLM 输出错误时 fallback)."""
    if not isinstance(d, dict):
        return None
    try:
        return Predicate.from_dict(d)
    except Exception:
        return None


# ============================================================
# Heuristic: 从自然语言关键词推断 predicate (LLM 不可用时 fallback)
# ------------------------------------------------------------
# 🩹 [β.5.19-B / 2026-05-20] Sir 准则 6 vocab 持久化第 1 维.
#   - keywords 从 _WAKE/EXPORT/PREMIERE_KEYWORDS source list 迁到
#     memory_pool/predicate_keywords.json (CLI scripts/predicate_vocab_dump.py)
#   - py 仅留 _SEED_*_KEYWORDS 作 fallback (json 损坏 / 首次启动)
#   - get_predicate_keywords(group) 带 mtime cache, 文件变自动 reload
#   - L7 reflector LLM-propose 新 keyword 入 review queue 待后续轨道
# ============================================================
import os as _pred_os
import json as _pred_json
import threading as _pred_threading

_SEED_WAKE_KEYWORDS = ('醒', '起床', '起来', 'wake', 'woken', 'morning',
                        '早上', '明早', '一早', 'woke', 'wake up')
_SEED_EXPORT_KEYWORDS = ('导出完', '导出之后', '导完', 'export finished', 'export done',
                          'finished exporting')
_SEED_PREMIERE_KEYWORDS = ('视频', 'premiere', '剪辑', 'video')

_PRED_VOCAB_PATH = _pred_os.path.join(
    _pred_os.path.dirname(_pred_os.path.abspath(__file__)),
    'memory_pool', 'predicate_keywords.json')

# mtime cache: 重读 json 仅当文件 mtime 变 (vocab 加 keyword / dump 工具改).
_pred_vocab_lock = _pred_threading.Lock()
_pred_vocab_cache: dict = {}
_pred_vocab_mtime: float = 0.0


def _load_predicate_vocab() -> dict:
    """读 memory_pool/predicate_keywords.json (mtime cache).

    Returns: {'wake': tuple, 'export': tuple, 'premiere': tuple}
    Fail-safe: 文件不存在 / 损坏 → 返 SEED fallback (兼容老路径).
    """
    global _pred_vocab_cache, _pred_vocab_mtime
    fallback = {
        'wake': _SEED_WAKE_KEYWORDS,
        'export': _SEED_EXPORT_KEYWORDS,
        'premiere': _SEED_PREMIERE_KEYWORDS,
    }
    try:
        if not _pred_os.path.exists(_PRED_VOCAB_PATH):
            return fallback
        mtime = _pred_os.path.getmtime(_PRED_VOCAB_PATH)
        with _pred_vocab_lock:
            if _pred_vocab_cache and mtime == _pred_vocab_mtime:
                return _pred_vocab_cache
            with open(_PRED_VOCAB_PATH, 'r', encoding='utf-8') as f:
                data = _pred_json.load(f)
            groups = data.get('groups', {})
            cache = {
                'wake': tuple(groups.get('wake', {}).get(
                    'keywords', _SEED_WAKE_KEYWORDS)),
                'export': tuple(groups.get('export', {}).get(
                    'keywords', _SEED_EXPORT_KEYWORDS)),
                'premiere': tuple(groups.get('premiere', {}).get(
                    'keywords', _SEED_PREMIERE_KEYWORDS)),
            }
            _pred_vocab_cache = cache
            _pred_vocab_mtime = mtime
            return cache
    except Exception:
        return fallback


def get_predicate_keywords(group: str) -> tuple:
    """[β.5.19-B] 取某 group keywords (vocab-driven). group ∈ {'wake', 'export', 'premiere'}.

    Returns: tuple of str. 文件损坏 / group 未知 → 返 () 安全空.
    """
    vocab = _load_predicate_vocab()
    return vocab.get(group, ())


# 旧符号兼容: 读 vocab live (避免老 import 拿到 stale snapshot).
# 新代码请直接用 get_predicate_keywords('wake') 等.
_WAKE_KEYWORDS = _SEED_WAKE_KEYWORDS
_EXPORT_KEYWORDS = _SEED_EXPORT_KEYWORDS
_PREMIERE_KEYWORDS = _SEED_PREMIERE_KEYWORDS


def predicate_library_prompt() -> str:
    """β-3: 给 Gatekeeper LLM 看的 predicate library 描述. 自动从 registry 生成,
    新加 predicate 自动出现在 prompt 里 — 准则 6 (拒绝硬编码) 的真正落地.
    """
    lines = [
        "Predicate library (use these as building blocks, NOT keyword-matched):",
        "",
    ]
    # 单原子 predicate (跳过 composite 自身, 它们有专门 schema 段)
    for name in sorted(PREDICATE_REGISTRY.keys()):
        if name in ('AND', 'OR', 'NOT'):
            continue
        cls = PREDICATE_REGISTRY[name]
        # 抽 __init__ args 让 LLM 知道怎么填
        import inspect
        try:
            sig = inspect.signature(cls.__init__)
            args = [p for p in sig.parameters.values()
                    if p.name not in ('self',)]
            args_str = ', '.join(
                f'{p.name}'
                + (f'={p.default!r}' if p.default is not inspect.Parameter.empty else '')
                for p in args
            )
        except Exception:
            args_str = '...'
        # 取一份 description (通过 instance.describe(), 用默认值实例化)
        # 失败 (无默认参数) 就只显示名字 + arg signature
        try:
            inst = cls()
            desc = inst.describe()
        except Exception:
            desc = ''
        if desc:
            lines.append(f'  - type="{name}"({args_str}): {desc}')
        else:
            lines.append(f'  - type="{name}"({args_str})')
    lines.append("")
    lines.append("Composite (always recursive on `args`):")
    lines.append('  - type="AND", args=[<predicate1>, <predicate2>, ...]')
    lines.append('  - type="OR",  args=[<p1>, <p2>, ...]')
    lines.append('  - type="NOT", arg=<predicate>')
    return '\n'.join(lines)


def heuristic_predicate_from_text(text: str) -> Optional[Predicate]:
    """从自然语言尝试启发式推断 predicate. LLM parser 未上前的兜底.

    例:
      "明早醒了" → WakeFirstActive AND TimeAfter("06:00")
      "导出完视频" → ProcessExited("Adobe Premiere Pro.exe")
    """
    if not text:
        return None
    t = text.lower()
    children: List[Predicate] = []
    # [β.5.19-B] 用 vocab-driven keyword (memory_pool/predicate_keywords.json)
    # mtime cache, Sir 加新词不动代码即可生效
    _wake = get_predicate_keywords('wake')
    _export = get_predicate_keywords('export')
    _premiere = get_predicate_keywords('premiere')

    if any(k in t for k in _wake):
        children.append(WakeFirstActive())
        children.append(TimeAfter('06:00'))

    if any(k in t for k in _export):
        # 优先匹配 Premiere; 也接受 generic
        target = 'Adobe Premiere Pro.exe' if any(k in t for k in _premiere) \
            else 'Adobe Premiere Pro.exe'
        children.append(ProcessExited(target, max_recent_s=900))
        children.append(IdleFor(30))

    if not children:
        return None
    if len(children) == 1:
        return children[0]
    return AndPredicate(*children)
