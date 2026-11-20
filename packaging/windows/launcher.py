"""PyInstaller 冻结入口:启动桌面客户端。

`client.desktop` 使用绝对导入(`from client.app import ...`),因此不能把它
直接作为 PyInstaller 入口脚本;由 spec 的 `pathex` 指向仓库根,保证
`client`、`mhagent` 包可被分析到。
"""

import sys

from client.desktop import main

if __name__ == "__main__":
    sys.exit(main())
