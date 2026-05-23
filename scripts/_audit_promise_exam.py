# -*- coding: utf-8 -*-
"""[temp audit] 找 stale 体检/面试 promise."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open('memory_pool/jarvis_promise_log.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

hits = []
for pid, p in data.items():
    if p.get('state') != 'pending':
        continue
    desc = (p.get('description') or '').lower()
    src = (p.get('source_text') or '').lower() if isinstance(p.get('source_text'), str) else ''
    jrep = (p.get('jarvis_reply') or '')
    src_text = (p.get('source_text') or '') if isinstance(p.get('source_text'), str) else ''
    blob = (desc + ' ' + src + ' ' + (jrep.lower() if jrep else '') + ' ' + src_text.lower()).lower()
    if any(t in blob for t in ('exam', 'medical', 'interview', 'examination',
                                  '\u4f53\u68c0', '\u533b\u9662', '\u9762\u8bd5')):
        hits.append((pid, p))

print('Found', len(hits), 'pending exam/interview promises:')
for pid, p in hits:
    auth = p.get('author', '?')
    reg = time.strftime('%m-%d %H:%M', time.localtime(p.get('registered_at', 0)))
    desc = (p.get('description') or '')[:80]
    src = (p.get('source_text') or '')[:80] if isinstance(p.get('source_text'), str) else ''
    jrep = (p.get('jarvis_reply') or '')[:80]
    print('  ', pid, 'author=' + auth, 'reg=' + reg)
    print('     desc=', desc)
    if src:
        print('     src=', src)
    if jrep:
        print('     jarvis_reply=', jrep)
