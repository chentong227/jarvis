# -*- coding: utf-8 -*-
"""[P0+20-β.2.7.3 / 2026-05-17] Jarvis Self-Promise Detector

灵魂工程"承诺必行"原则的关键补齐：

之前 Sir 实测发现的耦合缺陷:
| 谁说"我会 X" | 走的路径 | 结果 |
|---|---|---|
| Sir 说 | Gatekeeper LLM → commitment_watcher → 定时 nudge | 主动提醒 |
| Jarvis 说 | 只 extract_open_threads 注入下一轮 prompt | **没主动定时，Sir 不开口永远不触发** |

本模块补齐 Jarvis 自己说的话也算数，与 Sir 的承诺平等地走 commitment_watcher 持久化 + 定时 nudge。

设计原则（性能第一）:
- 纯本地 regex（不调 LLM）, ~50us / call
- fire-and-forget 后台线程，主对话路径零阻塞
- 容错：任何异常静默丢弃，不影响主路径
- 去重：同一 reply 30s 内只检测一次（防重复入队）

接入路径:
- chat_bypass.stream_chat 末尾 (主对话)
- chat_bypass.stream_nudge 末尾 (SmartNudge / Conductor / CommitmentWatcher / ReturnSentinel)
- chat_bypass.stream_chat_local 末尾 (local fallback)
- chat_bypass.stream_chat_cloud_followup 末尾 (cloud followup)
- sentinels._speak_mail 末尾 (Chronos mail)
"""
from __future__ import annotations

import re
import threading
import time
from typing import List, Dict, Optional


# ============================================================
# Regex 模式（编译一次缓存）
# ============================================================

# 英文承诺 + 时间锚
# 例: "I shall hold you to that 13:05 deadline" / "I will remind you at 11pm"
#     "I'll check on you in 30 minutes" / "I'm going to follow up tomorrow"
_EN_PROMISE_PATTERNS = [
    # 直接 "I will/shall/'ll X (at|by|in|on|before) <time>"
    re.compile(
        r"(?P<subject>\bi\s+(?:will|shall|'ll|am\s+going\s+to|am\s+about\s+to))\s+"
        r"(?P<action>[^.!?]{3,80}?)\s+"
        r"(?P<prep>at|by|in|on|before|until|after|around|near)\s+"
        r"(?P<time>\d{1,2}(?::\d{2})?(?:\s*[ap]m\.?)?|tonight|tomorrow|this\s+evening|today|now)",
        re.IGNORECASE,
    ),
    # "I'll hold you to X" (无 prep, X 含时间)
    re.compile(
        r"(?P<subject>\bi\s+(?:will|shall|'ll))\s+(?P<action>hold\s+you\s+to[^.!?]*?)\s+"
        r"(?P<time>\d{1,2}:\d{2}|\d{1,2}\s*[ap]m\.?)",
        re.IGNORECASE,
    ),
    # "remind you at X" / "monitor you until X" / "watch over you until X"
    re.compile(
        r"(?P<subject>\bi\s+(?:will|shall|'ll))\s+(?P<action>(?:remind|monitor|watch|check|follow\s+up|ensure)[^.!?]*?)\s+"
        r"(?:at|by|until|in|around)\s+(?P<time>\d{1,2}(?::\d{2})?(?:\s*[ap]m\.?)?|tonight|tomorrow)",
        re.IGNORECASE,
    ),
    # "I'll check on you in N minutes" — 相对时间锚（兼容 "I'll" 缩写 无 space）
    re.compile(
        r"(?P<subject>\bi\s*(?:will|shall|'ll))\s+(?P<action>[^.!?]{3,60}?)\s+"
        r"in\s+(?P<time>\d+\s*(?:min(?:ute)?s?|hours?|hrs?))",
        re.IGNORECASE,
    ),
]

