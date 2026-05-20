# -*- coding: utf-8 -*-
"""[β.5.35-B / 2026-05-20] ScreenTeaseReflector — L7 vocab propose daemon

Sir 2026-05-20 10:46 实测 BUG 2: SmartNudge screen_tease 一周静音.
β.5.35-A 已修硬编码 → vocab 持久化 + CLI. 本 daemon (β.5.35-B) 补 L7 reflector:

设计:
  1. 后台 in-memory 累计 24h unique window titles (tick=60s 从 PhysicalEnvironmentProbe.window_history 采样)
  2. 每 24h 跑 1 次 LLM (OpenRouter cheap), 看哪些 title 不在 vocab 但出现 ≥ 3 次 → propose 新 category
  3. 写 memory_pool/screen_tease_vocab.json `review_queue`, Sir CLI 拍板 (`--review-list` / `--activate` / `--reject`)
  4. 失败/超时/无 key 静默, 不阻塞主路径

config:
  primary_model: 'google/gemini-2.5-flash-lite' (cheap, ~$0.001/run, 24h 一跑 ~$0.03/月)
  fallback_model: 'google/gemini-3.1-pro-preview'
  min_interval_s: 86400 (24h)
  min_unique_titles_for_run: 30 (< 30 不够 propose)
  max_propose_per_run: 3

doc: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from jarvis_utils import safe_openrouter_call  # noqa: F401
except Exception:
    safe_openrouter_call = None  # type: ignore


SCREEN_TEASE_REFLECTOR_CONFIG = {
    'primary_model': 'google/gemini-2.5-flash-lite',
    'fallback_model': 'google/gemini-3.1-pro-preview',
    'temperature': 0.2,
    'max_output_tokens': 600,
    'timeout_s': 15.0,
    'tick_seconds': 60.0,
    'min_interval_s': 86400,            # 24h 1 跑
    'min_unique_titles_for_run': 30,    # < 30 unique titles 不跑 (没足够样本)
    'max_propose_per_run': 3,           # 一次最多 propose 3 个新 category
    'sampling_tick': 60.0,              # 每分钟采一次 PhysicalEnvironmentProbe.window_history
    'unique_titles_maxlen': 2000,       # 内存 cap, 24h 大概 100-500 unique title
}


SCREEN_TEASE_REFLECTOR_PROMPT = """[ROLE]
You are Jarvis's screen-observation reflector. You look at window titles Sir's been on for 24h, and decide if there's a NEW activity category Jarvis should learn to recognize for "screen_tease" nudges (butler 远场调皮观察).

[CRITICAL CONSTRAINTS]
1. APPEND ONLY — do NOT propose categories that already exist (see [EXISTING CATEGORIES] below).
2. AT MOST 3 new categories per run. Quality over quantity.
3. Each proposed category MUST have at least 3 unmatched window titles as evidence.
4. NEVER propose meta categories about "using Jarvis" / "computer use in general".
5. Categories should be SPECIFIC activity patterns Sir does (e.g. "writing_email", "watching_tutorials", "AI_chat_window").
6. Keywords should be substrings that match the window title (e.g. "outlook" / "ChatGPT" / "Notion").
7. Output empty array if all unmatched titles look noisy/random.

[EXISTING CATEGORIES — DO NOT DUPLICATE]
{existing_categories_str}

[24H UNIQUE WINDOW TITLES — sorted by frequency, top 100]
{unmatched_titles_str}

[OUTPUT]
Output ONLY a JSON object on a single line:
{{"proposed_categories": [
    {{"id": "<snake_case_id_under_30_chars>",
      "keywords": ["substring1", "substring2", "substring3"],
      "directive_hint": "<one sentence in 中文 or English, < 60 chars>",
      "evidence_titles": ["title1", "title2", "title3"]}}
]}}

Empty if nothing: {{"proposed_categories": []}}

