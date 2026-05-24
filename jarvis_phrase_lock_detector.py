# -*- coding: utf-8 -*-
"""[Reshape 准则 6 / 2026-05-24] PhraseLockDetector — 反话术锁 reflector.

# Sir 12:09 真测痛点 (准则 3 + 准则 6 退步)

主脑被否定后 reply 太一致:
  - "Understood, Sir. I shall stay out of your way." (12:01)
  - "Understood, Sir. I shall step back and let you focus." (11:39)
  - "明白了, 先生. 我不打扰您." (多次)

短期治法 (已加, 12:13): refusal_response_freedom directive priority=11 反话术锁.

长期治法 (本 module): 周期扫 STM, n-gram count, 找出主脑反复用的固定话术,
让 Sir 看 phrase_lock_review.json 自决 ban / 加新 directive 反向教.

# 设计 (准则 1 + 准则 6)

- 准则 1 (高效): 纯 Python n-gram count, 不调 LLM. cycle 6h 跑一次, 不阻塞主流.
- 准则 6 (拒绝硬编码 + 持久化):
  * 配置: memory_pool/phrase_lock_config.json (CLI 可改)
  * 输出: memory_pool/phrase_lock_review.json (Sir 拍板)
  * 接口: SWM event 'phrase_lock_detected' (主脑/RejectLearner 看见)
- 准则 8 (优雅): 不写死 stop word list, ngram cutoff = 反话术锁的 phrase 长度范围.

# n-gram 选择

- N=4-8 个汉字 / N=3-6 个英文词 (ngram 太短 = noise, 太长 = 全句重复才命中)
- min_count=5: 同 phrase 出现 ≥ 5 次才算锁
- min_diversity=3: phrase 在 ≥ 3 个不同 turn 出现 (避免单 turn 重复)
- exclude_corpus: stop phrases 列表 (e.g. "Sir" / "the" / 通用问候 — vocab 持久化)

# 输出 schema (phrase_lock_review.json)

[
  {
    "id": "lock_<hash8>",
    "ts": <unix>,
    "iso": "...",
    "phrase": "stay out of your way",
    "lang": "en",
    "count": 7,
    "diversity": 5,
    "first_seen_iso": "...",
    "last_seen_iso": "...",
    "sample_turns": ["turn_xxx_yyy_aaa", "turn_xxx_yyy_bbb", ...],
    "status": "pending"  # pending / accepted / rejected (Sir 拍板)
  }
]

# Sir 流程

1. 看 `python scripts/phrase_lock_dump.py` 列 pending lock
2. accept → 加进 directive ban list 或 raw signal vocab
3. reject → 不算锁 (phrase 是必要的, e.g. "Sir said")

# Cycle

- 每 6h
- 启动延 5min (让其他 module 稳)
- env JARVIS_PHRASE_LOCK_DETECTOR=0 关
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


_THIS = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_THIS, 'memory_pool', 'phrase_lock_config.json')
_REVIEW_PATH = os.path.join(_THIS, 'memory_pool', 'phrase_lock_review.json')
_STM_PATH = os.path.join(_THIS, 'memory_pool', 'stm_recent.jsonl')

DEFAULT_CONFIG = {
    'enabled': True,
    'cycle_interval_hours': 6.0,
    'lookback_hours': 168.0,                 # 7 days
    'min_count': 5,                           # 同 phrase 出现 ≥ N 次
    'min_diversity_turns': 3,                 # 不同 turn 数
    'ngram_zh_chars': [4, 6, 8],              # 中文字符长度
    'ngram_en_words': [3, 5],                 # 英文词数
    'cooldown_after_propose_hours': 24.0,    # 同 phrase 24h 内不重复 propose
    'exclude_phrases_zh': [
        '先生', '好的', '嗯嗯', '是的', '对的', '没问题',
        '我可以', '我知道', '我明白',
    ],
    'exclude_phrases_en': [
        'sir', 'the the', 'a the', 'is is',
        'i can', 'i will', 'i shall',
    ],
}


def _load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    try:
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                disk = json.load(f)
            if isinstance(disk, dict):
                for k, v in disk.items():
                    if not k.startswith('_'):
                        cfg[k] = v
    except Exception:
        pass
    # env override
    val = os.environ.get('JARVIS_PHRASE_LOCK_DETECTOR', '').strip()
    if val in ('0', 'false', 'False', 'no', 'off'):
        cfg['enabled'] = False
    elif val in ('1', 'true', 'True', 'yes', 'on'):
        cfg['enabled'] = True
    return cfg


def _is_zh(text: str) -> bool:
    """启发: 含 ≥ 30% 中文字符 = ZH."""
    if not text:
        return False
    zh_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    return zh_count >= len(text) * 0.3


def _extract_zh_ngrams(text: str, n: int) -> List[str]:
    """提取连续 n 个汉字 ngram (跳标点/空白)."""
    # 仅保留汉字
    chars = [c for c in text if '\u4e00' <= c <= '\u9fff']
    return [''.join(chars[i:i + n]) for i in range(len(chars) - n + 1)]


def _extract_en_ngrams(text: str, n: int) -> List[str]:
    """提取连续 n 个英文词 ngram (lowercased, 标点 strip)."""
    words = re.findall(r"[a-z']+", text.lower())
    if len(words) < n:
        return []
    return [' '.join(words[i:i + n]) for i in range(len(words) - n + 1)]


def _read_stm_replies(stm_path: Optional[str] = None,
                       lookback_hours: float = 168.0) -> List[Dict[str, Any]]:
    """读 STM jsonl, 返 jarvis 自己 reply 条目 (有 jarvis 字段, 非空).

    stm_path 默认 None → late binding 到模块级 _STM_PATH (test 可 monkey-patch).
    """
    if stm_path is None:
        stm_path = _STM_PATH
    if not os.path.exists(stm_path):
        return []
    out = []
    cutoff = time.time() - lookback_hours * 3600
    try:
        with open(stm_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                jarvis = (rec.get('jarvis') or '').strip()
                if not jarvis or len(jarvis) < 8:
                    continue
                # ts 兼容: 'time' (HH:MM:SS) 不能比, 看 'ts' 字段 (新版有)
                ts = rec.get('ts')
                if ts is None:
                    # 老条目无 ts, 按 read order 当作"近期"(保守 OK)
                    out.append(rec)
                else:
                    try:
                        ts = float(ts)
                        if ts >= cutoff:
                            out.append(rec)
                    except Exception:
                        out.append(rec)
    except Exception:
        pass
    return out


def _detect_phrase_locks(replies: List[Dict[str, Any]],
                         cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """主算法: n-gram count + filter + return locks."""
    if not replies:
        return []
    # phrase → list of (turn_id, ts)
    phrase_to_occurrences: Dict[str, List[Tuple[str, float]]] = collections.defaultdict(list)

    excl_zh = set(cfg.get('exclude_phrases_zh') or [])
    excl_en = set(cfg.get('exclude_phrases_en') or [])
    ngram_zh = list(cfg.get('ngram_zh_chars') or [4, 6, 8])
    ngram_en = list(cfg.get('ngram_en_words') or [3, 5])

    for rec in replies:
        jarvis = (rec.get('jarvis') or '').strip()
        if not jarvis:
            continue
        turn_id = rec.get('turn_id') or rec.get('time') or 'unknown'
        ts = float(rec.get('ts') or 0)

        if _is_zh(jarvis):
            for n in ngram_zh:
                for ng in _extract_zh_ngrams(jarvis, n):
                    if ng in excl_zh or len(ng) < 4:
                        continue
                    phrase_to_occurrences[ng].append((turn_id, ts))
        else:
            # EN or mixed → both ngram families
            for n in ngram_en:
                for ng in _extract_en_ngrams(jarvis, n):
                    if ng in excl_en or len(ng) < 6:
                        continue
                    phrase_to_occurrences[ng].append((turn_id, ts))

    # filter: count >= min_count + diversity >= min_diversity_turns
    min_count = int(cfg.get('min_count', 5))
    min_div = int(cfg.get('min_diversity_turns', 3))
    locks = []
    for phrase, occs in phrase_to_occurrences.items():
        if len(occs) < min_count:
            continue
        unique_turns = {t for t, _ in occs}
        if len(unique_turns) < min_div:
            continue
        ts_list = [t for _, t in occs if t > 0]
        first_ts = min(ts_list) if ts_list else 0.0
        last_ts = max(ts_list) if ts_list else 0.0
        h = hashlib.md5(phrase.encode('utf-8', 'ignore')).hexdigest()[:8]
        locks.append({
            'id': f'lock_{h}',
            'phrase': phrase,
            'lang': 'zh' if any('\u4e00' <= c <= '\u9fff' for c in phrase) else 'en',
            'count': len(occs),
            'diversity': len(unique_turns),
            'first_seen_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                              time.localtime(first_ts)) if first_ts else '',
            'last_seen_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                             time.localtime(last_ts)) if last_ts else '',
            'sample_turns': list(unique_turns)[:5],
        })
    # sort by count desc
    locks.sort(key=lambda x: x['count'], reverse=True)
    return locks


def _load_review() -> List[Dict[str, Any]]:
    if not os.path.exists(_REVIEW_PATH):
        return []
    try:
        with open(_REVIEW_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _save_review(queue: List[Dict[str, Any]]) -> bool:
    try:
        os.makedirs(os.path.dirname(_REVIEW_PATH), exist_ok=True)
        tmp = _REVIEW_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _REVIEW_PATH)
        return True
    except Exception:
        return False


# ============================================================
# Detector main class
# ============================================================


class PhraseLockDetector:
    """周期扫 STM 找重复话术, propose 进 review queue."""

    def __init__(self):
        self.cfg = _load_config()
        self._stop = threading.Event()
        self._daemon: Optional[threading.Thread] = None
        self._stats = {
            'cycles_run': 0,
            'locks_proposed_total': 0,
            'last_cycle_iso': '',
            'last_n_locks': 0,
        }

    def run_cycle(self) -> List[Dict[str, Any]]:
        """跑一次 detection cycle. Returns new locks added to queue."""
        self._stats['cycles_run'] += 1
        self._stats['last_cycle_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        cfg = _load_config()
        if not cfg.get('enabled'):
            return []
        replies = _read_stm_replies(lookback_hours=cfg.get('lookback_hours', 168.0))
        if not replies:
            return []
        locks = _detect_phrase_locks(replies, cfg)
        self._stats['last_n_locks'] = len(locks)
        if not locks:
            return []
        # cooldown: 同 lock_id 24h 内已 propose 过则 skip
        existing = _load_review()
        cooldown_s = float(cfg.get('cooldown_after_propose_hours', 24.0)) * 3600.0
        existing_by_id: Dict[str, Dict[str, Any]] = {}
        for ex in existing:
            existing_by_id[ex.get('id', '')] = ex
        now = time.time()
        new_or_updated = []
        for lock in locks:
            lid = lock['id']
            if lid in existing_by_id:
                ex = existing_by_id[lid]
                age = now - float(ex.get('ts', 0))
                if age < cooldown_s and ex.get('status') == 'pending':
                    # 不重复 propose, 但 update count/diversity
                    ex['count'] = lock['count']
                    ex['diversity'] = lock['diversity']
                    ex['last_seen_iso'] = lock['last_seen_iso']
                    continue
            entry = dict(lock)
            entry['ts'] = now
            entry['iso'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            entry['status'] = 'pending'
            existing_by_id[lid] = entry
            new_or_updated.append(entry)
        # cap queue size 200
        merged = list(existing_by_id.values())
        merged.sort(key=lambda r: float(r.get('ts', 0)), reverse=True)
        merged = merged[:200]
        _save_review(merged)
        self._stats['locks_proposed_total'] += len(new_or_updated)
        # publish SWM event for RejectLearner / 主脑 awareness
        if new_or_updated:
            try:
                from jarvis_utils import get_event_bus
                bus = get_event_bus()
                if bus is not None:
                    bus.publish(
                        etype='phrase_lock_detected',
                        description=(
                            f"PhraseLockDetector: {len(new_or_updated)} new lock(s) "
                            f"detected. top: '{new_or_updated[0]['phrase']}' "
                            f"(×{new_or_updated[0]['count']})"
                        ),
                        source='PhraseLockDetector',
                        salience=0.65,
                        metadata={
                            'n_new': len(new_or_updated),
                            'top_lock_id': new_or_updated[0]['id'],
                            'top_phrase': new_or_updated[0]['phrase'][:60],
                            'top_count': new_or_updated[0]['count'],
                        },
                    )
            except Exception:
                pass
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"🔍 [PhraseLockDetector] {len(new_or_updated)} new lock(s) — "
                    f"see scripts/phrase_lock_dump.py"
                )
            except Exception:
                pass
        return new_or_updated

    def start_daemon(self) -> None:
        if self._daemon is not None and self._daemon.is_alive():
            return
        if not self.cfg.get('enabled'):
            return
        def _loop():
            time.sleep(300.0)  # 启动延 5min
            interval_s = float(self.cfg.get('cycle_interval_hours', 6.0)) * 3600.0
            while not self._stop.is_set():
                try:
                    self.run_cycle()
                except Exception:
                    pass
                self._stop.wait(max(60.0, interval_s))
        self._daemon = threading.Thread(target=_loop, daemon=True,
                                          name='PhraseLockDetector')
        self._daemon.start()

    def stop(self):
        self._stop.set()

    def stats(self) -> Dict[str, Any]:
        return dict(self._stats)


# ============================================================
# Singleton
# ============================================================

_DEFAULT: Optional[PhraseLockDetector] = None
_LOCK = threading.Lock()


def get_default_detector() -> PhraseLockDetector:
    global _DEFAULT
    with _LOCK:
        if _DEFAULT is None:
            _DEFAULT = PhraseLockDetector()
        return _DEFAULT


def reset_for_test() -> None:
    global _DEFAULT
    with _LOCK:
        if _DEFAULT is not None:
            _DEFAULT.stop()
        _DEFAULT = None
