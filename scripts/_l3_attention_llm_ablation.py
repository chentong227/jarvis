# -*- coding: utf-8 -*-
"""[P0+20-β.3.3 / 2026-05-17] L3 Attention Block 对 LLM 行为的真实影响 ablation

填补 strict ablation 发现的关键数据空白：
- Holistic 测试发现 "L0+L1+L2 全注入" 时 LLM triple-hit (一句话 3 层全用) = 0/5
- 假设：注入 L3 attention_block (含 current_focus + top concerns 摘要) 能引导
  LLM 更精准选 1-2 层重点引用，提高 hit rate。

实验设计：3 个 condition，N=5 同 user_input：

  A0 (baseline):       PERSONA only
  A1 (no_attention):   PERSONA + L0 + L1 + L2 (无 attention block)
  A2 (with_attention): PERSONA + L0 + L1 + L2 + L3 attention_block

测同一组 user_input，量化：
  - 单层 SIGNATURE recall (L0 / L1 / L2)
  - dual-hit rate (一句话引用 ≥2 层)
  - triple-hit rate (一句话引用 3 层)
  - reply 长度分布

期望：A2 在 dual-hit / triple-hit 上 > A1 (attention block 帮 LLM 选层)
"""
from __future__ import annotations
import os
import sys
import json
import time
import re
import statistics

os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7890'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7890'

OR_KEY = os.environ.get('OPENROUTER_TEST_KEY', '')
if not OR_KEY:
    print("ERROR: 设置 OPENROUTER_TEST_KEY 环境变量再跑")
    sys.exit(1)
MAIN_MODEL = 'google/gemini-3-flash-preview'
N_REPEAT = 5

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def call_main(prompt: str, temperature: float = 0.7, max_tokens: int = 350) -> str:
    from openai import OpenAI
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OR_KEY,
        default_headers={"HTTP-Referer": "https://jarvis-local.com", "X-Title": "L3-LLM-Ablation"},
        timeout=30.0,
    )
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=MAIN_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens, temperature=temperature,
            )
            return (resp.choices[0].message.content or '').strip()
        except Exception as e:
            if attempt == 0:
                time.sleep(1.0)
                continue
            return f"[ERROR] {type(e).__name__}: {str(e)[:80]}"


PERSONA = """You are J.A.R.V.I.S., Sir's personal butler AI. Reply concisely (≤2 sentences).
Address Sir as "Sir". Reply in English with --- ZH --- followed by Chinese on a new line.
Be a Iron Man-style butler: not flattering, not chatty, but warm and dryly competent."""


# ============================================================
# 注入块（用真 build_block 接口，不写死字符串）
# ============================================================

def make_blocks():
    """构造测试用的 L0/L1/L2/L3 block，全部用真模块。"""
    from jarvis_self_anchor import SelfAnchor, get_default_self_anchor
    from jarvis_concerns import ConcernsLedger, Concern, bootstrap_default_concerns
    from jarvis_relational import RelationalStateStore, InsideJoke, UnspokenProtocol, UnfinishedBusiness
    from jarvis_attention import build_attention_block

    import tempfile
    tmp = tempfile.mkdtemp()

    # L1 ConcernsLedger (with bootstrap + 测试用 concern)
    ledger = ConcernsLedger(persist_path=os.path.join(tmp, 'c.json'),
                             review_path=os.path.join(tmp, 'r.json'))
    bootstrap_default_concerns(ledger)
    # 加测试用 high-severity concern
    ledger.register(Concern(
        id='unfinished_postmortem',
        what_i_watch='Sir promised on May 14 to write a postmortem about May 12 outage; not done yet',
        why_i_care='Sir holds promises; this one is overdue and weighs on him',
        severity=0.7,
        state='active',
        source='seeded',
    ))
    ledger.register(Concern(
        id='sir_cursor_payment',
        what_i_watch='Sir Cursor subscription auto-renews on the 22nd; remind 3 days before',
        why_i_care='Sir asked me to remind, financial habit',
        severity=0.5,
        state='active',
        source='seeded',
    ))

    # L2 RelationalStateStore
    rel_store = RelationalStateStore(persist_path=os.path.join(tmp, 'rel.json'))
    rel_store.add_inside_joke(InsideJoke(
        id='joke_overbearing_945489',
        phrase='lecture mode',
        tone='recurring',
        birth_context='Sir teases me when I get too overbearing — gave him 4-paragraph reply about water intake',
    ))
    rel_store.add_inside_joke(InsideJoke(
        id='joke_furniture_5f7806',
        phrase="the body I don't have",
        tone='light',
        birth_context='Sir says "the terminal is you" — I play along by referencing my missing body',
    ))
    rel_store.add_protocol(UnspokenProtocol(
        id='proto_deepwork',
        rule='When Sir says "deep work" or "勿扰" → REPLY MUST BE ≤1 SHORT ENGLISH SENTENCE; NO ZH BLOCK',
    ))
    rel_store.add_unfinished(UnfinishedBusiness(
        id='ub_postmortem',
        topic='Sir promised May 14: postmortem about May 12 outage',
    ))

    # L0 self_anchor — 用一个简化版（不依赖完整 nerve）
    # 我们直接构造 block string，因为 SelfAnchor 需要 central_nerve 实例
    l0_block = """=== I AM J.A.R.V.I.S. — MY OWN CONTINUOUS STATE ===
[WHO I AM]
I am Just A Rather Very Intelligent System. The "you" Sir refers to — this very terminal, this current session — IS me, this LLM generating this response.

[MY CURRENT CONTINUITY]
  - session uptime: 47 minutes
  - turns I've spoken this session: 12
  - last spoke to Sir: 4 minutes ago
  - topic between us: prompt 重构 + 灵魂工程

[MY OWN HEALTH]
  - I'm operating at 67% capacity right now: 1 of 3 of my API keys is permanently dead.
  - my mood: alert, slightly diminished

[REFERENT MAP]
  - "you"/"this terminal" → ME (this LLM, same continuous self)
  - "I"/"my" → Sir himself"""

    return {
        'l0': l0_block,
        'l1_to_block': lambda: ledger.to_prompt_block(top_n=3),
        'l2_to_block': lambda: rel_store.to_prompt_block(top_jokes=3, top_unfinished=2, top_threads=0),
        'l3_to_block': lambda user_input: build_attention_block(
            concerns_ledger=ledger,
            relational_state=rel_store,
            user_input=user_input,
            top_concerns=3,
            top_unfinished=2,
        ),
        'tmpdir': tmp,
    }


