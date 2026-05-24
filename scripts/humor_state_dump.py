# -*- coding: utf-8 -*-
"""[Reshape M3.H / 2026-05-24] CLI dump for HumorMemory state.

# Usage

```
python scripts/humor_state_dump.py             # full snapshot
python scripts/humor_state_dump.py --json       # raw JSON
python scripts/humor_state_dump.py --topics     # only topic cooldowns
python scripts/humor_state_dump.py --weights    # only topic weights
```

# Output

- 全局 joke cooldown 剩余秒
- 各 topic 冷却剩余 + freshness
- 各 topic weight (用户反馈减权)
- profile keyword 真激活的 jokes (来自 RelationalState)
- 最近 5 条 register_joke 历史

# 准则 6 — 数据强耦合 + CLI 可看

humor_state.json 持久化 + 此 CLI dump + register_joke publish SWM event.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _format_seconds(s: float) -> str:
    if s <= 0:
        return 'expired'
    if s < 60:
        return f'{int(s)}s'
    if s < 3600:
        return f'{s/60:.1f}min'
    return f'{s/3600:.1f}h'


def main():
    parser = argparse.ArgumentParser(
        description='Dump HumorMemory state (cooldowns / weights / recent fires)'
    )
    parser.add_argument('--json', action='store_true',
                        help='raw JSON output (pipe-friendly)')
    parser.add_argument('--topics', action='store_true',
                        help='only show topic cooldowns')
    parser.add_argument('--weights', action='store_true',
                        help='only show topic weights')
    args = parser.parse_args()

    try:
        from jarvis_memory_core import HumorMemory
    except Exception as e:
        print(f'❌ import HumorMemory failed: {e}', file=sys.stderr)
        sys.exit(1)

    hm = HumorMemory()
    snap = hm.get_state_snapshot()

    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2, default=str))
        return

    if args.topics:
        print('# Topic cooldowns')
        if not snap['topic_cooldowns']:
            print('  (none)')
        else:
            for k, v in sorted(snap['topic_cooldowns'].items(),
                                key=lambda x: -x[1]['last_fired_at']):
                print(f"  {k:30s}  cd_remain={_format_seconds(v['cooldown_remain_s']):>8s}  "
                      f"freshness={v['freshness']:.1f}")
        return

    if args.weights:
        print('# Topic weights')
        if not snap['topic_weights']:
            print('  (none)')
        else:
            for k, v in sorted(snap['topic_weights'].items(), key=lambda x: -x[1]):
                print(f"  {k:30s}  weight={v:.2f}")
        return

    # full
    print('=' * 60)
    print('HumorMemory state snapshot')
    print('=' * 60)
    g_cd = snap['global_cooldown_remain_s']
    print(f"\nGlobal joke cooldown:    {_format_seconds(g_cd):>8s}")
    print(f"Used topics in deque:    {snap['used_topics_count']}")
    print(f"Profile keywords active: {len(snap['profile_keywords_active'])}")
    if snap['profile_keywords_active']:
        print(f"  → {', '.join(snap['profile_keywords_active'])}")

    if snap['used_topics_recent5']:
        print('\n## Recent 5 fires')
        now = time.time()
        for entry in snap['used_topics_recent5']:
            ago = now - entry.get('time', 0)
            print(f"  [{_format_seconds(ago):>8s} ago] {entry.get('topic'):20s}  "
                  f"text={entry.get('text', '')[:60]}")

    if snap['topic_cooldowns']:
        print('\n## Topic cooldowns (top 10 most recent)')
        sorted_cds = sorted(snap['topic_cooldowns'].items(),
                              key=lambda x: -x[1]['last_fired_at'])[:10]
        for k, v in sorted_cds:
            print(f"  {k:30s}  cd_remain={_format_seconds(v['cooldown_remain_s']):>8s}  "
                  f"freshness={v['freshness']:.1f}")
    else:
        print('\n## Topic cooldowns: (none)')

    if snap['topic_weights']:
        print('\n## Topic weights (减权 by user feedback)')
        for k, v in sorted(snap['topic_weights'].items(), key=lambda x: -x[1]):
            bar_n = int(v * 10)
            print(f"  {k:30s}  weight={v:.2f}  {'█' * bar_n}")

    print('\n' + '=' * 60)
    print(f'humor_state.json: jarvis_config/humor_state.json')
    print('=' * 60)


if __name__ == '__main__':
    main()
