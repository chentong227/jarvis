# -*- coding: utf-8 -*-
"""[P5-Layer1-fix19 / 2026-05-22] 主脑最小 thinking pass — META Self-Check parser

Sir 13:13 立: 主脑加 1 行 thinking pass. 反 Sir 真测 fix16/17/18 类
"主脑被外部信号推着说错话" 痛点 (3/5 BUG).

设计:
  - jarvis_directives.py meta_self_check_directive 教主脑 reply 末尾 emit 1 行
    [META] evidence=... reaction=... skip_alert=... note=...
  - 本模块 parse_meta(reply_text) 抽 META + 裁 Sir-facing text
  - publish 'main_brain_meta' SWM event 给 ClaimTracer / IntegrityWatcher 订阅
  - bg_log + audit jsonl trace ('jarvis 为什么这样说' debug 神器)

准则 6 三维耦合:
  - 数据强耦合: META 入 SWM, ClaimTracer/IntegrityWatcher 读 not grep
  - 行为弱耦合: parser 不 mutate, 只 publish; 订阅者自决
  - 决策集中主脑: SELF_CHECK 4 问主脑 LLM 自答, python 只 parse + trace

格式 (主脑 emit):
  [META] evidence=stm:turn_xxx,swm:cand_yyy reaction=voice skip_alert=no note=hold ack
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
# Constants
# ============================================================

_META_LINE_RE = re.compile(
    r'^\s*\[META\]\s+(.+?)\s*$',
    re.MULTILINE | re.IGNORECASE,
)

_KV_RE = re.compile(r'(\w+)\s*=\s*(\S.*?)(?=\s+\w+\s*=|\s*$)')

_AUDIT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'main_brain_meta_audit.jsonl'
)

_VALID_REACTIONS = {'voice', 'silent_text', 'silence'}
_VALID_SKIP_ALERT = {'yes', 'no'}


# ============================================================
# Data class
# ============================================================

@dataclass
class MetaSelfCheck:
    """主脑 1 行 [META] 解析结果."""

    evidence: List[str] = field(default_factory=list)  # ['stm:turn_xxx', 'swm:cand_yyy', ...]
    reaction: str = 'voice'                             # voice / silent_text / silence
    skip_alert: bool = False                            # 主脑明确拒绝道歉?
    note: str = ''                                       # 自由文本 note (<= 60 chars)
    raw_line: str = ''                                   # 原始 [META] 行 (debug)
    parse_ok: bool = False                              # parse 成功?

    def to_dict(self) -> Dict[str, Any]:
        return {
            'evidence': list(self.evidence),
            'reaction': self.reaction,
            'skip_alert': bool(self.skip_alert),
            'note': self.note,
            'raw_line': self.raw_line,
            'parse_ok': bool(self.parse_ok),
        }

    @property
    def has_evidence(self) -> bool:
        """主脑声明用了真 evidence (不是 'none')?"""
        if not self.evidence:
            return False
        if len(self.evidence) == 1 and self.evidence[0].lower().strip() == 'none':
            return False
        return True


# ============================================================
# Parser
# ============================================================

def parse_meta(reply_text: str) -> Tuple[str, MetaSelfCheck]:
    """从主脑 reply 抽 [META] 行 + 裁掉 (返干净 Sir-facing text + MetaSelfCheck obj).

    主脑可能多行 emit (multiple [META] 行) — 只取最后 1 行 (主脑 finalize 那行).
    [META] 行不存在 → parse_ok=False, sir_text 原样返.

    Args:
      reply_text: 主脑原始 reply (含 [META] 末行 + ---ZH--- block + ...)
    Returns:
      (sir_facing_text, meta_obj)
      sir_facing_text: 已裁 [META] 行的 Sir 可见 text
      meta_obj: parse_ok=True 表示成功 parse
    """
    if not reply_text or not isinstance(reply_text, str):
        return reply_text or '', MetaSelfCheck()

    matches = list(_META_LINE_RE.finditer(reply_text))
    if not matches:
        return reply_text, MetaSelfCheck()

    # 取最后 1 个 (主脑 finalize)
    last = matches[-1]
    raw_line = last.group(0).strip()
    body = last.group(1).strip()

    # 裁掉所有 [META] 行 (防多次 emit 残留)
    sir_text = _META_LINE_RE.sub('', reply_text).rstrip()

    # 解析 kv pairs
    meta = MetaSelfCheck(raw_line=raw_line)
    try:
        kv_dict = _parse_kv_body(body)
        # evidence — comma list
        ev_str = kv_dict.get('evidence', '').strip()
        if ev_str:
            meta.evidence = [e.strip() for e in ev_str.split(',') if e.strip()]
        # reaction
        reaction = kv_dict.get('reaction', 'voice').strip().lower()
        meta.reaction = reaction if reaction in _VALID_REACTIONS else 'voice'
        # skip_alert
        sa = kv_dict.get('skip_alert', 'no').strip().lower()
        meta.skip_alert = (sa == 'yes' or sa == 'true' or sa == '1')
        # note
        meta.note = kv_dict.get('note', '').strip()[:60]
        meta.parse_ok = True
    except Exception:
        meta.parse_ok = False

    return sir_text, meta


def _parse_kv_body(body: str) -> Dict[str, str]:
    """解析 'k1=v1 k2=v2 ...' (v 内可含空格直到下个 k='). 简单状态机.

    输入: 'evidence=a,b reaction=voice skip_alert=no note=long note text here'
    输出: {'evidence': 'a,b', 'reaction': 'voice', 'skip_alert': 'no',
            'note': 'long note text here'}
    """
    if not body:
        return {}
    out: Dict[str, str] = {}
    # split on whitespace then re-merge until next k=
    tokens = body.split()
    cur_key: Optional[str] = None
    cur_val_parts: List[str] = []
    for tok in tokens:
        if '=' in tok:
            # flush previous
            if cur_key is not None:
                out[cur_key] = ' '.join(cur_val_parts).strip()
            k, _, v = tok.partition('=')
            cur_key = k.strip().lower()
            cur_val_parts = [v.strip()] if v else []
        else:
            if cur_key is not None:
                cur_val_parts.append(tok)
    if cur_key is not None:
        out[cur_key] = ' '.join(cur_val_parts).strip()
    return out


# ============================================================
# SWM publish + audit jsonl
# ============================================================

def publish_meta(meta: MetaSelfCheck, turn_id: str = '',
                  user_input: str = '',
                  event_bus=None) -> bool:
    """publish 'main_brain_meta' SWM event + append audit jsonl.

    ClaimTracer / IntegrityWatcher 订阅. Debug 用 — Sir 看 audit 知 jarvis 当时
    评估了什么 evidence / reaction.
    """
    if not meta or not meta.parse_ok:
        return False
    payload = meta.to_dict()
    payload['turn_id'] = turn_id or ''
    payload['ts'] = time.time()
    payload['iso'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    payload['user_input_excerpt'] = (user_input or '')[:120]

    # 1. SWM publish
    try:
        if event_bus is None:
            from jarvis_utils import get_event_bus
            event_bus = get_event_bus()
        if event_bus is not None:
            event_bus.publish(
                etype='main_brain_meta',
                description=(
                    f"main brain META: ev={len(meta.evidence)} "
                    f"reaction={meta.reaction} "
                    f"skip_alert={'Y' if meta.skip_alert else 'N'}"
                ),
                source='meta_self_check',
                metadata=payload,
                ttl=600.0,
            )
    except Exception:
        pass

    # 2. audit jsonl append (debug 神器)
    try:
        os.makedirs(os.path.dirname(_AUDIT_PATH), exist_ok=True)
        with open(_AUDIT_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(payload, ensure_ascii=False) + '\n')
    except Exception:
        pass

    # 3. bg_log
    try:
        from jarvis_utils import bg_log
        bg_log(
            f"🧠 [SelfCheck/META] turn={turn_id} ev={len(meta.evidence)} "
            f"reaction={meta.reaction} skip_alert={'Y' if meta.skip_alert else 'N'} "
            f"note='{meta.note[:40]}'"
        )
    except Exception:
        pass

    return True


def read_recent_meta(limit: int = 20,
                      audit_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """读最近 N 条 META audit. CLI / IntegrityWatcher / Sir debug 用."""
    path = audit_path or _AUDIT_PATH
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def find_meta_for_turn(turn_id: str,
                        audit_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """按 turn_id 查 META audit 条目. ClaimTracer / IntegrityWatcher 主用.

    Returns:
      最新 1 条 dict (turn_id 命中) 或 None.
    """
    if not turn_id:
        return None
    path = audit_path or _AUDIT_PATH
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            # 倒读, 找最新匹配
            for line in reversed(f.readlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get('turn_id') == turn_id:
                        return obj
                except Exception:
                    continue
    except OSError:
        return None
    return None
