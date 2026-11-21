# 开发规则

- PyInstaller 以 console=False（窗口化）打包时，入口必须保证 sys.stdout/sys.stderr 不为 None（重定向到日志文件或空设备），否则 uvicorn 等库初始化日志时调用 isatty 会崩溃。
