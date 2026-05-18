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
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                        errors='replace')
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
    """🤝 贾维斯口头承诺 — PromiseLog"""
    out = {'rows': [], 'pending_n': 0, 'fulfilled_n': 0, 'untracked_n': 0,
           'total': 0, 'err': None}
    data = _safe_read_json(os.path.join(MEM, 'jarvis_promise_log.json'), {})
    if not isinstance(data, dict):
        out['err'] = 'promise_log 格式异常'
        return out
    promises = list(data.values())
    promises.sort(key=lambda p: -float(p.get('registered_at', 0) or 0))
    out['total'] = len(promises)
    for p in promises:
        st = p.get('state', '?')
        if st == 'pending':
            out['pending_n'] += 1
        elif st == 'fulfilled':
            out['fulfilled_n'] += 1
        elif st == 'untracked':
            out['untracked_n'] += 1
    for p in promises[:12]:
        st = p.get('state', '?')
        st_zh = {
            'pending': '⏳ 还没动',
            'fulfilled': '✓ 已兑现',
            'overdue': '⏰ 超时',
            'untracked': '❓ 没监控到',
            'cancelled': '🚫 已撤销',
        }.get(st, st)
        out['rows'].append({
            'id': p.get('id', '?'),
            'state': st,
            'state_zh': st_zh,
            'kind': p.get('kind', '?'),
            'desc': (p.get('description') or '')[:80],
            'when': p.get('deadline_str') or '-',
            'age': _humanize_age_zh(float(p.get('registered_at', 0) or 0)),
            'evidence_n': len(p.get('evidence', []) or []),
        })

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
    """💞 你们之间的默契 — RelationalState L2"""
    out = {'jokes': [], 'protocols': [], 'unfinished': [], 'review_n': 0, 'err': None}
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
    review = _safe_read_json(os.path.join(MEM, 'relational_review.json'), [])
    if isinstance(review, list):
        out['review_n'] = len(review)
    elif isinstance(review, dict):
        out['review_n'] = sum(
            len(v) for v in review.values() if isinstance(v, (list, dict))
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

def _find_latest_log() -> str:
    pointer = os.path.join(LOG_DIR, 'latest.txt')
    if os.path.exists(pointer):
        try:
            with open(pointer, 'r', encoding='utf-8', errors='ignore') as f:
                p = f.read().strip()
                if os.path.isabs(p) and os.path.exists(p):
                    return p
                cand = os.path.join(ROOT, p)
                if os.path.exists(cand):
                    return cand
        except Exception:
            pass
    if not os.path.isdir(LOG_DIR):
        return ''
    cands = []
    for f in os.listdir(LOG_DIR):
        if f.startswith('jarvis_') and f.endswith('.log'):
            full = os.path.join(LOG_DIR, f)
            try:
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
    ('Chronos', '心跳起搏 (每秒看一眼系统时间)',
     r'起搏器|ChronosTick.*started'),
    ('SoulArchivist', '灵魂归档 (Sir 长期 profile 演化)',
     r'SoulArchivist'),
    ('ScreenshotSentinel', '截屏哨兵 (定期抓你屏幕看你在干啥)',
     r'ScreenshotSentinel|截屏哨兵'),
    ('UserStatusLedger', 'Sir 状态账本 (生理/情绪/活动历史快照)',
     r'UserStatusLedger'),
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

    # 📌 诊断
    live = sum(1 for x in out['daemons'] if x['live'])
    total = len(out['daemons'])
    crit_offline = [x for x in out['daemons']
                     if not x['live'] and x['id'] in
                     ('ProactiveCare', 'Inconsistency', 'HealthProbe',
                      'Return', 'Commitment')]
    if live == total:
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

def read_review_queues() -> Dict:
    """⚠️ 等你拍板的提案 — concerns/relational/directive review"""
    out = {'items': []}
    cr = _safe_read_json(os.path.join(MEM, 'concerns_review.json'), [])
    items_cr = cr if isinstance(cr, list) else (cr.get('proposals', []) if isinstance(cr, dict) else [])
    for i in items_cr[:5]:
        if isinstance(i, dict):
            out['items'].append({
                'kind': 'concern',
                'kind_zh': '🎯 长期关心',
                'id': i.get('id', '?'),
                'preview': (i.get('what_i_watch') or i.get('id') or '?')[:90],
                'cli': f"python scripts/concerns_dump.py --review",
            })
    rr = _safe_read_json(os.path.join(MEM, 'relational_review.json'), [])
    if isinstance(rr, list):
        for i in rr[:5]:
            if isinstance(i, dict):
                out['items'].append({
                    'kind': 'relational',
                    'kind_zh': '💞 你们之间',
                    'id': i.get('id', '?'),
                    'preview': (i.get('phrase') or i.get('rule') or
                                 i.get('topic') or '?')[:90],
                    'cli': f"python scripts/relational_dump.py --review-list",
                })
    elif isinstance(rr, dict):
        for kind, lst in rr.items():
            if isinstance(lst, list):
                for i in lst[:3]:
                    if isinstance(i, dict):
                        out['items'].append({
                            'kind': f'relational/{kind}',
                            'kind_zh': f'💞 {kind}',
                            'id': i.get('id', '?'),
                            'preview': (i.get('phrase') or i.get('rule') or
                                         i.get('topic') or '?')[:90],
                            'cli': f"python scripts/relational_dump.py --review-list",
                        })
    # 过滤掉 preview == '?' 的垃圾条目 (review json 字段空)
    out['items'] = [i for i in out['items'] if i['preview'] != '?']

    # 📌 诊断
    n = len(out['items'])
    if n == 0:
        out['diagnosis'] = '✅ 没什么要你定的'
        out['suggestion'] = '无需操作'
    elif n <= 3:
        out['diagnosis'] = f'📝 {n} 条小提案, 不急'
        out['suggestion'] = '有空时点 "处理这批" 按钮逐条 ✅/❌'
    else:
        out['diagnosis'] = f'⚠️ {n} 条提案累积 — 贾维斯想了解你的看法'
        out['suggestion'] = '建议今天抽 5 分钟处理 (按钮在卡片底部)'
    return out


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
                             review: dict, events: dict) -> dict:
    """🤖 整体一句话 — 综合所有 reader, 给 Sir 看就懂的 top-3 重点"""
    out = {'level': 'ok', 'headline': '', 'top_actions': []}

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

    # critical daemon offline
    crit_off = [x for x in daemon.get('daemons', [])
                 if not x.get('live') and x.get('id') in
                 ('ProactiveCare', 'Inconsistency', 'HealthProbe', 'Commitment')]
    if crit_off:
        names = '/'.join(x['id'] for x in crit_off[:3])
        issues.append((
            'crit',
            f'{len(crit_off)} 个关键管家未启动: {names}',
            '重启贾维斯主程序',
        ))

    # memory abnormal
    ws_mb = health.get('health_last', {}).get('ws_mb', 0)
    if ws_mb > 4000:
        issues.append((
            'warn',
            f'内存 {ws_mb:.0f}MB 偏高 (> 4GB) — 可能泄漏',
            '看 24h 趋势; 必要重启',
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


def action_activate_review(kind: str, item_id: str, on_done=None) -> None:
    """✅ 通过一条 review 提案 (concern / relational).

    🩹 [β.2.9.8 / 2026-05-18] Sir 10:34 痛点: 不想跳终端, 直接按钮 yes/no.
    复用 scripts/<kind>_dump.py --activate <id> 路径, 不直接写 json (避免
    破坏单例 + 主程序写锁竞争).
    """
    if kind.startswith('concern'):
        script = 'scripts/concerns_dump.py'
    elif kind.startswith('relational'):
        script = 'scripts/relational_dump.py'
    else:
        if on_done:
            on_done(False, f'不支持的 kind: {kind}')
        return
    _run_script_subprocess(
        [script, '--activate', str(item_id)],
        on_done=on_done,
    )


def action_reject_review(kind: str, item_id: str, on_done=None) -> None:
    """❌ 拒绝一条 review 提案 (转 archived)."""
    if kind.startswith('concern'):
        script = 'scripts/concerns_dump.py'
    elif kind.startswith('relational'):
        script = 'scripts/relational_dump.py'
    else:
        if on_done:
            on_done(False, f'不支持的 kind: {kind}')
        return
    _run_script_subprocess(
        [script, '--reject', str(item_id)],
        on_done=on_done,
    )


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
    root.title("贾维斯总览看板  J.A.R.V.I.S. Dashboard  β.2.9.8")
    root.geometry(geometry)
    if use_color:
        root.configure(bg=COLOR['bg'])

    try:
        default_font = tkfont.nametofont('TkDefaultFont')
        default_font.configure(family='Microsoft YaHei UI', size=9)
        text_font = tkfont.Font(family='Microsoft YaHei UI', size=10)
        h1_font = tkfont.Font(family='Microsoft YaHei UI', size=14, weight='bold')
        h2_font = tkfont.Font(family='Microsoft YaHei UI', size=11, weight='bold')
        h3_font = tkfont.Font(family='Microsoft YaHei UI', size=10, weight='bold')
        btn_font = tkfont.Font(family='Microsoft YaHei UI', size=9)
    except Exception:
        text_font = h1_font = h2_font = h3_font = btn_font = None

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
        gframe.grid(row=row, column=0, sticky='nsew', padx=0, pady=(8, 0))
        # 标题条
        title_bg = COLOR[color_key] if use_color else 'lightgray'
        title_lbl = tk.Label(
            gframe, text=f"  {title}",
            bg=title_bg,
            fg=COLOR['header_bg'] if use_color else 'black',
            font=h3_font, anchor='w', padx=10, pady=3,
        )
        title_lbl.pack(side='top', fill='x')
        # 内容区
        body = tk.Frame(gframe, bg=bg)
        body.pack(side='top', fill='both', expand=True, padx=2, pady=2)
        return body

    def _make_card(parent, row, col, title, default_text='', sticky='nsew'):
        card_bg = COLOR['card_bg'] if use_color else 'SystemButtonFace'
        frame = tk.Frame(parent, bg=card_bg, highlightthickness=1,
                          highlightbackground=COLOR['card_border'] if use_color
                          else 'gray')
        frame.grid(row=row, column=col, sticky=sticky, padx=3, pady=3)
        title_lbl = tk.Label(frame, text=title, bg=card_bg,
                              fg=COLOR['header_fg'] if use_color else 'black',
                              font=h2_font, anchor='w', padx=8, pady=4)
        title_lbl.pack(side='top', fill='x')
        body = scrolledtext.ScrolledText(
            frame, wrap='word', height=8, font=text_font,
            bg=card_bg, fg=COLOR['card_fg'] if use_color else 'black',
            insertbackground=fg, relief='flat', borderwidth=0,
        )
        body.pack(side='top', fill='both', expand=True, padx=4, pady=(0, 4))
        body.config(state='disabled')
        return body, title_lbl

    def _make_action_card(parent, row, col, title, sticky='nsew'):
        """带按钮列表的卡片. 返回 (frame, title_lbl, list_canvas)."""
        card_bg = COLOR['card_bg'] if use_color else 'SystemButtonFace'
        frame = tk.Frame(parent, bg=card_bg, highlightthickness=1,
                          highlightbackground=COLOR['card_border'] if use_color
                          else 'gray')
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
    main = tk.Frame(root, bg=bg)
    main.pack(side='top', fill='both', expand=True, padx=6, pady=4)
    main.columnconfigure(0, weight=1)
    main.rowconfigure(0, weight=2)  # 信息块
    main.rowconfigure(1, weight=2)  # 待处理块
    main.rowconfigure(2, weight=3)  # 观测块

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
    group_obs = _make_group_frame(main, '▌ 观测 — 看贾维斯有没有偏轨', 'group_obs', 2)
    group_obs.columnconfigure(0, weight=2, uniform='g3')
    group_obs.columnconfigure(1, weight=2, uniform='g3')
    group_obs.columnconfigure(2, weight=2, uniform='g3')
    group_obs.rowconfigure(0, weight=1)

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
        _clear_frame(review_inner)
        card_bg = COLOR['card_bg'] if use_color else 'SystemButtonFace'

        # 顶部诊断条
        diag = data.get('diagnosis', '')
        sugg = data.get('suggestion', '')
        if diag:
            tk.Label(review_inner, text=f"📌 评估: {diag}",
                      bg=card_bg, fg=COLOR['warn'] if use_color else 'darkred',
                      font=h3_font, anchor='w', wraplength=420).pack(
                fill='x', padx=4, pady=(4, 0))
            tk.Label(review_inner, text=f"💡 建议: {sugg}",
                      bg=card_bg, fg=COLOR['dim'] if use_color else 'gray',
                      font=btn_font, anchor='w', wraplength=420).pack(
                fill='x', padx=4, pady=(0, 6))

        if not data['items']:
            tk.Label(review_inner, text='✓ 没有待审 — 贾维斯没主动提新建议',
                      bg=card_bg, fg=COLOR['ok'] if use_color else 'darkgreen',
                      font=text_font, anchor='w').pack(fill='x', padx=4, pady=8)
            return

        tk.Label(review_inner,
                  text=f"⚠️ {len(data['items'])} 条提案等你拍板:",
                  bg=card_bg, fg=COLOR['fg'] if use_color else 'black',
                  font=h3_font, anchor='w').pack(fill='x', padx=4, pady=(4, 2))

        # 🩹 [β.2.9.8] 按 kind 分组, 每条独立 ✅/❌ 按钮 (Sir 10:34 痛点)
        by_kind: Dict[str, list] = {}
        for it in data['items']:
            base_kind = it['kind'].split('/')[0]
            by_kind.setdefault(base_kind, []).append(it)

        def _make_action(kind, item_id, action_kind, preview):
            """生成按钮 callback. 闭包捕获参数. 返回结果弹窗 + 刷新 dashboard."""
            action_fn = (action_activate_review if action_kind == 'activate'
                          else action_reject_review)
            verb_zh = '通过' if action_kind == 'activate' else '拒绝'

            def _do():
                if not messagebox.askyesno(
                        f'{verb_zh}提案',
                        f'确定要{verb_zh}这条吗?\n\n  {preview}\n\n'
                        f'(可在 scripts/relational_dump.py / concerns_dump.py 撤回)'):
                    return

                def _on_done(ok, out):
                    short = (out or '').strip().splitlines()
                    first = short[0] if short else ''
                    if ok:
                        msg = f'✓ {verb_zh}成功: {first[:80]}'
                    else:
                        msg = f'❌ {verb_zh}失败: {first[:80]}'
                    root.after(0, lambda: _set_status(msg, ok))
                    root.after(50, lambda: messagebox.showinfo(
                        f'{verb_zh}结果',
                        f"对 \"{preview[:60]}\" {verb_zh}:\n\n"
                        f"{'✓ 成功' if ok else '❌ 失败'}\n\n"
                        f"脚本输出:\n{(out or '')[:400]}"
                    ))
                    root.after(1500, _do_refresh)

                action_fn(kind, item_id, on_done=_on_done)
            return _do

        for kind, items in by_kind.items():
            section = tk.Frame(review_inner, bg=card_bg)
            section.pack(fill='x', padx=2, pady=(6, 0))

            label_zh = {'concern': '🎯 长期关心提案',
                         'relational': '💞 默契提案'}.get(kind, kind)
            tk.Label(section, text=f"  {label_zh}  ({len(items)} 条)",
                      bg=card_bg, fg=COLOR['header_fg'] if use_color else 'black',
                      font=h3_font, anchor='w').pack(fill='x', padx=2, pady=2)

            for it in items[:8]:
                row = tk.Frame(section, bg=card_bg)
                row.pack(fill='x', padx=6, pady=1)

                # 左侧 preview (可换行)
                tk.Label(row, text=f"  • {it['preview']}", bg=card_bg,
                          fg=COLOR['fg'] if use_color else 'black',
                          font=text_font, anchor='w', justify='left',
                          wraplength=320).pack(side='left', fill='x', expand=True)

                # 右侧 [✅ 通过] [❌ 拒绝]
                tk.Button(
                    row, text='❌ 拒绝',
                    command=_make_action(kind, it['id'], 'reject', it['preview']),
                    font=btn_font,
                    bg=COLOR['btn_danger'] if use_color else 'SystemButtonFace',
                    padx=4).pack(side='right', padx=1)
                tk.Button(
                    row, text='✅ 通过',
                    command=_make_action(kind, it['id'], 'activate', it['preview']),
                    font=btn_font,
                    bg=COLOR['btn_ok'] if use_color else 'SystemButtonFace',
                    padx=4).pack(side='right', padx=1)

            # 备选: 批量开 CLI
            def _make_open(k=kind):
                def _do():
                    action_open_review_cli(
                        k, on_done=lambda ok, m: _set_status(m, ok))
                return _do
            tk.Button(section, text=f'🔧 批量处理 (开终端)',
                       command=_make_open(),
                       font=btn_font,
                       bg=COLOR['btn_neutral'] if use_color else 'SystemButtonFace',
                       padx=8).pack(side='top', anchor='e', padx=4, pady=(2, 4))

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
            overall = compute_overall_status(
                concerns, directive, promise, relation,
                daemon, health, review, events)
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
            lbl_review.config(
                text=f"⚠️  等你拍板的提案  ({len(review['items'])} 条)")
            h = directive['health']
            lbl_directive.config(
                text=f"📜  临时提醒规则  ({directive['total']} 条 · "
                      f"⚠️ 偏移 {h.get('low_help', 0) + h.get('untriggered', 0)})")
            live_n = sum(1 for d in daemon['daemons'] if d['live'])
            lbl_daemon.config(
                text=f"💡  后台管家  ({live_n}/{len(daemon['daemons'])} 在跑)")
            lbl_event.config(
                text=f"🔔  贾维斯最近在干嘛  ({len(events['events'])} 件)")

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
