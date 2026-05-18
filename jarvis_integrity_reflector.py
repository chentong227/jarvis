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
# β.4.5.2: IntegrityReflector — L7 LLM-propose daemon (Sir 永远仲裁)
#
# 设计契约:
#   1. 触发: weekly (3d 兜底) 或 audit jsonl 累积 > 50 条 + Sir idle > 4h
#   2. 扫 7d audit, LLM (Gemini-3-Flash) propose 3 类:
#      A. claim_classify_proposals: 新 keyword 给 6 个 claim_type (Past/Future/State/Recall/Social/Tool)
#      B. evidence_req_proposals: 新 evidence_kind 给某 claim_type
#      C. directive_proposals: 新 directive 阻止反复 unverified 短语
#   3. 输出: 写 review state 进 vocab.json (state='review') / directive_review.json
#   4. 准则 7 Sir 元否决: propose 只入 review, 不自动 active.
#      Sir 用 CLI --activate <id> 才生效. Reject 也是 CLI.
#   5. 准则 6: prompt 只约束 schema, 不教 LLM 具体中文/英文措辞
#   6. 准则 6.5: 全持久化 + CLI + 动态 (本身就是 dynamic vocab proposer)
# ============================================================

INTEGRITY_REFLECTOR_CONFIG = {
    'primary_model': 'google/gemini-3.1-pro-preview',
    'fallback_model': 'google/gemini-2.5-flash-lite',
    'temperature': 0.2,         # 略放手, 但要 grounded in evidence
    'max_output_tokens': 1000,
    'timeout_s': 15.0,
    'tick_seconds': 60.0,       # daemon tick (不是反思频率)
    'min_interval_s': 86400 * 3,   # 3 天兜底反思 (audit 是低频)
    'min_audit_for_trigger': 50,   # audit jsonl 累积 ≥ 50 条触发
    'min_idle_hours_for_trigger': 4.0,  # Sir idle > 4h 才反思
    'max_propose_per_run': 5,      # 每次最多 propose 5 条 (3 类合计)
    'window_days': 7,              # 看 7 天 audit
    'startup_sleep_s': 30,         # 启动 sleep 30s 让其他模块就绪
}


INTEGRITY_REFLECTOR_PROMPT = """[ROLE]
You are Jarvis's Integrity Auditor. You analyze records of factual claims that Jarvis made but failed to trace to evidence (called "unverified claims"), and propose system improvements.

[CRITICAL CONSTRAINTS]
1. Every proposal MUST be grounded in concrete patterns observed in the audit log below. No speculation.
2. AT MOST 5 proposals TOTAL across all three categories.
3. Each proposal goes to "review" state — Sir reviews and activates manually via CLI.
4. NEVER prescribe specific Chinese/English phrasing in directives. Only describe the pattern.
5. Output empty arrays if no clear pattern emerges. Quality over quantity.
6. Avoid duplicating existing review-state items (see [EXISTING REVIEW ITEMS]).

[CATEGORIES]
A. claim_classify_proposals — 新 keyword 给现有 claim_type
   When: ClaimTracer 漏抓某类 claim (e.g. 一种 Future 表达 vocab 里没有)
   Schema: {{"id": "<snake_case>", "claim_type": "Past|Future|State|Recall|Social|Tool",
            "keywords": ["..."], "rationale": "<one sentence>"}}

B. evidence_req_proposals — 新 evidence_kind 给某 claim_type
   When: 某 claim_type 反复 unverified 说明 evidence path 缺一类来源
   Schema: {{"claim_type": "...", "evidence_kind": "<from canonical list>",
            "rationale": "<one sentence>"}}
   evidence_kinds_canonical: tool_results_success / tool_results_any / stm_match /
     ltm_match / system_clock_within_2min / promise_log_recorded / uncertainty_marker_nearby

C. directive_proposals — 新 directive 阻止反复 unverified 短语
   When: 同一短语 ≥ 5 次 unverified 应加 directive 提醒主脑此类 claim 须先 verify
   Schema: {{"id": "<snake_case>", "trigger_pattern": "<regex or short keyword>",
            "rule_summary": "<what main brain should do, < 100 chars>",
            "rationale": "<one sentence>"}}

[INPUT]
audit_window: {window_days} days
total_unverified_in_window: {total_unverified}
kind_distribution: {kind_distribution_str}

[TOP UNVERIFIED CLAIMS (≥ 3 repeats, max 20 lines)]
{top_claims_str}

[SAMPLE UNVERIFIED CLAIMS (last {sample_n})]
{sample_claims_str}

[EXISTING REVIEW ITEMS — DO NOT DUPLICATE]
claim_classify (review state):
{existing_classify_str}

evidence_req (review state):
{existing_evreq_str}

directive (review state):
{existing_directive_str}

[OUTPUT]
JSON only, single line:
{{"claim_classify_proposals": [...], "evidence_req_proposals": [...], "directive_proposals": [...]}}

Empty arrays if no proposals. ALL string values in English. NO markdown, NO explanation.
"""


