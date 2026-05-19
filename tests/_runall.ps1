# [P0+ / 2026-05-15 init] [P0+20-W.3 / 2026-05-16 trace_id 化] 全量回归脚本
# 跑所有 _test_*.py + pytest 套件，聚合统计后写 tests/last_run.json
# 规范：详 docs/JARVIS_WORKFLOW_PROTOCOL.md §2

$ErrorActionPreference = "Continue"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$lastRunJson = Join-Path $repoRoot "tests\last_run.json"

# ============================================================
# [P0+20-W.3] 生成 test_run_id + 抓 git 元信息
# ============================================================
$tsCompact = Get-Date -Format "yyyyMMdd_HHmmss"
$rid = -join ((48..57 + 97..102) | Get-Random -Count 4 | ForEach-Object { [char]$_ })
$testRunId = "test_${tsCompact}_${rid}"
$startedAt = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
$startedTs = [double](Get-Date -UFormat %s)

try {
    $gitHead = (git rev-parse --short HEAD 2>$null).Trim()
    if (-not $gitHead) { $gitHead = "unknown" }
} catch { $gitHead = "unknown" }

try {
    $gitBranch = (git rev-parse --abbrev-ref HEAD 2>$null).Trim()
    if (-not $gitBranch) { $gitBranch = "unknown" }
} catch { $gitBranch = "unknown" }

$markerContext = $env:JARVIS_TEST_MARKER
if (-not $markerContext) { $markerContext = "" }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host "TEST_RUN_ID = $testRunId" -ForegroundColor Yellow
Write-Host "GIT_HEAD    = $gitHead  ($gitBranch)" -ForegroundColor Yellow
Write-Host "STARTED_AT  = $startedAt" -ForegroundColor Yellow
if ($markerContext) {
    Write-Host "MARKER      = $markerContext" -ForegroundColor Yellow
}
Write-Host "============================================================" -ForegroundColor Yellow

$total = 0
$pass = 0
$fail = 0
$results = @()
$failedSuites = @()

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
    "_test_v5_sleep_intent",
    "_test_p0_plus_20_b01_directive_registry",
    "_test_p0_plus_20_b1_firefighting",
    "_test_p0_plus_20_b1_nameerror_guards",
    "_test_p0_plus_20_b1_future_tense_lie",
    "_test_p0_plus_20_beta05_evaluator",
    "_test_p0_plus_20_b115_reminder_read",
    "_test_p0_plus_20_beta2_soul_anchor",
    "_test_p0_plus_20_beta2_soul_relational",
    "_test_p0_plus_20_beta2_soul_attention",
    "_test_p0_plus_20_beta2_migrate",
    "_test_p0_plus_20_beta2_oldpath_decom",
    "_test_p0_plus_20_beta2_worker_jarvis_resolve",
    "_test_p0_plus_20_beta2_5_hotfix",
    "_test_p0_plus_20_beta2_soul_reflector",
    "_test_p0_plus_20_beta2_soul_evaluator",
    "_test_p0_plus_20_beta271_nudge_soul_inject",
    "_test_p0_plus_20_beta273_self_promise",
    "_test_p0_plus_20_beta2710_directness",
    "_test_p0_plus_20_beta28_proactive_care",
    "_test_p0_plus_20_beta284_subtitle_double_write",
    "_test_p0_plus_20_beta285_promise_log",
    "_test_p0_plus_20_beta286_predicate",
    "_test_p0_plus_20_beta287_claim_tracer",
    "_test_p0_plus_20_beta297_inconsistency_subject",
    "_test_p0_plus_20_beta297_timeanchor",
    "_test_p0_plus_20_beta297_care_live",
    "_test_p0_plus_20_beta298_dashboard",
    "_test_p0_plus_20_beta299_commit_confidence",
    "_test_p0_plus_20_beta299_concern_feedback",
    "_test_p0_plus_20_beta299_focus_after_nudge",
    "_test_p0_plus_20_beta2910_fastcall_async",
    "_test_p0_plus_20_beta2911_closure_loop",
    "_test_p0_plus_20_beta2912_vocab_persist",
    "_test_p0_plus_20_beta30_tool_intent_vocab_persist",
    "_test_p0_plus_20_beta33_agent_discipline_red_lines",
    "_test_p0_plus_20_beta34_vocab3_memory_correction_persist",
    "_test_p0_plus_20_beta34_vocab4_inconsistency_persist",
    "_test_p0_plus_20_beta34_vocab5_response_classify_persist",
    "_test_p0_plus_20_beta34_vocab6_feedback_persist",
    "_test_p0_plus_20_beta34_vocab7_concern_keywords_persist",
    "_test_p0_plus_20_beta41_claim_enforce_persist",
    "_test_p0_plus_20_beta36_docs_references_valid",
    "_test_p0_plus_20_beta42_time_claim_audit_skip",
    "_test_p0_plus_20_beta434_claim_classify_evidence_persist",
    "_test_p0_plus_20_beta44_dashboard_integrity_persist",
    "_test_p0_plus_20_beta451_claim_stats_dump_persist",
    "_test_p0_plus_20_beta452_integrity_reflector_persist",
    "_test_p0_plus_20_beta46_directives_vocab_persist",
    "_test_p0_plus_20_beta48_acoustic_wake_persist",
    "_test_p0_plus_20_beta49_emergent_coupling_persist",
    "_test_p0_plus_20_beta410_stm_persist_silent_gate",
    "_test_p0_plus_20_beta411_conditional_vocab_persist",
    "_test_p0_plus_20_beta412_morning_greeting_screen_time"
)

