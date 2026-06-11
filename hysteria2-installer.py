#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hysteria2 一键安装脚本
功能：安装 Hysteria2 服务端，自动生成所有主流客户端配置文件
支持系统：Debian / Ubuntu / CentOS / Rocky Linux
运行方式：python3 hysteria2-installer.py（需要 root 权限）
"""

import subprocess
import os
import sys
import json
import random
import string
import struct
import shutil
import urllib.request
import urllib.parse
import platform
import time

# ============================================================
# 常量
# ============================================================

HYSTERIA_BIN = "/usr/local/bin/hysteria"
HYSTERIA_CONFIG_DIR = "/etc/hysteria"
HYSTERIA_CONFIG = os.path.join(HYSTERIA_CONFIG_DIR, "config.yaml")
HYSTERIA_SERVICE = "/etc/systemd/system/hysteria-server.service"
OUTPUT_DIR_NAME = "hysteria2-client-configs"
MASQUERADE_DIR = "/var/www/masquerade"

GITHUB_API = "https://api.github.com/repos/apernet/hysteria/releases/latest"
GITHUB_MIRRORS = [
    "https://github.com",
    "https://mirror.ghproxy.com/https://github.com",
]

ARCH_MAP = {
    "x86_64": "amd64",
    "aarch64": "arm64",
    "armv7l": "arm",
    "armv6l": "arm",
    "s390x": "s390x",
    "i386": "386",
    "i686": "386",
}

COLOR_RED = "\033[91m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_CYAN = "\033[96m"
COLOR_BOLD = "\033[1m"
COLOR_RESET = "\033[0m"


# ============================================================
# 工具函数
# ============================================================

def print_color(msg, color=COLOR_RESET):
    print("{}{}{}".format(color, msg, COLOR_RESET))


def print_success(msg):
    print_color("[✓] {}".format(msg), COLOR_GREEN)


def print_error(msg):
    print_color("[✗] {}".format(msg), COLOR_RED)


def print_warn(msg):
    print_color("[!] {}".format(msg), COLOR_YELLOW)


def print_info(msg):
    print_color("[*] {}".format(msg), COLOR_CYAN)


def print_step(step, total, msg):
    print_color("[{}/{}] {}".format(step, total, msg), COLOR_BOLD)


def run_cmd(cmd, check=True, capture=False):
    """执行 shell 命令"""
    if capture:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError("命令执行失败: {}\n{}".format(cmd, result.stderr))
        return result
    else:
        result = subprocess.run(cmd, shell=True)
        if check and result.returncode != 0:
            raise RuntimeError("命令执行失败: {}".format(cmd))
        return result


def ask_input(prompt, default=""):
    """交互式输入"""
    if default:
        raw = input("{} (默认: {}): ".format(prompt, default)).strip()
    else:
        raw = input("{}: ".format(prompt)).strip()
    return raw if raw else default


def ask_choice(prompt, choices, default=1):
    """交互式选择"""
    for i, choice in enumerate(choices, 1):
        print("  {}) {}".format(i, choice))
    while True:
        raw = input("{} (默认: {}): ".format(prompt, default)).strip()
        if not raw:
            return default
        try:
            idx = int(raw)
            if 1 <= idx <= len(choices):
                return idx
        except ValueError:
            pass
        print_warn("无效选择，请重新输入")


def ask_yes_no(prompt, default=False):
    """交互式是/否"""
    default_str = "Y/n" if default else "y/N"
    raw = input("{} ({}): ".format(prompt, default_str)).strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "是")


# ============================================================
# 系统检测模块
# ============================================================

def print_banner():
    banner = """
{}╔══════════════════════════════════════════════╗
║        Hysteria2 一键安装脚本 v1.0           ║
║     安装完成自动生成所有客户端配置文件        ║
╚══════════════════════════════════════════════╝{}
""".format(COLOR_CYAN, COLOR_RESET)
    print(banner)


def check_root():
    """检查是否 root 用户"""
    if os.geteuid() != 0:
        print_error("请使用 root 用户运行此脚本")
        sys.exit(1)


def detect_os():
    """检测 Linux 发行版"""
    try:
        with open("/etc/os-release") as f:
            lines = f.read()
        info = {}
        for line in lines.strip().split("\n"):
            if "=" in line:
                key, value = line.split("=", 1)
                info[key] = value.strip('"')
        distro_id = info.get("ID", "").lower()
        version = info.get("VERSION_ID", "")
        if distro_id in ("debian", "ubuntu", "linuxmint", "pop"):
            return "debian", version
        elif distro_id in ("centos", "rhel", "rocky", "almalinux", "fedora"):
            return "centos", version
        else:
            print_warn("未识别的发行版: {}，将按 Debian 系处理".format(distro_id))
            return "debian", version
    except Exception:
        print_warn("无法检测系统版本，将按 Debian 系处理")
        return "debian", ""


def detect_arch():
    """检测 CPU 架构，返回 Hysteria2 下载后缀"""
    machine = platform.machine().lower()
    arch = ARCH_MAP.get(machine)
    if not arch:
        print_error("不支持的 CPU 架构: {}".format(machine))
        sys.exit(1)
    return arch


def get_public_ip():
    """获取服务器公网 IPv4 和 IPv6"""
    ipv4 = ""
    ipv6 = ""
    # IPv4
    for url in ["https://api.ipify.org", "https://ifconfig.me/ip", "https://ip.sb"]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.88.1"})
            with urllib.request.urlopen(req, timeout=10) as r:
                ipv4 = r.read().decode().strip()
            if ipv4:
                break
        except Exception:
            continue
    # IPv6
    for url in ["https://api6.ipify.org", "https://ifconfig.co/ip"]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.88.1"})
            with urllib.request.urlopen(req, timeout=10) as r:
                ipv6 = r.read().decode().strip()
            if ipv6:
                break
        except Exception:
            continue
    return ipv4, ipv6


def check_dependencies():
    """检查必要工具"""
    required = ["openssl", "curl", "systemctl"]
    missing = []
    for tool in required:
        if not shutil.which(tool):
            missing.append(tool)
    if missing:
        print_warn("缺少工具: {}".format(", ".join(missing)))
        distro, _ = detect_os()
        if distro == "debian":
            print_info("正在安装缺失工具...")
            run_cmd("apt-get update -qq && apt-get install -y -qq {}".format(" ".join(missing)), check=False)
        elif distro == "centos":
            print_info("正在安装缺失工具...")
            run_cmd("yum install -y {}".format(" ".join(missing)), check=False)


def detect_existing_hysteria():
    """检查是否已安装 Hysteria2"""
    if os.path.exists(HYSTERIA_BIN):
        try:
            result = run_cmd("systemctl is-active hysteria-server", check=False, capture=True)
            active = result.returncode == 0
        except Exception:
            active = False
        return True, active
    return False, False


# ============================================================
# 安装管理模块
# ============================================================

def uninstall_hysteria():
    """卸载 Hysteria2"""
    print_info("正在卸载 Hysteria2...")
    run_cmd("systemctl stop hysteria-server", check=False)
    run_cmd("systemctl disable hysteria-server", check=False)
    if os.path.exists(HYSTERIA_SERVICE):
        os.remove(HYSTERIA_SERVICE)
    if os.path.exists(HYSTERIA_BIN):
        os.remove(HYSTERIA_BIN)
    run_cmd("systemctl daemon-reload", check=False)
    print_success("Hysteria2 已卸载")


def handle_existing():
    """处理已有安装"""
    installed, active = detect_existing_hysteria()
    if not installed:
        return
    status_str = "运行中" if active else "已停止"
    print_warn("检测到已安装 Hysteria2 ({})".format(status_str))
    choice = ask_choice("请选择操作", ["卸载", "重新安装（覆盖）", "取消退出"], default=2)
    if choice == 1:
        uninstall_hysteria()
        sys.exit(0)
    elif choice == 2:
        print_info("将覆盖安装...")
    else:
        print_info("已取消")
        sys.exit(0)


def get_latest_version():
    """获取 Hysteria2 最新版本号"""
    print_info("正在获取 Hysteria2 最新版本...")
    try:
        req = urllib.request.Request(GITHUB_API, headers={"User-Agent": "hysteria2-installer"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        version = data.get("tag_name", "")
        if version:
            print_success("最新版本: {}".format(version))
            return version
    except Exception:
        pass
    # 备用：使用官方安装脚本
    print_warn("无法从 GitHub API 获取版本，尝试使用官方安装脚本...")
    return None


def download_hysteria(version, arch):
    """下载 Hysteria2 二进制文件"""
    if version:
        # 直接从 GitHub 下载指定版本
        filename = "hysteria-linux-{}".format(arch)
        for mirror in GITHUB_MIRRORS:
            url = "{}/apernet/hysteria/releases/download/{}/{}".format(mirror, version, filename)
            print_info("正在从 {} 下载...".format(url))
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "curl/7.88.1"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = r.read()
                tmp_path = "/tmp/hysteria"
                with open(tmp_path, "wb") as f:
                    f.write(data)
                os.chmod(tmp_path, 0o755)
                shutil.move(tmp_path, HYSTERIA_BIN)
                print_success("下载完成: {}".format(version))
                return True
            except Exception as e:
                print_warn("下载失败: {}".format(str(e)))
                continue
    # 降级方案：使用官方安装脚本
    print_info("使用官方安装脚本安装...")
    try:
        run_cmd('bash -c "curl -fsSL https://get.hy2.sh/ | bash"', check=True)
        print_success("通过官方脚本安装完成")
        return True
    except Exception as e:
        print_error("安装失败: {}".format(str(e)))
        return False


def install_binary():
    """验证安装"""
    if not os.path.exists(HYSTERIA_BIN):
        print_error("Hysteria2 二进制文件未找到")
        sys.exit(1)
    try:
        result = run_cmd("{} version".format(HYSTERIA_BIN), check=True, capture=True)
        version_info = result.stdout.strip()
        print_success("安装验证: {}".format(version_info.split("\n")[0] if version_info else "OK"))
    except Exception:
        print_warn("无法获取版本信息，但文件已存在，继续安装...")


# ============================================================
# 交互式配置模块
# ============================================================

def generate_password(length=16):
    """生成强密码"""
    chars = string.ascii_letters + string.digits + "!@#$%&*"
    return "".join(random.choice(chars) for _ in range(length))


def generate_port():
    """生成随机高位端口"""
    return random.randint(30000, 50000)


def collect_certificate_config():
    """收集证书配置：有域名走 ACME，无域名走自签。"""
    print()
    print_color("[3/5] 证书模式", COLOR_BOLD)
    domain = ask_input("  请输入你的域名 (留空则使用无域名自签证书)", "")
    if domain:
        email = ask_input("  请输入邮箱 (用于证书通知)", "admin@{}".format(domain))
        return {
            "cert_mode": "acme",
            "domain": domain,
            "email": email,
        }

    print_info("未输入域名，将使用自签证书；客户端会自动启用 skip-cert-verify")
    return {
        "cert_mode": "self-signed",
        "domain": "",
        "email": "",
    }


def get_static_masquerade_choices():
    """静态伪装模板选项。"""
    return [
        ("API 文档页面（无域名时推荐，像 API 网关）", "api-doc"),
        ("404 Not Found（看起来像废弃服务）", "404"),
    ]


def get_acme_custom_port_notice(port):
    """ACME 与自定义服务端口的提示。"""
    return (
        "已选择 ACME 证书。当前自定义端口 {}/udp 可以继续使用；"
        "443/udp 只是更像普通 HTTP/3 网站的建议。"
        "ACME 证书验证仍需域名解析正确，并确保 80/443 验证端口可达。"
    ).format(port)


def interactive_config(ipv4, ipv6):
    """交互式配置收集"""
    print()
    print_color("═══ Hysteria2 安装配置 ═══", COLOR_BOLD)
    print()

    # 1. 端口
    default_port = generate_port()
    port_str = ask_input("[1/5] 监听端口", str(default_port))
    try:
        port = int(port_str)
    except ValueError:
        port = default_port
        print_info("端口格式错误，使用默认: {}".format(port))

    # 2. 密码
    default_pwd = generate_password()
    password = ask_input("[2/5] 认证密码 (留空自动生成)", "")
    if not password:
        password = default_pwd
        print_info("已生成密码: {}".format(password))

    # 3. 证书模式
    cert_config = collect_certificate_config()
    cert_mode = cert_config["cert_mode"]
    domain = cert_config["domain"]
    email = cert_config["email"]
    if cert_mode == "acme" and port != 443:
        print_warn(get_acme_custom_port_notice(port))
    elif cert_mode == "self-signed":
        print_info("无域名模式建议使用静态 API 文档或 404 页面；这是当前脚本的默认伪装方式。")

    # 4. 端口跳跃
    print()
    port_hopping = ask_yes_no("[4/5] 是否开启端口跳跃", default=False)
    port_hopping_range = ""
    if port_hopping:
        port_hopping_range = ask_input("  端口跳跃范围", "20000-50000")

    # 5. 伪装方式
    print()
    print_color("[5/5] 网站伪装方式", COLOR_BOLD)
    masquerade_choice = ask_choice("  选择伪装方式", [
        "反向代理真实网站（默认 bing.com）",
        "静态伪装页面（高可信模板，无需 Nginx）",
        "不伪装",
    ], default=2)

    masquerade_mode = "proxy"
    masquerade_url = "https://bing.com"
    masquerade_template = ""

    if masquerade_choice == 1:
        masquerade_mode = "proxy"
        masquerade_url = ask_input("  伪装网站 URL", "https://bing.com")
    elif masquerade_choice == 2:
        masquerade_mode = "string"
        static_choices = get_static_masquerade_choices()
        template_choice = ask_choice("  选择伪装模板", [label for label, _name in static_choices], default=1)
        template_names = [name for _label, name in static_choices]
        masquerade_template = template_names[template_choice - 1]
    else:
        masquerade_mode = "none"

    config = {
        "port": port,
        "password": password,
        "cert_mode": cert_mode,
        "domain": domain,
        "email": email,
        "masquerade_mode": masquerade_mode,
        "masquerade_url": masquerade_url,
        "masquerade_template": masquerade_template,
        "port_hopping": port_hopping,
        "port_hopping_range": port_hopping_range,
    }

    # 确认
    print()
    print_color("═══ 配置确认 ═══", COLOR_BOLD)
    print("  端口:       {}".format(port))
    print("  密码:       {}".format(password))
    print("  证书:       {}".format("ACME ({})".format(domain) if cert_mode == "acme" else "自签证书"))
    print("  端口跳跃:   {}".format("是 ({})".format(port_hopping_range) if port_hopping else "否"))
    if masquerade_mode == "proxy":
        print("  伪装:       反向代理 ({})".format(masquerade_url))
    elif masquerade_mode == "string":
        template_labels = {"api-doc": "API 文档", "404": "404 页面"}
        print("  伪装:       静态页面 ({})".format(template_labels.get(masquerade_template, masquerade_template)))
    else:
        print("  伪装:       不伪装")
    print()

    if not ask_yes_no("确认以上配置", default=True):
        print_info("已取消")
        sys.exit(0)

    return config


# ============================================================
# 证书处理模块
# ============================================================

def generate_self_signed_cert(ip):
    """生成自签证书"""
    os.makedirs(HYSTERIA_CONFIG_DIR, exist_ok=True)
    cert_path = os.path.join(HYSTERIA_CONFIG_DIR, "self-signed.crt")
    key_path = os.path.join(HYSTERIA_CONFIG_DIR, "self-signed.key")

    print_info("正在生成自签证书...")

    # 用 openssl 生成
    cmd = (
        'openssl req -x509 -nodes -newkey ec -pkeyopt ec_paramgen_curve:P-256 '
        '-sha256 -days 36500 '
        '-subj "/CN=bing.com" '
        '-addext "subjectAltName=IP:{}" '
        '-out {} -keyout {}'
    ).format(ip, cert_path, key_path)

    try:
        run_cmd(cmd, check=True)
        print_success("自签证书已生成")
        return cert_path, key_path
    except Exception:
        # 旧版 openssl 不支持 -addext，使用配置文件方式
        print_warn("尝试备用证书生成方式...")
        return _generate_cert_fallback(ip, cert_path, key_path)


def _generate_cert_fallback(ip, cert_path, key_path):
    """旧版 openssl 证书生成"""
    config_content = (
        "[req]\n"
        "distinguished_name=req\n"
        "x509_extensions=v3_req\n"
        "prompt=no\n"
        "[v3_req]\n"
        "subjectAltName=IP:{}\n"
    ).format(ip)

    config_file = "/tmp/openssl-san.cnf"
    with open(config_file, "w") as f:
        f.write(config_content)

    cmd = (
        'openssl req -x509 -nodes -newkey ec -pkeyopt ec_paramgen_curve:P-256 '
        '-sha256 -days 36500 -subj "/CN=bing.com" '
        '-extensions v3_req -config {} '
        '-out {} -keyout {}'
    ).format(config_file, cert_path, key_path)

    run_cmd(cmd, check=True)
    os.remove(config_file)
    print_success("自签证书已生成（备用方式）")
    return cert_path, key_path


# ============================================================
# 伪装模板模块
# ============================================================

def get_masquerade_html(template_name):
    """获取伪装页面 HTML 模板"""
    templates = {
        "api-doc": _template_api_doc(),
        "404": _template_404(),
    }
    return templates.get(template_name, _template_api_doc())


def _template_api_doc():
    """API 文档页面"""
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>API Documentation</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f8f9fa;color:#333;line-height:1.6}
.header{background:#fff;border-bottom:1px solid #e1e4e8;padding:20px 40px}
.header h1{font-size:24px;color:#0366d6}
.header p{color:#586069;margin-top:4px}
.container{display:flex;max-width:1200px;margin:0 auto;padding:20px}
.sidebar{width:260px;flex-shrink:0;padding-right:30px}
.sidebar a{display:block;padding:8px 16px;color:#0366d6;text-decoration:none;border-radius:6px;margin-bottom:2px;font-size:14px}
.sidebar a:hover{background:#f1f8ff}
.sidebar a.active{background:#0366d6;color:#fff}
.main{flex:1}
.endpoint{background:#fff;border:1px solid #e1e4e8;border-radius:6px;padding:20px;margin-bottom:16px}
.method{display:inline-block;padding:3px 10px;border-radius:3px;font-size:12px;font-weight:600;color:#fff;margin-right:10px}
.get{background:#61affe}.post{background:#49cc90}.put{background:#fca130}.delete{background:#f93e3e}
.endpoint h3{font-size:16px;margin-bottom:8px}
.endpoint p{color:#586069;font-size:14px}
.endpoint code{background:#f6f8fa;padding:2px 6px;border-radius:3px;font-size:13px;font-family:SFMono-Regular,Consolas,'Liberation Mono',Menlo,monospace}
.status{display:inline-block;padding:2px 8px;border-radius:3px;font-size:12px;margin-top:8px}
.status-ok{background:#dcffe4;color:#22863a}
.version{color:#586069;font-size:13px}
</style>
</head>
<body>
<div class="header">
<h1>API Documentation</h1>
<p class="version">v2.4.1 &middot; RESTful API Reference</p>
</div>
<div class="container">
<div class="sidebar">
<a class="active" href="#">Getting Started</a>
<a href="#">Authentication</a>
<a href="#">Users</a>
<a href="#">Products</a>
<a href="#">Orders</a>
<a href="#">Webhooks</a>
<a href="#">Rate Limits</a>
<a href="#">Error Codes</a>
</div>
<div class="main">
<div class="endpoint">
<p>This API provides programmatic access to manage resources. All requests must be authenticated using an API key passed in the <code>Authorization</code> header.</p>
</div>
<div class="endpoint">
<h3><span class="method get">GET</span> /api/v2/users</h3>
<p>Retrieve a paginated list of users. Supports filtering by role, status, and registration date.</p>
<code>Authorization: Bearer &lt;api_key&gt;</code>
<br><span class="status status-ok">200 OK</span>
</div>
<div class="endpoint">
<h3><span class="method post">POST</span> /api/v2/users</h3>
<p>Create a new user account. Requires admin privileges. Returns the created user object.</p>
<code>Content-Type: application/json</code>
<br><span class="status status-ok">201 Created</span>
</div>
<div class="endpoint">
<h3><span class="method get">GET</span> /api/v2/products</h3>
<p>List all available products with pricing and inventory information. Results are paginated with 25 items per page.</p>
<code>?page=1&amp;limit=25&amp;category=electronics</code>
<br><span class="status status-ok">200 OK</span>
</div>
<div class="endpoint">
<h3><span class="method put">PUT</span> /api/v2/products/:id</h3>
<p>Update product information. Supports partial updates via JSON merge patch format.</p>
<code>Content-Type: application/merge-patch+json</code>
<br><span class="status status-ok">200 OK</span>
</div>
<div class="endpoint">
<h3><span class="method delete">DELETE</span> /api/v2/orders/:id</h3>
<p>Cancel an existing order. Only orders in pending status can be cancelled.</p>
<code>Authorization: Bearer &lt;api_key&gt;</code>
<br><span class="status status-ok">204 No Content</span>
</div>
</div>
</div>
</body>
</html>"""


