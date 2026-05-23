# -*- coding: utf-8 -*-
"""[hotfix] Sir 体检已完成 — cancel 两个 stale 体检 promise.
- p_b344410c author=sir 5/21 21:04 (要去医院)
- p_cdc96ad5 author=jarvis 5/22 14:36 (我会关注体检)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_promise_log import get_default_log

log = get_default_log()
for pid in ('p_b344410c', 'p_cdc96ad5'):
    ok = log.mark_cancelled(pid, reason='Sir 5/22 体检已完成 — 热修 cancel stale')
    print(f'{pid}: cancelled={ok}')

# 显示 stats
print()
print('After cancel stats:', log.stats())
