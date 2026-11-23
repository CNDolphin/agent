"""桌面入口:本地 FastAPI 服务 + pywebview 原生窗口。

用法:
    python -m client.desktop                 # 原生窗口
    python -m client.desktop --browser       # 浏览器窗口(无 pywebview 时自动降级)
    python -m client.desktop --dev           # 配合 client/web 的 vite dev server

开启 `client.lan.enabled` 后服务监听 0.0.0.0,局域网内的手机/电脑可打开同一地址,
用主账号创建的子账号用户名 + 密码登录。
"""

from __future__ import annotations

import argparse
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import httpx
import uvicorn

from client.app import create_app
from client.profiles import RuntimeManager
from main import load_config

DEV_PORT = 8770
DEV_UI_URL = "http://127.0.0.1:5198"


def _ensure_standard_streams() -> None:
    """窗口化打包(console=False)下 sys.stdout/stderr 为 None。

    uvicorn 初始化日志时会调用 ``sys.stdout.isatty()``,流为 None 会直接崩溃,
    因此这里把缺失的流重定向到 ``~/.mhagent/desktop.log``(不可写时退回空设备)。
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        log_dir = Path.home() / ".mhagent"
        log_dir.mkdir(parents=True, exist_ok=True)
        stream = open(log_dir / "desktop.log", "a", encoding="utf-8", buffering=1)
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def local_ip() -> str | None:
    """获取本机局域网地址,失败时返回 None。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
    except OSError:
        return None
    return None if address.startswith("127.") else address


def wait_until_ready(base_url: str, token: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(
                f"{base_url}/api/health",
                headers={"X-Local-Token": token},
                timeout=2.0,
            )
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.15)
    raise RuntimeError(f"本地服务启动失败:{last_error}")


def main(argv=None) -> int:
    _ensure_standard_streams()
    parser = argparse.ArgumentParser(description="本地心理助手桌面客户端")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--data-dir", default=None, help="本地数据目录(覆盖配置)")
    parser.add_argument("--browser", action="store_true", help="使用浏览器窗口")
    parser.add_argument("--dev", action="store_true", help="加载 vite 开发服务器")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    client_cfg = config.get("client") or {}
    dev_mode = bool(client_cfg.get("dev_tools", False))
    window_cfg = client_cfg.get("window") or {}
    lan_cfg = client_cfg.get("lan") or {}
    lan_enabled = bool(lan_cfg.get("enabled", False))
    width = int(window_cfg.get("width", 1100))
    height = int(window_cfg.get("height", 760))

    if args.dev and not dev_mode:
        print("提示:--dev 需要 client.dev_tools=true 才能获取本地令牌。", file=sys.stderr)

    manager = RuntimeManager(config, args.data_dir)
    if manager.legacy_required:
        print("检测到旧版本地数据,请在界面中完成一次性升级。", file=sys.stderr)
    token = secrets.token_urlsafe(24)
    app = create_app(manager, token, dev_mode=dev_mode)

    if args.dev:
        port = DEV_PORT
    elif lan_enabled:
        port = int(lan_cfg.get("port", 8780))
    else:
        port = free_port()
    host = "0.0.0.0" if lan_enabled else "127.0.0.1"
    base_url = f"http://127.0.0.1:{port}"

    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    try:
        wait_until_ready(base_url, token)
    except RuntimeError as exc:
        print(f"启动失败:{exc}", file=sys.stderr)
        server.should_exit = True
        manager.close()
        return 1

    ui_url = DEV_UI_URL if args.dev else base_url
    print(f"本地服务:{base_url}")
    print(f"界面地址:{ui_url}")
    if lan_enabled:
        address = local_ip()
        if address:
            print(f"局域网地址:http://{address}:{port}(用子账号用户名 + 密码登录)")
        else:
            print(f"局域网已开启,请用本机局域网 IP 加端口 {port} 访问。")

    try:
        if args.browser:
            webbrowser.open(ui_url)
            _wait_for_interrupt()
        else:
            if not _start_native_window(ui_url, "本地心理助手", width, height):
                webbrowser.open(ui_url)
                _wait_for_interrupt()
    finally:
        manager.close()
        server.should_exit = True
    return 0


def _enable_media_capture_permission() -> None:
    """放行页面发起的麦克风请求。

    pywebview 的 macOS 后端没有实现 WKUIDelegate 的媒体采集授权回调,
    WKWebView 默认拒绝,导致语音识别直接报 not-allowed 且系统里不会出现授权记录。
    这里替换其委托类,对页面请求统一返回 Grant,随后由系统弹出麦克风授权。
    """
    if sys.platform != "darwin":
        return
    try:
        from webview.platforms import cocoa
    except Exception:
        return
    if getattr(cocoa.BrowserView, "_mhagent_media_capture_patched", False):
        return

    webkit = cocoa.WebKit

    class MediaCaptureDelegate(cocoa.BrowserView.BrowserDelegate):
        def webView_requestMediaCapturePermissionForOrigin_initiatedByFrame_decisionHandler_(
            self, webview, origin, frame, handler
        ):
            handler(webkit.WKPermissionDecisionGrant)

    cocoa.BrowserView.BrowserDelegate = MediaCaptureDelegate
    cocoa.BrowserView._mhagent_media_capture_patched = True


def _start_native_window(url: str, title: str, width: int, height: int) -> bool:
    try:
        import webview
    except Exception:
        print("未安装 pywebview,改用浏览器打开(可执行 pip install pywebview)。", file=sys.stderr)
        return False
    _enable_media_capture_permission()
    window = webview.create_window(
        title,
        url,
        width=width,
        height=height,
        min_size=(900, 640),
    )
    webview.start()
    return window is not None


def _wait_for_interrupt() -> None:
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
