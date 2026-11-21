#!/usr/bin/env bash
# 触发 GitHub Actions 构建 Windows 安装包，并下载到 artifacts/windows/。
#
# 用法:
#   ./scripts/build-windows-installer.sh          # 有未提交改动时询问是否提交
#   ./scripts/build-windows-installer.sh --yes    # 自动提交并构建
#   ./scripts/build-windows-installer.sh --help
#
# 依赖: git、gh（已执行 gh auth login）、curl 不需要。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WORKFLOW="build-windows.yml"
ARTIFACT="mhagent-windows-setup"
BRANCH="${BRANCH:-main}"
AUTO_YES=0

usage() {
    cat <<'EOF'
用法: scripts/build-windows-installer.sh [选项]

选项:
  -y, --yes    工作区有未提交改动时自动提交，不再询问
  -h, --help   显示帮助

流程:
  1. 检查 gh 登录与当前分支
  2. 提交并推送当前改动到 main
  3. 触发 build-windows-installer workflow
  4. 等待构建完成并下载 mhagent-setup-<version>.exe
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        -y|--yes) AUTO_YES=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "未知参数: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if ! command -v gh >/dev/null 2>&1; then
    if [ -x "$HOME/.local/bin/gh" ]; then
        PATH="$HOME/.local/bin:$PATH"
    else
        echo "未找到 gh，请先安装并执行 gh auth login" >&2
        exit 1
    fi
fi
if ! command -v git >/dev/null 2>&1; then
    echo "未找到 git" >&2
    exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
    echo "gh 未登录，请先执行: gh auth login -h github.com -p https -w" >&2
    exit 1
fi

REPO="$(gh repo view --json nameWithOwner --jq '.nameWithOwner')"
VERSION="$(grep -E '^version[[:space:]]*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
if [ -z "$VERSION" ]; then
    echo "无法从 pyproject.toml 读取版本号" >&2
    exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
    echo "当前分支为 $CURRENT_BRANCH，请切换到 $BRANCH 后再构建" >&2
    exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
    echo "检测到未提交改动:"
    git status --short
    if [ "$AUTO_YES" -eq 1 ]; then
        DO_COMMIT=1
    else
        read -r -p "是否提交这些改动并继续构建？[y/N] " answer
        case "$answer" in
            y|Y) DO_COMMIT=1 ;;
            *) echo "已取消"; exit 1 ;;
        esac
    fi
    if [ "${DO_COMMIT:-0}" -eq 1 ]; then
        git add -A
        git commit -m "chore: build windows installer v${VERSION}"
        echo "已提交本地改动"
    fi
fi

LOCAL_SHA="$(git rev-parse HEAD)"

remote_sha() {
    gh api "repos/${REPO}/commits/${BRANCH}" --jq '.sha' 2>/dev/null || true
}

REMOTE_SHA="$(remote_sha)"
if [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
    echo "推送 ${BRANCH} 到 ${REPO}..."
    PUSH_LOG="$(mktemp)"
    git -c http.version=HTTP/1.1 push origin "$BRANCH" >"$PUSH_LOG" 2>&1 &
    PUSH_PID=$!

    PUSH_OK=0
    for _ in $(seq 1 120); do
        if [ "$(remote_sha)" = "$LOCAL_SHA" ]; then
            PUSH_OK=1
            break
        fi
        if ! kill -0 "$PUSH_PID" 2>/dev/null; then
            wait "$PUSH_PID" 2>/dev/null || true
            [ "$(remote_sha)" = "$LOCAL_SHA" ] && PUSH_OK=1
            break
        fi
        sleep 1
    done

    if kill -0 "$PUSH_PID" 2>/dev/null; then
        pkill -P "$PUSH_PID" 2>/dev/null || true
        kill "$PUSH_PID" 2>/dev/null || true
        wait "$PUSH_PID" 2>/dev/null || true
    fi

    if [ "$PUSH_OK" -ne 1 ]; then
        echo "推送失败:" >&2
        cat "$PUSH_LOG" >&2
        rm -f "$PUSH_LOG"
        exit 1
    fi
    rm -f "$PUSH_LOG"
    echo "推送完成: $LOCAL_SHA"
fi

echo "触发 GitHub Actions: ${WORKFLOW} (${BRANCH})"
START_TS="$(date +%s)"
gh workflow run "$WORKFLOW" --ref "$BRANCH"

RUN_ID=""
for _ in $(seq 1 20); do
    RUN_ID="$(gh run list --workflow "$WORKFLOW" --branch "$BRANCH" --limit 20 \
        --json databaseId,createdAt \
        --jq ".[] | select((.createdAt | fromdateiso8601) >= $((START_TS - 5))) | .databaseId" \
        2>/dev/null | head -1 || true)"
    [ -n "$RUN_ID" ] && break
    sleep 2
done
if [ -z "$RUN_ID" ]; then
    echo "未找到刚触发的构建，请到 https://github.com/${REPO}/actions 查看" >&2
    exit 1
fi
echo "构建任务: https://github.com/${REPO}/actions/runs/${RUN_ID}"

while true; do
    STATUS="$(gh run view "$RUN_ID" --json status --jq '.status')"
    CONCLUSION="$(gh run view "$RUN_ID" --json conclusion --jq '.conclusion // ""')"
    echo "状态: ${STATUS}${CONCLUSION:+ (${CONCLUSION})}"
    [ "$STATUS" = "completed" ] && break
    sleep 15
done

if [ "$CONCLUSION" != "success" ]; then
    echo "构建失败，失败日志:" >&2
    gh run view "$RUN_ID" --log-failed 2>&1 | tail -80 >&2 || true
    exit 1
fi

DEST="$ROOT/artifacts/windows"
mkdir -p "$DEST"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "下载安装包..."
gh run download "$RUN_ID" -n "$ARTIFACT" -D "$TMP_DIR"
EXE_PATH="$(find "$TMP_DIR" -type f -name 'mhagent-setup-*.exe' | head -1)"
if [ -z "$EXE_PATH" ]; then
    echo "构建成功但未找到 mhagent-setup-*.exe" >&2
    exit 1
fi

TARGET="$DEST/mhagent-setup-${VERSION}.exe"
mv -f "$EXE_PATH" "$TARGET"
echo ""
echo "安装包: $TARGET"
echo "SHA256: $(shasum -a 256 "$TARGET" | awk '{print $1}')"
echo "构建记录: https://github.com/${REPO}/actions/runs/${RUN_ID}"
