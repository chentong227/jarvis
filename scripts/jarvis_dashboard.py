#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
[P0+20-β.2.9.8 / 2026-05-18] jarvis_dashboard.py — 贾维斯总览看板 (中文)

Sir 三轮反馈合成版:
  1. (10:06) "一个可视化窗口的中文界面一次性看出来所有模块"
  2. (10:13) "翻译成最简单直白的信息, directive 我记得但看不懂"
  3. (10:15) "操作变成按钮 + 排版整理: 信息 / 待处理 / 观测 三块"

三大块布局:
  ▌信息 (你想了解的)          → 长期惦记 / 默契 / 健康
  ▌待处理 (等你拍板的)        → 待办 + [✓完成][🚫取消]  /  审阅 + [✅通过][❌拒绝]
  ▌观测 (看贾维斯有没有偏轨)  → Directive 偏移信号 / Daemon 健康 / 实时事件

设计原则:
  - 全人话, 不用工程术语 (PromiseLog → "贾维斯口头承诺"; severity → "紧迫度 70%")
  - 按钮点击 → subprocess 调 scripts/, 不阻塞 GUI / 不直接改 db
  - 任何 reader / 按钮异常都被吞掉, 该卡片显错误, 其他正常
  - 5s 自动刷新, F5 / Ctrl+R 手动刷新, Ctrl+P 暂停

用法:
  python scripts/jarvis_dashboard.py             # 默认 1500x950 窗口
  python scripts/jarvis_dashboard.py --refresh 10
  python scripts/jarvis_dashboard.py --no-color
  python scripts/jarvis_dashboard.py --text-only # CI/SSH 快照
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

MEM = os.path.join(ROOT, 'memory_pool')
CFG = os.path.join(ROOT, 'jarvis_config')
LOG_DIR = os.path.join(ROOT, 'docs', 'runtime_logs')


# ============================================================
# 配色 (Catppuccin Mocha 暗色, Sir IDE 友好)
# ============================================================
COLOR = {
    'bg': '#1e1e2e',
    'fg': '#cdd6f4',
    'header_bg': '#11111b',
    'header_fg': '#f5c2e7',
    'group_info': '#89dceb',     # 信息块标题色 — 青
    'group_todo': '#f9e2af',     # 待处理块 — 黄
    'group_obs': '#cba6f7',      # 观测块 — 紫
    'card_bg': '#313244',
    'card_fg': '#cdd6f4',
    'card_border': '#585b70',
    'ok': '#a6e3a1',
    'warn': '#fab387',
    'err': '#f38ba8',
    'btn_ok': '#a6e3a1',
    'btn_warn': '#fab387',
    'btn_neutral': '#74c7ec',
    'btn_danger': '#f38ba8',
    'dim': '#6c7086',
}


# ============================================================
# Reader 函数 (所有 reader 独立 try/except)
# ============================================================

def _safe_read_json(path: str, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f) or (default if default is not None else {})
    except Exception:
        return default if default is not None else {}


def _safe_read_jsonl(path: str, tail: int = 100) -> List[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-tail:]
        out = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
    except Exception:
        return []


