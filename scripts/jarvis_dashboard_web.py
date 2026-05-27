#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[P0+20-β.5.25 / 2026-05-20] Jarvis Web Dashboard

Sir 02:17 反馈"老 tkinter 不喜欢, 现代审美卡片 + 操作体验 + 窗口缩放".

设计:
- Flask + Tailwind (CDN) + Alpine.js (CDN, 15kb 无构建)
- 单文件 Python (~400 行) + 单 HTML 模板 (~250 行)
- 自动开浏览器到 http://127.0.0.1:8765
- 复用 jarvis_dashboard.py 的 read_*() / action_*() 函数 (不重写业务)
- 现代 dark theme + 响应式 grid + 平滑过渡

启动:
  python scripts/jarvis_dashboard_web.py
  # 或带参数
  python scripts/jarvis_dashboard_web.py --port 8765 --no-browser

老 tkinter 仍可用 (python scripts/jarvis_dashboard.py).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import webbrowser
from typing import Any, Dict

# 加 scripts 到 sys.path 复用 jarvis_dashboard 业务
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

try:
    from flask import Flask, jsonify, render_template_string, request
except ImportError:
    print("❌ Flask 未安装. 跑: pip install flask")
    sys.exit(1)

# 复用业务函数
import jarvis_dashboard as jd

app = Flask(__name__)


# ============================================================
# HTML 模板 (Tailwind + Alpine, 单文件)
# ============================================================

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>贾维斯 Dashboard β.5.25</title>
<script src="https://cdn.tailwindcss.com"></script>
<script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
<style>
  html, body { background: #0f172a; color: #e2e8f0; font-family: 'Microsoft YaHei UI', sans-serif; }
  .glass { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(8px); }
  .scrollbar-thin::-webkit-scrollbar { width: 6px; }
  .scrollbar-thin::-webkit-scrollbar-track { background: #1e293b; }
  .scrollbar-thin::-webkit-scrollbar-thumb { background: #475569; border-radius: 3px; }
  .scrollbar-thin::-webkit-scrollbar-thumb:hover { background: #64748b; }
  /* fade-in 动画 */
  @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
  .fade-in { animation: fadeIn 0.25s ease-out; }
  /* badge */
  .badge { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 9999px; font-size: 0.75rem; }
</style>
</head>
<body class="min-h-screen" x-data="dashboard()" x-init="init()">

<!-- Header -->
<header class="glass border-b border-slate-700/50 sticky top-0 z-50">
  <div class="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
    <div class="flex items-center gap-3">
      <div class="text-2xl">🤖</div>
      <div>
        <h1 class="text-xl font-bold tracking-tight">J.A.R.V.I.S. Dashboard</h1>
        <p class="text-xs text-slate-400">β.5.43 · build {{ build_ts }} · <span x-text="lastUpdate"></span></p>
      </div>
      <!-- 🩹 [β.5.43-A / 2026-05-20] Jarvis HUD 状态条 -->
      <div class="ml-4 px-3 py-1 rounded-lg bg-slate-800 border border-slate-700 text-xs flex items-center gap-1"
           :title="'reason: ' + (jarvisState.reason||'') + ' / age: ' + Math.round(jarvisState.age_seconds||0) + 's'"
           x-show="jarvisState && jarvisState.state">
        <span x-text="jarvisState.display && jarvisState.display.emoji" class="text-base"></span>
        <span x-text="jarvisState.display && jarvisState.display.label_zh"
              :class="{
                'text-green-400': jarvisState.state === 'ready',
                'text-blue-400': jarvisState.state === 'thinking',
                'text-yellow-300': jarvisState.state === 'speaking',
                'text-orange-300': jarvisState.state === 'listening',
                'text-purple-300': jarvisState.state === 'focused',
                'text-red-400': jarvisState.state === 'error',
              }"></span>
      </div>
    </div>
    <div class="flex items-center gap-2">
      <!-- 🩹 [β.5.41-C / 2026-05-20] Sir 拍板事项新面板入口 -->
      <a href="/items"
         class="px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 transition text-sm font-medium"
         title="所有 Sir 拍板事项 + 修正/删除 (β.5.41)">
        💡 我们的事
      </a>
      <!-- 🆕 [P5-Layer1-fix19-dashboard / 2026-05-22] 主脑 thinking pass 入口 -->
      <a href="/main_brain_meta"
         class="px-3 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 transition text-sm font-medium"
         title="主脑每轮 thinking pass META 自检 (evidence/reaction/skip_alert) - 看贾维斯为什么这样说">
        🧠 思考链
      </a>
      <!-- 🆕 [P1 / Sir 2026-05-25 22:10 数字生命基础] Inner Thought 入口 -->
      <a href="/inner_thoughts"
         class="px-3 py-1.5 rounded-lg bg-pink-600 hover:bg-pink-500 transition text-sm font-medium"
         title="贾维斯持续后台思考 (adaptive 60s-30min tick, 5 类思考池) - 看他独自一人时想什么">
        💭 思考层
      </a>
      <!-- 🆕 [Sir 2026-05-27 18:44 真愿景] InnerVoiceTrack 心声轨道入口 -->
      <a href="/inner_voice"
         class="px-3 py-1.5 rounded-lg bg-fuchsia-700 hover:bg-fuchsia-600 transition text-sm font-medium"
         title="贾维斯 24/7 心声轨道 (意识流) - 所有思考脑/sensor/care_trigger 统一时序流, 主脑被召唤时看的就是这个">
        🌊 心声
      </a>
      <!-- 🆕 [AA / Sir 2026-05-25 22:58 自决] AutoArbiter 入口 -->
      <a href="/auto_arbiter"
         class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 transition text-sm font-medium"
         title="贾维斯自己拍板 review queue (低风险真自决, 中风险给建议) - Sir 一键撤销 + 每日反思迭代准确性">
        🤖 自决
      </a>
      <!-- 🆕 [WRC / Sir 2026-05-25 23:52 真问 "3 也做"] WeeklyReflectionConsolidator 入口 -->
      <a href="/weekly_insights"
         class="px-3 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-500 transition text-sm font-medium"
         title="贾维斯每周日 03:xx 自合并 7d self_reflection 提 long-term insight - Sir 一键 accept/reject (不直接 mutate sir_profile)">
        🪞 周反思
      </a>
      <!-- 🆕 [P5-Layer1-fix19-dashboard / 2026-05-22] intent log 入口 (老的没显示) -->
      <a href="/intent_resolved"
         class="px-3 py-1.5 rounded-lg bg-sky-700 hover:bg-sky-600 transition text-sm font-medium"
         title="每轮 IntentResolver mutation log - 看贾维斯真做了什么 tool 调用 (β.5.44)">
        🧭 Intent
      </a>
      <!-- 🆕 [Translator Phase 4.C / 2026-05-24 23:00] Translator vocab 入口 -->
      <a href="/translator"
         class="px-3 py-1.5 rounded-lg bg-amber-700 hover:bg-amber-600 transition text-sm font-medium"
         title="L4.6 翻译层 alias vocab + reflector propose - Sir 一键 activate/reject (Translator Phase 4)">
        📚 Translator
      </a>
      <button @click="refresh()" :disabled="loading"
              class="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-50 transition text-sm font-medium">
        <span x-show="!loading">🔄 刷新</span>
        <span x-show="loading">⏳ 加载...</span>
      </button>
      <button @click="autoRefresh = !autoRefresh"
              :class="autoRefresh ? 'bg-emerald-600 hover:bg-emerald-500' : 'bg-slate-700 hover:bg-slate-600'"
              class="px-3 py-1.5 rounded-lg transition text-sm font-medium">
        <span x-show="autoRefresh">⏸ 暂停自动</span>
        <span x-show="!autoRefresh">▶ 自动 10s</span>
      </button>
      <!-- 🩹 [β.5.28-fix6] Sir 想立即跑 SoulArchivist 反思 (propose 新 joke/thread) -->
      <button onclick="window.dashboardReflectNow(this)"
              title="立刻让 Reflector 跑一次反思 (proposal 新 joke/thread/concern)"
              class="px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 transition text-sm font-medium">
        💭 立刻反思
      </button>
    </div>
  </div>
</header>

<!-- 🆕 [P5-fix20-A1 / 2026-05-22] Sir 14:32 真测痛点 — Key 池雪崩 header banner -->
<!-- 当 keyHealth.overall === 'crit' (有池全挂), 顶部红条提醒 + 一键跳卡片. -->
<div x-show="keyHealth && keyHealth.overall === 'crit'"
     x-transition
     class="bg-rose-900/80 border-b-2 border-rose-500 text-rose-100 px-6 py-2.5 sticky top-[var(--header-h,3.5rem)] z-40 backdrop-blur">
  <div class="max-w-7xl mx-auto flex items-center justify-between gap-3 text-sm">
    <div class="flex items-center gap-2 flex-1 min-w-0">
      <span class="text-lg">🚨</span>
      <span class="font-semibold">API Key 池雪崩</span>
      <span class="text-rose-200 truncate" x-text="keyHealth.health_msg || '某个 key 池已无可用 key, 主脑/IntentResolver/Vision 会降级'"></span>
    </div>
    <div class="flex items-center gap-2 shrink-0">
      <button @click="document.querySelector('[data-key-card]')?.scrollIntoView({behavior:'smooth'}); showKeyDetail = true;"
              class="px-3 py-1 rounded bg-rose-700 hover:bg-rose-600 text-xs font-medium">
        ↓ 看详情
      </button>
      <button @click="resetAllKeys()"
              :disabled="keyResetPending"
              class="px-3 py-1 rounded bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-xs font-medium">
        ⚡ 一键复活
      </button>
    </div>
  </div>
</div>

<!-- 整体状态条 -->
<section class="max-w-7xl mx-auto px-6 pt-6">
  <div class="glass rounded-2xl p-5 shadow-xl border border-slate-700/30">
    <div class="flex items-baseline gap-3 justify-between">
      <div class="flex items-baseline gap-3">
        <span class="text-3xl"
              :class="{
                'text-emerald-400': summary.level === 'ok',
                'text-amber-400': summary.level === 'warn',
                'text-rose-400': summary.level === 'crit'
              }" x-text="summary.emoji"></span>
        <h2 class="text-2xl font-bold" x-text="summary.headline"></h2>
      </div>
      <!-- 🆕 [P5-fix25-stand-down] Stand Down mini badge + toggle -->
      <div class="flex items-center gap-2 flex-shrink-0">
        <button @click="standDownToggle()"
                :disabled="standDownActionPending"
                :class="(standDown.state && standDown.state.active)
                          ? 'bg-indigo-600/30 hover:bg-indigo-600/50 border-indigo-400/50 text-indigo-200'
                          : 'bg-slate-700/40 hover:bg-slate-600/60 border-slate-600/40 text-slate-300'"
                class="text-xs px-3 py-1.5 rounded-lg border flex items-center gap-1.5 transition disabled:opacity-50"
                :title="(standDown.state && standDown.state.active)
                          ? ('Stand Down active · ' + (standDown.state.reason || '') + ' · ' + fmtRemaining(standDown.state.remaining_s) + ' remain · 点击 wake')
                          : '点击进入 Stand Down (30min, voice+nudge OFF, 字幕 ON)'">
          <span x-text="(standDown.state && standDown.state.active) ? '🌙' : '☀️'"></span>
          <span class="font-medium"
                x-text="(standDown.state && standDown.state.active)
                          ? ('Stand Down · ' + (standDown.state.reason || '') + ' · ' + fmtRemaining(standDown.state.remaining_s))
                          : 'Stand Down: OFF'"></span>
          <span x-show="standDown.state && standDown.state.active && standDown.state.in_grace"
                class="text-amber-300 text-[0.7rem] ml-1">grace</span>
        </button>
      </div>
    </div>
    <template x-if="summary.actions && summary.actions.length">
      <ol class="mt-3 space-y-1.5 pl-1">
        <template x-for="(act, i) in summary.actions" :key="i">
          <li class="flex items-start gap-2 text-sm">
            <span class="font-mono text-slate-500" x-text="(i+1) + '.'"></span>
            <span :class="{
              'text-rose-300': act.level === 'crit',
              'text-amber-300': act.level === 'warn',
              'text-slate-300': act.level === 'info'
            }">
              <span x-text="act.what"></span>
              <span class="text-slate-500 ml-2" x-text="'→ ' + act.how"></span>
            </span>
          </li>
        </template>
      </ol>
    </template>
  </div>
</section>

<!-- 主区: 待拍板 (放大显眼) -->
<section class="max-w-7xl mx-auto px-6 pt-6">
  <div class="flex items-center justify-between mb-3">
    <h2 class="text-xl font-bold flex items-center gap-2">
      <span>⚠️</span>
      <span>等你拍板的提案</span>
      <span class="badge bg-amber-500/20 text-amber-300" x-text="reviewItems.length + ' 条'"></span>
    </h2>
    <div class="flex gap-2 text-xs">
      <template x-for="(c, k) in reviewKindCounts" :key="k">
        <span class="badge bg-slate-700/50" x-text="kindEmoji(k) + ' ' + c"></span>
      </template>
    </div>
  </div>

  <!-- 空状态 -->
  <template x-if="!reviewItems.length">
    <div class="glass rounded-2xl p-12 text-center border-2 border-dashed border-slate-700">
      <div class="text-5xl mb-3">✅</div>
      <p class="text-slate-400">没有待审 — 贾维斯没主动提新建议</p>
    </div>
  </template>

  <!-- 卡片网格 (响应式 1/2 列) -->
  <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
    <template x-for="(it, idx) in reviewItems" :key="it.kind + '/' + it.id">
      <div class="glass rounded-2xl p-5 border border-slate-700/30 shadow-lg hover:shadow-xl hover:border-slate-600 transition fade-in flex flex-col">
        <!-- meta 行 -->
        <div class="flex items-center gap-2 mb-3 text-xs">
          <span class="badge"
                :class="kindColorClass(it.kind)"
                x-text="it.kind_zh"></span>
          <span class="text-slate-500" x-text="it.source ? '来源: ' + it.source : ''"></span>
          <span class="text-slate-500" x-text="it.created_iso ? '⏱ ' + it.created_iso : ''"></span>
          <template x-if="it.severity !== undefined">
            <span class="text-amber-400 font-mono text-xs"
                  x-text="'紧迫 ' + (it.severity * 100).toFixed(0) + '%'"></span>
          </template>
        </div>
        <!-- preview (英文原文) -->
        <p class="text-base font-medium mb-1 leading-snug" x-text="it.preview"></p>
        <!-- preview_zh (翻译, 仅当有) -->
        <p x-show="it.preview_zh" class="text-sm text-cyan-300 mb-2 leading-snug" x-text="'🇨🇳 ' + it.preview_zh"></p>
        <!-- rationale (英文) -->
        <p x-show="it.rationale" class="text-sm text-slate-400 leading-relaxed mb-1" x-text="it.rationale"></p>
        <!-- rationale_zh (翻译) -->
        <p x-show="it.rationale_zh" class="text-xs text-cyan-400/70 leading-relaxed mb-4 flex-1" x-text="'  └ ' + it.rationale_zh"></p>
        <!-- action 按钮 -->
        <!-- 🩹 [β.5.28-fix4 / 2026-05-20] Sir 03:03 反馈"按钮还是点不了". -->
        <!-- 改用纯 inline onclick + fetch (不依赖 Alpine reactive), 100% 能点. -->
        <div class="flex gap-2 mt-auto">
          <button
                  :data-kind="it.kind"
                  :data-id="it.id"
                  :data-pv="it.proposed_value"
                  onclick="window.dashboardFallbackAct(this, 'activate')"
                  class="flex-1 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 transition text-sm font-medium cursor-pointer">
            ✅ 通过
          </button>
          <button
                  :data-kind="it.kind"
                  :data-id="it.id"
                  :data-pv="it.proposed_value"
                  onclick="window.dashboardFallbackAct(this, 'reject')"
                  class="flex-1 px-4 py-2 rounded-lg bg-rose-600/80 hover:bg-rose-500 transition text-sm font-medium cursor-pointer">
            ❌ 拒绝
          </button>
        </div>
      </div>
    </template>
  </div>
</section>

<!-- 🩹 [β.5.28-fix9/β.5.30 / 2026-05-20] 言行一致审计双账本 (Jarvis + Sir) -->
<section class="max-w-7xl mx-auto px-6 pt-8"
         x-show="(promise.jarvis_total || 0) > 0 || (promise.sir_total || 0) > 0">
  <div class="flex items-center justify-between mb-3">
    <h2 class="text-xl font-bold flex items-center gap-2">
      <span>⚖️</span>
      <span>言行一致审计</span>
    </h2>
    <button onclick="window.dashboardResetPromise(this)"
            title="清空所有 pending/untracked 承诺 (保留已兑现)"
            class="px-3 py-1.5 rounded-lg bg-rose-700 hover:bg-rose-600 transition text-xs font-medium">
      🧹 清残留 (留 ✓)
    </button>
  </div>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-4">

    <!-- Jarvis 承诺 (机器人答应却没做) -->
    <div class="glass rounded-2xl p-5 border border-rose-500/20 shadow-lg"
         x-show="(promise.jarvis_total || 0) > 0">
      <h3 class="font-semibold flex items-center gap-2 mb-3">
        <span>🤖</span>
        <span>Jarvis 答应过</span>
        <span class="badge"
              :class="(promise.jarvis_untracked_n || 0) > 3 ? 'bg-rose-500/20 text-rose-300' : 'bg-amber-500/20 text-amber-300'"
              x-text="'untracked ' + (promise.jarvis_untracked_n || 0) + ' · pending ' + (promise.jarvis_pending_n || 0) + ' · ✓' + (promise.jarvis_fulfilled_n || 0)"></span>
      </h3>
      <p class="text-xs text-slate-400 mb-2">机器人嘴说要做的事 (没做到 = 言行不一)</p>
      <div class="space-y-1 text-xs max-h-72 overflow-y-auto scrollbar-thin">
        <template x-for="p in (promise.jarvis_rows || [])" :key="p.id">
          <div class="flex items-start gap-2 p-2 rounded hover:bg-slate-800/50">
            <span :class="p.state === 'fulfilled' ? 'text-emerald-400' : (p.state === 'untracked' ? 'text-rose-400' : 'text-amber-400')"
                  x-text="p.state_zh"></span>
            <div class="flex-1 min-w-0">
              <p class="text-slate-200 truncate" x-text="p.desc"></p>
              <p class="text-slate-500 text-[10px]" x-text="p.age + ' · ' + p.when"></p>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- Sir 承诺 (Sir 自己说过要做的事) -->
    <div class="glass rounded-2xl p-5 border border-blue-500/20 shadow-lg"
         x-show="(promise.sir_total || 0) > 0">
      <h3 class="font-semibold flex items-center gap-2 mb-3">
        <span>👤</span>
        <span>你自己说过</span>
        <span class="badge bg-blue-500/20 text-blue-300"
              x-text="'pending ' + (promise.sir_pending_n || 0) + ' · ✓' + (promise.sir_fulfilled_n || 0) + (promise.sir_untracked_n > 0 ? ' · 漏 ' + promise.sir_untracked_n : '')"></span>
      </h3>
      <p class="text-xs text-slate-400 mb-2">你自己 cmd 表过态的 (Jarvis 看见, 但不主动催)</p>
      <div class="space-y-1 text-xs max-h-72 overflow-y-auto scrollbar-thin">
        <template x-for="p in (promise.sir_rows || [])" :key="p.id">
          <div class="flex items-start gap-2 p-2 rounded hover:bg-slate-800/50">
            <span :class="p.state === 'fulfilled' ? 'text-emerald-400' : (p.state === 'untracked' ? 'text-slate-500' : 'text-blue-400')"
                  x-text="p.state_zh"></span>
            <div class="flex-1 min-w-0">
              <p class="text-slate-200 truncate" x-text="p.desc"></p>
              <p class="text-slate-500 text-[10px]" x-text="p.age + ' · ' + p.when"></p>
            </div>
          </div>
        </template>
      </div>
    </div>

  </div>
</section>

<!-- 待办区: 你要他盯的事 (Commitments) -->
<section class="max-w-7xl mx-auto px-6 pt-8" x-show="(todo.rows && todo.rows.length) > 0">
  <h2 class="text-xl font-bold mb-3 flex items-center gap-2">
    <span>📋</span>
    <span>你要他盯的事 (Commitments)</span>
    <span class="badge bg-amber-500/20 text-amber-300"
          x-text="'⏳' + (todo.count_pending || 0) + ' ✓' + (todo.count_done || 0)"></span>
  </h2>
  <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
    <template x-for="r in (todo.rows || [])" :key="r.id">
      <div class="glass rounded-xl p-4 border border-slate-700/30 hover:border-slate-600 transition flex items-center justify-between gap-3">
        <div class="flex-1 min-w-0">
          <p class="text-xs"
             :class="r.state === 'done' ? 'text-emerald-400' : (r.state === 'overdue' ? 'text-rose-400' : 'text-amber-400')"
             x-text="'[' + r.state_zh + '] ' + r.when"></p>
          <p class="text-sm text-slate-300 mt-1 truncate" x-text="r.desc"></p>
        </div>
        <template x-if="r.state === 'pending' || r.state === 'overdue'">
          <button @click="cancelCommitment(r)"
                  :disabled="actionPending['todo/'+r.id]"
                  class="px-3 py-1.5 rounded-lg bg-rose-600/70 hover:bg-rose-500 disabled:opacity-50 transition text-xs font-medium">
            🚫 取消
          </button>
        </template>
      </div>
    </template>
  </div>
</section>

<!-- 🩹 [β.5.32 / 2026-05-20] Sir 03:54 反馈"删 Jarvis 承诺卡 + 长期惦记/你们之间均分 + 系统健康放下面" -->
<!-- 信息区: 长期惦记 + 你们之间 (50/50 一行) -->
<section class="max-w-7xl mx-auto px-6 pt-8">
  <h2 class="text-xl font-bold mb-3 flex items-center gap-2"><span>📋</span><span>信息 - 你想了解的</span></h2>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-4">

    <!-- 长期惦记 -->
    <div class="glass rounded-2xl p-5 border border-slate-700/30 shadow-lg">
      <div class="flex items-center justify-between mb-3">
        <h3 class="font-semibold flex items-center gap-2"><span>🎯</span>长期惦记</h3>
        <span class="badge bg-slate-700/50" x-text="(concerns.rows ? concerns.rows.length : 0) + ' 件'"></span>
      </div>
      <div class="space-y-2 max-h-96 overflow-y-auto scrollbar-thin">
        <template x-for="r in (concerns.rows || []).slice(0, 12)" :key="r.zh_name">
          <div class="text-xs">
            <div class="flex items-center gap-2">
              <span x-text="r.warn"></span>
              <span class="font-medium text-slate-200" x-text="r.zh_name"></span>
              <span class="font-mono text-amber-400" x-text="r.severity_pct + '%'"></span>
            </div>
            <p class="text-slate-500 ml-5 mt-0.5" x-text="r.what"></p>
          </div>
        </template>
      </div>
    </div>

    <!-- 默契 + 共同经历 (Sir 通过的 thread 落地处) -->
    <div class="glass rounded-2xl p-5 border border-slate-700/30 shadow-lg">
      <div class="flex items-center justify-between mb-3">
        <h3 class="font-semibold flex items-center gap-2"><span>💞</span>你们之间</h3>
        <span class="badge bg-slate-700/50"
              x-text="((relation.jokes||[]).length) + '梗·' + ((relation.protocols||[]).length) + '默·' + ((relation.threads||[]).length) + '经历'"></span>
      </div>
      <div class="space-y-2 text-xs max-h-96 overflow-y-auto scrollbar-thin">
        <template x-for="j in (relation.jokes || []).slice(0, 5)" :key="j.phrase">
          <div>
            <p class="text-emerald-300">😂 "<span x-text="j.phrase"></span>"</p>
            <p class="text-slate-500 ml-5" x-text="j.birth"></p>
          </div>
        </template>
        <!-- 🩹 [β.5.28-fix5] 共同经历 - Sir 通过的 thread 显示位 -->
        <template x-for="t in (relation.threads || []).slice(0, 10)" :key="t.id">
          <div>
            <p class="text-pink-300">📖 <span x-text="t.title"></span></p>
            <p x-show="t.what" class="text-slate-500 ml-5 text-xs" x-text="t.what"></p>
            <p class="text-slate-600 ml-5 text-[10px]" x-text="(t.last_milestone || t.started) + ' · ' + t.n_highlights + ' 高光'"></p>
          </div>
        </template>
        <template x-for="u in (relation.unfinished || []).slice(0, 5)" :key="u.topic">
          <div class="text-amber-300">📌 <span x-text="u.topic"></span></div>
        </template>
      </div>
    </div>

  </div>

  <!-- 系统健康单独一行 (Sir 03:54 改 layout) -->
  <div class="glass rounded-2xl p-5 border border-slate-700/30 shadow-lg mt-4">
    <h3 class="font-semibold flex items-center gap-2 mb-3"><span>📊</span>系统健康</h3>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
      <div>
        <p class="text-slate-400">内存</p>
        <p class="text-slate-200 text-base font-mono" x-text="(health.health_last && health.health_last.ws_mb ? health.health_last.ws_mb.toFixed(0) : '?') + ' MB'"></p>
      </div>
      <div>
        <p class="text-slate-400">日志数</p>
        <p class="text-slate-200 text-base font-mono" x-text="health.log_count || 0"></p>
      </div>
      <div class="col-span-2">
        <p class="text-slate-400">诊断</p>
        <p class="text-slate-300" x-text="health.diagnosis || '-'"></p>
      </div>
    </div>
  </div>
</section>

<!-- 观测区: directive / daemon / events / mutations -->
<section class="max-w-7xl mx-auto px-6 pt-8 pb-12">
  <h2 class="text-xl font-bold mb-3 flex items-center gap-2"><span>🔍</span><span>观测 - 后台状态</span></h2>
  <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">

    <!-- Directive -->
    <div class="glass rounded-2xl p-5 border border-slate-700/30">
      <h3 class="font-semibold flex items-center gap-2 mb-3"><span>📜</span>临时规则</h3>
      <p class="text-xs text-slate-400">共 <span x-text="directive.total || 0"></span> 条</p>
      <p class="text-xs text-amber-300 mt-1" x-show="directive.health">
        ⚠️ 偏移 <span x-text="((directive.health||{}).low_help || 0) + ((directive.health||{}).untriggered || 0)"></span>
      </p>
    </div>

    <!-- Daemon -->
    <div class="glass rounded-2xl p-5 border border-slate-700/30">
      <h3 class="font-semibold flex items-center gap-2 mb-3"><span>💡</span>后台管家</h3>
      <p class="text-xs text-slate-400">
        在跑 <span class="text-emerald-400 font-mono" x-text="daemonLiveCount"></span> /
        共 <span class="font-mono" x-text="(daemon.daemons||[]).length"></span>
      </p>
      <div class="mt-2 space-y-0.5 text-xs max-h-32 overflow-y-auto scrollbar-thin">
        <template x-for="d in (daemon.daemons || [])" :key="d.zh">
          <div class="flex items-center gap-1">
            <span x-text="d.live ? '✅' : '⚫'"></span>
            <span :class="d.live ? 'text-slate-300' : 'text-slate-500'" x-text="d.zh"></span>
          </div>
        </template>
      </div>
    </div>

    <!-- Events -->
    <div class="glass rounded-2xl p-5 border border-slate-700/30">
      <h3 class="font-semibold flex items-center gap-2 mb-3"><span>🔔</span>最近事件</h3>
      <div class="space-y-1 text-xs max-h-40 overflow-y-auto scrollbar-thin">
        <template x-for="e in (events.events || []).slice(0, 8)" :key="e.ts + e.body">
          <div>
            <span class="text-slate-500 font-mono" x-text="e.ts"></span>
            <span class="text-slate-300 ml-1" x-text="e.tag"></span>
            <p class="text-slate-400 ml-1" x-text="(e.body || '').slice(0, 60)"></p>
          </div>
        </template>
      </div>
    </div>

    <!-- Mutations -->
    <div class="glass rounded-2xl p-5 border border-slate-700/30">
      <h3 class="font-semibold flex items-center gap-2 mb-3"><span>🔬</span>信任审计</h3>
      <p class="text-xs text-slate-400">今天 <span x-text="mutations.today_n || 0"></span> / 总 <span x-text="mutations.total_n || 0"></span></p>
    </div>

  </div>

  <!-- 言出必行健康度 (跨整行宽卡) -->
  <div class="glass rounded-2xl p-5 border border-slate-700/30 mt-4">
    <div class="flex items-center justify-between mb-3">
      <h3 class="font-semibold flex items-center gap-2">
        <span>💯</span>言出必行健康度
        <span class="badge"
              :class="(integrity.unverified_today || 0) === 0 ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'"
              x-text="'今 ' + (integrity.unverified_today || 0) + ' · 7d ' + (integrity.unverified_7d || 0)"></span>
        <template x-if="integrity.verify_rate !== null && integrity.verify_rate !== undefined">
          <span class="badge bg-blue-500/20 text-blue-300"
                x-text="'兑现 ' + (integrity.verify_rate * 100).toFixed(0) + '%'"></span>
        </template>
      </h3>
    </div>
    <template x-if="(integrity.unverified_today || 0) === 0 && (integrity.unverified_7d || 0) === 0">
      <p class="text-sm text-emerald-400">✓ 干净 — 没有 unverified claim</p>
    </template>
    <template x-if="(integrity.top_unverified || []).length > 0">
      <div class="space-y-1 text-xs">
        <p class="text-slate-400 mb-1">🔁 7 天最常空头话:</p>
        <template x-for="r in (integrity.top_unverified || []).slice(0, 5)" :key="r.text">
          <div class="flex items-center gap-2">
            <span class="badge bg-rose-500/20 text-rose-300" x-text="r.kind"></span>
            <span class="text-slate-500" x-text="'×' + r.count"></span>
            <span class="text-slate-300 truncate" x-text="r.text"></span>
          </div>
        </template>
      </div>
    </template>
  </div>

  <!-- 🆕 [P5-Layer1-fix19-dashboard / 2026-05-22] 主脑 Thinking Pass mini card -->
  <!-- Sir 13:13 立 Layer 1: 主脑 reply 末尾 emit [META] 一行自检. 这卡片让 Sir -->
  <!-- 不点 /main_brain_meta page 也能一眼看主脑是否在认真 self-check. -->
  <div class="glass rounded-2xl p-5 border border-slate-700/30 mt-4">
    <div class="flex items-center justify-between mb-3">
      <h3 class="font-semibold flex items-center gap-2">
        <span>🧠</span>主脑思考链 (Layer 1 META)
        <span class="badge"
              :class="{
                'bg-emerald-500/20 text-emerald-300': (brainMeta.health || 'empty') === 'ok',
                'bg-amber-500/20 text-amber-300': brainMeta.health === 'warn',
                'bg-slate-700/50 text-slate-400': (brainMeta.health || 'empty') === 'empty'
              }"
              x-text="(brainMeta.total || 0) + ' 轮'"></span>
        <span class="badge bg-violet-500/20 text-violet-300" x-show="(brainMeta.skip_alert_count || 0) > 0"
              x-text="'拒道歉 ' + (brainMeta.skip_alert_count || 0)"></span>
      </h3>
      <a href="/main_brain_meta"
         class="text-xs text-violet-400 hover:text-violet-300">详情 →</a>
    </div>

    <!-- 健康度 banner -->
    <p class="text-sm mb-3"
       :class="{
         'text-emerald-300': (brainMeta.health || 'empty') === 'ok',
         'text-amber-300': brainMeta.health === 'warn',
         'text-slate-400': (brainMeta.health || 'empty') === 'empty'
       }"
       x-text="(brainMeta.health === 'ok' ? '✅ ' : (brainMeta.health === 'warn' ? '⚠️ ' : 'ℹ️ ')) + (brainMeta.health_msg || '')"></p>

    <!-- 4 mini stat -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
      <div class="bg-slate-800/50 rounded-lg p-2.5">
        <p class="text-slate-400">📚 evidence 非空</p>
        <p class="text-emerald-300 text-base font-mono mt-0.5"
           x-text="(brainMeta.evidence_pct || 0) + '%'"></p>
        <p class="text-slate-500 text-[0.7rem]"
           x-text="(brainMeta.evidence_count || 0) + ' / ' + (brainMeta.total || 0) + ' 轮'"></p>
      </div>
      <div class="bg-slate-800/50 rounded-lg p-2.5">
        <p class="text-slate-400">🚫 skip_alert</p>
        <p class="text-amber-300 text-base font-mono mt-0.5"
           x-text="(brainMeta.skip_alert_pct || 0) + '%'"></p>
        <p class="text-slate-500 text-[0.7rem]"
           x-text="(brainMeta.skip_alert_count || 0) + ' / ' + (brainMeta.total || 0) + ' 轮拒道歉'"></p>
      </div>
      <div class="bg-slate-800/50 rounded-lg p-2.5">
        <p class="text-slate-400">📊 平均 evidence</p>
        <p class="text-blue-300 text-base font-mono mt-0.5"
           x-text="(brainMeta.avg_evidence_per_turn || 0).toFixed(2)"></p>
        <p class="text-slate-500 text-[0.7rem]">每轮主脑用证据数</p>
      </div>
      <div class="bg-slate-800/50 rounded-lg p-2.5">
        <p class="text-slate-400">💭 最近 1 轮 note</p>
        <p class="text-slate-200 text-xs mt-0.5 truncate"
           x-text="brainMeta.latest_turn_note || '(空)'"
           :title="brainMeta.latest_turn_note"></p>
        <p class="text-slate-500 text-[0.7rem]"
           x-show="brainMeta.latest_turn_id"
           x-text="(brainMeta.latest_turn_skip_alert ? '🚫 拒道歉' : '✓') + ' · ' + (brainMeta.latest_turn_reaction || '?')"></p>
      </div>
    </div>
  </div>

  <!-- 🆕 [P5-fix20-A1 / 2026-05-22] Sir 14:32 真测痛点 — key 池雪崩可视化 -->
  <!-- Sir 真测发现 OpenRouter 全挂 + Google 429 → 主脑能开口但 IntentResolver/ -->
  <!-- Vision/Hippocampus 全降级 → "嘴上说没真做". 这卡片让 Sir 一眼看哪个池挂了. -->
  <div data-key-card
       class="glass rounded-2xl p-5 border border-slate-700/30 mt-4"
       :class="{
         'border-rose-500/50': (keyHealth.overall || 'ok') === 'crit',
         'border-amber-500/50': keyHealth.overall === 'warn'
       }">
    <div class="flex items-center justify-between mb-3">
      <h3 class="font-semibold flex items-center gap-2">
        <span>🔑</span>API Key 池健康
        <span class="badge"
              :class="{
                'bg-emerald-500/20 text-emerald-300': (keyHealth.overall || 'ok') === 'ok',
                'bg-amber-500/20 text-amber-300': keyHealth.overall === 'warn',
                'bg-rose-500/20 text-rose-300': keyHealth.overall === 'crit',
                'bg-slate-700/50 text-slate-400': !keyHealth.available
              }"
              x-text="(keyHealth.overall || 'unknown').toUpperCase()"></span>
        <span class="text-xs text-slate-500"
              x-show="keyHealth.snapshot_age_s !== null && keyHealth.snapshot_age_s !== undefined"
              x-text="'· ' + keyHealth.snapshot_age_s + 's 前'"></span>
      </h3>
      <button @click="resetAllKeys()"
              x-show="keyHealth.available && keyHealth.overall !== 'ok'"
              :disabled="keyResetPending"
              class="px-3 py-1 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-50 transition text-xs font-medium">
        <span x-show="!keyResetPending">⚡ 一键复活全部</span>
        <span x-show="keyResetPending">⏳ 处理中...</span>
      </button>
    </div>

    <!-- 健康度 banner -->
    <p class="text-sm mb-3"
       :class="{
         'text-emerald-300': (keyHealth.overall || 'ok') === 'ok',
         'text-amber-300': keyHealth.overall === 'warn',
         'text-rose-300': keyHealth.overall === 'crit',
         'text-slate-400': !keyHealth.available
       }"
       x-text="keyHealth.health_msg || '加载中...'"></p>

    <!-- 3 池 grid -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs"
         x-show="keyHealth.available">
      <template x-for="(p, name) in (keyHealth.pools || {})" :key="name">
        <div class="bg-slate-800/50 rounded-lg p-2.5"
             :class="{
               'border border-rose-500/40': p.healthy === 0 && p.total > 0,
               'border border-amber-500/40': p.healthy > 0 && p.healthy < p.total,
             }">
          <div class="flex items-center justify-between">
            <p class="text-slate-300 font-mono uppercase" x-text="name"></p>
            <p :class="{
                 'text-emerald-300': p.healthy === p.total,
                 'text-amber-300': p.healthy > 0 && p.healthy < p.total,
                 'text-rose-300': p.healthy === 0
               }"
               class="text-base font-mono"
               x-text="p.healthy + '/' + p.total"></p>
          </div>
          <p class="text-slate-500 text-[0.7rem] mt-1">
            <span x-show="p.permanent_dead > 0" class="text-rose-400" x-text="'⛔ 永久死 ' + p.permanent_dead + ' '"></span>
            <span x-show="p.in_cooldown > 0" class="text-amber-400" x-text="'❄️ 冷却 ' + p.in_cooldown + ' '"></span>
            <span x-show="p.healthy === p.total" class="text-emerald-400">✓ 全部健康</span>
          </p>
        </div>
      </template>
    </div>

    <!-- 详细 key 列表 (展开时显示) -->
    <div x-show="keyHealth.available && Object.keys(keyHealth.key_status || {}).length > 0 && showKeyDetail"
         class="mt-3 space-y-1 text-xs max-h-48 overflow-y-auto scrollbar-thin border-t border-slate-700 pt-3">
      <template x-for="(st, label) in (keyHealth.key_status || {})" :key="label">
        <div class="flex items-center gap-2 p-1.5 rounded hover:bg-slate-800/50">
          <span x-text="st.healthy ? '🟢' : (st.permanently_dead ? '⛔' : '❄️')"></span>
          <span class="font-mono text-slate-300 min-w-[6rem]" x-text="label"></span>
          <span class="text-slate-500 text-[0.7rem]" x-show="st.in_cooldown" x-text="'冷却剩 ' + st.cooldown_remaining_s + 's'"></span>
          <span class="text-slate-500 text-[0.7rem] truncate flex-1" x-show="st.last_error" :title="st.last_error" x-text="st.last_error.slice(0, 60)"></span>
          <button @click="resetKey(label, st.permanently_dead ? 'permanent' : 'cooldown')"
                  x-show="!st.healthy"
                  :disabled="keyResetPending"
                  class="px-2 py-0.5 text-[0.7rem] rounded bg-slate-700 hover:bg-violet-600 transition disabled:opacity-50">
            复活
          </button>
        </div>
      </template>
    </div>

    <button @click="showKeyDetail = !showKeyDetail"
            x-show="keyHealth.available && Object.keys(keyHealth.key_status || {}).length > 0"
            class="mt-2 text-xs text-slate-500 hover:text-slate-300">
      <span x-show="!showKeyDetail">▼ 展开详细 key 列表</span>
      <span x-show="showKeyDetail">▲ 收起</span>
    </button>
  </div>
