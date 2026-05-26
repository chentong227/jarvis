# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 20:14 真意 anchor 3] Sir Skepticism Loop CLI Dump.

让 Sir 一行命令查看 / 操作 Sir Skepticism Learning Loop 状态.

用法:
    python scripts/sir_skepticism_dump.py                      # ASCII 表 (vocab + decayed items)
    python scripts/sir_skepticism_dump.py --vocab              # 仅看 vocab (keywords + thresholds)
    python scripts/sir_skepticism_dump.py --items              # 仅看被 decayed 的 items
    python scripts/sir_skepticism_dump.py --reactivate joke <id>     # 反激活 inside joke (count→0, weight 恢复)
    python scripts/sir_skepticism_dump.py --reactivate concern <id>  # 反激活 concern (count→0)
    python scripts/sir_skepticism_dump.py --reactivate protocol <id> # 反激活 protocol (count→0)
    python scripts/sir_skepticism_dump.py --add-keyword <type> <phrase>   # 加 vocab keyword
                                                                          # type ∈ skepticism_zh/skepticism_en/confusion/reactivation_zh/reactivation_en
    python scripts/sir_skepticism_dump.py --json                          # 机读 JSON

文件依赖:
- memory_pool/sir_skepticism_vocab.json      ← vocab + history + thresholds
- memory_pool/relational_state.json          ← inside_jokes / protocols (with skepticism_count)
- memory_pool/concerns.json                  ← concerns (with skepticism_count)

规范: docs/JARVIS_THINKING_TO_AGENCY_DESIGN.md §3 + jarvis_sir_skepticism.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time


if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        os.system('chcp 65001 > nul 2>&1')
    except Exception:
        pass

os.environ.setdefault('HTTP_PROXY', 'http://127.0.0.1:7890')
os.environ.setdefault('HTTPS_PROXY', 'http://127.0.0.1:7890')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'memory_pool', 'sir_skepticism_vocab.json',
)


# ==========================================================================
# Vocab IO
# ==========================================================================
def _load_vocab() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return {}
    try:
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ vocab load fail: {e}")
        return {}


