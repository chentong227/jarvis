import sqlite3
import json
import math
import time
import numpy as np
import os
from typing import Optional
from google import genai
from google.genai import types
from jarvis_utils import network_retry, create_genai_client
import threading
from fuzzywuzzy import fuzz

class Hippocampus:
    # [R7-β1/post-test] Embedding 熔断器：连续 403 PERMISSION_DENIED 时静默冷却 60s
    # 避免海马体在 Google API 整体不可用时刷屏报错 + 卡 search/seal 路径
    _EMBED_COOLDOWN_SECONDS = 60.0
    _NON_RETRYABLE_KEYWORDS = (
        '403', 'permission_denied', 'permission denied',
        'project has been denied', 'unauthorized', '401',
        'billing', 'quota_exceeded', 'forbidden',
    )

    def __init__(self, db_path="memory_pool/jarvis_memory.db", key_router=None):
        self.db_path = db_path
        self.key_router = key_router
        # 熔断状态
        self._embed_cooldown_until = 0.0
        self._embed_cooldown_lock = threading.Lock()
        self._embed_cooldown_reason = ''
        self._get_conn().close()
        # [R7-β post-test v4] 启动后台 backfill worker：
        # 冷却期间 seal_chat 会把 semantic_embedding 写成 NULL（保证记忆不丢），
        # 冷却结束后扫描所有 NULL 向量记忆，批量补 embedding（gemini-embedding-2 768 维），
        # 让长期检索完整恢复。
        self._backfill_worker_started = False
        self._backfill_in_progress = False
        try:
            self._start_backfill_worker()
        except Exception:
            pass

    def _is_embed_in_cooldown(self) -> bool:
        with self._embed_cooldown_lock:
            return time.time() < self._embed_cooldown_until

    def _mark_embed_failed(self, err_msg: str):
        """判定错误是否触发冷却：仅在权限/账号级错误时冷却 60s，
        网络抖动等可重试错误不冷却。"""
        err_lower = (err_msg or '').lower()
        if any(kw in err_lower for kw in self._NON_RETRYABLE_KEYWORDS):
            with self._embed_cooldown_lock:
                self._embed_cooldown_until = time.time() + self._EMBED_COOLDOWN_SECONDS
                self._embed_cooldown_reason = err_msg[:120]
            try:
                from jarvis_utils import bg_log
                bg_log(f"⛔ [Embedding Circuit] 检测到权限错误，海马体 embedding 冷却 {int(self._EMBED_COOLDOWN_SECONDS)}s")
            except Exception:
                pass

    def _start_backfill_worker(self):
        """[R7-β post-test v4 / P0-7 strengthened 2026-05-15] 启动后台 backfill 守护线程：
        - tick 周期 15s（旧版 60s 太懒；冷却结束后能 15s 内立刻补，不会拖到下次启动）
        - 启动后先 sleep 5s 让其他模块就绪，然后立刻试第一次（之前是先 sleep 60s 才试，
          实测下来用户重启后第一个 90s 窗口完全等不到 backfill）
        - 每次 tick：(a) 不在冷却 + (b) 有 NULL 向量待补 → 批量补 embedding（最多每轮 20 条）
        - 进程退出自动死掉（daemon=True）
        """
        if self._backfill_worker_started:
            return
        self._backfill_worker_started = True

        def _worker():
            try:
                from jarvis_utils import bg_log
                bg_log("♻️ [Embedding Backfill Worker] 后台守护线程已启动 (tick=15s)")
            except Exception:
                pass
            try:
                time.sleep(5.0)  # 让 KeyRouter / VocalCord 等先就绪
            except Exception:
                pass
            tick_interval = 15.0
            while True:
                try:
                    if self._is_embed_in_cooldown():
                        time.sleep(tick_interval)
                        continue
                    if self._backfill_in_progress:
                        time.sleep(tick_interval)
                        continue
                    self._backfill_in_progress = True
                    try:
                        n = self._run_backfill_batch(max_per_batch=20)
                        # 如果这一轮补了一些，下一轮立刻再试（可能还有更多 NULL 向量）
                        # 否则保持 15s 间隔
                        if n > 0:
                            time.sleep(2.0)
                            continue
                    finally:
                        self._backfill_in_progress = False
                    time.sleep(tick_interval)
                except Exception:
                    # 后台 worker 永不挂，任何异常都吞掉
                    try:
                        time.sleep(tick_interval)
                    except Exception:
                        pass

        t = threading.Thread(target=_worker, daemon=True, name='HippocampusBackfill')
        t.start()

    def _run_backfill_batch(self, max_per_batch: int = 20) -> int:
        """扫描 NULL 向量记忆，最多补 max_per_batch 条 embedding。返回补了几条。"""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, environment, user_intent, macro_goal, execution_summary, timestamp "
                "FROM TaskMemories WHERE semantic_embedding IS NULL AND is_deleted = 0 "
                "ORDER BY timestamp DESC LIMIT ?",
                (max_per_batch,)
            )
            rows = cursor.fetchall()
            conn.close()
            if not rows:
                return 0

            try:
                from jarvis_utils import bg_log
                bg_log(f"♻️ [Embedding Backfill] 冷却结束，开始补 {len(rows)} 条 NULL 向量记忆...")
            except Exception:
                pass

            # [P0+18-b.4 / 2026-05-15] 改造：每条记忆用 _embed_with_rotation
            # 独立拿 key + 失败自动换 key，不再共享同一 client
            # （旧版整批共享一个 client → 第一个 key 403 后整批 break）
            filled = 0
            failed = 0
            for mem_id, env, intent, goal, summary, ts in rows:
                try:
                    time_str = time.strftime('%Y年%m月%d日 %H:%M:%S', time.localtime(ts))
                    raw = f"【物理任务记录 | 发生时间：{time_str}】\n环境：{env}\n用户原始意图：{intent}\n系统拆解目标：{goal}\n最终执行结果：{summary}"
                    doc = f"title: none | text: {raw}"
                    response, _ = self._embed_with_rotation(
                        contents=[doc],
                        output_dimensionality=768,
                    )
                    vec_bytes = np.array(response.embeddings[0].values, dtype=np.float32).tobytes()
                    conn = self._get_conn()
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE TaskMemories SET semantic_embedding = ? WHERE id = ?",
                        (vec_bytes, mem_id)
                    )
                    conn.commit()
                    conn.close()
                    filled += 1
                except Exception as e:
                    failed += 1
                    if any(kw in str(e).lower() for kw in self._NON_RETRYABLE_KEYWORDS):
                        self._mark_embed_failed(str(e))
                        break
                    continue

            try:
                from jarvis_utils import bg_log
                if filled > 0:
                    bg_log(f"♻️ [Embedding Backfill] 已补 {filled} 条向量，失败 {failed} 条；剩余 NULL 见下轮（≤60s）")
            except Exception:
                pass
            return filled
        except Exception:
            return 0

    def _get_key_and_client(self, api_key=None, prefer_free_google: bool = False):
        """🆕 [Sir 2026-05-26 22:50 真痛 BUG 治本] prefer_free_google 参数.

        Sir 真意: google_1 是 paid (RPD 无限), google_2/3 是 free (RPD 20).
        Hippocampus summary (1/day, ≤20 RPD) 应该用 free, 不消耗 paid quota.
        embedding (高频) 用 _embed_with_rotation 显式遍历 _google_pool, 不走这里.
        其他 caller default prefer_free_google=False → 只取 paid google_1.
        """
        if self.key_router:
            tier = 'free' if prefer_free_google else 'paid'
            try:
                _key, _key_name = self.key_router.get_google_key('hippocampus', tier_filter=tier)
                _provider = self.key_router.PROVIDER_GOOGLE
            except (RuntimeError, AttributeError):
                # 老路径兜底 (key_router 无 get_google_key tier 参数)
                _key, _key_name, _provider = self.key_router.get_key(
                    'hippocampus', 'flash_lite', allow_openrouter_fallback=False
                )
        else:
            _key, _key_name = api_key, 'direct'
        return _key, _key_name, create_genai_client(api_key=_key)
    
    def _release_key(self, key_name):
        if self.key_router and key_name != 'direct':
            self.key_router.release(key_name)
        
    def _get_conn(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10.0) 
        cursor = conn.cursor()
        cursor.execute('PRAGMA journal_mode=WAL;') 
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS TaskMemories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                environment TEXT NOT NULL,
                user_intent TEXT NOT NULL,
                macro_goal TEXT NOT NULL,
                execution_summary TEXT,
                raw_actions JSON,
                semantic_embedding BLOB,
                is_deleted INTEGER DEFAULT 0
            )
        ''')
        # 👇 新增的数据库平滑升级脚本（统一记忆协议字段）
        try:
            cursor.execute("ALTER TABLE TaskMemories ADD COLUMN memory_type TEXT DEFAULT 'UNKNOWN'")
            cursor.execute("ALTER TABLE TaskMemories ADD COLUMN entities_json TEXT DEFAULT '{}'")
            cursor.execute("ALTER TABLE TaskMemories ADD COLUMN is_future_task INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE TaskMemories ADD COLUMN trigger_time REAL DEFAULT 0.0")
        except Exception:
            pass

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ProjectTimeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL UNIQUE,
                last_active_time REAL NOT NULL,
                total_hours REAL DEFAULT 0,
                status TEXT DEFAULT 'active',
                first_seen_time REAL NOT NULL,
                session_count INTEGER DEFAULT 0
            )
        ''')
        # 🆕 [β.5.46-fix18 / 2026-05-22] Sir 11:39 真测 BUG: "驾照放一放" 持久化失效.
        # Root cause: ProjectTimeline 不感知 Sir hold 信号. Sir 5/20 + 5/22 反复说
        # "驾照放一放/on hold/suppress nudges", SmartNudge 仍 fire dormant_project.
        # 治本 (3 数据源 refactor B 层): 加 held_until_ts 列, hold_project method,
        # get_dormant_projects 过滤. SQLite ALTER 在 try/except 内 (老 db migration 友好).
        try:
            cursor.execute("ALTER TABLE ProjectTimeline ADD COLUMN held_until_ts REAL DEFAULT 0")
        except Exception:
            pass  # 列已存在 (老 db 升级幂等)

        # [P0+18-e.3 / 2026-05-15] CommitmentWatcher 持久化表（迁旧 in-memory list 到 SQLite）。
        # 因果：原 CW.commitments 是 in-memory python list，进程重启就丢；Sir 24:00 说"两点睡觉"，
        # 23:59 重启 Jarvis 后再问 "我今晚要做什么" → CW 看不到，主脑只能猜（log:225-228 风格 BUG）。
        # 设计:
        #   - INSERT on add_commitment / extract_from_input
        #   - UPDATE deadline/desc on update_by_keyword
        #   - is_deleted=1 on cancel_by_keyword（保留审计痕迹，不物理删）
        #   - nudged=1 on watcher 推送过的（避免重启后重复 nudge）
        #   - CW 启动时 load_active_commitments() 拉回 in-memory list
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Commitments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                deadline_ts REAL NOT NULL,
                grace_minutes INTEGER DEFAULT 10,
                source_text TEXT DEFAULT '',
                created_at REAL NOT NULL,
                nudged INTEGER DEFAULT 0,
                is_deleted INTEGER DEFAULT 0
            )
        ''')

        conn.commit()
        return conn

    # ====================================================================
    # [P0+18-e.3 / 2026-05-15] Commitments CRUD 接口
    # ====================================================================
    def add_commitment_row(self, description: str, deadline_ts: float,
                            grace_minutes: int = 10, source_text: str = '',
                            created_at: float = None) -> int:
        """INSERT 一条 commitment，返回 rowid。失败返回 0。
        被 CommitmentWatcher.add_commitment / extract_from_input 调用。"""
        try:
            if created_at is None:
                created_at = time.time()
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO Commitments (description, deadline_ts, grace_minutes, source_text, created_at, nudged, is_deleted) '
                'VALUES (?, ?, ?, ?, ?, 0, 0)',
                (description, deadline_ts, grace_minutes, source_text, created_at)
            )
            conn.commit()
            rowid = cursor.lastrowid
            conn.close()
            return rowid
        except Exception as e:
            try:
                from jarvis_utils import bg_log
                bg_log(f"⚠️ [Commitments DB] add_commitment_row failed: {str(e)[:100]}")
            except Exception:
                pass
            return 0

    def mark_commitment_nudged(self, rowid: int) -> bool:
        """标记某条 commitment 已 nudged（推送过）。重启后不再二次推。"""
        if not rowid or rowid <= 0:
            return False
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE Commitments SET nudged = 1 WHERE id = ?',
                (rowid,)
            )
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def update_commitment_row(self, rowid: int, new_description: str = None,
                                new_deadline_ts: float = None) -> bool:
        """根据 rowid 更新 commitment 描述/截止时间。任一为 None 则保留旧值。"""
        if not rowid or rowid <= 0:
            return False
        try:
            sets = []
            args = []
            if new_description is not None:
                sets.append('description = ?')
                args.append(new_description)
            if new_deadline_ts is not None:
                sets.append('deadline_ts = ?')
                args.append(new_deadline_ts)
            if not sets:
                return False
            args.append(rowid)
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE Commitments SET {", ".join(sets)} WHERE id = ?',
                tuple(args)
            )
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def soft_delete_commitment(self, rowid: int) -> bool:
        """软删除（is_deleted=1）。保留审计。"""
        if not rowid or rowid <= 0:
            return False
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE Commitments SET is_deleted = 1 WHERE id = ?',
                (rowid,)
            )
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def add_completed_event(self, summary: str, keywords: list = None,
                              source: str = 'cascade_completion',
                              turn_id: str = '') -> int:
        """🆕 [P5-fix82-X / 2026-05-23 22:27] Sir 教 "X 完成" → 写 TaskMemories.

        让 list_recent_completed_events 能 hit. 不调 embed (避免 quota), 仅 schema 写.
        user_intent 字段 = 'Completed: <summary>' (统一前缀 list 函数能 LIKE 抓).
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            import json as _json
            entities = {
                'keywords': keywords or [],
                'source': source,
                'turn_id': turn_id,
            }
            cursor.execute(
                'INSERT INTO TaskMemories '
                '(timestamp, environment, user_intent, macro_goal, '
                ' execution_summary, raw_actions, semantic_embedding, '
                ' is_deleted, memory_type, entities_json, is_future_task, trigger_time) '
                'VALUES (?, ?, ?, ?, ?, ?, NULL, 0, ?, ?, 0, 0)',
                (time.time(), source, f'Completed: {summary[:120]}',
                 'sir-taught completion', summary[:300], '[]',
                 'completed_event', _json.dumps(entities, ensure_ascii=False)),
            )
            rowid = cursor.lastrowid
            conn.commit()
            conn.close()
            try:
                from jarvis_utils import bg_log as _ce_bg
                _ce_bg(
                    f"📝 [fix82-X CompletedEvent] TaskMemories#{rowid} "
                    f"'Completed: {summary[:50]}'"
                )
            except Exception:
                pass
            return rowid
        except Exception as _e:
            try:
                from jarvis_utils import bg_log as _ce_bg
                _ce_bg(f"⚠️ [fix82-X CompletedEvent] insert fail: {_e}")
            except Exception:
                pass
            return 0

    def list_recent_completed_events(self, days_back: int = 7, max_n: int = 20) -> list:
        """🆕 [P5-fix82-X / 2026-05-23 22:25] Sir 真意 "教一次, 多处同步".

        抽 TaskMemories.user_intent LIKE 'Completed:%' 近 N 天 → 给主脑 prompt
        block. 主脑下轮看到 "今天血压咨询 ✓" 不再误报 "明天血压咨询".

        Returns: list of dict {id, intent, timestamp_iso, time_ago_str}
                sorted by timestamp DESC.
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            min_ts = time.time() - days_back * 86400.0
            cursor.execute(
                "SELECT id, user_intent, timestamp FROM TaskMemories "
                "WHERE is_deleted = 0 "
                "AND (user_intent LIKE 'Completed:%' OR user_intent LIKE 'completed:%') "
                "AND timestamp > ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (min_ts, max_n),
            )
            rows = cursor.fetchall()
            conn.close()
            out = []
            now_ts = time.time()
            for rid, intent, ts in rows:
                # 时间差
                try:
                    ts_f = float(ts)
                    age_s = now_ts - ts_f
                    if age_s < 3600:
                        age = f"{int(age_s / 60)}分钟前"
                    elif age_s < 86400:
                        age = f"{int(age_s / 3600)}小时前"
                    else:
                        age = f"{int(age_s / 86400)}天前"
                    iso = time.strftime('%Y-%m-%d %H:%M', time.localtime(ts_f))
                except Exception:
                    age = '?'
                    iso = '?'
                # 去掉 'Completed:' 前缀
                clean = (intent or '').strip()
                for p in ('Completed:', 'completed:'):
                    if clean.startswith(p):
                        clean = clean[len(p):].strip()
                        break
                out.append({
                    'id': rid,
                    'intent': clean,
                    'iso': iso,
                    'age': age,
                })
            return out
        except Exception:
            return []

    def load_active_commitments(self, max_age_hours: float = 48.0) -> list:
        """加载所有未删除/未 nudged 的 commitment（用于 CW 启动时反查）。
        过滤过老的（>48h 老的 deadline）避免拉回过期数据。"""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            min_deadline = time.time() - max_age_hours * 3600
            cursor.execute(
                'SELECT id, description, deadline_ts, grace_minutes, source_text, created_at, nudged '
                'FROM Commitments WHERE is_deleted = 0 AND nudged = 0 AND deadline_ts > ? '
                'ORDER BY deadline_ts ASC LIMIT 100',
                (min_deadline,)
            )
            rows = cursor.fetchall()
            conn.close()
            results = []
            for row in rows:
                results.append({
                    'id': row[0],
                    'description': row[1],
                    'deadline_ts': row[2],
                    'grace_minutes': row[3] or 10,
                    'source_text': row[4] or '',
                    'created_at': row[5] or 0.0,
                    'nudged': bool(row[6]),
                })
            return results
        except Exception as e:
            try:
                from jarvis_utils import bg_log
                bg_log(f"⚠️ [Commitments DB] load_active_commitments failed: {str(e)[:100]}")
            except Exception:
                pass
            return []
        
    @network_retry(max_retries=3, base_delay=1.5)
    def _safe_embed_call(self, client, model, contents, output_dimensionality):
        """🛡️ 向量降维网络装甲（含指数退避重试）"""
        return client.models.embed_content(
            model=model,
            contents=contents,
            config=types.EmbedContentConfig(output_dimensionality=output_dimensionality)
        )

    # ====================================================================
    # [P0+18-b.4 / 2026-05-15] Key 轮换 Embed 入口
    # ----------------------------------------------------------------
    # 旧设计 BUG：embed 失败后只在同一个 google key 上 retry（network_retry
    # 内部），权限错误（403/billing）立刻向上抛出，**不会换 key 再试** →
    # google_1 一旦 403 → 标记不健康 + 60s 冷却 → 恢复后又被同一调用站点
    # 拿到（KeyRouter 是 healthy 池里随机抽，恢复后立刻又会被抽到）→ 又 403
    # → 又冷却 → 永远死循环。
    #
    # 新设计：失败后立即换下一个 google key 再试，最多试 max_keys 次。
    # 任一 key 成功就返回；全部失败再抛异常让上层进入冷却。
    # ====================================================================
    def _embed_with_rotation(self, contents, output_dimensionality: int = 768,
                              model: str = 'gemini-embedding-2', max_keys: int = 3):
        """对所有 google key **显式遍历**调 embed_content。任一 key 成功即返回 (response, key_name)。

        [P0+18-c.5 / 2026-05-15] **重写**：旧版靠 `_get_key_and_client` → KeyRouter 选 key，
        但 KeyRouter `_pick_from_pool` random.shuffle 后可能连续返同一 key（特别是 google_1
        第 1 次 PROJECT_DENIED 后还没被 `report_error` 标 unhealthy 时），导致第 2 轮
        `tried_labels` 命中 break → 实际只试 1 个 key 就熔断的"假 3/3 失败"。

        修法：直接拿 `key_router._google_pool` 的 label 列表（保序），每个 label 独立
        build client，**不依赖 KeyRouter 选 key**。仍然 release 给 KeyRouter 让并发计数和
        健康标记走完。

        失败规则：
        - 401/403/permission/billing/quota/429 → 立刻换下一个 key
        - 503/timeout/connection → 退避 1.5s 后换下一个 key
        - 其它未知错误 → 也换下一个 key（保持可用性）

        全部 google key 失败 → 抛 last_err；上层据此进入冷却。
        """
        last_err = None
        tried_labels = []  # 改 list 保序记录，日志友好

        # [c.5] 显式取 google_pool 名单。若 key_router 不可用，回退老路径（单 key 一次）
        google_entries = []
        if self.key_router is not None:
            try:
                google_entries = list(self.key_router._google_pool)
            except Exception:
                google_entries = []

        if not google_entries:
            # 没有 key_router 或 pool 空 → 走老路径单次尝试
            try:
                _key, _key_name, client = self._get_key_and_client(api_key=None)
            except Exception as ge:
                raise ge
            try:
                response = client.models.embed_content(
                    model=model,
                    contents=contents,
                    config=types.EmbedContentConfig(output_dimensionality=output_dimensionality)
                )
                self._release_key(_key_name)
                return response, _key_name
            except Exception as e:
                self._release_key(_key_name)
                if self.key_router:
                    try:
                        self.key_router.report_error(_key_name, str(e))
                    except Exception:
                        pass
                raise e

        # [c.5] 显式遍历：每个 label 独立 try
        # 注意：跳过已 unhealthy 的 key（KeyRouter._key_status[key]['healthy']==False）
        for entry in google_entries[:max_keys]:
            _key_name = entry['label']
            _key = entry['key']

            # 健康过滤：unhealthy key 直接跳过（不计入 tried，避免误报"试过了"）
            try:
                _status = self.key_router._key_status.get(_key, {})
                if not _status.get('healthy', True):
                    # [P0+20-α.2 / 2026-05-16] 跳过日志治理：
                    # ① 永久死亡的 key 完全静默（KeyRouter 已经一次性提示过）
                    # ② 普通 unhealthy（5min cooldown）的 key 按 label 节流 60s 一次（避免每轮对话刷屏）
                    if not _status.get('permanently_dead', False):
                        try:
                            now_ts = time.time()
                            _throttle_dict = getattr(self, '_skip_log_throttle', None)
                            if _throttle_dict is None:
                                _throttle_dict = {}
                                self._skip_log_throttle = _throttle_dict
                            last_ts = _throttle_dict.get(_key_name, 0.0)
                            if now_ts - last_ts >= 60.0:
                                _throttle_dict[_key_name] = now_ts
                                from jarvis_utils import bg_log
                                bg_log(f"♻️ [Hippocampus/KeyRotate] 跳过 {_key_name}（KeyRouter 标记 unhealthy）")
                        except Exception:
                            pass
                    continue
            except Exception:
                pass

            # 并发占位（仍走 KeyRouter 的 _try_acquire 避免压垮单 key）
            try:
                acquired = self.key_router._try_acquire(_key)
            except Exception:
                acquired = True  # 兜底：拿不到锁也试
            if not acquired:
                # 并发满了，等一下再试同个 key（不算失败）
                try:
                    time.sleep(0.1)
                    acquired = self.key_router._try_acquire(_key)
                except Exception:
                    acquired = True
            tried_labels.append(_key_name)

            try:
                client = create_genai_client(api_key=_key)
                response = client.models.embed_content(
                    model=model,
                    contents=contents,
                    config=types.EmbedContentConfig(output_dimensionality=output_dimensionality)
                )
                if acquired:
                    try:
                        self.key_router.release(_key_name)
                    except Exception:
                        pass
                return response, _key_name
            except Exception as e:
                last_err = e
                err_lower = str(e).lower()
                if self.key_router:
                    try:
                        self.key_router.report_error(_key_name, str(e))
                    except Exception:
                        pass
                if acquired:
                    try:
                        self.key_router.release(_key_name)
                    except Exception:
                        pass
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"♻️ [Hippocampus/KeyRotate] {_key_name} 失败 → 切下一个 google key (已试 {len(tried_labels)}/{len(google_entries[:max_keys])}) [{','.join(tried_labels)}]")
                except Exception:
                    pass
                if any(kw in err_lower for kw in (
                    '401', '403', 'permission', 'forbidden',
                    'invalid_key', 'api_key_invalid', 'denied',
                    'billing', 'quota', '429', 'exceeded',
                    'rate limit', 'resource_exhausted',
                )):
                    continue
                if any(kw in err_lower for kw in (
                    '503', 'unavailable', 'overloaded', 'timeout',
                    'connection', 'reset', 'temporarily',
                )):
                    try:
                        time.sleep(1.5)
                    except Exception:
                        pass
                    continue
                continue

        # 全部 google key 失败 → 抛 last_err，并附准确计数
        try:
            from jarvis_utils import bg_log
            bg_log(f"⛔ [Hippocampus/KeyRotate] 全部 {len(tried_labels)} 个 google key 失败 [{','.join(tried_labels)}]")
        except Exception:
            pass
        if last_err:
            raise last_err
        raise RuntimeError(f"[Hippocampus] _embed_with_rotation: 全部 {len(tried_labels)} 个 google key 均失败或都被标记 unhealthy")

    def seal_memory(self, api_key: str = None, env: str = "", intent: str = "", goal: str = "", summary: str = "", actions: list = None, image_path: str = None, memory_protocol: dict = None):
        """封印物理任务记忆：加入精确时间戳以供语义检索

        [P0+18-b.4 / 2026-05-15] 改造：用 _embed_with_rotation 统一入口，
        失败任一 google key 自动切下一个；权限错误 → 跨 key 全失败再降级纯文本。
        """
        vector_bytes = None

        try:
            time_str = time.strftime('%Y年%m月%d日 %H:%M:%S')
            raw_text = f"【物理任务记录 | 发生时间：{time_str}】\n环境：{env}\n用户原始意图：{intent}\n系统拆解目标：{goal}\n最终执行结果：{summary}"
            document_text = f"title: none | text: {raw_text}"

            contents_with_image = [document_text]
            if image_path:
                try:
                    with open(image_path, "rb") as f:
                        image_bytes = f.read()
                    contents_with_image.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
                except Exception as img_e:
                    print(f"读取快照文件失败，忽略图像]: {img_e}")

            try:
                response, _ = self._embed_with_rotation(
                    contents=contents_with_image,
                    output_dimensionality=768,
                )
                vector_bytes = np.array(response.embeddings[0].values, dtype=np.float32).tobytes()
            except Exception:
                response, _ = self._embed_with_rotation(
                    contents=[document_text],
                    output_dimensionality=768,
                )
                vector_bytes = np.array(response.embeddings[0].values, dtype=np.float32).tobytes()
                print(f"   └─  储存成功")

        except Exception as e:
            self._mark_embed_failed(str(e))
            print(f" [降级为纯文本存储]: {e}")
            vector_bytes = None

        protocol = memory_protocol or {}
        mem_type = protocol.get("memory_type", "TASK")
        entities_json = json.dumps(protocol.get("entities", {}), ensure_ascii=False)
        is_future = 1 if protocol.get("is_future_task") else 0
        trigger_ts = protocol.get("trigger_timestamp", 0.0)

        conn = self._get_conn()
        cursor = conn.cursor()
        # 👇 更新 INSERT 语句，写入所有高维字段
        cursor.execute('''
            INSERT INTO TaskMemories 
            (timestamp, environment, user_intent, macro_goal, execution_summary, raw_actions, semantic_embedding, memory_type, entities_json, is_future_task, trigger_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            time.time(), env, intent, goal, summary, 
            json.dumps([a.__dict__ for a in actions], ensure_ascii=False),
            vector_bytes, mem_type, entities_json, is_future, trigger_ts
        ))
        conn.commit()
        conn.close()
        print(f"[海马体]: 高维结构化记忆已刻印。")
    
    # ==========================================
