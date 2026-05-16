"""[P0+20-β.0.2 smoke] 验证 _assemble_prompt dry-run 路径 + registry 单例正常。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jarvis_central_nerve  # noqa: F401
from jarvis_directives import (
    DirectiveContext,
    get_default_registry,
    reset_default_registry_for_test,
)


def main():
    reset_default_registry_for_test()
    r = get_default_registry()
    print(f"registry bootstrapped, total directives: {len(r.directives)}")

    # Case 1: P0+18-f.2 场景
    ctx = DirectiveContext(
        user_input="不用再提",
        last_jarvis_reply="I've struck it from the active agenda.",
        stm=[{"user": "x", "jarvis": "y"}],
        tier="SHORT_CHAT",
    )
    fired = r.collect(ctx)
    print(f"Case 1 (nudge refusal): fired={[d.id for d in fired]}")

    # Case 2: TWO_PARTS (Sir 09:25 BUG)
    ctx2 = DirectiveContext(
        user_input="OK got it, by the way how is the deploy going?",
        stm=[{"user": "p", "jarvis": "q"}],
        tier="SHORT_CHAT",
    )
    fired2 = r.collect(ctx2)
    print(f"Case 2 (two parts): fired={[d.id for d in fired2]}")

    # Case 3: 首轮纯英文 short chat
    ctx3 = DirectiveContext(
        user_input="what time is it",
        stm=[],
        tier="SHORT_CHAT",
    )
    fired3 = r.collect(ctx3)
    print(f"Case 3 (cold short): fired={[d.id for d in fired3]}")

    # Case 4: TOOL_REQUEST + 失败
    ctx4 = DirectiveContext(
        user_input="open the file",
        last_tool_results=["❌ file_hands.open: not found"],
        stm=[{"user": "p", "jarvis": "q"}],
        tier="TOOL_REQUEST",
    )
    fired4 = r.collect(ctx4)
    print(f"Case 4 (tool fail): fired={[d.id for d in fired4]}")

    # 看 dump_human
    print()
    print(r.dump_human())


if __name__ == "__main__":
    main()
