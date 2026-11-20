#!/usr/bin/env python3
"""构建工具:把 skills/ 目录加密为单个密文包。

用法:
    python scripts/encrypt_skills.py [--src skills] [--out mhagent/data/skills.enc] [--verify]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mhagent.skill_crypto import decrypt_file, encrypt_dir, encrypted_path  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="加密 skills 目录")
    parser.add_argument("--src", default=str(ROOT / "skills"), help="技能明文目录")
    parser.add_argument("--out", default=str(encrypted_path()), help="密文包输出路径")
    parser.add_argument("--verify", action="store_true", help="加密后解密并逐文件比对")
    args = parser.parse_args(argv)

    src = Path(args.src)
    out = Path(args.out)
    try:
        stats = encrypt_dir(src, out)
    except ValueError as exc:
        print(f"加密失败: {exc}")
        return 1

    if args.verify:
        original = {
            path.relative_to(src).as_posix(): path.read_bytes()
            for path in src.rglob("*")
            if path.is_file()
        }
        if decrypt_file(out) != original:
            print("校验失败: 解密内容与源文件不一致")
            return 1

    print(f"已生成密文包: {out}")
    print(f"技能: {', '.join(stats['skills'])}")
    print(f"文件数: {stats['files']}, 密文大小: {stats['bytes'] / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
