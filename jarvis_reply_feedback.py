# -*- coding: utf-8 -*-
"""[β.5.43-D / 2026-05-20] Reply Feedback — Sir 评 Jarvis reply 反馈通道.

Sir 17:10 真理: "Sir 评 Jarvis reply 的显式反馈通道". Sir 在 dashboard 一键
👍/👎/✏️ 评 Jarvis 刚说的话, 写 memory_pool/reply_feedback.jsonl. 主脑 prompt
注入 [SIR LAST REPLY FEEDBACK / 24h] block, 主脑下轮 reply 看 Sir 上次评价
调 tone.

Schema (jsonl append-only):
  {"ts": ..., "iso": "2026-05-20T17:30:00",
   "reply_excerpt": "I'll do that, Sir...",
   "verdict": "good|bad|edit|silent_wanted",
   "sir_note": "太啰嗦"}

verdict 含义:
  - 'good': 👍 Sir 喜欢, tone/length 都对
  - 'bad': 👎 不喜欢, 但没具体说什么
  - 'edit': Sir 改了文本 (sir_note 含改后版本)
  - 'silent_wanted': Sir 觉得这条不该说

主脑用法: 看最近 5 条 feedback, identify pattern (e.g. 多个 bad 都是 reply 过长) → 调整下轮 tone.

test: tests/_test_p0_plus_20_beta543_reply_feedback.py
"""
from __future__ import annotations

import json
import os
import time
from typing import List, Optional


ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(ROOT, 'memory_pool', 'reply_feedback.jsonl')

VALID_VERDICTS = ('good', 'bad', 'edit', 'silent_wanted')


def log_reply_feedback(reply_excerpt: str, verdict: str,
                        sir_note: str = '',
                        path: Optional[str] = None) -> bool:
    """Sir 在 dashboard 评 reply. Append-only jsonl."""
    if verdict not in VALID_VERDICTS:
        return False
    p = path or DEFAULT_PATH
    entry = {
        'ts': time.time(),
        'iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'reply_excerpt': str(reply_excerpt or '')[:500],
        'verdict': verdict,
        'sir_note': str(sir_note or '')[:300],
    }
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return True
    except Exception:
        return False


def get_recent_reply_feedback(hours: float = 24.0,
                                limit: int = 10,
                                path: Optional[str] = None) -> List[dict]:
    """主脑 prompt assembler 用. 最近 hours 内的 reply feedback."""
    p = path or DEFAULT_PATH
    entries = []
    try:
        if not os.path.exists(p):
            return []
        with open(p, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        return []
    cutoff = time.time() - hours * 3600
    recent = [e for e in entries if float(e.get('ts', 0)) >= cutoff]
    return recent[-limit:]


def format_for_prompt(entries: List[dict], max_chars: int = 600) -> str:
    """渲染 feedback 给主脑 prompt 看."""
    if not entries:
        return ''
    lines = ['[SIR LAST REPLY FEEDBACK / 24h]']
    lines.append('  Sir 评了你这些 reply, 学习他的偏好:')
    for e in entries[-5:]:  # 最多 5 条
        v = e.get('verdict', '?')
        excerpt = (e.get('reply_excerpt', '') or '')[:60]
        note = e.get('sir_note', '')
        verdict_emoji = {
            'good': '👍', 'bad': '👎',
            'edit': '✏️', 'silent_wanted': '🤐',
        }.get(v, '?')
        line = f"  - {verdict_emoji} [{v}] \"{excerpt}...\""
        if note:
            line += f" — Sir 说: \"{note[:80]}\""
        lines.append(line)
    out = '\n'.join(lines)
    if len(out) > max_chars:
        out = out[:max_chars - 10].rstrip() + '\n…'
    return out