class IntegrityReflector(threading.Thread):
    """7d audit 反思 daemon. LLM propose vocab/directive 进 review queue."""

    DEFAULT_AUDIT_PATH = os.path.join('memory_pool', 'integrity_audit.jsonl')
    CLASSIFY_VOCAB_PATH = os.path.join('memory_pool', 'claim_classify_vocab.json')
    EVREQ_VOCAB_PATH = os.path.join('memory_pool', 'evidence_requirements.json')
    DIRECTIVE_REVIEW_PATH = os.path.join('memory_pool', 'directive_review.json')

    def __init__(self, key_router=None,
                 audit_path: Optional[str] = None,
                 classify_vocab_path: Optional[str] = None,
                 evreq_vocab_path: Optional[str] = None,
                 directive_review_path: Optional[str] = None,
                 config: Optional[dict] = None):
        super().__init__(daemon=True, name='IntegrityReflector')
        self.key_router = key_router
        self.audit_path = audit_path or self.DEFAULT_AUDIT_PATH
        self.classify_vocab_path = classify_vocab_path or self.CLASSIFY_VOCAB_PATH
        self.evreq_vocab_path = evreq_vocab_path or self.EVREQ_VOCAB_PATH
        self.directive_review_path = directive_review_path or self.DIRECTIVE_REVIEW_PATH
        self.config = dict(INTEGRITY_REFLECTOR_CONFIG)
        if config:
            self.config.update(config)
        # 🩹 [β.4.5.2 / 2026-05-18] _stop_event 避 Python 3.9 Thread._stop 冲突 (β.4.5.1 教训内化)
        self._stop_event = threading.Event()
        self._last_run_ts = 0.0
        self._stats = {
            'runs_total': 0,
            'runs_proposed': 0,
            'proposals_total': 0,
            'last_run_ts': 0.0,
            'last_error': '',
        }

    def stop(self):
        self._stop_event.set()

    def get_stats(self) -> dict:
        return dict(self._stats)

    def force_run_now(self) -> dict:
        """立刻强制反思一次 (CLI / 测试用). 返 result dict."""
        try:
            return self._reflect_once(force=True)
        except Exception as e:
            return {'error': str(e)[:200]}

    def run(self):
        try:
            from jarvis_utils import bg_log
            bg_log(
                f"🔬 [IntegrityReflector] 启动 (tick={self.config['tick_seconds']}s, "
                f"min_interval={self.config['min_interval_s']/86400:.1f}d, "
                f"audit_trigger=≥{self.config['min_audit_for_trigger']}, "
                f"INTEGRITY_STACK L7 已激活)"
            )
        except Exception:
            pass
        if self._stop_event.wait(self.config['startup_sleep_s']):
            return
        while not self._stop_event.is_set():
            try:
                if self._should_reflect_now():
                    self._reflect_once(force=False)
            except Exception as e:
                self._stats['last_error'] = str(e)[:200]
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"⚠️ [IntegrityReflector] 反思失败（非致命）：{str(e)[:120]}")
                except Exception:
                    pass
            if self._stop_event.wait(self.config['tick_seconds']):
                return

    # ---------------------------------------------------------
    # 触发判定
    # ---------------------------------------------------------

    def _should_reflect_now(self) -> bool:
        """三个或条件:
          (a) time-based 兜底: 上次反思 > min_interval_s (3 天)
          (b) audit-based 触发: 7d audit 累积 ≥ min_audit_for_trigger 且 Sir idle > min_idle_hours_for_trigger
        """
        now = time.time()
        elapsed = now - self._last_run_ts
        if elapsed >= self.config['min_interval_s']:
            return True
        # audit-based
        try:
            audit_n = self._count_recent_audit()
            if audit_n < self.config['min_audit_for_trigger']:
                return False
            idle_h = self._sir_idle_hours()
            if idle_h < self.config['min_idle_hours_for_trigger']:
                return False
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"🔬 [IntegrityReflector/Trigger] audit {audit_n}/"
                    f"{self.config['min_audit_for_trigger']} + idle "
                    f"{idle_h:.1f}h/{self.config['min_idle_hours_for_trigger']}h → 触发反思"
                )
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _count_recent_audit(self) -> int:
        """count 7d audit 条数 (用 file seek -512KB 避免 OOM)."""
        if not os.path.exists(self.audit_path):
            return 0
        try:
            size = os.path.getsize(self.audit_path)
            with open(self.audit_path, 'r', encoding='utf-8', errors='ignore') as f:
                if size > 512 * 1024:
                    f.seek(size - 512 * 1024)
                    f.readline()  # 弃 partial 首行
                lines = f.readlines()
        except Exception:
            return 0
        cutoff = time.time() - self.config['window_days'] * 86400
        n = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if float(rec.get('ts', 0) or 0) >= cutoff:
                    n += 1
            except Exception:
                continue
        return n

    @staticmethod
    def _sir_idle_hours() -> float:
        try:
            import win32api  # type: ignore
            idle_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
            return idle_ms / 3600_000.0
        except Exception:
            return 0.0

    # ---------------------------------------------------------
    # 反思主流程
    # ---------------------------------------------------------

    def _gather_audit_window(self) -> list:
        """读 7d audit, 返 records list."""
        if not os.path.exists(self.audit_path):
            return []
        try:
            size = os.path.getsize(self.audit_path)
            with open(self.audit_path, 'r', encoding='utf-8', errors='ignore') as f:
                if size > 512 * 1024:
                    f.seek(size - 512 * 1024)
                    f.readline()
                lines = f.readlines()
        except Exception:
            return []
        cutoff = time.time() - self.config['window_days'] * 86400
        out = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if float(rec.get('ts', 0) or 0) >= cutoff:
                    out.append(rec)
            except Exception:
                continue
        return out

    @staticmethod
    def _build_top_claims(records: list, min_count: int = 3,
                           max_lines: int = 20) -> list:
        """按 claim text 聚合, ≥ min_count 次的归 'top'."""
        counter: dict = {}
        for r in records:
            text = (r.get('claim') or '').strip()[:80]
            kind = (r.get('kind') or '?').strip() or '?'
            if not text:
                continue
            key = (text, kind)
            counter[key] = counter.get(key, 0) + 1
        top = [(t, k, c) for (t, k), c in counter.items() if c >= min_count]
        top.sort(key=lambda x: -x[2])
        return top[:max_lines]

    @staticmethod
    def _kind_distribution(records: list) -> dict:
        d: dict = {}
        for r in records:
            k = (r.get('kind') or '?').strip() or '?'
            d[k] = d.get(k, 0) + 1
        return d

    def _existing_review_items(self) -> dict:
        """读 3 个 review queue 当前内容, 给 LLM 看 (避免重复 propose)."""
        out = {'classify': [], 'evreq': [], 'directive': []}
        try:
            if os.path.exists(self.classify_vocab_path):
                with open(self.classify_vocab_path, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
                for p in (data.get('patterns', []) or []):
                    if p.get('state') == 'review':
                        out['classify'].append({
                            'id': p.get('id', ''),
                            'claim_type': p.get('claim_type', ''),
                            'keywords': p.get('keywords', [])[:5],
                        })
        except Exception:
            pass
        try:
            if os.path.exists(self.evreq_vocab_path):
                with open(self.evreq_vocab_path, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
                for p in (data.get('patterns', []) or []):
                    if p.get('state') == 'review':
                        out['evreq'].append({
                            'claim_type': p.get('claim_type', ''),
                            'accepted_evidence_kinds': p.get('accepted_evidence_kinds', []),
                        })
        except Exception:
            pass
        try:
            if os.path.exists(self.directive_review_path):
                with open(self.directive_review_path, 'r', encoding='utf-8') as f:
                    data = json.load(f) or []
                for d in (data if isinstance(data, list) else []):
                    out['directive'].append({
                        'id': d.get('id', ''),
                        'trigger': str(d.get('trigger_pattern', ''))[:60],
                    })
        except Exception:
            pass
        return out

    def _reflect_once(self, force: bool = False) -> dict:
        """主反思流程. 返 {'proposed_n', 'reason', 'errors'}."""
        result = {'proposed_n': 0, 'reason': '', 'errors': []}
        records = self._gather_audit_window()
        if not force and len(records) < self.config['min_audit_for_trigger']:
            result['reason'] = f'audit only {len(records)} (< {self.config["min_audit_for_trigger"]})'
            self._last_run_ts = time.time()
            return result
        if not records:
            result['reason'] = 'audit empty'
            self._last_run_ts = time.time()
            return result

        top_claims = self._build_top_claims(records)
        kind_dist = self._kind_distribution(records)
        existing = self._existing_review_items()

        # 渲染 prompt
        top_str = '\n'.join(
            f"  - [{c}x] kind={k} claim=\"{t}\""
            for (t, k, c) in top_claims
        ) or '(none)'
        sample_n = min(15, len(records))
        sample_str = '\n'.join(
            f"  - turn={r.get('turn_id', '?')[:20]} kind={r.get('kind', '?')} "
            f"claim=\"{(r.get('claim') or '')[:80]}\""
            for r in records[-sample_n:]
        ) or '(none)'
        existing_classify = '\n'.join(
            f"  - {it['id']} ({it['claim_type']}) kw={it['keywords']}"
            for it in existing['classify']
        ) or '(none)'
        existing_evreq = '\n'.join(
            f"  - {it['claim_type']} kinds={it['accepted_evidence_kinds']}"
            for it in existing['evreq']
        ) or '(none)'
        existing_directive = '\n'.join(
            f"  - {it['id']}: {it['trigger']}"
            for it in existing['directive']
        ) or '(none)'

        prompt = INTEGRITY_REFLECTOR_PROMPT.format(
            window_days=self.config['window_days'],
            total_unverified=len(records),
            kind_distribution_str=json.dumps(kind_dist, ensure_ascii=False),
            top_claims_str=top_str,
            sample_n=sample_n,
            sample_claims_str=sample_str,
            existing_classify_str=existing_classify,
            existing_evreq_str=existing_evreq,
            existing_directive_str=existing_directive,
        )

        # 调 LLM
        response_text = self._call_llm(prompt)
        if not response_text:
            result['reason'] = 'LLM no response'
            self._stats['last_error'] = result['reason']
            return result
        # 解析 JSON
        import re
        m = re.search(r'\{.*\}', response_text, re.DOTALL)
        if not m:
            result['reason'] = 'no JSON in LLM response'
            return result
        try:
            data = json.loads(m.group(0))
        except Exception as e:
            result['reason'] = f'JSON parse: {str(e)[:60]}'
            return result

        # 应用 propose (累计 ≤ max_propose_per_run)
        max_n = self.config['max_propose_per_run']
        n_added = 0
        for entry in (data.get('claim_classify_proposals') or [])[:max_n - n_added]:
            if self._propose_claim_classify(entry):
                n_added += 1
            if n_added >= max_n:
                break
        for entry in (data.get('evidence_req_proposals') or [])[:max_n - n_added]:
            if n_added >= max_n:
                break
            if self._propose_evidence_req(entry):
                n_added += 1
        for entry in (data.get('directive_proposals') or [])[:max_n - n_added]:
            if n_added >= max_n:
                break
            if self._propose_directive(entry):
                n_added += 1

        if n_added > 0:
            self._stats['runs_proposed'] += 1
            self._stats['proposals_total'] += n_added
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"🔬 [IntegrityReflector] propose {n_added} new items → review queues "
                    f"(scripts/claim_classify_dump.py / evidence_req_dump.py / registry_dump.py --review-list)"
                )
            except Exception:
                pass
        self._stats['runs_total'] += 1
        self._stats['last_run_ts'] = time.time()
        self._last_run_ts = time.time()
        result['proposed_n'] = n_added
        return result

    def _call_llm(self, prompt: str) -> str:
        """调 OpenRouter (primary → fallback). 失败返 ''."""
        if self.key_router is None:
            self._stats['last_error'] = 'no key_router'
            return ''
        try:
            okey, _label = self.key_router.get_openrouter_key(
                caller='integrity_reflector')
        except Exception as e:
            self._stats['last_error'] = f'key_router: {str(e)[:80]}'
            return ''
        try:
            from jarvis_utils import safe_openrouter_call
        except Exception as e:
            self._stats['last_error'] = f'import safe_openrouter_call: {str(e)[:80]}'
            return ''
        for model_key in ('primary_model', 'fallback_model'):
            try:
                text = safe_openrouter_call(
                    openrouter_key=okey,
                    model=self.config[model_key],
                    prompt=prompt,
                    max_tokens=self.config['max_output_tokens'],
                    temperature=self.config['temperature'],
                    max_retries=1,
                )
                if text and text.strip():
                    return text
            except Exception as e:
                self._stats['last_error'] = f'{model_key}: {str(e)[:80]}'
                continue
        return ''

    # ---------------------------------------------------------
    # propose 应用器 — 写入 review state (准则 7 Sir 仲裁)
    # ---------------------------------------------------------

    @staticmethod
    def _load_vocab_atomic(path: str) -> dict:
        """读 vocab json. 失败返 {'patterns': []} (fail-safe)."""
        if not os.path.exists(path):
            return {'patterns': []}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f) or {'patterns': []}
        except Exception:
            return {'patterns': []}

    @staticmethod
    def _save_vocab_atomic(path: str, data: dict) -> bool:
        try:
            d = os.path.dirname(path)
            if d and not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return True
        except OSError:
            return False

    def _propose_claim_classify(self, entry: dict) -> bool:
        """加新 keyword pattern 进 claim_classify_vocab.json patterns[] (state=review)."""
        if not isinstance(entry, dict):
            return False
        pid = str(entry.get('id') or '').strip()
        ctype = str(entry.get('claim_type') or '').strip()
        kws_raw = entry.get('keywords') or []
        kws = [str(k).strip().lower() for k in kws_raw if str(k).strip()]
        if not pid or not ctype or not kws:
            return False
        if ctype not in ('Past', 'Future', 'State', 'Recall', 'Social', 'Tool'):
            return False
        vocab = self._load_vocab_atomic(self.classify_vocab_path)
        patterns = vocab.setdefault('patterns', [])
        # dedup: 同 id 已存在 → skip
        for p in patterns:
            if p.get('id') == pid:
                return False
        patterns.append({
            'id': pid[:60],
            'claim_type': ctype,
            'kinds_hard_map': [],
            'keywords': kws[:30],
            'state': 'review',
            'source': 'integrity_reflector',
            'created_at': time.time(),
            'note': (str(entry.get('rationale') or '')[:200] or
                      'L7 IntegrityReflector propose, Sir review')
        })
        return self._save_vocab_atomic(self.classify_vocab_path, vocab)

    def _propose_evidence_req(self, entry: dict) -> bool:
        """加新 evidence_kind 给某 claim_type 进 evidence_requirements.json (state=review)."""
        if not isinstance(entry, dict):
            return False
        ctype = str(entry.get('claim_type') or '').strip()
        ekind = str(entry.get('evidence_kind') or '').strip()
        if not ctype or not ekind:
            return False
        canonical = ('tool_results_success', 'tool_results_any', 'stm_match',
                     'ltm_match', 'system_clock_within_2min',
                     'promise_log_recorded', 'uncertainty_marker_nearby')
        if ekind not in canonical:
            return False
        vocab = self._load_vocab_atomic(self.evreq_vocab_path)
        patterns = vocab.setdefault('patterns', [])
        # dedup: 同 claim_type + 同 kind 已 review → skip
        for p in patterns:
            if (p.get('claim_type') == ctype and
                    ekind in (p.get('accepted_evidence_kinds') or []) and
                    p.get('state') == 'review'):
                return False
        patterns.append({
            'id': f'reflector_{ctype.lower()}_{int(time.time())}',
            'claim_type': ctype,
            'accepted_evidence_kinds': [ekind],
            'state': 'review',
            'source': 'integrity_reflector',
            'created_at': time.time(),
            'note': (str(entry.get('rationale') or '')[:200] or
                      'L7 IntegrityReflector propose extra evidence_kind')
        })
        return self._save_vocab_atomic(self.evreq_vocab_path, vocab)

    def _propose_directive(self, entry: dict) -> bool:
        """加新 directive 进 directive_review.json (list)."""
        if not isinstance(entry, dict):
            return False
        did = str(entry.get('id') or '').strip()
        trigger = str(entry.get('trigger_pattern') or '').strip()
        rule = str(entry.get('rule_summary') or '').strip()
        if not did or not trigger or not rule:
            return False
        # 读现有 review
        review_list = []
        if os.path.exists(self.directive_review_path):
            try:
                with open(self.directive_review_path, 'r', encoding='utf-8') as f:
                    review_list = json.load(f) or []
                if not isinstance(review_list, list):
                    review_list = []
            except Exception:
                review_list = []
        # dedup
        for r in review_list:
            if isinstance(r, dict) and r.get('id') == did:
                return False
        review_list.append({
            'id': did[:60],
            'trigger_pattern': trigger[:200],
            'rule_summary': rule[:300],
            'state': 'review',
            'source': 'integrity_reflector',
            'created_at': time.time(),
            'note': (str(entry.get('rationale') or '')[:200] or
                      'L7 IntegrityReflector propose directive, Sir review')
        })
        try:
            d = os.path.dirname(self.directive_review_path)
            if d and not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
            tmp = self.directive_review_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(review_list, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.directive_review_path)
            return True
        except OSError:
            return False


# 单例 factory (central_nerve.__init__ 启动用)
_DEFAULT_INTEGRITY_REFLECTOR: Optional[IntegrityReflector] = None


def get_default_integrity_reflector(key_router=None,
                                     audit_path: Optional[str] = None,
                                     config: Optional[dict] = None
                                     ) -> IntegrityReflector:
    global _DEFAULT_INTEGRITY_REFLECTOR
    if _DEFAULT_INTEGRITY_REFLECTOR is None:
        _DEFAULT_INTEGRITY_REFLECTOR = IntegrityReflector(
            key_router=key_router, audit_path=audit_path, config=config)
    return _DEFAULT_INTEGRITY_REFLECTOR
