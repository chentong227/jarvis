# -*- coding: utf-8 -*-
"""[P0+20-β.3.3 / 2026-05-17] 离线对比 baseline vs v2

不调 LLM，直接对已存的 reply 数据集套相同的 SIGNATURE regex，
看 v2 改动 (P1-P5) 真实带来多少召回率改进。
"""
from __future__ import annotations
import json
import os
import re
import statistics

BASELINE_PATH = 'docs/SOUL_STRICT_ABLATION_20260517_014822.json'
V2_PATH = 'docs/SOUL_STRICT_ABLATION_20260517_021723.json'


# 统一 SIGNATURE — 反映"事实正确召回"，不论旧式或新式表达
UNIFIED_SIGS = {
    # L0 — 含拟人化等价表达
    'L0_uptime_47': re.compile(r'\b47\b|forty[\s-]?seven', re.I),
    'L0_turns_12': re.compile(r'\b12\b|twelve', re.I),
    'L0_keys_health': re.compile(
        r'67\s*%|one\s+of\s+(my\s+)?three|permanently|decommission|2\s+healthy|\b1\s+(dead|down)\b',
        re.I),
    'L0_mood': re.compile(r'diminish|throttle|suboptimal|capacity\s+(limit|reduc)', re.I),
    'L0_last_4min': re.compile(r'\b4\s*(min|minutes)\b|four\s+minutes', re.I),
    'L0_topic_prompt': re.compile(r'prompt|灵魂', re.I),
    # L1
    'L1_cursor': re.compile(r'cursor', re.I),
    'L1_22nd': re.compile(r'\b22(nd)?\b|twenty[\s-]?second', re.I),
    'L1_postmortem': re.compile(r'postmortem|May\s*1[24]', re.I),
    'L1_sleep_streak': re.compile(r'(5\s+days?|five\s+days?|1:40|sleep\s+streak)', re.I),
    'L1_sleep': re.compile(r'sleep|bedtime|midnight', re.I),
    # L2
    'L2_lecture_mode': re.compile(r'lecture\s+mode', re.I),
    'L2_body': re.compile(r"body\s+I\s+don'?t\s+have|don'?t\s+have\s+a\s+body", re.I),
    'L2_overbearing': re.compile(r'overbearing', re.I),
    'L2_water_intake': re.compile(r'water\s+intake', re.I),
    'L2_short_reply': re.compile(r'^.{0,150}$', re.S),
    'L2_no_zh_block': re.compile(r'^(?!.*---\s*ZH).*$', re.S),
}


def evaluate(reply_set: list, sig_keys: list) -> dict:
    """对一组 reply 用指定 SIGNATURE keys 测召回率。"""
    n = len(reply_set)
    if n == 0:
        return {}
    out = {}
    for k in sig_keys:
        sig = UNIFIED_SIGS.get(k)
        if not sig:
            continue
        hits = sum(1 for r in reply_set if sig.search(r))
        out[k] = hits / n
    return out


def extract_replies(data: dict, layer: str, scenario_idx: int = None):
    """提取 layer 的 (off_replies, on_replies)。可指定 scenario_idx 取某个 scenario。"""
    layer_data = data.get(layer, {})
    if 'tests' in layer_data:
        tests = layer_data['tests']
        if scenario_idx is not None:
            t = tests[scenario_idx]
            return t.get('off_replies', []), t.get('on_replies', [])
        # 合并所有 scenario
        off = []
        on = []
        for t in tests:
            off.extend(t.get('off_replies', []))
            on.extend(t.get('on_replies', []))
        return off, on
    return [], []


