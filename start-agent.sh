#!/usr/bin/env bash
# 启动本地心理助手 Agent(桌面端),可选同时拉起 Go 后端。
#
# 用法:
#   ./start-agent.sh                  # 只启动桌面端(后端需已在 8899 运行)
#   ./start-agent.sh --with-backend   # 先启动后端,再启动桌面端;Ctrl-C 退出时一并停止后端
#   ./start-agent.sh --browser        # 用浏览器窗口代替 pywebview 原生窗口
#   ./start-agent.sh --dev            # 配合 client/web 的 vite dev server(5198)
#
# 其余参数会原样透传给 client.desktop,例如 --data-dir ~/mhagent-data。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8899" # 与 config.yaml 的 gateway.base_url 保持一致
BACKEND_LOG="$ROOT/.start-agent-backend.log"

WITH_BACKEND=0
DEV_MODE=0
BROWSER_MODE=0
PASSTHROUGH=()

usage() {
  cat <<'EOF'
启动本地心理助手 Agent(桌面端),可选同时拉起 Go 后端。

用法:
  ./start-agent.sh                  # 只启动桌面端(后端需已在 8899 运行)
  ./start-agent.sh --with-backend   # 先启动后端,再启动桌面端;Ctrl-C 退出时一并停止后端
  ./start-agent.sh --browser        # 用浏览器窗口代替 pywebview 原生窗口
  ./start-agent.sh --dev            # 配合 client/web 的 vite dev server(5198)

其余参数会原样透传给 client.desktop,例如 --data-dir ~/mhagent-data。
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-backend) WITH_BACKEND=1; shift ;;
    --dev) DEV_MODE=1; shift ;;
    --browser) BROWSER_MODE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) PASSTHROUGH+=("$1"); shift ;;
  esac
done

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON" ]]; then
  echo "未找到 python3,请先创建虚拟环境:python3 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi

backend_ready() {
  curl -fsS -o /dev/null --max-time 1 "http://$BACKEND_HOST:$BACKEND_PORT/health"
}

BACKEND_PID=""

stop_backend() {
  [[ -z "$BACKEND_PID" ]] && return
  if kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "停止后端(pid $BACKEND_PID)..."
    # go run 会派生出实际的服务进程,先结束子进程再结束 go run 本身。
    pkill -P "$BACKEND_PID" 2>/dev/null || true
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  BACKEND_PID=""
}

cleanup() {
  stop_backend
}
trap cleanup EXIT INT TERM

start_backend() {
  if backend_ready; then
    echo "后端已在 $BACKEND_HOST:$BACKEND_PORT 运行,跳过启动。"
    return
  fi
  if ! command -v go >/dev/null 2>&1; then
    echo "未找到 go 命令,无法启动后端。" >&2
    exit 1
  fi
  echo "启动后端($BACKEND_HOST:$BACKEND_PORT)..."
  (
    cd "$ROOT/backend"
    DATABASE_URL="${DATABASE_URL:-postgres://postgres:postgres@localhost:5432/mhagent?sslmode=disable}" \
    JWT_SECRET="${JWT_SECRET:-dev-jwt-secret-local}" \
    ADMIN_JWT_SECRET="${ADMIN_JWT_SECRET:-dev-admin-jwt-secret-local}" \
    PHONE_HASH_PEPPER="${PHONE_HASH_PEPPER:-dev-phone-pepper-local}" \
      go run . -f etc/mhagent.yaml
  ) >"$BACKEND_LOG" 2>&1 &
  BACKEND_PID=$!

  for _ in $(seq 1 90); do
    if backend_ready; then
      echo "后端就绪。"
      return
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      echo "后端启动失败,日志:$BACKEND_LOG" >&2
      tail -n 20 "$BACKEND_LOG" >&2 || true
      exit 1
    fi
    sleep 1
  done
  echo "后端启动超时,日志:$BACKEND_LOG" >&2
  exit 1
}

[[ "$WITH_BACKEND" -eq 1 ]] && start_backend

DESKTOP_ARGS=()
[[ "$DEV_MODE" -eq 1 ]] && DESKTOP_ARGS+=(--dev)
[[ "$BROWSER_MODE" -eq 1 ]] && DESKTOP_ARGS+=(--browser)

echo "启动本地 Agent..."
"$PYTHON" -m client.desktop ${DESKTOP_ARGS[@]+"${DESKTOP_ARGS[@]}"} ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}
