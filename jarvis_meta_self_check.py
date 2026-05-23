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
    # 🆕 [P5-fix20-B2 / 2026-05-22] commitments 列表 — 主脑承认本轮承诺哪些 mutation
    # IntegrityWatcher 看 commitments vs 真 tool_called 数, 差异 = '嘴上说没真做'.
    # e.g. ['note', 'remember 8 cups goal', 'hold dashboard 72h']
    commitments: List[str] = field(default_factory=list)
    raw_line: str = ''                                   # 原始 [META] 行 (debug)
    parse_ok: bool = False                              # parse 成功?

    def to_dict(self) -> Dict[str, Any]:
        return {
            'evidence': list(self.evidence),
            'reaction': self.reaction,
            'skip_alert': bool(self.skip_alert),
            'note': self.note,
            'commitments': list(self.commitments),
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
        # 🆕 [P5-fix20-B2 / 2026-05-22] commitments — 'a;b;c' or 'a,b,c' (分号优先, 防 note 内有逗号)
        co_str = kv_dict.get('commitments', '').strip()
        if co_str and co_str.lower() not in ('none', '[]', '-'):
            sep = ';' if ';' in co_str else ','
            meta.commitments = [c.strip()[:120] for c in co_str.split(sep)
                                  if c.strip() and c.strip().lower() not in ('none', '-')]
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
    # 🆕 [P5-fix54 / 2026-05-23 15:48] evidence_resolved — 按 prefix 分组 evidence IDs
    # debug 神器: Sir 看 'main_brain_meta_dump.py --evidence sensor' 找哪些 reply 用了 sensor.
    # 配合 PromptBuilder block ID 标准, 端到端 trace 主脑 reply ← 源 block 的关系.
    try:
        _resolved: Dict[str, List[str]] = {}
        for ev in (meta.evidence or []):
            if not isinstance(ev, str) or ':' not in ev:
                continue
            prefix, _, suffix = ev.partition(':')
            prefix = prefix.strip().lower()
            suffix = suffix.strip()
            if not prefix:
                continue
            _resolved.setdefault(prefix, []).append(suffix)
        payload['evidence_resolved'] = _resolved
    except Exception:
        pass
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


# ============================================================
# 🆕 [P5-fix20-B2 / 2026-05-22] commitments vs mutation 检查
# Sir 14:32 真测痛点: 主脑嘴上说"我已经记下了"但 IntentResolver 0 tool_called.
# 此函数比对 META.commitments vs 本 turn 的真 tool_called 数, mismatch =
# "嘴上说没真做". 主脑下轮 prompt 看 [COMMITMENT MISMATCH] block, 自决撤回 or 补做.
# ============================================================

def check_commitments_vs_mutations(turn_id: str,
                                     within_seconds: float = 60.0,
                                     event_bus=None,
                                     audit_path: Optional[str] = None
                                     ) -> Dict[str, Any]:
    """对比 META.commitments vs 本 turn 真 tool_called.

    Args:
      turn_id: 要检查的 turn
      within_seconds: SWM 事件回看窗口
      event_bus: 注入用 (None = get_event_bus())
      audit_path: 测试用

    Returns:
      {
        'turn_id': str,
        'commitments': List[str],           # 主脑嘴上说的
        'commitments_count': int,
        'mutations_ok': int,                # 真 tool_called ok=True
        'mutations_fail': int,              # 真 tool_called ok=False
        'mutations_via': List[str],         # llm / fast_path
        'mismatch': bool,                   # commitments > 0 但 mutations_ok < commitments
        'status': 'ok' / 'partial' / 'mismatch' / 'no_commitments' / 'no_meta',
        'reason': str (人话原因),
      }
    """
    result: Dict[str, Any] = {
        'turn_id': turn_id,
        'commitments': [],
        'commitments_count': 0,
        'mutations_ok': 0,
        'mutations_fail': 0,
        'mutations_via': [],
        'mismatch': False,
        'status': 'no_meta',
        'reason': '',
    }
    if not turn_id:
        result['reason'] = 'no turn_id'
        return result

    # 1. 读 META audit
    meta = find_meta_for_turn(turn_id, audit_path=audit_path)
    if not meta:
        result['reason'] = 'no META audit for this turn'
        return result
    commitments = meta.get('commitments', []) or []
    result['commitments'] = list(commitments)
    result['commitments_count'] = len(commitments)
    if not commitments:
        result['status'] = 'no_commitments'
        result['reason'] = '主脑本轮 commitments=none (无 mutation 承诺)'
        return result

    # 2. 收同 turn 的 tool_called events (from IntentResolver)
    bus = event_bus
    if bus is None:
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
        except Exception:
            bus = None
    if bus is None:
        result['status'] = 'mismatch'
        result['mismatch'] = True
        result['reason'] = f'no event_bus, 无法验证 commitments {commitments}'
        return result

    try:
        events = bus.recent_events(within_seconds=within_seconds,
                                       types={'tool_called'}) or []
    except Exception:
        events = []
    ok_n = 0
    fail_n = 0
    via_list: List[str] = []
    for ev in events:
        meta_ev = ev.get('metadata') or {}
        if meta_ev.get('turn_id') != turn_id:
            continue
        via_list.append(meta_ev.get('via', '?'))
        if meta_ev.get('ok'):
            ok_n += 1
        else:
            fail_n += 1
    result['mutations_ok'] = ok_n
    result['mutations_fail'] = fail_n
    result['mutations_via'] = via_list

    # 3. 判断 mismatch
    if ok_n >= len(commitments):
        result['status'] = 'ok'
        result['reason'] = (f'commitments {len(commitments)} 全部对得上 '
                              f'tool_called ok={ok_n}')
    elif ok_n > 0:
        result['status'] = 'partial'
        result['mismatch'] = True
        result['reason'] = (f'commitments={len(commitments)} 但仅 {ok_n} 个 '
                              f'tool_called ok (fail={fail_n}) → 部分嘴上说没真做')
    else:
        result['status'] = 'mismatch'
        result['mismatch'] = True
        result['reason'] = (f'commitments={len(commitments)} 但 0 tool_called ok '
                              f'(fail={fail_n}) → 完全嘴上说没真做')

    return result


def render_commitment_mismatch_block(turn_id: str,
                                       within_seconds: float = 60.0,
                                       audit_path: Optional[str] = None) -> str:
    """渲染 [COMMITMENT MISMATCH] block 给主脑下轮 prompt 看.

    仅 mismatch=True 时返非空 str, 否则空.
    """
    chk = check_commitments_vs_mutations(turn_id,
                                            within_seconds=within_seconds,
                                            audit_path=audit_path)
    if not chk.get('mismatch'):
        return ''
    co = chk['commitments']
    co_str = '; '.join(f'"{c}"' for c in co[:5])
    if len(co) > 5:
        co_str += f' ... (+{len(co)-5} more)'
    lines = [
        '[COMMITMENT MISMATCH — P5-fix20-B2 / Sir 14:32 痛点: 嘴上说没真做]',
        f'  上一轮 (turn={turn_id[:24]}) 你的 [META] 写了 {chk["commitments_count"]} 条 commitments:',
        f'    {co_str}',
        f'  但 IntentResolver 真 tool_called ok={chk["mutations_ok"]} / '
        f'fail={chk["mutations_fail"]}.',
        f'  → {chk["reason"]}',
        '',
        '  你本轮选择 (准则 5 言出必行):',
        '    A. 主动 inline acknowledge "Sir, 我刚说的 X 没真生效 (LLM 挂/tool fail), 我现在重试 / 您要不要手动 Y" — 不要装没说.',
        '    B. 如果当时只是 verbal ack / empathize 而非真承诺 mutation, 这轮 [META] commitments=none, 不再列已落空的项.',
        '  ❌ 错误反应: 装没说过 / 再次列同样 commitments 但仍不做.',
    ]
    return '\n'.join(lines)


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