# 📍 修改目标位置: jarvis_hippocampus.py (search_memory 函数)
# ==========================================
    def _fuzzy_fallback_search(self, query: str, top_k: int = 3, time_limit: float = 0.0,
                                min_similarity: float = 0.0) -> list:
        """[R7-β1/post-test v2] 冷却期间的本地兜底检索：用 fuzzywuzzy 对 user_intent / 
        execution_summary 做模糊匹配，给 LLM 一份"虽然没向量但好歹有相关历史"的上下文。
        准确率不如向量，但比"完全检索不到记忆"强得多。

        [P0+16 / 2026-05-15] 新增 min_similarity（0.0-1.0）：调用方（如 Memory Deletion）可
        指定更严格的相似度阈值，低于阈值的不返回，避免"那个东西"这种宽 hint 误删无关记忆。
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, timestamp, environment, user_intent, execution_summary "
                "FROM TaskMemories WHERE is_deleted = 0 AND timestamp >= ? "
                "ORDER BY timestamp DESC LIMIT 200",
                (time_limit,)
            )
            rows = cursor.fetchall()
            conn.close()
            if not rows:
                return []
            q_lower = (query or "").strip().lower()
            if not q_lower:
                return []
            # [P0+16] 噪声底线 50% 与调用方传入的 min_similarity 取较大值
            effective_floor = max(50, int(min_similarity * 100))
            scored = []
            for mem_id, ts, env, intent, summary in rows:
                # 简单分：意图相似 + 摘要包含
                intent_score = fuzz.partial_ratio(q_lower, (intent or "").lower())
                summary_score = fuzz.partial_ratio(q_lower, (summary or "").lower())
                score = max(intent_score, summary_score)
                if score >= effective_floor:
                    scored.append({
                        'id': mem_id,
                        'timestamp': ts,
                        'environment': env,
                        'intent': intent or '',
                        'summary': summary or '',
                        'similarity': score / 100.0,  # 归一化到 0-1
                    })
            scored.sort(key=lambda x: x['similarity'], reverse=True)
            return scored[:top_k]
        except Exception:
            return []

    def search_memory(self, api_key: str = None, query: str = "", top_k: int = 3,
                       time_limit: float = 0.0, min_similarity: float = 0.0,
                       time_decay_halflife_days: Optional[float] = None) -> list:
        """[P0+16 / 2026-05-15] 新增 min_similarity（0.0-1.0）：删除/纠正等高风险路径
        必须传入 ≥ 0.45 的阈值，否则会返回与 query 几乎无关的近邻噪声 → 工具误用根因。
        默认 0.0 保持向后兼容（普通 LTM 检索行为不变）。

        🆕 [Gap-Z5 / β.5.46-fix8 / 2026-05-21 23:55] time_decay_halflife_days:
        - None (默认): 旧行为, 纯 cosine similarity
        - >0: final_score = similarity × exp(-age_days / halflife), 旧 memory
          自动衰减 (主脑不被 30+ 天前 memory 干扰).

        Default halflife in default_search_memory_with_decay() = 30 days.
        """
        # [R7-β1/post-test v2] 冷却期内退到 fuzzy 兜底检索，不再返回空
        if self._is_embed_in_cooldown():
            return self._fuzzy_fallback_search(query, top_k=top_k, time_limit=time_limit,
                                                min_similarity=min_similarity)
        formatted_query = f"task: search result | query: {query}"
        # [P0+18-b.4 / 2026-05-15] 用 _embed_with_rotation 替代单 key 调用，
        # 避免 google_1 403 → 永远不切其它 key → 死循环冷却的旧 BUG。
        try:
            response, _ = self._embed_with_rotation(
                contents=[formatted_query],
                output_dimensionality=768,
            )
            query_vector = np.array(response.embeddings[0].values, dtype=np.float32)
        except Exception as e:
            # 全部 google key 都失败 → 进入冷却 + 退到 fuzzy 兜底
            self._mark_embed_failed(str(e))
            try:
                from jarvis_utils import bg_log
                if self._is_embed_in_cooldown():
                    # [P0+18-c.5] 改成真实计数的措辞：原"三 Key 均失败"在 b.4 修复后仍是
                    # 静态文案，与实际尝试 key 数解耦 → 引发"已试 1/3 却报三 Key 均失败"误导
                    bg_log(f"⛔ [海马体熔断]: 当前所有 google key 均不可用，60s 冷却中不再 embed（原因: {str(e)[:80]}）")
                else:
                    bg_log(f"⚠️ [海马体检索降级]: 网络波动，已闪避耗时操作 ({str(e)[:100]})")
            except Exception:
                pass
            return self._fuzzy_fallback_search(query, top_k=top_k, time_limit=time_limit,
                                                min_similarity=min_similarity)

        # ... 下方的 SQLite 数据库比对代码保持不变 ...

        # 👇 强制使用自愈池
        conn = self._get_conn()
        cursor = conn.cursor()
        # 👇 核心增加：把 timestamp 和 environment 一起 select 出来！
        cursor.execute(
            "SELECT id, timestamp, environment, user_intent, execution_summary, semantic_embedding FROM TaskMemories WHERE semantic_embedding IS NOT NULL AND timestamp >= ? AND is_deleted = 0", 
            (time_limit,)
        )
        all_memories = cursor.fetchall()
        conn.close()

        if not all_memories:
            return []

        results =[]
        query_norm = np.linalg.norm(query_vector)
        # 🆕 [Gap-Z5 / β.5.46-fix8] 时间衰减计算
        _now_ts = time.time()
        _halflife_s = None
        if time_decay_halflife_days is not None and time_decay_halflife_days > 0:
            _halflife_s = float(time_decay_halflife_days) * 86400.0
        for mem in all_memories:
            mem_id, timestamp, env, intent, summary, blob_data = mem
            mem_vector = np.frombuffer(blob_data, dtype=np.float32)
            mem_norm = np.linalg.norm(mem_vector)
            if query_norm == 0 or mem_norm == 0:
                similarity = 0.0
            else:
                similarity = float(
                    np.dot(query_vector, mem_vector) / (query_norm * mem_norm)
                )
            # 🆕 [Gap-Z5] time decay (final_score = similarity × exp(-age/halflife))
            final_score = similarity
            decay_factor = 1.0
            if _halflife_s is not None and timestamp > 0:
                age_s = max(0.0, _now_ts - float(timestamp))
                decay_factor = math.exp(-age_s / _halflife_s)
                final_score = similarity * decay_factor

            # 👇 将精准的时间戳和环境打包返回
            results.append({
                "id": mem_id,
                "timestamp": timestamp,
                "environment": env,
                "intent": intent,
                "summary": summary,
                "similarity": similarity,
                "decay_factor": float(decay_factor),
                "final_score": float(final_score),
            })

        # 🆕 [Gap-Z5] 排序用 final_score (decay 启用时), 否则 similarity (向后兼容)
        if _halflife_s is not None:
            results.sort(key=lambda x: x["final_score"], reverse=True)
        else:
            results.sort(key=lambda x: x["similarity"], reverse=True)
        # [P0+16 / 2026-05-15] 删除/纠正高风险路径会传 min_similarity ≥ 0.45。
        # 09:22 误删事件根因之一：原 search 完全无阈值，返回 0.1 相似度的近邻 + 全删。
        if min_similarity > 0.0:
            results = [r for r in results if r.get("similarity", 0.0) >= min_similarity]
        return results[:top_k]

    # 🆕 [Gap-Z5 / β.5.46-fix8 / 2026-05-21 23:55] decay 配置加载 (准则 6.5)
    _decay_config_cache = None
    _decay_config_mtime = 0.0
    _decay_config_lock = threading.Lock()

    @classmethod
    def _load_decay_config(cls) -> dict:
        """读 memory_pool/hippocampus_decay_config.json (mtime cache)."""
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'memory_pool', 'hippocampus_decay_config.json',
        )
        try:
            if not os.path.exists(path):
                return {'enabled': False}
            mtime = os.path.getmtime(path)
            with cls._decay_config_lock:
                if (cls._decay_config_cache is not None
                        and mtime <= cls._decay_config_mtime):
                    return cls._decay_config_cache
                with open(path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                cls._decay_config_cache = cfg if isinstance(cfg, dict) else {'enabled': False}
                cls._decay_config_mtime = mtime
                return cls._decay_config_cache
        except Exception:
            return {'enabled': False}

    def search_memory_default(self, api_key: str = None, query: str = "",
                                top_k: int = 3, time_limit: float = 0.0,
                                min_similarity: float = 0.0) -> list:
        """🆕 [Gap-Z5 / β.5.46-fix8] 默认带 time decay 的 search.

        从 memory_pool/hippocampus_decay_config.json 读 halflife_days, 调 search_memory.
        config disabled / 文件不存在 → fallback 旧行为 (纯 cosine).

        删除/纠正路径仍直调 search_memory(time_decay_halflife_days=None) 保旧行为
        (Sir 让删 1 月前 X 时旧 memory 该召回).
        """
        cfg = self._load_decay_config()
        if cfg.get('enabled', False):
            halflife = float(cfg.get('halflife_days', 30.0))
            return self.search_memory(
                api_key=api_key, query=query, top_k=top_k,
                time_limit=time_limit, min_similarity=min_similarity,
                time_decay_halflife_days=halflife,
            )
        return self.search_memory(
            api_key=api_key, query=query, top_k=top_k,
            time_limit=time_limit, min_similarity=min_similarity,
        )

    def delete_memory(self, memory_id: int):
        """逻辑删除 (移入回收站)"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE TaskMemories SET is_deleted = 1 WHERE id = ?", (memory_id,))
        conn.commit()
        conn.close()
        print(f"🗑️ [海马体]: 记忆坐标 [ID: {memory_id}] 已移入回收站。")

    def restore_memory(self, memory_id: int):
        """从回收站恢复记忆"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE TaskMemories SET is_deleted = 0 WHERE id = ?", (memory_id,))
        conn.commit()
        conn.close()
        print(f"✨ [海马体]: 记忆坐标 [ID: {memory_id}] 已从回收站恢复。")

    def update_memory(self, api_key: str = None, memory_id: int = 0, env: str = "", intent: str = "", goal: str = "", new_summary: str = ""):
        """重塑已有记忆：更新摘要文本并重新生成语义向量

        [P0+18-b.4 / 2026-05-15] 改造：用 _embed_with_rotation 替代单 key 调用，
        失败任一 google key 自动切下一个；全部失败再标记冷却。
        """
        if self._is_embed_in_cooldown():
            return
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            raw_text = f"环境：{env}\n用户原始意图：{intent}\n系统拆解目标：{goal}\n最终执行结果：{new_summary}"
            document_text = f"title: none | text: {raw_text}"
            response, _ = self._embed_with_rotation(
                contents=[document_text],
                output_dimensionality=768,
            )
            vector_bytes = np.array(response.embeddings[0].values, dtype=np.float32).tobytes()
            cursor.execute(
                "UPDATE TaskMemories SET execution_summary = ?, semantic_embedding = ? WHERE id = ?",
                (new_summary, vector_bytes, memory_id)
            )
            conn.commit()
            try:
                from jarvis_utils import bg_log
                bg_log(f"[海马体]: 记忆坐标 [ID: {memory_id}] 已修改。")
            except Exception:
                print(f"[海马体]: 记忆坐标 [ID: {memory_id}] 已修改。")
        except Exception as e:
            self._mark_embed_failed(str(e))
            try:
                from jarvis_utils import bg_log
                bg_log(f"⚠️ [记忆重塑失败]: {str(e)[:140]}")
            except Exception:
                pass
        finally:
            conn.close()
    
    # ==========================================
# 📍 修改目标文件: jarvis_hippocampus.py
# ==========================================

    # ==========================================
# 📍 修改目标位置: jarvis_hippocampus.py (seal_chat_async 函数内部)
# ==========================================
    def seal_chat_async(self, api_key: str = None, user_input: str = "", jarvis_reply: str = "", memory_protocol=None):
        """异步封印日常对话：支持多重意图与时间阵列写入（含智能去重）。
        [R7-β1/post-test v2] 冷却期内**仍写 SQLite**（用 NULL semantic_embedding），
        只是不调 embedding API。冷却结束后可批量补 embed（留作后续）。
        长期记忆不丢失。
        """
        embedding_cooldown = self._is_embed_in_cooldown()
        def _task():
            _key_name = 'direct'
            try:
                # ==========================================
                # 🛡️ 智能去重哨兵：防止同一句话被重复封印
                # ==========================================
                protocol_list = memory_protocol if isinstance(memory_protocol, list) else [memory_protocol] if memory_protocol else [{}]
                
                conn = self._get_conn()
                cursor = conn.cursor()
                
                # 查询最近 10 分钟内的聊天记录
                recent_cutoff = time.time() - 600
                cursor.execute('''
                    SELECT id, user_intent, execution_summary, is_future_task, trigger_time 
                    FROM TaskMemories 
                    WHERE environment = 'CHAT' AND is_deleted = 0 AND timestamp >= ?
                    ORDER BY timestamp DESC LIMIT 10
                ''', (recent_cutoff,))
                recent_rows = cursor.fetchall()
                
                dedup_skipped = 0
                filtered_protocols = []
                
                for protocol in protocol_list:
                    is_future = protocol.get("is_future_task", False)
                    trigger_ts = protocol.get("trigger_timestamp", 0.0)
                    clean_intent = protocol.get("clean_intent", user_input)
                    
                    # 对最近记录做模糊匹配去重
                    is_duplicate = False
                    for row in recent_rows:
                        existing_intent = row[1] or ""
                        existing_reply = row[2] or ""
                        existing_is_future = row[3] == 1
                        existing_trigger = row[4] or 0.0
                        
                        # 规则1：用户输入高度相似 (>85%) → 直接判定重复
                        intent_sim = fuzz.ratio(clean_intent[:80], existing_intent[:80])
                        if intent_sim > 85:
                            is_duplicate = True
                            break
                        
                        # 规则2：同为未来任务且触发时间相近 (60秒内) → 判定重复排期
                        if is_future and existing_is_future and trigger_ts > 0 and existing_trigger > 0:
                            if abs(trigger_ts - existing_trigger) < 60:
                                is_duplicate = True
                                break
                    
                    if is_duplicate:
                        dedup_skipped += 1
                    else:
                        filtered_protocols.append(protocol)
                
                if dedup_skipped > 0:
                    print(f" └─ 🛡️ [去重哨兵] 已拦截 {dedup_skipped} 条重复记忆，防止冗余写入。")
                
                if not filtered_protocols:
                    conn.close()
                    return

                # [R7-β1/post-test v2] 冷却期 → 跳过 embedding 调用，直接用 NULL 向量写入。
                # 这样长期记忆链不断（SQLite 仍然有这条对话），冷却结束后可补 embed。
                if embedding_cooldown:
                    vector_bytes = None
                    try:
                        from jarvis_utils import bg_log
                        bg_log(f"⛔ [海马体]: embedding 冷却中，本轮 seal_chat 写入 SQLite 但 NULL 向量")
                    except Exception:
                        pass
                else:
                    # [P0+18-b.4 / 2026-05-15] 用 _embed_with_rotation 替代单 key 调用
                    time_str = time.strftime('%Y年%m月%d日 %H:%M:%S')
                    raw_text = f"【日常对话记录 | 发生时间：{time_str}】\n人类：{user_input}\nJarvis：{jarvis_reply}"
                    document_text = f"title: none | text: {raw_text}"

                    response, _key_name = self._embed_with_rotation(
                        contents=[document_text],
                        output_dimensionality=768,
                    )
                    vector_bytes = np.array(response.embeddings[0].values, dtype=np.float32).tobytes()
                
                for protocol in filtered_protocols:
                    mem_type = protocol.get("memory_type", "CHAT")
                    entities_json = json.dumps(protocol.get("entities", {}), ensure_ascii=False)
                    is_future = 1 if protocol.get("is_future_task") else 0
                    trigger_ts = protocol.get("trigger_timestamp", 0.0)

                    cursor.execute('''
                        INSERT INTO TaskMemories 
                        (timestamp, environment, user_intent, macro_goal, execution_summary, raw_actions, semantic_embedding, memory_type, entities_json, is_future_task, trigger_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        time.time(), "CHAT", user_input, "日常对话", jarvis_reply, 
                        "[]", vector_bytes, mem_type, entities_json, is_future, trigger_ts
                    ))
                conn.commit()
                conn.close()
                print(f" └─ 💾 [System] 记忆数据 (共 {len(filtered_protocols)} 项意图) 已封存。")
            except Exception as e:
                # [R7-β1/post-test] 权限级错误触发冷却 60s，普通错误只记录
                self._mark_embed_failed(str(e))
                try:
                    from jarvis_utils import bg_log
                    if self._is_embed_in_cooldown():
                        bg_log(f"⛔ [海马体熔断/写入]: 权限错误，60s 冷却生效")
                    else:
                        bg_log(f"⚠️ [海马体写入异常]: {str(e)[:140]}")
                except Exception:
                    pass
                if self.key_router:
                    self.key_router.report_error(_key_name, str(e))
            finally:
                self._release_key(_key_name)
                
        threading.Thread(target=_task, daemon=True).start()
    def fetch_due_reminders(self, current_timestamp: float) -> list:
        """只取不焚：提取已到点的未来任务，但不修改数据库状态"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT id, user_intent, trigger_time 
                FROM TaskMemories 
                WHERE is_future_task = 1 AND is_deleted = 0 AND trigger_time > 0 AND trigger_time <= ?
            ''', (current_timestamp,))
            rows = cursor.fetchall()
            
            if not rows:
                return []
                
            reminders = []
            for r in rows:
                reminders.append({"id": r[0], "intent": r[1], "trigger_time": r[2]})
            return reminders
        except Exception as e:
            print(f"⚠️ [海马体时钟检索异常]: {e}")
            return []
        finally:
            conn.close()

    def consume_reminder(self, memory_id: int):
        """确认消费：用户已响应或重试耗尽，将单条提醒的 is_future_task 置为 0"""
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE TaskMemories SET is_future_task = 0 WHERE id = ?", (memory_id,))
            conn.commit()
        except Exception as e:
            print(f"⚠️ [海马体消费异常]: {e}")
        finally:
            conn.close()    

    def compress_chat_history(self, api_key: str = None, days: int = 7):
        """记忆压缩机（梦境整理）：静默扫描超过 N 天的零碎闲聊，释放空间并提纯核心概念"""
        def _compress():
            _key_name = 'direct'
            try:
                import threading
                conn = self._get_conn()
                cursor = conn.cursor()
                
                # 寻找 N 天前（默认7天）的原始闲聊记录
                cutoff_time = time.time() - days * 24 * 3600
                cursor.execute('''
                    SELECT id, timestamp, user_intent, execution_summary 
                    FROM TaskMemories 
                    WHERE environment = 'CHAT' AND is_deleted = 0 AND timestamp < ?
                    ORDER BY timestamp ASC
                ''', (cutoff_time,))
                rows = cursor.fetchall()
                
                # 👇 核心防扰机制：如果没有积累超过3句的“7天前旧聊天”，直接静默退出！
                # 绝对不会在控制台打印任何废话，让你感觉不到它的存在。
                if len(rows) < 3: 
                    conn.close()
                    return 
                    
                chat_log = ""
                ids_to_delete =[]
                for r in rows:
                    ids_to_delete.append(r[0])
                    t_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(r[1]))
                    chat_log += f"[{t_str}] 用户: {r[2]}\n[{t_str}] Jarvis: {r[3]}\n"
                
                print(f"\n🧠 [海马体]: 监测到 {days} 天前的零碎对话，正在进入潜意识梦境进行压缩整理...")
                
                # 🆕 [Sir 2026-05-26 22:50] summary 1/day, 走 google free (google_2/3),
                # 不消耗 paid google_1 quota. fallback paid 如 free 全爆.
                _key, _key_name, client = self._get_key_and_client(
                    api_key, prefer_free_google=True
                )
                prompt = f"""你是一个记忆整理模块。请将以下人类与Jarvis的日常对话记录，浓缩总结为一段极其精简的【长期记忆档案】。
必须提取的核心：用户表达的习惯、喜好、情绪、计划、发生的关键事件。去除毫无意义的客套话。
请以 Jarvis (第一人称) 的视角记录这段回忆。
--- 原始记录 ---
{chat_log}"""
                
                # 🩹 [β.2.7.6 / 2026-05-17] 升 gemini-3-flash-preview 与主对话模型一致
                # 凌晨 1 次/天 压缩，cost 几乎 0 差额（同 pricing tier 0.50/3 vs 0.30/2.5）
                # 一致性: 主对话 reply 风格被 hippocampus summary 忠实保留
                summary_res = client.models.generate_content(
                    model='gemini-3-flash-preview',
                    contents=prompt
                )
                summary_text = summary_res.text
                
                # [P0+18-b.4 / 2026-05-15] 向量化走 _embed_with_rotation（多 key 轮换）
                doc_text = f"title: none | text: 【潜意识压缩记忆】{summary_text}"
                emb_res, _ = self._embed_with_rotation(
                    contents=[doc_text],
                    output_dimensionality=768,
                )
                vector_bytes = np.array(emb_res.embeddings[0].values, dtype=np.float32).tobytes()
                
                # 存入总结
                cursor.execute('''
                    INSERT INTO TaskMemories 
                    (timestamp, environment, user_intent, macro_goal, execution_summary, raw_actions, semantic_embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (time.time(), "CHAT_SUMMARY", f"{days}天前的记忆碎片整理", "记忆压缩", summary_text, "[]", vector_bytes))
                
                # 软删除被压缩的原始碎片
                for i in ids_to_delete:
                    cursor.execute("UPDATE TaskMemories SET is_deleted = 1 WHERE id = ?", (i,))
                    
                conn.commit()
                conn.close()
                print("✨ [海马体]: 梦境压缩完成！远古杂乱碎片已合并为长期高维概念。\n")
            except Exception as e:
                print(f"⚠️[记忆压缩异常]: {e}")
                if self.key_router:
                    self.key_router.report_error(_key_name, str(e))
            finally:
                self._release_key(_key_name)
                
        threading.Thread(target=_compress, daemon=True).start()

    def consolidate(self):
        """Consolidate recent memories (called by sleep archive)"""
        import threading
        threading.Thread(target=self.compress_chat_history, args=(None, 1), daemon=True).start()

    # ==========================================
