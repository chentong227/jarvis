import os
import re
import subprocess
import difflib
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "text_hands",
    "description": "文本/文件操作工具。读取/写入/追加/搜索/统计/格式化。纯本地。",
}


def _suggest_similar_paths(path: str, max_suggestions: int = 3) -> list:
    """[P0+20-β.2.5 hotfix / 2026-05-17] 文件不存在时，扫同目录下"名字相似"的候选项。

    Sir 23:58 实测 BUG：LLM 把 TODO.md 听成 'to do.txt' → text_hands.read 失败
    只返回纯文本 "文件不存在"，LLM 没足够信息向 Sir 反问。
    修法：失败时附 fuzzy 匹配建议，让 LLM 能反问 Sir 'Did you mean TODO.md?'。

    实现：difflib.get_close_matches 大小写不敏感 + 紧凑形式匹配
    ('to do.txt' → 'TODO.md' / 'todo.md')。
    """
    try:
        dir_path = os.path.dirname(path) or '.'
        target_name = os.path.basename(path).lower()
        if not target_name or not os.path.isdir(dir_path):
            return []
        try:
            entries = os.listdir(dir_path)
        except Exception:
            return []
        all_files = []
        for f in entries:
            try:
                if os.path.isfile(os.path.join(dir_path, f)):
                    all_files.append(f)
            except Exception:
                continue
        if not all_files:
            return []

        # 策略 1：difflib 相似度
        names_lower = [f.lower() for f in all_files]
        matches = list(difflib.get_close_matches(
            target_name, names_lower, n=max_suggestions, cutoff=0.4
        ))
        # 策略 2：紧凑匹配（"to do.txt" → "TODO.md" / "todo.md"）
        target_compact = re.sub(r'[\s_\-]+', '', target_name)
        target_stem = os.path.splitext(target_compact)[0]
        if target_stem and len(target_stem) >= 3:
            for f in all_files:
                f_compact = re.sub(r'[\s_\-]+', '', f.lower())
                f_stem = os.path.splitext(f_compact)[0]
                if f_stem and target_stem == f_stem:
                    if f.lower() not in matches:
                        matches.insert(0, f.lower())  # exact stem match 排前
                elif f_stem and target_stem in f_stem:
                    if f.lower() not in matches:
                        matches.append(f.lower())

        # 映射回原大小写文件名
        out = []
        seen = set()
        for m in matches:
            for f in all_files:
                if f.lower() == m and f not in seen:
                    out.append(os.path.join(dir_path, f))
                    seen.add(f)
                    break
        return out[:max_suggestions]
    except Exception:
        return []


def _file_not_found_msg(path: str) -> str:
    """[β.2.5 hotfix] 统一格式：'文件不存在: <path>。Did you mean: <s1>, <s2>?'
    让 LLM 看到这条 tool result 后能反问 Sir 'Did you mean TODO.md?' 而不是沉默。"""
    msg = f"文件不存在: {path}"
    sug = _suggest_similar_paths(path)
    if sug:
        msg += f"。Did you mean: {', '.join(sug)} ?"
    return msg


