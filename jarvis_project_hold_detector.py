# -*- coding: utf-8 -*-
"""[β.5.46-fix18 / 2026-05-22] Project Hold Detector — Sir 真测 BUG fix

Sir 11:39 真测痛点:
  > "驾照考试我说了不用在意, 最近, 但是贾维斯好像没有记住"

Sir 5/20 + 5/22 反复说 "驾照放一放/hold off/暂停/搁置", SmartNudge 仍 fire
dormant_project. Root cause: ProjectTimeline 不感知 Sir hold 信号. 治本 (3
数据源 refactor):
  - Phase A: vocab `memory_pool/project_hold_phrases_vocab.json` (持久化 phrase)
  - Phase B: ProjectTimeline 加 `held_until_ts` 列 + migration
  - Phase C: hippo.hold_project(name, hours) + find_project_by_keyword(kw)
  - Phase D: get_dormant_projects 过滤 held_until_ts > now
  - Phase E: tool_project_hold + IntentResolver 调度
  - Phase F (本模块): detect_and_publish — vocab 命中 + project 命中 → publish
                     'sir_intent_project_hold_candidate' SWM event, 主脑自决.

准则 6 三维耦合:
  - 数据强耦合: publish 进 SWM ConversationEventBus
  - 行为弱耦合: 不直接 mutate, 让 IntentResolver 主脑自决调 tool_project_hold
  - 决策集中主脑: 主脑看 candidate + STM evidence + tool registry 自决

Sir 对话路径调用 (chat_bypass / worker reflect hook):
  detect_and_publish(cmd, jarvis_reply, turn_id, hippo, bus)
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Optional, List, Tuple, Dict

_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'project_hold_phrases_vocab.json'
)

_VOCAB_CACHE: Optional[List[Dict]] = None
_VOCAB_MTIME: float = 0.0
_VOCAB_LOCK = threading.Lock()


def _load_vocab() -> List[Dict]:
    """读 vocab + mtime cache reload (Sir 改 json 不必重启).

    准则 6 范式: source of truth = json, code 是 cache.
    """
    global _VOCAB_CACHE, _VOCAB_MTIME
    try:
        mtime = os.path.getmtime(_VOCAB_PATH) if os.path.exists(_VOCAB_PATH) else 0
    except Exception:
        mtime = 0
    with _VOCAB_LOCK:
        if _VOCAB_CACHE is not None and mtime == _VOCAB_MTIME:
            return _VOCAB_CACHE
        try:
            if not os.path.exists(_VOCAB_PATH):
                _VOCAB_CACHE = []
                _VOCAB_MTIME = mtime
                return _VOCAB_CACHE
            with open(_VOCAB_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            phrases = data.get('phrases', []) or []
            # 仅 active state
            active = [p for p in phrases if p.get('state') == 'active']
            _VOCAB_CACHE = active
            _VOCAB_MTIME = mtime
            return _VOCAB_CACHE
        except Exception:
            _VOCAB_CACHE = []
            _VOCAB_MTIME = mtime
            return _VOCAB_CACHE


def detect_hold_phrase(text: str) -> Optional[Dict]:
    """检测文本是否含 hold phrase. 返第一条命中的 vocab item (含 default_hours).

    Args:
      text: Sir cmd 或 Jarvis reply.
    Returns:
      命中的 phrase dict (含 'phrase' / 'default_hours' / 'lang' / 'id') 或 None.
    """
    if not text or not str(text).strip():
        return None
    text_l = str(text).lower()
    vocab = _load_vocab()
    for item in vocab:
        phrase = (item.get('phrase') or '').lower().strip()
        if phrase and phrase in text_l:
            return item
    return None


def detect_and_publish(cmd: str = '', jarvis_reply: str = '',
                        turn_id: str = '',
                        hippocampus=None,
                        event_bus=None) -> Optional[Dict]:
    """主入口. 检测 cmd / jarvis_reply 含 hold phrase + project keyword,
    publish SWM candidate 让主脑下轮决定调 tool_project_hold.

    Args:
      cmd: Sir 本轮原话
      jarvis_reply: Jarvis 本轮 reply (Sir 同意 hold 时 Jarvis 自己说 "I shall suppress nudges" 也算)
      turn_id: 本轮 trace id
      hippocampus: jarvis_hippocampus.Hippocampus 实例 (含 find_project_by_keyword)
      event_bus: jarvis_utils.ConversationEventBus 实例
    Returns:
      命中时返 candidate dict 摘要, 不命中返 None.
    """
    if not (cmd or jarvis_reply):
        return None
    if hippocampus is None or event_bus is None:
        return None
    # 1. 检测 hold phrase (cmd 优先, jarvis reply 次之)
    text_for_phrase = (cmd or '') + ' ' + (jarvis_reply or '')
    phrase_hit = detect_hold_phrase(text_for_phrase)
    if not phrase_hit:
        return None
    # 2. 找 project keyword — 从 cmd 里抽 (Sir 主语决定项目)
    project_name = _extract_project_name(cmd, hippocampus)
    if not project_name:
        # cmd 没找到, 试 jarvis reply (Sir 同意 Jarvis suppress 时 reply 含 project)
        project_name = _extract_project_name(jarvis_reply, hippocampus)
    if not project_name:
        return None
    # 3. publish SWM candidate
    try:
        candidate = {
            'project_name': project_name,
            'phrase_hit': phrase_hit.get('phrase'),
            'phrase_id': phrase_hit.get('id'),
            'default_hours': phrase_hit.get('default_hours', 72),
            'turn_id': turn_id,
            'cmd_excerpt': str(cmd or '')[:120],
        }
        event_bus.publish(
            etype='sir_intent_project_hold_candidate',
            description=(
                f"Sir hold phrase '{phrase_hit.get('phrase')}' + project "
                f"'{project_name}' detected; default {phrase_hit.get('default_hours', 72)}h"
            ),
            source='project_hold_detector',
            metadata={
                'confidence': 0.85,  # vocab + project 双命中 = 高置信
                'judgement': candidate,
            },
            ttl=300.0,  # 5min TTL — IntentResolver 看到下轮 tool_project_hold
        )
        try:
            from jarvis_utils import bg_log
            bg_log(
                f"⏸️ [ProjectHoldDetector] candidate published: "
                f"project='{project_name}' phrase='{phrase_hit.get('phrase')}' "
                f"hours={phrase_hit.get('default_hours', 72)} turn={turn_id}"
            )
        except Exception:
            pass
        return candidate
    except Exception:
        return None


def _extract_project_name(text: str, hippocampus) -> Optional[str]:
    """从 text 抽 project_name. 简单: 用 hippo.find_project_by_keyword 模糊查
    已知 active project name 的前缀/子串.

    准则 6: 不写死项目名, 全依赖 hippo 的真实数据. Sir 加新项目, 自动适配.
    """
    if not text or hippocampus is None:
        return None
    if not hasattr(hippocampus, 'find_project_by_keyword'):
        return None
    # 先试整句, 再试 split 后的每个 token (中英文都 try)
    for candidate_kw in _gen_keyword_candidates(text):
        try:
            name = hippocampus.find_project_by_keyword(candidate_kw)
            if name:
                return name
        except Exception:
            continue
    return None


def _gen_keyword_candidates(text: str) -> List[str]:
    """从 text 拆出可能的 project keyword. 简单分词, 不依赖 jieba.

    🩹 [β.5.46-fix18-bugfix / 2026-05-22] 老 _gen 用 re.findall {2,6} non-overlapping
    匹配, "所以驾照考试" 整段 6 字会被一次性 match → 子串 "驾照" 提不出来.
    修: 中文段取所有 2-4 字 substring (sliding window), 让 SQL LIKE 模糊匹更精准.

    返回 candidates 按命中可能性排序 (短词优先 — '驾照' 比 '驾照考试' 更通用).
    """
    if not text:
        return []
    text = str(text).strip()
    if not text:
        return []
    candidates: List[str] = []
    seen = set()

    def _add(c: str):
        if c and c not in seen:
            seen.add(c)
            candidates.append(c)

    # 1. 整句 (匹配 'driver's license preparation' 整体)
    _add(text)

    import re
    # 2. 中文连续段抽出后, 取所有 2-4 字 sliding substring.
    # 例: "所以驾照考试先放一放呢" → ['所以','驾照','照考','考试',
    #   '所以驾','以驾照','驾照考','照考试',...] 让 hippo SQL LIKE 模糊匹 '驾照科一复习' 命中.
    zh_segments = re.findall(r'[\u4e00-\u9fff]+', text)
    for seg in zh_segments:
        seg_len = len(seg)
        # 2-4 字 substring (sliding window)
        for win in (2, 3, 4):
            if seg_len < win:
                continue
            for i in range(seg_len - win + 1):
                _add(seg[i:i + win])
        # 整段也加 (e.g. '驾照科一')
        if seg_len >= 2:
            _add(seg)

    # 3. 英文 token (适配 'driver / license / interview / cursor')
    en_tokens = re.findall(r'\b[a-zA-Z][a-zA-Z\-]{2,30}\b', text.lower())
    en_blacklist = {'about', 'the', 'and', 'with', 'this', 'that', 'have',
                     'will', 'would', 'should', 'could', 'must', 'shall',
                     'currently', 'preparation', 'recently', 'previously',
                     'occupying', 'certainly', 'wait', 'theory', 'top',
                     'your', 'stack', 'shall', 'suppress', 'nudges', 'the'}
    for t in en_tokens:
        if t not in en_blacklist:
            _add(t)

    # 4. 短的优先 (2-4 字中文 token 排前面)
    candidates.sort(key=lambda x: (len(x), x))
    return candidates[:40]  # cap 40 防爆 query (粗扩张了)
