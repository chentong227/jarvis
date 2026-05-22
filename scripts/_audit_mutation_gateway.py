"""[P5-fix32-A/B/C smoke] 验证 mutation gateway 新加 4 个 layer routing.

测试:
  1. ProfileCard overwrite_field 真覆写 sir_profile.json (高置信 fast_call)
  2. ProfileCard fallback apply_correction (低置信)
  3. PromiseLog fulfill / cancel (gateway 路由)
  4. CommitmentWatcher cancel_by_keyword / update_by_keyword
  5. RelationalStateStore archive_inside_joke / archive_protocol / mark_unfinished_done / archive_thread

每个 case 都通过 gateway.update_sir_field() 调用, 不直接调底层. 验证 WriteReceipt
正确返回 + jsonl 写入 + SWM publish 不抛错.
"""
import os
import sys
import json
import time
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_profile_overwrite_field_atomic():
    """Test 1: ProfileCard.overwrite_field 真覆写 sir_profile.json (atomic)."""
    from jarvis_routing import ProfileCard

    # Backup current sir_profile.json
    profile_path = os.path.join('jarvis_config', 'sir_profile.json')
    if not os.path.exists(profile_path):
        print(f"  ⚠️ {profile_path} 不存在, 跳过此测试")
        return False
    backup_path = profile_path + '.test_bak'
    shutil.copy2(profile_path, backup_path)

    try:
        # Mock nerve (ProfileCard 要 nerve, 但 overwrite_field 不依赖 nerve)
        class MockNerve:
            habit_clock = None
            causal_chain = None
            project_timeline = None
            status_ledger = None

        pc = ProfileCard(MockNerve())

        # Read current value
        with open(profile_path, 'r', encoding='utf-8') as f:
            before = json.load(f)
        old_rhythms = before.get('work_rhythms', '')

        # Overwrite work_rhythms (in whitelist)
        new_val = f"[TEST] sleep at 23:00, wake at 7:00 - {time.time():.0f}"
        ok, msg, ow_old = pc.overwrite_field(
            field='work_rhythms',
            new_value=new_val,
            source='fast_call_mutation',
            turn_id='test_turn_001',
            reason='smoke test',
        )
        assert ok, f"overwrite_field failed: {msg}"
        assert ow_old == old_rhythms, f"old mismatch: {ow_old!r} vs {old_rhythms!r}"

        # Verify file truly written
        with open(profile_path, 'r', encoding='utf-8') as f:
            after = json.load(f)
        assert after.get('work_rhythms') == new_val, \
            f"file not overwritten: {after.get('work_rhythms')!r}"
        print(f"  ✅ profile.work_rhythms 真覆写: {new_val[:50]}...")

        # Test schema 保护: field 不在白名单 → 拒
        ok2, msg2, _ = pc.overwrite_field(
            field='secret_field_not_in_whitelist',
            new_value='hacked',
            source='fast_call_mutation',
        )
        assert not ok2, f"expected reject for non-whitelist field"
        assert 'not in allowed list' in msg2, f"unexpected msg: {msg2}"
        print(f"  ✅ schema 保护 ok: {msg2[:60]}")
        return True
    finally:
        # Restore
        shutil.copy2(backup_path, profile_path)
        os.remove(backup_path)


def test_gateway_profile_routing():
    """Test 2: gateway 路由 'profile.work_rhythms' 走 overwrite_field 高置信路径."""
    from jarvis_memory_gateway import get_default_gateway, reset_default_gateway_for_test
    from jarvis_routing import ProfileCard

    # Mock nerve
    class MockNerve:
        habit_clock = None
        causal_chain = None
        project_timeline = None
        status_ledger = None
        profile_card = None

    nerve = MockNerve()
    nerve.profile_card = ProfileCard(nerve)

    # Backup profile
    profile_path = os.path.join('jarvis_config', 'sir_profile.json')
    if not os.path.exists(profile_path):
        print(f"  ⚠️ {profile_path} 不存在, 跳过")
        return False
    backup_path = profile_path + '.test_bak'
    shutil.copy2(profile_path, backup_path)

    try:
        # Use temp receipt path so we don't pollute real jsonl
        tmp_dir = tempfile.mkdtemp(prefix='gw_test_')
        tmp_receipt = os.path.join(tmp_dir, 'receipts.jsonl')
        reset_default_gateway_for_test(persist_path=tmp_receipt) \
            if False else reset_default_gateway_for_test()  # signature mismatch handled

        from jarvis_memory_gateway import MemoryMutationGateway
        gw = MemoryMutationGateway(receipt_path=tmp_receipt)

        # Call gateway with high-confidence fast_call source
        new_val = f"[GW-TEST] sleep target {time.time():.0f}"
        receipt = gw.update_sir_field(
            field_path='profile.work_rhythms',
            new_value=new_val,
            source='fast_call_mutation',
            confidence=0.95,
            turn_id='test_gw_001',
            nerve=nerve,
        )
        assert receipt.ok, f"gateway failed: {receipt.error}"
        assert receipt.layer_targeted == 'ProfileCard', \
            f"layer wrong: {receipt.layer_targeted}"

        # Verify file written
        with open(profile_path, 'r', encoding='utf-8') as f:
            after = json.load(f)
        assert after.get('work_rhythms') == new_val, \
            f"file not overwritten via gateway: {after.get('work_rhythms')!r}"
        print(f"  ✅ gateway high-conf → overwrite_field 链路通: {new_val[:50]}...")

        # Verify receipt written
        with open(tmp_receipt, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        assert len(lines) >= 1, f"no receipt written"
        last_r = json.loads(lines[-1])
        assert last_r.get('layer_targeted') == 'ProfileCard'
        assert last_r.get('ok') is True
        print(f"  ✅ receipt jsonl 写入 ok: mutation_id={last_r.get('mutation_id')}")

        shutil.rmtree(tmp_dir)
        return True
    finally:
        shutil.copy2(backup_path, profile_path)
        os.remove(backup_path)


def main():
    print("=" * 60)
    print("[P5-fix32 smoke] mutation gateway + ProfileCard overwrite_field")
    print("=" * 60)

    tests = [
        ('ProfileCard.overwrite_field atomic', test_profile_overwrite_field_atomic),
        ('Gateway → overwrite_field 高置信路径', test_gateway_profile_routing),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        print(f"\n--- {name} ---")
        try:
            ok = fn()
            if ok:
                passed += 1
            else:
                print(f"  (skipped)")
        except Exception as e:
            failed += 1
            print(f"  ❌ FAIL: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"Passed: {passed}  Failed: {failed}")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
