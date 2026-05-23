# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_intent_router import IntentParser, get_default_intent_router

text = '<TOOL_CALL>{"intent": "dashboard_open"}</TOOL_CALL>'
print('has_tool_call_tag:', IntentParser.has_tool_call_tag(text))
calls = IntentParser.extract_all(text)
print('parsed calls:', len(calls))
for c in calls:
    print('  intent=', c.intent_id, 'args=', c.args)

router = get_default_intent_router()
print('router:', router)
if router:
    print('  fast_call_executor:', router.fast_call_executor)
    entry = router.resolve_intent('dashboard_open')
    print('  resolve dashboard_open:', entry)

    # try invoke (will fail if no fast_call_executor)
    if router.fast_call_executor is None:
        print()
        print('❌ ROOT CAUSE: get_default_intent_router has NO fast_call_executor!')
        print('   stream_chat 末尾调 get_default_intent_router() 但 lazy init')
        print('   而 init_default_intent_router(fast_call_executor=...) 在 central_nerve 调.')
        print('   如果调用顺序不对, 可能 lazy 创建了 router 但 fast_call_executor=None.')
