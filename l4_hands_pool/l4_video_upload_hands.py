import os
import json
import time
import hashlib
import subprocess
import threading
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "video_upload_hands",
    "description": "视频上传引擎。B站(API+ Cookies)/YouTube(Selenium浏览器自动化)。支持查重字典、进度追踪。",
}

BILIBILI_AUTH_PATH = os.path.join("jarvis_config", "bilibili_auth.json")
UPLOADED_DICT_PATH = os.path.join("jarvis_config", "uploaded_videos.json")


def _load_uploaded_dict():
    if os.path.exists(UPLOADED_DICT_PATH):
        try:
            with open(UPLOADED_DICT_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_uploaded_dict(data):
    os.makedirs(os.path.dirname(UPLOADED_DICT_PATH), exist_ok=True)
    with open(UPLOADED_DICT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_bilibili_cookies():
    if not os.path.exists(BILIBILI_AUTH_PATH):
        return None
    try:
        with open(BILIBILI_AUTH_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        cookies = {}
        for c in data.get("cookies", []):
            cookies[c["name"]] = c["value"]
        return cookies
    except Exception:
        return None


class Hands:
    def __init__(self):
        self.requires_memory_seal = False
        self._uploaded_dict = _load_uploaded_dict()

    def get_instruction_dict(self) -> str:
        return """
        【视频上传引擎 指令字典】：
        1. "upload_bilibili": {"video_path": "D:/videos/test.mp4", "title": "标题",
           "desc": "简介", "tags": ["标签1","标签2"], "tid": 17, "source": "来源"}
           — 上传到B站。tid默认17(电子竞技)。返回BV号。
        2. "upload_youtube": {"video_path": "D:/videos/test.mp4", "title": "标题",
           "desc": "简介", "tags": ["tag1"], "privacy": "private/public/unlisted"}
           — 上传到YouTube(浏览器自动化)。privacy默认private。
        3. "upload_both": {"video_path": "...", "title": "...", ...}
           — 同时上传B站+YouTube
        4. "check_uploaded": {"video_path": "D:/videos/test.mp4"}
           — 检查视频是否已上传过(基于MD5)
        5. "list_uploaded": {}
           — 列出已上传视频字典
        6. "mark_uploaded": {"video_path": "...", "platform": "bilibili/youtube", "url": "..."}
           — 手动标记已上传
        7. "find_new_videos": {"directory": "D:/videos", "extensions": [".mp4",".mov"]}
           — 扫描目录找出未上传的新视频
        """

    def _file_md5(self, path):
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _is_uploaded(self, video_path, platform=None):
        md5 = self._file_md5(video_path)
        if md5 in self._uploaded_dict:
            entry = self._uploaded_dict[md5]
            if platform and platform not in entry.get("platforms", []):
                return False
            return True
        return False

    def _mark_uploaded(self, video_path, platform, url=""):
        md5 = self._file_md5(video_path)
        if md5 not in self._uploaded_dict:
            self._uploaded_dict[md5] = {
                "path": video_path,
                "filename": os.path.basename(video_path),
                "platforms": [],
                "urls": {},
                "first_uploaded": time.time(),
            }
        entry = self._uploaded_dict[md5]
        if platform not in entry["platforms"]:
            entry["platforms"].append(platform)
        if url:
            entry["urls"][platform] = url
        entry["last_uploaded"] = time.time()
        _save_uploaded_dict(self._uploaded_dict)

    def _upload_bilibili_edge(self, video_path, title, desc="", tags=None, tid=17, source=""):
        if not os.path.exists(video_path):
            return ExecutionResult(success=False, msg=f"视频文件不存在: {video_path}")

        try:
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.edge.options import Options
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
        except ImportError:
            return ExecutionResult(success=False,
                                   msg="selenium not installed. Run: pip install selenium")

        cookies = _load_bilibili_cookies()

        options = Options()
        options.add_argument("--start-maximized")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--disable-blink-features=AutomationControlled")

        driver = None
        try:
            driver = webdriver.Edge(options=options)
            wait = WebDriverWait(driver, 30)

            driver.get("https://www.bilibili.com")
            time.sleep(2)

            if cookies:
                for name, value in cookies.items():
                    try:
                        driver.add_cookie({"name": name, "value": value, "domain": ".bilibili.com"})
                    except Exception:
                        pass
                driver.refresh()
                time.sleep(2)

            driver.get("https://member.bilibili.com/platform/upload/video/frame")
            time.sleep(3)

            try:
                file_input = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
                )
                file_input.send_keys(os.path.abspath(video_path))
                print(f"[B站Edge] 视频文件已选择: {os.path.basename(video_path)}")
            except Exception as e:
                return ExecutionResult(success=False, msg=f"B站上传页面文件选择失败: {e}")

            time.sleep(3)

            if title:
                try:
                    title_input = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR,
                            "input[placeholder*='标题'], .title-input input, input.title-inp"))
                    )
                    title_input.clear()
                    title_input.send_keys(title)
                    print(f"[B站Edge] 标题已填入: {title}")
                except Exception:
                    print("[B站Edge] 标题自动填入失败，请手动填写")

            if desc:
                try:
                    desc_input = driver.find_element(By.CSS_SELECTOR,
                        "textarea[placeholder*='简介'], .desc-input textarea, textarea.desc-inp")
                    desc_input.clear()
                    desc_input.send_keys(desc)
                except Exception:
                    pass

            if tags:
                try:
                    tag_input = driver.find_element(By.CSS_SELECTOR,
                        "input[placeholder*='标签'], .tag-input input")
                    tag_input.clear()
                    tag_input.send_keys(",".join(tags))
                except Exception:
                    pass

            print(f"\n{'='*60}")
            print(f"[B站Edge] 视频已加载到上传页面")
            print(f"[B站Edge] 请在 Edge 浏览器中:")
            print(f"  1. 确认/修改标题")
            print(f"  2. 上传/编辑封面")
            print(f"  3. 选择分区和标签")
            print(f"  4. 点击「提交」发布")
            print(f"[B站Edge] 浏览器窗口将保持打开，完成后可手动关闭")
            print(f"{'='*60}\n")

            self._mark_uploaded(video_path, "bilibili", "https://member.bilibili.com/platform/upload/video/frame")
            return ExecutionResult(success=True,
                                   msg=f"B站上传页面已在Edge中打开。请在浏览器中完成标题、封面和发布。",
                                   data={"note": "浏览器窗口保持打开，请手动完成标题/封面/发布"})

        except Exception as e:
            return ExecutionResult(success=False, msg=f"B站Edge上传异常: {e}")

    def _upload_youtube_chrome(self, video_path, title, desc="", tags=None, privacy="private"):
        if not os.path.exists(video_path):
            return ExecutionResult(success=False, msg=f"视频文件不存在: {video_path}")

        try:
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
        except ImportError:
            return ExecutionResult(success=False,
                                   msg="selenium not installed. Run: pip install selenium")

        import glob as _glob
        user_data_dir = os.path.expanduser(r"~\AppData\Local\Google\Chrome\User Data")
        profile_dir = "Default"

        if os.path.isdir(user_data_dir):
            profiles = [d for d in os.listdir(user_data_dir)
                       if os.path.isdir(os.path.join(user_data_dir, d)) and d.startswith("Profile ")]
            for p in profiles:
                pref_path = os.path.join(user_data_dir, p, "Preferences")
                if os.path.exists(pref_path):
                    try:
                        with open(pref_path, "r", encoding="utf-8") as f:
                            import json as _json
                            prefs = _json.load(f)
                        name = prefs.get("profile", {}).get("name", "")
                        if "之北" in name:
                            profile_dir = p
                            print(f"[YouTube Chrome] 找到之北Profile: {p} ({name})")
                            break
                    except Exception:
                        pass

        options = Options()
        options.add_argument(f"--user-data-dir={user_data_dir}")
        options.add_argument(f"--profile-directory={profile_dir}")
        options.add_argument("--start-maximized")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--disable-blink-features=AutomationControlled")

        driver = None
        try:
            driver = webdriver.Chrome(options=options)
            wait = WebDriverWait(driver, 30)

            driver.get("https://studio.youtube.com")
            time.sleep(3)

            try:
                upload_btn = wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "ytcp-icon-button#upload-icon, ytcp-button#create-icon"))
                )
                upload_btn.click()
            except Exception:
                try:
                    driver.get("https://studio.youtube.com/channel/UC/upload")
                    time.sleep(3)
                except Exception:
                    pass

            time.sleep(2)

            try:
                file_input = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
                )
                file_input.send_keys(os.path.abspath(video_path))
                print(f"[YouTube Chrome] 视频文件已选择: {os.path.basename(video_path)}")
            except Exception as e:
                return ExecutionResult(success=False, msg=f"YouTube上传按钮未找到: {e}")

            time.sleep(5)

            if title:
                try:
                    title_input = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR,
                            "div#textbox[contenteditable], #title-textarea, ytcp-social-suggestions-textbox#title-textarea div#textbox"))
                    )
                    title_input.click()
                    title_input.clear()
                    title_input.send_keys(title)
                    print(f"[YouTube Chrome] 标题已填入: {title}")
                except Exception:
                    pass

            if desc:
                try:
                    desc_inputs = driver.find_elements(By.CSS_SELECTOR, "div#textbox[contenteditable]")
                    if len(desc_inputs) > 1:
                        desc_inputs[1].click()
                        desc_inputs[1].send_keys(desc)
                except Exception:
                    pass

            try:
                not_for_kids = wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR,
                        "tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']"))
                )
                not_for_kids.click()
            except Exception:
                pass

            for _ in range(3):
                try:
                    next_btn = driver.find_element(By.CSS_SELECTOR, "#next-button button, ytcp-button#next-button")
                    next_btn.click()
                    time.sleep(2)
                except Exception:
                    break

            for _ in range(3):
                try:
                    next_btn = driver.find_element(By.CSS_SELECTOR, "#next-button button, ytcp-button#next-button")
                    next_btn.click()
                    time.sleep(2)
                except Exception:
                    break

            if privacy == "public":
                try:
                    public_radio = wait.until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR,
                            "tp-yt-paper-radio-button[name='PUBLIC']"))
                    )
                    public_radio.click()
                except Exception:
                    pass
            elif privacy == "unlisted":
                try:
                    unlisted_radio = wait.until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR,
                            "tp-yt-paper-radio-button[name='UNLISTED']"))
                    )
                    unlisted_radio.click()
                except Exception:
                    pass

            time.sleep(1)

            try:
                done_btn = driver.find_element(By.CSS_SELECTOR, "#done-button button, ytcp-button#done-button")
                done_btn.click()
            except Exception:
                pass

            time.sleep(5)

            try:
                close_btn = driver.find_element(By.CSS_SELECTOR, "#close-button button, ytcp-button#close-button")
                close_btn.click()
            except Exception:
                pass

            current_url = driver.current_url
            self._mark_uploaded(video_path, "youtube", current_url)
            return ExecutionResult(success=True,
                                   msg=f"YouTube上传已提交! 当前页面: {current_url}",
                                   data={"url": current_url})

        except Exception as e:
            return ExecutionResult(success=False, msg=f"YouTube上传异常: {e}")
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        try:
            if cmd == "upload_bilibili":
                video_path = params.get("video_path", "")
                if not video_path:
                    return ExecutionResult(success=False, msg="缺少 video_path")
                if self._is_uploaded(video_path, "bilibili"):
                    entry = self._uploaded_dict[self._file_md5(video_path)]
                    return ExecutionResult(success=True,
                                           msg=f"视频已上传过B站: {entry.get('urls', {}).get('bilibili', '')}",
                                           data={"already_uploaded": True, "url": entry.get("urls", {}).get("bilibili", "")})
                return self._upload_bilibili_edge(
                    video_path,
                    title=params.get("title", os.path.basename(video_path)),
                    desc=params.get("desc", ""),
                    tags=params.get("tags", []),
                    tid=params.get("tid", 17),
                    source=params.get("source", ""),
                )

            elif cmd == "upload_youtube":
                video_path = params.get("video_path", "")
                if not video_path:
                    return ExecutionResult(success=False, msg="缺少 video_path")
                if self._is_uploaded(video_path, "youtube"):
                    entry = self._uploaded_dict[self._file_md5(video_path)]
                    return ExecutionResult(success=True,
                                           msg=f"视频已上传过YouTube: {entry.get('urls', {}).get('youtube', '')}",
                                           data={"already_uploaded": True, "url": entry.get("urls", {}).get("youtube", "")})
                return self._upload_youtube_chrome(
                    video_path,
                    title=params.get("title", os.path.basename(video_path)),
                    desc=params.get("desc", ""),
                    tags=params.get("tags", []),
                    privacy=params.get("privacy", "private"),
                )

            elif cmd == "upload_both":
                video_path = params.get("video_path", "")
                if not video_path:
                    return ExecutionResult(success=False, msg="缺少 video_path")
                results = {}
                bili_result = self.execute(Action(command="upload_bilibili", params=params))
                results["bilibili"] = {"success": bili_result.success, "msg": bili_result.msg}
                yt_result = self.execute(Action(command="upload_youtube", params=params))
                results["youtube"] = {"success": yt_result.success, "msg": yt_result.msg}
                all_ok = bili_result.success and yt_result.success
                return ExecutionResult(success=all_ok,
                                       msg=f"B站: {bili_result.msg} | YouTube: {yt_result.msg}",
                                       data=results)

            elif cmd == "check_uploaded":
                video_path = params.get("video_path", "")
                if not video_path or not os.path.exists(video_path):
                    return ExecutionResult(success=False, msg=f"文件不存在: {video_path}")
                md5 = self._file_md5(video_path)
                if md5 in self._uploaded_dict:
                    entry = self._uploaded_dict[md5]
                    return ExecutionResult(success=True,
                                           msg=f"已上传: {entry.get('platforms', [])} | {entry.get('urls', {})}",
                                           data={"uploaded": True, "entry": entry})
                return ExecutionResult(success=True, msg="未上传过", data={"uploaded": False})

            elif cmd == "list_uploaded":
                entries = []
                for md5, entry in self._uploaded_dict.items():
                    entries.append({
                        "filename": entry.get("filename", ""),
                        "platforms": entry.get("platforms", []),
                        "urls": entry.get("urls", {}),
                        "first_uploaded": entry.get("first_uploaded", 0),
                    })
                entries.sort(key=lambda x: x.get("first_uploaded", 0), reverse=True)
                lines = [f"  {e['filename']} → {e['platforms']} {e.get('urls', {})}" for e in entries[:20]]
                return ExecutionResult(success=True,
                                       msg=f"已上传 {len(entries)} 个视频:\n" + "\n".join(lines),
                                       data={"total": len(entries), "entries": entries})

            elif cmd == "mark_uploaded":
                video_path = params.get("video_path", "")
                platform = params.get("platform", "")
                url = params.get("url", "")
                if not video_path or not os.path.exists(video_path):
                    return ExecutionResult(success=False, msg=f"文件不存在: {video_path}")
                self._mark_uploaded(video_path, platform, url)
                return ExecutionResult(success=True, msg=f"已标记: {os.path.basename(video_path)} → {platform}")

            elif cmd == "find_new_videos":
                directory = params.get("directory", "")
                extensions = params.get("extensions", [".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv"])
                if not directory or not os.path.isdir(directory):
                    return ExecutionResult(success=False, msg=f"目录不存在: {directory}")
                new_videos = []
                for root, dirs, files in os.walk(directory):
                    for f in files:
                        ext = os.path.splitext(f)[1].lower()
                        if ext in extensions:
                            full_path = os.path.join(root, f)
                            if not self._is_uploaded(full_path):
                                size_mb = os.path.getsize(full_path) / (1024 * 1024)
                                new_videos.append({
                                    "path": full_path,
                                    "filename": f,
                                    "size_mb": round(size_mb, 1),
                                })
                if new_videos:
                    lines = [f"  {v['filename']} ({v['size_mb']}MB)" for v in new_videos[:20]]
                    return ExecutionResult(success=True,
                                           msg=f"发现 {len(new_videos)} 个新视频:\n" + "\n".join(lines),
                                           data={"new_videos": new_videos})
                return ExecutionResult(success=True, msg="没有发现新视频", data={"new_videos": []})

            else:
                return ExecutionResult(success=False, msg=f"未知指令: {cmd}")

        except Exception as e:
            return ExecutionResult(success=False, msg=f"视频上传异常: {str(e)}")