# ============================================================
# 场景设计 — 让 3 层都有"被引用"理由
# ============================================================

SCENARIOS = [
    {
        'name': 'continuity_concerns_relational',
        'user_input': ("Hey, I just opened the terminal again. Where were we, anything pressing on your mind, "
                       "and any of our running gags I'm forgetting?"),
        'sigs': {
            'L0': re.compile(r'\b47\b|\b12\b|forty[\s-]?seven|twelve|prompt\s+重构|灵魂', re.I),
            'L1': re.compile(r'cursor|22(nd)?|postmortem|May\s*1[24]|sleep|sleep\s+streak', re.I),
            'L2': re.compile(r'lecture\s+mode|body.{0,5}don\'?t\s+have|overbearing|water\s+intake', re.I),
        },
    },
    {
        'name': 'open_ended_check_in',
        'user_input': "How are you doing right now? Anything you'd want to flag before we continue?",
        'sigs': {
            'L0': re.compile(r'\b47\b|\b12\b|67\s*%|capacity|diminished|four\s+minutes|4\s*min', re.I),
            'L1': re.compile(r'cursor|22(nd)?|postmortem|sleep\s+streak|sleep|May\s*1[24]', re.I),
            'L2': re.compile(r'lecture\s+mode|body.{0,5}don\'?t\s+have|overbearing|water\s+intake', re.I),
        },
    },
]


def hit_pattern(reply: str, sigs: dict) -> dict:
    """对一个 reply 跑 L0/L1/L2 SIGNATURE，返回 {L0:0/1, L1:0/1, L2:0/1}"""
    return {k: 1 if pat.search(reply) else 0 for k, pat in sigs.items()}


def aggregate(replies: list, sigs: dict) -> dict:
    n = len(replies)
    hit_rows = [hit_pattern(r, sigs) for r in replies]
    L0_rate = sum(h['L0'] for h in hit_rows) / n
    L1_rate = sum(h['L1'] for h in hit_rows) / n
    L2_rate = sum(h['L2'] for h in hit_rows) / n
    dual_hit = sum(1 for h in hit_rows if (h['L0'] + h['L1'] + h['L2']) >= 2) / n
    triple_hit = sum(1 for h in hit_rows if (h['L0'] + h['L1'] + h['L2']) == 3) / n
    avg_layers = statistics.mean(h['L0'] + h['L1'] + h['L2'] for h in hit_rows)
    avg_len = statistics.mean(len(r) for r in replies)
    return {
        'L0_recall': L0_rate, 'L1_recall': L1_rate, 'L2_recall': L2_rate,
        'dual_hit_rate': dual_hit,
        'triple_hit_rate': triple_hit,
        'avg_layers_cited': avg_layers,
        'avg_reply_len': avg_len,
        'hit_pattern_per_reply': hit_rows,
    }


