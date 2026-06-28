#!/usr/bin/env bash
# 用 Docker 构建 APK，不污染本机环境。
# 用法：bash docker-build-apk.sh
set -euo pipefail

IMAGE_TAG="beiyang-builder:latest"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 1. 构建镜像（首次慢，之后走 Docker 缓存）
echo "[1/3] Building Docker image (cached)..."
docker build -t "$IMAGE_TAG" -f "$SCRIPT_DIR/Dockerfile" "$SCRIPT_DIR"

# 2. 在容器内构建 APK，项目目录挂载进 /app，产物直接落到本机 build/apk/
echo "[2/3] Building APK in container..."
docker run --rm \
  -v "$SCRIPT_DIR":/app \
  -v beiyang-pub-cache:/root/.pub-cache \
  -v beiyang-gradle-cache:/root/.gradle \
  -w /app \
  "$IMAGE_TAG" \
  flet build apk --yes --no-rich-output

# 3. 确认产物
echo "[3/3] Build result:"
ls -lh "$SCRIPT_DIR/build/apk/"*.apk 2>/dev/null && echo "DONE" || echo "No APK found — check build output above."