def _template_404():
    """404 Not Found 页面"""
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>404 Not Found</title>
<style>
body{background:#fff;color:#666;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;text-align:center;padding-top:15%}
h1{font-size:72px;color:#ccc;margin-bottom:10px}
p{font-size:18px;color:#999}
</style>
</head>
<body>
<h1>404</h1>
<p>The page you requested was not found on this server.</p>
</body>
</html>"""


# ============================================================
# 服务端配置生成模块
# ============================================================

def generate_server_config(config, cert_path=None, key_path=None):
    """生成服务端 config.yaml"""
    os.makedirs(HYSTERIA_CONFIG_DIR, exist_ok=True)

    # 监听地址
    listen = ":{}".format(config["port"])
    if config["port_hopping"] and config["port_hopping_range"]:
        listen = ":{},{}".format(config["port"], config["port_hopping_range"])

    # TLS 配置
    if config["cert_mode"] == "self-signed":
        tls_section = (
            "tls:\n"
            "  cert: {}\n"
            "  key: {}"
        ).format(cert_path, key_path)
    else:
        # ACME
        acme_section = (
            "acme:\n"
            "  domains:\n"
            "    - {}\n"
            "  email: {}"
        ).format(config["domain"], config["email"] if config["email"] else "admin@{}".format(config["domain"]))
        tls_section = acme_section

    # 伪装配置
    if config.get("masquerade_mode") == "string":
        html = get_masquerade_html(config.get("masquerade_template", "api-doc"))
        html_file = os.path.join(MASQUERADE_DIR, "index.html")
        os.makedirs(MASQUERADE_DIR, exist_ok=True)
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html)
        masquerade_section = (
            "masquerade:\n"
            "  type: file\n"
            "  file:\n"
            "    dir: {dir}"
        ).format(dir=MASQUERADE_DIR)
        print_info("静态伪装页面已保存至: {}".format(html_file))
        print_info("Hysteria2 将从 {} 提供伪装页面".format(MASQUERADE_DIR))
    elif config.get("masquerade_mode") == "proxy":
        masquerade_section = (
            "masquerade:\n"
            "  type: proxy\n"
            "  proxy:\n"
            "    url: {masq}\n"
            "    rewriteHost: true"
        ).format(masq=config.get("masquerade_url", "https://bing.com"))
    else:
        masquerade_section = ""

    # 完整配置
    yaml_content = (
        "listen: {listen}\n"
        "\n"
        "{tls}\n"
        "\n"
        "auth:\n"
        "  type: password\n"
        "  password: {password}\n"
        "\n"
        "{masquerade}\n"
        "\n"
        "ignoreClientBandwidth: false\n"
    ).format(
        listen=listen,
        tls=tls_section,
        password=config["password"],
        masquerade=masquerade_section,
    )

    with open(HYSTERIA_CONFIG, "w") as f:
        f.write(yaml_content)

    print_success("服务端配置已生成: {}".format(HYSTERIA_CONFIG))


def setup_systemd():
    """配置 systemd 服务"""
    service_content = (
        "[Unit]\n"
        "Description=Hysteria 2 Server\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "ExecStart={} server -c {}\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "LimitNOFILE=infinity\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    ).format(HYSTERIA_BIN, HYSTERIA_CONFIG)

    with open(HYSTERIA_SERVICE, "w") as f:
        f.write(service_content)

    run_cmd("systemctl daemon-reload", check=True)
    run_cmd("systemctl enable hysteria-server", check=True)
    run_cmd("systemctl restart hysteria-server", check=True)

    # 检查状态
    time.sleep(1)
    result = run_cmd("systemctl is-active hysteria-server", check=False, capture=True)
    if result.returncode == 0:
        print_success("Hysteria2 服务已启动")
    else:
        print_error("服务启动失败，查看日志:")
        run_cmd("journalctl -u hysteria-server -n 20 --no-pager", check=False)


# ============================================================
# 防火墙模块
# ============================================================

def configure_firewall(port, hopping_range=""):
    """配置防火墙放行 UDP 端口"""
    print_info("正在配置防火墙...")

    # iptables（通用）
    try:
        run_cmd("iptables -C INPUT -p udp --dport {} -j ACCEPT 2>/dev/null || iptables -I INPUT -p udp --dport {} -j ACCEPT".format(port, port), check=False)
        if hopping_range:
            run_cmd("iptables -I INPUT -p udp -m udp --dport {} -j ACCEPT".format(hopping_range.replace("-", ":")), check=False)
        print_success("iptables 规则已添加 (UDP:{})".format(port))
    except Exception:
        print_warn("iptables 配置失败，请手动放行 UDP 端口 {}".format(port))

    # ufw（Debian/Ubuntu）
    if shutil.which("ufw"):
        try:
            run_cmd("ufw allow {}/udp".format(port), check=False)
            if hopping_range:
                run_cmd("ufw allow {}/udp".format(hopping_range.replace("-", ":")), check=False)
            print_success("ufw 规则已添加 (UDP:{})".format(port))
        except Exception:
            pass

    # firewalld（CentOS/Rocky）
    if shutil.which("firewall-cmd"):
        try:
            run_cmd("firewall-cmd --permanent --add-port={}/udp".format(port), check=False)
            if hopping_range:
                run_cmd("firewall-cmd --permanent --add-port={}/udp".format(hopping_range.replace("-", ":")), check=False)
            run_cmd("firewall-cmd --reload", check=False)
            print_success("firewalld 规则已添加 (UDP:{})".format(port))
        except Exception:
            pass


# ============================================================
# 客户端配置生成模块
# ============================================================

def build_context(config, ipv4, ipv6, cert_path, key_path):
    """构建配置上下文"""
    is_self_signed = config["cert_mode"] == "self-signed"
    sni = config["domain"] if config["cert_mode"] == "acme" else "bing.com"
    server_ip = ipv4 or ipv6 or "YOUR_SERVER_IP"

    return {
        "server_ip": server_ip,
        "ipv4": ipv4,
        "ipv6": ipv6,
        "port": config["port"],
        "password": config["password"],
        "sni": sni,
        "skip_cert_verify": is_self_signed,
        "is_self_signed": is_self_signed,
        "cert_mode": config["cert_mode"],
        "domain": config["domain"],
        "port_hopping": config["port_hopping"],
        "port_hopping_range": config["port_hopping_range"],
        "masquerade_mode": config.get("masquerade_mode", "proxy"),
        "masquerade_url": config.get("masquerade_url", "https://bing.com"),
        "masquerade_template": config.get("masquerade_template", ""),
        "cert_path": cert_path or "",
        "key_path": key_path or "",
    }


# --- 订阅链接 ---

def gen_subscription_link(ctx):
    """生成 hysteria2:// URI"""
    params = []
    if ctx["skip_cert_verify"]:
        params.append("insecure=1")
    else:
        params.append("insecure=0")
    params.append("sni={}".format(ctx["sni"]))

    port_part = str(ctx["port"])
    if ctx["port_hopping"] and ctx["port_hopping_range"]:
        port_part = "{},{}".format(ctx["port"], ctx["port_hopping_range"])

    encoded_pwd = urllib.parse.quote(ctx["password"], safe="")

    uri = "hysteria2://{password}@{ip}:{port}?{params}#Hysteria2-Server".format(
        password=encoded_pwd,
        ip=ctx["server_ip"],
        port=port_part,
        params="&".join(params),
    )
    return uri


# --- 服务器信息 ---

def gen_server_info(ctx):
    """生成服务器信息摘要"""
    uri = gen_subscription_link(ctx)

    # 伪装信息
    masq_mode = ctx.get("masquerade_mode", "proxy")
    if masq_mode == "string":
        template_labels = {"api-doc": "API 文档", "404": "404 页面"}
        masq_info = "静态页面 ({})".format(template_labels.get(ctx.get("masquerade_template", ""), "未知"))
    elif masq_mode == "proxy":
        masq_info = "反向代理 ({})".format(ctx.get("masquerade_url", ""))
    else:
        masq_info = "未启用"

    return (
        "========================================\n"
        "  Hysteria2 服务器信息\n"
        "========================================\n"
        "\n"
        "协议类型:     Hysteria2\n"
        "服务器 IP:    {ip}\n"
        "IPv6:         {ipv6}\n"
        "端口:         {port}\n"
        "密码:         {password}\n"
        "SNI:          {sni}\n"
        "自签证书:     {self_signed}\n"
        "端口跳跃:     {hopping}\n"
        "网站伪装:     {masq}\n"
        "\n"
        "安装路径:     {bin}\n"
        "配置路径:     {config}\n"
        "{cert_info}"
        "\n"
        "订阅链接:\n"
        "{uri}\n"
        "\n"
        "========================================\n"
        "  管理命令\n"
        "========================================\n"
        "\n"
        "  启动:   systemctl start hysteria-server\n"
        "  停止:   systemctl stop hysteria-server\n"
        "  重启:   systemctl restart hysteria-server\n"
        "  状态:   systemctl status hysteria-server\n"
        "  日志:   journalctl -u hysteria-server -f\n"
        "  卸载:   python3 hysteria2-installer.py --uninstall\n"
        "\n"
    ).format(
        ip=ctx["server_ip"],
        ipv6=ctx["ipv6"] or "无",
        port=ctx["port"],
        password=ctx["password"],
        sni=ctx["sni"],
        self_signed="是" if ctx["is_self_signed"] else "否",
        hopping="是 ({})".format(ctx["port_hopping_range"]) if ctx["port_hopping"] else "否",
        masq=masq_info,
        bin=HYSTERIA_BIN,
        config=HYSTERIA_CONFIG,
        cert_info=(
            "证书路径:     {}\n密钥路径:     {}".format(ctx["cert_path"], ctx["key_path"])
            if ctx["is_self_signed"]
            else "域名:         {}".format(ctx["domain"])
        ),
        uri=uri,
    )


# --- Clash Meta / Clash Verge Rev ---

def gen_clash_config(ctx):
    """生成 Clash Meta 完整配置"""
    skip_cert = "true" if ctx["skip_cert_verify"] else "false"

    hopping_lines = ""
    if ctx["port_hopping"] and ctx["port_hopping_range"]:
        hopping_lines = (
            '    ports: "{}"\n'
            "    hop-interval: 30\n"
        ).format(ctx["port_hopping_range"])

    return (
        "mixed-port: 7890\n"
        "allow-lan: false\n"
        "mode: rule\n"
        "log-level: info\n"
        "\n"
        "sniffer:\n"
        "  enable: true\n"
        "  sniffing:\n"
        "    - tls\n"
        "    - http\n"
        "\n"
        "dns:\n"
        "  enable: true\n"
        "  enhanced-mode: fake-ip\n"
        "  nameserver:\n"
        "    - https://dns.alidns.com/dns-query\n"
        "    - https://doh.pub/dns-query\n"
        "  fallback:\n"
        "    - https://1.1.1.1/dns-query\n"
        "    - https://dns.google/dns-query\n"
        "  fallback-filter:\n"
        "    geoip: true\n"
        "    geoip-code: CN\n"
        "\n"
        "proxies:\n"
        "  - name: \"Hysteria2\"\n"
        "    type: hysteria2\n"
        "    server: {server}\n"
        "    port: {port}\n"
        "{hopping}"
        "    password: {password}\n"
        "    sni: {sni}\n"
        "    skip-cert-verify: {skip_cert}\n"
        "\n"
        "proxy-groups:\n"
        "  - name: \"🚀 节点选择\"\n"
        "    type: select\n"
        "    proxies:\n"
        "      - Hysteria2\n"
        "      - DIRECT\n"
        "\n"
        "  - name: \"🎯 全球直连\"\n"
        "    type: select\n"
        "    proxies:\n"
        "      - DIRECT\n"
        "      - 🚀 节点选择\n"
        "\n"
        "rules:\n"
        "  - GEOIP,PRIVATE,DIRECT\n"
        "  - GEOIP,CN,🎯 全球直连\n"
        "  - MATCH,🚀 节点选择\n"
    ).format(
        server=ctx["server_ip"],
        port=ctx["port"],
        password=ctx["password"],
        sni=ctx["sni"],
        skip_cert=skip_cert,
        hopping=hopping_lines,
    )


# --- Shadowrocket ---

def gen_shadowrocket(ctx):
    """生成 Shadowrocket 导入链接"""
    uri = gen_subscription_link(ctx)
    return (
        "Shadowrocket 配置\n"
        "==================\n"
        "\n"
        "1. 打开 Shadowrocket\n"
        "2. 点击右上角 + 添加节点\n"
        "3. 类型选择 Hysteria2\n"
        "4. 或者直接复制以下链接导入:\n"
        "\n"
        "{uri}\n"
        "\n"
        "参数说明:\n"
        "  服务器: {server}\n"
        "  端口:   {port}\n"
        "  密码:   {password}\n"
        "  SNI:    {sni}\n"
        "  跳过证书验证: {skip}\n"
    ).format(
        uri=uri,
        server=ctx["server_ip"],
        port=ctx["port"],
        password=ctx["password"],
        sni=ctx["sni"],
        skip="是" if ctx["skip_cert_verify"] else "否",
    )


# --- NekoRay / NekoBox (sing-box outbound) ---

def gen_nekoray_config(ctx):
    """生成 NekoRay/NekoBox sing-box outbound 配置"""
    outbound = {
        "type": "hysteria2",
        "tag": "hy2-out",
        "server": ctx["server_ip"],
        "server_port": ctx["port"],
        "password": ctx["password"],
        "tls": {
            "enabled": True,
            "server_name": ctx["sni"],
            "insecure": ctx["skip_cert_verify"],
        }
    }
    if ctx["port_hopping"] and ctx["port_hopping_range"]:
        outbound["server_ports"] = [ctx["port_hopping_range"]]
        outbound["hop_interval"] = "30s"

    content = json.dumps(outbound, indent=2, ensure_ascii=False)
    return (
        "NekoRay / NekoBox 配置 (sing-box outbound 格式)\n"
        "=================================================\n"
        "\n"
        "1. 打开 NekoRay / NekoBox\n"
        "2. 添加节点 → 类型选择 Hysteria2\n"
        "3. 或者直接导入以下 JSON (仅 outbound 部分):\n"
        "\n"
        "{content}\n"
    ).format(content=content)


# --- v2rayN ---

def gen_v2rayn(ctx):
    """生成 v2rayN 导入链接"""
    uri = gen_subscription_link(ctx)
    return (
        "v2rayN 配置\n"
        "===========\n"
        "\n"
        "1. 打开 v2rayN\n"
        "2. 服务器 → 添加 VMess/VLESS 服务器\n"
        "3. 或者复制以下链接，通过「从剪贴板导入」:\n"
        "\n"
        "{uri}\n"
        "\n"
        "注意: v2rayN 需要 6.x 以上版本才支持 Hysteria2\n"
    ).format(uri=uri)


# --- sing-box 完整配置 ---

def gen_singbox_config(ctx):
    """生成 sing-box 完整配置"""
    skip_cert = ctx["skip_cert_verify"]

    outbound = {
        "type": "hysteria2",
        "tag": "hy2-out",
        "server": ctx["server_ip"],
        "server_port": ctx["port"],
        "password": ctx["password"],
        "tls": {
            "enabled": True,
            "server_name": ctx["sni"],
            "insecure": skip_cert,
        }
    }
    if ctx["port_hopping"] and ctx["port_hopping_range"]:
        outbound["server_ports"] = [ctx["port_hopping_range"]]
        outbound["hop_interval"] = "30s"

    config = {
        "log": {"level": "info", "timestamp": True},
        "dns": {
            "servers": [
                {"tag": "dns-remote", "address": "https://1.1.1.1/dns-query"},
                {"tag": "dns-local", "address": "https://dns.alidns.com/dns-query", "detour": "direct-out"},
            ],
            "rules": [
                {"outbound": "any", "server": "dns-local"},
                {"rule_set": "geosite-cn", "server": "dns-local"},
            ],
            "final": "dns-remote",
        },
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": 7890,
            },
            {
                "type": "tun",
                "tag": "tun-in",
                "inet4_address": "172.19.0.1/30",
                "auto_route": True,
                "strict_route": True,
            },
        ],
        "outbounds": [
            outbound,
            {"type": "direct", "tag": "direct-out"},
            {"type": "block", "tag": "block-out"},
            {"type": "dns", "tag": "dns-out"},
        ],
        "route": {
            "rules": [
                {"protocol": "dns", "outbound": "dns-out"},
                {"ip_is_private": True, "outbound": "direct-out"},
                {"rule_set": "geoip-cn", "outbound": "direct-out"},
                {"rule_set": "geosite-cn", "outbound": "direct-out"},
            ],
            "rule_set": [
                {
                    "type": "remote",
                    "tag": "geoip-cn",
                    "format": "binary",
                    "url": "https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-cn.srs",
                    "download_detour": "hy2-out",
                },
                {
                    "type": "remote",
                    "tag": "geosite-cn",
                    "format": "binary",
                    "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-cn.srs",
                    "download_detour": "hy2-out",
                },
            ],
            "final": "hy2-out",
            "auto_detect_interface": True,
        },
    }
    return json.dumps(config, indent=2, ensure_ascii=False)


# --- Surfboard ---

def gen_surfboard_config(ctx):
    """生成 Surfboard 配置"""
    skip_cert = "true" if ctx["skip_cert_verify"] else "false"
    proxy_line = "ProxyHysteria2 = hysteria2, {server}, {port}, password={password}, skip-cert-verify={skip}, sni={sni}, udp-relay=true".format(
        server=ctx["server_ip"],
        port=ctx["port"],
        password=ctx["password"],
        skip=skip_cert,
        sni=ctx["sni"],
    )
    if ctx["port_hopping"] and ctx["port_hopping_range"]:
        range_fmt = ctx["port_hopping_range"].replace("-", ";")
        proxy_line += ', port-hopping="{}", port-hopping-interval=30'.format(range_fmt)

    return (
        "[General]\n"
        "loglevel = notify\n"
        "skip-proxy = 127.0.0.1, 192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12, 100.64.0.0/10, localhost, *.local\n"
        "\n"
        "[Proxy]\n"
        "Direct = direct\n"
        "{proxy_line}\n"
        "\n"
        "[Proxy Group]\n"
        "Proxy = select, ProxyHysteria2, Direct\n"
        "\n"
        "[Rule]\n"
        "GEOIP,CN,Direct\n"
        "FINAL,Proxy\n"
    ).format(proxy_line=proxy_line)


# --- Quantumult X ---

def gen_quantumultx(ctx):
    """Quantumult X 不支持 Hysteria2，输出替代方案"""
    return (
        "Quantumult X 配置\n"
        "==================\n"
        "\n"
        "Quantumult X 目前不支持 Hysteria2 协议。\n"
        "\n"
        "替代方案:\n"
        "  iOS 客户端:\n"
        "    - Shadowrocket (推荐，支持 Hysteria2)\n"
        "    - Surge (支持 Hysteria2)\n"
        "    - Loon (支持 Hysteria2)\n"
        "\n"
        "  或者通过本地运行 sing-box 客户端作为前端代理，\n"
        "  将 Quantumult X 的流量转发到本地代理。\n"
        "  本配置包中已包含 sing-box.json，可配合使用。\n"
        "\n"
        "订阅链接（可用于支持 Hysteria2 的客户端）:\n"
        "{uri}\n"
    ).format(uri=gen_subscription_link(ctx))


# --- 生成所有配置 ---

def gen_all_client_configs(ctx):
    """生成全部客户端配置文件"""
    output_dir = os.path.join(os.getcwd(), OUTPUT_DIR_NAME)
    os.makedirs(output_dir, exist_ok=True)

    generators = [
        ("server-info.txt",       gen_server_info),
        ("subscription-link.txt", gen_subscription_link),
        ("clash-verge.yaml",      gen_clash_config),
        ("shadowrocket.txt",      gen_shadowrocket),
        ("nekoray.json",          gen_nekoray_config),
        ("v2rayn.txt",            gen_v2rayn),
        ("sing-box.json",         gen_singbox_config),
        ("surfboard.txt",         gen_surfboard_config),
        ("quantumultx.txt",       gen_quantumultx),
    ]

    print()
    print_color("═══ 生成客户端配置文件 ═══", COLOR_BOLD)
    print_info("输出目录: {}".format(os.path.abspath(output_dir)))
    print()
    for filename, gen_func in generators:
        filepath = os.path.join(output_dir, filename)
        abs_path = os.path.abspath(filepath)
        content = gen_func(ctx)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print_success("已生成: {}".format(abs_path))

    return output_dir


# ============================================================
# 终端输出模块
# ============================================================

def print_summary(ctx, output_dir):
    """终端输出安装摘要"""
    uri = gen_subscription_link(ctx)

    print()
    print_color("╔══════════════════════════════════════════════╗", COLOR_GREEN)
    print_color("║          Hysteria2 安装完成！                ║", COLOR_GREEN)
    print_color("╚══════════════════════════════════════════════╝", COLOR_GREEN)
    print()
    print("  服务器 IP:   {}".format(ctx["server_ip"]))
    print("  端口:        {}".format(ctx["port"]))
    print("  密码:        {}".format(ctx["password"]))
    print("  SNI:         {}".format(ctx["sni"]))
    print("  自签证书:    {}".format("是 (客户端需 skip-cert-verify)" if ctx["is_self_signed"] else "否"))
    if ctx["port_hopping"]:
        print("  端口跳跃:    {}".format(ctx["port_hopping_range"]))
    print()
    print_color("  订阅链接:", COLOR_BOLD)
    print_color("  {}".format(uri), COLOR_CYAN)
    print()
    print("  客户端配置文件已生成至:")
    print_color("  {}/".format(output_dir), COLOR_CYAN)
    print()
    print("  支持的客户端:")
    print("    Clash Verge Rev  → clash-verge.yaml")
    print("    Shadowrocket     → shadowrocket.txt")
    print("    NekoRay/NekoBox  → nekoray.json")
    print("    v2rayN           → v2rayn.txt")
    print("    sing-box         → sing-box.json")
    print("    Surfboard        → surfboard.txt")
    print()
    print("  管理命令:")
    print("    启动: systemctl start hysteria-server")
    print("    停止: systemctl stop hysteria-server")
    print("    重启: systemctl restart hysteria-server")
    print("    日志: journalctl -u hysteria-server -f")
    print()


# ============================================================
# 主函数
# ============================================================

def main():
    # 处理命令行参数
    if "--uninstall" in sys.argv:
        check_root()
        uninstall_hysteria()
        return

    print_banner()

    # 1. 环境检查
    check_root()
    distro, version = detect_os()
    arch = detect_arch()
    print_info("系统: {} {} | 架构: {}".format(distro, version, arch))

    check_dependencies()

    # 2. 获取公网 IP
    ipv4, ipv6 = get_public_ip()
    if ipv4:
        print_success("IPv4: {}".format(ipv4))
    if ipv6:
        print_success("IPv6: {}".format(ipv6))
    if not ipv4 and not ipv6:
        print_error("无法获取公网 IP")
        sys.exit(1)

    # 3. 检查已有安装
    handle_existing()

    # 4. 交互式配置
    config = interactive_config(ipv4, ipv6)

    # 5. 下载安装
    version = get_latest_version()
    download_hysteria(version, arch)
    install_binary()

    # 6. 证书处理
    cert_path = ""
    key_path = ""
    if config["cert_mode"] == "self-signed":
        cert_path, key_path = generate_self_signed_cert(ipv4 or ipv6)

    # 7. 生成服务端配置
    generate_server_config(config, cert_path, key_path)

    # 8. 启动服务
    setup_systemd()

    # 9. 防火墙
    configure_firewall(config["port"], config.get("port_hopping_range", ""))

    # 10. 构建上下文
    ctx = build_context(config, ipv4, ipv6, cert_path, key_path)

    # 11. 生成客户端配置
    output_dir = gen_all_client_configs(ctx)

    # 12. 终端输出
    print_summary(ctx, output_dir)


if __name__ == "__main__":
    main()