</section>

<!-- Toast 通知 -->
<div x-show="toast.show" x-transition
     class="fixed bottom-6 right-6 max-w-md glass border rounded-xl p-4 shadow-2xl"
     :class="toast.ok ? 'border-emerald-500/50' : 'border-rose-500/50'">
  <p class="font-medium" :class="toast.ok ? 'text-emerald-300' : 'text-rose-300'" x-text="toast.title"></p>
  <p class="text-xs text-slate-400 mt-1" x-text="toast.detail"></p>
</div>

<script>
// 🩹 [β.5.28-fix4 / 2026-05-20] inline fallback - alpine 没绑/失败也能点
// 🩹 [β.5.28-fix6 / 2026-05-20] Sir 03:13 反馈"通过的瞬间所有信息不显示, 延迟避免?"
// 修法: 不再 location.reload (整页 flash). 改 in-place 删卡片 + 调 alpine refresh().
// 立刻反思 - trigger SoulArchivist propose 新 joke/thread
window.dashboardReflectNow = async function(btn) {
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = '⏳ 反思中 (10-30s)...';
  try {
    const resp = await fetch('/api/reflect_now', {method: 'POST'});
    const r = await resp.json();
    btn.textContent = r.ok ? '✓ 反思完成' : '✗ 反思失败';
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = orig;
      try { if (document.body.__x) document.body.__x.$data.refresh(); }
      catch (e) {}
    }, 2000);
    if (!r.ok) alert('反思失败: ' + (r.detail || r.stderr || ''));
    else console.log('[Reflect]', r.stdout);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = orig;
    alert('请求失败: ' + e);
  }
};

// 🩹 [β.5.28-fix9] 一键清空 Jarvis 承诺残留
window.dashboardResetPromise = async function(btn) {
  if (!confirm('清空所有 pending/untracked 承诺 (保留已兑现) ?\n\n这不可撤销.')) return;
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = '⏳ 清理中...';
  try {
    const resp = await fetch('/api/promise_reset', {method: 'POST'});
    const r = await resp.json();
    btn.textContent = r.ok ? '✓ 已清' : '✗ 失败';
    if (!r.ok) alert('失败: ' + (r.detail || r.stderr || ''));
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = orig;
      try { if (document.body.__x) document.body.__x.$data.refresh(); }
      catch (e) { location.reload(); }
    }, 1500);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = orig;
    alert('请求失败: ' + e);
  }
};

window.dashboardFallbackAct = async function(btn, action) {
  const kind = (btn.dataset.kind || '').split('/')[0];
  const id = btn.dataset.id;
  const pv = btn.dataset.pv;
  if (!kind || !id) { alert('数据丢失: kind=' + kind + ' id=' + id); return; }
  console.log('[Fallback]', action, kind, id);
  btn.disabled = true;
  btn.textContent = '⏳ 处理中...';
  // 立刻视觉淡出整张卡片 (找最近的 .glass.rounded-2xl 父)
  const card = btn.closest('.rounded-2xl');
  if (card) {
    card.style.transition = 'opacity 0.3s, transform 0.3s';
    card.style.opacity = '0.4';
  }
  try {
    const resp = await fetch('/api/review/' + action, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({kind: kind, id: id, proposed_value: pv})
    });
    const r = await resp.json();
    btn.textContent = r.ok ? '✓ ' + (action === 'activate' ? '已通过' : '已拒绝') : '✗ 失败';
    if (!r.ok) {
      // 失败 → 恢复卡片
      if (card) card.style.opacity = '1';
      alert('失败: ' + (r.detail || '未知'));
    } else {
      // 成功 → 卡片缩走 + 触发 Alpine refresh 而非 reload
      if (card) {
        card.style.transform = 'scale(0.95) translateX(20px)';
        card.style.opacity = '0';
      }
      // 触发 Alpine refresh (in-place 拉新数据更新 reviewItems / threads)
      setTimeout(() => {
        try {
          const root = document.body;
          if (root.__x) {
            root.__x.$data.refresh();
          } else {
            // Alpine 没 init → 退到 reload (兜底)
            location.reload();
          }
        } catch (e) {
          location.reload();
        }
      }, 350);
    }
  } catch (e) {
    if (card) card.style.opacity = '1';
    btn.disabled = false;
    btn.textContent = (action === 'activate' ? '✅ 通过' : '❌ 拒绝');
    alert('请求失败: ' + e);
  }
};

function dashboard() {
  return {
    loading: false,
    autoRefresh: true,
    lastUpdate: '...',
    summary: { level: 'ok', emoji: '🤖', headline: '加载中...', actions: [] },
    // 🩹 [β.5.43-A / 2026-05-20] HUD 状态条
    jarvisState: { state: '', display: {}, reason: '', age_seconds: 0 },
    reviewItems: [],
    concerns: {},
    relation: {},
    health: {},
    directive: {},
    daemon: {},
    events: {},
    mutations: {},
    integrity: {},
    todo: {},
    promise: {},
    // 🆕 [P5-Layer1-fix19-dashboard / 2026-05-22] 主脑 thinking pass META state
    brainMeta: {},
    // 🆕 [P5-fix20-A1 / 2026-05-22] KeyRouter 健康可视化 state
    keyHealth: {},
    showKeyDetail: false,
    keyResetPending: false,
    // 🆕 [P5-fix25-stand-down / 2026-05-22] Stand Down state
    standDown: { state: { active: false }, history: [], stats: {} },
    standDownActionPending: false,
    actionPending: {},
    toast: { show: false, ok: true, title: '', detail: '' },

    get reviewKindCounts() {
      const m = {};
      for (const it of this.reviewItems) {
        const bk = it.kind.split('/')[0];
        m[bk] = (m[bk] || 0) + 1;
      }
      return m;
    },
    get daemonLiveCount() {
      return (this.daemon.daemons || []).filter(d => d.live).length;
    },
    kindEmoji(k) {
      return ({concern:'🎯', relational:'💞', directive:'📜', cooldown:'⏰'})[k] || '·';
    },
    kindColorClass(kind) {
      const bk = kind.split('/')[0];
      return ({
        concern: 'bg-emerald-500/20 text-emerald-300',
        relational: 'bg-pink-500/20 text-pink-300',
        directive: 'bg-amber-500/20 text-amber-300',
        cooldown: 'bg-blue-500/20 text-blue-300',
      })[bk] || 'bg-slate-700/50';
    },

    async init() {
      await this.refresh();
      this.fetchJarvisState();
      this.fetchStandDown();
      setInterval(() => { if (this.autoRefresh) this.refresh(); }, 10000);
      // 🩹 [β.5.43-A / 2026-05-20] HUD 状态 2s 轮询 (Jarvis 状态变化要看得即时)
      setInterval(() => { this.fetchJarvisState(); }, 2000);
      // 🆕 [P5-fix25-stand-down] Stand Down 5s 轮询 (state 变化看得即时)
      setInterval(() => { this.fetchStandDown(); }, 5000);
    },
    async fetchJarvisState() {
      try {
        const r = await fetch('/api/state').then(r => r.json());
        if (r.ok) {
          this.jarvisState = r;
        }
      } catch (e) { /* silent */ }
    },
    // 🆕 [P5-fix25-stand-down]
    async fetchStandDown() {
      try {
        const r = await fetch('/api/stand_down').then(r => r.json());
        if (r.ok && r.data) {
          this.standDown = r.data;
        }
      } catch (e) { /* silent */ }
    },
    async standDownToggle() {
      if (this.standDownActionPending) return;
      this.standDownActionPending = true;
      try {
        const isActive = this.standDown.state && this.standDown.state.active;
        const action = isActive ? 'clear' : 'set';
        const body = isActive
          ? { action: 'clear', reason: 'dashboard wake' }
          : { action: 'set', reason: 'manual', duration_min: 30,
              exit_hint: 'dashboard manual set' };
        const r = await fetch('/api/stand_down_action', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(body),
        }).then(r => r.json());
        if (r.ok) {
          this.showToast(true, isActive ? '☀️ Wake up' : '🌙 进入沉默',
                          r.message || '');
          await this.fetchStandDown();
        } else {
          this.showToast(false, '失败', r.error || '');
        }
      } catch (e) {
        this.showToast(false, '错误', String(e));
      } finally {
        this.standDownActionPending = false;
      }
    },
    fmtRemaining(s) {
      if (!s || s <= 0) return '';
      if (s < 60) return Math.round(s) + 's';
      const m = Math.floor(s / 60);
      return m + 'min';
    },

    async refresh() {
      this.loading = true;
      try {
        const res = await fetch('/api/all');
        const data = await res.json();
        Object.assign(this, data);
        this.lastUpdate = new Date().toLocaleTimeString('zh-CN');
      } catch (e) {
        console.error(e);
      }
      this.loading = false;
    },

    async approve(it) { await this._act(it, 'activate'); },
    async reject(it) { await this._act(it, 'reject'); },

    async cancelCommitment(r) {
      const key = 'todo/' + r.id;
      console.log('[Dashboard] cancelCommitment', r.id);
      this.actionPending = {...this.actionPending, [key]: true};
      this.showToast(true, '⏳ 处理中...', '正在取消 ' + r.desc.slice(0, 40));
      try {
        const resp = await fetch(`/api/commitment/cancel/${r.id}`, {
          method: 'POST'
        });
        const j = await resp.json();
        this.showToast(j.ok, (j.ok ? '✓ 已取消' : '✗ 取消失败') + ': ' + r.desc.slice(0, 40), j.detail || '');
        setTimeout(() => this.refresh(), 600);
      } catch (e) {
        console.error('[Dashboard] cancelCommitment err', e);
        this.showToast(false, '✗ 请求失败', String(e));
      }
      const np = {...this.actionPending}; delete np[key]; this.actionPending = np;
    },

    async _act(it, kind) {
      const key = it.kind + '/' + it.id;
      console.log('[Dashboard]', kind, key, it.preview.slice(0, 40));
      // 🩹 [β.5.25-fix3 / 2026-05-20] Sir 02:49 反馈 '按钮按不动'.
      // 老 actionPending[key]=true 在 Alpine 3 新 key 不触发 reactive. 改 spread + immediate toast 反馈.
      this.actionPending = {...this.actionPending, [key]: true};
      this.showToast(true, '⏳ 处理中...', (kind === 'activate' ? '通过' : '拒绝') + ': ' + it.preview.slice(0, 40));
      try {
        const resp = await fetch(`/api/review/${kind}`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            kind: it.kind.split('/')[0],
            id: it.id,
            proposed_value: it.proposed_value,
          })
        });
        const r = await resp.json();
        console.log('[Dashboard] response', r);
        this.showToast(r.ok,
          (kind === 'activate' ? '✓ 通过' : '✗ 拒绝') + ': ' + it.preview.slice(0, 40),
          r.detail || (r.ok ? '完成' : '失败'));
        setTimeout(() => this.refresh(), 600);
      } catch (e) {
        console.error('[Dashboard] _act err', e);
        this.showToast(false, '✗ 请求失败', String(e));
      }
      const np = {...this.actionPending}; delete np[key]; this.actionPending = np;
    },

    showToast(ok, title, detail) {
      this.toast = { show: true, ok, title, detail };
      setTimeout(() => { this.toast.show = false; }, 4000);
    },

    // 🆕 [P5-fix20-A1 / 2026-05-22] Key 池 reset — 写 reset_request.json 让主进程 poll 执行
    async resetAllKeys() {
      if (!confirm('确认一键复活全部 key (清冷却 + 解永久死)? 主进程会在数秒内执行.')) return;
      this.keyResetPending = true;
      try {
        const r = await fetch('/api/key_reset', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'all', source: 'dashboard' })
        });
        const d = await r.json();
        this.showToast(d.ok !== false, '⚡ Reset 请求已写入', d.message || '主进程将在数秒内 poll 执行');
      } catch (e) {
        this.showToast(false, '❌ Reset 失败', String(e));
      } finally {
        this.keyResetPending = false;
      }
    },

    async resetKey(label, kind) {
      this.keyResetPending = true;
      try {
        const r = await fetch('/api/key_reset', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: kind, key_label: label, source: 'dashboard' })
        });
        const d = await r.json();
        this.showToast(d.ok !== false, `⚡ Reset ${label}`, d.message || '已写入');
      } catch (e) {
        this.showToast(false, `❌ Reset ${label} 失败`, String(e));
      } finally {
        this.keyResetPending = false;
      }
    }
  };
}
</script>

