#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 Phase 5] InnerVoice — Sir 主动注入想法 CLI.

Sir 可在 jarvis 跑时直接注入"心声", source='sir_injected'. 主脑下次召唤会
看到, 思考脑也会读. 用于:

  - Sir 提前告知: "我等会要洗澡, 别提醒水" → inject 一句, jarvis 自己装下来
  - Sir 引导话题: "我现在心情低, 别太兴奋" → inject, 主脑下轮自然 match 情绪
  - Sir 加 commitment 待办: "记得 3pm 提醒我开会" → inject ★, spotlight 顶推

用法:
  python scripts/inner_voice_inject.py "想跟 Sir 说洗澡前 5min 我会提醒"
  python scripts/inner_voice_inject.py "Sir 心情低, 别太兴奋" --urgency 0.7 --no-want
  python scripts/inner_voice_inject.py "提醒 3pm 开会" --intent reminder --urgency 0.9 --want
  python scripts/inner_voice_inject.py "天气好, 让 jarvis 知道" --intent observation
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description='Sir 注入 inner_voice (source=sir_injected)'
    )
    p.add_argument('content', type=str,
                          help='注入内容 (一句话, ≤300 char)')
    p.add_argument('--intent', type=str, default='reflection',
                          choices=['observation', 'care', 'reflection',
                                       'reminder', 'noting'],
                          help='intent label (default reflection)')
    p.add_argument('--urgency', type=float, default=0.5,
                          help='0-1 紧急度 (default 0.5)')
    grp = p.add_mutually_exclusive_group()
    grp.add_argument('--want', dest='wants_voice', action='store_true',
                              help='★ wants_voice=True (默 True)')
    grp.add_argument('--no-want', dest='wants_voice', action='store_false',
                              help='不带 ★ (内部 awareness only)')
    p.set_defaults(wants_voice=True)
    p.add_argument('--source', type=str, default='sir_injected',
                          help='源 (default sir_injected). 其它用例: noting')
    args = p.parse_args(argv)

    if not args.content or not args.content.strip():
        print('error: content empty', file=sys.stderr)
        return 2

    from jarvis_inner_voice_track import (
        get_inner_voice_track, is_enabled,
    )
    if not is_enabled():
        print('warn: JARVIS_INNER_VOICE_ENABLED=0, append 仍 work 但主脑不读',
              file=sys.stderr)

    track = get_inner_voice_track()
    e = track.append(
        source=str(args.source),
        intent=str(args.intent),
        content=str(args.content),
        urgency=float(args.urgency),
        wants_voice=bool(args.wants_voice),
        meta={'kind': 'sir_injection'},
    )
    print(f'[ok] injected: id={e.entry_id}')
    print(f'     source={e.source} intent={e.intent} '
          f'urgency={e.urgency:.2f} wants_voice={e.wants_voice}')
    print(f'     content: {e.content}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
