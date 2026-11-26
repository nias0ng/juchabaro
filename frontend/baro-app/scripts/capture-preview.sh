#!/usr/bin/env bash
# 미리보기 화면(/dev/design-system)을 라이트/다크로 찍는다. 개발 서버(웹)가 떠 있어야 한다.
# 사용법: scripts/capture-preview.sh <before|after> [포트=8090]
set -euo pipefail
LABEL="$1"; PORT="${2:-8090}"
CHROME="${CHROME:-C:/Program Files/Google/Chrome/Application/chrome.exe}"
OUT="$(cd "$(dirname "$0")/.." && pwd -W 2>/dev/null || pwd)/docs/design-system/screenshots"
mkdir -p "$OUT"
for MODE in light dark; do
  SCHEME=1; [ "$MODE" = dark ] && SCHEME=0
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --user-data-dir="${TEMP:-/tmp}/preview-shot-$MODE" \
    --window-size=500,3600 --virtual-time-budget=20000 --blink-settings=preferredColorScheme=$SCHEME \
    --screenshot="$OUT/$LABEL-$MODE.png" "http://localhost:$PORT/dev/design-system" >/dev/null 2>&1
done
ls "$OUT"
