# Hysteria2 一键安装脚本

用于快速安装 Hysteria2 服务端，并生成常见客户端配置文件。

## 功能

- 自动检测系统和 CPU 架构
- 自动下载 Hysteria2 最新版本
- 支持自签证书和 ACME 证书
- 支持静态 masquerade 伪装页面
- 支持端口跳跃
- 自动配置 systemd 服务
- 自动添加 UDP 防火墙规则
- 自动生成常见客户端配置
- 提供远端 HTTP/3 探测工具

## 文件

| 文件 | 说明 |
| --- | --- |
| `hysteria2-installer.py` | 一键安装脚本 |
| `probe_gfw_like_masquerade.py` | 远端 HTTP/3 探测工具 |
| `test_hysteria2_installer.py` | 安装脚本测试 |
| `test_probe_gfw_like_masquerade.py` | 探测工具测试 |

## 安装

在服务器上运行：

```bash
python3 hysteria2-installer.py
```

如果缺少基础依赖：

```bash
apt update
apt install -y python3 curl openssl
```

安装过程会依次配置：

1. 监听端口
2. 认证密码
3. 证书模式
4. 端口跳跃
5. 网站伪装

## 证书

没有域名时，域名输入处直接留空，脚本会使用自签证书。

有域名时，输入域名和邮箱，脚本会生成 Hysteria2 ACME 配置，由 Hysteria2 自动申请证书。

```text
请输入你的域名 (留空则使用无域名自签证书):
```

说明：

- Hysteria2 服务端口可以自定义
- `443/udp` 只是更接近普通 HTTP/3 网站的推荐端口
- ACME 证书验证需要域名解析正确，并确保验证端口可达

## 伪装页面

静态伪装模板：

- API 文档页面
- 404 Not Found

安装时选择：

```text
网站伪装方式 -> 静态伪装页面
```

生成的静态页面会放在：

```text
/var/www/masquerade/index.html
```

## 客户端配置

安装完成后，客户端配置会生成到：

```text
hysteria2-client-configs/
```

包含：

- `server-info.txt`
- `subscription-link.txt`
- `clash-verge.yaml`
- `shadowrocket.txt`
- `nekoray.json`
- `v2rayn.txt`
- `sing-box.json`
- `surfboard.txt`

## 管理命令

```bash
systemctl status hysteria-server
systemctl restart hysteria-server
systemctl stop hysteria-server
systemctl start hysteria-server
journalctl -u hysteria-server -f
```

卸载：

```bash
python3 hysteria2-installer.py --uninstall
```

## 验证伪装

在本地电脑或另一台服务器安装依赖：

```bash
python3 -m pip install aioquic
```

运行探测：

```bash
python3 probe_gfw_like_masquerade.py 服务器IP 端口 --sni bing.com --timeout 5
```

示例：

```bash
python3 probe_gfw_like_masquerade.py 38.148.253.138 44880 --sni bing.com --timeout 5
```

如果使用自己的域名：

```bash
python3 probe_gfw_like_masquerade.py example.com 443 --sni example.com --timeout 5
```

看到类似结果表示伪装页面生效：

```text
RESULT: PASS - remote probes saw a masquerade response
```

## 测试

```bash
python3 -m unittest test_hysteria2_installer.py test_probe_gfw_like_masquerade.py
python3 -m py_compile hysteria2-installer.py probe_gfw_like_masquerade.py
```

## 免责声明

请遵守所在地法律法规和服务商使用条款。本项目仅用于学习、测试和个人网络研究。