# 中文承诺 + 时间锚 — 两个 pattern 覆盖两种语序：
# Pattern A: subject + action(动词) + time   "我会监督您 13:05 准时休息"
# Pattern B: subject + time + action(动词)   "我会在 23:30 提醒你"
# 关键：action 必须含真正的动作动词，不能是单字介词"在/到/于"
_ZH_VERB_GROUP = (
    r"(?:监督|提醒|催|看|盯|跟进|留意|关注|去|帮|做|让你|拉你|确保|"
    r"准时|按时|检查|核对|跟进|追问|核实|叫(?:醒)?|唤(?:醒)?|"
    r"汇报|更新|通知|告诉|讲|说|review|check|监测|警告)"
)
_ZH_TIME_GROUP = (
    r"\d{1,2}[:：]\d{2}|"
    r"[一二三四五六七八九十两\d]{1,3}\s*点(?:[一二三四五六七八九十两半\d]{0,3}\s*分?)?|"
    r"今晚|今夜|明早|明天(?:早上|上午|中午|下午|晚上)?|后天|大后天"
)
_ZH_PROMISE_PATTERNS = [
    # Pattern A: 主语 + 动词在前 + 可选介词 + 时间
    re.compile(
        r"(?P<subject>我(?:会|要|将|得|打算|答应))\s*"
        r"(?P<action>" + _ZH_VERB_GROUP + r"\s*[您你]?(?:[^。！？]{0,15}?))\s*"
        r"(?:在|到|于)?\s*"
        r"(?P<time>" + _ZH_TIME_GROUP + r")"
    ),
    # Pattern B: 主语 + 中间词 + 时间 + 动词
    re.compile(
        r"(?P<subject>我(?:会|要|将|得|打算|答应))\s*"
        r"(?:在|到|于)?\s*"
        r"(?P<time>" + _ZH_TIME_GROUP + r")"
        r"\s*(?:就|再|准时|准点|的时候)?\s*"
        r"(?P<action>" + _ZH_VERB_GROUP + r"(?:[您你]?[^。！？]{0,20}?))"
    ),
]


# 拒绝模式：reply 不像承诺的（避免误判）
_REJECT_PATTERNS = [
    # 反问/疑问
    re.compile(r"^\s*(?:would\s+you|do\s+you|shall\s+i\?|do\s+i|may\s+i|can\s+i)", re.IGNORECASE),
    # 报告自己已经做了过去 action（不是 future 承诺）
    re.compile(r"\bi\s+(?:have|just|already)\s+(?:checked|monitored|reminded|set)", re.IGNORECASE),
    re.compile(r"我(?:已经|刚才|刚刚)(?:提醒|监督|催)了", re.IGNORECASE),
]


# ============================================================
# Detector
# ============================================================