</body>
</html>
"""


# ============================================================
# API endpoints
# ============================================================

_BUILD_TS = __import__('time').strftime('%H:%M:%S')


@app.route('/')
def index():
    from flask import make_response
    resp = make_response(render_template_string(HTML_TEMPLATE, build_ts=_BUILD_TS))
    # 🩹 [β.5.28-fix4 / 2026-05-20] Sir 03:03 反馈"按钮还是点不了" - 浏览器缓存老 JS.
    # 加 no-cache header 防 Sir 刷新仍跑老 JS.
    # build_ts 显头部让 Sir 一眼看是不是新 server (老 server 跑 build_ts 不变).
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


def _summary_for_web() -> Dict[str, Any]:
    """复用 compute_overall_status 算出整体状态."""
    try:
        concerns = jd.read_concerns()
        relation = jd.read_relational()
        promise = jd.read_jarvis_promises()
        directive = jd.read_directives()
        daemon = jd.read_daemon_status()
        health = jd.read_system_health()
        review = jd.read_review_queues()
        events = jd.read_event_stream(limit=25)
        mutations = jd.read_memory_mutations()
        integrity = jd.read_integrity_stats()
        todo = jd.read_sir_commitments()
        overall = jd.compute_overall_status(
            concerns, directive, promise, relation,
            daemon, health, review, events,
            mutations=mutations, integrity=integrity)
        # 🆕 [P5-Layer1-fix19-dashboard / 2026-05-22] 主页 mini stats card
        # 主脑 thinking pass META 健康度: total/skip%/evidence% 一眼看,
        # 不点 /main_brain_meta page 也能瞄一眼.
        brain_meta = _read_brain_meta_summary()
        # 🆕 [P5-fix20-A1 / 2026-05-22] Sir 14:32 key 池雪崩真测痛点修.
        # 主页加 key 池健康 mini card, Sir 一眼看哪个池挂了.
        key_health = _read_key_health()
        emoji_map = {'ok': '✅', 'warn': '⚠️', 'crit': '❌'}
        return {
            'summary': {
                'level': overall.get('level', 'ok'),
                'emoji': emoji_map.get(overall.get('level', 'ok'), '🤖'),
                'headline': overall.get('headline', ''),
                'actions': overall.get('top_actions', []),
            },
            'reviewItems': review.get('items', []),
            'concerns': concerns,
            'relation': relation,
            'health': health,
            'directive': directive,
            'daemon': daemon,
            'events': events,
            'mutations': mutations,
            'integrity': integrity,
            'todo': todo,
            'promise': promise,
            'brainMeta': brain_meta,
            'keyHealth': key_health,
        }
    except Exception as e:
        return {
            'summary': {'level': 'crit', 'emoji': '❌',
                         'headline': f'读取失败: {e}', 'actions': []},
            'reviewItems': [], 'concerns': {}, 'relation': {}, 'health': {},
            'directive': {}, 'daemon': {}, 'events': {}, 'mutations': {},
            'integrity': {}, 'todo': {}, 'promise': {}, 'brainMeta': {},
            'keyHealth': {},
        }


def _read_key_health() -> Dict[str, Any]:
    """🆕 [P5-fix20-A1 / 2026-05-22] 读 KeyRouter health snapshot.

    KeyRouter daemon 每 15s 写 memory_pool/key_router_health.json.
    Sir 14:32 真测痛点: OpenRouter 全挂 + Google 池 429 → 主脑能开口但
    IntentResolver/Vision/Hippocampus 全降级 → "嘴上说没真做". 这卡片
    一眼让 Sir 看到哪个池挂了, 不用进 log 翻.
    """
    import json as _json
    path = os.path.join(ROOT, 'memory_pool', 'key_router_health.json')
    if not os.path.exists(path):
        return {'available': False,
                'health_msg': 'Jarvis 未启动 / KeyRouter 未上线 (启 jarvis 等 15s)'}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            stats = _json.load(f)
    except Exception as e:
        return {'available': False, 'health_msg': f'读 snapshot 失败: {e}'}

    # 加诊断文本
    pools = stats.get('pools', {})
    overall = stats.get('overall_health', 'ok')
    issues = []
    for name, p in pools.items():
        if p['total'] == 0:
            continue
        if p['healthy'] == 0:
            issues.append(f"❌ {name} 池全挂 (0/{p['total']})")
        elif p['healthy'] < p['total']:
            cooling = p.get('in_cooldown', 0)
            dead = p.get('permanent_dead', 0)
            issues.append(
                f"⚠️ {name} 部分降级 ({p['healthy']}/{p['total']}"
                + (f", 永久死 {dead}" if dead else '')
                + (f", 冷却 {cooling}" if cooling else '')
                + ')'
            )

    if not issues:
        health_msg = f"✅ 全部 key 池健康"
    else:
        health_msg = ' · '.join(issues)

    snapshot_ts = stats.get('_snapshot_ts', 0)
    age_s = max(0, int(time.time() - snapshot_ts)) if snapshot_ts else None

    return {
        'available': True,
        'overall': overall,
        'health_msg': health_msg,
        'issues': issues,
        'pools': pools,
        'key_status': stats.get('key_status', {}),
        'openrouter_calls_today': stats.get('openrouter_calls_today', 0),
        'snapshot_age_s': age_s,
        'snapshot_iso': stats.get('_snapshot_iso', ''),
    }


def _read_brain_meta_summary() -> Dict[str, Any]:
    """🆕 [P5-Layer1-fix19-dashboard / 2026-05-22] 主页 mini card 数据.

    返回简版 stats: total / skip% / evidence% / health / 最近 1 条 turn note.
    """
    try:
        from jarvis_meta_self_check import read_recent_meta
        records = read_recent_meta(limit=200)  # 最近 200 算 stats
        n = len(records)
        if n == 0:
            return {
                'total': 0,
                'skip_alert_pct': 0,
                'evidence_pct': 0,
                'avg_evidence_per_turn': 0,
                'health': 'empty',
                'health_msg': '主脑还没跑 META (jarvis 重启后等几轮)',
                'latest_turn_note': '',
                'latest_turn_skip_alert': False,
            }
        n_skip = sum(1 for r in records if r.get('skip_alert'))
        n_ev = sum(1 for r in records
                   if r.get('evidence') and r.get('evidence') != ['none'])
        avg_ev = sum(len(r.get('evidence', []) or []) for r in records) / n
        skip_pct = round(100 * n_skip / n, 1)
        ev_pct = round(100 * n_ev / n, 1)

        if skip_pct > 50:
            health = 'warn'
            health_msg = f'skip_alert {skip_pct}% — 主脑频繁拒道歉'
        elif ev_pct < 30 and n > 5:
            health = 'warn'
            health_msg = f'evidence 非空 {ev_pct}% — directive 可能被忽略'
        elif ev_pct > 70:
            health = 'ok'
            health_msg = f'evidence {ev_pct}% — Layer 1 落地良好'
        else:
            health = 'ok'
            health_msg = f'{n} 轮 META, evidence {ev_pct}%'

        latest = records[-1] if records else {}
        return {
            'total': n,
            'skip_alert_count': n_skip,
            'skip_alert_pct': skip_pct,
            'evidence_count': n_ev,
            'evidence_pct': ev_pct,
            'avg_evidence_per_turn': round(avg_ev, 2),
            'health': health,
            'health_msg': health_msg,
            'latest_turn_note': (latest.get('note') or '')[:50],
            'latest_turn_skip_alert': bool(latest.get('skip_alert')),
            'latest_turn_id': latest.get('turn_id', ''),
            'latest_turn_reaction': latest.get('reaction', ''),
        }
    except Exception:
        return {}


@app.route('/api/commitment/cancel/<int:cw_id>', methods=['POST'])
def api_cancel_commitment(cw_id: int):
    """🩹 [β.5.25] 取消 Sir 待办 (Commitments)."""
    result = {'ok': False, 'detail': ''}
    done = threading.Event()
    def _on_done(ok, out):
        result['ok'] = bool(ok)
        result['detail'] = str(out)[:400]
        done.set()
    try:
        jd.action_cancel_commitment(cw_id, on_done=_on_done)
    except Exception as e:
        return jsonify({'ok': False, 'detail': str(e)}), 500
    if not done.wait(timeout=15):
        return jsonify({'ok': False, 'detail': '超时'}), 504
    return jsonify(result)


@app.route('/api/promise_reset', methods=['POST'])
def api_promise_reset():
    """🩹 [β.5.28-fix9 / 2026-05-20] Sir 03:33 反馈 'Jarvis 口头答应没做到没地方显示'.
    一键清残留 promise (保留已兑现历史). 调 scripts/promise_log_reset.py."""
    import subprocess as _sp
    try:
        r = _sp.run(
            [sys.executable, 'scripts/promise_log_reset.py',
             '--apply', '--keep-fulfilled'],
            capture_output=True, text=True, timeout=15,
        )
        return jsonify({
            'ok': r.returncode == 0,
            'stdout': (r.stdout or '')[:1000],
            'stderr': (r.stderr or '')[:500],
        })
    except _sp.TimeoutExpired:
        return jsonify({'ok': False, 'detail': '超时'}), 504
    except Exception as e:
        return jsonify({'ok': False, 'detail': str(e)}), 500


@app.route('/api/reflect_now', methods=['POST'])
def api_reflect_now():
    """🩹 [β.5.28-fix6/8 / 2026-05-20] Sir 03:13/03:25 反馈 'JOKE/经历 不动态更新'.

    双路触发:
    1. concerns_dump.py --reflect-now → WeeklyReflector (propose concerns)
    2. 写 memory_pool/_force_soul_now.flag → 主 jarvis 进程的 SoulArchivist 60s 内
       检测 flag → 强制反思一次 (propose jokes/threads, 绕过 last_update_hour cooldown).
    """
    import subprocess as _sp
    import os as _os
    # 1. SoulArchivist flag (主进程 SoulArchivist 60s 内会 pick up)
    soul_flag_ok = False
    try:
        flag_path = _os.path.join('memory_pool', '_force_soul_now.flag')
        with open(flag_path, 'w') as f:
            f.write(str(int(__import__('time').time())))
        soul_flag_ok = True
    except Exception as fe:
        pass
    # 2. WeeklyReflector concerns
    try:
        r = _sp.run(
            [sys.executable, 'scripts/concerns_dump.py', '--reflect-now'],
            capture_output=True, text=True, timeout=60,
        )
        return jsonify({
            'ok': r.returncode == 0 and soul_flag_ok,
            'stdout': (r.stdout or '')[:1000],
            'stderr': (r.stderr or '')[:500],
            'soul_flag': '✓ SoulArchivist flag written (60s 内会反思 propose joke/thread)'
                          if soul_flag_ok else '✗ flag 写入失败',
        })
    except _sp.TimeoutExpired:
        return jsonify({
            'ok': soul_flag_ok,
            'detail': 'WeeklyReflector 60s 超时, 但 SoulArchivist flag 已写',
            'soul_flag': soul_flag_ok,
        }), 504
    except Exception as e:
        return jsonify({
            'ok': soul_flag_ok,
            'detail': str(e),
            'soul_flag': soul_flag_ok,
        }), 500


@app.route('/api/all')
def api_all():
    data = _summary_for_web()
    # 🩹 [β.5.28-i18n / 2026-05-20] Sir 02:49 'review 提案能不能带翻译'.
    # 用 QuickClassifier.prompt_raw (本地 ollama qwen2.5:1.5b) 翻 preview/rationale 英→中.
    # 失败/无 ollama → preview_zh 留空 (前端 fallback 只显原文).
    try:
        _i18n_review_items(data.get('reviewItems', []))
    except Exception as _ie:
        pass
    return jsonify(data)


# 简单 i18n cache (per-process, key=源字符串 → zh)
_I18N_CACHE: Dict[str, str] = {}
_I18N_LOCK = threading.Lock()


def _looks_english(s: str) -> bool:
    """判 s 是否主要英文 (字母 > 50% + 没有 CJK)."""
    if not s:
        return False
    if any('\u4e00' <= c <= '\u9fff' for c in s):
        return False  # 已有中文不翻
    letters = sum(1 for c in s if c.isalpha())
    return letters > len(s) * 0.4


def _translate_to_zh(text: str, max_len: int = 300) -> str:
    """用 QuickClassifier.prompt_raw 翻英→中. 失败返空."""
    if not text or not _looks_english(text):
        return ''
    t = text[:max_len].strip()
    with _I18N_LOCK:
        if t in _I18N_CACHE:
            return _I18N_CACHE[t]
    try:
        from jarvis_utils import get_quick_classifier
        qc = get_quick_classifier()
        if not qc or not getattr(qc, 'is_available', False):
            return ''
        if not hasattr(qc, 'prompt_raw'):
            return ''
        prompt = (
            "将下面这段英文简洁地翻成中文 (1 句话, 保留原意, 不加解释).\n\n"
            f"英文: {t}\n\n"
            "中文:"
        )
        resp = qc.prompt_raw(prompt, max_tokens=200, temperature=0.0, timeout=5.0)
        zh = (resp or '').strip()
        # 取首行 + 去 "中文:" 前缀
        zh = zh.split('\n')[0].strip()
        for prefix in ('中文:', '中文：', 'Chinese:', '翻译:', '翻译：'):
            if zh.startswith(prefix):
                zh = zh[len(prefix):].strip()
        if zh:
            with _I18N_LOCK:
                _I18N_CACHE[t] = zh
                # 缓存上限防内存爆
                if len(_I18N_CACHE) > 500:
                    # FIFO drop 100
                    for _k in list(_I18N_CACHE.keys())[:100]:
                        del _I18N_CACHE[_k]
            return zh
    except Exception:
        return ''
    return ''


def _i18n_review_items(items: list) -> None:
    """给每条 review item 加 preview_zh / rationale_zh (in-place)."""
    for it in items[:30]:  # 30 上限防 ollama 慢
        if 'preview_zh' not in it:
            it['preview_zh'] = _translate_to_zh(it.get('preview', ''))
        if 'rationale_zh' not in it:
            it['rationale_zh'] = _translate_to_zh(it.get('rationale', ''))


@app.route('/api/review/<action_kind>', methods=['POST'])
def api_review(action_kind: str):
    """通过/拒绝一条 review 提案. 同步阻塞调 subprocess (浏览器请求会等)."""
    if action_kind not in ('activate', 'reject'):
        return jsonify({'ok': False, 'detail': f'invalid action: {action_kind}'}), 400
    data = request.get_json(silent=True) or {}
    kind = data.get('kind', '')
    item_id = data.get('id', '')
    if not kind or not item_id:
        return jsonify({'ok': False, 'detail': 'missing kind / id'}), 400

    # 同步 wrap action_*_review (它是异步, 用 Event)
    result = {'ok': False, 'detail': ''}
    done = threading.Event()
    def _on_done(ok, out):
        result['ok'] = bool(ok)
        result['detail'] = str(out)[:400]
        done.set()

    extra = None
    if kind == 'cooldown':
        extra = {'proposed_value': data.get('proposed_value')}

    fn = jd.action_activate_review if action_kind == 'activate' else jd.action_reject_review
    try:
        fn(kind, item_id, on_done=_on_done, extra=extra)
    except TypeError:
        # 老接口没 extra
        fn(kind, item_id, on_done=_on_done)
    # 等最多 15s
    if not done.wait(timeout=15):
        return jsonify({'ok': False, 'detail': '操作超时 (>15s)'}), 504
    return jsonify(result)


# ============================================================
# 🩹 [β.5.41-C / 2026-05-20] Actionable Items API + UI (Sir 16:43 真理)
# 所有 Sir 拍板事项全面出现 + 修正/删除按钮 + 实时状态 + 影响预览
# ============================================================

try:
    import jarvis_actionable_items as _ai
except Exception:
    _ai = None

try:
    import jarvis_state_tracker as _jst
except Exception:
    _jst = None


@app.route('/api/state')
def api_state():
    """🩹 [β.5.43-A / 2026-05-20] Jarvis HUD 状态: ready/thinking/speaking/listening/focused/error."""
    if _jst is None:
        return jsonify({'ok': False, 'state': 'unknown', 'error': 'state_tracker not available'}), 500
    try:
        snap = _jst.get_state_tracker().get_snapshot()
        return jsonify({'ok': True, **snap})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/recent_replies')
def api_recent_replies():
    """🩹 [β.5.43-D / 2026-05-20] 最近 N 条 Jarvis reply (供 Sir 评价).
    从 nerve STM 拿 jarvis assistant entries."""
    try:
        # 尝试从 STM 持久化文件读 (jarvis_central_nerve 持久化路径)
        stm_path = os.path.join(ROOT, 'memory_pool', 'short_term_memory.jsonl')
        recent = []
        if os.path.exists(stm_path):
            with open(stm_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                        jrv = (e.get('jarvis', '') or '').strip()
                        if jrv and len(jrv) > 5:
                            recent.append({
                                'ts': e.get('ts', 0),
                                'user_input': (e.get('user', '') or '')[:120],
                                'reply': jrv[:300],
                            })
                    except Exception:
                        pass
        recent = recent[-12:]  # 最近 12 条
        # 已有 feedback 标记
        try:
            import jarvis_reply_feedback as _rfb
            fb_entries = _rfb.get_recent_reply_feedback(hours=48, limit=50)
            feedback_map = {}
            for fb in fb_entries:
                fb_excerpt = (fb.get('reply_excerpt', '') or '')[:50]
                if fb_excerpt:
                    feedback_map[fb_excerpt] = fb.get('verdict', '?')
            for r in recent:
                excerpt = r['reply'][:50]
                r['existing_verdict'] = feedback_map.get(excerpt, '')
        except Exception:
            for r in recent:
                r['existing_verdict'] = ''
        return jsonify({'ok': True, 'replies': recent})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/reply_feedback', methods=['POST'])
def api_reply_feedback():
    """🩹 [β.5.43-D / 2026-05-20] Sir 评 reply: 写 reply_feedback.jsonl."""
    payload = request.get_json(silent=True) or {}
    reply_excerpt = payload.get('reply_excerpt', '')
    verdict = payload.get('verdict', '')
    sir_note = payload.get('sir_note', '')
    try:
        import jarvis_reply_feedback as _rfb
        ok = _rfb.log_reply_feedback(reply_excerpt, verdict, sir_note)
        if ok:
            return jsonify({'ok': True, 'detail': f'{verdict} 已记录'})
        else:
            return jsonify({'ok': False, 'error': f'invalid verdict {verdict}'}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/system_errors')
def api_system_errors():
    """🩹 [β.5.43-F / 2026-05-20 19:10] System Error Banner
    
    Sir 17:10 真理 (6 缺口 F): 让 Sir 看到哪些 module 静默 fail.
    
    Query params:
      - hours: 回看小时数 (default 1)
      - min_severity: minor / moderate / severe (default moderate)
      - limit: 最多条数 (default 30)
    """
    try:
        from jarvis_error_bus import get_error_bus, SEVERITY_MINOR
        bus = get_error_bus()
        hours = float(request.args.get('hours', 1))
        min_sev = (request.args.get('min_severity', 'moderate') or 'moderate').strip()
        limit = int(request.args.get('limit', 30))
        within = max(60, min(86400, hours * 3600))
        errors = bus.recent_errors(
            within_seconds=within,
            min_severity=min_sev,
            max_n=limit,
        )
        # 统计
        by_sev = {'minor': 0, 'moderate': 0, 'severe': 0}
        by_module = {}
        for e in errors:
            by_sev[e.get('severity', 'minor')] = by_sev.get(e.get('severity', 'minor'), 0) + 1
            m = e.get('module', '?')
            by_module[m] = by_module.get(m, 0) + 1
        return jsonify({
            'ok': True,
            'errors': errors,
            'stats': {
                'total': len(errors),
                'by_severity': by_sev,
                'by_module': by_module,
                'bus_stats': bus.stats(),
            },
            'hours': hours,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============================================================
# 🆕 [P5-fix20-A1/A2 / 2026-05-22] KeyRouter 健康 API + reset endpoint
# Sir 14:32 真测痛点: OpenRouter 全挂 + Google 429 → 主脑嘴上说没真做.
# A1: /api/key_health 返回 KeyRouter snapshot.
# A2: /api/key_reset (POST) 调 reset_cooldown / reset_permanent / reset_all.
# 注意: dashboard 是独立进程, 通过 disk snapshot 读 (不直持 KeyRouter 实例).
# 但 reset 必须打到主进程 KeyRouter — 这里先用 file-based signal:
#   写 memory_pool/key_router_reset_request.json, 主进程 daemon poll + 执行.
# ============================================================

@app.route('/api/key_health')
def api_key_health():
    """🆕 [P5-fix20-A1] KeyRouter 健康 snapshot (Sir 一眼看 key 池状态)."""
    try:
        return jsonify({'ok': True, 'data': _read_key_health()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/key_reset', methods=['POST'])
def api_key_reset():
    """🆕 [P5-fix20-A2] Sir 一键复活 key. 写 reset_request.json, 主进程 poll 执行.

    POST body: {"action": "cooldown"|"permanent"|"all", "label": "google_1"}
    """
    try:
        payload = request.get_json(silent=True) or {}
        action = (payload.get('action', '') or '').strip().lower()
        # 接受 label 或 key_label (前端 dashboard 用 key_label, CLI 用 label)
        label = (payload.get('label', '') or payload.get('key_label', '') or '').strip()
        source = (payload.get('source', '') or 'api').strip()
        if action not in ('cooldown', 'permanent', 'all'):
            return jsonify({'ok': False, 'error': f'invalid action: {action}'}), 400
        if action != 'all' and not label:
            return jsonify({'ok': False, 'error': 'label required for cooldown/permanent action'}), 400

        req = {
            'action': action,
            'label': label,
            'source': source,
            'requested_at': time.time(),
            'requested_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'consumed': False,
        }
        path = os.path.join(ROOT, 'memory_pool', 'key_router_reset_request.json')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(req, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        msg = f"已写 reset 请求 ({action}{' ' + label if label else ''}). 主进程 KeyRouter ≤15s 内 poll 执行."
        return jsonify({
            'ok': True,
            'message': msg,
            'detail': msg,
            'request': req,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e), 'message': f'失败: {e}'}), 500


# ============================================================
# 🆕 [P5-fix21-c-dashboard / 2026-05-22] WatchTask panel
# Sir 14:50 痛点: "答应盯 S 联赛比赛 但其实没真注册" — dashboard 一眼看哪些
# active task / 失败注册的 SWM event / 哪些是空壳 fallback (trigger='an event...')
# ============================================================

@app.route('/api/watch_tasks')
def api_watch_tasks():
    """🆕 [P5-fix21-c] WatchTask snapshot — active / fired / cancelled / expired.

    Query params:
      - state: 'active' (default) | 'all'
      - limit: max records (default 50)

    Returns:
      {ok, data: {active: [...], total: N, register_fails: [...]}}
    """
    try:
        sys.path.insert(0, ROOT)
        from jarvis_watch_task import _load_tasks, list_active_tasks
        state = (request.args.get('state', 'active') or 'active').strip().lower()
        try:
            limit = int(request.args.get('limit', '50') or '50')
        except Exception:
            limit = 50
        if limit <= 0 or limit > 500:
            limit = 50

        if state == 'all':
            raw = _load_tasks()
        else:
            raw = list_active_tasks()

        records = []
        now = time.time()
        for t in raw[:limit]:
            age_s = max(0, int(now - t.created_at))
            ttl_s = int(t.expires_at - now) if t.expires_at > 0 else -1
            # 检测是否空壳 fallback (旧 _template_fallback 写的)
            is_empty_shell = (
                t.trigger_evidence == 'an event Sir mentioned in his utterance'
                and t.notify_msg_en.startswith('Sir, the event you')
            )
            records.append({
                'id': t.id,
                'state': t.state,
                'turn_id': t.turn_id,
                'what_to_watch': t.what_to_watch[:200],
                'trigger_evidence': t.trigger_evidence[:200],
                'notify_msg_en': t.notify_msg_en[:200],
                'notify_msg_zh': t.notify_msg_zh[:200],
                'created_at': t.created_at,
                'created_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                                time.localtime(t.created_at)),
                'expires_at': t.expires_at,
                'fired_at': t.fired_at,
                'fired_evidence': t.fired_evidence[:200] if t.fired_at > 0 else '',
                'judge_count': t.judge_count,
                'last_judge_at': t.last_judge_at,
                'last_judge_age_s': (max(0, int(now - t.last_judge_at))
                                          if t.last_judge_at > 0 else -1),
                'last_judge_summary': t.last_judge_summary[:200],
                'age_s': age_s,
                'ttl_s': ttl_s,
                'is_empty_shell': is_empty_shell,  # 老版 fallback 留下的
            })

        # register_fail SWM events (recent 600s)
        register_fails = []
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                evs = bus.recent_events(within_seconds=600.0,
                                            types={'watch_task_register_fail'}) or []
                for e in evs[-20:]:
                    meta = e.get('metadata') or {}
                    register_fails.append({
                        'sir_text': (meta.get('sir_text') or '')[:200],
                        'reason': (meta.get('reason') or '')[:120],
                        'turn_id': (meta.get('turn_id') or '')[:30],
                        'ts': float(meta.get('ts', 0) or 0),
                        'age_s': max(0, int(now - float(meta.get('ts', 0) or 0))),
                    })
        except Exception:
            pass

        # stats
        all_tasks = _load_tasks()
        stats = {'active': 0, 'fired': 0, 'cancelled': 0, 'expired': 0}
        empty_shell_active = 0
        for t in all_tasks:
            stats[t.state] = stats.get(t.state, 0) + 1
            if (t.state == 'active'
                and t.trigger_evidence == 'an event Sir mentioned in his utterance'):
                empty_shell_active += 1

        return jsonify({
            'ok': True,
            'data': {
                'records': records,
                'total': len(raw),
                'state_filter': state,
                'stats': stats,
                'empty_shell_active': empty_shell_active,
                'register_fails': register_fails,
            }
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============================================================
# 🆕 [P5-fix25-stand-down-dashboard / 2026-05-22] Stand Down panel
# Sir 痛点: 玩游戏/接电话/和爸妈说话尴尬. Dashboard 一眼看 active state +
# 一键 set / clear / 看 history.
# ============================================================

@app.route('/api/stand_down')
def api_stand_down():
    """🆕 [P5-fix25-stand-down] Stand Down 当前 state + history.

    Returns:
      {ok, data: {state: {...}, history: [...recent N], stats: {...}}}
    """
    try:
        sys.path.insert(0, ROOT)
        import jarvis_stand_down as sd
        s = sd.get_state()
        now = time.time()

        # state snapshot for UI
        state_dict = {
            'active': s.is_active_now(),
            'reason': s.reason,
            'since_ts': s.since_ts,
            'since_iso': (time.strftime('%H:%M:%S', time.localtime(s.since_ts))
                              if s.since_ts > 0 else ''),
            'until_ts': s.until_ts,
            'until_iso': (time.strftime('%H:%M:%S', time.localtime(s.until_ts))
                              if s.until_ts > 0 else ''),
            'elapsed_s': int(s.elapsed_s()),
            'remaining_s': int(s.remaining_s()),
            'in_grace': s.is_in_grace(),
            'grace_until_ts': s.grace_until_ts,
            'exit_hint': s.exit_hint,
            'set_by_source': s.set_by_source,
            'set_by_turn': s.set_by_turn,
            'cleared_at_ts': s.cleared_at_ts,
            'cleared_by_source': s.cleared_by_source,
            'cleared_iso': (time.strftime('%H:%M:%S',
                                                time.localtime(s.cleared_at_ts))
                                if s.cleared_at_ts > 0 else ''),
        }

        # history (recent 30)
        history = []
        try:
            hist_path = os.path.join(ROOT, 'memory_pool',
                                          'stand_down_history.jsonl')
            if os.path.exists(hist_path):
                with open(hist_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                for L in lines[-30:]:
                    try:
                        history.append(json.loads(L.strip()))
                    except Exception:
                        pass
        except Exception:
            pass

        # stats (count enter/exit, total held time today)
        today_start = time.mktime(time.strptime(
            time.strftime('%Y-%m-%d 00:00:00'), '%Y-%m-%d %H:%M:%S'))
        sets_today = 0
        clears_today = 0
        held_s_today = 0.0
        for h in history:
            if h.get('ts', 0) >= today_start:
                ev = h.get('event', '')
                if ev == 'set':
                    sets_today += 1
                elif ev == 'clear':
                    clears_today += 1
                    held_s_today += float(h.get('duration_held_s', 0) or 0)
        stats = {
            'sets_today': sets_today,
            'clears_today': clears_today,
            'held_s_today': int(held_s_today),
            'held_min_today': round(held_s_today / 60, 1),
        }

        return jsonify({
            'ok': True,
            'data': {
                'state': state_dict,
                'history': history,
                'stats': stats,
            }
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/stand_down_action', methods=['POST'])
def api_stand_down_action():
    """🆕 [P5-fix25-stand-down] set / clear stand_down via dashboard.

    POST body:
      {action: 'set'|'clear', reason: str, duration_min: float, exit_hint: str}
    """
    try:
        sys.path.insert(0, ROOT)
        import jarvis_stand_down as sd
        payload = request.get_json(silent=True) or {}
        action = (payload.get('action', '') or '').strip().lower()
        if action == 'set':
            reason = (payload.get('reason', '') or sd.REASON_MANUAL)[:64]
            try:
                duration_min = float(payload.get('duration_min',
                                                       sd.DEFAULT_DURATION_MIN))
            except Exception:
                duration_min = sd.DEFAULT_DURATION_MIN
            exit_hint = (payload.get('exit_hint', '') or '')[:200]
            s = sd.set_stand_down(
                reason=reason,
                duration_min=duration_min,
                exit_hint=exit_hint,
                source='dashboard',
            )
            eta = time.strftime('%H:%M', time.localtime(s.until_ts))
            return jsonify({
                'ok': True,
                'message': f'进入沉默 reason={s.reason} until={eta}',
                'state': {
                    'active': True,
                    'reason': s.reason,
                    'until_iso': eta,
                    'remaining_min': int(s.remaining_s() / 60),
                },
            })
        if action == 'clear':
            reason = (payload.get('reason', '') or 'dashboard wake')[:200]
            was_active = sd.is_active()
            sd.clear_stand_down(reason=reason, source='dashboard')
            return jsonify({
                'ok': True,
                'message': ('wake up' if was_active
                              else '当前未在 stand_down, 无需 clear'),
                'state': {'active': False},
            })
        return jsonify({'ok': False,
                          'error': f'invalid action: {action} (set|clear)'}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/watch_task_action', methods=['POST'])
def api_watch_task_action():
    """🆕 [P5-fix21-c] cancel / expire 一个 task. POST {action, task_id}."""
    try:
        sys.path.insert(0, ROOT)
        from jarvis_watch_task import cancel_task, expire_task
        payload = request.get_json(silent=True) or {}
        action = (payload.get('action', '') or '').strip().lower()
        task_id = (payload.get('task_id', '') or '').strip()
        if action not in ('cancel', 'expire'):
            return jsonify({'ok': False, 'error': f'invalid action: {action}'}), 400
        if not task_id:
            return jsonify({'ok': False, 'error': 'task_id required'}), 400

        if action == 'cancel':
            ok = cancel_task(task_id)
        else:
            ok = expire_task(task_id)

        if ok:
            return jsonify({'ok': True,
                              'message': f"{action}ed {task_id}",
                              'detail': f"{action}ed {task_id}"})
        return jsonify({'ok': False,
                          'error': f'task not found or not active: {task_id}',
                          'message': f'失败: not found / not active'}), 404
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============================================================
# 🆕 [P5-Layer1-fix19-dashboard / 2026-05-22] Sir 13:13 立 Layer 1 主脑 thinking pass
# 可视化集成 — 把 main_brain_meta_audit.jsonl 数据搬上 dashboard.
# Sir 14:31 反馈: "把这些信息能放都放到可视化窗口方便我看".
# ============================================================

@app.route('/api/main_brain_meta')
def api_main_brain_meta():
    """主脑 thinking pass META audit (每轮 evidence/reaction/skip_alert/note).

    Query params:
      - limit: 最近 N 条 (default 50)
      - turn:  按 turn_id 过滤
      - skip_alert: 仅主脑拒道歉的 (yes / no / all)
      - reaction:   仅特定 reaction (voice/silent_text/silence/all)

    Returns:
      {ok, records: [...], stats: {...}, total: N}
    """
    try:
        from jarvis_meta_self_check import read_recent_meta
        # 拿全部 (内部 cap), 然后再 client 端 filter + 切 limit
        limit = int(request.args.get('limit', '50') or '50')
        if limit <= 0:
            limit = 50
        if limit > 500:
            limit = 500
        # debug-only: testcase 可传 audit_path 显式指定 (production 路径不用)
        audit_path = (request.args.get('audit_path', '') or '').strip() or None
        all_records = read_recent_meta(limit=limit * 4,
                                          audit_path=audit_path)  # 多拿一些供 filter

        # filter
        turn = (request.args.get('turn', '') or '').strip()
        skip_alert_f = (request.args.get('skip_alert', 'all') or 'all').strip().lower()
        reaction_f = (request.args.get('reaction', 'all') or 'all').strip().lower()

        filtered = all_records
        if turn:
            filtered = [r for r in filtered if r.get('turn_id') == turn]
        if skip_alert_f == 'yes':
            filtered = [r for r in filtered if r.get('skip_alert')]
        elif skip_alert_f == 'no':
            filtered = [r for r in filtered if not r.get('skip_alert')]
        if reaction_f != 'all':
            filtered = [r for r in filtered if r.get('reaction') == reaction_f]

        # 取最后 limit 条 (倒序 newest first)
        if len(filtered) > limit:
            filtered = filtered[-limit:]
        # 倒序 (新的在上)
        filtered = list(reversed(filtered))

        # stats (基于 all_records, 看全局健康度)
        n_all = len(all_records)
        n_skip = sum(1 for r in all_records if r.get('skip_alert'))
        n_evidence = sum(1 for r in all_records
                          if r.get('evidence') and r.get('evidence') != ['none'])
        reactions: Dict[str, int] = {}
        for r in all_records:
            rc = r.get('reaction', '?')
            reactions[rc] = reactions.get(rc, 0) + 1

        # 平均 evidence 数 / 轮
        avg_ev = (sum(len(r.get('evidence', []) or []) for r in all_records) /
                   max(1, n_all))

        stats = {
            'total': n_all,
            'skip_alert_count': n_skip,
            'skip_alert_pct': round(100 * n_skip / max(1, n_all), 1),
            'evidence_count': n_evidence,
            'evidence_pct': round(100 * n_evidence / max(1, n_all), 1),
            'reactions': reactions,
            'avg_evidence_per_turn': round(avg_ev, 2),
        }
        # 健康度判定 (供前端着色)
        health = 'ok'
        health_msg = ''
        if n_all == 0:
            health = 'empty'
            health_msg = '主脑还没跑过含 META 的对话 (jarvis 重启后等几轮才有数据)'
        elif n_skip / max(1, n_all) > 0.5:
            health = 'warn'
            health_msg = (f'skip_alert > 50% — 主脑频繁拒道歉, '
                           f'可能 IntegrityAlert 误判过多')
        elif n_evidence / max(1, n_all) < 0.3 and n_all > 5:
            health = 'warn'
            health_msg = (f'evidence 非空 < 30% — 主脑很多轮 evidence=none, '
                           f'directive 可能被忽略')
        elif n_evidence / max(1, n_all) > 0.7:
            health = 'ok'
            health_msg = 'evidence 非空 > 70% — Layer 1 落地良好'

        return jsonify({
            'ok': True,
            'records': filtered,
            'stats': stats,
            'total': n_all,
            'returned': len(filtered),
            'health': health,
            'health_msg': health_msg,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/intent_resolved')
def api_intent_resolved():
    """🩹 [β.5.44-F / 2026-05-20 19:08] IntentResolver 最近 mutation log
    
    Sir 18:55 真理可视化: '这轮 Jarvis 做了什么'. 让 Sir 看到 SWM 里
    intent_resolved + tool_called events 时序, 知道哪轮真调了 tool, 调成功 / 失败.
    
    Query params:
      - hours: 回看小时数 (default 2)
      - limit: 最多条数 (default 30)
    """
    try:
        from jarvis_utils import get_event_bus
        bus = get_event_bus()
        if bus is None:
            return jsonify({
                'ok': True,
                'events': [],
                'note': 'event_bus not initialized',
            })
        hours = float(request.args.get('hours', 2))
        limit = int(request.args.get('limit', 30))
        within = max(60, min(86400, hours * 3600))
        try:
            events = bus.recent_events(
                within_seconds=within,
                types={'intent_resolved', 'tool_called'},
            )
        except Exception:
            events = []
        # 排序: 新 → 老, 截 limit
        events_sorted = sorted(
            events, key=lambda e: e.get('ts', 0), reverse=True
        )[:limit]
        # 简化 output (避免 metadata 太大)
        out = []
        for ev in events_sorted:
            meta = ev.get('metadata') or {}
            entry = {
                'ts': ev.get('ts', 0),
                'etype': ev.get('etype', '?'),
                'source': ev.get('source', '?'),
                'description': ev.get('description', '')[:200],
                'turn_id': meta.get('turn_id', '')[:30],
            }
            if ev.get('etype') == 'tool_called':
                entry['tool_name'] = meta.get('name', '?')
                entry['ok'] = meta.get('ok', False)
                entry['error'] = meta.get('error', '')[:200]
                entry['args'] = meta.get('args', {})
                entry['reason'] = meta.get('reason', '')[:120]
            elif ev.get('etype') == 'intent_resolved':
                entry['tool_calls_count'] = len(meta.get('tool_calls', []))
                entry['tool_calls'] = meta.get('tool_calls', [])
                entry['sir_utterance'] = meta.get('sir_utterance_excerpt', '')[:200]
                entry['candidates_count'] = meta.get('candidates_count', 0)
            out.append(entry)
        # 统计
        n_ir = sum(1 for e in out if e.get('etype') == 'intent_resolved')
        n_tc = sum(1 for e in out if e.get('etype') == 'tool_called')
        n_tc_ok = sum(1 for e in out
                       if e.get('etype') == 'tool_called' and e.get('ok'))
        return jsonify({
            'ok': True,
            'events': out,
            'stats': {
                'intent_resolved_count': n_ir,
                'tool_called_count': n_tc,
                'tool_called_ok_count': n_tc_ok,
                'tool_called_fail_count': n_tc - n_tc_ok,
            },
            'hours': hours,
            'total': len(out),
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/items')
def api_items_list():
    """list actionable items, optional filter by category/state."""
    if _ai is None:
        return jsonify({'ok': False, 'error': 'actionable_items not available'}), 500
    cat = request.args.get('category', '').strip() or None
    state = request.args.get('state', '').strip() or None
    try:
        items = _ai.get_all_sir_actionable_items(
            filter_category=cat, filter_state=state)
        counts = _ai.get_category_counts()
        return jsonify({
            'ok': True,
            'items': [it.to_dict() for it in items],
            'counts': counts,
            'total': len(items),
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/items/<item_id>/<action>', methods=['POST'])
def api_items_mutate(item_id: str, action: str):
    """Sir 操作: modify / delete / restore / activate / reject / ack / feedback."""
    if _ai is None:
        return jsonify({'ok': False, 'error': 'actionable_items not available'}), 500
    if action not in ('modify', 'delete', 'restore', 'activate', 'reject', 'ack', 'feedback'):
        return jsonify({'ok': False, 'error': f'invalid action: {action}'}), 400

    if action == 'ack':
        ok = _ai.mark_sir_acked(item_id)
        return jsonify({'ok': ok, 'detail': 'sir_acked recorded'})

    # 🩹 [P5-fix-items-i18n / 2026-05-21 10:10] Sir item-level 👍/👎 反馈
    if action == 'feedback':
        payload = request.get_json(silent=True) or {}
        verdict = payload.get('verdict', '')
        sir_note = payload.get('sir_note', '')
        if verdict not in ('up', 'down', ''):
            return jsonify({'ok': False, 'error': f'invalid verdict: {verdict}'}), 400
        ok = _ai.save_item_feedback(item_id, verdict, sir_note)
        if ok:
            verdict_label = {'up': '👍 已赞', 'down': '👎 已踩', '': '↩️ 已撤销'}[verdict]
            return jsonify({'ok': True, 'detail': verdict_label})
        return jsonify({'ok': False, 'error': 'save fail'}), 500

    payload = request.get_json(silent=True) or {}
    new_fields = payload.get('new_fields')
    sir_note = payload.get('sir_note', '')
    try:
        result = _ai.mutate_actionable_item(
            item_id, action, new_fields=new_fields, sir_note=sir_note)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    return jsonify(result)


# 3-pane Actionable Items HTML page
_ITEMS_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>贾维斯 · 我们的事 (β.5.41)</title>
<script src="https://cdn.tailwindcss.com"></script>
<script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
<style>
  body { background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); min-height: 100vh; }
  .scroll-y { max-height: calc(100vh - 90px); overflow-y: auto; }
  .scroll-y::-webkit-scrollbar { width: 8px; }
  .scroll-y::-webkit-scrollbar-thumb { background: #475569; border-radius: 4px; }
  .card { transition: all .15s; }
  .card:hover { transform: translateY(-1px); box-shadow: 0 8px 20px rgba(0,0,0,0.3); }
  .toast { animation: slidein .3s ease-out; }
  @keyframes slidein { from { transform: translateX(100%); opacity: 0; } }
  .ack-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
</style>
</head>
<body class="text-slate-100" x-data="itemsApp()" x-init="loadAll()">
  <!-- 顶 bar -->
  <header class="bg-slate-900/80 backdrop-blur border-b border-slate-700 px-6 py-3 flex items-center justify-between sticky top-0 z-10">
    <div class="flex items-center gap-3">
      <h1 class="text-xl font-bold">🤖 贾维斯 · 我们的事</h1>
      <span class="text-xs text-slate-400">β.5.41/43 · <span x-text="items.length"></span> items · 共 <span x-text="totalAcked"></span> 已看</span>
    </div>
    <div class="flex items-center gap-2">
      <button @click="showReplies = !showReplies" class="px-3 py-1 bg-purple-700 hover:bg-purple-600 rounded text-sm"
              :title="'Sir 评 Jarvis recent reply (β.5.43-D)'">
        💬 评 Reply <span x-show="recentReplies.length > 0" x-text="'(' + recentReplies.length + ')'"></span>
      </button>
      <button @click="loadAll()" class="px-3 py-1 bg-slate-700 hover:bg-slate-600 rounded text-sm">🔄 刷新</button>
      <a href="/" class="px-3 py-1 bg-slate-700 hover:bg-slate-600 rounded text-sm">← 老 dashboard</a>
    </div>
  </header>

  <!-- Recent Replies 抽屉 (β.5.43-D) -->
  <div x-show="showReplies" x-transition class="fixed top-14 right-4 w-[480px] max-h-[80vh] bg-slate-900 border border-purple-700 rounded-lg shadow-2xl p-4 z-20 overflow-y-auto">
    <div class="flex justify-between items-center mb-3">
      <h3 class="font-bold text-purple-300">💬 最近 Jarvis Reply — Sir 评一下</h3>
      <button @click="showReplies = false" class="text-slate-400 hover:text-slate-100">✕</button>
    </div>
    <p class="text-xs text-slate-400 mb-3">点 👍 = 喜欢, 👎 = 不喜欢, ✏️ = 改 (主脑下次看反馈学习)</p>
    <template x-for="(rep, i) in recentReplies" :key="i">
      <div class="border border-slate-700 rounded p-2 mb-2">
        <div class="text-xs text-slate-500 mb-1" x-show="rep.user_input">
          <span class="text-green-400">Sir:</span> <span x-text="rep.user_input"></span>
        </div>
        <div class="text-sm text-slate-100 mb-2">
          <span class="text-cyan-400">Jarvis:</span> <span x-text="rep.reply"></span>
        </div>
        <div class="flex gap-1 items-center">
          <button @click="rateReply(rep, 'good')"
                  :class="rep.existing_verdict === 'good' ? 'bg-green-600' : 'bg-slate-700 hover:bg-green-700'"
                  class="px-2 py-0.5 rounded text-xs">👍</button>
          <button @click="rateReply(rep, 'bad')"
                  :class="rep.existing_verdict === 'bad' ? 'bg-red-600' : 'bg-slate-700 hover:bg-red-700'"
                  class="px-2 py-0.5 rounded text-xs">👎</button>
          <button @click="rateReply(rep, 'silent_wanted')"
                  :class="rep.existing_verdict === 'silent_wanted' ? 'bg-orange-600' : 'bg-slate-700 hover:bg-orange-700'"
                  class="px-2 py-0.5 rounded text-xs" title="这条不该说">🤐</button>
          <button @click="editReply(rep)"
                  :class="rep.existing_verdict === 'edit' ? 'bg-blue-600' : 'bg-slate-700 hover:bg-blue-700'"
                  class="px-2 py-0.5 rounded text-xs">✏️</button>
          <span x-show="rep.existing_verdict" x-text="'已评: ' + rep.existing_verdict" class="text-xs text-slate-500 ml-2"></span>
        </div>
      </div>
    </template>
    <div x-show="recentReplies.length === 0" class="text-slate-500 text-sm text-center py-8">
      暂无 reply (STM 还没积累)
    </div>
  </div>

  <!-- 3-pane -->
  <div class="flex" style="height: calc(100vh - 56px);">
    <!-- Sidebar -->
    <aside class="w-56 bg-slate-900/50 border-r border-slate-700 p-4 scroll-y">
      <div class="text-xs text-slate-400 uppercase tracking-wider mb-3">分类</div>
      <button @click="setCat('')" class="w-full text-left px-3 py-2 rounded mb-1 text-sm"
              :class="filter.cat==='' ? 'bg-blue-600 text-white' : 'hover:bg-slate-700'">
        🌍 全部 <span class="float-right text-slate-400" x-text="totalAll"></span>
      </button>
      <template x-for="cat in Object.keys(counts).sort()" :key="cat">
        <button @click="setCat(cat)" class="w-full text-left px-3 py-2 rounded mb-1 text-sm"
                :class="filter.cat===cat ? 'bg-blue-600 text-white' : 'hover:bg-slate-700'">
          <span x-text="categoryZh(cat)"></span>
          <span class="float-right text-slate-400" x-text="catTotal(cat)"></span>
        </button>
      </template>

      <div class="text-xs text-slate-400 uppercase tracking-wider mt-6 mb-3">状态</div>
      <template x-for="st in ['', 'review', 'active', 'archived']" :key="st">
        <button @click="setState(st)" class="w-full text-left px-3 py-2 rounded mb-1 text-sm"
                :class="filter.state===st ? 'bg-purple-600 text-white' : 'hover:bg-slate-700'">
          <span x-text="st==='' ? '🌍 全部状态' : stateZh(st)"></span>
        </button>
      </template>
    </aside>

    <!-- Cards stream -->
    <main class="flex-1 p-4 scroll-y">
      <div class="space-y-3">
        <template x-for="item in filteredItems" :key="item.id">
          <div class="card bg-slate-800/70 border border-slate-700 rounded-lg p-4">
            <div class="flex items-start justify-between mb-2">
              <div class="flex-1">
                <div class="flex items-center gap-2 mb-1 flex-wrap">
                  <!-- 🩹 [P5-fix-items-i18n] 中文 category 替英文 enum -->
                  <span class="text-sm font-medium text-slate-200"
                        x-text="item.category_zh || (catIcon(item.category) + ' ' + item.category)"></span>
                  <span class="text-xs px-2 py-0.5 rounded"
                        :class="stateClass(item.state)"
                        x-text="stateZh(item.state)"></span>
                  <span x-show="item.auto_proposed" class="text-xs px-2 py-0.5 rounded bg-purple-700/50 text-purple-300" title="L7 reflector 自动提议">🤖 自动提议</span>
                  <!-- 🩹 [P5-fix-items-i18n] 👍/👎 状态标识 (已评的) -->
                  <span x-show="item.sir_feedback === 'up'" class="text-xs px-2 py-0.5 rounded bg-green-700/50 text-green-300" title="你赞过这条">👍 已赞</span>
                  <span x-show="item.sir_feedback === 'down'" class="text-xs px-2 py-0.5 rounded bg-red-700/50 text-red-300" title="你踩过这条">👎 已踩</span>
                  <span :class="item.sir_acked ? 'bg-green-500' : 'bg-orange-500'" class="ack-dot ml-auto" :title="item.sir_acked ? '你已看过' : '未看'"></span>
                </div>
                <div class="text-base text-slate-100 mb-1" x-text="item.preview"></div>
                <!-- 🩹 [P5-fix-items-i18n] 人话 description (这条干啥用) -->
                <div x-show="item.description_zh" class="text-sm text-cyan-300/90 mb-2 leading-snug" x-text="'🔍 ' + item.description_zh"></div>
                <div class="text-xs text-slate-500" x-text="'id=' + item.id + ' · 提议者: ' + proposerZh(item.proposed_by)"></div>
              </div>
            </div>
            <!-- 影响 tooltip + 按钮 -->
            <div class="flex items-center gap-2 mt-3 pt-3 border-t border-slate-700/50 flex-wrap">
              <span class="text-xs text-slate-400 flex-1" x-text="'⚠️ 改影响: ' + (item.impact_if_modified || '?')"></span>
              <!-- 🩹 [P5-fix-items-i18n] 👍/👎 反馈按钮 -->
              <button @click="rateItem(item, item.sir_feedback === 'up' ? '' : 'up')"
                      :class="item.sir_feedback === 'up' ? 'bg-green-600' : 'bg-slate-700 hover:bg-green-700/70'"
                      class="px-2 py-1 rounded text-xs"
                      :title="item.sir_feedback === 'up' ? '点击撤销赞' : '👍 这条对/有用'">👍</button>
              <button @click="rateItem(item, item.sir_feedback === 'down' ? '' : 'down')"
                      :class="item.sir_feedback === 'down' ? 'bg-red-600' : 'bg-slate-700 hover:bg-red-700/70'"
                      class="px-2 py-1 rounded text-xs"
                      :title="item.sir_feedback === 'down' ? '点击撤销踩' : '👎 这条不对/没用'">👎</button>
              <button @click="openDetail(item)" class="px-3 py-1 bg-blue-600 hover:bg-blue-500 rounded text-xs">✏️ 修正</button>
              <button @click="ack(item.id)" x-show="!item.sir_acked" class="px-3 py-1 bg-slate-600 hover:bg-slate-500 rounded text-xs">👁 标已看</button>
              <button @click="del(item)" class="px-3 py-1 bg-red-700/70 hover:bg-red-600 rounded text-xs">🗑 删</button>
              <template x-if="item.state==='review'">
                <button @click="mutate(item.id, 'activate', null)" class="px-3 py-1 bg-green-700 hover:bg-green-600 rounded text-xs">✅ 激活</button>
              </template>
            </div>
          </div>
        </template>
        <div x-show="filteredItems.length === 0" class="text-center text-slate-500 py-12">
          这个分类下没有 item.
        </div>
      </div>
    </main>

    <!-- Detail panel (修正面板, 隐藏直到 click 修正) -->
    <aside class="w-96 bg-slate-900/50 border-l border-slate-700 p-4 scroll-y" x-show="detail">
      <template x-if="detail">
        <div>
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-lg font-bold">修正</h3>
            <button @click="detail=null" class="text-slate-400 hover:text-slate-100">✕</button>
          </div>
          <div class="text-xs text-slate-400 mb-1" x-text="'id: ' + detail.id"></div>
          <div class="text-xs text-slate-400 mb-3"
               x-text="'分类: ' + categoryZh(detail.category) + ' · 状态: ' + stateZh(detail.state)"></div>

          <template x-for="(value, key) in editingFields" :key="key">
            <div class="mb-3">
              <label class="text-xs text-slate-400" x-text="fieldKeyZh(key)"
                     :title="key"></label>
              <template x-if="Array.isArray(value)">
                <textarea x-model="editingFieldsStr[key]" rows="3"
                          class="w-full bg-slate-800 border border-slate-700 rounded p-2 text-sm mt-1"
                          placeholder="JSON array"></textarea>
              </template>
              <template x-if="typeof value === 'string' && value.length > 60">
                <textarea x-model="editingFields[key]" rows="3"
                          class="w-full bg-slate-800 border border-slate-700 rounded p-2 text-sm mt-1"></textarea>
              </template>
              <template x-if="typeof value === 'string' && value.length <= 60">
                <input x-model="editingFields[key]" type="text"
                       class="w-full bg-slate-800 border border-slate-700 rounded p-2 text-sm mt-1">
              </template>
              <template x-if="typeof value === 'number'">
                <input x-model.number="editingFields[key]" type="number" step="0.01"
                       class="w-full bg-slate-800 border border-slate-700 rounded p-2 text-sm mt-1">
              </template>
              <template x-if="typeof value === 'boolean'">
                <select x-model="editingFields[key]" class="w-full bg-slate-800 border border-slate-700 rounded p-2 text-sm mt-1">
                  <option :value="true">true</option>
                  <option :value="false">false</option>
                </select>
              </template>
            </div>
          </template>

          <div class="mb-3">
            <label class="text-xs text-slate-400 uppercase">备注 (Sir 你的解释)</label>
            <input x-model="editingNote" type="text" placeholder="可选, 写一句为什么"
                   class="w-full bg-slate-800 border border-slate-700 rounded p-2 text-sm mt-1">
          </div>

          <div class="bg-yellow-900/40 border border-yellow-700 rounded p-3 text-xs mb-3">
            ⚠️ <strong>影响</strong>: <span x-text="detail.impact_if_modified"></span>
          </div>

          <div class="flex gap-2">
            <button @click="saveModify()" class="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm">💾 保存修正</button>
            <button @click="detail=null" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded text-sm">取消</button>
          </div>
        </div>
      </template>
      <div x-show="!detail" class="text-slate-500 text-sm text-center py-12">
        点 ✏️ 修正 看详情<br/>所有 Sir 拍板事项实时显示 + 一键修正/删除
      </div>
    </aside>
  </div>

  <!-- Toast -->
  <div x-show="toast" class="toast fixed bottom-4 right-4 bg-green-700 px-4 py-3 rounded shadow-lg" x-text="toast"></div>

<script>
function itemsApp() { return {
  items: [],
  counts: {},
  filter: { cat: '', state: '' },
  detail: null,
  editingFields: {},
  editingFieldsStr: {},  // for array fields
  editingNote: '',
  toast: '',
  // 🩹 [β.5.43-D / 2026-05-20] Sir 评 reply 反馈通道
  showReplies: false,
  recentReplies: [],
  get totalAll() {
    let n = 0;
    for (const c in this.counts) for (const s in this.counts[c]) n += this.counts[c][s];
    return n;
  },
  get totalAcked() { return this.items.filter(i => i.sir_acked).length; },
  get filteredItems() {
    return this.items.filter(i =>
      (!this.filter.cat || i.category === this.filter.cat) &&
      (!this.filter.state || i.state === this.filter.state)
    );
  },
  catIcon(c) {
    return {concern:'🎯', inside_joke:'💭', thread:'📜', protocol:'🤝',
            unfinished:'⏱️', screen_tease:'🪞', struggle:'🆘', directive:'📡',
            sleep_pattern:'💤', behavior_inference:'⏱️', callback:'📞',
            cooldown:'⏰', profile:'👤', commitment:'📋', promise:'🤞',
            watch_task:'👁️', milestone:'🏆', memory_correction:'🔧',
            wake_filler:'🌅', refusal:'🙅', evidence:'📊', intent:'🧭'}[c] || '📌';
  },
  // 🩹 [P5-fix-items-i18n / 2026-05-22] frontend i18n maps — Sir 真测看 dashboard 全中文
  // 不靠 backend 必带 category_zh (老 extractor 没填的也能兜底).
  categoryZh(c) {
    return {
      concern:'🎯 我在关心的事', inside_joke:'💭 我们的梗',
      thread:'📜 共同经历', protocol:'🤝 默契规则',
      unfinished:'⏱️ 未完结的事', screen_tease:'🪞 屏幕调侃词',
      struggle:'🆘 Sir 困境词', directive:'📡 主脑 directive',
      sleep_pattern:'💤 Sir 睡眠习惯', behavior_inference:'⏱️ 行为推断词',
      callback:'📞 跨会话提醒', cooldown:'⏰ 冷却时段',
      profile:'👤 Sir 资料', commitment:'📋 承诺',
      promise:'🤞 Jarvis 许诺', watch_task:'👁️ 等屏幕事件',
      milestone:'🏆 重要时刻', memory_correction:'🔧 记忆修正',
      wake_filler:'🌅 唤起开场词', refusal:'🙅 拒绝表态',
      evidence:'📊 证据', intent:'🧭 意图',
    }[c] || (this.catIcon(c) + ' ' + c);
  },
  stateZh(st) {
    return {
      review:'🔥 待拍板', active:'✅ 已生效', archived:'📦 已归档',
      rejected:'❌ 已驳回', pending:'⏳ 待办', done:'✔️ 已完成',
      overdue:'🚨 逾期', expired:'⌛ 已失效', fired:'⚡ 已触发',
      cancelled:'🚫 已取消', fulfilled:'🎉 已兑现', untracked:'⚠️ 未追踪',
      paused:'⏸️ 已暂停', draft:'📝 草稿',
    }[st] || st;
  },
  stateClass(st) {
    const map = {
      review:'bg-orange-700/50 text-orange-300',
      active:'bg-green-700/50 text-green-300',
      archived:'bg-slate-700 text-slate-400',
      rejected:'bg-red-900/50 text-red-400',
      pending:'bg-amber-700/50 text-amber-300',
      done:'bg-emerald-700/50 text-emerald-300',
      overdue:'bg-rose-700/50 text-rose-300',
      expired:'bg-slate-600 text-slate-500',
      fired:'bg-purple-700/50 text-purple-300',
      cancelled:'bg-slate-700 text-slate-500',
      fulfilled:'bg-emerald-700/50 text-emerald-200',
      untracked:'bg-orange-900/40 text-orange-400',
    };
    return map[st] || 'bg-slate-700 text-slate-400';
  },
  fieldKeyZh(k) {
    return {
      priority:'优先级', severity:'严重度', urgency:'紧迫度',
      threshold:'触发阈值', cooldown:'冷却 (秒)', cooldown_s:'冷却 (秒)',
      tags:'标签', keywords:'触发关键词', triggers:'触发条件',
      state:'状态', category:'分类', subcategory:'子分类',
      note:'备注', description:'描述', preview:'预览',
      preview_zh:'预览 (中文)', rationale:'理由', rationale_zh:'理由 (中文)',
      created_at:'创建时间', updated_at:'更新时间', expires_at:'过期时间',
      fired_at:'触发时间', confirmed_at:'确认时间',
      ttl:'存活 (秒)', ttl_s:'存活 (秒)',
      sir_acked:'已看', sir_feedback:'你的反馈', auto_proposed:'自动提议',
      source:'来源', proposed_by:'提议者', target:'目标',
      progress:'进度', current:'当前值', target_value:'目标值',
      what_to_watch:'看什么', trigger_evidence:'触发证据',
      notify_msg_en:'通知 (英)', notify_msg_zh:'通知 (中)',
      sir_request:'Sir 原话', jarvis_ack:'Jarvis 回复',
      enabled:'启用', disabled:'禁用',
      helped:'有帮助计数', not_helped:'没用计数',
      fired:'命中次数', rejected:'被拒次数',
      min_severity:'最低严重度', max_active:'最大活跃数',
      vocab:'词表', value:'值', field:'字段', field_path:'字段路径',
      old_value:'旧值', new_value:'新值',
    }[k] || k;
  },
  proposerZh(p) {
    if (!p) return 'Sir 拍板';
    return {
      sir:'Sir 拍板',
      sir_request_reflector:'L7 反思器',
      directive_evaluator:'directive 评分器',
      l7_reflector:'L7 反思器',
      concerns_reflector:'concern 反思器',
      weekly_reflector:'每周反思器',
      relational_reflector:'关系反思器',
      sleep_pattern_reflector:'睡眠习惯反思器',
      intent_resolver:'意图调度器',
      watch_task_registrar:'WatchTask 提取器',
      self_promise_detector:'Jarvis 许诺侦测',
      profile_card_reflector:'Sir 资料反思器',
      gate_keeper:'Gatekeeper',
      memory_correction:'记忆修正',
      reject_learner:'反馈学习器',
    }[p] || p;
  },
  catTotal(c) {
    if (!this.counts[c]) return 0;
    return Object.values(this.counts[c]).reduce((a,b)=>a+b, 0);
  },
  setCat(c) { this.filter.cat = c; },
  setState(s) { this.filter.state = s; },
  async loadAll() {
    const r = await fetch('/api/items').then(r=>r.json());
    if (r.ok) {
      this.items = r.items;
      this.counts = r.counts;
    }
    this.fetchReplies();
  },
  async fetchReplies() {
    try {
      const r = await fetch('/api/recent_replies').then(r=>r.json());
      if (r.ok) this.recentReplies = r.replies;
    } catch (e) { /* silent */ }
  },
  async rateReply(rep, verdict) {
    const r = await fetch('/api/reply_feedback', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        reply_excerpt: rep.reply,
        verdict: verdict,
        sir_note: '',
      }),
    }).then(r=>r.json());
    if (r.ok) {
      rep.existing_verdict = verdict;
      this.showToast(`✅ ${verdict} 已记录, Jarvis 下次会看`);
    } else {
      alert('评价失败: ' + r.error);
    }
  },
  async editReply(rep) {
    const note = prompt('改成什么 / 你想 Jarvis 改成怎样?', rep.reply);
    if (!note || note === rep.reply) return;
    const r = await fetch('/api/reply_feedback', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        reply_excerpt: rep.reply,
        verdict: 'edit',
        sir_note: note,
      }),
    }).then(r=>r.json());
    if (r.ok) {
      rep.existing_verdict = 'edit';
      this.showToast('✏️ 已记录, Jarvis 下次会看你的版本');
    }
  },
  openDetail(item) {
    this.detail = item;
    this.editingFields = {};
    this.editingFieldsStr = {};
    for (const k in item.fields) {
      if (Array.isArray(item.fields[k])) {
        this.editingFields[k] = item.fields[k];
        this.editingFieldsStr[k] = JSON.stringify(item.fields[k], null, 2);
      } else {
        this.editingFields[k] = item.fields[k];
      }
    }
    this.editingNote = '';
  },
  async ack(id) {
    await fetch(`/api/items/${id}/ack`, {method:'POST'});
    const it = this.items.find(i=>i.id===id);
    if (it) it.sir_acked = true;
    this.showToast('✅ 已标已看');
  },
  // 🩹 [P5-fix-items-i18n / 2026-05-21 10:12] Sir 评 item: 👍/👎/撤销
  async rateItem(item, verdict) {
    try {
      const r = await fetch(`/api/items/${item.id}/feedback`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({verdict: verdict, sir_note: ''}),
      }).then(r=>r.json());
      if (r.ok) {
        item.sir_feedback = verdict;
        this.showToast(r.detail || '已记录');
      } else {
        this.showToast('❌ ' + (r.error || '失败'));
      }
    } catch (e) {
      this.showToast('❌ 网络错: ' + e);
    }
  },
  async del(item) {
    if (!confirm(`确定删除 "${item.preview.slice(0,60)}"?\n影响: ${item.impact_if_deleted}`)) return;
    const reason = prompt('原因 (可空)?', '');
    const r = await fetch(`/api/items/${item.id}/delete`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({sir_note: reason || ''}),
    }).then(r=>r.json());
    if (r.ok) {
      this.showToast('🗑 已删除');
      this.loadAll();
    } else {
      alert('删除失败: ' + r.error);
    }
  },
  async mutate(id, action, fields) {
    const r = await fetch(`/api/items/${id}/${action}`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({new_fields: fields}),
    }).then(r=>r.json());
    if (r.ok) {
      this.showToast(`✅ ${action} 成功`);
      this.loadAll();
    } else {
      alert(`${action} 失败: ` + r.error);
    }
  },
  async saveModify() {
    // 合并 array string fields back
    const fields = {...this.editingFields};
    for (const k in this.editingFieldsStr) {
      try { fields[k] = JSON.parse(this.editingFieldsStr[k]); }
      catch { alert(`字段 ${k} JSON 解析失败`); return; }
    }
    const r = await fetch(`/api/items/${this.detail.id}/modify`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({new_fields: fields, sir_note: this.editingNote}),
    }).then(r=>r.json());
    if (r.ok) {
      this.showToast('✅ 已保存. ' + (this.detail.impact_if_modified || ''));
      this.detail = null;
      this.loadAll();
    } else {
      alert('保存失败: ' + r.error);
    }
  },
  showToast(msg) {
    this.toast = msg;
    setTimeout(()=>{this.toast=''}, 3000);
  },
}; }
</script>
</body>
</html>
"""