# 📍 修改目标文件: jarvis_hippocampus.py
# ==========================================
    def cancel_future_reminder(self, api_key: str = None, cancel_query: str = "") -> str:
        """根据语义狙击并抹杀尚未触发的旧提醒

        [P0+18-b.4 / 2026-05-15] 用 _embed_with_rotation 替代单 key 调用。
        """
        try:
            formatted_query = f"task: search result | query: {cancel_query}"
            response, _ = self._embed_with_rotation(
                contents=[formatted_query],
                output_dimensionality=768,
            )
            query_vector = np.array(response.embeddings[0].values, dtype=np.float32)
            
            conn = self._get_conn()
            cursor = conn.cursor()
            # 💡 核心：只在【尚未触发的未来任务】中进行搜索
            cursor.execute("SELECT id, user_intent, semantic_embedding FROM TaskMemories WHERE is_future_task = 1 AND is_deleted = 0")
            rows = cursor.fetchall()
            
            if not rows:
                conn.close()
                return "当前没有任何待触发的提醒任务。"
            
            best_match_id = -1
            best_score = -1
            best_intent = ""
            
            query_norm = np.linalg.norm(query_vector)
            for r in rows:
                mem_id, intent, blob_data = r
                mem_vector = np.frombuffer(blob_data, dtype=np.float32)
                mem_norm = np.linalg.norm(mem_vector)
                if query_norm > 0 and mem_norm > 0:
                    sim = np.dot(query_vector, mem_vector) / (query_norm * mem_norm)
                    if sim > best_score:
                        best_score = sim
                        best_match_id = mem_id
                        best_intent = intent
            
            # 💡 阈值判定：如果相似度大于 0.6，认为是同一个任务
            if best_match_id != -1 and best_score > 0.60:
                # 物理抹杀：取消未来属性，并打入回收站
                cursor.execute("UPDATE TaskMemories SET is_future_task = 0, is_deleted = 1 WHERE id = ?", (best_match_id,))
                conn.commit()
                conn.close()
                return f"已成功狙击并取消旧提醒：'{best_intent}' (相似度得分: {best_score:.2f})"
            else:
                conn.close()
                return f"未找到与 '{cancel_query}' 高度匹配的旧提醒，无法取消。"
        except Exception as e:
            # [P0+18-b.4 / 2026-05-15] _embed_with_rotation 内部已 report_error，
            # 此处不再重复；纯文本失败回显给上层即可。
            self._mark_embed_failed(str(e))
            return f"取消旧提醒时发生异常: {e}"

    def track_project_activity(self, project_name: str, session_duration_minutes: float = 0):
        """记录项目活跃度：每次检测到项目活动时调用"""
        now = time.time()
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT id, total_hours, session_count FROM ProjectTimeline WHERE project_name = ?",
            (project_name,)
        )
        row = cursor.fetchone()
        
        if row:
            new_hours = row[1] + (session_duration_minutes / 60.0) if session_duration_minutes > 0 else row[1]
            cursor.execute(
                "UPDATE ProjectTimeline SET last_active_time = ?, total_hours = ?, session_count = session_count + 1, status = 'active' WHERE project_name = ?",
                (now, new_hours, project_name)
            )
        else:
            cursor.execute(
                "INSERT INTO ProjectTimeline (project_name, last_active_time, total_hours, status, first_seen_time, session_count) VALUES (?, ?, ?, 'active', ?, 1)",
                (project_name, now, session_duration_minutes / 60.0, now)
            )
        
        conn.commit()
        conn.close()

    def get_dormant_projects(self, dormant_days: int = 3) -> list:
        """获取沉寂超过指定天数的项目.

        🆕 [β.5.46-fix18 / 2026-05-22] Sir 真测 BUG fix:
        - 过滤 held_until_ts > now (Sir 显式 hold 中, 不算 dormant).
        - 老 db (无 held_until_ts 列) 兼容: COALESCE 取 0 → 不影响.
        """
        now = time.time()
        threshold = now - (dormant_days * 86400)
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT project_name, last_active_time, total_hours, session_count "
            "FROM ProjectTimeline "
            "WHERE status = 'active' "
            "  AND last_active_time < ? "
            "  AND COALESCE(held_until_ts, 0) < ? "
            "ORDER BY last_active_time ASC",
            (threshold, now)
        )
        rows = cursor.fetchall()
        conn.close()

        results = []
        for r in rows:
            days_since = (now - r[1]) / 86400
            results.append({
                'project_name': r[0],
                'last_active': time.strftime('%Y-%m-%d %H:%M', time.localtime(r[1])),
                'days_dormant': round(days_since, 1),
                'total_hours': round(r[2], 1),
                'session_count': r[3]
            })
        return results

    def hold_project(self, project_name: str, hours: float = 72.0,
                      source: str = '') -> bool:
        """🆕 [β.5.46-fix18 / 2026-05-22] Sir 显式 hold project N 小时.

        Sir 11:39 真测痛点: 反复说 "驾照放一放/hold off" 但 SmartNudge 仍触
        dormant_project. 治本: ProjectTimeline.held_until_ts = now + hours*3600,
        get_dormant_projects 过滤期间. 默认 72h (3天) — Sir 重复说会 refresh.

        Args:
          project_name: 严格匹配 ProjectTimeline.project_name (case-insensitive 模糊见 _find_project_match).
          hours: hold 时长, default 72h.
          source: trace 来源 ('intent_resolver' / 'sir_cmd' / 'reflector').
        Returns:
          True 真 hold 成功 / False 项目不存在.
        """
        if not project_name or hours <= 0:
            return False
        until_ts = time.time() + (hours * 3600.0)
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE ProjectTimeline SET held_until_ts = ? "
                "WHERE LOWER(project_name) = LOWER(?)",
                (until_ts, project_name)
            )
            ok = cursor.rowcount > 0
            conn.commit()
        except Exception:
            ok = False
        finally:
            conn.close()
        if ok:
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"⏸️ [ProjectTimeline/hold] '{project_name}' held until "
                    f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(until_ts))} "
                    f"({hours:.0f}h, src={source or 'unknown'})"
                )
            except Exception:
                pass
        return ok

    def find_project_by_keyword(self, keyword: str) -> Optional[str]:
        """🆕 [β.5.46-fix18 / 2026-05-22] 模糊查找 project_name (Sir 说"驾照" 找 "驾照科一").

        IntentResolver project_hold action 用此 helper 把 Sir 自然语言中的项目词
        映射到真实 project_name. 不命中返 None.
        """
        if not keyword or not str(keyword).strip():
            return None
        kw = str(keyword).strip().lower()
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT project_name FROM ProjectTimeline "
                "WHERE LOWER(project_name) LIKE ? AND status = 'active' "
                "ORDER BY last_active_time DESC LIMIT 1",
                (f"%{kw}%",)
            )
            row = cursor.fetchone()
        except Exception:
            row = None
        finally:
            conn.close()
        return row[0] if row else None

    def get_active_projects_summary(self) -> str:
        """生成活跃项目摘要，供 Prompt 注入"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT project_name, last_active_time, total_hours, session_count FROM ProjectTimeline WHERE status = 'active' ORDER BY last_active_time DESC LIMIT 5"
        )
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return ""
        
        now = time.time()
        parts = ["[PROJECT TIMELINE - Sir's active projects tracked by Jarvis]:"]
        for r in rows:
            days_ago = round((now - r[1]) / 86400, 1)
            if days_ago < 1:
                ago_str = "today"
            elif days_ago < 2:
                ago_str = "yesterday"
            else:
                ago_str = f"{int(days_ago)} days ago"
            parts.append(f"  - {r[0]}: last active {ago_str}, {round(r[2],1)}h total, {r[3]} sessions")
        
        return '\n'.join(parts)

    def mark_project_completed(self, project_name: str):
        """标记项目为已完成"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE ProjectTimeline SET status = 'completed' WHERE project_name = ?",
            (project_name,)
        )
        conn.commit()
        conn.close()