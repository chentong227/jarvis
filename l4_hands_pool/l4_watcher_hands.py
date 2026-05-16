import ctypes
import time
import json
import base64
import threading
import os
import io
import uuid
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "watcher_hands",
    "description": "屏幕/窗口监控调度引擎。定时截图→规则匹配或LLM判断→自动点击/输入/通知。支持持续轮询监控、发现即操作。纯本地调度，可选LLM辅助判断。",
    "requires_eyes": "desktop_eyes"
}

user32 = ctypes.windll.user32

try:
    from PIL import ImageGrab, Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


class WatcherJob:
    def __init__(self, job_id, config):
        self.job_id = job_id
        self.config = config
        self.created_at = time.time()
        self.last_check = 0
        self.check_count = 0
        self.consecutive_empty = 0
        self.current_interval = config.get("check_interval", 5)
        self.min_interval = config.get("min_interval", 2)
        self.max_interval = config.get("max_interval", 30)
        self.status = "running"
        self.last_result = None
        self.action_history = []

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "config": self.config,
            "status": self.status,
            "check_count": self.check_count,
            "elapsed": round(time.time() - self.created_at, 1),
            "current_interval": self.current_interval,
            "consecutive_empty": self.consecutive_empty,
            "last_result": self.last_result,
        }


class WatcherScheduler(threading.Thread):
    _instance = None
    _lock = threading.Lock()

    # [P0+19-deps] 默认 key 从 .env 读取（Jarvis 启动时 jarvis_config.keys.load_keys 已注入 os.environ）
    # 仍为 None 表示未加载或运行在 watcher_hands 单测脚本中，使用方需先 configure()
    DEFAULT_API_KEY = None
    DEFAULT_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self):
        if WatcherScheduler._instance is not None:
            raise RuntimeError("WatcherScheduler is a singleton")
        super().__init__(daemon=True)
        self._jobs = {}
        self._running = False
        self._job_lock = threading.Lock()
        self._api_key = os.environ.get("GEMINI_KEY") or WatcherScheduler.DEFAULT_API_KEY
        self._api_base = WatcherScheduler.DEFAULT_API_BASE
        self._on_action = None
        WatcherScheduler._instance = self

    @classmethod
    def get_instance(cls):
        if cls._instance is None or not cls._instance.is_alive():
            cls._instance = WatcherScheduler()
            cls._instance.start()
        return cls._instance

    def configure(self, api_key=None, api_base=None, on_action=None):
        self._api_key = api_key
        self._api_base = api_base
        self._on_action = on_action

    def add_job(self, config: dict) -> str:
        job_id = config.get("job_id") or str(uuid.uuid4())[:8]
        job = WatcherJob(job_id, config)
        with self._job_lock:
            self._jobs[job_id] = job
        if not self._running:
            self._running = True
            self.start()
        return job_id

    def remove_job(self, job_id: str) -> bool:
        with self._job_lock:
            if job_id in self._jobs:
                self._jobs[job_id].status = "stopped"
                del self._jobs[job_id]
                return True
        return False

    def get_job(self, job_id: str):
        with self._job_lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list:
        with self._job_lock:
            return [j.to_dict() for j in self._jobs.values()]

    def stop_all(self):
        with self._job_lock:
            for j in self._jobs.values():
                j.status = "stopped"
            self._jobs.clear()
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            with self._job_lock:
                jobs = list(self._jobs.values())
            if not jobs:
                time.sleep(1)
                continue

            now = time.time()
            for job in jobs:
                if job.status != "running":
                    continue
                duration = job.config.get("duration", 0)
                if duration > 0 and (now - job.created_at) > duration:
                    job.status = "done"
                    continue
                if now - job.last_check < job.current_interval:
                    continue

                job.last_check = now
                job.check_count += 1
                try:
                    self._execute_check(job)
                except Exception as e:
                    job.last_result = f"check_error: {e}"

            time.sleep(0.3)

    def _execute_check(self, job: WatcherJob):
        config = job.config
        mode = config.get("mode", "rule")
        use_dynamic = config.get("dynamic_interval", True)

        screenshot = self._capture(config)

        if mode == "rule":
            result = self._rule_check(screenshot, config)
        elif mode == "llm":
            result = self._llm_check(screenshot, config)
        elif mode == "hybrid":
            result = self._rule_check(screenshot, config)
            if not result or not result.get("found"):
                result = self._llm_check(screenshot, config)
        else:
            result = {"found": False, "reason": f"unknown mode: {mode}"}

        job.last_result = result

        if result and result.get("found"):
            job.consecutive_empty = 0
            if use_dynamic:
                job.current_interval = job.min_interval
            if result.get("action"):
                self._dispatch_action(job, result["action"])
        else:
            job.consecutive_empty += 1
            if use_dynamic:
                backoff = min(job.consecutive_empty, 10)
                job.current_interval = min(
                    job.min_interval + backoff * 2,
                    job.max_interval
                )

    def _capture(self, config: dict):
        if not HAS_PIL:
            return None
        capture_type = config.get("capture", "full")
        try:
            if capture_type == "window":
                hwnd = config.get("hwnd")
                if hwnd:
                    rect = ctypes.c_int()
                    class RECT(ctypes.Structure):
                        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
                    r = RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(r))
                    img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
                else:
                    title = config.get("window_title", "")
                    hwnd = user32.FindWindowW(None, title) if title else None
                    if hwnd:
                        class RECT(ctypes.Structure):
                            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
                        r = RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(r))
                        img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
                    else:
                        img = ImageGrab.grab()
            elif capture_type == "region":
                region = config.get("region", {})
                bbox = (region.get("x1", 0), region.get("y1", 0),
                        region.get("x2", 1920), region.get("y2", 1080))
                img = ImageGrab.grab(bbox=bbox)
            else:
                img = ImageGrab.grab()
            return img
        except Exception:
            return None

    def _rule_check(self, screenshot, config: dict):
        if screenshot is None:
            return {"found": False, "reason": "screenshot failed"}
        rules = config.get("rules", [])
        if not rules:
            return {"found": False, "reason": "no rules configured"}

        for rule in rules:
            rule_type = rule.get("type", "")
            if rule_type == "text_ocr":
                result = self._ocr_find(screenshot, rule)
                if result:
                    return result
            elif rule_type == "template_match":
                result = self._template_find(screenshot, rule)
                if result:
                    return result
            elif rule_type == "color_check":
                result = self._color_check(screenshot, rule)
                if result:
                    return result
            elif rule_type == "pixel_change":
                result = self._pixel_change(screenshot, rule, config)
                if result:
                    return result
        return {"found": False, "reason": "no rule matched"}

    def _ocr_find(self, screenshot, rule: dict):
        target_text = rule.get("text", "").lower()
        if not target_text:
            return None
        try:
            import pytesseract
            text = pytesseract.image_to_string(screenshot, lang=rule.get("lang", "chi_sim+eng"))
            if target_text in text.lower():
                data = pytesseract.image_to_data(screenshot, lang=rule.get("lang", "chi_sim+eng"),
                                                  output_type=pytesseract.Output.DICT)
                for i, word in enumerate(data["text"]):
                    if target_text in word.lower():
                        x = data["left"][i] + data["width"][i] // 2
                        y = data["top"][i] + data["height"][i] // 2
                        return {
                            "found": True,
                            "method": "ocr",
                            "matched_text": word,
                            "position": {"x": x, "y": y},
                            "action": rule.get("action", {"type": "click", "x": x, "y": y})
                        }
        except ImportError:
            pass
        except Exception:
            pass
        return None

    def _template_find(self, screenshot, rule: dict):
        template_path = rule.get("template", "")
        if not template_path or not os.path.exists(template_path) or not HAS_CV2:
            return None
        try:
            screen_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
            template = cv2.imread(template_path)
            result = cv2.matchTemplate(screen_cv, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            threshold = rule.get("threshold", 0.8)
            if max_val >= threshold:
                h, w = template.shape[:2]
                x = max_loc[0] + w // 2
                y = max_loc[1] + h // 2
                return {
                    "found": True,
                    "method": "template",
                    "confidence": float(max_val),
                    "position": {"x": x, "y": y},
                    "action": rule.get("action", {"type": "click", "x": x, "y": y})
                }
        except Exception:
            pass
        return None

    def _color_check(self, screenshot, rule: dict):
        target_color = rule.get("color")
        tolerance = rule.get("tolerance", 10)
        if not target_color:
            return None
        try:
            if HAS_CV2:
                screen_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
                r, g, b = target_color if isinstance(target_color, (list, tuple)) else (target_color, target_color, target_color)
                lower = np.array([max(0, b - tolerance), max(0, g - tolerance), max(0, r - tolerance)])
                upper = np.array([min(255, b + tolerance), min(255, g + tolerance), min(255, r + tolerance)])
                mask = cv2.inRange(screen_cv, lower, upper)
                ys, xs = np.where(mask > 0)
                if len(xs) > 0:
                    cx, cy = int(np.mean(xs)), int(np.mean(ys))
                    return {
                        "found": True,
                        "method": "color",
                        "pixel_count": len(xs),
                        "position": {"x": cx, "y": cy},
                        "action": rule.get("action", {"type": "click", "x": cx, "y": cy})
                    }
        except Exception:
            pass
        return None

    def _pixel_change(self, screenshot, rule: dict, config: dict):
        cache_key = f"_pixel_cache_{config.get('job_id', '')}"
        if not hasattr(self, cache_key):
            setattr(self, cache_key, None)
        prev = getattr(self, cache_key)
        if prev is None:
            setattr(self, cache_key, screenshot)
            return None
        try:
            if HAS_CV2:
                curr = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
                prev_gray = cv2.cvtColor(np.array(prev), cv2.COLOR_RGB2GRAY)
                diff = cv2.absdiff(curr, prev_gray)
                _, thresh = cv2.threshold(diff, rule.get("threshold", 30), 255, cv2.THRESH_BINARY)
                ys, xs = np.where(thresh > 0)
                setattr(self, cache_key, screenshot)
                if len(xs) > rule.get("min_pixels", 100):
                    cx, cy = int(np.mean(xs)), int(np.mean(ys))
                    return {
                        "found": True,
                        "method": "pixel_change",
                        "changed_pixels": len(xs),
                        "position": {"x": cx, "y": cy},
                        "action": rule.get("action", {"type": "notify",
                                        "message": f"Screen changed: {len(xs)} pixels"})
                    }
        except Exception:
            pass
        setattr(self, cache_key, screenshot)
        return None

    def _llm_check(self, screenshot, config: dict):
        if screenshot is None or not self._api_key:
            return {"found": False, "reason": "no api key or screenshot"}
        try:
            buf = io.BytesIO()
            screenshot.save(buf, format="JPEG", quality=60)
            img_b64 = base64.b64encode(buf.getvalue()).decode()

            prompt = config.get("llm_prompt", "Look at this screenshot. Describe what you see in one sentence. "
                                "If there is a button or element that needs to be clicked, "
                                "return JSON: {\"found\": true, \"action\": {\"type\": \"click\", \"x\": X, \"y\": Y}, \"reason\": \"...\"}. "
                                "If nothing needs action, return {\"found\": false, \"reason\": \"...\"}.")

            import requests
            api_base = self._api_base or "https://generativelanguage.googleapis.com/v1beta"
            model = config.get("llm_model", "gemini-3.1-flash-lite")
            url = f"{api_base}/models/{model}:generateContent?key={self._api_key}"

            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
                    ]
                }],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 256}
            }

            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                try:
                    json_match = text
                    if "```json" in text:
                        json_match = text.split("```json")[1].split("```")[0]
                    elif "```" in text:
                        json_match = text.split("```")[1].split("```")[0]
                    result = json.loads(json_match.strip())
                    result["raw_response"] = text
                    return result
                except json.JSONDecodeError:
                    return {"found": False, "reason": "parse_error", "raw_response": text}
            return {"found": False, "reason": f"api_error: {resp.status_code}"}
        except Exception as e:
            return {"found": False, "reason": f"llm_error: {e}"}

    def _dispatch_action(self, job: WatcherJob, action: dict):
        action_type = action.get("type", "")
        job.action_history.append({"time": time.time(), "action": action})

        if self._on_action:
            try:
                self._on_action(job.job_id, action)
            except Exception:
                pass

        if action_type == "click":
            x, y = action.get("x", 0), action.get("y", 0)
            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)
            abs_x = int(x * 65535 / screen_w)
            abs_y = int(y * 65535 / screen_h)

            class MOUSEINPUT(ctypes.Structure):
                _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                            ("mouseData", ctypes.c_uint), ("dwFlags", ctypes.c_uint),
                            ("time", ctypes.c_uint), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                            ("dwFlags", ctypes.c_uint), ("time", ctypes.c_uint),
                            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
            class INPUT_UNION(ctypes.Union):
                _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]
            class INPUT(ctypes.Structure):
                _fields_ = [("type", ctypes.c_uint), ("union", INPUT_UNION)]

            def _send(inp):
                ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

            inp_move = INPUT()
            inp_move.type = 0
            inp_move.union.mi.dx = abs_x
            inp_move.union.mi.dy = abs_y
            inp_move.union.mi.dwFlags = 0x0001 | 0x8000
            _send(inp_move)
            time.sleep(0.02)

            inp_down = INPUT()
            inp_down.type = 0
            inp_down.union.mi.dwFlags = 0x0002
            _send(inp_down)
            inp_up = INPUT()
            inp_up.type = 0
            inp_up.union.mi.dwFlags = 0x0004
            _send(inp_up)

        elif action_type == "notify":
            msg = action.get("message", "Watcher alert")
            try:
                ctypes.windll.user32.MessageBoxW(0, msg, "Jarvis Watcher", 0x40)
            except Exception:
                pass

        elif action_type == "stop_job":
            job.status = "done"

        elif action_type == "run_module":
            module_action = action.get("module_action", {})
            if self._on_action:
                try:
                    self._on_action(job.job_id, {"type": "module_call", "data": module_action})
                except Exception:
                    pass