class SelfPromiseDetector:
    """检测 Jarvis 自己 reply 里的承诺 + 注册到 commitment_watcher。"""

    DEDUP_WINDOW_SEC = 30.0

    def __init__(self):
        self._recent = []  # [(reply_hash, ts), ...]
        self._lock = threading.Lock()
        self._stats = {'detected': 0, 'registered': 0, 'rejected': 0, 'dedup_skip': 0}

    def detect(self, jarvis_reply: str) -> List[Dict[str, str]]:
        """从 reply 提取所有承诺。返回 [{description, deadline_str, raw_match}, ...]"""
        if not jarvis_reply or len(jarvis_reply.strip()) < 10:
            return []

        # 拒绝模式：reply 整体不像承诺
        text = jarvis_reply.strip()
        for rej in _REJECT_PATTERNS:
            if rej.search(text):
                # 整段是疑问/过去时 → 通常不会有真承诺，但仍跑 patterns 以防局部含
                pass  # 不直接 return，让模式自己 match

        results = []

        # 英文 patterns
        for pat in _EN_PROMISE_PATTERNS:
            for m in pat.finditer(text):
                action = m.groupdict().get('action', '').strip()
                time_str = m.groupdict().get('time', '').strip()
                if not action or not time_str:
                    continue
                # 局部 reject：action 含反问词
                if re.search(r'\b(?:would|could|should\s+i|may\s+i|do\s+i)\b', action, re.IGNORECASE):
                    continue
                # 描述：subject + action
                desc = f"{m.group('subject').strip()} {action}".strip()
                if len(desc) >= 5:
                    results.append({
                        'description': desc[:120],
                        'deadline_str': time_str[:30],
                        'raw_match': m.group(0)[:150],
                        'lang': 'en',
                    })

        # 中文 patterns
        for pat in _ZH_PROMISE_PATTERNS:
            for m in pat.finditer(text):
                action = m.groupdict().get('action', '').strip()
                time_str = m.groupdict().get('time', '').strip()
                if not action or not time_str:
                    continue
                desc = f"{m.group('subject')}{action}".strip()
                if len(desc) >= 3:
                    results.append({
                        'description': desc[:120],
                        'deadline_str': time_str[:30],
                        'raw_match': m.group(0)[:150],
                        'lang': 'zh',
                    })

        return self._dedup_within_result(results)

    @staticmethod
    def _dedup_within_result(items: List[Dict]) -> List[Dict]:
        """同一 reply 里同 description 只保留一个，避免英中双语两次 match 同一承诺。"""
        seen = set()
        out = []
        for item in items:
            key = (item.get('description', '')[:50].lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def detect_and_register(self, jarvis_reply: str,
                             commitment_watcher=None,
                             turn_id: str = '') -> Dict:
        """fire-and-forget 用：检测 + 注册到 commitment_watcher。

        Returns dict {registered: int, detected: int, skipped_reason: str|None}
        """
        if not jarvis_reply:
            return {'registered': 0, 'detected': 0, 'skipped_reason': 'empty_reply'}

        # 去重：同 reply 30s 内不重复处理
        _hash = hash(jarvis_reply[:200])
        with self._lock:
            now = time.time()
            self._recent = [(h, t) for h, t in self._recent if now - t < self.DEDUP_WINDOW_SEC]
            if any(h == _hash for h, _ in self._recent):
                self._stats['dedup_skip'] += 1
                return {'registered': 0, 'detected': 0, 'skipped_reason': 'dedup'}
            self._recent.append((_hash, now))
            if len(self._recent) > 50:
                self._recent = self._recent[-30:]

        promises = self.detect(jarvis_reply)
        if not promises:
            return {'registered': 0, 'detected': 0, 'skipped_reason': 'no_match'}

        with self._lock:
            self._stats['detected'] += len(promises)

        registered = 0
        if commitment_watcher is None:
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"⚠️ [SelfPromise] 检测到 {len(promises)} 条 Jarvis 自承诺，"
                    f"但 commitment_watcher=None，跳过注册"
                )
            except Exception:
                pass
            return {'registered': 0, 'detected': len(promises),
                    'skipped_reason': 'no_watcher'}

        for p in promises:
            try:
                commitment_watcher.add_commitment(
                    description=p['description'],
                    deadline_str=p['deadline_str'],
                    user_text=jarvis_reply[:200],
                    is_future_task_confirmed=True,
                    source='self_promise',
                )
                registered += 1
                try:
                    from jarvis_utils import bg_log
                    bg_log(
                        f"📌 [SelfPromise] 注册 Jarvis 自承诺: "
                        f"'{p['description'][:60]}' deadline='{p['deadline_str']}' "
                        f"(lang={p['lang']} turn={turn_id or '?'})"
                    )
                except Exception:
                    pass
            except Exception as _add_err:
                try:
                    from jarvis_utils import bg_log
                    bg_log(
                        f"⚠️ [SelfPromise] add_commitment 失败: "
                        f"{type(_add_err).__name__}: {str(_add_err)[:80]}"
                    )
                except Exception:
                    pass

        with self._lock:
            self._stats['registered'] += registered

        return {'registered': registered, 'detected': len(promises), 'skipped_reason': None}

    def detect_and_register_async(self, jarvis_reply: str,
                                    commitment_watcher=None,
                                    turn_id: str = '') -> threading.Thread:
        """fire-and-forget thread 入口。主对话路径调这个，零阻塞。"""
        t = threading.Thread(
            target=self.detect_and_register,
            args=(jarvis_reply, commitment_watcher, turn_id),
            daemon=True,
            name=f'SelfPromiseDetector/{turn_id or "?"}'
        )
        t.start()
        return t

    def get_stats(self) -> Dict:
        with self._lock:
            return dict(self._stats)


# ============================================================
# 单例
# ============================================================

_DEFAULT_DETECTOR: Optional[SelfPromiseDetector] = None


def get_default_detector() -> SelfPromiseDetector:
    global _DEFAULT_DETECTOR
    if _DEFAULT_DETECTOR is None:
        _DEFAULT_DETECTOR = SelfPromiseDetector()
    return _DEFAULT_DETECTOR


def reset_default_detector_for_test() -> None:
    global _DEFAULT_DETECTOR
    _DEFAULT_DETECTOR = None
