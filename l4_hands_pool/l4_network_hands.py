import subprocess
import socket
import json
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "network_hands",
    "description": "网络探测器。IP/延迟/WiFi/DNS/端口/下载测试。纯本地。",
}


class Hands:
    def __init__(self):
        self.requires_memory_seal = False

    def get_instruction_dict(self) -> str:
        return """
        【网络探测器 指令字典】：
        1. "my_ip": {} — 本机局域网IP
        2. "public_ip": {} — 公网IP
        3. "ping": {"host": "8.8.8.8", "count": 4} — Ping测试
        4. "wifi_status": {} — WiFi连接状态
        5. "dns_lookup": {"host": "google.com"} — DNS解析
        6. "check_port": {"host": "127.0.0.1", "port": 8080} — 端口检测
        """

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        try:
            if cmd == "my_ip":
                hostname = socket.gethostname()
                ip = socket.gethostbyname(hostname)
                return ExecutionResult(success=True, msg=f"本机IP: {ip} ({hostname})",
                                       data={"ip": ip, "hostname": hostname})

            elif cmd == "public_ip":
                try:
                    import urllib.request
                    resp = urllib.request.urlopen("https://api.ipify.org?format=json", timeout=10)
                    data = json.loads(resp.read().decode())
                    return ExecutionResult(success=True, msg=f"公网IP: {data['ip']}",
                                           data={"public_ip": data['ip']})
                except Exception:
                    try:
                        resp = urllib.request.urlopen("https://httpbin.org/ip", timeout=10)
                        data = json.loads(resp.read().decode())
                        return ExecutionResult(success=True, msg=f"公网IP: {data['origin']}",
                                               data={"public_ip": data['origin']})
                    except Exception as e:
                        return ExecutionResult(success=False, msg=f"获取公网IP失败: {e}")

            elif cmd == "ping":
                host = params.get("host", "8.8.8.8")
                count = params.get("count", 4)
                result = subprocess.run(["ping", "-n", str(count), host],
                                        capture_output=True, text=True, timeout=count * 2 + 5)
                output = result.stdout
                times = []
                import re
                for m in re.finditer(r'time[=<]\s*(\d+)ms', output):
                    times.append(int(m.group(1)))
                if times:
                    avg = sum(times) / len(times)
                    return ExecutionResult(success=True,
                                           msg=f"Ping {host}: 平均 {avg:.0f}ms | 最小 {min(times)}ms | 最大 {max(times)}ms | {len(times)}/{count}",
                                           data={"host": host, "avg_ms": round(avg, 1),
                                                 "min_ms": min(times), "max_ms": max(times),
                                                 "received": len(times), "sent": count})
                return ExecutionResult(success=False, msg=f"Ping {host} 失败:\n{output[:200]}")

            elif cmd == "wifi_status":
                try:
                    result = subprocess.run(["netsh", "wlan", "show", "interfaces"],
                                            capture_output=True, text=True, timeout=10)
                    output = result.stdout
                    ssid = ""
                    signal = ""
                    state = ""
                    for line in output.split("\n"):
                        line = line.strip()
                        if "SSID" in line and "BSSID" not in line:
                            ssid = line.split(":")[-1].strip()
                        if "Signal" in line:
                            signal = line.split(":")[-1].strip()
                        if "State" in line:
                            state = line.split(":")[-1].strip()
                    if ssid:
                        return ExecutionResult(success=True,
                                               msg=f"WiFi: {ssid} | 信号 {signal} | {state}",
                                               data={"ssid": ssid, "signal": signal, "state": state})
                    return ExecutionResult(success=False, msg="未连接WiFi或无法获取状态")
                except Exception as e:
                    return ExecutionResult(success=False, msg=f"WiFi查询失败: {e}")

            elif cmd == "dns_lookup":
                host = params.get("host", "google.com")
                try:
                    ip = socket.gethostbyname(host)
                    return ExecutionResult(success=True, msg=f"{host} → {ip}",
                                           data={"host": host, "ip": ip})
                except socket.gaierror as e:
                    return ExecutionResult(success=False, msg=f"DNS解析失败: {e}")

            elif cmd == "check_port":
                host = params.get("host", "127.0.0.1")
                port = params.get("port", 8080)
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                try:
                    sock.connect((host, port))
                    sock.close()
                    return ExecutionResult(success=True, msg=f"端口 {host}:{port} 开放",
                                           data={"host": host, "port": port, "open": True})
                except (socket.timeout, ConnectionRefusedError, OSError):
                    return ExecutionResult(success=True, msg=f"端口 {host}:{port} 关闭",
                                           data={"host": host, "port": port, "open": False})

            else:
                return ExecutionResult(success=False, msg=f"未知指令: {cmd}")

        except Exception as e:
            return ExecutionResult(success=False, msg=f"网络探测异常: {str(e)}")