foreach ($t in $tests) {
    $total++
    Write-Host ("`n=== $t ===") -ForegroundColor Cyan
    $output = & python "tests\$t.py" 2>&1
    $tail = $output | Select-Object -Last 4
    $tail | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -eq 0) {
        $pass++
        $results += [PSCustomObject]@{Suite=$t; Result="OK"; Runner="unittest"}
    } else {
        $fail++
        $results += [PSCustomObject]@{Suite=$t; Result="FAIL"; Runner="unittest"}
        $failedSuites += $t
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
    $results += [PSCustomObject]@{Suite="test_three_centers"; Result="OK"; Runner="pytest"}
} else {
    $fail++
    $results += [PSCustomObject]@{Suite="test_three_centers"; Result="FAIL"; Runner="pytest"}
    $failedSuites += "test_three_centers"
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host "REGRESSION SUMMARY: $pass / $total OK,   $fail FAIL" -ForegroundColor Yellow
Write-Host "TEST_RUN_ID = $testRunId" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Yellow
$results | Format-Table -AutoSize

# ============================================================
# [P0+20-W.3] 写 tests/last_run.json
# ============================================================
$endedAt = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
$endedTs = [double](Get-Date -UFormat %s)
$durationS = [math]::Round($endedTs - $startedTs, 2)

$report = [ordered]@{
    test_run_id    = $testRunId
    git_head       = $gitHead
    git_branch     = $gitBranch
    started_at     = $startedAt
    ended_at       = $endedAt
    duration_s     = $durationS
    runner         = "_runall.ps1"
    marker_context = $markerContext
    summary        = [ordered]@{
        total   = $total
        passed  = $pass
        failed  = $fail
        skipped = 0
        errors  = 0
    }
    failed_suites  = $failedSuites
    suites         = $results | ForEach-Object { [ordered]@{
        suite  = $_.Suite
        result = $_.Result
        runner = $_.Runner
    } }
}

try {
    $reportJson = $report | ConvertTo-Json -Depth 6
    Set-Content -Path $lastRunJson -Value $reportJson -Encoding UTF8
    Write-Host "📝 [last_run.json] $lastRunJson  (pass=$pass fail=$fail total=$total dur=${durationS}s)" -ForegroundColor Green
} catch {
    Write-Host "❌ [last_run.json] failed to write: $($_.Exception.Message)" -ForegroundColor Red
}

# 失败时退出码非 0，便于 CI / git hook 集成
if ($fail -gt 0) { exit 1 } else { exit 0 }
