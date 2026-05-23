# -*- coding: utf-8 -*-
"""[temp smoke test] dismiss / reactivate API."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_concerns import ConcernsLedger, Concern

L = ConcernsLedger(persist_path='_test_concerns.json', review_path='_test_review.json')
c = Concern(id='test_c', what_i_watch='x', why_i_care='y', severity=1.0)
L.register(c)
print('Before dismiss: triggers_proactive=', L.concerns['test_c'].triggers_proactive,
        'severity=', L.concerns['test_c'].severity)
ok = L.dismiss('test_c', reason="Sir said don't worry", source='sir_voice',
                  source_turn_id='turn_xxx')
print('Dismiss returned:', ok)
print('After dismiss : triggers_proactive=', L.concerns['test_c'].triggers_proactive,
        'severity=', L.concerns['test_c'].severity)
print('Signal count:', len(L.concerns['test_c'].recent_signals))
print('Last signal:', L.concerns['test_c'].recent_signals[-1]['what'][:80])
print('Notes:', L.concerns['test_c'].notes_for_self[:100])
print()

ok = L.reactivate('test_c', reason='changed my mind', source='sir_voice')
print('Reactivate returned:', ok)
print('After reactivate: triggers_proactive=', L.concerns['test_c'].triggers_proactive)
print('Severity unchanged:', L.concerns['test_c'].severity)

# 不存在 concern
ok = L.dismiss('does_not_exist', reason='x')
print('Dismiss missing returned:', ok, '(should be False)')

# cleanup
for f in ['_test_concerns.json', '_test_review.json']:
    if os.path.exists(f):
        os.remove(f)