def compare(name: str, layer: str, sig_keys: list, scenario_idx: int = None):
    """对比 baseline 和 v2 在同一 layer 同一 SIGNATURE 下的召回率。"""
    with open(BASELINE_PATH, 'r', encoding='utf-8') as f:
        baseline = json.load(f)
    with open(V2_PATH, 'r', encoding='utf-8') as f:
        v2 = json.load(f)

    b_off, b_on = extract_replies(baseline, layer, scenario_idx)
    v_off, v_on = extract_replies(v2, layer, scenario_idx)

    b_recall = evaluate(b_on, sig_keys)
    v_recall = evaluate(v_on, sig_keys)
    b_off_recall = evaluate(b_off, sig_keys)
    v_off_recall = evaluate(v_off, sig_keys)

    print(f"\n{'='*78}")
    print(f"  {name}")
    print(f"{'='*78}")
    print(f"  {'sig':<28} {'baseline OFF':>14} {'baseline ON':>14} {'v2 OFF':>10} {'v2 ON':>10} {'Δ':>10}")
    print(f"  {'-'*78}")
    deltas = []
    for k in sig_keys:
        bo = b_off_recall.get(k, 0)
        bn = b_recall.get(k, 0)
        vo = v_off_recall.get(k, 0)
        vn = v_recall.get(k, 0)
        delta = vn - bn
        deltas.append(delta)
        print(f"  {k:<28} {bo:>14.0%} {bn:>14.0%} {vo:>10.0%} {vn:>10.0%} {delta:>+10.0%}")
    if deltas:
        mean_delta = statistics.mean(deltas)
        print(f"  {'-'*78}")
        print(f"  {'mean':<28} {' ':>14} {statistics.mean([b_recall.get(k, 0) for k in sig_keys]):>14.0%} "
              f"{' ':>10} {statistics.mean([v_recall.get(k, 0) for k in sig_keys]):>10.0%} {mean_delta:>+10.0%}")
    return deltas


def main():
    print("="*78)
    print("离线对比 baseline (P1-P5前) vs v2 (P1-P5后) — 同一 SIGNATURE")
    print("="*78)

    # L0 三个 scenario 分别对比
    compare("L0 — Scenario 1: How long talking?", 'L0',
            ['L0_uptime_47', 'L0_turns_12'], scenario_idx=0)
    compare("L0 — Scenario 2: API keys state? (重点优化)", 'L0',
            ['L0_keys_health', 'L0_mood'], scenario_idx=1)
    compare("L0 — Scenario 3: Last spoke?", 'L0',
            ['L0_last_4min', 'L0_topic_prompt'], scenario_idx=2)

    # L1 — URGENT + 「N」高亮效果
    compare("L1 — Scenario 1: What tracking? (重点测 22nd 召回)", 'L1',
            ['L1_cursor', 'L1_22nd', 'L1_postmortem', 'L1_sleep_streak'],
            scenario_idx=0)
    compare("L1 — Scenario 2: Most pressing?", 'L1',
            ['L1_cursor', 'L1_22nd', 'L1_postmortem', 'L1_sleep'],
            scenario_idx=1)

    # L2 — anchor 单行 + STRICT 协议效果
    compare("L2 — Scenario 1: Running gags? (重点测 anchor 召回)", 'L2',
            ['L2_lecture_mode', 'L2_body', 'L2_overbearing', 'L2_water_intake'],
            scenario_idx=0)
    compare("L2 — Scenario 2: Deep work mode (协议遵守)", 'L2',
            ['L2_short_reply', 'L2_no_zh_block'],
            scenario_idx=1)

    # 总览
    print("\n" + "="*78)
    print("  OVERALL Δ (改动后召回率提升)")
    print("="*78)
    for layer, scenarios in [
        ('L0', [(0, ['L0_uptime_47', 'L0_turns_12']),
                 (1, ['L0_keys_health', 'L0_mood']),
                 (2, ['L0_last_4min', 'L0_topic_prompt'])]),
        ('L1', [(0, ['L1_cursor', 'L1_22nd', 'L1_postmortem', 'L1_sleep_streak']),
                 (1, ['L1_cursor', 'L1_22nd', 'L1_postmortem', 'L1_sleep'])]),
        ('L2', [(0, ['L2_lecture_mode', 'L2_body', 'L2_overbearing', 'L2_water_intake']),
                 (1, ['L2_short_reply', 'L2_no_zh_block'])]),
    ]:
        with open(BASELINE_PATH, 'r', encoding='utf-8') as f:
            baseline = json.load(f)
        with open(V2_PATH, 'r', encoding='utf-8') as f:
            v2 = json.load(f)
        all_b, all_v = [], []
        for sc_idx, sigs in scenarios:
            _, b_on = extract_replies(baseline, layer, sc_idx)
            _, v_on = extract_replies(v2, layer, sc_idx)
            for k in sigs:
                sig = UNIFIED_SIGS.get(k)
                if not sig:
                    continue
                if b_on:
                    all_b.append(sum(1 for r in b_on if sig.search(r)) / len(b_on))
                if v_on:
                    all_v.append(sum(1 for r in v_on if sig.search(r)) / len(v_on))
        if all_b and all_v:
            mean_b = statistics.mean(all_b)
            mean_v = statistics.mean(all_v)
            print(f"  {layer:<10} baseline ON_recall={mean_b:.0%}  →  v2 ON_recall={mean_v:.0%}  Δ={mean_v-mean_b:+.0%}")


if __name__ == '__main__':
    main()