class Hands:
    def __init__(self):
        self.requires_memory_seal = False
        self._scheduler = None

    def _get_scheduler(self):
        if self._scheduler is None:
            self._scheduler = WatcherScheduler.get_instance()
        return self._scheduler

    def get_instruction_dict(self) -> str:
        return """
        【监控调度引擎 指令字典】：
        1. "start_watch": {"job_id": "可选", "mode": "rule/llm/hybrid", "capture": "full/window/region",
           "window_title": "窗口标题", "check_interval": 10, "duration": 1800,
           "rules": [{"type": "text_ocr", "text": "确认", "action": {"type": "click"}}],
           "llm_prompt": "判断截图是否需要操作"}
           — 启动一个监控任务。duration=0表示无限。check_interval秒数。
        2. "stop_watch": {"job_id": "任务ID"} — 停止监控
        3. "list_watches": {} — 列出所有活跃监控
        4. "stop_all_watches": {} — 停止所有监控
        5. "screenshot": {"capture": "full/window/region", "window_title": "可选", "save_path": "可选"}
           — 截图并返回base64或保存
        6. "find_on_screen": {"text": "要查找的文字", "lang": "chi_sim+eng"}
           — OCR查找屏幕上文字位置
        7. "find_template": {"template_path": "图片路径", "threshold": 0.8}
           — 模板匹配查找
        8. "find_color": {"color": [R,G,B], "tolerance": 10}
           — 颜色查找
        9. "wait_for_window": {"title": "窗口标题", "timeout": 30}
           — 等待窗口出现
        10. "wait_for_text": {"text": "文字", "timeout": 30, "lang": "chi_sim+eng"}
           — 等待屏幕上出现文字
        11. "llm_judge": {"prompt": "判断指令", "capture": "full", "model": "gemini-2.0-flash"}
           — 截图发给LLM判断，返回JSON
        12. "watch_and_click": {"window_title": "窗口", "target_text": "按钮文字",
           "check_interval": 5, "duration": 600}
           — 快捷：监控窗口→找到文字→点击
        13. "watch_and_notify": {"window_title": "窗口", "target_text": "完成/导出",
           "check_interval": 10, "duration": 3600}
           — 快捷：监控窗口→找到文字→弹窗通知
        14. "get_job_status": {"job_id": "任务ID"} — 查看任务状态
        15. "configure_llm": {"api_key": "key", "api_base": "url"}
           — 配置LLM判断用的API
        16. "watch_jarvis": {"duration": 1800, "check_interval": 3}
           — 监控Jarvis任务状态，检测到「任务停止」自动点击「继续」
           duration默认1800s(30分钟)，check_interval默认3s
        """

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        try:
            sched = self._get_scheduler()

            if cmd == "start_watch":
                job_id = sched.add_job(params)
                return ExecutionResult(success=True, msg=f"监控任务已启动: {job_id}",
                                       data={"job_id": job_id})

            elif cmd == "stop_watch":
                job_id = params.get("job_id", "")
                ok = sched.remove_job(job_id)
                return ExecutionResult(success=ok, msg=f"任务 {'已停止' if ok else '未找到'}: {job_id}")

            elif cmd == "list_watches":
                jobs = sched.list_jobs()
                if not jobs:
                    return ExecutionResult(success=True, msg="当前无活跃监控任务", data={"jobs": []})
                lines = [f"  [{j['job_id']}] {j['status']} | 检查{j['check_count']}次 | 运行{j['elapsed']}s" for j in jobs]
                return ExecutionResult(success=True, msg=f"活跃监控 {len(jobs)} 个:\n" + "\n".join(lines),
                                       data={"jobs": jobs})

            elif cmd == "stop_all_watches":
                sched.stop_all()
                return ExecutionResult(success=True, msg="所有监控任务已停止")

            elif cmd == "screenshot":
                if not HAS_PIL:
                    return ExecutionResult(success=False, msg="PIL not installed")
                img = sched._capture(params)
                if img is None:
                    return ExecutionResult(success=False, msg="截图失败")
                save_path = params.get("save_path", "")
                if save_path:
                    img.save(save_path)
                    return ExecutionResult(success=True, msg=f"截图已保存: {save_path}",
                                           data={"path": save_path, "size": f"{img.width}x{img.height}"})
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=70)
                b64 = base64.b64encode(buf.getvalue()).decode()
                return ExecutionResult(success=True, msg=f"截图完成 {img.width}x{img.height}",
                                       data={"base64": b64[:200] + "...", "width": img.width, "height": img.height})

            elif cmd == "find_on_screen":
                if not HAS_PIL:
                    return ExecutionResult(success=False, msg="PIL not installed")
                img = sched._capture(params)
                if img is None:
                    return ExecutionResult(success=False, msg="截图失败")
                rule = {"type": "text_ocr", "text": params.get("text", ""),
                        "lang": params.get("lang", "chi_sim+eng")}
                result = sched._ocr_find(img, rule)
                if result:
                    return ExecutionResult(success=True,
                                           msg=f"找到 '{result['matched_text']}' 在 ({result['position']['x']},{result['position']['y']})",
                                           data=result)
                return ExecutionResult(success=False, msg=f"未找到文字: {params.get('text', '')}")

            elif cmd == "find_template":
                if not HAS_PIL or not HAS_CV2:
                    return ExecutionResult(success=False, msg="PIL/OpenCV not installed")
                img = sched._capture(params)
                if img is None:
                    return ExecutionResult(success=False, msg="截图失败")
                rule = {"type": "template_match", "template": params.get("template_path", ""),
                        "threshold": params.get("threshold", 0.8)}
                result = sched._template_find(img, rule)
                if result:
                    return ExecutionResult(success=True,
                                           msg=f"模板匹配成功 (置信度:{result['confidence']:.2f}) 在 ({result['position']['x']},{result['position']['y']})",
                                           data=result)
                return ExecutionResult(success=False, msg="模板未匹配")

            elif cmd == "find_color":
                if not HAS_PIL or not HAS_CV2:
                    return ExecutionResult(success=False, msg="PIL/OpenCV not installed")
                img = sched._capture(params)
                if img is None:
                    return ExecutionResult(success=False, msg="截图失败")
                rule = {"type": "color_check", "color": params.get("color", [255, 255, 255]),
                        "tolerance": params.get("tolerance", 10)}
                result = sched._color_check(img, rule)
                if result:
                    return ExecutionResult(success=True,
                                           msg=f"找到 {result['pixel_count']} 个匹配像素，中心 ({result['position']['x']},{result['position']['y']})",
                                           data=result)
                return ExecutionResult(success=False, msg="未找到匹配颜色")

            elif cmd == "wait_for_window":
                title = params.get("title", "")
                timeout = params.get("timeout", 30)
                start = time.time()
                while time.time() - start < timeout:
                    hwnd = user32.FindWindowW(None, title)
                    if hwnd:
                        return ExecutionResult(success=True, msg=f"窗口已出现: {title}",
                                               data={"hwnd": hwnd, "waited": round(time.time() - start, 1)})
                    time.sleep(0.5)
                return ExecutionResult(success=False, msg=f"超时 {timeout}s，窗口未出现: {title}")

            elif cmd == "wait_for_text":
                if not HAS_PIL:
                    return ExecutionResult(success=False, msg="PIL not installed")
                target = params.get("text", "")
                timeout = params.get("timeout", 30)
                start = time.time()
                while time.time() - start < timeout:
                    img = sched._capture(params)
                    if img:
                        rule = {"type": "text_ocr", "text": target,
                                "lang": params.get("lang", "chi_sim+eng")}
                        result = sched._ocr_find(img, rule)
                        if result:
                            return ExecutionResult(success=True,
                                                   msg=f"文字已出现 '{result['matched_text']}' 在 ({result['position']['x']},{result['position']['y']})",
                                                   data=result)
                    time.sleep(1)
                return ExecutionResult(success=False, msg=f"超时 {timeout}s，未找到: {target}")

            elif cmd == "llm_judge":
                if not HAS_PIL:
                    return ExecutionResult(success=False, msg="PIL not installed")
                img = sched._capture(params)
                if img is None:
                    return ExecutionResult(success=False, msg="截图失败")
                config = {"llm_prompt": params.get("prompt", ""),
                          "llm_model": params.get("model", "gemini-2.0-flash")}
                result = sched._llm_check(img, config)
                return ExecutionResult(success=result.get("found", False),
                                       msg=result.get("reason", str(result)),
                                       data=result)

            elif cmd == "watch_and_click":
                config = {
                    "mode": "rule",
                    "capture": "full",
                    "window_title": params.get("window_title", ""),
                    "check_interval": params.get("check_interval", 5),
                    "duration": params.get("duration", 600),
                    "rules": [{"type": "text_ocr", "text": params.get("target_text", ""),
                               "action": {"type": "click"}}]
                }
                job_id = sched.add_job(config)
                return ExecutionResult(success=True, msg=f"监控+点击任务已启动: {job_id}",
                                       data={"job_id": job_id})

            elif cmd == "watch_and_notify":
                config = {
                    "mode": "rule",
                    "capture": "full",
                    "window_title": params.get("window_title", ""),
                    "check_interval": params.get("check_interval", 10),
                    "duration": params.get("duration", 3600),
                    "rules": [{"type": "text_ocr", "text": params.get("target_text", ""),
                               "action": {"type": "notify",
                                          "message": f"检测到: {params.get('target_text', '')}"}}]
                }
                job_id = sched.add_job(config)
                return ExecutionResult(success=True, msg=f"监控+通知任务已启动: {job_id}",
                                       data={"job_id": job_id})

            elif cmd == "get_job_status":
                job_id = params.get("job_id", "")
                job = sched.get_job(job_id)
                if job:
                    return ExecutionResult(success=True, msg=f"任务 {job_id}: {job.status}",
                                           data=job.to_dict())
                return ExecutionResult(success=False, msg=f"任务不存在: {job_id}")

            elif cmd == "configure_llm":
                sched.configure(api_key=params.get("api_key"), api_base=params.get("api_base"))
                return ExecutionResult(success=True, msg="LLM配置已更新")

            elif cmd == "watch_jarvis":
                duration = params.get("duration", 1800)
                check_interval = params.get("check_interval", 3)
                config = {
                    "mode": "rule",
                    "capture": "full",
                    "check_interval": check_interval,
                    "min_interval": 2,
                    "max_interval": 10,
                    "dynamic_interval": True,
                    "duration": duration,
                    "rules": [
                        {"type": "text_ocr", "text": "任务停止",
                         "lang": "chi_sim",
                         "action": {"type": "click"}},
                        {"type": "text_ocr", "text": "继续",
                         "lang": "chi_sim",
                         "action": {"type": "click"}},
                        {"type": "text_ocr", "text": "stopped",
                         "lang": "eng",
                         "action": {"type": "click"}},
                        {"type": "text_ocr", "text": "error",
                         "lang": "eng",
                         "action": {"type": "click"}},
                    ]
                }
                job_id = sched.add_job(config)
                return ExecutionResult(success=True,
                                       msg=f"Jarvis守护已启动: {job_id} | 持续{duration}s | 间隔{check_interval}s | 检测到「任务停止/继续/stopped/error」自动点击",
                                       data={"job_id": job_id, "duration": duration, "check_interval": check_interval})

            else:
                return ExecutionResult(success=False, msg=f"未知指令: {cmd}")

        except Exception as e:
            return ExecutionResult(success=False, msg=f"监控引擎异常: {str(e)}")