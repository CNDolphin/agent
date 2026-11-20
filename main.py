"""命令行入口:本地心理健康 Agent。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from mhagent.cli_setup import CliSetup, SetupAborted
from mhagent.consent import ConsentStore
from mhagent.llm.gateway import GatewayClient
from mhagent.loop import AgentLoop
from mhagent.notifier import Notifier

DEFAULT_CONFIG = {
    "gateway": {"base_url": "http://127.0.0.1:8888", "model": "deepseek-flash", "timeout_seconds": 30},
    "storage": {"data_dir": "~/.mhagent"},
    "session": {"max_context_chars": 2000, "max_tokens": 1024},
}


def load_config(path: str | Path) -> dict:
    config_path = Path(path).expanduser()
    if not config_path.exists():
        return dict(DEFAULT_CONFIG)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    merged = {**DEFAULT_CONFIG}
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(DEFAULT_CONFIG.get(key), dict):
            merged[key] = {**DEFAULT_CONFIG[key], **value}
        else:
            merged[key] = value
    return merged


def build_services(config: dict, session):
    gateway_cfg = config["gateway"]
    return GatewayClient(
        gateway_cfg["base_url"],
        session,
        model=gateway_cfg["model"],
        timeout=float(gateway_cfg["timeout_seconds"]),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="本地心理健康支持 Agent")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--data-dir", default=None, help="本地数据目录(覆盖配置)")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    data_dir = args.data_dir or config["storage"]["data_dir"]

    setup = CliSetup(
        data_dir=data_dir,
        auth_factory=lambda session: build_services(config, session),
        consent_factory=lambda session: build_services(config, session),
    )
    try:
        result = setup.run()
    except SetupAborted as exc:
        print(f"已停止: {exc}")
        return 1
    except Exception as exc:  # 口令错误等
        print(f"启动失败: {exc}")
        return 1

    consent = ConsentStore(result.store)
    notifier = Notifier(config["gateway"]["base_url"], consent)
    llm = build_services(config, result.session)
    loop = AgentLoop(
        llm,
        result.store,
        consent=consent,
        notifier=notifier,
        max_tokens=int(config["session"].get("max_tokens", 1024)),
        max_history_chars=int(config["session"].get("max_context_chars", 2000)),
    )
    print("\n已进入对话。输入「退出」结束。危机热线 12356,急救电话 120。\n")
    try:
        while True:
            try:
                user_text = input("你: ")
            except (EOFError, KeyboardInterrupt):
                break
            if user_text.strip() in {"退出", "exit", "quit"}:
                break
            print("助手:", loop.handle(user_text))
    finally:
        llm.close()
        notifier.close()
        result.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
