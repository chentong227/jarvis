# -*- coding: utf-8 -*-
"""[temp smoke test] /api/stand_down + /api/stand_down_action."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 先 clear 任何现有 state, 隔离测试
import jarvis_stand_down as sd
if sd.is_active():
    sd.clear_stand_down(source='audit_smoke')

import jarvis_dashboard_web as d

with d.app.test_client() as c:
    r = c.get('/api/stand_down')
    print('GET /api/stand_down status:', r.status_code)
    j = r.get_json()
    print('ok:', j.get('ok'))
    if j.get('ok'):
        print('state.active:', j['data']['state']['active'])
        print('history count:', len(j['data']['history']))
        print('stats:', j['data']['stats'])

    r2 = c.post('/api/stand_down_action',
                 json={'action': 'set', 'reason': 'phone_call', 'duration_min': 5})
    print()
    print('POST set status:', r2.status_code)
    j2 = r2.get_json()
    print('  ok:', j2.get('ok'), '| msg:', j2.get('message'))

    r3 = c.get('/api/stand_down')
    j3 = r3.get_json()
    print()
    print('After set:')
    print('  active:', j3['data']['state']['active'])
    print('  reason:', j3['data']['state']['reason'])
    print('  in_grace:', j3['data']['state']['in_grace'])
    print('  remaining_s:', j3['data']['state']['remaining_s'])

    r4 = c.post('/api/stand_down_action', json={'action': 'clear', 'reason': 'test'})
    j4 = r4.get_json()
    print()
    print('POST clear ok:', j4.get('ok'), 'msg:', j4.get('message'))