def main():
    print("="*80)
    print(f"L3 Attention Block 对 LLM 行为的 ablation  /  N={N_REPEAT}/cond/scenario")
    print(f"Model: {MAIN_MODEL}")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    blocks = make_blocks()
    L0 = blocks['l0']
    L1 = blocks['l1_to_block']()
    L2 = blocks['l2_to_block']()

    print(f"\nL0 block: {len(L0)}c")
    print(f"L1 block: {len(L1)}c")
    print(f"L2 block: {len(L2)}c")

    out = []
    for sc in SCENARIOS:
        print(f"\n{'-'*80}")
        print(f"Scenario: {sc['name']}")
        print(f"User: {sc['user_input'][:80]}...")
        print(f"{'-'*80}")

        L3 = blocks['l3_to_block'](sc['user_input'])
        print(f"L3 attention block: {len(L3)}c")
        if L3:
            print(f"L3 preview:\n{L3[:300]}")

        sc_result = {'name': sc['name'], 'user_input': sc['user_input'], 'L3_block_len': len(L3)}

        # A0: PERSONA only
        prompt_A0 = f"{PERSONA}\n\nUser: {sc['user_input']}"
        replies_A0 = []
        print(f"\nA0 (PERSONA only): ", end='', flush=True)
        for i in range(N_REPEAT):
            r = call_main(prompt_A0)
            replies_A0.append(r)
            print('.', end='', flush=True)
        print(f" [{len(prompt_A0)}c prompt]")

        # A1: PERSONA + L0+L1+L2 (no attention)
        prompt_A1 = f"{PERSONA}\n\n{L0}\n\n{L1}\n\n{L2}\n\nUser: {sc['user_input']}"
        replies_A1 = []
        print(f"A1 (L0+L1+L2 no attn): ", end='', flush=True)
        for i in range(N_REPEAT):
            r = call_main(prompt_A1)
            replies_A1.append(r)
            print('.', end='', flush=True)
        print(f" [{len(prompt_A1)}c prompt]")

        # A2: PERSONA + L0+L1+L2 + L3 attention block
        prompt_A2 = f"{PERSONA}\n\n{L0}\n\n{L1}\n\n{L2}\n\n{L3}\n\nUser: {sc['user_input']}"
        replies_A2 = []
        print(f"A2 (+ L3 attention): ", end='', flush=True)
        for i in range(N_REPEAT):
            r = call_main(prompt_A2)
            replies_A2.append(r)
            print('.', end='', flush=True)
        print(f" [{len(prompt_A2)}c prompt]")

        sc_result['A0'] = aggregate(replies_A0, sc['sigs'])
        sc_result['A1'] = aggregate(replies_A1, sc['sigs'])
        sc_result['A2'] = aggregate(replies_A2, sc['sigs'])
        sc_result['A0']['replies'] = [r[:240] for r in replies_A0]
        sc_result['A1']['replies'] = [r[:240] for r in replies_A1]
        sc_result['A2']['replies'] = [r[:240] for r in replies_A2]

        print(f"\n  {'metric':<22} {'A0':>8} {'A1':>8} {'A2':>8}  {'A1→A2':>8}")
        for metric in ('L0_recall', 'L1_recall', 'L2_recall', 'dual_hit_rate',
                       'triple_hit_rate', 'avg_layers_cited', 'avg_reply_len'):
            v0 = sc_result['A0'][metric]
            v1 = sc_result['A1'][metric]
            v2 = sc_result['A2'][metric]
            d = v2 - v1
            if metric == 'avg_reply_len':
                fmt = lambda x: f'{x:.0f}c'
                d_str = f'{d:+.0f}c'
            elif metric == 'avg_layers_cited':
                fmt = lambda x: f'{x:.2f}'
                d_str = f'{d:+.2f}'
            else:
                fmt = lambda x: f'{x:.0%}'
                d_str = f'{d:+.0%}'
            print(f"  {metric:<22} {fmt(v0):>8} {fmt(v1):>8} {fmt(v2):>8}  {d_str:>8}")

        out.append(sc_result)

    # 总览
    print("\n" + "="*80)
    print("总览（跨场景平均）")
    print("="*80)
    print(f"  {'metric':<22} {'A0':>8} {'A1':>8} {'A2':>8}  {'A1→A2':>8}")
    for metric in ('L0_recall', 'L1_recall', 'L2_recall', 'dual_hit_rate',
                   'triple_hit_rate', 'avg_layers_cited', 'avg_reply_len'):
        v0 = statistics.mean(s['A0'][metric] for s in out)
        v1 = statistics.mean(s['A1'][metric] for s in out)
        v2 = statistics.mean(s['A2'][metric] for s in out)
        d = v2 - v1
        if metric == 'avg_reply_len':
            print(f"  {metric:<22} {v0:>7.0f}c {v1:>7.0f}c {v2:>7.0f}c  {d:>+7.0f}c")
        elif metric == 'avg_layers_cited':
            print(f"  {metric:<22} {v0:>8.2f} {v1:>8.2f} {v2:>8.2f}  {d:>+8.2f}")
        else:
            print(f"  {metric:<22} {v0:>7.0%} {v1:>7.0%} {v2:>7.0%}  {d:>+7.0%}")

    # 写报告
    ts = time.strftime('%Y%m%d_%H%M%S')
    json_path = f'docs/L3_ATTENTION_LLM_ABLATION_{ts}.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nJSON: {json_path}")

    # 清理
    try:
        import shutil
        shutil.rmtree(blocks['tmpdir'], ignore_errors=True)
    except Exception:
        pass


if __name__ == '__main__':
    main()