ALL string values MUST be valid JSON. NO markdown, NO explanations.
"""


class ScreenTeaseReflector(threading.Thread):
    """L7 daemon: 24h 1 跑 LLM, propose 新 screen_tease category 进 review_queue.

    用法:
        reflector = ScreenTeaseReflector(
            key_router=worker.key_router,
            vocab_path='memory_pool/screen_tease_vocab.json',
        )
        reflector.start()

    停止: reflector.stop()
    强制跑 (CLI / 测试): reflector.force_run_now() -> dict stats
    """

    def __init__(
        self,
        key_router=None,
        vocab_path: Optional[str] = None,
        config: Optional[Dict] = None,
    ):
        super().__init__(daemon=True, name='ScreenTeaseReflector')
        self.key_router = key_router
        self.config = dict(SCREEN_TEASE_REFLECTOR_CONFIG)
        if config:
            self.config.update(config)
        self.vocab_path = vocab_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'memory_pool', 'screen_tease_vocab.json',
        )
        self._stop = threading.Event()
        self._last_run_ts = 0.0
        self._last_sampling_ts = 0.0
        # 24h unique window titles {title: (first_seen, count)}
        self._unique_titles: Dict[str, Tuple[float, int]] = {}
        self._unique_lock = threading.Lock()
        self._stats = {
            'runs_total': 0,
            'runs_proposed': 0,
            'proposals_total': 0,
            'last_run_ts': 0.0,
            'last_error': '',
            'unique_titles_count': 0,
        }

    def stop(self):
        self._stop.set()

    def force_run_now(self) -> Dict:
        """立刻强制反思一次 (CLI / 测试用). 返回 stats 摘要."""
        try:
            return self._reflect_once(force=True)
        except Exception as e:
            return {'error': str(e)[:200]}

    def sample_titles_now(self) -> int:
        """从 PhysicalEnvironmentProbe.window_history 采样一次, 累计到 _unique_titles.

        返回本次新增的 unique title 数.
        """
        try:
            from jarvis_env_probe import PhysicalEnvironmentProbe as _P
        except Exception:
            return 0
        try:
            history = list(_P.window_history)
        except Exception:
            return 0
        new_count = 0
        now = time.time()
        with self._unique_lock:
            # GC: 删 > 25h 老 title (24h 滚动窗口 + 1h buffer)
            cutoff = now - 25 * 3600
            self._unique_titles = {
                t: (fs, c) for t, (fs, c) in self._unique_titles.items()
                if fs >= cutoff
            }
            for entry in history:
                title = entry.get('title', '').strip()
                if not title or len(title) < 3:
                    continue
                if title not in self._unique_titles:
                    self._unique_titles[title] = (now, 1)
                    new_count += 1
                else:
                    fs, c = self._unique_titles[title]
                    self._unique_titles[title] = (fs, c + 1)
            # 内存 cap
            maxlen = self.config.get('unique_titles_maxlen', 2000)
            if len(self._unique_titles) > maxlen:
                # 按 first_seen 老 -> 新 排序, 删最老的 N 个
                items = sorted(self._unique_titles.items(), key=lambda kv: kv[1][0])
                to_keep = items[-maxlen:]
                self._unique_titles = dict(to_keep)
            self._stats['unique_titles_count'] = len(self._unique_titles)
        return new_count

    def _load_existing_vocab_keywords(self) -> List[str]:
        """读 vocab 已有所有 keywords (lower) 用于 dedup."""
        try:
            if not os.path.exists(self.vocab_path):
                return []
            with open(self.vocab_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            all_kws = []
            for c in data.get('categories', []):
                if c.get('state', 'active') == 'active':
                    all_kws.extend([k.lower() for k in c.get('keywords', [])])
            for c in data.get('review_queue', []):
                all_kws.extend([k.lower() for k in c.get('keywords', [])])
            return all_kws
        except Exception:
            return []

    def _get_unmatched_titles_top_n(self, n: int = 100) -> List[Tuple[str, int]]:
        """返 top-N unique titles 不命中现有 vocab keyword, 按 count 降序."""
        all_kws = self._load_existing_vocab_keywords()
        with self._unique_lock:
            items = list(self._unique_titles.items())
        unmatched = []
        for title, (fs, count) in items:
            lower_t = title.lower()
            matched = any(kw in lower_t for kw in all_kws)
            if not matched:
                unmatched.append((title, count))
        unmatched.sort(key=lambda x: -x[1])
        return unmatched[:n]

    def _build_existing_categories_str(self) -> str:
        try:
            if not os.path.exists(self.vocab_path):
                return '(none yet)'
            with open(self.vocab_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            lines = []
            for c in data.get('categories', []):
                if c.get('state', 'active') == 'active':
                    kws = ', '.join(c.get('keywords', [])[:8])
                    lines.append(f"  - {c.get('id')}: [{kws}]")
            if not lines:
                return '(none yet)'
            return '\n'.join(lines)
        except Exception:
            return '(failed to load)'

    def _reflect_once(self, force: bool = False) -> Dict:
        """跑一次反思. 返回 {ok, reason, proposed_n, ...}."""
        result = {
            'ok': False,
            'reason': '',
            'proposed_n': 0,
            'unique_titles_count': 0,
            'unmatched_titles_count': 0,
        }

        if not force:
            now = time.time()
            since = now - self._last_run_ts
            if since < self.config['min_interval_s']:
                result['reason'] = f'too soon: {since:.0f}s < {self.config["min_interval_s"]}s'
                return result

        unmatched = self._get_unmatched_titles_top_n(100)
        with self._unique_lock:
            result['unique_titles_count'] = len(self._unique_titles)
        result['unmatched_titles_count'] = len(unmatched)

        if not force and len(unmatched) < self.config['min_unique_titles_for_run']:
            result['reason'] = (
                f'not enough unmatched titles: {len(unmatched)} < '
                f'{self.config["min_unique_titles_for_run"]}'
            )
            return result

        existing_str = self._build_existing_categories_str()
        unmatched_str = '\n'.join(
            f"  - [{count:3d}x] {title[:80]}" for title, count in unmatched
        )

        prompt = SCREEN_TEASE_REFLECTOR_PROMPT.format(
            existing_categories_str=existing_str,
            unmatched_titles_str=unmatched_str,
        )

        global safe_openrouter_call
        if safe_openrouter_call is None:
            try:
                from jarvis_utils import safe_openrouter_call as _sor
                safe_openrouter_call = _sor
            except Exception as e:
                result['reason'] = f'import safe_openrouter_call failed: {e}'
                return result

        if self.key_router is None:
            result['reason'] = 'no key_router'
            self._stats['last_error'] = result['reason']
            return result
        try:
            okey, _label = self.key_router.get_openrouter_key(caller='screen_tease_reflector')
        except Exception as e:
            result['reason'] = f'key_router error: {str(e)[:120]}'
            self._stats['last_error'] = result['reason']
            return result

        response_text = ''
        try:
            response_text = safe_openrouter_call(
                openrouter_key=okey,
                model=self.config['primary_model'],
                prompt=prompt,
                max_tokens=self.config['max_output_tokens'],
                temperature=self.config['temperature'],
                timeout_s=self.config['timeout_s'],
            )
        except Exception as e_primary:
            try:
                response_text = safe_openrouter_call(
                    openrouter_key=okey,
                    model=self.config['fallback_model'],
                    prompt=prompt,
                    max_tokens=self.config['max_output_tokens'],
                    temperature=self.config['temperature'],
                    timeout_s=self.config['timeout_s'],
                )
            except Exception as e_fallback:
                result['reason'] = (
                    f'LLM both failed: primary={str(e_primary)[:60]} '
                    f'fallback={str(e_fallback)[:60]}'
                )
                self._stats['last_error'] = result['reason']
                self._last_run_ts = time.time()
                self._stats['runs_total'] += 1
                return result

        # parse
        try:
            txt = response_text.strip()
            # 去 markdown 代码块标记
            if txt.startswith('```'):
                lines = txt.split('\n')
                # 去首行 ```json / ``` 和尾行 ```
                if len(lines) >= 3 and lines[-1].strip().startswith('```'):
                    txt = '\n'.join(lines[1:-1])
            parsed = json.loads(txt)
            proposed = parsed.get('proposed_categories', [])
            if not isinstance(proposed, list):
                proposed = []
            proposed = proposed[: self.config['max_propose_per_run']]
        except Exception as e:
            result['reason'] = f'parse fail: {str(e)[:80]} resp={response_text[:120]}'
            self._stats['last_error'] = result['reason']
            self._last_run_ts = time.time()
            self._stats['runs_total'] += 1
            return result

        # 写 vocab review_queue
        added_n = 0
        if proposed:
            try:
                with open(self.vocab_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                existing_review_ids = {c.get('id') for c in data.get('review_queue', [])}
                existing_active_ids = {c.get('id') for c in data.get('categories', [])}
                for p in proposed:
                    pid = (p.get('id') or '').strip()
                    if not pid or pid in existing_review_ids or pid in existing_active_ids:
                        continue
                    kws = p.get('keywords', [])
                    if not isinstance(kws, list) or not kws:
                        continue
                    item = {
                        'id': pid,
                        'state': 'review',
                        'keywords': [str(k).strip() for k in kws if str(k).strip()],
                        'directive_hint': str(p.get('directive_hint', f'Sir 在 {pid}')),
                        'evidence_titles': p.get('evidence_titles', []),
                        'source': 'L7 reflector',
                        'proposed_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        'ttl_seconds': None,
                    }
                    data.setdefault('review_queue', []).append(item)
                    added_n += 1
                if added_n > 0:
                    data.setdefault('_meta', {})['last_l7_run_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
                    tmp = self.vocab_path + '.tmp'
                    with open(tmp, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                        f.write('\n')
                    os.replace(tmp, self.vocab_path)
            except Exception as e:
                result['reason'] = f'write vocab fail: {str(e)[:80]}'
                self._stats['last_error'] = result['reason']
                self._last_run_ts = time.time()
                self._stats['runs_total'] += 1
                return result

        # done
        self._last_run_ts = time.time()
        self._stats['runs_total'] += 1
        self._stats['last_run_ts'] = self._last_run_ts
        if added_n > 0:
            self._stats['runs_proposed'] += 1
            self._stats['proposals_total'] += added_n
        result.update({
            'ok': True,
            'proposed_n': added_n,
            'reason': f'proposed {added_n} new categories from {len(unmatched)} unmatched titles',
        })
        try:
            from jarvis_utils import bg_log
            bg_log(
                f"🪞 [ScreenTeaseReflector] {result['reason']} "
                f"(unique_titles={result['unique_titles_count']})"
            )
        except Exception:
            pass
        return result

    def run(self):
        """daemon loop: tick=60s, 采样 + (满足条件时) LLM 反思."""
        try:
            from jarvis_utils import bg_log
            bg_log('[ScreenTeaseReflector] L7 vocab daemon ready')
        except Exception:
            pass
        # 启动 30s 等 PhysicalEnvironmentProbe 就绪
        self._stop.wait(30.0)
        while not self._stop.is_set():
            now = time.time()
            # sampling: 60s 一次采 window_history
            if now - self._last_sampling_ts >= self.config['sampling_tick']:
                try:
                    self.sample_titles_now()
                except Exception:
                    pass
                self._last_sampling_ts = now
            # reflection: 24h 一次跑 LLM
            try:
                self._reflect_once(force=False)
            except Exception as e:
                self._stats['last_error'] = f'reflect_once threw: {str(e)[:80]}'
            self._stop.wait(self.config['tick_seconds'])
