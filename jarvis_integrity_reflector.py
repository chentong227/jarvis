# -*- coding: utf-8 -*-
"""
[P0+20-β.4.5 / 2026-05-18] INTEGRITY_STACK Session 4 — L7 IntegrityReflector

模块职责 (与 jarvis_claim_tracer 边界):
  - jarvis_claim_tracer: 同步路径 — 抽 claim / trace evidence / write audit jsonl /
                         in-memory _CLAIM_STATS counter (累计统计)
  - jarvis_integrity_reflector (本文件): 异步路径 / daemon —
      (1) ClaimStatsDumper: 60s tick dump _CLAIM_STATS → memory_pool/claim_stats.json
          (跨进程持久化, dashboard L6 跨进程读 verify_rate)
      (2) IntegrityReflector (β.4.5.2 后续): LLM-propose vocab / directive / evidence_kind
          基于 7d audit jsonl, 写各 review queue, Sir 拍板才生效

设计准则:
  - 准则 5 言出必行: 跨进程数据流必须 trace 到真文件 (atomic write)
  - 准则 6: 无新硬编码 vocab, 只是 in-memory counter 镜像到 disk + LLM 反思 (β.4.5.2)
  - 准则 6.5: dump 失败 fail-safe (return False 不 raise), 路径可注入 (testcase)
  - 准则 7 (β.3.5): claim_tracer 职责单一只做 trace, 反思/持久化分到本文件
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Optional


# ============================================================
# β.4.5.1: ClaimStatsDumper — _CLAIM_STATS 跨进程持久化
# ============================================================

_CLAIM_STATS_DUMP_PATH = os.path.join('memory_pool', 'claim_stats.json')


def dump_claim_stats(path: Optional[str] = None) -> bool:
    """把 jarvis_claim_tracer.get_stats() 当前快照写到 disk (atomic).

    schema: total_replies_traced / total_claims / total_unverified / dumped_at / dumped_iso
    失败 (路径不可写 / OSError) 返 False 不 raise.

    跨模块依赖 (lazy import 避免循环):
      jarvis_claim_tracer.get_stats() — 返 dict copy of _CLAIM_STATS
    """
    p = path or _CLAIM_STATS_DUMP_PATH
    try:
        from jarvis_claim_tracer import get_stats
        snapshot = get_stats()
    except Exception:
        return False
    snapshot['dumped_at'] = time.time()
    snapshot['dumped_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    try:
        d = os.path.dirname(p)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return True
    except OSError:
        return False


class ClaimStatsDumper(threading.Thread):
    """60s tick: dump _CLAIM_STATS in-memory → memory_pool/claim_stats.json.

    设计 (Sir Session 4 β.4.5.1 快赢):
      - dashboard 跨进程读 claim_stats.json 算 verify_rate (β.4.4 hook 已就位)
      - 本 daemon 让主进程把 in-memory counter 定期暴露到 disk
      - 启动后立刻 dump 一次 (即使 0 也写, 表明系统在跑)
      - tick_seconds 默认 60s 平衡实时性与 IO 开销
      - 任一 dump 失败 fail-safe 静默 (不污染主对话)

    real-machine 风险点预防:
      - 不能用 self._stop (与 Python 3.9+ threading.Thread 内部 _stop method 冲突,
        join() 会 raise 'Event object is not callable')
    """

    def __init__(self, tick_seconds: float = 60.0,
                 dump_path: Optional[str] = None):
        super().__init__(daemon=True, name='ClaimStatsDumper')
        self.tick_seconds = tick_seconds
        self.dump_path = dump_path
        self._stop_event = threading.Event()
        self._stats = {
            'dumps_total': 0,
            'dumps_failed': 0,
            'last_dump_ts': 0.0,
        }

    def stop(self):
        self._stop_event.set()

    def get_stats(self) -> dict:
        return dict(self._stats)

    def run(self):
        try:
            from jarvis_utils import bg_log
            bg_log(
                f"💯 [ClaimStatsDumper] 启动 (tick={self.tick_seconds}s) — "
                f"_CLAIM_STATS → memory_pool/claim_stats.json"
            )
        except Exception:
            pass
        # 启动后立刻 dump 一次 (让 dashboard 知道系统在跑)
        try:
            ok = dump_claim_stats(self.dump_path)
            self._stats['dumps_total'] += 1
            if not ok:
                self._stats['dumps_failed'] += 1
            self._stats['last_dump_ts'] = time.time()
        except Exception:
            self._stats['dumps_failed'] += 1
        while not self._stop_event.is_set():
            if self._stop_event.wait(self.tick_seconds):
                return
            try:
                ok = dump_claim_stats(self.dump_path)
                self._stats['dumps_total'] += 1
                if not ok:
                    self._stats['dumps_failed'] += 1
                self._stats['last_dump_ts'] = time.time()
            except Exception:
                self._stats['dumps_failed'] += 1


# 单例 factory (central_nerve.__init__ 启动用)
_DEFAULT_CLAIM_STATS_DUMPER: Optional[ClaimStatsDumper] = None


def get_default_claim_stats_dumper(tick_seconds: float = 60.0,
                                     dump_path: Optional[str] = None
                                     ) -> ClaimStatsDumper:
    global _DEFAULT_CLAIM_STATS_DUMPER
    if _DEFAULT_CLAIM_STATS_DUMPER is None:
        _DEFAULT_CLAIM_STATS_DUMPER = ClaimStatsDumper(
            tick_seconds=tick_seconds, dump_path=dump_path)
    return _DEFAULT_CLAIM_STATS_DUMPER


# ============================================================
# β.4.5.2 (后续 sub-step): IntegrityReflector LLM-propose daemon
#
# 待办:
#   class IntegrityReflector(threading.Thread):
#     - daemon, weekly trigger 或 audit jsonl 累积 > 50 条触发
#     - _reflect_integrity_audit(): 扫 7d audit, LLM propose vocab/directive/evidence_kind
#     - 输出: 写 memory_pool/{claim_classify_vocab.json,evidence_requirements.json,directive_review.json}
#     - 核心契约: Sir 永远是仲裁人, propose 只入 review state
# ============================================================
