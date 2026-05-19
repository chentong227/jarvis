"""Quick benchmark: CosyVoice render speed isolation test."""
import sys, os, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'CosyVoice'))

os.environ['TQDM_DISABLE'] = '1'
import logging
logging.getLogger().setLevel(logging.ERROR)

print('[1/6] loading VocalCord...')
t0 = time.time()
from jarvis_vocal_cord import VocalCord
v = VocalCord()
print(f'    init done in {time.time()-t0:.2f}s (含 warmup)')

print('[2/6] render 1: "It is 5:58 PM, Sir." (19 chars)')
t1 = time.time()
b1 = v.render_only('It is 5:58 PM, Sir.')
dt1 = time.time() - t1
print(f'    -> {dt1:.3f}s, bytes={len(b1) if b1 else 0}')

print('[3/6] render 2 (same text, cache test)')
t2 = time.time()
b2 = v.render_only('It is 5:58 PM, Sir.')
dt2 = time.time() - t2
print(f'    -> {dt2:.3f}s')

print('[4/6] render 3: "Yes, Sir." (9 chars)')
t3 = time.time()
b3 = v.render_only('Yes, Sir.')
dt3 = time.time() - t3
print(f'    -> {dt3:.3f}s')

print('[5/6] render 4: "A fortuitous outcome, Sir." (26 chars)')
t4 = time.time()
b4 = v.render_only('A fortuitous outcome, Sir.')
dt4 = time.time() - t4
print(f'    -> {dt4:.3f}s')

print('[6/6] render 5: long sentence ~80 chars')
t5 = time.time()
b5 = v.render_only('Sir, the network appears congested this morning, though I should be ready momentarily.')
dt5 = time.time() - t5
print(f'    -> {dt5:.3f}s')

print()
print(f'=== SUMMARY ===')
print(f'  19 chars: {dt1:.2f}s (cold) / {dt2:.2f}s (hot)')
print(f'   9 chars: {dt3:.2f}s')
print(f'  26 chars: {dt4:.2f}s')
print(f'  88 chars: {dt5:.2f}s')
print(f'  推断: 短句 1-2s 正常, 6s 异常')