# 🩹 [β.4.4 / 2026-05-18] Sir Session 3: file-seek tail 版 — 防 jsonl > 100K 条全 load.
# 真机风险点预判 (KICKOFF Session 3 §): integrity_audit.jsonl 长跑后可能膨胀,
# _safe_read_jsonl 的 f.readlines() 会一次性把整个文件读进内存.
# 此函数用 seek -max_bytes 只读末尾段, 丢弃 partial 首行, 上限 tail_lines.
# 损坏行 fail-safe skip (单行 json 解析错不影响其他行).
def _safe_read_jsonl_tail(path: str, tail_lines: int = 2000,
                           max_bytes: int = 512 * 1024) -> List[dict]:
    """读 jsonl 文件末尾 N 行. 用 file seek -max_bytes 避免大文件全 load."""
    if not os.path.exists(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()  # 弃 partial 首行 (可能切到一半 json)
            lines = f.readlines()
        out = []
        for line in lines[-tail_lines:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
    except Exception:
        return []


def _humanize_age_zh(ts: float) -> str:
    """中文时间差: '5 分钟前' / '2 小时前' / '3 天前' / '从没'"""
    if not ts:
        return '从没'
    age = time.time() - float(ts)
    if age < 60:
        return f"{int(age)} 秒前"
    if age < 3600:
        return f"{int(age/60)} 分钟前"
    if age < 86400:
        return f"{age/3600:.1f} 小时前"
    return f"{age/86400:.1f} 天前"


def _humanize_when_zh(ts: float) -> str:
    """中文具体时间: '今天 22:00' / '明天 08:00' / '5-20 14:00'"""
    if not ts:
        return '--'
    try:
        now = time.localtime()
        t = time.localtime(float(ts))
        if t.tm_year == now.tm_year and t.tm_yday == now.tm_yday:
            return f"今天 {t.tm_hour:02d}:{t.tm_min:02d}"
        if (t.tm_year == now.tm_year and
                t.tm_yday == now.tm_yday + 1):
            return f"明天 {t.tm_hour:02d}:{t.tm_min:02d}"
        if (t.tm_year == now.tm_year and
                t.tm_yday == now.tm_yday - 1):
            return f"昨天 {t.tm_hour:02d}:{t.tm_min:02d}"
        return time.strftime("%m-%d %H:%M", t)
    except Exception:
        return '?'


# ---- 此刻状态条 (顶部) ----

def read_now_status() -> Dict:
    """🤖 此刻贾维斯在做什么 — 顶部状态条"""
    out = {
        'wall_clock': time.strftime('%H:%M:%S'),
        'today_zh': time.strftime('%Y-%m-%d %A'),
        'session_id': '',
        'session_age': '',
        'in_conversation': '?',
        'log_age': '?',
        'log_path': '',
    }
    log = _find_latest_log()
    out['log_path'] = log
    if not log:
        return out
    try:
        head_size = min(os.path.getsize(log), 4096)
        with open(log, 'r', encoding='utf-8', errors='ignore') as f:
            head = f.read(head_size)
            # 也尝试 tail
            if os.path.getsize(log) > 4096:
                f.seek(max(0, os.path.getsize(log) - 4096))
                f.readline()
                tail = f.read()
            else:
                tail = head
        m = re.search(r'sess_(\d{8}_\d{6})_(\d+)', head)
        if m:
            out['session_id'] = m.group(0)
            # session 起点时间
            try:
                tstr = m.group(1)
                t = time.strptime(tstr, '%Y%m%d_%H%M%S')
                out['session_age'] = _humanize_age_zh(time.mktime(t))
            except Exception:
                pass
        try:
            log_mtime = os.path.getmtime(log)
            out['log_age'] = _humanize_age_zh(log_mtime)
        except Exception:
            pass
        # 推断 in_conversation
        if re.search(r'_bypass_speech_count|active_conversation.*True|focus_lock|wake_word_detected',
                     tail):
            out['in_conversation'] = '在对话中'
        else:
            out['in_conversation'] = '空闲观察中'
    except Exception:
        pass
    return out


# ---- 待办 (Sir Commitments from SQLite) ----

def read_sir_commitments() -> Dict:
    """📋 你要他盯的事 — Commitments 表"""
    out = {'rows': [], 'count_pending': 0, 'count_done': 0, 'err': None}
    db = os.path.join(MEM, 'jarvis_memory.db')
    if not os.path.exists(db):
        out['err'] = '记忆数据库不存在'
        return out
    try:
        # 🩹 [β.2.9.8 fix v2 / 2026-05-18] Sir 10:34 实测 "unable to open database
        # file" — 旧 nolock=1 + mode=ro 在 Windows 不兼容主程序锁. immutable=1
        # 又会缓存使按钮 cancel 后看不到变化. 换最简方案: 默认连接 + 短 timeout,
        # 主程序短暂写锁等 1s 即可, 不缓存. (主程序写也是短交易, 几乎不冲突.)
        conn = sqlite3.connect(db, timeout=1.0)
        # 设 read_uncommitted 不必抢写锁
        conn.execute("PRAGMA read_uncommitted=1")
        try:
            cur = conn.execute(
                "SELECT id, description, deadline_ts, nudged, is_deleted, "
                "       source_text, created_at "
                "FROM Commitments ORDER BY deadline_ts DESC LIMIT 50"
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        now = time.time()
        for rid, desc, dl, nudged, deleted, src, created in rows:
            if deleted:
                continue
            if nudged:
                state = 'done'
                state_zh = '✓ 已提过'
                out['count_done'] += 1
            elif dl and dl > now:
                state = 'pending'
                state_zh = '⏳ 待到点'
                out['count_pending'] += 1
            elif dl and dl <= now:
                state = 'overdue'
                state_zh = '⏰ 超时未提'
                out['count_pending'] += 1
            else:
                state = 'unknown'
                state_zh = '?'
            out['rows'].append({
                'id': rid,
                'desc': (desc or '')[:80],
                'when': _humanize_when_zh(dl) if dl else '--',
                'state': state,
                'state_zh': state_zh,
                'age': _humanize_age_zh(created or 0),
            })
        out['rows'] = out['rows'][:15]
    except Exception as e:
        out['err'] = f'读 Commitments: {e}'

    # 📌 诊断
    if out.get('err'):
        out['diagnosis'] = f'❌ 读取异常: {out["err"]}'
        out['suggestion'] = '看看 memory_pool/jarvis_memory.db 是否正常'
    elif out['count_pending'] == 0:
        out['diagnosis'] = '✅ 没有待到点的提醒'
        out['suggestion'] = '无需操作'
    elif out['count_pending'] >= 5:
        out['diagnosis'] = f'📝 你设了 {out["count_pending"]} 件等到点 — 别忘'
        out['suggestion'] = '不想要的点 "🚫 取消" 按钮'
    else:
        # 看是否有 overdue
        overdue = [r for r in out['rows'] if r['state'] == 'overdue']
        if overdue:
            out['diagnosis'] = (
                f'⏰ {len(overdue)} 件超时未提 (贾维斯可能漏了)')
            out['suggestion'] = '看是否真要; 不要就 🚫 取消'
        else:
            out['diagnosis'] = f'⏳ {out["count_pending"]} 件待到点'
            out['suggestion'] = '到点贾维斯会主动提醒你'
    return out


# ---- 贾维斯口头承诺 (PromiseLog) ----

def read_jarvis_promises() -> Dict:
    """🤝 贾维斯口头承诺 — PromiseLog (β.5.30: 按 author 区分 jarvis/sir 双账本).

    🩹 [β.5.30 / 2026-05-20] Sir 03:35 反馈"我承诺和 jarvis 承诺要分明白".
    老版混在一起 (Sir 自己说"我两点睡"也算 Jarvis 承诺) → 言行不一信号误报.
    修法: 返 jarvis_* (Jarvis 自己说的) + sir_* (Sir 自己说的) 双账本.
    """
    out = {
        'rows': [],          # 兼容老 API: jarvis 部分
        'pending_n': 0, 'fulfilled_n': 0, 'untracked_n': 0,
        'total': 0,
        # β.5.30 新: 分账本
        'jarvis_rows': [], 'jarvis_pending_n': 0, 'jarvis_fulfilled_n': 0,
        'jarvis_untracked_n': 0, 'jarvis_total': 0,
        'sir_rows': [], 'sir_pending_n': 0, 'sir_fulfilled_n': 0,
        'sir_untracked_n': 0, 'sir_total': 0,
        'err': None,
    }
    data = _safe_read_json(os.path.join(MEM, 'jarvis_promise_log.json'), {})
    if not isinstance(data, dict):
        out['err'] = 'promise_log 格式异常'
        return out
    promises = list(data.values())
    promises.sort(key=lambda p: -float(p.get('registered_at', 0) or 0))

    st_zh_map = {
        'pending': '⏳ 还没动',
        'fulfilled': '✓ 已兑现',
        'overdue': '⏰ 超时',
        'untracked': '❓ 没监控到',
        'cancelled': '🚫 已撤销',
    }
    for p in promises:
        st = p.get('state', '?')
        author = p.get('author', 'jarvis')  # 老数据无字段默认 jarvis
        out['total'] += 1
        bucket = 'sir' if author == 'sir' else 'jarvis'
        if st == 'pending':
            out[f'{bucket}_pending_n'] += 1
        elif st == 'fulfilled':
            out[f'{bucket}_fulfilled_n'] += 1
        elif st == 'untracked':
            out[f'{bucket}_untracked_n'] += 1
        out[f'{bucket}_total'] += 1

    # 老 API 兼容: rows/*_n 只算 jarvis (Sir 通常 view 的"言行不一"指 Jarvis)
    out['pending_n'] = out['jarvis_pending_n']
    out['fulfilled_n'] = out['jarvis_fulfilled_n']
    out['untracked_n'] = out['jarvis_untracked_n']

    for p in promises[:30]:
        st = p.get('state', '?')
        author = p.get('author', 'jarvis')
        row = {
            'id': p.get('id', '?'),
            'state': st,
            'state_zh': st_zh_map.get(st, st),
            'kind': p.get('kind', '?'),
            'author': author,
            'desc': (p.get('description') or '')[:80],
            'when': p.get('deadline_str') or '-',
            'age': _humanize_age_zh(float(p.get('registered_at', 0) or 0)),
            'evidence_n': len(p.get('evidence', []) or []),
        }
        if author == 'sir':
            if len(out['sir_rows']) < 15:
                out['sir_rows'].append(row)
        else:
            if len(out['jarvis_rows']) < 15:
                out['jarvis_rows'].append(row)
                out['rows'].append(row)  # 老 API 兼容

    # 📌 诊断 — 言行一致的关键指标
    if out['total'] == 0:
        out['diagnosis'] = '✅ 干净 — 贾维斯没有未兑现的口头承诺'
        out['suggestion'] = '无需操作'
    elif out['untracked_n'] > 3:
        out['diagnosis'] = (
            f'❌ {out["untracked_n"]} 件贾维斯说过却没监控到 — 言行不一信号')
        out['suggestion'] = (
            '看详情: scripts/promise_tail.py; '
            '清残留: scripts/promise_log_reset.py --apply --keep-fulfilled')
    elif out['pending_n'] > 5:
        out['diagnosis'] = f'📝 {out["pending_n"]} 件挂着 — 贾维斯许诺了但还没动'
        out['suggestion'] = '可清残留: scripts/promise_log_reset.py --apply'
    elif out['pending_n'] > 0:
        out['diagnosis'] = (
            f'⏳ {out["pending_n"]} 件挂着 / {out["fulfilled_n"]} 件已兑')
        out['suggestion'] = '到点会自动兑现或转 untracked, 无需操作'
    else:
        out['diagnosis'] = f'✅ 全部兑现 ({out["fulfilled_n"]} 件)'
        out['suggestion'] = '言行一致, 无需操作'
    return out


# ---- L1 Concerns (贾维斯长期惦记) ----

def read_concerns() -> Dict:
    """🎯 贾维斯长期惦记你的什么 — Concerns L1"""
    out = {'rows': [], 'review_n': 0, 'err': None}
    data = _safe_read_json(os.path.join(MEM, 'concerns.json'), {})
    concerns = data.get('concerns', {}) if isinstance(data, dict) else {}
    if not concerns and isinstance(data, dict):
        concerns = data
    active = [(cid, c) for cid, c in concerns.items()
              if isinstance(c, dict) and c.get('state') == 'active']
    active.sort(key=lambda x: -float(x[1].get('severity', 0)))

    # 人话翻译 (id → 中文)
    _CONCERN_ZH = {
        'sir_sleep_streak': '你最近睡眠',
        'sir_pomodoro_compliance': '你的工作-休息节奏',
        'sir_hydration_habit': '你喝水',
        'sir_cursor_payment': 'Cursor 订阅状态',
        'sir_jiazhao_progress': '驾照科一进度',
        'unfinished_project_jiazhao': '驾照科一项目',
        'jarvis_keyrouter_health': '我自己的 API key 池子健康',
    }

    for cid, c in active[:10]:
        sev = float(c.get('severity', 0))
        sigs = c.get('recent_signals', []) or []
        last_sig = max((s.get('when', 0) for s in sigs), default=0)
        aligned = int(c.get('aligned_count', 0))
        missed = int(c.get('missed_count', 0))
        # 偏移信号: missed > aligned + sev > 0.7 → 警告
        warn = '⚠️' if missed > aligned and sev > 0.6 else ''
        out['rows'].append({
            'id': cid,
            'zh_name': _CONCERN_ZH.get(cid, cid),
            'severity_pct': int(sev * 100),
            'severity': sev,
            'what': (c.get('what_i_watch') or '')[:80],
            'aligned': aligned,
            'missed': missed,
            'sig_n': len(sigs),
            'last_sig': _humanize_age_zh(last_sig),
            'last_trigger': _humanize_age_zh(float(c.get('last_triggered', 0) or 0)),
            'warn': warn,
        })
    review = _safe_read_json(os.path.join(MEM, 'concerns_review.json'), [])
    if isinstance(review, list):
        out['review_n'] = len(review)
    elif isinstance(review, dict):
        items = review.get('proposals', review)
        if isinstance(items, list):
            out['review_n'] = len(items)

    # 📌 诊断
    if not out['rows']:
        out['diagnosis'] = '✅ 平静 — 贾维斯没在惦记什么'
        out['suggestion'] = '正常运行, 无需操作'
    else:
        max_sev = out['rows'][0]['severity_pct'] if out['rows'] else 0
        critical = [r for r in out['rows'] if r['severity_pct'] >= 85]
        warned = [r for r in out['rows'] if r['warn']]
        if critical:
            top = critical[0]['zh_name']
            out['diagnosis'] = (
                f'⚠️ "{top}" 紧迫度 {critical[0]["severity_pct"]}% '
                f'— 贾维斯准备主动提醒了')
            out['suggestion'] = (
                '真去做 → 紧迫度自动衰减; 或对贾维斯说 "别催了" → 24h 静默')
        elif warned:
            out['diagnosis'] = (
                f'📝 {len(warned)} 件"没理过" > "听过", 贾维斯有点失望')
            out['suggestion'] = '挑一件回应他, 或调整: scripts/concerns_dump.py'
        else:
            out['diagnosis'] = (
                f'✅ 平稳 — 最严重 {max_sev}% (< 85% 还不会主动催)')
            out['suggestion'] = '让贾维斯继续观察, 无需操作'
    return out


# ---- L2 Relational (你们之间的默契) ----

def read_relational() -> Dict:
    """💞 你们之间的默契 — RelationalState L2

    🩹 [β.5.28-fix5 / 2026-05-20] Sir 03:11 反馈"拍板 y 后显示在哪? 什么地方都没增加".
    Root cause: 老版漏读 shared_history_threads (共同经历). Sir 通过的 thread → state=active
    但 read 不出来 → Sir 看不到. 修法: 加 'threads' 字段.
    """
    out = {'jokes': [], 'protocols': [], 'unfinished': [], 'threads': [],
           'review_n': 0, 'err': None}
    data = _safe_read_json(os.path.join(MEM, 'relational_state.json'), {})
    if not isinstance(data, dict):
        out['err'] = 'relational 格式异常'
        return out

    def _items(key):
        v = data.get(key, {})
        if isinstance(v, dict):
            return list(v.values())
        if isinstance(v, list):
            return v
        return []

    for j in _items('inside_jokes')[:5]:
        if not isinstance(j, dict) or j.get('state', 'active') != 'active':
            continue
        out['jokes'].append({
            'phrase': (j.get('phrase') or '')[:70],
            'birth': _humanize_age_zh(float(j.get('birth_ts', j.get('created_at', 0)) or 0)),
            'used': int(j.get('use_count', 0)),
        })
    for p in _items('unspoken_protocols')[:6]:
        if not isinstance(p, dict) or p.get('state', 'active') != 'active':
            continue
        out['protocols'].append({
            'rule': (p.get('rule') or '')[:80],
            'violations': len(p.get('violations', []) or []),
        })
    for u in _items('unfinished_business')[:5]:
        if not isinstance(u, dict):
            continue
        out['unfinished'].append({
            'topic': (u.get('topic') or '')[:70],
            'last': _humanize_age_zh(
                float(u.get('last_referenced', u.get('last_touched', 0)) or 0)),
        })
    # 🩹 [β.5.28-fix5] 共同经历 - Sir 通过的 thread 落地处!
    for t in _items('shared_history_threads')[:10]:
        if not isinstance(t, dict) or t.get('state', 'active') != 'active':
            continue
        # 取 highlights[0].what 作为简介
        hl = t.get('highlights') or []
        what = ''
        if hl and isinstance(hl, list) and isinstance(hl[0], dict):
            what = (hl[0].get('what') or '')[:100]
        out['threads'].append({
            'id': t.get('id', '?'),
            'title': (t.get('title') or '')[:60],
            'what': what,
            'started': _humanize_age_zh(
                float(t.get('started_at', t.get('created_at', 0)) or 0)),
            'last_milestone': _humanize_age_zh(
                float(t.get('last_milestone_at', t.get('last_updated', 0)) or 0)),
            'n_highlights': len(hl) if isinstance(hl, list) else 0,
        })
    review = _safe_read_json(os.path.join(MEM, 'relational_review.json'), [])
    if isinstance(review, list):
        out['review_n'] = len(review)
    elif isinstance(review, dict):
        # 🩹 [β.5.39-fix / 2026-05-20] 排除 _meta 等下划线 key, 防 review_n=2 误算
        out['review_n'] = sum(
            len(v) for k, v in review.items()
            if not k.startswith('_') and isinstance(v, (list, dict))
        )

    # 📌 诊断
    total = len(out['jokes']) + len(out['protocols']) + len(out['unfinished'])
    if total == 0 and out['review_n'] == 0:
        out['diagnosis'] = '📝 还在学你 — 贾维斯还没积累跟你之间的"老朋友感"'
        out['suggestion'] = '多聊几天自然会有; 也可手动录: scripts/relational_dump.py'
    elif out['review_n'] > 0:
        out['diagnosis'] = (
            f'⚠️ {out["review_n"]} 条"是不是新默契"的提案等你拍板')
        out['suggestion'] = '点 "处理这批" 按钮 → 开终端逐条 ✅/❌'
    else:
        unread = [u for u in out['unfinished'] if '天前' in u['last']]
        if unread:
            out['diagnosis'] = (
                f'📌 你停了 {len(unread)} 件没继续, 贾维斯还记着')
            out['suggestion'] = '想关掉某件: scripts/relational_dump.py --close <id>'
        else:
            out['diagnosis'] = '✅ 你们之间健康'
            out['suggestion'] = '无需操作'
    return out


# ---- L2 Directive Registry (贾维斯临时提醒规则 + 偏移信号) ----

# 人话翻译 (Sir 看不懂的 directive id → 大白话)
_DIRECTIVE_ZH = {
    'nudge_agenda_honesty':
        '催办诚实 — 别假装"已经把提醒删了"',
    'continuity_two_parts':
        '复合句两段答 — 你说两个意图时不要混答',
    'tool_honesty_directive':
        '工具失败要承认 — 别说"已完成"',
    'fuzzy_candidates_policy':
        '模糊匹配要确认 — 别瞎猜执行',
    'promise_protocol_directive':
        '承诺协议 — 真要承诺时用结构化标签',
    'bilingual_directive':
        '中英双语 — 每句回复后追加中文翻译',
    'search_directive':
        '搜索时机 — 什么场景该调搜索',
    'memory_callback':
        '记忆回调 — 引用过去对话',
    'image_context':
        '图片上下文 — 看到截图怎么用',
    'system_environment':
        '系统环境 — 知道当前 Windows / 时区',
    'smart_routing_working_feed':
        '智能路由 — 给主脑塞最近 30min 工作状态',
    'correction_writepath_no_tool':
        '纠正记忆不要假调工具 — 直接改记忆',
    'reminder_read_truth_source':
        '念提醒以 DB 为准 — 不要凭空捏造',
    'future_tense_capability_check':
        '未来时撒谎检查 — 别说"我会..."但其实没能力',
}


def read_directives() -> Dict:
    """📜 贾维斯的临时提醒规则 (Directive) + 偏移信号 — registry"""
    out = {'rows': [], 'total': 0, 'review_n': 0, 'err': None,
           'health': {'ok': 0, 'untriggered': 0, 'low_help': 0, 'candidate_merge': 0}}
    data = _safe_read_json(os.path.join(MEM, 'directive_registry.json'), {})
    if not isinstance(data, dict):
        out['err'] = 'directive_registry 格式异常'
        return out
    out['total'] = len(data)
    now = time.time()
    for did, info in data.items():
        if not isinstance(info, dict):
            continue
        fired = int(info.get('fired', 0))
        helped = int(info.get('helped', 0))
        rejected = int(info.get('rejected', 0))
        last_fired = float(info.get('last_triggered', 0) or 0)
        help_rate = (helped / fired * 100) if fired > 0 else 0
        reject_rate = (rejected / fired * 100) if fired > 0 else 0
        age_since_fire = (now - last_fired) if last_fired > 0 else float('inf')

        # 偏移信号 — Sir 准则 11.A: 监测 directive 健康
        if fired == 0 and age_since_fire > 14 * 86400:
            health = '❌'
            health_zh = '长期空转 (≥14d 没触发)'
            out['health']['untriggered'] += 1
        elif fired >= 5 and help_rate < 30:
            health = '⚠️'
            health_zh = f'触发{fired}次但只帮了{help_rate:.0f}% — 可能没用了'
            out['health']['low_help'] += 1
        elif help_rate > 90 and fired >= 20:
            health = '🌟'
            health_zh = f'帮助率 {help_rate:.0f}% — 建议合并进核心人设'
            out['health']['candidate_merge'] += 1
        else:
            health = '✅'
            health_zh = '正常'
            out['health']['ok'] += 1

        out['rows'].append({
            'id': did,
            'zh_name': _DIRECTIVE_ZH.get(did, did),
            'fired': fired,
            'helped': helped,
            'rejected': rejected,
            'help_rate': help_rate,
            'last_fired_zh': _humanize_age_zh(last_fired),
            'health': health,
            'health_zh': health_zh,
            'priority': int(info.get('priority', 5)),
        })
    # 按健康状态排序: ⚠️/❌ 在前 (需关注), ✅ 在后
    health_order = {'❌': 0, '⚠️': 1, '🌟': 2, '✅': 3}
    out['rows'].sort(key=lambda r: (health_order.get(r['health'], 9), -r['fired']))

    review = _safe_read_json(os.path.join(MEM, 'directive_review.json'), [])
    if isinstance(review, list):
        out['review_n'] = len(review)
    elif isinstance(review, dict):
        out['review_n'] = sum(
            len(v) for v in review.values() if isinstance(v, list)
        )

    # 📌 诊断 — Sir 准则 11.A: directive 偏移信号
    h = out['health']
    offset = h.get('untriggered', 0) + h.get('low_help', 0)
    if out['total'] == 0:
        out['diagnosis'] = '⚠️ 规则未加载'
        out['suggestion'] = '重启贾维斯应自动 bootstrap 14 条'
    elif offset >= 5:
        worst = next((r for r in out['rows'] if r['health'] != '✅'), None)
        worst_name = worst['zh_name'] if worst else '?'
        out['diagnosis'] = (
            f'⚠️ {offset} 条规则跑偏 — 主脑可能不再听 ({h.get("low_help", 0)} 条) '
            f'或场景已废 ({h.get("untriggered", 0)} 条)')
        out['suggestion'] = (
            f'最严重: "{worst_name}". 找 Agent review: '
            f'scripts/registry_dump.py')
    elif offset > 0:
        out['diagnosis'] = (
            f'📝 {offset} 条规则有小问题, 不急')
        out['suggestion'] = '等 7d 看是否回正; 或主动 review'
    elif h.get('candidate_merge', 0) > 0:
        out['diagnosis'] = (
            f'🌟 {h["candidate_merge"]} 条已是 baseline (帮助率 90%+), '
            f'可考虑并入核心人设')
        out['suggestion'] = '让 Agent 评估: 是否把"高效"规则永久写入 PERSONA'
    else:
        out['diagnosis'] = f'✅ {out["total"]} 条规则全健康 — 主脑听得进, 触发合理'
        out['suggestion'] = '无需操作'
    return out


# ---- Daemon 状态 ----

# 🩹 [β.3.0 / 2026-05-18] Sir 16:18 实测 BUG: dashboard 看到 0/12 daemon, 但 Sir
# 主进程实际在跑. 真因: 测试 fixture (_runall.ps1) 写 latest.txt 短小测试 log,
# dashboard 误把它当主进程 log → 找不到 daemon banner. 治本: 跳过 < 5KB 的 log.
_MIN_REAL_LOG_BYTES = 5_000  # 测试 fixture log < 2KB, 主进程 log 通常 ≥ 50KB


def _find_latest_log() -> str:
    pointer = os.path.join(LOG_DIR, 'latest.txt')
    if os.path.exists(pointer):
        try:
            with open(pointer, 'r', encoding='utf-8', errors='ignore') as f:
                p = f.read().strip()
                cand = None
                if os.path.isabs(p) and os.path.exists(p):
                    cand = p
                elif os.path.exists(os.path.join(ROOT, p)):
                    cand = os.path.join(ROOT, p)
                # 🩹 [β.3.0 Sir 16:18] verify 不是测试 log
                if cand and os.path.getsize(cand) >= _MIN_REAL_LOG_BYTES:
                    return cand
                # 测试 log 太小, 跳过 pointer 走兜底扫描
        except Exception:
            pass
    if not os.path.isdir(LOG_DIR):
        return ''
    cands = []
    for f in os.listdir(LOG_DIR):
        if f.startswith('jarvis_') and f.endswith('.log'):
            full = os.path.join(LOG_DIR, f)
            try:
                # 🩹 [β.3.0 Sir 16:18] 跳过 < 5KB 测试 fixture log
                if os.path.getsize(full) < _MIN_REAL_LOG_BYTES:
                    continue
                cands.append((os.path.getmtime(full), full))
            except OSError:
                continue
    if not cands:
        return ''
    cands.sort(reverse=True)
    return cands[0][1]


_DAEMON_REGISTRY = [
    # (id, zh_name, banner_regex)
    ('SmartNudge', '轻推 (喝水/休息提醒)',
     r'\[CompanionCenter\].*SmartNudgeSentinel'),
    ('ProactiveCare', '主动关心 (按你长期关心的事说话)',
     r'\[CompanionCenter\].*ProactiveCareEngine.*?mode=(\w+[-\w]*)'),
    ('Inconsistency', '言行反差检测 (你说一套做另一套时提醒)',
     r'\[CompanionCenter\].*InconsistencyWatcher'),
    ('Curiosity', '好奇心 (你专注太久时随口问一句)',
     r'\[CompanionCenter\].*CuriosityDaemon'),
    ('PromiseSweep', '承诺扫描 (24h 没动静的承诺标"没做到")',
     r'\[CompanionCenter\].*PromiseSweepDaemon'),
    ('HealthProbe', '健康自检 (每 5min 看自己内存/CPU)',
     r'\[CompanionCenter\].*HealthProbeDaemon'),
    ('Return', '归来感知 (你 AFK 回来时打招呼)',
     r'\[ReturnSentinel/Health\]'),
    ('Commitment', '提醒守门 (你设的提醒到点触发)',
     r'\[CommitmentWatcher\]'),
    # 🩹 [β.5.28 / 2026-05-20] Sir 02:50 反馈 '3 个 daemon 不运行'.
    # Root cause: regex 跟实际 print banner 不匹配 → grep miss → 显灰但 daemon 真在跑.
    # - ChronosTick: 老 run() 完全没 print banner. 加 banner (jarvis_sentinels.py:361).
    # - UserStatusLedger: print '[StatusLedger]' 不是 '[UserStatusLedger]'. regex 加 StatusLedger.
    # - SoulArchivist / ScreenshotSentinel: print banner 在, regex 应能匹配.
    ('Chronos', '心跳起搏 (每秒看一眼系统时间)',
     r'起搏器|ChronosTick|\[ChronosTick\]|Chronos.*就绪'),
    ('SoulArchivist', '灵魂归档 (Sir 长期 profile 演化)',
     r'SoulArchivist'),
    ('ScreenshotSentinel', '截屏哨兵 (定期抓你屏幕看你在干啥)',
     r'ScreenshotSentinel|截屏哨兵'),
    ('UserStatusLedger', 'Sir 状态账本 (生理/情绪/活动历史快照)',
     r'UserStatusLedger|\[StatusLedger\]|状态台账|异步增量更新引擎就绪'),
]


def read_daemon_status() -> Dict:
    """💡 后台管家 — 17 daemon 是否在跑"""
    out = {'daemons': [], 'log_path': '', 'err': None}
    log = _find_latest_log()
    out['log_path'] = log
    if not log or not os.path.exists(log):
        out['err'] = '找不到最近的运行日志'
        return out
    try:
        with open(log, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception as e:
        out['err'] = f'读 log: {e}'
        return out

    for did, zh, pat in _DAEMON_REGISTRY:
        m = re.search(pat, content, re.IGNORECASE)
        extra = ''
        if m and m.groups():
            extra = f' [{m.group(1)}]'
        out['daemons'].append({
            'id': did,
            'zh': zh,
            'live': bool(m),
            'extra': extra,
        })
    # ProactiveCare 加 LIVE/DRY 状态
    if re.search(r'\[ProactiveCare/LIVE\]', content):
        for d in out['daemons']:
            if d['id'] == 'ProactiveCare':
                d['extra'] = ' [LIVE 已发声]'
    elif re.search(r'\[ProactiveCare/DRY\]', content):
        for d in out['daemons']:
            if d['id'] == 'ProactiveCare':
                d['extra'] = ' [DRY-RUN]'

    # 🩹 [β.3.0 / 2026-05-18] Sir 16:18 实测 BUG: log 是冷的 (5min 前最后写入)
    # → 主进程已退出 → daemon 全 0 是预期, 不应该恐吓 Sir "管家未启动".
    # 治本: 看 log mtime 判主进程在不在跑.
    try:
        log_age_s = time.time() - os.path.getmtime(log)
    except Exception:
        log_age_s = 0
    out['log_age_s'] = int(log_age_s)
    is_cold = log_age_s > 300  # 5 min 没新写入 = 主进程已退或卡死
    out['main_process_cold'] = is_cold

    # 📌 诊断
    live = sum(1 for x in out['daemons'] if x['live'])
    total = len(out['daemons'])
    crit_offline = [x for x in out['daemons']
                     if not x['live'] and x['id'] in
                     ('ProactiveCare', 'Inconsistency', 'HealthProbe',
                      'Return', 'Commitment')]
    if is_cold:
        # 🩹 [β.3.0] 主进程冷 — 不恐吓"管家未启动", 报告真因
        mins = int(log_age_s / 60)
        out['diagnosis'] = (
            f'💤 主进程未在跑 (日志已冷 {mins} 分钟) — '
            f'daemon 0/{total} 是预期'
        )
        out['suggestion'] = '启动贾维斯主程序: python jarvis_nerve.py'
    elif live == total:
        out['diagnosis'] = f'✅ 全部 {total} 个后台在跑'
        out['suggestion'] = '无需操作'
    elif crit_offline:
        names = '、'.join(x['zh'].split(' (')[0] for x in crit_offline[:3])
        out['diagnosis'] = (
            f'❌ 关键管家未启动: {names}')
        out['suggestion'] = '重启贾维斯主程序; 或看 log 找启动报错'
    else:
        offline_names = [x['id'] for x in out['daemons'] if not x['live']]
        out['diagnosis'] = (
            f'📝 {live}/{total} 在跑. 没匹配的 {len(offline_names)} 个'
            f' (可能 banner 短启动 / 此 log 已老)')
        out['suggestion'] = '看新 log 应该更全; 不影响功能'
    return out


# ---- 系统健康 ----

def read_system_health() -> Dict:
    """📊 贾维斯自己健不健康"""
    out = {'health_last': {}, 'health_trend': {}, 'key_router': {},
           'log_size_mb': 0.0, 'log_count': 0, 'err': None}
    history = _safe_read_jsonl(
        os.path.join(MEM, 'jarvis_health_history.jsonl'), tail=300)
    if history:
        last = history[-1]
        out['health_last'] = {
            'iso': last.get('iso', '?'),
            'ws_mb': last.get('ws_mb', 0),
            'private_mb': last.get('private_mb', 0),
            'threads': last.get('threads', 0),
            'handles': last.get('handles', 0),
        }
        cutoff = time.time() - 24 * 3600
        recent = [h for h in history if h.get('ts', 0) >= cutoff]
        if recent:
            out['health_trend'] = {
                'samples': len(recent),
                'ws_mb_max': max(r.get('ws_mb', 0) for r in recent),
                'ws_mb_min': min(r.get('ws_mb', 0) for r in recent),
                'threads_max': max(r.get('threads', 0) for r in recent),
            }
    kr = _safe_read_json(os.path.join(MEM, 'key_router_state.json'), {})
    if isinstance(kr, dict):
        dead = [k for k, v in kr.items()
                if isinstance(v, dict) and v.get('permanently_dead')]
        out['key_router'] = {
            'total': len(kr),
            'dead_n': len(dead),
            'dead_keys': dead,
        }
    if os.path.isdir(LOG_DIR):
        total = 0
        n = 0
        for f in os.listdir(LOG_DIR):
            if f.startswith('jarvis_') and f.endswith('.log'):
                try:
                    total += os.path.getsize(os.path.join(LOG_DIR, f))
                    n += 1
                except OSError:
                    pass
        out['log_size_mb'] = round(total / 1024 / 1024, 1)
        out['log_count'] = n

    # 📌 诊断
    issues = []
    ws_mb = out['health_last'].get('ws_mb', 0)
    if ws_mb > 4000:
        issues.append(f'内存 {ws_mb:.0f}MB 偏高 (> 4GB)')
    if ws_mb > 0 and ws_mb < 1000:
        issues.append(f'内存 {ws_mb:.0f}MB 偏低 (贾维斯可能没启)')
    kr_dead = out['key_router'].get('dead_n', 0)
    if kr_dead > 0:
        issues.append(f'{kr_dead} 把 API key 死了')
    if out['log_size_mb'] > 50:
        issues.append(f'历史日志 {out["log_size_mb"]:.0f}MB (建议清旧)')
    if not issues:
        out['diagnosis'] = '✅ 系统健康 (内存正常 / API 全活 / 日志合理)'
        out['suggestion'] = '无需操作'
    elif kr_dead > 0:
        out['diagnosis'] = '⚠️ ' + ' · '.join(issues)
        out['suggestion'] = '重启贾维斯可能恢复 API key; 或登 OpenRouter 看 quota'
    else:
        out['diagnosis'] = '📝 ' + ' · '.join(issues)
        out['suggestion'] = (
            '日志清理: Get-ChildItem docs/runtime_logs -Recurse | '
            'Where LastWriteTime -lt (Get-Date).AddDays(-7) | Remove-Item')
    return out


# ---- 待审阅队列 ----

def read_memory_mutations() -> Dict:
    """🔬 信任审计 — Jarvis 今天真改了什么.

    🩹 [β.2.9.9 / 2026-05-18] Sir 10:51 诚信审计治本卡片. 显示:
      - 今天写入 N 条 (Jarvis 真"改记忆"几次)
      - 最近 5 条 detail (field / old → new / source / 时间)
      - 诊断: ✅ 真做了 / ⚠️ 今天 0 条 (主脑可能空头说"已更新")

    🆕 [P5-fix35 / 2026-05-23 BUG#7] 合并 2 源 audit:
      - profile_corrections.jsonl (β.2.9.9, ProfileCard.apply_correction 路径)
      - mutation_receipts.jsonl (P5-fix32, MemoryGateway 6-layer 新路径)
      按 ts 排序合并, Sir 一处看全.
    """
    out = {'today_n': 0, 'total_n': 0, 'rows': [],
           'sources': {}, 'err': None}
    pc_path = os.path.join(MEM, 'profile_corrections.jsonl')
    mr_path = os.path.join(MEM, 'mutation_receipts.jsonl')

    records = []
    errs = []
    try:
        if os.path.exists(pc_path):
            for r in _safe_read_jsonl(pc_path, tail=300):
                r2 = dict(r)
                r2['_origin'] = 'profile_corrections'
                records.append(r2)
    except Exception as e:
        errs.append(f'pc:{e}')
    try:
        if os.path.exists(mr_path):
            # mutation_receipts schema 跟 profile_corrections 不同, 转齐
            for r in _safe_read_jsonl(mr_path, tail=300):
                records.append({
                    'ts': r.get('ts', 0),
                    'time': (r.get('iso', '') or '')[-8:] or '?',
                    'iso': r.get('iso', ''),
                    'source': r.get('source', '?'),
                    'field': r.get('field_path', ''),
                    'old': r.get('old_value_excerpt', ''),
                    'new': r.get('new_value_excerpt', ''),
                    'confidence': r.get('confidence', 0),
                    '_origin': 'mutation_receipts',
                    '_layer': r.get('layer_targeted', ''),
                    '_mutation_id': r.get('mutation_id', ''),
                    '_ok': r.get('ok', True),
                })
    except Exception as e:
        errs.append(f'mr:{e}')

    if errs:
        out['err'] = '; '.join(errs)
    if not records:
        out['diagnosis'] = '📝 还没有任何记忆变更记录'
        out['suggestion'] = (
            '正常 — 触发 ProfileCard.apply_correction / FAST_CALL mutation organ '
            '/ <MEMORY_UPDATE> 标签后产生.'
        )
        return out

    # 按 ts 排序 (旧→新)
    records.sort(key=lambda r: r.get('ts', 0) or 0)
    out['total_n'] = len(records)
    now = time.time()
    today_start = now - (now % 86400) - time.timezone  # 本地今日 00:00
    today_records = [r for r in records if r.get('ts', 0) >= today_start]
    out['today_n'] = len(today_records)
    # source 分布
    src_counter = {}
    for r in records:
        s = r.get('source', '?')
        # 截短 source label (e.g. 'fast_call_mutation:update:intent=revise' → 取前段)
        s_short = s.split(':', 1)[0] if ':' in s else s
        src_counter[s_short] = src_counter.get(s_short, 0) + 1
    out['sources'] = src_counter
    # 最近 12 条
    for r in records[-12:]:
        out['rows'].append({
            'time': r.get('time', '?'),
            'iso': r.get('iso', ''),
            'age': _humanize_age_zh(r.get('ts', 0)),
            'source': r.get('source', '?'),
            'field': str(r.get('field', ''))[:40],
            'old': str(r.get('old', ''))[:60],
            'new': str(r.get('new', ''))[:60],
            'confidence': float(r.get('confidence', 0) or 0),
            'origin': r.get('_origin', ''),
            'layer': r.get('_layer', ''),
            'mutation_id': r.get('_mutation_id', ''),
            'ok': r.get('_ok', True),
        })
    out['rows'].reverse()  # 最新在上

    # 📌 诊断
    if out['today_n'] == 0 and out['total_n'] == 0:
        out['diagnosis'] = '⚪ 全程 0 次记忆变更 — 系统还没触发过 apply_correction'
        out['suggestion'] = (
            'Sir 跟 Jarvis 纠正记忆 (如"职业考试 vs 成绩") 后, 应该出现新记录. '
            '若 Sir 说了纠正但这里仍 0 → 主脑在撒"已更新"假话, 应触发 '
            'memory_update_honesty directive 拦截'
        )
    elif out['today_n'] == 0 and out['total_n'] > 0:
        last_iso = records[-1].get('iso', '?') if records else '?'
        out['diagnosis'] = (
            f'⚠️ 今天 0 条记忆变更 (上次是 {last_iso}) — 主脑可能在空头说"已更新"'
        )
        out['suggestion'] = (
            '看主对话 log: Sir 如有纠正话语 ("不是/其实/澄清/两码事") + Jarvis '
            '回 "I\'ve updated", 但这里 0 条 → 是诚信 BUG'
        )
    elif out['today_n'] > 5:
        out['diagnosis'] = f'📈 今天 {out["today_n"]} 条记忆变更 — 活跃学习中'
        out['suggestion'] = '正常 — Sir 多次纠正/澄清产生的真写入'
    else:
        out['diagnosis'] = f'✅ 今天 {out["today_n"]} 条真写入 (言行一致)'
        out['suggestion'] = '主脑用 MEMORY_UPDATE 标签或 ProfileCard 触发真改了'
    return out


# 🩹 [β.4.4 / 2026-05-18] Sir Session 3: INTEGRITY_STACK L6 dashboard 信任卡升级.
# 读 memory_pool/integrity_audit.jsonl (L4 ClaimTracer 写入, 仅 unverified 入表) +
# memory_pool/claim_stats.json (Session 4 daemon 未来加, 此处 fail-safe 兼容缺失).
#
# 真机风险点 (KICKOFF Session 3 §):
#   1. jsonl 可能 > 100K 条 → 用 _safe_read_jsonl_tail (file seek -512KB) 防全 load
#   2. daily/weekly 聚合 timezone: Sir 中国, 用 local time (time.timezone 偏移)
#   3. 任何异常都 fail-safe (return out with err 字段, 不 raise)
#   4. claim_stats.json 缺失 → verify_rate 为 None, 卡片显 '--' 不崩
#   5. window='today' / '7d' 任一字符串异常 → 默认 today
def read_integrity_stats(window: str = 'today',
                          audit_path: Optional[str] = None,
                          stats_path: Optional[str] = None,
                          now_ts: Optional[float] = None) -> Dict:
    """🔬 言出必行健康度 — Jarvis claim 未兑现情况

    数据源:
      - memory_pool/integrity_audit.jsonl: 仅 unverified claim 条目 (β.4.1+)
      - memory_pool/claim_stats.json (Session 4 daemon hook, 可选)

    返回 schema:
      {
        'window': 'today' / '7d',
        'unverified_today': int,
        'unverified_7d': int,
        'kind_dist': {'time': N, 'past_action': N, 'recall': N, ...},
        'top_unverified': [{'text': str, 'kind': str, 'count': N}, ...],  # top 3 (7d 窗)
        'trend_7d': [d-6, d-5, d-4, d-3, d-2, d-1, today],  # 7 day buckets, 末位=今天
        'verify_rate': None | float,  # 0.0-1.0, 仅当 claim_stats.json 存在
        'diagnosis': str,
        'suggestion': str,
        'err': None | str,
      }
    """
    out = {
        'window': window if window in ('today', '7d') else 'today',
        'unverified_today': 0,
        'unverified_7d': 0,
        'kind_dist': {},
        'top_unverified': [],
        'trend_7d': [0] * 7,
        'verify_rate': None,
        'diagnosis': '',
        'suggestion': '',
        'err': None,
    }
    path = audit_path or os.path.join(MEM, 'integrity_audit.jsonl')
    if not os.path.exists(path):
        out['diagnosis'] = '📝 还没有任何 claim audit 记录'
        out['suggestion'] = (
            '正常 — Jarvis 还没出过 unverified claim, 或 ClaimTracer 没启用. '
            '说几句话给 Jarvis 听看后续会不会写入'
        )
        return out

    now = float(now_ts) if now_ts is not None else time.time()
    # 本地今日 00:00 (中国时区, 不要 UTC)
    today_start = now - (now % 86400) - time.timezone
    seven_d_start = today_start - 6 * 86400  # 7 天窗 (含今天)

    try:
        records = _safe_read_jsonl_tail(path, tail_lines=5000)
    except Exception as e:
        out['err'] = f'读取异常: {e}'
        out['diagnosis'] = '⚠️ jsonl 读取失败'
        out['suggestion'] = f'看 {path} 是否权限/编码异常'
        return out

    today_records = []
    week_records = []
    for r in records:
        try:
            ts = float(r.get('ts', 0) or 0)
        except (TypeError, ValueError):
            continue
        if ts >= today_start:
            today_records.append(r)
        if ts >= seven_d_start:
            week_records.append(r)

    out['unverified_today'] = len(today_records)
    out['unverified_7d'] = len(week_records)

    # kind 分布 (今日; 类型未填默认 '?')
    kind_counter: Dict[str, int] = {}
    for r in today_records:
        k = (r.get('kind') or '?').strip() or '?'
        kind_counter[k] = kind_counter.get(k, 0) + 1
    out['kind_dist'] = kind_counter

    # top 3 frequent unverified text (7d 窗, 同 text+kind 计 count)
    text_counter: Dict[tuple, int] = {}
    for r in week_records:
        text = (r.get('claim') or '').strip()[:80]
        kind = (r.get('kind') or '?').strip() or '?'
        if not text:
            continue
        key = (text, kind)
        text_counter[key] = text_counter.get(key, 0) + 1
    top3 = sorted(text_counter.items(), key=lambda x: -x[1])[:3]
    out['top_unverified'] = [
        {'text': t, 'kind': k, 'count': c} for (t, k), c in top3
    ]

    # 7d trend (day buckets, 索引 6 = 今天, 0 = 6 天前)
    # 🩹 [β.4.4 / 2026-05-18] bucket bug fix: ts 不在 00:00 时, 直接用 (today_start - ts) // 86400
    # 会偏小一天 (如 d-3 12:00 → (3天-0.5天)//86400=2). 修法: 先把 ts 对齐到当天 00:00.
    for r in week_records:
        try:
            ts = float(r.get('ts', 0) or 0)
        except (TypeError, ValueError):
            continue
        if ts < seven_d_start:
            continue
        ts_day_start = ts - (ts % 86400) - time.timezone  # ts 当天的本地午夜
        day_offset = int((today_start - ts_day_start) // 86400)  # 0=今天 / 1=昨天
        if day_offset < 0:
            day_offset = 0  # 未来 ts (时间戳错乱) 算今天
        if 0 <= day_offset < 7:
            out['trend_7d'][6 - day_offset] += 1

    # verify_rate hook (Session 4 daemon 写 claim_stats.json 后自动生效)
    stats_p = stats_path or os.path.join(MEM, 'claim_stats.json')
    if os.path.exists(stats_p):
        try:
            stats = _safe_read_json(stats_p, {})
            total_claims = int(stats.get('total_claims', 0) or 0)
            total_unverified = int(stats.get('total_unverified', 0) or 0)
            if total_claims > 0:
                rate = (total_claims - total_unverified) / float(total_claims)
                out['verify_rate'] = max(0.0, min(1.0, rate))  # clamp
        except Exception:
            pass  # fail-safe: verify_rate 保持 None

    # 诊断 (准则 6: 不教主脑句式, 这是 Sir 看的 UI 文案, 直接说事)
    if out['unverified_today'] == 0:
        if out['unverified_7d'] == 0:
            out['diagnosis'] = '✅ 言出必行 — 7 天 0 件空头话'
            out['suggestion'] = '正常 — 所有 claim 都 trace 到 evidence'
        else:
            out['diagnosis'] = (
                f'✅ 今天 0 件 (7 天累计 {out["unverified_7d"]} 件)'
            )
            out['suggestion'] = '今天干净, 看下面 7d 趋势看历史走势'
    elif out['unverified_today'] <= 5:
        out['diagnosis'] = (
            f'⚠️ 今天 {out["unverified_today"]} 件空头话'
        )
        out['suggestion'] = (
            '少量正常 — 主脑会在下轮 [INTEGRITY ALERT] 自己撤回. '
            '如重复多次同 text → 看是否 ClaimTracer 误报或 vocab 漏抓'
        )
    else:
        out['diagnosis'] = (
            f'❌ 今天 {out["unverified_today"]} 件空头话频发 — 言行不一信号'
        )
        out['suggestion'] = (
            '可能 ClaimTracer 误报 / vocab 漏抓 / 主脑诚信问题. '
            '看 memory_pool/integrity_audit.jsonl tail + '
            'scripts/claim_classify_dump.py / evidence_req_dump.py 调 vocab'
        )

    return out


def read_review_queues() -> Dict:
    """⚠️ 等你拍板的提案 — concerns/relational/directive/cooldown review.

    🩹 [β.5.24 / 2026-05-19] 全面重构 (Sir 01:58 反馈 'X 拒绝说不存在'):
    - relational thread 加 title + highlights[0].what fallback (老代码只查 phrase/rule/topic 漏 title 全过滤掉)
    - 加 cooldown_vocab.review_queue 源 (β.5.23-B L7 propose)
    - 加 source / rationale / detail / created_iso 字段供详情面板用
    - 过滤 preview 太短 (< 5 字) 防 'X' 类垃圾
    - 不再 [:5] 截断 — 让 Sir 看全
    """
    out = {'items': []}

    # ====== 1. Concerns review ======
    cr = _safe_read_json(os.path.join(MEM, 'concerns_review.json'), [])
    items_cr = cr if isinstance(cr, list) else (
        cr.get('proposals', []) if isinstance(cr, dict) else [])
    for i in items_cr:
        if not isinstance(i, dict):
            continue
        preview = i.get('what_i_watch') or i.get('id') or ''
        if not preview or len(preview.strip()) < 5:
            continue  # filter X / 短垃圾
        out['items'].append({
            'kind': 'concern',
            'kind_zh': '🎯 长期关心',
            'id': i.get('id', '?'),
            'preview': preview.strip(),
            'rationale': (i.get('why_i_care') or '')[:300],
            'source': i.get('source', '?'),
            'severity': float(i.get('severity', 0)),
            'created_iso': i.get('created_at_iso')
                or _ts_to_iso(i.get('created_at')),
            'cli': "python scripts/concerns_dump.py --review",
        })

    # ====== 2. Relational review (thread / joke / protocol) ======
    rr = _safe_read_json(os.path.join(MEM, 'relational_review.json'), [])
    if isinstance(rr, list):
        for i in rr:
            if not isinstance(i, dict):
                continue
            preview = (i.get('phrase') or i.get('rule')
                        or i.get('topic') or i.get('title') or '')
            if not preview or len(preview.strip()) < 5:
                continue
            out['items'].append({
                'kind': 'relational',
                'kind_zh': '💞 你们之间',
                'id': i.get('id', '?'),
                'preview': preview.strip(),
                'rationale': (i.get('detail') or i.get('birth_context')
                              or i.get('rationale') or '')[:300],
                'source': i.get('source', '?'),
                'created_iso': i.get('created_at_iso')
                    or _ts_to_iso(i.get('created_at') or i.get('started_at')),
                'cli': "python scripts/relational_dump.py --review-list",
            })
    elif isinstance(rr, dict):
        for kind, lst in rr.items():
            if kind.startswith('_'):
                continue  # skip _meta
            if not isinstance(lst, list):
                continue
            for i in lst:
                if not isinstance(i, dict):
                    continue
                # 🩹 β.5.24 thread 字段是 title (老 dashboard 漏)
                title = i.get('title') or ''
                rationale_src = ''
                # highlights 是 thread 的 evidence 列表
                hl = i.get('highlights') or []
                if hl and isinstance(hl, list) and isinstance(hl[0], dict):
                    rationale_src = hl[0].get('what', '')[:300]
                preview = (i.get('phrase') or i.get('rule')
                            or i.get('topic') or title or '')
                if not preview or len(preview.strip()) < 5:
                    continue
                kind_zh_map = {
                    'inside_jokes': '😂 内部梗',
                    'unspoken_protocols': '🤝 默契',
                    'shared_history_threads': '📖 共同经历',
                    'unfinished_business': '📌 未完事项',
                }
                out['items'].append({
                    'kind': f'relational/{kind}',
                    'kind_zh': kind_zh_map.get(kind, f'💞 {kind}'),
                    'id': i.get('id', '?'),
                    'preview': preview.strip(),
                    'rationale': (rationale_src or i.get('detail')
                                   or i.get('birth_context')
                                   or i.get('rationale') or '')[:300],
                    'source': i.get('source', '?'),
                    'created_iso': i.get('created_at_iso')
                        or _ts_to_iso(i.get('created_at')
                                       or i.get('started_at')),
                    'cli': "python scripts/relational_dump.py --review-list",
                })

    # ====== 3. Directive review ======
    dr = _safe_read_json(os.path.join(MEM, 'directive_review.json'), [])
    items_dr = dr if isinstance(dr, list) else []
    for i in items_dr:
        if not isinstance(i, dict):
            continue
        preview = i.get('rule') or i.get('directive') or i.get('id') or ''
        if not preview or len(preview.strip()) < 5:
            continue
        out['items'].append({
            'kind': 'directive',
            'kind_zh': '📜 临时规则',
            'id': i.get('id', '?'),
            'preview': preview.strip(),
            'rationale': (i.get('reason') or '')[:300],
            'source': i.get('source', '?'),
            'created_iso': i.get('created_at_iso'),
            'cli': "python scripts/registry_dump.py --review",
        })

    # ====== 4. 🩹 [β.5.24] Cooldown vocab review (β.5.23-B L7 propose) ======
    cd_path = os.path.join(MEM, 'proactive_care_cooldown_vocab.json')
    cd = _safe_read_json(cd_path, {})
    if isinstance(cd, dict):
        rq = cd.get('review_queue') or []
        for i in rq:
            if not isinstance(i, dict):
                continue
            key = i.get('key', '')
            cur = i.get('current')
            prop = i.get('proposed')
            if not key:
                continue
            preview = f"{key}: {cur} → {prop}"
            out['items'].append({
                'kind': 'cooldown',
                'kind_zh': '⏰ Cooldown 阈值',
                'id': key,
                'preview': preview,
                'rationale': (i.get('rationale') or '')[:300],
                'source': i.get('source', 'L7'),
                'proposed_value': prop,
                'created_iso': i.get('when'),
                'cli': "python scripts/cooldown_vocab_dump.py review",
            })

    # ====== 5a. 🩹 [β.5.39-fix / 2026-05-20] 新 vocab review sources (β.5.35/36/39)
    # 这些 vocab 都有 review_queue 段, 但老 dashboard 没 cover.
    # 全部走 generic _scan_vocab_review_queue 简化.
    for vocab_name, kind_label, cli_cmd, preview_extractor in [
        ('screen_tease_vocab.json', '🪞 屏幕调侃',
         'python scripts/screen_tease_vocab_dump.py --review-list',
         lambda it: f"{it.get('category', '?')}: {', '.join(it.get('keywords', [])[:3])}"),
        ('sir_struggle_vocab.json', '🆘 Sir 困境词',
         'python scripts/struggle_vocab_dump.py --review-list',
         lambda it: f"{it.get('id', '?')}: {', '.join(it.get('patterns', [])[:3])}"),
        ('directives_vocab.json', '📜 主脑 directive',
         'python scripts/registry_dump.py --review',
         lambda it: f"{it.get('id', '?')}: {(it.get('text', '') or '')[:80]}"),
        ('sir_sleep_pattern_vocab.json', '💤 入睡习惯',
         'python scripts/sleep_pattern_dump.py --show',
         lambda it: f"{it.get('kind', '?')}: cur={it.get('current')} → prop={it.get('proposed')}"),
        ('behavior_inference_vocab.json', '⏱️ 履约推断',
         'python scripts/behavior_vocab_dump.py review',
         lambda it: f"{it.get('id', '?')}: {', '.join(it.get('keywords', [])[:3])}"),
    ]:
        vpath = os.path.join(MEM, vocab_name)
        vdata = _safe_read_json(vpath, {})
        if not isinstance(vdata, dict):
            continue
        rq = vdata.get('review_queue') or []
        if not isinstance(rq, list):
            continue
        for it in rq:
            if not isinstance(it, dict):
                continue
            try:
                preview = preview_extractor(it)
            except Exception:
                preview = it.get('id', '?')
            if not preview or len(preview.strip()) < 3:
                continue
            out['items'].append({
                'kind': vocab_name.replace('.json', ''),
                'kind_zh': kind_label,
                'id': it.get('id', '?'),
                'preview': preview.strip()[:200],
                'rationale': (it.get('rationale') or it.get('source') or it.get('note') or '')[:300],
                'source': it.get('source', 'L7 reflector'),
                'created_iso': it.get('proposed_at_iso') or _ts_to_iso(it.get('proposed_at') or it.get('created_at')),
                'cli': cli_cmd,
            })

    # ====== 5. 🩹 [β.5.33 / 2026-05-20] Cross-session callback review ======
    cb_path = os.path.join(MEM, 'cross_session_callback.json')
    cb_data = _safe_read_json(cb_path, {})
    if isinstance(cb_data, dict):
        callbacks = (cb_data.get('callbacks') or {}).values() if isinstance(cb_data.get('callbacks'), dict) else []
        for cb in callbacks:
            if not isinstance(cb, dict) or cb.get('state') != 'review':
                continue
            action = (cb.get('action') or '')[:120]
            when_natural = (cb.get('when_natural') or '')[:60]
            when_iso = (cb.get('when_iso') or '')[:30]
            preview = f"{when_natural} - {action}" + (f" (~{when_iso})" if when_iso else '')
            out['items'].append({
                'kind': 'callback',
                'kind_zh': '📅 跨 Session 提醒',
                'id': cb.get('id', '?'),
                'preview': preview,
                'rationale': (cb.get('source_utterance') or '')[:200],
                'source': 'auto_proposed (SoulArchivist)',
                'proposed_value': when_iso,
                'created_iso': time.strftime(
                    '%Y-%m-%d %H:%M', time.localtime(float(cb.get('proposed_at', 0) or 0))) if cb.get('proposed_at') else '',
                'cli': 'dashboard 通过 → 转 commitment_watcher 到点提醒',
            })

    # 🩹 [β.5.28-dedup / 2026-05-20] Sir 02:49 反馈 '还有重复的'.
    # runtime dedup 兜底 (即使 propose_thread 加 dedup 漏掉 / 老数据). 同 base_kind 内,
    # preview 前 25 字 lowercased + 去标点 → 重复 sig → 保第一条丢后续.
    import re as _re
    _seen_sigs = {}
    _deduped = []
    _dropped = 0
    for _it in out['items']:
        _bk = _it['kind'].split('/')[0]
        _pv = (_it.get('preview') or '').lower().strip()
        _pv = _re.sub(r'[^\w\u4e00-\u9fff]+', '', _pv)  # 去标点
        _sig = (_bk, _pv[:25])
        if _sig in _seen_sigs and _pv:
            _dropped += 1
            continue
        _seen_sigs[_sig] = True
        _deduped.append(_it)
    if _dropped > 0:
        out['_dedup_dropped'] = _dropped
    out['items'] = _deduped

    # 📌 诊断
    n = len(out['items'])
    if n == 0:
        out['diagnosis'] = '✅ 没什么要你定的'
        out['suggestion'] = '无需操作'
    elif n <= 3:
        out['diagnosis'] = f'📝 {n} 条小提案, 不急'
        out['suggestion'] = '有空时点 "处理这批" 按钮逐条 ✅/❌'
    else:
        _dedup_note = f' (已去重 {_dropped})' if _dropped > 0 else ''
        out['diagnosis'] = (
            f'⚠️ {n} 条提案累积{_dedup_note} — 贾维斯想了解你的看法')
        out['suggestion'] = '建议今天抽 5 分钟处理 (按钮在卡片底部)'
    return out


def _ts_to_iso(ts) -> str:
    """epoch float → ISO 字符串. 失败返 ''."""
    if not ts:
        return ''
    try:
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(float(ts)))
    except Exception:
        return ''


# ---- 实时事件流 ----

_EVENT_PATTERNS = [
    ('🤝 主动发声', r'🤝\s*\[ProactiveCare/LIVE\]\s*(.+)'),
    ('🤝 想发声', r'🤝\s*\[ProactiveCare/DRY\]\s*(.+)'),
    ('🛑 不打扰', r'🛑\s*\[ProactiveCare\]\s*skip\s*(.+)'),
    ('📡 信号', r'📡\s*\[ProactiveCare/Sensor\]\s*(.+)'),
    ('⚖️ 言行反差', r'⚖️\s*\[InconsistencyWatcher\]\s*(.+)'),
    ('🚫 拒了你', r'🚫\s*\[ProactiveCare\]\s*Sir.*?显式拒绝.*'),
    ('✓ 兑现承诺', r'✅\s*\[Jarvis Promise FULFILLED\]\s*(.+)'),
    ('⏰ 承诺超时', r'⏰\s*\[Jarvis Promise OVERDUE\]\s*(.+)'),
    ('❓ 没监控到', r'❓\s*\[Jarvis Promise UNTRACKED\]\s*(.+)'),
    ('📝 收新承诺', r'📝\s*\[CommitmentWatcher\]\s*已注册:\s*(.+)'),
    ('🔁 归来问候', r'\[ReturnSentinel/Sent\]\s*(.+)'),
]


def read_event_stream(limit: int = 30) -> Dict:
    """🔔 贾维斯最近在干嘛 — latest.log 最近 N 件"""
    out = {'events': [], 'log_path': '', 'err': None}
    log = _find_latest_log()
    out['log_path'] = log
    if not log or not os.path.exists(log):
        out['err'] = '找不到最近的运行日志'
        return out
    try:
        size = os.path.getsize(log)
        with open(log, 'r', encoding='utf-8', errors='ignore') as f:
            if size > 200 * 1024:
                f.seek(size - 200 * 1024)
                f.readline()
            lines = f.readlines()
    except Exception as e:
        out['err'] = f'读 log: {e}'
        return out
    for line in lines:
        line = line.rstrip()
        for tag, pat in _EVENT_PATTERNS:
            m = re.search(pat, line)
            if not m:
                continue
            ts_m = re.search(r'sess_\d{8}_(\d{6})_', line)
            ts = '?'
            if ts_m:
                hms = ts_m.group(1)
                ts = f"{hms[:2]}:{hms[2:4]}:{hms[4:6]}"
            body = (m.group(1) if m.lastindex else line.strip())[:90]
            out['events'].append({'ts': ts, 'tag': tag, 'body': body})
            break
    out['events'] = out['events'][-limit:]

    # 📌 诊断 — 看事件类型分布
    if not out['events']:
        out['diagnosis'] = '😴 静悄悄 — 贾维斯没在做事件级动作'
        out['suggestion'] = '正常 (刚启动 / 空闲)'
    else:
        from collections import Counter
        tags = Counter(e['tag'] for e in out['events'])
        n_skip = sum(v for k, v in tags.items() if '不打扰' in k)
        n_speak = sum(v for k, v in tags.items() if '主动发声' in k)
        n_incon = sum(v for k, v in tags.items() if '言行反差' in k)
        n_fulf = sum(v for k, v in tags.items() if '兑现' in k)
        n_untrk = sum(v for k, v in tags.items() if '没监控到' in k)
        parts = []
        if n_skip > n_speak * 2:
            parts.append(f'✅ 懂分寸 (拒 {n_skip} 次, 说 {n_speak} 次)')
        elif n_speak > n_skip + 3:
            parts.append(f'⚠️ 今天主动多 (说了 {n_speak} 次, 拒 {n_skip} 次)')
        else:
            parts.append(f'📝 节奏正常 (说 {n_speak} / 拒 {n_skip})')
        if n_incon > 0:
            parts.append(f'⚖️ {n_incon} 次言行反差检测')
        if n_untrk > 0:
            parts.append(f'❓ {n_untrk} 件承诺没监控到执行')
        if n_fulf > 0:
            parts.append(f'✓ 兑现 {n_fulf} 件承诺')
        out['diagnosis'] = ' · '.join(parts)
        if n_speak > 5:
            out['suggestion'] = '若觉烦, env JARVIS_PROACTIVE_CARE_LEVEL=low 降阈值'
        elif n_untrk > 3:
            out['suggestion'] = '言行不一信号; 看 scripts/promise_tail.py 详情'
        else:
            out['suggestion'] = '健康节奏, 无需操作'
    return out


# ---- 整体评估 (顶部) ----

def compute_overall_status(concerns: dict, directive: dict, promise: dict,
                             relation: dict, daemon: dict, health: dict,
                             review: dict, events: dict,
                             mutations: dict = None,
                             integrity: dict = None) -> dict:
    """🤖 整体一句话 — 综合所有 reader, 给 Sir 看就懂的 top-3 重点

    🩹 [β.4.4 / 2026-05-18] Sir Session 3: 加 integrity 入参 — Jarvis 言出必行健康度.
      阈值 (准则 5 言出必行优先级最高):
        - 今日 unverified > 5  → crit (言行不一频发)
        - 今日 unverified 1-5  → warn (少量空头话)
        - 今日 unverified == 0 → 不入 issues (✅ 健康)
    """
    out = {'level': 'ok', 'headline': '', 'top_actions': []}
    if mutations is None:
        mutations = {'today_n': 0, 'total_n': 0}
    if integrity is None:
        integrity = {'unverified_today': 0, 'unverified_7d': 0}

    issues = []  # [(severity, text, action), ...] severity: 'crit' / 'warn' / 'info'

    # critical concerns
    crit_concerns = [r for r in concerns.get('rows', []) if r.get('severity_pct', 0) >= 85]
    if crit_concerns:
        top = crit_concerns[0]
        issues.append((
            'crit',
            f'"{top["zh_name"]}" 紧迫度 {top["severity_pct"]}% — 贾维斯准备催你了',
            f'对贾维斯说 "别催了" 静默 24h, 或真去做',
        ))

    # directive offset
    h = directive.get('health', {})
    offset = h.get('untriggered', 0) + h.get('low_help', 0)
    if offset >= 5:
        issues.append((
            'warn',
            f'{offset} 条临时规则跑偏 (规则不再准 / 不再触发)',
            'review: scripts/registry_dump.py',
        ))

    # promise untracked / overdue
    if promise.get('untracked_n', 0) > 2:
        issues.append((
            'warn',
            f'{promise["untracked_n"]} 条贾维斯口头答应却没监控到执行 (言行不一)',
            'scripts/promise_tail.py 看详情',
        ))

    # review queues
    if len(review.get('items', [])) >= 3:
        issues.append((
            'warn',
            f'{len(review["items"])} 条提案等你拍板',
            '点 "处理这批" 按钮',
        ))

    # key router dead
    kr_dead = health.get('key_router', {}).get('dead_n', 0)
    if kr_dead > 0:
        issues.append((
            'warn',
            f'{kr_dead} 把 API key 死了',
            '重启贾维斯 / 看 OpenRouter 后台',
        ))

    # 🩹 [β.3.0 / 2026-05-18] Sir 16:18 实测 BUG: 主进程冷时不恐吓"管家未启动"
    if daemon.get('main_process_cold'):
        mins = int(daemon.get('log_age_s', 0) / 60)
        issues.append((
            'info',  # info 而非 crit, 不当紧急告警
            f'主进程未在跑 (日志冷 {mins}min) — 后台全 0 是预期',
            '启动贾维斯主程序: python jarvis_nerve.py',
        ))
    else:
        # 主进程在跑时才报 daemon offline
        crit_off = [x for x in daemon.get('daemons', [])
                     if not x.get('live') and x.get('id') in
                     ('ProactiveCare', 'Inconsistency', 'HealthProbe', 'Commitment')]
        if crit_off:
            names = '/'.join(x['id'] for x in crit_off[:3])
            issues.append((
                'crit',
                f'{len(crit_off)} 个关键管家未启动: {names}',
                '重启贾维斯主程序; 或看 log 找启动报错',
            ))

    # memory abnormal
    ws_mb = health.get('health_last', {}).get('ws_mb', 0)
    if ws_mb > 4000:
        issues.append((
            'warn',
            f'内存 {ws_mb:.0f}MB 偏高 (> 4GB) — 可能泄漏',
            '看 24h 趋势; 必要重启',
        ))

    # 🩹 [β.2.9.9] 信任审计 — 今天 Sir 有纠正话语但 0 真写入 → 言行不一信号
    if mutations.get('today_n', 0) == 0 and mutations.get('total_n', 0) > 0:
        # 检查 events 流是否有 "correction" 触发
        n_correction = sum(1 for e in events.get('events', [])
                            if '纠错' in e.get('tag', '') or
                            '言行' in e.get('tag', ''))
        if n_correction > 0:
            issues.append((
                'crit',
                f'今天 Sir 纠正 {n_correction} 次但 0 真写入 — 可能在空头"我已更新"',
                '看 dashboard 信任审计卡 + log 主对话纠正话语',
            ))

    # 🩹 [β.4.4 / 2026-05-18] Sir Session 3: 言出必行健康度 — claim 未兑现条数阈值
    # 准则 5 优先级最高: 今日 unverified > 5 = crit / 1-5 = warn / 0 = 不入 issues
    unv_today = int(integrity.get('unverified_today', 0) or 0)
    if unv_today > 5:
        issues.append((
            'crit',
            f'今天 {unv_today} 件空头话频发 — 言行不一信号 (准则 5)',
            '看 dashboard "言出必行" 卡 + integrity_audit.jsonl tail',
        ))
    elif unv_today > 0:
        issues.append((
            'warn',
            f'今天 {unv_today} 件 unverified claim — 主脑下轮会自己撤回',
            '看 dashboard "言出必行" 卡详情 + top 高频空头话',
        ))

    # 综合 headline
    if not issues:
        out['level'] = 'ok'
        out['headline'] = '✅ 健康 — 没什么需要你操作的'
    else:
        crit_n = sum(1 for s, _, _ in issues if s == 'crit')
        warn_n = sum(1 for s, _, _ in issues if s == 'warn')
        if crit_n > 0:
            out['level'] = 'crit'
            out['headline'] = f'❌ {crit_n} 件要紧 + {warn_n} 件留意'
        else:
            out['level'] = 'warn'
            out['headline'] = f'⚠️ {warn_n} 件留意 (无要紧)'

    # top 3 actions (按严重度排)
    issues.sort(key=lambda x: {'crit': 0, 'warn': 1, 'info': 2}.get(x[0], 9))
    out['top_actions'] = [
        {'level': s, 'what': t, 'how': a}
        for s, t, a in issues[:5]
    ]
    return out


# ============================================================
# 按钮操作 (subprocess 调 scripts/, 不阻塞 GUI / 不直接动 db)
# ============================================================

def _run_script_subprocess(args: list, on_done=None) -> None:
    """非阻塞 subprocess. 用单独 thread 跑, 完成 callback 主线程."""
    import threading

    def _worker():
        try:
            r = subprocess.run(
                [sys.executable] + args,
                cwd=ROOT, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=15.0,
            )
            ok = r.returncode == 0
            out = (r.stdout or '') + (r.stderr or '')
        except Exception as e:
            ok = False
            out = str(e)
        if on_done:
            on_done(ok, out)

    threading.Thread(target=_worker, daemon=True,
                      name='DashboardScriptRunner').start()


def action_cancel_commitment(cw_id: int, on_done=None) -> None:
    """🚫 取消 Sir 待办 (调 scripts/commitment_cancel.py).

    🩹 [β.2.9.8 fix / 2026-05-18] Sir 实测按钮无反应 — 旧版传错了参数名
    (`--by-id` 实际不存在, script 接受的是 `--cancel`). 修正参数 + on_done
    返回 script stdout 让 Sir 在状态栏直接看到结果.
    """
    _run_script_subprocess(
        ['scripts/commitment_cancel.py', '--cancel', str(cw_id)],
        on_done=on_done,
    )


def action_reset_promise_log(keep_fulfilled: bool = True,
                                on_done=None) -> None:
    """🧹 清空贾维斯口头承诺残留"""
    args = ['scripts/promise_log_reset.py', '--apply']
    if keep_fulfilled:
        args.append('--keep-fulfilled')
    _run_script_subprocess(args, on_done=on_done)


def action_open_review_cli(kind: str, on_done=None) -> None:
    """🔧 打开 review CLI 让 Sir 处理 (备选, 给批量看用)"""
    if kind == 'concern':
        cmd = 'python scripts/concerns_dump.py --review'
    elif kind == 'relational':
        cmd = 'python scripts/relational_dump.py --review-list'
    elif kind == 'directive':
        cmd = 'python scripts/registry_dump.py'
    else:
        cmd = ''
    if cmd and sys.platform == 'win32':
        try:
            subprocess.Popen(['cmd.exe', '/c', 'start', 'cmd.exe', '/k', cmd],
                              cwd=ROOT)
            if on_done:
                on_done(True, f'已开新窗口跑: {cmd}')
        except Exception as e:
            if on_done:
                on_done(False, str(e))


def action_activate_review(kind: str, item_id: str, on_done=None,
                             extra=None) -> None:
    """✅ 通过一条 review 提案 (concern / relational / directive / cooldown).

    🩹 [β.2.9.8 / 2026-05-18] Sir 10:34 痛点: 不想跳终端, 直接按钮 yes/no.
    🩹 [β.5.24 / 2026-05-19] Sir 01:58 反馈"全面重构":
    - 加 cooldown 类型 (β.5.23-B L7 propose): activate = scripts/cooldown_vocab_dump.py set <key> <proposed_value>
    - reject 失败时 fallback 直接从 review json pop (修 'X 数据不存在' BUG)
    - extra dict 传 cooldown 的 proposed_value
    """
    if kind.startswith('concern'):
        script = 'scripts/concerns_dump.py'
        args = [script, '--activate', str(item_id)]
    elif kind.startswith('relational'):
        script = 'scripts/relational_dump.py'
        args = [script, '--activate', str(item_id)]
    elif kind == 'directive':
        script = 'scripts/registry_dump.py'
        args = [script, '--activate', str(item_id)]
    elif kind == 'cooldown':
        # cooldown 'activate' = apply L7 propose 值 + 从 queue 删
        if extra is None or extra.get('proposed_value') is None:
            if on_done:
                on_done(False, 'cooldown 提案缺 proposed_value')
            return
        prop = extra['proposed_value']
        # 1. set 新值
        # 2. 拿 cooldown vocab review_queue pop 这条
        _apply_cooldown_proposal(item_id, prop, on_done=on_done)
        return
    elif kind == 'callback':
        # 🩹 [β.5.33 / 2026-05-20] Sir 通过 callback → 转 commitment_watcher 到点 nudge
        _apply_callback_proposal(item_id, on_done=on_done)
        return
    else:
        if on_done:
            on_done(False, f'不支持的 kind: {kind}')
        return
    _run_script_subprocess(args, on_done=on_done)


def action_reject_review(kind: str, item_id: str, on_done=None,
                           extra=None) -> None:
    """❌ 拒绝一条 review 提案 (转 archived / 从 queue 删)."""
    if kind.startswith('concern'):
        script = 'scripts/concerns_dump.py'
        args = [script, '--reject', str(item_id)]
    elif kind.startswith('relational'):
        script = 'scripts/relational_dump.py'
        args = [script, '--reject', str(item_id)]
    elif kind == 'directive':
        script = 'scripts/registry_dump.py'
        args = [script, '--reject', str(item_id)]
    elif kind == 'cooldown':
        # cooldown reject = 直接从 review_queue 删 (不 apply)
        _reject_cooldown_proposal(item_id, on_done=on_done)
        return
    elif kind == 'callback':
        # 🩹 [β.5.33] callback reject = state=archived (不再 propose 同 action)
        _reject_callback_proposal(item_id, on_done=on_done)
        return
    else:
        if on_done:
            on_done(False, f'不支持的 kind: {kind}')
        return
    _run_script_subprocess(args, on_done=on_done)


def _apply_callback_proposal(cb_id: str, on_done=None) -> None:
    """🩹 [β.5.33 / 2026-05-20] Sir 通过 callback → activate + 转 commitment_watcher.

    步骤:
    1. CrossSessionCallbackStore.activate(cb_id) → state=active + 返 cb 对象
    2. commitment_watcher.add_commitment(action, when_iso) → 到点 nudge
    """
    import threading as _t
    def _do():
        try:
            from jarvis_cross_session_callback import get_default_store as _cb_store
            store = _cb_store()
            cb = store.activate(cb_id)
            if cb is None:
                if on_done:
                    on_done(False, f'callback {cb_id} 不存在或已 activate')
                return
            # 注册到 commitment_watcher (跨进程, 用 jsonl 存)
            try:
                # 简单办法: 写 commitment_log 文件让主进程 watcher 读
                cw_path = os.path.join(MEM, 'pending_callbacks.jsonl')
                import json as _json
                with open(cw_path, 'a', encoding='utf-8') as f:
                    f.write(_json.dumps({
                        'cb_id': cb.id,
                        'action': cb.action,
                        'when_iso': cb.when_iso,
                        'when_natural': cb.when_natural,
                        'source_utterance': cb.source_utterance,
                        'activated_at': time.time(),
                    }, ensure_ascii=False) + '\n')
                # 🆕 [Reshape M4.7 / 2026-05-24] dual-write to PromiseLog (lineage 价值).
                # jsonl 仍保留兼容老 consumer (commitment_watcher._consume_pending_callbacks).
                # PromiseLog 让 Sir 跨 source 看到所有 promise (cross_session_callback +
                # commitment + cyclic + watch + self_promise) 在一处. M5+ daemon 真切
                # PromiseLog 单源后, 老 jsonl write 可删 (cleanup checklist trigger).
                try:
                    from jarvis_promise_log import get_default_log as _m47_gpl
                    _plog = _m47_gpl()
                    _plog.register(
                        description=cb.action[:200],
                        kind='cross_session_callback',
                        deadline_str=cb.when_iso or '',
                        jarvis_reply=cb.source_utterance[:1000] if cb.source_utterance else '',
                        author='sir',
                    )
                except Exception:
                    pass
                if on_done:
                    on_done(True,
                        f'✓ {cb.action[:40]} → 已激活 (主进程 watcher 到 {cb.when_iso} 提醒) + PromiseLog')
            except Exception as e:
                if on_done:
                    on_done(False, f'写 pending_callbacks.jsonl 失败: {e}')
        except Exception as e:
            if on_done:
                on_done(False, str(e))
    _t.Thread(target=_do, daemon=True).start()


def _reject_callback_proposal(cb_id: str, on_done=None) -> None:
    """🩹 [β.5.33] Sir 拒绝 callback → state=archived (不再 propose 同 action)."""
    import threading as _t
    def _do():
        try:
            from jarvis_cross_session_callback import get_default_store as _cb_store
            store = _cb_store()
            ok = store.reject(cb_id)
            if on_done:
                on_done(ok, f'✓ {cb_id} archived' if ok else f'✗ {cb_id} 不存在')
        except Exception as e:
            if on_done:
                on_done(False, str(e))
    _t.Thread(target=_do, daemon=True).start()


def _apply_cooldown_proposal(key: str, proposed_value, on_done=None) -> None:
    """🩹 [β.5.24] cooldown vocab apply L7 propose. Threaded 防 UI 卡."""
    import threading as _t
    def _do():
        try:
            args = ['scripts/cooldown_vocab_dump.py', 'set', str(key),
                    str(proposed_value)]
            # 跑 set 命令
            import subprocess as _sp
            r = _sp.run([sys.executable] + args,
                         capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                if on_done:
                    on_done(False, f'set 失败: {r.stderr[:200]}')
                return
            # 删 review queue 里这条
            _drop_cooldown_review_entry(key)
            if on_done:
                on_done(True, f'✓ {key} → {proposed_value}, queue 删')
        except Exception as e:
            if on_done:
                on_done(False, str(e))
    _t.Thread(target=_do, daemon=True).start()


def _reject_cooldown_proposal(key: str, on_done=None) -> None:
    """直接从 cooldown_vocab.json review_queue 删指定 key."""
    import threading as _t
    def _do():
        try:
            removed = _drop_cooldown_review_entry(key)
            if removed:
                if on_done:
                    on_done(True, f'✓ {key} 已从 review queue 删')
            else:
                if on_done:
                    on_done(False, f'{key} 不在 review queue')
        except Exception as e:
            if on_done:
                on_done(False, str(e))
    _t.Thread(target=_do, daemon=True).start()


def _drop_cooldown_review_entry(key: str) -> bool:
    """从 cooldown_vocab.json review_queue 删指定 key 的所有 entry. 返是否删了."""
    path = os.path.join(MEM, 'proactive_care_cooldown_vocab.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return False
    rq = data.get('review_queue') or []
    n_before = len(rq)
    rq = [e for e in rq if e.get('key') != key]
    if len(rq) == n_before:
        return False
    data['review_queue'] = rq
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def action_open_latest_log(on_done=None) -> None:
    """📜 在系统默认编辑器打开最近的运行日志"""
    log = _find_latest_log()
    if log and os.path.exists(log):
        try:
            if sys.platform == 'win32':
                os.startfile(log)  # type: ignore
            if on_done:
                on_done(True, f'已打开: {os.path.basename(log)}')
        except Exception as e:
            if on_done:
                on_done(False, str(e))
    elif on_done:
        on_done(False, '找不到 log')


# ============================================================
# GUI (Tkinter) — 三大块布局 + 按钮
# ============================================================

def launch_gui(refresh_s: int, use_color: bool, geometry: str) -> int:
    try:
        import tkinter as tk
        from tkinter import font as tkfont, scrolledtext, messagebox
    except ImportError:
        print("Tkinter 不可用. Windows 默认带, Linux 装 python3-tk.")
        return 1

    root = tk.Tk()
    root.title("贾维斯总览看板  J.A.R.V.I.S. Dashboard  β.5.24")
    root.geometry(geometry)
    if use_color:
        root.configure(bg=COLOR['bg'])

    try:
        default_font = tkfont.nametofont('TkDefaultFont')
        default_font.configure(family='Microsoft YaHei UI', size=10)
        # 🩹 [β.2.9.9 / 2026-05-18] Sir 10:43 反馈"UI 美化". 字号 +1 / 加粗层次
        text_font = tkfont.Font(family='Microsoft YaHei UI', size=10)
        h1_font = tkfont.Font(family='Microsoft YaHei UI', size=15, weight='bold')
        h2_font = tkfont.Font(family='Microsoft YaHei UI', size=12, weight='bold')
        h3_font = tkfont.Font(family='Microsoft YaHei UI', size=11, weight='bold')
        btn_font = tkfont.Font(family='Microsoft YaHei UI', size=10)
        dim_font = tkfont.Font(family='Microsoft YaHei UI', size=9)
    except Exception:
        text_font = h1_font = h2_font = h3_font = btn_font = dim_font = None

    # 🩹 [β.2.9.9 / 2026-05-18] ttk theme 改 clam — 比默认 Win Vista 风更现代
    try:
        from tkinter import ttk
        style = ttk.Style()
        if 'clam' in style.theme_names():
            style.theme_use('clam')
    except Exception:
        pass

    bg = COLOR['bg'] if use_color else 'SystemButtonFace'
    fg = COLOR['fg'] if use_color else 'black'

    paused = {'value': False}
    status_msg = {'value': ''}

    # ============ Header (此刻状态条) ============
    header = tk.Frame(root, bg=COLOR['header_bg'] if use_color else 'SystemButtonFace')
    header.pack(side='top', fill='x')

    tk.Label(
        header, text='🤖  贾维斯', font=h1_font,
        bg=COLOR['header_bg'] if use_color else 'SystemButtonFace',
        fg=COLOR['header_fg'] if use_color else 'black',
        padx=12, pady=8,
    ).pack(side='left')

    now_lbl = tk.Label(
        header, text='', font=h2_font,
        bg=COLOR['header_bg'] if use_color else 'SystemButtonFace',
        fg=COLOR['btn_neutral'] if use_color else 'black',
        padx=10,
    )
    now_lbl.pack(side='left')

    status_lbl = tk.Label(
        header, text='', font=btn_font,
        bg=COLOR['header_bg'] if use_color else 'SystemButtonFace',
        fg=COLOR['ok'] if use_color else 'darkgreen',
        padx=10,
    )
    status_lbl.pack(side='left')

    def _set_status(msg: str, ok: bool = True):
        status_msg['value'] = msg
        status_lbl.config(
            text=msg,
            fg=(COLOR['ok'] if ok else COLOR['err']) if use_color
            else ('darkgreen' if ok else 'red')
        )

    def _toggle_pause():
        paused['value'] = not paused['value']
        pause_btn.config(text='▶ 恢复刷新' if paused['value'] else '⏸ 暂停刷新')

    def _force_refresh():
        _do_refresh()

    # 控制按钮
    btn_quit = tk.Button(header, text='❌ 退出', command=root.destroy,
                          font=btn_font, padx=8)
    btn_quit.pack(side='right', padx=4, pady=6)
    btn_log = tk.Button(header, text='📜 打开日志',
                         command=lambda: action_open_latest_log(
                             on_done=lambda ok, m: _set_status(m, ok)),
                         font=btn_font, padx=8)
    btn_log.pack(side='right', padx=4, pady=6)
    pause_btn = tk.Button(header, text='⏸ 暂停刷新', command=_toggle_pause,
                           font=btn_font, padx=8)
    pause_btn.pack(side='right', padx=4, pady=6)
    refresh_btn = tk.Button(header, text='🔄 立刻刷新', command=_force_refresh,
                             font=btn_font, padx=8)
    refresh_btn.pack(side='right', padx=4, pady=6)

    # ============ 大块工厂 ============
    def _make_group_frame(parent, title: str, color_key: str, row: int):
        gframe = tk.Frame(parent, bg=bg)
        gframe.grid(row=row, column=0, sticky='nsew', padx=0, pady=(12, 0))
        # 🩹 [β.2.9.9] 标题条加左侧色块 + 右侧细 separator 更分明
        title_bg = COLOR[color_key] if use_color else 'lightgray'
        title_bar = tk.Frame(gframe, bg=title_bg, height=4)
        title_bar.pack(side='top', fill='x')
        title_lbl = tk.Label(
            gframe, text=f"   {title}",
            bg=COLOR['header_bg'] if use_color else 'SystemButtonFace',
            fg=COLOR[color_key] if use_color else 'black',
            font=h2_font, anchor='w', padx=14, pady=6,
        )
        title_lbl.pack(side='top', fill='x')
        # 内容区
        body = tk.Frame(gframe, bg=bg)
        body.pack(side='top', fill='both', expand=True, padx=4, pady=4)
        return body

    def _make_card(parent, row, col, title, default_text='', sticky='nsew',
                    columnspan=1, height=9):
        # 🩹 [β.4.4 / 2026-05-18] Sir Session 3: 加 columnspan / height kwargs
        # 支持新加宽卡 (跨多列), 默认行为兼容老 caller (columnspan=1, height=9)
        card_bg = COLOR['card_bg'] if use_color else 'SystemButtonFace'
        # 🩹 [β.2.9.9] 卡片间距 +1px / 边框 +1 / 标题 padding 加倍 — Sir 体感更呼吸
        frame = tk.Frame(parent, bg=card_bg, highlightthickness=2,
                          highlightbackground=COLOR['card_border'] if use_color
                          else 'gray')
        frame.grid(row=row, column=col, sticky=sticky, padx=5, pady=5,
                   columnspan=columnspan)
        title_lbl = tk.Label(frame, text=title, bg=card_bg,
                              fg=COLOR['header_fg'] if use_color else 'black',
                              font=h2_font, anchor='w', padx=12, pady=7)
        title_lbl.pack(side='top', fill='x')
        body = scrolledtext.ScrolledText(
            frame, wrap='word', height=height, font=text_font,
            bg=card_bg, fg=COLOR['card_fg'] if use_color else 'black',
            insertbackground=fg, relief='flat', borderwidth=0,
            spacing1=2, spacing3=2,  # 行间距 (top/bottom)
            padx=8, pady=4,
        )
        body.pack(side='top', fill='both', expand=True, padx=2, pady=(0, 6))
        body.config(state='disabled')
        return body, title_lbl

    def _make_action_card(parent, row, col, title, sticky='nsew'):
        """带按钮列表的卡片. 返回 (frame, title_lbl, list_canvas).

        🩹 [β.5.24-fix / 2026-05-19] Sir 截图 'review 区不见了' 修.
        Root cause: 空 inner canvas 高度=0 → group_todo 整块塌掉.
        修法: 加 frame.configure(height=380) 强制最小高度 + propagate(False).
        """
        card_bg = COLOR['card_bg'] if use_color else 'SystemButtonFace'
        frame = tk.Frame(parent, bg=card_bg, highlightthickness=1,
                          highlightbackground=COLOR['card_border'] if use_color
                          else 'gray', height=380)
        frame.grid_propagate(False)  # 不让子组件压缩整 frame 高
        frame.grid(row=row, column=col, sticky=sticky, padx=3, pady=3)
        title_lbl = tk.Label(frame, text=title, bg=card_bg,
                              fg=COLOR['header_fg'] if use_color else 'black',
                              font=h2_font, anchor='w', padx=8, pady=4)
        title_lbl.pack(side='top', fill='x')
        # 内部 canvas + scrollbar 才能容多行按钮
        canvas_frame = tk.Frame(frame, bg=card_bg)
        canvas_frame.pack(side='top', fill='both', expand=True, padx=4, pady=(0, 4))
        canvas = tk.Canvas(canvas_frame, bg=card_bg, highlightthickness=0)
        scroll = tk.Scrollbar(canvas_frame, orient='vertical',
                               command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        inner = tk.Frame(canvas, bg=card_bg)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor='nw')

        def _on_inner_configure(_event):
            canvas.configure(scrollregion=canvas.bbox('all'))

        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)

        inner.bind('<Configure>', _on_inner_configure)
        canvas.bind('<Configure>', _on_canvas_configure)

        return frame, title_lbl, inner

    # ============ 整体评估条 (顶部, 一句话 + top 3 action) ============
    overall_bar = tk.Frame(root, bg=COLOR['header_bg'] if use_color else 'lightyellow')
    overall_bar.pack(side='top', fill='x', pady=(0, 0))

    overall_headline = tk.Label(
        overall_bar, text='', font=h2_font,
        bg=COLOR['header_bg'] if use_color else 'lightyellow',
        fg=COLOR['ok'] if use_color else 'darkgreen',
        anchor='w', padx=12, pady=4,
    )
    overall_headline.pack(side='top', fill='x')

    overall_actions = scrolledtext.ScrolledText(
        overall_bar, height=4, wrap='word', font=text_font,
        bg=COLOR['header_bg'] if use_color else 'lightyellow',
        fg=COLOR['fg'] if use_color else 'black',
        relief='flat', borderwidth=0,
    )
    overall_actions.pack(side='top', fill='x', padx=12, pady=(0, 4))
    overall_actions.config(state='disabled')

    # ============ 主容器 grid ============
    # 🩹 [β.2.9.9] padding 加大让卡片更呼吸 (6→10)
    main = tk.Frame(root, bg=bg)
    main.pack(side='top', fill='both', expand=True, padx=10, pady=6)
    main.columnconfigure(0, weight=1)
    # 🩹 [β.5.24 / 2026-05-19] Sir 01:58 反馈: 待处理框太小看不到新建议.
    # 老版本: 信息=2 / 待处理=2 / 观测=3 → 待处理只 25% 高度.
    # 新版本: 信息=1 / 待处理=5 / 观测=2 → 待处理 62.5%, 观测 25%, 信息 12.5%.
    # Sir 拍板才是 dashboard 主目的, 其他放小.
    main.rowconfigure(0, weight=1)   # 信息块 (缩小)
    main.rowconfigure(1, weight=5)   # 待处理块 (放大 — Sir 主目的)
    main.rowconfigure(2, weight=2)   # 观测块 (中)

    # ===== 第 1 块: 信息 =====
    group_info = _make_group_frame(main, '▌ 信息 — 你想了解的', 'group_info', 0)
    group_info.columnconfigure(0, weight=1, uniform='g1')
    group_info.columnconfigure(1, weight=1, uniform='g1')
    group_info.columnconfigure(2, weight=1, uniform='g1')
    group_info.rowconfigure(0, weight=1)

    card_concerns, lbl_concerns = _make_card(
        group_info, 0, 0,
        '🎯  贾维斯长期惦记你的什么',
    )
    card_relation, lbl_relation = _make_card(
        group_info, 0, 1,
        '💞  你们之间的默契',
    )
    card_health, lbl_health = _make_card(
        group_info, 0, 2,
        '📊  贾维斯自己健不健康',
    )

    # ===== 第 2 块: 待处理 =====
    group_todo = _make_group_frame(main, '▌ 待处理 — 等你拍板/取消', 'group_todo', 1)
    group_todo.columnconfigure(0, weight=1, uniform='g2')
    group_todo.columnconfigure(1, weight=1, uniform='g2')
    group_todo.rowconfigure(0, weight=1)

    todo_card_frame, lbl_todo, todo_inner = _make_action_card(
        group_todo, 0, 0,
        '📋  你要他盯的事 (Commitments)',
    )
    review_card_frame, lbl_review, review_inner = _make_action_card(
        group_todo, 0, 1,
        '⚠️  等你拍板的提案 (Concerns + 默契)',
    )

    # ===== 第 3 块: 观测 =====
    # 🩹 [β.2.9.9] 加第 4 列 "信任审计" — Sir 10:51 诚信审计治本卡片
    # 🩹 [β.4.4 / 2026-05-18] Sir Session 3: 加 row 1 跨 4 列 "言出必行健康度" 宽卡
    group_obs = _make_group_frame(main, '▌ 观测 — 看贾维斯有没有偏轨', 'group_obs', 2)
    group_obs.columnconfigure(0, weight=2, uniform='g3')
    group_obs.columnconfigure(1, weight=2, uniform='g3')
    group_obs.columnconfigure(2, weight=2, uniform='g3')
    group_obs.columnconfigure(3, weight=2, uniform='g3')
    group_obs.rowconfigure(0, weight=2)  # 上排 4 卡 (高)
    group_obs.rowconfigure(1, weight=1)  # 下排 1 宽卡 (矮)

    card_directive, lbl_directive = _make_card(
        group_obs, 0, 0,
        '📜  临时提醒规则 (Directive 偏移信号)',
    )
    card_daemon, lbl_daemon = _make_card(
        group_obs, 0, 1,
        '💡  后台管家 (Daemon 在不在跑)',
    )
    card_event, lbl_event = _make_card(
        group_obs, 0, 2,
        '🔔  贾维斯最近在干嘛 (实时事件流)',
    )
    card_mutations, lbl_mutations = _make_card(
        group_obs, 0, 3,
        '🔬  信任审计 (今天真改了什么)',
    )
    # 🩹 [β.4.4 / 2026-05-18] Sir Session 3 INTEGRITY_STACK L6: 言出必行健康度宽卡
    # 跨 4 列 (columnspan=4) 显 unverified claim 趋势 + 类型分布 + top 高频
    # 数据源: memory_pool/integrity_audit.jsonl + (可选) claim_stats.json
    card_integrity, lbl_integrity = _make_card(
        group_obs, 1, 0,
        '💯  言出必行健康度 (今天 claim 兑现)',
        columnspan=4, height=10,
    )

    # ============ 渲染函数 ============
    def _set_text(widget, text):
        widget.config(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', text)
        widget.config(state='disabled')

    def _diag_header(data):
        """所有卡片顶部统一的诊断块. data 含 diagnosis + suggestion."""
        diag = data.get('diagnosis', '')
        sugg = data.get('suggestion', '')
        if not diag:
            return ''
        return (
            f"📌 评估: {diag}\n"
            f"💡 建议: {sugg}\n"
            f"{'─' * 50}\n"
        )

    def _render_concerns(data):
        if data.get('err'):
            return f"读取失败: {data['err']}\n"
        lines = [_diag_header(data)]
        lines.append(f"惦记着 {len(data['rows'])} 件   (等你拍板的新建议 × {data['review_n']})")
        if not data['rows']:
            lines.append("\n(干净 — 贾维斯没在惦记什么)")
        else:
            for r in data['rows']:
                bar = '█' * (r['severity_pct'] // 10) + '░' * (10 - r['severity_pct'] // 10)
                lines.append(f"\n{r['warn']} {r['zh_name']}")
                lines.append(f"  紧迫度 [{bar}] {r['severity_pct']}%")
                lines.append(f"  └ {r['what']}")
                lines.append(f"  └ 你听过 {r['aligned']} 次 / 没理 {r['missed']} 次 / "
                              f"最近信号 {r['last_sig']}")
        return '\n'.join(lines) + '\n'

    def _render_relation(data):
        if data.get('err'):
            return f"读取失败: {data['err']}\n"
        lines = [_diag_header(data)]
        if data['jokes']:
            lines.append(f"😂 你们之间的梗 ({len(data['jokes'])} 个)")
            for j in data['jokes']:
                used_zh = f"用过 {j['used']} 次" if j['used'] > 0 else "还没用过"
                lines.append(f"   • \"{j['phrase']}\"")
                lines.append(f"      {j['birth']}, {used_zh}")
        else:
            lines.append("😂 你们还没产生共同的梗")

        if data['protocols']:
            lines.append(f"\n🤝 没说出口的默契 ({len(data['protocols'])} 条)")
            for p in data['protocols']:
                mark = '❗ 违过' if p['violations'] > 0 else '✓'
                lines.append(f"   {mark} {p['rule']}")
        else:
            lines.append("\n🤝 还没形成默契规则")

        if data['unfinished']:
            lines.append(f"\n📌 你停了没继续的事 ({len(data['unfinished'])} 件)")
            for u in data['unfinished']:
                lines.append(f"   • {u['topic']}   ({u['last']})")
        return '\n'.join(lines) + '\n'

    def _render_health(data):
        h = data.get('health_last', {})
        t = data.get('health_trend', {})
        kr = data.get('key_router', {})
        lines = [_diag_header(data)]
        if h:
            ws = h.get('ws_mb', 0)
            mem_status = '正常' if ws < 4000 else '⚠️ 偏高'
            lines.append(f"🧠 当前内存: {ws:.0f} MB  ({mem_status})")
            lines.append(f"🧵 后台线程: {h.get('threads', 0)} 个")
            lines.append(f"🪟 系统 Handle: {h.get('handles', 0)} 个")
            lines.append(f"⏱️  最后采集: {h.get('iso', '?')}")
        if t:
            lines.append(f"\n📈 过去 24h 趋势 (采样 {t['samples']} 次):")
            lines.append(f"   内存波动: {t['ws_mb_min']:.0f} → {t['ws_mb_max']:.0f} MB")
            lines.append(f"   线程峰值: {t['threads_max']} 个")
        if kr:
            if kr['dead_n'] == 0:
                lines.append(f"\n🔑 云端 API 钥匙: 全活 (共 {kr['total']} 把)")
            else:
                lines.append(f"\n🔑 云端 API 钥匙: ⚠️ 死 {kr['dead_n']} 把 / 共 {kr['total']} 把")
                for d in kr.get('dead_keys', []):
                    lines.append(f"   ⛔ {d}")
        lines.append(f"\n📁 历史日志: {data['log_count']} 份 / 总 {data['log_size_mb']:.1f} MB")
        return '\n'.join(lines) + '\n'

    def _render_directive(data):
        if data.get('err'):
            return f"读取失败: {data['err']}\n"
        h = data.get('health', {})
        lines = [
            _diag_header(data),
            f"共 {data['total']} 条规则   "
            f"✅ {h.get('ok', 0)}  ⚠️ {h.get('low_help', 0)}  "
            f"❌ {h.get('untriggered', 0)}  🌟 {h.get('candidate_merge', 0)}",
            "(这是贾维斯给自己的小备忘录, 比如\"工具失败别假装完成\")",
            "",
        ]
        for r in data['rows']:
            lines.append(f"{r['health']}  {r['zh_name']}")
            lines.append(f"   触发 {r['fired']} 次, 帮上 {r['helped']} 次"
                          f" ({r['help_rate']:.0f}%), 被拒 {r['rejected']} 次")
            if r['health'] != '✅':
                lines.append(f"   └ {r['health_zh']}")
            lines.append(f"   └ 最近触发: {r['last_fired_zh']}")
            lines.append("")
        return '\n'.join(lines)

    def _render_daemon(data):
        if data.get('err'):
            return f"读取失败: {data['err']}\n"
        live = sum(1 for d in data['daemons'] if d['live'])
        total = len(data['daemons'])
        lines = [_diag_header(data), f"在跑 {live} / 共 {total} 个", ""]
        for d in data['daemons']:
            mark = '✅' if d['live'] else '⚫'
            lines.append(f"{mark}  {d['zh']}{d['extra']}")
        return '\n'.join(lines) + '\n'

    def _render_events(data):
        if data.get('err'):
            return f"读取失败: {data['err']}\n"
        if not data['events']:
            return _diag_header(data) + "(暂无关键事件 — 贾维斯刚启动 / 静默观察中)\n"
        lines = [_diag_header(data), f"📄 {os.path.basename(data['log_path'])}"]
        for e in data['events']:
            lines.append(f"{e['ts']}  {e['tag']}  {e['body']}")
        return '\n'.join(lines) + '\n'

    def _render_mutations(data):
        if data.get('err'):
            return f"读取失败: {data['err']}\n"
        lines = [_diag_header(data)]
        lines.append(f"今天 {data['today_n']} 条  /  总 {data['total_n']} 条")
        if data['sources']:
            src_str = '  '.join(f"{k}={v}" for k, v in data['sources'].items())
            lines.append(f"来源: {src_str}")
        lines.append("")
        if not data['rows']:
            lines.append("(无记录 — Jarvis 还没真做过任何记忆变更)")
        else:
            for r in data['rows']:
                lines.append(f"  {r['time']}  [{r['source']}]")
                lines.append(f"    field: {r['field']}")
                if r['old']:
                    lines.append(f"    {r['old'][:50]}  →  {r['new'][:50]}")
                else:
                    lines.append(f"    → {r['new'][:50]}")
                lines.append(f"    ({r['age']}  conf={r['confidence']:.2f})")
        return '\n'.join(lines) + '\n'

    # 🩹 [β.4.4 / 2026-05-18] Sir Session 3 INTEGRITY_STACK L6: 言出必行卡渲染
    # 渲染顺序: 诊断 → 总数行 → kind 分布 → top 3 高频 → 7d ASCII trend chart
    # 不教主脑句式 (准则 6): Sir 看 UI 文案, 直接陈述事实
    def _render_integrity(data):
        if data.get('err'):
            return f"读取失败: {data['err']}\n"
        lines = [_diag_header(data)]
        # 总数 + verify_rate (claim_stats.json hook)
        head_line = (
            f"今天 {data['unverified_today']} 件未兑现  /  "
            f"7 天 {data['unverified_7d']} 件"
        )
        if data.get('verify_rate') is not None:
            head_line += f"  /  兑现率 {data['verify_rate']*100:.1f}%"
        else:
            head_line += "  /  兑现率 -- (Session 4 daemon 待加)"
        lines.append(head_line)
        lines.append('')

        if data['unverified_today'] == 0 and data['unverified_7d'] == 0:
            lines.append('(干净 — 没有 unverified claim)')
            return '\n'.join(lines) + '\n'

        # kind 分布 (今日)
        if data['kind_dist']:
            kind_str = '  '.join(
                f"{k}={v}" for k, v in
                sorted(data['kind_dist'].items(), key=lambda x: -x[1])
            )
            lines.append(f"📊 今日类型分布:  {kind_str}")
            lines.append('')

        # top 3 高频空头话 (7d 窗)
        if data['top_unverified']:
            lines.append('🔁 7 天最常空头话 top 3:')
            for r in data['top_unverified']:
                text = (r['text'] or '')[:60]
                lines.append(f"  [{r['kind']}] x{r['count']}  '{text}'")
            lines.append('')

        # 7d ASCII trend chart (5 行高条形图, 左 = 6 天前, 右 = 今天)
        trend = data.get('trend_7d') or []
        if trend and any(v > 0 for v in trend):
            max_v = max(trend)
            chart_h = 4  # 4 行高度 (含 0 行总 5 行渲染)
            lines.append('📉 7 天趋势 (左 = 6 天前, 右 = 今天):')
            # 每天一列, 每列宽 4 字符 (含 1 空格分隔)
            for row in range(chart_h, 0, -1):
                row_line = '   '
                for v in trend:
                    bar_h = int(v / max_v * chart_h) if max_v > 0 else 0
                    row_line += ' █ ' if bar_h >= row else ' · '
                lines.append(row_line)
            # 数值行
            num_line = '   ' + ''.join(f'{v:>3}' for v in trend)
            lines.append(num_line)
            # 标尺行 (相对今天的偏移)
            scale_line = '   -6d-5d-4d-3d-2d-1d今天'
            lines.append(scale_line)

        return '\n'.join(lines) + '\n'

    # ============ 待处理卡片 渲染 (带真按钮) ============
    def _clear_frame(frame):
        for child in frame.winfo_children():
            child.destroy()

    def _render_todo_buttons(data):
        _clear_frame(todo_inner)
        card_bg = COLOR['card_bg'] if use_color else 'SystemButtonFace'

        if data.get('err'):
            tk.Label(todo_inner, text=f"读取失败: {data['err']}",
                      bg=card_bg, fg=COLOR['err'] if use_color else 'red',
                      font=text_font, anchor='w').pack(fill='x', padx=4, pady=4)
            return

        # 顶部诊断条
        diag = data.get('diagnosis', '')
        sugg = data.get('suggestion', '')
        if diag:
            tk.Label(todo_inner, text=f"📌 评估: {diag}",
                      bg=card_bg, fg=COLOR['warn'] if use_color else 'darkred',
                      font=h3_font, anchor='w', wraplength=420).pack(
                fill='x', padx=4, pady=(4, 0))
            tk.Label(todo_inner, text=f"💡 建议: {sugg}",
                      bg=card_bg, fg=COLOR['dim'] if use_color else 'gray',
                      font=btn_font, anchor='w', wraplength=420).pack(
                fill='x', padx=4, pady=(0, 6))

        if not data['rows']:
            tk.Label(todo_inner, text='✓ 没有待办 (空闲)',
                      bg=card_bg, fg=COLOR['ok'] if use_color else 'darkgreen',
                      font=text_font, anchor='w').pack(fill='x', padx=4, pady=8)
            return

        summary = (f"⏳ 待到点 {data['count_pending']} 件   "
                   f"✓ 已提过 {data['count_done']} 件")
        tk.Label(todo_inner, text=summary, bg=card_bg,
                  fg=COLOR['fg'] if use_color else 'black',
                  font=h3_font, anchor='w').pack(fill='x', padx=4, pady=(4, 2))

        for r in data['rows']:
            row_bg = card_bg
            row = tk.Frame(todo_inner, bg=row_bg)
            row.pack(fill='x', padx=4, pady=2)

            txt_color = COLOR['ok'] if use_color and r['state'] == 'done' \
                else (COLOR['warn'] if use_color and r['state'] == 'overdue'
                       else (COLOR['fg'] if use_color else 'black'))

            label_text = f"[{r['state_zh']}]  {r['when']}  {r['desc']}"
            tk.Label(row, text=label_text, bg=row_bg, fg=txt_color,
                      font=text_font, anchor='w', justify='left',
                      wraplength=400).pack(side='left', fill='x', expand=True)

            if r['state'] in ('pending', 'overdue'):
                def _make_cancel(cw_id=r['id'], desc=r['desc']):
                    def _do():
                        if messagebox.askyesno(
                                '取消待办',
                                f'确定要取消这条待办吗?\n\n  {desc}\n\n'
                                f'(贾维斯不会再到点提醒你)'):
                            # 🩹 [β.2.9.8] 接收 subprocess 完整输出, 失败弹窗给 Sir 看
                            def _on_done(ok, out):
                                # _set_status 显示在顶部 + 用户可点 "立刻刷新" 验证
                                short = (out or '').strip().splitlines()
                                short_first = short[0] if short else ''
                                if ok:
                                    msg = f'✓ 已取消待办 #{cw_id}: {short_first[:80]}'
                                else:
                                    msg = f'❌ 取消 #{cw_id} 失败: {short_first[:80]}'
                                # tkinter 不能跨 thread 直接更新 widget, 用 after
                                root.after(0, lambda: _set_status(msg, ok))
                                # 顺便弹窗让 Sir 一定看到
                                root.after(50, lambda: messagebox.showinfo(
                                    '取消结果',
                                    f"待办 #{cw_id} 取消结果:\n\n"
                                    f"{'✓ 成功' if ok else '❌ 失败'}\n\n"
                                    f"脚本输出:\n{(out or '')[:400]}"
                                ))
                                # 1.5s 后强制刷新让 Sir 看到列表变化
                                root.after(1500, _do_refresh)
                            action_cancel_commitment(cw_id, on_done=_on_done)
                    return _do
                tk.Button(row, text='🚫 取消', command=_make_cancel(),
                           font=btn_font,
                           bg=COLOR['btn_danger'] if use_color else 'SystemButtonFace',
                           padx=4).pack(side='right', padx=2)

    def _render_review_buttons(data):
        """🩹 [β.5.24 / 2026-05-19] 全面重构 review 卡片渲染.

        Sir 01:58 反馈:
        - 'X' 拒绝说不存在 → 过滤短 preview + 加错误 fallback (action 层)
        - 框太小看不到新建议 → main grid row weight 5 (放大到 62%)
        - 排版老旧 → 每条独立 card-in-card with 更大字号 / source 标签 / rationale 详情
        - 信息不够到位 → 显 preview + rationale + source + created_iso

        UI 结构 (每条):
        ┌────────────────────────────────────────────────┐
        │ [来源]                                          │
        │ ✦ <preview 完整文本, 大字号>                    │
        │   └ <rationale 详细 why, 灰字>                  │
        │   └ 创建时间: 2026-05-19 22:02                  │
        │                       [✅ 通过] [❌ 拒绝]       │
        └────────────────────────────────────────────────┘
        """
        _clear_frame(review_inner)
        card_bg = COLOR['card_bg'] if use_color else 'SystemButtonFace'
        item_card_bg = '#1a2540' if use_color else 'gray95'

        # 顶部诊断条
        diag = data.get('diagnosis', '')
        sugg = data.get('suggestion', '')
        if diag:
            tk.Label(review_inner, text=f"📌 {diag}",
                      bg=card_bg,
                      fg=COLOR['warn'] if use_color else 'darkred',
                      font=h3_font, anchor='w', wraplength=820).pack(
                fill='x', padx=8, pady=(6, 0))
            tk.Label(review_inner, text=f"💡 {sugg}",
                      bg=card_bg, fg=COLOR['dim'] if use_color else 'gray',
                      font=text_font, anchor='w', wraplength=820).pack(
                fill='x', padx=8, pady=(0, 6))

        if not data['items']:
            tk.Label(review_inner,
                      text='✓ 没有待审 — 贾维斯没主动提新建议',
                      bg=card_bg,
                      fg=COLOR['ok'] if use_color else 'darkgreen',
                      font=h3_font, anchor='w').pack(
                fill='x', padx=8, pady=20)
            return

        tk.Label(review_inner,
                  text=f"⚠️ {len(data['items'])} 条提案等你拍板:",
                  bg=card_bg,
                  fg=COLOR['fg'] if use_color else 'black',
                  font=h3_font, anchor='w').pack(
            fill='x', padx=8, pady=(4, 6))

        # 按 base kind 分组 (concern / relational / directive / cooldown)
        by_kind: Dict[str, list] = {}
        for it in data['items']:
            base_kind = it['kind'].split('/')[0]
            by_kind.setdefault(base_kind, []).append(it)

        kind_label = {
            'concern': '🎯 长期关心',
            'relational': '💞 你们之间',
            'directive': '📜 临时规则',
            'cooldown': '⏰ Cooldown 阈值 (L7 LLM propose)',
        }

        def _make_action(item, action_kind):
            """生成按钮 callback. item dict 含 kind/id/preview/proposed_value 等."""
            kind = item['kind'].split('/')[0]
            base_kind = kind
            item_id = item['id']
            preview = item['preview']
            action_fn = (action_activate_review if action_kind == 'activate'
                          else action_reject_review)
            verb_zh = '通过' if action_kind == 'activate' else '拒绝'
            extra = None
            if base_kind == 'cooldown':
                extra = {'proposed_value': item.get('proposed_value')}

            def _do():
                # 🩹 [β.5.24-fix2 / 2026-05-19] Sir 02:17 反馈"同意默契没反应".
                # Root cause: 我去掉了完成弹窗, status bar 反馈不显眼.
                # 修法: 加回 messagebox.showinfo 完成弹窗 (但保持无确认弹窗 - 拍板就拍板)
                def _on_done(ok, out):
                    short = (out or '').strip().splitlines()
                    first = short[0] if short else ''
                    if ok:
                        msg = f'✓ {verb_zh}: {first[:60]}'
                    else:
                        msg = f'❌ {verb_zh}失败: {first[:60]}'
                    root.after(0, lambda: _set_status(msg, ok))
                    # 完成弹窗 (让 Sir 一定看到)
                    root.after(50, lambda: messagebox.showinfo(
                        f'{verb_zh}结果',
                        f"对 \"{preview[:60]}\" {verb_zh}:\n\n"
                        f"{'✓ 成功' if ok else '❌ 失败'}\n\n"
                        f"脚本输出:\n{(out or '(无输出)')[:400]}"
                    ))
                    # 1.5s 后强制刷新让 Sir 看到列表变化
                    root.after(1500, _do_refresh)

                action_fn(base_kind, item_id, on_done=_on_done, extra=extra)
            return _do

        for kind, items in by_kind.items():
            section_label = kind_label.get(kind, kind)
            section = tk.Frame(review_inner, bg=card_bg)
            section.pack(fill='x', padx=4, pady=(8, 2))

            tk.Label(section,
                      text=f"  {section_label}  · {len(items)} 条",
                      bg=card_bg,
                      fg=COLOR['header_fg'] if use_color else 'black',
                      font=h3_font, anchor='w').pack(fill='x', padx=2, pady=2)

            # 每条 → 独立 item card
            for it in items:
                ic = tk.Frame(section, bg=item_card_bg,
                                 highlightbackground=COLOR['dim'],
                                 highlightthickness=1)
                ic.pack(fill='x', padx=6, pady=3)
                # 顶部 source + 时间
                meta_bits = []
                src = it.get('source', '')
                if src:
                    meta_bits.append(f"来源: {src}")
                created = it.get('created_iso', '')
                if created:
                    meta_bits.append(f"⏱ {created}")
                if 'severity' in it:
                    meta_bits.append(f"紧迫度: {it['severity']:.2f}")
                if meta_bits:
                    tk.Label(ic, text=' · '.join(meta_bits), bg=item_card_bg,
                              fg=COLOR['dim'] if use_color else 'gray',
                              font=btn_font, anchor='w').pack(
                        fill='x', padx=6, pady=(4, 1))
                # 主预览 (大字号)
                tk.Label(ic, text=f"✦  {it['preview']}", bg=item_card_bg,
                          fg=COLOR['fg'] if use_color else 'black',
                          font=h3_font, anchor='w', justify='left',
                          wraplength=780).pack(
                    fill='x', padx=6, pady=(2, 2))
                # rationale 详情 (灰字)
                rat = it.get('rationale', '')
                if rat:
                    tk.Label(ic, text=f"   └ {rat}", bg=item_card_bg,
                              fg=COLOR['dim'] if use_color else 'gray',
                              font=text_font, anchor='w', justify='left',
                              wraplength=760).pack(
                        fill='x', padx=6, pady=(0, 4))
                # 按钮行 (右对齐)
                btn_row = tk.Frame(ic, bg=item_card_bg)
                btn_row.pack(fill='x', padx=6, pady=(2, 6))
                tk.Button(
                    btn_row, text='✅ 通过',
                    command=_make_action(it, 'activate'),
                    font=btn_font,
                    bg=COLOR['btn_ok'] if use_color else 'SystemButtonFace',
                    padx=12, pady=2).pack(side='right', padx=3)
                tk.Button(
                    btn_row, text='❌ 拒绝',
                    command=_make_action(it, 'reject'),
                    font=btn_font,
                    bg=COLOR['btn_danger'] if use_color else 'SystemButtonFace',
                    padx=12, pady=2).pack(side='right', padx=3)

    # ============ 主刷新 ============
    def _do_refresh():
        if paused['value']:
            now_lbl.config(text=f"⏸ 暂停中   (上次刷新 {time.strftime('%H:%M:%S')})")
            return
        try:
            t0 = time.time()
            now = read_now_status()
            todo = read_sir_commitments()
            promise = read_jarvis_promises()
            concerns = read_concerns()
            relation = read_relational()
            directive = read_directives()
            daemon = read_daemon_status()
            health = read_system_health()
            review = read_review_queues()
            events = read_event_stream(limit=25)
            mutations = read_memory_mutations()  # 🩹 [β.2.9.9] 信任审计
            integrity = read_integrity_stats()  # 🩹 [β.4.4] L6 言出必行
            overall = compute_overall_status(
                concerns, directive, promise, relation,
                daemon, health, review, events,
                mutations=mutations, integrity=integrity)
            elapsed = (time.time() - t0) * 1000

            # Header 状态条
            in_conv = now.get('in_conversation', '?')
            in_conv_emoji = '💬' if in_conv == '在对话中' else '👀'
            now_text = (
                f"  {time.strftime('%Y-%m-%d  %H:%M:%S')}     "
                f"{in_conv_emoji} {in_conv}     "
                f"📡 进程已上线 {now.get('session_age', '?')}     "
                f"📄 日志活跃 {now.get('log_age', '?')}"
            )
            now_lbl.config(text=now_text)

            # 顶部整体评估
            level_color = {
                'ok': COLOR['ok'],
                'warn': COLOR['warn'],
                'crit': COLOR['err'],
            }.get(overall['level'], COLOR['fg'])
            overall_headline.config(
                text=f"  🤖 贾维斯整体状态: {overall['headline']}",
                fg=level_color if use_color else 'black',
            )
            if overall['top_actions']:
                action_lines = ['你要看的事 (按重要性):']
                for i, act in enumerate(overall['top_actions'], 1):
                    mark = {'crit': '❌', 'warn': '⚠️', 'info': '📝'}.get(
                        act['level'], '·')
                    action_lines.append(
                        f"  {i}. {mark} {act['what']}\n     → {act['how']}")
                action_text = '\n'.join(action_lines)
            else:
                action_text = '✅ 一切正常 — 你今天不用操心贾维斯, 让他自己跑.'
            overall_actions.config(state='normal')
            overall_actions.delete('1.0', 'end')
            overall_actions.insert('1.0', action_text)
            overall_actions.config(state='disabled')

            _set_text(card_concerns, _render_concerns(concerns))
            _set_text(card_relation, _render_relation(relation))
            _set_text(card_health, _render_health(health))
            _set_text(card_directive, _render_directive(directive))
            _set_text(card_daemon, _render_daemon(daemon))
            _set_text(card_event, _render_events(events))
            _set_text(card_mutations, _render_mutations(mutations))
            _set_text(card_integrity, _render_integrity(integrity))  # 🩹 [β.4.4]

            _render_todo_buttons(todo)
            _render_review_buttons(review)

            # 标题徽章
            lbl_concerns.config(
                text=f"🎯  贾维斯长期惦记你的什么  ({len(concerns['rows'])} 件 + 待拍板 {concerns['review_n']})")
            lbl_relation.config(
                text=f"💞  你们之间的默契  ({len(relation['jokes'])}梗 + {len(relation['protocols'])}默 + {len(relation['unfinished'])}未)")
            lbl_health.config(
                text=f"📊  贾维斯自己健不健康  ({health['health_last'].get('ws_mb', 0):.0f}MB · {health.get('log_count', 0)}log)")
            lbl_todo.config(
                text=f"📋  你要他盯的事  (待 {todo['count_pending']} · 已提 {todo['count_done']})")
            # 🩹 [β.5.24 / 2026-05-19] review 标题徽章按 kind 分布显
            _kind_counts = {}
            for _it in review['items']:
                _bk = _it['kind'].split('/')[0]
                _kind_counts[_bk] = _kind_counts.get(_bk, 0) + 1
            _badge_bits = []
            for _bk, _zh in (('concern', '🎯'), ('relational', '💞'),
                             ('directive', '📜'), ('cooldown', '⏰')):
                if _kind_counts.get(_bk, 0) > 0:
                    _badge_bits.append(f"{_zh}{_kind_counts[_bk]}")
            _badge = '·'.join(_badge_bits) if _badge_bits else '空'
            lbl_review.config(
                text=f"⚠️  等你拍板的提案  ({len(review['items'])} 条 · {_badge})")
            h = directive['health']
            lbl_directive.config(
                text=f"📜  临时提醒规则  ({directive['total']} 条 · "
                      f"⚠️ 偏移 {h.get('low_help', 0) + h.get('untriggered', 0)})")
            live_n = sum(1 for d in daemon['daemons'] if d['live'])
            lbl_daemon.config(
                text=f"💡  后台管家  ({live_n}/{len(daemon['daemons'])} 在跑)")
            lbl_event.config(
                text=f"🔔  贾维斯最近在干嘛  ({len(events['events'])} 件)")
            lbl_mutations.config(
                text=f"🔬  信任审计 — 今天真改了什么  "
                     f"({mutations['today_n']}/{mutations['total_n']})")
            # 🩹 [β.4.4 / 2026-05-18] Sir Session 3: 言出必行卡标题徽章
            integ_t = integrity.get('unverified_today', 0)
            integ_w = integrity.get('unverified_7d', 0)
            integ_rate = integrity.get('verify_rate')
            rate_str = f" · {integ_rate*100:.0f}%" if integ_rate is not None else ""
            lbl_integrity.config(
                text=f"💯  言出必行健康度  "
                     f"(今日 {integ_t} · 7d {integ_w}{rate_str})")

            _set_status(f"刷新 {time.strftime('%H:%M:%S')}  ({elapsed:.0f}ms)", True)
        except Exception as e:
            _set_status(f"刷新失败: {type(e).__name__} {e}", False)
            import traceback
            traceback.print_exc()

    def _schedule_refresh():
        _do_refresh()
        root.after(refresh_s * 1000, _schedule_refresh)

    # 快捷键
    root.bind('<Control-r>', lambda e: _force_refresh())
    root.bind('<Control-R>', lambda e: _force_refresh())
    root.bind('<Control-p>', lambda e: _toggle_pause())
    root.bind('<Control-P>', lambda e: _toggle_pause())
    root.bind('<Control-q>', lambda e: root.destroy())
    root.bind('<F5>', lambda e: _force_refresh())

    root.after(100, _schedule_refresh)
    root.mainloop()
    return 0


def print_snapshot() -> int:
    """文本模式: 一次性打印所有 reader 结果. 给 CI / SSH 用."""
    sep = '=' * 70
    print(f"\n{sep}\n贾维斯总览快照  {time.strftime('%Y-%m-%d %H:%M:%S')}\n{sep}\n")
    sections = [
        ('🤖 此刻状态', read_now_status),
        ('🎯 长期惦记 (Concerns)', read_concerns),
        ('💞 你们之间 (Relational)', read_relational),
        ('📊 系统健康', read_system_health),
        ('📋 待办 (Commitments)', read_sir_commitments),
        ('🤝 贾维斯口头承诺 (Promise)', read_jarvis_promises),
        ('⚠️ 待审阅', read_review_queues),
        ('📜 临时提醒规则 (Directive)', read_directives),
        ('💡 后台管家 (Daemon)', read_daemon_status),
        ('🔔 实时事件流', lambda: read_event_stream(limit=15)),
        ('🔬 信任审计 (今天真改了什么)', read_memory_mutations),  # β.2.9.9
        ('💯 言出必行健康度', read_integrity_stats),  # β.4.4 Session 3
    ]
    for title, reader in sections:
        print(f"\n--- {title} ---")
        try:
            d = reader()
            print(json.dumps(d, ensure_ascii=False, indent=2, default=str)[:1500])
        except Exception as e:
            print(f"读取失败: {e}")
    print(f"\n{sep}\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--refresh', type=int, default=5,
                    help='自动刷新间隔秒 (默认 5)')
    ap.add_argument('--no-color', action='store_true',
                    help='不上色 (默认系统主题, 适合截图打印)')
    ap.add_argument('--geometry', default='1500x950',
                    help='窗口尺寸 W x H (默认 1500x950)')
    ap.add_argument('--text-only', action='store_true',
                    help='不开 GUI, 仅打印一次性快照 (CI / SSH 友好)')
    args = ap.parse_args()
    if args.text_only:
        return print_snapshot()
    return launch_gui(args.refresh, not args.no_color, args.geometry)


if __name__ == '__main__':
    sys.exit(main())
