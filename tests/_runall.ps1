# [P0+ / 2026-05-15] 全量回归脚本（不含真 GPU 依赖测试）
# 跑所有 _test_*.py + 三个中心 pytest，输出每个套件的 Ran/Result
$ErrorActionPreference = "Continue"
$total = 0
$pass = 0
$fail = 0
$results = @()

# 全部 unittest 风格的 _test_*.py
$tests = @(
    "_test_axis1_5_visual_pulse",
    "_test_axis1_6_unicode_safe_print",
    "_test_axis2_1_open_threads",
    "_test_axis2_2_project_context",
    "_test_axis2_3_session_digest",
    "_test_axis2_4_local_phrase_pool",
    "_test_echo_guard_and_retry",
    "_test_p0_dawn_commit_chain_fixes",
    "_test_p0_plus_deep_audit_fixes",
    "_test_p0_plus_16_memory_deletion_safety",
    "_test_p0_plus_17_commitment_startup_guard",
    "_test_p0_plus_18_axis3_bugs",
    "_test_p0_plus_18_axis3_a16_capability_honesty",
    "_test_p0_plus_18_b8_b9_fuzzy_and_log_routing",
    "_test_p0_plus_18_c1_promise_leak",
    "_test_p0_plus_18_c2_reminder_firing",
    "_test_p0_plus_18_c3_to_c14_remaining",
    "_test_p0_plus_18_c5_embed_rotation",
    "_test_p0_plus_18_d_brain_db_link",
    "_test_p0_plus_18_e_link_close",
    "_test_p0_plus_18_f_perf_and_honesty",
    "_test_r8_axis3_l0_1_skill_registry",
    "_test_r8_axis3_l0_2_skill_scanner",
    "_test_r8_axis3_l0_3_bootstrap_autosave",
    "_test_r8_axis3_l0_4_kpi_tracking",
    "_test_r8_axis3_l1_offer_guard",
    "_test_r8_axis3_l2_capability_phrasing",
    "_test_r8_axis3_l3_1_promise_parser",
    "_test_p1_fixes",
    "_test_p2_refusal_and_audio",
    "_test_p3_v4_fixes",
    "_test_r6_bus_and_tier",
    "_test_r7_alpha_attention",
    "_test_r7_alpha_bugs",
    "_test_r7_alpha_nudge_channel",
    "_test_r7_alpha_plan_ledger",
    "_test_r7_alpha_state",
    "_test_r7_alpha_working_feed",
    "_test_r7_beta1_factual_recall",
    "_test_r7_beta2_backchannel",
    "_test_r7_beta3_tone_pool",
    "_test_r7_beta4_anti_phrase_verbosity",
    "_test_r7_beta5_soft_subtitle",
    "_test_r7_beta_post_test_fixes",
    "_test_r7_beta_seamless_dialog",
    "_test_r7_oneshot_and_screenshot",
    "_test_v5_sleep_intent"
)

foreach ($t in $tests) {
    $total++
    Write-Host ("`n=== $t ===") -ForegroundColor Cyan
    $output = & python "tests\$t.py" 2>&1
    $tail = $output | Select-Object -Last 4
    $tail | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -eq 0) {
        $pass++
        $results += [PSCustomObject]@{Suite=$t; Result="OK"}
    } else {
        $fail++
        $results += [PSCustomObject]@{Suite=$t; Result="FAIL"}
    }
}

# pytest test_three_centers
Write-Host ("`n=== pytest test_three_centers ===") -ForegroundColor Cyan
$output = & python -m pytest "tests\test_three_centers.py" -q 2>&1
$tail = $output | Select-Object -Last 6
$tail | ForEach-Object { Write-Host $_ }
$total++
if ($LASTEXITCODE -eq 0) {
    $pass++
    $results += [PSCustomObject]@{Suite="test_three_centers"; Result="OK"}
} else {
    $fail++
    $results += [PSCustomObject]@{Suite="test_three_centers"; Result="FAIL"}
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host "REGRESSION SUMMARY: $pass / $total OK,   $fail FAIL" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Yellow
$results | Format-Table -AutoSize
