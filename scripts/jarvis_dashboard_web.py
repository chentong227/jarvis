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
        <p class="text-xs text-slate-400">β.5.28-fix4 · build {{ build_ts }} · <span x-text="lastUpdate"></span></p>
      </div>
    </div>
    <div class="flex items-center gap-2">
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

<!-- 整体状态条 -->
<section class="max-w-7xl mx-auto px-6 pt-6">
  <div class="glass rounded-2xl p-5 shadow-xl border border-slate-700/30">
    <div class="flex items-baseline gap-3">
      <span class="text-3xl"
            :class="{
              'text-emerald-400': summary.level === 'ok',
              'text-amber-400': summary.level === 'warn',
              'text-rose-400': summary.level === 'crit'
            }" x-text="summary.emoji"></span>
      <h2 class="text-2xl font-bold" x-text="summary.headline"></h2>
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
      setInterval(() => { if (this.autoRefresh) this.refresh(); }, 10000);
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
        }
    except Exception as e:
        return {
            'summary': {'level': 'crit', 'emoji': '❌',
                         'headline': f'读取失败: {e}', 'actions': []},
            'reviewItems': [], 'concerns': {}, 'relation': {}, 'health': {},
            'directive': {}, 'daemon': {}, 'events': {}, 'mutations': {},
            'integrity': {}, 'todo': {}, 'promise': {},
        }


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