@app.route('/items')
def page_items():
    """β.5.41-C 新 3-pane UI: 所有 Sir 拍板事项 + 修正/删除."""
    from flask import make_response
    resp = make_response(render_template_string(_ITEMS_HTML))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


# 🩹 [β.5.44-F / 2026-05-20 19:09] IntentResolver 可视化 page
# Sir 18:55 真理: 看每轮 Jarvis 真做了什么 mutation, 验证主脑有没有撒谎
_INTENT_RESOLVED_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8"/>
  <title>Jarvis · Intent Resolved Log</title>
  <style>
    body { font-family: -apple-system, "Segoe UI", monospace; background: #0e1116;
           color: #d1d5db; margin: 0; padding: 1rem; }
    .header { background: #161b22; padding: 1rem; border-radius: 6px;
              border: 1px solid #30363d; margin-bottom: 1rem; }
    .header h1 { margin: 0 0 0.5rem 0; color: #58a6ff; font-size: 1.3rem; }
    .header p { margin: 0; color: #8b949e; font-size: 0.9rem; }
    .stats { display: flex; gap: 1rem; margin: 1rem 0; }
    .stat-box { flex: 1; background: #161b22; padding: 0.8rem; border-radius: 6px;
                border: 1px solid #30363d; text-align: center; }
    .stat-box .num { font-size: 1.8rem; font-weight: bold; color: #58a6ff; }
    .stat-box .label { font-size: 0.85rem; color: #8b949e; margin-top: 0.3rem; }
    .stat-box.ok .num { color: #3fb950; }
    .stat-box.fail .num { color: #f85149; }
    .event-list { background: #161b22; padding: 1rem; border-radius: 6px;
                  border: 1px solid #30363d; }
    .event { padding: 0.7rem; margin-bottom: 0.6rem; border-radius: 4px;
             border-left: 3px solid #30363d; background: #0d1117; font-size: 0.9rem; }
    .event.intent_resolved { border-left-color: #58a6ff; }
    .event.tool_called.ok { border-left-color: #3fb950; }
    .event.tool_called.fail { border-left-color: #f85149; }
    .event-header { display: flex; justify-content: space-between;
                    margin-bottom: 0.3rem; font-weight: bold; }
    .event-ts { color: #8b949e; font-size: 0.85rem; font-weight: normal; }
    .event-meta { color: #8b949e; font-size: 0.83rem; margin-top: 0.3rem; }
    .event-tool-calls { margin-top: 0.5rem; padding-left: 1rem;
                        border-left: 2px solid #30363d; }
    .tool-call-line { padding: 0.2rem 0; font-size: 0.85rem; }
    .tool-call-line.ok { color: #3fb950; }
    .tool-call-line.fail { color: #f85149; }
    .empty { color: #8b949e; text-align: center; padding: 2rem; }
    .refresh-btn { background: #238636; color: white; border: none; padding: 0.5rem 1rem;
                   border-radius: 4px; cursor: pointer; font-size: 0.9rem; }
    .refresh-btn:hover { background: #2ea043; }
    .args-json { background: #0a0d13; padding: 0.4rem; border-radius: 3px;
                 color: #c9d1d9; font-size: 0.78rem; margin-top: 0.3rem;
                 word-break: break-all; }
    .hours-selector { background: #21262d; color: #c9d1d9; border: 1px solid #30363d;
                      padding: 0.4rem; border-radius: 4px; margin-right: 0.5rem; }
    a { color: #58a6ff; text-decoration: none; }
    a:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <div class="header">
    <h1>🧭 Intent Resolved Log — Sir 18:55 真理可视化</h1>
    <p>每轮 Sir 说完话, IntentResolver 集中 LLM judge → 真调 tool → 主脑下轮看 result. 
       这个页面让 Sir 看到哪轮真调了 tool, 调成功还是失败, 主脑有没有撒谎.</p>
    <p style="margin-top: 0.5rem;">
      <a href="/">← 主面板</a> | <a href="/items">items page</a>
    </p>
  </div>
  
  <div style="margin-bottom: 1rem;">
    <label>回看时长:
      <select id="hours-sel" class="hours-selector" onchange="loadEvents()">
        <option value="0.5">30 分钟</option>
        <option value="1">1 小时</option>
        <option value="2" selected>2 小时</option>
        <option value="6">6 小时</option>
        <option value="24">24 小时</option>
      </select>
    </label>
    <button class="refresh-btn" onclick="loadEvents()">🔄 刷新</button>
    <span id="status" style="margin-left: 1rem; color: #8b949e;"></span>
  </div>
  
  <div class="stats" id="stats-box">
    <div class="stat-box"><div class="num" id="n-ir">-</div><div class="label">turn 数 (intent_resolved)</div></div>
    <div class="stat-box ok"><div class="num" id="n-ok">-</div><div class="label">tool 成功</div></div>
    <div class="stat-box fail"><div class="num" id="n-fail">-</div><div class="label">tool 失败</div></div>
    <div class="stat-box"><div class="num" id="n-total">-</div><div class="label">总 events</div></div>
  </div>
  
  <div class="event-list" id="events">
    <div class="empty">loading...</div>
  </div>
  
  <script>
    function fmtTs(ts) {
      const d = new Date(ts * 1000);
      return d.toLocaleTimeString('zh-CN', {hour12: false});
    }
    function loadEvents() {
      const hours = document.getElementById('hours-sel').value;
      document.getElementById('status').textContent = 'loading...';
      fetch('/api/intent_resolved?hours=' + hours + '&limit=50')
        .then(r => r.json())
        .then(data => {
          if (!data.ok) {
            document.getElementById('events').innerHTML = 
              '<div class="empty">error: ' + (data.error || 'unknown') + '</div>';
            return;
          }
          const stats = data.stats || {};
          document.getElementById('n-ir').textContent = stats.intent_resolved_count || 0;
          document.getElementById('n-ok').textContent = stats.tool_called_ok_count || 0;
          document.getElementById('n-fail').textContent = stats.tool_called_fail_count || 0;
          document.getElementById('n-total').textContent = data.total || 0;
          const events = data.events || [];
          if (events.length === 0) {
            document.getElementById('events').innerHTML = 
              '<div class="empty">这段时间内没有 IntentResolver activity — 主脑还没被触发, 或没 mutation 需求.</div>';
          } else {
            let html = '';
            events.forEach(e => {
              const cls = e.etype === 'tool_called'
                ? (e.ok ? 'tool_called ok' : 'tool_called fail')
                : 'intent_resolved';
              const icon = e.etype === 'tool_called'
                ? (e.ok ? '✓' : '✗')
                : '🧭';
              html += '<div class="event ' + cls + '">';
              html += '<div class="event-header">';
              html += '<span>' + icon + ' ' + (e.etype) + ' — ' + (e.source) + '</span>';
              html += '<span class="event-ts">' + fmtTs(e.ts) + '</span>';
              html += '</div>';
              html += '<div>' + (e.description || '').replace(/</g, '&lt;') + '</div>';
              if (e.etype === 'tool_called') {
                html += '<div class="event-meta">tool: <b>' + (e.tool_name || '?') + '</b>';
                if (e.error) html += ' · error: ' + e.error;
                if (e.reason) html += ' · reason: ' + e.reason;
                html += '</div>';
                if (e.args && Object.keys(e.args).length > 0) {
                  html += '<div class="args-json">' + JSON.stringify(e.args) + '</div>';
                }
              } else if (e.etype === 'intent_resolved') {
                if (e.sir_utterance) {
                  html += '<div class="event-meta">Sir: "' + 
                          e.sir_utterance.replace(/</g, '&lt;') + '"</div>';
                }
                html += '<div class="event-meta">candidates=' + (e.candidates_count || 0) + 
                        ', tool_calls=' + (e.tool_calls_count || 0) + '</div>';
                if (e.tool_calls && e.tool_calls.length > 0) {
                  html += '<div class="event-tool-calls">';
                  e.tool_calls.forEach(tc => {
                    const lcls = tc.ok ? 'ok' : 'fail';
                    const licon = tc.ok ? '✓' : '✗';
                    html += '<div class="tool-call-line ' + lcls + '">' + licon + ' ' + 
                            (tc.name || '?') + (tc.error ? ' (' + tc.error + ')' : '') + '</div>';
                  });
                  html += '</div>';
                }
              }
              html += '</div>';
            });
            document.getElementById('events').innerHTML = html;
          }
          document.getElementById('status').textContent = 
            'updated ' + new Date().toLocaleTimeString('zh-CN', {hour12: false});
        })
        .catch(err => {
          document.getElementById('events').innerHTML = 
            '<div class="empty">fetch error: ' + err.message + '</div>';
        });
    }
    loadEvents();
    setInterval(loadEvents, 30000);  // 30s 自动刷新
  </script>
</body>
</html>
"""


@app.route('/intent_resolved')
def page_intent_resolved():
    """🩹 [β.5.44-F / 2026-05-20 19:09] Sir 18:55 真理可视化 page."""
    from flask import make_response
    resp = make_response(render_template_string(_INTENT_RESOLVED_HTML))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


# 🆕 [P5-Layer1-fix19-dashboard / 2026-05-22] 主脑 thinking pass 可视化 page
# Sir 14:31: "把这些信息能放都放到可视化窗口方便我看"
_MAIN_BRAIN_META_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8"/>
  <title>Jarvis · 主脑 Thinking Pass META</title>
  <style>
    body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei UI", monospace;
            background: #0e1116; color: #d1d5db; margin: 0; padding: 1rem; }
    .header { background: #161b22; padding: 1rem 1.2rem; border-radius: 8px;
              border: 1px solid #30363d; margin-bottom: 1rem; }
    .header h1 { margin: 0 0 0.4rem 0; color: #a78bfa; font-size: 1.3rem; }
    .header p { margin: 0.2rem 0; color: #8b949e; font-size: 0.9rem; line-height: 1.5; }
    .nav-links { margin-top: 0.5rem; }
    .nav-links a { color: #58a6ff; text-decoration: none; margin-right: 1rem; font-size: 0.9rem; }
    .nav-links a:hover { text-decoration: underline; }

    .controls { display: flex; gap: 0.8rem; align-items: center; margin-bottom: 1rem;
                flex-wrap: wrap; }
    .controls label { color: #8b949e; font-size: 0.88rem; }
    .controls select { background: #21262d; color: #c9d1d9;
                        border: 1px solid #30363d; padding: 0.4rem 0.6rem;
                        border-radius: 4px; font-size: 0.9rem; cursor: pointer; }
    .refresh-btn { background: #6f42c1; color: white; border: none; padding: 0.5rem 1rem;
                    border-radius: 4px; cursor: pointer; font-size: 0.9rem; font-weight: bold; }
    .refresh-btn:hover { background: #8957e5; }
    .status-text { color: #8b949e; font-size: 0.85rem; }

    .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
              gap: 0.8rem; margin: 1rem 0 1.2rem 0; }
    .stat-box { background: #161b22; padding: 0.9rem; border-radius: 6px;
                border: 1px solid #30363d; text-align: center; }
    .stat-box .num { font-size: 1.8rem; font-weight: bold; color: #a78bfa; }
    .stat-box .label { font-size: 0.83rem; color: #8b949e; margin-top: 0.3rem;
                        line-height: 1.3; }
    .stat-box.ok .num { color: #3fb950; }
    .stat-box.warn .num { color: #d29922; }
    .stat-box.crit .num { color: #f85149; }
    .stat-box.info .num { color: #58a6ff; }

    .health-banner { padding: 0.7rem 1rem; border-radius: 6px; margin-bottom: 1rem;
                      font-size: 0.92rem; line-height: 1.5; }
    .health-banner.ok { background: #1a2e22; border: 1px solid #3fb950; color: #7ee787; }
    .health-banner.warn { background: #332b00; border: 1px solid #d29922; color: #f1c969; }
    .health-banner.empty { background: #1c1d24; border: 1px solid #30363d; color: #8b949e; }

    .records { background: #161b22; padding: 1rem; border-radius: 8px;
                border: 1px solid #30363d; }
    .record { padding: 0.8rem 1rem; margin-bottom: 0.7rem; border-radius: 5px;
              border-left: 4px solid #30363d; background: #0d1117; font-size: 0.92rem; }
    .record.skip-alert { border-left-color: #d29922; }
    .record.silent { border-left-color: #8b949e; opacity: 0.8; }
    .record.evidence-none { border-left-color: #f85149; }
    .record.good { border-left-color: #3fb950; }

    .rec-head { display: flex; justify-content: space-between; align-items: center;
                margin-bottom: 0.4rem; }
    .rec-turn { font-family: monospace; color: #8b949e; font-size: 0.82rem; }
    .rec-ts { color: #6e7681; font-size: 0.82rem; }
    .rec-sir { color: #58a6ff; margin: 0.3rem 0;
                background: #0a0d13; padding: 0.4rem 0.6rem;
                border-left: 2px solid #58a6ff; border-radius: 2px; }
    .rec-sir-label { color: #6e7681; font-size: 0.78rem; margin-right: 0.4rem; }
    .rec-think { margin-top: 0.5rem; padding: 0.4rem 0.7rem;
                  background: #0a0d13; border-radius: 3px;
                  font-size: 0.86rem; }
    .rec-think-row { display: flex; gap: 0.6rem; align-items: baseline; margin: 0.2rem 0; }
    .rec-think-row .k { color: #8b949e; font-size: 0.82rem; min-width: 88px; }
    .rec-think-row .v { color: #c9d1d9; }
    .rec-think-row .v.evidence { color: #7ee787; font-family: monospace; font-size: 0.85rem; }
    .rec-think-row .v.evidence.none { color: #f85149; }
    .rec-think-row .v.voice { color: #79c0ff; }
    .rec-think-row .v.silent_text { color: #b1bac4; }
    .rec-think-row .v.silence { color: #6e7681; }
    .rec-think-row .v.skip-yes { color: #d29922; font-weight: bold; }
    .rec-think-row .v.skip-no { color: #6e7681; }
    .rec-think-row .v.note { color: #ffa657; font-style: italic; }

    .empty { color: #6e7681; text-align: center; padding: 3rem;
              font-size: 0.95rem; line-height: 1.7; }
    .empty .hint { font-size: 0.82rem; color: #484f58; margin-top: 0.4rem; }
  </style>
</head>
<body>
  <div class="header">
    <h1>🧠 主脑 Thinking Pass META — Sir 13:13 立 Layer 1</h1>
    <p>每轮 jarvis reply 时, 主脑自检 4 问 (claim/evidence/reaction/skip_alert), reply 末尾 emit <code style="color:#d29922;">[META]</code> 一行 (Sir 不见, TTS 不读). 这里让 Sir 看到 jarvis 每轮思考摘要 — "贾维斯为什么这样说".</p>
    <p style="color:#6e7681; font-size:0.83rem;">数据源: <code>memory_pool/main_brain_meta_audit.jsonl</code> · 每轮 1 行 jsonl · publish 'main_brain_meta' SWM event</p>
    <div class="nav-links">
      <a href="/">← 主面板</a>
      <a href="/items">items page</a>
      <a href="/intent_resolved">intent log</a>
    </div>
  </div>

  <div class="controls">
    <label>显示数:
      <select id="limit-sel" onchange="loadRecords()">
        <option value="20">最近 20</option>
        <option value="50" selected>最近 50</option>
        <option value="100">最近 100</option>
        <option value="200">最近 200</option>
      </select>
    </label>
    <label>skip_alert:
      <select id="skip-sel" onchange="loadRecords()">
        <option value="all" selected>全部</option>
        <option value="yes">仅拒道歉 (yes)</option>
        <option value="no">仅正常 (no)</option>
      </select>
    </label>
    <label>reaction:
      <select id="reaction-sel" onchange="loadRecords()">
        <option value="all" selected>全部</option>
        <option value="voice">仅 voice 🔊</option>
        <option value="silent_text">仅 silent_text 📝</option>
        <option value="silence">仅 silence 🤐</option>
      </select>
    </label>
    <button class="refresh-btn" onclick="loadRecords()">🔄 刷新</button>
    <span id="status" class="status-text"></span>
  </div>

  <div id="health-banner"></div>

  <div class="stats" id="stats-box">
    <div class="stat-box info"><div class="num" id="n-total">-</div>
      <div class="label">总轮数</div></div>
    <div class="stat-box ok"><div class="num" id="n-evidence">-</div>
      <div class="label">evidence 非空轮数<br/><span style="color:#3fb950;" id="n-evidence-pct">-</span></div></div>
    <div class="stat-box warn"><div class="num" id="n-skip">-</div>
      <div class="label">skip_alert=yes 轮数<br/><span style="color:#d29922;" id="n-skip-pct">-</span></div></div>
    <div class="stat-box info"><div class="num" id="avg-ev">-</div>
      <div class="label">平均 evidence/轮</div></div>
    <div class="stat-box info"><div class="num" id="n-voice">-</div>
      <div class="label">🔊 voice 轮数</div></div>
    <div class="stat-box info"><div class="num" id="n-silent">-</div>
      <div class="label">📝 silent_text 轮数</div></div>
    <div class="stat-box info"><div class="num" id="n-silence">-</div>
      <div class="label">🤐 silence 轮数</div></div>
  </div>

  <div class="records" id="records">
    <div class="empty">loading...</div>
  </div>

  <script>
    function fmtTs(ts) {
      if (!ts) return '?';
      const d = new Date(ts * 1000);
      return d.toLocaleTimeString('zh-CN', {hour12: false}) +
              ' ' + d.toLocaleDateString('zh-CN', {month: '2-digit', day: '2-digit'});
    }
    function escapeHtml(s) {
      if (!s) return '';
      return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                       .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function reactionEmoji(r) {
      return ({voice: '🔊', silent_text: '📝', silence: '🤐'})[r] || '?';
    }

    function loadRecords() {
      const limit = document.getElementById('limit-sel').value;
      const skip = document.getElementById('skip-sel').value;
      const reaction = document.getElementById('reaction-sel').value;
      document.getElementById('status').textContent = '⏳ loading...';
      const url = `/api/main_brain_meta?limit=${limit}&skip_alert=${skip}&reaction=${reaction}`;
      fetch(url)
        .then(r => r.json())
        .then(data => {
          if (!data.ok) {
            document.getElementById('records').innerHTML =
              `<div class="empty">error: ${escapeHtml(data.error || 'unknown')}</div>`;
            document.getElementById('status').textContent = '';
            return;
          }
          const s = data.stats || {};
          document.getElementById('n-total').textContent = s.total || 0;
          document.getElementById('n-evidence').textContent = s.evidence_count || 0;
          document.getElementById('n-evidence-pct').textContent = (s.evidence_pct || 0) + '%';
          document.getElementById('n-skip').textContent = s.skip_alert_count || 0;
          document.getElementById('n-skip-pct').textContent = (s.skip_alert_pct || 0) + '%';
          document.getElementById('avg-ev').textContent = (s.avg_evidence_per_turn || 0).toFixed(2);
          const reactions = s.reactions || {};
          document.getElementById('n-voice').textContent = reactions.voice || 0;
          document.getElementById('n-silent').textContent = reactions.silent_text || 0;
          document.getElementById('n-silence').textContent = reactions.silence || 0;

          // 健康度 banner
          const hb = document.getElementById('health-banner');
          if (data.health === 'empty') {
            hb.className = 'health-banner empty';
            hb.textContent = 'ℹ️ ' + (data.health_msg || '主脑还没跑过含 META 的对话');
          } else if (data.health === 'warn') {
            hb.className = 'health-banner warn';
            hb.textContent = '⚠️ ' + (data.health_msg || '');
          } else if (data.health_msg) {
            hb.className = 'health-banner ok';
            hb.textContent = '✅ ' + data.health_msg;
          } else {
            hb.className = 'health-banner';
            hb.textContent = '';
          }

          const records = data.records || [];
          if (records.length === 0) {
            document.getElementById('records').innerHTML =
              `<div class="empty">这段时间内没有匹配的 META 记录.<div class="hint">尝试: 改 filter, 或等 jarvis 多跑几轮.</div></div>`;
            document.getElementById('status').textContent =
              '✓ ' + new Date().toLocaleTimeString('zh-CN', {hour12: false});
            return;
          }

          let html = '';
          records.forEach(rec => {
            const ev = rec.evidence || [];
            const evIsNone = ev.length === 0 || (ev.length === 1 && ev[0] === 'none');
            const skipAlert = !!rec.skip_alert;
            const reaction = rec.reaction || '?';

            // 颜色分类
            let cls = 'good';
            if (skipAlert) cls = 'skip-alert';
            else if (evIsNone) cls = 'evidence-none';
            else if (reaction === 'silent_text' || reaction === 'silence') cls = 'silent';

            html += `<div class="record ${cls}">`;
            html += `<div class="rec-head">`;
            html += `<span class="rec-turn">turn=${escapeHtml(rec.turn_id || '?')}</span>`;
            html += `<span class="rec-ts">${fmtTs(rec.ts)}</span>`;
            html += `</div>`;

            if (rec.user_input_excerpt) {
              html += `<div class="rec-sir"><span class="rec-sir-label">Sir:</span>${escapeHtml(rec.user_input_excerpt)}</div>`;
            }

            html += `<div class="rec-think">`;
            // evidence
            const evClass = evIsNone ? 'evidence none' : 'evidence';
            const evDisplay = ev.length === 0 ? '(空)' : ev.join(', ');
            html += `<div class="rec-think-row"><span class="k">📚 evidence</span>`;
            html += `<span class="v ${evClass}">${escapeHtml(evDisplay)}</span></div>`;
            // reaction
            html += `<div class="rec-think-row"><span class="k">${reactionEmoji(reaction)} reaction</span>`;
            html += `<span class="v ${reaction}">${escapeHtml(reaction)}</span></div>`;
            // skip_alert
            const skipClass = skipAlert ? 'skip-yes' : 'skip-no';
            html += `<div class="rec-think-row"><span class="k">${skipAlert ? '🚫' : '✓'} skip_alert</span>`;
            html += `<span class="v ${skipClass}">${skipAlert ? 'YES (主脑拒道歉)' : 'no'}</span></div>`;
            // note
            if (rec.note) {
              html += `<div class="rec-think-row"><span class="k">💭 note</span>`;
              html += `<span class="v note">${escapeHtml(rec.note)}</span></div>`;
            }
            html += `</div>`; // rec-think
            html += `</div>`; // record
          });
          document.getElementById('records').innerHTML = html;
          document.getElementById('status').textContent =
            `✓ ${records.length}/${data.total} · ` +
            new Date().toLocaleTimeString('zh-CN', {hour12: false});
        })
        .catch(err => {
          document.getElementById('records').innerHTML =
            `<div class="empty">fetch error: ${escapeHtml(err.message)}</div>`;
          document.getElementById('status').textContent = '';
        });
    }
    loadRecords();
    setInterval(loadRecords, 15000);  // 15s 自动刷新
  </script>
</body>
</html>
"""


@app.route('/main_brain_meta')
def page_main_brain_meta():
    """🆕 [P5-Layer1-fix19-dashboard / 2026-05-22] 主脑 thinking pass META 可视化."""
    from flask import make_response
    resp = make_response(render_template_string(_MAIN_BRAIN_META_HTML))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


# ============================================================
# 🆕 [Translator Phase 4.C / 2026-05-24 23:00] /translator dashboard
# Sir 一眼看 alias vocab 健康: active/review/rejected 列表 + hit_count 排序
# + reflector stats + 一键 activate/reject (Sir 准则 7 元否决, 不自动 promote).
# 详 docs/JARVIS_TRANSLATOR_ARCHITECTURE.md §7.8
# ============================================================

@app.route('/api/translator')
def api_translator():
    """Translator vocab + reflector stats snapshot."""
    try:
        import json as _json
        import os as _os
        _here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        vocab_path = _os.path.join(_here, 'memory_pool',
                                    'translator_alias_vocab.json')
        if not _os.path.exists(vocab_path):
            return jsonify({'ok': True, 'aliases': [],
                            'stats': {}, 'note': 'no vocab file yet'})
        with open(vocab_path, 'r', encoding='utf-8') as f:
            vocab = _json.load(f)
        aliases = vocab.get('aliases', []) or []
        # 排序: review 优先 (Sir 待 review), 内部按 hit_count desc
        def _sort_key(a):
            status_rank = {'review': 0, 'active': 1, 'rejected': 2, 'archived': 3}
            return (status_rank.get(a.get('status', 'review'), 4),
                    -int(a.get('hit_count', 0) or 0))
        aliases_sorted = sorted(aliases, key=_sort_key)
        # stats
        stats = {
            'total': len(aliases),
            'active': sum(1 for a in aliases if a.get('status') == 'active'),
            'review': sum(1 for a in aliases if a.get('status') == 'review'),
            'rejected': sum(1 for a in aliases if a.get('status') == 'rejected'),
            'archived': sum(1 for a in aliases if a.get('status') == 'archived'),
            'total_hits': sum(int(a.get('hit_count', 0) or 0) for a in aliases),
        }
        # reflector stats
        try:
            from jarvis_translator_reflector import get_default_reflector
            r = get_default_reflector()
            if r is not None:
                stats['reflector'] = r.stats()
        except Exception:
            pass
        # translator runtime stats (含 hit buffer pending)
        try:
            from jarvis_translator import get_default_translator
            tr = get_default_translator()
            if tr is not None:
                stats['translator_runtime'] = tr.get_stats()
        except Exception:
            pass
        return jsonify({
            'ok': True,
            'aliases': aliases_sorted,
            'stats': stats,
            'last_modified': vocab.get('last_modified', ''),
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/translator/<alias_id>/<action>', methods=['POST'])
def api_translator_action(alias_id: str, action: str):
    """Sir 一键 activate / reject alias (调 scripts/translator_alias_dump.py).

    🆕 [Sir 2026-05-24 22:57 audit BUG #3 治本] alias_id input validation.
    必须 match `alias_\\d{1,8}` 防 path traversal / DOS 长字符串 / shell injection.
    """
    if action not in ('activate', 'reject'):
        return jsonify({'ok': False, 'error': f'invalid action: {action}',
                        'message_zh': f'非法操作: {action}'}), 400
    # 🆕 input validation: alias_id 必须形如 alias_XXX 数字 (最长 8 位防 DOS)
    import re as _re
    if not _re.fullmatch(r'alias_\d{1,8}', alias_id):
        return jsonify({
            'ok': False,
            'error': f'invalid alias_id format: {alias_id[:40]}',
            'message_zh': f'非法 alias 编号格式 (必须形如 alias_001)',
        }), 400
    try:
        import subprocess as _sp
        import sys as _sys
        import os as _os
        _here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        script = _os.path.join(_here, 'scripts', 'translator_alias_dump.py')
        if not _os.path.exists(script):
            return jsonify({'ok': False, 'error': 'CLI script not found'}), 500
        # 同步 invoke (浏览器请求会等)
        # 🆕 [Sir 2026-05-24 22:48 核对] encoding='utf-8' 防 windows GBK 解码 fail.
        # PYTHONIOENCODING env 让子进程 stdout/stderr 用 utf-8 (即使含中文也不乱).
        _env = dict(_os.environ)
        _env['PYTHONIOENCODING'] = 'utf-8'
        result = _sp.run(
            [_sys.executable, script, action, alias_id],
            capture_output=True, text=True, timeout=10,
            cwd=_here, env=_env,
            encoding='utf-8', errors='replace',
        )
        ok = result.returncode == 0
        return jsonify({
            'ok': ok,
            'stdout': (result.stdout or '')[:500],
            'stderr': (result.stderr or '')[:500],
            'action': action,
            'alias_id': alias_id,
            # 中文友好提示, 前端用
            'message_zh': (
                f'已激活 alias {alias_id}' if ok and action == 'activate'
                else f'已拒绝 alias {alias_id}' if ok and action == 'reject'
                else (result.stdout or result.stderr or '操作失败').strip()[:200]
            ),
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e),
                        'message_zh': f'调用 CLI 异常: {e}'}), 500


_TRANSLATOR_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><title>Translator Vocab — Jarvis</title>
<script src="https://unpkg.com/[email protected]/dist/cdn.min.js" defer></script>
<style>
body { font-family: -apple-system, sans-serif; background: #0d1117; color: #c9d1d9;
       margin: 0; padding: 20px; }
.header { background: #161b22; padding: 16px 24px; border-radius: 12px;
          border: 1px solid #30363d; margin-bottom: 20px; }
.header h1 { margin: 0 0 8px 0; font-size: 22px; }
.header p { margin: 4px 0; color: #8b949e; font-size: 13px; }
.nav-links a { color: #58a6ff; margin-right: 16px; text-decoration: none; }
.nav-links a:hover { text-decoration: underline; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
              gap: 12px; margin-bottom: 20px; }
.stat-card { background: #161b22; border: 1px solid #30363d; border-radius: 10px;
             padding: 14px; }
.stat-card .label { color: #8b949e; font-size: 12px; margin-bottom: 6px; }
.stat-card .value { font-size: 24px; font-weight: 600; }
.stat-card.review .value { color: #d29922; }
.stat-card.active .value { color: #3fb950; }
.stat-card.rejected .value { color: #f85149; }
.alias-table { background: #161b22; border: 1px solid #30363d; border-radius: 12px;
               overflow: hidden; }
.alias-table table { width: 100%; border-collapse: collapse; }
.alias-table th { background: #21262d; padding: 10px 14px; text-align: left;
                  font-size: 12px; color: #8b949e; font-weight: 500; }
.alias-table td { padding: 10px 14px; border-top: 1px solid #21262d; font-size: 13px; }
.status-badge { padding: 2px 8px; border-radius: 4px; font-size: 11px;
                font-weight: 500; }
.status-review { background: #5d4715; color: #d29922; }
.status-active { background: #1f3a26; color: #3fb950; }
.status-rejected { background: #4d1d22; color: #f85149; }
.status-archived { background: #21262d; color: #6e7681; }
.action-btn { padding: 4px 10px; margin-right: 6px; border-radius: 4px;
              border: 1px solid #30363d; background: #21262d; color: #c9d1d9;
              cursor: pointer; font-size: 12px; }
.action-btn:hover { background: #30363d; }
.action-btn.activate { color: #3fb950; border-color: #3fb950; }
.action-btn.reject { color: #f85149; border-color: #f85149; }
.evidence { color: #8b949e; font-size: 11px; max-width: 300px; }
.arrow { color: #58a6ff; }
.toast { position: fixed; top: 20px; right: 20px; background: #1f3a26;
         color: #3fb950; padding: 12px 20px; border-radius: 8px;
         border: 1px solid #3fb950; z-index: 1000; font-size: 13px;
         box-shadow: 0 4px 12px rgba(0,0,0,0.5); }
</style>
</head>
<body x-data="trVocab()" x-init="load()">
<div class="header">
  <h1>📚 翻译层别名总管 — alias 健康 / Sir 拍板</h1>
  <p>翻译层 (L4.6) 把主脑 emit 的不精确 organ 名修正成实际可执行的. reflector 周期 propose → Sir 一键 启用/拒绝.</p>
  <p style="color:#6e7681;font-size:0.83rem;">数据源: <code>memory_pool/translator_alias_vocab.json</code> · L7 反思 daemon 30min 一轮 · 设计文档: <code>docs/JARVIS_TRANSLATOR_ARCHITECTURE.md</code></p>
  <div class="nav-links">
    <a href="/">← 返回主面板</a>
    <a href="/main_brain_meta">🧠 主脑思考链</a>
    <a href="/intent_resolved">🎯 意图解析</a>
    <a href="javascript:void(0)" @click="load()">🔄 刷新</a>
  </div>
</div>

<div class="stats-grid">
  <div class="stat-card"><div class="label">总条目</div>
    <div class="value" x-text="stats.total || 0"></div></div>
  <div class="stat-card review"><div class="label">📋 待审核</div>
    <div class="value" x-text="stats.review || 0"></div></div>
  <div class="stat-card active"><div class="label">✅ 已启用</div>
    <div class="value" x-text="stats.active || 0"></div></div>
  <div class="stat-card rejected"><div class="label">❌ 已拒绝</div>
    <div class="value" x-text="stats.rejected || 0"></div></div>
  <div class="stat-card"><div class="label">总命中次数</div>
    <div class="value" x-text="stats.total_hits || 0"></div></div>
  <div class="stat-card"><div class="label">反思器运行轮数</div>
    <div class="value" x-text="(stats.reflector || {}).cycles_run || 0"></div></div>
</div>

<div x-show="toast" x-transition class="toast" x-text="toast"></div>

<div class="alias-table">
  <table>
    <thead><tr>
      <th>状态</th>
      <th>编号</th>
      <th>类型</th>
      <th>主脑写的</th>
      <th></th>
      <th>翻译层映射到</th>
      <th>命中次数</th>
      <th>来源证据</th>
      <th>Sir 拍板</th>
    </tr></thead>
    <tbody>
      <template x-if="!aliases || aliases.length === 0">
        <tr><td colspan="9" style="text-align:center;color:#8b949e;padding:30px;">
          (vocab 为空 — reflector 还没 propose, 或 Sir 没用过 alias)
        </td></tr>
      </template>
      <template x-for="a in aliases" :key="a.id">
        <tr>
          <td><span class="status-badge" :class="'status-' + (a.status || 'review')"
              x-text="statusZh(a.status)"></span></td>
          <td x-text="a.id"></td>
          <td x-text="kindZh(a.kind)"></td>
          <td><code x-text="a.from"></code></td>
          <td class="arrow">→</td>
          <td><code x-text="a.to"></code></td>
          <td x-text="a.hit_count || 0"></td>
          <td class="evidence" x-text="(a.evidence || '').slice(0, 120)"></td>
          <td>
            <template x-if="a.status === 'review'">
              <div>
                <button class="action-btn activate" @click="act(a.id, 'activate')">✅ 启用</button>
                <button class="action-btn reject" @click="act(a.id, 'reject')">❌ 拒绝</button>
              </div>
            </template>
            <template x-if="a.status === 'active'">
              <button class="action-btn reject" @click="act(a.id, 'reject')">❌ 撤销</button>
            </template>
            <template x-if="a.status === 'rejected'">
              <span style="color:#6e7681;font-size:11px;">已拒绝</span>
            </template>
            <template x-if="a.status === 'archived'">
              <span style="color:#6e7681;font-size:11px;">已归档</span>
            </template>
          </td>
        </tr>
      </template>
    </tbody>
  </table>
</div>

<div style="margin-top:16px;padding:12px;background:#161b22;border-radius:8px;
            border:1px solid #30363d;font-size:12px;color:#8b949e;">
  <strong style="color:#c9d1d9;">📖 字段说明:</strong>
  <ul style="margin:6px 0 0 20px;padding:0;line-height:1.6;">
    <li><strong>状态</strong> — review: reflector 提案待 Sir 拍板 · active: 已启用 · rejected: Sir 已否决 (不会再提案)</li>
    <li><strong>主脑写的 → 翻译层映射到</strong> — 主脑 emit FAST_CALL 的 organ 名 → 翻译层修正成的实际 organ 名</li>
    <li><strong>命中次数</strong> — 此 alias 被实际使用的次数 (Phase 4.A 闭环回写, 60s 落盘一次)</li>
    <li><strong>Sir 拍板</strong> — 一键操作: ✅ 启用让翻译层用此 alias; ❌ 拒绝防 reflector 重提</li>
  </ul>
</div>

<script>
const STATUS_ZH = {review:'📋 待审核', active:'✅ 已启用', rejected:'❌ 已拒绝', archived:'📦 已归档'};
const KIND_ZH = {organ:'器官名', command:'命令名'};

function trVocab() {
  return {
    aliases: [], stats: {}, toast: '',
    statusZh(s) { return STATUS_ZH[s] || s || '待审核'; },
    kindZh(k) { return KIND_ZH[k] || k || '器官名'; },
    showToast(msg, ms=2500) {
      this.toast = msg;
      setTimeout(() => this.toast = '', ms);
    },
    async load() {
      try {
        const r = await fetch('/api/translator');
        const d = await r.json();
        if (d.ok) { this.aliases = d.aliases || []; this.stats = d.stats || {}; }
        else { this.showToast('加载失败: ' + (d.error || '')); }
      } catch (e) { this.showToast('网络异常: ' + e); }
    },
    async act(id, action) {
      const verb = action === 'activate' ? '启用' : '拒绝';
      if (!confirm(`确定 ${verb} alias ${id}?`)) return;
      try {
        const r = await fetch(`/api/translator/${id}/${action}`, {method:'POST'});
        const d = await r.json();
        if (d.ok) {
          this.showToast(d.message_zh || `${verb}成功`);
          await this.load();
        } else {
          this.showToast('失败: ' + (d.message_zh || d.stderr || d.error || ''), 5000);
        }
      } catch (e) { this.showToast('网络异常: ' + e, 5000); }
    }
  };
}
</script>
</body>
</html>
"""


@app.route('/translator')
def page_translator():
    """🆕 [Translator Phase 4.C / 2026-05-24 23:00] /translator dashboard page."""
    from flask import make_response
    resp = make_response(render_template_string(_TRANSLATOR_HTML))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


# ============================================================
# 🆕 [P1 / Sir 2026-05-25 22:10 数字生命基础] /inner_thoughts dashboard
# Sir 22:52 真意: "都集成到 dashboard 直观 / 英文翻译成中文 / 带图文".
# 主脑碎碎念 (灵魂工程 Layer 1.5) — 5 类思考 + 4 actionable.
# 数据源: memory_pool/inner_thoughts.jsonl
# ============================================================

# 5 类英文 → 中文 + icon
_INNER_THOUGHT_CATEGORY_ZH = {
    'A': {'icon': '👁️', 'label': '观察', 'desc': 'Sir 当前外部状态',
            'color': '#58a6ff'},
    'B': {'icon': '🪞', 'label': '自我反思', 'desc': '看自己最近 reply',
            'color': '#a78bfa'},
    'C': {'icon': '🎯', 'label': '关怀演化', 'desc': '关怀重要度自评',
            'color': '#3fb950'},
    'D': {'icon': '🌱', 'label': '主动想法', 'desc': '下次该 silently 做什么',
            'color': '#d29922'},
    'E': {'icon': '💝', 'label': '关系维系', 'desc': 'inside joke / 心情笔记',
            'color': '#f78166'},
}

_INNER_THOUGHT_STATE_ZH = {
    'active': {'icon': '🟢', 'label': '活跃'},
    'afk_short': {'icon': '🟡', 'label': '短暂离开'},
    'afk_deep': {'icon': '🟠', 'label': '深度离开'},
    'sleep': {'icon': '🌙', 'label': '睡眠'},
    'unknown': {'icon': '⚪', 'label': '未知'},
}


def _translate_inner_actionable(action: str) -> str:
    """actionable 英文 → 中文人话."""
    if not action or action.lower() == 'none':
        return '无后续操作'
    if action.startswith('update_concern_severity:'):
        parts = action.split(':', 2)
        if len(parts) >= 3:
            return f"调整关怀「{parts[1]}」重要度 {parts[2]}"
        return '调整关怀重要度'
    if action.startswith('publish_swm:'):
        parts = action.split(':', 2)
        if len(parts) >= 3:
            return f"通知主脑事件「{parts[1]}」: {parts[2][:60]}"
        return '通知主脑事件'
    if action.startswith('suggest_inside_joke:'):
        parts = action.split(':', 1)
        if len(parts) >= 2:
            return f"提议 inside joke: 「{parts[1][:60]}」"
        return '提议 inside joke'
    return action[:80]


@app.route('/api/inner_thoughts')
def api_inner_thoughts():
    """🆕 [P1 / Sir 2026-05-25 22:52] InnerThoughtDaemon dashboard data.

    Query params:
      hours: 只看最近 N 小时 (default 24)
      limit: 最多返 N 条 (default 100)
      category: 只看某类 A/B/C/D/E (default all)
      min_salience: 只看 sal >= X (default 0.0)
      actionable_only: 1 = 只看 actionable != none

    Returns:
      {ok, total, stats: {count, avg_salience, category_breakdown,
                          actionable_done, actionable_total, current_state, current_interval},
       records: [...]}
    """
    try:
        hours = float(request.args.get('hours', 24))
        limit = int(request.args.get('limit', 100))
        category_filter = (request.args.get('category', '') or '').upper()
        min_sal = float(request.args.get('min_salience', 0.0))
        actionable_only = request.args.get('actionable_only', '0') == '1'

        persist_path = os.path.join(ROOT, 'memory_pool',
                                       'inner_thoughts.jsonl')
        if not os.path.exists(persist_path):
            return jsonify({
                'ok': True, 'total': 0, 'records': [],
                'stats': {
                    'count': 0, 'avg_salience': 0.0,
                    'category_breakdown': {c: 0 for c in 'ABCDE'},
                    'actionable_done': 0, 'actionable_total': 0,
                    'current_state': 'unknown', 'current_interval_s': 0,
                },
                'health': 'empty',
                'health_msg': "Jarvis 还没产生思考 — 启动后 30s 才有第一波. "
                              "如果一直没, 检查 daemon 是否启动 (log: '💭 [InnerThought] daemon active'). ",
            })

        cutoff = time.time() - hours * 3600.0
        all_thoughts = []
        with open(persist_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if d.get('ts', 0) >= cutoff:
                        all_thoughts.append(d)
                except (json.JSONDecodeError, ValueError):
                    continue

        # 全期 stats (filter 前)
        cat_count = {c: 0 for c in 'ABCDE'}
        sum_sal = 0.0
        action_done = 0
        action_total = 0
        for t in all_thoughts:
            cat_count[t.get('category', '?')] = \
                cat_count.get(t.get('category', '?'), 0) + 1
            sum_sal += t.get('salience', 0.0)
            if (t.get('actionable') or 'none').lower() != 'none':
                action_total += 1
                if t.get('actionable_done'):
                    action_done += 1

        # filter
        filtered = list(all_thoughts)
        if category_filter and category_filter in 'ABCDE':
            filtered = [t for t in filtered
                         if t.get('category') == category_filter]
        if min_sal > 0:
            filtered = [t for t in filtered
                         if t.get('salience', 0) >= min_sal]
        if actionable_only:
            filtered = [t for t in filtered
                         if (t.get('actionable') or 'none').lower() != 'none']

        # sort 新→旧, limit
        filtered.sort(key=lambda t: -t.get('ts', 0))
        records_out = []
        for t in filtered[:limit]:
            cat = t.get('category', '?')
            cat_meta = _INNER_THOUGHT_CATEGORY_ZH.get(
                cat, {'icon': '💭', 'label': '其它',
                       'desc': '', 'color': '#8b949e'}
            )
            sir_state = t.get('sir_state', 'unknown')
            state_meta = _INNER_THOUGHT_STATE_ZH.get(
                sir_state, _INNER_THOUGHT_STATE_ZH['unknown']
            )
            records_out.append({
                'id': t.get('id'),
                'ts': t.get('ts'),
                'ts_iso': t.get('ts_iso'),
                'category': cat,
                'category_zh': cat_meta['label'],
                'category_icon': cat_meta['icon'],
                'category_desc': cat_meta['desc'],
                'category_color': cat_meta['color'],
                'thought': t.get('thought', ''),
                'salience': t.get('salience', 0.0),
                'actionable': t.get('actionable', 'none'),
                'actionable_zh': _translate_inner_actionable(
                    t.get('actionable', 'none')
                ),
                'actionable_done': bool(t.get('actionable_done')),
                'actionable_result': t.get('actionable_result', ''),
                'sir_state': sir_state,
                'sir_state_icon': state_meta['icon'],
                'sir_state_zh': state_meta['label'],
                'tick_interval_s': t.get('tick_interval_s', 0),
                # 🆕 [Sir 2026-05-27 00:11 M1 ThoughtChain] continuity 字段透传
                'thread_id': t.get('thread_id', '') or t.get('id', ''),
                'continuity': t.get('continuity', 'new_topic'),
                # 🆕 [Sir 2026-05-27 00:11 M5 OutcomeTracker] outcome 字段透传
                'outcome': t.get('outcome', 'pending'),
                'evidence_link': (t.get('evidence_link') or '')[:80],
                'next_interval_s': t.get('next_interval_s', 0),
                'tick_origin': t.get('tick_origin', ''),
            })

        # 试拿 daemon 实时状态 (current_state / interval) — 主进程内才有
        cur_state = 'unknown'
        cur_interval = 0
        try:
            from jarvis_inner_thought_daemon import get_default_daemon
            daemon = get_default_daemon()
            if daemon is not None:
                stats = daemon.get_stats()
                cur_state = stats.get('current_sir_state', 'unknown')
                cur_interval = stats.get('current_interval_s', 0)
        except Exception:
            pass

        n = len(all_thoughts)
        avg_sal = sum_sal / n if n > 0 else 0.0

        # 健康度判断
        if n == 0:
            health = 'empty'
            health_msg = "最近 24h 没新思考. daemon 可能没启动."
        elif n < 5:
            health = 'warn'
            health_msg = (f"最近 24h 只 {n} 条思考 — daemon 可能 LLM 调用频繁失败. "
                            f"检查 jarvis 启动 log 看 '⚠️ [InnerThought]' 异常.")
        elif n > 200:
            health = 'warn'
            health_msg = (f"最近 24h {n} 条思考 — 偏多, 频率可能没正确 adaptive. "
                            f"看 'tick_interval_s' 字段是否真按 sir_state 调.")
        else:
            health = 'ok'
            health_msg = (f"最近 24h {n} 条思考, 5 类分布健康. "
                            f"actionable 完成 {action_done}/{action_total}.")

        # 🆕 [Sir 2026-05-27 00:11 M4 Dashboard] outcome 分布 (M5 OutcomeTracker)
        # 让 Sir 一眼看 Jarvis thought "真打动 Sir 还是被忽略", 反映 thought 学习信号.
        outcome_count = {
            'pending': 0,
            'sir_engaged': 0,
            'sir_silenced': 0,
            'sir_rejected': 0,
        }
        for t in all_thoughts:
            oc = t.get('outcome', 'pending')
            outcome_count[oc] = outcome_count.get(oc, 0) + 1

        # 🆕 [Sir 2026-05-27 00:11 M4 Dashboard] thread chain group
        # 让 Sir 看连续思考 "thread #X 续了 3 次, thread #Y 单次"
        thread_groups: dict = {}
        for t in all_thoughts:
            tid = t.get('thread_id', '') or t.get('id', '')
            if not tid:
                continue
            if tid not in thread_groups:
                thread_groups[tid] = {
                    'thread_id': tid,
                    'thought_ids': [],
                    'first_ts': t.get('ts', 0),
                    'last_ts': t.get('ts', 0),
                    'count': 0,
                    'category_distrib': {},
                    'first_thought_preview': (t.get('thought') or '')[:80],
                }
            tg = thread_groups[tid]
            tg['thought_ids'].append(t.get('id'))
            tg['count'] += 1
            tg['first_ts'] = min(tg['first_ts'], t.get('ts', 0))
            tg['last_ts'] = max(tg['last_ts'], t.get('ts', 0))
            ct = t.get('category', '?')
            tg['category_distrib'][ct] = tg['category_distrib'].get(ct, 0) + 1
        # 排序: 长链优先, 再按 last_ts 新 → 旧
        thread_list = sorted(
            thread_groups.values(),
            key=lambda g: (-g['count'], -g['last_ts'])
        )[:15]  # top 15 thread

        # 🆕 [Sir 2026-05-27 00:11 M4 Dashboard] time pattern @ now
        # 让 Sir 看 "12 点钟你常 lull, 现在 Jarvis 怎么反应"
        time_pattern_now = None
        try:
            from jarvis_time_awareness import get_pattern_at_now
            tp = get_pattern_at_now()
            if tp:
                time_pattern_now = tp
        except Exception:
            pass

        return jsonify({
            'ok': True,
            'total': len(filtered),
            'records': records_out,
            'stats': {
                'count': n,
                'avg_salience': round(avg_sal, 2),
                'category_breakdown': cat_count,
                'actionable_done': action_done,
                'actionable_total': action_total,
                'current_state': cur_state,
                'current_interval_s': cur_interval,
                # 🆕 M4
                'outcome_breakdown': outcome_count,
                'thread_count_total': len(thread_groups),
            },
            'thread_groups': thread_list,
            'time_pattern_now': time_pattern_now,
            'health': health,
            'health_msg': health_msg,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============================================================
# 🆕 [Sir 2026-05-27 01:00 β.5.50 LifetimeAwareness] /api/lifetime_state
# Sir 真意: dashboard 看 Jarvis 7 维生命体感快照
#   - process uptime / 今日 turn 数 / 跨 session 数
#   - 几分钟前 recent thoughts (last 15min, time-ordered)
#   - 几小时前 recent actions (last 2h)
#   - 上一 sleep ago / yesterday recap narrative
# 数据全 from daemon.get_stats() + daemon.build_lifetime_block(mode='full')
# 复用准则 6 vocab tier_mode (jarvis_lifetime_block_vocab.json).
# ============================================================
@app.route('/api/lifetime_state')
def api_lifetime_state():
    """Jarvis lifetime 7 维生命体感 snapshot for dashboard."""
    try:
        result: dict = {
            'ok': True,
            'lifetime_block_full': '',
            'lifetime_block_mini': '',
            'stats': {},
            'yesterday_recap': None,
            'vocab_tier_mode': {},
        }
        # 1. daemon snapshot
        try:
            from jarvis_inner_thought_daemon import get_default_daemon
            daemon = get_default_daemon()
            if daemon is not None:
                try:
                    result['lifetime_block_full'] = (
                        daemon.build_lifetime_block(mode='full') or ''
                    )
                except Exception as e:
                    result['lifetime_block_full'] = f"(error: {e})"
                try:
                    result['lifetime_block_mini'] = (
                        daemon.build_lifetime_block(mode='mini') or ''
                    )
                except Exception as e:
                    result['lifetime_block_mini'] = f"(error: {e})"
                try:
                    stats = daemon.get_stats() or {}
                    result['stats'] = {
                        'tick_count': stats.get('tick_count', 0),
                        'thought_count': stats.get('thought_count', 0),
                        'today_thought_count': getattr(
                            daemon, '_today_thought_count', 0
                        ),
                        'cross_session_records': len(getattr(
                            daemon, '_cross_session_index', []
                        )),
                        'current_state': stats.get(
                            'current_sir_state', 'unknown'
                        ),
                        'current_interval_s': stats.get(
                            'current_interval_s', 0
                        ),
                        'cooldown_skip_count': stats.get(
                            'cooldown_skip_count', 0
                        ),
                        'llm_fail_count': stats.get('llm_fail_count', 0),
                    }
                except Exception:
                    pass
                # vocab tier_mode (准则 6 可视化)
                try:
                    vocab = daemon._load_lifetime_vocab() or {}
                    result['vocab_tier_mode'] = vocab.get('tier_mode', {})
                except Exception:
                    pass
                # yesterday recap (last record)
                try:
                    yest = daemon._load_yesterday_recap()
                    if yest:
                        result['yesterday_recap'] = {
                            'date': yest.get('date'),
                            'narrative': yest.get('narrative'),
                            'ts_iso': yest.get('ts_iso'),
                            'thought_count': yest.get('thought_count'),
                            'action_count': yest.get('action_count'),
                        }
                except Exception:
                    pass
        except Exception as e:
            result['ok'] = False
            result['error'] = str(e)
        return jsonify(result)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


_INNER_THOUGHTS_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8"/>
  <title>Jarvis · 思考层 (Inner Thoughts)</title>
  <style>
    body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei UI", sans-serif;
            background: #0e1116; color: #d1d5db; margin: 0; padding: 1rem; }
    .header { background: #161b22; padding: 1rem 1.2rem; border-radius: 8px;
              border: 1px solid #30363d; margin-bottom: 1rem; }
    .header h1 { margin: 0 0 0.4rem 0; color: #ec4899; font-size: 1.4rem; }
    .header p { margin: 0.2rem 0; color: #8b949e; font-size: 0.9rem;
                line-height: 1.5; }
    .header .nav-links { margin-top: 0.6rem; }
    .header .nav-links a { color: #58a6ff; text-decoration: none;
                            margin-right: 1rem; font-size: 0.9rem; }
    .header .nav-links a:hover { text-decoration: underline; }

    /* 5 类色卡 */
    .legend { display: flex; gap: 0.6rem; margin-top: 0.6rem; flex-wrap: wrap;
              font-size: 0.82rem; }
    .legend-item { padding: 0.2rem 0.6rem; border-radius: 12px;
                    border: 1px solid #30363d; background: #0d1117; }

    /* controls */
    .controls { display: flex; gap: 0.8rem; align-items: center; margin-bottom: 1rem;
                flex-wrap: wrap; }
    .controls label { color: #8b949e; font-size: 0.88rem; }
    .controls select, .controls input[type=checkbox] {
      background: #21262d; color: #c9d1d9;
      border: 1px solid #30363d; padding: 0.4rem 0.6rem;
      border-radius: 4px; font-size: 0.9rem; cursor: pointer;
    }
    .refresh-btn { background: #ec4899; color: white; border: none; padding: 0.5rem 1rem;
                    border-radius: 4px; cursor: pointer; font-size: 0.9rem;
                    font-weight: bold; }
    .refresh-btn:hover { background: #f472b6; }
    .status-text { color: #8b949e; font-size: 0.85rem; }

    /* stats */
    .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
              gap: 0.8rem; margin: 1rem 0 1.2rem 0; }
    .stat-box { background: #161b22; padding: 0.9rem; border-radius: 6px;
                border: 1px solid #30363d; text-align: center; }
    .stat-box .num { font-size: 1.8rem; font-weight: bold; color: #ec4899; }
    .stat-box .label { font-size: 0.83rem; color: #8b949e; margin-top: 0.3rem;
                        line-height: 1.3; }
    .stat-box.live .num { color: #3fb950; }

    /* 5 类小柱状图 */
    .cat-bars { display: grid; grid-template-columns: repeat(5, 1fr); gap: 0.6rem;
                margin: 0.8rem 0 1.2rem 0; }
    .cat-bar { background: #161b22; padding: 0.7rem; border-radius: 6px;
                border: 1px solid #30363d; text-align: center; }
    .cat-bar .ic { font-size: 1.6rem; margin-bottom: 0.2rem; }
    .cat-bar .lbl { font-size: 0.85rem; color: #c9d1d9; font-weight: bold; }
    .cat-bar .cnt { font-size: 1.3rem; color: #ec4899; margin-top: 0.2rem;
                      font-weight: bold; }
    .cat-bar .desc { font-size: 0.72rem; color: #6e7681; margin-top: 0.2rem; }

    /* 健康 banner */
    .health-banner { padding: 0.7rem 1rem; border-radius: 6px; margin-bottom: 1rem;
                      font-size: 0.92rem; line-height: 1.5; }
    .health-banner.ok { background: #1a2e22; border: 1px solid #3fb950; color: #7ee787; }
    .health-banner.warn { background: #332b00; border: 1px solid #d29922; color: #f1c969; }
    .health-banner.empty { background: #1c1d24; border: 1px solid #30363d; color: #8b949e; }

    /* records (thoughts) */
    .records { display: grid; gap: 0.8rem; }
    .thought-card { background: #161b22; padding: 1rem 1.2rem; border-radius: 8px;
                      border: 1px solid #30363d; border-left: 4px solid #ec4899;
                      transition: border-color 0.2s; }
    .thought-card:hover { border-color: #ec4899; }

    .card-head { display: flex; justify-content: space-between; align-items: center;
                  margin-bottom: 0.6rem; flex-wrap: wrap; gap: 0.4rem; }
    .card-head-left { display: flex; align-items: center; gap: 0.6rem;
                        font-size: 0.92rem; }
    .cat-badge { padding: 0.2rem 0.7rem; border-radius: 14px; font-weight: bold;
                  font-size: 0.85rem; background: #21262d; }
    .card-head-right { color: #8b949e; font-size: 0.82rem; }

    /* 关注度星条 */
    .salience { display: inline-flex; align-items: center; gap: 0.3rem; }
    .salience .stars { color: #fbbf24; letter-spacing: 1px; }
    .salience .val { color: #8b949e; font-family: monospace; font-size: 0.85rem; }

    /* 思考正文 */
    .thought-body { font-size: 1.02rem; color: #e2e8f0; line-height: 1.55;
                      margin: 0.4rem 0; padding: 0.6rem 0.9rem;
                      background: #0d1117; border-radius: 4px;
                      border-left: 3px solid #475569; font-style: italic; }
    .thought-body::before { content: '"'; color: #6e7681; font-size: 1.5rem;
                              margin-right: 0.2rem; }
    .thought-body::after { content: '"'; color: #6e7681; font-size: 1.5rem;
                            margin-left: 0.2rem; }

    /* actionable */
    .actionable { margin-top: 0.5rem; padding: 0.5rem 0.8rem; background: #0d1117;
                    border-radius: 4px; font-size: 0.88rem; display: flex;
                    align-items: center; gap: 0.5rem; }
    .actionable.done { border-left: 3px solid #3fb950; }
    .actionable.pending { border-left: 3px solid #d29922; }
    .actionable .lbl { color: #8b949e; font-size: 0.78rem; }
    .actionable .txt { color: #c9d1d9; }
    .actionable .res { margin-left: auto; color: #6e7681; font-family: monospace;
                        font-size: 0.8rem; }

    /* Sir 状态 mini badge */
    .sir-badge { font-size: 0.78rem; color: #8b949e;
                  padding: 0.15rem 0.5rem; border-radius: 10px;
                  background: #0d1117; border: 1px solid #30363d; }

    .empty-state { color: #6e7681; text-align: center; padding: 3rem;
                    font-size: 0.95rem; line-height: 1.7;
                    background: #161b22; border-radius: 8px; border: 1px dashed #30363d; }
    .empty-state .hint { font-size: 0.82rem; color: #484f58; margin-top: 0.4rem; }

    /* current state badge top-right */
    .current-state { display: inline-block; padding: 0.3rem 0.7rem;
                      border-radius: 16px; font-size: 0.85rem;
                      background: #21262d; border: 1px solid #30363d;
                      margin-left: 0.6rem; }

    /* 🆕 [Sir 2026-05-27 12:22 真问 Phase 3] 实时 pulse 动画 + NEW badge
       Sir 真问: '我在什么方面能感受到他思考链的连续'
       让 Sir 看 dashboard 能感"思考脑活着" — 新 thought 进来视觉反馈. */
    @keyframes pulse-glow {
      0%   { box-shadow: 0 0 0 0 rgba(236, 72, 153, 0.7),
                          0 0 20px 5px rgba(236, 72, 153, 0.3); }
      70%  { box-shadow: 0 0 0 16px rgba(236, 72, 153, 0),
                          0 0 0 0 rgba(236, 72, 153, 0); }
      100% { box-shadow: 0 0 0 0 rgba(236, 72, 153, 0),
                          0 0 0 0 rgba(236, 72, 153, 0); }
    }
    .thought-card.is-fresh {
      animation: pulse-glow 2.4s ease-out 1;
      border-left-width: 6px !important;
      background: linear-gradient(135deg, #1a1f2e 0%, #161b22 100%);
    }
    .thought-card.is-fresh .fresh-badge {
      display: inline-block; background: linear-gradient(135deg, #ec4899, #a78bfa);
      color: white; padding: 0.18rem 0.55rem; border-radius: 12px;
      font-size: 0.72rem; font-weight: bold; margin-right: 0.5rem;
      letter-spacing: 0.5px; animation: badge-flash 1s ease-out;
    }
    @keyframes badge-flash {
      0%   { transform: scale(1.4); opacity: 0; }
      40%  { transform: scale(1.1); opacity: 1; }
      100% { transform: scale(1.0); opacity: 1; }
    }
    /* 顶部 pulse banner (Sir 一眼看到新进 thought) */
    #new-pulse-banner {
      position: fixed; top: 18px; right: 24px; z-index: 999;
      background: linear-gradient(135deg, #ec4899 0%, #a78bfa 100%);
      color: white; padding: 0.7rem 1.2rem; border-radius: 28px;
      font-weight: bold; font-size: 0.95rem;
      box-shadow: 0 6px 24px rgba(236, 72, 153, 0.45);
      opacity: 0; transform: translateY(-12px);
      transition: opacity 0.3s ease, transform 0.3s ease;
      pointer-events: none; user-select: none;
    }
    #new-pulse-banner.visible {
      opacity: 1; transform: translateY(0);
    }
    /* counter (n-total) 数字闪光 */
    #n-total.flash {
      animation: counter-flash 1.4s ease-out 1;
    }
    @keyframes counter-flash {
      0%   { color: #ec4899; transform: scale(1.45); text-shadow: 0 0 12px rgba(236,72,153,0.7); }
      55%  { color: #a78bfa; transform: scale(1.15); text-shadow: 0 0 6px rgba(167,139,250,0.5); }
      100% { color: inherit; transform: scale(1.0); text-shadow: none; }
    }
    /* 思考脑 heartbeat dot (永远 pulse 标识 daemon alive) */
    .heartbeat-dot {
      display: inline-block; width: 10px; height: 10px; border-radius: 50%;
      background: #ec4899; margin-right: 0.4rem; vertical-align: middle;
      animation: heartbeat 2s ease-in-out infinite;
    }
    @keyframes heartbeat {
      0%, 100% { opacity: 0.4; transform: scale(1.0); }
      50%      { opacity: 1.0; transform: scale(1.25); }
    }
  </style>
</head>
<body>
  <!-- 🆕 [Sir 2026-05-27 12:22 Phase 3] 顶部 pulse banner: 新 thought 进来弹 3s -->
  <div id="new-pulse-banner">💭 +<span id="pulse-count">0</span> 新思考</div>
  <div class="header">
    <h1><span class="heartbeat-dot" title="思考脑 alive"></span>贾维斯的思考层 <span class="current-state" id="cur-state-badge">⏳ 加载...</span></h1>
    <p>贾维斯独自一人时, 他在想什么? 后台 daemon 每 60s-30min 自适应思考一次 (按 Sir 真物理 idle 调频率), 主脑自选 5 类思考池产 1 条 inner thought, 高关注度的会进下一轮主脑 prompt — 让他记得"我刚才想过什么"形成 identity 连续性。</p>
    <p style="color:#6e7681; font-size:0.83rem;">数据源: <code>memory_pool/inner_thoughts.jsonl</code> · CLI: <code>python scripts/inner_thoughts_dump.py</code> · daemon log grep '💭 [InnerThought]'</p>
    <div class="legend">
      <span class="legend-item">👁️ A 观察 - Sir 当前状态</span>
      <span class="legend-item">🪞 B 自我反思 - 看自己 reply</span>
      <span class="legend-item">🎯 C 关怀演化 - severity 自评</span>
      <span class="legend-item">🌱 D 主动想法 - 下次该做啥</span>
      <span class="legend-item">💝 E 关系维系 - inside joke / mood</span>
    </div>
    <div class="nav-links">
      <a href="/">← 主面板</a>
      <a href="/main_brain_meta">🧠 思考链</a>
      <a href="/intent_resolved">🧭 Intent</a>
      <a href="/items">💡 我们的事</a>
    </div>
  </div>

  <div class="controls">
    <label>时间范围:
      <select id="hours-sel" onchange="loadRecords()">
        <option value="3">最近 3h</option>
        <option value="6">最近 6h</option>
        <option value="24" selected>最近 24h</option>
        <option value="72">最近 3 天</option>
      </select>
    </label>
    <label>显示数:
      <select id="limit-sel" onchange="loadRecords()">
        <option value="30">最多 30</option>
        <option value="50" selected>最多 50</option>
        <option value="100">最多 100</option>
        <option value="500">最多 500</option>
      </select>
    </label>
    <label>类型:
      <select id="cat-sel" onchange="loadRecords()">
        <option value="" selected>全部</option>
        <option value="A">👁️ A 观察</option>
        <option value="B">🪞 B 自我反思</option>
        <option value="C">🎯 C 关怀演化</option>
        <option value="D">🌱 D 主动想法</option>
        <option value="E">💝 E 关系维系</option>
      </select>
    </label>
    <label>关注度:
      <select id="sal-sel" onchange="loadRecords()">
        <option value="0" selected>全部</option>
        <option value="0.3">≥ 0.3 (中)</option>
        <option value="0.5">≥ 0.5 (高)</option>
        <option value="0.7">≥ 0.7 (主脑会看到)</option>
      </select>
    </label>
    <label>
      <input type="checkbox" id="action-only" onchange="loadRecords()"/>
      仅看真做了的
    </label>
    <button class="refresh-btn" onclick="loadRecords()">🔄 刷新</button>
    <span id="status" class="status-text"></span>
  </div>

  <div id="health-banner"></div>

  <!-- 🆕 [Sir 2026-05-27 01:00 β.5.50 LifetimeAwareness] Jarvis 7 维生命体感面板 -->
  <div id="lifetime-panel" style="background:#161b22; border:1px solid #30363d;
       border-radius:10px; padding:1rem 1.2rem; margin-bottom:1rem;">
    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:0.6rem;">
      <h3 style="margin:0; color:#f97316; font-size:1.05rem;">
        🌙 Jarvis 生命体感 <span style="color:#6e7681; font-size:0.85rem; font-weight:normal;">
          (7 维生命体感 — 主脑/思考脑同时看, 准则 6 vocab 持久化)</span>
      </h3>
      <button class="refresh-btn" onclick="loadLifetime()" style="padding:0.2rem 0.6rem; font-size:0.85rem;">🔄</button>
    </div>
    <pre id="lifetime-block" style="background:#0d1117; padding:0.8rem; border-radius:6px;
         color:#9ad1be; font-size:0.85rem; line-height:1.5; max-height:280px; overflow:auto;
         white-space:pre-wrap; word-break:break-word; margin:0;">加载中...</pre>
    <div id="lifetime-meta" style="margin-top:0.6rem; color:#8b949e; font-size:0.82rem;
         display:flex; gap:1.2rem; flex-wrap:wrap;"></div>
    <div id="yesterday-recap" style="margin-top:0.6rem; padding:0.5rem 0.7rem;
         background:#0d1117; border-left:3px solid #f97316; border-radius:4px;
         color:#d1d5db; font-size:0.85rem; display:none;"></div>
  </div>

  <div class="stats" id="stats-box">
    <div class="stat-box"><div class="num" id="n-total">-</div>
      <div class="label">最近 24h 思考数</div></div>
    <div class="stat-box"><div class="num" id="avg-sal">-</div>
      <div class="label">平均关注度</div></div>
    <div class="stat-box"><div class="num" id="n-action-done">-</div>
      <div class="label">真做了 / 总数</div></div>
    <div class="stat-box live"><div class="num" id="cur-interval">-</div>
      <div class="label">当前思考间隔</div></div>
  </div>

  <div class="cat-bars" id="cat-bars">
    <div class="cat-bar"><div class="ic">👁️</div><div class="lbl">A 观察</div>
      <div class="cnt" id="cat-A">-</div><div class="desc">Sir 状态</div></div>
    <div class="cat-bar"><div class="ic">🪞</div><div class="lbl">B 自反思</div>
      <div class="cnt" id="cat-B">-</div><div class="desc">看自己 reply</div></div>
    <div class="cat-bar"><div class="ic">🎯</div><div class="lbl">C 关怀演化</div>
      <div class="cnt" id="cat-C">-</div><div class="desc">severity 自评</div></div>
    <div class="cat-bar"><div class="ic">🌱</div><div class="lbl">D 主动想法</div>
      <div class="cnt" id="cat-D">-</div><div class="desc">下次该做啥</div></div>
    <div class="cat-bar"><div class="ic">💝</div><div class="lbl">E 关系维系</div>
      <div class="cnt" id="cat-E">-</div><div class="desc">inside joke</div></div>
  </div>

  <!-- 🆕 [Sir 2026-05-27 00:11 M4] outcome 分布 (M5 OutcomeTracker) -->
  <div class="cat-bars" id="outcome-bars" style="margin-top:0.8rem;">
    <div class="cat-bar" style="border-left-color:#6e7681">
      <div class="ic">⏳</div><div class="lbl">待观察</div>
      <div class="cnt" id="oc-pending">-</div><div class="desc">还未 Sir 反应</div></div>
    <div class="cat-bar" style="border-left-color:#3fb950">
      <div class="ic">✨</div><div class="lbl">Sir 接住</div>
      <div class="cnt" id="oc-engaged">-</div><div class="desc">10min 内 Sir 提了</div></div>
    <div class="cat-bar" style="border-left-color:#d29922">
      <div class="ic">🔇</div><div class="lbl">Sir 没接</div>
      <div class="cnt" id="oc-silenced">-</div><div class="desc">无 Sir 反应</div></div>
    <div class="cat-bar" style="border-left-color:#f85149">
      <div class="ic">❌</div><div class="lbl">Sir 拒了</div>
      <div class="cnt" id="oc-rejected">-</div><div class="desc">verbatim 否定</div></div>
  </div>

  <!-- 🆕 [Sir 2026-05-27 00:11 M4] 此刻时间感知 (M2 TimeAwareness) -->
  <div id="time-pattern-box" style="background:#161b22; padding:0.8rem 1rem; border-radius:6px; border:1px solid #30363d; margin-top:0.8rem; display:none;">
    <h3 style="margin:0 0 0.4rem 0; color:#3fb950; font-size:1rem;">🕐 此刻时间感知 (Jarvis 从历史中学的)</h3>
    <div id="time-pattern-content" style="color:#c9d1d9; font-size:0.88rem; line-height:1.6;"></div>
  </div>

  <!-- 🆕 [Sir 2026-05-27 00:11 M4] 思考链 (M1 ThoughtChain) -->
  <div id="thread-chains-box" style="background:#161b22; padding:0.8rem 1rem; border-radius:6px; border:1px solid #30363d; margin-top:0.8rem; display:none;">
    <h3 style="margin:0 0 0.4rem 0; color:#a78bfa; font-size:1rem;">🔗 思考链 (LLM 自选 continuity, 🔗 续 N 次 = 同主题串 / ✨ 独立 = 新 topic)</h3>
    <div id="thread-chains-content" style="color:#c9d1d9; font-size:0.85rem; line-height:1.7;"></div>
  </div>

  <div class="records" id="records">
    <div class="empty-state">loading...</div>
  </div>

  <script>
    function fmtTs(ts) {
      if (!ts) return '?';
      const d = new Date(ts * 1000);
      const now = new Date();
      const diffMin = Math.floor((now - d) / 60000);
      let ageStr;
      if (diffMin < 1) ageStr = '刚刚';
      else if (diffMin < 60) ageStr = diffMin + '分钟前';
      else if (diffMin < 1440) ageStr = (diffMin / 60).toFixed(1) + '小时前';
      else ageStr = (diffMin / 1440).toFixed(1) + '天前';
      const tStr = d.toLocaleTimeString('zh-CN', {hour12: false});
      return ageStr + ' · ' + tStr;
    }
    function escapeHtml(s) {
      if (!s) return '';
      return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                       .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function fmtSalience(s) {
      if (s == null) return '';
      const stars = Math.round(s * 5);
      const starStr = '★'.repeat(stars) + '☆'.repeat(5 - stars);
      return `<span class="salience"><span class="stars">${starStr}</span><span class="val">${s.toFixed(2)}</span></span>`;
    }
    function fmtInterval(s) {
      if (!s) return '-';
      if (s < 60) return s + 's';
      if (s < 3600) return Math.round(s / 60) + 'min';
      return (s / 3600).toFixed(1) + 'h';
    }

    // 🆕 [Sir 2026-05-27 12:22 真问 Phase 3] 增量 diff detection
    // ============================================================
    // Sir 真问: '我在什么方面能感受到他思考链的连续?'
    // 让 dashboard polling 不再"无声", 新 thought 进来:
    //   1. 顶部 pulse banner "💭 +N 新思考" 闪 3s
    //   2. counter n-total 数字闪光 1.4s
    //   3. 新 thought card 加 ✨ NEW badge + pulse-glow 边框 2.4s
    //   4. tab title 闪 "💭 (+N) Jarvis 思考层" 直到 Sir 切回 tab
    // 不上 SSE 复杂度, 用现有 polling 10s (短缩) + lastTopId 比对.
    // ============================================================
    let _lastTopId = null;
    let _pendingNewCount = 0;  // 累积 (Sir 没切回 tab 时)
    let _isFirstLoad = true;
    let _baseTitle = '💭 Jarvis · 思考层';

    function showPulseBanner(n) {
      const el = document.getElementById('new-pulse-banner');
      const cnt = document.getElementById('pulse-count');
      cnt.textContent = n;
      el.classList.add('visible');
      // 复位 timer (新 wave 来时 reset)
      if (window._pulseBannerTimer) clearTimeout(window._pulseBannerTimer);
      window._pulseBannerTimer = setTimeout(() => {
        el.classList.remove('visible');
      }, 3000);
    }
    function flashCounter() {
      const el = document.getElementById('n-total');
      el.classList.remove('flash');
      void el.offsetWidth;  // restart animation trick
      el.classList.add('flash');
      setTimeout(() => el.classList.remove('flash'), 1500);
    }
    function updateTitleBadge() {
      if (_pendingNewCount > 0) {
        document.title = `(+${_pendingNewCount}) ${_baseTitle}`;
      } else {
        document.title = _baseTitle;
      }
    }
    // Sir 切回 tab → 清空 pending badge
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) {
        _pendingNewCount = 0;
        updateTitleBadge();
      }
    });

    function loadRecords() {
      const hours = document.getElementById('hours-sel').value;
      const limit = document.getElementById('limit-sel').value;
      const cat = document.getElementById('cat-sel').value;
      const sal = document.getElementById('sal-sel').value;
      const actionOnly = document.getElementById('action-only').checked ? 1 : 0;
      document.getElementById('status').textContent = '⏳ loading...';
      const url = `/api/inner_thoughts?hours=${hours}&limit=${limit}` +
                   `&category=${cat}&min_salience=${sal}&actionable_only=${actionOnly}`;
      fetch(url)
        .then(r => r.json())
        .then(data => {
          if (!data.ok) {
            document.getElementById('records').innerHTML =
              `<div class="empty-state">⚠️ 错误: ${escapeHtml(data.error || 'unknown')}</div>`;
            document.getElementById('status').textContent = '';
            return;
          }
          const s = data.stats || {};
          document.getElementById('n-total').textContent = s.count || 0;
          document.getElementById('avg-sal').textContent =
            (s.avg_salience || 0).toFixed(2);
          document.getElementById('n-action-done').textContent =
            `${s.actionable_done || 0}/${s.actionable_total || 0}`;
          document.getElementById('cur-interval').textContent =
            fmtInterval(s.current_interval_s);

          // Sir 状态 badge in title
          const stateBadge = document.getElementById('cur-state-badge');
          if (s.current_state && s.current_state !== 'unknown') {
            const stateMap = {
              active: '🟢 Sir 活跃 / 60s tick',
              afk_short: '🟡 Sir 短暂离开 / 3min tick',
              afk_deep: '🟠 Sir 深度离开 / 10min tick',
              sleep: '🌙 Sir 睡眠 / 30min tick',
            };
            stateBadge.textContent = stateMap[s.current_state] || s.current_state;
          } else {
            stateBadge.textContent = '⚪ daemon 离线';
          }

          // 5 类柱状图
          const cb = s.category_breakdown || {};
          ['A','B','C','D','E'].forEach(c => {
            document.getElementById('cat-' + c).textContent = cb[c] || 0;
          });

          // 🆕 [M4] outcome 分布 (M5 OutcomeTracker)
          const ob = s.outcome_breakdown || {};
          document.getElementById('oc-pending').textContent = ob.pending || 0;
          document.getElementById('oc-engaged').textContent = ob.sir_engaged || 0;
          document.getElementById('oc-silenced').textContent = ob.sir_silenced || 0;
          document.getElementById('oc-rejected').textContent = ob.sir_rejected || 0;

          // 🆕 [M4] time pattern @ now (M2 TimeAwareness)
          // schema 来自 jarvis_time_awareness.get_pattern_at_now():
          //   hour, day, typical_activities[], typical_topics[],
          //   frequency, sample_count, fallback_used, has_data
          const tp = data.time_pattern_now;
          const tpBox = document.getElementById('time-pattern-box');
          if (tp && tp.has_data) {
            tpBox.style.display = 'block';
            const dayMap = {mon:'周一', tue:'周二', wed:'周三', thu:'周四', fri:'周五', sat:'周六', sun:'周日'};
            const dayZh = dayMap[tp.day] || tp.day;
            let tpHtml = `<div><strong>当前 ${tp.hour}:00 ${dayZh}</strong> · 历史 ${tp.sample_count} 次记录${tp.fallback_used ? ' (跨天聚合)' : ''}:</div>`;
            const traits = [];
            if (tp.typical_activities && tp.typical_activities.length) traits.push(`常做 <code style="color:#79c0ff">${tp.typical_activities.slice(0,3).join(' / ')}</code>`);
            if (tp.typical_topics && tp.typical_topics.length) traits.push(`常聊 <code style="color:#ec4899">${tp.typical_topics.slice(0,3).join(' / ')}</code>`);
            if (tp.frequency) traits.push(`频次 ${(tp.frequency * 100).toFixed(0)}%`);
            if (traits.length > 0) tpHtml += `<div style="margin-top:0.3rem;">${traits.join(' · ')}</div>`;
            document.getElementById('time-pattern-content').innerHTML = tpHtml;
          } else {
            tpBox.style.display = 'none';
          }

          // 🆕 [M4] thread chains (M1 ThoughtChain)
          // 🆕 [Sir 2026-05-27 00:43 真问"思考链可视化在哪"] 老 condition count>=2 太严,
          // Sir 没续链 thought 时 panel 永远 hidden. 改成: 有 thread_groups (>=1) 就显,
          // 续链 count>=2 标 🔗 续, 单条 thread 标 ✨ 独. Sir 能看到 LLM 真选的 continuity.
          const allThreads = data.thread_groups || [];
          const tcBox = document.getElementById('thread-chains-box');
          if (allThreads.length > 0) {
            tcBox.style.display = 'block';
            // sort: 续链 (count>=2) 优先, count desc
            const threads = allThreads.slice().sort((a, b) => b.count - a.count);
            let tcHtml = '';
            threads.slice(0, 15).forEach(t => {
              const catSummary = Object.entries(t.category_distrib || {})
                .sort((a,b) => b[1] - a[1])
                .map(([c, n]) => `${c}×${n}`)
                .join(' ');
              // 🆕 [Sir 2026-05-27 00:43] 续链 vs 独立 thread 区分标签
              const isContinued = t.count >= 2;
              const borderColor = isContinued ? '#a78bfa' : '#79c0ff';
              const badge = isContinued
                ? `<span style="color:#a78bfa; font-weight:bold;">🔗 续 ${t.count} 次</span>`
                : `<span style="color:#79c0ff; font-weight:bold;">✨ 独立 thread</span>`;
              tcHtml += `<div style="margin-bottom:0.4rem; padding:0.3rem 0.5rem; background:#0d1117; border-radius:4px; border-left:3px solid ${borderColor};">`;
              tcHtml += `<div style="display:flex; gap:0.5rem; align-items:center; flex-wrap:wrap;">`;
              tcHtml += badge;
              tcHtml += `<span style="color:#6e7681; font-size:0.78rem;">${catSummary}</span>`;
              tcHtml += `<span style="color:#6e7681; font-size:0.78rem;">${fmtTs(t.first_ts)} → ${fmtTs(t.last_ts)}</span>`;
              tcHtml += `</div>`;
              tcHtml += `<div style="margin-top:0.2rem; color:#c9d1d9; font-style:italic;">"${escapeHtml(t.first_thought_preview)}"</div>`;
              tcHtml += `</div>`;
            });
            document.getElementById('thread-chains-content').innerHTML = tcHtml;
          } else {
            tcBox.style.display = 'none';
          }

          // 健康 banner
          const hb = document.getElementById('health-banner');
          const healthClass = {empty: 'empty', warn: 'warn',
                                 ok: 'ok'}[data.health] || '';
          if (data.health === 'empty') {
            hb.className = 'health-banner empty';
            hb.textContent = 'ℹ️ ' + (data.health_msg || '');
          } else if (data.health === 'warn') {
            hb.className = 'health-banner warn';
            hb.textContent = '⚠️ ' + (data.health_msg || '');
          } else if (data.health_msg) {
            hb.className = 'health-banner ok';
            hb.textContent = '✅ ' + data.health_msg;
          } else {
            hb.className = 'health-banner';
            hb.textContent = '';
          }

          // records
          const records = data.records || [];
          if (records.length === 0) {
            document.getElementById('records').innerHTML =
              `<div class="empty-state">这个 filter 下还没有思考<div class="hint">尝试: 换 filter, 或等 daemon 多产几条 (60s 一波最快).</div></div>`;
            document.getElementById('status').textContent =
              '✓ ' + new Date().toLocaleTimeString('zh-CN', {hour12: false});
            return;
          }

          // 🆕 [Sir 2026-05-27 12:22 Phase 3] diff detect 新 thought
          // records[0] 是最新 thought (api desc sort by ts). 比对 _lastTopId.
          const freshIds = new Set();
          const topId = records[0].id;
          if (!_isFirstLoad && _lastTopId && topId !== _lastTopId) {
            // 找新 thought (从 records[0] 往下扫直到遇 _lastTopId 或扫完)
            for (const r of records) {
              if (r.id === _lastTopId) break;
              freshIds.add(r.id);
            }
            const nNew = freshIds.size;
            if (nNew > 0) {
              showPulseBanner(nNew);
              flashCounter();
              if (document.hidden) {
                _pendingNewCount += nNew;
                updateTitleBadge();
              }
            }
          }
          _lastTopId = topId;
          _isFirstLoad = false;

          let html = '';
          records.forEach(t => {
            const catColor = t.category_color || '#ec4899';
            const actionDone = t.actionable_done;
            const actionStr = t.actionable_zh || t.actionable;
            const hasAction = (t.actionable || 'none').toLowerCase() !== 'none';
            const isFresh = freshIds.has(t.id);

            html += `<div class="thought-card${isFresh ? ' is-fresh' : ''}" style="border-left-color:${catColor}">`;
            html += `<div class="card-head">`;
            html += `<div class="card-head-left">`;
            if (isFresh) html += `<span class="fresh-badge">✨ NEW</span>`;
            html += `<span class="cat-badge" style="color:${catColor}">`;
            html += `${t.category_icon} ${t.category} ${t.category_zh}`;
            html += `</span>`;
            html += `<span style="color:#6e7681; font-size:0.8rem;">${escapeHtml(t.category_desc)}</span>`;
            html += `</div>`;
            html += `<div class="card-head-right">`;
            html += fmtSalience(t.salience);
            html += `</div>`;
            html += `</div>`;  // card-head

            // 思考正文
            html += `<div class="thought-body">${escapeHtml(t.thought)}</div>`;

            // actionable
            if (hasAction) {
              html += `<div class="actionable ${actionDone ? 'done' : 'pending'}">`;
              html += `<span>${actionDone ? '✅' : '⏳'}</span>`;
              html += `<span class="lbl">真做了:</span>`;
              html += `<span class="txt">${escapeHtml(actionStr)}</span>`;
              if (t.actionable_result && t.actionable_result !== 'pending') {
                html += `<span class="res">→ ${escapeHtml(t.actionable_result)}</span>`;
              }
              html += `</div>`;
            }

            // meta footer (sir state + tick + 🆕 M1 thread + 🆕 M5 outcome)
            html += `<div style="margin-top:0.5rem; display:flex; gap:0.5rem; align-items:center; flex-wrap:wrap; font-size:0.78rem; color:#6e7681;">`;
            html += `<span class="sir-badge">${t.sir_state_icon} ${t.sir_state_zh}</span>`;
            html += `<span>·</span><span>tick ${t.tick_interval_s}s</span>`;
            // 🆕 [M1] continuity badge
            if (t.continuity === 'same_thread') {
              html += `<span>·</span><span style="color:#a78bfa;">🔗 续</span>`;
            } else if (t.continuity === 'new_topic') {
              html += `<span>·</span><span style="color:#79c0ff;">✨ 新</span>`;
            }
            // 🆕 [M5] outcome badge
            const ocMap = {
              'pending':      {icon: '⏳', label: '待观察', color: '#6e7681'},
              'sir_engaged':  {icon: '✨', label: 'Sir 接住', color: '#3fb950'},
              'sir_silenced': {icon: '🔇', label: 'Sir 没接', color: '#d29922'},
              'sir_rejected': {icon: '❌', label: 'Sir 拒了', color: '#f85149'},
            };
            const oc = ocMap[t.outcome] || ocMap.pending;
            html += `<span>·</span><span style="color:${oc.color};">${oc.icon} ${oc.label}</span>`;
            html += `<span>·</span><span>${fmtTs(t.ts)}</span>`;
            html += `</div>`;

            html += `</div>`;  // thought-card
          });
          document.getElementById('records').innerHTML = html;
          document.getElementById('status').textContent =
            `✓ ${records.length}/${data.total} · ` +
            new Date().toLocaleTimeString('zh-CN', {hour12: false});
        })
        .catch(err => {
          document.getElementById('records').innerHTML =
            `<div class="empty-state">⚠️ fetch 错: ${escapeHtml(err.message)}</div>`;
          document.getElementById('status').textContent = '';
        });
    }
    // 🆕 [Sir 2026-05-27 01:00 β.5.50 LifetimeAwareness] Jarvis 生命体感面板加载
    function loadLifetime() {
      fetch('/api/lifetime_state')
        .then(r => r.json())
        .then(data => {
          if (!data.ok) {
            document.getElementById('lifetime-block').textContent =
              '(error: ' + (data.error || 'unknown') + ')';
            return;
          }
          const block = data.lifetime_block_full || '(no data — daemon not running?)';
          document.getElementById('lifetime-block').textContent = block;
          const st = data.stats || {};
          const meta = [];
          if (st.tick_count !== undefined) meta.push('🫀 tick=' + st.tick_count);
          if (st.thought_count !== undefined) meta.push('💭 thoughts=' + st.thought_count);
          if (st.today_thought_count !== undefined) meta.push('📅 today=' + st.today_thought_count);
          if (st.cross_session_records !== undefined) meta.push('🔄 sessions=' + st.cross_session_records);
          if (st.current_state) meta.push('🎯 state=' + st.current_state);
          if (st.current_interval_s) meta.push('⏱ next=' + st.current_interval_s + 's');
          if (st.cooldown_skip_count !== undefined) meta.push('⏸ skip=' + st.cooldown_skip_count);
          if (st.llm_fail_count !== undefined) meta.push('⚠️ fail=' + st.llm_fail_count);
          document.getElementById('lifetime-meta').innerHTML =
            meta.map(m => '<span>' + m + '</span>').join('');
          // yesterday recap
          const yr = data.yesterday_recap;
          const yrEl = document.getElementById('yesterday-recap');
          if (yr && yr.narrative) {
            yrEl.style.display = 'block';
            yrEl.innerHTML = '<strong style="color:#f97316;">📜 昨日回忆 (' +
              (yr.date || '?') + ')</strong>: ' + yr.narrative +
              ' <span style="color:#6e7681;">(' +
              (yr.thought_count || 0) + ' thoughts, ' +
              (yr.action_count || 0) + ' actions)</span>';
          } else {
            yrEl.style.display = 'none';
          }
        })
        .catch(e => {
          document.getElementById('lifetime-block').textContent =
            '(fetch error: ' + e.message + ')';
        });
    }

    loadRecords();
    loadLifetime();
    // 🆕 [Sir 2026-05-27 12:22 Phase 3] 缩短 polling 30s→10s 让 Sir 感"实时"
    // (新 thought 进来 10s 内必触发 pulse + badge animation)
    setInterval(loadRecords, 10000);  // 10s 自动刷新 (Phase 3 缩短)
    setInterval(loadLifetime, 60000);  // 60s 刷生命体感
  </script>
</body>
</html>
"""


@app.route('/inner_thoughts')
def page_inner_thoughts():
    """🆕 [P1 / Sir 2026-05-25 22:52] /inner_thoughts dashboard page."""
    from flask import make_response
    resp = make_response(render_template_string(_INNER_THOUGHTS_HTML))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


# ============================================================
# 🆕 [AA / Sir 2026-05-25 22:58 自决] /auto_arbiter dashboard
# Sir 真意: 让贾维斯自己拍板 review queue + Sir 一键撤销 + 每日反思迭代准确性.
# 数据源: memory_pool/auto_arbiter_log.jsonl + auto_arbiter_calibration.json
# ============================================================

_AA_KIND_ZH = {
    'inside_joke': {'icon': '🃏', 'label': '内梗', 'color': '#ec4899'},
    'thread':      {'icon': '🧵', 'label': '历史线', 'color': '#a78bfa'},
    'concern':     {'icon': '🎯', 'label': '关怀', 'color': '#3fb950'},
    'directive':   {'icon': '📜', 'label': '指令', 'color': '#d29922'},
}

_AA_DECISION_ZH = {
    'activate':     {'icon': '✅', 'label': '通过', 'color': '#3fb950'},
    'reject':       {'icon': '❌', 'label': '拒绝', 'color': '#f85149'},
    'defer_to_sir': {'icon': '🙋', 'label': '建议 Sir 看', 'color': '#d29922'},
    'noop':         {'icon': '➖', 'label': '不动', 'color': '#6e7681'},
}

_AA_RISK_ZH = {
    'low':    {'icon': '🟢', 'label': '低风险'},
    'medium': {'icon': '🟡', 'label': '中风险'},
    'high':   {'icon': '🔴', 'label': '高风险'},
}


@app.route('/api/auto_arbiter')
def api_auto_arbiter():
    """🆕 [AA / Sir 22:58] AutoArbiter dashboard data.

    Query params:
      hours: 24/72/168 (default 24)
      limit: max records (default 50)
      kind: filter by kind (default all)
      decision: filter (activate/reject/defer_to_sir/noop, default all)
      reverted_only: 1 to show only Sir-reverted (default 0)
    """
    try:
        hours = float(request.args.get('hours', 24))
        limit = int(request.args.get('limit', 50))
        kind_filter = (request.args.get('kind', '') or '').strip()
        dec_filter = (request.args.get('decision', '') or '').strip()
        reverted_only = request.args.get('reverted_only', '0') == '1'

        persist_path = os.path.join(ROOT, 'memory_pool',
                                       'auto_arbiter_log.jsonl')
        cal_path = os.path.join(ROOT, 'memory_pool',
                                  'auto_arbiter_calibration.json')

        if not os.path.exists(persist_path):
            return jsonify({
                'ok': True, 'total': 0, 'records': [],
                'stats': {
                    'decisions_24h': 0, 'per_kind': {},
                    'thresholds': {}, 'current_state': 'idle',
                },
                'health': 'empty',
                'health_msg': ("贾维斯还没自决 — daemon 启动 60s 后第一波 tick. "
                                 "如果 review queue 是空的, 也不会产生 decision. "
                                 "等 reflector 提案累积后再看."),
            })

        cutoff = time.time() - hours * 3600.0
        latest_by_id = {}
        with open(persist_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get('ts', 0) < cutoff:
                        continue
                    latest_by_id[rec.get('id')] = rec
                except (json.JSONDecodeError, ValueError):
                    continue

        all_recent = list(latest_by_id.values())

        # 全期 stats
        per_kind = {}
        decisions_count = 0
        reverted_count = 0
        defer_count = 0
        for r in all_recent:
            k = r.get('kind', '?')
            dec = r.get('decision', '?')
            if k not in per_kind:
                per_kind[k] = {'total': 0, 'activate': 0, 'reject': 0,
                                 'defer_to_sir': 0, 'noop': 0, 'reverted': 0}
            per_kind[k]['total'] += 1
            per_kind[k][dec] = per_kind[k].get(dec, 0) + 1
            if dec in ('activate', 'reject'):
                decisions_count += 1
            if r.get('sir_reverted'):
                reverted_count += 1
                per_kind[k]['reverted'] += 1
            if dec == 'defer_to_sir':
                defer_count += 1

        # filter
        filtered = list(all_recent)
        if kind_filter:
            filtered = [r for r in filtered if r.get('kind') == kind_filter]
        if dec_filter:
            filtered = [r for r in filtered
                         if r.get('decision') == dec_filter]
        if reverted_only:
            filtered = [r for r in filtered if r.get('sir_reverted')]

        # sort 新→旧, limit
        filtered.sort(key=lambda r: -r.get('ts', 0))
        records_out = []
        for r in filtered[:limit]:
            k = r.get('kind', '?')
            dec = r.get('decision', '?')
            risk = r.get('risk_level', 'low')
            k_meta = _AA_KIND_ZH.get(k, {'icon': '?', 'label': k,
                                            'color': '#8b949e'})
            d_meta = _AA_DECISION_ZH.get(dec, {'icon': '?', 'label': dec,
                                                  'color': '#8b949e'})
            r_meta = _AA_RISK_ZH.get(risk, {'icon': '⚪', 'label': risk})
            records_out.append({
                'id': r.get('id'),
                'ts': r.get('ts'),
                'ts_iso': r.get('ts_iso'),
                'kind': k,
                'kind_zh': k_meta['label'],
                'kind_icon': k_meta['icon'],
                'kind_color': k_meta['color'],
                'item_id': r.get('item_id'),
                'item_preview': r.get('item_preview', ''),
                'risk_level': risk,
                'risk_zh': r_meta['label'],
                'risk_icon': r_meta['icon'],
                'decision': dec,
                'decision_zh': d_meta['label'],
                'decision_icon': d_meta['icon'],
                'decision_color': d_meta['color'],
                'confidence': r.get('confidence', 0.0),
                'threshold': r.get('threshold_at_decision', 0.0),
                'reason': r.get('reason', ''),
                'executed_ok': r.get('executed_ok'),
                'execution_msg': r.get('execution_msg', ''),
                'sir_reverted': r.get('sir_reverted'),
                'sir_reverted_at': r.get('sir_reverted_at'),
                'sir_revert_reason': r.get('sir_revert_reason', ''),
            })

        # 拿 calibration
        cal = {}
        if os.path.exists(cal_path):
            try:
                with open(cal_path, 'r', encoding='utf-8') as f:
                    cal = json.load(f) or {}
            except Exception:
                pass
        thresholds = (cal.get('thresholds') or {})

        # 试拿实时 daemon stats
        live_stats = {}
        try:
            from jarvis_auto_arbiter import get_default_daemon
            daemon = get_default_daemon()
            if daemon is not None:
                live_stats = daemon.get_stats()
        except Exception:
            pass

        # 健康度
        n = len(all_recent)
        if n == 0:
            health = 'empty'
            health_msg = f"最近 {int(hours)}h 没自决记录. daemon 启动 60s 后才 fire."
        else:
            revert_rate = reverted_count / max(1, decisions_count)
            if revert_rate > 0.30:
                health = 'warn'
                health_msg = (f"最近 {int(hours)}h Sir 撤销率 {revert_rate:.0%} > 30% "
                                f"— 贾维斯过于激进, 03:xx daily reflection 会自动升高阈值.")
            else:
                health = 'ok'
                health_msg = (f"最近 {int(hours)}h 自决 {decisions_count} 条 "
                                f"(通过/拒), 建议 Sir 看 {defer_count} 条, "
                                f"Sir 撤销 {reverted_count} 条 ({revert_rate:.0%}).")

        return jsonify({
            'ok': True,
            'total': len(filtered),
            'records': records_out,
            'stats': {
                'decisions_24h': decisions_count,
                'reverted_count': reverted_count,
                'defer_count': defer_count,
                'per_kind': per_kind,
                'thresholds': thresholds,
                'last_calibrated_iso': cal.get('last_calibrated_iso', ''),
                'live_tick_count': live_stats.get('tick_count', 0),
                'live_llm_call_count': live_stats.get('llm_call_count', 0),
            },
            'health': health,
            'health_msg': health_msg,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/auto_arbiter/revert', methods=['POST'])
def api_auto_arbiter_revert():
    """🆕 [AA / Sir 22:58] Sir 一键撤销一条 auto_arbiter decision.

    POST body: {"decision_id": "aa_...", "reason": "Sir 不喜欢这个 joke"}
    """
    payload = request.get_json(silent=True) or {}
    decision_id = (payload.get('decision_id') or '').strip()
    reason = (payload.get('reason') or '').strip()
    if not decision_id:
        return jsonify({'ok': False, 'error': 'decision_id required'}), 400
    try:
        from jarvis_auto_arbiter import get_default_daemon
        daemon = get_default_daemon()
        if daemon is None:
            return jsonify({
                'ok': False,
                'error': 'AutoArbiterDaemon not active (主进程未启动 或 init fail). '
                          '看 Jarvis 启动 log 是否有 [AutoArbiter] daemon active.',
            }), 503
        ok, msg = daemon.sir_revert(decision_id, reason)
        return jsonify({'ok': ok, 'detail': msg})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


_AUTO_ARBITER_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8"/>
  <title>Jarvis · 自决 (AutoArbiter)</title>
  <style>
    body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei UI", sans-serif;
            background: #0e1116; color: #d1d5db; margin: 0; padding: 1rem; }
    .header { background: #161b22; padding: 1rem 1.2rem; border-radius: 8px;
              border: 1px solid #30363d; margin-bottom: 1rem; }
    .header h1 { margin: 0 0 0.4rem 0; color: #10b981; font-size: 1.4rem; }
    .header p { margin: 0.2rem 0; color: #8b949e; font-size: 0.9rem;
                line-height: 1.5; }
    .header .nav-links { margin-top: 0.6rem; }
    .header .nav-links a { color: #58a6ff; text-decoration: none;
                            margin-right: 1rem; font-size: 0.9rem; }
    .header .nav-links a:hover { text-decoration: underline; }
    .legend { display: flex; gap: 0.6rem; margin-top: 0.6rem; flex-wrap: wrap;
              font-size: 0.82rem; }
    .legend-item { padding: 0.2rem 0.6rem; border-radius: 12px;
                    border: 1px solid #30363d; background: #0d1117; }

    .controls { display: flex; gap: 0.8rem; align-items: center; margin-bottom: 1rem;
                flex-wrap: wrap; }
    .controls label { color: #8b949e; font-size: 0.88rem; }
    .controls select, .controls input[type=checkbox] {
      background: #21262d; color: #c9d1d9;
      border: 1px solid #30363d; padding: 0.4rem 0.6rem;
      border-radius: 4px; font-size: 0.9rem; cursor: pointer;
    }
    .refresh-btn { background: #10b981; color: white; border: none; padding: 0.5rem 1rem;
                    border-radius: 4px; cursor: pointer; font-size: 0.9rem;
                    font-weight: bold; }
    .refresh-btn:hover { background: #34d399; }
    .status-text { color: #8b949e; font-size: 0.85rem; }

    .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
              gap: 0.8rem; margin: 1rem 0 1.2rem 0; }
    .stat-box { background: #161b22; padding: 0.9rem; border-radius: 6px;
                border: 1px solid #30363d; text-align: center; }
    .stat-box .num { font-size: 1.8rem; font-weight: bold; color: #10b981; }
    .stat-box .label { font-size: 0.83rem; color: #8b949e; margin-top: 0.3rem;
                        line-height: 1.3; }
    .stat-box.ok .num { color: #3fb950; }
    .stat-box.warn .num { color: #d29922; }
    .stat-box.crit .num { color: #f85149; }

    .thresholds { background: #161b22; padding: 0.9rem 1rem; border-radius: 6px;
                    border: 1px solid #30363d; margin-bottom: 1rem; }
    .thresholds h3 { margin: 0 0 0.5rem 0; color: #10b981; font-size: 1rem; }
    .thresholds .row { display: flex; gap: 0.6rem; flex-wrap: wrap;
                        font-size: 0.88rem; }
    .thresholds .item { padding: 0.3rem 0.7rem; border-radius: 12px;
                          background: #0d1117; border: 1px solid #30363d; }
    .thresholds .item .v { color: #10b981; font-weight: bold; margin-left: 0.4rem; }
    .thresholds .note { color: #6e7681; font-size: 0.78rem; margin-top: 0.4rem; }

    .health-banner { padding: 0.7rem 1rem; border-radius: 6px; margin-bottom: 1rem;
                      font-size: 0.92rem; line-height: 1.5; }
    .health-banner.ok { background: #1a2e22; border: 1px solid #3fb950; color: #7ee787; }
    .health-banner.warn { background: #332b00; border: 1px solid #d29922; color: #f1c969; }
    .health-banner.empty { background: #1c1d24; border: 1px solid #30363d; color: #8b949e; }

    .records { display: grid; gap: 0.8rem; }
    .decision-card { background: #161b22; padding: 1rem 1.2rem; border-radius: 8px;
                      border: 1px solid #30363d; border-left: 4px solid #10b981;
                      transition: border-color 0.2s; }
    .decision-card.reverted { opacity: 0.65; border-left-color: #f85149; }
    .decision-card.executed-fail { border-left-color: #d29922; }

    .card-head { display: flex; justify-content: space-between; align-items: flex-start;
                  margin-bottom: 0.5rem; flex-wrap: wrap; gap: 0.4rem; }
    .card-head-left { display: flex; align-items: center; gap: 0.6rem;
                        flex-wrap: wrap; }
    .kind-badge { padding: 0.2rem 0.7rem; border-radius: 14px; font-weight: bold;
                  font-size: 0.85rem; background: #21262d; }
    .decision-badge { padding: 0.2rem 0.7rem; border-radius: 14px; font-weight: bold;
                       font-size: 0.85rem; }
    .risk-badge { padding: 0.15rem 0.5rem; border-radius: 10px; font-size: 0.78rem;
                   background: #0d1117; border: 1px solid #30363d; }

    .conf-bar { display: inline-flex; align-items: center; gap: 0.3rem;
                  font-size: 0.85rem; }
    .conf-bar .bar { width: 60px; height: 6px; background: #30363d; border-radius: 3px;
                      overflow: hidden; display: inline-block; }
    .conf-bar .bar-fill { height: 100%; background: #10b981; }
    .conf-bar .val { color: #8b949e; font-family: monospace; }
    .conf-bar .thr { color: #6e7681; font-size: 0.75rem; }

    .item-preview { font-size: 0.98rem; color: #e2e8f0; margin: 0.3rem 0 0.5rem 0;
                      padding: 0.5rem 0.8rem; background: #0d1117; border-radius: 4px;
                      border-left: 3px solid #475569; font-style: italic; }
    .reason-line { font-size: 0.85rem; color: #79c0ff; margin-bottom: 0.4rem;
                     padding-left: 0.5rem; border-left: 2px solid #58a6ff; }

    .exec-row { margin-top: 0.4rem; font-size: 0.82rem; color: #6e7681;
                  display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
    .exec-row .ok { color: #3fb950; }
    .exec-row .fail { color: #f85149; }
    .exec-row .defer { color: #d29922; }

    .revert-row { margin-top: 0.6rem; padding: 0.5rem 0.7rem; background: #0d1117;
                    border-radius: 4px; border-left: 3px solid #f85149;
                    font-size: 0.85rem; }
    .revert-row .lbl { color: #f85149; font-weight: bold; }

    .revert-btn { padding: 0.3rem 0.8rem; border-radius: 4px;
                    background: #4b1d1d; color: #f85149; border: 1px solid #6e2c2c;
                    cursor: pointer; font-size: 0.82rem; transition: background 0.2s; }
    .revert-btn:hover { background: #6e2c2c; }
    .revert-btn:disabled { opacity: 0.4; cursor: not-allowed; }

    .empty-state { color: #6e7681; text-align: center; padding: 3rem;
                    font-size: 0.95rem; line-height: 1.7;
                    background: #161b22; border-radius: 8px; border: 1px dashed #30363d; }
    .empty-state .hint { font-size: 0.82rem; color: #484f58; margin-top: 0.4rem; }
  </style>
</head>
<body>
  <div class="header">
    <h1>🤖 贾维斯自决 (AutoArbiter)</h1>
    <p>贾维斯独立审 review queue 提案 + 自己拍板. 低风险 (内梗/历史线) 真自决 (通过/拒绝), 中风险 (关怀/指令) 只建议 Sir 看. 每天 03:xx 反思 24h Sir 撤销率 → 自动调阈值. Sir 一键撤销任何决定.</p>
    <p style="color:#6e7681; font-size:0.83rem;">数据源: <code>memory_pool/auto_arbiter_log.jsonl</code> · 阈值: <code>memory_pool/auto_arbiter_calibration.json</code> · CLI: <code>python scripts/auto_arbiter_dump.py</code></p>
    <div class="legend">
      <span class="legend-item">🃏 内梗 / 🧵 历史线 (低风险, 真自决)</span>
      <span class="legend-item">🎯 关怀 / 📜 指令 (中风险, 只建议)</span>
      <span class="legend-item">✅ 通过 / ❌ 拒绝 / 🙋 建议 Sir 看 / ➖ 不动</span>
    </div>
    <div class="nav-links">
      <a href="/">← 主面板</a>
      <a href="/inner_thoughts">💭 思考层</a>
      <a href="/main_brain_meta">🧠 思考链</a>
      <a href="/items">💡 我们的事</a>
    </div>
  </div>

  <div class="controls">
    <label>时间范围:
      <select id="hours-sel" onchange="loadRecords()">
        <option value="24" selected>最近 24h</option>
        <option value="72">最近 3 天</option>
        <option value="168">最近 7 天</option>
      </select>
    </label>
    <label>显示数:
      <select id="limit-sel" onchange="loadRecords()">
        <option value="30">最多 30</option>
        <option value="50" selected>最多 50</option>
        <option value="200">最多 200</option>
      </select>
    </label>
    <label>类型:
      <select id="kind-sel" onchange="loadRecords()">
        <option value="" selected>全部</option>
        <option value="inside_joke">🃏 内梗</option>
        <option value="thread">🧵 历史线</option>
        <option value="concern">🎯 关怀</option>
        <option value="directive">📜 指令</option>
      </select>
    </label>
    <label>决策:
      <select id="dec-sel" onchange="loadRecords()">
        <option value="" selected>全部</option>
        <option value="activate">✅ 通过</option>
        <option value="reject">❌ 拒绝</option>
        <option value="defer_to_sir">🙋 建议 Sir 看</option>
        <option value="noop">➖ 不动</option>
      </select>
    </label>
    <label>
      <input type="checkbox" id="reverted-only" onchange="loadRecords()"/>
      仅看 Sir 撤销的
    </label>
    <button class="refresh-btn" onclick="loadRecords()">🔄 刷新</button>
    <span id="status" class="status-text"></span>
  </div>

  <div id="health-banner"></div>

  <div class="stats" id="stats-box">
    <div class="stat-box ok"><div class="num" id="n-decisions">-</div>
      <div class="label">24h 真拍板数 (通过+拒)</div></div>
    <div class="stat-box warn"><div class="num" id="n-defer">-</div>
      <div class="label">建议 Sir 看 (中风险)</div></div>
    <div class="stat-box crit"><div class="num" id="n-reverted">-</div>
      <div class="label">Sir 撤销数 (反馈)</div></div>
    <div class="stat-box"><div class="num" id="n-llm">-</div>
      <div class="label">LLM 调用次数</div></div>
  </div>

  <div class="thresholds" id="thresholds-box">
    <h3>📊 当前 confidence 阈值 (Daily 03:xx 自动调整)</h3>
    <div class="row" id="thr-list"></div>
    <div class="note" id="thr-note"></div>
  </div>

  <div class="records" id="records">
    <div class="empty-state">loading...</div>
  </div>

  <script>
    function fmtTs(ts) {
      if (!ts) return '?';
      const d = new Date(ts * 1000);
      const now = new Date();
      const diffMin = Math.floor((now - d) / 60000);
      let ageStr;
      if (diffMin < 1) ageStr = '刚刚';
      else if (diffMin < 60) ageStr = diffMin + '分钟前';
      else if (diffMin < 1440) ageStr = (diffMin / 60).toFixed(1) + '小时前';
      else ageStr = (diffMin / 1440).toFixed(1) + '天前';
      const tStr = d.toLocaleTimeString('zh-CN', {hour12: false});
      return ageStr + ' · ' + tStr;
    }
    function escapeHtml(s) {
      if (!s) return '';
      return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                       .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function fmtConf(c, t) {
      const pct = Math.round((c || 0) * 100);
      const pctVal = (c || 0).toFixed(2);
      const thrVal = (t || 0).toFixed(2);
      return `<span class="conf-bar"><span class="bar"><span class="bar-fill" style="width:${pct}%"></span></span><span class="val">${pctVal}</span><span class="thr">(阈值 ${thrVal})</span></span>`;
    }

    async function doRevert(decisionId) {
      const reason = prompt('Sir 撤销原因 (短句, 帮贾维斯下次更准):', '');
      if (reason === null) return;
      const btn = document.querySelector(`[data-rev-id="${decisionId}"]`);
      if (btn) btn.disabled = true;
      try {
        const r = await fetch('/api/auto_arbiter/revert', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({decision_id: decisionId, reason: reason || ''}),
        });
        const j = await r.json();
        if (!j.ok) {
          alert('撤销失败: ' + (j.detail || j.error || 'unknown'));
          if (btn) btn.disabled = false;
          return;
        }
        loadRecords();
      } catch (e) {
        alert('请求失败: ' + e.message);
        if (btn) btn.disabled = false;
      }
    }

    function loadRecords() {
      const hours = document.getElementById('hours-sel').value;
      const limit = document.getElementById('limit-sel').value;
      const kind = document.getElementById('kind-sel').value;
      const dec = document.getElementById('dec-sel').value;
      const revOnly = document.getElementById('reverted-only').checked ? 1 : 0;
      document.getElementById('status').textContent = '⏳ loading...';
      const url = `/api/auto_arbiter?hours=${hours}&limit=${limit}` +
                   `&kind=${kind}&decision=${dec}&reverted_only=${revOnly}`;
      fetch(url)
        .then(r => r.json())
        .then(data => {
          if (!data.ok) {
            document.getElementById('records').innerHTML =
              `<div class="empty-state">⚠️ 错误: ${escapeHtml(data.error || 'unknown')}</div>`;
            document.getElementById('status').textContent = '';
            return;
          }
          const s = data.stats || {};
          document.getElementById('n-decisions').textContent = s.decisions_24h || 0;
          document.getElementById('n-defer').textContent = s.defer_count || 0;
          document.getElementById('n-reverted').textContent = s.reverted_count || 0;
          document.getElementById('n-llm').textContent = s.live_llm_call_count || 0;

          // thresholds
          const thr = s.thresholds || {};
          const KIND_ZH = {inside_joke: '🃏 内梗', thread: '🧵 历史线',
                            concern: '🎯 关怀', directive: '📜 指令'};
          const thrList = document.getElementById('thr-list');
          if (Object.keys(thr).length === 0) {
            thrList.innerHTML = '<span style="color:#6e7681">还没 calibrate (用默认值)</span>';
          } else {
            thrList.innerHTML = Object.entries(thr).map(([k, v]) =>
              `<span class="item">${KIND_ZH[k] || k}<span class="v">${(v || 0).toFixed(2)}</span></span>`
            ).join('');
          }
          const thrNote = document.getElementById('thr-note');
          if (s.last_calibrated_iso) {
            thrNote.textContent = `上次自调整: ${s.last_calibrated_iso} (Sir 撤销率 > 30% 升, < 10% 降)`;
          } else {
            thrNote.textContent = '还没 daily reflection 跑过 (03:xx fire)';
          }

          // 健康
          const hb = document.getElementById('health-banner');
          if (data.health === 'empty') {
            hb.className = 'health-banner empty';
            hb.textContent = 'ℹ️ ' + (data.health_msg || '');
          } else if (data.health === 'warn') {
            hb.className = 'health-banner warn';
            hb.textContent = '⚠️ ' + (data.health_msg || '');
          } else if (data.health_msg) {
            hb.className = 'health-banner ok';
            hb.textContent = '✅ ' + data.health_msg;
          } else {
            hb.className = 'health-banner';
            hb.textContent = '';
          }

          // records
          const records = data.records || [];
          if (records.length === 0) {
            document.getElementById('records').innerHTML =
              `<div class="empty-state">这个 filter 下没自决记录<div class="hint">换 filter, 或等 daemon 多产几条 (30min tick 一次).</div></div>`;
            document.getElementById('status').textContent =
              '✓ ' + new Date().toLocaleTimeString('zh-CN', {hour12: false});
            return;
          }

          let html = '';
          records.forEach(r => {
            const reverted = !!r.sir_reverted;
            const execFail = (r.decision === 'activate' || r.decision === 'reject') && !r.executed_ok;
            let cls = '';
            if (reverted) cls = 'reverted';
            else if (execFail) cls = 'executed-fail';

            html += `<div class="decision-card ${cls}" style="border-left-color:${reverted ? '#f85149' : r.decision_color}">`;
            // head
            html += `<div class="card-head">`;
            html += `<div class="card-head-left">`;
            html += `<span class="kind-badge" style="color:${r.kind_color}">${r.kind_icon} ${r.kind_zh}</span>`;
            html += `<span class="decision-badge" style="color:${r.decision_color}; background:${r.decision_color}22">${r.decision_icon} ${r.decision_zh}</span>`;
            html += `<span class="risk-badge">${r.risk_icon} ${r.risk_zh}</span>`;
            html += `<span style="color:#6e7681; font-size:0.78rem">${fmtTs(r.ts)}</span>`;
            html += `</div>`;
            html += `<div>${fmtConf(r.confidence, r.threshold)}</div>`;
            html += `</div>`;

            // item preview
            if (r.item_preview) {
              html += `<div class="item-preview">${escapeHtml(r.item_preview)}</div>`;
            }
            // reason
            if (r.reason) {
              html += `<div class="reason-line">🤖 ${escapeHtml(r.reason)}</div>`;
            }
            // exec
            const execIcon = r.executed_ok ? '✅ 真执行' :
                              (r.decision === 'defer_to_sir' ? '🙋 留给 Sir' :
                                r.decision === 'noop' ? '➖ 不动' : '⚠️ 执行失败');
            const execCls = r.executed_ok ? 'ok' :
                             (r.decision === 'defer_to_sir' || r.decision === 'noop' ? 'defer' : 'fail');
            html += `<div class="exec-row"><span class="${execCls}">${execIcon}</span>`;
            if (r.execution_msg) {
              html += `<span style="color:#6e7681">${escapeHtml(r.execution_msg)}</span>`;
            }
            // revert button (只对真 activate/reject 显示, 不对 defer/noop)
            if (!reverted && r.executed_ok && (r.decision === 'activate' || r.decision === 'reject')) {
              html += `<button class="revert-btn" data-rev-id="${r.id}" onclick="doRevert('${r.id}')" title="Sir 撤销这条决定 + 给原因, 贾维斯下次会更准">↩ Sir 撤销</button>`;
            }
            html += `</div>`;

            // reverted row
            if (reverted) {
              html += `<div class="revert-row">`;
              html += `<span class="lbl">↩ Sir 已撤销</span>`;
              if (r.sir_revert_reason) {
                html += ` — ${escapeHtml(r.sir_revert_reason)}`;
              }
              html += `</div>`;
            }
            html += `</div>`;
          });
          document.getElementById('records').innerHTML = html;
          document.getElementById('status').textContent =
            `✓ ${records.length}/${data.total} · ` +
            new Date().toLocaleTimeString('zh-CN', {hour12: false});
        })
        .catch(err => {
          document.getElementById('records').innerHTML =
            `<div class="empty-state">⚠️ fetch 错: ${escapeHtml(err.message)}</div>`;
          document.getElementById('status').textContent = '';
        });
    }
    loadRecords();
    setInterval(loadRecords, 30000);
  </script>
</body>
</html>
"""


@app.route('/auto_arbiter')
def page_auto_arbiter():
    """🆕 [AA / Sir 2026-05-25 22:58] /auto_arbiter dashboard page."""
    from flask import make_response
    resp = make_response(render_template_string(_AUTO_ARBITER_HTML))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


# ============================================================
# 🆕 [WRC / Sir 2026-05-25 23:52 真问 "3 也做"] /weekly_insights dashboard
# 灵魂工程 Layer 4.5 — 周反思合并器. Sir 一键 accept/reject 长期 insight.
# 数据源: memory_pool/long_term_insights.jsonl
# 准则 7 Sir 元否决 — accept 也不直接 mutate sir_profile (Sir 手工升级)
# ============================================================

_WRC_STATE_ZH = {
    'review': '🪞 待审',
    'accepted': '✅ Sir 已通过',
    'rejected': '❌ Sir 已拒',
}


@app.route('/api/weekly_insights')
def api_weekly_insights():
    """🆕 [WRC] List weekly insights.

    Query params:
      state: 'review' / 'accepted' / 'rejected' / 'all' (default all)
      limit: max records (default 100)
    """
    try:
        state_filter = (request.args.get('state', 'all') or 'all').lower()
        limit = int(request.args.get('limit', 100) or 100)

        persist_path = os.path.join(ROOT, 'memory_pool',
                                       'long_term_insights.jsonl')
        if not os.path.exists(persist_path):
            return jsonify({
                'ok': True, 'insights': [], 'stats': {
                    'total': 0, 'by_state': {}, 'last_fired_week_key': '',
                },
                'note': 'no insights yet (周日 03:xx 才 fire)',
            })

        # 读最新 by id (last-write-wins, 同模块 _load_persist 逻辑)
        latest_by_id = {}
        with open(persist_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if d.get('id'):
                        latest_by_id[d['id']] = d
                except (json.JSONDecodeError, ValueError):
                    continue

        records = sorted(latest_by_id.values(),
                            key=lambda r: -float(r.get('ts', 0)))
        if state_filter != 'all':
            records = [r for r in records
                          if r.get('state', 'review') == state_filter]
        records = records[:limit]

        # 加 zh state label
        for r in records:
            r['_state_zh'] = _WRC_STATE_ZH.get(
                r.get('state', 'review'), r.get('state', ''))

        # stats
        by_state = {}
        for d in latest_by_id.values():
            s = d.get('state', 'review')
            by_state[s] = by_state.get(s, 0) + 1

        live_last_week = ''
        try:
            from jarvis_weekly_reflection_consolidator import (
                get_default_consolidator
            )
            c = get_default_consolidator()
            if c is not None:
                live_last_week = c.get_stats().get('last_fired_week_key', '')
        except Exception:
            pass

        return jsonify({
            'ok': True,
            'insights': records,
            'stats': {
                'total': len(latest_by_id),
                'by_state': by_state,
                'last_fired_week_key': live_last_week,
            },
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/weekly_insights/decide', methods=['POST'])
def api_weekly_insights_decide():
    """🆕 [WRC] Sir 一键 accept/reject 一条 insight.

    POST body: {"insight_id": "wi_...", "decision": "accept"|"reject",
                 "reason": "optional"}
    """
    data = request.get_json(silent=True) or {}
    insight_id = (data.get('insight_id') or '').strip()
    decision = (data.get('decision') or '').strip().lower()
    reason = (data.get('reason') or '').strip()[:200]
    if not insight_id or decision not in ('accept', 'reject'):
        return jsonify({
            'ok': False,
            'error': 'insight_id + decision (accept|reject) required',
        }), 400
    try:
        from jarvis_weekly_reflection_consolidator import (
            get_default_consolidator
        )
        c = get_default_consolidator()
        if c is None:
            return jsonify({
                'ok': False,
                'error': 'WeeklyReflectionConsolidator daemon not active',
            }), 503
        if decision == 'accept':
            ok = c.sir_accept(insight_id, reason)
        else:
            ok = c.sir_reject(insight_id, reason)
        if not ok:
            return jsonify({
                'ok': False, 'error': f'insight {insight_id} not found',
            }), 404
        return jsonify({'ok': True, 'insight_id': insight_id,
                          'new_state': 'accepted' if decision == 'accept'
                          else 'rejected'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


_WEEKLY_INSIGHTS_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>🪞 周反思 (WeeklyReflectionConsolidator)</title>
  <style>
    *{box-sizing:border-box}
    body{margin:0;font-family:-apple-system,'Segoe UI',sans-serif;
          background:#0d1117;color:#c9d1d9;line-height:1.5}
    .header{padding:1.2rem 1.8rem;background:#161b22;border-bottom:1px solid #30363d}
    .header h1{margin:0;font-size:1.5rem;color:#9ad1be}
    .header p{margin:.4rem 0 0;color:#8b949e;font-size:.92rem}
    .legend{margin-top:.4rem;color:#6e7681;font-size:.83rem}
    .legend code{background:#161b22;padding:.1rem .3rem;border-radius:3px}
    .controls{padding:1rem 1.8rem;background:#0d1117;border-bottom:1px solid #30363d;
                display:flex;gap:1rem;flex-wrap:wrap;align-items:center}
    .controls label{font-size:.88rem;color:#8b949e}
    .controls select,.controls input[type=number]{
        background:#161b22;color:#c9d1d9;border:1px solid #30363d;
        padding:.3rem .6rem;border-radius:5px;font-size:.88rem}
    .controls button{background:#238636;color:#fff;border:0;
        padding:.4rem .9rem;border-radius:5px;cursor:pointer;font-size:.88rem}
    .controls button:hover{background:#2ea043}
    .status{margin-left:auto;color:#9ad1be;font-size:.85rem}
    .container{padding:1.5rem 1.8rem}
    .stats{display:flex;gap:1rem;margin-bottom:1rem;flex-wrap:wrap}
    .stat{background:#161b22;border:1px solid #30363d;border-radius:6px;
            padding:.7rem 1.2rem;flex:1;min-width:160px}
    .stat-label{color:#6e7681;font-size:.78rem;text-transform:uppercase}
    .stat-value{color:#c9d1d9;font-size:1.4rem;font-weight:600;margin-top:.2rem}
    .insight{background:#161b22;border:1px solid #30363d;border-radius:6px;
               padding:1rem 1.2rem;margin-bottom:.8rem}
    .insight-head{display:flex;justify-content:space-between;
                   align-items:start;flex-wrap:wrap;gap:.5rem}
    .insight-state{padding:.18rem .55rem;border-radius:4px;
                    font-size:.78rem;font-weight:600}
    .state-review{background:#1f6feb33;color:#79c0ff}
    .state-accepted{background:#23863633;color:#7ee787}
    .state-rejected{background:#da363322;color:#ff7b72}
    .insight-ts{color:#6e7681;font-size:.78rem}
    .insight-pattern{color:#9ad1be;font-size:1rem;margin-top:.5rem;
                     font-weight:500}
    .insight-action{color:#c9d1d9;font-size:.92rem;margin-top:.4rem}
    .insight-meta{color:#6e7681;font-size:.78rem;margin-top:.5rem}
    .insight-excerpts{margin-top:.5rem;background:#0d1117;
                       padding:.5rem .8rem;border-radius:4px;
                       border:1px solid #21262d}
    .insight-excerpts ul{margin:.2rem 0;padding-left:1.2rem;font-size:.85rem;
                          color:#8b949e}
    .actions{margin-top:.7rem;display:flex;gap:.5rem}
    .btn{padding:.35rem .8rem;border-radius:4px;cursor:pointer;
          font-size:.85rem;border:0;font-weight:500}
    .btn-accept{background:#238636;color:#fff}
    .btn-accept:hover{background:#2ea043}
    .btn-reject{background:#6e7681;color:#fff}
    .btn-reject:hover{background:#8b949e}
    .btn:disabled{opacity:.5;cursor:not-allowed}
    .empty-state{padding:2rem;text-align:center;color:#6e7681}
  </style>
</head>
<body>
  <div class="header">
    <h1>🪞 周反思 (WeeklyReflectionConsolidator)</h1>
    <p>每周日 03:xx 自动 fire 一次. 从 Hippocampus 提 7d <code>self_reflection</code> events, LLM (Flash-Lite) 找 recurring pattern, propose long-term insight 给 Sir. 准则 7 Sir 元否决: accept 不直接 mutate <code>sir_profile</code>, Sir 手动决定升级.</p>
    <p class="legend">数据源: <code>memory_pool/long_term_insights.jsonl</code> · 灵魂工程 Layer 4.5 · 成本 ~$0.001/周</p>
  </div>
  <div class="controls">
    <label>状态: <select id="state-sel">
      <option value="all">全部</option>
      <option value="review" selected>🪞 待审</option>
      <option value="accepted">✅ 已通过</option>
      <option value="rejected">❌ 已拒</option>
    </select></label>
    <label>限制: <input type="number" id="limit-input" value="100"
                          min="1" max="500" style="width:80px"></label>
    <button onclick="loadInsights()">🔄 刷新</button>
    <span class="status" id="status"></span>
  </div>
  <div class="container">
    <div class="stats" id="stats-box"></div>
    <div id="insights-box"></div>
  </div>
  <script>
    function escapeHtml(s){
      if(!s) return '';
      return String(s).replace(/[&<>"']/g, function(m){
        return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m];
      });
    }
    async function decideInsight(insightId, decision){
      const reason = prompt(
        decision==='accept'
          ? 'Sir 通过这个 insight 的原因 (选填):'
          : 'Sir 拒绝这个 insight 的原因 (选填):'
      );
      if(reason===null) return;
      const btns = document.querySelectorAll(`[data-iid="${insightId}"]`);
      btns.forEach(b=>b.disabled=true);
      try{
        const r = await fetch('/api/weekly_insights/decide', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({insight_id:insightId, decision:decision,
                                 reason:reason||''}),
        });
        const data = await r.json();
        if(data.ok){
          loadInsights();
        } else {
          alert('失败: ' + (data.error||'unknown'));
          btns.forEach(b=>b.disabled=false);
        }
      } catch(e){
        alert('网络错: ' + e.message);
        btns.forEach(b=>b.disabled=false);
      }
    }
    function loadInsights(){
      const state = document.getElementById('state-sel').value;
      const limit = document.getElementById('limit-input').value || 100;
      document.getElementById('status').textContent = '⏳ loading...';
      fetch(`/api/weekly_insights?state=${state}&limit=${limit}`)
        .then(r=>r.json())
        .then(data=>{
          if(!data.ok){
            document.getElementById('insights-box').innerHTML =
              `<div class="empty-state">⚠️ ${escapeHtml(data.error||'unknown')}</div>`;
            document.getElementById('status').textContent = '';
            return;
          }
          const s = data.stats || {};
          const by = s.by_state || {};
          document.getElementById('stats-box').innerHTML = `
            <div class="stat"><div class="stat-label">总 insight 数</div>
              <div class="stat-value">${s.total||0}</div></div>
            <div class="stat"><div class="stat-label">🪞 待审</div>
              <div class="stat-value">${by.review||0}</div></div>
            <div class="stat"><div class="stat-label">✅ 已通过</div>
              <div class="stat-value">${by.accepted||0}</div></div>
            <div class="stat"><div class="stat-label">❌ 已拒</div>
              <div class="stat-value">${by.rejected||0}</div></div>
            <div class="stat"><div class="stat-label">上次 fire 周</div>
              <div class="stat-value" style="font-size:1rem">
                ${escapeHtml(s.last_fired_week_key||'尚未')}</div></div>
          `;
          const list = data.insights || [];
          if(list.length === 0){
            document.getElementById('insights-box').innerHTML =
              `<div class="empty-state">📭 无 insight (${escapeHtml(data.note||'当前筛选条件下无记录')})</div>`;
          } else {
            document.getElementById('insights-box').innerHTML = list.map(r=>{
              const stateCls = `state-${r.state||'review'}`;
              const stateLabel = r._state_zh || r.state;
              const conf = r.confidence ? (r.confidence*100).toFixed(0)+'%' : '?';
              const excerpts = (r.evidence_excerpts||[]).map(e=>
                `<li>${escapeHtml(e)}</li>`).join('');
              const actionsHtml = r.state==='review' ? `
                <div class="actions">
                  <button class="btn btn-accept" data-iid="${r.id}"
                    onclick="decideInsight('${r.id}','accept')">✅ Sir 通过</button>
                  <button class="btn btn-reject" data-iid="${r.id}"
                    onclick="decideInsight('${r.id}','reject')">❌ Sir 拒</button>
                </div>` : (r.sir_decision_reason ? `
                <div class="insight-meta">Sir 理由: ${escapeHtml(r.sir_decision_reason)}</div>`
                : '');
              // 🆕 [Sir 2026-05-27 00:30 Phase 2B 后半] insight_type 区分两条 reflector path
              const itype = r.insight_type || 'self_reflection_pattern';
              const typeBadge = itype === 'inner_thought_vocab_tune'
                ? '<span style="background:#ec489922;color:#ec4899;padding:0.15rem 0.55rem;border-radius:4px;font-size:0.75rem;margin-right:0.3rem;">🎚️ 思考阈值调</span>'
                : '<span style="background:#3fb95022;color:#3fb950;padding:0.15rem 0.55rem;border-radius:4px;font-size:0.75rem;margin-right:0.3rem;">🪞 反思 pattern</span>';
              // vocab tune 详情 — 真显具体 field + old/new value 让 Sir 一眼看改啥
              const vocabTuneHtml = (itype === 'inner_thought_vocab_tune' && r.target_field) ? `
                <div style="background:#0d1117;padding:0.6rem 0.8rem;border-radius:4px;margin-top:0.5rem;border-left:3px solid #ec4899;">
                  <div style="color:#ec4899;font-size:0.83rem;font-weight:600;margin-bottom:0.3rem;">建议修改 (Sir 元否决: accept 后 Sir 手工改 JSON)</div>
                  <div style="font-family:monospace;font-size:0.85rem;color:#c9d1d9;">
                    <span style="color:#8b949e;">file:</span> ${escapeHtml(r.target_vocab_path||'')}<br>
                    <span style="color:#8b949e;">field:</span> <span style="color:#79c0ff;">${escapeHtml(r.target_field)}</span><br>
                    <span style="color:#8b949e;">old:</span> <span style="color:#f85149;">${escapeHtml(String(r.proposed_old_value))}</span> →
                    <span style="color:#8b949e;">new:</span> <span style="color:#3fb950;">${escapeHtml(String(r.proposed_new_value))}</span>
                  </div>
                </div>` : '';
              return `
                <div class="insight">
                  <div class="insight-head">
                    <span>${typeBadge}<span class="insight-state ${stateCls}">${stateLabel}</span></span>
                    <span class="insight-ts">${escapeHtml(r.ts_iso||'')} · ${escapeHtml(r.week_range_iso||'')}</span>
                  </div>
                  <div class="insight-pattern">${escapeHtml(r.pattern_summary||'')}</div>
                  <div class="insight-action">💡 ${escapeHtml(r.suggested_action||'')}</div>
                  ${vocabTuneHtml}
                  <div class="insight-meta">置信度 ${conf} · evidence ${r.evidence_count||0} 条</div>
                  ${excerpts ? `<div class="insight-excerpts">证据节选:<ul>${excerpts}</ul></div>` : ''}
                  ${actionsHtml}
                </div>`;
            }).join('');
          }
          document.getElementById('status').textContent =
            `✓ ${list.length} 条 @ ${new Date().toLocaleTimeString()}`;
        })
        .catch(err=>{
          document.getElementById('insights-box').innerHTML =
            `<div class="empty-state">⚠️ fetch 错: ${escapeHtml(err.message)}</div>`;
          document.getElementById('status').textContent = '';
        });
    }
    loadInsights();
    setInterval(loadInsights, 30000);
  </script>
</body>
</html>
"""


@app.route('/weekly_insights')
def page_weekly_insights():
    """🆕 [WRC / Sir 2026-05-25 23:52] /weekly_insights dashboard page."""
    from flask import make_response
    resp = make_response(render_template_string(_WEEKLY_INSIGHTS_HTML))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


# ============================================================
# 🆕 [Sir 2026-05-27 18:44 真愿景 Phase 1 Step 4] /inner_voice
# InnerVoiceTrack 心声轨道 dashboard
# 数据源: memory_pool/inner_voice_24h.jsonl (jarvis_inner_voice_track)
# ============================================================

_INNER_VOICE_SOURCE_META = {
    'inner_thought': {'cn': '🧠 思考脑',     'color': '#a78bfa'},
    'sensor':        {'cn': '👁️ 感官',        'color': '#60a5fa'},
    'care_trigger':  {'cn': '💗 关怀触发',    'color': '#f472b6'},
    'self_reflection': {'cn': '🪞 自省',     'color': '#fbbf24'},
    'noting':        {'cn': '📝 心跳',        'color': '#94a3b8'},
    'sir_injected':  {'cn': '👤 Sir 注入',    'color': '#34d399'},
}

_INNER_VOICE_INTENT_META = {
    'observation': '观察',
    'care': '关怀',
    'reflection': '反思',
    'reminder': '提醒',
    'noting': '心跳',
}


@app.route('/api/inner_voice')
def api_inner_voice():
    """🆕 [Sir 2026-05-27 18:44 Phase 1 Step 4] InnerVoiceTrack 数据.

    Query:
      hours: 取近 N 小时 (default 24)
      source: 过滤 source (e.g. inner_thought / sensor)
      wants_voice_only: 1 = 只显 wants_voice=True

    Returns:
      {ok, entries: [...], stats: {...}, prompt_block_preview: '...'}
    """
    try:
        from jarvis_inner_voice_track import (
            get_inner_voice_track, is_enabled,
        )
    except Exception as e:
        return jsonify({'ok': False, 'error': f'import_fail:{e}'})
    try:
        hours = float(request.args.get('hours', '24'))
    except Exception:
        hours = 24.0
    source_filter = (request.args.get('source') or '').strip().lower()
    wants_voice_only = request.args.get('wants_voice_only', '0') == '1'

    track = get_inner_voice_track()
    entries = track.all_recent(hours=hours)
    if source_filter:
        entries = [e for e in entries if e.source == source_filter]
    if wants_voice_only:
        entries = [e for e in entries if e.wants_voice]
    # 倒序 (新在上)
    entries = sorted(entries, key=lambda e: -e.ts)

    out_entries = []
    now = time.time()
    for e in entries[:200]:
        age_s = int(now - e.ts)
        if age_s < 60:
            age_str = f'{age_s}s ago'
        elif age_s < 3600:
            age_str = f'{age_s // 60}m ago'
        else:
            age_str = f'{age_s // 3600}h{(age_s % 3600) // 60}m ago'
        src_meta = _INNER_VOICE_SOURCE_META.get(
            e.source, {'cn': e.source, 'color': '#94a3b8'}
        )
        intent_cn = _INNER_VOICE_INTENT_META.get(e.intent, e.intent)
        out_entries.append({
            'ts': e.ts,
            'hhmm': time.strftime('%H:%M:%S', time.localtime(e.ts)),
            'age_str': age_str,
            'source': e.source,
            'source_cn': src_meta['cn'],
            'source_color': src_meta['color'],
            'intent': e.intent,
            'intent_cn': intent_cn,
            'content': e.content,
            'urgency': e.urgency,
            'wants_voice': e.wants_voice,
            'meta': e.meta or {},
        })

    return jsonify({
        'ok': True,
        'enabled': is_enabled(),
        'entries': out_entries,
        'stats': track.stats(),
        'prompt_block_preview': track.build_prompt_block_for_brain(
            max_chars=3000, show_l3=True
        ),
    })


_INNER_VOICE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>🌊 心声轨道 — Jarvis InnerVoiceTrack</title>
<style>
* { box-sizing: border-box; }
body {
  font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: #0d1117; color: #c9d1d9; margin: 0; padding: 1rem 1.5rem;
  min-height: 100vh;
}
.header h1 { color: #fda4af; margin: 0 0 0.3rem 0; font-size: 1.5rem; }
.header p { color: #8b949e; font-size: 0.88rem; margin: 0.2rem 0; }
.header code { background: #161b22; padding: 0.1rem 0.4rem; border-radius: 3px;
              color: #79c0ff; font-size: 0.82rem; }
.controls {
  margin: 0.8rem 0; display: flex; gap: 0.6rem; align-items: center;
  flex-wrap: wrap; padding: 0.6rem 0.8rem;
  background: #161b22; border-radius: 8px;
  border: 1px solid #30363d;
}
.controls label { color: #8b949e; font-size: 0.85rem; }
.controls select, .controls input[type="number"] {
  background: #0d1117; color: #c9d1d9; border: 1px solid #30363d;
  padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.85rem;
}
.controls button {
  background: #1f6feb; color: #fff; border: none;
  padding: 0.3rem 0.7rem; border-radius: 4px; cursor: pointer;
  font-size: 0.85rem;
}
.controls button:hover { background: #388bfd; }
.stats {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.6rem; margin: 0.8rem 0;
}
.stat-card {
  background: #161b22; border: 1px solid #30363d; border-radius: 6px;
  padding: 0.7rem; text-align: center;
}
.stat-card .value { font-size: 1.5rem; color: #fda4af; font-weight: 700; }
.stat-card .label { font-size: 0.78rem; color: #8b949e; margin-top: 0.2rem; }
.entry {
  background: #161b22; border-left: 3px solid #30363d;
  border-radius: 4px; padding: 0.6rem 0.8rem; margin: 0.4rem 0;
  display: flex; gap: 0.7rem; align-items: flex-start;
}
.entry.wants_voice { border-left-color: #f472b6;
                     background: linear-gradient(90deg, #2a1426, #161b22); }
.entry .ts {
  color: #8b949e; font-family: ui-monospace, Consolas, monospace;
  font-size: 0.78rem; flex-shrink: 0; min-width: 65px;
}
.entry .src-tag {
  background: #0d1117; padding: 0.1rem 0.4rem; border-radius: 3px;
  font-size: 0.75rem; font-weight: 600; flex-shrink: 0;
}
.entry .intent-tag {
  color: #8b949e; font-size: 0.78rem; flex-shrink: 0;
}
.entry .urgency-bar {
  height: 4px; background: #30363d; border-radius: 2px;
  width: 60px; flex-shrink: 0; margin-top: 6px;
  position: relative; overflow: hidden;
}
.entry .urgency-fill { height: 100%; background: #f59e0b; }
.entry .star {
  color: #f472b6; flex-shrink: 0; font-size: 0.95rem; margin-top: 1px;
}
.entry .content { flex: 1; color: #c9d1d9; font-size: 0.92rem;
                  line-height: 1.45; word-break: break-word; }
.entry .age {
  color: #6e7681; font-size: 0.74rem; flex-shrink: 0; margin-top: 2px;
}
.empty { color: #6e7681; text-align: center; padding: 2rem;
         font-style: italic; }
.prompt-preview {
  margin-top: 1.5rem; padding: 0.8rem 1rem;
  background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
}
.prompt-preview h3 { color: #79c0ff; margin: 0 0 0.5rem 0; font-size: 1rem; }
.prompt-preview pre {
  white-space: pre-wrap; word-wrap: break-word;
  color: #8b949e; font-family: ui-monospace, Consolas, monospace;
  font-size: 0.78rem; max-height: 360px; overflow-y: auto; margin: 0;
  padding: 0.6rem; background: #161b22; border-radius: 4px;
}
.nav-links { margin: 1rem 0 0 0; padding-top: 0.8rem;
            border-top: 1px solid #30363d; }
.nav-links a {
  color: #79c0ff; margin-right: 1.2rem; text-decoration: none;
  font-size: 0.88rem;
}
.heartbeat-dot {
  display: inline-block; width: 10px; height: 10px; border-radius: 50%;
  background: #fda4af; margin-right: 6px; vertical-align: middle;
  animation: pulse-glow 1.5s ease-in-out infinite;
}
@keyframes pulse-glow {
  0%, 100% { box-shadow: 0 0 4px #fda4af, 0 0 6px #fda4af; }
  50% { box-shadow: 0 0 10px #fda4af, 0 0 16px #fda4af; }
}
.disabled-banner {
  background: #3b2419; border: 1px solid #6e3818;
  color: #fca5a5; padding: 0.6rem 1rem; border-radius: 6px;
  margin: 0.8rem 0; text-align: center; font-size: 0.9rem;
}
</style>
</head>
<body>
  <div class="header">
    <h1><span class="heartbeat-dot"></span>🌊 心声轨道 <span id="enabled-badge" style="font-size:0.82rem;color:#8b949e;font-weight:normal;"></span></h1>
    <p>Jarvis 24/7 持续意识流 — 所有思考脑/感官/关怀/自省统一时序 append. 主脑被召唤时, 看的就是这个轨道, 自然 weave 进 reply (不刻意 reference).</p>
    <p>数据源: <code>memory_pool/inner_voice_24h.jsonl</code> · 主脑 prompt Layer 1.6 注入. 关闭: <code>JARVIS_INNER_VOICE_ENABLED=0</code></p>
  </div>

  <div id="disabled-banner-wrap"></div>

  <div class="controls">
    <label>取近 <input type="number" id="hours" value="24" min="0.1" step="0.1" style="width:60px"> h</label>
    <label>source
      <select id="source-sel">
        <option value="">全部</option>
        <option value="inner_thought">🧠 思考脑</option>
        <option value="sensor">👁️ 感官</option>
        <option value="care_trigger">💗 关怀触发</option>
        <option value="self_reflection">🪞 自省</option>
        <option value="noting">📝 心跳</option>
        <option value="sir_injected">👤 Sir 注入</option>
      </select>
    </label>
    <label><input type="checkbox" id="wv-only"> 只显 ★ (wants_voice)</label>
    <button id="refresh-btn">🔄 刷新</button>
    <span id="status" style="color:#8b949e;font-size:0.82rem;"></span>
    <span style="margin-left:auto;color:#6e7681;font-size:0.78rem;">10s 自动 poll</span>
  </div>

  <div id="stats-grid" class="stats"></div>

  <div id="entries-wrap">
    <div class="empty">⏳ loading...</div>
  </div>

  <div class="prompt-preview">
    <h3>👁️ 主脑实际看到的 inner_voice block (3 层视图 preview)</h3>
    <pre id="prompt-preview-pre">(loading...)</pre>
  </div>

  <div class="nav-links">
    <a href="/">← 主面板</a>
    <a href="/inner_thoughts">💭 思考层</a>
    <a href="/main_brain_meta">🧠 思考链</a>
    <a href="/auto_arbiter">🤖 自决</a>
  </div>

<script>
function load() {
  const hours = document.getElementById('hours').value;
  const source = document.getElementById('source-sel').value;
  const wvOnly = document.getElementById('wv-only').checked ? 1 : 0;
  document.getElementById('status').textContent = '⏳ loading...';
  const url = `/api/inner_voice?hours=${hours}&source=${source}&wants_voice_only=${wvOnly}`;
  fetch(url)
    .then(r => r.json())
    .then(data => {
      if (!data.ok) {
        document.getElementById('status').textContent = '❌ ' + (data.error || 'fail');
        return;
      }
      // enabled badge
      const eb = document.getElementById('enabled-badge');
      const dbw = document.getElementById('disabled-banner-wrap');
      if (data.enabled) {
        eb.textContent = '· env=ENABLED';
        eb.style.color = '#86efac';
        dbw.innerHTML = '';
      } else {
        eb.textContent = '· env=DISABLED';
        eb.style.color = '#fca5a5';
        dbw.innerHTML = '<div class="disabled-banner">⚠️ JARVIS_INNER_VOICE_ENABLED=0 — voice 仍 append 但主脑 prompt 不注入. 设 1 恢复.</div>';
      }
      // stats
      const s = data.stats;
      const grid = document.getElementById('stats-grid');
      grid.innerHTML = `
        <div class="stat-card"><div class="value">${s.total}</div><div class="label">总 entries</div></div>
        <div class="stat-card"><div class="value">${s.last_10min}</div><div class="label">近 10min</div></div>
        <div class="stat-card"><div class="value">${s.last_1h}</div><div class="label">近 1h</div></div>
        <div class="stat-card"><div class="value">${s.last_24h}</div><div class="label">近 24h</div></div>
        <div class="stat-card"><div class="value">${s.wants_voice_pending_30min}</div><div class="label">★ pending (30min)</div></div>
        <div class="stat-card"><div class="value">${s.newest_age_sec}s</div><div class="label">最新距今</div></div>
      `;
      // entries
      const wrap = document.getElementById('entries-wrap');
      if (!data.entries || data.entries.length === 0) {
        wrap.innerHTML = '<div class="empty">⏳ 心声暂空 — 主脑刚醒 / 思考脑还没产 thought / 过滤条件无匹配</div>';
      } else {
        wrap.innerHTML = data.entries.map(e => {
          const wvCls = e.wants_voice ? ' wants_voice' : '';
          const star = e.wants_voice ? '<span class="star">★</span>' : '';
          const urgPct = Math.round(e.urgency * 100);
          const urgBar = e.urgency >= 0.3 ?
            `<div class="urgency-bar"><div class="urgency-fill" style="width:${urgPct}%"></div></div>` : '';
          return `<div class="entry${wvCls}">
            <span class="ts">${e.hhmm}</span>
            <span class="src-tag" style="color:${e.source_color}">${e.source_cn}</span>
            <span class="intent-tag">${e.intent_cn}</span>
            ${urgBar}
            ${star}
            <span class="content">${escapeHtml(e.content)}</span>
            <span class="age">${e.age_str}</span>
          </div>`;
        }).join('');
      }
      // prompt preview
      document.getElementById('prompt-preview-pre').textContent =
        data.prompt_block_preview || '(empty)';
      document.getElementById('status').textContent =
        `✅ ${data.entries.length} entries`;
    })
    .catch(err => {
      document.getElementById('status').textContent = '❌ fetch fail: ' + err;
    });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;',
    '"': '&quot;', "'": '&#39;'
  }[c]));
}

document.getElementById('refresh-btn').addEventListener('click', load);
document.getElementById('source-sel').addEventListener('change', load);
document.getElementById('wv-only').addEventListener('change', load);
document.getElementById('hours').addEventListener('change', load);

load();
setInterval(load, 10000);
</script>
</body>
</html>
"""


@app.route('/inner_voice')
def page_inner_voice():
    """🆕 [Sir 2026-05-27 18:44 Phase 1 Step 4] /inner_voice dashboard page."""
    from flask import make_response
    resp = make_response(render_template_string(_INNER_VOICE_HTML))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


# ============================================================
# main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Jarvis Web Dashboard (β.5.25)')
    parser.add_argument('--host', default='127.0.0.1',
                          help='bind host (default 127.0.0.1)')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true',
                          help='不自动开浏览器')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    url = f'http://{args.host}:{args.port}/'
    print(f"🌐 Jarvis Web Dashboard β.5.25")
    print(f"   listening on {url}")
    if not args.no_browser:
        # 延迟 1s 等 Flask 起来
        def _open():
            import time
            time.sleep(1.0)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()
    # disable Flask 默认 reloader (会 spawn 子进程)
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)


if __name__ == '__main__':
    main()