class Hands:
    def __init__(self):
        self.requires_memory_seal = False

    def get_instruction_dict(self) -> str:
        return """
        【文本/文件操作工具 指令字典】：
        1. "read": {"path": "文件路径", "lines": 50, "offset": 0} — 读取文件
        2. "write": {"path": "文件路径", "content": "内容"} — 写入文件(覆盖)
        3. "append": {"path": "文件路径", "content": "内容"} — 追加到文件末尾
        4. "search_in_file": {"path": "文件路径", "pattern": "关键词"} — 文件中搜索
        5. "count_lines": {"path": "文件路径"} — 统计行数
        6. "tail": {"path": "文件路径", "lines": 20} — 读取文件末尾N行
        7. "head": {"path": "文件路径", "lines": 20} — 读取文件开头N行
        8. "replace_in_file": {"path": "文件路径", "old": "旧文本", "new": "新文本"} — 替换文本
        """

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        try:
            if cmd == "read":
                path = params.get("path", "")
                lines = params.get("lines", 50)
                offset = params.get("offset", 0)
                if not path or not os.path.exists(path):
                    return ExecutionResult(success=False, msg=_file_not_found_msg(path))
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                    all_lines = content.split("\n")
                    selected = all_lines[offset:offset + lines]
                    result = "\n".join(selected)
                    return ExecutionResult(success=True,
                                           msg=f"读取 {path} (行 {offset+1}-{offset+len(selected)}/{len(all_lines)}):\n{result[:500]}",
                                           data={"content": result, "total_lines": len(all_lines),
                                                 "shown_lines": len(selected)})
                except UnicodeDecodeError:
                    with open(path, "r", encoding="gbk", errors="replace") as f:
                        content = f.read()
                    all_lines = content.split("\n")
                    selected = all_lines[offset:offset + lines]
                    result = "\n".join(selected)
                    return ExecutionResult(success=True,
                                           msg=f"读取 {path} (行 {offset+1}-{offset+len(selected)}/{len(all_lines)}):\n{result[:500]}",
                                           data={"content": result, "total_lines": len(all_lines),
                                                 "shown_lines": len(selected)})

            elif cmd == "write":
                path = params.get("path", "")
                content = params.get("content", "")
                if not path:
                    return ExecutionResult(success=False, msg="缺少 path 参数")
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                return ExecutionResult(success=True, msg=f"已写入 {path} ({len(content)} 字符)")

            elif cmd == "append":
                path = params.get("path", "")
                content = params.get("content", "")
                if not path:
                    return ExecutionResult(success=False, msg="缺少 path 参数")
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(content)
                return ExecutionResult(success=True, msg=f"已追加 {path} (+{len(content)} 字符)")

            elif cmd == "search_in_file":
                path = params.get("path", "")
                pattern = params.get("pattern", "")
                if not path or not os.path.exists(path):
                    return ExecutionResult(success=False, msg=_file_not_found_msg(path))
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                except UnicodeDecodeError:
                    with open(path, "r", encoding="gbk", errors="replace") as f:
                        lines = f.readlines()
                matches = []
                for i, line in enumerate(lines, 1):
                    if pattern.lower() in line.lower():
                        matches.append(f"  L{i}: {line.rstrip()[:120]}")
                if matches:
                    return ExecutionResult(success=True,
                                           msg=f"在 {path} 中找到 {len(matches)} 处匹配:\n" + "\n".join(matches[:20]),
                                           data={"matches": len(matches), "lines": [m.strip() for m in matches]})
                return ExecutionResult(success=False, msg=f"未找到: {pattern}")

            elif cmd == "count_lines":
                path = params.get("path", "")
                if not path or not os.path.exists(path):
                    return ExecutionResult(success=False, msg=_file_not_found_msg(path))
                count = 0
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        for _ in f:
                            count += 1
                except UnicodeDecodeError:
                    with open(path, "r", encoding="gbk", errors="replace") as f:
                        for _ in f:
                            count += 1
                size = os.path.getsize(path)
                return ExecutionResult(success=True, msg=f"{path}: {count} 行, {size} 字节",
                                       data={"lines": count, "size_bytes": size})

            elif cmd == "tail":
                path = params.get("path", "")
                n = params.get("lines", 20)
                if not path or not os.path.exists(path):
                    return ExecutionResult(success=False, msg=_file_not_found_msg(path))
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                except UnicodeDecodeError:
                    with open(path, "r", encoding="gbk", errors="replace") as f:
                        lines = f.readlines()
                tail_lines = lines[-n:] if len(lines) > n else lines
                result = "".join(tail_lines)
                return ExecutionResult(success=True,
                                       msg=f"{path} 末尾 {len(tail_lines)} 行:\n{result[:500]}",
                                       data={"content": result, "lines": len(tail_lines)})

            elif cmd == "head":
                path = params.get("path", "")
                n = params.get("lines", 20)
                if not path or not os.path.exists(path):
                    return ExecutionResult(success=False, msg=_file_not_found_msg(path))
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                except UnicodeDecodeError:
                    with open(path, "r", encoding="gbk", errors="replace") as f:
                        lines = f.readlines()
                head_lines = lines[:n]
                result = "".join(head_lines)
                return ExecutionResult(success=True,
                                       msg=f"{path} 开头 {len(head_lines)} 行:\n{result[:500]}",
                                       data={"content": result, "lines": len(head_lines)})

            elif cmd == "replace_in_file":
                path = params.get("path", "")
                old = params.get("old", "")
                new = params.get("new", "")
                if not path or not os.path.exists(path):
                    return ExecutionResult(success=False, msg=_file_not_found_msg(path))
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                except UnicodeDecodeError:
                    with open(path, "r", encoding="gbk", errors="replace") as f:
                        content = f.read()
                count = content.count(old)
                if count == 0:
                    return ExecutionResult(success=False, msg=f"未找到: {old}")
                new_content = content.replace(old, new)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                return ExecutionResult(success=True, msg=f"已替换 {count} 处: {old} → {new}")

            else:
                return ExecutionResult(success=False, msg=f"未知指令: {cmd}")

        except Exception as e:
            return ExecutionResult(success=False, msg=f"文本操作异常: {str(e)}")