def _save_vocab(data: dict) -> None:
    try:
        with open(VOCAB_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ vocab save fail: {e}")


def _append_history(data: dict, entry: dict) -> None:
    history = data.setdefault('history', [])
    entry['ts'] = time.time()
    entry['ts_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())
    history.append(entry)
    # cap 200
    if len(history) > 200:
        data['history'] = history[-200:]


# ==========================================================================
# Print helpers
# ==========================================================================
def _print_vocab(data: dict) -> None:
    print("\n=== Sir Skepticism Vocab ===")
    meta = data.get('_meta') or {}
    thresholds = meta.get('decay_thresholds') or {}
    print(f"  schema={meta.get('schema_version', '?')}  "
          f"created={meta.get('created_at', '?')}")
    print(f"  thresholds: count_1_weight={thresholds.get('count_1_weight', 0.7):.2f}  "
          f"count_2_weight={thresholds.get('count_2_weight', 0.5):.2f}  "
          f"count_3_action={thresholds.get('count_3_action', 'auto_archive')!r}")

    for key, label in (
        ('skepticism_keywords_zh', '质疑 zh'),
        ('skepticism_keywords_en', '质疑 en'),
        ('confusion_keywords', '困惑 (不累 count)'),
        ('reactivation_keywords_zh', '反悔 zh'),
        ('reactivation_keywords_en', '反悔 en'),
    ):
        kws = data.get(key) or []
        if kws:
            print(f"\n  [{label}] ({len(kws)})")
            for kw in kws:
                print(f"    • {kw}")
    history = data.get('history') or []
    review = data.get('review_queue') or []
    print(f"\n  history entries: {len(history)} | review queue: {len(review)}")


def _print_decayed_items() -> None:
    """显示当前 inside_jokes / protocols / concerns 含 skepticism_count > 0 的项."""
    print("\n=== Decayed Items (skepticism_count > 0) ===")

    # Inside jokes + protocols
    try:
        from jarvis_relational import RelationalStateStore
        store = RelationalStateStore()
        try:
            store.load_from_disk()
        except Exception:
            pass

        skep_jokes = [
            j for j in store.inside_jokes.values()
            if int(getattr(j, 'skepticism_count', 0) or 0) > 0
        ]
        if skep_jokes:
            print("\n  [Inside Jokes]")
            for j in sorted(skep_jokes,
                              key=lambda x: -int(getattr(x, 'skepticism_count', 0))):
                print(
                    f"    • {j.id} | count={j.skepticism_count} "
                    f"| weight={getattr(j, 'use_weight', 1.0):.2f} "
                    f"| state={j.state} | phrase=\"{(j.phrase or '')[:60]}\""
                )

        skep_protos = [
            p for p in store.unspoken_protocols.values()
            if int(getattr(p, 'skepticism_count', 0) or 0) > 0
        ]
        if skep_protos:
            print("\n  [Protocols]")
            for p in sorted(skep_protos,
                              key=lambda x: -int(getattr(x, 'skepticism_count', 0))):
                print(
                    f"    • {p.id} | count={p.skepticism_count} "
                    f"| rejected={getattr(p, 'rejected', 0)} "
                    f"| state={p.state} | rule=\"{(p.rule or '')[:60]}\""
                )
    except Exception as e:
        print(f"  ⚠️ relational state load fail: {e}")

    # Concerns
    try:
        from jarvis_concerns import ConcernsLedger
        ledger = ConcernsLedger()
        try:
            ledger.load_from_disk()
        except Exception:
            pass
        skep_concerns = [
            c for c in ledger.concerns.values()
            if int(getattr(c, 'skepticism_count', 0) or 0) > 0
        ]
        if skep_concerns:
            print("\n  [Concerns]")
            for c in sorted(skep_concerns,
                              key=lambda x: -int(getattr(x, 'skepticism_count', 0))):
                print(
                    f"    • {c.id} | count={c.skepticism_count} "
                    f"| severity={c.severity:.2f} "
                    f"| state={c.state} | what=\"{(c.what_i_watch or '')[:60]}\""
                )
    except Exception as e:
        print(f"  ⚠️ concerns load fail: {e}")


# ==========================================================================
# Mutation: reactivate
# ==========================================================================
def _reactivate(kind: str, item_id: str) -> bool:
    """Sir 元否决: 反激活某 item, 把 skepticism_count → 0, 恢复 state/weight."""
    kind = (kind or '').lower().strip()
    if kind in ('joke', 'inside_joke'):
        return _reactivate_joke(item_id)
    elif kind in ('proto', 'protocol'):
        return _reactivate_protocol(item_id)
    elif kind == 'concern':
        return _reactivate_concern(item_id)
    else:
        print(f"⚠️ kind 必须 ∈ joke / protocol / concern, got {kind!r}")
        return False


def _reactivate_joke(jid: str) -> bool:
    try:
        from jarvis_relational import get_default_store
        store = get_default_store()
        joke = store.inside_jokes.get(jid)
        if joke is None:
            print(f"⚠️ inside_joke '{jid}' not found")
            return False
        old_count = int(getattr(joke, 'skepticism_count', 0) or 0)
        old_weight = float(getattr(joke, 'use_weight', 1.0) or 1.0)
        old_state = joke.state
        joke.skepticism_count = 0
        joke.use_weight = 1.0
        if old_state == 'archived':
            joke.state = 'active'  # un-archive
        store._dirty = True
        store.persist()

        # log to vocab history
        data = _load_vocab()
        _append_history(data, {
            'action': 'reactivate_inside_joke',
            'target_id': jid,
            'phrase': (joke.phrase or '')[:80],
            'old_count': old_count, 'old_weight': old_weight,
            'old_state': old_state,
            'source': 'cli_sir_veto',
        })
        _save_vocab(data)
        print(f"✅ reactivated inside_joke '{jid}' (count {old_count}→0, "
              f"weight {old_weight:.2f}→1.0, state {old_state}→{joke.state})")
        return True
    except Exception as e:
        print(f"⚠️ reactivate joke exception: {e}")
        return False


def _reactivate_protocol(pid: str) -> bool:
    try:
        from jarvis_relational import get_default_store
        store = get_default_store()
        proto = store.unspoken_protocols.get(pid)
        if proto is None:
            print(f"⚠️ protocol '{pid}' not found")
            return False
        old_count = int(getattr(proto, 'skepticism_count', 0) or 0)
        old_rejected = int(getattr(proto, 'rejected', 0) or 0)
        old_state = proto.state
        proto.skepticism_count = 0
        # 不重置 rejected (历史记录), Sir 主动恢复就好
        if old_state == 'archived':
            proto.state = 'active'
        store._dirty = True
        store.persist()

        data = _load_vocab()
        _append_history(data, {
            'action': 'reactivate_protocol',
            'target_id': pid,
            'rule': (proto.rule or '')[:80],
            'old_count': old_count,
            'old_rejected': old_rejected,
            'old_state': old_state,
            'source': 'cli_sir_veto',
        })
        _save_vocab(data)
        print(f"✅ reactivated protocol '{pid}' (count {old_count}→0, "
              f"state {old_state}→{proto.state})")
        return True
    except Exception as e:
        print(f"⚠️ reactivate protocol exception: {e}")
        return False


def _reactivate_concern(cid: str) -> bool:
    try:
        from jarvis_concerns import get_default_ledger
        ledger = get_default_ledger()
        if ledger is None:
            print(f"⚠️ concerns ledger unavailable")
            return False
        concern = ledger.concerns.get(cid)
        if concern is None:
            print(f"⚠️ concern '{cid}' not found")
            return False
        old_count = int(getattr(concern, 'skepticism_count', 0) or 0)
        old_state = concern.state
        old_severity = concern.severity
        concern.skepticism_count = 0
        if old_state in ('dismissed', 'archived'):
            concern.state = 'active'
        ledger._dirty = True

        data = _load_vocab()
        _append_history(data, {
            'action': 'reactivate_concern',
            'target_id': cid,
            'what': (concern.what_i_watch or '')[:80],
            'old_count': old_count,
            'old_severity': old_severity,
            'old_state': old_state,
            'source': 'cli_sir_veto',
        })
        _save_vocab(data)
        print(f"✅ reactivated concern '{cid}' (count {old_count}→0, "
              f"state {old_state}→{concern.state})")
        return True
    except Exception as e:
        print(f"⚠️ reactivate concern exception: {e}")
        return False


# ==========================================================================
# Mutation: add vocab keyword (Sir 手动 vocab 扩展 — L7 reflector 后期 LLM-propose)
# ==========================================================================
def _add_keyword(kind: str, phrase: str) -> bool:
    kind_map = {
        'skepticism_zh': 'skepticism_keywords_zh',
        'skepticism_en': 'skepticism_keywords_en',
        'confusion': 'confusion_keywords',
        'reactivation_zh': 'reactivation_keywords_zh',
        'reactivation_en': 'reactivation_keywords_en',
    }
    key = kind_map.get(kind)
    if key is None:
        print(f"⚠️ kind 必须 ∈ {list(kind_map.keys())}, got {kind!r}")
        return False
    phrase = phrase.strip()
    if not phrase:
        print(f"⚠️ phrase 不能为空")
        return False

    data = _load_vocab()
    kws = data.setdefault(key, [])
    if phrase in kws:
        print(f"⚠️ phrase {phrase!r} 已存在 {key}")
        return False
    kws.append(phrase)
    _append_history(data, {
        'action': 'add_keyword',
        'kind': kind, 'phrase': phrase,
        'source': 'cli_sir_manual',
    })
    _save_vocab(data)
    print(f"✅ added {kind!r} keyword {phrase!r} ({len(kws)} total)")
    return True


# ==========================================================================
# CLI main
# ==========================================================================
def main() -> int:
    p = argparse.ArgumentParser(description='Sir Skepticism Loop CLI')
    p.add_argument('--vocab', action='store_true',
                   help='print vocab only')
    p.add_argument('--items', action='store_true',
                   help='print decayed items only')
    p.add_argument('--reactivate', nargs=2, metavar=('KIND', 'ID'),
                   help='reactivate item: KIND ∈ joke/protocol/concern')
    p.add_argument('--add-keyword', nargs=2, metavar=('KIND', 'PHRASE'),
                   help='add vocab keyword: KIND ∈ skepticism_zh/skepticism_en/confusion/reactivation_zh/reactivation_en')
    p.add_argument('--json', action='store_true',
                   help='machine-readable output (vocab only)')
    args = p.parse_args()

    if args.json:
        data = _load_vocab()
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    if args.reactivate:
        kind, item_id = args.reactivate
        return 0 if _reactivate(kind, item_id) else 1

    if args.add_keyword:
        kind, phrase = args.add_keyword
        return 0 if _add_keyword(kind, phrase) else 1

    # default: print both vocab + items
    data = _load_vocab()
    if not data:
        print(f"⚠️ vocab file empty / missing: {VOCAB_PATH}")
        return 1
    if not args.items:
        _print_vocab(data)
    if not args.vocab:
        _print_decayed_items()
    return 0


if __name__ == '__main__':
    sys.exit(main())
