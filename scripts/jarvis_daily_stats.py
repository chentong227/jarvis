# -*- coding: utf-8 -*-
"""[P0+20-β.2.7.9 / 2026-05-17] Jarvis 日常 dashboard — Phase α 剩余项

给 Sir 一行命令看 Jarvis 24h / 7d 健康状况, ASCII chart 友好.
不调 LLM, 纯本地 grep + 统计.

用法:
    python scripts/jarvis_daily_stats.py                       # 默认看 24h
    python scripts/jarvis_daily_stats.py --days 7              # 7d 趋势
    python scripts/jarvis_daily_stats.py --logs-dir <PATH>     # 自定义日志目录

输出 5 段:
1. 对话量 (轮次 / 平均时长 / TTFT 分布)
2. Nudge 触发 (type 分布 / Sir 反应)
3. Commitment 健康 (注册/触发/完成 比例)
4. L1 Concerns 状态 (severity top 5 + signal counts)
5. LLM 成本 (estimated 月度)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        os.system('chcp 65001 > nul 2>&1')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# 工具
# ============================================================

def _ascii_bar(value: float, max_value: float, width: int = 40) -> str:
    """ASCII 柱状: ████████░░░░ 70%"""
    if max_value <= 0:
        return '░' * width + '  (no data)'
    ratio = min(1.0, value / max_value)
    filled = int(ratio * width)
    return '█' * filled + '░' * (width - filled) + f'  {value:.1f}/{max_value:.0f}'


def _ascii_hist(counts: Dict[str, int], width: int = 30) -> List[str]:
    """ASCII 直方图: key | ████░ 23"""
    if not counts:
        return ['  (no data)']
    max_c = max(counts.values())
    lines = []
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        ratio = v / max_c if max_c > 0 else 0
        filled = int(ratio * width)
        lines.append(f"  {str(k)[:30]:<30} | {'█'*filled}{'░'*(width-filled)} {v}")
    return lines


def _collect_logs(logs_dir: str, days: int) -> List[str]:
    """返回最近 N 天的 log 文件路径 (按修改时间排, 最新在后)."""
    if not os.path.isdir(logs_dir):
        return []
    now = time.time()
    cutoff = now - days * 86400
    files = []
    for name in os.listdir(logs_dir):
        if not name.startswith('jarvis_') or not name.endswith('.log'):
            continue
        path = os.path.join(logs_dir, name)
        try:
            mtime = os.path.getmtime(path)
            if mtime >= cutoff:
                files.append((mtime, path))
        except Exception:
            continue
    files.sort()
    return [p for _, p in files]


# ============================================================
# 5 段 stats
# ============================================================

# 1. 对话量
_RE_HUMAN = re.compile(r'║\s*🗣️\s+\[Human\]')
_RE_JARVIS = re.compile(r'║\s*⏰\s*\[\d{2}:\d{2}:\d{2}\] Jarvis 开始响应')
_RE_TTFT = re.compile(r'\[Timing\] TTFT\s+([\d.]+)s.*?full\s+([\d.]+)s')

def stat_conversations(log_paths: List[str]) -> Dict:
    n_human = 0
    n_jarvis = 0
    ttft_samples = []
    full_samples = []
    for p in log_paths:
        try:
            with open(p, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    if _RE_HUMAN.search(line):
                        n_human += 1
                    elif _RE_JARVIS.search(line):
                        n_jarvis += 1
                    m = _RE_TTFT.search(line)
                    if m:
                        try:
                            ttft_samples.append(float(m.group(1)))
                            full_samples.append(float(m.group(2)))
                        except Exception:
                            pass
        except Exception:
            continue
    return {
        'n_human_turns': n_human,
        'n_jarvis_replies': n_jarvis,
        'ttft_mean': sum(ttft_samples)/len(ttft_samples) if ttft_samples else 0,
        'ttft_max': max(ttft_samples) if ttft_samples else 0,
        'ttft_min': min(ttft_samples) if ttft_samples else 0,
        'full_mean': sum(full_samples)/len(full_samples) if full_samples else 0,
        'full_max': max(full_samples) if full_samples else 0,
        'n_samples': len(ttft_samples),
    }


# 2. Nudge
_RE_NUDGE = re.compile(r'\[Smart Nudge\]\s+(\w+)')
_RE_NUDGE_SKIP = re.compile(r'\[SmartNudge/Skip\]\s+(\w+)')
_RE_SHIELD_TRIGGER = re.compile(r'\[Shield TRIGGER\]')
_RE_RETURN_GREETING = re.compile(r'\[ReturnSentinel/Sent\]')

def stat_nudges(log_paths: List[str]) -> Dict:
    nudge_types = Counter()
    skip_types = Counter()
    shield_n = 0
    return_greet_n = 0
    for p in log_paths:
        try:
            with open(p, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    m = _RE_NUDGE.search(line)
                    if m:
                        nudge_types[m.group(1)] += 1
                    m = _RE_NUDGE_SKIP.search(line)
                    if m:
                        skip_types[m.group(1)] += 1
                    if _RE_SHIELD_TRIGGER.search(line):
                        shield_n += 1
                    if _RE_RETURN_GREETING.search(line):
                        return_greet_n += 1
        except Exception:
            continue
    return {
        'nudge_types': dict(nudge_types),
        'skip_types': dict(skip_types),
        'shield_trigger_count': shield_n,
        'return_greeting_count': return_greet_n,
    }


# 3. Commitment
_RE_COMMIT_REG = re.compile(r'\[CommitmentWatcher[^\]]*\]\s+已注册:\s+(.+?)\s+@\s+(\d{2}:\d{2})')
_RE_COMMIT_GK_TRUE = re.compile(r'\[Gatekeeper Commitment\] has_commitment=True')
_RE_COMMIT_GK_FALSE = re.compile(r'\[Gatekeeper Commitment\] has_commitment=False')
_RE_SELFPROMISE = re.compile(r'\[SelfPromise([/\w]*)\]\s+(?:注册|检测)')

def stat_commitments(log_paths: List[str]) -> Dict:
    reg_n = 0
    gk_true = 0
    gk_false = 0
    self_hard = 0
    self_soft = 0
    sample_commits = []
    for p in log_paths:
        try:
            with open(p, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    m = _RE_COMMIT_REG.search(line)
                    if m:
                        reg_n += 1
                        if len(sample_commits) < 5:
                            sample_commits.append(f"{m.group(2)}: {m.group(1)[:50]}")
                    if _RE_COMMIT_GK_TRUE.search(line):
                        gk_true += 1
                    if _RE_COMMIT_GK_FALSE.search(line):
                        gk_false += 1
                    m = _RE_SELFPROMISE.search(line)
                    if m:
                        kind = m.group(1)
                        if 'soft' in kind:
                            self_soft += 1
                        else:
                            self_hard += 1
        except Exception:
            continue
    return {
        'registered': reg_n,
        'gatekeeper_yes': gk_true,
        'gatekeeper_no': gk_false,
        'gatekeeper_yes_rate': (gk_true / (gk_true + gk_false)) if (gk_true + gk_false) > 0 else 0,
        'self_promise_hard': self_hard,
        'self_promise_soft': self_soft,
        'samples': sample_commits,
    }


# 4. L1 Concerns
def stat_concerns() -> Dict:
    try:
        from jarvis_concerns import ConcernsLedger, bootstrap_default_concerns
        ledger = ConcernsLedger()
        bootstrap_default_concerns(ledger)
        ledger.load()
        actives = sorted(
            ledger.list_active(),
            key=lambda c: -getattr(c, 'severity', 0)
        )
        review = ledger.list_review()
        return {
            'active_count': len(actives),
            'review_count': len(review),
            'top_5': [
                {
                    'id': c.id,
                    'severity': c.severity,
                    'aligned_count': getattr(c, 'aligned_count', 0),
                    'missed_count': getattr(c, 'missed_count', 0),
                    'recent_signals': len(c.recent_signals or []),
                }
                for c in actives[:5]
            ],
        }
    except Exception as e:
        return {'error': f'{type(e).__name__}: {str(e)[:80]}'}


# 5. LLM 成本 estimated
_RE_ALIGNMENT = re.compile(r'\[SoulEvaluator\][^|]*\[(\w+(?:[.\-]\w+)*).*?score=(\d+)')
_RE_DIRECTIVE_EVAL = re.compile(r'\[Evaluator\]\s+\w+\s+→\s+helped=(\w+)')

def stat_cost(log_paths: List[str], conv_stats: Dict) -> Dict:
    flash_n = 0  # 主对话每轮 1 次 stream_chat
    soul_eval_n = 0
    directive_eval_n = 0
    soul_eval_models = Counter()
    for p in log_paths:
        try:
            with open(p, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    if _RE_TTFT.search(line):
                        flash_n += 1
                    m = _RE_ALIGNMENT.search(line)
                    if m:
                        soul_eval_n += 1
                        soul_eval_models[m.group(1)] += 1
                    if _RE_DIRECTIVE_EVAL.search(line):
                        directive_eval_n += 1
        except Exception:
            continue

    # 估算 (USD, gemini-3-flash $0.5/M input + $3/M output, gemini-2.5-pro $1.25/$10)
    # 主对话 ~5K input + 300 output: $0.0034
    # SoulEval flash ~1.5K + 200 output: $0.00135
    # SoulEval pro ~1.5K + 200 output: $0.003875
    # DirectiveEval ~1K + 100 output: $0.0008
    cost_main = flash_n * 0.0034
    pro_n = soul_eval_models.get('2.5-pro', 0)
    flash_eval_n = soul_eval_n - pro_n
    cost_soul = pro_n * 0.003875 + flash_eval_n * 0.00135
    cost_dir = directive_eval_n * 0.0008
    total = cost_main + cost_soul + cost_dir
    return {
        'main_dialogue_calls': flash_n,
        'soul_evaluator_calls': soul_eval_n,
        'soul_evaluator_models': dict(soul_eval_models),
        'directive_evaluator_calls': directive_eval_n,
        'estimated_total_usd': total,
        'cost_breakdown_usd': {
            'main_dialogue': cost_main,
            'soul_evaluator': cost_soul,
            'directive_evaluator': cost_dir,
        },
    }


# ============================================================
# 打印
# ============================================================

def print_dashboard(days: int, logs_dir: str):
    log_paths = _collect_logs(logs_dir, days)
    if not log_paths:
        print(f"[!] {logs_dir} 内最近 {days}d 无 jarvis_*.log")
        return

    print("=" * 80)
    print(f"Jarvis 健康 Dashboard  /  最近 {days} 天  /  {len(log_paths)} 个 log 文件")
    print("=" * 80)

    # 1. 对话量
    print("\n[1/5] 对话量")
    print("-" * 80)
    c = stat_conversations(log_paths)
    print(f"  Sir 发言:    {c['n_human_turns']} 轮")
    print(f"  Jarvis 回话: {c['n_jarvis_replies']} 轮")
    print(f"  TTFT 分布:   mean={c['ttft_mean']:.1f}s | min={c['ttft_min']:.1f}s | max={c['ttft_max']:.1f}s")
    print(f"  Full 分布:   mean={c['full_mean']:.1f}s | max={c['full_max']:.1f}s")
    print(f"  样本量:      {c['n_samples']}")

    # 2. Nudge
    print("\n[2/5] Nudge 活动")
    print("-" * 80)
    n = stat_nudges(log_paths)
    if n['nudge_types']:
        print(f"  触发的 Nudge 类型:")
        for line in _ascii_hist(n['nudge_types']):
            print(line)
    else:
        print(f"  无 Nudge 触发")
    print(f"  ProactiveShield 触发: {n['shield_trigger_count']}")
    print(f"  ReturnSentinel 问候:  {n['return_greeting_count']}")
    if n['skip_types']:
        skip_total = sum(n['skip_types'].values())
        print(f"  Nudge 跳过 (cooldown): {skip_total}")

    # 3. Commitment
    print("\n[3/5] Commitment 健康")
    print("-" * 80)
    cm = stat_commitments(log_paths)
    print(f"  Gatekeeper 判定 future_task: yes={cm['gatekeeper_yes']} no={cm['gatekeeper_no']}  yes率={cm['gatekeeper_yes_rate']:.0%}")
    print(f"  注册到 commitment_watcher: {cm['registered']} 条")
    print(f"  SelfPromise 检测: hard={cm['self_promise_hard']}, soft={cm['self_promise_soft']}")
    if cm['samples']:
        print(f"  最近 commitment 样例:")
        for s in cm['samples']:
            print(f"    {s}")

    # 4. L1 Concerns
    print("\n[4/5] L1 Concerns (Jarvis 关心的事)")
    print("-" * 80)
    co = stat_concerns()
    if 'error' in co:
        print(f"  [!] {co['error']}")
    else:
        print(f"  active: {co['active_count']}  review queue: {co['review_count']}")
        print(f"  top 5 (按 severity):")
        if co['top_5']:
            max_sev = max(c['severity'] for c in co['top_5'])
            for c in co['top_5']:
                bar = _ascii_bar(c['severity'], 1.0, width=30)
                print(f"    {c['id'][:30]:<30} {bar}")
                print(f"      └─ aligned={c['aligned_count']}  missed={c['missed_count']}  recent_signals={c['recent_signals']}")

    # 5. LLM 成本
    print("\n[5/5] LLM 成本 (估算)")
    print("-" * 80)
    cs = stat_cost(log_paths, c)
    print(f"  主对话调用: {cs['main_dialogue_calls']}  → ${cs['cost_breakdown_usd']['main_dialogue']:.2f}")
    print(f"  SoulEval 调用: {cs['soul_evaluator_calls']}  → ${cs['cost_breakdown_usd']['soul_evaluator']:.2f}")
    if cs['soul_evaluator_models']:
        print(f"    模型分布: {cs['soul_evaluator_models']}")
    print(f"  DirectiveEval 调用: {cs['directive_evaluator_calls']}  → ${cs['cost_breakdown_usd']['directive_evaluator']:.2f}")
    print(f"  ───────────────────────────────────────")
    print(f"  总估算 ({days}d):  ${cs['estimated_total_usd']:.2f}")
    if days > 0:
        monthly = cs['estimated_total_usd'] / days * 30
        print(f"  月度推算:          ${monthly:.2f}/月")

    print("\n" + "=" * 80)
    print("Tip: --days N 看更长 trend | --json 机读输出")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description='Jarvis Daily Stats Dashboard (Phase α)')
    parser.add_argument('--days', type=int, default=1, help='看最近几天 (默认 1)')
    parser.add_argument('--logs-dir', default='docs/runtime_logs',
                        help='日志目录 (默认 docs/runtime_logs)')
    parser.add_argument('--json', action='store_true', help='输出 JSON (机读)')
    args = parser.parse_args()

    if args.json:
        log_paths = _collect_logs(args.logs_dir, args.days)
        c = stat_conversations(log_paths)
        out = {
            'days': args.days,
            'log_count': len(log_paths),
            'conversations': c,
            'nudges': stat_nudges(log_paths),
            'commitments': stat_commitments(log_paths),
            'concerns': stat_concerns(),
            'cost': stat_cost(log_paths, c),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print_dashboard(args.days, args.logs_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
