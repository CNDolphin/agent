#!/usr/bin/env bash
# 启动 mhagent Go 后端(本地开发)。
#
# 用法:
#   ./start-backend.sh                  # 以 go run 方式启动
#   ./start-backend.sh --build          # 先编译到 bin/mhagent 再启动
#   ./start-backend.sh -f etc/mhagent.yaml  # 指定配置文件
#
# 启动前会自动加载 etc/.env 中的本地环境变量(密钥只从环境变量读取),
# 并检查配置端口是否已被占用。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

CONF="etc/mhagent.yaml"
BUILD=0

usage() {
  cat <<'EOF'
启动 mhagent Go 后端(本地开发)。

用法:
  ./start-backend.sh                      # 以 go run 方式启动
  ./start-backend.sh --build              # 先编译到 bin/mhagent 再启动
  ./start-backend.sh -f etc/mhagent.yaml  # 指定配置文件
  ./start-backend.sh -h                   # 显示帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build) BUILD=1; shift ;;
    -f|--conf)
      if [[ $# -lt 2 ]]; then
        echo "参数 $1 需要配置文件路径。" >&2
        exit 1
      fi
      CONF="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "未知参数: $1" >&2
      usage >&2
      exit 1 ;;
  esac
done

if ! command -v go >/dev/null 2>&1; then
  echo "未找到 go 命令,请先安装 Go 并确保其在 PATH 中。" >&2
  exit 1
fi

if [[ ! -f "$CONF" ]]; then
  echo "配置文件不存在: $CONF" >&2
  exit 1
fi

# 加载本地开发环境变量;已存在的同名变量会被 .env 中的值覆盖。
if [[ -f etc/.env ]]; then
  set -a
  # shellcheck disable=SC1091
  . etc/.env
  set +a
else
  echo "提示: 未找到 etc/.env,请确认 JWT_SECRET / ADMIN_JWT_SECRET / PHONE_HASH_PEPPER 等必需变量已导出。" >&2
fi

PORT="$(awk -F': *' '/^Port:/ {print $2; exit}' "$CONF")"
PORT="${PORT:-8899}"
if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "端口 $PORT 已被占用,请先停止占用进程:" >&2
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2 || true
  exit 1
fi

echo "配置: $CONF"
echo "PostgreSQL: ${DATABASE_URL:-未设置}"
echo "Redis: ${REDIS_ADDR:-localhost:6379}"

if [[ "$BUILD" -eq 1 ]]; then
  mkdir -p bin
  echo "编译后端..."
  go build -o bin/mhagent .
  echo "启动后端(bin/mhagent)..."
  exec ./bin/mhagent -f "$CONF"
fi

echo "启动后端(go run)..."
exec go run . -f "$CONF"
